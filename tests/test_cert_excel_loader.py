"""
Regresión — Loader del set de pruebas DGII (Excel) y comprador en E32/RFCE.

La DGII compara cada comprobante contra su conjunto de datos (el Excel).
Los valores del Comprador deben copiarse EXACTAMENTE de la fila del Excel:
  - E32 (cualquier monto) y RFCE: RNCComprador=131880681 presente.
  - E43/E47 (sin RNCComprador en el Excel): no debe aparecer RNCComprador.

Motivo: en una versión intermedia se limpió el comprador de E32<250K/RFCE y
la DGII rechazó con "el valor enviado () no coincide con el valor (131880681)
del conjunto de datos entregados".
"""
import sys
import os
from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.dgii_test_data_loader import DgiiTestDataLoader

DS_NS = "{http://www.w3.org/2000/09/xmldsig#}"


def _sanitized_schema(path):
    x = open(path, encoding="utf-8").read()
    x = x.replace("[$0-9]", "[0-9]").replace("(?:", "(")
    return etree.XMLSchema(etree.fromstring(x.encode()))


def _mk_row(**fields):
    letters = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
               "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"]
    headers = {}
    row_dict = {}
    for i, (name, val) in enumerate(fields.items()):
        col = letters[i]
        headers[col] = name
        row_dict[col] = val
    return row_dict, headers


def _e32_row(total, rnc_comprador="131880681"):
    return _mk_row(
        TipoeCF="32",
        ENCF="E320000000011",
        IndicadorMontoGravado="0",
        TipoIngresos="01",
        TipoPago="1",
        RNCEmisor="133753652",
        RazonSocialEmisor="EMISOR PRUEBA SRL",
        DireccionEmisor="CALLE PRUEBA 123",
        FechaEmision="01-04-2020",
        MontoGravadoTotal="34000.00",
        MontoGravadoI1="34000.00",
        ITBIS1="18",
        TotalITBIS="6120.00",
        TotalITBIS1="6120.00",
        MontoTotal=total,
        RNCComprador=rnc_comprador,
        RazonSocialComprador="DOCUMENTOS ELECTRONICOS DE 03",
        **{
            "NumeroLinea[1]": "1",
            "IndicadorFacturacion[1]": "1",
            "NombreItem[1]": "Producto prueba",
            "IndicadorBienoServicio[1]": "1",
            "CantidadItem[1]": "1",
            "UnidadMedida[1]": "55",
            "PrecioUnitarioItem[1]": "34000.00",
            "MontoItem[1]": "34000.00",
        },
    )


def _rfce_row():
    return _mk_row(
        TipoeCF="32",
        ENCF="E320000000011",
        TipoIngresos="01",
        TipoPago="1",
        RNCEmisor="133753652",
        RazonSocialEmisor="EMISOR PRUEBA SRL",
        FechaEmision="01-04-2020",
        MontoGravadoTotal="34000.00",
        MontoGravadoI1="34000.00",
        TotalITBIS="6120.00",
        TotalITBIS1="6120.00",
        MontoTotal="40120.00",
        RNCComprador="131880681",
        RazonSocialComprador="DOCUMENTOS ELECTRONICOS DE 03",
    )


def _comprador_children(doc):
    comp = doc.find("Encabezado/Comprador")
    return [] if comp is None else list(comp)


def test_e32_menor_250k_conserva_comprador_del_excel():
    row_dict, headers = _e32_row("40120.00")
    raw = DgiiTestDataLoader.build_xml_from_row(row_dict, headers)
    doc = etree.fromstring(raw)
    rnc = doc.findtext("Encabezado/Comprador/RNCComprador")
    rz = doc.findtext("Encabezado/Comprador/RazonSocialComprador")
    assert rnc == "131880681"
    assert rz == "DOCUMENTOS ELECTRONICOS DE 03"


def test_e32_mayor_250k_conserva_rnc_comprador():
    row_dict, headers = _e32_row("413785.30")
    raw = DgiiTestDataLoader.build_xml_from_row(row_dict, headers)
    doc = etree.fromstring(raw)
    rnc = doc.findtext("Encabezado/Comprador/RNCComprador")
    assert rnc == "131880681"


def test_rfce_conserva_comprador_del_excel():
    row_dict, headers = _rfce_row()
    raw = DgiiTestDataLoader.build_rfce_xml_from_row(row_dict, headers, codigo_seguridad="ABC123")
    doc = etree.fromstring(raw)
    rnc = doc.findtext("Encabezado/Comprador/RNCComprador")
    rz = doc.findtext("Encabezado/Comprador/RazonSocialComprador")
    assert rnc == "131880681"
    assert rz == "DOCUMENTOS ELECTRONICOS DE 03"


def test_e43_sin_comprador_cuando_el_excel_lo_trae_vacio():
    row_dict, headers = _mk_row(
        TipoeCF="43",
        ENCF="E430000000001",
        MontoTotal="700.00",
        RNCEmisor="133753652",
    )
    raw = DgiiTestDataLoader.build_xml_from_row(row_dict, headers)
    doc = etree.fromstring(raw)
    assert _comprador_children(doc) == []


def test_e43_xsd_valido_sin_comprador():
    # Regresión: una versión intermedia emitía <Comprador/> en E43 y la DGII
    # lo rechazaba con "El formato del XML no es válido. en el grupo 1".
    row_dict, headers = _mk_row(
        TipoeCF="43",
        ENCF="E430000000001",
        FechaVencimientoSecuencia="31-12-2028",
        RNCEmisor="133753652",
        RazonSocialEmisor="EMISOR PRUEBA SRL",
        DireccionEmisor="CALLE PRUEBA 123",
        FechaEmision="01-04-2020",
        MontoExento="700.00",
        MontoTotal="700.00",
        **{
            "NumeroLinea[1]": "1",
            "IndicadorFacturacion[1]": "1",
            "NombreItem[1]": "Producto prueba",
            "IndicadorBienoServicio[1]": "1",
            "CantidadItem[1]": "1",
            "PrecioUnitarioItem[1]": "700.00",
            "MontoItem[1]": "700.00",
        },
    )
    raw = DgiiTestDataLoader.build_xml_from_row(row_dict, headers)
    doc = etree.fromstring(raw)
    assert doc.find("Encabezado/Comprador") is None
    etree.SubElement(doc, f"{DS_NS}Signature")
    schema = _sanitized_schema(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Schemas", "e-CF 43 v1.0.xsd")
    )
    assert schema.validate(doc), [str(e) for e in schema.error_log[:3]]


def test_e47_con_identificador_extranjero_y_sin_rnc():
    row_dict, headers = _mk_row(
        TipoeCF="47",
        ENCF="E470000000009",
        MontoTotal="66000.00",
        RNCEmisor="133753652",
        IdentificadorExtranjero="350555123",
        RazonSocialComprador="DOCUMENTOS ELECTRONICOS DE 03",
    )
    raw = DgiiTestDataLoader.build_xml_from_row(row_dict, headers)
    doc = etree.fromstring(raw)
    assert doc.findtext("Encabezado/Comprador/RNCComprador") is None
    assert doc.findtext("Encabezado/Comprador/IdentificadorExtranjero") == "350555123"


def test_e32_menor_250k_xsd_valido_con_comprador():
    row_dict, headers = _e32_row("40120.00")
    raw = DgiiTestDataLoader.build_xml_from_row(row_dict, headers)
    doc = etree.fromstring(raw)
    etree.SubElement(doc, f"{DS_NS}Signature")
    schema = _sanitized_schema(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Schemas", "e-CF 32 v1.0.xsd")
    )
    assert schema.validate(doc), [str(e) for e in schema.error_log[:3]]


def test_rfce_xsd_valido_con_comprador():
    row_dict, headers = _rfce_row()
    raw = DgiiTestDataLoader.build_rfce_xml_from_row(row_dict, headers, codigo_seguridad="ABC123")
    doc = etree.fromstring(raw)
    etree.SubElement(doc, f"{DS_NS}Signature")
    schema = _sanitized_schema(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Schemas", "RFCE 32 v.1.0.xsd")
    )
    assert schema.validate(doc), [str(e) for e in schema.error_log[:3]]


def _signed_with_signature(raw_bytes):
    doc = etree.fromstring(raw_bytes)
    etree.SubElement(doc, f"{DS_NS}Signature")
    return etree.tostring(doc, encoding="utf-8")


def test_cached_e32_matches_mismo_contenido_ignora_fecha_firma():
    from app.services.dgii_cert_service import DgiiCertService

    row_dict, headers = _e32_row("40120.00")
    raw1 = DgiiTestDataLoader.build_xml_from_row(row_dict, headers)
    cached = _signed_with_signature(raw1)

    doc = etree.fromstring(raw1)
    doc.find("FechaHoraFirma").text = "12-08-2026 23:59:59"
    raw2 = etree.tostring(doc, encoding="utf-8")

    assert DgiiCertService._cached_e32_matches(cached, raw2) is True


def test_cached_e32_matches_detecta_contenido_diferente():
    from app.services.dgii_cert_service import DgiiCertService

    row_dict, headers = _e32_row("40120.00")
    raw1 = DgiiTestDataLoader.build_xml_from_row(row_dict, headers)
    cached = _signed_with_signature(raw1)

    # Código viejo que emitía <Comprador/> vacío en lugar del comprador del Excel
    doc = etree.fromstring(raw1)
    comp = doc.find("Encabezado/Comprador")
    for child in list(comp):
        comp.remove(child)
    raw2 = etree.tostring(doc, encoding="utf-8")

    assert DgiiCertService._cached_e32_matches(cached, raw2) is False
