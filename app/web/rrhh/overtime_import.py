"""RRHH module — Importacion masiva de Horas Extras."""

from datetime import date, datetime, timezone
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
)
from app.services import hr_data_service as hr
from app.services.overtime_service import OvertimeService
from app.services.ai_service import AIService
from app.extensions import limiter
import csv, html, io, json, os, re, uuid, threading


TEMP_IMPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", "temp_imports")
JOB_DIR = os.path.join(TEMP_IMPORT_DIR, "jobs")

OVERTIME_CSV_FIELDS = [
    ("*employeeCedula",   "Cédula del empleado",   True,  ["cedula", "rnc", "identificacion", "identificación", "empleado", "id", "documento"]),
    ("*overtimeTypeCode", "Tipo de hora extra",    True,  ["tipo", "type", "codigo", "he", "horaextra", "tipo_he"]),
    ("*date",             "Fecha",                 True,  ["fecha", "date", "dia", "día"]),
    ("*fromTime",         "Hora inicio (HH:MM)",   True,  ["desde", "inicio", "from", "entrada", "hora_inicio", "hora desde"]),
    ("*toTime",           "Hora fin (HH:MM)",      True,  ["hasta", "fin", "to", "salida", "hora_fin", "hora hasta"]),
    ("comment",           "Comentario",            False, ["comentario", "nota", "motivo", "observacion", "observación"]),
    ("sourceReference",   "Referencia",            False, ["referencia", "ref", "source", "referencia_origen"]),
]

OVERTIME_REQUIRED_FIELDS = [f[0].lstrip("*") for f in OVERTIME_CSV_FIELDS if f[2]]
OVERTIME_TARGET_FIELDS = [
    {"id": f[0].lstrip("*"), "name": f"{f[1]}{' *' if f[2] else ''}", "required": f[2], "suggestions": f[3]}
    for f in OVERTIME_CSV_FIELDS
]

OVERTIME_CSV_HEADERS = [f[0] for f in OVERTIME_CSV_FIELDS]
OVERTIME_EXAMPLE_ROW = [
    "40212345678", "HE01", "2026-07-15", "18:00", "22:00", "Cierre de mes", "CIERRE-JUL",
]


def _get_delimiter(first_line):
    for delimiter in [";", "\t", ","]:
        if delimiter in first_line:
            return delimiter
    return ","


def _strip_asterisk(h):
    return h[1:] if h.startswith("*") else h


def _compute_minutes(from_time, to_time):
    if not from_time or not to_time:
        return 0
    try:
        def _parse(t):
            parts = str(t).strip().split(":")
            if len(parts) >= 2:
                return int(parts[0]) * 60 + int(parts[1])
            return None
        fm = _parse(from_time)
        tm = _parse(to_time)
        if fm is not None and tm is not None:
            if tm > fm:
                return tm - fm
    except Exception:
        pass
    return 0


@web_rrhh_bp.route("/rrhh/overtime/import")
def overtime_import_wizard():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    overtime_types = hr.get_overtime_types(company_id, sandbox=sandbox)
    active_types = [t["code"] for t in overtime_types if t.get("active", True)]

    system_defaults = {
        "overtimeTypeCode": active_types,
    }

    return render_template(
        "rrhh/overtime/import.html",
        active_page="rrhh_overtime",
        target_fields=OVERTIME_TARGET_FIELDS,
        required_fields=OVERTIME_REQUIRED_FIELDS,
        system_defaults=system_defaults,
    )


@web_rrhh_bp.route("/rrhh/overtime/import/template")
def overtime_import_template():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(OVERTIME_CSV_HEADERS)
    writer.writerow(OVERTIME_EXAMPLE_ROW)
    buf = io.BytesIO(csv_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    return send_file(buf, mimetype="text/csv", as_attachment=True,
                     download_name="plantilla_horas_extras.csv")


@web_rrhh_bp.route("/rrhh/overtime/import/upload", methods=["POST"])
def overtime_import_upload():
    if _login_required():
        return jsonify({"success": False, "error": "No autorizado"}), 401

    file = request.files.get("file")
    if not file:
        return jsonify({"success": False, "error": "Por favor sube un archivo CSV valido."}), 400

    from app.utils.security import validate_uploaded_file, sanitize_filename

    valid, err_msg = validate_uploaded_file(file, allowed_extensions={"csv"})
    if not valid:
        return jsonify({"success": False, "error": err_msg}), 400

    os.makedirs(TEMP_IMPORT_DIR, exist_ok=True)
    safe_name = sanitize_filename(file.filename)
    file_id = f"temp_ot_{session['user']['uid']}_{uuid.uuid4().hex}_{safe_name}"
    temp_path = os.path.join(TEMP_IMPORT_DIR, file_id)
    file.save(temp_path)

    try:
        with open(temp_path, "r", encoding="utf-8-sig", errors="ignore") as f:
            first_line = f.readline()
            delimiter = _get_delimiter(first_line)
            f.seek(0)
            reader = csv.reader(f, delimiter=delimiter)
            headers = next(reader, None)
            if not headers:
                raise ValueError("El archivo CSV esta vacio.")
            headers = [h.strip() for h in headers]
            data_rows = list(reader)
            row_count = len(data_rows)
            preview_rows = []
            for row in data_rows[:5]:
                if row:
                    preview_rows.append([cell.strip() for cell in row])
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({"success": False, "error": f"Error al analizar el archivo: {html.escape(str(e))}"}), 400

    if row_count == 0:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({"success": False, "error": "El archivo CSV no contiene filas de datos. Solo se encontro la cabecera."}), 400

    return jsonify({
        "success": True,
        "headers": headers,
        "preview_rows": preview_rows,
        "temp_filename": file_id,
        "row_count": row_count,
        "delimiter": delimiter,
        "target_fields": OVERTIME_TARGET_FIELDS,
    })


@web_rrhh_bp.route("/rrhh/overtime/import/ai-suggest", methods=["POST"])
def overtime_import_ai_suggest():
    if _login_required():
        return jsonify({"success": False, "message": "No autorizado"}), 401

    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    data = request.get_json() or {}
    headers = data.get("headers", [])
    target_fields = data.get("target_fields", [])

    if not headers or not target_fields:
        return jsonify({"success": False, "message": "Datos faltantes."}), 400

    res = AIService.suggest_mapping(owner_uid, headers, target_fields)
    return jsonify(res)


@web_rrhh_bp.route("/rrhh/overtime/import/process", methods=["POST"])
def overtime_import_process():
    if _login_required():
        return jsonify({"success": False, "error": "No autorizado"}), 401

    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    temp_filename = request.form.get("temp_filename")
    if not temp_filename:
        return jsonify({"success": False, "error": "Informacion de importacion incompleta."}), 400

    temp_path = os.path.join(TEMP_IMPORT_DIR, temp_filename)
    if not os.path.exists(temp_path):
        return jsonify({"success": False, "error": "El archivo temporal ya no existe. Intenta subirlo de nuevo."}), 400

    mapping = {}
    for key, value in request.form.items():
        if key.startswith("map_") and value:
            field_id = key.replace("map_", "")
            try:
                mapping[field_id] = int(value)
            except ValueError:
                pass

    os.makedirs(JOB_DIR, exist_ok=True)
    job_id = str(uuid.uuid4())
    job_file = os.path.join(JOB_DIR, f"{job_id}.json")

    def _write_job(state):
        with open(job_file, "w") as jf:
            json.dump(state, jf, default=str)

    try:
        with open(temp_path, "r", encoding="utf-8-sig", errors="ignore") as f:
            first_line = f.readline()
            delimiter = _get_delimiter(first_line)
            f.seek(0)
            reader = csv.reader(f, delimiter=delimiter)
            next(reader, None)
            rows = list(reader)
    except Exception as e:
        return jsonify({"success": False, "error": f"Error al leer el archivo: {html.escape(str(e))}"}), 500

    total = len([r for r in rows if r])
    if total == 0:
        return jsonify({"success": False, "error": "No hay filas de datos para procesar."}), 400

    state = {
        "job_id": job_id, "status": "processing", "total": total,
        "processed": 0, "imported": 0, "skipped": 0, "errors": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _write_job(state)

    field_defaults = {}
    for key, value in request.form.items():
        if key.startswith("default_") and value.strip():
            field_defaults[key.replace("default_", "")] = value.strip()

    def _get_val(row_data, field_id, default=""):
        if field_id in mapping and len(row_data) > mapping[field_id]:
            val = row_data[mapping[field_id]].strip()
            if val:
                return val
        return field_defaults.get(field_id, default)

    def process_rows():
        imported = 0
        skipped = 0
        errors = []
        processed = 0
        try:
            update_every = max(1, total // 20)

            employees_list = hr.get_employees(company_id, sandbox=sandbox)
            cedula_to_emp = {}
            id_to_emp = {}
            for e in employees_list:
                ced = (e.get("cedula") or e.get("idNumber") or "").strip()
                if ced:
                    cedula_to_emp[ced] = e
                    cedula_to_emp[re.sub(r"\D", "", ced)] = e
                eid = e.get("id", "")
                if eid:
                    id_to_emp[eid] = e

            active_types_list = hr.get_overtime_types(company_id, sandbox=sandbox)
            active_types = {t["code"]: t for t in active_types_list if t.get("active", True)}

            def resolve_employee(identifier):
                ident = str(identifier).strip()
                if not ident:
                    return None
                if ident in id_to_emp:
                    return id_to_emp[ident]
                clean = re.sub(r"\D", "", ident)
                if clean in cedula_to_emp:
                    return cedula_to_emp[clean]
                cedulas_map = {re.sub(r"\D", "", k): v for k, v in cedula_to_emp.items()}
                if clean in cedulas_map:
                    return cedulas_map[clean]
                for e in employees_list:
                    name = (e.get("fullName") or "").lower()
                    if ident.lower() in name or name in ident.lower():
                        return e
                return None

            groups = {}
            group_order = []

            for row_idx, row_data in enumerate(rows):
                if not row_data:
                    continue
                processed += 1
                row_num = row_idx + 2

                try:
                    emp_identifier = _get_val(row_data, "employeeCedula")
                    emp = resolve_employee(emp_identifier)
                    if not emp:
                        errors.append({"row": row_num, "reason": f"No se encontro empleado con identificacion: '{emp_identifier}'"})
                        skipped += 1
                        if processed % update_every == 0 or processed == total:
                            _write_job({
                                "job_id": job_id, "status": "processing", "total": total,
                                "processed": processed, "imported": imported, "skipped": skipped,
                                "errors": errors[-30:],
                            })
                        continue

                    emp_id = emp["id"]
                    emp_name = emp.get("fullName", "")
                    emp_code = emp.get("code", "")
                    department = emp.get("department", "")

                    type_code = _get_val(row_data, "overtimeTypeCode")
                    if not type_code:
                        errors.append({"row": row_num, "reason": "Falta tipo de hora extra (overtimeTypeCode)"})
                        skipped += 1
                        if processed % update_every == 0 or processed == total:
                            _write_job({
                                "job_id": job_id, "status": "processing", "total": total,
                                "processed": processed, "imported": imported, "skipped": skipped,
                                "errors": errors[-30:],
                            })
                        continue
                    type_code = type_code.strip().upper()

                    if type_code not in active_types:
                        errors.append({"row": row_num, "reason": f"Tipo de hora extra '{type_code}' no existe o no esta activo"})
                        skipped += 1
                        if processed % update_every == 0 or processed == total:
                            _write_job({
                                "job_id": job_id, "status": "processing", "total": total,
                                "processed": processed, "imported": imported, "skipped": skipped,
                                "errors": errors[-30:],
                            })
                        continue

                    date_raw = _get_val(row_data, "date")
                    if not date_raw:
                        errors.append({"row": row_num, "reason": "Falta fecha (date)"})
                        skipped += 1
                        if processed % update_every == 0 or processed == total:
                            _write_job({
                                "job_id": job_id, "status": "processing", "total": total,
                                "processed": processed, "imported": imported, "skipped": skipped,
                                "errors": errors[-30:],
                            })
                        continue

                    parsed_date = None
                    date_clean = str(date_raw).strip()
                    if " " in date_clean:
                        date_clean = date_clean.split(" ")[0]
                    try:
                        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_clean):
                            datetime.strptime(date_clean, "%Y-%m-%d")
                            parsed_date = date_clean
                        elif re.match(r"^\d{2}/\d{2}/\d{4}$", date_clean):
                            dt = datetime.strptime(date_clean, "%d/%m/%Y")
                            parsed_date = dt.strftime("%Y-%m-%d")
                        elif re.match(r"^\d{2}-\d{2}-\d{4}$", date_clean):
                            dt = datetime.strptime(date_clean, "%d-%m-%Y")
                            parsed_date = dt.strftime("%Y-%m-%d")
                        elif re.match(r"^\d{2}/\d{2}/\d{2}$", date_clean):
                            dt = datetime.strptime(date_clean, "%d/%m/%y")
                            parsed_date = dt.strftime("%Y-%m-%d")
                        else:
                            raise ValueError
                    except Exception:
                        errors.append({"row": row_num, "reason": f"Fecha invalida: '{date_raw}'. Use DD/MM/AAAA o AAAA-MM-DD."})
                        skipped += 1
                        if processed % update_every == 0 or processed == total:
                            _write_job({
                                "job_id": job_id, "status": "processing", "total": total,
                                "processed": processed, "imported": imported, "skipped": skipped,
                                "errors": errors[-30:],
                            })
                        continue

                    from_time = _get_val(row_data, "fromTime")
                    to_time = _get_val(row_data, "toTime")

                    if not from_time or not to_time:
                        errors.append({"row": row_num, "reason": "Falta hora inicio (fromTime) o hora fin (toTime)"})
                        skipped += 1
                        if processed % update_every == 0 or processed == total:
                            _write_job({
                                "job_id": job_id, "status": "processing", "total": total,
                                "processed": processed, "imported": imported, "skipped": skipped,
                                "errors": errors[-30:],
                            })
                        continue

                    minutes = _compute_minutes(from_time, to_time)
                    if minutes <= 0:
                        errors.append({"row": row_num, "reason": f"Rango invalido: {from_time} a {to_time} (minutos={minutes}). La hora fin debe ser mayor."})
                        skipped += 1
                        if processed % update_every == 0 or processed == total:
                            _write_job({
                                "job_id": job_id, "status": "processing", "total": total,
                                "processed": processed, "imported": imported, "skipped": skipped,
                                "errors": errors[-30:],
                            })
                        continue

                    comment = _get_val(row_data, "comment")
                    source_ref = _get_val(row_data, "sourceReference")

                    group_key = (emp_id, parsed_date, type_code)
                    if group_key not in groups:
                        groups[group_key] = {
                            "employeeId": emp_id,
                            "employeeName": emp_name,
                            "employeeCode": emp_code,
                            "department": department,
                            "date": parsed_date,
                            "overtimeTypeCode": type_code,
                            "comment": comment or "",
                            "sourceReference": source_ref or "",
                            "details": [],
                            "totalMinutes": 0,
                        }
                        group_order.append(group_key)

                    groups[group_key]["details"].append({
                        "date": parsed_date,
                        "fromTime": from_time,
                        "toTime": to_time,
                        "minutes": minutes,
                    })
                    groups[group_key]["totalMinutes"] += minutes

                except Exception as e:
                    errors.append({"row": row_num, "reason": f"Error inesperado: {html.escape(str(e))}"})
                    skipped += 1

                if processed % update_every == 0 or processed == total:
                    _write_job({
                        "job_id": job_id, "status": "processing", "total": total,
                        "processed": processed, "imported": imported, "skipped": skipped,
                        "errors": errors[-30:],
                    })

            group_count = len(groups)
            g_processed = 0
            for group_key in group_order:
                group = groups[group_key]
                g_processed += 1
                try:
                    data_payload = {
                        "employeeId": group["employeeId"],
                        "employeeCode": group["employeeCode"],
                        "employeeName": group["employeeName"],
                        "departmentCode": group["department"],
                        "payrollCode": "",
                        "companyCode": "",
                        "date": group["date"],
                        "overtimeTypeCode": group["overtimeTypeCode"],
                        "totalMinutes": group["totalMinutes"],
                        "comment": group["comment"],
                        "source": "import",
                        "sourceReference": group["sourceReference"],
                        "details": group["details"],
                    }
                    OvertimeService.create_record(company_id, data_payload, user_email, sandbox=sandbox)
                    imported += 1
                except Exception as e:
                    errors.append({"row": 0, "reason": f"Error al crear registro para empleado {group['employeeName']} ({group['date']}): {html.escape(str(e))}"})
                    skipped += 1

                if g_processed % max(1, group_count // 10) == 0 or g_processed == group_count:
                    _write_job({
                        "job_id": job_id, "status": "processing", "total": total,
                        "processed": processed, "imported": imported, "skipped": skipped,
                        "errors": errors[-30:],
                    })

            final_state = {
                "job_id": job_id, "status": "completed", "total": total,
                "processed": processed, "imported": imported, "skipped": skipped,
                "errors": errors,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            _write_job(final_state)
        except Exception as e:
            print(f"[overtime_import] Error fatal en process_rows: {e}")
            error_state = {
                "job_id": job_id, "status": "failed", "total": total,
                "processed": processed, "imported": imported, "skipped": skipped,
                "errors": errors[-30:] if errors else [{"row": 0, "reason": f"Error fatal: {html.escape(str(e))}"}],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            }
            try:
                _write_job(error_state)
            except Exception:
                pass

    thread = threading.Thread(target=process_rows)
    thread.daemon = True
    thread.start()

    return jsonify({"success": True, "job_id": job_id, "total": total})


@web_rrhh_bp.route("/rrhh/overtime/import/status/<job_id>")
@limiter.exempt
def overtime_import_status(job_id):
    if _login_required():
        return jsonify({"status": "not_found", "error": "No autorizado"}), 401
    job_file = os.path.join(JOB_DIR, job_id + ".json")
    if os.path.exists(job_file):
        try:
            with open(job_file, "r") as jf:
                state = json.load(jf)
            return jsonify(state)
        except Exception:
            return jsonify({"status": "not_found", "error": "Error al leer el estado del job"}), 500
    return jsonify({"status": "not_found", "error": "Job no encontrado"}), 404
