import base64
import hashlib
import json
import os
import shutil
import time
import zipfile
from datetime import datetime, timezone
from io import BytesIO

from app.services.db_service import db_firestore, DatabaseService
from app.services.dgii_signer import DgiiSigner
from app.services.dgii_test_data_loader import DgiiTestDataLoader
from app.services.dgii_direct import DgiiDirectService
from app.services.dgii_xml_builder import DgiiXmlBuilder
from app.models.certificacion import CertificacionProcess, CertStep, CertRun, CaseResult
from config import Config

RFCE_THRESHOLD = 250000.00

DGII_ORDER_GROUP1 = ["31", "32", "41", "43", "44", "45", "46", "47"]
DGII_ORDER_GROUP2 = ["33", "34"]

CERT_COLLECTION = "certificacion"

# Ambiente de DGII para certificación — siempre CerteCF, independiente de .env
CERT_DGII_ENVIRONMENT = "CerteCF"

ECF_BASE = f"https://ecf.dgii.gov.do/{CERT_DGII_ENVIRONMENT}"
FC_BASE = f"https://fc.dgii.gov.do/{CERT_DGII_ENVIRONMENT}"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _get_evidence_dir(company_id, step, run_number):
    return f"uploads/certificacion/{company_id}/step{step}/run{run_number}"


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def _get_cert_doc_path(company_id):
    return f"companies/{company_id}/{CERT_COLLECTION}/process"


def _get_run_doc_path(company_id, step, run_number):
    return f"companies/{company_id}/{CERT_COLLECTION}/runs/step{step}_run{run_number}"


class DgiiCertService:

    # ═══════════════════════════════════════════════════════════════
    # Persistencia
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def _get_firestore_doc(cls, path):
        parts = path.split("/")
        doc_ref = db_firestore.collection(parts[0]).document(parts[1])
        if len(parts) > 2:
            doc_ref = db_firestore.collection(parts[0]).document(parts[1]).collection(parts[2]).document(parts[3])
        snap = doc_ref.get()
        if snap.exists:
            return snap.to_dict()
        return None

    @classmethod
    def _set_firestore_doc(cls, path, data, merge=False):
        parts = path.split("/")
        doc_ref = db_firestore.collection(parts[0]).document(parts[1])
        if len(parts) > 2:
            doc_ref = db_firestore.collection(parts[0]).document(parts[1]).collection(parts[2]).document(parts[3])
        doc_ref.set(data, merge=merge)

    @classmethod
    def get_process(cls, company_id):
        path = _get_cert_doc_path(company_id)
        doc = cls._get_firestore_doc(path)
        if doc:
            doc["id"] = company_id
            return doc
        return {
            "id": company_id,
            "current_step": 1,
            "steps": {},
            "created_at": _now(),
            "updated_at": _now(),
        }

    @classmethod
    def save_process(cls, company_id, process_dict):
        process_dict["updated_at"] = _now()
        path = _get_cert_doc_path(company_id)
        cls._set_firestore_doc(path, process_dict, merge=True)

    @classmethod
    def is_certification_completed(cls, company_id):
        process = cls.get_process(company_id)
        steps = process.get("steps", {})
        step_15 = steps.get("15", {})
        return step_15.get("status") == "completed"

    @classmethod
    def is_certification_locked(cls, company_id):
        return cls.is_certification_completed(company_id)

    @classmethod
    def get_step_status(cls, company_id):
        process = cls.get_process(company_id)
        current_step = process.get("current_step", 1)
        steps = process.get("steps", {})
        return {
            "current_step": current_step,
            "steps": steps,
        }

    @classmethod
    def init_step(cls, company_id, step_num):
        process = cls.get_process(company_id)
        steps = process.get("steps", {})
        step_key = str(step_num)

        existing = steps.get(step_key, {})
        current_run = existing.get("current_run", 0) + 1
        runs = existing.get("runs", [])

        step_data = {
            "status": "in_progress",
            "current_run": current_run,
            "runs": runs,
            "started_at": _now(),
            "completed_at": None,
        }
        steps[step_key] = step_data
        process["steps"] = steps
        process["current_step"] = step_num
        cls.save_process(company_id, process)

        return current_run, step_data

    @classmethod
    def complete_step(cls, company_id, step_num, run_number, run_dict):
        process = cls.get_process(company_id)
        steps = process.get("steps", {})
        step_key = str(step_num)
        step_data = steps.get(step_key, {})

        run_dict["status"] = "completed"
        run_dict["completed_at"] = _now()

        runs = step_data.get("runs", [])
        runs.append(run_dict)
        step_data["runs"] = runs
        step_data["status"] = "completed"
        step_data["completed_at"] = _now()

        run_path = _get_run_doc_path(company_id, step_num, run_number)
        cls._set_firestore_doc(run_path, run_dict)

        steps[step_key] = step_data
        process["steps"] = steps
        cls.save_process(company_id, process)

    @classmethod
    def fail_step(cls, company_id, step_num, run_number, run_dict):
        process = cls.get_process(company_id)
        steps = process.get("steps", {})
        step_key = str(step_num)
        step_data = steps.get(step_key, {})

        run_dict["status"] = "failed"
        run_dict["completed_at"] = _now()

        runs = step_data.get("runs", [])
        runs.append(run_dict)
        step_data["runs"] = runs
        step_data["status"] = "failed"
        step_data["completed_at"] = _now()

        run_path = _get_run_doc_path(company_id, step_num, run_number)
        cls._set_firestore_doc(run_path, run_dict)

        steps[step_key] = step_data
        process["steps"] = steps
        cls.save_process(company_id, process)

    @classmethod
    def save_run_progress(cls, company_id, step_num, run_number, run_dict):
        run_dict["updated_at"] = _now()
        run_path = _get_run_doc_path(company_id, step_num, run_number)
        cls._set_firestore_doc(run_path, run_dict)

    @classmethod
    def mark_step_skipped(cls, company_id, step_num):
        process = cls.get_process(company_id)
        steps = process.get("steps", {})
        step_key = str(step_num)
        steps[step_key] = {
            "status": "completed",
            "current_run": 0,
            "runs": [],
            "completed_at": _now(),
        }
        process["steps"] = steps
        cls.save_process(company_id, process)

    @classmethod
    def set_current_step_manual(cls, company_id, step_num):
        process = cls.get_process(company_id)
        process["current_step"] = step_num
        cls.save_process(company_id, process)

    @classmethod
    def get_run(cls, company_id, step_num, run_number):
        run_path = _get_run_doc_path(company_id, step_num, run_number)
        return cls._get_firestore_doc(run_path)

    # ═══════════════════════════════════════════════════════════════
    # Validacion de certificado
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def validate_certificate(cls, company_profile):
        cert_content = company_profile.get("certificateContent", "")
        cert_password = company_profile.get("certificatePassword", "")

        if not cert_content:
            return {"valid": False, "error": "No hay certificado digital cargado."}

        try:
            cert_bundle = DgiiSigner.export_pem_bundle(company_profile)
            if not cert_bundle:
                return {"valid": False, "error": "No se pudo leer el certificado."}
        except Exception as e:
            return {"valid": False, "error": f"Error al leer el certificado: {str(e)}"}

        try:
            from cryptography import x509
            from cryptography.hazmat.backends import default_backend
            cert_data = base64.b64decode(cert_content)
            cert = x509.load_pkcs12(cert_data, cert_password.encode(), default_backend())
            not_after = cert.certificate.not_valid_after_utc.isoformat()
            subject = str(cert.certificate.subject)
            return {
                "valid": True,
                "not_after": not_after,
                "subject": subject,
                "name": company_profile.get("certificateName", ""),
            }
        except Exception:
            return {
                "valid": True,
                "name": company_profile.get("certificateName", ""),
                "has_content": True,
            }

    # ═══════════════════════════════════════════════════════════════
    # Endpoints y autenticación específicos de certificación (CerteCF)
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def _cert_endpoints(cls):
        return {
            "semilla": f"{ECF_BASE}/autenticacion/api/autenticacion/semilla",
            "validar_semilla": f"{ECF_BASE}/autenticacion/api/autenticacion/validarsemilla",
            "recepcion": f"{ECF_BASE}/recepcion/api/facturaselectronicas",
            "rfce_recepcion": f"{FC_BASE}/recepcionfc/api/recepcion/ecf",
            "consulta_resultado": f"{ECF_BASE}/consultaresultado/api/consultas/estado",
            "consulta_estado": f"{ECF_BASE}/consultaestado/api/consultas/estado",
            "aprobacion_comercial": f"{ECF_BASE}/aprobacioncomercial/api/aprobacioncomercial",
        }

    @classmethod
    def _get_cert_token(cls, company_profile):
        import requests
        from xml.sax.saxutils import escape

        endpoints = cls._cert_endpoints()
        semilla_url = endpoints.get("semilla")
        validar_url = endpoints.get("validar_semilla")

        if not semilla_url or not validar_url:
            return None, "Certification endpoints not configured"

        cert_path = DgiiDirectService._prepare_tls_cert(company_profile)

        try:
            headers = DgiiDirectService._build_headers()
            response = requests.get(
                semilla_url, headers=headers, cert=cert_path,
                timeout=Config.DGII_HTTP_TIMEOUT,
            )
            response_data = DgiiDirectService._safe_json(response)
            response_text = response.text if response is not None else ""

            if response.status_code < 200 or response.status_code >= 300:
                return None, f"DGII auth error HTTP {response.status_code}"

            token = DgiiDirectService._extract_token(response_data, response_text)
            if token:
                return token, None

            seed, fecha_seed = DgiiDirectService._extract_seed_xml(response_data, response_text)
            if not seed:
                return None, "No se pudo obtener la semilla de autenticacion (CerteCF)."

            fecha_str = fecha_seed if fecha_seed else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            semilla_xml = (
                '<?xml version="1.0" encoding="utf-8"?>'
                f"<SemillaModel>"
                f"<valor>{escape(seed)}</valor>"
                f"<fecha>{escape(fecha_str)}</fecha>"
                f"</SemillaModel>"
            ).encode("utf-8")

            signed_semilla = DgiiSigner.sign_xml(semilla_xml, company_profile)

            token_response = DgiiDirectService._multipart_post(
                validar_url, signed_semilla, token=None,
                filename="signed_seed.xml", cert_path=cert_path,
            )

            if token_response is None or token_response.status_code < 200 or token_response.status_code >= 300:
                return None, f"Error validando semilla (CerteCF): HTTP {token_response.status_code if token_response else 'N/A'}"

            t_data = DgiiDirectService._safe_json(token_response)
            t_text = token_response.text if token_response else ""
            token = DgiiDirectService._extract_token(t_data, t_text)
            if token:
                return token, None

            return None, f"No se pudo extraer token de la respuesta (CerteCF)."
        except Exception as e:
            return None, f"Error autenticando con DGII CerteCF: {str(e)}"

    # ═══════════════════════════════════════════════════════════════
    # Envío a DGII (forzando CerteCF)
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def _send_ecf(cls, company_profile, signed_xml, token, caso):
        try:
            endpoints = cls._cert_endpoints()
            url = endpoints.get("recepcion")
            cert_path = DgiiDirectService._prepare_tls_cert(company_profile)
            response = DgiiDirectService._multipart_post(
                url, signed_xml, token=token, filename=f"{caso['encf']}.xml", cert_path=cert_path
            )
            text = response.text if response else ""
            data = DgiiDirectService._safe_json(response) if response else None

            track_id = DgiiDirectService._extract_track_id(data, text)
            dgii_status = DgiiDirectService._extract_status(data, text)

            return {
                "success": response is not None and response.status_code == 200,
                "track_id": track_id,
                "dgii_status": dgii_status or "UNKNOWN",
                "response_data": data or {},
            }
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    @classmethod
    def _send_rfce(cls, company_profile, signed_xml, token, caso):
        try:
            endpoints = cls._cert_endpoints()
            url = endpoints.get("rfce_recepcion")
            if not url:
                return {"success": False, "error_message": "RFCE endpoint not configured"}
            cert_path = DgiiDirectService._prepare_tls_cert(company_profile)
            response = DgiiDirectService._multipart_post(
                url, signed_xml, token=token, filename=f"{caso['encf']}_rfce.xml", cert_path=cert_path
            )
            text = response.text if response else ""
            data = DgiiDirectService._safe_json(response) if response else None

            track_id = DgiiDirectService._extract_track_id(data, text)
            dgii_status = DgiiDirectService._extract_status(data, text)

            return {
                "success": response is not None and response.status_code == 200,
                "track_id": track_id,
                "dgii_status": dgii_status or "UNKNOWN",
                "response_data": data or {},
            }
        except Exception as e:
            return {"success": False, "error_message": str(e)}

    # ═══════════════════════════════════════════════════════════════
    # Paso 2: Pruebas de Datos e-CF
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def parse_step2_excel(cls, excel_path):
        sheet1_rows, sheet2_rows = DgiiTestDataLoader.load_workbook(excel_path)

        casos_map = {}
        for row_dict, headers in sheet1_rows:
            tipo = row_dict.get("C", "?")
            encf = row_dict.get("D", f"E{tipo}??????")
            total_str = row_dict.get(
                "EW",
                row_dict.get(
                    next((c for c, h in headers.items() if h.strip() == "MontoTotal"), ""), "0"
                ),
            )
            total = float(total_str) if total_str else 0.0
            casos_map[encf] = {"row_dict": row_dict, "headers": headers, "tipo": tipo, "total": total}

        grupos = {"1": [], "2": [], "3": [], "4": []}
        for encf, caso in casos_map.items():
            tipo = caso["tipo"]
            total = caso["total"]
            is_e32 = tipo == "32"
            is_rfce = is_e32 and total < RFCE_THRESHOLD

            if is_rfce:
                grupos["3"].append({**caso, "encf": encf, "tag": "rfce"})
                grupos["4"].append({**caso, "encf": encf, "tag": "manual_upload"})
            elif tipo in DGII_ORDER_GROUP1:
                grupos["1"].append({**caso, "encf": encf, "tag": "e-cf"})
            elif tipo in DGII_ORDER_GROUP2:
                grupos["2"].append({**caso, "encf": encf, "tag": "e-cf"})

        def sort_key(item):
            t = item["tipo"]
            if t in DGII_ORDER_GROUP1:
                return (DGII_ORDER_GROUP1.index(t), item["encf"])
            elif t in DGII_ORDER_GROUP2:
                return (10 + DGII_ORDER_GROUP2.index(t), item["encf"])
            return (99, item["encf"])

        for g in ["1", "2", "3", "4"]:
            grupos[g].sort(key=sort_key)

        preview = []
        for g in ["1", "2", "3", "4"]:
            for caso in grupos[g]:
                preview.append({
                    "encf": caso["encf"],
                    "tipo": caso["tipo"],
                    "total": caso["total"],
                    "grupo": int(g),
                    "tag": caso["tag"],
                })

        return {
            "total_cases": len(preview),
            "grupo_1_count": len(grupos["1"]),
            "grupo_2_count": len(grupos["2"]),
            "grupo_3_count": len(grupos["3"]),
            "grupo_4_count": len(grupos["4"]),
            "casos": preview,
            "_grupos_raw": grupos,
        }

    @classmethod
    def process_step2_generate(cls, company_id, company_profile, parsed_data, selected_groups=None,
                               dry_run=False, run_number=1):
        if selected_groups is None:
            selected_groups = ["1", "2", "3", "4"]
        selected_groups = [str(g) for g in selected_groups]

        grupos = parsed_data.get("_grupos_raw", {})
        evidence_dir = _get_evidence_dir(company_id, 2, run_number)
        xml_dir = os.path.join(evidence_dir, "xml")
        _ensure_dir(xml_dir)

        token = None
        results = []
        all_cases = []

        for g in ["1", "2", "3", "4"]:
            if g not in selected_groups:
                continue
            for caso in grupos.get(g, []):
                all_cases.append((g, caso))

        total = len(all_cases)
        accepted = rejected = pending_count = 0

        for idx, (g, caso) in enumerate(all_cases, 1):
            encf = caso["encf"]
            tipo = caso["tipo"]
            row_dict = caso["row_dict"]
            headers = caso["headers"]
            tag = caso["tag"]
            total_monto = caso["total"]
            is_rfce = (tag == "rfce")

            case_result = {
                "encf": encf, "tipo": tipo, "total": total_monto,
                "grupo": int(g), "tag": tag, "success": False,
            }

            try:
                if is_rfce:
                    raw_xml = DgiiTestDataLoader.build_rfce_xml_from_row(row_dict, headers)
                else:
                    raw_xml = DgiiTestDataLoader.build_xml_from_row(row_dict, headers)

                raw_path = os.path.join(xml_dir, f"{encf}_raw.xml")
                with open(raw_path, "wb") as f:
                    f.write(raw_xml)
                case_result["raw_xml_path"] = raw_path

                signed_xml = DgiiSigner.sign_xml(raw_xml, company_profile)
                signed_path = os.path.join(xml_dir, f"{encf}_signed.xml")
                with open(signed_path, "wb") as f:
                    f.write(signed_xml)
                case_result["signed_xml_path"] = signed_path

                if is_rfce:
                    sv = DgiiSigner.extract_signature_value(signed_xml) or ""
                    codigo_seg = sv[:6] if len(sv) >= 6 else hashlib.sha256(signed_xml).hexdigest()[:6]
                    case_result["codigo_seguridad"] = codigo_seg
                    e32_signed_path = os.path.join(xml_dir, f"{encf}_e32_firmado.xml")
                    shutil.copy(signed_path, e32_signed_path)

                if dry_run:
                    case_result["success"] = True
                    case_result["dry_run"] = True
                    case_result["dgii_status"] = "DRY_RUN"
                    accepted += 1
                    results.append(case_result)
                    continue

                if g == "4":
                    manual_path = os.path.join(xml_dir, f"{encf}_manual_signed.xml")
                    e32_signed_path = os.path.join(xml_dir, f"{encf}_e32_firmado.xml")
                    if os.path.exists(e32_signed_path):
                        shutil.copy(e32_signed_path, manual_path)
                    else:
                        shutil.copy(signed_path, manual_path)
                    case_result["signed_xml_path"] = manual_path
                    case_result["success"] = True
                    case_result["nota"] = "Subir manualmente en portal DGII > Facturas de consumo < 250Mil"
                    accepted += 1
                    results.append(case_result)
                    continue

                if token is None and g in ("1", "2", "3"):
                    token, err = cls._get_cert_token(company_profile)
                    if err:
                        case_result["error_message"] = f"Error de autenticacion DGII: {err}"
                        rejected += 1
                        results.append(case_result)
                        continue

                if is_rfce and tag == "rfce":
                    result = cls._send_rfce(company_profile, signed_xml, token, caso)
                else:
                    result = cls._send_ecf(company_profile, signed_xml, token, caso)

                case_result.update({
                    "success": result.get("success", False),
                    "track_id": result.get("track_id"),
                    "dgii_status": result.get("dgii_status"),
                    "response_data": result.get("response_data", {}),
                    "error_message": result.get("error_message"),
                })

                if case_result["success"]:
                    accepted += 1
                else:
                    rejected += 1

            except Exception as e:
                case_result["error_message"] = str(e)
                rejected += 1

            results.append(case_result)
            time.sleep(0.3)

        run_dict = {
            "run_number": run_number,
            "step": 2,
            "status": "in_progress",
            "started_at": _now(),
            "total_cases": total,
            "accepted": accepted,
            "rejected": rejected,
            "pending": pending_count,
            "manual_uploaded": 0,
            "cases": results,
            "evidencias_dir": evidence_dir,
            "dry_run": dry_run,
        }

        if rejected > 0:
            cls.fail_step(company_id, 2, run_number, run_dict)
            run_dict["status"] = "failed"
        else:
            cls.complete_step(company_id, 2, run_number, run_dict)
            run_dict["status"] = "completed"

        cls.save_run_progress(company_id, 2, run_number, run_dict)

        return {
            "success": rejected == 0,
            "total": total,
            "accepted": accepted,
            "rejected": rejected,
            "results": results,
            "run_number": run_number,
            "evidence_dir": evidence_dir,
        }

    @classmethod
    def check_case_status(cls, company_profile, track_id):
        try:
            endpoints = cls._cert_endpoints()
            consulta_url = endpoints.get("consulta_estado")
            cert_path = DgiiDirectService._prepare_tls_cert(company_profile)

            result = DgiiDirectService.check_status(
                company_profile, track_id, sandbox=None
            )
            result["success"] = result.get("success", False)
            return {
                "success": result.get("success", False),
                "dgii_status": result.get("dgiiStatus", "UNKNOWN"),
                "track_id": track_id,
                "mensajes": result.get("mensajes", []),
                "response": result,
            }
        except Exception as e:
            return {"success": False, "dgii_status": "ERROR", "track_id": track_id, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════
    # Paso 3: Pruebas de Datos Aprobación Comercial (ACECF)
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def parse_step3_excel(cls, excel_path):
        import openpyxl
        wb = openpyxl.load_workbook(excel_path, data_only=True)
        ws = wb[wb.sheetnames[0]]

        def col_letter(n):
            r = ""
            while n > 0:
                n -= 1
                r = chr(n % 26 + ord("A")) + r
                n //= 26
            return r

        headers = {}
        for cell in ws[1]:
            if cell.value is not None:
                headers[col_letter(cell.column)] = str(cell.value).strip()

        rows = []
        for row in ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=False):
            row_dict = {}
            for cell in row:
                if cell.value is not None and str(cell.value).strip() != "#e":
                    row_dict[col_letter(cell.column)] = str(cell.value).strip()
            if row_dict:
                rows.append((row_dict, headers))
        wb.close()

        preview = []
        grupos_raw = {"1": []}
        for row_dict, headers in rows:
            encf = row_dict.get("D", row_dict.get("E", "?"))
            tipo = "ACECF"
            preview.append({"encf": encf, "tipo": tipo, "grupo": 1})
            grupos_raw["1"].append({"row_dict": row_dict, "headers": headers, "encf": encf})

        return {"total_cases": len(preview), "casos": preview, "_grupos_raw": grupos_raw}

    @classmethod
    def process_step3_generate(cls, company_id, company_profile, parsed_data,
                               dry_run=False, run_number=1):
        grupos = parsed_data.get("_grupos_raw", {})
        evidence_dir = _get_evidence_dir(company_id, 3, run_number)
        xml_dir = os.path.join(evidence_dir, "xml")
        _ensure_dir(xml_dir)

        token, err = cls._get_cert_token(company_profile)
        if err:
            return {"success": False, "error": f"Error de autenticacion: {err}"}

        endpoints = cls._cert_endpoints()
        acecf_url = endpoints.get("aprobacion_comercial")

        results = []
        all_cases = grupos.get("1", [])
        total = len(all_cases)
        accepted = rejected = 0

        for idx, caso in enumerate(all_cases, 1):
            encf = caso["encf"]
            row_dict = caso["row_dict"]
            headers = caso["headers"]

            case_result = {"encf": encf, "tipo": "ACECF", "success": False, "grupo": 1}

            try:
                raw_xml = DgiiTestDataLoader.build_acecf_xml_from_row(row_dict, headers)
                raw_path = os.path.join(xml_dir, f"ACECF_{encf}_raw.xml")
                with open(raw_path, "wb") as f:
                    f.write(raw_xml)
                case_result["raw_xml_path"] = raw_path

                signed_xml = DgiiSigner.sign_xml(raw_xml, company_profile)
                signed_path = os.path.join(xml_dir, f"ACECF_{encf}_signed.xml")
                with open(signed_path, "wb") as f:
                    f.write(signed_xml)
                case_result["signed_xml_path"] = signed_path

                if dry_run:
                    case_result["success"] = True
                    case_result["dry_run"] = True
                    case_result["dgii_status"] = "DRY_RUN"
                    accepted += 1
                    results.append(case_result)
                    continue

                cert_path = DgiiDirectService._prepare_tls_cert(company_profile)
                response = DgiiDirectService._multipart_post(
                    acecf_url, signed_xml, token=token, filename=f"ACECF_{encf}.xml", cert_path=cert_path
                )
                text = response.text if response else ""
                data = DgiiDirectService._safe_json(response) if response else None

                success = response is not None and response.status_code == 200
                case_result["success"] = success
                case_result["response_data"] = data or {}
                case_result["track_id"] = DgiiDirectService._extract_track_id(data, text)

                if success:
                    accepted += 1
                else:
                    rejected += 1

            except Exception as e:
                case_result["error_message"] = str(e)
                rejected += 1

            results.append(case_result)
            time.sleep(0.3)

        run_dict = {
            "run_number": run_number,
            "step": 3,
            "status": "in_progress",
            "started_at": _now(),
            "total_cases": total,
            "accepted": accepted,
            "rejected": rejected,
            "pending": 0,
            "cases": results,
            "evidencias_dir": evidence_dir,
            "dry_run": dry_run,
        }

        if rejected > 0:
            cls.fail_step(company_id, 3, run_number, run_dict)
            run_dict["status"] = "failed"
        else:
            cls.complete_step(company_id, 3, run_number, run_dict)
            run_dict["status"] = "completed"

        cls.save_run_progress(company_id, 3, run_number, run_dict)

        return {
            "success": rejected == 0,
            "total": total,
            "accepted": accepted,
            "rejected": rejected,
            "results": results,
            "run_number": run_number,
            "evidence_dir": evidence_dir,
        }

    # ═══════════════════════════════════════════════════════════════
    # Descarga de evidencias
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def download_xml(cls, xml_path):
        if not os.path.exists(xml_path):
            return None
        with open(xml_path, "rb") as f:
            return f.read()

    @classmethod
    def download_all_evidence_zip(cls, company_id, step, run_number):
        evidence_dir = _get_evidence_dir(company_id, step, run_number)
        if not os.path.exists(evidence_dir):
            return None

        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(evidence_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, evidence_dir)
                    zf.write(file_path, arcname)

        buffer.seek(0)
        return buffer.getvalue()

    @classmethod
    def mark_manual_uploaded(cls, company_id, step_num, run_number, encf):
        run_path = _get_run_doc_path(company_id, step_num, run_number)
        run_data = cls._get_firestore_doc(run_path) or {}
        cases = run_data.get("cases", [])

        manual_count = 0
        for case in cases:
            if case.get("encf") == encf:
                case["manual_uploaded"] = True
            if case.get("manual_uploaded"):
                manual_count += 1

        run_data["cases"] = cases
        run_data["manual_uploaded"] = manual_count
        cls.save_run_progress(company_id, step_num, run_number, run_data)
        return {"success": True, "manual_uploaded": manual_count}

    # ═══════════════════════════════════════════════════════════════
    # Paso 4: Pruebas de Simulación e-CF (emisión real desde el sistema)
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def emit_for_certification(cls, company_profile, invoice_dict):
        token, err = cls._get_cert_token(company_profile)
        if err:
            return {"success": False, "error": f"Error de autenticacion: {err}"}

        endpoints = cls._cert_endpoints()
        recepcion_url = endpoints.get("recepcion")
        rfce_url = endpoints.get("rfce_recepcion")

        try:
            raw_xml = DgiiXmlBuilder.build_invoice_xml(company_profile, invoice_dict)
            signed_xml = DgiiSigner.sign_xml(raw_xml, company_profile)
            xml_signature = DgiiSigner.extract_signature_value(signed_xml) or hashlib.sha256(signed_xml).hexdigest()
            codigo_seguridad = xml_signature[:6]

            encf = invoice_dict.get("encf", "")
            company_rnc = str(company_profile.get("companyRNC", "")).replace("-", "").strip()
            total = float(invoice_dict.get("total", 0.0))
            ecf_type = invoice_dict.get("ecfType", "")
            is_rfce = "E32" in ecf_type and total < RFCE_THRESHOLD

            if is_rfce and rfce_url:
                from app.services.dgii_xml_builder import DgiiXmlBuilder
                rfce_xml = DgiiXmlBuilder.build_rfce_xml(company_profile, invoice_dict, codigo_seguridad)
                rfce_signed = DgiiSigner.sign_xml(rfce_xml, company_profile)
                cert_path = DgiiDirectService._prepare_tls_cert(company_profile)
                response = DgiiDirectService._multipart_post(
                    rfce_url, rfce_signed, token=token, filename=f"{company_rnc}_rfce.xml", cert_path=cert_path
                )
            else:
                cert_path = DgiiDirectService._prepare_tls_cert(company_profile)
                filename = f"{company_rnc}{encf}.xml"
                response = DgiiDirectService._multipart_post(
                    recepcion_url, signed_xml, token=token, filename=filename, cert_path=cert_path
                )

            text = response.text if response else ""
            data = DgiiDirectService._safe_json(response) if response else None
            status_code = response.status_code if response else 0
            dgii_status = DgiiDirectService._extract_status(data, text)
            track_id = DgiiDirectService._extract_track_id(data, text)

            success = status_code >= 200 and status_code < 300

            return {
                "success": success,
                "track_id": track_id,
                "dgii_status": dgii_status or "UNKNOWN",
                "codigo_seguridad": codigo_seguridad,
                "status_code": status_code,
                "response_data": data or {},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def process_step4(cls, company_id, company_profile, invoice_ids, owner_uid, sandbox_origin=True,
                      run_number=1):
        evidence_dir = _get_evidence_dir(company_id, 4, run_number)
        xml_dir = os.path.join(evidence_dir, "xml")
        _ensure_dir(xml_dir)

        results = []
        total = len(invoice_ids)
        accepted = rejected = 0

        for idx, inv_id in enumerate(invoice_ids, 1):
            try:
                invoice_data = DatabaseService.get_invoice(
                    owner_uid, inv_id, sandbox=sandbox_origin, company_id=company_id
                )
                if not invoice_data:
                    results.append({
                        "encf": inv_id, "tipo": "?", "total": 0,
                        "success": False, "error_message": f"Factura {inv_id} no encontrada",
                    })
                    rejected += 1
                    continue

                result = cls.emit_for_certification(company_profile, invoice_data)

                raw_xml = DgiiXmlBuilder.build_invoice_xml(company_profile, invoice_data)
                raw_path = os.path.join(xml_dir, f"{inv_id}_raw.xml")
                with open(raw_path, "wb") as f:
                    f.write(raw_xml)

                signed_xml = DgiiSigner.sign_xml(raw_xml, company_profile)
                signed_path = os.path.join(xml_dir, f"{inv_id}_signed.xml")
                with open(signed_path, "wb") as f:
                    f.write(signed_xml)

                case_result = {
                    "encf": invoice_data.get("encf", inv_id),
                    "tipo": invoice_data.get("ecfType", "?"),
                    "total": float(invoice_data.get("total", 0)),
                    "grupo": 1,
                    "tag": "simulacion",
                    "success": result.get("success", False),
                    "track_id": result.get("track_id"),
                    "dgii_status": result.get("dgii_status"),
                    "response_data": result.get("response_data", {}),
                    "error_message": result.get("error"),
                    "signed_xml_path": signed_path,
                    "raw_xml_path": raw_path,
                }

                if result.get("success"):
                    accepted += 1
                else:
                    rejected += 1

                results.append(case_result)
            except Exception as e:
                results.append({
                    "encf": inv_id, "tipo": "?", "total": 0,
                    "success": False, "error_message": str(e),
                })
                rejected += 1

            time.sleep(0.5)

        run_dict = {
            "run_number": run_number,
            "step": 4,
            "status": "in_progress",
            "started_at": _now(),
            "total_cases": total,
            "accepted": accepted,
            "rejected": rejected,
            "pending": 0,
            "cases": results,
            "evidencias_dir": evidence_dir,
        }

        if rejected > 0:
            cls.fail_step(company_id, 4, run_number, run_dict)
            run_dict["status"] = "failed"
        else:
            cls.complete_step(company_id, 4, run_number, run_dict)
            run_dict["status"] = "completed"

        cls.save_run_progress(company_id, 4, run_number, run_dict)

        return {
            "success": rejected == 0,
            "total": total,
            "accepted": accepted,
            "rejected": rejected,
            "results": results,
            "run_number": run_number,
            "evidence_dir": evidence_dir,
        }

    @classmethod
    def get_available_invoices(cls, owner_uid, company_id, sandbox=True, limit=50):
        invoices = DatabaseService.get_invoices(
            owner_uid, sandbox=sandbox, company_id=company_id
        ) or []
        result = []
        for inv in invoices[:limit]:
            result.append({
                "id": inv.get("id", ""),
                "invoiceNumber": inv.get("invoiceNumber", ""),
                "encf": inv.get("encf", ""),
                "ecfType": inv.get("ecfType", ""),
                "date": inv.get("date", ""),
                "clientName": inv.get("clientName", ""),
                "clientRNC": inv.get("clientRNC", ""),
                "total": float(inv.get("total", 0) or 0),
            })
        return result

    # ═══════════════════════════════════════════════════════════════
    # Paso 1: Firma de XML de postulacion
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def sign_postulacion_xml(cls, company_profile, raw_xml_bytes):
        signed_xml = DgiiSigner.sign_xml(raw_xml_bytes, company_profile)
        rnc = company_profile.get("companyRNC", "").replace("-", "")
        filename = f"{rnc}_postulacion_firmada.xml" if rnc else "postulacion_firmada.xml"
        return signed_xml, filename
