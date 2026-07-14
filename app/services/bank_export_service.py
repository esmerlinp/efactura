"""BankExportService — Generación de archivos bancarios para pago de nómina.

Formatos soportados:
- Banco Popular (fixed-width, formato ACH estándar)
- Banreservas (CSV)
- BHD (CSV)
"""

import io
from datetime import datetime, timezone


BANK_FORMATS = {
    "popular": {
        "name": "Banco Popular Dominicano",
        "extension": "txt",
        "header": True,
    },
    "banreservas": {
        "name": "Banco de Reservas",
        "extension": "txt",
        "header": True,
    },
    "bhd": {
        "name": "Banco BHD",
        "extension": "txt",
        "header": True,
    },
}


# ── Formato Banco Popular (fixed-width) ──────────────────────────────────
#
# Basado en el estándar ACH del Banco Popular Dominicano:
#
# HEADER (168 chars):
#   Pos  0  (1)   Tipo registro: 'H'
#   Pos  1-9 (9)   Código de compañía/contrato
#   Pos 10-15 (6)  Espacios
#   Pos 16-40 (25) Nombre empresa (left-padded, uppercase)
#   Pos 41-50 (10) Espacios
#   Pos 51-58 (8)  Referencia/sequence (padded 8 digits)
#   Pos 59-60 (2)  Indicador '01'
#   Pos 61-68 (8)  Fecha proceso YYYYMMDD (pago)
#   Pos 69-?  (39) Disponible (ceros)
#   Pos ?-?   (8)  Monto total (centavos, sin decimal, 8 dígitos)  => NOTA: probar posición
#   Pos ?-?   (15) Ceros / relleno
#   Pos ?-?   (12) Fecha+hora envío YYYYMMDDHHMM (ej: 202607132120)
#   Pos ?-fin      Email de notificación
#
# DETALLE (165 chars):
#   Pos  0  (1)   Tipo registro: 'N'
#   Pos  1-9 (9)   Código de compañía/contrato
#   Pos 10-15 (6)  Espacios
#   Pos 16-22 (7)  Secuencia/lote del detalle (3+4 o 7 dígitos)
#   Pos 23-38 (16) Cédula sin guiones, left-padded con ceros
#   Pos 39-49 (11) Espacios
#   Pos 50-64 (15) Número de cuenta bancaria
#   Pos 65-77 (13) Monto (centavos ×10, 13 dígitos, zero-padded) — ej: $960.00 → 9600000 → '0000009600000'
#                  NOTA: en el ejemplo real $960.00 aparece como '0000000096000' (×10000?).
#                  Por seguridad usamos centavos × 100 (formato más común en RD).
#   Pos 78-94 (17) Espacios
#   Pos 95-125(31) Nombre del empleado (left-padded, uppercase)
#   Pos 126-130(5) Espacios
#   Pos 131-138(8) Fecha pago YYYYMMDD
#   Pos 139-141(3) Espacios
#   Pos 142-163(22) Concepto: 'PAGO NOMINA ELECTRONICA'
#
# NOTA: El formato exacto puede variar ligeramente según la versión del banco.
#       Los valores se generan con UTF-8 BOM.


HEADER_TEMPLATE = (
    "{record_type:1s}"            # 0     — 'H'
    "{company_code:9s}"           # 1-9
    "      "                       # 10-15 (6 spaces)
    "{company_name:25s}"          # 16-40
    "          "                   # 41-50 (10 spaces)
    "{reference:>7s}"             # 51-57
    "01"                           # 58-59
    "{process_date}"              # 60-67  YYYYMMDD
    "{zeros_33}"                  # 68-100
    "{amount_prefix:7s}"          # 101-107  — "7100000"
    "{total_amount:>8s}"          # 108-115 — total × 10, 8 dígitos
    "{zeros_15}"                  # 116-130
    "{timestamp}"                 # 131-142 YYYYMMDDHHMM
    "{email}"                     # 143+   email
    "\n"
)

DETALLE_TEMPLATE = (
    "{record_type:1s}"            # 0     — 'N'
    "{company_code:9s}"           # 1-9
    "      "                       # 10-15 (6 spaces)
    "{secuencia:>7s}"             # 16-22
    "{cedula:>16s}"               # 23-38
    "           "                  # 39-49 (11 spaces)
    "{account:15s}"               # 50-64
    "{amount:>13s}"               # 65-77  — ×10, 13 dígitos
    "                 "           # 78-94  (17 spaces)
    "{employee_name:31s}"         # 95-125
    "    "                         # 126-129 (4 spaces)
    "{payment_date}"              # 130-137 YYYYMMDD
    "    "                         # 138-141 (4 spaces)
    "{concept:23s}"               # 142-164
    "\n"
)


def _fmt_amount(pesos: float, width: int = 13) -> str:
    """Convierte monto en pesos a formato ×10 (1 decimal implícito), padded.

    Ej: $96,026.90 → 960269 (×10).  $180,000.00 → 1800000 (×10).
    """
    valor = int(round(pesos * 10))
    return f"{valor:0{width}d}"


def _fmt_amount_header(pesos: float) -> str:
    """Convierte monto total para header: ×10, 8 dígitos."""
    valor = int(round(pesos * 10))
    return f"{valor:08d}"


import unicodedata


def _normalize_ascii(text: str) -> str:
    """Normaliza caracteres especiales del español a ASCII.
    Ñ → N, ñ → n, á → a, é → e, í → i, ó → o, ú → u, ü → u, etc.
    """
    # Paso 1: descomponer (NFKD) para separar diacríticos
    nfkd = unicodedata.normalize("NFKD", text)
    # Paso 2: eliminar diacríticos (combining marks), preservando letras base
    ascii_bytes = nfkd.encode("ascii", "ignore")
    return ascii_bytes.decode("ascii")


def _fmt_name(name: str, width: int = 31) -> str:
    """Formatea nombre: uppercase, ASCII-only, recortado/padded al ancho."""
    cleaned = " ".join(name.upper().split())
    cleaned = _normalize_ascii(cleaned)
    return cleaned[:width].ljust(width)


def _fmt_cedula(cedula: str) -> str:
    """Limpia cédula: quita guiones y padd con ceros a 16."""
    clean = cedula.replace("-", "").replace(" ", "")
    if clean.isdigit() and len(clean) < 16:
        return clean.zfill(16)
    return clean.rjust(16)


def _fmt_account(account: str) -> str:
    """Limpia número de cuenta: quita guiones/espacios, padd a 15."""
    clean = account.replace("-", "").replace(" ", "")
    return clean.ljust(15)[:15]


def generate_bank_file(payroll_period: dict, employees: dict,
                       bank: str = "popular",
                       company_name: str = "MI EMPRESA SRL",
                       company_code: str = "101003383",
                       company_email: str = "") -> bytes:
    """
    Genera archivo bancario para pago de nómina.

    Args:
        payroll_period: Período de nómina con sus líneas
        employees: Mapa {employee_id: employee_data}
        bank: 'popular' | 'banreservas' | 'bhd'
        company_name: Nombre de la empresa
        company_code: Código/contrato en el banco
        company_email: Email para notificaciones (header Popular)
    """
    bank_config = BANK_FORMATS.get(bank, BANK_FORMATS["popular"])
    output = io.StringIO()
    total_amount = 0.0
    line_count = 0

    # Normalizar campos de texto a ASCII (el banco requiere Latin-1 / ANSI)
    company_name = _normalize_ascii(company_name.upper())
    company_email = _normalize_ascii(company_email)

    period_key = (payroll_period.get("periodRange")
                  or payroll_period.get("periodKey", ""))
    payment_date = (payroll_period.get("scheduledPaymentDate", "")
                    or payroll_period.get("endDate", ""))
    if not payment_date:
        payment_date = datetime.now(timezone.utc).strftime("%Y%m%d")
    else:
        payment_date = payment_date.replace("-", "")[:8]

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d%H%M")

    if bank == "popular":
        # ── Generar Header (H) con placeholder total ──
        ref_num = payroll_period.get("revision", 1)
        ref = f"{ref_num:07d}"
        output.write(
            HEADER_TEMPLATE.format(
                record_type="H",
                company_code=company_code[:9].ljust(9),
                company_name=_fmt_name(company_name, 25),
                reference=ref,
                process_date=payment_date,
                zeros_33="0" * 33,
                amount_prefix="7100000",
                total_amount=_fmt_amount_header(0.0),
                zeros_15="0" * 15,
                timestamp=timestamp,
                email=company_email or "",
            )
        )
        header_len = output.tell()

        # ── Generar Detalles (N) ──
        for idx, pl in enumerate(payroll_period.get("lines", []), start=1):
            emp_id = pl.get("employeeId", "")
            emp = employees.get(emp_id, {})
            neto = pl.get("netSalary", 0)
            if neto <= 0:
                continue

            account = emp.get("accountNumber", "")
            cedula = emp.get("cedula", "") or emp.get("idNumber", "")
            name = pl.get("employeeName", "") or emp.get("fullName", "")

            output.write(
                DETALLE_TEMPLATE.format(
                    record_type="N",
                    company_code=company_code[:9].ljust(9),
                    secuencia=f"{idx:07d}",
                    cedula=_fmt_cedula(cedula),
                account=_fmt_account(account),
                    amount=_fmt_amount(neto),
                    employee_name=_fmt_name(name, 31),
                    payment_date=payment_date,
                    concept="PAGO NOMINA ELECTRONICA",
                )
            )
            total_amount += neto
            line_count += 1

        # ── Reescribir Header con total correcto ──
        output.seek(0)
        header = output.read(header_len)
        output.seek(0)
        output.write(
            HEADER_TEMPLATE.format(
                record_type="H",
                company_code=company_code[:9].ljust(9),
                company_name=_fmt_name(company_name, 25),
                reference=ref,
                process_date=payment_date,
                zeros_33="0" * 33,
                amount_prefix="7100000",
                total_amount=_fmt_amount_header(total_amount),
                zeros_15="0" * 15,
                timestamp=timestamp,
                email=company_email or "",
            )
        )
        output.seek(0, io.SEEK_END)

    elif bank == "banreservas":
        output.write(f"H|{company_name}|Nomina {period_key}|{payment_date}\n")
        for pl in payroll_period.get("lines", []):
            emp_id = pl.get("employeeId", "")
            emp = employees.get(emp_id, {})
            neto = pl.get("netSalary", 0)
            if neto <= 0:
                continue
            account = emp.get("accountNumber", "")
            cedula = emp.get("cedula", "") or emp.get("idNumber", "")
            name = pl.get("employeeName", "")
            output.write(f"{account}|{name[:50]}|{neto:.2f}|DOP|{cedula}\n")
            total_amount += neto
            line_count += 1
        output.write(f"T|{line_count}|{total_amount:.2f}\n")

    elif bank == "bhd":
        output.write(f"H|{company_name}|Nomina {period_key}|{payment_date}\n")
        for pl in payroll_period.get("lines", []):
            emp_id = pl.get("employeeId", "")
            emp = employees.get(emp_id, {})
            neto = pl.get("netSalary", 0)
            if neto <= 0:
                continue
            account = emp.get("accountNumber", "")
            name = pl.get("employeeName", "")
            output.write(f"{account}|{name[:40]}|{neto:.2f}|DOP|PAGO NOMINA\n")
            total_amount += neto
            line_count += 1
        output.write(f"T|{line_count}|{total_amount:.2f}\n")

    else:
        output.write(f"H|{company_name}|Nomina {period_key}|{payment_date}\n")
        for pl in payroll_period.get("lines", []):
            emp_id = pl.get("employeeId", "")
            emp = employees.get(emp_id, {})
            neto = pl.get("netSalary", 0)
            if neto <= 0:
                continue
            account = emp.get("accountNumber", "")
            cedula = emp.get("cedula", "") or emp.get("idNumber", "")
            name = pl.get("employeeName", "")
            output.write(f"{account}|{name[:50]}|{neto:.2f}|DOP|{cedula}\n")
            total_amount += neto
            line_count += 1
        output.write(f"T|{line_count}|{total_amount:.2f}\n")

    return output.getvalue().encode("latin-1")
