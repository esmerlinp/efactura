AFP_EMPLOYEE_RATE = 0.0287
AFP_EMPLOYER_RATE = 0.0710
SFS_EMPLOYEE_RATE = 0.0304
SFS_EMPLOYER_RATE = 0.0709
SRL_EMPLOYER_RATES = {1: 0.0110, 2: 0.0115, 3: 0.0120, 4: 0.0130}
SRL_EMPLOYER_RATE = 0.0120
SRL_SALARY_CAP = 92892.00
INFOTEP_EMPLOYER_RATE = 0.0100
INFOTEP_EMPLOYEE_RATE = 0.0050
INFOTEP_RATE = INFOTEP_EMPLOYER_RATE

AFP_SALARY_CAP = 464460.00
SFS_SALARY_CAP = 232230.00

ISR_ANNUAL_TABLE = [
    (0.00,        416220.00,   0.00, 0.00),
    (416220.01,   624329.00,   0.15, 0.00),
    (624329.01,   867123.00,   0.20, 31216.00),
    (867123.01,   float("inf"), 0.25, 79776.00),
]

ANNUAL_EDUCATION_DEDUCTION = 50000.00
MIN_SALARY = 23223.00
# ── SFS Dependientes Adicionales (Ley 87-01 / TSS / SISALRIL) ──
# Actualización TSS 5 de octubre 2026 (notificación de pago octubre 2026 en adelante):
#   - Per cápita base SFS: RD$ 1,938.18
#   - FONAMAT (Medicamentos Alto Costo): RD$ 32.24
#   - Total mensual aplicable: RD$ 1,970.42
# Períodos históricos (< 2026-10-01): RD$ 1,919.78
SFS_DEPENDENTS_ADDITIONAL_CAPITA_OCT2026 = 1938.18
SFS_DEPENDENTS_ADDITIONAL_FONAMAT_OCT2026 = 32.24
SFS_DEPENDENTS_ADDITIONAL_TOTAL_OCT2026 = 1970.42
SFS_DEPENDENTS_ADDITIONAL_HISTORICAL_RATE = 1919.78

DEPENDENTS_ADDITIONAL_RATE = SFS_DEPENDENTS_ADDITIONAL_TOTAL_OCT2026
DEFAULT_SFS_DEPENDENTS_ADDITIONAL_RATE = DEPENDENTS_ADDITIONAL_RATE

SFS_DEPENDENTS_ADDITIONAL_SCHEDULE = [
    {
        "effective_from": "2026-10-01",
        "effective_to": "",
        "capita_rate": SFS_DEPENDENTS_ADDITIONAL_CAPITA_OCT2026,
        "fonamat_rate": SFS_DEPENDENTS_ADDITIONAL_FONAMAT_OCT2026,
        "total_rate": SFS_DEPENDENTS_ADDITIONAL_TOTAL_OCT2026,
        "description": "Resolución TSS/SISALRIL Octubre 2026 (Cápita RD$ 1,938.18 + FONAMAT RD$ 32.24)",
    },
    {
        "effective_from": "2000-01-01",
        "effective_to": "2026-09-30",
        "capita_rate": SFS_DEPENDENTS_ADDITIONAL_HISTORICAL_RATE,
        "fonamat_rate": 0.0,
        "total_rate": SFS_DEPENDENTS_ADDITIONAL_HISTORICAL_RATE,
        "description": "Tarifa Histórica SFS Dependientes Adicionales (hasta Septiembre 2026)",
    },
]


def get_sfs_dependents_additional_rate_schedule(target_date: str = "") -> dict:
    """Retorna el desglose de tarifas oficial de dependientes adicionales para una fecha dada.

    Args:
        target_date: Fecha YYYY-MM-DD o vacía para la tarifa vigente actual.

    Returns:
        dict con {capita_rate, fonamat_rate, total_rate, effective_from, effective_to, description}
    """
    date_str = (target_date or "")[:10]
    if not date_str:
        return dict(SFS_DEPENDENTS_ADDITIONAL_SCHEDULE[0])

    for entry in SFS_DEPENDENTS_ADDITIONAL_SCHEDULE:
        eff_from = entry.get("effective_from", "")
        eff_to = entry.get("effective_to", "")
        if eff_from and date_str < eff_from:
            continue
        if eff_to and date_str > eff_to:
            continue
        return dict(entry)

    return dict(SFS_DEPENDENTS_ADDITIONAL_SCHEDULE[0])

DEFAULT_OVERTIME_RATE = 1.35
DEFAULT_WORKING_DAYS_PER_MONTH = 23.83
DEFAULT_WORKING_HOURS_PER_DAY = 8.0
DEFAULT_INFOTEP_THRESHOLD_MULTIPLIER = 5

DEFAULT_ACCOUNT_SALARIES_PAYABLE = "2.1.2.1.02"
DEFAULT_ACCOUNT_AFP_EMPLOYEE = "2.1.2.1.05"
DEFAULT_ACCOUNT_SFS_EMPLOYEE = "2.1.2.1.06"
DEFAULT_ACCOUNT_SFS_DEPENDENTS_ADDITIONAL = "2.1.2.1.07"
DEFAULT_ACCOUNT_ISR_EMPLOYEE = "2.1.2.1.08"
DEFAULT_ACCOUNT_AFP_EMPLOYER = "2.1.2.1.10"
DEFAULT_ACCOUNT_SFS_EMPLOYER = "2.1.2.1.09"
DEFAULT_ACCOUNT_SRL_EMPLOYER = "2.1.2.1.11"
DEFAULT_ACCOUNT_INFOTEP_EMPLOYER = "2.1.2.1.12"
DEFAULT_ACCOUNT_INFOTEP_EMPLOYEE = "2.1.2.1.12"
DEFAULT_ACCOUNT_OTHER_DEDUCTIONS = "2.1.2.1.13"
DEFAULT_COST_CENTER_ACCOUNTS = {
    "General":         "6.2.1.01",
    "Ventas":          "6.2.1.01.01",
    "Produccion":      "6.2.1.01.02",
    "Administrativa":  "6.2.1.01.03",
}
