"""Conciliación 609 ↔ IR-17 y protecciones de consistencia de retención."""

from app.services.dgii_609_service import (
    build_609_record_from_invoice,
    validate_retention_consistency,
)
from app.services.ir17_build_service import build_applied_retention_records


def _supplier():
    return {
        "supplierName": "Proveedor Exterior SRL", "tipoIdentificacion609": "2",
        "supplierRnc": "123456789", "paisDestino609": "USA", "parteRelacionada": "0",
    }


def _invoice(rule, base=1000.0, calculated=150.0, applied=150.0, rate=0.15):
    return {
        "id": "inv-1", "supplierId": "sup-1", "ncf": "E470000000001",
        "date": "2026-03-15", "total": 1000.0,
        "tipoServicio609": "2", "detalleServicio609": "21",
        "retentionIsrRule": rule, "retentionIsrBase": base,
        "retentionIsrAmount": calculated, "retentionIsrApplied": applied,
        "retentionIsrRate": rate,
    }


def _pay(retention, date="2026-03-20", status="approved", pay_status=""):
    p = {"retentionIsrApplied": retention, "paymentDate": date, "approvalStatus": status}
    if pay_status:
        p["status"] = pay_status
    return p


class Test609Ir17Conciliation:
    def test_applied_retention_consistent(self):
        inv = _invoice("professional_fees", calculated=150.0, applied=150.0)
        payments = [_pay(150.0)]
        rec, blocked = build_609_record_from_invoice(inv, _supplier(), payments)
        recs = build_applied_retention_records([{"invoice": inv, "payments": payments}])
        assert blocked is None
        assert float(rec["isrRetenido"]) == recs[0]["isrWithheld"] == 150.0

    def test_no_duplication_multiple_payments(self):
        inv = _invoice("professional_fees", base=1000.0, calculated=150.0, applied=150.0)
        payments = [_pay(50.0), _pay(100.0)]
        recs = build_applied_retention_records([{"invoice": inv, "payments": payments}])
        total = sum(r["isrWithheld"] for r in recs)
        assert total == 150.0  # no duplicado
        assert len(recs) == 2

    def test_partial_not_exceeding_invoice(self):
        inv = _invoice("professional_fees", calculated=150.0, applied=75.0)
        payments = [_pay(75.0)]
        recs = build_applied_retention_records([{"invoice": inv, "payments": payments}])
        assert recs[0]["isrWithheld"] <= 150.0

    def test_reversal_excluded_both(self):
        inv = _invoice("professional_fees", calculated=150.0, applied=0.0)
        payments = [_pay(150.0, pay_status="voided")]
        rec, blocked = build_609_record_from_invoice(inv, _supplier(), payments)
        recs = build_applied_retention_records([{"invoice": inv, "payments": payments}])
        assert blocked is not None
        assert recs == []

    def test_periods_coherent(self):
        inv = _invoice("professional_fees", calculated=150.0, applied=150.0)
        payments = [_pay(150.0, "2026-04-05")]
        recs = build_applied_retention_records([{"invoice": inv, "payments": payments}])
        assert recs[0]["period"] == "202604"


class TestRetentionConsistencyProtections:
    def test_negative_applied(self):
        errs = validate_retention_consistency({"retentionIsrApplied": -1.0})
        assert any("negativa" in e for e in errs)

    def test_applied_exceeds_calculated(self):
        errs = validate_retention_consistency(
            {"retentionIsrApplied": 200.0, "retentionIsrAmount": 150.0}
        )
        assert any("excede" in e for e in errs)

    def test_consistent_ok(self):
        assert validate_retention_consistency(
            {"retentionIsrApplied": 150.0, "retentionIsrAmount": 150.0, "retentionIsrBase": 1000.0}
        ) == []
