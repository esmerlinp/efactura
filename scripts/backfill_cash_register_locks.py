"""
Backfill de locks de ocupación para turnos de caja legacy.

Los turnos abiertos ANTES de la Fase 1 no tienen documento de lock
(``cash_register_locks/{registerId}`` / ``sandbox_cash_register_locks/...``).
Sin el lock, el nuevo mecanismo de ocupación no reconoce la caja como ocupada y
otro cajero podría abrir una segunda sesión sobre la misma caja física.

Este script detecta turnos abiertos (OPEN/CLOSING/REOPENED) sin lock y:

  * ``--mode lock``  (por defecto): crea el lock correspondiente para preservar
    el turno abierto y habilitar el control de ocupación.  -> RECOMENDADO
  * ``--mode close`` : fuerza el cierre del turno (status FORCED_CLOSED) y libera
    la caja. Útil si el turno quedó obsoleto.

Es NO destructivo e idempotente: nunca borra datos; solo crea locks o marca
turnos como FORCED_CLOSED. Por defecto se ejecuta en modo DRY-RUN (no escribe).

Uso:
    python scripts/backfill_cash_register_locks.py --mode lock
    python scripts/backfill_cash_register_locks.py --mode close --apply
    python scripts/backfill_cash_register_locks.py --company <company_id> --apply

Ejecutar ANTES de desplegar la Fase 1, con el módulo de POS detenido, para no
dejar cajas ocupadas que el sistema no reconoce.
"""
import os
import sys
import argparse
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app.services.db_service import (
        db_firestore, firebase_initialized, _company_coll,
        CASH_LOCK_ACTIVE, CASH_LOCK_LEASE_TTL,
    )
except ImportError as e:
    print(f"❌ Error al importar módulos: {e}")
    sys.exit(1)


OPEN_STATUSES = ("OPEN", "CLOSING", "REOPENED")


def log(msg):
    print(f"[{datetime.now().isoformat()}] {msg}")


def list_companies():
    companies = []
    try:
        for doc in db_firestore.collection("companies").get():
            companies.append(doc.id)
    except Exception as e:
        log(f"⚠️ Error listando companies: {e}")
    return companies


def iter_open_shifts(company_id, sandbox):
    prefix = "sandbox_" if sandbox else ""
    coll = _company_coll(company_id=company_id, coll_name=f"{prefix}cash_shifts")
    if coll is None:
        return []
    try:
        docs = coll.get()
    except Exception as e:
        log(f"⚠️ Error leyendo {prefix}cash_shifts de {company_id}: {e}")
        return []
    shifts = []
    for doc in docs:
        data = doc.to_dict()
        if data.get("status") in OPEN_STATUSES:
            shifts.append((doc.id, data))
    return shifts


def get_lock(company_id, register_id, sandbox):
    prefix = "sandbox_" if sandbox else ""
    coll = _company_coll(company_id=company_id, coll_name=f"{prefix}cash_register_locks")
    if coll is None:
        return None
    try:
        doc = coll.document(register_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        log(f"⚠️ Error leyendo lock {register_id}: {e}")
        return None


def create_lock(company_id, shift_id, register_id, opened_by, sandbox):
    prefix = "sandbox_" if sandbox else ""
    coll = _company_coll(company_id=company_id, coll_name=f"{prefix}cash_register_locks")
    now = datetime.now(timezone.utc)
    coll.document(register_id).set({
        "registerId": register_id,
        "shiftId": shift_id,
        "openedByUserId": opened_by,
        "status": CASH_LOCK_ACTIVE,
        "leaseOwner": shift_id,
        "leaseExpiresAt": (now + timedelta(seconds=CASH_LOCK_LEASE_TTL)).isoformat(),
        "createdAt": now.isoformat(),
        "updatedAt": now.isoformat(),
    })


def force_close_shift(company_id, shift_id, register_id, sandbox):
    prefix = "sandbox_" if sandbox else ""
    shifts_coll = _company_coll(company_id=company_id, coll_name=f"{prefix}cash_shifts")
    regs_coll = _company_coll(company_id=company_id, coll_name=f"{prefix}cash_registers")
    shifts_coll.document(shift_id).update({
        "status": "FORCED_CLOSED",
        "closingTime": datetime.now(timezone.utc).isoformat(),
        "forcedClosedBy": "backfill_cash_register_locks",
        "forcedClosedReason": "Turno legacy sin lock migrado a cierre en despliegue de Fase 1",
    })
    try:
        regs_coll.document(register_id).update({"status": "CLOSED"})
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("lock", "close"), default="lock")
    parser.add_argument("--company", default=None, help="Solo una empresa (id).")
    parser.add_argument("--apply", action="store_true", help="Escribir (sin este flag es DRY-RUN).")
    args = parser.parse_args()

    if not firebase_initialized:
        log("❌ Firebase no inicializado. Verifica firebase-adminsdk.json.")
        sys.exit(1)

    companies = [args.company] if args.company else list_companies()
    log(f"=== Backfill de locks de caja (mode={args.mode}, apply={args.apply}) ===")
    log(f"📊 Empresas a revisar: {len(companies)}")

    stats = {"missing_lock": 0, "lock_created": 0, "closed": 0, "skipped_locked": 0, "errors": 0}
    for cid in companies:
        for sandbox in (True, False):
            for shift_id, data in iter_open_shifts(cid, sandbox):
                register_id = data.get("registerId")
                if not register_id:
                    log(f"⚠️ Turno {shift_id} ({cid}) sin registerId; se omite.")
                    stats["errors"] += 1
                    continue
                lock = get_lock(cid, register_id, sandbox)
                if lock and lock.get("status") in ("ACTIVE", "CLOSING"):
                    stats["skipped_locked"] += 1
                    continue
                stats["missing_lock"] += 1
                scope = f"{'sandbox' if sandbox else 'prod'} / {cid}"
                log(f"  • Turno {shift_id} en caja {register_id} ({scope}) sin lock")
                if not args.apply:
                    continue
                try:
                    if args.mode == "lock":
                        create_lock(cid, shift_id, register_id, data.get("openedByUserId", ""), sandbox)
                        stats["lock_created"] += 1
                    else:
                        force_close_shift(cid, shift_id, register_id, sandbox)
                        stats["closed"] += 1
                except Exception as e:
                    log(f"⚠️ Error procesando {shift_id}: {e}")
                    stats["errors"] += 1

    log("=== Resumen ===")
    log(f"  Turnos abiertos sin lock: {stats['missing_lock']}")
    log(f"  Locks creados: {stats['lock_created']}")
    log(f"  Turnos forzados a cierre: {stats['closed']}")
    log(f"  Turnos ya con lock (omitidos): {stats['skipped_locked']}")
    log(f"  Errores: {stats['errors']}")
    if not args.apply:
        log("ℹ️ DRY-RUN: no se escribió nada. Usa --apply para aplicar.")


if __name__ == "__main__":
    main()
