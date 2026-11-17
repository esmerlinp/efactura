"""Entregable 3.2 — Reporte 606 reconciliable.

Verifica el mapeo de facturas al 606 (retenciones como montos, no tasas), la
conciliación por período/proveedor/documento, y que no se adivinen tasas vs montos.
"""

from unittest.mock import patch

from app.web.reports_606 import _map_supplier_invoice, _compute_606_summary


def _invoice(**kw):
    inv = {
        "id": "inv-1", "supplierRnc": "131111111", "supplierName": "Proveedor A",
        "supplierInvoiceNumber": "F001", "ncf": "E310000000001", "ecfType": "E31",
        "total": 1180.0, "itbis": 180.0, "tipoGastoDGII": "02",
    }
    inv.update(kw)
    return inv


class TestMapSupplierInvoice:
    def test_uses_explicit_retention_amounts(self):
        m = _map_supplier_invoice(_invoice(retentionIsrAmount=20.0, retentionItbisAmount=54.0))
        assert m["isrWithheld"] == 20.0
        assert m["itbisWithheld"] == 54.0

    def test_fallback_to_legacy_amounts_without_rate_guessing(self):
        # isrWithheld=20 (monto), retainedISR=0.02 (tasa) → NO multiplica por base
        m = _map_supplier_invoice(_invoice(isrWithheld=20.0, retainedISR=0.02))
        assert m["isrWithheld"] == 20.0

    def test_professional_fees_maps_tipo_retencion(self):
        m = _map_supplier_invoice(_invoice(retentionIsrRule="professional_fees"))
        assert m["tipoRetencionISR"] == "02"

    def test_goods_services_no_tipo_retencion(self):
        m = _map_supplier_invoice(_invoice(retentionIsrRule="goods_services"))
        assert m["tipoRetencionISR"] == ""

    def test_exempt_no_retention(self):
        m = _map_supplier_invoice(_invoice(itbis=0.0, retentionItbisAmount=0.0, retentionIsrAmount=0.0))
        assert m["isrWithheld"] == 0.0
        assert m["itbisWithheld"] == 0.0

    def test_credit_note_ncf_modificado_preserved(self):
        m = _map_supplier_invoice(_invoice(ncfModificado="E310000000099"))
        assert m["ncfModificado"] == "E310000000099"

    def test_exterior_payments_abroad(self):
        m = _map_supplier_invoice(_invoice(retentionIsrAmount=270.0, retentionIsrRule="payments_abroad",
                                           retentionItbisAmount=0.0))
        assert m["isrWithheld"] == 270.0
        assert m["itbisWithheld"] == 0.0


class TestCompute606Summary:
    def test_totals_and_documents(self):
        items = [
            {"rncEmisor": "131111111", "ncf": "E310000000001", "amount": 1000.0,
             "itbisAmount": 180.0, "isrWithheld": 20.0, "itbisWithheld": 54.0},
            {"rncEmisor": "131111111", "ncf": "E310000000002", "amount": 500.0,
             "itbisAmount": 90.0, "isrWithheld": 10.0, "itbisWithheld": 0.0},
            {"rncEmisor": "131222222", "ncf": "E310000000003", "amount": 2000.0,
             "itbisAmount": 0.0, "isrWithheld": 0.0, "itbisWithheld": 0.0},
        ]
        s = _compute_606_summary(items)
        assert s["count"] == 3
        assert s["totalMonto"] == 3500.0
        assert s["totalITBIS"] == 270.0
        assert s["totalISRRetenido"] == 30.0
        assert s["totalITBISRetenido"] == 54.0
        assert s["byProvider"]["131111111"] == 1500.0
        assert s["byProvider"]["131222222"] == 2000.0
        assert len(s["documents"]) == 3


class TestMapFormaPago:
    def _inv(self, **kw):
        inv = {"paymentMethod": "", "paymentTerms": "contado"}
        inv.update(kw)
        return inv

    def test_efectivo(self):
        from app.web.reports_606 import _map_forma_pago
        assert _map_forma_pago(self._inv(paymentMethod="Efectivo")) == "01"

    def test_cheque(self):
        from app.web.reports_606 import _map_forma_pago
        assert _map_forma_pago(self._inv(paymentMethod="Cheque")) == "02"

    def test_transferencia(self):
        from app.web.reports_606 import _map_forma_pago
        assert _map_forma_pago(self._inv(paymentMethod="Transferencia")) == "02"

    def test_tarjeta(self):
        from app.web.reports_606 import _map_forma_pago
        assert _map_forma_pago(self._inv(paymentMethod="Tarjeta")) == "03"

    def test_nota_credito(self):
        from app.web.reports_606 import _map_forma_pago
        assert _map_forma_pago(self._inv(paymentMethod="Nota Crédito")) == "06"

    def test_credito_terms_wins(self):
        from app.web.reports_606 import _map_forma_pago
        assert _map_forma_pago(self._inv(paymentTerms="credito_30d", paymentMethod="Efectivo")) == "04"

    def test_default(self):
        from app.web.reports_606 import _map_forma_pago
        assert _map_forma_pago(self._inv()) == "02"
