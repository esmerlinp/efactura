import pytest
import xml.etree.ElementTree as ET
from app.services.dgii_xml_builder import DgiiXmlBuilder


@pytest.fixture
def company_profile():
    return {
        "companyRNC": "132-10912-2",
        "companyName": "Tecnología Dominicana SRL",
        "tradeName": "TecnoDom",
        "companyAddress": "Av. Winston Churchill #1012, Santo Domingo",
        "companyPhone": "809-555-0199",
        "municipality": "Santo Domingo Este",
        "province": "Santo Domingo"
    }


@pytest.fixture
def invoice_data():
    return {
        "ecfType": "Factura de Consumo (E32)",
        "encf": "E320000000005",
        "currency": "COP",
        "paymentMethod": "Crédito",
        "clientRNC": "",
        "clientName": "",
        "clientMunicipality": "Cabral",
        "clientProvince": "Barahona",
        "subtotal": 1500.00,
        "discountRate": 0.0,
        "totalITBIS": 270.00,
        "retainedITBIS": 0.00,
        "retainedISR": 0.00,
        "total": 1770.00,
        "items": [
            {
                "code": "ART-001",
                "name": "Bandeja de Bocadillos",
                "unit": "Bandeja",
                "quantity": 2.0,
                "price": 750.00,
                "subtotal": 1500.00,
                "itbisRate": 0.18,
                "itbis_amount": 270.00,
                "type": "Bien"
            }
        ]
    }


def test_xml_syntax_valid(company_profile, invoice_data):
    xml_bytes = DgiiXmlBuilder.build_invoice_xml(company_profile, invoice_data)
    xml_str = xml_bytes.decode('utf-8')
    root = ET.fromstring(xml_str)
    assert root is not None


def test_xml_currency_mapping(company_profile, invoice_data):
    xml_bytes = DgiiXmlBuilder.build_invoice_xml(company_profile, invoice_data)
    xml_str = xml_bytes.decode('utf-8')
    root = ET.fromstring(xml_str)
    tipo_moneda = root.find(".//TipoMoneda")
    assert tipo_moneda is not None
    assert tipo_moneda.text == "COP"


def test_xml_emisor_province_municipality(company_profile, invoice_data):
    xml_bytes = DgiiXmlBuilder.build_invoice_xml(company_profile, invoice_data)
    xml_str = xml_bytes.decode('utf-8')
    root = ET.fromstring(xml_str)
    prov = root.find(".//Emisor/Provincia")
    mun = root.find(".//Emisor/Municipio")
    assert prov is not None and prov.text == "320000"
    assert mun is not None and mun.text == "320100"


def test_xml_receptor_omitted_for_low_consumption(company_profile, invoice_data):
    xml_bytes = DgiiXmlBuilder.build_invoice_xml(company_profile, invoice_data)
    xml_str = xml_bytes.decode('utf-8')
    root = ET.fromstring(xml_str)
    rnc = root.find(".//Receptor/RNCReceptor")
    razon = root.find(".//Receptor/RazonSocialReceptor")
    assert rnc is None
    assert razon is None


def test_xml_zero_retentions_omitted(company_profile, invoice_data):
    e41_data = dict(invoice_data, ecfType="Factura de Compras (E41)", encf="E410000000001")
    xml_bytes = DgiiXmlBuilder.build_invoice_xml(company_profile, e41_data)
    xml_str = xml_bytes.decode('utf-8')
    root = ET.fromstring(xml_str)
    ret_itbis = root.find(".//Totales/TotalITBISRetenido")
    ret_isr = root.find(".//Totales/TotalISRRetencion")
    # Campos opcionales: con retención 0 se omiten (no "0.00").
    assert ret_itbis is None
    assert ret_isr is None


def test_xml_unit_of_measure_mapping(company_profile, invoice_data):
    xml_bytes = DgiiXmlBuilder.build_invoice_xml(company_profile, invoice_data)
    xml_str = xml_bytes.decode('utf-8')
    root = ET.fromstring(xml_str)
    unidad = root.find(".//UnidadMedida")
    assert unidad is not None and unidad.text == "57"


def test_xml_includes_exempt_lines_in_totals(company_profile):
    data = {
        "ecfType": "Factura de Consumo (E32)",
        "encf": "E320000000192",
        "paymentMethod": "Efectivo",
        "subtotal": 15275.00,
        "totalITBIS": 2700.00,
        "total": 17975.00,
        "items": [
            {
                "name": "Arroz Selecto 5 lb",
                "quantity": 1,
                "price": 275.00,
                "subtotal": 275.00,
                "itbisRate": 0.0,
            },
            {
                "name": "ASESORIA LEGAL",
                "quantity": 1,
                "price": 15000.00,
                "subtotal": 15000.00,
                "itbisRate": 0.18,
            },
        ],
    }

    root = ET.fromstring(DgiiXmlBuilder.build_invoice_xml(company_profile, data))
    totales = root.find(".//Totales")
    assert totales.findtext("MontoExento") == "275.00"
    assert totales.findtext("MontoGravadoI1") == "15000.00"
    assert totales.findtext("MontoTotal") == "17975.00"


def test_validate_totals_rejects_stale_exempt_amount(company_profile):
    data = {
        "items": [{"price": 275, "quantity": 1, "itbisRate": 0.0}],
        "montoExento": 0.0,
    }
    with pytest.raises(ValueError, match="MontoExento informado 0.00"):
        DgiiXmlBuilder.validate_totals(data)


def test_rfce_summary_does_not_include_payment_collection_fields(company_profile):
    data = {
        "encf": "E320000000193",
        "paymentMethod": "Efectivo",
        "total": 4405.00,
        "totalITBIS": 630.00,
        "items": [
            {"name": "Arroz", "quantity": 1, "price": 275.00, "subtotal": 275.00, "itbisRate": 0.0},
            {"name": "Servicio", "quantity": 1, "price": 3500.00, "subtotal": 3500.00, "itbisRate": 0.18},
        ],
    }
    root = ET.fromstring(DgiiXmlBuilder.build_rfce_summary_xml(company_profile, data, "ABC123"))
    id_doc = root.find(".//IdDoc")
    assert id_doc.findtext("TipoPago") == "1"
    assert id_doc.find("TablaFormasPago") is None
