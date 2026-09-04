"""Cálculos reutilizables para reportes proyectados de nómina."""

from app.services.payroll_service import PayrollService
from app.services.liquidacion_service import LiquidacionService
from app.utils.hr_utils import is_active_equivalent


class PayrollProjectionService:
    """Genera proyecciones sin persistir períodos ni modificar empleados."""

    @staticmethod
    def filter_employees(employees, employee_id="", department="", area="", group_id="",
                         status="", include_inactive=False):
        result = []
        for employee in employees or []:
            if status and employee.get("status", "") != status:
                continue
            if not status and not include_inactive and not is_active_equivalent(employee.get("status", "")):
                continue
            if employee_id and employee.get("id") != employee_id:
                continue
            if department and employee.get("department", employee.get("area", "")) != department:
                continue
            if area and employee.get("area", "") != area:
                continue
            if group_id and employee.get("payrollGroupId", employee.get("groupId", "")) != group_id:
                continue
            result.append(employee)
        return result

    @classmethod
    def project_payroll(cls, employees, year, tax_rates=None, **filters):
        selected = cls.filter_employees(employees, **filters)
        months = []
        detail = []
        for month in range(1, 13):
            rows = []
            for employee in selected:
                base = float(employee.get("baseSalary", employee.get("salary", 0)) or 0)
                if base <= 0:
                    continue
                line = PayrollService.calculate_payroll_line(base_salary=base, tax_rates=tax_rates)
                row = dict(line)
                row.update({
                    "employeeId": employee.get("id", ""),
                    "employeeName": employee.get("fullName", "") or cls.employee_name(employee),
                    "employeeCode": employee.get("code", ""),
                    "cedula": employee.get("cedula", ""),
                    "position": employee.get("position", employee.get("jobTitle", "")),
                    "department": employee.get("department", employee.get("area", "General")),
                    "month": month,
                })
                rows.append(row)
                detail.append(row)
            months.append(cls.summarize(rows, month))
        totals = cls.summarize(detail)
        return {"year": int(year), "months": months, "rows": detail, "totals": totals,
                "employee_count": len(selected), "calculation_mode": "projected"}

    @staticmethod
    def employee_name(employee):
        return " ".join(str(employee.get(key, "")).strip() for key in
                         ("firstName", "middleName", "firstLastName", "secondLastName") if employee.get(key)).strip()

    @staticmethod
    def summarize(rows, month=None):
        fields = ("totalIncome", "afpEmployee", "sfsEmployee", "infotepEmployee", "isrRetention",
                  "otherDeductions", "netSalary", "afpEmployer", "sfsEmployer", "srlEmployer",
                  "infotepEmployer", "totalEmployerContrib")
        result = {field: round(sum(float(row.get(field, 0) or 0) for row in rows), 2) for field in fields}
        result["totalCost"] = round(result["totalIncome"] + result["totalEmployerContrib"], 2)
        result["employees"] = len(rows)
        if month is not None:
            result["month"] = month
        return result

    @classmethod
    def project_benefits(cls, employees, cutoff_date, company_id="", sandbox=True, **filters):
        from app.services import hr_data_service as hr
        from app.services import recurring_service as recurring_svc

        selected = cls.filter_employees(employees, **filters)
        ids = [e.get("id", "") for e in selected if e.get("id")]

        txs_by_emp = {}
        recurring_by_emp = {}
        if company_id:
            try:
                txs_by_emp = hr.get_payroll_transactions_for_employees(
                    company_id, ids, sandbox=sandbox)
                all_recurring = recurring_svc.get_recurring_movements(
                    company_id, sandbox=sandbox)
                for mv in all_recurring:
                    recurring_by_emp.setdefault(mv.get("employeeId", ""), []).append(mv)
            except Exception:
                txs_by_emp = {}
                recurring_by_emp = {}

        rows = []
        for employee in selected:
            base = float(employee.get("baseSalary", employee.get("salary", 0)) or 0)
            if base <= 0:
                continue
            emp_id = employee.get("id", "")
            salary_frequency = employee.get("paymentFrequency", "") or "mensual"

            prom = LiquidacionService.calcular_salario_promedio_mensual(
                txs_by_emp.get(emp_id, [])
            )
            monthly_last_12 = prom.get("monthly_totals_last_12") or [base]
            monthly_ytd = prom.get("monthly_salaries_ytd") or [base]

            result = LiquidacionService.calcular_liquidacion(
                employee_id=emp_id,
                employee_name=employee.get("fullName", "") or cls.employee_name(employee),
                cedula=employee.get("cedula", ""),
                hire_date=employee.get("hireDate", ""),
                termination_date=cutoff_date,
                termination_type="desahucio_empleador",
                last_base_salary=base,
                salary_frequency=salary_frequency,
                monthly_salaries_last_12=monthly_last_12,
                monthly_salaries_ytd=monthly_ytd,
                recurring_movements=recurring_by_emp.get(emp_id, []),
            )
            concepts = result.get("conceptos", {})
            totales = result.get("totales", {})
            row = {
                "employeeId": emp_id, "employeeCode": employee.get("code", ""),
                "employeeName": employee.get("fullName", "") or cls.employee_name(employee),
                "cedula": employee.get("cedula", ""), "position": employee.get("position", employee.get("jobTitle", "")),
                "department": employee.get("department", employee.get("area", "General")),
                "hireDate": employee.get("hireDate", ""), "baseSalary": base,
                "salarioPromedio": result.get("salarioPromedioMensual", 0),
                "seniority": result.get("antiguedad", {}),
                "preaviso": concepts.get("preaviso", {}).get("monto", 0),
                "cesantia": concepts.get("cesantia", {}).get("monto", 0),
                "vacaciones": concepts.get("vacaciones", {}).get("monto", 0),
                "salarioNavidad": concepts.get("salarioNavidad", {}).get("monto", 0),
                "salarioProporcional": concepts.get("salarioProporcional", {}).get("monto", 0),
                "asistenciaEconomica": concepts.get("asistenciaEconomica", {}).get("monto", 0),
                "total": totales.get("montoTotal", 0),
                "descuentos": totales.get("montoDescuentos", 0),
                "netoAPagar": totales.get("montoNetoAPagar", 0),
            }
            rows.append(row)
        return {"cutoff_date": cutoff_date, "rows": rows,
                "total": round(sum(row["total"] for row in rows), 2),
                "totalNeto": round(sum(row["netoAPagar"] for row in rows), 2),
                "calculation_mode": "projected"}
