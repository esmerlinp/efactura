from decimal import Decimal
import xml.etree.ElementTree as ET

import pytest

from app.services.dgii_xml_builder import DgiiXmlBuilder
from app.services.ecf_emission import EcfEmissionService
from app.utils.e32_rules import (
    E32_BUYER_IDENTIFICATION_THRESHOLD,
    e32_is_rfce,
    e32_requires_buyer_identification,
    has_valid_e32_buyer_identifier,
)


def test_e32_threshold_matrix():
    cases = [
        (Decimal("100"), "", False),
        (Decimal("100"), "123456789", False),
        (Decimal("249999.99"), "", False),
        (Decimal("249999.99"), "123456789", False),
        (Decimal("250000.00"), "", True),
        (Decimal("250000.00"), "123456789", True),
        (Decimal("300000.00"), "", True),
        (Decimal("300000.00"), "123456789", True),
    ]
    for total, identifier, required in cases:
        assert e32_requires_buyer_identification(total) is required
        if required:
            assert has_valid_e32_buyer_identifier(identifier) is (identifier != "")


@pytest.mark.parametrize("identifier", ["123456789", "00112345678"])
def test_rnc_and_cedula_are_valid_buyer_identifiers(identifier):
    assert has_valid_e32_buyer_identifier(identifier)


def test_foreign_identifier_is_not_used_as_rnc_for_e32():
    assert not has_valid_e32_buyer_identifier("AB-12345")


def test_boundary_selects_direct_e32(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.services.ecf_emission.DgiiDirectService.emit_direct",
        lambda *args, **kwargs: calls.append("direct") or {"success": True},
    )
    monkeypatch.setattr(
        "app.services.ecf_emission.DgiiDirectService.emit_rfce",
        lambda *args, **kwargs: calls.append("rfce") or {"success": True},
    )
    monkeypatch.setattr("app.services.ecf_emission.DgiiXmlBuilder._calculate_exento", lambda _: 0.0)
    monkeypatch.setattr("app.services.ecf_emission.DgiiXmlBuilder.validate_totals", lambda _: None)
    company = {}
    base = {"ecfType": "Factura de Consumo (E32)", "items": [], "clientRNC": "123456789"}
    EcfEmissionService.emit_electronic_comprobante(company, {**base, "total": 249999.99})
    EcfEmissionService.emit_electronic_comprobante(company, {**base, "total": 250000.00})
    assert calls == ["rfce", "direct"]


def test_boundary_requires_buyer_at_250k(monkeypatch):
    monkeypatch.setattr("app.services.ecf_emission.DgiiXmlBuilder._calculate_exento", lambda _: 0.0)
    monkeypatch.setattr("app.services.ecf_emission.DgiiXmlBuilder.validate_totals", lambda _: None)
    with pytest.raises(ValueError, match="250,000"):
        EcfEmissionService.emit_electronic_comprobante(
            {}, {"ecfType": "Factura de Consumo (E32)", "total": E32_BUYER_IDENTIFICATION_THRESHOLD, "clientRNC": ""}
        )


def test_xml_preserves_voluntary_buyer():
    company = {
        "companyRNC": "132109122", "companyName": "Empresa", "companyAddress": "Direccion",
        "municipality": "Santo Domingo Este", "province": "Santo Domingo",
    }
    data = {
        "ecfType": "Factura de Consumo (E32)", "encf": "E320000000001",
        "clientRNC": "123456789", "clientName": "Cliente voluntario", "total": 100.00,
        "items": [{"name": "Producto", "quantity": 1, "price": 100, "subtotal": 100, "itbisRate": 0}],
    }
    root = ET.fromstring(DgiiXmlBuilder.build_invoice_xml(company, data))
    assert root.findtext(".//Comprador/RNCComprador") == "123456789"
    assert root.findtext(".//Comprador/RazonSocialComprador") == "Cliente voluntario"


def test_rfce_rule_remains_strictly_below_threshold():
    assert e32_is_rfce(Decimal("249999.99"))
    assert not e32_is_rfce(Decimal("250000.00"))
