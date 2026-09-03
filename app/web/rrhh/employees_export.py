"""RRHH module — auto-extracted."""

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.data.nationality_catalog import get_nationality_name
from app.data.disability_catalog import get_disability_name, normalize_disability
import csv, io


# ── Exportación completa: todas las columnas del modelo Employee, en orden ──
# (columna, clave(s) del documento). Se resuelven referencias (sucursal, supervisor).
EXPORT_COLUMNS = [
    ("Código", "code"),
    ("Nombre Completo", "fullName"),
    ("Primer Nombre", "firstName"),
    ("Segundo Nombre", "middleName"),
    ("Primer Apellido", "firstLastName"),
    ("Segundo Apellido", "secondLastName"),
    ("Tipo Documento", "idType"),
    ("Cédula", "cedula"),
    ("ID Número", "idNumber"),
    ("Cargo", "position"),
    ("Departamento", "department"),
    ("Área", "area"),
    ("Centro de Costo", "costCenter"),
    ("Sucursal", "branchName"),
    ("Fecha Ingreso", "hireDate"),
    ("Salario Base", "baseSalary"),
    ("Tipo Salario", "salaryType"),
    ("Tarifa por Hora", "hourlyRate"),
    ("Estado", "status"),
    ("Tipo Empleado", "employeeType"),
    ("Tipo Contrato", "contractType"),
    ("Jornada", "workday"),
    ("Vigilante", "isVigilante"),
    ("Clave TSS", "tssKey"),
    ("Email", "email"),
    ("Teléfono", "phone"),
    ("Dirección", "address"),
    ("Municipio", "municipality"),
    ("Contacto Emergencia", "emergencyContact"),
    ("Teléfono Emergencia", "emergencyPhone"),
    ("Género", "gender"),
    ("Fecha Nacimiento", "birthDate"),
    ("Fin Período de Prueba", "probationEndDate"),
    ("Método de Pago", "paymentMethod"),
    ("Número de Cuenta", "accountNumber"),
    ("Banco", "bank"),
    ("Tipo de Cuenta", "accountType"),
    ("AFP", "afpProvider"),
    ("Tope AFP", "afpSalaryCap"),
    ("Tope SFS", "sfsSalaryCap"),
    ("No. Registro TSS", "tssRegistrationNumber"),
    ("Supervisor", "supervisorName"),
    ("Nacionalidad", "nationalityName"),
    ("ID Nacionalidad SIRLA", "nationality"),
    ("Estado Civil", "maritalStatus"),
    ("No. Hijos", "numberOfChildren"),
    ("Código Ocupación (CNO)", "occupationCode"),
    ("Horas Semanales", "weeklyHours"),
    ("Turno", "workShift"),
    ("Nivel Educación", "educationLevel"),
    ("Código Educación SIRLA", "sirlaEducationCode"),
    ("Concesión Vacaciones", "vacationGranted"),
    ("No. SDSS", "sdssNumber"),
    ("Inicio Vacaciones (DGT)", "vacationStartDate"),
    ("Fin Vacaciones (DGT)", "vacationEndDate"),
    ("Discapacidad", "disabilityName"),
    ("Días Trabajados", "daysWorked"),
    ("Sueldo Diario", "dailySalary"),
    ("Fecha Salida", "terminationDate"),
    ("Motivo Salida", "terminationReason"),
    ("Tipo Salida", "terminationType"),
    ("Grupos de Nómina", "payrollGroupIds"),
    ("Vacaciones Disponibles", "vacationDays"),
    ("Notas", "notes"),
]

# Metadatos internos que no son campos del empleado
_EXPORT_EXCLUDE = {
    "id", "ownerUid", "owner_uid", "companyId", "sandbox",
}


def _stringify(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    if isinstance(value, bool):
        return "Sí" if value else "No"
    return value


def disability_names(value) -> str:
    """Nombres legibles de las discapacidades SIRLA separados por coma."""
    codes = normalize_disability(value).split(",")
    return ", ".join(get_disability_name(c) for c in codes if get_disability_name(c))


def _build_export_rows(employees, branches):
    """Devuelve (headers, rows) con TODOS los campos del empleado.

    Columnas fijas del modelo Employee en orden + columnas dinámicas para
    cualquier campo extra presente en los datos (orden alfabético),
    excluyendo metadatos internos (GUID, owner, company, sandbox).
    """
    branch_names = {b.get("id"): b.get("name", "") for b in branches}
    emp_by_id = {e.get("id"): e for e in employees}

    known_keys = set()
    for _, key in EXPORT_COLUMNS:
        if key in ("branchName", "supervisorName"):
            continue
        known_keys.add(key)

    extra_keys = set()
    for emp in employees:
        for key in emp.keys():
            if key not in known_keys and key not in _EXPORT_EXCLUDE:
                extra_keys.add(key)

    headers = [label for label, _ in EXPORT_COLUMNS]
    headers += sorted(extra_keys)

    def resolve(emp, key):
        if key == "branchName":
            return branch_names.get(emp.get("branchId", ""), emp.get("branchId", "") or "")
        if key == "supervisorName":
            sup = emp_by_id.get(emp.get("reportsTo", ""))
            return sup.get("fullName", "") if sup else ""
        if key == "vacationDays":
            return emp.get("vacationDays", 0)
        if key == "nationalityName":
            return get_nationality_name(emp.get("nationality", 1))
        if key == "disabilityName":
            return disability_names(emp.get("disability"))
        return emp.get(key, "")

    rows = []
    for emp in employees:
        row = [_stringify(resolve(emp, key)) for _, key in EXPORT_COLUMNS]
        row += [_stringify(emp.get(key, "")) for key in sorted(extra_keys)]
        rows.append(row)
    return headers, rows


@web_rrhh_bp.route("/rrhh/employees/export")
def employee_export():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService
    from app.services.db_service import DatabaseService

    employees = hr.get_employees(company_id, sandbox=sandbox)
    ids = request.args.get("ids", "")
    if ids:
        id_set = set(ids.split(","))
        employees = [e for e in employees if e.get("id") in id_set]

    for emp in employees:
        emp["vacationDays"] = PayrollService.calculate_vacation_days(emp.get("hireDate", ""))

    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox, company_id=company_id)

    headers, rows = _build_export_rows(employees, branches)

    import io as _io
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Empleados"
        ws.append(headers)
        for row in rows:
            ws.append(row)
        output = _io.BytesIO()
        wb.save(output)
        output.seek(0)
        return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name="empleados.xlsx")
    except ImportError:
        csv_out = _io.StringIO()
        writer = csv.writer(csv_out)
        writer.writerow(headers)
        writer.writerows(rows)
        buf = _io.BytesIO(csv_out.getvalue().encode("utf-8-sig"))
        return send_file(buf, mimetype="text/csv", as_attachment=True, download_name="empleados.csv")
