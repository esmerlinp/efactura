"""RRHH module — auto-extracted."""

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
import csv, io


@web_rrhh_bp.route("/rrhh/employees/export")
def employee_export():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    employees = hr.get_employees(company_id, sandbox=sandbox)
    ids = request.args.get("ids", "")
    if ids:
        id_set = set(ids.split(","))
        employees = [e for e in employees if e.get("id") in id_set]

    for emp in employees:
        emp["vacationDays"] = PayrollService.calculate_vacation_days(emp.get("hireDate", ""))

    import io as _io
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Empleados"
        ws.append(["Nombre", "Cédula", "Cargo", "Área", "Departamento", "Salario Base",
                    "Tipo Contrato", "Fecha Ingreso", "Estado", "Email", "Teléfono",
                    "Municipio", "Género", "Fecha Nac.", "Supervisor", "Vacaciones"])
        for emp in employees:
            supervisor_name = ""
            sup_id = emp.get("reportsTo", "")
            if sup_id:
                sup = next((e for e in employees if e.get("id") == sup_id), None)
                if sup:
                    supervisor_name = sup.get("fullName", "")
            ws.append([
                emp.get("fullName", ""),
                emp.get("cedula", "") or emp.get("idNumber", ""),
                emp.get("position", ""),
                emp.get("area", "") or emp.get("department", ""),
                emp.get("department", ""),
                emp.get("baseSalary", 0),
                emp.get("contractType", ""),
                emp.get("hireDate", ""),
                emp.get("status", ""),
                emp.get("email", ""),
                emp.get("phone", ""),
                emp.get("municipality", ""),
                emp.get("gender", ""),
                emp.get("birthDate", ""),
                supervisor_name,
                emp.get("vacationDays", 0),
            ])
        output = _io.BytesIO()
        wb.save(output)
        output.seek(0)
        return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name="empleados.xlsx")
    except ImportError:
        csv_out = _io.StringIO()
        csv_out.write("Nombre,Cédula,Cargo,Área,Salario,Estado,Email,Teléfono,Fecha Ingreso\n")
        for emp in employees:
            csv_out.write(f"{emp.get('fullName','')},{emp.get('cedula','') or emp.get('idNumber','')},"
                         f"{emp.get('position','')},{emp.get('area','') or emp.get('department','')},"
                         f"{emp.get('baseSalary',0)},{emp.get('status','')},{emp.get('email','')},"
                         f"{emp.get('phone','')},{emp.get('hireDate','')}\n")
        buf = _io.BytesIO(csv_out.getvalue().encode("utf-8-sig"))
        return send_file(buf, mimetype="text/csv", as_attachment=True, download_name="empleados.csv")


