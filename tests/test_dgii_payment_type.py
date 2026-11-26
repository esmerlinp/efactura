import xml.etree.ElementTree as ET

from app.services.dgii_xml_builder import DgiiXmlBuilder


COMPANY = {
    "companyRNC": "131880681",
    "companyName": "EMPRESA TEST SRL",
    "municipality": "Santo Domingo de Guzman",
    "province": "Distrito Nacional",
}


def _invoice(**overrides):
    data = {
        "ecfType": "Crédito Fiscal (E31)",
        "encf": "E310000000001",
        "clientRNC": "101010101",
        "razonSocial": "CLIENTE TEST SRL",
        "date": "2026-11-26",
        "paymentType": "Contado",
        "paymentMethod": "Efectivo",
        "subtotal": 1000.0,
        "total": 1180.0,
        "totalITBIS": 180.0,
        "items": [{
            "name": "Servicio de prueba",
            "unit": "Servicio",
            "quantity": 1,
            "price": 1000.0,
            "subtotal": 1000.0,
            "itbisRate": 0.18,
        }],
    }
    data.update(overrides)
    return data


def _id_doc(xml_bytes):
    root = ET.fromstring(xml_bytes)
    return next(elem for elem in root.iter() if elem.tag == "IdDoc")


def test_credit_condition_controls_tipo_pago_even_with_transfer_method():
    id_doc = _id_doc(DgiiXmlBuilder.build_invoice_xml(
        COMPANY, _invoice(paymentType="Crédito", paymentMethod="Transferencia")
    ))
    assert id_doc.findtext("TipoPago") == "2"
    assert id_doc.findtext("FechaLimitePago") is None


def test_credit_condition_includes_due_date():
    id_doc = _id_doc(DgiiXmlBuilder.build_invoice_xml(
        COMPANY,
        _invoice(paymentType="02 - Crédito", paymentMethod="Efectivo", dueDate="2026-12-26"),
    ))
    assert id_doc.findtext("TipoPago") == "2"
    assert id_doc.findtext("FechaLimitePago") == "26-12-2026"


def test_cash_condition_remains_contado_with_transfer_method():
    id_doc = _id_doc(DgiiXmlBuilder.build_invoice_xml(
        COMPANY, _invoice(paymentType="Contado", paymentMethod="Transferencia")
    ))
    assert id_doc.findtext("TipoPago") == "1"


def test_numeric_credit_condition_is_supported():
    id_doc = _id_doc(DgiiXmlBuilder.build_invoice_xml(
        COMPANY, _invoice(paymentType="2", paymentMethod="Efectivo", dueDate="2026-12-26")
    ))
    assert id_doc.findtext("TipoPago") == "2"
