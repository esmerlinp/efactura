"""Servicio de conciliación de fondos (Fase 4.3) — CashReconciliation.

Compara, por canal, el importe esperado contra el efectivamente recibido:

  - Efectivo DOP/USD: esperado = importe del `CASH_DROP` vinculado a la `CashDelivery`
    (derivado, no provisto por el cliente); recibido = efectivo recibido.
  - Tarjeta: esperado = `expectedCard` del cierre; recibido = lote del adquirente.
  - Transferencia: esperado = `expectedTransfer` del cierre; recibido = depósito bancario.

La diferencia (faltante/sobrante) es inmutable y, si excede la tolerancia, la conciliación
queda `UNDER_REVIEW` y requiere aprobación de supervisor (autorización single-use de F2).

Estados: `OPEN → RECONCILED`; `OPEN → UNDER_REVIEW → RECONCILED`.
"""
import hashlib
from datetime import datetime, timezone
from decimal import Decimal

from app.services.db_service import (
    DatabaseService,
    firebase_initialized,
    _money,
    _money_round,
)
from app.services import db_service as _db


RECONCILIATION_OPEN = "OPEN"
RECONCILIATION_RECONCILED = "RECONCILED"
RECONCILIATION_UNDER_REVIEW = "UNDER_REVIEW"

CHANNEL_CASH_DOP = "CASH_DOP"
CHANNEL_CASH_USD = "CASH_USD"
CHANNEL_CARD = "CARD"
CHANNEL_TRANSFER = "TRANSFER"

RECONCILIATION_TOLERANCE = Decimal("0.01")


class CashReconciliationError(Exception):
    """Error de negocio en una conciliación."""


class CashReconciliationService:
    """Conciliación de fondos por canal."""

    @staticmethod
    def _coll_name(sandbox):
        return "sandbox_cash_reconciliations" if sandbox else "cash_reconciliations"

    @staticmethod
    def _derive_reconciliation_id(company_id, sandbox, idempotency_key):
        return "rec-" + hashlib.sha256(f"{company_id}:{1 if sandbox else 0}:{idempotency_key}".encode()).hexdigest()[:24]

    @staticmethod
    def _content_signature(company_id, sandbox, channel, expected, received, delivery_id, shift_id):
        canonical = "|".join([
            str(company_id), str(1 if sandbox else 0), channel,
            f"expected={_money(expected).normalize():f}", f"received={_money(received).normalize():f}",
            str(delivery_id or ""), str(shift_id or ""),
        ])
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def _read_delivery(cls, owner_uid, company_id, sandbox, delivery_id):
        from app.services.cash_delivery_service import CashDeliveryService
        delivery = CashDeliveryService.get_delivery(owner_uid, company_id, sandbox, delivery_id)
        if not delivery:
            raise CashReconciliationError("Entrega no encontrada.")
        return delivery

    @classmethod
    def _read_shift(cls, owner_uid, company_id, sandbox, shift_id):
        shifts_coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid,
                                        coll_name="sandbox_cash_shifts" if sandbox else "cash_shifts")
        if shifts_coll is None:
            raise CashReconciliationError("No se pudo resolver la colección de turnos.")
        snap = shifts_coll.document(shift_id).get()
        if not (snap and snap.exists):
            raise CashReconciliationError("Turno no encontrado.")
        return snap.to_dict() or {}

    @classmethod
    def _reconcile(cls, owner_uid, company_id, sandbox, channel, expected_amount, received_amount,
                   delivery_id, shift_id, reference, reconciled_by_uid, reconciled_by_name,
                   notes, idempotency_key):
        expected = _money_round(expected_amount)
        received = _money_round(received_amount)
        difference = _money_round(_money(received) - _money(expected))

        reconciliation_id = cls._derive_reconciliation_id(company_id, sandbox, idempotency_key)
        content_sig = cls._content_signature(company_id, sandbox, channel, expected, received, delivery_id, shift_id)

        coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._coll_name(sandbox))
        if coll is None:
            raise CashReconciliationError("No se pudo resolver la colección de conciliaciones.")
        rec_ref = coll.document(reconciliation_id)
        now_iso = datetime.now(timezone.utc).isoformat()

        def _run(txn):
            snap = txn.get(rec_ref)
            if snap.exists:
                existing = snap.to_dict() or {}
                if existing.get("contentSignature") == content_sig:
                    return {"already": True, "reconciliation": existing}
                raise CashReconciliationError("La clave de idempotencia ya fue usada con parámetros distintos.")

            status = RECONCILIATION_RECONCILED if abs(_money(difference)) <= RECONCILIATION_TOLERANCE else RECONCILIATION_UNDER_REVIEW
            rec = {
                "id": reconciliation_id,
                "idempotencyKey": idempotency_key,
                "contentSignature": content_sig,
                "ownerUID": owner_uid,
                "companyId": company_id,
                "deliveryId": delivery_id or None,
                "shiftId": shift_id,
                "channel": channel,
                "expectedAmount": expected,
                "receivedAmount": received,
                "difference": difference,
                "status": status,
                "reference": reference or "",
                "reconciledBy": {"uid": reconciled_by_uid, "name": reconciled_by_name},
                "reconciledAt": now_iso,
                "approvedBy": None,
                "approvalJustification": "",
                "notes": notes or "",
                "createdAt": now_iso,
                "updatedAt": now_iso,
                "history": [{
                    "event": "RECONCILED" if status == RECONCILIATION_RECONCILED else "UNDER_REVIEW",
                    "by": reconciled_by_uid, "at": now_iso,
                    "fromStatus": None, "toStatus": status, "notes": notes or "",
                }],
            }
            txn.set(rec_ref, rec)
            return {"already": False, "reconciliation": rec}

        try:
            return DatabaseService._run_in_transaction(_run)
        except CashReconciliationError:
            raise
        except Exception as e:
            raise CashReconciliationError(f"Error al conciliar: {e}")

    @classmethod
    def reconcile_cash(cls, owner_uid, company_id, sandbox, delivery_id, channel, received_amount,
                       reference, reconciled_by_uid, reconciled_by_name, notes, idempotency_key):
        if channel not in (CHANNEL_CASH_DOP, CHANNEL_CASH_USD):
            raise CashReconciliationError("Canal de efectivo inválido.")
        delivery = cls._read_delivery(owner_uid, company_id, sandbox, delivery_id)
        currency_key = "dop" if channel == CHANNEL_CASH_DOP else "usd"
        expected = _money(delivery.get("amounts", {}).get(currency_key, 0))
        if expected <= 0:
            raise CashReconciliationError(f"La entrega no tiene importe en {currency_key.upper()}.")
        return cls._reconcile(owner_uid, company_id, sandbox, channel, expected, received_amount,
                              delivery_id, delivery.get("shiftId"), reference,
                              reconciled_by_uid, reconciled_by_name, notes, idempotency_key)

    @classmethod
    def reconcile_channel(cls, owner_uid, company_id, sandbox, shift_id, channel, received_amount,
                          reference, reconciled_by_uid, reconciled_by_name, notes, idempotency_key):
        if channel not in (CHANNEL_CARD, CHANNEL_TRANSFER):
            raise CashReconciliationError("Canal inválido para conciliación de cierre.")
        shift = cls._read_shift(owner_uid, company_id, sandbox, shift_id)
        field = "expectedCard" if channel == CHANNEL_CARD else "expectedTransfer"
        expected = _money(shift.get(field, 0))
        return cls._reconcile(owner_uid, company_id, sandbox, channel, expected, received_amount,
                              None, shift_id, reference,
                              reconciled_by_uid, reconciled_by_name, notes, idempotency_key)

    @classmethod
    def get_reconciliation(cls, owner_uid, company_id, sandbox, reconciliation_id):
        coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._coll_name(sandbox))
        if coll is None:
            return None
        snap = coll.document(reconciliation_id).get()
        return snap.to_dict() if snap and snap.exists else None

    @classmethod
    def approve_difference(cls, owner_uid, company_id, sandbox, reconciliation_id,
                           approval_justification, authorized_by_uid, authorized_by_name,
                           auth_request_id, performer_uid):
        """Aprueba una diferencia (UNDER_REVIEW → RECONCILED) con autorización single-use F2."""
        from app.services.cash_authorization_service import CashAuthorizationService

        coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._coll_name(sandbox))
        if coll is None:
            raise CashReconciliationError("No se pudo resolver la colección de conciliaciones.")
        rec_ref = coll.document(reconciliation_id)
        now_iso = datetime.now(timezone.utc).isoformat()

        def _run(txn):
            snap = txn.get(rec_ref)
            if not snap.exists:
                raise CashReconciliationError("Conciliación no encontrada.")
            r = snap.to_dict() or {}
            if r.get("status") == RECONCILIATION_RECONCILED:
                return r  # idempotente (ya aprobada/conciliada)
            if r.get("status") != RECONCILIATION_UNDER_REVIEW:
                raise CashReconciliationError(f"No se puede aprobar una conciliación en estado {r.get('status')}.")

            # Consumir autorización single-use (contexto ligado a la conciliación).
            auth = CashAuthorizationService.consume(
                txn, owner_uid, company_id, sandbox, auth_request_id,
                "RECONCILIATION_APPROVE", abs(_money(r.get("difference", 0))), "DOP",
                r.get("deliveryId") or r.get("shiftId", ""), r.get("shiftId", ""), performer_uid,
            )

            history = list(r.get("history") or [])
            history.append({
                "event": "APPROVED", "by": authorized_by_uid, "at": now_iso,
                "fromStatus": RECONCILIATION_UNDER_REVIEW, "toStatus": RECONCILIATION_RECONCILED,
                "notes": approval_justification or "",
            })
            r["approvedBy"] = {"uid": auth.get("uid", authorized_by_uid), "name": auth.get("name", authorized_by_name)}
            r["approvalJustification"] = approval_justification or ""
            r["approvedAt"] = now_iso
            r["status"] = RECONCILIATION_RECONCILED
            r["history"] = history
            r["updatedAt"] = now_iso
            txn.set(rec_ref, r)
            return r

        try:
            return DatabaseService._run_in_transaction(_run)
        except CashReconciliationError:
            raise
        except Exception as e:
            raise CashReconciliationError(f"Error al aprobar la diferencia: {e}")
