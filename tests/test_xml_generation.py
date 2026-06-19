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
    ns = {"cf": "http://dgii.gov.do/CF"}
    tipo_moneda = root.find(".//cf:TipoMoneda", ns)
    assert tipo_moneda is not None
    assert tipo_moneda.text == "COP"


def test_xml_emisor_province_municipality(company_profile, invoice_data):
    xml_bytes = DgiiXmlBuilder.build_invoice_xml(company_profile, invoice_data)
    xml_str = xml_bytes.decode('utf-8')
    root = ET.fromstring(xml_str)
    ns = {"cf": "http://dgii.gov.do/CF"}
    prov = root.find(".//cf:Emisor/cf:Provincia", ns)
    mun = root.find(".//cf:Emisor/cf:Municipio", ns)
    assert prov is not None and prov.text == "320000"
    assert mun is not None and mun.text == "320100"


def test_xml_receptor_omitted_for_low_consumption(company_profile, invoice_data):
    xml_bytes = DgiiXmlBuilder.build_invoice_xml(company_profile, invoice_data)
    xml_str = xml_bytes.decode('utf-8')
    root = ET.fromstring(xml_str)
    ns = {"cf": "http://dgii.gov.do/CF"}
    rnc = root.find(".//cf:Receptor/cf:RNCReceptor", ns)
    razon = root.find(".//cf:Receptor/cf:RazonSocialReceptor", ns)
    assert rnc is None
    assert razon is None


def test_xml_zero_retentions_present(company_profile, invoice_data):
    xml_bytes = DgiiXmlBuilder.build_invoice_xml(company_profile, invoice_data)
    xml_str = xml_bytes.decode('utf-8')
    root = ET.fromstring(xml_str)
    ns = {"cf": "http://dgii.gov.do/CF"}
    ret_itbis = root.find(".//cf:Totales/cf:TotalITBISRetenido", ns)
    ret_isr = root.find(".//cf:Totales/cf:TotalISRRetencion", ns)
    assert ret_itbis is not None and ret_itbis.text == "0.00"
    assert ret_isr is not None and ret_isr.text == "0.00"


def test_xml_unit_of_measure_mapping(company_profile, invoice_data):
    xml_bytes = DgiiXmlBuilder.build_invoice_xml(company_profile, invoice_data)
    xml_str = xml_bytes.decode('utf-8')
    root = ET.fromstring(xml_str)
    ns = {"cf": "http://dgii.gov.do/CF"}
    unidad = root.find(".//cf:Detalle/cf:UnidadMedida", ns)
    assert unidad is not None and unidad.text == "57"
