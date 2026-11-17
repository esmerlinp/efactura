"""Entregable 3.3.4 — Construcción del IR-17 desde retenciones aplicadas.

Verifica correspondencias confirmadas, prorrateo de base en parciales, exclusión
de pendientes/rechazados/anulados, períodos, idempotencia y conciliación.
"""

from app.services.ir17_build_service import (
    build_applied_retention_records,
    aggregate_ir17,
    build_ir17_summary,
)


def _invoice(rule, base=1000.0, calculated=150.0, rate=0.15, **kw):
    inv = {
        "id": "inv-1", "supplierId": "sup-1",
        "retentionIsrRule": rule, "retentionIsrBase": base,
        "retentionIsrAmount": calculated, "retentionIsrRate": rate,
    }
    inv.update(kw)
    return inv


def _pay(retention, date="2026-03-20", status="approved", pay_status=""):
    p = {"retentionIsrApplied": retention, "paymentDate": date, "approvalStatus": status}
    if pay_status:
        p["status"] = pay_status
    return p


class TestLineMapping:
    def test_professional_fees_l2(self):
        recs = build_applied_retention_records(
            [{"invoice": _invoice("professional_fees", calculated=150.0),
              "payments": [_pay(150.0)]}]
        )
        assert recs[0]["ir17Line"] == 2
        assert recs[0]["ir17Rate"] == 0.15

    def test_payments_abroad_l10(self):
        recs = build_applied_retention_records(
            [{"invoice": _invoice("payments_abroad", calculated=270.0, rate=0.27),
              "payments": [_pay(270.0)]}]
        )
        assert recs[0]["ir17Line"] == 10

    def test_royalties_l22(self):
        recs = build_applied_retention_records(
            [{"invoice": _invoice("royalties", calculated=150.0),
              "payments": [_pay(150.0)]}]
        )
        assert recs[0]["ir17Line"] == 22

    def test_digital_services_l23(self):
        recs = build_applied_retention_records(
            [{"invoice": _invoice("digital_services_abroad", calculated=150.0),
              "payments": [_pay(150.0)]}]
        )
        assert recs[0]["ir17Line"] == 23

    def test_goods_services_no_line(self):
        recs = build_applied_retention_records(
            [{"invoice": _invoice("goods_services", calculated=20.0),
              "payments": [_pay(20.0)]}]
        )
        assert recs == []


class TestPartialAndAggregation:
    def test_partial_payment_proportional_base(self):
        # base 1000, calculated 150, applied 75 (50%) → base aplicada 500
        inv = _invoice("professional_fees", base=1000.0, calculated=150.0)
        recs = build_applied_retention_records(
            [{"invoice": inv, "payments": [_pay(75.0)]}]
        )
        assert recs[0]["ir17Base"] == 500.0
        assert recs[0]["isrWithheld"] == 75.0

    def test_multiple_payments_aggregated(self):
        inv = _invoice("professional_fees", base=1000.0, calculated=150.0)
        recs = build_applied_retention_records(
            [{"invoice": inv, "payments": [_pay(50.0, "2026-03-20"), _pay(100.0, "2026-03-20")]}]
        )
        assert len(recs) == 2
        grouped = aggregate_ir17(recs)
        assert grouped[2]["tax"] == 150.0
        assert grouped[2]["base"] == 1000.0
        assert grouped[2]["count"] == 2

    def test_reversal_voided_excluded(self):
        inv = _invoice("professional_fees", base=1000.0, calculated=150.0)
        recs = build_applied_retention_records(
            [{"invoice": inv, "payments": [_pay(150.0, pay_status="voided")]}]
        )
        assert recs == []

    def test_pending_rejected_excluded(self):
        inv = _invoice("professional_fees", base=1000.0, calculated=150.0)
        recs = build_applied_retention_records(
            [{"invoice": inv, "payments": [
                _pay(150.0, status="pending"),
                _pay(150.0, status="rejected"),
            ]}]
        )
        assert recs == []


class TestPeriodsAndIdempotency:
    def test_period_extraction(self):
        inv = _invoice("professional_fees", base=1000.0, calculated=150.0)
        recs = build_applied_retention_records(
            [{"invoice": inv, "payments": [_pay(150.0, "2026-04-05")]}]
        )
        assert recs[0]["period"] == "202604"

    def test_idempotent(self):
        items = [{"invoice": _invoice("professional_fees", base=1000.0, calculated=150.0),
                  "payments": [_pay(150.0, "2026-03-20")]}]
        r1, g1 = build_ir17_summary(items)
        r2, g2 = build_ir17_summary(items)
        assert r1 == r2
        assert g1 == g2

    def test_company_isolation_is_caller_scope(self):
        # La función es pura: solo recibe los documentos de una empresa.
        items_a = [{"invoice": _invoice("professional_fees", id="inv-a", calculated=150.0),
                    "payments": [_pay(150.0)]}]
        recs = build_applied_retention_records(items_a)
        assert all(r["invoiceId"] == "inv-a" for r in recs)
