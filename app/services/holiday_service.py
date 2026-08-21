"""HolidayService — Calendario de días feriados RD (Ley 139-97) con personalización por empresa.

Reglas:
- Feriados oficiales RD fijos + móviles (Viernes Santo y Corpus Christi, computados por Pascua).
- Traslado Ley 139-97: martes/miércoles → lunes anterior; jueves/viernes/sábado/domingo → lunes siguiente.
- Viernes Santo se conserva en su fecha natural.
- La empresa puede excluir feriados (días que trabaja) o agregar feriados propios por año,
  guardados en companies/{id}/{sandbox_}hr_holidays con doc id = año.
"""

from datetime import date, timedelta


FIXED_HOLIDAYS = [
    (1, 1, "Año Nuevo"),
    (1, 6, "Día de Reyes"),
    (1, 21, "Día de la Altagracia"),
    (1, 26, "Día de Duarte"),
    (2, 27, "Independencia Nacional"),
    (5, 1, "Día del Trabajo"),
    (8, 16, "Día de la Restauración"),
    (9, 24, "Día de las Mercedes"),
    (11, 6, "Día de la Constitución"),
    (12, 25, "Navidad"),
]


def compute_easter(year: int) -> date:
    """Domingo de Pascua (algoritmo gregoriano anónimo)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _shift_ley_139_97(d: date) -> date:
    """Traslada feriados según Ley 139-97: mar/mié → lunes anterior; jue/vie/sáb/dom → lunes siguiente."""
    wd = d.weekday()
    if wd in (1, 2):
        return d - timedelta(days=wd)
    if wd in (3, 4, 5, 6):
        return d + timedelta(days=(7 - wd) % 7)
    return d


def rd_holidays(year: int) -> list:
    """Feriados oficiales RD del año (con traslados) como lista de dicts {date, name, source}."""
    easter = compute_easter(year)
    good_friday = easter - timedelta(days=2)
    corpus = easter + timedelta(days=60)

    by_date = {}
    for month, day, name in FIXED_HOLIDAYS:
        shifted = _shift_ley_139_97(date(year, month, day))
        by_date.setdefault(shifted.isoformat(), {"date": shifted.isoformat(), "name": [], "source": "rd"})
        by_date[shifted.isoformat()]["name"].append(name)

    by_date.setdefault(good_friday.isoformat(), {"date": good_friday.isoformat(), "name": [], "source": "rd"})
    by_date[good_friday.isoformat()]["name"].append("Viernes Santo")

    corpus_shifted = _shift_ley_139_97(corpus)
    by_date.setdefault(corpus_shifted.isoformat(), {"date": corpus_shifted.isoformat(), "name": [], "source": "rd"})
    by_date[corpus_shifted.isoformat()]["name"].append("Corpus Christi")

    result = []
    for iso in sorted(by_date):
        entry = by_date[iso]
        result.append({"date": iso, "name": " / ".join(entry["name"]), "source": "rd"})
    return result


class HolidayService:

    @staticmethod
    def get_company_config(company_id: str, year: int, sandbox: bool = True) -> dict:
        from app.services import hr_data_service as hr
        return hr.get_holidays_config(company_id, str(year), sandbox=sandbox) or {}

    @staticmethod
    def get_holidays(company_id: str, year: int, sandbox: bool = True) -> list:
        """Feriados efectivos del año: RD (con traslados) − excluidos por la empresa + propios."""
        config = HolidayService.get_company_config(company_id, year, sandbox=sandbox)
        excluded = set(config.get("excluded", []) or [])
        result = [h for h in rd_holidays(year) if h["date"] not in excluded]
        for custom in (config.get("custom", []) or []):
            if custom.get("date"):
                result.append({
                    "date": str(custom["date"]),
                    "name": custom.get("name", "Feriado"),
                    "source": "custom",
                })
        result.sort(key=lambda h: h["date"])
        return result

    @staticmethod
    def get_holiday_dates(company_id: str, start_date_str: str, end_date_str: str,
                          sandbox: bool = True) -> set:
        """Fechas ISO de feriados dentro del rango [inicio, fin] inclusive."""
        try:
            start = date.fromisoformat(str(start_date_str)[:10])
            end = date.fromisoformat(str(end_date_str)[:10])
        except (ValueError, TypeError):
            return set()
        if start > end:
            return set()

        dates = set()
        for year in range(start.year, end.year + 1):
            for holiday in HolidayService.get_holidays(company_id, year, sandbox=sandbox):
                if start.isoformat() <= holiday["date"] <= end.isoformat():
                    dates.add(holiday["date"])
        return dates

    @staticmethod
    def save_company_config(company_id: str, year: int, excluded: list, custom: list,
                            sandbox: bool = True) -> dict:
        from app.services import hr_data_service as hr
        data = {"year": int(year), "excluded": excluded or [], "custom": custom or []}
        hr.save_holidays_config(company_id, str(year), data, sandbox=sandbox)
        return data
