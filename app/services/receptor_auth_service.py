import base64
import logging
import uuid
from datetime import datetime, timezone, timedelta
from cryptography import x509
from lxml import etree
from config import Config

logger = logging.getLogger(__name__)

DS_NS = "http://www.w3.org/2000/09/xmldsig#"


class ReceptorAuthService:

    # ─────────────────────────────────────────────────────────────────
    # Semilla (GET /fe/autenticacion/api/semilla)
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _now_dominican_iso():
        now = datetime.now(timezone.utc) - timedelta(hours=4)
        return now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "-04:00"

    @staticmethod
    def generate_seed_xml():
        seed = uuid.uuid4().hex + uuid.uuid4().hex
        now_str = ReceptorAuthService._now_dominican_iso()
        root = etree.Element("SemillaModel", nsmap={
            "xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsd": "http://www.w3.org/2001/XMLSchema"
        })
        etree.SubElement(root, "valor").text = seed
        etree.SubElement(root, "fecha").text = now_str
        xml_bytes = etree.tostring(root, encoding="utf-8", xml_declaration=True)

        from app.repositories.receptor_repository import ReceptorRepository
        ReceptorRepository.save_seed(seed, datetime.now(timezone.utc).isoformat())
        return xml_bytes.decode("utf-8"), seed

    # ─────────────────────────────────────────────────────────────────
    # Validación de semilla firmada (POST ValidacionCertificado)
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _find_local_text(root, *names):
        for name in names:
            for elem in root.iter():
                try:
                    local = etree.QName(elem).localname
                except Exception:
                    local = elem.tag
                if local == name and elem.text and elem.text.strip():
                    return elem.text.strip()
        return ""

    @staticmethod
    def _extract_embedded_cert_pem(root):
        for elem in root.iter():
            local = etree.QName(elem).localname
            if local == "X509Certificate" and elem.text and elem.text.strip():
                raw = "".join(elem.text.strip().split())
                if "-----BEGIN CERTIFICATE-----" in raw:
                    return raw
                lines = [raw[i:i + 64] for i in range(0, len(raw), 64)]
                return "-----BEGIN CERTIFICATE-----\n" + "\n".join(lines) + "\n-----END CERTIFICATE-----\n"
        return None

    @staticmethod
    def _subject_sn_from_pem(cert_pem):
        certificate = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
        sn = ""
        for attr in certificate.subject.get_attributes_for_oid(x509.oid.NameOID.SERIAL_NUMBER):
            sn = attr.value.strip()
            break
        if sn.upper().startswith("IDCDO-"):
            sn = sn[6:]
        return sn, certificate

    @staticmethod
    def _validate_legacy_signature(root, submitted_seed):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        seed_elem = None
        signature_elem = None
        for elem in root.iter():
            local = etree.QName(elem).localname
            if local in ("Semilla", "semilla", "valor") and elem.text and elem.text.strip():
                seed_elem = elem
            if local in ("Firma", "firma", "SignatureValue") and elem.text and elem.text.strip():
                signature_elem = elem
        if seed_elem is None or signature_elem is None:
            return None, "No se encontró Semilla o Firma en el XML."
        cert_pem = ReceptorAuthService._extract_embedded_cert_pem(root)
        if not cert_pem:
            return None, "No se encontró el certificado en el XML firmado."
        try:
            signature_bytes = base64.b64decode(signature_elem.text.strip())
            certificate = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
            certificate.public_key().verify(
                signature_bytes,
                submitted_seed.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
        except Exception:
            return None, "La firma digital no es válida para la semilla proporcionada."
        return ReceptorAuthService._result_from_cert(cert_pem), None

    @staticmethod
    def _result_from_cert(cert_pem):
        subject_sn, certificate = ReceptorAuthService._subject_sn_from_pem(cert_pem)
        return {
            "subject_sn": subject_sn,
            "subject": str(certificate.subject),
            "issuer": str(certificate.issuer),
            "not_before": certificate.not_valid_before_utc.isoformat(),
            "not_after": certificate.not_valid_after_utc.isoformat(),
        }

    @staticmethod
    def _find_element_by_id(root, id_value):
        for elem in root.iter():
            for attr_name in ("Id", "ID", "id"):
                if elem.get(attr_name) == id_value:
                    return elem
        return None

    @staticmethod
    def _c14n_signature_info(root, ns):
        """Extrae firma, SignedInfo, SignatureValue y algoritmos declarados."""
        sig = root.find(".//ds:Signature", ns)
        if sig is None:
            raise ValueError("No se encontró ds:Signature.")
        signed_info = sig.find("ds:SignedInfo", ns)
        sig_value_el = sig.find("ds:SignatureValue", ns)
        if signed_info is None or sig_value_el is None or not sig_value_el.text:
            raise ValueError("Firma incompleta: faltan ds:SignedInfo/ds:SignatureValue.")
        c14n_el = signed_info.find("ds:CanonicalizationMethod", ns)
        sig_method_el = signed_info.find("ds:SignatureMethod", ns)
        c14n_method = c14n_el.get("Algorithm", "") if c14n_el is not None else ""
        sig_method = sig_method_el.get("Algorithm", "") if sig_method_el is not None else ""
        return sig, signed_info, sig_value_el, c14n_method, sig_method

    @staticmethod
    def _reference_target(root, ref, ns):
        uri = ref.get("URI", "")
        if not uri:
            return root, True
        if uri.startswith("#"):
            target = ReceptorAuthService._find_element_by_id(root, uri[1:])
            if target is None:
                raise ValueError(f"Referencia no resuelta: {uri}")
            return target, False
        raise ValueError(f"URI de referencia no soportado: {uri}")

    @staticmethod
    def _check_reference_digest(root, ref, ns, exclusive):
        """Verifica el digest de una ds:Reference (resuelve URI, aplica
        transform enveloped-signature, canonicaliza y compara DigestValue)."""
        import hashlib
        target, is_document = ReceptorAuthService._reference_target(root, ref, ns)
        transforms = []
        transforms_el = ref.find("ds:Transforms", ns)
        if transforms_el is not None:
            transforms = [t.get("Algorithm", "") for t in transforms_el.findall("ds:Transform", ns)]
        work = etree.fromstring(etree.tostring(target))
        if any("enveloped-signature" in t for t in transforms):
            sig_in_work = work.find(".//ds:Signature", ns)
            if sig_in_work is not None:
                work.remove(sig_in_work)
        c14n_bytes = etree.tostring(work, method="c14n", exclusive=exclusive, with_comments=False)
        digest_method_el = ref.find("ds:DigestMethod", ns)
        digest_method = digest_method_el.get("Algorithm", "") if digest_method_el is not None else ""
        digest_value = (ref.findtext("ds:DigestValue", default="", namespaces=ns) or "").strip()
        hash_name = digest_method.rsplit("#", 1)[-1].lower() if digest_method else ""
        if hash_name not in ("sha1", "sha256", "sha384", "sha512"):
            hash_name = "sha256"
        computed = hashlib.new(hash_name, c14n_bytes).digest()
        expected = base64.b64decode("".join(digest_value.split()))
        if computed != expected:
            raise ValueError(
                f"Digest de referencia URI='{ref.get('URI', '')}' no coincide (algoritmo {hash_name})."
            )
        return c14n_bytes

    @staticmethod
    def _signed_info_c14n(root, ns, exclusive=False):
        """Canonicaliza ds:SignedInfo al estilo del firmante (Java/.NET):
        incluye TODAS las declaraciones de namespaces en alcance sobre el
        elemento SignedInfo y sin xmlns="" espurios en los hijos (quirk de
        libxml2 con default-namespace en subárboles)."""
        sig = root.find(".//ds:Signature", ns)
        if sig is None:
            raise ValueError("No se encontró ds:Signature.")
        signed_info = sig.find("ds:SignedInfo", ns)
        if signed_info is None:
            raise ValueError("No se encontró ds:SignedInfo.")
        in_scope = {}
        for anc in signed_info.iterancestors():
            for pfx, uri in (anc.nsmap or {}).items():
                in_scope.setdefault(pfx, uri)
        for pfx, uri in (signed_info.nsmap or {}).items():
            in_scope.setdefault(pfx, uri)

        def _copy(parent, src):
            qsrc = etree.QName(src)
            child = etree.SubElement(parent, "{%s}%s" % (qsrc.namespace, qsrc.localname))
            for key, value in src.attrib.items():
                child.set(key, value)
            if src.text and src.text.strip():
                child.text = src.text
            for sub in src:
                _copy(child, sub)
            if src.tail and src.tail.strip():
                child.tail = src.tail
            return child

        q = etree.QName(signed_info)
        rebuilt = etree.Element("{%s}%s" % (q.namespace, q.localname), nsmap=in_scope or None)
        for key, value in signed_info.attrib.items():
            rebuilt.set(key, value)
        if signed_info.text and signed_info.text.strip():
            rebuilt.text = signed_info.text
        for child in signed_info:
            _copy(rebuilt, child)
        return etree.tostring(rebuilt, method="c14n", exclusive=exclusive, with_comments=False)

    @staticmethod
    def _manual_xmldsig_verify(root, cert_pem):
        """Verificación XMLDSig manual equivalente al firmante Java/.NET:
        1) digest de cada ds:Reference (URI, transform enveloped, c14n),
        2) firma RSA PKCS#1 v1.5 sobre el c14n de ds:SignedInfo (namespaces
           en alcance incluidos, estilo .NET)."""
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        ns = {"ds": DS_NS}
        sig, signed_info, sig_value_el, c14n_method, sig_method = ReceptorAuthService._c14n_signature_info(root, ns)
        exclusive = "exc-c14n" in c14n_method
        logger.warning(
            f"ValidacionCertificado: verificador manual (c14n={c14n_method or 'inclusiva por defecto'}, "
            f"sig={sig_method or 'desconocido'})"
        )
        for ref in signed_info.findall("ds:Reference", ns):
            ReceptorAuthService._check_reference_digest(root, ref, ns, exclusive)
        hash_map = {
            "rsa-sha1": hashes.SHA1, "sha1": hashes.SHA1,
            "rsa-sha256": hashes.SHA256, "sha256": hashes.SHA256,
            "rsa-sha384": hashes.SHA384, "sha384": hashes.SHA384,
            "rsa-sha512": hashes.SHA512, "sha512": hashes.SHA512,
        }
        sig_hash_cls = hash_map.get(sig_method.rsplit("#", 1)[-1].lower(), hashes.SHA256)
        c14n_si = ReceptorAuthService._signed_info_c14n(root, ns, exclusive=exclusive)
        certificate = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
        signature_bytes = base64.b64decode("".join(sig_value_el.text.split()))
        try:
            certificate.public_key().verify(
                signature_bytes, c14n_si, padding.PKCS1v15(), sig_hash_cls()
            )
        except Exception as e:
            raise ValueError(f"SignatureValue no válida (método {sig_method or 'desconocido'}): {e}") from e

    @staticmethod
    def validate_signed_seed(signed_seed_xml_bytes, expected_seed=None):
        try:
            root = etree.fromstring(signed_seed_xml_bytes)
        except Exception as e:
            return None, f"XML inválido: {str(e)}"

        submitted_seed = ReceptorAuthService._find_local_text(root, "valor", "Valor", "Semilla", "semilla")
        if not submitted_seed:
            return None, "No se encontró el valor de la semilla en el XML."

        consume_on_success = None
        if expected_seed:
            if submitted_seed != expected_seed:
                return None, "La semilla no coincide con la emitida."
        else:
            from app.repositories.receptor_repository import ReceptorRepository
            if not ReceptorRepository.validate_seed(submitted_seed):
                return None, "La semilla no fue emitida por este receptor o ha expirado."
            consume_on_success = submitted_seed

        has_dsig = any(
            etree.QName(elem).namespace == DS_NS and etree.QName(elem).localname == "Signature"
            for elem in root.iter()
        )
        if has_dsig:
            try:
                cert_pem = ReceptorAuthService._extract_embedded_cert_pem(root)
                verified = False
                try:
                    from signxml import XMLVerifier
                    if cert_pem:
                        XMLVerifier().verify(signed_seed_xml_bytes, x509_cert=cert_pem)
                    else:
                        XMLVerifier().verify(signed_seed_xml_bytes)
                    verified = True
                except Exception as signxml_error:
                    logger.warning(f"ValidacionCertificado: signxml primario falló: {signxml_error}")
                    for id_attr in ("Id", "ID", "id"):
                        try:
                            from signxml import XMLVerifier
                            kwargs = {"x509_cert": cert_pem} if cert_pem else {}
                            kwargs["id_attribute"] = id_attr
                            XMLVerifier().verify(signed_seed_xml_bytes, **kwargs)
                            verified = True
                            break
                        except Exception as retry_error:
                            logger.warning(
                                f"ValidacionCertificado: signxml id_attribute={id_attr} falló: {retry_error}"
                            )
                if not verified:
                    if not cert_pem:
                        cert_pem = ReceptorAuthService._extract_embedded_cert_pem(etree.fromstring(signed_seed_xml_bytes))
                    if not cert_pem:
                        return None, "No se encontró el certificado en la firma digital."
                    ReceptorAuthService._manual_xmldsig_verify(root, cert_pem)
                if not cert_pem:
                    cert_pem = ReceptorAuthService._extract_embedded_cert_pem(etree.fromstring(signed_seed_xml_bytes))
                if not cert_pem:
                    return None, "No se encontró el certificado en la firma digital."
                result, _ = ReceptorAuthService._result_from_cert(cert_pem), None
                if consume_on_success:
                    from app.repositories.receptor_repository import ReceptorRepository
                    ReceptorRepository.consume_seed(consume_on_success)
                return result, None
            except Exception as e:
                logger.warning(f"ValidacionCertificado: verificación de firma falló: {e!r}")
                return None, f"Firma digital no válida: {str(e)}"

        result, error = ReceptorAuthService._validate_legacy_signature(root, submitted_seed)
        if error:
            return None, error
        if consume_on_success:
            from app.repositories.receptor_repository import ReceptorRepository
            ReceptorRepository.consume_seed(consume_on_success)
        return result, None

    # ─────────────────────────────────────────────────────────────────
    # Tokens
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def issue_token(owner_uid, taxpayer_rnc, sandbox=True):
        import hashlib
        raw = f"{owner_uid}:{taxpayer_rnc}:{uuid.uuid4().hex}:{datetime.now(timezone.utc).isoformat()}"
        token = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        issued_at = datetime.now(timezone.utc)
        expiry_minutes = getattr(Config, "RECEPTOR_TOKEN_EXPIRY_MINUTES", 30)
        expires_at = issued_at + timedelta(minutes=expiry_minutes)
        return {
            "token": token,
            "taxpayer_rnc": taxpayer_rnc,
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

    @staticmethod
    def resolve_company_by_rnc(taxpayer_rnc):
        """Resuelve owner_uid y perfil de empresa a partir del RNC del certificado."""
        if not taxpayer_rnc:
            return None, None
        from app.services.db_service import DatabaseService
        company_doc = DatabaseService.get_company_by_rnc(taxpayer_rnc)
        if not company_doc:
            return None, None
        owner_uid = company_doc.get("owner_uid", "")
        company_id = company_doc.get("company_id", "")
        profile = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
        return owner_uid, profile
