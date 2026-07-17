"""PayrollOvertimeCalculator — Cálculo monetario puro de horas extras.

Responsabilidad exclusiva: calcular montos usando valores ya congelados
(hourlyRateAtApproval, factorAtApproval). No consulta empleados ni bases
de datos. Separado de OvertimeService para mantener responsabilidades
únicas (SRP).
"""

from app.countries.do.payroll_rules import (
    DEFAULT_WORKING_DAYS_PER_MONTH,
    DEFAULT_WORKING_HOURS_PER_DAY,
)


class PayrollOvertimeCalculator:
    """Cálculos financieros de horas extras. Stateless."""

    @staticmethod
    def calculate_hourly_rate(base_salary: float,
                                working_days: float = DEFAULT_WORKING_DAYS_PER_MONTH,
                                working_hours: float = DEFAULT_WORKING_HOURS_PER_DAY) -> float:
        """Obtiene el valor de la hora ordinaria: salario / días / horas."""
        if base_salary <= 0:
            return 0.0
        return round(base_salary / working_days / working_hours, 4)

    @staticmethod
    def calculate_pay(hourly_rate: float, minutes: int, factor: float) -> float:
        """Calcula monto de horas extras usando VALORES CONGELADOS.

        Args:
            hourly_rate: Valor hora ordinaria (congelado al aprobar).
            minutes: Minutos totales trabajados.
            factor: Factor multiplicador del tipo de HE (ej: 1.35).

        Returns:
            Monto total calculado.
        """
        if minutes <= 0 or hourly_rate <= 0 or factor <= 0:
            return 0.0
        hours = minutes / 60.0
        return round(hourly_rate * factor * hours, 2)

    @staticmethod
    def calculate_from_salary(base_salary: float, minutes: int, factor: float) -> float:
        """Atajo para obtener monto directamente desde salario mensual.

        Útil cuando aún no se ha congelado el rate (antes de aprobación).
        """
        rate = PayrollOvertimeCalculator.calculate_hourly_rate(base_salary)
        return PayrollOvertimeCalculator.calculate_pay(rate, minutes, factor)

    @staticmethod
    def minutes_from_hours(decimal_hours: float) -> int:
        """Convierte horas decimales (ej: 2.5) a minutos enteros (150)."""
        return int(round(decimal_hours * 60))

    @staticmethod
    def hours_from_minutes(minutes: int) -> float:
        """Convierte minutos enteros (150) a horas decimales (2.5)."""
        return round(minutes / 60.0, 2)
