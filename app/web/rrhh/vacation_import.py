"""RRHH module — Importación masiva de historial de vacaciones."""

from datetime import date, datetime, timezone
from flask import render_template, request, redirect, url_for, session, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
)
from app.services import hr_data_service as hr
from app.services.payroll_service import PayrollService
from app.services.payroll_audit_service import log_action
from app.services.ai_service import AIService
from app.extensions import limiter
import csv, html, io, json, os, re, uuid, threading


TEMP_IMPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", "temp_imports")
JOB_DIR = os.path.join(TEMP_IMPORT_DIR, "jobs")

VACATION_CSV_FIELDS = [
    ("*employeeCedula", "Cédula del empleado",                True,  ["cedula", "rnc", "identificacion", "identificación", "empleado", "id", "documento"]),
    ("*startDate",      "Fecha inicio (vacaciones)",          True,  ["desde", "inicio", "fecha inicio", "fecha_inicio", "fecha desde", "start", "inicio vacaciones"]),
    ("*endDate",        "Fecha fin (vacaciones)",             True,  ["hasta", "fin", "fecha fin", "fecha_fin", "fecha hasta", "end", "fin vacaciones"]),
    ("days",            "Días tomados (opcional)",            False, ["dias", "días", "dias tomados", "días tomados", "dias_tomados", "duracion", "duración"]),
    ("notes",           "Notas",                              False, ["notas", "nota", "comentario", "observacion", "observación", "motivo"]),
]

VACATION_REQUIRED_FIELDS = [f[0].lstrip("*") for f in VACATION_CSV_FIELDS if f[2]]
VACATION_TARGET_FIELDS = [
    {"id": f[0].lstrip("*"), "name": f"{f[1]}{' *' if f[2] else ''}", "required": f[2], "suggestions": f[3]}
    for f in VACATION_CSV_FIELDS
]

VACATION_CSV_HEADERS = [f[0] for f in VACATION_CSV_FIELDS]
VACATION_EXAMPLE_ROW = [
    "40212345678", "2026-03-02", "2026-03-13", "10", "Vacaciones migradas del sistema anterior",
]


def _get_delimiter(first_line):
    for delimiter in [";", "\t", ","]:
        if delimiter in first_line:
            return delimiter
    return ","


def _normalize_date(raw_value):
    """Normaliza fechas DD/MM/AAAA, AAAA-MM-DD, DD-MM-AAAA y DD/MM/AA a AAAA-MM-DD."""
    date_clean = str(raw_value or "").strip()
    if " " in date_clean:
        date_clean = date_clean.split(" ")[0]
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_clean):
            datetime.strptime(date_clean, "%Y-%m-%d")
            return date_clean
        elif re.match(r"^\d{2}/\d{2}/\d{4}$", date_clean):
            dt = datetime.strptime(date_clean, "%d/%m/%Y")
            return dt.strftime("%Y-%m-%d")
        elif re.match(r"^\d{2}-\d{2}-\d{4}$", date_clean):
            dt = datetime.strptime(date_clean, "%d-%m-%Y")
            return dt.strftime("%Y-%m-%d")
        elif re.match(r"^\d{2}/\d{2}/\d{2}$", date_clean):
            dt = datetime.strptime(date_clean, "%d/%m/%y")
            return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    return None


def _resolve_employee(identifier, id_to_emp, cedula_to_emp, employees_list):
    """Resuelve un empleado por id, cédula/RNC normalizada o coincidencia de nombre."""
    ident = str(identifier or "").strip()
    if not ident:
        return None
    if ident in id_to_emp:
        return id_to_emp[ident]
    clean = re.sub(r"\D", "", ident)
    if clean:
        if clean in cedula_to_emp:
            return cedula_to_emp[clean]
        for key, emp in cedula_to_emp.items():
            if re.sub(r"\D", "", key) == clean:
                return emp
    for e in employees_list:
        name = (e.get("fullName") or "").lower()
        if ident.lower() in name or name in ident.lower():
            return e
    return None


@web_rrhh_bp.route("/rrhh/vacations/import")
def vacation_import():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    return render_template(
        "rrhh/vacation_import.html",
        active_page="rrhh_attendance",
        target_fields=VACATION_TARGET_FIELDS,
        required_fields=VACATION_REQUIRED_FIELDS,
        system_defaults={},
    )


@web_rrhh_bp.route("/rrhh/vacations/import/template")
def vacation_import_template():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(VACATION_CSV_HEADERS)
    writer.writerow(VACATION_EXAMPLE_ROW)
    buf = io.BytesIO(csv_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    return send_file(buf, mimetype="text/csv", as_attachment=True,
                     download_name="plantilla_historial_vacaciones.csv")


@web_rrhh_bp.route("/rrhh/vacations/import/upload", methods=["POST"])
def vacation_import_upload():
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
    file_id = f"temp_vac_{session['user']['uid']}_{uuid.uuid4().hex}_{safe_name}"
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
        "target_fields": VACATION_TARGET_FIELDS,
    })


@web_rrhh_bp.route("/rrhh/vacations/import/ai-suggest", methods=["POST"])
def vacation_import_ai_suggest():
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


@web_rrhh_bp.route("/rrhh/vacations/import/process", methods=["POST"])
def vacation_import_process():
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
            id_to_emp = {}
            cedula_to_emp = {}
            for e in employees_list:
                ced = (e.get("cedula") or e.get("idNumber") or "").strip()
                if ced:
                    cedula_to_emp[re.sub(r"\D", "", ced)] = e
                eid = e.get("id", "")
                if eid:
                    id_to_emp[eid] = e

            existing_requests = hr.get_vacation_requests(company_id, sandbox=sandbox)
            existing_keys = set()
            taken_by_emp = {}
            for r in existing_requests:
                eid = r.get("employeeId", "")
                existing_keys.add((eid, r.get("startDate", "")))
                if r.get("status") == "aprobada":
                    taken_by_emp[eid] = taken_by_emp.get(eid, 0) + int(r.get("days", 0) or 0)

            pending_entries = []
            holiday_cache = {}
            for row_idx, row_data in enumerate(rows):
                if not row_data:
                    continue
                processed += 1
                row_num = row_idx + 2

                try:
                    emp_identifier = _get_val(row_data, "employeeCedula")
                    emp = _resolve_employee(emp_identifier, id_to_emp, cedula_to_emp, employees_list)
                    if not emp:
                        errors.append({"row": row_num, "reason": f"No se encontro empleado con identificacion: '{emp_identifier}'"})
                        skipped += 1
                        continue

                    start_raw = _get_val(row_data, "startDate")
                    end_raw = _get_val(row_data, "endDate")
                    start_date = _normalize_date(start_raw)
                    end_date = _normalize_date(end_raw)
                    if not start_date:
                        errors.append({"row": row_num, "reason": f"Fecha de inicio invalida: '{start_raw}'. Use DD/MM/AAAA o AAAA-MM-DD."})
                        skipped += 1
                        continue
                    if not end_date:
                        errors.append({"row": row_num, "reason": f"Fecha fin invalida: '{end_raw}'. Use DD/MM/AAAA o AAAA-MM-DD."})
                        skipped += 1
                        continue
                    if start_date > end_date:
                        errors.append({"row": row_num, "reason": f"La fecha de inicio ({start_date}) es posterior a la fecha fin ({end_date})."})
                        skipped += 1
                        continue

                    days_raw = _get_val(row_data, "days")
                    if days_raw:
                        try:
                            days = int(float(str(days_raw).replace(",", ".")))
                        except ValueError:
                            days = None
                        if days is None or days <= 0:
                            errors.append({"row": row_num, "reason": f"Valor de días invalido: '{days_raw}'. Debe ser un entero positivo o dejar la celda vacía."})
                            skipped += 1
                            continue
                    else:
                        cache_key = (start_date, end_date)
                        if cache_key not in holiday_cache:
                            from app.services.holiday_service import HolidayService
                            holiday_cache[cache_key] = HolidayService.get_holiday_dates(
                                company_id, start_date, end_date, sandbox=sandbox
                            )
                        days = PayrollService.calculate_business_days(
                            start_date, end_date, holidays=holiday_cache[cache_key],
                            work_days=PayrollService.resolve_employee_work_days(company_id, emp, sandbox=sandbox),
                        )
                        if days <= 0:
                            errors.append({"row": row_num, "reason": f"No se pudieron calcular días hábiles entre {start_date} y {end_date}."})
                            skipped += 1
                            continue

                    pending_entries.append({
                        "row_num": row_num,
                        "emp": emp,
                        "start_date": start_date,
                        "end_date": end_date,
                        "days": days,
                        "notes": _get_val(row_data, "notes"),
                    })
                except Exception as e:
                    errors.append({"row": row_num, "reason": f"Error inesperado: {html.escape(str(e))}"})
                    skipped += 1

                if processed % update_every == 0 or processed == total:
                    _write_job({
                        "job_id": job_id, "status": "processing", "total": total,
                        "processed": processed, "imported": imported, "skipped": skipped,
                        "errors": errors[-30:],
                    })

            pending_entries.sort(key=lambda x: (x["emp"].get("id", ""), x["start_date"], x["end_date"], x["row_num"]))

            imported_keys = set()
            now_iso = date.today().isoformat()

            for entry in pending_entries:
                emp = entry["emp"]
                emp_id = emp.get("id", "")
                key = (emp_id, entry["start_date"])

                if key in existing_keys or key in imported_keys:
                    errors.append({"row": entry["row_num"], "reason": f"Ya existe una solicitud para {emp.get('fullName', '')} con inicio {entry['start_date']}. Fila omitida."})
                    skipped += 1
                    continue

                try:
                    taken_before = taken_by_emp.get(emp_id, 0)
                    remaining = PayrollService.calculate_vacation_days(
                        emp.get("hireDate", ""), taken_days=taken_before
                    )

                    req_id = str(uuid.uuid4())
                    hr.save_vacation_request(company_id, req_id, {
                        "id": req_id,
                        "employeeId": emp_id,
                        "employeeName": emp.get("fullName", ""),
                        "startDate": entry["start_date"],
                        "endDate": entry["end_date"],
                        "days": entry["days"],
                        "status": "aprobada",
                        "approvedBy": user_email,
                        "approvedDate": now_iso,
                        "remainingDaysBefore": remaining,
                        "notes": entry["notes"],
                        "createdDate": now_iso,
                        "source": "masivo",
                    }, sandbox=sandbox)

                    log_action(company_id, "create", "vacation_request", req_id, user_email,
                               changes={"source": "csv_import", "historical": True},
                               sandbox=sandbox)

                    imported_keys.add(key)
                    taken_by_emp[emp_id] = taken_before + entry["days"]
                    imported += 1
                except Exception as e:
                    errors.append({"row": entry["row_num"], "reason": f"Error al crear solicitud para {emp.get('fullName', '')}: {html.escape(str(e))}"})
                    skipped += 1

            final_state = {
                "job_id": job_id, "status": "completed", "total": total,
                "processed": processed, "imported": imported, "skipped": skipped,
                "errors": errors,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            _write_job(final_state)
        except Exception as e:
            print(f"[vacation_import] Error fatal en process_rows: {e}")
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


@web_rrhh_bp.route("/rrhh/vacations/import/status/<job_id>")
@limiter.exempt
def vacation_import_status(job_id):
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
