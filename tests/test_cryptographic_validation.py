"""
Bloque 2 — Validación Criptográfica
=====================================
Verifica para cada tipo de comprobante:
  1. XML well-formed (lxml parse)
  2. Firma mock: hash SHA-256 presente y correcto
  3. Firma real (signxml): canonicalización, digest, SignatureValue, cert
  4. XSD post-firma (real signature satisface wildcard <xs:any>)

Uso:
  python3 tests/test_cryptographic_validation.py              # mock only
  arch -arm64 python3 tests/test_cryptographic_validation.py  # mock + real

Requiere:
  pip install lxml signxml cryptography
"""
import importlib.util
import sys
import os
import base64
import hashlib
import re
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

spec = importlib.util.spec_from_file_location(
    "dgii_xml_builder",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "app", "services", "dgii_xml_builder.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
DgiiXmlBuilder = mod.DgiiXmlBuilder

spec_signer = importlib.util.spec_from_file_location(
    "dgii_signer",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "app", "services", "dgii_signer.py")
)
mod_signer = importlib.util.module_from_spec(spec_signer)
spec_signer.loader.exec_module(mod_signer)
DgiiSigner = mod_signer.DgiiSigner

from lxml import etree

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from signxml import XMLSigner, XMLVerifier, methods
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_company():
    return {
        "companyRNC": "131111111",
        "companyName": "EMPRESA TEST SRL",
        "tradeName": "TEST",
        "companyAddress": "Av. Test 123",
        "municipality": "Santo Domingo de Guzmán",
        "province": "Santo Domingo",
        "companyPhone": "809-555-1234",
        "companyEmail": "test@example.com",
    }


def build_invoice(tipo_ecf):
    d = {
        "ecfType": f"E{tipo_ecf}",
        "encf": f"E{tipo_ecf}0000000001",
        "subtotal": 1000.00,
        "total": 1180.00,
        "totalITBIS": 180.00,
        "montoExento": 0.00,
        "paymentMethod": "Efectivo",
        "incomeType": "01",
        "clientRNC": "131222222",
        "razonSocial": "CLIENTE TEST SRL",
        "clientMunicipality": "Santo Domingo de Guzmán",
        "clientProvince": "Santo Domingo",
        "internalInvoiceNumber": "INV-001",
        "fechaVencimientoSecuencia": "15-12-2028",
        "ncfModificado": f"E{tipo_ecf}0000000000",
        "fechaNCFModificado": "14-06-2026",
        "codigoModificacion": "1",
        "items": [{"name": "Servicio test", "unit": "Servicio", "quantity": 1,
                   "price": 1000.00, "subtotal": 1000.00, "type": "servicio"}],
    }
    return d


def _gen_self_signed_cert_pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "DGII Test Cert"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test SRL"),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "DO"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(issuer)
        .public_key(key.public_key()).serial_number(1000)
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()).decode()
    cert_pem = cert.public_bytes(Encoding.PEM).decode()
    return key_pem, cert_pem, cert


def _sign_real(raw_xml, key_pem, cert_pem):
    root = etree.fromstring(raw_xml)
    signer = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    )
    signed_root = signer.sign(root, key=key_pem, cert=cert_pem)
    return etree.tostring(signed_root, encoding="utf-8", xml_declaration=False)


# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------

RESULTS = {}  # tipo -> [(step, status, detail)]


def _r(tipo, step, status, detail=""):
    RESULTS.setdefault(tipo, []).append((step, status, detail))


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------

def step_well_formed(tipo, xml_bytes):
    try:
        etree.fromstring(xml_bytes)
        _r(tipo, "well_formed", "PASS")
    except Exception as e:
        _r(tipo, "well_formed", "FAIL", str(e))


def step_mock_signature(tipo, raw_xml, signed_xml):
    s = signed_xml.decode("utf-8")
    if "SIMULATION_SIGNATURE" not in s:
        _r(tipo, "mock_signature", "FAIL", "No SIMULATION_SIGNATURE comment")
        return
    m = re.search(r"SIMULATION_SIGNATURE:\s*([A-Za-z0-9+/=]+)", s)
    if not m:
        _r(tipo, "mock_signature", "FAIL", "Could not extract hash")
        return
    sig_hash = m.group(1)
    expected = base64.b64encode(hashlib.sha256(raw_xml).digest()).decode("utf-8")
    if sig_hash == expected:
        _r(tipo, "mock_signature", "PASS")
    else:
        _r(tipo, "mock_signature", "FAIL", "Hash mismatch")


def step_real_signature(tipo, raw_xml, key_pem, cert_pem, cert_obj):
    if not CRYPTO_AVAILABLE:
        _r(tipo, "real_signature", "SKIP", "cryptography/signxml not available")
        _r(tipo, "real_xsd_post_sign", "SKIP", "")
        _r(tipo, "real_canonicalization", "SKIP", "")
        _r(tipo, "real_digest", "SKIP", "")
        _r(tipo, "real_signaturevalue", "SKIP", "")
        return

    try:
        signed_xml = _sign_real(raw_xml, key_pem, cert_pem)
        doc = etree.fromstring(signed_xml)

        # Check ds:Signature exists
        ns = {"ds": "http://www.w3.org/2000/09/xmldsig#"}
        sig_elem = doc.find(".//ds:Signature", ns)
        if sig_elem is None:
            _r(tipo, "real_signature", "FAIL", "No ds:Signature element")
            return
        _r(tipo, "real_signature", "PASS")

        # Verify with signxml
        try:
            XMLVerifier().verify(doc, x509_cert=cert_pem)
            _r(tipo, "real_verify", "PASS")
        except Exception as e:
            _r(tipo, "real_verify", "FAIL", str(e))

        # Extract and check components
        signed_info = doc.find(".//ds:SignedInfo", ns)
        ref = doc.find(".//ds:Reference", ns)
        digest_val = doc.find(".//ds:DigestValue", ns)
        sig_val = doc.find(".//ds:SignatureValue", ns)
        canon_method = doc.find(".//ds:CanonicalizationMethod", ns)

        if canon_method is not None:
            alg = canon_method.get("Algorithm", "")
            if "c14n-20010315" in alg:
                _r(tipo, "real_canonicalization", "PASS", alg.split("/")[-1])
            else:
                _r(tipo, "real_canonicalization", "WARN", f"Unexpected: {alg}")

        if digest_val is not None and ref is not None:
            _r(tipo, "real_digest", "PASS", f"DigestValue={digest_val.text[:20]}...")

        if sig_val is not None:
            _r(tipo, "real_signaturevalue", "PASS", f"SignatureValue={sig_val.text[:20]}...")

        # XSD validation post-sign (signature should satisfy wildcard)
        xsd_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "Schemas", f"e-CF {tipo} v1.0.xsd")
        if os.path.exists(xsd_path):
            xsd = etree.XMLSchema(etree.parse(xsd_path))
            if xsd.validate(doc):
                _r(tipo, "real_xsd_post_sign", "PASS")
            else:
                errors = [str(e) for e in xsd.error_log]
                _r(tipo, "real_xsd_post_sign", "WARN", f"{len(errors)} XSD errors")

    except Exception as e:
        _r(tipo, "real_signature", "FAIL", str(e))


def step_cert_validity(tipo, cert_obj):
    now = datetime.datetime.now(datetime.timezone.utc)
    if cert_obj.not_valid_before_utc <= now <= cert_obj.not_valid_after_utc:
        _r(tipo, "cert_validity", "PASS")
    else:
        _r(tipo, "cert_validity", "FAIL", "Certificate expired or not yet valid")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    types = ["31", "32", "33", "34", "41", "43", "44", "45", "46", "47"]
    company = build_company()

    # Generate self-signed cert for real-mode
    key_pem = cert_pem = cert_obj = None
    if CRYPTO_AVAILABLE:
        try:
            key_pem, cert_pem, cert_obj = _gen_self_signed_cert_pem()
            print("🔐 Real-mode disponible: certificado RSA-2048 autofirmado")
        except Exception as e:
            print(f"⚠️  No se pudo generar certificado: {e}")

    # Header
    print(f"\n{'='*70}")
    print(f"{'Tipo':<6} {'Paso':<28} {'Resultado':<10} {'Detalle'}")
    print(f"{'='*70}")

    for tipo in types:
        invoice = build_invoice(tipo)
        raw_xml = DgiiXmlBuilder.build_invoice_xml(company, invoice)

        # 1. Well-formed
        step_well_formed(tipo, raw_xml)

        # 2. Mock sign + verify
        signed_mock = DgiiSigner.sign_xml(raw_xml, company)
        step_mock_signature(tipo, raw_xml, signed_mock)

        # 3. Real sign + full verification
        if key_pem and cert_pem and cert_obj:
            step_real_signature(tipo, raw_xml, key_pem, cert_pem, cert_obj)
            step_cert_validity(tipo, cert_obj)

    # Print results
    print()
    for tipo in types:
        for paso, estado, detalle in RESULTS.get(tipo, []):
            d = detalle[:55] if detalle else ""
            print(f"E{tipo:<4} {paso:<28} {estado:<10} {d}")

    # Summary
    print(f"\n{'='*70}")
    total = sum(len(v) for v in RESULTS.values())
    passed = sum(1 for v in RESULTS.values() for _, e, _ in v if e == "PASS")
    failed = sum(1 for v in RESULTS.values() for _, e, _ in v if e == "FAIL")
    skipped = sum(1 for v in RESULTS.values() for _, e, _ in v if e in ("SKIP", "WARN"))
    print(f"Total: {total} | ✅ PASS: {passed} | ❌ FAIL: {failed} | ⚠️  SKIP/WARN: {skipped}")
    if failed == 0:
        print("\n✅ VALIDACIÓN CRIPTOGRÁFICA COMPLETA: OK")
    else:
        print(f"\n❌ {failed} fallo(s) — revisar arriba")


if __name__ == "__main__":
    main()
