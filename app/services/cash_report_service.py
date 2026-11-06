"""Servicio de reportes y controles de caja (Fase 4.4)."""
from app.services.db_service import _money, _money_round
from app.services import db_service as _db


class CashReportService:
    """Reportes de entregas, conciliaciones y métricas del ciclo de caja."""

    @staticmethod
    def _deliveries_coll_name(sandbox):
        return "sandbox_cash_deliveries" if sandbox else "cash_deliveries"

    @staticmethod
    def _reconciliations_coll_name(sandbox):
        return "sandbox_cash_reconciliations" if sandbox else "cash_reconciliations"

    @classmethod
    def _fetch(cls, owner_uid, company_id, sandbox, coll_name):
        coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=coll_name)
        if coll is None:
            return []
        try:
            return [d.to_dict() for d in coll.get() if d.exists]
        except Exception:
            return []

    @classmethod
    def list_deliveries(cls, owner_uid, company_id, sandbox, shift_id=None, status=None, delivered_by_uid=None):
        result = []
        for data in cls._fetch(owner_uid, company_id, sandbox, cls._deliveries_coll_name(sandbox)):
            if shift_id and data.get("shiftId") != shift_id:
                continue
            if status and data.get("status") != status:
                continue
            if delivered_by_uid and (data.get("deliveredBy") or {}).get("uid") != delivered_by_uid:
                continue
            result.append({
                "id": data.get("id"),
                "shiftId": data.get("shiftId"),
                "registerId": data.get("registerId"),
                "status": data.get("status"),
                "amounts": data.get("amounts") or {"dop": 0.0, "usd": 0.0},
                "deliveredBy": data.get("deliveredBy"),
                "receivedBy": data.get("receivedBy"),
                "cashDropTransactionIds": data.get("cashDropTransactionIds") or [],
                "createdAt": data.get("createdAt"),
                "receivedAt": data.get("receivedAt"),
            })
        return result

    @classmethod
    def list_reconciliations(cls, owner_uid, company_id, sandbox, shift_id=None, channel=None, status=None):
        result = []
        for data in cls._fetch(owner_uid, company_id, sandbox, cls._reconciliations_coll_name(sandbox)):
            if shift_id and data.get("shiftId") != shift_id:
                continue
            if channel and data.get("channel") != channel:
                continue
            if status and data.get("status") != status:
                continue
            result.append({
                "id": data.get("id"),
                "shiftId": data.get("shiftId"),
                "deliveryId": data.get("deliveryId"),
                "channel": data.get("channel"),
                "expectedAmount": data.get("expectedAmount"),
                "receivedAmount": data.get("receivedAmount"),
                "difference": data.get("difference"),
                "status": data.get("status"),
                "reference": data.get("reference"),
                "approvedBy": data.get("approvedBy"),
                "approvalJustification": data.get("approvalJustification"),
                "createdAt": data.get("createdAt"),
            })
        return result

    @classmethod
    def shift_summary(cls, owner_uid, company_id, sandbox, shift_id):
        deliveries = cls.list_deliveries(owner_uid, company_id, sandbox, shift_id=shift_id)
        reconciliations = cls.list_reconciliations(owner_uid, company_id, sandbox, shift_id=shift_id)

        def _sum(items):
            dop = sum(_money(x.get("amounts", {}).get("dop", 0)) for x in items)
            usd = sum(_money(x.get("amounts", {}).get("usd", 0)) for x in items)
            return _money_round(dop), _money_round(usd)

        pending_receipt = [d for d in deliveries if d["status"] == "PENDING_RECEIPT"]
        received = [d for d in deliveries if d["status"] in ("RECEIVED", "PENDING_RECONCILIATION", "RECONCILED")]
        under_review = [r for r in reconciliations if r["status"] == "UNDER_REVIEW"]
        reconciled = [r for r in reconciliations if r["status"] == "RECONCILED"]

        p_dop, p_usd = _sum(pending_receipt)
        r_dop, r_usd = _sum(received)
        total_difference = _money_round(sum(_money(r.get("difference", 0)) for r in reconciliations))

        return {
            "shiftId": shift_id,
            "deliveries": {
                "total": len(deliveries),
                "pendingReceipt": len(pending_receipt),
                "pendingReceiptDop": p_dop,
                "pendingReceiptUsd": p_usd,
                "received": len(received),
                "receivedDop": r_dop,
                "receivedUsd": r_usd,
            },
            "reconciliations": {
                "total": len(reconciliations),
                "underReview": len(under_review),
                "reconciled": len(reconciled),
                "totalDifference": total_difference,
            },
        }
