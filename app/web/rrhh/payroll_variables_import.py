"""RRHH module — Importación CSV de Variables de Nómina por empleado."""

from flask import render_template, request, redirect, url_for, session, flash, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
)
from app.services import hr_data_service as hr
from app.utils.hr_utils import is_active_equivalent
import csv, io


SESSION_KEY = "payroll_variables_draft"
SESSION_KEY_PENDING = "payroll_variables_pending"

# Catálogo compartido de tabs/conceptos (módulo neutro, sin imports circulares)
from app.services.payroll_variable_catalog import (  # noqa: E402
    VARIABLE_TABS, VARIABLE_TAB_BY_CONCEPT, VARIABLE_CONCEPT_CODES,
    RECURRING_MANAGED_TABS,
)

# (conceptField=conceptCode, label, sinónimos aceptados)
VARIABLE_CONCEPTS = [
    ("HORAS_EXTRA",        "Horas trabajadas",       ["horas_extra", "horas extra", "horaextra", "hora_extra", "he", "overtime", "extra"]),
    ("COMISION",           "Comisión",               ["comision", "comisión", "comisiones", "commission"]),
    ("BONIFICACION",       "Bonificación",           ["bonificacion", "bonificación", "bono", "bonos", "bonus"]),
    ("INGRESO_VARIABLE",   "Ingresos variables",     ["otros_ingresos", "otros ingresos", "otro_ingreso", "otro ingreso", "other_income", "ingresos"]),
    ("OTRAS_DEDUCCIONES",  "Descuentos variables",   ["otras_deducciones", "otras deducciones", "otra_deduccion", "otra deducción", "other_ded", "deducciones"]),
]

VARIABLES_CSV_FIELDS = [
    ("*cedula",   "Cédula del empleado", True, ["cedula", "cédula", "rnc", "identificacion", "identificación", "empleado", "id", "documento"]),
    ("*concepto", "Concepto",            True, ["concepto", "tipo", "concept"]),
    ("*monto",    "Monto",               True, ["monto", "valor", "importe", "amount", "total"]),
]


def _get_delimiter(first_line):
    for delimiter in [";", "\t", ","]:
        if delimiter in first_line:
            return delimiter
    return ","


def _match_field(header: str, field_def) -> bool:
    h = header.strip().lstrip("*").strip().lower()
    return h in field_def[3]


def _parse_amount(raw: str):
    """Acepta '5000', '5,000.00', '5000,00', 'RD$ 5,000'."""
    s = (raw or "").strip().replace("RD$", "").replace("$", "").strip()
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        val = float(s)
    except ValueError:
        return None
    return val


def _normalize_cedula(raw: str) -> str:
    return (raw or "").strip().replace("-", "").strip()


def parse_variables_csv(content: str, employees_by_cedula: dict,
                        known_concepts: dict = None) -> dict:
    """Parsea el CSV genérico de variables (columnas cédula, concepto, monto).

    known_concepts: {codigo: nombre} de conceptos activos del editor; permite
    importar conceptos dinámicos por código o nombre además de los sinónimos.

    Returns:
        {"rows": [{line, cedula, employeeId, employeeName, conceptField,
                   conceptLabel, amount}], "errors": [{line, error}]}
    """
    rows = []
    errors = []

    try:
        lines = content.replace("\ufeff", "").splitlines()
        if not lines:
            return {"rows": rows, "errors": [{"line": 0, "error": "El archivo está vacío."}]}
        delimiter = _get_delimiter(lines[0])
        reader = csv.reader(lines, delimiter=delimiter)
        all_rows = [r for r in reader if r and any(c.strip() for c in r)]
    except Exception:
        return {"rows": rows, "errors": [{"line": 0, "error": "No se pudo leer el archivo CSV."}]}

    if not all_rows:
        return {"rows": rows, "errors": [{"line": 0, "error": "El archivo está vacío."}]}

    header = all_rows[0]
    idx = {}
    for field_def in VARIABLES_CSV_FIELDS:
        found = None
        for i, h in enumerate(header):
            if _match_field(h, field_def):
                found = i
                break
        idx[field_def[0].lstrip("*")] = found

    if idx["cedula"] is None or idx["concepto"] is None or idx["monto"] is None:
        return {"rows": rows, "errors": [{
            "line": 1,
            "error": "El encabezado debe incluir las columnas: cédula, concepto y monto.",
        }]}

    for line_no, r in enumerate(all_rows[1:], start=2):
        def _col(name):
            i = idx[name]
            return r[i].strip() if i is not None and i < len(r) else ""

        cedula_raw = _col("cedula")
        concepto_raw = _col("concepto")
        monto_raw = _col("monto")

        if not cedula_raw and not concepto_raw and not monto_raw:
            continue

        cedula = _normalize_cedula(cedula_raw)
        emp = employees_by_cedula.get(cedula)
        if not emp:
            errors.append({"line": line_no, "error": f"Empleado no encontrado con cédula «{cedula_raw or 'vacía'}»."})
            continue

        concepto_norm = concepto_raw.lower().strip()
        concept_match = None
        for field, label, synonyms in VARIABLE_CONCEPTS:
            if concepto_norm in synonyms:
                concept_match = (field, label)
                break
        if not concept_match and known_concepts:
            upper = concepto_raw.strip().upper()
            for code, label in known_concepts.items():
                if upper == code.upper() or concepto_norm == (label or "").lower():
                    concept_match = (code, label or code)
                    break
        if not concept_match:
            validos = ", ".join(s[0] for s in VARIABLE_CONCEPTS)
            if known_concepts:
                validos += ", " + ", ".join(sorted(known_concepts.keys()))
            errors.append({"line": line_no, "error": f"Concepto inválido «{concepto_raw}». Válidos: {validos}."})
            continue

        amount = _parse_amount(monto_raw)
        if amount is None:
            errors.append({"line": line_no, "error": f"Monto inválido «{monto_raw}»."})
            continue
        if amount < 0:
            errors.append({"line": line_no, "error": f"El monto no puede ser negativo ({amount})."})
            continue

        rows.append({
            "line": line_no,
            "cedula": cedula,
            "employeeId": emp.get("id", ""),
            "employeeName": emp.get("fullName", "") or emp.get("name", ""),
            "conceptField": concept_match[0],
            "conceptLabel": concept_match[1],
            "amount": round(amount, 2),
        })

    return {"rows": rows, "errors": errors}


def parse_tab_csv(content: str, employees_by_cedula: dict, tab_def: dict) -> dict:
    """Parsea un CSV de plantilla por tab (columnas cédula y monto; concepto implícito)."""
    rows = []
    errors = []

    try:
        lines = content.replace("\ufeff", "").splitlines()
        if not lines:
            return {"rows": rows, "errors": [{"line": 0, "error": "El archivo está vacío."}]}
        delimiter = _get_delimiter(lines[0])
        reader = csv.reader(lines, delimiter=delimiter)
        all_rows = [r for r in reader if r and any(c.strip() for c in r)]
    except Exception:
        return {"rows": rows, "errors": [{"line": 0, "error": "No se pudo leer el archivo CSV."}]}

    if not all_rows:
        return {"rows": rows, "errors": [{"line": 0, "error": "El archivo está vacío."}]}

    header = all_rows[0]

    def _find_idx(synonyms):
        for i, h in enumerate(header):
            if h.strip().lstrip("*").strip().lower() in synonyms:
                return i
        return None

    idx_cedula = _find_idx(["cedula", "cédula", "rnc", "identificacion", "identificación", "empleado", "id", "documento"])
    idx_monto = _find_idx(["monto", "valor", "importe", "amount", "total"])

    if idx_cedula is None or idx_monto is None:
        return {"rows": rows, "errors": [{
            "line": 1,
            "error": "El encabezado debe incluir las columnas: cédula y monto.",
        }]}

    for line_no, r in enumerate(all_rows[1:], start=2):
        def _col(i):
            return r[i].strip() if i is not None and i < len(r) else ""

        cedula_raw = _col(idx_cedula)
        monto_raw = _col(idx_monto)
        if not cedula_raw and not monto_raw:
            continue

        cedula = _normalize_cedula(cedula_raw)
        emp = employees_by_cedula.get(cedula)
        if not emp:
            errors.append({"line": line_no, "error": f"Empleado no encontrado con cédula «{cedula_raw or 'vacía'}»."})
            continue

        amount = _parse_amount(monto_raw)
        if amount is None:
            errors.append({"line": line_no, "error": f"Monto inválido «{monto_raw}»."})
            continue
        if amount < 0:
            errors.append({"line": line_no, "error": f"El monto no puede ser negativo ({amount})."})
            continue

        rows.append({
            "line": line_no,
            "cedula": cedula,
            "employeeId": emp.get("id", ""),
            "employeeName": emp.get("fullName", "") or emp.get("name", ""),
            "conceptField": tab_def["tab"],
            "conceptLabel": tab_def["label"],
            "amount": round(amount, 2),
        })

    return {"rows": rows, "errors": errors}


def _active_employees_by_cedula(company_id: str, sandbox: bool) -> dict:
    employees = hr.get_employees(company_id, sandbox=sandbox)
    result = {}
    for e in employees:
        if not is_active_equivalent(e.get("status", "")):
            continue
        cedula = _normalize_cedula(e.get("cedula") or e.get("idNumber", ""))
        if cedula:
            result[cedula] = e
    return result


def _resolve_tab_def(company_id: str, sandbox: bool, tab_key: str = "",
                     concept_code: str = "") -> dict | None:
    """Resuelve la definición de tab para importar: por concepto (dinámico) o por tab legacy."""
    if concept_code:
        try:
            from app.services.payroll_concept_engine import get_editor_tabs
            ing, dec = get_editor_tabs(company_id, sandbox=sandbox)
            for t in ing + dec:
                if t["concept"] == concept_code:
                    return t
        except Exception:
            pass
        for t in VARIABLE_TABS:
            if t["concept"] == concept_code:
                return t
        return None
    for t in VARIABLE_TABS:
        if t["tab"] == tab_key:
            return t
    return None


@web_rrhh_bp.route("/rrhh/payroll/variables-import")
def payroll_variables_import_page():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    tab_key = request.args.get("tab", "")
    concept_code = request.args.get("concept", "")
    tab_def = _resolve_tab_def(company_id, sandbox, tab_key=tab_key, concept_code=concept_code)
    return render_template("rrhh/payroll_variables_import.html", active_page="rrhh_payroll",
                           tab_def=tab_def, all_tabs=VARIABLE_TABS)


@web_rrhh_bp.route("/rrhh/payroll/variables-import/template")
def payroll_variables_import_template():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    tab_key = request.args.get("tab", "")
    concept_code = request.args.get("concept", "")
    tab_def = _resolve_tab_def(company_id, sandbox, tab_key=tab_key, concept_code=concept_code)
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    if tab_def:
        writer.writerow(["*cedula", "*monto"])
        writer.writerow(["40212345678", "5000.00"])
        filename = f"plantilla_{tab_def.get('tab', 'variables')}.csv"
    else:
        writer.writerow([f[0] for f in VARIABLES_CSV_FIELDS])
        writer.writerow(["40212345678", "comision", "5000.00"])
        filename = "plantilla_variables_nomina.csv"
    buf = io.BytesIO(csv_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    return send_file(buf, mimetype="text/csv", as_attachment=True,
                     download_name=filename)


@web_rrhh_bp.route("/rrhh/payroll/variables-import/upload", methods=["POST"])
def payroll_variables_import_upload():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    tab_key = request.form.get("tab", "")
    concept_code = request.form.get("concept", "")
    tab_def = _resolve_tab_def(company_id, sandbox, tab_key=tab_key, concept_code=concept_code)

    file = request.files.get("file")
    if not file:
        flash("Por favor sube un archivo CSV válido.", "error")
        return redirect(url_for("web_rrhh.payroll_variables_import_page", tab=tab_key, concept=concept_code))

    from app.utils.security import validate_uploaded_file
    valid, err_msg = validate_uploaded_file(file, allowed_extensions={"csv"})
    if not valid:
        flash(err_msg, "error")
        return redirect(url_for("web_rrhh.payroll_variables_import_page", tab=tab_key, concept=concept_code))

    try:
        content = file.read().decode("utf-8-sig", errors="ignore")
    except Exception:
        flash("No se pudo leer el archivo CSV.", "error")
        return redirect(url_for("web_rrhh.payroll_variables_import_page", tab=tab_key, concept=concept_code))

    emp_map = _active_employees_by_cedula(company_id, sandbox)
    if tab_def:
        result = parse_tab_csv(content, emp_map, tab_def)
    else:
        known_concepts = {}
        try:
            from app.services.payroll_concept_engine import get_editor_tabs
            _ing, _dec = get_editor_tabs(company_id, sandbox=sandbox)
            known_concepts = {t["concept"]: t["label"] for t in _ing + _dec}
        except Exception:
            known_concepts = {}
        result = parse_variables_csv(content, emp_map, known_concepts=known_concepts)

    if result["errors"]:
        # Vista previa: permitir importar las filas válidas si las hay
        rows = [
            {
                "employeeId": r["employeeId"],
                "employeeName": r["employeeName"],
                "cedula": r["cedula"],
                "conceptField": r["conceptField"],
                "conceptLabel": r["conceptLabel"],
                "amount": r["amount"],
            }
            for r in result["rows"]
        ]
        if rows:
            session[SESSION_KEY_PENDING] = rows
        return render_template(
            "rrhh/payroll_variables_import_result.html",
            active_page="rrhh_payroll",
            errors=result["errors"],
            rows_ok=len(result["rows"]),
            preview_rows=rows,
            tab_key=tab_key,
        )

    rows = [
        {
            "employeeId": r["employeeId"],
            "employeeName": r["employeeName"],
            "cedula": r["cedula"],
            "conceptField": r["conceptField"],
            "conceptLabel": r["conceptLabel"],
            "amount": r["amount"],
        }
        for r in result["rows"]
    ]
    session[SESSION_KEY] = rows
    flash(f"{len(rows)} variable(s) importadas en «{tab_def['label'] if tab_def else 'variables'}». Revísalas en el tab antes de procesar la nómina.", "success")
    return redirect(url_for("web_rrhh.payroll_new"))


@web_rrhh_bp.route("/rrhh/payroll/variables-import/apply", methods=["POST"])
def payroll_variables_import_apply():
    """Aplica las filas válidas aparcadas en la vista previa."""
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    pending = session.pop(SESSION_KEY_PENDING, [])
    if not pending:
        flash("No hay filas pendientes para importar.", "warning")
        return redirect(url_for("web_rrhh.payroll_new"))
    current = session.get(SESSION_KEY, []) or []
    session[SESSION_KEY] = current + pending
    flash(f"{len(pending)} variable(s) importada(s). Revísalas en el tab correspondiente antes de procesar.", "success")
    return redirect(url_for("web_rrhh.payroll_new"))
