"""BankExportService — Generación de archivos bancarios para pago de nómina.

Formatos soportados:
- Banco Popular (ACH)
- Banreservas (TXT)
- BHD (TXT)
"""

import io


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


def generate_bank_file(payroll_period: dict, employees: dict, bank: str = "popular") -> bytes:
    bank_config = BANK_FORMATS.get(bank, BANK_FORMATS["popular"])
    output = io.StringIO()
    total_amount = 0.0
    line_count = 0

    if bank_config.get("header"):
        period_label = payroll_period.get("periodRange") or payroll_period.get("periodKey", "")
        output.write(f"H|{bank_config['name']}|Nomina {period_label}|{payroll_period.get('processedDate','')}\n")

    for pl in payroll_period.get("lines", []):
        emp_id = pl.get("employeeId", "")
        emp = employees.get(emp_id, {})
        neto = pl.get("netSalary", 0)
        if neto <= 0:
            continue

        account = emp.get("accountNumber", "")
        acct_type = emp.get("accountType", "")
        emp_bank = emp.get("bank", "")
        cedula = emp.get("cedula", "") or emp.get("idNumber", "")
        name = pl.get("employeeName", "")

        if bank == "popular":
            output.write(f"D|{account}|{acct_type or 'A'}|{cedula}|{name[:40]}|{neto:.2f}|DOP|Concepto: Pago nomina\n")
        elif bank == "banreservas":
            output.write(f"{account}|{name[:50]}|{neto:.2f}|DOP|{cedula}\n")
        elif bank == "bhd":
            output.write(f"{account}|{name[:40]}|{neto:.2f}|DOP|PAGO NOMINA\n")
        else:
            output.write(f"{account}|{name[:50]}|{neto:.2f}|DOP|{cedula}\n")

        total_amount += neto
        line_count += 1

    if bank_config.get("header"):
        output.write(f"T|{line_count}|{total_amount:.2f}\n")

    return output.getvalue().encode("utf-8-sig")
