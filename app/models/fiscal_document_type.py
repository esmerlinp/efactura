"""
FiscalDocumentType — Documentos Fiscales Dominicanos unificados.

Elimina definiciones dispersas en TIPO_CONFIG, ecf_utils, reportes,
templates y JS. Fuente única de verdad para todos los tipos.

Jerarquía:
  E31–E50  →  e-CF (Comprobantes Fiscales Electrónicos)
  B01–B18  →  NCF (Numeración de Comprobantes Fiscales) papel pre-impreso
  B12      →  RUI (Registro Único de Ingresos) — caso especial
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class Family(Enum):
    """Gran familia del documento fiscal."""
    ECF = "e-cf"         # Comprobante Fiscal Electrónico (DGII XML)
    TRADITIONAL = "ncf"  # Comprobante en papel pre-impreso (B01-B18)
    RUI = "rui"          # Registro Único de Ingresos (B12)


class Category(Enum):
    """Categoría contable/fiscal."""
    SALES = "ventas"
    PURCHASES = "compras"
    CREDIT_NOTE = "nota_credito"
    DEBIT_NOTE = "nota_debito"
    EXPORT = "exportacion"
    FOREIGN_PAYMENT = "pago_exterior"
    GOVERNMENT = "gubernamental"
    SPECIAL = "regimen_especial"
    CONSUMER = "consumo"
    MINOR_EXPENSE = "gastos_menores"
    COMMON = "comun"


@dataclass(frozen=True)
class FiscalDocumentType:
    """Descriptor inmutable de un tipo de documento fiscal dominicano.

    Cada instancia es singleton (usar ``by_code()`` en vez del constructor).
    """
    code: str                       # "E31", "B01", etc.
    numeric_code: str               # "31", "01", etc.  (para TIPO_CONFIG legacy)
    label: str                      # "Factura de Crédito Fiscal"
    family: Family
    category: Category
    description: str = ""

    # --- Boletas fiscales ---
    has_itbis: bool = True
    has_retention: bool = False
    has_comprador: bool = True
    has_vencimiento: bool = True
    has_payment_schedule: bool = True
    has_discounts: bool = True
    has_deferred_shipping: bool = True
    requires_rnc: bool = True
    max_amount: Optional[float] = None
    has_itbis_breakdown: bool = True

    # --- Reportes ---
    in_reporte_606: bool = False
    in_reporte_607: bool = False
    in_reporte_608: bool = True
    in_reporte_623: bool = False

    # --- Contabilidad ---
    accounting_entry_type: str = "standard"  # "invoice" / "expense" / "credit_note"

    # --- XSD ---
    xsd_file: Optional[str] = None

    @property
    def short_label(self) -> str:
        return self.label.partition(" (")[0]

    @property
    def label_with_code(self) -> str:
        return f"{self.short_label} ({self.code})"

    @property
    def report_label(self) -> str:
        return f"{self.code[0]}-{self.code[1:]} ({self.short_label})"

    def __str__(self):
        return f"{self.code} – {self.short_label}"


# =========================================================================
# Registry
# =========================================================================

_TYPES: dict[str, FiscalDocumentType] = {}


def _reg(t: FiscalDocumentType) -> FiscalDocumentType:
    _TYPES[t.code] = t
    return t


# -----------------------------------------------------------------------
# e-CF (E31–E50)
# -----------------------------------------------------------------------

E31 = _reg(FiscalDocumentType(
    code="E31", numeric_code="31",
    label="Factura de Crédito Fiscal",
    family=Family.ECF, category=Category.SALES,
    description="Factura de crédito fiscal con derecho a ITBIS",
    has_retention=True, in_reporte_607=True,
    accounting_entry_type="invoice",
    xsd_file="Schemas/e-CF 31 v1.0.xsd",
))

E32 = _reg(FiscalDocumentType(
    code="E32", numeric_code="32",
    label="Factura de Consumo",
    family=Family.ECF, category=Category.CONSUMER,
    description="Factura de consumo para consumidor final",
    has_vencimiento=False, has_deferred_shipping=False,
    has_payment_schedule=True, has_discounts=True,
    requires_rnc=False,
    in_reporte_607=True,
    accounting_entry_type="invoice",
    xsd_file="Schemas/e-CF 32 v1.0.xsd",
))

E33 = _reg(FiscalDocumentType(
    code="E33", numeric_code="33",
    label="Nota de Débito",
    family=Family.ECF, category=Category.DEBIT_NOTE,
    description="Nota de débito — incremento de factura existente",
    has_retention=True,
    in_reporte_607=True,
    accounting_entry_type="invoice",
    xsd_file="Schemas/e-CF 33 v1.0.xsd",
))

E34 = _reg(FiscalDocumentType(
    code="E34", numeric_code="34",
    label="Nota de Crédito",
    family=Family.ECF, category=Category.CREDIT_NOTE,
    description="Nota de crédito — devolución/anulación",
    has_vencimiento=False, has_deferred_shipping=False,
    has_payment_schedule=False, has_discounts=True,
    has_retention=True,
    in_reporte_607=True,
    accounting_entry_type="credit_note",
    xsd_file="Schemas/e-CF 34 v1.0.xsd",
))

E41 = _reg(FiscalDocumentType(
    code="E41", numeric_code="41",
    label="Comprobante de Compras",
    family=Family.ECF, category=Category.PURCHASES,
    description="Comprobante de compras para proveedores con RNC",
    has_retention=True, has_vencimiento=True,
    has_payment_schedule=False, has_discounts=True,
    has_deferred_shipping=False,
    in_reporte_606=True,
    accounting_entry_type="expense",
    xsd_file="Schemas/e-CF 41 v1.0.xsd",
))

E43 = _reg(FiscalDocumentType(
    code="E43", numeric_code="43",
    label="Gastos Menores",
    family=Family.ECF, category=Category.MINOR_EXPENSE,
    description="Comprobante de gastos menores (sin ITBIS detallado)",
    has_comprador=False, has_vencimiento=True,
    has_payment_schedule=False, has_discounts=False,
    has_deferred_shipping=False, has_retention=False,
    has_itbis_breakdown=False,
    max_amount=250000,
    in_reporte_606=True, in_reporte_623=True,
    accounting_entry_type="expense",
    xsd_file="Schemas/e-CF 43 v1.0.xsd",
))

E44 = _reg(FiscalDocumentType(
    code="E44", numeric_code="44",
    label="Regímenes Especiales",
    family=Family.ECF, category=Category.SPECIAL,
    description="Comprobante para regímenes especiales de ITBIS",
    has_itbis=False, has_itbis_breakdown=False,
    requires_rnc=False,
    xsd_file="Schemas/e-CF 44 v1.0.xsd",
))

E45 = _reg(FiscalDocumentType(
    code="E45", numeric_code="45",
    label="Gubernamental",
    family=Family.ECF, category=Category.GOVERNMENT,
    description="Comprobante para instituciones del Estado",
    has_itbis=False, has_comprador=True, has_vencimiento=True,
    has_payment_schedule=True, has_discounts=True,
    has_deferred_shipping=True, has_retention=False,
    has_itbis_breakdown=True,
    in_reporte_606=True, in_reporte_607=True,
    accounting_entry_type="invoice",
    xsd_file="Schemas/e-CF 45 v1.0.xsd",
))

E46 = _reg(FiscalDocumentType(
    code="E46", numeric_code="46",
    label="Exportación",
    family=Family.ECF, category=Category.EXPORT,
    description="Comprobante de exportación (ITBIS 0%)",
    has_itbis=False, has_vencimiento=True,
    has_payment_schedule=True, has_discounts=True,
    has_deferred_shipping=True, has_retention=False,
    has_itbis_breakdown=True,
    in_reporte_607=True,
    accounting_entry_type="invoice",
    xsd_file="Schemas/e-CF 46 v1.0.xsd",
))

E47 = _reg(FiscalDocumentType(
    code="E47", numeric_code="47",
    label="Pagos al Exterior",
    family=Family.ECF, category=Category.FOREIGN_PAYMENT,
    description="Comprobante de pago al exterior (servicios del exterior)",
    has_itbis=False, has_vencimiento=True,
    has_payment_schedule=True, has_discounts=False,
    has_deferred_shipping=False, has_retention=True,
    has_itbis_breakdown=False,
    in_reporte_606=True, in_reporte_623=True,
    accounting_entry_type="expense",
    xsd_file="Schemas/e-CF 47 v1.0.xsd",
))

E48 = _reg(FiscalDocumentType(
    code="E48", numeric_code="48",
    label="Clientes del Exterior",
    family=Family.ECF, category=Category.EXPORT,
    description="Factura para clientes del exterior (sin XSD publicado)",
    has_itbis=False, has_vencimiento=True,
    has_payment_schedule=True, has_discounts=True,
    has_deferred_shipping=True, has_retention=False,
    has_itbis_breakdown=False,
    in_reporte_607=True,
    accounting_entry_type="invoice",
    xsd_file=None,
))

E49 = _reg(FiscalDocumentType(
    code="E49", numeric_code="49",
    label="Zonas Francas",
    family=Family.ECF, category=Category.EXPORT,
    description="Operaciones de zonas francas (sin XSD publicado)",
    has_itbis=False, has_vencimiento=True,
    has_payment_schedule=True, has_discounts=True,
    has_deferred_shipping=True, has_retention=False,
    has_itbis_breakdown=False,
    in_reporte_606=True, in_reporte_607=True,
    accounting_entry_type="invoice",
    xsd_file=None,
))

E50 = _reg(FiscalDocumentType(
    code="E50", numeric_code="50",
    label="Comprobante de Retención",
    family=Family.ECF,
    category=Category.COMMON,
    description="Comprobante de retención — pendiente habilitación DGII",
    has_itbis=False, has_retention=True,
    has_comprador=False, has_vencimiento=False,
    has_payment_schedule=False, has_discounts=False,
    has_deferred_shipping=False, has_itbis_breakdown=False,
    xsd_file=None,
))

# -----------------------------------------------------------------------
# NCF tradicionales (B01–B18)
# -----------------------------------------------------------------------

B01 = _reg(FiscalDocumentType(
    code="B01", numeric_code="01",
    label="Factura de Crédito Fiscal (B01)",
    family=Family.TRADITIONAL, category=Category.SALES,
    description="Factura de crédito fiscal en papel (pre-impresa)",
    has_itbis=True, has_retention=False,
    in_reporte_607=True,
    accounting_entry_type="invoice",
))

B02 = _reg(FiscalDocumentType(
    code="B02", numeric_code="02",
    label="Factura de Consumo (B02)",
    family=Family.TRADITIONAL, category=Category.CONSUMER,
    description="Factura de consumo en papel",
    requires_rnc=False,
    in_reporte_607=True,
    accounting_entry_type="invoice",
))

B03 = _reg(FiscalDocumentType(
    code="B03", numeric_code="03",
    label="Nota de Débito (B03)",
    family=Family.TRADITIONAL, category=Category.DEBIT_NOTE,
    description="Nota de débito en papel",
    in_reporte_607=True,
    accounting_entry_type="invoice",
))

B04 = _reg(FiscalDocumentType(
    code="B04", numeric_code="04",
    label="Nota de Crédito (B04)",
    family=Family.TRADITIONAL, category=Category.CREDIT_NOTE,
    description="Nota de crédito en papel",
    has_vencimiento=False, has_payment_schedule=False,
    in_reporte_607=True,
    accounting_entry_type="credit_note",
))

B05 = _reg(FiscalDocumentType(
    code="B05", numeric_code="05",
    label="Factura a Proveedores (B05)",
    family=Family.TRADITIONAL, category=Category.PURCHASES,
    description="Factura a proveedores en papel",
    accounting_entry_type="expense",
))

B06 = _reg(FiscalDocumentType(
    code="B06", numeric_code="06",
    label="Comprobante de Proveedores (B06)",
    family=Family.TRADITIONAL, category=Category.PURCHASES,
    description="Comprobante de proveedores en papel",
    accounting_entry_type="expense",
))

B07 = _reg(FiscalDocumentType(
    code="B07", numeric_code="07",
    label="Comprobante de Gastos Menores (B07)",
    family=Family.TRADITIONAL, category=Category.MINOR_EXPENSE,
    description="Comprobante de gastos menores en papel",
    has_itbis_breakdown=False,
    max_amount=250000,
    accounting_entry_type="expense",
))

B08 = _reg(FiscalDocumentType(
    code="B08", numeric_code="08",
    label="Comprobante Gubernamental (B08)",
    family=Family.TRADITIONAL, category=Category.GOVERNMENT,
    description="Comprobante gubernamental en papel",
    has_itbis=False, has_itbis_breakdown=False,
    accounting_entry_type="invoice",
))

B09 = _reg(FiscalDocumentType(
    code="B09", numeric_code="09",
    label="Comprobante Exportación (B09)",
    family=Family.TRADITIONAL, category=Category.EXPORT,
    description="Comprobante de exportación en papel",
    has_itbis=False, has_itbis_breakdown=False,
    accounting_entry_type="invoice",
))

B10 = _reg(FiscalDocumentType(
    code="B10", numeric_code="10",
    label="Comprobante Pagos Exterior (B10)",
    family=Family.TRADITIONAL, category=Category.FOREIGN_PAYMENT,
    description="Comprobante de pago al exterior en papel",
    has_itbis=False, has_itbis_breakdown=False,
    accounting_entry_type="expense",
))

B11 = _reg(FiscalDocumentType(
    code="B11", numeric_code="11",
    label="Regímenes Especiales (B11)",
    family=Family.TRADITIONAL, category=Category.SPECIAL,
    description="Comprobante para regímenes especiales en papel",
    has_itbis=False, has_itbis_breakdown=False,
    accounting_entry_type="invoice",
))

B12 = _reg(FiscalDocumentType(
    code="B12", numeric_code="12",
    label="Registro Único de Ingresos",
    family=Family.RUI, category=Category.SALES,
    description="Registro Único de Ingresos (RUI) — para pequeños contribuyentes",
    has_itbis=False, has_retention=False, has_comprador=False,
    has_vencimiento=False, has_payment_schedule=False,
    has_discounts=False, has_deferred_shipping=False,
    has_itbis_breakdown=False, requires_rnc=False,
    accounting_entry_type="invoice",
))

B13 = _reg(FiscalDocumentType(
    code="B13", numeric_code="13",
    label="Gastos Menores Educativos (B13)",
    family=Family.TRADITIONAL, category=Category.MINOR_EXPENSE,
    description="Gastos menores educativos en papel",
    has_itbis_breakdown=False,
    max_amount=250000,
    accounting_entry_type="expense",
))

B14 = _reg(FiscalDocumentType(
    code="B14", numeric_code="14",
    label="Factura Pymes (B14)",
    family=Family.TRADITIONAL, category=Category.SALES,
    description="Factura para pequeñas y medianas empresas en papel",
    accounting_entry_type="invoice",
))

B15 = _reg(FiscalDocumentType(
    code="B15", numeric_code="15",
    label="Comprobante Gubernamental (B15)",
    family=Family.TRADITIONAL, category=Category.GOVERNMENT,
    description="Comprobante gubernamental en papel",
    has_itbis=False, has_itbis_breakdown=False,
    accounting_entry_type="invoice",
))

B16 = _reg(FiscalDocumentType(
    code="B16", numeric_code="16",
    label="Comprobante Suplidores (B16)",
    family=Family.TRADITIONAL, category=Category.PURCHASES,
    description="Comprobante de suplidores en papel",
    accounting_entry_type="expense",
))

B17 = _reg(FiscalDocumentType(
    code="B17", numeric_code="17",
    label="Nota de Débito (B17)",
    family=Family.TRADITIONAL, category=Category.DEBIT_NOTE,
    description="Nota de débito en papel (formato extendido)",
    accounting_entry_type="invoice",
))

B18 = _reg(FiscalDocumentType(
    code="B18", numeric_code="18",
    label="Nota de Crédito (B18)",
    family=Family.TRADITIONAL, category=Category.CREDIT_NOTE,
    description="Nota de crédito en papel (formato extendido)",
    has_vencimiento=False, has_payment_schedule=False,
    accounting_entry_type="credit_note",
))


# =========================================================================
# Lookup API
# =========================================================================

def by_code(code: str) -> FiscalDocumentType:
    """Retorna el tipo por código exacto (``'E31'``, ``'B01'``, etc.)."""
    c = code.strip().upper()
    if c in _TYPES:
        return _TYPES[c]
    raise KeyError(f"Tipo de documento fiscal desconocido: {code!r}")


def by_numeric(numeric: str) -> FiscalDocumentType:
    """Busca por código numérico (``'31'``, ``'01'``, etc.)."""
    for t in _TYPES.values():
        if t.numeric_code == numeric:
            return t
    raise KeyError(f"Sin tipo para código numérico: {numeric!r}")


def by_ncf_prefix(ncf: str) -> FiscalDocumentType:
    """Deriva el tipo desde un NCF/e-NCF (primeros 3 caracteres)."""
    prefix = ncf.strip().upper()[:3]
    return by_code(prefix)


def emitables() -> list[FiscalDocumentType]:
    """Tipos que pueden emitirse por API (e-CF)."""
    return [t for t in _TYPES.values() if t.family == Family.ECF]


def all_types() -> list[FiscalDocumentType]:
    """Todos los tipos registrados."""
    return list(_TYPES.values())


def has_code(code: str) -> bool:
    return code.strip().upper() in _TYPES


# =========================================================================
# Helpers para reemplazar scattering actual
# =========================================================================

def get_tipo_config(tipo_ecf: str) -> dict:
    """Puente hacia TIPO_CONFIG legacy (usa el descriptor).

    Acepta ``"31"`` o ``"E31"`` (con o sin prefijo ``E``).
    """
    try:
        t = by_code(_normalize_code(tipo_ecf))
    except KeyError:
        return {}
    return {
        "label": t.label,
        "nc_nd": t.category in (Category.CREDIT_NOTE, Category.DEBIT_NOTE),
        "expense": t.accounting_entry_type == "expense" and t.category != Category.FOREIGN_PAYMENT,
        "export": t.family == Family.ECF and t.category == Category.EXPORT,
        "foreign_payment": t.category == Category.FOREIGN_PAYMENT,
        "has_comprador": t.has_comprador,
        "vencimiento": t.has_vencimiento,
        "envio_diferido": t.has_deferred_shipping,
        "monto_gravado": t.has_itbis_breakdown and t.category not in (Category.EXPORT, Category.FOREIGN_PAYMENT),
        "ingresos": t.accounting_entry_type != "expense",
        "pago_req": t.accounting_entry_type != "expense",
        "retenciones": t.has_retention,
        "tabla_pagos": t.has_payment_schedule,
        "descuentos": t.has_discounts,
    }


def has_itbis_breakdown(tipo_ecf: str) -> bool:
    """Reemplaza inline check ``tipo_ecf in ("31","32",...)``."""
    code = _normalize_code(tipo_ecf)
    try:
        t = by_code(code)
        return t.has_itbis_breakdown
    except KeyError:
        return False


def has_retencion_item(tipo_ecf: str) -> bool:
    """Reemplaza inline check ``tipo_ecf in ("41","47")``.

    Solo E41 y E47 tienen retención a nivel de ítem (DetallesItems >
    Item > Retencion). Los demás (E31/E33/E34) tienen retención solo
    a nivel de totales (TotalITBISRetenido / TotalISRRetencion).
    """
    code = _normalize_code(tipo_ecf)
    return code in ("E41", "E47")


def select_options(family: Family | str | None = None,
                   category: Category | str | None = None) -> list[tuple[str, str]]:
    """Options para ``<select>``: ``[(code, "Label (CODE)"), ...]``.

    Filtra por familia y/o categoría. Acepta string (``"e-cf"``, ``"ncf"``)
    o enum (``Family.ECF``). Ordenado por código.
    """
    family_enum = Family(family) if isinstance(family, str) and family else family
    category_enum = Category(category) if isinstance(category, str) and category else category
    result = []
    for t in sorted(_TYPES.values(), key=lambda x: x.code):
        if family_enum is not None and t.family != family_enum:
            continue
        if category_enum is not None and t.category != category_enum:
            continue
        result.append((t.code, t.label_with_code))
    return result


def report_labels(report: str = "606") -> dict[str, str]:
    """Retorna dict ``{code: "E-XX (Label)"}`` filtrado por reporte.

    ``report`` puede ser ``"606"``, ``"607"``, ``"608"`` o ``"623"``.
    """
    field_map = {"606": "in_reporte_606", "607": "in_reporte_607",
                 "608": "in_reporte_608", "623": "in_reporte_623"}
    field = field_map.get(report)
    if not field:
        return {}
    return {t.code: t.report_label for t in _TYPES.values()
            if getattr(t, field)}


def _normalize_code(code: str) -> str:
    """Acepta ``"31"``, ``"E31"``, ``"e31"``."""
    c = code.strip().upper()
    if c.isdigit():
        return f"E{c}"
    return c
