import base64
import io
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from lxml import etree

from app.services.receptor_auth_service import ReceptorAuthService
from app.services.receptor_xml_service import ReceptorXmlService

ECF_XML = """<?xml version="1.0" encoding="utf-8"?>
<ECF xmlns="http://www.dgii.gov.do/ecf" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Encabezado>
    <IdDoc>
      <TipoeCF>31</TipoeCF>
      <eNCF>E310000000001</eNCF>
      <FechaVencimientoSecuencia>31-12-2026</FechaVencimientoSecuencia>
    </IdDoc>
    <Emisor>
      <RNCEmisor>132109122</RNCEmisor>
      <RazonSocialEmisor>EMISOR SRL</RazonSocialEmisor>
    </Emisor>
    <Comprador>
      <RNCComprador>131880681</RNCComprador>
      <RazonSocialComprador>COMPRADOR SRL</RazonSocialComprador>
    </Comprador>
    <Totales>
      <MontoTotal>1000.00</MontoTotal>
    </Totales>
  </Encabezado>
</ECF>"""

SIGNED_SEED_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<SemillaModel>
  <valor>abc123semilla</valor>
  <fecha>2026-08-31T10:00:00.000-04:00</fecha>
  <ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
    <ds:SignedInfo/>
    <ds:SignatureValue>c2ln</ds:SignatureValue>
    <ds:KeyInfo>
      <ds:X509Data>
        <ds:X509Certificate>Y2VydA==</ds:X509Certificate>
      </ds:X509Data>
    </ds:KeyInfo>
  </ds:Signature>
</SemillaModel>"""


# ── Rutas expuestas exactamente como las registró la DGII ──────────────────

def test_dgii_routes_registered_at_root(app):
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/fe/autenticacion/api/semilla" in rules
    assert "/fe/autenticacion/api/ValidacionCertificado" in rules
    assert "/fe/autenticacion/api/validacioncertificado" in rules
    assert "/fe/recepcion/api/ecf" in rules
    assert "/fe/aprobacioncomercial/api/ecf" in rules
    assert not any(rule.startswith("/api/v1/fe/") for rule in rules)


def test_semilla_case_insensitive(client):
    resp = client.get("/fe/autenticacion/api/Semilla")
    assert resp.status_code == 200
    root = etree.fromstring(resp.data)
    assert root.tag == "SemillaModel"


def test_validacion_certificado_mixed_case(client):
    fake_result = {"subject_sn": "131880681", "subject": "CN=X", "issuer": "CN=I",
                   "not_before": "x", "not_after": "x"}
    with patch.object(ReceptorAuthService, "validate_signed_seed", return_value=(fake_result, None)), \
            patch("app.api.v1.receptor.ReceptorRepository.save_token"):
        resp = client.post(
            "/fe/autenticacion/api/validacionCertificado",
            data=b"<SemillaModel><valor>abc</valor></SemillaModel>",
            content_type="application/xml",
        )
        assert resp.status_code == 200
        assert resp.get_json().get("token")


def test_recepcion_ecf_uppercase_path(client):
    with _patch_auth_and_company()[0], _patch_auth_and_company()[1], \
            patch("app.api.v1.receptor.ReceptorXmlService.verify_signature", return_value=(None, "sin firma")), \
            patch("app.api.v1.receptor.ReceptorRepository.find_received_by_encf", return_value=None), \
            patch("app.api.v1.receptor.ReceptorRepository.save_received_ecf"):
        resp = client.post(
            "/FE/RecepciON/API/ECF",
            data={"xml": (io.BytesIO(ECF_XML.encode("utf-8")), "ecf.xml")},
            content_type="multipart/form-data",
            headers=_recepcion_headers(),
        )
        assert resp.status_code == 200
        assert etree.fromstring(resp.data).tag == "ARECF"


# ── Semilla ────────────────────────────────────────────────────────────────

def test_semilla_endpoint_returns_semilla_model(client):
    resp = client.get("/fe/autenticacion/api/semilla")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("application/xml")
    root = etree.fromstring(resp.data)
    assert root.tag == "SemillaModel"
    valor = root.find("valor")
    fecha = root.find("fecha")
    assert valor is not None and len(valor.text) >= 32
    assert fecha is not None and "-04:00" in fecha.text


# ── ValidacionCertificado ──────────────────────────────────────────────────

def test_validacion_certificado_returns_token_json(client):
    fake_result = {
        "subject_sn": "131880681",
        "subject": "CN=COMPRADOR SRL,SN=131880681",
        "issuer": "CN=AVANSI",
        "not_before": "2026-01-01T00:00:00+00:00",
        "not_after": "2028-01-01T00:00:00+00:00",
    }
    with patch.object(ReceptorAuthService, "validate_signed_seed", return_value=(fake_result, None)), \
            patch("app.api.v1.receptor.ReceptorRepository.save_token") as save_token:
        resp = client.post(
            "/fe/autenticacion/api/ValidacionCertificado",
            data={"xml": (io.BytesIO(b"<xml/>"), "signed_seed.xml")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("token")
        assert data.get("expira") and data.get("expedido")
        save_token.assert_called_once()
        stored = save_token.call_args[0][1]
        assert stored["taxpayer_rnc"] == "131880681"


def test_validacion_certificado_returns_xml_on_accept_xml(client):
    fake_result = {"subject_sn": "131880681", "subject": "CN=X", "issuer": "CN=I",
                   "not_before": "x", "not_after": "x"}
    with patch.object(ReceptorAuthService, "validate_signed_seed", return_value=(fake_result, None)), \
            patch("app.api.v1.receptor.ReceptorRepository.save_token"):
        resp = client.post(
            "/fe/autenticacion/api/ValidacionCertificado",
            data={"xml": (io.BytesIO(b"<xml/>"), "signed_seed.xml")},
            content_type="multipart/form-data",
            headers={"Accept": "application/xml"},
        )
        assert resp.status_code == 200
        root = etree.fromstring(resp.data)
        assert root.tag == "RespuestaAutenticacion"
        assert root.find("token") is not None and root.find("token").text


def test_validacion_certificado_rejects_invalid_seed(client):
    with patch.object(ReceptorAuthService, "validate_signed_seed", return_value=(None, "La semilla no fue emitida por este receptor o ha expirado.")):
        resp = client.post(
            "/fe/autenticacion/api/ValidacionCertificado",
            data={"xml": (io.BytesIO(b"<xml/>"), "signed_seed.xml")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "semilla" in resp.get_json()["error"]


def test_validacion_certificado_accepts_raw_xml_body(client):
    fake_result = {"subject_sn": "131880681", "subject": "CN=X", "issuer": "CN=I",
                   "not_before": "x", "not_after": "x"}
    with patch.object(ReceptorAuthService, "validate_signed_seed", return_value=(fake_result, None)) as validate, \
            patch("app.api.v1.receptor.ReceptorRepository.save_token"):
        resp = client.post(
            "/fe/autenticacion/api/ValidacionCertificado",
            data=b"<SemillaModel><valor>abc</valor></SemillaModel>",
            content_type="application/xml",
        )
        assert resp.status_code == 200
        validate.assert_called_once()
        assert validate.call_args[0][0].startswith(b"<SemillaModel>")


def test_validacion_certificado_accepts_form_field(client):
    fake_result = {"subject_sn": "131880681", "subject": "CN=X", "issuer": "CN=I",
                   "not_before": "x", "not_after": "x"}
    with patch.object(ReceptorAuthService, "validate_signed_seed", return_value=(fake_result, None)) as validate, \
            patch("app.api.v1.receptor.ReceptorRepository.save_token"):
        resp = client.post(
            "/fe/autenticacion/api/ValidacionCertificado",
            data={"xml": "<SemillaModel><valor>abc</valor></SemillaModel>"},
        )
        assert resp.status_code == 200
        assert validate.call_args[0][0].startswith(b"<SemillaModel>")


def test_recepcion_ecf_accepts_raw_xml_body(client):
    with _patch_auth_and_company()[0], _patch_auth_and_company()[1], \
            patch("app.api.v1.receptor.ReceptorXmlService.verify_signature", return_value=(None, "sin firma")), \
            patch("app.api.v1.receptor.ReceptorRepository.find_received_by_encf", return_value=None), \
            patch("app.api.v1.receptor.ReceptorRepository.save_received_ecf"):
        resp = client.post(
            "/fe/recepcion/api/ecf",
            data=ECF_XML.encode("utf-8"),
            content_type="application/xml",
            headers=_recepcion_headers(),
        )
        assert resp.status_code == 200
        root = etree.fromstring(resp.data)
        assert root.tag == "ARECF"


def test_validate_signed_seed_xmldsig_server_side_matching():
    fake_signxml = MagicMock()
    with patch.dict("sys.modules", {"signxml": fake_signxml}), \
            patch.object(ReceptorAuthService, "_extract_embedded_cert_pem", return_value="PEM"), \
            patch.object(ReceptorAuthService, "_subject_sn_from_pem",
                         return_value=("131880681", MagicMock())), \
            patch("app.repositories.receptor_repository.ReceptorRepository.validate_seed", return_value=True) as validate_seed, \
            patch("app.repositories.receptor_repository.ReceptorRepository.consume_seed") as consume_seed:
        result, error = ReceptorAuthService.validate_signed_seed(SIGNED_SEED_XML)
        assert error is None
        assert result["subject_sn"] == "131880681"
        validate_seed.assert_called_once_with("abc123semilla")
        consume_seed.assert_called_once_with("abc123semilla")


def test_validate_signed_seed_rejects_unknown_seed():
    with patch("app.repositories.receptor_repository.ReceptorRepository.validate_seed", return_value=False):
        result, error = ReceptorAuthService.validate_signed_seed(SIGNED_SEED_XML)
        assert result is None
        assert "no fue emitida" in error


def test_validate_signed_seed_falls_back_to_manual_verify():
    class _RaisingVerifier:
        def __init__(self, *args, **kwargs):
            pass

        def verify(self, *args, **kwargs):
            raise RuntimeError("bad signature")

    fake_signxml = MagicMock()
    fake_signxml.XMLVerifier = _RaisingVerifier
    with patch.dict("sys.modules", {"signxml": fake_signxml}), \
            patch.object(ReceptorAuthService, "_extract_embedded_cert_pem", return_value="PEM"), \
            patch.object(ReceptorAuthService, "_subject_sn_from_pem",
                         return_value=("131880681", MagicMock())), \
            patch.object(ReceptorAuthService, "_manual_xmldsig_verify") as manual_verify, \
            patch("app.repositories.receptor_repository.ReceptorRepository.validate_seed", return_value=True), \
            patch("app.repositories.receptor_repository.ReceptorRepository.consume_seed") as consume_seed:
        result, error = ReceptorAuthService.validate_signed_seed(SIGNED_SEED_XML)
        assert error is None
        assert result["subject_sn"] == "131880681"
        manual_verify.assert_called_once()
        consume_seed.assert_called_once_with("abc123semilla")


def test_validate_signed_seed_consumes_only_after_valid_signature():
    class _RaisingVerifier:
        def __init__(self, *args, **kwargs):
            pass

        def verify(self, *args, **kwargs):
            raise RuntimeError("bad signature")

    fake_signxml = MagicMock()
    fake_signxml.XMLVerifier = _RaisingVerifier
    with patch.dict("sys.modules", {"signxml": fake_signxml}), \
            patch.object(ReceptorAuthService, "_extract_embedded_cert_pem", return_value="PEM"), \
            patch.object(ReceptorAuthService, "_manual_xmldsig_verify",
                         side_effect=RuntimeError("tampoco verifica manual")), \
            patch("app.repositories.receptor_repository.ReceptorRepository.validate_seed", return_value=True), \
            patch("app.repositories.receptor_repository.ReceptorRepository.consume_seed") as consume_seed:
        result, error = ReceptorAuthService.validate_signed_seed(SIGNED_SEED_XML)
        assert result is None
        assert "Firma digital" in error
        consume_seed.assert_not_called()


def test_fe_routes_exempt_from_csrf(app):
    app.config["WTF_CSRF_ENABLED"] = True
    client = app.test_client()
    with patch("app.api.v1.receptor.ReceptorRepository.get_token_global", return_value=None):
        resp = client.post(
            "/fe/recepcion/api/ecf",
            data=b"<xml/>",
            content_type="application/xml",
        )
        assert resp.status_code == 401


# ── Verificador XMLDSig manual (equivalente .NET SignedXml) ──────────────────

DS = "http://www.w3.org/2000/09/xmldsig#"


def _build_signed_seed_root(digest_value, uri="", add_id=False):
    nsmap = {"ds": DS}
    root = etree.Element("SemillaModel", nsmap={
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsd": "http://www.w3.org/2001/XMLSchema",
    })
    if add_id:
        root.set("Id", "seed-id-1")
    etree.SubElement(root, "valor").text = "abc123semilla"
    etree.SubElement(root, "fecha").text = "2026-08-31T10:00:00.000-04:00"
    signature = etree.SubElement(root, "{%s}Signature" % DS, nsmap=nsmap)
    signed_info = etree.SubElement(signature, "{%s}SignedInfo" % DS)
    c14n_method = etree.SubElement(signed_info, "{%s}CanonicalizationMethod" % DS)
    c14n_method.set("Algorithm", "http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
    sig_method = etree.SubElement(signed_info, "{%s}SignatureMethod" % DS)
    sig_method.set("Algorithm", "%srsa-sha256" % DS)
    reference = etree.SubElement(signed_info, "{%s}Reference" % DS)
    if uri:
        reference.set("URI", uri)
    transforms = etree.SubElement(reference, "{%s}Transforms" % DS)
    transform = etree.SubElement(transforms, "{%s}Transform" % DS)
    transform.set("Algorithm", "%senveloped-signature" % DS)
    digest_method = etree.SubElement(reference, "{%s}DigestMethod" % DS)
    digest_method.set("Algorithm", "%ssha256" % DS)
    etree.SubElement(reference, "{%s}DigestValue" % DS).text = digest_value
    etree.SubElement(signature, "{%s}SignatureValue" % DS).text = "c2lnbmF0dXJl"
    key_info = etree.SubElement(signature, "{%s}KeyInfo" % DS)
    x509_data = etree.SubElement(key_info, "{%s}X509Data" % DS)
    etree.SubElement(x509_data, "{%s}X509Certificate" % DS).text = "Y2VydA=="
    return root


def _expected_digest(root, uri="", add_id=False):
    import hashlib
    copy = etree.fromstring(etree.tostring(root))
    if not uri:
        sig = copy.find(".//ds:Signature", namespaces={"ds": DS})
        if sig is not None:
            copy.remove(sig)
    else:
        for elem in copy.iter():
            if elem.get("Id") == uri[1:]:
                copy = elem
                break
        sig = copy.find(".//ds:Signature", namespaces={"ds": DS})
        if sig is not None:
            copy.remove(sig)
    c14n = etree.tostring(copy, method="c14n", exclusive=False, with_comments=False)
    return base64.b64encode(hashlib.new("sha256", c14n).digest()).decode()


def test_manual_verifier_checks_reference_digest_and_signature():
    from app.services import receptor_auth_service
    base_root = _build_signed_seed_root("")
    expected = _expected_digest(base_root)
    root = _build_signed_seed_root(expected)
    fake_cert = MagicMock()
    verify_mock = MagicMock()
    fake_cert.public_key.return_value.verify = verify_mock
    with patch.object(receptor_auth_service.x509, "load_pem_x509_certificate", return_value=fake_cert):
        receptor_auth_service.ReceptorAuthService._manual_xmldsig_verify(root, "PEM")
    assert verify_mock.call_count == 1
    expected_si = receptor_auth_service.ReceptorAuthService._signed_info_c14n(
        root, {"ds": DS}, exclusive=False
    )
    assert verify_mock.call_args[0][1] == expected_si


def test_manual_verifier_rejects_bad_digest():
    from app.services import receptor_auth_service
    root = _build_signed_seed_root("QUJDRA==")
    with pytest.raises(ValueError, match="Digest de referencia"):
        receptor_auth_service.ReceptorAuthService._manual_xmldsig_verify(root, "PEM")


def test_manual_verifier_resolves_reference_by_id():
    from app.services import receptor_auth_service
    base_root = _build_signed_seed_root("", uri="#seed-id-1", add_id=True)
    expected = _expected_digest(base_root, uri="#seed-id-1", add_id=True)
    root = _build_signed_seed_root(expected, uri="#seed-id-1", add_id=True)
    fake_cert = MagicMock()
    fake_cert.public_key.return_value.verify = MagicMock()
    with patch.object(receptor_auth_service.x509, "load_pem_x509_certificate", return_value=fake_cert):
        receptor_auth_service.ReceptorAuthService._manual_xmldsig_verify(root, "PEM")
    assert fake_cert.public_key.return_value.verify.call_count == 1


def test_manual_verifier_rejects_missing_signature():
    from app.services import receptor_auth_service
    root = etree.Element("SemillaModel")
    etree.SubElement(root, "valor").text = "abc"
    with pytest.raises(ValueError, match="ds:Signature"):
        receptor_auth_service.ReceptorAuthService._manual_xmldsig_verify(root, "PEM")


def test_signxml_retries_use_id_attribute_in_verify():
    class _FakeVerifier:
        def __init__(self):
            pass

        def verify(self, *args, **kwargs):
            if "id_attribute" not in kwargs:
                raise RuntimeError("sin id_attribute")
            return MagicMock()

    fake_signxml = MagicMock()
    fake_signxml.XMLVerifier = _FakeVerifier
    with patch.dict("sys.modules", {"signxml": fake_signxml}), \
            patch.object(ReceptorAuthService, "_extract_embedded_cert_pem", return_value="PEM"), \
            patch.object(ReceptorAuthService, "_subject_sn_from_pem",
                         return_value=("131880681", MagicMock())), \
            patch.object(ReceptorAuthService, "_manual_xmldsig_verify") as manual_verify, \
            patch("app.repositories.receptor_repository.ReceptorRepository.validate_seed", return_value=True), \
            patch("app.repositories.receptor_repository.ReceptorRepository.consume_seed"):
        result, error = ReceptorAuthService.validate_signed_seed(SIGNED_SEED_XML)
        assert error is None
        assert result["subject_sn"] == "131880681"
        manual_verify.assert_not_called()


def test_rejected_seed_saved_to_diagnostics(client):
    with patch.object(ReceptorAuthService, "validate_signed_seed",
                      return_value=(None, "Firma digital no válida: prueba")), \
            patch("app.api.v1.receptor.ReceptorRepository.save_diagnostic") as save_diag:
        resp = client.post(
            "/fe/autenticacion/api/ValidacionCertificado",
            data=b"<SemillaModel><valor>abc</valor></SemillaModel>",
            content_type="application/xml",
        )
        assert resp.status_code == 400
        save_diag.assert_called_once()
        diag = save_diag.call_args[0][0]
        assert diag["endpoint"] == "validacioncertificado"
        assert "Firma digital no válida" in diag["error"]
        assert "<SemillaModel>" in diag["payload"]


# ── Regresión con el payload real de la DGII (firma estilo Java/.NET) ───────

DGII_DIGEST_VALUE = "WeHtTkuDh8NJ30+Kq5CkNGjzB/ORF0pn3FW7ppNiPYM="

DGII_SIGNED_INFO_C14N = (
    '<SignedInfo xmlns="http://www.w3.org/2000/09/xmldsig#" '
    'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    '<CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"></CanonicalizationMethod>'
    '<SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"></SignatureMethod>'
    '<Reference URI=""><Transforms>'
    '<Transform Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature"></Transform>'
    '</Transforms>'
    '<DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"></DigestMethod>'
    '<DigestValue>WeHtTkuDh8NJ30+Kq5CkNGjzB/ORF0pn3FW7ppNiPYM=</DigestValue>'
    '</Reference></SignedInfo>'
)


def _build_dgii_style_seed_root():
    """Réplica del payload real enviado por la DGII (Signature con default ns)."""
    root = etree.Element("SemillaModel", nsmap={
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsd": "http://www.w3.org/2001/XMLSchema",
    })
    etree.SubElement(root, "valor").text = "6816b0b89aa2443085eb4fb01afe44b35c5a1be45f1e4568b61b5e703469011c"
    etree.SubElement(root, "fecha").text = "2026-08-31T20:46:05.162-04:00"
    signature = etree.SubElement(root, "{%s}Signature" % DS, nsmap={None: DS})
    signed_info = etree.SubElement(signature, "{%s}SignedInfo" % DS)
    cm = etree.SubElement(signed_info, "{%s}CanonicalizationMethod" % DS)
    cm.set("Algorithm", "http://www.w3.org/TR/2001/REC-xml-c14n-20010315")
    sm = etree.SubElement(signed_info, "{%s}SignatureMethod" % DS)
    sm.set("Algorithm", "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256")
    ref = etree.SubElement(signed_info, "{%s}Reference" % DS)
    ref.set("URI", "")
    tr = etree.SubElement(ref, "{%s}Transforms" % DS)
    t = etree.SubElement(tr, "{%s}Transform" % DS)
    t.set("Algorithm", "%senveloped-signature" % DS)
    dm = etree.SubElement(ref, "{%s}DigestMethod" % DS)
    dm.set("Algorithm", "http://www.w3.org/2001/04/xmlenc#sha256")
    dv = etree.SubElement(ref, "{%s}DigestValue" % DS)
    dv.text = DGII_DIGEST_VALUE
    etree.SubElement(signature, "{%s}SignatureValue" % DS).text = "c2lnbmF0dXJl"
    return root


def test_signed_info_c14n_matches_dgii_bytes():
    from app.services import receptor_auth_service
    root = _build_dgii_style_seed_root()
    c14n = receptor_auth_service.ReceptorAuthService._signed_info_c14n(root, {"ds": DS}, exclusive=False)
    assert c14n.decode("utf-8") == DGII_SIGNED_INFO_C14N


def test_manual_verifier_signs_over_dgii_style_c14n():
    from app.services import receptor_auth_service
    root = _build_dgii_style_seed_root()
    fake_cert = MagicMock()
    verify_mock = MagicMock()
    fake_cert.public_key.return_value.verify = verify_mock
    with patch.object(receptor_auth_service.x509, "load_pem_x509_certificate", return_value=fake_cert):
        receptor_auth_service.ReceptorAuthService._manual_xmldsig_verify(root, "PEM")
    assert verify_mock.call_count == 1
    assert verify_mock.call_args[0][1] == DGII_SIGNED_INFO_C14N.encode("utf-8")


# ── Recepción e-CF ─────────────────────────────────────────────────────────

def _recepcion_headers():
    return {"Authorization": "Bearer token-de-prueba"}


def _post_ecf(client, xml=ECF_XML, headers=None):
    return client.post(
        "/fe/recepcion/api/ecf",
        data={"xml": (io.BytesIO(xml.encode("utf-8")), "ecf.xml")},
        content_type="multipart/form-data",
        headers=headers or _recepcion_headers(),
    )


def _patch_auth_and_company(comprador_rnc="131880681", owner_uid="owner-1"):
    token_doc = {
        "token": "token-de-prueba",
        "taxpayer_rnc": "00199999996",
        "owner_uid": "",
        "expires_at": "2999-01-01T00:00:00+00:00",
    }
    profile = {
        "companyRNC": comprador_rnc,
        "companyName": "COMPRADOR SRL",
        "certificateContent": "",
        "certificatePassword": "",
    }
    return (
        patch("app.api.v1.receptor.ReceptorRepository.get_token_global", return_value=token_doc),
        patch.object(ReceptorAuthService, "resolve_company_by_rnc",
                     return_value=(owner_uid, profile)),
    )


def test_recepcion_ecf_returns_arecf_estado_0(client):
    with _patch_auth_and_company()[0], _patch_auth_and_company()[1], \
            patch("app.api.v1.receptor.ReceptorXmlService.verify_signature", return_value=(None, "sin firma")), \
            patch("app.api.v1.receptor.ReceptorRepository.find_received_by_encf", return_value=None), \
            patch("app.api.v1.receptor.ReceptorRepository.save_received_ecf"):
        resp = _post_ecf(client)
        assert resp.status_code == 200
        assert resp.headers["Content-Type"].startswith("application/xml")
        root = etree.fromstring(resp.data)
        assert root.tag == "ARECF"
        detalle = root.find("DetalleAcusedeRecibo")
        assert detalle is not None
        assert detalle.find("Version").text == "1.0"
        assert detalle.find("RNCEmisor").text == "132109122"
        assert detalle.find("RNCComprador").text == "131880681"
        assert detalle.find("eNCF").text == "E310000000001"
        assert detalle.find("Estado").text == "0"
        assert detalle.find("CodigoMotivoNoRecibido") is None
        assert detalle.find("FechaHoraAcuseRecibo") is not None


def test_recepcion_ecf_rejects_duplicate(client):
    with _patch_auth_and_company()[0], _patch_auth_and_company()[1], \
            patch("app.api.v1.receptor.ReceptorXmlService.verify_signature", return_value=(None, "sin firma")), \
            patch("app.api.v1.receptor.ReceptorRepository.find_received_by_encf", return_value={"id": "dup"}), \
            patch("app.api.v1.receptor.ReceptorRepository.save_received_ecf"):
        resp = _post_ecf(client)
        root = etree.fromstring(resp.data)
        detalle = root.find("DetalleAcusedeRecibo")
        assert detalle.find("Estado").text == "1"
        assert detalle.find("CodigoMotivoNoRecibido").text == "3"


def test_recepcion_ecf_rejects_rnc_mismatch(client):
    from app.api.v1 import receptor as receptor_module
    wrong_buyer = ECF_XML.replace("131880681", "999999999")
    profile = {"companyRNC": "131880681", "companyName": "COMPRADOR SRL",
               "certificateContent": "", "certificatePassword": ""}
    with patch("app.api.v1.receptor.ReceptorRepository.get_token_global",
               return_value={"token": "token-de-prueba", "taxpayer_rnc": "00199999996",
                             "owner_uid": "", "expires_at": "2999-01-01T00:00:00+00:00"}), \
            patch.object(receptor_module.Config, "RECEPTOR_DEFAULT_OWNER_UID", "default-owner"), \
            patch.object(ReceptorAuthService, "resolve_company_by_rnc", return_value=(None, None)), \
            patch("app.api.v1.receptor.DatabaseService.get_company_profile", return_value=profile), \
            patch("app.api.v1.receptor.ReceptorXmlService.verify_signature", return_value=(None, "sin firma")), \
            patch("app.api.v1.receptor.ReceptorRepository.find_received_by_encf", return_value=None), \
            patch("app.api.v1.receptor.ReceptorRepository.save_received_ecf"):
        resp = _post_ecf(client, xml=wrong_buyer)
        root = etree.fromstring(resp.data)
        detalle = root.find("DetalleAcusedeRecibo")
        assert detalle.find("Estado").text == "1"
        assert detalle.find("CodigoMotivoNoRecibido").text == "4"


def test_recepcion_ecf_unknown_comprador_without_fallback_returns_404(client):
    wrong_buyer = ECF_XML.replace("131880681", "999999999")
    with patch("app.api.v1.receptor.ReceptorRepository.get_token_global",
               return_value={"token": "token-de-prueba", "taxpayer_rnc": "00199999996",
                             "owner_uid": "", "expires_at": "2999-01-01T00:00:00+00:00"}), \
            patch.object(ReceptorAuthService, "resolve_company_by_rnc", return_value=(None, None)):
        resp = _post_ecf(client, xml=wrong_buyer)
        assert resp.status_code == 404
        assert "999999999" in resp.get_json()["error"]


def test_recepcion_ecf_requires_token(client):
    with patch("app.api.v1.receptor.ReceptorRepository.get_token_global", return_value=None):
        resp = _post_ecf(client, headers={})
        assert resp.status_code == 401


def test_recepcion_ecf_resolves_company_by_comprador_rnc(client):
    token_doc = {
        "token": "token-de-prueba",
        "taxpayer_rnc": "00199999996",
        "owner_uid": "",
        "expires_at": "2999-01-01T00:00:00+00:00",
    }
    profile = {"companyRNC": "131880681", "companyName": "COMPRADOR SRL",
               "certificateContent": "", "certificatePassword": ""}
    with patch("app.api.v1.receptor.ReceptorRepository.get_token_global", return_value=token_doc), \
            patch.object(ReceptorAuthService, "resolve_company_by_rnc",
                         return_value=("owner-1", profile)) as resolve, \
            patch("app.api.v1.receptor.ReceptorXmlService.verify_signature", return_value=(None, "sin firma")), \
            patch("app.api.v1.receptor.ReceptorRepository.find_received_by_encf", return_value=None), \
            patch("app.api.v1.receptor.ReceptorRepository.save_received_ecf"):
        resp = _post_ecf(client)
        assert resp.status_code == 200
        resolve.assert_called_once_with("131880681")


def test_recepcion_ecf_multitenant_resolves_by_comprador_per_request(client):
    profile_a = {"companyRNC": "131880681", "companyName": "EMPRESA A",
                 "certificateContent": "", "certificatePassword": ""}
    profile_b = {"companyRNC": "133753652", "companyName": "EMPRESA B",
                 "certificateContent": "", "certificatePassword": ""}
    token_doc = {
        "token": "token-de-prueba",
        "taxpayer_rnc": "00199999996",
        "owner_uid": "",
        "expires_at": "2999-01-01T00:00:00+00:00",
    }

    def _resolve(rnc):
        if rnc == "131880681":
            return "owner-a", profile_a
        if rnc == "133753652":
            return "owner-b", profile_b
        return None, None

    ecf_b = ECF_XML.replace("131880681", "133753652")
    with patch("app.api.v1.receptor.ReceptorRepository.get_token_global", return_value=token_doc), \
            patch.object(ReceptorAuthService, "resolve_company_by_rnc", side_effect=_resolve) as resolve, \
            patch("app.api.v1.receptor.ReceptorXmlService.verify_signature", return_value=(None, "sin firma")), \
            patch("app.api.v1.receptor.ReceptorRepository.find_received_by_encf", return_value=None), \
            patch("app.api.v1.receptor.ReceptorRepository.save_received_ecf") as save:
        resp_a = _post_ecf(client)
        resp_b = _post_ecf(client, xml=ecf_b)
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        assert etree.fromstring(resp_a.data).find("DetalleAcusedeRecibo/RNCComprador").text == "131880681"
        assert etree.fromstring(resp_b.data).find("DetalleAcusedeRecibo/RNCComprador").text == "133753652"
        assert [c.args[0] for c in resolve.call_args_list] == ["131880681", "133753652"]
        assert save.call_count == 2


# ── Formato ARECF contra XSD oficial ───────────────────────────────────────

def _sanitized_arecf_xsd():
    xsd_path = os.path.join(os.path.dirname(__file__), "..", "Schemas", "ARECF v1.0.xsd")
    with open(xsd_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace("{13,13}", "{13}").replace("{11,11}", "{11}").replace("{9,9}", "{9}")
    return etree.fromstring(content.encode("utf-8"))


def test_arecf_matches_official_xsd():
    parsed = {
        "rnc_emisor": "132109122",
        "encf": "E310000000001",
    }
    xml_bytes, track_id = ReceptorXmlService.build_arecf("131880681", parsed)
    schema_doc = _sanitized_arecf_xsd()
    schema = etree.XMLSchema(schema_doc)
    root = etree.fromstring(xml_bytes)
    assert schema.validate(root), schema.error_log
    assert track_id and len(track_id) == 20


def test_arecf_with_motivo_matches_official_xsd():
    parsed = {"rnc_emisor": "132109122", "encf": "E310000000001"}
    xml_bytes, _ = ReceptorXmlService.build_arecf("131880681", parsed, estado="1", codigo_motivo="2")
    schema = etree.XMLSchema(_sanitized_arecf_xsd())
    root = etree.fromstring(xml_bytes)
    assert root.find("DetalleAcusedeRecibo/CodigoMotivoNoRecibido").text == "2"
    assert schema.validate(root), schema.error_log


# ── Parseo del e-CF namespaced (formato real DGII) ─────────────────────────

def test_parse_ecf_namespaced():
    parsed, error = ReceptorXmlService.parse_ecf(ECF_XML.encode("utf-8"))
    assert error is None
    assert parsed["encf"] == "E310000000001"
    assert parsed["tipo_ecf"] == "31"
    assert parsed["rnc_emisor"] == "132109122"
    assert parsed["rnc_comprador"] == "131880681"
    assert parsed["monto_total"] == 1000.0


def test_parse_ecf_unprefixed():
    xml = ECF_XML.replace(' xmlns="http://www.dgii.gov.do/ecf"', "")
    parsed, error = ReceptorXmlService.parse_ecf(xml.encode("utf-8"))
    assert error is None
    assert parsed["encf"] == "E310000000001"


# ── Lecturas combinadas sandbox + producción (UI /recepcion/ecf) ────────────

class _FakeDoc:
    def __init__(self, doc_id, data, exists=True):
        self.id = doc_id
        self._data = data
        self.exists = exists

    def to_dict(self):
        return self._data

    def get(self):
        return self


class _FakeColl:
    def __init__(self, docs):
        self._docs = docs

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, n):
        return self

    def stream(self):
        return iter(self._docs)

    def document(self, doc_id):
        for d in self._docs:
            if d.id == doc_id:
                return d
        return _FakeDoc(doc_id, None, exists=False)


def _doc(id_, received_at, status="recibido", **extra):
    data = {"received_at": received_at, "status": status}
    data.update(extra)
    return _FakeDoc(id_, data)


def test_list_received_ecf_merged_combines_both_collections():
    from app.repositories.receptor_repository import ReceptorRepository
    sandbox = _FakeColl([_doc("s1", "2026-08-31T10:00:00+00:00", encf="E310000000001")])
    prod = _FakeColl([
        _doc("p1", "2026-08-31T12:00:00+00:00", encf="E310000000002"),
        _doc("p2", "2026-08-31T11:00:00+00:00", encf="E310000000003"),
    ])
    with patch.object(ReceptorRepository, "_receptor_collections", return_value=[sandbox, prod]):
        docs = ReceptorRepository.list_received_ecf_merged("owner-1")
        assert [d["id"] for d in docs] == ["p1", "p2", "s1"]


def test_list_received_ecf_merged_filters_status_in_memory():
    from app.repositories.receptor_repository import ReceptorRepository
    coll = _FakeColl([
        _doc("a", "2026-08-31T10:00:00+00:00", status="recibido"),
        _doc("b", "2026-08-31T11:00:00+00:00", status="rechazado"),
    ])
    with patch.object(ReceptorRepository, "_receptor_collections", return_value=[coll]):
        docs = ReceptorRepository.list_received_ecf_merged("owner-1", status="recibido")
        assert [d["id"] for d in docs] == ["a"]


def test_get_received_ecf_merged_finds_across_collections():
    from app.repositories.receptor_repository import ReceptorRepository
    sandbox = _FakeColl([])
    prod = _FakeColl([_doc("p9", "2026-08-31T12:00:00+00:00", encf="E310000000009")])
    with patch.object(ReceptorRepository, "_receptor_collections", return_value=[sandbox, prod]):
        doc = ReceptorRepository.get_received_ecf_merged("owner-1", "p9")
        assert doc is not None and doc["encf"] == "E310000000009"
        assert ReceptorRepository.get_received_ecf_merged("owner-1", "missing") is None
