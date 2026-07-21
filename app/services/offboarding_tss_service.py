"""OffboardingTSSService — Generación de notificación de baja para TSS.

Genera un archivo de texto de ancho fijo en formato SUIRPLUS v6.0
con los datos del empleado para notificar su egreso a la TSS.
"""

from datetime import datetime
from typing import Optional


def _clean(val: str, length: int, pad: str = " ") -> str:
    """Limpia y trunca/pad un campo a longitud fija."""
    s = (val or "").strip().upper()
    s = s.replace("Ñ", "N").replace("Ó", "O").replace("Í", "I")
    s = s.replace("É", "E").replace("Á", "A").replace("Ú", "U")
    s = s.replace("Ü", "U")
    if len(s) > length:
        s = s[:length]
    return s.ljust(length, pad)


def _format_date_tss(date_str: str) -> str:
    """Convierte YYYY-MM-DD a DDMMAAAA."""
    if not date_str:
        return " " * 8
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return d.strftime("%d%m%Y")
    except ValueError:
        return date_str.replace("-", "")


def _clean_doc(doc: str) -> str:
    """Limpia cédula/RNC: solo dígitos."""
    return "".join(c for c in (doc or "") if c.isdigit())


def _prorate_salary(base_salary: float, effective_date_str: str) -> float:
    """Calcula el salario proporcional para una salida a mitad de mes.

    Según el instructivo TSS, cuando un empleado sale antes de fin de mes,
    el salario cotizable reportado debe corresponder al monto realmente
    devengado en ese período, no al salario mensual completo.

    Se usa 30 como divisor estándar (convención TSS).
    Si la salida es el día 28 o posterior, se reporta el mes completo.
    """
    if not effective_date_str or not base_salary:
        return base_salary
    try:
        d = datetime.strptime(effective_date_str[:10], "%Y-%m-%d")
        day = d.day
        if day >= 28:
            return base_salary
        return round(base_salary / 30 * day, 2)
    except (ValueError, TypeError):
        return base_salary


def _get_period_from_date(date_str: str) -> str:
    """Extrae el período TSS (MMAAAA) de la fecha efectiva de salida."""
    if not date_str:
        return datetime.now().strftime("%m%Y")
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return d.strftime("%m%Y")
    except ValueError:
        return datetime.now().strftime("%m%Y")


def generate_tss_baja(
    request_data: dict,
    employee: dict,
    company_rnc: str,
    period_key: str = None,
) -> str:
    """Genera archivo de texto SUIRPLUS v6.0 para notificar una baja.

    Formato: cabecera (1 línea) + detalle (1 línea por empleado).

    Returns:
        str: Contenido del archivo de texto.
    """
    effective_date = request_data.get("effectiveDate", "") or employee.get("terminationDate", "")
    period = period_key or _get_period_from_date(effective_date)

    base_salary = float(employee.get("baseSalary", 0) or 0)
    prorated_salary = _prorate_salary(base_salary, effective_date)

    encabezado = _generate_encabezado(company_rnc, period)
    detalle = _generate_detalle(request_data, employee, period, prorated_salary)

    return encabezado + "\n" + detalle + "\n"


def _generate_encabezado(rnc: str, period: str) -> str:
    """E = Encabezado (20 caracteres)."""
    rnc_clean = _clean_doc(rnc)[:11]
    return "E" + rnc_clean.ljust(11) + period.ljust(6) + " " * 2


def _generate_detalle(request_data: dict, employee: dict, period: str, salary_cotizable: float) -> str:
    """D = Detalle (356 caracteres por SUIRPLUS v6.0)."""
    emp_name = (employee.get("firstName", "") or "") + " " + (employee.get("middleName", "") or "")
    emp_surname1 = employee.get("firstLastName", "") or employee.get("lastName", "") or ""
    emp_surname2 = employee.get("secondLastName", "") or ""
    cedula = _clean_doc(employee.get("cedula", "") or employee.get("idNumber", ""))
    doc_type = "C" if len(cedula) == 11 else "P"
    sexo = (employee.get("gender", "") or "M")[:1].upper()
    if sexo not in ("M", "F"):
        sexo = "M"
    birth = _format_date_tss(employee.get("birthDate", ""))
    tss_key = (employee.get("tssKey", "") or "")[:3]
    termination_type = request_data.get("terminationType", "")
    effective_date = request_data.get("effectiveDate", "") or employee.get("terminationDate", "")

    tipo_novedad = "2"
    if termination_type in ("fallecimiento",):
        tipo_novedad = "3"
    elif termination_type in ("jubilacion",):
        tipo_novedad = "4"

    nov_detalle = _clean(effective_date[:10], 10)
    fecha_egreso = _format_date_tss(effective_date)

    line = "D"
    line += _clean(tss_key, 3)                    # 1-3:  Clave Nómina
    line += _clean(doc_type, 1)                   # 4:    Tipo doc
    line += _clean(cedula, 13)                    # 5-17: Documento
    line += _clean(emp_name, 30)                  # 18-47: Nombres
    line += _clean(emp_surname1, 15)              # 48-62: 1er Apellido
    line += _clean(emp_surname2, 15)              # 63-77: 2do Apellido
    line += _clean(sexo, 1)                       # 78:   Sexo
    line += _clean(birth, 8)                      # 79-86: Fecha Nac.
    line += _clean(fecha_egreso, 8)               # 87-94: Fecha Egreso
    line += _clean(tipo_novedad, 1)               # 95:   Tipo Novedad (2=baja)
    line += _clean(period, 6)                     # 96-101: Período
    line += f"{salary_cotizable:010.2f}".replace(".", "")[:10]  # 102-111: Salario Cotizable
    line += "0" * 10                               # 112-121: Aporte Voluntario AFP
    line += "0" * 10                               # 122-131: Salario ISR
    line += _clean("", 30)                         # 132-161: Otras Remuneraciones
    line += _clean("", 11)                         # 162-172: RNC Agente Retención
    line += "0" * 10                               # 173-182: Remun. Otros Empleadores
    line += "0" * 10                               # 183-192: Ingresos Exentos
    line += "0" * 10                               # 193-202: Saldo a Favor
    line += "0" * 10                               # 203-212: Salario INFOTEP
    line += " " * 10                               # 213-222: (reservado)
    line += _clean(nov_detalle, 10)                # 223-232: Detalle Novedad
    line += " " * 24                               # 233-256: (reservado)
    line += "0" * 10                               # 257-266: Regalía Pascual
    line += "0" * 10                               # 267-276: Preaviso/Cesantía
    line += "0" * 10                               # 277-286: Retención Pensión Alimenticia
    line += " " * 60                               # 287-346: (filler)
    line += "0" * 10                               # 347-356: Remuneración período
    line += " " * 10                               # 357-366: (filler)

    return line


def get_tss_baja_filename(company_rnc: str, period: str = None) -> str:
    now = datetime.now()
    p = period or now.strftime("%m%Y")
    rnc = _clean_doc(company_rnc)[:11]
    return f"BA_{rnc}_{p}.txt"
