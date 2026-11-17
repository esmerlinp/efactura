"""Entregable 3.1 — Cálculo y registro de retenciones ISR/ITBIS.

Verifica la matriz central, la precedencia (categoría, tasas personalizadas y
flags), el cálculo de bases separadas, la integración en create y la aplicación
de retención por pago (proporcional e idempotente).
"""

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

import app.services.supplier_invoice_service as mod
from app.services.tax_engine import TaxEngine
from app.services.supplier_invoice_service import SupplierInvoiceService


def _supplier(**kw):
    s = {
        "id": "sup-1",
        "withholdingCategory": "",
        "tasaRetencionISR": 0.0,
        "tasaRetencionITBIS": 0.0,
        "esExtranjero": False,
        "isrWithholding": False,
        "itbisWithholding": False,
    }
    s.update(kw)
    return s


class TestTaxEngineWithholdingPrecedence:
    def test_custom_rate_wins_over_category(self):
        s = _supplier(withholdingCategory="professional_fees", tasaRetencionISR=5.0)
        r = TaxEngine(country="DO").resolve_withholding(s)
        assert r["isr_rate"] == 0.05
        assert r["isr_rule"] == "custom"

    def test_professional_fees_category(self):
        r = TaxEngine(country="DO").resolve_withholding(_supplier(withholdingCategory="professional_fees"))
        assert r["isr_rate"] == 0.15
        assert r["isr_rule"] == "professional_fees"
        assert r["isr_ir17_line"] == 2
        assert r["itbis_rate"] == 1.00
        assert r["itbis_rule"] == "independent_professionals"

    def test_payments_abroad_category(self):
        r = TaxEngine(country="DO").resolve_withholding(_supplier(withholdingCategory="payments_abroad"))
        assert r["isr_rate"] == 0.27
        assert r["isr_ir17_line"] == 10
        assert r["itbis_rate"] == 0.0
        assert r["itbis_rule"] is None

    def test_digital_services_abroad_category(self):
        r = TaxEngine(country="DO").resolve_withholding(_supplier(withholdingCategory="digital_services_abroad"))
        assert r["isr_rate"] == 0.15
        assert r["isr_ir17_line"] == 23
        assert r["itbis_rate"] == 0.0

    def test_legal_services_category_only_itbis(self):
        r = TaxEngine(country="DO").resolve_withholding(_supplier(withholdingCategory="legal_services"))
        assert r["isr_rate"] == 0.0
        assert r["itbis_rate"] == 0.75
        assert r["itbis_rule"] == "legal_services"

    def test_goods_services_category(self):
        r = TaxEngine(country="DO").resolve_withholding(_supplier(withholdingCategory="goods_services"))
        assert r["isr_rate"] == 0.02
        assert r["itbis_rate"] == 0.30
        assert r["isr_ir17_line"] is None  # sin correspondencia confirmada

    def test_es_extranjero_flag(self):
        r = TaxEngine(country="DO").resolve_withholding(_supplier(esExtranjero=True))
        assert r["isr_rate"] == 0.15
        assert r["isr_rule"] == "digital_services_abroad"

    def test_flags_existing(self):
        r = TaxEngine(country="DO").resolve_withholding(_supplier(isrWithholding=True, itbisWithholding=True))
        assert r["isr_rate"] == 0.02
        assert r["itbis_rate"] == 0.30

    def test_exempt_no_flags(self):
        r = TaxEngine(country="DO").resolve_withholding(_supplier())
        assert r["isr_rate"] == 0.0
        assert r["itbis_rate"] == 0.0
        assert r["isr_rule"] is None
        assert r["itbis_rule"] is None

    def test_unknown_category_falls_back_to_flags(self):
        r = TaxEngine(country="DO").resolve_withholding(_supplier(withholdingCategory="nope", isrWithholding=True))
        assert r["isr_rate"] == 0.02


class TestCalculateRetention:
    def test_goods_services_bases_separated(self):
        # subtotal 1000, descuento 100, itbis 162 (18% de 900)
        ret = SupplierInvoiceService.calculate_retention(
            _supplier(withholdingCategory="goods_services"), subtotal=1000.0, discount=100.0, itbis=162.0
        )
        assert ret["retentionIsrBase"] == 900.0
        assert ret["retentionIsrRate"] == 0.02
        assert ret["retentionIsrAmount"] == 18.0
        assert ret["retentionItbisBase"] == 162.0
        assert ret["retentionItbisRate"] == 0.30
        assert ret["retentionItbisAmount"] == 48.6
        assert ret["retentionStatus"] == "calculated"
        assert ret["retentionIsrApplied"] == 0.0

    def test_professional_fees(self):
        ret = SupplierInvoiceService.calculate_retention(
            _supplier(withholdingCategory="professional_fees"), subtotal=1000.0, discount=0.0, itbis=180.0
        )
        assert ret["retentionIsrAmount"] == 150.0
        assert ret["retentionItbisAmount"] == 180.0  # 100% del ITBIS

    def test_exempt_zero(self):
        ret = SupplierInvoiceService.calculate_retention(_supplier(), subtotal=1000.0, discount=0.0, itbis=180.0)
        assert ret["retentionIsrAmount"] == 0.0
        assert ret["retentionItbisAmount"] == 0.0


def _delegating_tx():
    class _Tx:
        def get(self, ref):
            return ref.get()

        def set(self, ref, data, **kw):
            ref.set(data)

        def update(self, ref, data):
            ref.update(data)

        def delete(self, ref):
            ref.delete()

    def _run(func, *args, **kwargs):
        return func(_Tx(), *args, **kwargs)

    return patch("app.services.db_service.run_firestore_transaction", side_effect=_run)


def _snap(data):
    s = MagicMock()
    s.exists = True
    s.to_dict.return_value = data
    return s


class TestCreateWiringRetention:
    def test_create_sets_retention_fields(self):
        data = {
            "date": "2026-06-15", "total": 1180.0, "subtotal": 1000.0,
            "discount": 0.0, "itbis": 180.0, "supplierId": "sup-1",
        }
        inv_ref = MagicMock()
        inv_coll = MagicMock()
        inv_coll.document.return_value = inv_ref
        with patch.object(mod, "firebase_initialized", True), \
             patch.object(mod, "db_firestore", MagicMock()), \
             patch.object(SupplierInvoiceService, "validate_period"), \
             patch.object(SupplierInvoiceService, "_coll_ref", return_value=inv_coll), \
             patch("app.services.supplier_service.SupplierService.get_supplier",
                   return_value=_supplier(withholdingCategory="professional_fees")), \
             _delegating_tx():
            result = SupplierInvoiceService.create(owner_uid="u", data=data, sandbox=True, company_id="c")
        assert result["retentionIsrAmount"] == 150.0
        assert result["retentionItbisAmount"] == 180.0
        assert result["retentionIsrRule"] == "professional_fees"
        assert result["retentionIsrIr17Line"] == 2


class TestAppliedRetentionOnApproval:
    def _invoice_ref(self, data):
        ref = MagicMock()
        ref.get.return_value = _snap(data)
        return ref

    def test_partial_payment_applies_proportional_retention(self):
        inv = {
            "id": "inv-1", "status": "registrada", "cxpStatus": "Pendiente",
            "total": 1000.0, "cxpRemainingBalance": 1000.0,
            "retentionIsrAmount": 20.0, "retentionItbisAmount": 10.0,
            "retentionIsrApplied": 0.0, "retentionItbisApplied": 0.0,
        }
        inv_ref = self._invoice_ref(inv)
        pay_ref = MagicMock()
        pay_ref.get.return_value = _snap({"amount": 500.0, "approvalStatus": "pending"})
        inv_ref.collection.return_value.document.return_value = pay_ref
        with patch.object(mod, "firebase_initialized", True), \
             patch.object(mod, "db_firestore", MagicMock()), \
             patch.object(SupplierInvoiceService, "_coll_ref", return_value=MagicMock()) as coll_ref, \
             patch.object(SupplierInvoiceService, "validate_period"), \
             _delegating_tx():
            coll_ref.return_value.document.return_value = inv_ref
            ok, msg = SupplierInvoiceService.approve_payment(
                owner_uid="u", invoice_id="inv-1", payment_id="pay-1",
                sandbox=True, company_id="c",
            )
        assert ok is True
        inv_update = inv_ref.update.call_args[0][0]
        assert inv_update["retentionIsrApplied"] == 10.0  # 20 × 0.5
        assert inv_update["retentionItbisApplied"] == 5.0  # 10 × 0.5
        assert inv_update["retentionStatus"] == "partial"
        pay_updates = [c[0][0] for c in pay_ref.update.call_args_list]
        retention_pay_update = next(u for u in pay_updates if "retentionIsrApplied" in u)
        assert retention_pay_update["retentionIsrApplied"] == 10.0
        assert retention_pay_update["retentionItbisApplied"] == 5.0
