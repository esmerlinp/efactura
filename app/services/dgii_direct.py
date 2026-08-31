import hashlib
import os
import re
import tempfile
import uuid
from urllib.parse import urlencode, quote
from xml.sax.saxutils import escape

import requests

from app.services.dgii_xml_builder import DgiiXmlBuilder
from app.services.dgii_signer import DgiiSigner
from config import Config


class DgiiDirectService:

    @classmethod
    def _use_local_simulation(cls, sandbox):
        return sandbox and Config.DGII_ALLOW_SIMULATION and Config.DGII_SANDBOX_MODE == "local"

    @classmethod
    def _resolve_endpoints(cls, sandbox=True):
        if sandbox:
            return {
                "semilla": Config.DGII_AUTH_SEMILLA_URL,
                "validar_semilla": Config.DGII_AUTH_VALIDAR_URL,
                "recepcion": Config.DGII_RECEPCION_URL,
                "rfce_recepcion": Config.DGII_RFCE_RECEPCION_URL,
                "rfce_consulta": Config.DGII_RFCE_CONSULTA_URL,
                "consulta_resultado": Config.DGII_CONSULTA_RESULTADO_URL,
                "consulta_estado": Config.DGII_CONSULTA_ESTADO_URL,
                "consulta_trackids": Config.DGII_CONSULTA_TRACKIDS_URL,
                "aprobacion_comercial": Config.DGII_APROBACION_COMERCIAL_URL,
                "anulacion_rangos": Config.DGII_ANULACION_RANGOS_URL,
                "directorio_listado": Config.DGII_DIRECTORIO_LISTADO_URL,
                "directorio_por_rnc": Config.DGII_DIRECTORIO_POR_RNC_URL,
            }
        return {
            "semilla": getattr(Config, "DGII_AUTH_SEMILLA_URL_PRODUCTION", "") or Config.DGII_AUTH_SEMILLA_URL,
            "validar_semilla": getattr(Config, "DGII_AUTH_VALIDAR_URL_PRODUCTION", "") or Config.DGII_AUTH_VALIDAR_URL,
            "recepcion": getattr(Config, "DGII_RECEPCION_URL_PRODUCTION", "") or Config.DGII_RECEPCION_URL,
            "rfce_recepcion": getattr(Config, "DGII_RFCE_RECEPCION_URL_PRODUCTION", "") or Config.DGII_RFCE_RECEPCION_URL,
            "rfce_consulta": getattr(Config, "DGII_RFCE_CONSULTA_URL_PRODUCTION", "") or Config.DGII_RFCE_CONSULTA_URL,
            "consulta_resultado": getattr(Config, "DGII_CONSULTA_RESULTADO_URL_PRODUCTION", "") or Config.DGII_CONSULTA_RESULTADO_URL,
            "consulta_estado": Config.DGII_CONSULTA_ESTADO_URL,
            "consulta_trackids": Config.DGII_CONSULTA_TRACKIDS_URL,
            "aprobacion_comercial": Config.DGII_APROBACION_COMERCIAL_URL,
            "anulacion_rangos": getattr(Config, "DGII_ANULACION_RANGOS_URL_PRODUCTION", "") or Config.DGII_ANULACION_RANGOS_URL,
            "directorio_listado": Config.DGII_DIRECTORIO_LISTADO_URL,
            "directorio_por_rnc": Config.DGII_DIRECTORIO_POR_RNC_URL,
        }

    @classmethod
    def _prepare_tls_cert(cls, company_profile):
        try:
            cert_bundle = DgiiSigner.export_pem_bundle(company_profile)
        except Exception:
            return None
        if not cert_bundle:
            return None
        cert_pem, key_pem, chain_pem = cert_bundle
        if not cert_pem or not key_pem:
            return None

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
        temp_file.write(key_pem)
        temp_file.write(cert_pem)
        if chain_pem:
            temp_file.write(chain_pem)
        temp_file.flush()
        temp_file.close()
        return temp_file.name

    @classmethod
    def _cleanup_tls_cert(cls, cert_path):
        if not cert_path:
            return
        try:
            os.unlink(cert_path)
        except Exception:
            pass

    @classmethod
    def _build_headers(cls, token=None):
        headers = {
            "accept": "application/json",
            "User-Agent": Config.DGII_USER_AGENT,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def _safe_json(response):
        try:
            return response.json()
        except Exception:
            return None

    @staticmethod
    def _extract_xml_tag(text, tag_name):
        if not text:
            return None
        pattern = rf"<{tag_name}[^>]*>([^<]+)</{tag_name}>"
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    @classmethod
    def _multipart_post(cls, url, xml_bytes, token=None, filename="document.xml", cert_path=None):
        headers = cls._build_headers(token=token)
        files = {"xml": (filename, xml_bytes, "text/xml")}
        return requests.post(
            url, files=files, headers=headers, cert=cert_path,
            timeout=Config.DGII_HTTP_TIMEOUT
        )

    @classmethod
    def _get_with_params(cls, url, params, token=None, cert_path=None):
        headers = cls._build_headers(token=token)
        return requests.get(
            url, params=params, headers=headers, cert=cert_path,
            timeout=Config.DGII_HTTP_TIMEOUT
        )

    @staticmethod
    def _parse_response(data, text):
        result = {}
        if isinstance(data, dict):
            result.update(data)
        if text and not data:
            result["_xml_raw"] = text
        return result

    @classmethod
    def _extract_seed_value(cls, data, text):
        if isinstance(data, dict):
            for key in ("seed", "semilla", "Semilla", "Seed", "valor", "Valor"):
                v = data.get(key)
                if v:
                    return str(v)
        for tag in ("valor", "Valor", "Semilla"):
            val = cls._extract_xml_tag(text, tag)
            if val:
                return val
        return None

    @classmethod
    def _extract_token(cls, data, text):
        if isinstance(data, dict):
            for key in ("token", "Token", "jwt", "access_token", "accessToken", "sessionToken"):
                v = data.get(key)
                if v:
                    return str(v)
        if text:
            jwt_match = re.search(r"eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+", text)
            if jwt_match:
                return jwt_match.group(0)
            for tag in ("Token", "token"):
                val = cls._extract_xml_tag(text, tag)
                if val:
                    return val
        return None

    @classmethod
    def _extract_track_id(cls, data, text):
        if isinstance(data, dict):
            for key in ("trackId", "track_id", "TrackId", "TrackID", "idTracking", "trackid", "trackID"):
                v = data.get(key)
                if v:
                    return str(v)
        if text:
            match = re.search(r"track\s*id\s*[:=]\s*([A-Za-z0-9_-]+)", text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _normalize_status(value):
        if not value:
            return None
        raw = str(value).strip().upper()
        if any(token in raw for token in ["ACEPTADO", "APROBADO", "ACCEPTED", "RECIBIDO", "PROCESADO"]):
            return "ACCEPTED"
        if any(token in raw for token in ["PENDIENTE", "PENDING", "EN PROCESO", "EN_PROCESO"]):
            return "PENDING"
        if any(token in raw for token in ["RECHAZADO", "REJECTED", "ERROR", "FALLIDO", "FAILED"]):
            return "REJECTED"
        return None

    @classmethod
    def _extract_status(cls, data, text):
        status_candidates = []
        if isinstance(data, dict):
            for key in ("status", "estado", "dgiiStatus", "result", "message", "Estado"):
                v = data.get(key)
                if v:
                    status_candidates.append(v)
        elif text:
            status_candidates.append(text)
        for candidate in status_candidates:
            normalized = cls._normalize_status(candidate)
            if normalized:
                return normalized
        return None

    @staticmethod
    def _build_qr_url_e_cf(company_rnc, client_rnc, encf, total, fecha_emision, fecha_firma, codigo_seguridad):
        query_params = urlencode({
            "RncEmisor": company_rnc,
            "RncComprador": client_rnc,
            "ENCF": encf,
            "FechaEmision": fecha_emision,
            "MontoTotal": f"{float(total):.2f}",
            "FechaFirma": fecha_firma,
            "CodigoSeguridad": codigo_seguridad,
        }, quote_via=quote)
        return f"https://ecf.dgii.gov.do/{Config.DGII_ENVIRONMENT}/ConsultaTimbre?{query_params}"

    @staticmethod
    def _build_qr_url_rfce(company_rnc, encf, total, codigo_seguridad):
        query_params = urlencode({
            "RncEmisor": company_rnc,
            "ENCF": encf,
            "MontoTotal": f"{float(total):.2f}",
            "CodigoSeguridad": codigo_seguridad,
        }, quote_via=quote)
        return f"https://fc.dgii.gov.do/{Config.DGII_ENVIRONMENT}/ConsultaTimbreFC?{query_params}"

    @classmethod
    def build_qr_url(cls, company_profile, invoice_data, codigo_seguridad):
        """QR oficial DGII (formato CamelCase) con el ambiente del env configurado.

        Reglas por tipo:
          - E32 < RD$250,000 → fc.dgii.gov.do/{env}/ConsultaTimbreFC (4 params, sin comprador).
          - E41 → RncComprador = RNC de la empresa (el Comprador del XML es el emisor).
          - E43/E46/E47 → sin RncComprador (el XML no lleva RNCComprador).
          - Demás tipos → RncComprador = RNC del comprador (fallback 000000000).
        """
        from app.utils.ecf_utils import get_ecf_type_number_code
        from datetime import datetime as _dt

        env = Config.DGII_ENVIRONMENT
        encf = str(invoice_data.get("encf", "") or "")
        company_rnc = str(company_profile.get("companyRNC", "") or "").replace("-", "").strip()
        client_rnc = str(invoice_data.get("clientRNC", "") or "").replace("-", "").strip()
        ecf_type = str(invoice_data.get("ecfType", "") or "")
        total = float(invoice_data.get("total", 0.0) or 0.0)
        tipo = get_ecf_type_number_code(ecf_type)

        date_str = str(invoice_data.get("date", "") or "")[:10]
        try:
            fecha_emision = _dt.strptime(date_str, "%Y-%m-%d").strftime("%d-%m-%Y")
        except Exception:
            fecha_emision = date_str or ""
        fecha_firma = str(invoice_data.get("fechaHoraFirma", "") or "").strip()
        if not fecha_firma:
            # Fallback: extraer la FechaHoraFirma real del XML firmado almacenado
            xml_content = invoice_data.get("xmlContent") or invoice_data.get("xml_content") or ""
            if xml_content:
                try:
                    from app.services.dgii_signer import DgiiSigner
                    fhf_xml = DgiiSigner.extract_fecha_hora_firma(xml_content)
                    if fhf_xml:
                        fecha_firma = fhf_xml
                except Exception:
                    pass
        if not fecha_firma:
            fecha_firma = fecha_emision + " 12:00:00"
            if invoice_data.get("paymentDate"):
                try:
                    dt = _dt.fromisoformat(str(invoice_data["paymentDate"]).replace("Z", "+00:00"))
                    fecha_firma = dt.strftime("%d-%m-%Y %H:%M:%S")
                except Exception:
                    pass

        if tipo == "32" and total < 250000.00:
            query_params = urlencode({
                "RncEmisor": company_rnc,
                "ENCF": encf,
                "MontoTotal": f"{total:.2f}",
                "CodigoSeguridad": codigo_seguridad or "",
            }, quote_via=quote)
            return f"https://fc.dgii.gov.do/{env}/ConsultaTimbreFC?{query_params}"

        # Orden de parámetros según Informe Técnico e-CF §18.2.3:
        # RncEmisor, RncComprador, ENCF, FechaEmision, MontoTotal, FechaFirma, CodigoSeguridad
        ordered = {
            "RncEmisor": company_rnc,
            "ENCF": encf,
            "FechaEmision": fecha_emision,
            "MontoTotal": f"{total:.2f}",
            "FechaFirma": fecha_firma,
            "CodigoSeguridad": codigo_seguridad or "",
        }
        if tipo == "41":
            rnc_comprador = company_rnc
        elif tipo in ("43", "47"):
            rnc_comprador = None  # sin RNCComprador en el XML → se omite del QR
        elif tipo == "46":
            # E46 (Exportación): el XML lleva RNCComprador salvo que no exista
            # ningún RNC (ahí usa IdentificadorExtranjero). Regla espejo del
            # builder: clientRNC válido → ese; si no → RNC de la empresa.
            if client_rnc and client_rnc not in ("000000000", "0"):
                rnc_comprador = client_rnc
            elif company_rnc:
                rnc_comprador = company_rnc
            else:
                rnc_comprador = None
        else:
            rnc_comprador = client_rnc or "000000000"
        if rnc_comprador:
            ordered["RncComprador"] = rnc_comprador
        # Reordenar: RncComprador después de RncEmisor
        final = {"RncEmisor": ordered.pop("RncEmisor")}
        if "RncComprador" in ordered:
            final["RncComprador"] = ordered.pop("RncComprador")
        final.update(ordered)
        return f"https://ecf.dgii.gov.do/{env}/ConsultaTimbre?{urlencode(final, quote_via=quote)}"

    @classmethod
    def qr_url_valido(cls, company_profile, invoice_data):
        """Auto-reparación de QR para documentos emitidos antes del fix de
        FechaFirma real: si el qrCodeURL guardado trae el placeholder
        'FechaFirma=...%2012%3A00%3A00' (la DGII lo valida contra la
        FechaHoraFirma del XML y devuelve 'No fue encontrada la factura'),
        se recalcula con build_qr_url usando el xmlContent almacenado.
        Los QR válidos (y los de RFCE, que no llevan FechaFirma) se devuelven
        intactos.
        """
        stored = str(invoice_data.get("qrCodeURL", "") or "").strip()
        has_placeholder = ("12%3A00%3A00" in stored) or ("12:00:00" in stored)
        if stored and not has_placeholder:
            return stored

        xml_content = invoice_data.get("xmlContent") or invoice_data.get("xml_content") or ""
        if not xml_content:
            return stored

        try:
            sig = DgiiSigner.extract_signature_value(xml_content)
        except Exception:
            sig = None
        codigo_seguridad = (invoice_data.get("xmlSignature", "") or (sig or ""))[:6]
        if not codigo_seguridad:
            return stored

        try:
            data = dict(invoice_data)
            # Normalizar campos según el origen del documento:
            # - gastos guardan rncEmisor y amount (no clientRNC/total),
            # - facturas de proveedor guardan supplierRnc/supplierCedula.
            # Sin esto el QR recalculado saldría con RncComprador=000000000
            # o MontoTotal=0.00.
            if not str(data.get("clientRNC", "") or "").strip():
                data["clientRNC"] = (invoice_data.get("supplierRnc")
                                     or invoice_data.get("supplierCedula")
                                     or invoice_data.get("rncEmisor") or "")
            if not float(data.get("total", 0.0) or 0.0):
                data["total"] = invoice_data.get("amount", 0.0)
            return cls.build_qr_url(company_profile, data, codigo_seguridad) or stored
        except Exception:
            return stored

    @classmethod
    def _extract_seed_xml(cls, data, text):
        valor = cls._extract_seed_value(data, text)
        fecha = None
        if isinstance(data, dict):
            for key in ("fecha", "Fecha", "date", "Date"):
                v = data.get(key)
                if v:
                    fecha = str(v)
                    break
        if not fecha and text:
            fecha = cls._extract_xml_tag(text, "fecha") or cls._extract_xml_tag(text, "Fecha")
        return valor, fecha

    # ═══════════════════════════════════════════════════════════════
    # Autenticación
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def get_dgii_token(cls, company_profile, sandbox=True):
        endpoints = cls._resolve_endpoints(sandbox=sandbox)
        semilla_url = endpoints.get("semilla")
        validar_url = endpoints.get("validar_semilla")

        if cls._use_local_simulation(sandbox) and (not semilla_url or not validar_url):
            return "simulated_dgii_token_jwt_2026", None

        if not semilla_url:
            return None, "DGII_AUTH_SEMILLA_URL no configurado."

        cert_path = cls._prepare_tls_cert(company_profile)
        try:
            headers = cls._build_headers()
            response = requests.get(semilla_url, headers=headers, cert=cert_path, timeout=Config.DGII_HTTP_TIMEOUT)
            response_data = cls._safe_json(response)
            response_text = response.text if response is not None else ""

            if response.status_code < 200 or response.status_code >= 300:
                return None, f"DGII auth error HTTP {response.status_code}"

            token = cls._extract_token(response_data, response_text)
            if token:
                return token, None

            seed, fecha_seed = cls._extract_seed_xml(response_data, response_text)
            if not seed:
                return None, "No se pudo obtener la semilla de autenticacion."

            if not validar_url:
                if cls._use_local_simulation(sandbox):
                    return "simulated_dgii_token_jwt_2026", None
                return None, "DGII_AUTH_VALIDAR_URL no configurado."

            # ── Construir SemillaModel y firmarlo con XMLDSig (XSD Semilla v1.0) ──
            fecha_str = fecha_seed if fecha_seed else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            semilla_xml = (
                '<?xml version="1.0" encoding="utf-8"?>'
                f"<SemillaModel>"
                f"<valor>{escape(seed)}</valor>"
                f"<fecha>{escape(fecha_str)}</fecha>"
                f"</SemillaModel>"
            ).encode("utf-8")

            signed_semilla = DgiiSigner.sign_xml(semilla_xml, company_profile)

            token_response = cls._multipart_post(
                validar_url, signed_semilla, token=None,
                filename="signed_seed.xml", cert_path=cert_path
            )

            token_data = cls._safe_json(token_response)
            token_text = token_response.text if token_response is not None else ""
            token = cls._extract_token(token_data, token_text)

            if not token:
                return None, "No se pudo obtener token DGII."
            return token, None

        except Exception as e:
            if cls._use_local_simulation(sandbox):
                return "simulated_dgii_token_jwt_2026", None
            return None, f"Error al autenticar con DGII: {str(e)}"
        finally:
            cls._cleanup_tls_cert(cert_path)

    # ═══════════════════════════════════════════════════════════════
    # Simulación (sandbox local)
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def _simulate_emit(cls, company_profile, invoice_data):
        encf = invoice_data.get("encf", "E310000000001")
        track_id = f"dgii_tr_{uuid.uuid4().hex[:12]}"
        cod_seg = f"SIM{uuid.uuid4().hex[:3]}"
        qr_url = cls.build_qr_url(company_profile, invoice_data, cod_seg)

        return {
            "success": True,
            "encf": encf,
            "trackId": track_id,
            "xmlSignature": f"SIM-{uuid.uuid4().hex[:12]}",
            "codigoSeguridad": cod_seg,
            "qrCodeURL": qr_url,
            "mode": "FALLBACK",
            "status": "PENDING",
            "dgiiStatus": "PENDING",
            "message": "Simulacion DGII habilitada (sandbox)."
        }

    # ═══════════════════════════════════════════════════════════════
    # Recepción e-CF
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def emit_direct(cls, company_profile, invoice_data, sandbox=True):
        try:
            endpoints = cls._resolve_endpoints(sandbox=sandbox)
            recepcion_url = endpoints.get("recepcion")

            if cls._use_local_simulation(sandbox) and not recepcion_url:
                return cls._simulate_emit(company_profile, invoice_data)

            if not recepcion_url:
                return {
                    "success": False,
                    "error": "DGII_RECEPCION_URL no configurado.",
                    "message": "DGII_RECEPCION_URL no configurado."
                }

            raw_xml = DgiiXmlBuilder.build_invoice_xml(company_profile, invoice_data)
            print(f"\n{'='*60}\n📄 XML GENERADO:\n{'='*60}\n{raw_xml.decode('utf-8', errors='replace')}\n{'='*60}\n", flush=True)
            signed_xml = DgiiSigner.sign_xml(raw_xml, company_profile)
            xml_signature = DgiiSigner.extract_signature_value(signed_xml) or hashlib.sha256(signed_xml).hexdigest()
            codigo_seguridad = xml_signature[:6]
            invoice_data["xmlContent"] = signed_xml.decode("utf-8", errors="replace")

            token, token_error = cls.get_dgii_token(company_profile, sandbox=sandbox)
            if not token:
                if cls._use_local_simulation(sandbox):
                    return cls._simulate_emit(company_profile, invoice_data)
                return {
                    "success": False,
                    "error": token_error or "No se pudo obtener token DGII.",
                    "message": token_error or "No se pudo obtener token DGII."
                }

            company_rnc = str(company_profile.get("companyRNC", "")).replace("-", "").strip()
            client_rnc = str(invoice_data.get("clientRNC", "000000000")).replace("-", "").strip() or "000000000"
            encf = invoice_data.get("encf", "E310000000001")
            filename = f"{company_rnc}{encf}.xml"

            cert_path = cls._prepare_tls_cert(company_profile)
            try:
                response = cls._multipart_post(
                    recepcion_url, signed_xml, token=token,
                    filename=filename, cert_path=cert_path
                )

                response_data = cls._safe_json(response)
                response_text = response.text if response is not None else ""
                status_code = response.status_code if response is not None else 0
                dgii_status = cls._extract_status(response_data, response_text)
                track_id = cls._extract_track_id(response_data, response_text) or f"dgii_tr_{uuid.uuid4().hex[:12]}"
                error_msg = ""
                if isinstance(response_data, dict):
                    error_msg = response_data.get("error") or response_data.get("mensaje") or ""

                qr_url = cls.build_qr_url(company_profile, invoice_data, codigo_seguridad)

                if status_code >= 200 and status_code < 300:
                    # DGII devuelve HTTP 200 incluso cuando rechaza el contenido.
                    # Verificar tanto el campo "error" en JSON como el estado extraído.
                    rejection_error = None
                    if isinstance(response_data, dict):
                        rejection_error = response_data.get("error") or response_data.get("mensaje")
                    if not rejection_error and dgii_status == "REJECTED":
                        # El texto crudo contiene "REJECTED" pero no hay error explícito en JSON.
                        # Consultar el endpoint de resultado para confirmar el estado real.
                        poll_res = cls.check_status(company_profile, track_id, sandbox=sandbox)
                        if poll_res.get("success"):
                            poll_status = poll_res.get("dgiiStatus")
                            poll_mensajes = poll_res.get("mensajes", [])
                            if poll_status == "ACCEPTED":
                                dgii_status = "ACCEPTED"
                                rejection_error = None  # Falso rechazo, el doc fue aceptado
                            elif poll_status == "REJECTED":
                                msgs = "; ".join(m.get("valor", "") for m in poll_mensajes if m.get("valor"))
                                rejection_error = msgs or f"DGII rechazó el comprobante (status={poll_status})"
                            # else PENDING → se deja rejection_error con texto genérico
                        else:
                            # No se pudo consultar → marcar como PENDING, no como rechazo
                            dgii_status = "PENDING"
                    if rejection_error:
                        return {
                            "success": False,
                            "encf": encf,
                            "error": str(rejection_error),
                            "message": str(rejection_error),
                            "responseBody": response_data or response_text,
                            "statusCode": status_code,
                        }

                    return {
                        "success": True,
                        "encf": encf,
                        "trackId": track_id,
                        "xmlSignature": xml_signature,
                        "signedXml": signed_xml.decode("utf-8", errors="replace"),
                        "codigoSeguridad": codigo_seguridad,
                        "qrCodeURL": qr_url,
                        "mode": "API",
                        "status": dgii_status or "PENDING",
                        "dgiiStatus": dgii_status or "PENDING",
                        "responseBody": response_data or response_text,
                        "statusCode": status_code,
                    }

                return {
                    "success": False,
                    "error": f"DGII recepcion error HTTP {status_code}: {error_msg}",
                    "message": "Error en recepcion DGII.",
                    "responseBody": response_data or response_text,
                    "statusCode": status_code
                }

            finally:
                cls._cleanup_tls_cert(cert_path)

        except Exception as e:
            return {
                "success": False,
                "error": f"Fallo en motor directo: {str(e)}"
            }

    # ═══════════════════════════════════════════════════════════════
    # RFCE — E32 < RD$250K (dominio fc.dgii.gov.do)
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def emit_rfce(cls, company_profile, invoice_data, sandbox=True):
        try:
            endpoints = cls._resolve_endpoints(sandbox=sandbox)
            rfce_url = endpoints.get("rfce_recepcion")

            if cls._use_local_simulation(sandbox) and not rfce_url:
                sim = cls._simulate_emit(company_profile, invoice_data)
                sim["message"] = "Simulacion RFCE (sandbox)."
                return sim

            if not rfce_url:
                return {
                    "success": False,
                    "error": "DGII_RFCE_RECEPCION_URL no configurado.",
                    "message": "DGII_RFCE_RECEPCION_URL no configurado."
                }

            # Paso 1: Generar E32 completo + firmar → extraer CodigoSeguridadeCF
            full_e32 = DgiiXmlBuilder.build_invoice_xml(company_profile, invoice_data)
            signed_e32 = DgiiSigner.sign_xml(full_e32, company_profile)
            xml_sig = DgiiSigner.extract_signature_value(signed_e32) or hashlib.sha256(signed_e32).hexdigest()
            codigo_seguridad = xml_sig[:6]
            # Persistir el XML firmado en el dict para que la descarga posterior
            # sirva EXACTAMENTE el archivo cuya firma generó CodigoSeguridadeCF
            # (FechaHoraFirma cambia en cada build → re-firmar produce otro signature value).
            invoice_data["xmlContent"] = signed_e32.decode("utf-8", errors="replace")

            # Paso 2: Construir RFCE summary con CodigoSeguridadeCF
            rfce_raw = DgiiXmlBuilder.build_rfce_summary_xml(company_profile, invoice_data, codigo_seguridad)
            signed_rfce = DgiiSigner.sign_xml(rfce_raw, company_profile)
            rfce_xml_signature = DgiiSigner.extract_signature_value(signed_rfce) or hashlib.sha256(signed_rfce).hexdigest()

            token, token_error = cls.get_dgii_token(company_profile, sandbox=sandbox)
            if not token:
                if cls._use_local_simulation(sandbox):
                    sim = cls._simulate_emit(company_profile, invoice_data)
                    sim["message"] = "Simulacion RFCE (sandbox)."
                    return sim
                return {
                    "success": False,
                    "error": token_error or "No se pudo obtener token DGII.",
                    "message": token_error or "No se pudo obtener token DGII."
                }

            company_rnc = str(company_profile.get("companyRNC", "")).replace("-", "").strip()
            client_rnc = str(invoice_data.get("clientRNC", "000000000")).replace("-", "").strip() or "000000000"
            encf = invoice_data.get("encf", "E320000000001")
            filename = f"{company_rnc}{encf}.xml"

            # Paso 3: Enviar RFCE firmado al endpoint de resúmenes
            cert_path = cls._prepare_tls_cert(company_profile)
            try:
                response = cls._multipart_post(
                    rfce_url, signed_rfce, token=token,
                    filename=filename, cert_path=cert_path
                )

                response_data = cls._safe_json(response)
                response_text = response.text if response is not None else ""
                status_code = response.status_code if response is not None else 0

                codigo = None
                estado = None
                secuencia_utilizada = None
                if isinstance(response_data, dict):
                    codigo = response_data.get("codigo")
                    estado = response_data.get("estado")
                    secuencia_utilizada = response_data.get("secuenciaUtilizada")
                    if not codigo:
                        codigo = cls._extract_xml_tag(response_text, "codigo") or cls._extract_xml_tag(response_text, "Codigo")
                    if not estado:
                        estado = cls._extract_xml_tag(response_text, "estado") or cls._extract_xml_tag(response_text, "Estado")

                dgii_status = cls._extract_status(response_data, response_text)
                qr_url = cls._build_qr_url_rfce(company_rnc, encf, invoice_data.get("total", 0.0), codigo_seguridad)
                if status_code >= 200 and status_code < 300:
                    # RFCE: codigo != 1 o estado == "Rechazado" indica rechazo
                    if isinstance(response_data, dict) and (
                        (codigo is not None and codigo != 1) or
                        (estado and str(estado).lower() == "rechazado")
                    ):
                        return {
                            "success": False,
                            "encf": encf,
                            "error": f"RFCE rechazado (codigo={codigo}, estado={estado})",
                            "message": f"RFCE rechazado",
                            "responseBody": response_data,
                            "statusCode": status_code,
                        }

                    return {
                        "success": True,
                        "encf": encf,
                        "trackId": uuid.uuid4().hex[:20].upper(),
                        "xmlSignature": rfce_xml_signature,
                        "signedXml": signed_e32.decode("utf-8", errors="replace"),
                        "codigoSeguridad": codigo_seguridad,
                        "qrCodeURL": qr_url,
                        "mode": "RFCE_API",
                        "status": dgii_status or "ACCEPTED",
                        "dgiiStatus": dgii_status or "ACCEPTED",
                        "codigoRFCE": codigo,
                        "estadoRFCE": estado,
                        "secuenciaUtilizada": secuencia_utilizada,
                        "responseBody": response_data or response_text,
                        "statusCode": status_code,
                    }

                return {
                    "success": False,
                    "error": f"DGII RFCE error HTTP {status_code}",
                    "message": "Error en recepcion RFCE.",
                    "responseBody": response_data or response_text,
                    "statusCode": status_code
                }

            finally:
                cls._cleanup_tls_cert(cert_path)

        except Exception as e:
            return {
                "success": False,
                "error": f"Fallo en RFCE: {str(e)}"
            }

    # ═══════════════════════════════════════════════════════════════
    # Consulta de resultado (TrackId)
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def check_status(cls, company_profile, track_id, sandbox=True):
        endpoints = cls._resolve_endpoints(sandbox=sandbox)
        consulta_url = endpoints.get("consulta_resultado")
        if not consulta_url:
            if cls._use_local_simulation(sandbox):
                return {
                    "success": True,
                    "trackId": track_id,
                    "dgiiStatus": "PENDING",
                    "responseBody": {"message": "Simulacion local DGII (status)."},
                    "statusCode": 200
                }
            return {"success": False, "message": "DGII_CONSULTA_RESULTADO_URL no configurado."}

        token, token_error = cls.get_dgii_token(company_profile, sandbox=sandbox)
        if not token:
            return {"success": False, "message": token_error or "No se pudo obtener token DGII."}

        cert_path = cls._prepare_tls_cert(company_profile)
        try:
            params = {"trackid": track_id}
            response = cls._get_with_params(consulta_url, params, token=token, cert_path=cert_path)

            response_data = cls._safe_json(response)
            response_text = response.text if response is not None else ""
            status_code = response.status_code if response is not None else 0

            track_id_found = cls._extract_track_id(response_data, response_text) or track_id
            dgii_status = cls._extract_status(response_data, response_text)

            codigo_num = None
            rnc = None
            encf_resp = None
            secuencia_utilizada = None
            fecha_recepcion = None
            mensajes = []

            if isinstance(response_data, dict):
                codigo_num = response_data.get("codigo")
                rnc = response_data.get("rnc", response_data.get("RNC", ""))
                encf_resp = response_data.get("eNCF", response_data.get("encf", ""))
                secuencia_utilizada = response_data.get("secuenciaUtilizada")
                fecha_recepcion = response_data.get("fechaRecepcion")
                mensajes = response_data.get("mensajes", [])

            if status_code >= 200 and status_code < 300:
                return {
                    "success": True,
                    "trackId": track_id_found,
                    "dgiiStatus": dgii_status or "PENDING",
                    "codigo": codigo_num,
                    "rnc": rnc,
                    "eNCF": encf_resp,
                    "secuenciaUtilizada": secuencia_utilizada,
                    "fechaRecepcion": fecha_recepcion,
                    "mensajes": mensajes,
                    "responseBody": response_data or response_text,
                    "statusCode": status_code
                }

            return {
                "success": False,
                "message": f"Error al consultar estado DGII (HTTP {status_code}).",
                "responseBody": response_data or response_text,
                "statusCode": status_code
            }
        finally:
            cls._cleanup_tls_cert(cert_path)

    # ═══════════════════════════════════════════════════════════════
    # Health check
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def check_dgii_status(cls, company_profile, sandbox=True):
        endpoints = cls._resolve_endpoints(sandbox=sandbox)
        semilla_url = endpoints.get("semilla")
        if not semilla_url:
            if cls._use_local_simulation(sandbox):
                return {
                    "success": True,
                    "status": "ONLINE",
                    "message": "Simulacion local DGII habilitada."
                }
            return {
                "success": False,
                "status": "NOT_CONFIGURED",
                "message": "DGII_AUTH_SEMILLA_URL no configurado."
            }

        token, token_error = cls.get_dgii_token(company_profile, sandbox=sandbox)
        if not token:
            if cls._use_local_simulation(sandbox):
                return {
                    "success": True,
                    "status": "ONLINE",
                    "message": "Simulacion local DGII habilitada."
                }
            return {
                "success": False,
                "status": "AUTH_ERROR",
                "message": token_error or "No se pudo autenticar con DGII."
            }

        return {
            "success": True,
            "status": "ONLINE",
            "message": "Autenticacion DGII exitosa."
        }

    # ═══════════════════════════════════════════════════════════════
    # Anulación de Rangos (ANECF)
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def _build_anecf_xml(cls, company_profile, cancellation_dict):
        rnc = str(company_profile.get("companyRNC", "")).replace("-", "").strip()
        serie = cancellation_dict.get("series", "")
        desde = cancellation_dict.get("startSequence", "")
        hasta = cancellation_dict.get("endSequence", "")
        motivo = cancellation_dict.get("reason", "")

        xml = '<?xml version="1.0" encoding="utf-8"?>'
        xml += f"<ANECF>"
        xml += f"<RNCEmisor>{escape(rnc)}</RNCEmisor>"
        xml += f"<Serie>{escape(str(serie))}</Serie>"
        xml += f"<SecuenciaeNCFDesde>{escape(str(desde))}</SecuenciaeNCFDesde>"
        xml += f"<SecuenciaeNCFHasta>{escape(str(hasta))}</SecuenciaeNCFHasta>"
        xml += f"<Motivo>{escape(str(motivo))}</Motivo>"
        xml += f"</ANECF>"
        return xml.encode("utf-8")

    @classmethod
    def cancel_direct(cls, company_profile, cancellation_dict, sandbox=True):
        endpoints = cls._resolve_endpoints(sandbox=sandbox)
        cancel_url = endpoints.get("anulacion_rangos")
        if cls._use_local_simulation(sandbox) and not cancel_url:
            return {
                "success": True,
                "message": "Comprobante anulado directamente (simulado).",
                "cancellationCode": f"CANCEL-{uuid.uuid4().hex[:8].upper()}"
            }

        if not cancel_url:
            return {
                "success": False,
                "message": "DGII_ANULACION_RANGOS_URL no configurado."
            }

        token, token_error = cls.get_dgii_token(company_profile, sandbox=sandbox)
        if not token:
            return {"success": False, "message": token_error or "No se pudo obtener token DGII."}

        anecf_xml = cls._build_anecf_xml(company_profile, cancellation_dict)

        cert_path = cls._prepare_tls_cert(company_profile)
        try:
            response = cls._multipart_post(
                cancel_url, anecf_xml, token=token,
                filename="anulacion_rangos.xml", cert_path=cert_path
            )

            response_data = cls._safe_json(response)
            response_text = response.text if response is not None else ""
            status_code = response.status_code if response is not None else 0

            rnc_resp = None
            codigo = None
            nombre = None
            mensajes = []
            if isinstance(response_data, dict):
                rnc_resp = response_data.get("rnc", "")
                codigo = response_data.get("codigo", "")
                nombre = response_data.get("nombre", "")
                mensajes = response_data.get("mensajes", [])
            if not codigo:
                codigo = cls._extract_xml_tag(response_text, "codigo") or cls._extract_xml_tag(response_text, "Codigo")

            if status_code >= 200 and status_code < 300:
                return {
                    "success": True,
                    "message": "Comprobante anulado directamente con exito.",
                    "cancellationCode": codigo or f"CANCEL-{uuid.uuid4().hex[:8].upper()}",
                    "rnc": rnc_resp,
                    "nombre": nombre,
                    "mensajes": mensajes,
                    "responseBody": response_data or response_text,
                    "statusCode": status_code
                }

            return {
                "success": False,
                "message": "Error al anular comprobante en DGII.",
                "responseBody": response_data or response_text,
                "statusCode": status_code
            }

        finally:
            cls._cleanup_tls_cert(cert_path)

    # ═══════════════════════════════════════════════════════════════
    # Consulta Estado e-CF (por RNC + eNCF)
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def consultar_estado_ecf(cls, company_profile, rnc_emisor, encf,
                              rnc_comprador="", codigo_seguridad="", sandbox=True):
        endpoints = cls._resolve_endpoints(sandbox=sandbox)
        consulta_url = endpoints.get("consulta_estado")
        if not consulta_url:
            return {"success": False, "message": "DGII_CONSULTA_ESTADO_URL no configurado."}

        token, token_error = cls.get_dgii_token(company_profile, sandbox=sandbox)
        if not token:
            return {"success": False, "message": token_error or "No se pudo obtener token DGII."}

        cert_path = cls._prepare_tls_cert(company_profile)
        try:
            params = {
                "rncemisor": rnc_emisor,
                "ncfelectronico": encf,
            }
            if rnc_comprador:
                params["rnccomprador"] = rnc_comprador
            if codigo_seguridad:
                params["codigoseguridad"] = codigo_seguridad

            response = cls._get_with_params(consulta_url, params, token=token, cert_path=cert_path)
            response_data = cls._safe_json(response)
            response_text = response.text if response is not None else ""
            status_code = response.status_code if response is not None else 0

            if status_code >= 200 and status_code < 300:
                return {
                    "success": True,
                    "responseBody": response_data or response_text,
                    "statusCode": status_code
                }

            return {
                "success": False,
                "message": f"Error consulta estado e-CF (HTTP {status_code}).",
                "responseBody": response_data or response_text,
                "statusCode": status_code
            }
        finally:
            cls._cleanup_tls_cert(cert_path)

    # ═══════════════════════════════════════════════════════════════
    # Consulta TrackIds (por RNC + eNCF)
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def consultar_trackids(cls, company_profile, rnc_emisor, encf, sandbox=True):
        endpoints = cls._resolve_endpoints(sandbox=sandbox)
        consulta_url = endpoints.get("consulta_trackids")
        if not consulta_url:
            return {"success": False, "message": "DGII_CONSULTA_TRACKIDS_URL no configurado."}

        token, token_error = cls.get_dgii_token(company_profile, sandbox=sandbox)
        if not token:
            return {"success": False, "message": token_error or "No se pudo obtener token DGII."}

        cert_path = cls._prepare_tls_cert(company_profile)
        try:
            params = {"rncemisor": rnc_emisor, "encf": encf}
            response = cls._get_with_params(consulta_url, params, token=token, cert_path=cert_path)
            response_data = cls._safe_json(response)
            response_text = response.text if response is not None else ""
            status_code = response.status_code if response is not None else 0

            if status_code >= 200 and status_code < 300:
                return {
                    "success": True,
                    "responseBody": response_data or response_text,
                    "statusCode": status_code
                }

            return {
                "success": False,
                "message": f"Error consulta trackIds (HTTP {status_code}).",
                "responseBody": response_data or response_text,
                "statusCode": status_code
            }
        finally:
            cls._cleanup_tls_cert(cert_path)

    # ═══════════════════════════════════════════════════════════════
    # Aprobación Comercial (ACECF)
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def emit_acecf(cls, company_profile, approval_xml_bytes, sandbox=True):
        endpoints = cls._resolve_endpoints(sandbox=sandbox)
        acecf_url = endpoints.get("aprobacion_comercial")
        if not acecf_url:
            return {"success": False, "message": "DGII_APROBACION_COMERCIAL_URL no configurado."}

        token, token_error = cls.get_dgii_token(company_profile, sandbox=sandbox)
        if not token:
            return {"success": False, "message": token_error or "No se pudo obtener token DGII."}

        cert_path = cls._prepare_tls_cert(company_profile)
        try:
            response = cls._multipart_post(
                acecf_url, approval_xml_bytes, token=token,
                filename="aprobacion_comercial.xml", cert_path=cert_path
            )
            response_data = cls._safe_json(response)
            response_text = response.text if response is not None else ""
            status_code = response.status_code if response is not None else 0

            if status_code >= 200 and status_code < 300:
                return {
                    "success": True,
                    "responseBody": response_data or response_text,
                    "statusCode": status_code
                }

            return {
                "success": False,
                "message": f"Error aprobacion comercial (HTTP {status_code}).",
                "responseBody": response_data or response_text,
                "statusCode": status_code
            }
        finally:
            cls._cleanup_tls_cert(cert_path)

    # ═══════════════════════════════════════════════════════════════
    # Consulta Directorio
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def consultar_directorio(cls, company_profile, rnc=None, sandbox=True):
        endpoints = cls._resolve_endpoints(sandbox=sandbox)
        if rnc:
            url = endpoints.get("directorio_por_rnc")
        else:
            url = endpoints.get("directorio_listado")

        if not url:
            return {"success": False, "message": "DGII_DIRECTORIO_URL no configurado."}

        token, token_error = cls.get_dgii_token(company_profile, sandbox=sandbox)
        if not token:
            return {"success": False, "message": token_error or "No se pudo obtener token DGII."}

        cert_path = cls._prepare_tls_cert(company_profile)
        try:
            params = {"RNC": rnc} if rnc else None
            response = cls._get_with_params(url, params, token=token, cert_path=cert_path)
            response_data = cls._safe_json(response)
            status_code = response.status_code if response is not None else 0

            if status_code >= 200 and status_code < 300:
                return {
                    "success": True,
                    "responseBody": response_data or [],
                    "statusCode": status_code
                }

            return {
                "success": False,
                "message": f"Error consulta directorio (HTTP {status_code}).",
                "statusCode": status_code
            }
        finally:
            cls._cleanup_tls_cert(cert_path)
