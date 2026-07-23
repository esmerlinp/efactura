"""DGTService — Lógica de negocio para formularios DGT (Ministerio de Trabajo RD).

Genera los datos estructurados para los formularios DGT-2, DGT-3, DGT-4, DGT-5, DGT-9 y DGT-12
en el formato requerido por el SIRLA (Sistema Integrado de Registros Laborales).
"""

import calendar
from datetime import date, datetime, timedelta
from typing import List, Optional

from app.services.hr_data_service import (
    get_employees, get_employee, get_payroll_periods, get_payroll_period,
    get_payroll_period_by_key, get_all_salary_history, get_vacation_requests,
)
from app.data.occupations_catalog import get_occupation_name


def _to_dgt_date(d: str) -> str:
    """Convierte YYYY-MM-DD a DD/MM/AAAA (formato SIRLA)."""
    if not d:
        return ""
    try:
        parts = d.split("-")
        if len(parts) == 3:
            return f"{int(parts[2]):02d}/{int(parts[1]):02d}/{parts[0]}"
    except (ValueError, IndexError):
        pass
    return d


def _map_sexo(gender: str) -> str:
    if gender == "masculino":
        return "M"
    if gender == "femenino":
        return "F"
    return ""


def _map_pago_frecuencia(freq: str) -> int:
    m = {"mensual": 1, "quincenal": 2, "semanal": 3, "diario": 4}
    return m.get(freq, 1)


def _map_contrato(contract: str) -> int:
    if contract == "tiempo_indefinido":
        return 1
    return 2


def _map_estado_civil(ms: str) -> str:
    if ms in ("S", "C", "U", "D", "V"):
        return ms
    return ""


def _build_dgt_line(emp: dict, novedad_tipo: int = 0, novedad_fecha: str = "") -> dict:
    """Construye un dict de 22 campos desde un Employee de Firestore."""
    cedula = (emp.get("cedula") or emp.get("idNumber") or "").replace("-", "").replace(" ", "")
    id_type = emp.get("idType", "cedula")
    tipo_doc = 2 if id_type == "pasaporte" else 1

    nombres = " ".join(
        p for p in [emp.get("firstName", ""), emp.get("middleName", "")] if p
    ) or emp.get("fullName", "")

    apellidos = " ".join(
        p for p in [emp.get("firstLastName", ""), emp.get("secondLastName", "")] if p
    )

    oc_code = emp.get("occupationCode", "")

    return {
        "tipoDocumento": tipo_doc,
        "documento": cedula,
        "nombres": nombres[:40],
        "apellidos": apellidos[:40],
        "nacionalidad": emp.get("nationality", 1),
        "sexo": _map_sexo(emp.get("gender", "")),
        "fechaNacimiento": _to_dgt_date(emp.get("birthDate", "")),
        "estadoCivil": _map_estado_civil(emp.get("maritalStatus", "")),
        "salario": float(emp.get("baseSalary", emp.get("salary", 0))),
        "tipoMoneda": 1,
        "frecuenciaPago": _map_pago_frecuencia(emp.get("paymentFrequency", "")),
        "ocupacionCodigo": oc_code,
        "ocupacionTexto": get_occupation_name(oc_code) or emp.get("position", ""),
        "fechaIngreso": _to_dgt_date(emp.get("hireDate", "")),
        "tipoContrato": _map_contrato(emp.get("contractType", "")),
        "horasSemanales": emp.get("weeklyHours", 44) or 44,
        "turnoTrabajo": emp.get("workShift", 1) or 1,
        "estadoTrabajador": 1 if emp.get("status") == "activo" else 1,
        "tipoNovedad": novedad_tipo,
        "fechaNovedad": _to_dgt_date(novedad_fecha) if novedad_fecha else "",
        "gradoInstruccion": emp.get("educationLevel", 0) or 0,
        "concesionVacaciones": emp.get("vacationGranted", 1) or 1,
    }


class DGTService:

    @staticmethod
    def get_dgt3_data(company_id: str, year: int, sandbox: bool = True) -> dict:
        """DGT-3: Personal fijo activo al corte del año."""
        employees = get_employees(company_id, sandbox=sandbox)
        fijos = [
            e for e in employees
            if e.get("status") == "activo"
            and e.get("contractType") == "tiempo_indefinido"
        ]

        lines = [_build_dgt_line(emp) for emp in fijos]
        total_salary = sum(l["salario"] for l in lines)

        return {
            "year": year,
            "totalEmployees": len(lines),
            "totalSalary": round(total_salary, 2),
            "lines": lines,
        }

    @staticmethod
    def get_dgt4_data(company_id: str, year: int, month: int, sandbox: bool = True) -> dict:
        """DGT-4: Cambios mensuales en personal fijo.

        Compara el snapshot de empleados entre el período de nómina actual y anterior.
        Si no hay snapshot, detecta altas/bajas usando el mes de contratación/terminación.
        """
        employees = get_employees(company_id, sandbox=sandbox)
        changes = []
        altas = bajas = modificaciones = 0

        # Detección por fecha de contratación/terminación vs mes solicitado
        for emp in employees:
            hire = emp.get("hireDate", "")
            term = emp.get("terminationDate", "")
            contract_type = emp.get("contractType", "")
            status = emp.get("status", "")

            if contract_type != "tiempo_indefinido":
                continue

            hire_month = hire[:7] if hire else ""
            term_month = term[:7] if term else ""
            period_key = f"{year:04d}-{month:02d}"

            # Alta: contratado este mes
            if hire_month == period_key:
                altas += 1
                changes.append({
                    "tipo": "alta",
                    "documento": emp.get("cedula", ""),
                    "nombre": emp.get("fullName", ""),
                    "detalle": f"Ingresó el {_to_dgt_date(hire)}",
                    "fechaCambio": hire,
                    "linea": _build_dgt_line(emp, novedad_tipo=1, novedad_fecha=hire),
                })

            # Baja: terminado este mes
            if term_month == period_key and status != "activo":
                bajas += 1
                changes.append({
                    "tipo": "baja",
                    "documento": emp.get("cedula", ""),
                    "nombre": emp.get("fullName", ""),
                    "detalle": f"Terminó el {_to_dgt_date(term)}",
                    "fechaCambio": term,
                    "linea": _build_dgt_line(emp, novedad_tipo=2, novedad_fecha=term),
                })

        # Modificaciones: revisar salary history del mes
        salary_history = get_all_salary_history(company_id, sandbox=sandbox)
        for sh in salary_history:
            eff = sh.get("effectiveDate", "")
            if eff[:7] == f"{year:04d}-{month:02d}":
                emp = next((e for e in employees if e.get("id") == sh.get("employeeId")), None)
                if emp and emp.get("contractType") == "tiempo_indefinido":
                    modificaciones += 1
                    old = sh.get("previousAmount", 0)
                    new = sh.get("amount", 0)
                    changes.append({
                        "tipo": "modificacion",
                        "documento": emp.get("cedula", ""),
                        "nombre": emp.get("fullName", ""),
                        "detalle": f"Salario: {old:.2f} → {new:.2f}",
                        "fechaCambio": eff,
                        "linea": _build_dgt_line(emp, novedad_tipo=3, novedad_fecha=eff),
                    })

        changes.sort(key=lambda c: c.get("fechaCambio", ""))

        return {
            "year": year,
            "month": month,
            "totalCambios": len(changes),
            "altas": altas,
            "bajas": bajas,
            "modificaciones": modificaciones,
            "lines": changes,
        }

    @staticmethod
    def get_dgt2_data(company_id: str, year: int, sandbox: bool = True) -> dict:
        """DGT-2: Cartel de Horas y Vacaciones."""
        employees = get_employees(company_id, sandbox=sandbox)
        vacations = get_vacation_requests(company_id, sandbox=sandbox)

        # Obtener HE totales del año desde nóminas
        payrolls = get_payroll_periods(company_id, sandbox=sandbox)
        total_overtime = 0.0
        for p in payrolls:
            if str(p.get("year", "")) == str(year) and p.get("status") in ("aprobada", "pagada", "cerrada"):
                for line in p.get("lines", []):
                    total_overtime += float(line.get("overtimeHours", 0))

        employees_on_vacation = []
        for v in vacations:
            if v.get("status") == "aprobada" and str(v.get("startDate", ""))[:4] == str(year):
                emp = next((e for e in employees if e.get("id") == v.get("employeeId")), None)
                employees_on_vacation.append({
                    "name": emp.get("fullName", v.get("employeeName", "")) if emp else v.get("employeeName", ""),
                    "desde": _to_dgt_date(v.get("startDate", "")),
                    "hasta": _to_dgt_date(v.get("endDate", "")),
                    "days": v.get("days", 0),
                })

        # Tomar configuración de jornada de cualquier empleado activo como referencia
        active_emp = next((e for e in employees if e.get("status") == "activo"), {})

        return {
            "year": year,
            "totalOvertimeHours": round(total_overtime, 2),
            "workersOnVacation": employees_on_vacation,
            "workdayStart": "08:00",
            "workdayEnd": "17:00",
            "lunchStart": "12:00",
            "lunchEnd": "13:00",
            "workDays": ["L", "M", "Mi", "J", "V"],
            "restDays": ["S", "D"],
            "saturdayHours": "08:00 - 12:00",
        }

    @staticmethod
    def get_dgt5_data(company_id: str, sandbox: bool = True) -> list:
        """DGT-5: Personal móvil u ocasional (contrato temporal)."""
        employees = get_employees(company_id, sandbox=sandbox)
        temporales = [
            e for e in employees
            if e.get("status") == "activo"
            and e.get("contractType") in ("tiempo_definido", "temporal", "obra_servicio")
        ]
        return [{
            "tipoDocumento": 2 if e.get("idType") == "pasaporte" else 1,
            "documento": (e.get("cedula") or e.get("idNumber", "")).replace("-", ""),
            "nombres": e.get("fullName", ""),
            "apellidos": " ".join(p for p in [e.get("firstLastName", ""), e.get("secondLastName", "")] if p),
            "ocupacion": e.get("position", ""),
            "fechaInicio": _to_dgt_date(e.get("hireDate", "")),
            "fechaFin": _to_dgt_date(e.get("terminationDate", "")) if e.get("terminationDate") else "",
            "salario": float(e.get("baseSalary", e.get("salary", 0))),
            "motivo": e.get("terminationReason", ""),
        } for e in temporales]

    @staticmethod
    def get_dgt9_data(company_id: str, sandbox: bool = True) -> list:
        """DGT-9: Suspensiones activas."""
        from app.services.hr_data_service import get_dgt_suspensions
        return get_dgt_suspensions(company_id, sandbox=sandbox)

    @staticmethod
    def save_dgt9(company_id: str, data: dict, sandbox: bool = True) -> str:
        """Guarda una suspensión DGT-9."""
        from app.services.hr_data_service import save_dgt_suspension
        import uuid
        susp_id = str(uuid.uuid4())
        data["id"] = susp_id
        data["estado"] = "activa"
        save_dgt_suspension(company_id, susp_id, data, sandbox=sandbox)
        return susp_id

    @staticmethod
    def save_dgt12(company_id: str, data: dict, sandbox: bool = True) -> str:
        """Guarda un cese de suspensión DGT-12 y actualiza el estado de la suspensión."""
        from app.services.hr_data_service import save_dgt_reinstatement, save_dgt_suspension
        import uuid
        reinst_id = str(uuid.uuid4())
        data["id"] = reinst_id
        save_dgt_reinstatement(company_id, reinst_id, data, sandbox=sandbox)

        # Marcar suspensión como cesada
        suspension_id = data.get("suspensionId")
        if suspension_id:
            susp = DGTService.get_dgt9_data(company_id, sandbox=sandbox)
            for s in susp:
                if s.get("id") == suspension_id:
                    s["estado"] = "cesada"
                    save_dgt_suspension(company_id, suspension_id, s, sandbox=sandbox)
                    break

        return reinst_id

    # ═══════════════════════════════════════════════════════════════════════════
    # TSS-3-01 y TSS-3-02 — Planillas de Pago a la Tesorería de Seguridad Social
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def get_tss_3_01_data(company_id: str, period_key: str, sandbox: bool = True) -> dict:
        """Genera los datos para la planilla TSS-3-01 (Resumen de Pago).
        
        Formato requerido por TSS para pago mensual de seguridad social.
        """
        periods = get_payroll_periods(company_id, sandbox=sandbox)
        period = next((p for p in periods if p.get("periodKey") == period_key), None)
        if not period:
            return {"error": "Período no encontrado"}

        lines = period.get("lines", [])
        employees = {e["id"]: e for e in get_employees(company_id, sandbox=sandbox)}

        total_afp_empleado = sum(float(l.get("afpEmployee", 0)) for l in lines)
        total_sfs_empleado = sum(float(l.get("sfsEmployee", 0)) for l in lines)
        total_afp_empleador = sum(float(l.get("afpEmployer", 0)) for l in lines)
        total_sfs_empleador = sum(float(l.get("sfsEmployer", 0)) for l in lines)
        total_srl = sum(float(l.get("srlEmployer", 0)) for l in lines)
        total_infotep = sum(float(l.get("infotepEmployer", 0)) for l in lines)
        total_isr = sum(float(l.get("isrRetention", 0)) for l in lines)
        total_empleados = sum(1 for l in lines if l.get("employeeId") in employees)
        total_salarios = sum(float(l.get("grossSalary", 0)) for l in lines)

        return {
            "periodKey": period_key,
            "totalEmployees": total_empleados,
            "totalSalaries": round(total_salarios, 2),
            "afpEmployee": round(total_afp_empleado, 2),
            "sfsEmployee": round(total_sfs_empleado, 2),
            "afpEmployer": round(total_afp_empleador, 2),
            "sfsEmployer": round(total_sfs_empleador, 2),
            "srlEmployer": round(total_srl, 2),
            "infotepEmployer": round(total_infotep, 2),
            "isrRetention": round(total_isr, 2),
            "totalEmployee": round(total_afp_empleado + total_sfs_empleado + total_isr, 2),
            "totalEmployer": round(total_afp_empleador + total_sfs_empleador + total_srl + total_infotep, 2),
            "grandTotal": round(total_afp_empleado + total_sfs_empleado + total_isr + 
                               total_afp_empleador + total_sfs_empleador + total_srl + total_infotep, 2),
        }

    @staticmethod
    def get_tss_3_02_data(company_id: str, period_key: str, sandbox: bool = True) -> list:
        """Genera los datos para la planilla TSS-3-02 (Relación de Empleados).
        
        Lista cada empleado con sus aportes individuales.
        """
        periods = get_payroll_periods(company_id, sandbox=sandbox)
        period = next((p for p in periods if p.get("periodKey") == period_key), None)
        if not period:
            return []

        lines = period.get("lines", [])
        employees = {e["id"]: e for e in get_employees(company_id, sandbox=sandbox)}
        rows = []

        for l in lines:
            emp_id = l.get("employeeId", "")
            emp = employees.get(emp_id, {})
            rows.append({
                "cedula": (emp.get("cedula") or emp.get("idNumber", "")).replace("-", ""),
                "nombre": emp.get("fullName", ""),
                "tssKey": emp.get("tssKey", ""),
                "salary": float(l.get("baseSalary", 0)),
                "grossSalary": float(l.get("grossSalary", 0)),
                "afpEmployee": float(l.get("afpEmployee", 0)),
                "sfsEmployee": float(l.get("sfsEmployee", 0)),
                "isrRetention": float(l.get("isrRetention", 0)),
                "afpEmployer": float(l.get("afpEmployer", 0)),
                "sfsEmployer": float(l.get("sfsEmployer", 0)),
                "srlEmployer": float(l.get("srlEmployer", 0)),
                "infotepEmployer": float(l.get("infotepEmployer", 0)),
                "netSalary": float(l.get("netSalary", 0)),
            })

        return rows

    @staticmethod
    def export_tss_txt(company_id: str, period_key: str, sandbox: bool = True) -> str:
        """Exporta datos TSS en formato TXT de columna fija para envío a TSS."""
        summary = DGTService.get_tss_3_01_data(company_id, period_key, sandbox)
        if "error" in summary:
            return ""

        lines = []
        lines.append(f"TSS310|{period_key}|{summary['totalEmployees']}|{summary['totalSalaries']:.2f}|{summary['grandTotal']:.2f}")

        details = DGTService.get_tss_3_02_data(company_id, period_key, sandbox)
        for row in details:
            lines.append(
                f"TSS320|{row['cedula'][:15]:<15}|{row['nombre'][:60]:<60}|"
                f"{row['tssKey'][:12]:<12}|{row['grossSalary']:>10.2f}|"
                f"{row['afpEmployee']:>8.2f}|{row['sfsEmployee']:>8.2f}|"
                f"{row['isrRetention']:>8.2f}|{row['netSalary']:>10.2f}"
            )

        return "\n".join(lines)
