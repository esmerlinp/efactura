from unittest.mock import MagicMock, patch

from app.services.receptor_xml_service import ReceptorXmlService
from app.web import recepcion


VALID_XML = b'''<?xml version="1.0" encoding="utf-8"?>
<ECF xmlns="http://www.dgii.gov.do/ecf">
  <Encabezado>
    <IdDoc><TipoeCF>31</TipoeCF><eNCF>E310000000001</eNCF><TipoPago>2</TipoPago></IdDoc>
    <Emisor><RNCEmisor>132109122</RNCEmisor><RazonSocialEmisor>PROVEEDOR TEST</RazonSocialEmisor><FechaEmision>15-10-2026</FechaEmision></Emisor>
    <Comprador><RNCComprador>131880681</RNCComprador></Comprador>
    <Totales><MontoTotal>1180.00</MontoTotal><TotalITBIS>180.00</TotalITBIS></Totales>
  </Encabezado>
  <DetallesItems><Item><NumeroLinea>1</NumeroLinea><NombreItem>Servicio</NombreItem><IndicadorFacturacion>1</IndicadorFacturacion><IndicadorBienoServicio>2</IndicadorBienoServicio><CantidadItem>1</CantidadItem><PrecioUnitarioItem>1000</PrecioUnitarioItem><MontoItem>1000</MontoItem></Item></DetallesItems>
</ECF>'''


def test_validate_manual_ecf_requires_ecf_fields():
    detail, error = ReceptorXmlService.validate_manual_ecf(VALID_XML)
    assert error is None
    assert detail["encf"] == "E310000000001"
    assert detail["rnc_emisor"] == "132109122"

    detail, error = ReceptorXmlService.validate_manual_ecf(b"<Factura />")
    assert detail is None
    assert "elemento raíz ECF" in error


def test_manual_upload_saves_origin_and_signature_status():
    client = MagicMock()
    client.method = "POST"
    client.files = {"xml_file": MagicMock(filename="factura.xml", read=MagicMock(return_value=VALID_XML))}
    client.form = {}
    client.args = {}

    with patch.object(recepcion, "request", client), \
         patch.object(recepcion, "session", {"user": {"uid": "user-1"}, "sandbox": True}), \
         patch.object(recepcion, "_check_auth", return_value=None), \
         patch.object(recepcion, "_get_context", return_value=("owner-1", "company-1")), \
         patch.object(recepcion.DatabaseService, "get_company_profile", return_value={"companyRNC": "131880681"}), \
         patch.object(recepcion.ReceptorRepository, "find_received_by_encf_merged", return_value=None), \
         patch.object(recepcion.ReceptorRepository, "save_received_ecf", return_value="new-id") as save, \
         patch.object(recepcion.ReceptorXmlService, "verify_signature", return_value=(None, "El XML no contiene firma digital.")), \
         patch.object(recepcion, "flash"), \
         patch.object(recepcion, "redirect", return_value="redirected"):
        result = recepcion.upload_manual_ecf()

    assert result == "redirected"
    payload = save.call_args.args[1]
    assert payload["source"] == "manual_upload"
    assert payload["receipt_channel"] == "manual"
    assert payload["received_automatically"] is False
    assert payload["status"] == "recibido_manual"
    assert payload["signature_status"] == "missing"
    assert payload["arecf_xml"] == ""
