"""
Regresión — Set automático del paso 4 de certificación (25 comprobantes).

Valida:
  1. Estructura del set: 11 bloques en el orden DGII, 25 comprobantes en total.
  2. Montos: E32 ≥250K efectivamente ≥ RD$250,000 y E32 RFCE < RD$250,000.
  3. Payloads E41/E43/E47 (gastos / proveedor extranjero) mapean al formato
     invoice_dict que consumen DgiiXmlBuilder/EcfEmissionService.
  4. El XML de cada tipo se genera con DgiiXmlBuilder real (detección de tipo,
     Comprador/IdentificadorExtranjero, InformacionReferencia en E33/E34).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.dgii_cert_service import DgiiCertService, RFCE_THRESHOLD
from app.services.dgii_xml_builder import DgiiXmlBuilder
from app.services.dgii import DGIIService

PROFILE = {
    "companyRNC": "131880681",
    "companyName": "EMPRESA CERTIFICACION SRL",
    "tradeName": "CERT SRL",
    "companyAddress": "Av. Certificacion 123, Santo Domingo",
    "municipality": "Santo Domingo",
    "province": "Distrito Nacional",
    "companyPhone": "809-555-0000",
    "companyEmail": "cert@test.do",
}


def _tipo(raw_xml):
    return DgiiXmlBuilder._detect_tipo_ecf(raw_xml)


def test_set_template_blocks():
    blocks = DgiiCertService.STEP4_SET_TEMPLATE
    assert len(blocks) == 11
    total = sum(b["count"] for b in blocks)
    assert total == 25
    order = [b["tipo"] for b in blocks]
    assert order[:5] == ["E31", "E32", "E33", "E34", "E41"]
    assert order[5:10] == ["E43", "E44", "E45", "E46", "E47"]
    assert blocks[-1]["tipo"] == "E32" and blocks[-1].get("rfce") is True
    assert blocks[-1]["count"] == 4
    assert blocks[0]["count"] == 4 and blocks[1]["count"] == 2
    assert blocks[2]["count"] == 1 and blocks[3]["count"] == 2


def test_e32_amounts_ge_and_rfce():
    ge_block = DgiiCertService.STEP4_SET_TEMPLATE[1]
    for i in range(ge_block["count"]):
        price = DgiiCertService._step4_price(ge_block, i)
        calcs = DGIIService.calculate_invoice_totals([
            {"price": price, "quantity": 1, "itbisRate": 0.18, "discountRate": 0.0, "name": "x"}
        ])
        assert calcs["total"] >= 250000.00, f"E32 #{i} total {calcs['total']} < 250K"

    rfce_block = DgiiCertService.STEP4_SET_TEMPLATE[-1]
    for i in range(rfce_block["count"]):
        price = DgiiCertService._step4_price(rfce_block, i)
        calcs = DGIIService.calculate_invoice_totals([
            {"price": price, "quantity": 1, "itbisRate": 0.18, "discountRate": 0.0, "name": "x"}
        ])
        assert calcs["total"] < RFCE_THRESHOLD, f"RFCE #{i} total {calcs['total']} >= 250K"


def test_expense_payload_mapping():
    exp = {
        "id": "exp-1",
        "ecfType": "E41",
        "encf": "E410000000001",
        "amount": 17700.0,
        "itbisAmount": 2700.0,
        "date": "2026-08-16",
        "dueDate": "2026-09-15",
        "providerName": "PROVEEDOR FORMAL CERT SRL",
        "rncEmisor": "131880681",
        "paymentType": "Contado",
        "concept": "Compra certificación",
        "notes": "Set",
    }
    payload = DgiiCertService._step4_build_payload(exp, "expense")
    assert payload["ecfType"] == "Comprobante de Compras (E41)"
    assert payload["total"] == 17700.0
    assert payload["subtotal"] == 15000.0
    assert payload["totalITBIS"] == 2700.0
    assert payload["items"][0]["name"] == "Compra certificación"
    assert payload["items"][0]["itbisRate"] == 0.18

    exp43 = dict(exp, ecfType="E43", amount=8000.0, itbisAmount=0.0, rncEmisor="")
    payload43 = DgiiCertService._step4_build_payload(exp43, "expense")
    assert payload43["ecfType"] == "Comprobante para Gastos Menores (E43)"
    assert payload43["items"][0]["itbisRate"] == 0.0


def test_supplier_invoice_payload_mapping():
    sinv = {
        "id": "sinv-1",
        "ecfType": "E47",
        "encf": "E470000000001",
        "supplierName": "FOREIGN SERVICES INC",
        "supplierRnc": "350555123",
        "total": 10000.0,
        "itbis": 0.0,
        "subtotal": 10000.0,
        "date": "2026-08-16",
        "dueDate": "2026-09-15",
        "paymentType": "Contado",
        "retainedISR": 0.27,
        "items": [{"name": "Servicio exterior", "unitPrice": 10000.0, "quantity": 1, "subtotal": 10000.0, "itbisRate": 0.0}],
    }
    payload = DgiiCertService._step4_build_payload(sinv, "supplier_invoice")
    assert payload["ecfType"] == "Pagos al Exterior (E47)"
    assert payload["clientRNC"] == "350555123"
    assert payload["items"][0]["retainedISR"] == 2700.0
    raw = DgiiXmlBuilder.build_invoice_xml(PROFILE, payload)
    xml_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    assert "IdentificadorExtranjero" in xml_str
    assert "350555123" in xml_str


def test_xml_build_for_all_kinds():
    kinds = [
        ("invoice", "E31", "Factura de Crédito Fiscal (E31)", "131880681", "RNCComprador"),
        ("invoice", "E32", "Factura de Consumo (E32)", "131880681", "RNCComprador"),
        ("nota", "E33", "Nota de Débito (E33)", "131880681", "NCFModificado"),
        ("nota", "E34", "Nota de Crédito (E34)", "131880681", "NCFModificado"),
        ("invoice", "E44", "Comprobante de Regímenes Especiales (E44)", "131880681", "RNCComprador"),
        ("invoice", "E45", "Comprobante Gubernamental (E45)", "131880681", "RNCComprador"),
        ("invoice", "E46", "Comprobante de Exportación (E46)", "", "RNCComprador"),
    ]
    for kind, tipo, label, rnc, expected_tag in kinds:
        payload = {
            "id": f"{tipo}-1",
            "ecfType": label,
            "encf": f"E{tipo[1:]}0000000001",
            "date": "2026-08-16",
            "clientName": "CERTIFICACION DGII SRL",
            "clientRNC": rnc,
            "paymentType": "Contado",
            "paymentMethod": "Efectivo",
            "subtotal": 1000.0,
            "totalITBIS": 180.0,
            "total": 1180.0,
            "netPayable": 1180.0,
            "items": [{
                "name": "Servicio certificación",
                "price": 1000.0,
                "quantity": 1,
                "itbisRate": 0.18,
                "discountRate": 0.0,
                "subtotal": 1000.0,
                "subtotal_raw": 1000.0,
                "discount_amount": 0.0,
                "itbis_amount": 180.0,
                "total": 1180.0,
            }],
        }
        if tipo == "E46":
            payload["identificadorExtranjero"] = "US123456789"
            payload["foreignTaxId"] = "US123456789"
            payload["clientCountry"] = "US"
        if kind == "nota":
            payload["informationReference"] = {
                "modificationCode": 1 if tipo == "E33" else 2,
                "ncfModified": "E310000000001",
                "ncfModifiedDate": "2026-08-16",
                "reasonForModification": "Prueba",
            }
        raw = DgiiXmlBuilder.build_invoice_xml(PROFILE, payload)
        xml_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        assert expected_tag in xml_str, f"{tipo}: falta {expected_tag}"
        if tipo == "E43":
            pass

    exp_payload = DgiiCertService._step4_build_payload({
        "id": "e1", "ecfType": "E43", "encf": "E430000000001",
        "amount": 8000.0, "itbisAmount": 0.0, "date": "2026-08-16",
        "providerName": "PROVEEDOR INFORMAL", "rncEmisor": "",
        "concept": "Gasto menor certificación",
    }, "expense")
    raw43 = DgiiXmlBuilder.build_invoice_xml(PROFILE, exp_payload)
    xml43 = raw43.decode("utf-8") if isinstance(raw43, bytes) else str(raw43)
    assert "E430000000001" in xml43


def test_e46_identificador_extranjero_sin_rnc_propio():
    """Sin RNC en el perfil, E46 emite IdentificadorExtranjero (regla DGII de exclusión mutua)."""
    profile = {"companyRNC": "", "companyName": "EMPRESA CERT SRL"}
    payload = {
        "id": "E46-2", "ecfType": "Comprobante de Exportación (E46)",
        "encf": "E460000000002", "date": "2026-08-16",
        "clientName": "EXPORT CUSTOMER LLC", "clientRNC": "",
        "identificadorExtranjero": "US123456789", "foreignTaxId": "US123456789",
        "clientCountry": "US",
        "paymentType": "Contado", "paymentMethod": "Efectivo",
        "subtotal": 1000.0, "totalITBIS": 0.0, "total": 1000.0, "netPayable": 1000.0,
        "items": [{
            "name": "Exportación certificación", "price": 1000.0, "quantity": 1,
            "itbisRate": 0.0, "discountRate": 0.0,
            "subtotal": 1000.0, "subtotal_raw": 1000.0, "discount_amount": 0.0,
            "itbis_amount": 0.0, "total": 1000.0,
        }],
    }
    raw = DgiiXmlBuilder.build_invoice_xml(profile, payload)
    xml_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    assert "IdentificadorExtranjero" in xml_str
    assert "US123456789" in xml_str


def test_expense_and_supplier_artifacts_via_services():
    """Los payloads pasan por el mismo builder real que usa el flujo manual."""
    exp_payload = DgiiCertService._step4_build_payload({
        "id": "e2", "ecfType": "E41", "encf": "E410000000001",
        "amount": 17700.0, "itbisAmount": 2700.0, "date": "2026-08-16",
        "providerName": "PROVEEDOR FORMAL CERT SRL", "rncEmisor": "131880681",
        "concept": "Compra certificación",
    }, "expense")
    raw41 = DgiiXmlBuilder.build_invoice_xml(PROFILE, exp_payload)
    xml41 = raw41.decode("utf-8") if isinstance(raw41, bytes) else str(raw41)
    assert "<TipoeCF>41</TipoeCF>" in xml41


def test_generate_set_docs_have_required_fields():
    """El set crea 25 documentos con los campos que exigen save_invoice / sus listas.
    Regresión: KeyError('dueDate') en E32 por omitir dueDate."""
    from unittest.mock import patch

    saved_invoices = []
    saved_expenses = []
    saved_supplier = []
    seq_counter = {}

    def fake_consume(owner_uid, tipo, email, sandbox=True, company_id=None):
        seq_counter[tipo] = seq_counter.get(tipo, 0) + 1
        return f"{tipo}{seq_counter[tipo]:010d}", "log-1"

    def fake_save_invoice(owner_uid, inv_id, inv_dict, sandbox=True, company_id=None):
        saved_invoices.append(dict(inv_dict))
        return inv_dict

    def fake_save_expense(owner_uid, exp_id, exp_dict, sandbox=True, company_id=None):
        saved_expenses.append(dict(exp_dict))
        return exp_dict

    def fake_supplier_create(owner_uid=None, data=None, sandbox=True, company_id=None):
        data["id"] = f"sinv-{len(saved_supplier)}"
        saved_supplier.append(dict(data))
        return data

    def fake_load(owner_uid, case, sandbox=True, company_id=None):
        return {"encf": case.get("encf"), "total": case.get("total", 1), "items": []}

    with patch.object(DgiiCertService, "ensure_cert_sequences", return_value={"created": [], "existing": []}), \
         patch.object(DgiiCertService, "_get_firestore_doc", return_value={}), \
         patch.object(DgiiCertService, "save_run_progress", return_value=None), \
         patch("app.services.dgii_cert_service.DatabaseService.consume_next_sequence", side_effect=fake_consume), \
         patch("app.services.dgii_cert_service.DatabaseService.save_invoice", side_effect=fake_save_invoice), \
         patch("app.services.dgii_cert_service.DatabaseService.save_expense", side_effect=fake_save_expense), \
         patch("app.services.dgii_cert_service.SupplierInvoiceService.create", side_effect=fake_supplier_create), \
         patch.object(DgiiCertService, "_load_step4_payload", side_effect=fake_load), \
         patch.object(DgiiCertService, "_step4_case_artifacts", return_value=None):
        result = DgiiCertService.generate_step4_test_set(
            company_id="c1", company_profile=PROFILE, owner_uid="u1",
            user_email="t@t.do", sandbox=True, run_number=1,
        )

    assert result["success"] is True
    assert result["set"]["total"] == 25
    assert result["errors"] == []

    invoice_kinds = [i for i in saved_invoices if i["ecfType"] not in ("E33", "E34")]
    assert len(invoice_kinds) == 16  # 4 E31 + 2 E32 + 2 E44 + 2 E45 + 2 E46 + 4 RFCE
    for inv in invoice_kinds:
        assert inv.get("dueDate"), f"{inv['ecfType']} sin dueDate"
        assert inv.get("encf", "").startswith("E")
        assert inv.get("items") and inv["items"][0].get("discountRate") is not None

    # E33/E34 ya no se crean desde el set: son marcadores manuales
    notas = [i for i in saved_invoices if i["ecfType"] in ("E33", "E34")]
    assert len(notas) == 0
    blocks_by_tipo = {b["tipo"]: b for b in result["set"]["blocks"]}
    for tipo, count in (("E33", 1), ("E34", 2)):
        b = blocks_by_tipo[tipo]
        assert b.get("manual_required") is True
        assert len(b["cases"]) == count
        for c in b["cases"]:
            assert c.get("manual") is True
            assert not c.get("doc_id")
            assert not c.get("encf")
    assert all(t not in seq_counter for t in ("E33", "E34"))  # no se consumen secuencias

    assert len(saved_expenses) == 4
    for e in saved_expenses:
        assert e.get("encf", "").startswith("E")
        assert e.get("ecfType") in ("E41", "E43")

    assert len(saved_supplier) == 2
    for s in saved_supplier:
        assert s.get("ecfType") == "E47"
        assert s.get("encf", "").startswith("E47")


def test_case_artifacts_use_rnc_nomenclature(tmp_path):
    """Regresión: XML/PDF del set se nombran {rnc}{encf}.* (nomenclatura DGII)."""
    from unittest.mock import patch
    import tempfile
    import os as _os

    xml_dir = str(tmp_path / "xml")
    pdf_dir = str(tmp_path / "pdf")
    _os.makedirs(xml_dir, exist_ok=True)
    _os.makedirs(pdf_dir, exist_ok=True)

    payload = {"encf": "E310000000001", "total": 1.0, "items": []}
    case = {"encf": "E310000000001", "rfce": True}

    def fake_sign(raw, profile):
        return b"<signed/>"

    def fake_pdf(payload, profile, pdf_dir, encf):
        p = _os.path.join(pdf_dir, f"{profile['companyRNC']}{encf}.pdf")
        with open(p, "wb") as f:
            f.write(b"%PDF-")
        return p

    with patch("app.services.dgii_cert_service.DgiiSigner.sign_xml", side_effect=fake_sign), \
         patch("app.services.dgii_cert_service.DgiiSigner.extract_signature_value", return_value="ABCDEF123456"), \
         patch.object(DgiiCertService, "_step4_case_pdf", side_effect=fake_pdf):
        DgiiCertService._step4_case_artifacts(PROFILE, payload, case, xml_dir, pdf_dir)

    rnc = PROFILE["companyRNC"]
    assert _os.path.exists(_os.path.join(xml_dir, f"{rnc}E310000000001_raw.xml"))
    assert _os.path.exists(_os.path.join(xml_dir, f"{rnc}E310000000001.xml"))
    assert _os.path.exists(_os.path.join(xml_dir, f"{rnc}E310000000001_rfce.xml"))
    assert _os.path.exists(_os.path.join(pdf_dir, f"{rnc}E310000000001.pdf"))
    assert case["xml_path"].endswith(f"{rnc}E310000000001.xml")
    assert case["rfce_xml_path"].endswith(f"{rnc}E310000000001_rfce.xml")


def test_light_run_summary_strips_test_set():
    run_dict = {
        "run_number": 1,
        "test_set": {
            "total": 25,
            "set_errors": [],
            "blocks": [
                {"index": 1, "tipo": "E31", "label": "x", "count": 4,
                 "status": "sent", "sent_count": 4, "failed_count": 0,
                 "cases": [{"doc_id": "d", "response_data": {"big": "x" * 5000}}]},
            ],
        },
        "cases": [{"a": 1}],
    }
    light = DgiiCertService._light_run_summary(run_dict)
    assert "test_set" not in light
    assert light["test_set_summary"]["total"] == 25
    assert light["test_set_summary"]["blocks"][0]["status"] == "sent"
    assert "cases" not in light["test_set_summary"]["blocks"][0]


def test_gate_nota_references():
    from unittest.mock import patch

    blocks = [
        {"index": 1, "tipo": "E31", "label": "31", "count": 1, "status": "sent",
         "cases": [{"encf": "E310000000019", "status": "accepted", "track_id": "T1"}]},
        {"index": 2, "tipo": "E33", "label": "33", "count": 1, "status": "pending",
         "cases": [{"encf": "E330000000005", "ncfModified": "E310000000019", "status": "pending"}]},
    ]

    with patch.object(DgiiCertService, "_check_dgii_acceptance", return_value=True) as mock_check:
        assert DgiiCertService._gate_nota_references(PROFILE, blocks, 2) is None
        mock_check.assert_called_once_with(PROFILE, "E310000000019", track_id="T1")

    # Pendiente/desconocido NO bloquea (la DGII rechazará explícitamente si aplica)
    with patch.object(DgiiCertService, "_check_dgii_acceptance", return_value=None):
        assert DgiiCertService._gate_nota_references(PROFILE, blocks, 2) is None

    # Referenciado no aceptado en el set → no bloquea (el orden de bloques ya se exige)
    blocks[0]["cases"][0]["status"] = "pending"
    with patch.object(DgiiCertService, "_check_dgii_acceptance", return_value=True):
        assert DgiiCertService._gate_nota_references(PROFILE, blocks, 2) is None

    # Rechazo explícito confirmado por la DGII → bloquea
    blocks[0]["cases"][0]["status"] = "accepted"
    with patch.object(DgiiCertService, "_check_dgii_acceptance", return_value=False):
        err = DgiiCertService._gate_nota_references(PROFILE, blocks, 2)
        assert err and "RECHAZADO" in err


def test_classify_consulta_status():
    cls = DgiiCertService
    assert cls._classify_consulta_status({"estado": "Aceptado"}, "") == "ACCEPTED"
    assert cls._classify_consulta_status(None, "RECHAZADO por validacion") == "REJECTED"
    assert cls._classify_consulta_status(None, "El comprobante no existe en el sistema") == "NOT_FOUND"
    assert cls._classify_consulta_status(None, "Error interno del servidor") is None
    assert cls._classify_consulta_status({"mensajes": [{"valor": "ok"}]}, "") is None


def test_emit_for_certification_detects_rejection_on_http_200():
    """Regresión: la DGII devuelve HTTP 200 con mensajes de rechazo en el body.
    Antes se marcaba como éxito; ahora debe marcarse rechazado con el mensaje."""
    from unittest.mock import patch

    class FakeResp:
        status_code = 200
        text = '{"mensajes": [{"valor": "eNCF fuera de rango autorizado"}]}'

        def json(self):
            import json as _json
            return _json.loads(self.text)

    with patch.object(DgiiCertService, "_get_cert_token", return_value=("tok", None)), \
         patch.object(DgiiCertService, "_cert_endpoints",
                      return_value={"recepcion": "http://x", "rfce_recepcion": "http://y"}), \
         patch("app.services.dgii_cert_service.DgiiXmlBuilder.build_invoice_xml", return_value=b"<xml/>"), \
         patch("app.services.dgii_cert_service.DgiiSigner.sign_xml", return_value=b"<signed/>"), \
         patch("app.services.dgii_cert_service.DgiiSigner.extract_signature_value", return_value="ABC123456"), \
         patch("app.services.dgii_cert_service.DgiiDirectService._multipart_post", return_value=FakeResp()), \
         patch("app.services.dgii_cert_service.DgiiDirectService._prepare_tls_cert", return_value=None), \
         patch("app.services.dgii_cert_service.DgiiDirectService._cleanup_tls_cert", return_value=None):
        res = DgiiCertService.emit_for_certification(
            PROFILE, {"encf": "E310000000001", "ecfType": "Factura de Crédito Fiscal (E31)",
                      "total": 100.0, "items": []})
    assert res["success"] is False
    assert "fuera de rango" in (res.get("error") or "")
    assert res.get("dgii_status") == "REJECTED"


def test_emit_for_certification_confirms_rejected_status():
    """HTTP 200 + status REJECTED sin mensaje explícito → consulta para confirmar."""
    from unittest.mock import patch

    class FakeResp:
        status_code = 200
        text = '{"status": "RECHAZADO"}'

        def json(self):
            import json as _json
            return _json.loads(self.text)

    with patch.object(DgiiCertService, "_get_cert_token", return_value=("tok", None)), \
         patch.object(DgiiCertService, "_cert_endpoints",
                      return_value={"recepcion": "http://x", "rfce_recepcion": "http://y"}), \
         patch("app.services.dgii_cert_service.DgiiXmlBuilder.build_invoice_xml", return_value=b"<xml/>"), \
         patch("app.services.dgii_cert_service.DgiiSigner.sign_xml", return_value=b"<signed/>"), \
         patch("app.services.dgii_cert_service.DgiiSigner.extract_signature_value", return_value="ABC123456"), \
         patch("app.services.dgii_cert_service.DgiiDirectService._multipart_post", return_value=FakeResp()), \
         patch("app.services.dgii_cert_service.DgiiDirectService._prepare_tls_cert", return_value=None), \
         patch("app.services.dgii_cert_service.DgiiDirectService._cleanup_tls_cert", return_value=None), \
         patch.object(DgiiCertService, "_check_dgii_acceptance", return_value=False):
        res = DgiiCertService.emit_for_certification(
            PROFILE, {"encf": "E310000000001", "ecfType": "Factura de Crédito Fiscal (E31)",
                      "total": 100.0, "items": []})
    assert res["success"] is False
    assert "RECHAZADO" in (res.get("error") or "")

    with patch.object(DgiiCertService, "_get_cert_token", return_value=("tok", None)), \
         patch.object(DgiiCertService, "_cert_endpoints",
                      return_value={"recepcion": "http://x", "rfce_recepcion": "http://y"}), \
         patch("app.services.dgii_cert_service.DgiiXmlBuilder.build_invoice_xml", return_value=b"<xml/>"), \
         patch("app.services.dgii_cert_service.DgiiSigner.sign_xml", return_value=b"<signed/>"), \
         patch("app.services.dgii_cert_service.DgiiSigner.extract_signature_value", return_value="ABC123456"), \
         patch("app.services.dgii_cert_service.DgiiDirectService._multipart_post", return_value=FakeResp()), \
         patch("app.services.dgii_cert_service.DgiiDirectService._prepare_tls_cert", return_value=None), \
         patch("app.services.dgii_cert_service.DgiiDirectService._cleanup_tls_cert", return_value=None), \
         patch.object(DgiiCertService, "_check_dgii_acceptance", return_value=True):
        res2 = DgiiCertService.emit_for_certification(
            PROFILE, {"encf": "E310000000001", "ecfType": "Factura de Crédito Fiscal (E31)",
                      "total": 100.0, "items": []})
    assert res2["success"] is True
    assert res2.get("dgii_status") == "ACCEPTED"
    assert str(res2.get("qrCodeURL", "")).startswith("https://ecf.dgii.gov.do/")
    assert "ConsultaTimbre?" in str(res2.get("qrCodeURL", ""))


def test_check_dgii_acceptance_uses_trackid_and_encf_params():
    """Regresión: consultaresultado se consulta con trackid y consultaestado con encf
    (no ncfelectronico, que la DGII no reconoce en CerteCF)."""
    from unittest.mock import patch

    captured = []

    class FakeResp:
        status_code = 200
        text = "no encontrado"

        def json(self):
            return {"estado": "no existe"}

    def fake_get(url, params, token=None, cert_path=None):
        captured.append((url, dict(params)))
        return FakeResp()

    with patch.object(DgiiCertService, "_cert_endpoints", return_value={
            "consulta_resultado": "https://ecf.dgii.gov.do/CerteCF/consultaresultado/api/consultas/estado",
            "consulta_estado": "https://ecf.dgii.gov.do/CerteCF/consultaestado/api/consultas/estado",
        }), \
         patch.object(DgiiCertService, "_get_cert_token", return_value=("tok", None)), \
         patch("app.services.dgii_cert_service.DgiiDirectService._get_with_params", side_effect=fake_get), \
         patch("app.services.dgii_cert_service.DgiiDirectService._prepare_tls_cert", return_value=None), \
         patch("app.services.dgii_cert_service.DgiiDirectService._cleanup_tls_cert", return_value=None):
        res = DgiiCertService._check_dgii_acceptance(
            PROFILE, "E310000000019", track_id="TRACK123", attempts=1, delay=0
        )

    assert res is None
    urls_params = {u.split("/api")[0].split("/")[-1]: p for u, p in captured}
    assert urls_params["consultaresultado"] == {"rncemisor": "131880681", "trackid": "TRACK123"}
    assert urls_params["consultaestado"] == {"rncemisor": "131880681", "encf": "E310000000019"}


def test_mark_step4_block_sent():
    """Marcar bloque como enviado manualmente (envíos hechos fuera del wizard)."""
    from unittest.mock import patch

    run_data = {
        "run_number": 7,
        "test_set": {
            "total": 25,
            "blocks": [
                {"index": 1, "tipo": "E31", "label": "31", "count": 1, "status": "sent",
                 "cases": [{"encf": "E310000000019", "status": "accepted"}]},
                {"index": 2, "tipo": "E32", "label": "32", "count": 2, "status": "pending",
                 "cases": [{"encf": "E320000000030", "status": "pending"},
                           {"encf": "E320000000031", "status": "pending"}]},
                {"index": 3, "tipo": "E33", "label": "33", "count": 1, "status": "pending",
                 "cases": [{"encf": "E330000000005", "status": "pending"}]},
            ],
        },
    }
    with patch.object(DgiiCertService, "_get_firestore_doc", return_value=run_data), \
         patch.object(DgiiCertService, "save_run_progress", return_value=None), \
         patch.object(DgiiCertService, "complete_step", return_value=None):
        # Bloque 3 antes del 2 → error de orden
        res = DgiiCertService.mark_step4_block_sent("c1", 7, 3, marked_by="t@t.do")
        assert res["success"] is False
        assert "debe enviarse primero" in res["error"]

        # Marcar bloque 2 → casos quedan manual_sent
        res2 = DgiiCertService.mark_step4_block_sent("c1", 7, 2, marked_by="t@t.do")
        assert res2["success"] is True
        assert res2["block"]["status"] == "sent"
        assert all(c["status"] == "manual_sent" for c in res2["block"]["cases"])
        assert res2["all_blocks_sent"] is False

        # Marcar bloque 3 (ya permitido) → todo enviado
        res3 = DgiiCertService.mark_step4_block_sent("c1", 7, 3, marked_by="t@t.do")
        assert res3["success"] is True
        assert res3["all_blocks_sent"] is True

        # Re-marcar bloque 2 → reused
        res4 = DgiiCertService.mark_step4_block_sent("c1", 7, 2, marked_by="t@t.do")
        assert res4["success"] is True and res4.get("reused") is True


def test_build_qr_url_by_type():
    """QR DGII unificado: formato CamelCase oficial + env, reglas por tipo."""
    from app.services.dgii_direct import DgiiDirectService

    profile = {"companyRNC": "133753652"}
    base = {
        "encf": "E310000000019",
        "date": "2026-08-16",
        "total": 53100.0,
        "clientRNC": "131880681",
        "ecfType": "Factura de Crédito Fiscal (E31)",
    }
    url = DgiiDirectService.build_qr_url(profile, base, "ABC123")
    assert url.startswith("https://ecf.dgii.gov.do/")
    assert "ConsultaTimbre?" in url
    assert "RncEmisor=133753652" in url
    assert "RncComprador=131880681" in url
    assert "ENCF=E310000000019" in url
    assert "MontoTotal=53100.00" in url
    assert "FechaEmision=16-08-2026" in url
    assert "CodigoSeguridad=ABC123" in url

    # E41 → RncComprador = RNC de la empresa (Comprador del XML = emisor)
    url41 = DgiiDirectService.build_qr_url(
        profile, dict(base, ecfType="Comprobante de Compras (E41)", encf="E410000000001"), "SIG123")
    assert "RncComprador=133753652" in url41
    assert "ConsultaTimbre?" in url41

    # E43 / E46 / E47 → sin RncComprador
    for tipo in ["E43", "Comprobante para Gastos Menores (E43)",
                 "Pagos al Exterior (E47)", "Comprobante de Exportación (E46)"]:
        u = DgiiDirectService.build_qr_url(profile, dict(base, ecfType=tipo, clientRNC=""), "S")
        assert "RncComprador" not in u, f"{tipo} no debe llevar RncComprador"

    # E44 / E45 → igual que E31 (RNC del comprador)
    for tipo in ["Comprobante de Regímenes Especiales (E44)", "Comprobante Gubernamental (E45)"]:
        u = DgiiDirectService.build_qr_url(profile, dict(base, ecfType=tipo), "S")
        assert "RncComprador=131880681" in u

    # E32 < 250K → ruta FC sin RncComprador (paridad con QR real DGII)
    ufc = DgiiDirectService.build_qr_url(
        profile, dict(base, ecfType="Factura de Consumo (E32)", total=14750.0, encf="E320000000034"), "S%2Fbv%2Ft")
    assert ufc.startswith("https://fc.dgii.gov.do/")
    assert "ConsultaTimbreFC?" in ufc
    assert "RncComprador" not in ufc
    assert "ENCF=E320000000034" in ufc
    assert "MontoTotal=14750.00" in ufc
    assert "CodigoSeguridad=S%252Fbv%252Ft" in ufc

    # E32 >= 250K → ruta e-CF normal
    uge = DgiiDirectService.build_qr_url(
        profile, dict(base, ecfType="Factura de Consumo (E32)", total=259600.0), "S")
    assert "ecf.dgii.gov.do" in uge
    assert "ConsultaTimbre?" in uge


def test_send_step4_block_resend():
    """Reenvío intencional: manda los MISMOS eNCF (la DGII reinicia esa prueba)."""
    from unittest.mock import patch

    run_data = {
        "run_number": 7,
        "test_set": {
            "total": 2,
            "blocks": [
                {"index": 1, "tipo": "E31", "label": "31", "count": 1, "status": "sent", "sent_count": 1,
                 "cases": [{"encf": "E310000000019", "status": "accepted", "doc_id": "d1",
                            "track_id": "OLD", "dgii_status": "ACCEPTED"}]},
                {"index": 2, "tipo": "E32", "label": "32", "count": 1, "status": "sent", "sent_count": 1,
                 "cases": [{"encf": "E320000000030", "status": "accepted", "doc_id": "d2",
                            "track_id": "OLD2", "dgii_status": "ACCEPTED"}]},
            ],
        },
    }
    emitted = []

    def fake_emit(company_profile, invoice_dict):
        emitted.append(invoice_dict.get("encf"))
        return {"success": True, "track_id": "NEW", "dgii_status": "UNKNOWN",
                "response_data": {}, "qrCodeURL": "https://ecf.dgii.gov.do/x"}

    with patch.object(DgiiCertService, "_get_firestore_doc", return_value=run_data), \
         patch.object(DgiiCertService, "_load_step4_payload", side_effect=lambda o, c, **kw: {"encf": c["encf"], "total": 1.0}), \
         patch.object(DgiiCertService, "emit_for_certification", side_effect=fake_emit), \
         patch.object(DgiiCertService, "_step4_case_artifacts_from_emission", return_value=None), \
         patch.object(DgiiCertService, "_mark_step4_case_emitted", return_value=None), \
         patch.object(DgiiCertService, "save_run_progress", return_value=None), \
         patch.object(DgiiCertService, "complete_step", return_value=None), \
         patch.object(DgiiCertService, "fail_step", return_value=None):
        # Sin resend → bloque ya enviado se reutiliza
        res = DgiiCertService.send_step4_block("c1", PROFILE, "u1", "t@t.do", run_number=7, block_index=1)
        assert res["success"] is True and res.get("reused") is True
        assert emitted == []

        # Con resend → re-emite el caso (reset de estado previo)
        res2 = DgiiCertService.send_step4_block("c1", PROFILE, "u1", "t@t.do", run_number=7, block_index=1, resend=True)
        assert res2["success"] is True
        assert emitted == ["E310000000019"]
        case = res2["block"]["cases"][0]
        assert case["status"] == "accepted"
        assert case.get("track_id") == "NEW"
        assert "OLD" not in str(case.get("dgii_status", ""))
        assert res2["block"].get("resend_count") == 1


def test_skip_step4_sequences():
    """Omite N números por tipo sobre el máximo consecutivo YA GENERADO (logs),
    en TODAS las secuencias activas del tipo. Evita 'ya enviado' en DGII."""
    from unittest.mock import patch

    sequences = [
        {"id": "s1", "tipoComprobante": "E31", "estado": "ACTIVA", "bloqueadaManualmente": False,
         "secuenciaInicial": 1, "secuenciaFinal": 1000000, "ultimoConsecutivoUsado": 4,
         "alertaMinimoDisponible": 100, "creadoEn": ""},
        {"id": "s2a", "tipoComprobante": "E32", "estado": "ACTIVA", "bloqueadaManualmente": False,
         "secuenciaInicial": 1, "secuenciaFinal": 1000000, "ultimoConsecutivoUsado": 20,
         "alertaMinimoDisponible": 100, "creadoEn": ""},
        {"id": "s2b", "tipoComprobante": "E32", "estado": "ACTIVA", "bloqueadaManualmente": False,
         "secuenciaInicial": 1, "secuenciaFinal": 1000000, "ultimoConsecutivoUsado": 0,
         "alertaMinimoDisponible": 100, "creadoEn": ""},
        {"id": "s3", "tipoComprobante": "E33", "estado": "ACTIVA", "bloqueadaManualmente": False,
         "secuenciaInicial": 1, "secuenciaFinal": 1000000, "ultimoConsecutivoUsado": 999999,
         "alertaMinimoDisponible": 100, "creadoEn": ""},
        {"id": "s4", "tipoComprobante": "E34", "estado": "EXPIRADA", "bloqueadaManualmente": False,
         "secuenciaInicial": 1, "secuenciaFinal": 1000000, "ultimoConsecutivoUsado": 2,
         "alertaMinimoDisponible": 100, "creadoEn": ""},
    ]
    logs = [
        {"tipoComprobante": "E31", "consecutivo": 4},
        {"tipoComprobante": "E32", "consecutivo": 38},  # > ultimo de s2a → base = 38
        {"tipoComprobante": "E33", "consecutivo": 999999},
        # E34 sin historial → no se toca aunque haya secuencia activa
    ]
    saved = {}

    def fake_get_sequences(owner_uid, sandbox=True, company_id=None):
        return sequences

    def fake_save_sequence(owner_uid, seq_id, seq_dict, sandbox=True, company_id=None):
        saved[seq_id] = dict(seq_dict)

    with patch("app.services.dgii_cert_service.DatabaseService.get_sequences", side_effect=fake_get_sequences), \
         patch("app.services.dgii_cert_service.DatabaseService.get_sequence_logs", return_value=logs), \
         patch("app.services.dgii_cert_service.DatabaseService.save_sequence", side_effect=fake_save_sequence):
        skipped = DgiiCertService.skip_step4_sequences("u1", "c1", sandbox=True)

    # E31: base max(4, log 4) + 10 = 14; E32: base max(20, 38) + 10 = 48 en AMBAS activas;
    # E33: clamp a final; E34 sin logs → no se toca
    assert skipped["E31"] == {"desde": 4, "hasta": 14, "max_usado": 4}
    assert skipped["E32"] == {"desde": 38, "hasta": 48, "max_usado": 38}
    assert skipped["E33"] == {"desde": 999999, "hasta": 1000000, "max_usado": 999999}
    assert "E34" not in skipped
    assert saved["s1"]["ultimoConsecutivoUsado"] == 14
    assert saved["s2a"]["ultimoConsecutivoUsado"] == 48
    assert saved["s2b"]["ultimoConsecutivoUsado"] == 48  # todas las activas del tipo
    assert saved["s3"]["ultimoConsecutivoUsado"] == 1000000


def test_generate_set_skips_sequences_on_new_run_too():
    """Regresión: el salto de secuencias se aplica en TODA generación (corrida
    nueva incluida), validando contra los e-CF ya generados (logs)."""
    from unittest.mock import patch

    seq_state = {"ultimo": 4}
    saved = []

    def fake_get_sequences(owner_uid, sandbox=True, company_id=None):
        return [{"id": "s1", "tipoComprobante": "E31", "estado": "ACTIVA", "bloqueadaManualmente": False,
                 "secuenciaInicial": 1, "secuenciaFinal": 1000000,
                 "ultimoConsecutivoUsado": seq_state["ultimo"],
                 "alertaMinimoDisponible": 100, "creadoEn": ""}]

    def fake_save_sequence(owner_uid, seq_id, seq_dict, sandbox=True, company_id=None):
        seq_state["ultimo"] = int(seq_dict["ultimoConsecutivoUsado"])
        saved.append(seq_dict)

    base_patches = [
        patch("app.services.dgii_cert_service.DatabaseService.get_sequences", side_effect=fake_get_sequences),
        patch("app.services.dgii_cert_service.DatabaseService.get_sequence_logs",
              return_value=[{"tipoComprobante": "E31", "consecutivo": 4}]),
        patch("app.services.dgii_cert_service.DatabaseService.save_sequence", side_effect=fake_save_sequence),
        patch("app.services.dgii_cert_service.DatabaseService.consume_next_sequence",
              side_effect=lambda o, t, e, sandbox=True, company_id=None: (f"{t}0000000001", "l")),
        patch("app.services.dgii_cert_service.DatabaseService.save_invoice", return_value=None),
        patch("app.services.dgii_cert_service.DatabaseService.save_expense", return_value=None),
        patch("app.services.dgii_cert_service.SupplierInvoiceService.create",
              side_effect=lambda **kw: kw["data"].__setitem__("id", "x") or kw["data"]),
        patch.object(DgiiCertService, "_load_step4_payload",
                     side_effect=lambda o, c, **kw: {"encf": c.get("encf"), "total": 1.0, "items": []}),
        patch.object(DgiiCertService, "_step4_case_artifacts", return_value=None),
        patch.object(DgiiCertService, "save_run_progress", return_value=None),
        patch.object(DgiiCertService, "ensure_cert_sequences",
                     return_value={"created": [], "existing": []}),
    ]

    # Corrida NUEVA (doc vacío, sin force) con historial → salta igual
    import contextlib
    with contextlib.ExitStack() as stack:
        for p in base_patches:
            stack.enter_context(p)
        stack.enter_context(patch.object(DgiiCertService, "_get_firestore_doc", return_value={}))
        result = DgiiCertService.generate_step4_test_set(
            company_id="c1", company_profile=PROFILE, owner_uid="u1",
            user_email="t@t.do", sandbox=True, run_number=9, force_rerun=False)
    assert seq_state["ultimo"] == 14  # 4 usados + hueco de 10
    assert result["set"]["sequence_skip"]["E31"]["hasta"] == 14
    assert any("omitieron 10" in w for w in result["set"]["warnings"])

    # Sin historial (logs vacíos) → no avanza (primera generación usa la posición actual)
    seq_state["ultimo"] = 0
    saved.clear()
    with patch.object(DgiiCertService, "_get_firestore_doc", return_value={}), \
         patch("app.services.dgii_cert_service.DatabaseService.get_sequences", side_effect=fake_get_sequences), \
         patch("app.services.dgii_cert_service.DatabaseService.get_sequence_logs", return_value=[]), \
         patch("app.services.dgii_cert_service.DatabaseService.save_sequence", side_effect=fake_save_sequence), \
         patch("app.services.dgii_cert_service.DatabaseService.consume_next_sequence",
               side_effect=lambda o, t, e, sandbox=True, company_id=None: (f"{t}0000000001", "l")), \
         patch("app.services.dgii_cert_service.DatabaseService.save_invoice", return_value=None), \
         patch("app.services.dgii_cert_service.DatabaseService.save_expense", return_value=None), \
         patch("app.services.dgii_cert_service.SupplierInvoiceService.create",
               side_effect=lambda **kw: kw["data"].__setitem__("id", "x") or kw["data"]), \
         patch.object(DgiiCertService, "_load_step4_payload",
                      side_effect=lambda o, c, **kw: {"encf": c.get("encf"), "total": 1.0, "items": []}), \
         patch.object(DgiiCertService, "_step4_case_artifacts", return_value=None), \
         patch.object(DgiiCertService, "save_run_progress", return_value=None), \
         patch.object(DgiiCertService, "ensure_cert_sequences",
                      return_value={"created": [], "existing": []}):
        result2 = DgiiCertService.generate_step4_test_set(
            company_id="c1", company_profile=PROFILE, owner_uid="u1",
            user_email="t@t.do", sandbox=True, run_number=10, force_rerun=False)
    assert seq_state["ultimo"] == 0
    assert result2["set"]["sequence_skip"] == {}
    assert any("omitieron 10" in w for w in result2["set"]["warnings"]) is False


def test_send_step4_block_manual_required_rejected():
    """Los bloques E33/E34 no pueden enviarse desde el wizard: son manuales."""
    from unittest.mock import patch

    run_data = {
        "run_number": 7,
        "test_set": {
            "total": 2,
            "blocks": [
                {"index": 1, "tipo": "E31", "label": "31", "count": 1, "status": "sent",
                 "cases": [{"encf": "E310000000019", "status": "accepted", "doc_id": "d1"}]},
                {"index": 2, "tipo": "E33", "label": "33", "count": 1, "status": "pending",
                 "manual_required": True,
                 "cases": [{"tipo": "E33", "kind": "nota_manual", "manual": True, "status": "pending"}]},
            ],
        },
    }
    with patch.object(DgiiCertService, "_get_firestore_doc", return_value=run_data), \
         patch.object(DgiiCertService, "emit_for_certification", return_value={"success": True}) as mock_emit:
        res = DgiiCertService.send_step4_block("c1", PROFILE, "u1", "t@t.do", run_number=7, block_index=2)
        assert res["success"] is False
        assert "manualmente" in res["error"]
        assert "Marcar enviado" in res["error"]
        mock_emit.assert_not_called()

        res2 = DgiiCertService.send_step4_block("c1", PROFILE, "u1", "t@t.do", run_number=7, block_index=2, resend=True)
        assert res2["success"] is False
        mock_emit.assert_not_called()


def test_emit_for_certification_rfce_filename():
    """Regresión: la DGII valida el nombre del archivo RFCE ({RNC}{eNCF}.xml, 26 chars).
    El nombre anterior {RNC}_rfce.xml provocaba 'La longitud del nombre del archivo no es válida'."""
    from unittest.mock import patch

    captured = {}

    class FakeResp:
        status_code = 200
        text = '{"trackId": "T1"}'

        def json(self):
            import json as _json
            return _json.loads(self.text)

    def fake_multipart(url, xml_bytes, token=None, filename="document.xml", cert_path=None):
        captured["url"] = url
        captured["filename"] = filename
        return FakeResp()

    with patch.object(DgiiCertService, "_get_cert_token", return_value=("tok", None)), \
         patch.object(DgiiCertService, "_cert_endpoints",
                      return_value={"recepcion": "http://x", "rfce_recepcion": "http://fc/x"}), \
         patch("app.services.dgii_cert_service.DgiiXmlBuilder.build_invoice_xml", return_value=b"<xml/>"), \
         patch("app.services.dgii_cert_service.DgiiXmlBuilder.build_rfce_summary_xml", return_value=b"<rfce/>"), \
         patch("app.services.dgii_cert_service.DgiiSigner.sign_xml", return_value=b"<signed/>"), \
         patch("app.services.dgii_cert_service.DgiiSigner.extract_signature_value", return_value="ABC123456"), \
         patch("app.services.dgii_cert_service.DgiiDirectService._multipart_post", side_effect=fake_multipart), \
         patch("app.services.dgii_cert_service.DgiiDirectService._prepare_tls_cert", return_value=None), \
         patch("app.services.dgii_cert_service.DgiiDirectService._cleanup_tls_cert", return_value=None):
        res = DgiiCertService.emit_for_certification(
            PROFILE, {"encf": "E320000000034", "ecfType": "Factura de Consumo (E32)",
                      "total": 14750.0, "items": []})

    assert captured["url"] == "http://fc/x"
    assert captured["filename"] == "131880681E320000000034.xml"
    assert len(captured["filename"]) == 26
    assert res["success"] is True


def test_send_step4_block_persists_exact_sent_bytes(tmp_path):
    """Regresión vínculo de firma DGII: los XML guardados en disco son EXACTAMENTE
    los enviados (sin re-firmar). CodigoSeguridadeCF del RFCE (API) debe coincidir
    con SignatureValue[:6] del E32 completo que se sube al portal."""
    import os as _os
    from unittest.mock import patch

    run_data = {
        "run_number": 7,
        "test_set": {
            "total": 1,
            "blocks": [
                {"index": 1, "tipo": "E32", "label": "RFCE", "count": 1, "status": "pending", "rfce": True,
                 "cases": [{"encf": "E320000000129", "status": "pending", "doc_id": "d1", "rfce": True,
                            "total": 14750.0, "kind": "invoice", "invoiceNumber": "CERT-E32-01"}]},
            ],
        },
    }
    fake_result = {
        "success": True,
        "track_id": "T-1",
        "dgii_status": "UNKNOWN",
        "codigo_seguridad": "iyQ1gf",
        "xml_signature": "iyQ1gfXXXX",
        "qrCodeURL": "https://fc.dgii.gov.do/CerteCF/ConsultaTimbreFC?x=1",
        "response_data": {},
        "signed_xml": b"<ECF>FIRMADO-ENVIADO</ECF>",
        "rfce_signed_xml": b"<RFCE>FIRMADO-ENVIADO</RFCE>",
    }

    with patch.object(DgiiCertService, "_get_firestore_doc", return_value=run_data), \
         patch.object(DgiiCertService, "_load_step4_payload",
                      side_effect=lambda o, c, **kw: {"encf": c["encf"], "ecfType": "Factura de Consumo (E32)",
                                                      "total": 14750.0, "items": []}), \
         patch.object(DgiiCertService, "emit_for_certification", return_value=fake_result), \
         patch.object(DgiiCertService, "_step4_case_pdf", return_value=None), \
         patch.object(DgiiCertService, "_mark_step4_case_emitted", return_value=None), \
         patch.object(DgiiCertService, "save_run_progress", return_value=None), \
         patch.object(DgiiCertService, "complete_step", return_value=None), \
         patch.object(DgiiCertService, "fail_step", return_value=None), \
         patch("app.services.dgii_cert_service._get_evidence_dir",
               return_value=str(tmp_path / "run7")):
        res = DgiiCertService.send_step4_block("c1", PROFILE, "u1", "t@t.do", run_number=7, block_index=1)

    assert res["success"] is True
    xml_dir = tmp_path / "run7" / "xml"
    rnc = PROFILE["companyRNC"]
    with open(xml_dir / f"{rnc}E320000000129.xml", "rb") as f:
        assert f.read() == b"<ECF>FIRMADO-ENVIADO</ECF>"
    with open(xml_dir / f"{rnc}E320000000129_rfce.xml", "rb") as f:
        assert f.read() == b"<RFCE>FIRMADO-ENVIADO</RFCE>"
    assert res["block"]["cases"][0]["xml_path"].endswith(f"{rnc}E320000000129.xml")


def test_build_qr_url_fecha_firma_real_y_orden():
    """Regresión RI: FechaFirma usa la fecha/hora REAL de la firma (no '12:00:00')
    y los parámetros siguen el orden del Informe Técnico §18.2.3."""
    from app.services.dgii_direct import DgiiDirectService

    profile = {"companyRNC": "133753652"}
    base = {
        "encf": "E310000000125",
        "date": "2026-08-16",
        "total": 53100.0,
        "clientRNC": "131880681",
        "ecfType": "Factura de Crédito Fiscal (E31)",
        "fechaHoraFirma": "16-08-2026 12:57:17",
    }
    url = DgiiDirectService.build_qr_url(profile, base, "ABC123")
    assert "FechaFirma=16-08-2026%2012%3A57%3A17" in url  # %20 (no '+') como exige el Informe
    assert "+" not in url.split("FechaFirma=")[1].split("&")[0]
    pos_rnc = url.index("RncEmisor=")
    pos_cmp = url.index("RncComprador=")
    pos_encf = url.index("ENCF=")
    pos_ff = url.index("FechaFirma=")
    assert pos_rnc < pos_cmp < pos_encf < pos_ff

    sin_firma = dict(base)
    sin_firma.pop("fechaHoraFirma", None)
    url_sf = DgiiDirectService.build_qr_url(profile, sin_firma, "ABC123")
    assert "12%3A00%3A00" in url_sf  # fallback cuando no hay fecha real
    assert "+" not in url_sf.split("FechaFirma=")[1].split("&")[0]


def test_extract_fecha_hora_firma():
    from app.services.dgii_signer import DgiiSigner
    xml = b"<ECF><FechaHoraFirma>16-08-2026 12:57:17</FechaHoraFirma><FechaVencimientoSecuencia>31-12-2028</FechaVencimientoSecuencia></ECF>"
    assert DgiiSigner.extract_fecha_hora_firma(xml) == "16-08-2026 12:57:17"
    assert DgiiSigner.extract_fecha_vencimiento_secuencia(xml) == "31-12-2028"
    assert DgiiSigner.extract_fecha_hora_firma(b"<ECF/>") == ""


def test_build_qr_url_fecha_firma_desde_xmlcontent():
    """Regresión: rutas que pasan el invoice almacenado (PDF normal, detalle, etc.)
    extraen la FechaHoraFirma REAL del xmlContent (no '12:00:00' fabricada)."""
    from app.services.dgii_direct import DgiiDirectService

    profile = {"companyRNC": "133753652"}
    invoice = {
        "encf": "E310000000142",
        "date": "2026-08-19",
        "total": 112100.0,
        "clientRNC": "131880681",
        "ecfType": "Factura de Crédito Fiscal (E31)",
        "xmlContent": "<ECF><FechaHoraFirma>19-08-2026 16:35:53</FechaHoraFirma></ECF>",
    }
    url = DgiiDirectService.build_qr_url(profile, invoice, "CQTMV/")
    assert "FechaFirma=19-08-2026%2016%3A35%3A53" in url
    assert "12%3A00%3A00" not in url

    sin_xml = dict(invoice)
    sin_xml.pop("xmlContent", None)
    url2 = DgiiDirectService.build_qr_url(profile, sin_xml, "CQTMV/")
    assert "12%3A00%3A00" in url2  # fallback sin información real
