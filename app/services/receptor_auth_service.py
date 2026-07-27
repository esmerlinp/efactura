import base64
import uuid
from datetime import datetime, timezone, timedelta
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography import x509
from lxml import etree
from config import Config


class ReceptorAuthService:

    @staticmethod
    def generate_seed_xml():
        seed = uuid.uuid4().hex + uuid.uuid4().hex
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "-04:00"
        root = etree.Element("semillamodel", nsmap={
            "xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsd": "http://www.w3.org/2001/XMLSchema"
        })
        etree.SubElement(root, "valor").text = seed
        etree.SubElement(root, "fecha").text = now
        xml_bytes = etree.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=True)
        return xml_bytes.decode("utf-8"), seed

    @staticmethod
    def validate_signed_seed(signed_seed_xml_bytes, expected_seed):
        try:
            root = etree.fromstring(signed_seed_xml_bytes)
        except Exception as e:
            return None, f"XML inválido: {str(e)}"

        seed_elem = root.find(".//Semilla") or root.find(".//semilla") or root.find(".//valor")
        signature_elem = root.find(".//Firma") or root.find(".//firma") or root.find(".//SignatureValue")

        if seed_elem is None or signature_elem is None:
            return None, "No se encontró Semilla o Firma en el XML."

        submitted_seed = seed_elem.text.strip() if seed_elem.text else ""
        if submitted_seed != expected_seed:
            return None, "La semilla no coincide con la emitida."

        try:
            from cryptography.x509 import load_pem_x509_certificate
            cert_pem_elem = root.find(".//Certificado") or root.find(".//X509Certificate")
            if cert_pem_elem is not None and cert_pem_elem.text:
                cert_pem = cert_pem_elem.text.strip()
                if "-----BEGIN CERTIFICATE-----" not in cert_pem:
                    cert_pem = "-----BEGIN CERTIFICATE-----\n" + cert_pem + "\n-----END CERTIFICATE-----"
                certificate = load_pem_x509_certificate(cert_pem.encode("utf-8"))
            else:
                return None, "No se encontró el certificado en el XML firmado."
        except Exception as e:
            return None, f"Error al cargar el certificado: {str(e)}"

        signature_bytes = base64.b64decode(signature_elem.text.strip())
        public_key = certificate.public_key()
        try:
            public_key.verify(
                signature_bytes,
                submitted_seed.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
        except Exception:
            return None, "La firma digital no es válida para la semilla proporcionada."

        subject_sn = ""
        sn_attrs = certificate.subject.get_attributes_for_oid(x509.oid.NameOID.SERIAL_NUMBER)
        if sn_attrs:
            subject_sn = sn_attrs[0].value.strip()

        return {
            "subject_sn": subject_sn,
            "subject": str(certificate.subject),
            "issuer": str(certificate.issuer),
            "not_before": certificate.not_valid_before_utc.isoformat(),
            "not_after": certificate.not_valid_after_utc.isoformat(),
        }, None

    @staticmethod
    def issue_token(owner_uid, taxpayer_rnc, sandbox=True):
        import hashlib
        raw = f"{owner_uid}:{taxpayer_rnc}:{uuid.uuid4().hex}:{datetime.now(timezone.utc).isoformat()}"
        token = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        issued_at = datetime.now(timezone.utc)
        expiry_minutes = getattr(Config, "RECEPTOR_TOKEN_EXPIRY_MINUTES", 15)
        expires_at = issued_at + timedelta(minutes=expiry_minutes)
        return {
            "token": token,
            "taxpayer_rnc": taxpayer_rnc,
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
