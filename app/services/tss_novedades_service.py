"""TSSNovedadesService — Generación del archivo NV (Novedades) para TSS.

Formato: texto de ancho fijo SUIRPLUS v6.0.
Especificación: Instructivo Construcción Archivos Autodeterminación y
Novedades v6.0 — TSS, Junio 2025.

El archivo NV informa cambios en la plantilla de nómina:
  IN = Ingreso (nueva contratación)
  SA = Salida (terminación)
  VC = Vacaciones
  LV = Licencia Voluntaria
  LM = Licencia por Maternidad
  LD = Licencia por Discapacidad
  AD = Actualización de Datos/Sueldo
"""

import unicodedata
from datetime import datetime
from typing import Optional

NOVEDAD_TYPES = {"IN", "SA", "VC", "LV", "LM", "LD", "AD"}
NOVEDADES_WITH_END_DATE = {"VC", "LV", "LM", "LD"}

_AFP_SALARY_CAP = 464460.00

_MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
          "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def _ascii_upper(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return nfkd.encode("ascii", "ignore").decode("ascii").upper()


def _format_date_tss(date_str: str) -> str:
    """Convierte YYYY-MM-DD a DDMMAAAA."""
    if not date_str:
        return " " * 8
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return d.strftime("%d%m%Y")
    except ValueError:
        return date_str.replace("-", "")[:8]


def _clean_doc(doc: str) -> str:
    return "".join(c for c in (doc or "") if c.isdigit())


def _es_mes_incompleto(emp: dict, year: int, month: int) -> bool:
    hire = (emp.get("hireDate", "") or emp.get("startDate", "") or "").strip()
    term = (emp.get("terminationDate", "") or "").strip()
    try:
        mes_inicio = datetime(year, month, 1).date()
        if month == 12:
            mes_fin = datetime(year + 1, 1, 1).date()
        else:
            mes_fin = datetime(year, month + 1, 1).date()
    except (ValueError, TypeError):
        return False
    if hire:
        try:
            hd = datetime.strptime(hire[:10], "%Y-%m-%d").date()
            if mes_inicio < hd < mes_fin:
                return True
        except ValueError:
            pass
    if term:
        try:
            td = datetime.strptime(term[:10], "%Y-%m-%d").date()
            if mes_inicio <= td < mes_fin and td != mes_inicio:
                return True
        except ValueError:
            pass
    return False


def generate_tss_novedades(
    payroll_period: dict,
    employees: list,
    novedades: list,
    employer_rnc: str = "",
    company_id: str = "",
    sandbox: bool = True,
) -> dict:
    """Genera archivo de Novedades TSS en formato OFICIAL SUIRPLUS v6.0.

    Layout NV (384 caracteres por empleado):
      D(1) + clave(3) + tipoNovedad(2) + fechaInicio(8) + fechaFin(8) +
      tipoDoc(1) + documento(25) + nombres(50) + apellido1(40) +
      apellido2(40) + sexo(1) + fechaNac(8) +
      [salarios: igual que AM] +
      regalia(18) + preaviso(18) + pension(18)

    Args:
        payroll_period: Dict del período de nómina.
        employees: Lista de empleados con datos completos.
        novedades: Lista de novedades a reportar. Cada una:
            {employeeId, tipoNovedad, fechaInicio, fechaFin?}
        employer_rnc: RNC o Cédula del empleador (sin guiones).

    Returns:
        Dict con {content, filename, periodo, periodo_tss, total_empleados, resumen}.
    """
    year = payroll_period.get("year", datetime.now().year)
    month = payroll_period.get("month", datetime.now().month)
    periodo_mmaaaa = f"{month:02d}{year}"
    periodo_label = f"{_MESES[month]}_{year}"

    emp_map = {e.get("id", ""): e for e in employees}

    rnc = "".join(c for c in (employer_rnc or "") if c.isdigit())
    if len(rnc) < 11:
        rnc = rnc.rjust(11)

    output_lines = []

    # ENCABEZADO — 20 caracteres
    header = f"ENV{rnc[-11:].rjust(11)}{periodo_mmaaaa}"
    assert len(header) == 20, f"Encabezado NV: {len(header)} chars, deben ser 20"
    output_lines.append(header)

    empleados_contados = 0

    for nov in novedades:
        emp = emp_map.get(nov.get("employeeId", ""), {})
        if not emp:
            continue

        tipo_nov = (nov.get("tipoNovedad", "") or "").strip().upper()
        if tipo_nov not in NOVEDAD_TYPES:
            continue

        empleados_contados += 1

        # Clave nómina (3)
        tss_key = str(emp.get("tssKey", "") or "").strip()[:3]
        clave = tss_key.rjust(3)

        # Tipo Novedad (2)
        tipo_novedad_str = tipo_nov.ljust(2)[:2]

        # Fecha inicio (8, DDMMAAAA)
        fecha_inicio_str = _format_date_tss(nov.get("fechaInicio", ""))

        # Fecha fin (8, DDMMAAAA) — solo para VC, LV, LM, LD
        if tipo_nov in NOVEDADES_WITH_END_DATE:
            fecha_fin_str = _format_date_tss(nov.get("fechaFin", ""))
        else:
            fecha_fin_str = " " * 8

        # Tipo documento (1)
        id_type = (emp.get("idType", "") or "cedula").lower()
        tipo_doc = "C" if id_type == "cedula" else ("P" if id_type == "pasaporte" else "N")

        # Documento (25)
        doc = "".join(c for c in (emp.get("cedula", "") or emp.get("idNumber", "") or "") if c.isalnum())
        documento = doc.ljust(25)[:25]

        # Nombres (50)
        nombres_raw = f"{emp.get('firstName', '')} {emp.get('middleName', '')}".strip()
        nombres = _ascii_upper(nombres_raw).ljust(50)[:50]

        # 1er Apellido (40)
        apellido1 = (emp.get("firstLastName", "") or emp.get("lastName", "") or "").strip()
        apellido1 = _ascii_upper(apellido1).ljust(40)[:40]

        # 2do Apellido (40)
        apellido2 = (emp.get("secondLastName", "") or "").strip()
        apellido2 = _ascii_upper(apellido2).ljust(40)[:40]

        # Sexo (1)
        gender = (emp.get("gender", "") or "").lower()
        sexo = "M" if gender in ("masculino", "male", "m") else "F"

        # Fecha nacimiento (8, DDMMAAAA)
        birth = (emp.get("birthDate", "") or "").strip()
        fecha_nac = _format_date_tss(birth) if birth else " " * 8

        # ── Salarios ──
        pl = nov.get("payrollLine", {})
        total_income = pl.get("totalIncome", 0) or 0
        afp_cap = emp.get("afpSalaryCap", 0) or _AFP_SALARY_CAP

        emp_status = (emp.get("status", "") or "").lower()
        es_suspendido = emp_status == "suspendido"
        es_ex_empleado = emp_status not in ("activo", "") and emp_status != ""

        if es_suspendido:
            salario_ss = 0.0
            salario_isr = 0.01
            salario_infotep = 0.0
            otras_rem = 0.0
        elif es_ex_empleado:
            salario_ss = 0.0
            salario_isr = pl.get("totalIncome", 0) or 0
            salario_infotep = 0.0
            otras_rem = 0.0
        else:
            salario_ss = min(total_income, afp_cap)
            salario_isr = salario_ss
            salario_infotep = salario_ss
            otras_rem = (pl.get("commission", 0) or 0) + (pl.get("bonus", 0) or 0) + (pl.get("otherIncome", 0) or 0)

        salario_ss_str = f"{salario_ss:016.2f}"[:16]
        aporte_vol = "0000000000000.00"
        salario_isr_str = f"{salario_isr:016.2f}"[:16]
        otras_rem_str = f"{otras_rem:016.2f}"[:16]
        agente_ret = "".rjust(11)
        rem_otros = "0000000000000.00"
        ingresos_exentos = "0000000000000.00"
        saldo_favor = "0000000000000.00"
        salario_infotep_str = f"{salario_infotep:016.2f}"[:16]

        # Tipo ingreso dinámico
        contract_type = (emp.get("contractType", "") or "").lower()
        workday = (emp.get("workday", "") or "").lower()

        if es_suspendido:
            tipo_ingreso = "0001"
        elif contract_type in ("ocasional", "temporal"):
            tipo_ingreso = "0002"
        elif workday in ("media_jornada", "tiempo_parcial"):
            tipo_ingreso = "0003"
        elif contract_type == "prorrateado":
            tipo_ingreso = "0005"
        elif emp.get("pensionado", False):
            tipo_ingreso = "0006"
        elif emp.get("exentoSdss", False):
            tipo_ingreso = "0007"
        elif emp.get("salarioSectorizado", False):
            tipo_ingreso = "0008"
        elif _es_mes_incompleto(emp, year, month):
            tipo_ingreso = "0004"
        else:
            tipo_ingreso = "0001"

        # Ingresos exentos desglosados
        regalia = pl.get("christmasBonus", 0) or 0
        regalia_str = f"01{regalia:016.2f}"[:18]

        preaviso_cesantia = pl.get("preaviso", 0) or pl.get("cesantia", 0) or 0
        pc_str = f"02{preaviso_cesantia:016.2f}"[:18]

        pension = pl.get("pensionAlimenticia", 0) or 0
        pension_str = f"03{pension:016.2f}"[:18]

        # DETALLE — 366 caracteres
        detalle = (
            "D" + clave + tipo_novedad_str + fecha_inicio_str + fecha_fin_str +
            tipo_doc + documento + nombres + apellido1 + apellido2 +
            sexo + fecha_nac + salario_ss_str + aporte_vol +
            salario_isr_str + otras_rem_str + agente_ret + rem_otros +
            ingresos_exentos + saldo_favor + salario_infotep_str +
            tipo_ingreso + regalia_str + pc_str + pension_str
        )
        assert len(detalle) == 384, f"Detalle NV: {len(detalle)} chars, deben ser 384"
        output_lines.append(detalle)

    # SUMARIO — 7 caracteres
    total_registros = 1 + empleados_contados + 1
    trailer = f"S{total_registros:06d}"
    output_lines.append(trailer)

    content = "\n".join(output_lines) + "\n"

    rnc_clean = "".join(c for c in (employer_rnc or "000000000") if c.isdigit())
    filename = f"NV_{rnc_clean}_{periodo_mmaaaa}.txt"

    return {
        "content": content,
        "filename": filename,
        "periodo": periodo_label,
        "periodo_tss": periodo_mmaaaa,
        "total_empleados": empleados_contados,
        "resumen": {
            "total_empleados": empleados_contados,
            "total_registros": total_registros,
        },
    }


def build_novedades_for_period(
    payroll_period: dict,
    employees: list,
    vacation_requests: Optional[list] = None,
    leave_requests: Optional[list] = None,
    license_mapping: Optional[dict] = None,
) -> list:
    """Detecta automáticamente las novedades TSS para un período.

    Analiza contrataciones, salidas, vacaciones y licencias para generar
    la lista de novedades a incluir en el archivo NV.

    Args:
        payroll_period: Dict del período de nómina con year y month.
        employees: Lista de empleados con datos completos.
        vacation_requests: Lista de solicitudes de vacaciones aprobadas.
        leave_requests: Lista de solicitudes de licencia aprobadas.
        license_mapping: Mapeo SPN→TSS de licencias.

    Returns:
        Lista de novedades: [{employeeId, tipoNovedad, fechaInicio, fechaFin, employee, payrollLine}].
    """
    from app.services.tss_license_mapping import DEFAULT_TSS_LICENSE_MAPPING, map_leave_to_tss

    year = payroll_period.get("year", datetime.now().year)
    month = payroll_period.get("month", datetime.now().month)
    mapping = license_mapping or DEFAULT_TSS_LICENSE_MAPPING

    try:
        periodo_inicio = datetime(year, month, 1).date()
        if month == 12:
            periodo_fin = datetime(year + 1, 1, 1).date()
        else:
            periodo_fin = datetime(year, month + 1, 1).date()
    except (ValueError, TypeError):
        return []

    novedades = []
    emp_map = {e.get("id", ""): e for e in employees}

    for emp in employees:
        emp_id = emp.get("id", "")
        if not emp_id:
            continue

        # IN = Ingreso (contratado en el período)
        hire_date = (emp.get("hireDate", "") or emp.get("startDate", "") or "").strip()
        if hire_date:
            try:
                hd = datetime.strptime(hire_date[:10], "%Y-%m-%d").date()
                if periodo_inicio <= hd < periodo_fin:
                    novedades.append({
                        "employeeId": emp_id,
                        "tipoNovedad": "IN",
                        "fechaInicio": hire_date[:10],
                        "fechaFin": "",
                        "employee": emp,
                    })
            except ValueError:
                pass

        # SA = Salida (terminado en el período)
        term_date = (emp.get("terminationDate", "") or "").strip()
        if term_date:
            try:
                td = datetime.strptime(term_date[:10], "%Y-%m-%d").date()
                if periodo_inicio <= td < periodo_fin:
                    novedades.append({
                        "employeeId": emp_id,
                        "tipoNovedad": "SA",
                        "fechaInicio": term_date[:10],
                        "fechaFin": "",
                        "employee": emp,
                    })
            except ValueError:
                pass

    # VC = Vacaciones (solicitudes aprobadas que caen en el período)
    for vac in (vacation_requests or []):
        if vac.get("status", "") != "aprobada":
            continue
        emp_id = vac.get("employeeId", "")
        start = (vac.get("startDate", "") or "").strip()
        end = (vac.get("endDate", "") or "").strip()
        if not start:
            continue
        try:
            sd = datetime.strptime(start[:10], "%Y-%m-%d").date()
            ed = datetime.strptime(end[:10], "%Y-%m-%d").date() if end else sd
            if sd < periodo_fin and ed >= periodo_inicio:
                emp = emp_map.get(emp_id, {})
                novedades.append({
                    "employeeId": emp_id,
                    "tipoNovedad": "VC",
                    "fechaInicio": start[:10],
                    "fechaFin": end[:10] if end else "",
                    "employee": emp,
                })
        except ValueError:
            pass

    # LV, LM, LD = Licencias (solicitudes aprobadas que caen en el período)
    for lic in (leave_requests or []):
        if lic.get("status", "") != "aprobada":
            continue
        emp_id = lic.get("employeeId", "")
        spn_type = (lic.get("leaveType", "") or "").strip()
        tss_code = map_leave_to_tss(spn_type, mapping)
        if not tss_code or tss_code not in NOVEDAD_TYPES:
            continue
        start = (lic.get("startDate", "") or "").strip()
        end = (lic.get("endDate", "") or "").strip()
        if not start:
            continue
        try:
            sd = datetime.strptime(start[:10], "%Y-%m-%d").date()
            ed = datetime.strptime(end[:10], "%Y-%m-%d").date() if end else sd
            if sd < periodo_fin and ed >= periodo_inicio:
                emp = emp_map.get(emp_id, {})
                novedades.append({
                    "employeeId": emp_id,
                    "tipoNovedad": tss_code,
                    "fechaInicio": start[:10],
                    "fechaFin": end[:10] if end else "",
                    "employee": emp,
                })
        except ValueError:
            pass

    return novedades


def generate_tss_novedades_csv(novedades: list) -> str:
    """Genera CSV de novedades TSS.

    Columnas: Tipo Novedad, Fecha Inicio, Fecha Fin, Cédula, Nombre,
              Salario SS, Salario ISR, Otras Rem, Salario INFOTEP.
    """
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Tipo_Novedad", "Fecha_Inicio", "Fecha_Fin", "Cedula", "Nombre",
        "Salario_Seguridad_Social", "Salario_ISR", "Otras_Remuneraciones",
        "Salario_INFOTEP", "Tipo_Ingreso",
    ])

    for nov in novedades:
        emp = nov.get("employee", {})
        pl = nov.get("payrollLine", {})
        total_income = pl.get("totalIncome", 0) or 0

        writer.writerow([
            nov.get("tipoNovedad", ""),
            nov.get("fechaInicio", ""),
            nov.get("fechaFin", ""),
            emp.get("cedula", "") or emp.get("idNumber", ""),
            f"{emp.get('firstName', '')} {emp.get('firstLastName', '')}".strip(),
            f"{min(total_income, _AFP_SALARY_CAP):.2f}",
            f"{total_income:.2f}",
            f"{(pl.get('commission', 0) or 0) + (pl.get('bonus', 0) or 0) + (pl.get('otherIncome', 0) or 0):.2f}",
            f"{total_income:.2f}",
            "0001",
        ])

    return output.getvalue()
