import base64
import hashlib
import re
from config import Config

try:
    from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
except Exception:
    pkcs12 = None
    Encoding = None
    PrivateFormat = None
    NoEncryption = None
    hashes = None
    padding = None

class DgiiSigner:

    @classmethod
    def _extract_xml_tag_bytes(cls, xml_bytes, tag):
        try:
            text = xml_bytes.decode("utf-8", errors="ignore") if isinstance(xml_bytes, bytes) else str(xml_bytes)
        except Exception:
            return ""
        m = re.search(rf"<{tag}[^>]*>([^<]+)</{tag}>", text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    @classmethod
    def extract_fecha_hora_firma(cls, xml_bytes):
        """Fecha y hora real de la firma digital (dd-MM-aaaa HH:mm:ss) del XML firmado."""
        return cls._extract_xml_tag_bytes(xml_bytes, "FechaHoraFirma")

    @classmethod
    def extract_fecha_vencimiento_secuencia(cls, xml_bytes):
        """Fecha de vencimiento de la secuencia e-NCF (dd-MM-aaaa) del XML firmado."""
        return cls._extract_xml_tag_bytes(xml_bytes, "FechaVencimientoSecuencia")

    @classmethod
    def _sign_mode(cls):
        return (getattr(Config, "DGII_SIGNING_MODE", "mock") or "mock").lower()

    @classmethod
    def load_pkcs12(cls, company_profile):
        cert_content_b64 = company_profile.get("certificateContent") or company_profile.get("certificate_content")
        if not cert_content_b64:
            return None, None, None
        if pkcs12 is None:
            raise RuntimeError("cryptography no está disponible para cargar certificados PKCS#12.")

        cert_password = company_profile.get("certificatePassword") or company_profile.get("certificate_password") or ""
        cert_data = base64.b64decode(cert_content_b64)
        return pkcs12.load_key_and_certificates(
            cert_data,
            cert_password.encode("utf-8") if cert_password else None
        )

    @classmethod
    def export_pem_bundle(cls, company_profile):
        private_key, certificate, additional_certs = cls.load_pkcs12(company_profile)
        if not private_key or not certificate:
            return None

        key_pem = private_key.private_bytes(
            Encoding.PEM,
            PrivateFormat.TraditionalOpenSSL,
            NoEncryption()
        )
        cert_pem = certificate.public_bytes(Encoding.PEM)
        chain_pem = b"".join([
            cert.public_bytes(Encoding.PEM) for cert in (additional_certs or [])
        ])
        return cert_pem, key_pem, chain_pem
    
    @classmethod
    def _validate_certificate_subject(cls, company_profile):
        try:
            from cryptography import x509
        except Exception:
            return
        _pk, certificate, _add = cls.load_pkcs12(company_profile)
        if not certificate:
            return
        sn_attrs = certificate.subject.get_attributes_for_oid(x509.oid.NameOID.SERIAL_NUMBER)
        if not sn_attrs:
            raise ValueError("El certificado digital no tiene campo SN en el Subject.")
        cert_sn = sn_attrs[0].value.strip()
        cert_sn_clean = cert_sn[6:] if cert_sn.upper().startswith('IDCDO-') else cert_sn
        company_rnc = (company_profile.get("companyRNC") or company_profile.get("rnc") or company_profile.get("company_rnc") or "").replace("-", "").strip()
        if cert_sn_clean != company_rnc:
            import logging
            logging.warning(
                f"El SN del certificado ({cert_sn}) no coincide con el RNC de la empresa ({company_rnc})."
            )

    @classmethod
    def sign_xml(cls, xml_data, company_profile):
        """
        Firma digitalmente un archivo XML usando el formato W3C XMLDSig.
        Utiliza el certificado cargado (.p12/.pfx) en el perfil de la compañía.
        """
        cert_content_b64 = company_profile.get("certificateContent") or company_profile.get("certificate_content")
        sign_mode = cls._sign_mode()

        # Solo usar firma simulada si NO hay certificado cargado y no se exige modo real
        if not cert_content_b64 and sign_mode != "real":
            print("⚠️ [Firma Digital] Advertencia: No hay certificado digital cargado. Generando XML sin firma real (Simulado).", flush=True)
            fake_sig = base64.b64encode(hashlib.sha256(xml_data).digest()).decode("utf-8")
            signed_xml = xml_data.decode("utf-8") + f"\n<!-- SIMULATION_SIGNATURE: {fake_sig} -->"
            return signed_xml.encode("utf-8")

        if not cert_content_b64:
            raise RuntimeError("Se requiere un certificado digital para firmar en modo real.")

        cls._validate_certificate_subject(company_profile)

        try:
            cert_bundle = cls.export_pem_bundle(company_profile)
            if not cert_bundle:
                raise RuntimeError("No se pudo exportar el certificado a PEM.")
            cert_pem, key_pem, chain_pem = cert_bundle

            try:
                from signxml import XMLSigner, methods
                from lxml import etree
            except Exception as e:
                raise RuntimeError("Falta instalar signxml/lxml para firma real.") from e

            parser = etree.XMLParser(remove_blank_text=True)
            xml_root = etree.fromstring(xml_data, parser=parser)
            signer = XMLSigner(
                method=methods.enveloped,
                signature_algorithm="rsa-sha256",
                digest_algorithm="sha256",
                c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
            )
            signed_root = signer.sign(xml_root, key=key_pem, cert=cert_pem + chain_pem)
            signed_xml = etree.tostring(signed_root, encoding="utf-8", xml_declaration=True)
            return signed_xml

        except Exception as e:
            print(f"❌ [Firma Digital] Error al firmar XML: {e}", flush=True)
            raise RuntimeError(f"Fallo al firmar digitalmente el XML: {str(e)}")

    @classmethod
    def sign_seed(cls, seed, company_profile):
        if not seed:
            return None
        seed_bytes = seed if isinstance(seed, (bytes, bytearray)) else str(seed).encode("utf-8")
        if cls._sign_mode() != "real":
            return base64.b64encode(hashlib.sha256(seed_bytes).digest()).decode("utf-8")

        if pkcs12 is None:
            raise RuntimeError("cryptography no está disponible para firmar la semilla.")

        private_key, _certificate, _additional = cls.load_pkcs12(company_profile)
        if not private_key:
            raise RuntimeError("No se pudo cargar el certificado para firmar la semilla.")

        signature = private_key.sign(seed_bytes, padding.PKCS1v15(), hashes.SHA256())
        return base64.b64encode(signature).decode("utf-8")

    @staticmethod
    def extract_signature_value(xml_data):
        if not xml_data:
            return None
        xml_text = xml_data.decode("utf-8", errors="ignore") if isinstance(xml_data, (bytes, bytearray)) else str(xml_data)
        match = re.search(r"<(?:ds:)?SignatureValue>([^<]+)</(?:ds:)?SignatureValue>", xml_text)
        return match.group(1).strip() if match else None
