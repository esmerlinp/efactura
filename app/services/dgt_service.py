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
    get_overtime_records,
)
from app.data.occupations_catalog import get_occupation_name
from app.data.education_catalog import is_valid_education_code, get_education_label
from app.utils.hr_utils import is_active_equivalent


def _to_sirla_date(d: str) -> str:
    """Convierte YYYY-MM-DD a DDMMYYYY (formato SIRLA fixed-width)."""
    if not d:
        return ""
    try:
        parts = d.split("-")
        if len(parts) == 3:
            return f"{int(parts[2]):02d}{int(parts[1]):02d}{parts[0]}"
    except (ValueError, IndexError):
        pass
    return d.replace("/", "").replace("-", "")


def _map_doc_type_sirla(id_type: str) -> str:
    m = {"cedula": "C", "pasaporte": "P", "nss": "N", "migracion": "M", "seguro_social": "N", "ip": "I"}
    return m.get(id_type.lower(), "C")


def _sirla_education_code(emp: dict) -> int:
    """Código educativo oficial SIRLA (4744-4782) desde el campo del empleado.

    Si no existe un código oficial asignado, devuelve 0 (pendiente). No se
    inventan equivalencias desde el nivel legacy 1-6.
    """
    code = str(emp.get("sirlaEducationCode", "") or "").strip()
    if is_valid_education_code(code):
        return int(code)
    return 0


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


def _map_novedad_sirla(novedad_tipo: int) -> str:
    m = {1: "NI", 2: "NS", 3: "NC", 0: "NI"}
    return m.get(novedad_tipo, "NI")


def _map_causa_suspension(causa: str) -> str:
    m = {
        "fuerza_mayor": "1".rjust(15, "0"),
        "falta_materia_prima": "2".rjust(15, "0"),
        "caso_fortuito": "3".rjust(15, "0"),
        "hecho_principie": "4".rjust(15, "0"),
        "otro": "5".rjust(15, "0"),
    }
    return m.get(causa, "0".rjust(15, "0"))


def _build_dgt_line(emp: dict, novedad_tipo: int = 0, novedad_fecha: str = "") -> dict:
    """Construye un dict con los campos para DGT-3/4 (SIRLA + PDF) desde un Employee de Firestore."""
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
    posicion = emp.get("position", "")
    nationality_val = emp.get("nationality", 1)
    nationality_sirla = "" if nationality_val == 1 else str(nationality_val)[:3]

    return {
        # Legacy (mantener compatibilidad)
        "tipoDocumento": tipo_doc,
        "documento": cedula,
        "nombres": nombres[:40],
        "apellidos": apellidos[:40],
        "nacionalidad": nationality_val,
        "sexo": _map_sexo(emp.get("gender", "")),
        "fechaNacimiento": _to_dgt_date(emp.get("birthDate", "")),
        "estadoCivil": _map_estado_civil(emp.get("maritalStatus", "")),
        "salario": float(emp.get("baseSalary", emp.get("salary", 0))),
        "tipoMoneda": 1,
        "frecuenciaPago": _map_pago_frecuencia(emp.get("paymentFrequency", "")),
        "ocupacionCodigo": oc_code,
        "ocupacionTexto": get_occupation_name(oc_code) or posicion,
        "fechaIngreso": _to_dgt_date(emp.get("hireDate", "")),
        "tipoContrato": _map_contrato(emp.get("contractType", "")),
        "horasSemanales": emp.get("weeklyHours", 44) or 44,
        "turnoTrabajo": emp.get("workShift", 1) or 1,
        "estadoTrabajador": 1 if emp.get("status") == "activo" else 1,
        "tipoNovedad": novedad_tipo,
        "fechaNovedad": _to_dgt_date(novedad_fecha) if novedad_fecha else "",
        "gradoInstruccion": _sirla_education_code(emp),
        "concesionVacaciones": emp.get("vacationGranted", 1) or 1,
        # SIRLA (nuevo formato fixed-width)
        "docTypeSirla": _map_doc_type_sirla(id_type),
        "primerNombre": " ".join(
            p for p in [emp.get("firstName", ""), emp.get("middleName", "")] if p
        )[:50],
        "primerApellido": (emp.get("firstLastName", "") or "")[:40],
        "segundoApellido": (emp.get("secondLastName", "") or "")[:40],
        "fechaNacimientoSirla": _to_sirla_date(emp.get("birthDate", "")),
        "salarioSirla": int(float(emp.get("baseSalary", emp.get("salary", 0)))),
        "fechaIngresoSirla": _to_sirla_date(emp.get("hireDate", "")),
        "fechaSalidaSirla": _to_sirla_date(emp.get("terminationDate", "")),
        "fechaCambioSirla": _to_sirla_date(novedad_fecha) if novedad_fecha else "",
        "cargo": (get_occupation_name(oc_code) or posicion)[:150],
        "inicioVacaciones": _to_sirla_date(emp.get("vacationStartDate", "")),
        "finVacaciones": _to_sirla_date(emp.get("vacationEndDate", "")),
        "turnoSirla": emp.get("workShift", 1) or 1,
        "discapacidad": (emp.get("disability", "") or "")[:50],
        "sdssNumber": emp.get("sdssNumber", "") or emp.get("tssRegistrationNumber", ""),
        "novedadSirla": _map_novedad_sirla(novedad_tipo),
        "nacionalidadSirla": nationality_sirla,
        # DGT-4 PDF
        "nationalityCode": emp.get("nationalityCode", "") or nationality_sirla,
        "numberOfChildren": emp.get("numberOfChildren", 0) or 0,
        "birthDay": emp.get("birthDate", "")[8:10] if len(emp.get("birthDate", "")) >= 10 else "",
        "birthMonth": emp.get("birthDate", "")[5:7] if len(emp.get("birthDate", "")) >= 10 else "",
        "birthYear": emp.get("birthDate", "")[:4] if len(emp.get("birthDate", "")) >= 10 else "",
    }


class DGTService:

    @staticmethod
    def get_dgt3_data(company_id: str, year: int, month: int = None, sandbox: bool = True) -> dict:
        """DGT-3: Personal fijo activo al corte del período con datos SIRLA + PDF.

        El archivo SIRLA DGT-3 se declara por mes (Periodo = MMYYYY).
        """
        from datetime import datetime as _dt
        from app.services.db_service import DatabaseService

        if month is None:
            month = _dt.now().month

        employees = get_employees(company_id, sandbox=sandbox)
        fijos = [
            e for e in employees
            if is_active_equivalent(e.get("status"))
            and e.get("contractType") == "tiempo_indefinido"
        ]

        lines = [_build_dgt_line(emp) for emp in fijos]
        total_salary = sum(l["salario"] for l in lines)

        # Resumen por nacionalidad y género
        dominicanos = sum(1 for l in lines if l["nacionalidad"] == 1)
        extranjeros = sum(1 for l in lines if l["nacionalidad"] != 1)
        hombres = sum(1 for l in lines if l["sexo"] == "M")
        mujeres = sum(1 for l in lines if l["sexo"] == "F")

        # Datos de empresa
        company_raw = DatabaseService.get_company(company_id) or {}
        company_info = {
            "companyName": company_raw.get("company_name") or company_raw.get("trade_name") or "",
            "tradeName": company_raw.get("trade_name", ""),
            "companyRNC": company_raw.get("rnc", ""),
            "companyAddress": company_raw.get("address", ""),
            "province": company_raw.get("province", ""),
            "municipality": company_raw.get("municipality", ""),
            "companyPhone": company_raw.get("phone", ""),
            "companyEmail": company_raw.get("email", ""),
            "economicActivity": company_raw.get("economic_activity", ""),
            "rnlNumber": company_raw.get("rnl_number", ""),
            "insurancePolicy": company_raw.get("insurance_policy", ""),
            "employerName": company_raw.get("employer_name", ""),
            "employerCedula": company_raw.get("employer_cedula", ""),
            "representativeName": company_raw.get("representative_name", ""),
            "representativeCedula": company_raw.get("representative_cedula", ""),
            "sector": company_raw.get("sector", ""),
            "plaza": company_raw.get("plaza", ""),
            "fax": company_raw.get("fax", ""),
            "zonaFranca": company_raw.get("zona_franca", False),
            "parque": company_raw.get("parque", ""),
            "propertyValue": float(company_raw.get("property_value", 0) or 0),
        }

        return {
            "year": year,
            "month": month,
            "company": company_info,
            "totalEmployees": len(lines),
            "totalSalary": round(total_salary, 2),
            "dominicanos": dominicanos,
            "extranjeros": extranjeros,
            "hombres": hombres,
            "mujeres": mujeres,
            "lines": lines,
        }

    @staticmethod
    def get_dgt4_data(company_id: str, year: int, month: int, sandbox: bool = True) -> dict:
        """DGT-4: Cambios mensuales en personal fijo (SIRLA + PDF).

        Compara el snapshot de empleados entre el período de nómina actual y anterior.
        Si no hay snapshot, detecta altas/bajas usando el mes de contratación/terminación.
        """
        from app.services.db_service import DatabaseService

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
                    # DGT-4 PDF: flags para tabla
                    "esEntrada": True,
                    "esSalida": False,
                    "esSueldo": False,
                    "montoEntrada": float(emp.get("baseSalary", emp.get("salary", 0))),
                    "montoSalida": 0.0,
                    "montoSueldo": 0.0,
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
                    "esEntrada": False,
                    "esSalida": True,
                    "esSueldo": False,
                    "montoEntrada": 0.0,
                    "montoSalida": float(emp.get("baseSalary", emp.get("salary", 0))),
                    "montoSueldo": 0.0,
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
                        "esEntrada": False,
                        "esSalida": False,
                        "esSueldo": True,
                        "montoEntrada": 0.0,
                        "montoSalida": 0.0,
                        "montoSueldo": new,
                    })

        changes.sort(key=lambda c: c.get("fechaCambio", ""))

        # Datos de empresa
        company_raw = DatabaseService.get_company(company_id) or {}

        return {
            "year": year,
            "month": month,
            "company": {
                "companyName": company_raw.get("company_name") or company_raw.get("trade_name", ""),
                "companyRNC": company_raw.get("rnc", ""),
            },
            "totalCambios": len(changes),
            "altas": altas,
            "bajas": bajas,
            "modificaciones": modificaciones,
            "lines": changes,
        }

    @staticmethod
    def get_dgt2_data(company_id: str, year: int, month: int = None, sandbox: bool = True) -> dict:
        """DGT-2: Cartel de Horas y Vacaciones con datos SIRLA (mensual).

        El archivo SIRLA DGT-2 se declara por mes (Periodo = MMYYYY) y el bloque
        de "Día {n}" (1..31) exige el detalle diario de horas extras y su
        porcentaje, por lo que el reporte debe ser mensual.
        """
        from datetime import datetime as _dt
        from app.services.db_service import DatabaseService

        if month is None:
            month = _dt.now().month

        employees = get_employees(company_id, sandbox=sandbox)
        vacations = get_vacation_requests(company_id, sandbox=sandbox)

        # Horas extras del mes por empleado y día, desde overtime_records
        overtime_records = get_overtime_records(company_id, sandbox=sandbox)
        period_prefix = f"{year:04d}-{month:02d}"
        overtime_by_emp = {}  # employeeId -> {day(int): {"hours": h, "percentage": p}}
        total_overtime = 0.0
        for rec in overtime_records:
            if rec.get("status") not in ("approved", "locked", "processed"):
                continue
            rec_date = (rec.get("date") or "")[:10]
            if not rec_date or not rec_date.startswith(period_prefix):
                continue
            emp_id = rec.get("employeeId", "")
            try:
                day = int(rec_date[-2:])
            except ValueError:
                continue
            minutes = int(rec.get("totalMinutes", 0) or 0)
            hours = round(minutes / 60.0, 2)
            factor = float(rec.get("factorAtApproval", 0) or 0)
            # Porcentaje de recargo (Ley 16-92): 1.35 -> 35%, 2.00 -> 100%.
            percentage = round((factor - 1.0) * 100.0, 2) if factor > 1.0 else 0.0
            if hours <= 0:
                continue
            total_overtime += hours
            bucket = overtime_by_emp.setdefault(emp_id, {})
            if day in bucket:
                prev = bucket[day]
                combined_hours = prev["hours"] + hours
                combined_pct = round(
                    (prev["hours"] * prev["percentage"] + hours * percentage) / combined_hours,
                    2,
                ) if combined_hours else 0.0
                bucket[day] = {"hours": combined_hours, "percentage": combined_pct}
            else:
                bucket[day] = {"hours": hours, "percentage": percentage}

        employees_on_vacation = []
        for v in vacations:
            if v.get("status") == "aprobada" and str(v.get("startDate", ""))[:7] == period_prefix:
                emp = next((e for e in employees if e.get("id") == v.get("employeeId")), None)
                employees_on_vacation.append({
                    "name": emp.get("fullName", v.get("employeeName", "")) if emp else v.get("employeeName", ""),
                    "desde": _to_dgt_date(v.get("startDate", "")),
                    "hasta": _to_dgt_date(v.get("endDate", "")),
                    "days": v.get("days", 0),
                })

        # Datos de empresa para SIRLA
        company_raw = DatabaseService.get_company(company_id) or {}
        rnl = (company_raw.get("rnl_number", "") or "").replace("-", "").replace(" ", "")
        establishment_id = rnl[-4:].rjust(6, "0") if rnl else "000000"

        # Empleados vigentes para SIRLA (activo / vacaciones / licencia)
        activos = [e for e in employees if is_active_equivalent(e.get("status"))]
        sirla_lines = []
        for emp in activos:
            cedula = (emp.get("cedula") or emp.get("idNumber") or "").replace("-", "").replace(" ", "")
            id_type = emp.get("idType", "cedula")
            salary = float(emp.get("baseSalary", emp.get("salary", 0)))
            weekly_hours = emp.get("weeklyHours", 44) or 44
            hourly_rate = round(salary / (weekly_hours * 4.33), 2) if weekly_hours > 0 else 0.0

            emp_days = overtime_by_emp.get(emp.get("id"), {})
            horas35 = sum(v["hours"] for v in emp_days.values() if round(v["percentage"]) == 35)
            horas100 = sum(v["hours"] for v in emp_days.values() if round(v["percentage"]) == 100)
            horas_otro = sum(
                v["hours"] for v in emp_days.values()
                if round(v["percentage"]) not in (0, 35, 100)
            )
            total_horas = round(sum(v["hours"] for v in emp_days.values()), 2)

            sirla_lines.append({
                "docTypeSirla": _map_doc_type_sirla(id_type),
                "documento": cedula,
                "nombres": " ".join(p for p in [emp.get("firstName", ""), emp.get("middleName", "")] if p)[:50],
                "primerApellido": (emp.get("firstLastName", "") or "")[:40],
                "segundoApellido": (emp.get("secondLastName", "") or "")[:40],
                "sdssNumber": emp.get("sdssNumber", "") or emp.get("tssRegistrationNumber", ""),
                "hourlyRate": hourly_rate,
                "overtimeDays": emp_days,
                "overtimeCause": "",
                "horas35": horas35,
                "horas100": horas100,
                "horasOtro": horas_otro,
                "totalHoras": total_horas,
            })

        return {
            "year": year,
            "month": month,
            "company": {
                "companyName": company_raw.get("company_name") or company_raw.get("trade_name", ""),
                "tradeName": company_raw.get("trade_name", ""),
                "companyRNC": company_raw.get("rnc", ""),
                "companyAddress": company_raw.get("address", ""),
                "province": company_raw.get("province", ""),
                "municipality": company_raw.get("municipality", ""),
                "companyPhone": company_raw.get("phone", ""),
                "companyEmail": company_raw.get("email", ""),
                "employerName": company_raw.get("employer_name", ""),
                "employerCedula": company_raw.get("employer_cedula", ""),
                "representativeName": company_raw.get("representative_name", ""),
                "representativeCedula": company_raw.get("representative_cedula", ""),
                "sector": company_raw.get("sector", ""),
                "fax": company_raw.get("fax", ""),
                "parque": company_raw.get("parque", ""),
                "economicActivity": company_raw.get("economic_activity", ""),
                "rnlNumber": company_raw.get("rnl_number", ""),
                "propertyValue": float(company_raw.get("property_value", 0) or 0),
            },
            "totalOvertimeHours": round(total_overtime, 2),
            "workersOnVacation": employees_on_vacation,
            "workdayStart": "08:00",
            "workdayEnd": "17:00",
            "lunchStart": "12:00",
            "lunchEnd": "13:00",
            "workDays": ["L", "M", "Mi", "J", "V"],
            "restDays": ["S", "D"],
            "saturdayHours": "08:00 - 12:00",
            "establishmentId": establishment_id,
            "sirlaLines": sirla_lines,
            "totalEmployees": len(sirla_lines),
        }

    @staticmethod
    def get_dgt5_data(company_id: str, year: int = None, month: int = None, sandbox: bool = True) -> dict:
        """DGT-5: Personal móvil u ocasional (contrato temporal) con datos SIRLA + PDF.

        El archivo SIRLA DGT-5 se declara por mes (Periodo = MMYYYY).
        """
        from datetime import datetime as _dt
        from app.services.db_service import DatabaseService

        if year is None:
            year = _dt.now().year
        if month is None:
            month = _dt.now().month

        employees = get_employees(company_id, sandbox=sandbox)
        temporales = [
            e for e in employees
            if is_active_equivalent(e.get("status"))
            and e.get("contractType") in ("tiempo_definido", "temporal", "obra_servicio")
        ]

        lines = []
        for e in temporales:
            base = _build_dgt_line(e)
            days = e.get("daysWorked", 0) or 0
            daily = float(e.get("dailySalary", 0) or 0)
            monthly = days * daily
            lines.append({
                **base,
                "fechaEntrada": _to_dgt_date(e.get("hireDate", "")),
                "fechaFin": _to_dgt_date(e.get("terminationDate", "")) if e.get("terminationDate") else "",
                "motivo": e.get("terminationReason", ""),
                "daysWorked": days,
                "dailySalary": daily,
                "monthlySalary": monthly,
            })

        company_raw = DatabaseService.get_company(company_id) or {}

        return {
            "year": year,
            "month": month,
            "company": {
                "companyName": company_raw.get("company_name") or company_raw.get("trade_name", ""),
                "tradeName": company_raw.get("trade_name", ""),
                "companyRNC": company_raw.get("rnc", ""),
                "companyAddress": company_raw.get("address", ""),
                "province": company_raw.get("province", ""),
                "municipality": company_raw.get("municipality", ""),
                "companyPhone": company_raw.get("phone", ""),
                "companyEmail": company_raw.get("email", ""),
                "employerName": company_raw.get("employer_name", ""),
                "employerCedula": company_raw.get("employer_cedula", ""),
                "representativeName": company_raw.get("representative_name", ""),
                "representativeCedula": company_raw.get("representative_cedula", ""),
                "sector": company_raw.get("sector", ""),
                "fax": company_raw.get("fax", ""),
                "parque": company_raw.get("parque", ""),
                "economicActivity": company_raw.get("economic_activity", ""),
                "rnlNumber": company_raw.get("rnl_number", ""),
                "insurancePolicy": company_raw.get("insurance_policy", ""),
                "propertyValue": float(company_raw.get("property_value", 0) or 0),
            },
            "lines": lines,
            "totalEmployees": len(lines),
            "totalBaseSalary": sum(l["salario"] for l in lines),
            "totalDailySalary": sum(l["dailySalary"] for l in lines),
            "totalMonthlySalary": sum(l["monthlySalary"] for l in lines),
        }

    @staticmethod
    def get_dgt9_data(company_id: str, sandbox: bool = True) -> list:
        """DGT-9: Suspensiones activas."""
        from app.services.hr_data_service import get_dgt_suspensions
        return get_dgt_suspensions(company_id, sandbox=sandbox)

    @staticmethod
    def get_dgt9_sirla_data(company_id: str, sandbox: bool = True) -> dict:
        """DGT-9: Datos para exportación SIRLA y PDF."""
        from app.services.db_service import DatabaseService

        suspensions = DGTService.get_dgt9_data(company_id, sandbox=sandbox)
        activas = [s for s in suspensions if s.get("estado") == "activa"]
        company_raw = DatabaseService.get_company(company_id) or {}
        rnl = (company_raw.get("rnl_number", "") or "").replace("-", "").replace(" ", "")
        localidad = rnl[-4:].rjust(6, "0") if rnl else "000000"

        sirla_suspensions = []
        for susp in activas:
            duracion = 0
            inicio = susp.get("fechaInicio", "")
            fin = susp.get("fechaFinPrevista", "")
            if inicio and fin:
                try:
                    d0 = datetime.strptime(inicio[:10], "%Y-%m-%d")
                    d1 = datetime.strptime(fin[:10], "%Y-%m-%d")
                    duracion = (d1 - d0).days
                    if duracion < 0:
                        duracion = 0
                except (ValueError, TypeError):
                    pass

            workers = []
            for w in susp.get("trabajadores", []):
                doc_num = (w.get("documento", "") or "").replace("-", "").replace(" ", "")
                emp_id = w.get("employeeId", "")
                # Buscar por employeeId primero, luego por cédula como fallback
                emp = {}
                if emp_id:
                    emp = next((e for e in get_employees(company_id, sandbox=sandbox)
                               if e.get("id") == emp_id), {})
                if not emp and doc_num:
                    emp = next((e for e in get_employees(company_id, sandbox=sandbox)
                               if (e.get("cedula") or e.get("idNumber", "") or "").replace("-", "") == doc_num), {})
                id_type = emp.get("idType", "cedula") if emp else "cedula"
                workers.append({
                    "docTypeSirla": _map_doc_type_sirla(id_type),
                    "documento": doc_num[:25],
                    "apellidos": (emp.get("firstLastName", "") + " " + emp.get("secondLastName", "")).strip() if emp else "",
                    "nombres": " ".join(p for p in [emp.get("firstName", ""), emp.get("middleName", "")] if p) if emp else "",
                    "nombreCompleto": w.get("nombre", "") or emp.get("fullName", ""),
                    "cargo": w.get("cargo", "") or emp.get("position", ""),
                    "establecimientoId": localidad,
                    "provinciaMunicipio": (emp.get("municipality", "") or "")[:4] if emp else "",
                    "direccion": (emp.get("address", "") or "")[:300] if emp else "",
                    "telefono": (emp.get("phone", "") or "")[:10] if emp else "",
                    "fechaIngreso": _to_dgt_date(emp.get("hireDate", "")) if emp else "",
                    "salario": float(emp.get("baseSalary", emp.get("salary", 0))) if emp else 0.0,
                    "employeeType": emp.get("employeeType", "empleado") if emp else "empleado",
                    "esObrero": emp.get("employeeType", "empleado") == "obrero" if emp else False,
                })

            sirla_suspensions.append({
                "id": susp.get("id", ""),
                "fechaInicio": _to_sirla_date(inicio),
                "fechaInicioDisplay": _to_dgt_date(inicio),
                "fechaFinPrevista": _to_dgt_date(fin),
                "duracion": duracion,
                "causaCodigo": _map_causa_suspension(susp.get("causa", "")),
                "causaTexto": susp.get("causa", ""),
                "establishmentId": susp.get("establishmentId", localidad),
                "trabajadores": workers,
                "totalTrabajadores": len(workers),
            })

        return {
            "company": {
                "companyName": company_raw.get("company_name") or company_raw.get("trade_name", ""),
                "companyRNC": company_raw.get("rnc", ""),
                "rnlNumber": company_raw.get("rnl_number", ""),
            },
            "suspensions": sirla_suspensions,
            "totalSuspensiones": len(sirla_suspensions),
            "totalTrabajadores": sum(s["totalTrabajadores"] for s in sirla_suspensions),
        }

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
