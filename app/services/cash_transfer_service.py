"""Servicio de transferencias atómicas entre cajas (Fase 2).

Una transferencia genera dos movimientos que comparten un ``transferId`` único:
  - ``TRANSFER_OUT`` en la caja de origen.
  - ``TRANSFER_IN`` en la caja de destino.

Ambos se escriben en UNA transacción Firestore: o se registran los dos o ninguno.

Idempotencia:
  - Si se provee ``idempotency_key``, el ``transfer_id`` se deriva SIEMPRE de forma
    determinista (ámbito empresa+entorno); un ``transfer_id`` explícito incompatible
    con la clave se rechaza.
  - Un reintento con la misma clave y mismos parámetros devuelve la transferencia
    existente (sin consumir una autorización nueva ni duplicar movimientos).
  - Si la clave ya fue usada con parámetros distintos, o existe una transferencia
    parcial previa, se rechaza.
"""
import hashlib
import uuid
from datetime import datetime, timezone

from app.services.db_service import (
    DatabaseService,
    firebase_initialized,
    CASH_LOCK_ACTIVE,
    CASH_TYPE_TRANSFER_IN,
    CASH_TYPE_TRANSFER_OUT,
    CashShiftLockError,
    CashTransferError,
    CashAuthorizationError,
    _money,
    _money_round,
)
from app.services import db_service as _db


class CashTransferService:
    """Registro atómico de transferencias entre cajas."""

    @staticmethod
    def _tx_coll_name(sandbox):
        return "sandbox_cash_transactions" if sandbox else "cash_transactions"

    @staticmethod
    def _derive_transfer_id(company_id, sandbox, idempotency_key):
        return "tr-" + hashlib.sha256(f"{company_id}:{1 if sandbox else 0}:{idempotency_key}".encode()).hexdigest()[:24]

    @staticmethod
    def _content_signature(company_id, sandbox, amount, currency, source_register_id, target_register_id):
        raw = f"{company_id}:{1 if sandbox else 0}:{_money(amount):.2f}|{currency.upper()}|{source_register_id}|{target_register_id}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def register_transfer(cls, owner_uid, company_id, sandbox, source_shift, target_shift,
                          amount, currency="DOP", reason="", performed_by="", authorized_by="",
                          authorized_by_uid="", transfer_id=None, idempotency_key=None,
                          auth_request_id=None, performer_uid=None):
        """Registra TRANSFER_OUT (origen) + TRANSFER_IN (destino) atómicamente."""
        if not firebase_initialized:
            raise CashTransferError("Firebase no está inicializado.")

        source_register_id = source_shift.get("registerId")
        target_register_id = target_shift.get("registerId")
        source_shift_id = source_shift.get("id")
        target_shift_id = target_shift.get("id")
        if not (source_register_id and target_register_id and source_shift_id and target_shift_id):
            raise CashTransferError("Origen y destino de la transferencia son obligatorios.")
        if source_register_id == target_register_id:
            raise CashTransferError("No se puede transferir entre la misma caja.")

        amount_float = _money_round(amount)
        currency = (currency or "DOP").upper()
        content_sig = cls._content_signature(company_id, sandbox, amount_float, currency, source_register_id, target_register_id)

        # R1: idempotencia determinista a partir de la clave (ámbito empresa+entorno).
        if idempotency_key:
            derived = cls._derive_transfer_id(company_id, sandbox, idempotency_key)
            if transfer_id and transfer_id != derived:
                raise CashTransferError("El transfer_id no coincide con la clave de idempotencia.")
            transfer_id = derived
            key = idempotency_key
        else:
            transfer_id = transfer_id or str(uuid.uuid4())
            key = f"transfer-{transfer_id}"

        now_iso = datetime.now(timezone.utc).isoformat()

        locks_coll = _db._company_coll(
            company_id=company_id, owner_uid=owner_uid,
            coll_name=DatabaseService._cash_lock_coll_name(sandbox),
        )
        txs_coll = _db._company_coll(
            company_id=company_id, owner_uid=owner_uid,
            coll_name=cls._tx_coll_name(sandbox),
        )
        if locks_coll is None or txs_coll is None:
            raise CashTransferError("No se pudo resolver las colecciones de caja.")

        source_lock_ref = locks_coll.document(source_register_id)
        target_lock_ref = locks_coll.document(target_register_id)
        out_ref = txs_coll.document(f"transfer-{transfer_id}-out")
        in_ref = txs_coll.document(f"transfer-{transfer_id}-in")

        def _run(txn):
            # ── FASE 1: TODAS LAS LECTURAS PRIMERO ───────────────────────────
            src_snap = txn.get(source_lock_ref)
            dst_snap = txn.get(target_lock_ref)
            existing_out = txn.get(out_ref)
            existing_in = txn.get(in_ref)

            auth_data = None
            auth_ref = None
            if auth_request_id:
                from app.services.cash_authorization_service import CashAuthorizationService
                auth_data, auth_ref = CashAuthorizationService.verify(
                    txn, owner_uid, company_id, sandbox, auth_request_id,
                    CASH_TYPE_TRANSFER_OUT, amount_float, currency,
                    source_register_id, source_shift_id, performer_uid,
                )

            # ── FASE 2: VALIDACIONES (sobre las lecturas) ────────────────────
            if not src_snap.exists:
                raise CashShiftLockError("La caja de origen no tiene lock de ocupación.")
            if src_snap.to_dict().get("status") != CASH_LOCK_ACTIVE or \
                    src_snap.to_dict().get("shiftId") != source_shift_id:
                raise CashShiftLockError("La caja de origen no está activa para esta sesión.")
            if not dst_snap.exists:
                raise CashShiftLockError("La caja de destino no tiene lock de ocupación.")
            dst_lock = dst_snap.to_dict()
            if dst_lock.get("status") != CASH_LOCK_ACTIVE or dst_lock.get("shiftId") != target_shift_id:
                raise CashShiftLockError("La caja de destino no está activa para esta sesión.")

            out_exists = existing_out.exists
            in_exists = existing_in.exists
            if out_exists or in_exists:
                if out_exists and in_exists:
                    stored_out = existing_out.to_dict() or {}
                    stored_in = existing_in.to_dict() or {}
                    if (stored_out.get("contentSignature") == content_sig
                            and stored_out.get("transferId") == transfer_id
                            and stored_out.get("idempotencyKey") == key
                            and stored_in.get("idempotencyKey") == key):
                        # Idempotente: no consumir una autorización nueva.
                        return {
                            "transferId": transfer_id,
                            "out": stored_out,
                            "in": stored_in,
                            "idempotentHit": True,
                        }
                    raise CashTransferError("La clave de idempotencia ya fue usada con parámetros distintos.")
                raise CashTransferError("Integridad: existe una transferencia parcial previa.")

            # ── FASE 3: TODAS LAS ESCRITURAS ────────────────────────────────
            if auth_ref is not None:
                from app.services.cash_authorization_service import CashAuthorizationService
                txn.update(auth_ref, {
                    "status": CashAuthorizationService.STATUS_CONSUMED,
                    "consumedAt": datetime.now(timezone.utc),
                })

            base = {
                "ownerUID": owner_uid,
                "amount": amount_float,
                "currency": currency,
                "transferId": transfer_id,
                "idempotencyKey": key,
                "contentSignature": content_sig,
                "reason": reason,
                "performedBy": performed_by,
                "authorizedBy": (auth_data or {}).get("name", authorized_by),
                "authorizedByUid": (auth_data or {}).get("uid", authorized_by_uid),
                "authorizedAt": (auth_data or {}).get("authorizedAt", ""),
                "date": now_iso,
                "status": "ACTIVE",
            }
            out_tx = dict(base)
            out_tx.update({
                "id": f"transfer-{transfer_id}-out",
                "type": CASH_TYPE_TRANSFER_OUT,
                "shiftId": source_shift_id,
                "registerId": source_register_id,
                "paymentMethod": "Efectivo",
            })
            in_tx = dict(base)
            in_tx.update({
                "id": f"transfer-{transfer_id}-in",
                "type": CASH_TYPE_TRANSFER_IN,
                "shiftId": target_shift_id,
                "registerId": target_register_id,
                "paymentMethod": "Efectivo",
            })

            txn.set(out_ref, out_tx)
            txn.set(in_ref, in_tx)
            txn.update(source_lock_ref, {"updatedAt": now_iso})
            txn.update(target_lock_ref, {"updatedAt": now_iso})
            return {"transferId": transfer_id, "out": out_tx, "in": in_tx}

        try:
            return DatabaseService._run_in_transaction(_run)
        except (CashShiftLockError, CashTransferError, CashAuthorizationError):
            raise
        except Exception as e:
            raise CashTransferError(f"Error al registrar transferencia: {e}")
