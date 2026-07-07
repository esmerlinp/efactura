"""
PayrollService — Cálculo de nómina dominicana con ISR, TSS, prestaciones y asientos contables.

Basado en:
- Ley 16-92 (Código de Trabajo RD)
- Ley 87-01 (Seguridad Social)
- Tablas ISR DGII 2026 (escala anual para personas físicas)
- Norma 08-04 DGII sobre retenciones asalariados
"""

import calendar
from datetime import date, datetime, timedelta
from typing import Optional

# ═══════════════════════════════════════════════════════════════════════════
# TASAS DE SEGURIDAD SOCIAL (2026) — Valores por defecto
# Estos valores se usan como fallback si no hay configuración en Firestore.
# ═══════════════════════════════════════════════════════════════════════════
_AFP_EMPLOYEE_RATE = 0.0287   # 2.87% — Aporte del empleado a AFP
_AFP_EMPLOYER_RATE = 0.0710   # 7.10% — Aporte del empleador a AFP
_SFS_EMPLOYEE_RATE = 0.0304   # 3.04% — Aporte del empleado a SFS
_SFS_EMPLOYER_RATE = 0.0709   # 7.09% — Aporte del empleador a SFS
_SRL_EMPLOYER_RATE = 0.0120   # 1.20% — Seguro de Riesgo Laboral (empleador)
_INFOTEP_RATE = 0.0100        # 1.00% — INFOTEP (empleador; empleado solo si gana más de cierto tope)

_AFP_SALARY_CAP = 196750.00   # Tope máximo cotizable AFP (20 salarios mínimos aprox)
_SFS_SALARY_CAP = 98375.00    # Tope máximo cotizable SFS

_ISR_ANNUAL_TABLE = [
    (0.00,        416220.00,   0.00, 0.00),
    (416220.01,   624329.00,   0.15, 0.00),
    (624329.01,   867123.00,   0.20, 31216.00),
    (867123.01,   float("inf"), 0.25, 79775.00),
]

_ANNUAL_EDUCATION_DEDUCTION = 50000.00
_MIN_SALARY = 23223.00

# Compatibilidad hacia atrás — exponer como atributos de clase
AFP_EMPLOYEE_RATE = _AFP_EMPLOYEE_RATE
AFP_EMPLOYER_RATE = _AFP_EMPLOYER_RATE
SFS_EMPLOYEE_RATE = _SFS_EMPLOYEE_RATE
SFS_EMPLOYER_RATE = _SFS_EMPLOYER_RATE
SRL_EMPLOYER_RATE = _SRL_EMPLOYER_RATE
INFOTEP_RATE = _INFOTEP_RATE
AFP_SALARY_CAP = _AFP_SALARY_CAP
SFS_SALARY_CAP = _SFS_SALARY_CAP
ISR_ANNUAL_TABLE = _ISR_ANNUAL_TABLE
ANNUAL_EDUCATION_DEDUCTION = _ANNUAL_EDUCATION_DEDUCTION
MIN_SALARY = _MIN_SALARY
INFOTEP_EMPLOYEE_THRESHOLD = _MIN_SALARY * 5


class PayrollService:
    """Servicio de cálculo de nómina dominicana."""

    @staticmethod
    def get_rates(tax_rates: dict = None) -> dict:
        """Obtiene tasas desde dict de Firestore o usa valores por defecto."""
        if not tax_rates:
            tax_rates = {}
        return {
            "afp_employee_rate": tax_rates.get("afpEmployeeRate", _AFP_EMPLOYEE_RATE),
            "afp_employer_rate": tax_rates.get("afpEmployerRate", _AFP_EMPLOYER_RATE),
            "sfs_employee_rate": tax_rates.get("sfsEmployeeRate", _SFS_EMPLOYEE_RATE),
            "sfs_employer_rate": tax_rates.get("sfsEmployerRate", _SFS_EMPLOYER_RATE),
            "srl_employer_rate": tax_rates.get("srlEmployerRate", _SRL_EMPLOYER_RATE),
            "infotep_rate": tax_rates.get("infotepRate", _INFOTEP_RATE),
            "afp_salary_cap": tax_rates.get("afpSalaryCap", _AFP_SALARY_CAP),
            "sfs_salary_cap": tax_rates.get("sfsSalaryCap", _SFS_SALARY_CAP),
            "min_salary": tax_rates.get("minSalary", _MIN_SALARY),
            "education_deduction": tax_rates.get("educationDeduction", _ANNUAL_EDUCATION_DEDUCTION),
            "isr_table": tax_rates.get("isrAnnualTable", _ISR_ANNUAL_TABLE),
        }

    # ═══════════════════════════════════════════════════════════════════════
    # CÁLCULO DE NÓMINA INDIVIDUAL
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def calculate_payroll_line(
        cls,
        base_salary: float,
        overtime_hours: float = 0.0,
        overtime_rate: float = 1.35,
        commission: float = 0.0,
        bonus: float = 0.0,
        other_income: float = 0.0,
        other_deductions: float = 0.0,
        education_deduction: float = 0.0,
        period_type: str = "mensual",
        prorated_salary: float = None,
        tax_rates: dict = None,
    ) -> dict:
        """
        Calcula una línea de nómina completa.

        Args:
            base_salary: Salario base mensual bruto.
            overtime_hours: Horas extras trabajadas.
            overtime_rate: Multiplicador de hora extra (default 1.35).
            commission: Comisiones del período.
            bonus: Bonificación.
            other_income: Otros ingresos.
            other_deductions: Otros descuentos (préstamos, anticipos).
            education_deduction: Deducción mensual por educación (anual/12).
            period_type: "mensual" o "quincenal".
            prorated_salary: Salario ya prorrateado para el período (entrada a mitad, salida, cambio salarial).
                             Si es None, se calcula normalmente.
        """
        # ── 1. Ingresos ──────────────────────────────────────────────────
        if prorated_salary is not None:
            period_salary = prorated_salary
            period_factor = 24 if period_type == "quincenal" else 12
        elif period_type == "quincenal":
            period_salary = round(base_salary / 2, 2)
            period_factor = 24
        else:
            period_salary = base_salary
            period_factor = 12

        overtime_pay = cls._calculate_overtime(base_salary, overtime_hours, overtime_rate)
        gross_salary = period_salary
        total_income = round(period_salary + overtime_pay + commission + bonus + other_income, 2)

        # ── 2. Salario cotizable TSS (topado) ────────────────────────────
        r = cls.get_rates(tax_rates)
        afp_cap = r["afp_salary_cap"] / 2 if period_type == "quincenal" else r["afp_salary_cap"]
        sfs_cap = r["sfs_salary_cap"] / 2 if period_type == "quincenal" else r["sfs_salary_cap"]
        afp_cotizable = min(total_income, afp_cap)
        sfs_cotizable = min(total_income, sfs_cap)

        # ── 3. Descuentos al empleado ───────────────────────────────────
        afp_employee = round(afp_cotizable * r["afp_employee_rate"], 2)
        sfs_employee = round(sfs_cotizable * r["sfs_employee_rate"], 2)

        # INFOTEP empleado: aplica si total_income > 5x salario mínimo
        infotep_threshold = r["min_salary"] * 5
        if total_income > infotep_threshold:
            infotep_employee = round(total_income * r["infotep_rate"], 2)
        else:
            infotep_employee = 0.0

        # ISR: se calcula sobre renta neta anualizable con el factor correcto
        isr_monthly = cls._calculate_isr_monthly(
            total_income, afp_employee, sfs_employee, education_deduction, period_factor,
            tax_rates=r,
        )

        total_deductions = round(afp_employee + sfs_employee + infotep_employee + isr_monthly + other_deductions, 2)
        net_salary = round(total_income - total_deductions, 2)

        # ── 4. Aportes empleador ────────────────────────────────────────
        afp_employer = round(afp_cotizable * r["afp_employer_rate"], 2)
        sfs_employer = round(sfs_cotizable * r["sfs_employer_rate"], 2)
        srl_employer = round(sfs_cotizable * r["srl_employer_rate"], 2)
        infotep_employer = round(total_income * r["infotep_rate"], 2)
        total_employer = round(afp_employer + sfs_employer + srl_employer + infotep_employer, 2)

        return {
            "baseSalary": base_salary,
            "grossSalary": gross_salary,
            "overtimeHours": overtime_hours,
            "overtimePay": overtime_pay,
            "commission": commission,
            "bonus": bonus,
            "otherIncome": other_income,
            "totalIncome": total_income,
            "afpEmployee": afp_employee,
            "sfsEmployee": sfs_employee,
            "infotepEmployee": infotep_employee,
            "isrRetention": isr_monthly,
            "otherDeductions": other_deductions,
            "totalDeductions": total_deductions,
            "netSalary": net_salary,
            "afpEmployer": afp_employer,
            "sfsEmployer": sfs_employer,
            "srlEmployer": srl_employer,
            "infotepEmployer": infotep_employer,
            "totalEmployerContrib": total_employer,
        }

    @classmethod
    def _calculate_overtime(cls, base_salary: float, hours: float, rate: float) -> float:
        """Calcula pago de horas extras. Base: (salario / 23.83 días / 8 horas) * rate."""
        if hours <= 0 or base_salary <= 0:
            return 0.0
        hourly = base_salary / 23.83 / 8.0  # Días hábiles promedio mensual
        return round(hourly * rate * hours, 2)

    @classmethod
    def _calculate_isr_monthly(
        cls,
        monthly_income: float,
        afp_deduction: float,
        sfs_deduction: float,
        education_deduction: float = 0.0,
        period_factor: int = 12,
        tax_rates: dict = None,
    ) -> float:
        """
        Calcula ISR del período según tabla DGII para asalariados.

        Método: anualiza el ingreso usando el factor correcto según frecuencia
        (12 para mensual, 24 para quincenal), resta deducciones, aplica tabla
        progresiva anual, divide entre period_factor para obtener el ISR del período.

        Args:
            period_factor: 12 para mensual, 24 para quincenal, 52 para semanal.
        """
        r = cls.get_rates(tax_rates)
        annual_gross = monthly_income * period_factor
        annual_afp = afp_deduction * period_factor
        annual_sfs = sfs_deduction * period_factor
        annual_edu = min(education_deduction * period_factor, r["education_deduction"])

        # Renta neta anual
        annual_taxable = max(0.0, annual_gross - annual_afp - annual_sfs - annual_edu)

        # Aplicar tabla ISR
        annual_isr = 0.0
        for floor, ceiling, rate, fixed in r["isr_table"]:
            if annual_taxable <= floor:
                break
            bracket_top = min(annual_taxable, ceiling)
            if bracket_top > floor:
                annual_isr = round((bracket_top - floor) * rate + fixed, 2)
                break

        return round(annual_isr / period_factor, 2)

    # ═══════════════════════════════════════════════════════════════════════
    # PRESTACIONES LABORALES (Ley 16-92)
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def calculate_christmas_bonus(cls, base_salary: float, months_worked: int = 12) -> float:
        """
        Regalía pascual (salario de Navidad).
        = 1/12 del salario anual, proporcional a meses trabajados.
        Se paga antes del 20 de diciembre.
        """
        if months_worked >= 12:
            return round(base_salary, 2)
        return round((base_salary / 12.0) * months_worked, 2)

    @classmethod
    def calculate_vacation_days(cls, hire_date_str: str, today: Optional[date] = None) -> int:
        """
        Calcula días de vacaciones acumulados según Ley 16-92.

        - 1 a 5 años: 14 días hábiles por año
        - Más de 5 años: 18 días hábiles por año
        - Proporcional si no ha cumplido el año

        Returns:
            Días hábiles acumulados disponibles.
        """
        if today is None:
            today = date.today()

        try:
            hire_date = datetime.strptime(hire_date_str[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return 0

        # Años completos trabajados
        years = today.year - hire_date.year
        if today.month < hire_date.month or (today.month == hire_date.month and today.day < hire_date.day):
            years -= 1

        if years < 0:
            years = 0

        # Días proporcionales del año en curso
        if years < 1:
            days_since_hire = (today - hire_date).days
            return max(0, round((days_since_hire / 365.0) * 14))

        # Base: 14 o 18 días por año según antigüedad
        days_per_year = 18 if years >= 5 else 14
        total = years * days_per_year

        # Días proporcionales del año actual
        last_anniversary = hire_date.replace(year=today.year)
        if last_anniversary > today:
            last_anniversary = last_anniversary.replace(year=today.year - 1)
        days_proportional = max(0, round(((today - last_anniversary).days / 365.0) * days_per_year))
        total += days_proportional

        return total

    @classmethod
    def calculate_severance(cls, base_salary: float, hire_date_str: str, termination_date_str: str = "") -> dict:
        """
        Calcula prestaciones por cesantía/desahucio según Ley 16-92.

        - Preaviso: Art. 76 (7-28 días de salario según antigüedad)
        - Cesantía: Art. 80 (6-21 días por año trabajado, máx 10 años en base legal base)

        Returns:
            Dict con preaviso, cesantía, total, y vacaciones pendientes.
        """
        today = date.today()
        if termination_date_str:
            try:
                today = datetime.strptime(termination_date_str[:10], "%Y-%m-%d").date()
            except ValueError:
                pass

        try:
            hire_date = datetime.strptime(hire_date_str[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return {"preaviso": 0.0, "cesantia": 0.0, "vacaciones_pendientes": 0.0, "total": 0.0}

        months = (today.year - hire_date.year) * 12 + (today.month - hire_date.month)
        if today.day < hire_date.day:
            months -= 1
        years = max(0, months // 12)
        daily_salary = base_salary / 23.83

        # Preaviso (Art. 76)
        if months < 3:
            preaviso_days = 0
        elif months < 6:
            preaviso_days = 7
        elif months < 12:
            preaviso_days = 14
        else:
            preaviso_days = 28

        # Cesantía (Art. 80)
        # 6 días por cada año (o fracción > 6 meses), topado a los años de la escala
        full_years = years
        remaining_months = months - (full_years * 12)
        if remaining_months >= 6:
            full_years += 1
        cesantia_days = min(full_years, 10) * 21 + (max(0, full_years - 10) * 0)
        # Simplificado: 21 días por año, máx 10 años
        cesantia_days = min(years * 21, 10 * 21)
        if cesantia_days == 0 and months >= 3:
            cesantia_days = 6  # Fracción mínima

        vacaciones_pendientes = cls.calculate_vacation_days(hire_date_str, today)
        vacaciones_pago = daily_salary * vacaciones_pendientes

        preaviso_amount = round(daily_salary * preaviso_days, 2)
        cesantia_amount = round(daily_salary * cesantia_days, 2)
        total = round(preaviso_amount + cesantia_amount + vacaciones_pago, 2)

        return {
            "preaviso": preaviso_amount,
            "preaviso_days": preaviso_days,
            "cesantia": cesantia_amount,
            "cesantia_days": cesantia_days,
            "vacaciones_pendientes": vacaciones_pago,
            "vacaciones_days": vacaciones_pendientes,
            "total": total,
        }

    @classmethod
    def prorate_salary(
        cls,
        monthly_salary: float,
        period_start: str,
        period_end: str,
        hire_date: str = "",
        termination_date: str = "",
        salary_history: list = None,
    ) -> float | None:
        try:
            ps = datetime.strptime(period_start, "%Y-%m-%d").date()
            pe = datetime.strptime(period_end, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return monthly_salary
        period_days = (pe - ps).days + 1
        if period_days <= 0:
            return 0.0
        emp_start = ps
        emp_end = pe
        if hire_date:
            try:
                hd = datetime.strptime(hire_date[:10], "%Y-%m-%d").date()
                emp_start = max(ps, hd)
            except (ValueError, TypeError):
                pass
        if termination_date:
            try:
                td = datetime.strptime(termination_date[:10], "%Y-%m-%d").date()
                emp_end = min(pe, td)
            except (ValueError, TypeError):
                pass
        if emp_start > emp_end:
            return 0.0
        emp_days = (emp_end - emp_start).days + 1

        # Si el empleado trabajó el período completo y no hay cambios salariales,
        # retorna None para que calculate_payroll_line use la fórmula estándar
        if emp_start == ps and emp_end == pe:
            has_changes = False
            if salary_history:
                for h in salary_history:
                    try:
                        eff = datetime.strptime(h.get("effectiveDate", ""), "%Y-%m-%d").date()
                        if ps <= eff <= pe:
                            has_changes = True
                            break
                    except (ValueError, TypeError):
                        continue
            if not has_changes:
                return None

        daily_rate = monthly_salary / 23.83

        if salary_history:
            total = 0.0
            for h in sorted(salary_history, key=lambda x: x.get("effectiveDate", "")):
                try:
                    eff = datetime.strptime(h["effectiveDate"], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    continue
                end_date_str = h.get("endDate", "")
                try:
                    end_d = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else pe
                except (ValueError, TypeError):
                    end_d = pe
                seg_start = max(eff, emp_start)
                seg_end = min(end_d, emp_end)
                if seg_start <= seg_end:
                    seg_days = (seg_end - seg_start).days + 1
                    seg_amount = h.get("amount", monthly_salary)
                    seg_daily = seg_amount / 23.83
                    total += round(seg_daily * seg_days, 2)
            if total > 0:
                return round(total, 2)

        return round(daily_rate * emp_days, 2)

    @classmethod
    def calculate_business_days(cls, start_date_str: str, end_date_str: str) -> int:
        """Cuenta días hábiles (lunes-viernes) entre dos fechas."""
        try:
            start = datetime.strptime(start_date_str[:10], "%Y-%m-%d").date()
            end = datetime.strptime(end_date_str[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return 0

        if start > end:
            return 0

        days = 0
        current = start
        while current <= end:
            if current.weekday() < 5:  # L-V
                days += 1
            current += timedelta(days=1)
        return days

    # ═══════════════════════════════════════════════════════════════════════
    # ASIENTO CONTABLE DE NÓMINA
    # ═══════════════════════════════════════════════════════════════════════

    DEFAULT_COST_CENTER_ACCOUNTS = {
        "General": "6.2.1.01",
        "Ventas": "6.2.1.01.01",
        "Produccion": "6.2.1.01.02",
        "Administrativa": "6.2.1.01.03",
    }

    @classmethod
    def build_payroll_accounting_lines(cls, payroll_period: dict, employees: dict = None) -> list:
        lines = []
        period_label = payroll_period.get("periodKey", "")
        plines = payroll_period.get("lines", [])
        employees = employees or {}

        total_gross = 0.0
        total_net = 0.0
        total_afp_emp = 0.0
        total_sfs_emp = 0.0
        total_isr = 0.0
        total_afp_empl = 0.0
        total_sfs_empl = 0.0
        total_srl_empl = 0.0
        total_infotep = 0.0

        by_cc = {}
        for pl in plines:
            total_net += pl.get("netSalary", 0)
            total_afp_emp += pl.get("afpEmployee", 0)
            total_sfs_emp += pl.get("sfsEmployee", 0)
            total_isr += pl.get("isrRetention", 0)
            total_afp_empl += pl.get("afpEmployer", 0)
            total_sfs_empl += pl.get("sfsEmployer", 0)
            total_srl_empl += pl.get("srlEmployer", 0)
            total_infotep += pl.get("infotepEmployer", 0)

            emp_id = pl.get("employeeId", "")
            emp = employees.get(emp_id, {})
            cc = emp.get("costCenter", "") or emp.get("area", "") or emp.get("department", "") or "General"
            if cc not in by_cc:
                by_cc[cc] = {"gross": 0.0, "employer": 0.0}
            by_cc[cc]["gross"] += pl.get("totalIncome", 0)
            by_cc[cc]["employer"] += pl.get("totalEmployerContrib", 0)
            total_gross += pl.get("totalIncome", 0)

        total_employer = total_afp_empl + total_sfs_empl + total_srl_empl + total_infotep

        # DEBE: Líneas de gasto por centro de costo
        for cc, totals in by_cc.items():
            cc_gasto = round(totals["gross"] + totals["employer"], 2)
            acct_code = cls.DEFAULT_COST_CENTER_ACCOUNTS.get(cc, "6.2.1.01")
            lines.append({
                "accountCode": acct_code,
                "accountName": f"Sueldos y salarios - {cc}",
                "debit": cc_gasto,
                "credit": 0.00,
                "description": f"Nómina período {period_label} - {cc}",
            })

        # HABER: Salarios por pagar (neto)
        if total_net > 0:
            lines.append({
                "accountCode": "2.1.2.1.02",
                "accountName": "Salarios por pagar",
                "debit": 0.00, "credit": round(total_net, 2),
                "description": f"Salario neto período {period_label}",
            })
        if total_afp_emp > 0:
            lines.append({
                "accountCode": "2.1.2.1.05",
                "accountName": "Retenciones empleado AFP",
                "debit": 0.00, "credit": round(total_afp_emp, 2),
                "description": f"AFP empleado {period_label}",
            })
        if total_sfs_emp > 0:
            lines.append({
                "accountCode": "2.1.2.1.06",
                "accountName": "Retenciones a empleado SFS",
                "debit": 0.00, "credit": round(total_sfs_emp, 2),
                "description": f"SFS empleado {period_label}",
            })
        if total_isr > 0:
            lines.append({
                "accountCode": "2.1.2.1.08",
                "accountName": "Retención ISR empleados",
                "debit": 0.00, "credit": round(total_isr, 2),
                "description": f"ISR empleados {period_label}",
            })
        if total_afp_empl > 0:
            lines.append({
                "accountCode": "2.1.2.1.10",
                "accountName": "Acumulaciones AFP",
                "debit": 0.00, "credit": round(total_afp_empl, 2),
                "description": f"AFP empleador {period_label}",
            })
        if total_sfs_empl > 0:
            lines.append({
                "accountCode": "2.1.2.1.09",
                "accountName": "Acumulaciones SFS",
                "debit": 0.00, "credit": round(total_sfs_empl, 2),
                "description": f"SFS empleador {period_label}",
            })
        if total_srl_empl > 0:
            lines.append({
                "accountCode": "2.1.2.1.11",
                "accountName": "Acumulaciones SRL",
                "debit": 0.00, "credit": round(total_srl_empl, 2),
                "description": f"SRL empleador {period_label}",
            })
        total_infotep_line = total_infotep
        if total_infotep_line > 0:
            lines.append({
                "accountCode": "2.1.2.1.12",
                "accountName": "Acumulaciones INFOTEP",
                "debit": 0.00, "credit": round(total_infotep_line, 2),
                "description": f"INFOTEP {period_label}",
            })

        return lines

    # ═══════════════════════════════════════════════════════════════════════
    # EXPORTACIÓN TSS
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def generate_tss_csv(cls, payroll_period: dict, employees: list) -> str:
        """
        Genera CSV en formato TSS (Tesorería de la Seguridad Social).

        Columnas requeridas por TSS:
        Cédula, Nombre, Salario Cotizable, AFP Empleado, SFS Empleado,
        AFP Empleador, SFS Empleador, SRL, INFOTEP, Total
        """
        import csv, io

        output = io.StringIO()
        writer = csv.writer(output)

        # Header TSS
        writer.writerow([
            "Cedula", "Nombre", "Salario_Cotizable", "AFP_Empleado",
            "SFS_Empleado", "AFP_Empleador", "SFS_Empleador",
            "SRL", "INFOTEP", "Total_Aportes"
        ])

        period_label = payroll_period.get("periodKey", "")
        lines = payroll_period.get("lines", [])
        emp_map = {e.get("id", ""): e for e in employees}

        for pl in lines:
            emp = emp_map.get(pl.get("employeeId", ""), {})
            writer.writerow([
                pl.get("cedula", ""),
                pl.get("employeeName", ""),
                f"{pl.get('totalIncome', 0):.2f}",
                f"{pl.get('afpEmployee', 0):.2f}",
                f"{pl.get('sfsEmployee', 0):.2f}",
                f"{pl.get('afpEmployer', 0):.2f}",
                f"{pl.get('sfsEmployer', 0):.2f}",
                f"{pl.get('srlEmployer', 0):.2f}",
                f"{pl.get('infotepEmployer', 0):.2f}",
                f"{pl.get('afpEmployee',0) + pl.get('sfsEmployee',0) + pl.get('afpEmployer',0) + pl.get('sfsEmployer',0) + pl.get('srlEmployer',0) + pl.get('infotepEmployer',0):.2f}",
            ])

        return output.getvalue()

    # ═══════════════════════════════════════════════════════════════════════
    # AUTODETERMINACIÓN TSS — Formato oficial Tesorería de la Seguridad Social
    # ═══════════════════════════════════════════════════════════════════════

    # Mapeo de tipos de identificación a códigos TSS
    _TIPO_DOC_MAP = {"cedula": "1", "rnc": "2", "pasaporte": "3", "": "1"}

    # Meses en español para el período
    _MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
              "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

    @classmethod
    def generate_tss_autodeterminacion(cls, payroll_period: dict, employees: list,
                                        employer_rnc: str = "") -> dict:
        """
        Genera archivo de Autodeterminación TSS en formato OFICIAL SUIRPLUS v6.0.

        Formato: archivo de texto de ancho fijo con 3 tipos de registro:
          E = Encabezado (20 caracteres)
          D = Detalle (366 caracteres por empleado)
          S = Sumario (7 caracteres)

        Especificación: Instructivo Construcción Archivos Autodeterminación y
        Novedades v6.0 — TSS, Junio 2025.

        Args:
            payroll_period: Dict del período de nómina.
            employees: Lista de empleados con datos completos.
            employer_rnc: RNC o Cédula del empleador (sin guiones).

        Returns:
            Dict con {content, filename, periodo, periodo_tss, total_empleados, resumen}.
        """
        from datetime import datetime

        period_key = payroll_period.get("periodKey", "")
        year = payroll_period.get("year", datetime.now().year)
        month = payroll_period.get("month", datetime.now().month)
        periodo_mmaaaa = f"{month:02d}{year}"
        periodo_label = f"{cls._MESES[month]}_{year}"

        lines = payroll_period.get("lines", [])
        emp_map = {e.get("id", ""): e for e in employees}

        # Limpiar RNC: solo dígitos, quitar guiones
        rnc = "".join(c for c in (employer_rnc or "") if c.isdigit())
        if len(rnc) < 11:
            rnc = rnc.rjust(11)

        output_lines = []

        # ═══════════════════════════════════════════════════════════════
        # ENCABEZADO — 20 caracteres
        # Pos: 1(1) E, 2-3(2) AM, 4-14(11) RNC, 15-20(6) MMAAAA
        # ═══════════════════════════════════════════════════════════════
        header = f"EAM{rnc[-11:].rjust(11)}{periodo_mmaaaa}"
        output_lines.append(header)

        empleados_contados = 0

        for pl in lines:
            emp = emp_map.get(pl.get("employeeId", ""), {})
            if not emp:
                continue

            empleados_contados += 1

            # ── Datos del empleado ──

            # Clave nómina (3, justificada derecha)
            tss_key = str(emp.get("tssKey", "") or "").strip()[:3]
            clave = tss_key.rjust(3)

            # Tipo documento (1)
            id_type = (emp.get("idType", "") or "cedula").lower()
            tipo_doc = "C" if id_type == "cedula" else ("P" if id_type == "pasaporte" else "N")

            # Documento (25, justificado izquierda, sin guiones)
            doc = "".join(c for c in (emp.get("cedula", "") or emp.get("idNumber", "") or "") if c.isalnum())
            documento = doc.ljust(25)[:25]

            # Nombres (50, justificado izquierda)
            nombres_raw = f"{emp.get('firstName', '')} {emp.get('middleName', '')}".strip()
            nombres = nombres_raw.ljust(50)[:50]

            # 1er Apellido (40)
            apellido1 = (emp.get("firstLastName", "") or emp.get("lastName", "") or "").strip()
            apellido1 = apellido1.ljust(40)[:40]

            # 2do Apellido (40)
            apellido2 = (emp.get("secondLastName", "") or "").strip()
            apellido2 = apellido2.ljust(40)[:40]

            # Sexo (1)
            gender = (emp.get("gender", "") or "").lower()
            sexo = "M" if gender in ("masculino", "male", "m") else ("F" if gender else " ")

            # Fecha nacimiento (8, DDMMAAAA)
            birth = (emp.get("birthDate", "") or "").strip()
            fecha_nac = ""
            if birth:
                try:
                    bd = datetime.strptime(birth[:10], "%Y-%m-%d")
                    fecha_nac = bd.strftime("%d%m%Y")
                except ValueError:
                    fecha_nac = ""
            fecha_nac = fecha_nac.ljust(8)[:8]

            # ── Salarios ──
            gross_salary = pl.get("grossSalary", 0) or pl.get("baseSalary", 0) or 0
            total_income = pl.get("totalIncome", 0) or 0
            afp_cap = emp.get("afpSalaryCap", 0) or _AFP_SALARY_CAP
            salario_ss = min(gross_salary, afp_cap)

            # Salario_SS (16, ceros izq con 2 decimales)
            salario_ss_str = f"{salario_ss:016.2f}"[:16]

            # Aporte voluntario (16, ceros)
            aporte_vol = "0000000000000.00"

            # Salario_ISR (16): solo si es diferente de Salario_SS
            salario_isr = total_income
            salario_isr_str = "0000000000000.00" if abs(salario_isr - salario_ss) < 0.01 else f"{salario_isr:016.2f}"[:16]

            # Otras remuneraciones (16): comisiones + bonos + otros ingresos
            otras_rem = (pl.get("commission", 0) or 0) + (pl.get("bonus", 0) or 0) + (pl.get("otherIncome", 0) or 0)
            otras_rem_str = f"{otras_rem:016.2f}"[:16]

            # RNC agente retención (11, justificado derecha)
            agente_ret = "".rjust(11)

            # Remun. otros empleadores (16, ceros)
            rem_otros = "0000000000000.00"

            # Ingresos exentos ISR (16) — siempre en ceros (se desglosan abajo)
            ingresos_exentos = "0000000000000.00"

            # Saldo a favor (16, ceros)
            saldo_favor = "0000000000000.00"

            # Salario INFOTEP (16): solo si es diferente de Salario_SS
            salario_infotep = total_income
            salario_infotep_str = "0000000000000.00" if abs(salario_infotep - salario_ss) < 0.01 else f"{salario_infotep:016.2f}"[:16]

            # Tipo ingreso (4): default 0001 (Normal)
            tipo_ingreso = "0001"

            # ── Ingresos exentos desglosados (18 chars c/u: código 2 + monto 16) ──
            # 01 = Regalía Pascual
            regalia = pl.get("christmasBonus", 0) or 0
            regalia_str = f"01{regalia:016.2f}"[:18]

            # 02 = Preaviso, Cesantía, Viáticos e Indemnizaciones
            preaviso_cesantia = 0.0
            pc_str = f"02{preaviso_cesantia:016.2f}"[:18]

            # 03 = Retención Pensión Alimenticia
            pension = pl.get("pensionAlimenticia", 0) or 0
            pension_str = f"03{pension:016.2f}"[:18]

            # ═══════════════════════════════════════════════════════════
            # DETALLE — 366 caracteres
            # ═══════════════════════════════════════════════════════════
            detalle = (
                "D" + clave + tipo_doc + documento + nombres + apellido1 +
                apellido2 + sexo + fecha_nac + salario_ss_str + aporte_vol +
                salario_isr_str + otras_rem_str + agente_ret + rem_otros +
                ingresos_exentos + saldo_favor + salario_infotep_str +
                tipo_ingreso + regalia_str + pc_str + pension_str
            )
            # Verificar longitud exacta
            detalle = detalle.ljust(366)[:366]
            output_lines.append(detalle)

        # ═══════════════════════════════════════════════════════════════
        # SUMARIO — 7 caracteres
        # Pos: 1(1) S, 2-7(6) total registros (E + D's + S)
        # ═══════════════════════════════════════════════════════════════
        total_registros = 1 + empleados_contados + 1  # header + details + trailer
        trailer = f"S{total_registros:06d}"
        output_lines.append(trailer)

        content = "\n".join(output_lines)

        # Clean RNC for filename (just numbers, no spaces)
        rnc_clean = "".join(c for c in (employer_rnc or "000000000") if c.isdigit())
        filename = f"AM_{rnc_clean}_{periodo_mmaaaa}.txt"

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

    @classmethod
    def generate_tss_autodeterminacion_xls(cls, payroll_period: dict, employees: list,
                                            employer_rnc: str = "",
                                            tipo_archivo: str = "AM") -> dict:
        """
        Genera el archivo Excel (.xlsx) poblado con la plantilla oficial de
        Autodeterminación TSS de la Tesorería de la Seguridad Social RD.

        Columnas exactas de la plantilla oficial (21 columnas B-V, col A vacía):
          B: Clave Nómina        C: Tipo Doc.           D: Número Documento
          E: Nombres             F: 1er. Apellido       G: 2do. Apellido
          H: Sexo                I: Fecha Nacimiento
          J: Salario Cotizable   K: Aporte Voluntario
          L: Salario ISR         M: Tipo Ingreso         N: Otras Remuneraciones
          O: RNC/Céd. Agente Ret P: Remun. Otros Agentes Q: Remuneración del período
          R: Saldo a favor       S: Regalía Pascual      T: Preaviso/Cesantía/Indemniz.
          U: Retención Pensión   V: Salario INFOTEP

        Args:
            payroll_period: Dict del período de nómina.
            employees: Lista de empleados con datos completos.
            employer_rnc: RNC o Cédula del empleador.
            tipo_archivo: "AM" (Modificación) o "AR" (Reemplazo).

        Returns:
            Dict con {content (bytes), filename, periodo, total_empleados, resumen}.
        """
        import io
        from datetime import datetime
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = "Autodeterminación"

        period_key = payroll_period.get("periodKey", "")
        year = payroll_period.get("year", datetime.now().year)
        month = payroll_period.get("month", datetime.now().month)
        periodo_mmaaaa = f"{month:02d}{year}"
        periodo_label = f"{cls._MESES[month]}_{year}"

        lines = payroll_period.get("lines", [])
        emp_map = {e.get("id", ""): e for e in employees}

        # ── Estilos ──
        bold_font = Font(bold=True, size=10)
        title_font = Font(bold=True, size=12)
        header_font = Font(bold=True, size=9)
        header_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
        section_fill = PatternFill(start_color="B4C6E7", end_color="B4C6E7", fill_type="solid")
        thin_border = Border(
            left=Side(style="thin"), right=Side(style="thin"),
            top=Side(style="thin"), bottom=Side(style="thin"),
        )
        center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

        # ── Metadata rows ──
        ws.merge_cells("B1:V1")
        ws["B1"] = "Plantilla de Archivo AutoDeterminación"
        ws["B1"].font = title_font

        ws["B2"] = "Tipo de Archivo:"
        ws["B2"].font = bold_font
        ws["C2"] = tipo_archivo

        ws["B3"] = "RNC o Cédula:"
        ws["B3"].font = bold_font
        ws["C3"] = employer_rnc

        ws["B4"] = "Período:"
        ws["B4"].font = bold_font
        ws["C4"] = periodo_mmaaaa

        ws["B5"] = "# de Empleados:"
        ws["B5"].font = bold_font

        # ── Section headers (row 7) ──
        section_row = 7
        ws.merge_cells(f"B{section_row}:I{section_row}")
        ws[f"B{section_row}"] = "TRABAJADORES"
        ws[f"B{section_row}"].font = Font(bold=True, size=10)
        ws[f"B{section_row}"].fill = section_fill
        ws[f"B{section_row}"].alignment = center_align

        ws.merge_cells(f"J{section_row}:K{section_row}")
        ws[f"J{section_row}"] = "SDSS"
        ws[f"J{section_row}"].font = Font(bold=True, size=10)
        ws[f"J{section_row}"].fill = section_fill
        ws[f"J{section_row}"].alignment = center_align

        ws.merge_cells(f"L{section_row}:T{section_row}")
        ws[f"L{section_row}"] = "DGII"
        ws[f"L{section_row}"].font = Font(bold=True, size=10)
        ws[f"L{section_row}"].fill = section_fill
        ws[f"L{section_row}"].alignment = center_align

        ws.merge_cells(f"U{section_row}:V{section_row}")
        ws[f"U{section_row}"] = "INFOTEP"
        ws[f"U{section_row}"].font = Font(bold=True, size=10)
        ws[f"U{section_row}"].fill = section_fill
        ws[f"U{section_row}"].alignment = center_align

        # ── Column headers (row 8-9, 2-line headers) ──
        headers_r1 = [
            "", "Clave Nómina", "Tipo Doc.", "Número Documento",
            "Nombres", "1er. Apellido", "2do. Apellido", "Sexo",
            "Fecha Nacimiento", "Salario Cotizable", "Aporte Voluntario",
            "Salario ISR", "Tipo Ingreso", "Otras Remuneraciones",
            "RNC/Céd. Agente Ret", "Remun. Otros Agentes",
            "Remuneración del período", "Saldo a favor (Saldo 13)",
            "Regalía Pascual", "Preaviso, Cesantía, Viático e Indemnizaciones",
            "Retención Pensión Alimenticia", "Salario INFOTEP",
        ]

        header_row = 8
        for col_idx, h in enumerate(headers_r1):
            cell = ws.cell(row=header_row, column=col_idx + 1, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.border = thin_border
            cell.alignment = center_align

        # ── Widths ──
        widths = [3, 12, 10, 16, 18, 16, 16, 6, 14, 14, 14,
                  14, 12, 16, 18, 16, 16, 14, 14, 22, 16, 14]
        for i, w in enumerate(widths):
            ws.column_dimensions[get_column_letter(i + 1)].width = w

        # ── Data rows ──
        data_start = 9
        total_afp_emp = 0.0
        total_sfs_emp = 0.0
        total_afp_empl = 0.0
        total_sfs_empl = 0.0
        total_srl = 0.0
        total_infotep = 0.0
        emp_count = 0

        for pl in lines:
            emp = emp_map.get(pl.get("employeeId", ""), {})
            if not emp:
                continue

            emp_count += 1
            row = data_start + emp_count

            # Tipo doc
            id_type = emp.get("idType", "cedula") or "cedula"
            tipo_doc = "C" if id_type == "cedula" else ("P" if id_type == "pasaporte" else "N")

            # Sexo
            gender = (emp.get("gender", "") or "").lower()
            sexo = "M" if gender in ("masculino", "male", "m") else ("F" if gender else "")

            # Fecha nacimiento
            birth = (emp.get("birthDate", "") or "").strip()
            if birth:
                try:
                    bd = datetime.strptime(birth[:10], "%Y-%m-%d")
                    birth = bd.strftime("%d/%m/%Y")
                except ValueError:
                    pass

            # Nombres
            nombres = " ".join(p for p in [
                emp.get("firstName", ""), emp.get("middleName", "")
            ] if p).strip()

            total_income = pl.get("totalIncome", 0)
            afp_cap = emp.get("afpSalaryCap", 0) or _AFP_SALARY_CAP
            sfs_cap = emp.get("sfsSalaryCap", 0) or _SFS_SALARY_CAP
            salario_cotizable = min(total_income, afp_cap)

            # Aportes individuales
            afp_emp_val = pl.get("afpEmployee", 0)
            sfs_emp_val = pl.get("sfsEmployee", 0)
            afp_empl_val = pl.get("afpEmployer", 0)
            sfs_empl_val = pl.get("sfsEmployer", 0)
            srl_val = pl.get("srlEmployer", 0)
            infotep_val = pl.get("infotepEmployer", 0)

            # Otras remuneraciones = comisiones + bonos + otros ingresos
            otras_rem = (pl.get("commission", 0) + pl.get("bonus", 0) +
                        pl.get("otherIncome", 0))

            row_data = [
                "",  # A: empty
                emp.get("tssKey", ""),              # B: Clave Nómina
                tipo_doc,                            # C: Tipo Doc.
                emp.get("cedula", "") or emp.get("idNumber", ""),  # D: Documento
                nombres,                             # E: Nombres
                emp.get("firstLastName", "") or emp.get("lastName", ""),  # F: 1er Apellido
                emp.get("secondLastName", ""),       # G: 2do Apellido
                sexo,                                # H: Sexo
                birth,                               # I: Fecha Nacimiento
                salario_cotizable,                   # J: Salario Cotizable
                0.0,                                 # K: Aporte Voluntario
                total_income,                        # L: Salario ISR
                "01",                                # M: Tipo Ingreso (01=Normal)
                otras_rem,                           # N: Otras Remuneraciones
                "",                                  # O: RNC/Céd. Agente Ret
                0.0,                                 # P: Remun. Otros Agentes
                total_income,                        # Q: Remuneración del período
                0.0,                                 # R: Saldo a favor
                0.0,                                 # S: Regalía Pascual
                0.0,                                 # T: Preaviso/Cesantía/Indemniz.
                0.0,                                 # U: Retención Pensión Alimenticia
                total_income,                        # V: Salario INFOTEP
            ]

            for col_idx, val in enumerate(row_data):
                cell = ws.cell(row=row, column=col_idx + 1, value=val)
                cell.border = thin_border
                if isinstance(val, float):
                    cell.number_format = '#,##0.00'

            total_afp_emp += afp_emp_val
            total_sfs_emp += sfs_emp_val
            total_afp_empl += afp_empl_val
            total_sfs_empl += sfs_empl_val
            total_srl += srl_val
            total_infotep += infotep_val

        # Actualizar conteo
        ws["C5"] = emp_count

        # ── Save to bytes ──
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        filename = f"TSS_Autodeterminacion_{periodo_label.replace(' ', '_')}.xlsx"

        return {
            "content": output.getvalue(),
            "filename": filename,
            "periodo": periodo_label,
            "periodo_tss": periodo_mmaaaa,
            "total_empleados": emp_count,
            "resumen": {
                "afp_empleado": round(total_afp_emp, 2),
                "sfs_empleado": round(total_sfs_emp, 2),
                "afp_empleador": round(total_afp_empl, 2),
                "sfs_empleador": round(total_sfs_empl, 2),
                "srl": round(total_srl, 2),
                "infotep": round(total_infotep, 2),
                "total": round(total_afp_emp + total_sfs_emp + total_afp_empl +
                              total_sfs_empl + total_srl + total_infotep, 2),
            },
        }

    @classmethod
    def _split_name(cls, emp: dict) -> dict:
        """Separa nombres y apellidos para el formato TSS."""
        primer_nombre = (emp.get("firstName", "") or "").strip()
        segundo_nombre = (emp.get("middleName", "") or "").strip()
        primer_apellido = (emp.get("firstLastName", "") or emp.get("lastName", "") or "").strip()
        segundo_apellido = (emp.get("secondLastName", "") or "").strip()

        # Fallback: si no hay nombres separados, intentar separar fullName
        if not primer_nombre and not primer_apellido:
            full = (emp.get("fullName", "") or "").strip()
            parts = full.split()
            if len(parts) >= 2:
                primer_nombre = parts[0]
                primer_apellido = parts[-1]
                if len(parts) >= 3:
                    segundo_nombre = parts[1] if len(parts) > 2 else ""
                    if len(parts) >= 4:
                        segundo_apellido = parts[-2]

        return {
            "primer_nombre": primer_nombre,
            "segundo_nombre": segundo_nombre,
            "primer_apellido": primer_apellido,
            "segundo_apellido": segundo_apellido,
        }

    @classmethod
    def _calcular_estado_tss(cls, hire_date_str: str, termination_date_str: str,
                              year: int, month: int) -> str:
        """
        Determina el estado TSS del empleado para el período:
          I = Ingreso (fecha de entrada dentro del mes)
          P = Permanencia (activo, entró antes del mes)
          E = Egreso (fecha de salida dentro del mes)
        """
        from datetime import datetime

        # Primer día del período
        try:
            periodo_inicio = datetime(year, month, 1).date()
            if month == 12:
                periodo_fin = datetime(year + 1, 1, 1).date()
            else:
                periodo_fin = datetime(year, month + 1, 1).date()
        except (ValueError, TypeError):
            return "P"

        try:
            if hire_date_str:
                hd = datetime.strptime(hire_date_str[:10], "%Y-%m-%d").date()
                # Si entró en este mes, es Ingreso
                if periodo_inicio <= hd < periodo_fin:
                    return "I"

            if termination_date_str:
                td = datetime.strptime(termination_date_str[:10], "%Y-%m-%d").date()
                # Si salió en este mes, es Egreso
                if periodo_inicio <= td < periodo_fin:
                    return "E"
        except (ValueError, TypeError):
            pass

        return "P"
