"""RRHH module — Importación de asistencia (plantilla fija)."""

import csv
import html
import io
import re
import uuid
from datetime import datetime

from flask import render_template, request, redirect, url_for, session, send_file

from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
)
from app.services import hr_data_service as hr

# ── Plantilla fija de asistencia ────────────────────────────────────────────
# Columnas en orden. La cabecera descargable usa estos nombres; al importar se
# mapea por nombre (con sinónimos) y, si no coincide, por posición.
ATTENDANCE_CSV_HEADERS = ["empleadoCedula", "fecha", "estado", "entrada", "salida", "notas"]
ATTENDANCE_EXAMPLE_ROW = ["40212345678", "2026-03-02", "presente", "08:00", "17:00", ""]

_HEADER_SYNONYMS = {
    "empleadoCedula": ["empleadocedula", "cedula", "cédula", "rnc", "identificacion", "identificación", "empleado", "id", "documento"],
    "fecha": ["fecha", "date"],
    "estado": ["estado", "status"],
    "entrada": ["entrada", "checkin", "check-in", "hora entrada", "horaentrada"],
    "salida": ["salida", "checkout", "check-out", "hora salida", "horasalida"],
    "notas": ["notas", "nota", "notes", "comentario", "observacion", "observación", "motivo"],
}

_STATUS_MAP = {
    "presente": "presente",
    "p": "presente",
    "ausente": "ausente",
    "a": "ausente",
    "tarde": "tarde",
    "tardia": "tarde",
    "tardía": "tarde",
    "t": "tarde",
    "permiso": "permiso",
    "pe": "permiso",
}


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
            return datetime.strptime(date_clean, "%d/%m/%Y").strftime("%Y-%m-%d")
        elif re.match(r"^\d{2}-\d{2}-\d{4}$", date_clean):
            return datetime.strptime(date_clean, "%d-%m-%Y").strftime("%Y-%m-%d")
        elif re.match(r"^\d{2}/\d{2}/\d{2}$", date_clean):
            return datetime.strptime(date_clean, "%d/%m/%y").strftime("%Y-%m-%d")
    except ValueError:
        pass
    return None


def _normalize_status(raw_value):
    return _STATUS_MAP.get(str(raw_value or "").strip().lower())


def _resolve_employee(identifier, id_to_emp, cedula_to_emp, employees_list):
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


def _map_headers(headers):
    """Devuelve {campo: índice} mapeando por nombre (sinónimos) con fallback posicional."""
    mapping = {}
    normalized = [re.sub(r"[\s_\-*]", "", (h or "").lower()) for h in headers]
    for field in ATTENDANCE_CSV_HEADERS:
        target = field.lower()
        found = None
        for idx, h in enumerate(normalized):
            if h == target or h in _HEADER_SYNONYMS.get(field, []):
                found = idx
                break
        mapping[field] = found
    # Fallback posicional para campos no detectados
    for pos, field in enumerate(ATTENDANCE_CSV_HEADERS):
        if mapping.get(field) is None and pos < len(headers):
            mapping[field] = pos
    return mapping


@web_rrhh_bp.route("/rrhh/attendance/import")
def attendance_import():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    return render_template("rrhh/attendance_import.html", active_page="rrhh_attendance",
                           headers=ATTENDANCE_CSV_HEADERS, results=None)


@web_rrhh_bp.route("/rrhh/attendance/import/template")
def attendance_import_template():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(ATTENDANCE_CSV_HEADERS)
    writer.writerow(ATTENDANCE_EXAMPLE_ROW)
    buf = io.BytesIO(csv_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    return send_file(buf, mimetype="text/csv", as_attachment=True,
                     download_name="plantilla_asistencia.csv")


@web_rrhh_bp.route("/rrhh/attendance/import", methods=["POST"])
def attendance_import_process():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    file = request.files.get("file")
    if not file or not file.filename:
        return render_template("rrhh/attendance_import.html", active_page="rrhh_attendance",
                               headers=ATTENDANCE_CSV_HEADERS,
                               results={"error": "Por favor sube un archivo CSV válido."})

    from app.utils.security import validate_uploaded_file
    valid, err_msg = validate_uploaded_file(file, allowed_extensions={"csv"})
    if not valid:
        return render_template("rrhh/attendance_import.html", active_page="rrhh_attendance",
                               headers=ATTENDANCE_CSV_HEADERS, results={"error": err_msg})

    try:
        content = file.read().decode("utf-8-sig", errors="ignore")
    except Exception:
        return render_template("rrhh/attendance_import.html", active_page="rrhh_attendance",
                               headers=ATTENDANCE_CSV_HEADERS,
                               results={"error": "No se pudo leer el archivo."})

    try:
        first_line = content.splitlines()[0] if content.splitlines() else ""
        delimiter = _get_delimiter(first_line)
        reader = csv.reader(io.StringIO(content), delimiter=delimiter)
        headers = next(reader, None)
        rows = [r for r in reader if r and any((c or "").strip() for c in r)]
    except Exception as e:
        return render_template("rrhh/attendance_import.html", active_page="rrhh_attendance",
                               headers=ATTENDANCE_CSV_HEADERS,
                               results={"error": f"Error al analizar el archivo: {html.escape(str(e))}"})

    if not headers:
        return render_template("rrhh/attendance_import.html", active_page="rrhh_attendance",
                               headers=ATTENDANCE_CSV_HEADERS,
                               results={"error": "El archivo CSV está vacío."})

    if not rows:
        return render_template("rrhh/attendance_import.html", active_page="rrhh_attendance",
                               headers=ATTENDANCE_CSV_HEADERS,
                               results={"error": "El CSV no contiene filas de datos (solo cabecera)."})

    mapping = _map_headers(headers)

    def _get(row, field, default=""):
        idx = mapping.get(field)
        if idx is not None and idx < len(row):
            val = (row[idx] or "").strip()
            if val:
                return val
        return default

    employees_list = hr.get_employees(company_id, sandbox=sandbox)
    id_to_emp = {e.get("id", ""): e for e in employees_list if e.get("id")}
    cedula_to_emp = {}
    for e in employees_list:
        ced = (e.get("cedula") or e.get("idNumber") or "").strip()
        if ced:
            cedula_to_emp[re.sub(r"\D", "", ced)] = e

    existing_records = hr.get_attendance_records(company_id, sandbox=sandbox)
    existing_by_key = {}
    for r in existing_records:
        key = (r.get("employeeId", ""), r.get("date", ""))
        existing_by_key[key] = r

    imported = 0
    skipped = 0
    errors = []

    for row_idx, row_data in enumerate(rows):
        row_num = row_idx + 2  # +1 header, +1 index
        try:
            emp = _resolve_employee(_get(row_data, "empleadoCedula"), id_to_emp, cedula_to_emp, employees_list)
            if not emp:
                errors.append({"row": row_num, "reason": f"No se encontró empleado con identificación: '{_get(row_data, 'empleadoCedula')}'"})
                skipped += 1
                continue

            date_val = _normalize_date(_get(row_data, "fecha"))
            if not date_val:
                errors.append({"row": row_num, "reason": f"Fecha inválida: '{_get(row_data, 'fecha')}'. Use DD/MM/AAAA o AAAA-MM-DD."})
                skipped += 1
                continue

            status = _normalize_status(_get(row_data, "estado"))
            if not status:
                errors.append({"row": row_num, "reason": f"Estado inválido: '{_get(row_data, 'estado')}'. Use presente, ausente, tarde o permiso."})
                skipped += 1
                continue

            emp_id = emp.get("id", "")
            key = (emp_id, date_val)
            rec_id = (existing_by_key.get(key) or {}).get("id") or str(uuid.uuid4())

            hr.save_attendance_record(company_id, rec_id, {
                "id": rec_id,
                "employeeId": emp_id,
                "employeeName": emp.get("fullName", ""),
                "date": date_val,
                "checkIn": _get(row_data, "entrada"),
                "checkOut": _get(row_data, "salida"),
                "status": status,
                "notes": _get(row_data, "notas"),
            }, sandbox=sandbox)

            imported += 1
        except Exception as e:
            errors.append({"row": row_num, "reason": f"Error inesperado: {html.escape(str(e))}"})
            skipped += 1

    return render_template("rrhh/attendance_import.html", active_page="rrhh_attendance",
                           headers=ATTENDANCE_CSV_HEADERS,
                           results={"imported": imported, "skipped": skipped,
                                    "total": imported + skipped, "errors": errors,
                                    "filename": file.filename})
