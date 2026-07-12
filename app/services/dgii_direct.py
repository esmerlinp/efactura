import base64
import gzip
import hashlib
import os
import re
import tempfile
import uuid
from urllib.parse import quote

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
                "auth": Config.DGII_AUTH_URL_SANDBOX,
                "token": Config.DGII_TOKEN_URL_SANDBOX,
                "recepcion": Config.DGII_RECEPCION_URL_SANDBOX,
                "status": Config.DGII_STATUS_URL_SANDBOX,
                "cancel": Config.DGII_CANCEL_URL_SANDBOX
            }

        return {
            "auth": Config.DGII_AUTH_URL_PRODUCTION,
            "token": Config.DGII_TOKEN_URL_PRODUCTION,
            "recepcion": Config.DGII_RECEPCION_URL_PRODUCTION,
            "status": Config.DGII_STATUS_URL_PRODUCTION,
            "cancel": Config.DGII_CANCEL_URL_PRODUCTION
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
    def _build_headers(cls, token=None, content_type="application/json"):
        headers = {
            "accept": "application/json",
            "content-type": content_type,
            "User-Agent": Config.DGII_USER_AGENT
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
    def _extract_seed(cls, data, text):
        if isinstance(data, dict):
            for key in ("seed", "semilla", "Semilla", "Seed"):
                if data.get(key):
                    return str(data.get(key))
        for tag in ("Semilla", "seed"):
            val = cls._extract_xml_tag(text, tag)
            if val:
                return val
        return None

    @classmethod
    def _extract_token(cls, data, text):
        if isinstance(data, dict):
            for key in ("token", "Token", "jwt", "access_token", "accessToken", "sessionToken"):
                if data.get(key):
                    return str(data.get(key))

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
            for key in ("trackId", "track_id", "TrackId", "TrackID", "idTracking"):
                if data.get(key):
                    return str(data.get(key))
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
            for key in ("status", "estado", "dgiiStatus", "result", "message"):
                if data.get(key):
                    status_candidates.append(data.get(key))
        if text:
            status_candidates.append(text)

        for candidate in status_candidates:
            normalized = cls._normalize_status(candidate)
            if normalized:
                return normalized
        return None

    @staticmethod
    def _build_qr_url(company_rnc, client_rnc, encf, total):
        query_params = f"rncEmisor={company_rnc}&rncReceptor={client_rnc}&encf={encf}&monto={float(total):.2f}"
        return f"https://dgii.gov.do/validaecf?{quote(query_params)}"

    @classmethod
    def get_dgii_token(cls, company_profile, sandbox=True):
        endpoints = cls._resolve_endpoints(sandbox=sandbox)
        auth_url = endpoints.get("auth")
        token_url = endpoints.get("token")

        if cls._use_local_simulation(sandbox) and (not auth_url or not token_url):
            return "simulated_dgii_token_jwt_2026", None

        if not auth_url:
            return None, "DGII_AUTH_URL no configurado."

        cert_path = cls._prepare_tls_cert(company_profile)
        try:
            headers = cls._build_headers(content_type=Config.DGII_TOKEN_CONTENT_TYPE)
            response = requests.get(auth_url, headers=headers, cert=cert_path, timeout=Config.DGII_HTTP_TIMEOUT)
            response_data = cls._safe_json(response)
            response_text = response.text if response is not None else ""

            if response.status_code < 200 or response.status_code >= 300:
                return None, f"DGII auth error HTTP {response.status_code}"

            token = cls._extract_token(response_data, response_text)
            if token:
                return token, None

            seed = cls._extract_seed(response_data, response_text)
            if not seed:
                return None, "No se pudo obtener la semilla de autenticacion."

            if not token_url:
                if cls._use_local_simulation(sandbox):
                    return "simulated_dgii_token_jwt_2026", None
                return None, "DGII_TOKEN_URL no configurado."

            signed_seed = DgiiSigner.sign_seed(seed, company_profile)
            payload = {
                "seed": seed,
                "signedSeed": signed_seed
            }

            content_type = Config.DGII_TOKEN_CONTENT_TYPE
            headers = cls._build_headers(content_type=content_type)
            if "xml" in content_type.lower():
                payload_xml = f"<Autenticacion><Semilla>{seed}</Semilla><Firma>{signed_seed}</Firma></Autenticacion>"
                token_response = requests.post(token_url, data=payload_xml, headers=headers, cert=cert_path, timeout=Config.DGII_HTTP_TIMEOUT)
            else:
                token_response = requests.post(token_url, json=payload, headers=headers, cert=cert_path, timeout=Config.DGII_HTTP_TIMEOUT)

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

    @classmethod
    def _simulate_emit(cls, company_profile, invoice_data):
        encf = invoice_data.get("encf", "E310000000001")
        track_id = f"dgii_tr_{uuid.uuid4().hex[:12]}"
        company_rnc = str(company_profile.get("companyRNC", "")).replace("-", "").strip()
        client_rnc = str(invoice_data.get("clientRNC", "000000000")).replace("-", "").strip() or "000000000"
        qr_url = cls._build_qr_url(company_rnc, client_rnc, encf, invoice_data.get("total", 0.0))
        return {
            "success": True,
            "encf": encf,
            "trackId": track_id,
            "xmlSignature": f"SIM-{uuid.uuid4().hex[:12]}",
            "qrCodeURL": qr_url,
            "mode": "FALLBACK",
            "status": "PENDING",
            "dgiiStatus": "PENDING",
            "message": "Simulacion DGII habilitada (sandbox)."
        }

    @classmethod
    def emit_direct(cls, company_profile, invoice_data, sandbox=True):
        """
        Flujo de Emision Directa completo a la DGII:
        1. Generacion de XML.
        2. Firma Digital.
        3. Compresion GZIP.
        4. Envio a Web Services.
        """
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
            signed_xml = DgiiSigner.sign_xml(raw_xml, company_profile)
            xml_signature = DgiiSigner.extract_signature_value(signed_xml) or hashlib.sha256(signed_xml).hexdigest()

            compressed_xml = gzip.compress(signed_xml)
            payload_b64 = base64.b64encode(compressed_xml).decode("utf-8")

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

            payload = {
                "rncEmisor": company_rnc,
                "eNCF": encf,
                "archivo": payload_b64
            }
            payload_log = dict(payload)
            payload_log["archivo"] = "<BASE64_GZIP_STRING>"

            cert_path = cls._prepare_tls_cert(company_profile)
            try:
                headers = cls._build_headers(token=token, content_type=Config.DGII_RECEPCION_CONTENT_TYPE)
                if "xml" in Config.DGII_RECEPCION_CONTENT_TYPE.lower():
                    payload_xml = f"<Enviar><RNCEmisor>{company_rnc}</RNCEmisor><eNCF>{encf}</eNCF><Archivo>{payload_b64}</Archivo></Enviar>"
                    response = requests.post(recepcion_url, data=payload_xml, headers=headers, cert=cert_path, timeout=Config.DGII_HTTP_TIMEOUT)
                else:
                    response = requests.post(recepcion_url, json=payload, headers=headers, cert=cert_path, timeout=Config.DGII_HTTP_TIMEOUT)

                response_data = cls._safe_json(response)
                response_text = response.text if response is not None else ""
                status_code = response.status_code if response is not None else 0
                dgii_status = cls._extract_status(response_data, response_text)
                track_id = cls._extract_track_id(response_data, response_text) or f"dgii_tr_{uuid.uuid4().hex[:12]}"
                qr_url = cls._build_qr_url(company_rnc, client_rnc, encf, invoice_data.get("total", 0.0))

                if status_code >= 200 and status_code < 300:
                    return {
                        "success": True,
                        "encf": encf,
                        "trackId": track_id,
                        "xmlSignature": xml_signature,
                        "qrCodeURL": qr_url,
                        "mode": "API",
                        "status": dgii_status or "PENDING",
                        "dgiiStatus": dgii_status or "PENDING",
                        "requestPayload": payload_log,
                        "responseBody": response_data or response_text,
                        "statusCode": status_code
                    }

                return {
                    "success": False,
                    "error": f"DGII recepcion error HTTP {status_code}",
                    "message": "Error en recepcion DGII.",
                    "requestPayload": payload_log,
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

    @classmethod
    def check_status(cls, company_profile, track_id, sandbox=True):
        endpoints = cls._resolve_endpoints(sandbox=sandbox)
        status_url = endpoints.get("status")
        if not status_url:
            if cls._use_local_simulation(sandbox):
                return {
                    "success": True,
                    "trackId": track_id,
                    "dgiiStatus": "PENDING",
                    "responseBody": {"message": "Simulacion local DGII (status)."},
                    "statusCode": 200
                }
            return {"success": False, "message": "DGII_STATUS_URL no configurado."}

        token, token_error = cls.get_dgii_token(company_profile, sandbox=sandbox)
        if not token:
            return {"success": False, "message": token_error or "No se pudo obtener token DGII."}

        cert_path = cls._prepare_tls_cert(company_profile)
        try:
            headers = cls._build_headers(token=token, content_type=Config.DGII_STATUS_CONTENT_TYPE)
            params = {"trackId": track_id}
            if "xml" in Config.DGII_STATUS_CONTENT_TYPE.lower():
                payload_xml = f"<Consulta><TrackId>{track_id}</TrackId></Consulta>"
                response = requests.post(status_url, data=payload_xml, headers=headers, cert=cert_path, timeout=Config.DGII_HTTP_TIMEOUT)
            else:
                response = requests.get(status_url, params=params, headers=headers, cert=cert_path, timeout=Config.DGII_HTTP_TIMEOUT)

            response_data = cls._safe_json(response)
            response_text = response.text if response is not None else ""
            status_code = response.status_code if response is not None else 0
            dgii_status = cls._extract_status(response_data, response_text)
            track_id_found = cls._extract_track_id(response_data, response_text) or track_id

            if status_code >= 200 and status_code < 300:
                return {
                    "success": True,
                    "trackId": track_id_found,
                    "dgiiStatus": dgii_status or "PENDING",
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

    @classmethod
    def check_dgii_status(cls, company_profile, sandbox=True):
        endpoints = cls._resolve_endpoints(sandbox=sandbox)
        auth_url = endpoints.get("auth")
        token_url = endpoints.get("token")
        if not auth_url:
            if cls._use_local_simulation(sandbox):
                return {
                    "success": True,
                    "status": "ONLINE",
                    "message": "Simulacion local DGII habilitada."
                }
            return {
                "success": False,
                "status": "NOT_CONFIGURED",
                "message": "DGII_AUTH_URL no configurado."
            }

        if cls._use_local_simulation(sandbox) and not token_url:
            return {
                "success": True,
                "status": "ONLINE",
                "message": "Simulacion local DGII habilitada."
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

    @classmethod
    def cancel_direct(cls, company_profile, cancellation_dict, sandbox=True):
        endpoints = cls._resolve_endpoints(sandbox=sandbox)
        cancel_url = endpoints.get("cancel")
        if cls._use_local_simulation(sandbox) and not cancel_url:
            return {
                "success": True,
                "message": "Comprobante anulado directamente (simulado).",
                "cancellationCode": f"CANCEL-{uuid.uuid4().hex[:8].upper()}"
            }

        if not cancel_url:
            return {
                "success": False,
                "message": "DGII_CANCEL_URL no configurado."
            }

        token, token_error = cls.get_dgii_token(company_profile, sandbox=sandbox)
        if not token:
            return {"success": False, "message": token_error or "No se pudo obtener token DGII."}

        cert_path = cls._prepare_tls_cert(company_profile)
        try:
            headers = cls._build_headers(token=token, content_type=Config.DGII_CANCEL_CONTENT_TYPE)
            payload = {
                "rncEmisor": str(company_profile.get("companyRNC", "")).replace("-", "").strip(),
                "series": cancellation_dict.get("series"),
                "startSequence": cancellation_dict.get("startSequence"),
                "endSequence": cancellation_dict.get("endSequence"),
                "reason": cancellation_dict.get("reason", "")
            }

            if "xml" in Config.DGII_CANCEL_CONTENT_TYPE.lower():
                payload_xml = (
                    f"<Anulacion><RNCEmisor>{payload['rncEmisor']}</RNCEmisor>"
                    f"<Serie>{payload['series']}</Serie><Desde>{payload['startSequence']}</Desde>"
                    f"<Hasta>{payload['endSequence']}</Hasta><Motivo>{payload['reason']}</Motivo></Anulacion>"
                )
                response = requests.post(cancel_url, data=payload_xml, headers=headers, cert=cert_path, timeout=Config.DGII_HTTP_TIMEOUT)
            else:
                response = requests.post(cancel_url, json=payload, headers=headers, cert=cert_path, timeout=Config.DGII_HTTP_TIMEOUT)

            response_data = cls._safe_json(response)
            response_text = response.text if response is not None else ""
            status_code = response.status_code if response is not None else 0
            cancellation_code = None
            if isinstance(response_data, dict):
                for key in ("cancellationCode", "codigo", "code", "id"):
                    if response_data.get(key):
                        cancellation_code = response_data.get(key)
                        break
            if not cancellation_code:
                cancellation_code = cls._extract_xml_tag(response_text, "Codigo")

            if status_code >= 200 and status_code < 300:
                return {
                    "success": True,
                    "message": "Comprobante anulado directamente con exito.",
                    "cancellationCode": cancellation_code or f"CANCEL-{uuid.uuid4().hex[:8].upper()}",
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
