"""IR13Service — Cálculo y agregación del reporte IR-13 (DGII).

Declaración Jurada Anual del Agente de Retención de Asalariados.
Consolida los 12 períodos de nómina del año fiscal por empleado
y calcula las columnas oficiales A-N del formato DGII.

Especificación: IR-13 — DGII, República Dominicana.
"""

from datetime import date, datetime
from typing import Optional


ISR_ANNUAL_TABLE = [
    (0.00,        416220.00,   0.00, 0.00),
    (416220.01,   624329.00,   0.15, 0.00),
    (624329.01,   867123.00,   0.20, 31216.00),
    (867123.01,   float("inf"), 0.25, 79775.00),
]

ANNUAL_EDUCATION_DEDUCTION = 50000.00


def _resolve_company_id(owner_uid, company_id=None):
    """Helper para resolver company_id sin import circular."""
    return company_id or ""


def calculate_annual_isr(annual_taxable: float, education_deduction: float = 0.0) -> float:
    """Calcula el ISR anual según la tabla progresiva de la DGII.

    Formula: (base_imponible - floor) * rate + fixed

    Args:
        annual_taxable: Base imponible anual (columna I).
        education_deduction: Deducción anual por gastos educativos.

    Returns:
        ISR anual liquidado (columna J).
    """
    taxable = max(0.0, annual_taxable - min(education_deduction, ANNUAL_EDUCATION_DEDUCTION))
    for floor, ceiling, rate, fixed in ISR_ANNUAL_TABLE:
        if taxable <= ceiling:
            return round((taxable - floor) * rate + fixed, 2)
    return 0.0


def calculate_ir13(company_id: str, year: int, sandbox: bool = True) -> dict:
    """Consolida los datos anuales de todos los empleados para el IR-13.

    Itera todos los períodos de nómina del año y acumula por empleado
    los ingresos, deducciones, exentos e ISR retenido. Luego calcula
    el ISR liquidado (columna J) usando la tabla anual.

    Args:
        company_id: ID de la compañía en Firestore.
        year: Año fiscal a reportar (ej. 2025).
        sandbox: Si True, usa datos de sandbox.

    Returns:
        Dict con {
            company: dict,       # perfil de la compañía
            year: int,
            employees: [         # lista de filas por empleado
                {apellidos_nombres, cedula, C, D, E, F, G, H, I, J, L, M, N}
            ],
            totals: dict,        # sumatorias de cada columna
            num_asalariados: int,
            num_sujetos_retencion: int,
        }
    """
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    employee_map = {e.get("id", ""): e for e in hr.get_employees(company_id, sandbox=sandbox)}
    periods = hr.get_payroll_periods(company_id, sandbox=sandbox)

    accum = {}  # emp_id -> dict de acumulados

    for period in periods:
        pk = period.get("periodKey", "")
        py = period.get("year", 0)
        if py != year:
            continue

        lines = PayrollService.get_period_lines(period, company_id=company_id, sandbox=sandbox)
        for line in lines:
            emp_id = line.get("employeeId", "")
            if not emp_id:
                continue

            emp = employee_map.get(emp_id, {})
            if emp.get("status", "activo") not in ("activo", "inactivo", "suspendido"):
                continue

            if emp_id not in accum:
                accum[emp_id] = {
                    "C": 0.0, "D": 0.0, "E": 0.0, "G": 0.0, "H": 0.0, "L": 0.0,
                    "education": 0.0, "line_count": 0,
                }

            a = accum[emp_id]
            a["C"] += float(line.get("grossSalary", 0) or 0)
            a["D"] += (float(line.get("commission", 0) or 0) +
                        float(line.get("bonus", 0) or 0) +
                        float(line.get("otherIncome", 0) or 0))
            a["G"] += (float(line.get("christmasBonus", 0) or 0) +
                        float(line.get("preaviso", 0) or 0) +
                        float(line.get("cesantia", 0) or 0))
            a["H"] += (float(line.get("afpEmployee", 0) or 0) +
                        float(line.get("sfsEmployee", 0) or 0))
            a["L"] += float(line.get("isrRetention", 0) or 0)

            education = float(line.get("educationDeduction", 0) or 0)
            a["education"] = max(a["education"], education)

            a["line_count"] += 1

    employees = []
    totals = {"C": 0.0, "D": 0.0, "E": 0.0, "F": 0.0, "G": 0.0,
              "H": 0.0, "I": 0.0, "J": 0.0, "L": 0.0, "M": 0.0, "N": 0.0}
    num_sujetos = 0

    for emp_id, a in accum.items():
        emp = employee_map.get(emp_id, {})
        if not emp:
            continue
        if a["line_count"] == 0:
            continue

        C = round(a["C"], 2)
        D = round(a["D"], 2)
        E_val = 0.0
        F = round(C + D + E_val, 2)
        G = round(a["G"], 2)
        H = round(a["H"], 2)
        I_val = round(max(0.0, F - G - H), 2)
        J_val = calculate_annual_isr(I_val, a["education"])
        L_val = round(a["L"], 2)
        M_val = round(max(0.0, L_val - J_val), 2)
        N_val = round(max(0.0, J_val - L_val), 2)

        first_name = (emp.get("firstName", "") or "").strip()
        middle_name = (emp.get("middleName", "") or "").strip()
        first_last = (emp.get("firstLastName", "") or emp.get("lastName", "") or "").strip()
        second_last = (emp.get("secondLastName", "") or "").strip()

        nombres = f"{first_name} {middle_name}".strip()
        apellidos = f"{first_last} {second_last}".strip()
        apellidos_nombres = f"{apellidos}, {nombres}".strip(", ")

        row = {
            "apellidos_nombres": apellidos_nombres,
            "cedula": emp.get("cedula", "") or emp.get("idNumber", "") or "",
            "C": C, "D": D, "E": E_val, "F": F,
            "G": G, "H": H, "I": I_val,
            "J": J_val, "L": L_val,
            "M": M_val, "N": N_val,
        }

        employees.append(row)

        for k in ("C", "D", "E", "F", "G", "H", "I", "J", "L", "M", "N"):
            totals[k] = round(totals[k] + (row[k] or 0), 2)

        if J_val > 0 or L_val > 0:
            num_sujetos += 1

    employees.sort(key=lambda r: r["apellidos_nombres"])

    return {
        "company": {},
        "year": year,
        "employees": employees,
        "totals": totals,
        "num_asalariados": len(employees),
        "num_sujetos_retencion": num_sujetos,
    }
