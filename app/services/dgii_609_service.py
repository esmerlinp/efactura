"""Generador del Formato 609 — Pagos por Servicios al Exterior.

Fuente: Norma General 07-2018 (Anexo D) e instructivo oficial DGII (marzo 2026).

El formato es un TXT delimitado por pipe:
  - Encabezado: 609 | RNC/Cédula declarante | Período AAAAMM | cantidad de registros.
  - Detalle (13 columnas), con fechas AAAAMMDD y montos con punto decimal.
"""

from datetime import datetime, timezone

# ── Catálogos oficiales (Anexo D) ────────────────────────────────────────────

TIPO_IDENTIFICACION_609 = {
    "1": "Persona física",
    "2": "Persona jurídica",
}

PARTE_RELACIONADA_609 = {
    "0": "No relacionado",
    "1": "Relacionado",
}

TIPO_SERVICIO_609 = {
    "1": "Gastos de personal",
    "2": "Gastos por trabajos, suministros y servicios",
    "3": "Arrendamientos",
    "4": "Gastos de activos fijos",
    "5": "Gastos de representación",
    "6": "Gastos financieros",
    "7": "Gastos de seguros",
    "8": "Gastos por regalías y otros intangibles",
}

# Códigos de detalle del servicio adquirido (Anexo D, NG 07-2018). El primer
# dígito (decenas) corresponde al tipo de servicio (1-8). Solo existen estos 25
# códigos; el resto del rango 11-84 no es válido.
DETAIL_CODES_609 = {
    "11": "Sueldos y salarios",
    "12": "Otros gastos de personal",
    "21": "Honorarios por servicios profesionales (personas morales)",
    "22": "Honorarios por servicios profesionales (personas físicas)",
    "23": "Seguridad, mensajería, transporte y otros servicios (personas físicas)",
    "24": "Seguridad, mensajería, transporte y otros servicios (personas morales)",
    "31": "De inmuebles (a personas físicas)",
    "32": "De inmuebles (a personas morales)",
    "33": "Otros arrendamientos",
    "41": "Reparación",
    "42": "Mantenimiento",
    "51": "Relaciones públicas",
    "52": "Publicidad",
    "53": "Promociones",
    "54": "Otros gastos de representación",
    "61": "Por préstamos con bancos",
    "62": "Por préstamos con financieras",
    "63": "Por préstamos con personas físicas",
    "64": "Por préstamos con organismos internacionales",
    "65": "Otros gastos financieros",
    "71": "Gastos de seguros",
    "81": "Cesión/uso de marcas",
    "82": "Transferencia de know-how",
    "83": "Cesión/uso de patentes",
    "84": "Otras regalías",
}
VALID_DETAIL_CODES = set(DETAIL_CODES_609.keys())

# País de destino: código ISO 3166-1 numérico de 3 dígitos, según el catálogo
# oficial de la herramienta "Herramienta de Envío Formato 609" (DGII).
COUNTRIES_609 = {
    "004": "AFGANISTÁN",
    "008": "ALBANIA",
    "010": "ANTÁRTIDA",
    "012": "ARGELIA",
    "016": "SAMOA AMERICANA",
    "020": "ANDORRA",
    "024": "ANGOLA",
    "028": "ANTIGUA Y BARBUDA",
    "031": "AZERBAIYÁN",
    "032": "ARGENTINA",
    "036": "AUSTRALIA",
    "040": "AUSTRIA",
    "044": "BAHAMAS",
    "048": "BARÉIN",
    "050": "BANGLADÉS",
    "051": "ARMENIA",
    "052": "BARBADOS",
    "056": "BÉLGICA",
    "060": "BERMUDAS",
    "064": "BUTÁN",
    "068": "BOLIVIA",
    "070": "BOSNIA Y HERZEGOVINA",
    "072": "BOTSUANA",
    "074": "ISLA BOUVET",
    "076": "BRASIL",
    "084": "BELICE",
    "086": "TERRITORIO BRITÁNICO DEL OCÉANO ÍNDICO",
    "090": "ISLAS SALOMÓN",
    "092": "ISLAS VÍRGENES BRITÁNICAS",
    "096": "BRUNÉI",
    "100": "BULGARIA",
    "104": "MYANMAR",
    "108": "BURUNDI",
    "112": "BIELORRUSIA",
    "116": "CAMBOYA",
    "120": "CAMERÚN",
    "124": "CANADÁ",
    "132": "CABO VERDE",
    "136": "ISLAS CAIMÁN",
    "140": "REPÚBLICA CENTROAFRICANA",
    "144": "SRI LANKA",
    "148": "CHAD",
    "152": "CHILE",
    "156": "CHINA",
    "158": "TAIWÁN",
    "162": "ISLA DE NAVIDAD",
    "166": "ISLAS COCOS",
    "170": "COLOMBIA",
    "174": "COMORAS",
    "175": "MAYOTTE",
    "178": "REPÚBLICA DEL CONGO",
    "180": "REP. DEM. DEL CONGO",
    "184": "ISLAS COOK",
    "188": "COSTA RICA",
    "191": "CROACIA",
    "192": "CUBA",
    "196": "CHIPRE",
    "203": "REPÚBLICA CHECA",
    "204": "BENÍN",
    "208": "DINAMARCA",
    "212": "DOMINICA",
    "218": "ECUADOR",
    "222": "EL SALVADOR",
    "226": "GUINEA ECUATORIAL",
    "231": "ETIOPÍA",
    "232": "ERITREA",
    "233": "ESTONIA",
    "234": "ISLAS FEROE",
    "238": "ISLAS MALVINAS",
    "239": "ISLAS GEORGIAS DEL SUR Y SANDWICH DEL SUR",
    "242": "FIYI",
    "246": "FINLANDIA",
    "248": "ÅLAND",
    "250": "FRANCIA",
    "254": "GUAYANA FRANCESA",
    "258": "POLINESIA FRANCESA",
    "260": "TERRITORIOS AUSTRALES FRANCESES",
    "262": "YIBUTI",
    "266": "GABÓN",
    "268": "GEORGIA",
    "270": "GAMBIA",
    "275": "PALESTINA",
    "276": "ALEMANIA",
    "288": "GHANA",
    "292": "GIBRALTAR",
    "296": "KIRIBATI",
    "300": "GRECIA",
    "304": "GROENLANDIA",
    "308": "GRANADA",
    "312": "GUADALUPE",
    "316": "GUAM",
    "320": "GUATEMALA",
    "324": "GUINEA",
    "328": "GUYANA",
    "332": "HAITÍ",
    "334": "ISLAS HEARD Y MCDONALD",
    "336": "CIUDAD DEL VATICANO",
    "340": "HONDURAS",
    "344": "HONG KONG",
    "348": "HUNGRÍA",
    "352": "ISLANDIA",
    "356": "INDIA",
    "360": "INDONESIA",
    "364": "IRÁN",
    "368": "IRAK",
    "372": "IRLANDA",
    "376": "ISRAEL",
    "380": "ITALIA",
    "384": "COSTA DE MARFIL",
    "388": "JAMAICA",
    "392": "JAPÓN",
    "398": "KAZAJISTÁN",
    "400": "JORDANIA",
    "404": "KENIA",
    "408": "COREA DEL NORTE",
    "410": "COREA DEL SUR",
    "414": "KUWAIT",
    "417": "KIRGUISTÁN",
    "418": "LAOS",
    "422": "LÍBANO",
    "426": "LESOTO",
    "428": "LETONIA",
    "430": "LIBERIA",
    "434": "LIBIA",
    "438": "LIECHTENSTEIN",
    "440": "LITUANIA",
    "442": "LUXEMBURGO",
    "446": "MACAO",
    "450": "MADAGASCAR",
    "454": "MALAUI",
    "458": "MALASIA",
    "462": "MALDIVAS",
    "466": "MALÍ",
    "470": "MALTA",
    "474": "MARTINICA",
    "478": "MAURITANIA",
    "480": "MAURICIO",
    "484": "MÉXICO",
    "492": "MÓNACO",
    "496": "MONGOLIA",
    "498": "MOLDAVIA",
    "499": "MONTENEGRO",
    "500": "MONTSERRAT",
    "504": "MARRUECOS",
    "508": "MOZAMBIQUE",
    "512": "OMÁN",
    "516": "NAMIBIA",
    "520": "NAURU",
    "524": "NEPAL",
    "528": "PAÍSES BAJOS",
    "530": "ANTILLAS NEERLANDESAS",
    "533": "ARUBA",
    "534": "SAINT MARTIN",
    "540": "NUEVA CALEDONIA",
    "548": "VANUATU",
    "554": "NUEVA ZELANDA",
    "558": "NICARAGUA",
    "562": "NÍGER",
    "566": "NIGERIA",
    "570": "NIUE",
    "574": "NORFOLK",
    "578": "NORUEGA",
    "580": "ISLAS MARIANAS DEL NORTE",
    "581": "ISLAS ULTRAMARINAS DE ESTADOS UNIDOS",
    "583": "MICRONESIA",
    "584": "ISLAS MARSHALL",
    "585": "PALAOS",
    "586": "PAKISTÁN",
    "591": "PANAMÁ",
    "598": "PAPÚA NUEVA GUINEA",
    "600": "PARAGUAY",
    "604": "PERÚ",
    "608": "FILIPINAS",
    "612": "ISLAS PITCAIRN",
    "616": "POLONIA",
    "620": "PORTUGAL",
    "624": "GUINEA-BISSAU",
    "626": "TIMOR ORIENTAL",
    "630": "PUERTO RICO",
    "634": "QATAR",
    "638": "REUNIÓN",
    "642": "RUMANÍA",
    "643": "RUSIA",
    "646": "RUANDA",
    "652": "SAN BARTOLOMÉ",
    "654": "SANTA ELENA",
    "659": "SAN CRISTÓBAL Y NIEVES",
    "660": "ANGUILA",
    "662": "SANTA LUCÍA",
    "666": "SAN PEDRO Y MIQUELÓN",
    "670": "SAN VICENTE Y LAS GRANADINAS",
    "674": "SAN MARINO",
    "678": "SANTO TOMÉ Y PRÍNCIPE",
    "682": "ARABIA SAUDITA",
    "686": "SENEGAL",
    "688": "SERBIA",
    "690": "SEYCHELLES",
    "694": "SIERRA LEONA",
    "702": "SINGAPUR",
    "703": "ESLOVAQUIA",
    "704": "VIETNAM",
    "705": "ESLOVENIA",
    "706": "SOMALIA",
    "710": "SUDÁFRICA",
    "716": "ZIMBABUE",
    "724": "ESPAÑA",
    "732": "SAHARA OCCIDENTAL",
    "736": "SUDÁN",
    "740": "SURINAM",
    "744": "SVALBARD Y JAN MAYEN",
    "748": "SUAZILANDIA",
    "752": "SUECIA",
    "756": "SUIZA",
    "760": "SIRIA",
    "762": "TAYIKISTÁN",
    "764": "TAILANDIA",
    "768": "TOGO",
    "772": "TOKELAU",
    "776": "TONGA",
    "780": "TRINIDAD Y TOBAGO",
    "784": "EMIRATOS ÁRABES UNIDOS",
    "788": "TÚNEZ",
    "792": "TURQUÍA",
    "795": "TURKMENISTÁN",
    "796": "ISLAS TURCAS Y CAICOS",
    "798": "TUVALU",
    "800": "UGANDA",
    "804": "UCRANIA",
    "807": "REPÚBLICA DE MACEDONIA",
    "818": "EGIPTO",
    "826": "REINO UNIDO",
    "831": "GUERNSEY",
    "832": "JERSEY",
    "833": "ISLA DE MAN",
    "834": "TANZANIA",
    "840": "ESTADOS UNIDOS",
    "850": "ISLAS VÍRGENES ESTADOUNIDENSES",
    "854": "BURKINA FASO",
    "858": "URUGUAY",
    "860": "UZBEKISTÁN",
    "862": "VENEZUELA",
    "876": "WALLIS Y FUTUNA",
    "882": "SAMOA",
    "887": "YEMEN",
    "894": "ZAMBIA",
}

# Alias históricos (alfa-2/alfa-3 usados por la UI antes de alinear al catálogo
# oficial) → código numérico. Evita romper datos ya guardados.
COUNTRY_ALIASES_609 = {
    "US": "840", "USA": "840",
    "ES": "724", "ESP": "724",
    "MX": "484", "MEX": "484",
    "CO": "170", "COL": "170",
    "AR": "032", "ARG": "032",
    "CL": "152", "CHL": "152",
    "PE": "604", "PER": "604",
    "BR": "076", "BRA": "076",
    "UK": "826", "GB": "826", "GBR": "826",
    "DE": "276", "DEU": "276",
    "FR": "250", "FRA": "250",
    "IT": "380", "ITA": "380",
    "CN": "156", "CHN": "156",
    "JP": "392", "JPN": "392",
    "CA": "124", "CAN": "124",
    "PA": "591", "PAN": "591",
    "CR": "188", "CRI": "188",
    "GT": "320", "GTM": "320",
    "SV": "222", "SLV": "222",
    "HN": "340", "HND": "340",
    "NI": "558", "NIC": "558",
    "PR": "630", "PRI": "630",
    "DO": "214", "DOM": "214",
}

_COUNTRY_NAME_TO_CODE_609 = {name: code for code, name in COUNTRIES_609.items()}

MAX_RECORDS_609 = 5000

DETAIL_FIELDS = [
    "nombre",
    "tipoIdentificacion",
    "identificacion",
    "pais",
    "tipoServicio",
    "detalleServicio",
    "parteRelacionada",
    "numeroDocumento",
    "fechaDocumento",
    "montoFacturado",
    "fechaRetencionISR",
    "rentaPresunta",
    "isrRetenido",
]


def _yyyymmdd(value):
    clean = str(value or "").strip()[:10]
    clean = clean.replace("-", "").replace("/", "")
    if len(clean) != 8 or not clean.isdigit():
        return ""
    try:
        datetime(int(clean[:4]), int(clean[4:6]), int(clean[6:8]))
        return clean
    except ValueError:
        return ""


def _yyyymm(value):
    clean = str(value or "").strip()[:7]
    return clean.replace("-", "") if clean else ""


def _money(value):
    try:
        return f"{float(value or 0):.2f}"
    except (ValueError, TypeError):
        return "0.00"


def _parse_money(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _normalize_country(value):
    """Normaliza un país al código ISO 3166-1 numérico de 3 dígitos del 609.

    Acepta código numérico, nombre del país (catálogo oficial) o alias alfa-2/3
    heredados de la UI anterior. Devuelve el valor original si no se reconoce
    (la validación lo reportará).
    """
    v = str(value or "").strip().upper()
    if not v:
        return ""
    if v in COUNTRIES_609:
        return v
    # Códigos numéricos sin cero inicial (p. ej. "4" o 4 → "004")
    if v.isdigit():
        padded = v.zfill(3)
        if padded in COUNTRIES_609:
            return padded
    if v in _COUNTRY_NAME_TO_CODE_609:
        return _COUNTRY_NAME_TO_CODE_609[v]
    if v in COUNTRY_ALIASES_609:
        return COUNTRY_ALIASES_609[v]
    return v


def build_record(source):
    """Proyecta un documento de pago al exterior al shape del 609."""
    source = source or {}
    return {
        "nombre": str(source.get("nombre") or source.get("supplierName") or "").strip(),
        "tipoIdentificacion": str(source.get("tipoIdentificacion") or source.get("tipoIdentificacion609") or "").strip(),
        "identificacion": str(source.get("identificacion") or source.get("supplierRnc") or "").strip(),
        "pais": _normalize_country(source.get("pais") or source.get("paisDestino609")),
        "tipoServicio": str(source.get("tipoServicio") or source.get("tipoServicio609") or "").strip(),
        "detalleServicio": str(source.get("detalleServicio") or source.get("detalleServicio609") or "").strip(),
        "parteRelacionada": str(source.get("parteRelacionada") or "0").strip(),
        "numeroDocumento": str(source.get("numeroDocumento") or source.get("ncf") or source.get("encf") or "").strip(),
        "fechaDocumento": _yyyymmdd(source.get("fechaDocumento") or source.get("date")),
        "montoFacturado": _money(source.get("montoFacturado") or source.get("total")),
        "fechaRetencionISR": _yyyymmdd(source.get("fechaRetencionISR")),
        "rentaPresunta": _money(source.get("rentaPresunta") or source.get("retentionIsrBase")),
        "isrRetenido": _money(source.get("isrRetenido") or source.get("retentionIsrAmount")),
    }


def validate_record(record, period=None):
    """Valida un registro del 609 y devuelve la lista de errores.

    ``period`` (AAAAMM) es opcional; si se pasa, se valida que la fecha de
    retención ISR corresponda al período reportado (regla de la herramienta
    oficial DGII).
    """
    errors = []
    r = record or {}

    # 1. Nombre / Razón social (obligatorio, ≤50)
    nombre = str(r.get("nombre") or "").strip()
    if not nombre:
        errors.append("Nombre/Razón social es obligatorio.")
    elif len(nombre) > 50:
        errors.append("Nombre/Razón social excede los 50 caracteres.")

    # 2. Tipo de identificación (1=física, 2=jurídica)
    tipo_id = str(r.get("tipoIdentificacion") or "").strip()
    if tipo_id not in TIPO_IDENTIFICACION_609:
        errors.append(f"Tipo de identificación inválido: '{tipo_id}'.")

    # 3. Identificación tributaria (obligatoria, ≤50)
    identificacion = str(r.get("identificacion") or "").strip()
    if not identificacion:
        errors.append("Identificación tributaria es obligatoria.")
    elif len(identificacion) > 50:
        errors.append("Identificación tributaria excede los 50 caracteres.")

    # 4. País de destino (ISO 3166-1 numérico de 3 dígitos)
    pais = str(r.get("pais") or "").strip()
    if pais not in COUNTRIES_609:
        errors.append(
            f"País de destino inválido (código ISO 3166-1 numérico de 3 dígitos): '{pais}'."
        )

    # 5. Tipo de servicio (1-8)
    tipo_serv = str(r.get("tipoServicio") or "").strip()
    if tipo_serv not in TIPO_SERVICIO_609:
        errors.append(f"Tipo de servicio inválido: '{tipo_serv}'.")

    # 6. Detalle del servicio (25 códigos del Anexo D + relación tipo↔detalle)
    detalle = str(r.get("detalleServicio") or "").strip()
    if detalle not in DETAIL_CODES_609:
        errors.append(f"Detalle del servicio fuera del catálogo oficial: '{detalle}'.")
    elif tipo_serv.isdigit() and int(detalle) // 10 != int(tipo_serv):
        errors.append(
            f"El detalle '{detalle}' no corresponde al tipo de servicio '{tipo_serv}'."
        )

    # 7. Parte relacionada (0=No, 1=Sí)
    if str(r.get("parteRelacionada", "")).strip() not in PARTE_RELACIONADA_609:
        errors.append(f"Parte relacionada inválida: '{r.get('parteRelacionada')}'.")

    # 8. Número de documento (obligatorio, ≤30)
    numero_doc = str(r.get("numeroDocumento") or "").strip()
    if not numero_doc:
        errors.append("Número de documento es obligatorio.")
    elif len(numero_doc) > 30:
        errors.append("Número de documento excede los 30 caracteres.")

    # 9. Fecha de documento (AAAAMMDD + fecha calendario válida)
    if not r.get("fechaDocumento"):
        errors.append("Fecha del documento inválida o ausente (AAAAMMDD).")

    # 10. Monto facturado (obligatorio, >0, ≤12)
    monto = _parse_money(r.get("montoFacturado"))
    if monto is None:
        errors.append("Monto facturado inválido o ausente.")
    elif monto <= 0:
        errors.append("Monto facturado debe ser mayor que cero.")
    elif len(_money(monto)) > 12:
        errors.append("Monto facturado excede los 12 caracteres.")

    # 11. Fecha de retención ISR (requerida si renta presunta > 0; coincide con período)
    renta = _parse_money(r.get("rentaPresunta"))
    fecha_ret = str(r.get("fechaRetencionISR") or "").strip()
    if renta is not None and renta > 0:
        if not fecha_ret:
            errors.append(
                "Fecha de retención ISR es obligatoria cuando la renta presunta es mayor que cero."
            )
        elif period and fecha_ret[:6] != _yyyymm(period):
            errors.append("Fecha de retención ISR no corresponde al período del reporte.")

    # 12. Renta presunta (≥0, ≤12)
    if renta is not None:
        if renta < 0:
            errors.append("Renta presunta no puede ser negativa.")
        elif len(_money(renta)) > 12:
            errors.append("Renta presunta excede los 12 caracteres.")

    # 13. ISR retenido (obligatorio, ≥0, ≤12). Cero es válido.
    isr = _parse_money(r.get("isrRetenido"))
    if isr is None:
        errors.append("ISR retenido es obligatorio.")
    else:
        if isr < 0:
            errors.append("ISR retenido no puede ser negativo.")
        elif len(_money(isr)) > 12:
            errors.append("ISR retenido excede los 12 caracteres.")

    return errors


def detect_retention_dates(payments):
    """Fechas de retención (de pago) distintas y ordenadas de un conjunto de pagos."""
    dates = set()
    for p in (payments or []):
        d = _yyyymmdd(p.get("paymentDate") or p.get("date"))
        if d:
            dates.add(d)
    return sorted(dates)


def representable_retention_date(payments):
    """Devuelve la fecha única de retención si es representable, o None.

    Una fila 609 representa un documento con UNA fecha de retención. Si hay
    varios pagos con fechas distintas, no es representable en una fila y se
    bloquea hasta confirmar el tratamiento oficial.
    """
    dates = detect_retention_dates(payments)
    if len(dates) == 1:
        return dates[0]
    return None


def split_by_max_records(records, max_records=MAX_RECORDS_609):
    """Divide registros en lotes de hasta max_records (sin fraccionar un registro)."""
    return [records[i:i + max_records] for i in range(0, len(records), max_records)]


def generate_609_txt(records, owner_rnc, period, max_records=MAX_RECORDS_609):
    """Genera el contenido TXT del 609 (sin fraccionar; si excede el máximo lanza)."""
    period = _yyyymm(period)
    if len(records) > max_records:
        raise ValueError(
            f"El formato 609 admite hasta {max_records} registros por archivo; "
            f"se recibieron {len(records)}."
        )
    lines = [f"609|{owner_rnc}|{period}|{len(records)}"]
    for rec in records:
        fields = [str(rec.get(f, "")) for f in DETAIL_FIELDS]
        lines.append("|".join(fields))
    return "\n".join(lines)


def is_foreign_payment_invoice(invoice):
    """Indica si una factura de proveedor corresponde a un pago al exterior (609)."""
    invoice = invoice or {}
    ecf_type = str(invoice.get("ecfType") or "").strip().upper()
    if ecf_type in ("E47", "B17") or "PAGOS AL EXTERIOR" in ecf_type:
        return True
    rule = str(invoice.get("retentionIsrRule") or "").strip().lower()
    return rule in ("payments_abroad", "digital_services_abroad", "royalties")


def build_609_record_from_invoice(invoice, supplier, payments):
    """Construye el registro 609 desde factura + proveedor + pagos aprobados.

    Devuelve ``(record, blocked_reason)``. ``blocked_reason`` no vacío indica que
    el documento no puede representarse (p. ej. varias fechas de retención).

    Nota normativa: ``rentaPresunta`` se reporta como la base total del documento
    (``retentionIsrBase``). El concepto de "renta presunta" (posible gross-up o
    prorrateo) está pendiente de confirmación oficial; no se aplica prorrateo.
    """
    invoice = invoice or {}
    supplier = supplier or {}
    applied_payments = [
        p for p in (payments or [])
        if str(p.get("approvalStatus") or "").lower() == "approved"
        and str(p.get("status") or "").lower() != "voided"
    ]
    if not applied_payments:
        return None, "Sin pago aprobado (sin fecha de retención ISR)."
    retention_date = representable_retention_date(applied_payments)
    if retention_date is None:
        return None, "Pagos parciales con distintas fechas de retención (pendiente representación DGII)."

    source = {
        "nombre": supplier.get("supplierName") or invoice.get("supplierName", ""),
        "tipoIdentificacion": supplier.get("tipoIdentificacion609", ""),
        "identificacion": supplier.get("supplierRnc") or supplier.get("supplierCedula", ""),
        "pais": supplier.get("paisDestino609", ""),
        "tipoServicio": invoice.get("tipoServicio609", ""),
        "detalleServicio": invoice.get("detalleServicio609", ""),
        "parteRelacionada": supplier.get("parteRelacionada", "0"),
        "numeroDocumento": invoice.get("ncf") or invoice.get("encf", ""),
        "fechaDocumento": invoice.get("date", ""),
        "montoFacturado": invoice.get("total", 0),
        "fechaRetencionISR": retention_date,
        "rentaPresunta": invoice.get("retentionIsrBase", 0),
        "isrRetenido": invoice.get("retentionIsrApplied", 0),
    }
    return build_record(source), None


def validate_retention_consistency(invoice):
    """Valida la consistencia de la retención aplicada vs calculada (protecciones).

    Devuelve lista de errores. No aplica prorrateo de renta presunta (pendiente
    de confirmación normativa del concepto en el 609).
    """
    errors = []
    applied = float((invoice or {}).get("retentionIsrApplied") or 0)
    calculated = float((invoice or {}).get("retentionIsrAmount") or 0)
    base = float((invoice or {}).get("retentionIsrBase") or 0)
    if applied < 0:
        errors.append("Retención ISR aplicada negativa.")
    if calculated < 0:
        errors.append("Retención ISR calculada negativa.")
    if base < 0:
        errors.append("Base de retención negativa.")
    if calculated > 0 and applied > calculated + 0.01:
        errors.append(
            f"Retención aplicada ({applied:.2f}) excede la calculada ({calculated:.2f})."
        )
    return errors
