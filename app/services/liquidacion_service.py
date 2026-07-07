"""
LiquidacionService — Cálculo de Prestaciones Laborales y Derechos Adquiridos (RD).

Basado en:
- Ley 16-92 (Código de Trabajo de la República Dominicana)
- Art. 76 (Preaviso), Art. 80 (Cesantía), Art. 85 (Salario Diario Promedio)
- Art. 177 y 182 (Vacaciones), Art. 219 (Salario de Navidad)
- Ley 87-01 (Seguridad Social), Norma 08-04 DGII (Retenciones ISR)

Tratamiento fiscal:
  - Preaviso y Cesantía: EXENTOS de TSS y EXENTOS de ISR
  - Vacaciones: GRAVABLES (aplica TSS e ISR si excede mínimo exento)
  - Salario de Navidad: EXENTO de ISR y EXENTO de TSS (Art. 219, Ley 87-01)
"""

import calendar as _cal
from datetime import date, datetime, timedelta
from typing import Optional


class LiquidacionService:
    """Servicio de cálculo de liquidación laboral según Código de Trabajo RD."""

    # ─────────────────────────────────────────────────────────────────
    # CONSTANTES LEGALES
    # ─────────────────────────────────────────────────────────────────

    DIAS_LABORABLES_MENSUAL = 23.83   # Días hábiles promedio por mes (Art. 85)
    DIAS_LABORABLES_QUINCENAL = 11.91  # 23.83 / 2
    DIAS_LABORABLES_SEMANAL = 5.5      # Días hábiles promedio por semana

    # Tabla de proporcionalidad de vacaciones para fracción de año (Art. 182)
    TABLA_VACACIONES_PROPORCIONAL = {
        5: 6, 6: 7, 7: 8, 8: 9, 9: 10, 10: 11, 11: 12,
    }

    # ─────────────────────────────────────────────────────────────────
    # SALARIO DIARIO PROMEDIO (Art. 85)
    # ─────────────────────────────────────────────────────────────────

    @classmethod
    def calcular_sdp(cls, salaries: list, frequency: str = "mensual") -> float:
        """
        Calcula el Salario Diario Promedio según la frecuencia de pago.

        Args:
            salaries: Lista de salarios de los últimos 12 meses (o fracción).
            frequency: "mensual", "quincenal", "semanal" o "diario".

        Returns:
            Salario diario promedio.
        """
        if not salaries:
            return 0.0

        promedio = sum(salaries) / len(salaries)

        if frequency == "mensual":
            return round(promedio / cls.DIAS_LABORABLES_MENSUAL, 4)
        elif frequency == "quincenal":
            return round(promedio / cls.DIAS_LABORABLES_QUINCENAL, 4)
        elif frequency == "semanal":
            return round(promedio / cls.DIAS_LABORABLES_SEMANAL, 4)
        elif frequency == "diario":
            return round(promedio, 4)
        else:
            return round(promedio / cls.DIAS_LABORABLES_MENSUAL, 4)

    # ─────────────────────────────────────────────────────────────────
    # ANTIGÜEDAD
    # ─────────────────────────────────────────────────────────────────

    @classmethod
    def calcular_antiguedad(cls, hire_date_str: str, termination_date_str: str) -> dict:
        """
        Calcula años, meses y días de antigüedad exacta, y total de meses.

        Returns:
            Dict con years, months, days, total_months.
        """
        try:
            hd = datetime.strptime(hire_date_str[:10], "%Y-%m-%d").date()
            td = datetime.strptime(termination_date_str[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return {"years": 0, "months": 0, "days": 0, "total_months": 0}

        if td < hd:
            return {"years": 0, "months": 0, "days": 0, "total_months": 0}

        years = td.year - hd.year
        months = td.month - hd.month
        days = td.day - hd.day

        if days < 0:
            prev_month = td.month - 1 if td.month > 1 else 12
            prev_year = td.year if td.month > 1 else td.year - 1
            days_in_prev = _cal.monthrange(prev_year, prev_month)[1]
            days += days_in_prev
            months -= 1

        if months < 0:
            months += 12
            years -= 1

        total_months = years * 12 + months

        # Si hay días sueltos, contamos como un mes adicional si >= 1 día
        # (para efectos de fracciones legales, manejamos en las funciones específicas)

        return {
            "years": max(0, years),
            "months": max(0, months),
            "days": max(0, days),
            "total_months": max(0, total_months),
        }

    # ─────────────────────────────────────────────────────────────────
    # PREAVISO (Art. 76)
    # ─────────────────────────────────────────────────────────────────

    @classmethod
    def calcular_preaviso(cls, antiguedad: dict, sdp: float, preaviso_trabajado: bool = False) -> dict:
        """
        Calcula el preaviso según Art. 76 del Código de Trabajo.

        Escala:
          - 3 a 6 meses: 7 días de SDP
          - 6 meses a 1 año: 14 días de SDP
          - Más de 1 año: 28 días de SDP

        Si se ejerció el preaviso trabajando, el valor monetario es 0.
        """
        if preaviso_trabajado:
            return {
                "aplica": True,
                "dias": 0,
                "monto": 0.0,
                "detalle": "Preaviso ejercido trabajando — sin compensación monetaria (Art. 76)",
                "exentoTSS": True,
                "exentoISR": True,
                "baseLegal": "Art. 76 Código de Trabajo",
            }

        total_months = antiguedad["total_months"]
        if total_months < 3:
            dias = 0
            detalle = "Menos de 3 meses: no aplica preaviso (Art. 76)"
        elif total_months < 6:
            dias = 7
            detalle = "De 3 a 6 meses: 7 días de SDP (Art. 76)"
        elif total_months < 12:
            dias = 14
            detalle = "De 6 meses a 1 año: 14 días de SDP (Art. 76)"
        else:
            dias = 28
            detalle = "Más de 1 año: 28 días de SDP (Art. 76)"

        return {
            "aplica": dias > 0,
            "dias": dias,
            "monto": round(dias * sdp, 2),
            "detalle": detalle,
            "exentoTSS": True,
            "exentoISR": True,
            "baseLegal": "Art. 76 Código de Trabajo",
        }

    # ─────────────────────────────────────────────────────────────────
    # CESANTÍA (Art. 80)
    # ─────────────────────────────────────────────────────────────────

    @classmethod
    def calcular_cesantia(cls, antiguedad: dict, sdp: float) -> dict:
        """
        Calcula la cesantía según Art. 80 del Código de Trabajo.

        Escala:
          - 3 a 6 meses: 6 días de SDP
          - 6 meses a 1 año: 13 días de SDP
          - 1 a 5 años: 21 días de SDP por cada año
          - Más de 5 años: 23 días de SDP por cada año

        Fracciones de año (> 3 meses luego del primer año):
          - 3 a 6 meses: 6 días
          - 6 a 12 meses: 13 días
        """
        total_months = antiguedad["total_months"]
        years = antiguedad["years"]
        remaining_months_raw = antiguedad["months"]

        if total_months < 3:
            return {
                "aplica": False,
                "dias": 0,
                "monto": 0.0,
                "detalle": "Menos de 3 meses: no aplica cesantía (Art. 80)",
                "exentoTSS": True,
                "exentoISR": True,
                "baseLegal": "Art. 80 Código de Trabajo",
            }

        if total_months < 6:
            dias = 6
            detalle = "De 3 a 6 meses: 6 días de SDP (Art. 80)"
        elif total_months < 12:
            dias = 13
            detalle = "De 6 meses a 1 año: 13 días de SDP (Art. 80)"
        else:
            dias = 0
            detalle_parts = []

            # Años completos
            if years <= 5:
                dias += years * 21
                if years > 0:
                    detalle_parts.append(f"{years} año(s): 21×{years}={years * 21} días")
            else:
                dias += 5 * 21 + (years - 5) * 23
                detalle_parts.append("5 años: 21×5=105 días")
                detalle_parts.append(f"{years - 5} año(s) adicional(es): 23×{years - 5}={(years - 5) * 23} días")

            # Fracción de año posterior al primer año
            if 3 <= remaining_months_raw < 6:
                dias += 6
                detalle_parts.append(f"Fracción {remaining_months_raw} meses: 6 días")
            elif 6 <= remaining_months_raw < 12:
                dias += 13
                detalle_parts.append(f"Fracción {remaining_months_raw} meses: 13 días")

            detalle = f"Total: {dias} días ({'; '.join(detalle_parts)}) (Art. 80)"

        return {
            "aplica": True,
            "dias": dias,
            "monto": round(dias * sdp, 2),
            "detalle": detalle,
            "exentoTSS": True,
            "exentoISR": True,
            "baseLegal": "Art. 80 Código de Trabajo",
        }

    # ─────────────────────────────────────────────────────────────────
    # VACACIONES NO TOMADAS (Art. 177 / Art. 182)
    # ─────────────────────────────────────────────────────────────────

    @classmethod
    def calcular_vacaciones(
        cls,
        antiguedad: dict,
        sdp: float,
        pending_days: int = 0,
        days_taken_this_period: int = 0,
    ) -> dict:
        """
        Calcula vacaciones no tomadas según Art. 177 y 182.

        - Período completo no tomado: 14 días (1-5 años) o 18 días (>5 años).
        - Proporcionalidad por fracción de año según tabla fija (Art. 182).
        - Suma días pendientes reportados de períodos anteriores.

        Args:
            antiguedad: Resultado de calcular_antiguedad().
            sdp: Salario diario promedio.
            pending_days: Días de vacaciones pendientes de períodos anteriores.
            days_taken_this_period: Días ya tomados del período actual.
        """
        years = antiguedad["years"]
        months_current = antiguedad["months"]
        if antiguedad["days"] > 0:
            months_current += 1

        if months_current >= 12:
            months_current = 12

        dias_por_anio = 18 if years >= 5 else 14
        detalle_parts = []

        # Días del período actual (proporcional)
        if months_current < 5:
            dias_periodo_actual = 0
            detalle_parts.append(f"Fracción actual ({months_current} meses): no acumula vacaciones proporcionales")
        else:
            dias_periodo_actual = cls.TABLA_VACACIONES_PROPORCIONAL.get(months_current, dias_por_anio)
            detalle_parts.append(
                f"Período actual ({months_current} meses): {dias_periodo_actual} días "
                f"({dias_por_anio} días/año base, proporcional Art. 182)"
            )

        # Netear días ya tomados
        if days_taken_this_period > 0:
            dias_periodo_actual = max(0, dias_periodo_actual - days_taken_this_period)
            detalle_parts.append(f"Menos {days_taken_this_period} día(s) ya tomado(s)")

        # Días pendientes de períodos anteriores
        if pending_days > 0:
            detalle_parts.append(f"Más {pending_days} día(s) pendiente(s) de períodos anteriores")

        total_dias = dias_periodo_actual + pending_days

        if total_dias == 0:
            detalle = "Sin vacaciones pendientes"
        else:
            detalle = f"Total: {total_dias} días ({'; '.join(detalle_parts)}) (Art. 177 y 182)"

        return {
            "aplica": total_dias > 0,
            "dias": total_dias,
            "monto": round(total_dias * sdp, 2),
            "detalle": detalle,
            "exentoTSS": False,
            "exentoISR": False,
            "baseLegal": "Art. 177 y 182 Código de Trabajo",
        }

    # ─────────────────────────────────────────────────────────────────
    # SALARIO DE NAVIDAD / REGALÍA PASCUAL (Art. 219)
    # ─────────────────────────────────────────────────────────────────

    @classmethod
    def calcular_salario_navidad(
        cls,
        salaries_year_to_date: list,
        termination_date_str: str = "",
    ) -> dict:
        """
        Calcula el Salario de Navidad (Regalía Pascual) según Art. 219.

        Es la duodécima parte (1/12) de la suma de todos los salarios ordinarios
        devengados en el año calendario corriente (desde el 1 de enero hasta la
        fecha de salida).

        No se incluyen horas extras ni bonificaciones para este cálculo.

        Args:
            salaries_year_to_date: Lista de salarios mensuales desde enero hasta
                                   la fecha de salida (o fracción).
            termination_date_str: Fecha de salida (para validar meses).
        """
        if not salaries_year_to_date:
            return {
                "aplica": False,
                "dias": None,
                "monto": 0.0,
                "detalle": "Sin salarios registrados en el año corriente (Art. 219)",
                "exentoTSS": True,
                "exentoISR": True,
                "baseLegal": "Art. 219 Código de Trabajo",
            }

        total_salarios = sum(salaries_year_to_date)
        monto = round(total_salarios / 12.0, 2)
        meses = len(salaries_year_to_date)

        detalle = (
            f"Suma salarios ordinarios año corriente ({meses} mes(es)): "
            f"RD$ {total_salarios:,.2f} / 12 = RD$ {monto:,.2f} (Art. 219)"
        )

        return {
            "aplica": monto > 0,
            "dias": None,
            "monto": monto,
            "detalle": detalle,
            "exentoTSS": True,
            "exentoISR": True,
            "baseLegal": "Art. 219 Código de Trabajo",
        }

    # ─────────────────────────────────────────────────────────────────
    # CÁLCULO COMPLETO
    # ─────────────────────────────────────────────────────────────────

    @classmethod
    def calcular_liquidacion(
        cls,
        employee_id: str = "",
        employee_name: str = "",
        cedula: str = "",
        hire_date: str = "",
        termination_date: str = "",
        termination_type: str = "renuncia",
        last_base_salary: float = 0.0,
        salary_frequency: str = "mensual",
        monthly_salaries_last_12: list = None,
        monthly_salaries_ytd: list = None,
        preaviso_trabajado: bool = False,
        vacation_pending_days: int = 0,
        vacation_days_taken_this_period: int = 0,
        notes: str = "",
        created_by: str = "",
    ) -> dict:
        """
        Calcula la liquidación laboral completa según el Código de Trabajo RD.

        Agrupa todos los conceptos:
          1. Salario Diario Promedio (Art. 85)
          2. Preaviso (Art. 76) — solo si desahucio empleador o dimisión justificada
          3. Cesantía (Art. 80) — solo si desahucio empleador o dimisión justificada
          4. Vacaciones no tomadas (Art. 177/182) — siempre
          5. Salario de Navidad (Art. 219) — siempre

        Returns:
            Dict con todos los campos de LiquidacionOutput listo para serializar.
        """
        if monthly_salaries_last_12 is None:
            monthly_salaries_last_12 = []
        if monthly_salaries_ytd is None:
            monthly_salaries_ytd = []

        # Si no se proveyeron salarios variables, usar el último salario base repetido
        if not monthly_salaries_last_12:
            monthly_salaries_last_12 = [last_base_salary]
        if not monthly_salaries_ytd:
            monthly_salaries_ytd = [last_base_salary]

        # 1. Antigüedad
        antiguedad = cls.calcular_antiguedad(hire_date, termination_date)

        # 2. Salario Diario Promedio
        sdp = cls.calcular_sdp(monthly_salaries_last_12, salary_frequency)

        # 3. Determinar si aplican prestaciones (Preaviso + Cesantía)
        tipos_con_prestaciones = ["desahucio_empleador", "dimision_justificada"]
        aplica_prestaciones = termination_type in tipos_con_prestaciones

        # 4. Calcular conceptos
        conceptos = {}

        # Preaviso
        if aplica_prestaciones:
            conceptos["preaviso"] = cls.calcular_preaviso(antiguedad, sdp, preaviso_trabajado)
        else:
            conceptos["preaviso"] = {
                "aplica": False,
                "dias": 0,
                "monto": 0.0,
                "detalle": f"No aplica por tipo de salida: {termination_type}",
                "exentoTSS": True,
                "exentoISR": True,
                "baseLegal": "Art. 76 Código de Trabajo",
            }

        # Cesantía
        if aplica_prestaciones:
            conceptos["cesantia"] = cls.calcular_cesantia(antiguedad, sdp)
        else:
            conceptos["cesantia"] = {
                "aplica": False,
                "dias": 0,
                "monto": 0.0,
                "detalle": f"No aplica por tipo de salida: {termination_type}",
                "exentoTSS": True,
                "exentoISR": True,
                "baseLegal": "Art. 80 Código de Trabajo",
            }

        # Vacaciones (siempre)
        conceptos["vacaciones"] = cls.calcular_vacaciones(
            antiguedad, sdp, vacation_pending_days, vacation_days_taken_this_period
        )

        # Salario de Navidad (siempre)
        conceptos["salarioNavidad"] = cls.calcular_salario_navidad(
            monthly_salaries_ytd, termination_date
        )

        # 5. Totales
        monto_prestaciones = (
            conceptos["preaviso"]["monto"] + conceptos["cesantia"]["monto"]
        )
        monto_derechos = (
            conceptos["vacaciones"]["monto"] + conceptos["salarioNavidad"]["monto"]
        )
        monto_total = monto_prestaciones + monto_derechos

        # Montos gravables y exentos
        monto_gravable_tss = 0.0
        monto_gravable_isr = 0.0
        monto_exento = 0.0

        for key, c in conceptos.items():
            if not c["exentoTSS"]:
                monto_gravable_tss += c["monto"]
            else:
                monto_exento += c["monto"]

            if not c["exentoISR"]:
                monto_gravable_isr += c["monto"]

        totales = {
            "montoPrestaciones": round(monto_prestaciones, 2),
            "montoDerechosAdquiridos": round(monto_derechos, 2),
            "montoTotal": round(monto_total, 2),
            "montoGravableTSS": round(monto_gravable_tss, 2),
            "montoGravableISR": round(monto_gravable_isr, 2),
            "montoExento": round(monto_exento, 2),
        }

        from uuid import uuid4
        from datetime import datetime, timezone

        return {
            "id": str(uuid4()),
            "employeeId": employee_id,
            "employeeName": employee_name,
            "cedula": cedula,
            "hireDate": hire_date,
            "terminationDate": termination_date,
            "terminationType": termination_type,
            "aplicaPrestaciones": aplica_prestaciones,
            "antiguedad": antiguedad,
            "salarioDiarioPromedio": sdp,
            "conceptos": conceptos,
            "totales": totales,
            "notas": notes,
            "status": "calculada",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "createdBy": created_by,
            "paidAt": None,
        }
