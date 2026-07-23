"""AccountingDimensionService — Asientos contables multi-dimensión para nómina."""

from datetime import datetime
from typing import Optional


class AccountingDimensionService:
    """Segmenta asientos de nómina por múltiples dimensiones contables."""

    DEFAULT_DIMENSIONS = ["cost_center", "project", "region", "business_line", "department"]

    @classmethod
    def get_employee_dimensions(cls, employee: dict) -> dict:
        """Extrae dimensiones contables de un empleado.

        Returns:
            Dict con {cost_center, project, region, business_line, department, branch}
        """
        return {
            "cost_center": employee.get("costCenter") or employee.get("area") or employee.get("department") or "General",
            "project": employee.get("project", ""),
            "region": employee.get("region", ""),
            "business_line": employee.get("businessLine", ""),
            "department": employee.get("department", ""),
            "branch": employee.get("branchId", ""),
        }

    @classmethod
    def build_multi_dimension_accounting_lines(
        cls,
        payroll_period: dict,
        employees: dict = None,
        tax_rates: dict = None,
        owner_uid: str = "",
        sandbox: bool = True,
        company_id: str = None,
    ) -> list:
        """Genera asientos contables segmentados por múltiples dimensiones.

        A diferencia de build_payroll_accounting_lines que agrupa solo por
        centro de costo, este método segmenta por todas las dimensiones
        configuradas, generando líneas contables más granulares.

        Returns:
            Lista de líneas contables con dimensiones adicionales.
        """
        from app.services.payroll_service import PayrollService

        employees = employees or {}
        plines = PayrollService.get_period_lines(payroll_period, owner_uid=owner_uid, sandbox=sandbox, company_id=company_id)
        from app.services.hr_data_service import get_tax_rates_snapshot
        snapshot = get_tax_rates_snapshot(payroll_period)
        effective_rates = snapshot if snapshot else tax_rates
        r = PayrollService.get_rates(effective_rates)
        period_label = payroll_period.get("periodKey", "")

        cc_accounts = r.get("cost_center_accounts", {})

        # Agrupar por combinación única de dimensiones
        by_dimensions = {}
        for pl in plines:
            emp_id = pl.get("employeeId", "")
            emp = employees.get(emp_id, {})
            dims = cls.get_employee_dimensions(emp)

            dim_key = (
                dims["cost_center"],
                dims["project"] or "_",
                dims["region"] or "_",
                dims["business_line"] or "_",
                dims["department"] or "_",
            )

            if dim_key not in by_dimensions:
                by_dimensions[dim_key] = {
                    "dimensions": dims,
                    "gross": 0.0,
                    "net": 0.0,
                    "employer": 0.0,
                    "employee_count": 0,
                    "afp_employee": 0.0,
                    "sfs_employee": 0.0,
                    "isr": 0.0,
                    "afp_employer": 0.0,
                    "sfs_employer": 0.0,
                    "srl_employer": 0.0,
                    "infotep": 0.0,
                    "other_ded": 0.0,
                    "employee_ids": [],
                }

            dim_data = by_dimensions[dim_key]
            dim_data["gross"] += pl.get("totalIncome", 0)
            dim_data["net"] += pl.get("netSalary", 0)
            dim_data["employer"] += pl.get("totalEmployerContrib", 0)
            dim_data["employee_count"] += 1
            dim_data["afp_employee"] += pl.get("afpEmployee", 0)
            dim_data["sfs_employee"] += pl.get("sfsEmployee", 0)
            dim_data["isr"] += pl.get("isrRetention", 0)
            dim_data["afp_employer"] += pl.get("afpEmployer", 0)
            dim_data["sfs_employer"] += pl.get("sfsEmployer", 0)
            dim_data["srl_employer"] += pl.get("srlEmployer", 0)
            dim_data["infotep"] += pl.get("infotepEmployer", 0)
            dim_data["other_ded"] += pl.get("otherDeductions", 0)
            dim_data["employee_ids"].append(emp_id)

        lines = []
        for dim_key, dim_data in sorted(by_dimensions.items()):
            cc, project, region, biz_line, dept = dim_key
            dims = dim_data["dimensions"]
            cc_gasto = round(dim_data["gross"] + dim_data["employer"], 2)
            acct_code = cc_accounts.get(dims["cost_center"], "6.2.1.01")

            dim_label_parts = [f"CC:{dims['cost_center']}"]
            if dims["project"]:
                dim_label_parts.append(f"Proy:{dims['project']}")
            if dims["region"]:
                dim_label_parts.append(f"Reg:{dims['region']}")
            if dims["business_line"]:
                dim_label_parts.append(f"LN:{dims['business_line']}")

            lines.append({
                "accountCode": acct_code,
                "accountName": f"Sueldos y salarios - {', '.join(dim_label_parts)}",
                "debit": cc_gasto,
                "credit": 0.00,
                "description": f"Nómina período {period_label} - {dims['cost_center']} ({dim_data['employee_count']} emp.)",
                "dimensions": {
                    "cost_center": dims["cost_center"],
                    "project": dims["project"],
                    "region": dims["region"],
                    "business_line": dims["business_line"],
                    "department": dims["department"],
                },
                "employeeCount": dim_data["employee_count"],
            })

        totals = {
            "totalNet": round(sum(d["net"] for d in by_dimensions.values()), 2),
            "totalAfpEmployee": round(sum(d["afp_employee"] for d in by_dimensions.values()), 2),
            "totalSfsEmployee": round(sum(d["sfs_employee"] for d in by_dimensions.values()), 2),
            "totalIsr": round(sum(d["isr"] for d in by_dimensions.values()), 2),
            "totalAfpEmployer": round(sum(d["afp_employer"] for d in by_dimensions.values()), 2),
            "totalSfsEmployer": round(sum(d["sfs_employer"] for d in by_dimensions.values()), 2),
            "totalSrlEmployer": round(sum(d["srl_employer"] for d in by_dimensions.values()), 2),
            "totalInfotep": round(sum(d["infotep"] for d in by_dimensions.values()), 2),
            "totalOtherDed": round(sum(d["other_ded"] for d in by_dimensions.values()), 2),
        }

        cls._append_credit_lines(lines, totals, r, period_label)

        return lines

    @classmethod
    def _append_credit_lines(cls, lines: list, totals: dict, rates: dict, period_label: str):
        """Agrega líneas de HABER al asiento contable."""
        if totals["totalNet"] > 0:
            lines.append({
                "accountCode": rates["account_salaries_payable"],
                "accountName": "Salarios por pagar",
                "debit": 0.00, "credit": totals["totalNet"],
                "description": f"Salario neto período {period_label}",
                "dimensions": {},
            })
        if totals["totalAfpEmployee"] > 0:
            lines.append({
                "accountCode": rates["account_afp_employee"],
                "accountName": "Retenciones empleado AFP",
                "debit": 0.00, "credit": totals["totalAfpEmployee"],
                "description": f"AFP empleado {period_label}",
                "dimensions": {},
            })
        if totals["totalSfsEmployee"] > 0:
            lines.append({
                "accountCode": rates["account_sfs_employee"],
                "accountName": "Retenciones a empleado SFS",
                "debit": 0.00, "credit": totals["totalSfsEmployee"],
                "description": f"SFS empleado {period_label}",
                "dimensions": {},
            })
        if totals["totalIsr"] > 0:
            lines.append({
                "accountCode": rates["account_isr_employee"],
                "accountName": "Retención ISR empleados",
                "debit": 0.00, "credit": totals["totalIsr"],
                "description": f"ISR empleados {period_label}",
                "dimensions": {},
            })
        if totals["totalAfpEmployer"] > 0:
            lines.append({
                "accountCode": rates["account_afp_employer"],
                "accountName": "Acumulaciones AFP",
                "debit": 0.00, "credit": totals["totalAfpEmployer"],
                "description": f"AFP empleador {period_label}",
                "dimensions": {},
            })
        if totals["totalSfsEmployer"] > 0:
            lines.append({
                "accountCode": rates["account_sfs_employer"],
                "accountName": "Acumulaciones SFS",
                "debit": 0.00, "credit": totals["totalSfsEmployer"],
                "description": f"SFS empleador {period_label}",
                "dimensions": {},
            })
        if totals["totalSrlEmployer"] > 0:
            lines.append({
                "accountCode": rates["account_srl_employer"],
                "accountName": "Acumulaciones SRL",
                "debit": 0.00, "credit": totals["totalSrlEmployer"],
                "description": f"SRL empleador {period_label}",
                "dimensions": {},
            })
        if totals["totalInfotep"] > 0:
            lines.append({
                "accountCode": rates["account_infotep_employer"],
                "accountName": "Acumulaciones INFOTEP",
                "debit": 0.00, "credit": totals["totalInfotep"],
                "description": f"INFOTEP {period_label}",
                "dimensions": {},
            })
        if totals["totalOtherDed"] > 0:
            lines.append({
                "accountCode": rates["account_other_deductions"],
                "accountName": "Deducciones varias por pagar",
                "debit": 0.00, "credit": totals["totalOtherDed"],
                "description": f"Otras deducciones {period_label}",
                "dimensions": {},
            })

    @classmethod
    def get_dimension_summary(cls, payroll_lines: list, employees: dict,
                                dimension: str = "cost_center", company_id: str = None) -> list:
        """Genera un resumen agrupado por una dimensión específica.

        Args:
            dimension: "cost_center", "project", "region", "business_line", "department"
        """
        by_dim = {}
        emp_map = {e.get("id", ""): e for e in (employees or [])}
        if isinstance(employees, dict):
            emp_map = employees

        for line in payroll_lines:
            emp_id = line.get("employeeId", "")
            emp = emp_map.get(emp_id, {})
            dims = cls.get_employee_dimensions(emp)
            dim_value = dims.get(dimension, "Sin asignar") or "Sin asignar"

            if dim_value not in by_dim:
                by_dim[dim_value] = {"value": dim_value, "gross": 0, "net": 0, "employer": 0, "count": 0}
            by_dim[dim_value]["gross"] += line.get("totalIncome", 0)
            by_dim[dim_value]["net"] += line.get("netSalary", 0)
            by_dim[dim_value]["employer"] += line.get("totalEmployerContrib", 0)
            by_dim[dim_value]["count"] += 1

        result = sorted(by_dim.values(), key=lambda x: x["gross"], reverse=True)
        for item in result:
            item["gross"] = round(item["gross"], 2)
            item["net"] = round(item["net"], 2)
            item["employer"] = round(item["employer"], 2)
        return result
