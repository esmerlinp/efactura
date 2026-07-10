"""
Migración one-time: Garnishments legacy (hr_garnishments) → RecurringMovement (hr_recurring_movements).

- Lee de la colección legacy `users/{uid}/{prefix}hr_garnishments`
- Convierte cada documento al formato RecurringMovement con isGarnishment=True
- Guarda en la colección nueva `users/{uid}/{prefix}hr_recurring_movements`
- No elimina la colección legacy (respaldo)
- Reporta estadísticas de la migración
"""

import sys
import os
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db_service import db_firestore, firebase_initialized

DEFAULT_CONCEPT_CODE = "EMBARGO"

FIELD_MAP = {
    # (legacy_field, new_field, transform_fn or None)
    "employeeId": "employeeId",
    "employeeName": "employeeName",
    "garnishmentType": "garnishmentType",
    "referenceNumber": "referenceNumber",
    "beneficiaryName": "beneficiaryName",
    "beneficiaryAccount": "beneficiaryAccount",
    "totalAmount": "totalAmount",
    "remainingBalance": "remainingBalance",
    "priority": "priority",
    "status": "status",
    "notes": "notes",
    "createdBy": "createdBy",
    "createdAt": "createdAt",
    "updatedBy": "updatedBy",
    "updatedAt": "updatedAt",
}

LEGACY_COLL = "garnishments"
NEW_COLL = "recurring_movements"

# Mapeo de DeductionType legacy -> amountType nuevo
DEDUCTION_TYPE_MAP = {
    "fixed": "fixed",
    "percentage": "percentage",
    "max_of_legal": "percentage",
}


def _collection_path(owner_uid: str, collection: str, sandbox: bool = True) -> str:
    prefix = "sandbox_hr_" if sandbox else "hr_"
    return f"users/{owner_uid}/{prefix}{collection}"


def migrate_user(owner_uid: str, sandbox: bool = True, dry_run: bool = False) -> dict:
    """Migra los garnishments legacy de un usuario a RecurringMovement."""
    if not firebase_initialized or db_firestore is None:
        print("❌ Firebase no está inicializado.")
        return {"created": 0, "skipped": 0, "errors": 0}

    legacy_path = _collection_path(owner_uid, LEGACY_COLL, sandbox)
    new_path = _collection_path(owner_uid, NEW_COLL, sandbox)

    print(f"\n📋 Migrando garnishments de {owner_uid} ({'sandbox' if sandbox else 'produccion'})...")
    print(f"   Origen:  {legacy_path}")
    print(f"   Destino: {new_path}")

    legacy_docs = list(db_firestore.collection(legacy_path).get())
    print(f"   → {len(legacy_docs)} garnishments legacy encontrados")

    created = 0
    skipped = 0
    errors = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for doc in legacy_docs:
        try:
            legacy = doc.to_dict()
            if not legacy:
                skipped += 1
                continue

            legacy_id = doc.id
            emp_id = legacy.get("employeeId", "")

            if not emp_id:
                print(f"   ⚠️  {legacy_id}: sin employeeId, omitido")
                skipped += 1
                continue

            deduction_type = legacy.get("deductionType", "fixed")
            monthly_ded = float(legacy.get("monthlyDeduction", 0))
            ded_pct = float(legacy.get("deductionPercent", 0))
            amount_type = DEDUCTION_TYPE_MAP.get(deduction_type, "fixed")
            end_date = legacy.get("endDate", "")
            status = legacy.get("status", "active")

            # Construir descripción legible
            g_type = legacy.get("garnishmentType", "")
            g_type_label = {
                "judicial": "Embargo Judicial",
                "pension_alimenticia": "Pensión Alimenticia",
                "cooperativa": "Embargo Cooperativa",
                "prestamo": "Embargo Préstamo",
            }.get(g_type, f"Embargo ({g_type})")
            ref = legacy.get("referenceNumber", "")
            description = f"{g_type_label} - Ref: {ref}" if ref else g_type_label

            # Preparar concepto según tipo
            concept_code = DEFAULT_CONCEPT_CODE
            if g_type == "pension_alimenticia":
                concept_code = "PENSION_ALIMENTICIA"

            new_movement = {
                # ID: usar mismo ID legacy para trazabilidad (prefijo para evitar colisiones)
                "id": f"garnish_migrated_{legacy_id}",
                "employeeId": emp_id,
                "contractId": "",
                "employeeName": legacy.get("employeeName", ""),
                "legalEntityId": "",
                "conceptCode": concept_code,
                "movementType": "deduction",
                "description": description,
                "amountType": amount_type,
                "amount": monthly_ded if deduction_type == "fixed" else 0.0,
                "percentage": ded_pct / 100.0 if ded_pct > 0 else 0.0,
                "formula": "",
                "isLoan": False,
                "totalAmount": float(legacy.get("totalAmount", 0)),
                "installmentAmount": monthly_ded,
                "totalInstallments": 0,
                "paidInstallments": 0,
                "remainingBalance": float(legacy.get("remainingBalance", 0)),
                "isGarnishment": True,
                "garnishmentType": g_type,
                "referenceNumber": ref,
                "issuingEntity": legacy.get("courtName", ""),
                "beneficiaryName": legacy.get("beneficiaryName", ""),
                "beneficiaryAccount": legacy.get("beneficiaryAccount", ""),
                "deductionType": deduction_type,
                "deductionPercent": ded_pct / 100.0 if ded_pct > 0 else 0.0,
                "maxLegalRate": 0.0,
                "startDate": legacy.get("startDate", ""),
                "endDate": end_date,
                "indefinite": not bool(end_date),
                "applyFrequency": "every_period",
                "applyMonths": [],
                "priority": legacy.get("priority", 50),
                "status": status,
                "autoComplete": True,
                "notes": legacy.get("notes", ""),
                "createdBy": legacy.get("createdBy", "system:migration"),
                "createdAt": legacy.get("createdAt", now_iso),
                "updatedBy": legacy.get("updatedBy", "system:migration"),
                "updatedAt": now_iso,
                "auditLog": [{
                    "action": "migrated_from_garnishments",
                    "legacyId": legacy_id,
                    "timestamp": now_iso,
                }],
            }

            if not dry_run:
                db_firestore.collection(new_path).document(new_movement["id"]).set(new_movement)
            print(f"   ✅ {legacy_id} → {new_movement['id']} ({description}) [{status}]")
            created += 1

        except Exception as e:
            print(f"   ❌ Error migrando {doc.id}: {e}")
            errors += 1

    print(f"\n   📊 Resumen: {created} creados, {skipped} omitidos, {errors} errores")
    return {"created": created, "skipped": skipped, "errors": errors}


def get_all_user_uids() -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        docs = db_firestore.collection("users").get()
        return [doc.id for doc in docs]
    except Exception as e:
        print(f"⚠️ Error al obtener usuarios: {e}")
        return []


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrar garnishments legacy → RecurringMovement")
    parser.add_argument("--owner-uid", help="UID específico del owner (opcional, sino migra todos)")
    parser.add_argument("--sandbox", action="store_true", default=True, help="Usar colecciones sandbox (por defecto True)")
    parser.add_argument("--production", action="store_true", help="Usar colecciones de producción")
    parser.add_argument("--dry-run", action="store_true", help="Solo simular, no escribir en Firestore")
    args = parser.parse_args()

    sandbox = not args.production

    print("🚀 Iniciando migración de garnishments legacy → RecurringMovement...")
    print(f"   Entorno: {'sandbox' if sandbox else 'produccion'}")
    print(f"   Dry run: {args.dry_run}")

    if not firebase_initialized:
        print("❌ Firebase no está inicializado.")
        sys.exit(1)

    if args.owner_uid:
        results = [migrate_user(args.owner_uid, sandbox=sandbox, dry_run=args.dry_run)]
    else:
        uids = get_all_user_uids()
        print(f"\n👥 Usuarios encontrados: {len(uids)}")
        results = []
        for uid in uids:
            r = migrate_user(uid, sandbox=sandbox, dry_run=args.dry_run)
            results.append(r)

    total_created = sum(r["created"] for r in results)
    total_skipped = sum(r["skipped"] for r in results)
    total_errors = sum(r["errors"] for r in results)

    print(f"\n{'='*50}")
    print(f"🏁 MIGRACIÓN COMPLETADA")
    print(f"   Creados: {total_created}")
    print(f"   Omitidos: {total_skipped}")
    print(f"   Errores: {total_errors}")
    print(f"{'='*50}")