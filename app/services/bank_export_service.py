"""BankExportService — Generacion de archivos bancarios para pago de nomina.

Formatos soportados:
- Banco Popular (BPD 320 chars, especificacion oficial Servicios de Pagos Electronicos)
- Banreservas (CSV pipe-delimited)
- BHD (CSV semicolon-delimited)
"""

import io
import unicodedata
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
        "header": False,
    },
}

BANK_KEY_TO_NAME = {k: v["name"] for k, v in BANK_FORMATS.items()}

BPD_RECORD_LEN = 320


def _normalize_ascii(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_bytes = nfkd.encode("ascii", "ignore")
    return ascii_bytes.decode("ascii")


def _fmt_name_ascii(name: str, width: int) -> str:
    cleaned = " ".join(name.upper().split())
    cleaned = _normalize_ascii(cleaned)
    return cleaned[:width].ljust(width)


def _fmt_cedula_11(cedula: str) -> str:
    clean = cedula.replace("-", "").replace(" ", "")
    return clean.rjust(11)[:11]


def _fmt_cedula_15(cedula: str) -> str:
    clean = cedula.replace("-", "").replace(" ", "")
    return clean.rjust(15)[:15]


def _fmt_account_20(account: str) -> str:
    clean = account.replace("-", "").replace(" ", "")
    return clean.ljust(20)[:20]


def _fmt_monto_13(pesos: float) -> str:
    valor = int(round(pesos * 100))
    return f"{valor:013d}"


def _lookup_bank_entity(bank_name: str, bank_entities: list) -> dict | None:
    name_lower = bank_name.strip().lower()
    for be in (bank_entities or []):
        if be.get("name", "").strip().lower() == name_lower:
            return be
    return None


def _matches_export_bank(emp_bank: str, export_bank_name: str) -> bool:
    return emp_bank.strip().lower() == export_bank_name.strip().lower()


def _build_bpd_header(
    company_rnc: str,
    company_name: str,
    seq: str,
    service_type: str,
    payment_date: str,
    total_amount: float,
    line_count: int,
    email: str,
) -> str:
    now = datetime.now(timezone.utc)
    fecha = now.strftime("%Y%m%d")
    hora = now.strftime("%H%M")

    line = (
        "H"                                                                      # 1
        + company_rnc[:15].ljust(15)                                             # 2-16
        + _normalize_ascii(company_name.upper())[:35].ljust(35)                  # 17-51
        + f"{int(seq):07d}"                                                       # 52-58
        + service_type[:2].ljust(2)                                               # 59-60
        + payment_date                                                            # 61-68
        + f"{0:011d}"                                                             # 69-79  CantidadDB
        + f"{0:013d}"                                                             # 80-92  MontoTotalDB
        + f"{line_count:011d}"                                                    # 93-103 CantidadCR
        + _fmt_monto_13(total_amount)                                            # 104-116 MontoTotalCR
        + f"{0:015d}"                                                             # 117-131 NumeroAfiliacion
        + fecha                                                                   # 132-139
        + hora                                                                    # 140-143
        + _normalize_ascii(email or "")[:40].ljust(40)                           # 144-183
        + " "                                                                     # 184 Estatus
        + " " * 136                                                               # 185-320 Filler
    )
    return line[:BPD_RECORD_LEN].ljust(BPD_RECORD_LEN)


def _build_bpd_transaction(
    company_rnc: str,
    seq: str,
    trans_seq: int,
    account: str,
    account_type: str,
    bank_code: str,
    digi_ver: str,
    neto: float,
    cedula: str,
    employee_name: str,
    payment_date: str,
    email: str,
    ref: str = "",
) -> str:
    tipo_cuenta = "1" if account_type.lower() == "corriente" else "2"
    codigo_operacion = "22" if tipo_cuenta == "1" else "32"
    forma_contacto = "1" if email else "0"

    line = (
        "N"                                                                      # 1
        + company_rnc[:15].ljust(15)                                             # 2-16
        + f"{int(seq):07d}"                                                       # 17-23
        + f"{trans_seq:07d}"                                                      # 24-30
        + _fmt_account_20(account)                                                # 31-50
        + tipo_cuenta                                                             # 51
        + "214"                                                                   # 52-54 Moneda DOP
        + bank_code[:8].ljust(8)                                                 # 55-62
        + (digi_ver or "0")[:1]                                                  # 63
        + codigo_operacion                                                       # 64-65
        + _fmt_monto_13(neto)                                                    # 66-78
        + "CE"                                                                    # 79-80 TipoIdentificacion
        + _fmt_cedula_15(cedula)                                                 # 81-95
        + _fmt_name_ascii(employee_name, 35)                                     # 96-130
        + ref.ljust(12)                                                           # 131-142 NumeroReferencia
        + "PAGO NOMINA ELECTRONICA".ljust(40)                                    # 143-182
        + " " * 4                                                                 # 183-186 FechaVencimiento
        + forma_contacto                                                          # 187
        + _normalize_ascii(email or "")[:40].ljust(40)                           # 188-227
        + " " * 12                                                                # 228-239 FaxTelefonoBenef
        + "00"                                                                    # 240-241 Filler
        + " " * 15                                                                # 242-256 NumeroAut
        + " " * 3                                                                 # 257-259 CodigoRetornoRemoto
        + " " * 3                                                                 # 260-262 CodigoRazonRemoto
        + " " * 3                                                                 # 263-265 CodigoRazonInterno
        + " "                                                                     # 266 ProcesadorTransaccion
        + " " * 2                                                                 # 267-268 EstatusTransaccion
        + " " * 52                                                                # 269-320 Filler
    )
    return line[:BPD_RECORD_LEN].ljust(BPD_RECORD_LEN)


def generate_bank_file(
    payroll_period: dict,
    employees: dict,
    bank: str = "popular",
    company_name: str = "MI EMPRESA SRL",
    company_code: str = "101003383",
    company_email: str = "",
    include_other_banks: bool = False,
    bank_entities: list | None = None,
    export_bank_entity: dict | None = None,
) -> bytes:
    """
    Genera archivo bancario para pago de nomina.

    Args:
        payroll_period: Periodo de nomina con sus lineas
        employees: Mapa {employee_id: employee_data}
        bank: 'popular' | 'banreservas' | 'bhd'
        company_name: Nombre de la empresa
        company_code: RNC de la empresa
        company_email: Email para notificaciones
        include_other_banks: Si True, incluye empleados de otros bancos en el archivo
        bank_entities: Lista de entidades bancarias [{name, bpd_code, digi_ver, ...}]
        export_bank_entity: Entidad bancaria del banco de exportacion
    """
    bank_config = BANK_FORMATS.get(bank, BANK_FORMATS["popular"])
    export_bank_name = bank_config["name"]

    output = io.StringIO()
    total_amount = 0.0
    line_count = 0

    company_name = _normalize_ascii(company_name.upper())
    company_email = _normalize_ascii(company_email)
    company_rnc = company_code.replace("-", "").replace(" ", "")[:15] or "000000000"

    period_key = (payroll_period.get("periodRange")
                  or payroll_period.get("periodKey", ""))
    payment_date = (payroll_period.get("scheduledPaymentDate", "")
                    or payroll_period.get("endDate", ""))
    if not payment_date:
        payment_date = datetime.now(timezone.utc).strftime("%Y%m%d")
    else:
        payment_date = payment_date.replace("-", "")[:8]

    now = datetime.now(timezone.utc)

    if bank == "popular":
        seq = f"{payroll_period.get('revision', 1):07d}"
        service_type = (export_bank_entity or {}).get("bpd_service_type", "01") or "01"

        details_buffer = io.StringIO()
        trans_seq = 0

        for pl in payroll_period.get("lines", []):
            emp_id = pl.get("employeeId", "")
            emp = employees.get(emp_id, {})
            neto = pl.get("netSalary", 0)
            if neto <= 0:
                continue

            emp_bank = emp.get("bank", "")
            if not include_other_banks and not _matches_export_bank(emp_bank, export_bank_name):
                continue

            trans_seq += 1
            account = emp.get("accountNumber", "")
            cedula = emp.get("cedula", "") or emp.get("idNumber", "")
            name = pl.get("employeeName", "") or emp.get("fullName", "")
            email = emp.get("email", "")
            account_type = emp.get("accountType", "")

            emp_entity = _lookup_bank_entity(emp_bank, bank_entities or [])
            bpd_code = (emp_entity or {}).get("bpd_code", "") or "10101070"
            digi_ver = (emp_entity or {}).get("digi_ver", "0") or "0"

            ref = f"NOM{trans_seq:05d}"

            details_buffer.write(
                _build_bpd_transaction(
                    company_rnc=company_rnc,
                    seq=seq,
                    trans_seq=trans_seq,
                    account=account,
                    account_type=account_type,
                    bank_code=bpd_code,
                    digi_ver=digi_ver,
                    neto=neto,
                    cedula=cedula,
                    employee_name=name,
                    payment_date=payment_date,
                    email=email,
                    ref=ref,
                )
            )
            total_amount += neto
            line_count += 1

        header = _build_bpd_header(
            company_rnc=company_rnc,
            company_name=company_name,
            seq=seq,
            service_type=service_type,
            payment_date=payment_date,
            total_amount=total_amount,
            line_count=line_count,
            email=company_email,
        )
        output.write(header)
        output.write(details_buffer.getvalue())

    elif bank == "banreservas":
        output.write(f"H|{company_name}|Nomina {period_key}|{payment_date}\n")
        for pl in payroll_period.get("lines", []):
            emp_id = pl.get("employeeId", "")
            emp = employees.get(emp_id, {})
            neto = pl.get("netSalary", 0)
            if neto <= 0:
                continue

            emp_bank = emp.get("bank", "")
            if not include_other_banks and not _matches_export_bank(emp_bank, export_bank_name):
                continue

            account = emp.get("accountNumber", "")
            cedula = emp.get("cedula", "") or emp.get("idNumber", "")
            name = pl.get("employeeName", "")
            output.write(f"{account}|{name[:50]}|{neto:.2f}|DOP|{cedula}\n")
            total_amount += neto
            line_count += 1
        output.write(f"T|{line_count}|{total_amount:.2f}\n")

    elif bank == "bhd":
        period_type = payroll_period.get("periodType", "")
        if period_type == "quincenal":
            concepto = "Pago Nomina Quincenal"
        elif payroll_period.get("periodSubType") == "christmas_bonus":
            concepto = "Pago Bonificacion y Regalia"
        else:
            concepto = "Pago Nomina Mensual"

        for idx, pl in enumerate(payroll_period.get("lines", []), start=1):
            emp_id = pl.get("employeeId", "")
            emp = employees.get(emp_id, {})
            neto = pl.get("netSalary", 0)
            if neto <= 0:
                continue

            emp_bank = emp.get("bank", "")
            if not include_other_banks and not _matches_export_bank(emp_bank, export_bank_name):
                continue

            account = emp.get("accountNumber", "")
            name = pl.get("employeeName", "").upper().strip()[:50]
            ref = f"NOM{payment_date}{idx:03d}"
            email = emp.get("email", "")
            output.write(f"{account};{name};{ref};{neto:.2f};{concepto};{email}\n")
            total_amount += neto
            line_count += 1

    else:
        output.write(f"H|{company_name}|Nomina {period_key}|{payment_date}\n")
        for pl in payroll_period.get("lines", []):
            emp_id = pl.get("employeeId", "")
            emp = employees.get(emp_id, {})
            neto = pl.get("netSalary", 0)
            if neto <= 0:
                continue

            emp_bank = emp.get("bank", "")
            if not include_other_banks and not _matches_export_bank(emp_bank, export_bank_name):
                continue

            account = emp.get("accountNumber", "")
            cedula = emp.get("cedula", "") or emp.get("idNumber", "")
            name = pl.get("employeeName", "")
            output.write(f"{account}|{name[:50]}|{neto:.2f}|DOP|{cedula}\n")
            total_amount += neto
            line_count += 1
        output.write(f"T|{line_count}|{total_amount:.2f}\n")

    content = output.getvalue().encode("latin-1")

    if bank == "popular":
        _validate_bpd(content, line_count)

    return content


def _validate_bpd(content: bytes, expected_lines: int):
    text = content.decode("latin-1")
    records = text.splitlines()
    errors = []
    for i, rec in enumerate(records):
        if len(rec) != BPD_RECORD_LEN:
            errors.append(f"Registro {i}: esperados {BPD_RECORD_LEN} caracteres, tiene {len(rec)}")
    if errors:
        print(f"\u26a0\ufe0f [BPD Validation] {len(errors)} error(es):")
        for e in errors[:5]:
            print(f"  - {e}")


def generate_bpd_filename(
    contract_code: str,
    service_type: str,
    seq: str,
    submission_date: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    if not submission_date:
        submission_date = now.strftime("%m%d")
    else:
        submission_date = submission_date.replace("-", "")[4:8]
        if len(submission_date) < 4:
            submission_date = now.strftime("%m%d")

    cc = contract_code.strip()[:5].zfill(5) or "00000"
    st = service_type.strip()[:2].ljust(2) or "01"
    mmdd = submission_date[-4:].zfill(4)
    sq = seq.strip()[:7].zfill(7) or "0000001"

    return f"PE{cc}{st}{mmdd}{sq}E.TXT"
