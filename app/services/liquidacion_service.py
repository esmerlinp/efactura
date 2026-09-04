"""
LiquidacionService - Cálculo de Prestaciones Laborales y Derechos Adquiridos (RD).

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
    def calcular_sdp(cls, salaries: list, frequency: str = "mensual",
                     is_variable: bool = False) -> float:
        """
        Calcula el Salario Diario Promedio según la frecuencia de pago.

        - Salario fijo (is_variable=False): SDP = sueldo_base / divisor.
        - Salario variable (is_variable=True): SDP = promedio(salarios) / divisor,
          donde el promedio se divide entre los meses efectivamente trabajados.

        Args:
            salaries: Lista de salarios. Para fijo: [base_salary].
                      Para variable: salarios de los últimos 12 meses calendario.
            frequency: "mensual", "quincenal", "semanal" o "diario".
            is_variable: True si el salario es variable (comisiones, bonos habituales).

        Returns:
            Salario diario promedio.
        """
        if not salaries:
            return 0.0

        promedio = sum(salaries) / max(1.0, float(len(salaries)))

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
    # SALARIO PROMEDIO MENSUAL (Art. 85 — salario ordinario cotizable)
    # ─────────────────────────────────────────────────────────────────

    @classmethod
    def calcular_salario_promedio_mensual(cls, transactions: list) -> dict:
        """
        Calcula el salario ordinario promedio mensual a partir de transacciones
        de nómina. Solo se consideran conceptos tipo 'earning' con estado
        applied/adjusted cuyo concepto cotiza TSS (conceptSnapshot.affectsTSS),
        excluyendo implícitamente la regalía pascual y otros no-salariales.

        Returns:
            {"promedio_mensual": float, "monthly_salaries_ytd": list,
             "monthly_totals_last_12": list, "months": int}
        """
        monthly = {}
        for tx in (transactions or []):
            if tx.get("type") != "earning":
                continue
            if tx.get("status") not in ("applied", "adjusted"):
                continue
            snap = tx.get("conceptSnapshot") or {}
            if not snap.get("affectsTSS", False):
                continue
            period_key = tx.get("periodKey", "") or ""
            month_key = period_key[:7] if len(period_key) >= 7 else ""
            if not month_key:
                continue
            amount = float(tx.get("amount", 0.0) or 0.0)
            monthly[month_key] = monthly.get(month_key, 0.0) + amount

        sorted_months = sorted(monthly.keys())
        last_12 = sorted_months[-12:]
        total = sum(monthly[m] for m in last_12)
        n = len(last_12) or 1
        promedio_mensual = round(total / n, 2)

        current_year = last_12[-1][:4] if last_12 else ""
        ytd = [round(monthly[m], 2) for m in sorted_months if m.startswith(current_year)]
        monthly_totals_last_12 = [round(monthly[m], 2) for m in last_12]

        return {
            "promedio_mensual": promedio_mensual,
            "monthly_salaries_ytd": ytd,
            "monthly_totals_last_12": monthly_totals_last_12,
            "months": n,
        }

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
                "detalle": "Preaviso ejercido trabajando - sin compensación monetaria (Art. 76)",
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
                    detalle_parts.append(f"{years} año(s): 21x{years}={years * 21} días")
            else:
                dias += years * 23
                detalle_parts.append(f"{years} año(s): 23x{years}={years * 23} días (Art. 80, >5 años)")

            # Fracción de año posterior al primer año
            # Prorrateo proporcional: Meses x DíasPorAño / 12
            dias_por_anio_fraccion = 23 if years >= 5 else 21
            if remaining_months_raw >= 3:
                fraccion = round(remaining_months_raw * dias_por_anio_fraccion / 12.0)
                dias += fraccion
                detalle_parts.append(
                    f"Fracción {remaining_months_raw} meses x "
                    f"{dias_por_anio_fraccion}/12 = {fraccion} días"
                )

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
    # ASISTENCIA ECONÓMICA (Art. 82 - acumulativo)
    # ─────────────────────────────────────────────────────────────────

    TABLA_ASISTENCIA_ECONOMICA = [
        (3, 6, 5),
        (6, 12, 10),
        (12, 9999, 15),
    ]

    @classmethod
    def calcular_asistencia_economica(cls, antiguedad: dict, sdp: float) -> dict:
        """Asistencia económica según Art. 82 del Código de Trabajo RD.

        Solo aplica por causas ajenas a la voluntad del trabajador:
        - Muerte o incapacidad del empleador (cierre del negocio)
        - Muerte, incapacidad o inhabilidad del trabajador
        - Enfermedad prolongada (1 año)
        - Agotamiento de materia prima (industria extractiva)
        - Quiebra, cierre definitivo o reducción de personal (aprobado por M.T.)

        No aplica en desahucio, despido, dimisión ni renuncia.

        Escala:
          - 3 a 6 meses: 5 días de SDP
          - 6 a 12 meses: 10 días de SDP
          - Más de 1 año: 15 días de SDP por año + proporción de meses
        """
        total_months = antiguedad["total_months"]
        years = antiguedad["years"]
        remaining_months = antiguedad["months"]

        if total_months < 3:
            return {
                "aplica": False,
                "dias": 0,
                "monto": 0.0,
                "detalle": "Menos de 3 meses: no aplica asistencia económica (Art. 82)",
                "exentoTSS": True,
                "exentoISR": True,
                "baseLegal": "Art. 82 Código de Trabajo",
            }

        if total_months < 6:
            dias = 5
            detalle = "De 3 a 6 meses: 5 días de SDP (Art. 82)"
        elif total_months < 12:
            dias = 10
            detalle = "De 6 meses a 1 año: 10 días de SDP (Art. 82)"
        else:
            dias = years * 15
            detalle_parts = [f"{years} año(s): 15x{years}={years * 15} días"]
            if remaining_months >= 3:
                prop = remaining_months
                extra = round(15 * prop / 12, 1)
                dias += extra
                detalle_parts.append(f"Fracción {prop} meses: {extra} días")
            detalle = f"Total: {dias} días ({'; '.join(detalle_parts)}) (Art. 82)"

        return {
            "aplica": True,
            "dias": dias,
            "monto": round(dias * sdp, 2),
            "detalle": detalle,
            "exentoTSS": True,
            "exentoISR": True,
            "baseLegal": "Art. 82 Código de Trabajo",
        }

    # ─────────────────────────────────────────────────────────────────
    # VACACIONES NO TOMADAS (Art. 177 / Art. 182 / Art. 180)
    # ─────────────────────────────────────────────────────────────────

    @classmethod
    def calcular_vacaciones(
        cls,
        antiguedad: dict,
        sdp: float,
        termination_type: str = "renuncia",
        pending_complete_years: int = 0,
        taken_current_period: int = 0,
        dias_pendientes_directos: int = None,
    ) -> dict:
        """
        Calcula vacaciones no tomadas según Código de Trabajo RD.

        Si se provee dias_pendientes_directos > 0, se usa ese valor directamente
        en vez de la fórmula basada en años completos y período actual.
        Dos escenarios (Art. 180 vs Art. 177+182):

        ESCENARIO 1 - Menos de 1 año de antigüedad:
          - Solo aplica para desahucio (empleador) o dimisión justificada.
          - Tabla proporcional fija (Art. 182): 5→6, 6→7, ..., 11→12 días.
          - Renuncia voluntaria o despido justificado: 0 días.

        ESCENARIO 2 - Más de 1 año de antigüedad:
          - Años completos NO tomados x días_por_año (14 si <5a, 18 si ≥5a)
          - + Fracción del año en curso (tabla proporcional Art. 182)
          - - Días ya tomados del período actual
          - Aplica para cualquier tipo de salida (derecho adquirido)

        Args:
            antiguedad: Resultado de calcular_antiguedad().
            sdp: Salario diario promedio.
            termination_type: Tipo de salida (impacta Escenario 1).
            pending_complete_years: N° de años completos NO tomados (Escenario 2).
            taken_current_period: Días de vacaciones ya usados en el año en curso.
            dias_pendientes_directos: Si > 0, usa este valor directamente ignorando la fórmula.
        """
        if dias_pendientes_directos is not None and dias_pendientes_directos > 0:
            return {
                "aplica": True,
                "dias": dias_pendientes_directos,
                "monto": round(dias_pendientes_directos * sdp, 2),
                "detalle": f"{dias_pendientes_directos} días pendientes (valor ingresado manualmente)",
                "exentoTSS": False,
                "exentoISR": False,
                "baseLegal": "Art. 177 y 182 Código de Trabajo",
            }

        years = antiguedad["years"]
        months = antiguedad["months"]
        TIPOS_CON_DERECHO = ("desahucio_empleador", "dimision_justificada")

        # ── ESCENARIO 1: Menos de 1 año ──
        if years == 0:
            if termination_type not in TIPOS_CON_DERECHO:
                return {
                    "aplica": False, "dias": 0, "monto": 0.0,
                    "detalle": "Menos de 1 año sin derecho a vacaciones proporcionales "
                               f"para salida tipo '{termination_type}' (Art. 180).",
                    "exentoTSS": False, "exentoISR": False,
                    "baseLegal": "Art. 180 Código de Trabajo",
                }
            if months < 5:
                return {
                    "aplica": False, "dias": 0, "monto": 0.0,
                    "detalle": f"Menos de 1 año y {months} meses: "
                               "no acumula vacaciones proporcionales (Art. 180).",
                    "exentoTSS": False, "exentoISR": False,
                    "baseLegal": "Art. 180 Código de Trabajo",
                }
            dias = cls.TABLA_VACACIONES_PROPORCIONAL.get(months, 0)
            return {
                "aplica": dias > 0, "dias": dias,
                "monto": round(dias * sdp, 2),
                "detalle": f"Vacaciones proporcionales: {months} meses → {dias} días (Art. 180).",
                "exentoTSS": False, "exentoISR": False,
                "baseLegal": "Art. 180 y 182 Código de Trabajo",
            }

        # ── ESCENARIO 2: Más de 1 año ──
        dias_por_anio = 18 if years >= 5 else 14
        detalle_parts = []
        total_dias = 0

        # Años completos pendientes
        if pending_complete_years > 0:
            dias_completos = pending_complete_years * dias_por_anio
            total_dias += dias_completos
            detalle_parts.append(
                f"{pending_complete_years} año(s) completo(s) pendiente(s): "
                f"{pending_complete_years}x{dias_por_anio}={dias_completos} días"
            )

        # Fracción del año en curso
        if months < 5:
            detalle_parts.append(
                f"Año en curso ({months} meses): no acumula fracción (Art. 182)"
            )
        else:
            fraccion = cls.TABLA_VACACIONES_PROPORCIONAL.get(months, dias_por_anio)
            if taken_current_period > 0:
                fraccion = max(0, fraccion - taken_current_period)
                detalle_parts.append(
                    f"Año en curso ({months} meses): {cls.TABLA_VACACIONES_PROPORCIONAL.get(months, dias_por_anio)} días "
                    f"menos {taken_current_period} ya tomado(s) = {fraccion} días"
                )
            else:
                detalle_parts.append(
                    f"Año en curso ({months} meses): {fraccion} días (Art. 182)"
                )
            total_dias += fraccion

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
        dias_extra: int = 0,
    ) -> dict:
        """
        Calcula el Salario de Navidad (Regalía Pascual) según Art. 219.

        Es la duodécima parte (1/12) de la suma de todos los salarios ordinarios
        devengados en el año calendario corriente (desde el 1 de enero hasta la
        fecha de salida), incluyendo la fracción de días del mes de salida.

        No se incluyen horas extras ni bonificaciones para este cálculo.

        Args:
            salaries_year_to_date: Lista de salarios mensuales desde enero hasta
                                   la fecha de salida (o fracción).
            termination_date_str: Fecha de salida (para validar meses).
            dias_extra: Días del mes de salida a prorratear (1-30).
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
        meses = len(salaries_year_to_date)
        dias_extra_str = ""

        if dias_extra > 0 and salaries_year_to_date:
            ultimo_salario = salaries_year_to_date[-1]
            dias_mes = 30
            try:
                import calendar
                td = datetime.strptime(termination_date_str[:10], "%Y-%m-%d")
                dias_mes = calendar.monthrange(td.year, td.month)[1]
            except Exception:
                pass
            fraccion_dias = (dias_extra / dias_mes) * ultimo_salario
            total_salarios += fraccion_dias
            dias_extra_str = f" + {dias_extra}/{dias_mes} días (RD$ {fraccion_dias:,.2f})"

        monto = round(total_salarios / 12.0, 2)

        monto_exento_isr = min(monto, total_salarios / 12.0)
        monto_gravable_isr = max(0.0, monto - monto_exento_isr)

        detalle = (
            f"Suma salarios ordinarios año corriente ({meses} mes(es){dias_extra_str}): "
            f"RD$ {total_salarios:,.2f} / 12 = RD$ {monto:,.2f}"
        )
        if monto_gravable_isr > 0:
            detalle += f" (RD$ {monto_gravable_isr:,.2f} gravable ISR)"

        return {
            "aplica": monto > 0,
            "dias": None,
            "monto": monto,
            "detalle": detalle,
            "exentoTSS": True,
            "exentoISR": monto_gravable_isr == 0,
            "montoExentoISR": round(monto_exento_isr, 2),
            "baseLegal": "Art. 219 Código de Trabajo / Norma 08-04 DGII",
        }

    # ─────────────────────────────────────────────────────────────────
    # SALARIO PROPORCIONAL (Mes de Salida)
    # ─────────────────────────────────────────────────────────────────

    @classmethod
    def calcular_salario_proporcional(
        cls,
        dias_adeudados: int,
        sueldo_base: float,
        frequency: str = "mensual",
    ) -> dict:
        """
        Calcula el salario proporcional por los días trabajados en el mes de salida.

        Fórmula: Días Adeudados x (Sueldo Base / divisor).

        Args:
            dias_adeudados: Días trabajados reales en el mes hasta la fecha de salida.
            sueldo_base: Salario mensual ordinario fijo del empleado.
            frequency: "mensual", "quincenal", "semanal" o "diario".
        """
        if frequency == "mensual":
            divisor = 30.0
        elif frequency == "quincenal":
            divisor = 15.0
        elif frequency == "semanal":
            divisor = cls.DIAS_LABORABLES_SEMANAL
        else:
            divisor = cls.DIAS_LABORABLES_MENSUAL

        diario = sueldo_base / divisor
        monto = round(dias_adeudados * diario, 2)

        return {
            "aplica": dias_adeudados > 0,
            "dias": dias_adeudados,
            "monto": monto,
            "detalle": (
                f"Salario proporcional: {dias_adeudados} días x "
                f"(RD$ {sueldo_base:,.2f} / {divisor}) = RD$ {monto:,.2f}"
            ),
            "exentoTSS": False,
            "exentoISR": False,
            "baseLegal": "Art. 85 Código de Trabajo",
        }

    # ─────────────────────────────────────────────────────────────────
    # CÁLCULO COMPLETO
    # ─────────────────────────────────────────────────────────────────

    @classmethod
    def _normalizar_terminacion(cls, raw_type: str) -> str:
        if not raw_type:
            return "otro"
        t = raw_type.strip().lower()
        mapping = {
            "renuncia_voluntaria": "renuncia",
            "desahucio_empleador": "desahucio_empleador",
            "dimision_justificada": "dimision_justificada",
            "despido_justificado": "despido_justificado",
            "despido_injustificado": "despido_injustificado",
            "mutuo_acuerdo": "mutuo_acuerdo",
            "jubilacion": "jubilacion",
            "fallecimiento": "fallecimiento",
            "fin_contrato_temporal": "fin_contrato_temporal",
            "abandono": "abandono",
            "otro": "otro",
            "renuncia": "renuncia",
        }
        return mapping.get(t, "otro")

    @classmethod
    def build_recurring_deductions(cls, recurring_movements: list) -> list:
        """Construye la lista estructurada de descuentos recurrentes (préstamos,
        adelantos, otros) para pre-carga y edición en la UI de liquidación."""
        result = []
        for mv in (recurring_movements or []):
            status = mv.get("status", "")
            if status not in ("active", "scheduled"):
                continue
            if mv.get("isLoan"):
                tipo = "prestamo"
                monto = float(mv.get("remainingBalance", 0.0))
            elif mv.get("conceptCode") in ("ADELANTO", "ADVANCE"):
                tipo = "adelanto"
                monto = float(mv.get("remainingBalance", mv.get("amount", 0.0)))
            elif mv.get("movementType") == "deduction" and mv.get("remainingBalance", 0) > 0:
                tipo = "otro"
                monto = float(mv.get("remainingBalance", 0.0))
            else:
                continue
            if monto <= 0:
                continue
            result.append({
                "movementId": mv.get("id", ""),
                "id": mv.get("id", ""),
                "conceptCode": mv.get("conceptCode", ""),
                "name": mv.get("description", "") or mv.get("conceptCode", ""),
                "monto": round(monto, 2),
                "tipo": tipo,
                "aplica": True,
            })
        return result

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
        is_variable_salary: bool = False,
        monthly_salaries_last_12: list = None,
        monthly_salaries_ytd: list = None,
        preaviso_trabajado: bool = False,
        vacation_pending_complete_years: int = 0,
        vacation_taken_current_period: int = 0,
        dias_adeudados: int = 0,
        vacation_dias_pendientes: int = 0,
        dias_extra_navidad: int = 0,
        recurring_movements: list = None,
        recurring_deductions: list = None,
        additional_concepts: list = None,
        notes: str = "",
        created_by: str = "",
    ) -> dict:
        """
        Calcula la liquidación laboral completa según el Código de Trabajo RD.

        Agrupa todos los conceptos:
          1. Salario Diario Promedio (Art. 85)
          2. Preaviso (Art. 76) - solo si desahucio empleador o dimisión justificada
          3. Cesantía (Art. 80) - solo si desahucio empleador o dimisión justificada
          4. Vacaciones no tomadas (Art. 177/182) - siempre
          5. Salario de Navidad (Art. 219) - siempre
          6. Salario Proporcional (Mes de Salida) - siempre
          7. Conceptos adicionales (ingresos/descuentos desde catálogo de nómina)
          8. Descuentos recurrentes del empleado (préstamos/adelantos/otros)

        Returns:
            Dict con todos los campos de LiquidacionOutput listo para serializar.
        """
        if monthly_salaries_last_12 is None:
            monthly_salaries_last_12 = []
        if monthly_salaries_ytd is None:
            monthly_salaries_ytd = []
        if recurring_movements is None:
            recurring_movements = []
        if recurring_deductions is None:
            recurring_deductions = []
        if additional_concepts is None:
            additional_concepts = []

        # Si no se proveyeron salarios variables, usar el último salario base repetido
        if not monthly_salaries_last_12:
            monthly_salaries_last_12 = [last_base_salary]
        if not monthly_salaries_ytd:
            monthly_salaries_ytd = [last_base_salary]

        # 1. Antigüedad
        antiguedad = cls.calcular_antiguedad(hire_date, termination_date)

        # 2. Salario Diario Promedio
        #    Los conceptos adicionales que cotizan TSS se suman al acumulado salarial
        #    y se recalcula el promedio (Art. 85: salario ordinario).
        adicional_cotizable = 0.0
        for ac in additional_concepts:
            if (ac.get("type") or ac.get("movementType")) == "deduction":
                continue
            if not ac.get("affectsTSS", False):
                continue
            try:
                adicional_cotizable += float(ac.get("monto", 0.0) or 0.0)
            except (TypeError, ValueError):
                pass

        if adicional_cotizable > 0:
            total_acumulado = sum(monthly_salaries_last_12) + adicional_cotizable
            meses = max(1.0, float(len(monthly_salaries_last_12)))
            promedio_mensual = total_acumulado / meses
            sdp = cls.calcular_sdp([promedio_mensual], salary_frequency,
                                   is_variable=False)
        else:
            promedio_mensual = sum(monthly_salaries_last_12) / max(1.0, float(len(monthly_salaries_last_12)))
            sdp = cls.calcular_sdp(monthly_salaries_last_12, salary_frequency,
                                   is_variable=is_variable_salary)

        # 3. Determinar si aplican prestaciones (Preaviso + Cesantía)
        tipos_con_prestaciones = [
            "desahucio_empleador",
            "dimision_justificada",
            "despido_injustificado",
            "fin_contrato_temporal",
        ]
        tipos_sin_prestaciones = [
            "renuncia",
            "renuncia_voluntaria",
            "despido_justificado",
            "mutuo_acuerdo",
            "jubilacion",
            "fallecimiento",
            "abandono",
            "otro",
        ]
        nt = cls._normalizar_terminacion(termination_type)
        aplica_prestaciones = nt in tipos_con_prestaciones

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
            antiguedad, sdp,
            termination_type=termination_type,
            pending_complete_years=vacation_pending_complete_years,
            taken_current_period=vacation_taken_current_period,
            dias_pendientes_directos=vacation_dias_pendientes if vacation_dias_pendientes > 0 else None,
        )

        # Salario de Navidad (siempre)
        conceptos["salarioNavidad"] = cls.calcular_salario_navidad(
            monthly_salaries_ytd, termination_date,
            dias_extra=dias_extra_navidad,
        )

        # Salario Proporcional (siempre)
        conceptos["salarioProporcional"] = cls.calcular_salario_proporcional(
            dias_adeudados, last_base_salary, salary_frequency
        )

        # Asistencia Económica (Art. 82) - solo causas específicas
        tipos_asistencia_economica = ["fallecimiento", "jubilacion"]
        if termination_type in tipos_asistencia_economica:
            conceptos["asistenciaEconomica"] = cls.calcular_asistencia_economica(
                antiguedad, sdp
            )
        else:
            conceptos["asistenciaEconomica"] = {
                "aplica": False, "dias": 0, "monto": 0.0,
                "detalle": "No aplica por tipo de salida (Art. 82: solo fallecimiento, jubilación, cierre de empresa o quiebra)",
                "exentoTSS": True, "exentoISR": True,
                "baseLegal": "Art. 82 Código de Trabajo",
            }

        # 5. Totales base
        monto_prestaciones = (
            conceptos["preaviso"]["monto"]
            + conceptos["cesantia"]["monto"]
            + conceptos["asistenciaEconomica"]["monto"]
        )
        monto_derechos = (
            conceptos["vacaciones"]["monto"]
            + conceptos["salarioNavidad"]["monto"]
            + conceptos["salarioProporcional"]["monto"]
        )

        # 6. Conceptos adicionales (ingresos/descuentos desde catálogo de nómina)
        conceptos_adicionales = []
        monto_otros_ingresos = 0.0
        monto_otros_descuentos = 0.0
        for ac in additional_concepts:
            try:
                monto = float(ac.get("monto", 0.0) or 0.0)
            except (TypeError, ValueError):
                monto = 0.0
            if monto == 0.0:
                continue
            tipo = ac.get("type") or ac.get("movementType") or "earning"
            taxable = bool(ac.get("taxable", False))
            row = {
                "id": ac.get("id", ""),
                "conceptCode": ac.get("conceptCode", ""),
                "name": ac.get("name", ""),
                "monto": round(monto, 2),
                "comment": ac.get("comment", ""),
                "type": tipo,
                "taxable": taxable,
                "affectsTSS": bool(ac.get("affectsTSS", False)),
                "exentoTSS": not taxable,
                "exentoISR": not taxable,
            }
            if tipo == "deduction":
                monto_otros_descuentos += monto
            else:
                monto_otros_ingresos += monto
            conceptos_adicionales.append(row)

        monto_total = monto_prestaciones + monto_derechos + monto_otros_ingresos

        # Montos gravables y exentos
        monto_gravable_tss = 0.0
        monto_gravable_isr = 0.0
        monto_exento_tss = 0.0
        monto_exento_isr = 0.0

        for key, c in conceptos.items():
            if c["exentoTSS"]:
                monto_exento_tss += c["monto"]
            else:
                monto_gravable_tss += c["monto"]

            if c["exentoISR"]:
                monto_exento_isr += c["monto"]
            else:
                monto_gravable_isr += c["monto"]

        for ac in conceptos_adicionales:
            if ac["type"] == "deduction":
                continue
            if ac["exentoTSS"]:
                monto_exento_tss += ac["monto"]
            else:
                monto_gravable_tss += ac["monto"]
            if ac["exentoISR"]:
                monto_exento_isr += ac["monto"]
            else:
                monto_gravable_isr += ac["monto"]

        # 7. Descuentos recurrentes (Préstamos, Adelantos, Otros) — auto + editables
        descuentos = []
        loan_deductions = 0.0
        advance_deductions = 0.0
        other_deductions = 0.0

        def _clasificar_tipo(mv: dict) -> str:
            if mv.get("isLoan"):
                return "prestamo"
            if mv.get("conceptCode") in ("ADELANTO", "ADVANCE"):
                return "adelanto"
            return "otro"

        if recurring_deductions:
            for d in recurring_deductions:
                if not d.get("aplica", True):
                    continue
                try:
                    monto = float(d.get("monto", 0.0) or 0.0)
                except (TypeError, ValueError):
                    monto = 0.0
                if monto <= 0:
                    continue
                tipo = d.get("tipo") or _clasificar_tipo(d)
                descuentos.append({
                    "id": d.get("id", "") or d.get("movementId", ""),
                    "movementId": d.get("movementId", d.get("id", "")),
                    "conceptCode": d.get("conceptCode", ""),
                    "name": d.get("name", "") or d.get("description", ""),
                    "monto": round(monto, 2),
                    "tipo": tipo,
                    "aplica": True,
                })
                if tipo == "prestamo":
                    loan_deductions += monto
                elif tipo == "adelanto":
                    advance_deductions += monto
                else:
                    other_deductions += monto
        else:
            for d in cls.build_recurring_deductions(recurring_movements):
                descuentos.append(d)
                if d["tipo"] == "prestamo":
                    loan_deductions += d["monto"]
                elif d["tipo"] == "adelanto":
                    advance_deductions += d["monto"]
                else:
                    other_deductions += d["monto"]

        descuentos_totales = (
            loan_deductions + advance_deductions + other_deductions + monto_otros_descuentos
        )
        monto_neto_a_pagar = max(0.0, monto_total - descuentos_totales)

        totales = {
            "montoPrestaciones": round(monto_prestaciones, 2),
            "montoDerechosAdquiridos": round(monto_derechos, 2),
            "montoOtrosIngresos": round(monto_otros_ingresos, 2),
            "montoOtrosDescuentos": round(monto_otros_descuentos, 2),
            "montoTotal": round(monto_total, 2),
            "montoGravableTSS": round(monto_gravable_tss, 2),
            "montoGravableISR": round(monto_gravable_isr, 2),
            "montoExentoTSS": round(monto_exento_tss, 2),
            "montoExentoISR": round(monto_exento_isr, 2),
            "montoExento": round(monto_exento_tss, 2),
            "loanDeductions": round(loan_deductions, 2),
            "advanceDeductions": round(advance_deductions, 2),
            "otherDeductions": round(other_deductions, 2),
            "montoDescuentos": round(descuentos_totales, 2),
            "montoNetoAPagar": round(monto_neto_a_pagar, 2),
        }

        from uuid import uuid4
        from datetime import datetime, timezone

        if len(monthly_salaries_last_12) <= 1:
            notes = (notes or "") + " [⚠ Sin historial salarial: SDP estimado con último salario base.]"
        if len(monthly_salaries_ytd) <= 1 and len(monthly_salaries_last_12) > 1:
            notes = (notes or "") + " [⚠ Sin detalle YTD: regalía estimada con último salario base.]"

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
            "salarioPromedioMensual": round(promedio_mensual, 2),
            "conceptos": conceptos,
            "conceptosAdicionales": conceptos_adicionales,
            "descuentosDetalle": descuentos,
            "totales": totales,
            "notas": notes,
            "status": "calculada",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "createdBy": created_by,
            "paidAt": None,
        }
