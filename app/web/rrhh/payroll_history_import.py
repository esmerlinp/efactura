"""RRHH module — Importación masiva de histórico de nómina (vida laboral del empleado).

Carga un archivo CSV/Excel (formato ancho: 1 fila por empleado+período) y crea
``PayrollTransaction`` históricas (``source="import"``) para que la liquidación
(SDP), el ISR acumulado y los reportes reflejen la trayectoria del empleado.

La cédula es la clave de identificación del empleado. No se crean períodos ni
líneas de nómina reales: solo transacciones históricas + recálculo de YTD.
"""

import calendar
import csv
import io
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone

from flask import render_template, request, session, jsonify, send_file, redirect, url_for

from app.web.rrhh import web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required
from app.services import hr_data_service as hr
from app.services.ai_service import AIService
from app.extensions import limiter

TEMP_IMPORT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "uploads", "temp_imports")
JOB_DIR = os.path.join(TEMP_IMPORT_DIR, "jobs")

# ── Catálogo de columnas de la plantilla (formato ancho) ─────────────────────
# (field_id, label, required, synonyms)
HISTORY_CSV_FIELDS = [
    ("*cedula", "Cédula del empleado", True,
     ["cedula", "cédula", "rnc", "documento", "identificacion", "identificación", "idnumber", "id"]),
    ("*periodo", "Período (AAAA-MM, AAAA-MM-1/2)", True,
     ["periodo", "período", "period", "mes", "periodkey", "periodo_nomina", "periodo de nomina"]),
    ("salario_base", "Salario base", False,
     ["salario_base", "salario base", "sueldo", "salario", "sueldo_base", "salary", "sueldo fijo"]),
    ("horas_extra", "Horas extra", False,
     ["horas_extra", "horas extra", "horasextra", "overtime", "extras"]),
    ("comision", "Comisión", False,
     ["comision", "comisión", "comisiones", "commission"]),
    ("bonificacion", "Bonificación", False,
     ["bonificacion", "bonificación", "bono", "bonos", "bonus"]),
    ("otros_ingresos", "Otros ingresos", False,
     ["otros_ingresos", "otros ingresos", "otro_ingreso", "otrosingresos", "other_income"]),
    ("regalia_pascual", "Regalía pascual", False,
     ["regalia", "regalía", "regalia_pascual", "regalia pascual", "salario_navidad", "navidad"]),
    ("afp_empleado", "AFP empleado", False,
     ["afp_empleado", "afp empleado", "afp", "afp_emp", "afpemp"]),
    ("sfs_empleado", "SFS empleado", False,
     ["sfs_empleado", "sfs empleado", "sfs", "sfs_emp", "sfsemp", "seguro familiar de salud"]),
    ("isr", "ISR", False,
     ["isr", "isr_retencion", "isr retencion", "retencion_isr", "impuesto sobre la renta"]),
    ("otras_deducciones", "Otras deducciones", False,
     ["otras_deducciones", "otras deducciones", "otra_deduccion", "descuentos", "deducciones", "other_deductions"]),
    ("afp_empleador", "AFP empleador", False,
     ["afp_empleador", "afp empleador", "afp_empldor", "afp_patronal"]),
    ("sfs_empleador", "SFS empleador", False,
     ["sfs_empleador", "sfs empleador", "sfs_empldor", "sfs_patronal"]),
    ("srl_empleador", "SRL empleador", False,
     ["srl_empleador", "srl empleador", "srl", "srl_patronal"]),
    ("infotep_empleador", "INFOTEP empleador", False,
     ["infotep_empleador", "infotep empleador", "infotep", "infotep_patronal"]),
]

# ── Mapeo campo → concepto canónico (fallback si el concepto no existe aún) ──
HISTORY_CONCEPT_MAP = {
    "salario_base":      {"conceptCode": "SALARIO_BASE",      "type": "earning",         "affectsTSS": True,  "affectsISR": True},
    "horas_extra":       {"conceptCode": "HORAS_EXTRA",       "type": "earning",         "affectsTSS": True,  "affectsISR": True},
    "comision":          {"conceptCode": "COMISION",          "type": "earning",         "affectsTSS": True,  "affectsISR": True},
    "bonificacion":      {"conceptCode": "BONIFICACION",      "type": "earning",         "affectsTSS": True,  "affectsISR": True},
    "otros_ingresos":    {"conceptCode": "OTROS_INGRESOS",    "type": "earning",         "affectsTSS": True,  "affectsISR": True},
    "regalia_pascual":   {"conceptCode": "REGALIA_PASCUAL",   "type": "earning",         "affectsTSS": False, "affectsISR": False},
    "afp_empleado":      {"conceptCode": "AFP_EMPLEADO",      "type": "deduction",       "affectsTSS": True,  "affectsISR": True},
    "sfs_empleado":      {"conceptCode": "SFS_EMPLEADO",      "type": "deduction",       "affectsTSS": True,  "affectsISR": True},
    "isr":               {"conceptCode": "ISR_RETENCION",     "type": "deduction",       "affectsTSS": False, "affectsISR": True},
    "otras_deducciones": {"conceptCode": "OTRAS_DEDUCCIONES", "type": "deduction",       "affectsTSS": False, "affectsISR": False},
    "afp_empleador":     {"conceptCode": "AFP_EMPLEADOR",     "type": "employer_contrib", "affectsTSS": True,  "affectsISR": False},
    "sfs_empleador":     {"conceptCode": "SFS_EMPLEADOR",     "type": "employer_contrib", "affectsTSS": True,  "affectsISR": False},
    "srl_empleador":     {"conceptCode": "SRL_EMPLEADOR",     "type": "employer_contrib", "affectsTSS": True,  "affectsISR": False},
    "infotep_empleador": {"conceptCode": "INFOTEP_EMPLEADOR", "type": "employer_contrib", "affectsTSS": True,  "affectsISR": False},
}

HISTORY_REQUIRED_FIELDS = [f[0].lstrip("*") for f in HISTORY_CSV_FIELDS if f[2]]
HISTORY_TARGET_FIELDS = [
    {"id": f[0].lstrip("*"), "name": f"{f[1]}{' *' if f[2] else ''}", "required": f[2], "suggestions": f[3]}
    for f in HISTORY_CSV_FIELDS
]

HISTORY_CSV_HEADERS = [f[0] for f in HISTORY_CSV_FIELDS]
HISTORY_EXAMPLE_ROWS = [
    # Mensual
    ["40212345678", "2026-07", "35000", "0", "2500", "0", "0", "0",
     "1004.50", "1064.00", "0", "0", "2485.00", "2481.50", "0", "0"],
    # Quincenal Q1 (1–15)
    ["40212345678", "2026-07-1", "17500", "0", "0", "0", "0", "0",
     "502.25", "532.00", "0", "0", "1242.50", "1240.75", "0", "0"],
    # Quincenal Q2 (16–fin de mes)
    ["40212345678", "2026-07-2", "17500", "0", "0", "0", "0", "0",
     "502.25", "532.00", "0", "0", "1242.50", "1240.75", "0", "0"],
]


def _get_delimiter(first_line):
    for delimiter in [";", "\t", ","]:
        if delimiter in first_line:
            return delimiter
    return ","


def _sanitize_float_import(val, default=0.0):
    if val is None:
        return default
    if not str(val).strip():
        return default
    try:
        val_clean = str(val).strip().replace("RD$", "").replace("$", "").replace(" ", "")
        if "," in val_clean and "." in val_clean:
            val_clean = val_clean.replace(",", "")
        elif "," in val_clean:
            val_clean = val_clean.replace(",", ".")
        return float(val_clean)
    except Exception:
        return default


def _normalize_cedula(raw):
    return re.sub(r"\D", "", str(raw or ""))


def _normalize_period(raw):
    """Devuelve (periodKey, periodYear) o None si el período es inválido.

    Formatos aceptados en la columna ``periodo``:
      - ``YYYY-MM``      → mensual (``YYYY-MM-M``)
      - ``YYYY-MM-M``    → mensual explícito
      - ``YYYY-MM-1``    → quincena 1 (1–15)
      - ``YYYY-MM-2``    → quincena 2 (16–fin de mes)
      - ``YYYY-MM-DD``   → período con fecha específica
      - ``YYYY/MM``      → mensual (barras)
    """
    s = str(raw or "").strip()
    if not s:
        return None
    s = s.replace("/", "-")
    m = re.match(r"^(\d{4})-(\d{2})-([mM12])$", s)
    if m:
        year, month, suffix = m.groups()
        if not 1 <= int(month) <= 12:
            return None
        if suffix in ("1", "2"):
            return f"{year}-{month}-{suffix}", int(year)
        return f"{year}-{month}-M", int(year)
    m = re.match(r"^(\d{4})-(\d{2})$", s)
    if m:
        year, month = m.groups()
        if not 1 <= int(month) <= 12:
            return None
        return f"{year}-{month}-M", int(year)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        year, month, day = m.groups()
        if not 1 <= int(month) <= 12 or not 1 <= int(day) <= 31:
            return None
        return f"{year}-{month}-{day}", int(year)
    return None


def _load_concepts_by_code(company_id, sandbox):
    """Carga los conceptos reales por código (fallback a vacío)."""
    try:
        from app.services.payroll_concept_engine import get_concepts
        return {c.get("code"): c for c in get_concepts(company_id, sandbox=sandbox) if c.get("code")}
    except Exception:
        return {}


def _build_snapshot(field_id, concepts_by_code):
    """Construye el conceptSnapshot de un campo usando el concepto real si existe."""
    meta = HISTORY_CONCEPT_MAP[field_id]
    code = meta["conceptCode"]
    concept = concepts_by_code.get(code)
    if concept:
        from app.services.payroll_concept_engine import build_concept_snapshot
        return build_concept_snapshot(concept)
    return {
        "code": code,
        "name": meta["conceptCode"],
        "type": meta["type"],
        "category": "fixed",
        "affectsISR": meta["affectsISR"],
        "affectsTSS": meta["affectsTSS"],
        "affectsNet": meta["type"] == "deduction",
        "isLegalMandatory": False,
        "accountDebit": "",
        "accountCredit": "",
        "conceptVersion": 1,
        "maxPercentage": 0.0,
    }


def _read_rows(path, ext):
    """Lee el archivo y devuelve (headers, data_rows)."""
    if ext == "xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.active
            rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                rows.append([("" if c is None else str(c)) for c in row])
                if i > 50000:
                    break
            return rows
        finally:
            wb.close()
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        first_line = f.readline()
        delimiter = _get_delimiter(first_line)
        f.seek(0)
        reader = csv.reader(f, delimiter=delimiter)
        return list(reader)


def _employees_by_cedula(company_id, sandbox):
    employees = hr.get_employees(company_id, sandbox=sandbox)
    result = {}
    for e in employees:
        cedula = _normalize_cedula(e.get("cedula") or e.get("idNumber", ""))
        if cedula:
            result[cedula] = e
    return result


def _delete_imported_transactions(company_id, employee_id, period_key, sandbox):
    """Elimina transacciones importadas previas de un empleado+período (idempotencia)."""
    try:
        from app.services.db_service import db_firestore, firebase_initialized
        if not firebase_initialized or db_firestore is None:
            return
        coll_path = hr._hr_company_path(company_id, "payroll_transactions", sandbox)
        if not coll_path:
            return
        docs = db_firestore.collection(coll_path)\
            .where("employeeId", "==", employee_id).get()
        batch = db_firestore.batch()
        count = 0
        for d in docs:
            t = d.to_dict()
            if t.get("source") == "import" and t.get("periodKey") == period_key:
                batch.delete(d.reference)
                count += 1
        if count:
            batch.commit()
    except Exception as e:
        print(f"⚠️ [hist-import] Error eliminando transacciones previas: {e}")


def _build_line_from_transactions(txs):
    """Construye una 'línea' sintética (formato accumulate_ytd) desde transacciones."""
    total_income = 0.0
    afp_employee = sfs_employee = infotep_employee = 0.0
    isr_retention = other_deductions = 0.0
    afp_employer = sfs_employer = srl_employer = infotep_employer = 0.0
    summary = []
    for tx in txs:
        code = tx.get("conceptCode", "")
        amount = float(tx.get("amount", 0.0) or 0.0)
        ttype = tx.get("type", "")
        summary.append({"conceptCode": code, "amount": round(amount, 2), "type": ttype})
        if ttype == "earning":
            total_income += amount
        elif ttype == "deduction":
            if code == "AFP_EMPLEADO":
                afp_employee += amount
            elif code == "SFS_EMPLEADO":
                sfs_employee += amount
            elif code == "INFOTEP_EMPLEADO":
                infotep_employee += amount
            elif code in ("ISR_RETENCION", "ISR"):
                isr_retention += amount
            else:
                other_deductions += amount
        elif ttype == "employer_contrib":
            if code == "AFP_EMPLEADOR":
                afp_employer += amount
            elif code == "SFS_EMPLEADOR":
                sfs_employer += amount
            elif code == "SRL_EMPLEADOR":
                srl_employer += amount
            elif code == "INFOTEP_EMPLEADOR":
                infotep_employer += amount
    total_deductions = afp_employee + sfs_employee + infotep_employee + isr_retention + other_deductions
    total_employer = afp_employer + sfs_employer + srl_employer + infotep_employer
    return {
        "totalIncome": round(total_income, 2),
        "afpEmployee": round(afp_employee, 2),
        "sfsEmployee": round(sfs_employee, 2),
        "infotepEmployee": round(infotep_employee, 2),
        "isrRetention": round(isr_retention, 2),
        "otherDeductions": round(other_deductions, 2),
        "netSalary": round(max(0.0, total_income - total_deductions), 2),
        "afpEmployer": round(afp_employer, 2),
        "sfsEmployer": round(sfs_employer, 2),
        "srlEmployer": round(srl_employer, 2),
        "infotepEmployer": round(infotep_employer, 2),
        "totalEmployerContrib": round(total_employer, 2),
        "transactionSummary": summary,
    }


def build_import_transactions(employee, contract_id, period_key, period_year,
                              values, concepts_by_code, now_iso):
    """Construye las PayrollTransaction (dicts) para un empleado+período.

    ``values`` es un dict {field_id: raw_value} con los valores ya mapeados.
    Devuelve la lista de transacciones (vacia si no hay montos > 0).
    """
    txs = []
    for field_id, meta in HISTORY_CONCEPT_MAP.items():
        raw = str(values.get(field_id) or "").strip()
        if raw == "":
            continue
        amount = _sanitize_float_import(raw, 0.0)
        if amount == 0:
            continue
        snapshot = _build_snapshot(field_id, concepts_by_code)
        code = snapshot.get("code") or meta["conceptCode"]
        tx_id = f"imp_{period_key}_{employee['id']}_{code}"
        txs.append({
            "id": tx_id,
            "periodId": f"imp_{period_key}_{employee['id']}",
            "periodKey": period_key,
            "payrollLineId": "",
            "employeeId": employee["id"],
            "contractId": contract_id,
            "legalEntityId": "",
            "groupId": "",
            "conceptCode": code,
            "type": snapshot.get("type") or meta["type"],
            "amount": round(amount, 2),
            "source": "import",
            "sourceId": tx_id,
            "isRecurring": False,
            "recurringMovementId": "",
            "periodRevision": 1,
            "status": "applied",
            "conceptSnapshot": snapshot,
            "priority": 100,
            "periodYear": period_year,
            "notes": "Importación histórica de nómina",
            "createdAt": now_iso,
            "updatedAt": now_iso,
        })
    return txs


def _rebuild_ytd_for_employee(company_id, employee_id, year, contract_id, sandbox):
    """Reconstruye los acumulados YTD de un empleado/año desde sus transacciones."""
    try:
        from app.services.payroll_ytd_service import accumulate_ytd, _empty_ytd, save_ytd
        txs = hr.get_payroll_transactions(company_id, employee_id=employee_id, sandbox=sandbox)
        relevant = [t for t in txs
                    if t.get("status") in ("applied", "adjusted")
                    and int(t.get("periodYear") or 0) == year]
        if contract_id:
            relevant = [t for t in relevant
                        if (t.get("contractId") or "") == contract_id]
        by_period = {}
        for t in relevant:
            pk = t.get("periodKey") or t.get("periodId") or ""
            by_period.setdefault(pk, []).append(t)
        ytd = _empty_ytd(employee_id, year, contract_id)
        for pk, pts in by_period.items():
            line = _build_line_from_transactions(pts)
            period_id = pts[0].get("periodId") or f"imp_{pk}_{employee_id}"
            ytd = accumulate_ytd(ytd, line, period_key=pk, period_id=period_id)
        save_ytd(company_id, employee_id, year, ytd, contract_id=contract_id, sandbox=sandbox)
    except Exception as e:
        print(f"⚠️ [hist-import] Error recalculando YTD para {employee_id}/{year}: {e}")


_MONTHS_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def get_imported_period_summaries(company_id, sandbox=True):
    """Construye resúmenes de período (formato PayrollPeriod) desde las
    transacciones importadas (``source="import"``).

    Devuelve una lista de dicts virtuales (solo-lectura, sin ``id`` de Firestore)
    agrupados por ``periodKey``, con los mismos campos de totales que consume el
    dashboard de nómina. Se excluyen del scope de grupo (no tienen grupo).
    """
    from app.services.db_service import db_firestore, firebase_initialized
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = hr._hr_company_path(company_id, "payroll_transactions", sandbox)
        if not coll_path:
            return []
        docs = db_firestore.collection(coll_path).where("source", "==", "import").get()
        txs = [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ [hist-import] Error leyendo transacciones importadas: {e}")
        return []

    by_period = {}
    for t in txs:
        if t.get("status") not in ("applied", "adjusted"):
            continue
        pk = t.get("periodKey") or ""
        if not pk:
            continue
        by_period.setdefault(pk, []).append(t)

    summaries = []
    for pk, pts in by_period.items():
        year, month, suffix = _split_period_key(pk)
        if not year or not month:
            continue
        total_income = 0.0
        total_deductions = 0.0
        total_employer = 0.0
        total_isr = 0.0
        total_tss_employee = 0.0
        emp_ids = set()
        for t in pts:
            code = t.get("conceptCode", "")
            amount = float(t.get("amount", 0.0) or 0.0)
            ttype = t.get("type", "")
            eid = t.get("employeeId", "")
            if eid:
                emp_ids.add(eid)
            if ttype == "earning":
                total_income += amount
            elif ttype == "deduction":
                total_deductions += amount
                if code in ("ISR_RETENCION", "ISR"):
                    total_isr += amount
                if code in ("AFP_EMPLEADO", "SFS_EMPLEADO", "INFOTEP_EMPLEADO"):
                    total_tss_employee += amount
            elif ttype == "employer_contrib":
                total_employer += amount

        period_type = "quincenal" if suffix in ("1", "2") else "mensual"
        summaries.append({
            "id": f"imp_{pk}",
            "periodKey": pk,
            "periodType": period_type,
            "periodRange": _period_range_label(pk, year, month, suffix),
            "startDate": f"{year:04d}-{month:02d}-01",
            "endDate": f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}",
            "month": month,
            "year": year,
            "status": "importado",
            "source": "import",
            "totalGross": round(total_income, 2),
            "totalNet": round(max(0.0, total_income - total_deductions), 2),
            "totalEmployerContrib": round(total_employer, 2),
            "totalIsr": round(total_isr, 2),
            "totalTssEmployee": round(total_tss_employee, 2),
            "totalTssEmployer": round(total_employer, 2),
            "totalDeducciones": round(total_deductions, 2),
            "lineCount": len(emp_ids),
        })

    summaries.sort(key=lambda s: s["periodKey"])
    return summaries


def _split_period_key(pk):
    """Devuelve (year, month, suffix) desde un periodKey importado."""
    parts = str(pk or "").split("-")
    year = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
    month = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    suffix = parts[2] if len(parts) > 2 else ""
    return year, month, suffix


def _period_range_label(pk, year, month, suffix):
    label_m = _MONTHS_ES[month - 1] if 1 <= month <= 12 else str(month)
    if suffix == "1":
        return f"Q1: 1 {label_m} - 15 {label_m} {year}"
    if suffix == "2":
        last_day = calendar.monthrange(year, month)[1] if 1 <= month <= 12 else 30
        return f"Q2: 16 {label_m} - {last_day} {label_m} {year}"
    return f"{label_m} {year}"


# ═══════════════════════════════════════════════════════════════════════════
# RUTAS
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/history-import")
def payroll_history_import_page():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    return render_template("rrhh/payroll_history_import.html",
                           active_page="rrhh_payroll_history",
                           target_fields=HISTORY_TARGET_FIELDS,
                           required_fields=HISTORY_REQUIRED_FIELDS)


@web_rrhh_bp.route("/rrhh/payroll/history-import/template")
def payroll_history_import_template():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    fmt = request.args.get("format", "csv").lower()
    if fmt == "xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Histórico de nómina"
        ws.append(HISTORY_CSV_HEADERS)
        for row in HISTORY_EXAMPLE_ROWS:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True, download_name="plantilla_historico_nomina.xlsx")
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(HISTORY_CSV_HEADERS)
    for row in HISTORY_EXAMPLE_ROWS:
        writer.writerow(row)
    buf = io.BytesIO(csv_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    return send_file(buf, mimetype="text/csv", as_attachment=True,
                     download_name="plantilla_historico_nomina.csv")


@web_rrhh_bp.route("/rrhh/payroll/history-import/upload", methods=["POST"])
def payroll_history_import_upload():
    if _login_required():
        return jsonify({"success": False, "error": "No autorizado"}), 401

    file = request.files.get("file")
    if not file:
        return jsonify({"success": False, "error": "Por favor sube un archivo CSV o Excel válido."}), 400

    from app.utils.security import validate_uploaded_file, sanitize_filename

    valid, err_msg = validate_uploaded_file(file, allowed_extensions={"csv", "xlsx"})
    if not valid:
        return jsonify({"success": False, "error": err_msg}), 400

    os.makedirs(TEMP_IMPORT_DIR, exist_ok=True)
    safe_name = sanitize_filename(file.filename)
    ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else "csv"
    file_id = f"temp_hist_{session['user']['uid']}_{uuid.uuid4().hex}_{safe_name}"
    temp_path = os.path.join(TEMP_IMPORT_DIR, file_id)
    file.save(temp_path)

    try:
        rows = _read_rows(temp_path, ext)
        if not rows:
            raise ValueError("El archivo está vacío.")
        headers = [h.strip() for h in rows[0]]
        data_rows = rows[1:]
        row_count = len([r for r in data_rows if r and any(c.strip() for c in r)])
        preview_rows = []
        for row in data_rows[:5]:
            if row and any(c.strip() for c in row):
                preview_rows.append([c.strip() for c in row])
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({"success": False, "error": f"Error al analizar el archivo: {str(e)}"}), 400

    if row_count == 0:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({"success": False, "error": "El archivo no contiene filas de datos."}), 400

    return jsonify({
        "success": True,
        "headers": headers,
        "preview_rows": preview_rows,
        "temp_filename": file_id,
        "row_count": row_count,
        "target_fields": HISTORY_TARGET_FIELDS,
    })


@web_rrhh_bp.route("/rrhh/payroll/history-import/ai-suggest", methods=["POST"])
def payroll_history_import_ai_suggest():
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


@web_rrhh_bp.route("/rrhh/payroll/history-import/process", methods=["POST"])
def payroll_history_import_process():
    if _login_required():
        return jsonify({"success": False, "error": "No autorizado"}), 401

    _, sandbox, company_id = _get_owner_uid_and_sandbox()

    temp_filename = request.form.get("temp_filename")
    if not temp_filename:
        return jsonify({"success": False, "error": "Información de importación incompleta."}), 400

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

    ext = temp_filename.rsplit(".", 1)[-1].lower() if "." in temp_filename else "csv"
    try:
        rows = _read_rows(temp_path, ext)
        next_row = rows[0] if rows else []
        headers = [h.strip() for h in next_row]
        data_rows = rows[1:]
    except Exception as e:
        return jsonify({"success": False, "error": f"Error al leer el archivo: {str(e)}"}), 500

    total = len([r for r in data_rows if r and any(c.strip() for c in r)])
    if total == 0:
        return jsonify({"success": False, "error": "No hay filas de datos para procesar."}), 400

    os.makedirs(JOB_DIR, exist_ok=True)
    job_id = str(uuid.uuid4())
    job_file = os.path.join(JOB_DIR, f"{job_id}.json")

    def _write_job(state):
        with open(job_file, "w") as jf:
            json.dump(state, jf, default=str)

    _write_job({
        "job_id": job_id, "status": "processing", "total": total,
        "processed": 0, "imported": 0, "skipped": 0, "errors": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    employees_by_cedula = _employees_by_cedula(company_id, sandbox)
    concepts_by_code = _load_concepts_by_code(company_id, sandbox)
    # campo de período por defecto: columna 'periodo' si no se mapeó
    default_period_col = None
    for i, h in enumerate(headers):
        if _normalize_period(h) is not None and "periodo" in h.lower():
            default_period_col = i
            break

    def _get_col(row_data, field_id):
        if field_id in mapping and len(row_data) > mapping[field_id]:
            return row_data[mapping[field_id]].strip()
        return ""

    def process_rows():
        imported = 0
        skipped = 0
        errors = []
        processed = 0
        ytd_to_rebuild = set()
        try:
            update_every = max(1, total // 20)
            now_iso = datetime.now(timezone.utc).isoformat()

            for row_idx, row_data in enumerate(data_rows):
                if not row_data or not any(c.strip() for c in row_data):
                    continue
                processed += 1
                row_num = row_idx + 2

                try:
                    cedula = _normalize_cedula(_get_col(row_data, "cedula"))
                    if not cedula:
                        errors.append({"row": row_num, "reason": "Falta cédula del empleado."})
                        skipped += 1
                        continue
                    employee = employees_by_cedula.get(cedula)
                    if not employee:
                        errors.append({"row": row_num, "reason": f"Empleado no encontrado con cédula «{cedula}»."})
                        skipped += 1
                        continue

                    periodo_raw = _get_col(row_data, "periodo")
                    if periodo_raw == "" and default_period_col is not None and len(row_data) > default_period_col:
                        periodo_raw = row_data[default_period_col].strip()
                    norm = _normalize_period(periodo_raw)
                    if not norm:
                        errors.append({"row": row_num, "reason": f"Período inválido «{periodo_raw}». Use AAAA-MM."})
                        skipped += 1
                        continue
                    period_key, period_year = norm

                    contract_id = employee.get("currentEmploymentContractId", "") or ""
                    values = {fid: _get_col(row_data, fid) for fid in HISTORY_CONCEPT_MAP}
                    txs = build_import_transactions(
                        employee, contract_id, period_key, period_year,
                        values, concepts_by_code, now_iso)
                    if not txs:
                        errors.append({"row": row_num, "reason": "No hay montos para importar (todas las columnas están vacías o en 0)."})
                        skipped += 1
                        continue

                    _delete_imported_transactions(company_id, employee["id"], period_key, sandbox)
                    hr.save_payroll_transactions_batch(company_id, txs, sandbox=sandbox)
                    ytd_to_rebuild.add((employee["id"], period_year, contract_id))
                    imported += 1
                except Exception as e:
                    errors.append({"row": row_num, "reason": f"Error inesperado: {str(e)}"})
                    skipped += 1

                if processed % update_every == 0 or processed == total:
                    _write_job({
                        "job_id": job_id, "status": "processing", "total": total,
                        "processed": processed, "imported": imported, "skipped": skipped,
                        "errors": errors[-30:],
                    })

            # Recalcular YTD de empleados/años afectados
            for emp_id, year, cid in ytd_to_rebuild:
                _rebuild_ytd_for_employee(company_id, emp_id, year, cid, sandbox)

            _write_job({
                "job_id": job_id, "status": "completed", "total": total,
                "processed": processed, "imported": imported, "skipped": skipped,
                "errors": errors, "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            print(f"⚠️ [hist-import] Error fatal en process_rows: {e}")
            _write_job({
                "job_id": job_id, "status": "failed", "total": total,
                "processed": processed, "imported": imported, "skipped": skipped,
                "errors": errors[-30:] if errors else [{"row": 0, "reason": f"Error fatal: {e}"}],
                "timestamp": datetime.now(timezone.utc).isoformat(), "error": str(e),
            })

    thread = threading.Thread(target=process_rows)
    thread.daemon = True
    thread.start()

    return jsonify({"success": True, "job_id": job_id, "total": total})


@web_rrhh_bp.route("/rrhh/payroll/history-import/status/<job_id>")
@limiter.exempt
def payroll_history_import_status(job_id):
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
