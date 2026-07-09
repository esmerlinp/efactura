"""Garnishment — Embargo salarial (deducciones por orden judicial)."""

from datetime import date as dt_date, datetime
from typing import Optional
from pydantic import BaseModel


class Garnishment(BaseModel):
    """Embargo salarial activo de un empleado."""

    id: str = ""
    employeeId: str = ""
    employeeName: str = ""

    # Origen del embargo
    garnishmentType: str = "judicial"  # "judicial", "pension_alimenticia", "cooperativa", "prestamo"
    referenceNumber: str = ""          # Número de expediente/orden
    courtName: str = ""                # Juzgado o entidad
    beneficiaryName: str = ""          # Beneficiario del embargo
    beneficiaryAccount: str = ""       # Cuenta donde depositar

    # Montos
    totalAmount: float = 0.0           # Monto total a embargar
    remainingBalance: float = 0.0       # Saldo pendiente
    monthlyDeduction: float = 0.0       # Deducción mensual fija (si aplica)
    deductionPercent: float = 0.0       # Porcentaje de deducción (si es porcentual)
    deductionType: str = "fixed"        # "fixed", "percentage", "max_of_legal"

    # Prioridad (menor = mayor prioridad)
    priority: int = 0                   # 0 = pensión alimenticia, 1 = judicial, 2 = otro

    # Vigencia
    startDate: str = ""                 # Fecha de inicio del embargo
    endDate: str = ""                   # Fecha fin (vacío = hasta saldar)

    # Estado
    status: str = "active"              # "active", "paused", "completed", "cancelled"

    # Metadatos
    notes: str = ""
    createdBy: str = ""
    createdAt: str = ""
    updatedBy: str = ""
    updatedAt: str = ""

    @property
    def is_active(self) -> bool:
        return self.status == "active" and self.remainingBalance > 0

    @property
    def is_pension(self) -> bool:
        return self.garnishmentType == "pension_alimenticia"


class GarnishmentService:
    """Servicio de gestión de embargos salariales."""

    # Porcentajes máximos legales según tipo (RD)
    _LEGAL_MAX_RATES = {
        "pension_alimenticia": 0.50,   # Hasta 50% para pensión alimenticia
        "judicial": 0.30,              # Hasta 30% para embargo judicial
        "cooperativa": 0.20,           # Hasta 20% para cooperativas
        "prestamo": 0.15,              # Hasta 15% para préstamos voluntarios
    }

    # Porcentaje mínimo protegido (no embargable)
    _PROTECTED_INCOME_RATE = 0.40  # 40% del salario es inembargable (excepto pensión)

    @classmethod
    def calculate_max_garnishable(cls, net_salary: float, garnishment_type: str) -> float:
        """Calcula el monto máximo embargable según ley dominicana."""
        if net_salary <= 0:
            return 0.0

        protected = net_salary * cls._PROTECTED_INCOME_RATE
        garnishable = net_salary - protected

        if garnishment_type == "pension_alimenticia":
            max_pct = cls._LEGAL_MAX_RATES["pension_alimenticia"]
            return min(garnishable * (max_pct / (1 - cls._PROTECTED_INCOME_RATE)),
                       net_salary * max_pct)

        max_pct = cls._LEGAL_MAX_RATES.get(garnishment_type, 0.20)
        return min(garnishable, net_salary * max_pct)

    @classmethod
    def calculate_deduction(cls, net_salary: float, garnishment: dict) -> dict:
        """Calcula la deducción para un embargo específico en este período.

        Returns:
            Dict con {deduction, remainingAfter, isCompleted, note}
        """
        g_type = garnishment.get("garnishmentType", "judicial")
        remaining = float(garnishment.get("remainingBalance", 0))
        ded_type = garnishment.get("deductionType", "fixed")
        monthly_fixed = float(garnishment.get("monthlyDeduction", 0))
        ded_pct = float(garnishment.get("deductionPercent", 0))

        if remaining <= 0:
            return {"deduction": 0.0, "remainingAfter": 0.0, "isCompleted": True,
                    "note": "Embargo saldado"}

        max_garnishable = cls.calculate_max_garnishable(net_salary, g_type)

        if ded_type == "fixed":
            deduction = min(monthly_fixed, remaining, max_garnishable)
        elif ded_type == "percentage":
            deduction = min(net_salary * ded_pct, remaining, max_garnishable)
        else:
            deduction = min(max_garnishable, remaining)

        deduction = round(deduction, 2)
        new_remaining = round(remaining - deduction, 2)
        is_completed = new_remaining <= 0

        return {
            "deduction": deduction,
            "remainingAfter": max(0, new_remaining),
            "isCompleted": is_completed,
            "note": "Embargo saldado" if is_completed else f"Pendiente: RD$ {new_remaining:,.2f}",
        }

    @classmethod
    def process_all_garnishments(cls, net_salary: float, garnishments: list) -> dict:
        """Procesa todos los embargos de un empleado en orden de prioridad.

        Args:
            net_salary: Salario neto del empleado en este período.
            garnishments: Lista de embargos activos ordenados por prioridad.

        Returns:
            Dict con {totalDeduction, details, remainingSalary}
        """
        active = sorted(
            [g for g in garnishments if g.get("status") == "active" and g.get("remainingBalance", 0) > 0],
            key=lambda g: (g.get("priority", 99), g.get("startDate", ""))
        )

        total_deduction = 0.0
        remaining_salary = net_salary
        details = []

        for g in active:
            if remaining_salary <= 0:
                break
            result = cls.calculate_deduction(remaining_salary, g)
            total_deduction += result["deduction"]
            remaining_salary -= result["deduction"]
            details.append({
                "garnishmentId": g.get("id", ""),
                "type": g.get("garnishmentType", ""),
                "reference": g.get("referenceNumber", ""),
                "deduction": result["deduction"],
                "remainingBalance": result["remainingAfter"],
                "isCompleted": result["isCompleted"],
                "note": result["note"],
            })

        return {
            "totalDeduction": round(total_deduction, 2),
            "remainingSalary": round(max(0, remaining_salary), 2),
            "details": details,
        }

    @classmethod
    def validate_garnishment(cls, garnishment: dict) -> dict:
        """Valida un embargo antes de guardarlo.

        Returns:
            Dict con {valid: bool, errors: [...]}
        """
        errors = []
        if not garnishment.get("employeeId"):
            errors.append("El empleado es obligatorio.")
        if not garnishment.get("garnishmentType"):
            errors.append("El tipo de embargo es obligatorio.")
        if not garnishment.get("referenceNumber"):
            errors.append("El número de referencia es obligatorio.")
        total = float(garnishment.get("totalAmount", 0))
        if total <= 0:
            errors.append("El monto total debe ser mayor a cero.")

        ded_type = garnishment.get("deductionType", "fixed")
        if ded_type == "fixed":
            if float(garnishment.get("monthlyDeduction", 0)) <= 0:
                errors.append("La deducción mensual fija debe ser mayor a cero.")
        elif ded_type == "percentage":
            pct = float(garnishment.get("deductionPercent", 0))
            if pct <= 0 or pct > 1:
                errors.append("El porcentaje debe estar entre 0 y 1 (ej: 0.20 = 20%).")

        valid_types = {"judicial", "pension_alimenticia", "cooperativa", "prestamo"}
        if garnishment.get("garnishmentType") not in valid_types:
            errors.append(f"Tipo de embargo no válido. Debe ser: {', '.join(valid_types)}")

        return {"valid": len(errors) == 0, "errors": errors}
