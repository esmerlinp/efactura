import pytest
from app.services.dgii import DGIIService
from app.countries.do.dgii_client import REGIMEN_RULES


class TestDgiiRounding:
    def test_standard_rounding(self):
        assert DGIIService.dgii_round(10.456) == 10.46
        assert DGIIService.dgii_round(10.454) == 10.45
        assert DGIIService.dgii_round(10.455) == 10.46

    def test_zero_values(self):
        assert DGIIService.dgii_round(0.0) == 0.0
        assert DGIIService.dgii_round(None) == 0.0

    def test_negative_values(self):
        assert DGIIService.dgii_round(-10.456) == -10.46


class TestRncCleaner:
    def test_cleans_dashes(self):
        assert DGIIService.clean_rnc("131-23456-7") == "131234567"

    def test_cleans_spaces(self):
        assert DGIIService.clean_rnc("131 23456 7") == "131234567"

    def test_none_returns_empty(self):
        assert DGIIService.clean_rnc(None) == ""
        assert DGIIService.clean_rnc("") == ""


class TestRegimenRules:
    def test_ordinary_allows_all_ecf_types(self):
        rules = REGIMEN_RULES["ordinary"]
        assert "E31" in rules["allowed_ecf_types"]
        assert "E32" in rules["allowed_ecf_types"]
        assert "E47" in rules["allowed_ecf_types"]
        assert rules["itbis_enabled"] is True

    def test_consumer_only_e32(self):
        rules = REGIMEN_RULES["consumer"]
        assert rules["allowed_ecf_types"] == ["E32"]
        assert rules["itbis_enabled"] is True

    def test_exempt_no_itbis(self):
        rules = REGIMEN_RULES["exempt"]
        assert rules["itbis_enabled"] is False

    def test_rst_has_limit(self):
        rules = REGIMEN_RULES["rst_income"]
        assert rules["rst_limit"] is not None
        assert rules["rst_limit"] > 0


class TestCalculateInvoiceTotals:

    def test_simple_two_items(self, sample_invoice_items):
        result = DGIIService.calculate_invoice_totals(sample_invoice_items)
        assert result["subtotal"] == pytest.approx(115000.00, abs=0.01)
        assert result["total_itbis"] == pytest.approx(20700.00, abs=0.01)
        assert result["total"] == pytest.approx(135700.00, abs=0.01)
        assert len(result["items"]) == 2

    def test_with_discount(self, sample_invoice_items):
        result = DGIIService.calculate_invoice_totals(sample_invoice_items, discount_rate=0.10)
        assert result["global_discount"] == pytest.approx(11500.00, abs=0.01)
        assert result["subtotal"] == pytest.approx(103500.00, abs=0.01)
        assert result["total_itbis"] == pytest.approx(18630.00, abs=0.01)

    def test_with_retentions(self, sample_invoice_items):
        result = DGIIService.calculate_invoice_totals(
            sample_invoice_items, retained_isr_rate=0.10, retained_itbis_rate=1.0
        )
        assert result["retained_isr"] == pytest.approx(11500.00, abs=0.01)
        assert result["retained_itbis"] == pytest.approx(20700.00, abs=0.01)
        assert result["net_payable"] == pytest.approx(103500.00, abs=0.01)

    def test_item_level_discount(self):
        items = [{"price": 1000, "quantity": 2, "itbisRate": 0.18, "discountRate": 0.15}]
        result = DGIIService.calculate_invoice_totals(items)
        item = result["items"][0]
        assert item["discount_amount"] == pytest.approx(300.00, abs=0.01)
        assert item["subtotal"] == pytest.approx(1700.00, abs=0.01)

    def test_empty_items(self):
        result = DGIIService.calculate_invoice_totals([])
        assert result["subtotal"] == 0.0
        assert result["total"] == 0.0
        assert len(result["items"]) == 0

    def test_isc_alcohol(self):
        items = [{
            "price": 500.00, "quantity": 1, "itbisRate": 0.18,
            "codigoImpuesto": "012", "tasaImpuestoAdicional": 158.50,
            "gradosAlcohol": 40.0, "cantidadReferencia": 0.75, "subcantidad": 1.0,
            "precioReferencia": 0.0, "discountRate": 0.0
        }]
        result = DGIIService.calculate_invoice_totals(items)
        item = result["items"][0]
        assert item["isc_especifico_amount"] > 0

    def test_propina_legal(self):
        items = [{
            "price": 1000.00, "quantity": 1, "itbisRate": 0.18,
            "codigoImpuesto": "001", "tasaImpuestoAdicional": 0.10, "discountRate": 0.0
        }]
        result = DGIIService.calculate_invoice_totals(items)
        assert result["items"][0]["otros_impuestos_amount"] == pytest.approx(100.00, abs=0.01)

    def test_normalize_regimen_maps_legacy(self):
        assert DGIIService.normalize_regimen("General") == "ordinary"
        assert DGIIService.normalize_regimen("Simplificado") == "rst_income"
        assert DGIIService.normalize_regimen(None) == "ordinary"
        assert DGIIService.normalize_regimen("ordinary") == "ordinary"


class TestToleranciaCuadratura:

    def test_within_tolerance(self, sample_invoice_items):
        result = DGIIService.calculate_invoice_totals(sample_invoice_items)
        check = DGIIService.check_tolerancia_cuadratura(result["items"], result["total"])
        assert check["within_tolerance"] is True
        assert check["status"] == "ACCEPTED"

    def test_exceeds_line_tolerance(self):
        items = [{"quantity": 2, "price": 100, "subtotal": 500, "total": 500}]
        check = DGIIService.check_tolerancia_cuadratura(items, 500)
        assert check["within_tolerance"] is False
        assert check["status"] == "ACCEPTED_CONDITIONAL"
