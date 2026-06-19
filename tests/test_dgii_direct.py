import json
from unittest.mock import patch, MagicMock

import pytest

from config import Config
from app.services.dgii import DGIIService


@pytest.fixture
def company_profile():
    return {
        "companyRNC": "132-10912-2",
        "companyName": "Tecnología Dominicana SRL",
        "tradeName": "TecnoDom",
        "companyAddress": "Av. Winston Churchill #1012, Santo Domingo",
        "companyPhone": "809-555-0199",
        "companyEmail": "facturacion@tecnodom.com.do",
        "municipality": "Santo Domingo Este",
        "province": "Santo Domingo",
        "regimenFiscal": "ordinary",
        "certificateContent": "",
        "certificatePassword": "",
    }


@pytest.fixture
def invoice_dict():
    items = [
        {"price": 50000.00, "quantity": 2, "itbisRate": 0.18, "discountRate": 0.0,
         "codigoImpuesto": "", "tasaImpuestoAdicional": 0.0, "gradosAlcohol": 0.0,
         "cantidadReferencia": 0.0, "subcantidad": 1.0, "precioReferencia": 0.0,
         "id": "1", "code": "LAP-001", "name": "Laptop", "type": "Bien", "unit": "Unidad"},
        {"price": 15000.00, "quantity": 1, "itbisRate": 0.18, "discountRate": 0.0,
         "codigoImpuesto": "", "tasaImpuestoAdicional": 0.0, "gradosAlcohol": 0.0,
         "cantidadReferencia": 0.0, "subcantidad": 1.0, "precioReferencia": 0.0,
         "id": "2", "code": "SRV-001", "name": "Servicio", "type": "Servicio", "unit": "Unidad"},
    ]
    calcs = DGIIService.calculate_invoice_totals(items)
    return {
        "ecfType": "Factura de Consumo (E32)",
        "clientRNC": "999999999",
        "clientName": "Consumidor Final",
        "currency": "DOP",
        "paymentMethod": "Efectivo",
        "subtotal": calcs["subtotal"],
        "totalITBIS": calcs["total_itbis"],
        "total": calcs["total"],
        "retainedISR": calcs["retained_isr"],
        "retainedITBIS": calcs["retained_itbis"],
        "netPayable": calcs["net_payable"],
        "discountRate": 0.0,
        "items": calcs["items"],
    }


class TestDgiiDirectSimulation:

    def test_simulate_emit(self, company_profile, invoice_dict):
        with patch.object(Config, 'DGII_RECEPCION_URL_SANDBOX', ''):
            from app.services.dgii_direct import DgiiDirectService
            result = DgiiDirectService.emit_direct(company_profile, invoice_dict, sandbox=True)
        assert result["success"] is True
        assert result["mode"] == "FALLBACK"
        assert result["encf"] is not None
        assert "qrCodeURL" in result
        assert result["status"] == "PENDING"

    def test_simulate_emit_with_encf(self, company_profile, invoice_dict):
        with patch.object(Config, 'DGII_RECEPCION_URL_SANDBOX', ''):
            invoice_dict["encf"] = "E320000000099"
            from app.services.dgii_direct import DgiiDirectService
            result = DgiiDirectService.emit_direct(company_profile, invoice_dict, sandbox=True)
        assert result["success"] is True

    def test_check_dgii_status_online(self, company_profile):
        from app.services.dgii_direct import DgiiDirectService
        result = DgiiDirectService.check_dgii_status(company_profile, sandbox=True)
        assert result["success"] is True
        assert result["status"] == "ONLINE"

    def test_cancel_direct_simulated(self, company_profile):
        with patch.object(Config, 'DGII_CANCEL_URL_SANDBOX', ''):
            from app.services.dgii_direct import DgiiDirectService
            canc_dict = {
                "series": "E32",
                "startSequence": 1,
                "endSequence": 1,
                "reason": "Test cancellation"
            }
            result = DgiiDirectService.cancel_direct(company_profile, canc_dict, sandbox=True)
        assert result["success"] is True
        assert "cancellationCode" in result


class TestDgiiDirectXmlIntegration:

    def test_xml_generated_and_signed(self, company_profile, invoice_dict):
        with patch.object(Config, 'DGII_RECEPCION_URL_SANDBOX', ''):
            from app.services.dgii_direct import DgiiDirectService
            result = DgiiDirectService.emit_direct(company_profile, invoice_dict, sandbox=True)
        assert result["xmlSignature"] is not None
        assert len(result["xmlSignature"]) > 0

    def test_xml_contains_encf(self, company_profile, invoice_dict):
        with patch.object(Config, 'DGII_RECEPCION_URL_SANDBOX', ''):
            from app.services.dgii_direct import DgiiDirectService
            result = DgiiDirectService.emit_direct(company_profile, invoice_dict, sandbox=True)
        assert result["encf"] is not None
        assert result["encf"].startswith("E")


class TestDgiiDirectCheckStatus:

    def test_check_status_simulated(self, company_profile):
        with patch.object(Config, 'DGII_STATUS_URL_SANDBOX', ''):
            from app.services.dgii_direct import DgiiDirectService
            result = DgiiDirectService.check_status(company_profile, "fake-track-id-123", sandbox=True)
        assert result["success"] is True
        assert result["dgiiStatus"] is not None


class TestDgiiGetEcfTypeShortCode:
    """Verify the replacement utility works identically to the old AlanubeService method."""

    def test_ecf_type_mapping(self):
        from app.utils.ecf_utils import get_ecf_type_short_code
        assert get_ecf_type_short_code("Factura de Credito Fiscal (E31)") == "E31"
        assert get_ecf_type_short_code("Factura de Consumo (E32)") == "E32"
        assert get_ecf_type_short_code("Nota de Debito (E33)") == "E33"
