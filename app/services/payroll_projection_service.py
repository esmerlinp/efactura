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
    def project_benefits(cls, employees, cutoff_date, **filters):
        selected = cls.filter_employees(employees, **filters)
        rows = []
        for employee in selected:
            base = float(employee.get("baseSalary", employee.get("salary", 0)) or 0)
            if base <= 0:
                continue
            result = LiquidacionService.calcular_liquidacion(
                employee_id=employee.get("id", ""),
                employee_name=employee.get("fullName", "") or cls.employee_name(employee),
                cedula=employee.get("cedula", ""),
                hire_date=employee.get("hireDate", ""),
                termination_date=cutoff_date,
                termination_type="desahucio_empleador",
                last_base_salary=base,
            )
            concepts = result.get("conceptos", {})
            row = {
                "employeeId": employee.get("id", ""), "employeeCode": employee.get("code", ""),
                "employeeName": employee.get("fullName", "") or cls.employee_name(employee),
                "cedula": employee.get("cedula", ""), "position": employee.get("position", employee.get("jobTitle", "")),
                "department": employee.get("department", employee.get("area", "General")),
                "hireDate": employee.get("hireDate", ""), "baseSalary": base,
                "seniority": result.get("antiguedad", {}),
                "preaviso": concepts.get("preaviso", {}).get("monto", 0),
                "cesantia": concepts.get("cesantia", {}).get("monto", 0),
                "vacaciones": concepts.get("vacaciones", {}).get("monto", 0),
                "salarioNavidad": concepts.get("salarioNavidad", {}).get("monto", 0),
                "salarioProporcional": concepts.get("salarioProporcional", {}).get("monto", 0),
                "asistenciaEconomica": concepts.get("asistenciaEconomica", {}).get("monto", 0),
                "total": result.get("totales", {}).get("montoTotal", 0),
            }
            rows.append(row)
        return {"cutoff_date": cutoff_date, "rows": rows,
                "total": round(sum(row["total"] for row in rows), 2), "calculation_mode": "projected"}
