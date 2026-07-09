"""ThirdPartyPaymentService — Pagos a terceros deducidos de nómina."""

from datetime import date as dt_date, datetime
from typing import Optional
from pydantic import BaseModel


class ThirdPartyEntity(BaseModel):
    """Entidad externa que recibe pagos deducidos de nómina."""

    id: str = ""
    name: str = ""                       # Nombre de la entidad
    entityType: str = "cooperativa"      # "sindicato", "cooperativa", "seguro", "prestamo_institucional", "otro"
    rnc: str = ""                        # RNC de la entidad
    contactName: str = ""
    contactPhone: str = ""
    contactEmail: str = ""
    bankName: str = ""                   # Banco para transferencia
    accountNumber: str = ""              # Cuenta bancaria de la entidad
    accountType: str = "corriente"       # "corriente", "ahorro"

    # Metadatos
    isActive: bool = True
    notes: str = ""
    createdBy: str = ""
    createdAt: str = ""
    updatedBy: str = ""
    updatedAt: str = ""


class ThirdPartyDeduction(BaseModel):
    """Deducción individual de un empleado hacia una entidad tercera."""

    id: str = ""
    employeeId: str = ""
    employeeName: str = ""
    entityId: str = ""                   # ThirdPartyEntity ID
    entityName: str = ""

    deductionType: str = "fixed"         # "fixed", "percentage"
    monthlyAmount: float = 0.0           # Monto fijo mensual
    percentage: float = 0.0              # Porcentaje del salario bruto

    startDate: str = ""
    endDate: str = ""                    # Vacío = indefinido

    status: str = "active"               # "active", "paused", "completed"

    notes: str = ""
    createdBy: str = ""
    createdAt: str = ""


class ThirdPartyPaymentService:
    """Servicio de gestión de pagos a terceros."""

    @classmethod
    def calculate_deduction(cls, gross_salary: float, deduction: dict) -> float:
        """Calcula el monto a deducir para una entidad tercera."""
        ded_type = deduction.get("deductionType", "fixed")
        if ded_type == "percentage":
            pct = float(deduction.get("percentage", 0))
            return round(gross_salary * pct, 2)
        return round(float(deduction.get("monthlyAmount", 0)), 2)

    @classmethod
    def process_deductions(cls, employee_id: str, gross_salary: float,
                           deductions: list) -> dict:
        """Procesa todas las deducciones a terceros de un empleado.

        Returns:
            Dict con {total, details: [{entityId, entityName, amount, type}]}
        """
        active = [d for d in deductions if d.get("status") == "active"]
        total = 0.0
        details = []

        for d in active:
            amount = cls.calculate_deduction(gross_salary, d)
            if amount > 0:
                total += amount
                details.append({
                    "entityId": d.get("entityId", ""),
                    "entityName": d.get("entityName", ""),
                    "deductionId": d.get("id", ""),
                    "amount": amount,
                    "type": d.get("deductionType", ""),
                })

        return {
            "total": round(total, 2),
            "details": details,
        }

    @classmethod
    def generate_payment_summary(cls, payroll_lines: list, entities: dict,
                                  deductions: list) -> dict:
        """Genera un resumen de pagos a terceros para un período.

        Agrupa por entidad y calcula totales.

        Returns:
            Dict con {byEntity: {entityId: {name, total, employees, details}}, grandTotal}
        """
        by_entity = {}
        ded_map = {d.get("id", ""): d for d in deductions}
        entity_map = {e.get("id", ""): e for e in entities}

        for line in payroll_lines:
            emp_id = line.get("employeeId", "")
            emp_name = line.get("employeeName", "")
            third_party_deds = line.get("thirdPartyDetails", [])

            for td in third_party_deds:
                eid = td.get("entityId", "")
                if eid not in by_entity:
                    entity = entity_map.get(eid, {})
                    by_entity[eid] = {
                        "entityId": eid,
                        "entityName": entity.get("name", td.get("entityName", "")),
                        "entityType": entity.get("entityType", ""),
                        "bankName": entity.get("bankName", ""),
                        "accountNumber": entity.get("accountNumber", ""),
                        "total": 0.0,
                        "employees": [],
                    }
                by_entity[eid]["total"] += td.get("amount", 0)
                by_entity[eid]["employees"].append({
                    "employeeId": emp_id,
                    "employeeName": emp_name,
                    "amount": td.get("amount", 0),
                })

        grand_total = round(sum(e["total"] for e in by_entity.values()), 2)
        for e in by_entity.values():
            e["total"] = round(e["total"], 2)

        return {
            "byEntity": list(by_entity.values()),
            "grandTotal": grand_total,
        }

    @classmethod
    def validate_entity(cls, entity: dict) -> dict:
        errors = []
        if not entity.get("name", "").strip():
            errors.append("El nombre de la entidad es obligatorio.")
        valid_types = {"sindicato", "cooperativa", "seguro", "prestamo_institucional", "otro"}
        if entity.get("entityType") not in valid_types:
            errors.append(f"Tipo de entidad no válido: {valid_types}")
        if not entity.get("accountNumber", "").strip():
            errors.append("El número de cuenta bancaria es obligatorio.")
        return {"valid": len(errors) == 0, "errors": errors}
