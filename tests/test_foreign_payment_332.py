"""Fase 3.3.2 — Pagos al exterior (B17/E47) y categorías de retención.

Verifica la corrección de B17 a "Comprobante para Pagos al Exterior" y la nueva
categoría de retención "royalties" (regalías/derechos, 15%, IR-17 L22).
"""

from app.models.fiscal_document_type import B17, E47, Category
from app.services.tax_engine import TaxEngine
from app.services.supplier_invoice_service import SupplierInvoiceService


class TestB17Classification:
    def test_b17_is_foreign_payment_not_debit_note(self):
        assert B17.code == "B17"
        assert "Pagos al Exterior" in B17.label
        assert "Nota de Débito" not in B17.label
        assert B17.category == Category.FOREIGN_PAYMENT

    def test_e47_is_electronic_foreign_payment(self):
        assert E47.code == "E47"
        assert E47.category == Category.FOREIGN_PAYMENT
        assert "Pagos al Exterior" in E47.label


class TestRoyaltiesCategory:
    def test_royalties_isr_15_and_ir17_22(self):
        r = TaxEngine(country="DO").resolve_withholding({"withholdingCategory": "royalties"})
        assert r["isr_rate"] == 0.15
        assert r["isr_rule"] == "royalties"
        assert r["isr_ir17_line"] == 22
        assert r["itbis_rate"] == 0.0

    def test_calculate_retention_royalties(self):
        ret = SupplierInvoiceService.calculate_retention(
            {"withholdingCategory": "royalties"}, subtotal=1000.0, discount=0.0, itbis=0.0
        )
        assert ret["retentionIsrAmount"] == 150.0
        assert ret["retentionIsrRule"] == "royalties"
        assert ret["retentionIsrIr17Line"] == 22
