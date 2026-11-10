"""
tax_obligation_rules.py — Fuente única de reglas de obligaciones tributarias DGII/TSS (República Dominicana).

Este módulo centraliza el catálogo de obligaciones, los presets por régimen fiscal y
las referencias normativas. Las fechas de vencimiento se calculan de forma DINÁMICA en
`app/services/tax_obligation_service.py` (nunca se almacenan fechas fijas por año).

Fuentes oficiales:
  - Decreto No. 265-19 (Reglamento RST).
  - Norma General 04-22 (incorporación/permanencia/exclusión y DJ en RST).
  - Código Tributario (Arts. 300, 310, 314, 353).
  - Norma General 08-04 y modificaciones (remisión de información 606/607/608).
  - Norma General 07-07 (retenciones del Estado, 623).
  - Norma General 02-05 (pagos al exterior, 609).
  - FAQ oficial TSS (tss.gob.do/preguntas-frecuentes): pago hasta el 3er día laborable.
  - Instructivos RS1/RS2/RS3/RS4 (DGII) — sujetos y modalidades RST.

Campos por obligación:
  key                clave canónica (usada como id en Firestore).
  recurrence         tipo de recurrencia (ver tax_obligation_service._next_due_date).
  default_enabled    si se activa por defecto al sembrar.
  applies_to         regímenes en los que la obligación es aplicable (metadato informativo).
  conditional        si la obligación se condiciona a actividad/empleados (no es "siempre exenta").
  condition          identificador de la condición de auto-gate.
  source             referencia normativa.
  confirmation_status  "confirmed" | "pending" (reglas no verificables se marcan pending).
"""

# ── Catálogo de obligaciones ─────────────────────────────────────────────────

OBLIGATION_CATALOG = [
    {
        "key": "form_606",
        "label": "Formato de Compras — 606",
        "description": "Reporte mensual de compras de bienes y servicios para sustentar costos y gastos.",
        "recurrence": "monthly_15",
        "default_enabled": True,
        "action_url": "/reports-606",
        "action_label": "Generar 606",
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica", "exempt"],
        "source": "Norma 08-04 y modif.; Calendario del Contribuyente DGII (día 15 del mes siguiente).",
        "confirmation_status": "confirmed",
    },
    {
        "key": "form_607",
        "label": "Formato de Ventas — 607",
        "description": "Reporte mensual de ventas de bienes y servicios y retenciones de ITBIS/ISR.",
        "recurrence": "monthly_15",
        "default_enabled": True,
        "action_url": "/reports-607",
        "action_label": "Generar 607",
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica", "exempt"],
        "source": "Norma 08-04 y modif.; Calendario del Contribuyente DGII (día 15 del mes siguiente).",
        "confirmation_status": "confirmed",
    },
    {
        "key": "form_608",
        "label": "Comprobantes Anulados — 608",
        "description": "Reporte mensual de NCF/e-CF anulados. Herramienta de anulación; no es obligación ordinaria para RST.",
        "recurrence": "monthly_15",
        "default_enabled": False,
        "action_url": "/reports-608",
        "action_label": "Generar 608",
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica", "exempt"],
        "source": "Norma 08-04; Calendario DGII (día 15 — pendiente de confirmación exacta).",
        "confirmation_status": "pending",
    },
    {
        "key": "form_609",
        "label": "Pagos al Exterior — 609",
        "description": "Declaración informativa de pagos y retenciones a no residentes (proveedores del exterior).",
        "recurrence": "monthly_15",
        "default_enabled": False,
        "action_url": "",
        "action_label": "",
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica", "exempt"],
        "source": "Norma 02-05; Calendario DGII (día 15 — pendiente de confirmación exacta).",
        "confirmation_status": "pending",
    },
    {
        "key": "form_623",
        "label": "Retenciones del Estado — 623",
        "description": "Reporte mensual de retenciones efectuadas por entidades del Estado (5% ITBIS / ISR).",
        "recurrence": "monthly_15",
        "default_enabled": False,
        "action_url": "/reports-623",
        "action_label": "Generar 623",
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica"],
        "source": "Norma 07-07; Calendario DGII (día 15 — pendiente de confirmación exacta).",
        "confirmation_status": "pending",
    },
    {
        "key": "it1",
        "label": "Declaración Jurada de ITBIS — IT-1",
        "description": "Declaración jurada y pago mensual del ITBIS devengado, retenido y deducible.",
        "recurrence": "monthly_20",
        "default_enabled": True,
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica"],
        "source": "Código Tributario Art. 353; ITBIS día 20 del mes siguiente.",
        "confirmation_status": "confirmed",
    },
    {
        "key": "ir17",
        "label": "Retenciones y Retribuciones — IR-17",
        "description": "Declaración y pago mensual de retenciones de ISR sobre salarios y otras rentas, y retribuciones complementarias. Aplica cuando existan operaciones sujetas a retención (proveedores, contratistas, terceros) o retribuciones complementarias; no depende de la existencia de empleados.",
        "recurrence": "monthly_10",
        "default_enabled": True,
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica", "rst_income_fisica", "rst_income_juridica", "rst_purchases", "rst_agropecuario", "exempt"],
        "conditional": True,
        "condition": "withholding_operations",
        "source": "Código Tributario Art. 310; retenciones ISR día 10 del mes siguiente.",
        "confirmation_status": "confirmed",
    },
    {
        "key": "ir3",
        "label": "Retenciones de Renta a Empleados — IR-3",
        "description": "Retenciones de ISR aplicadas a los salarios de empleados (vía SUIR/TSS). Condicionado a empleados sujetos a retención salarial.",
        "recurrence": "monthly_10",
        "default_enabled": True,
        "action_url": "/rrhh",
        "action_label": "Nómina",
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica", "rst_income_fisica", "rst_income_juridica", "rst_purchases", "rst_agropecuario", "exempt"],
        "conditional": True,
        "condition": "employees_with_salary_retention",
        "source": "Retenciones ISR sobre salarios vía SUIR/TSS (plazo pendiente de confirmación).",
        "confirmation_status": "pending",
    },
    {
        "key": "tss",
        "label": "Seguridad Social — TSS (pago)",
        "description": "Pago mensual de cotizaciones TSS (Salud, Pensión, Riesgos). Condicionado a trabajadores registrados.",
        "recurrence": "third_business_day_next_month",
        "default_enabled": True,
        "action_url": "/rrhh/tss",
        "action_label": "Ver TSS",
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica", "rst_income_fisica", "rst_income_juridica", "rst_purchases", "rst_agropecuario", "exempt"],
        "conditional": True,
        "condition": "registered_workers",
        "source": "FAQ TSS #34 — pago hasta el 3er día laborable del mes siguiente.",
        "confirmation_status": "confirmed",
    },
    {
        "key": "dgt3",
        "label": "Declaración de Personal Fijo — DGT-3",
        "description": "Declaración mensual de personal fijo (nómina) ante la TSS (SUIR). Periodicidad de presentación propia e independiente del pago TSS.",
        "recurrence": "third_business_day_next_month",
        "default_enabled": True,
        "action_url": "/rrhh/tss",
        "action_label": "Ver TSS",
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica", "rst_income_fisica", "rst_income_juridica", "rst_purchases", "rst_agropecuario", "exempt"],
        "conditional": True,
        "condition": "employer",
        "source": "Declaración de personal fijo (SUIR) — plazo de presentación pendiente de confirmación.",
        "confirmation_status": "pending",
    },
    {
        "key": "anticipos_isr",
        "label": "Anticipos ISR (Art. 314 CT) — Mensual",
        "description": "Pago mensual de anticipos del Impuesto Sobre la Renta (12 cuotas del IR-1/IR-2). No aplica a contribuyentes RST.",
        "recurrence": "monthly_15",
        "default_enabled": True,
        "category": "monthly",
        "applies_to": ["ordinary_juridica", "ordinary_fisica"],
        "source": "Código Tributario Art. 314; anticipos mensuales día 15. Excluidos del RST (Decreto 265-19).",
        "confirmation_status": "confirmed",
    },
    {
        "key": "ir2",
        "label": "Impuesto Sobre la Renta Sociedades — IR-2",
        "description": "Declaración jurada anual del ISR para personas jurídicas (120 días post-cierre fiscal). Exento mientras permanezca en RST.",
        "recurrence": "annual_120days",
        "default_enabled": True,
        "category": "annual",
        "applies_to": ["ordinary_juridica", "exempt"],
        "source": "Código Tributario Art. 300; 120 días post-cierre. Excluido del RST (Decreto 265-19).",
        "confirmation_status": "confirmed",
    },
    {
        "key": "act",
        "label": "Activos Imponibles — ACT",
        "description": "Declaración jurada anual del Impuesto sobre los Activos (1% anual). Exento en RST para activos relacionados con la actividad económica.",
        "recurrence": "annual_120days",
        "default_enabled": True,
        "category": "annual",
        "applies_to": ["ordinary_juridica"],
        "source": "Ley 107-04; 120 días post-cierre. Excluido del RST (Decreto 265-19).",
        "confirmation_status": "confirmed",
    },
    {
        "key": "ir1",
        "label": "Impuesto Sobre la Renta Personas Físicas — IR-1",
        "description": "Declaración jurada anual de personas físicas y negocios de único dueño (90 días post-cierre). Exento mientras permanezca en RST.",
        "recurrence": "annual_90days",
        "default_enabled": False,
        "category": "annual",
        "applies_to": ["ordinary_fisica"],
        "source": "Código Tributario Art. 300; 90 días post-cierre. Excluido del RST (Decreto 265-19).",
        "confirmation_status": "confirmed",
    },
    # ── RST: Declaraciones juradas anuales ────────────────────────────────────
    {
        "key": "rs1",
        "label": "RST Ingresos (Persona Física) — RS-1",
        "description": "Declaración jurada anual de RST por ingresos para personas físicas (Decreto 265-19).",
        "recurrence": "last_business_day_february",
        "default_enabled": True,
        "category": "annual",
        "applies_to": ["rst_income_fisica"],
        "source": "Decreto 265-19 y Norma 04-22; DJ anual, último día laborable de febrero del año siguiente.",
        "confirmation_status": "confirmed",
    },
    {
        "key": "rs2",
        "label": "RST Ingresos (Persona Jurídica) — RS-2",
        "description": "Declaración jurada anual de RST por ingresos para personas jurídicas (Decreto 265-19).",
        "recurrence": "last_business_day_february",
        "default_enabled": True,
        "category": "annual",
        "applies_to": ["rst_income_juridica"],
        "source": "Decreto 265-19 y Norma 04-22; DJ anual, último día laborable de febrero del año siguiente.",
        "confirmation_status": "confirmed",
    },
    {
        "key": "rs3",
        "label": "RST Compras — RS-3",
        "description": "Declaración jurada anual de RST por método de compras (personas físicas o jurídicas).",
        "recurrence": "last_business_day_february",
        "default_enabled": True,
        "category": "annual",
        "applies_to": ["rst_purchases"],
        "source": "Decreto 265-19 y Norma 04-22; DJ anual, último día laborable de febrero del año siguiente.",
        "confirmation_status": "confirmed",
    },
    {
        "key": "rs4",
        "label": "RST Agropecuario — RS-4",
        "description": "Declaración jurada anual de RST para el sector agropecuario (personas físicas o jurídicas).",
        "recurrence": "last_business_day_february",
        "default_enabled": True,
        "category": "annual",
        "applies_to": ["rst_agropecuario"],
        "source": "Decreto 265-19 y Norma 04-22; DJ anual, último día laborable de febrero del año siguiente.",
        "confirmation_status": "confirmed",
    },
    # ── RST: Cuotas cuatrimestrales (persona jurídica por ingresos, RS2) ─────
    {
        "key": "rst_cuota_mar",
        "label": "Cuota RST — Marzo",
        "description": "Cuota cuatrimestral del RST (persona jurídica por ingresos), último día laborable de marzo.",
        "recurrence": "last_business_day_march",
        "default_enabled": True,
        "category": "quarterly",
        "applies_to": ["rst_income_juridica"],
        "source": "Decreto 265-19; cuotas RS2: marzo, junio, septiembre y diciembre.",
        "confirmation_status": "confirmed",
    },
    {
        "key": "rst_cuota_jun",
        "label": "Cuota RST — Junio",
        "description": "Cuota cuatrimestral del RST (persona jurídica por ingresos), último día laborable de junio.",
        "recurrence": "last_business_day_june",
        "default_enabled": True,
        "category": "quarterly",
        "applies_to": ["rst_income_juridica"],
        "source": "Decreto 265-19; cuotas RS2: marzo, junio, septiembre y diciembre.",
        "confirmation_status": "confirmed",
    },
    {
        "key": "rst_cuota_sep",
        "label": "Cuota RST — Septiembre",
        "description": "Cuota cuatrimestral del RST (persona jurídica por ingresos), último día laborable de septiembre.",
        "recurrence": "last_business_day_september",
        "default_enabled": True,
        "category": "quarterly",
        "applies_to": ["rst_income_juridica"],
        "source": "Decreto 265-19; cuotas RS2: marzo, junio, septiembre y diciembre.",
        "confirmation_status": "confirmed",
    },
    {
        "key": "rst_cuota_dic",
        "label": "Cuota RST — Diciembre",
        "description": "Cuota cuatrimestral del RST (persona jurídica por ingresos), último día laborable de diciembre.",
        "recurrence": "last_business_day_december",
        "default_enabled": True,
        "category": "quarterly",
        "applies_to": ["rst_income_juridica"],
        "source": "Decreto 265-19; cuotas RS2: marzo, junio, septiembre y diciembre.",
        "confirmation_status": "confirmed",
    },
]

OBLIGATIONS_DICT = {ob["key"]: ob for ob in OBLIGATION_CATALOG}


# ── Presets por régimen fiscal ───────────────────────────────────────────────

REGIMES = {
    "ordinary_juridica": {
        "key": "ordinary_juridica",
        "label": "Régimen Ordinario (Persona Jurídica / Sociedades)",
        "badge_color": "purple",
        "description": "Sociedades comerciales (SRL, SA, SAS, EIRL). Mensuales 606/607/IT-1/IR-17/IR-3/anticipos/TSS/DGT-3 y anuales IR-2 y Activos (ACT).",
        "enabled_keys": ["form_606", "form_607", "it1", "ir17", "ir3", "tss", "dgt3", "anticipos_isr", "ir2", "act"],
    },
    "ordinary_fisica": {
        "key": "ordinary_fisica",
        "label": "Régimen Ordinario (Persona Física)",
        "badge_color": "blue",
        "description": "Personas físicas con negocio de único dueño o servicios independientes. 606/607/IT-1/IR-17/IR-3/anticipos/TSS/DGT-3 y anual IR-1.",
        "enabled_keys": ["form_606", "form_607", "it1", "ir17", "ir3", "tss", "dgt3", "anticipos_isr", "ir1"],
    },
    "rst_income_fisica": {
        "key": "rst_income_fisica",
        "label": "RST por Ingresos (Persona Física) — RS-1",
        "badge_color": "emerald",
        "description": "RST por ingresos, persona física. DJ anual RS-1 (febrero) y obligaciones condicionales de retención y seguridad social. Exento de IT-1, IR-1, anticipos, 606-609 y 623.",
        "enabled_keys": ["rs1", "ir17", "ir3", "tss", "dgt3"],
    },
    "rst_income_juridica": {
        "key": "rst_income_juridica",
        "label": "RST por Ingresos (Persona Jurídica) — RS-2",
        "badge_color": "emerald",
        "description": "RST por ingresos, persona jurídica. DJ anual RS-2 (febrero) + 4 cuotas (mar/jun/sep/dic) y obligaciones condicionales de retención y seguridad social. Exento de IT-1, IR-2, anticipos, ACT y formatos 606-609/623.",
        "enabled_keys": ["rs2", "rst_cuota_mar", "rst_cuota_jun", "rst_cuota_sep", "rst_cuota_dic", "ir17", "ir3", "tss", "dgt3"],
    },
    "rst_purchases": {
        "key": "rst_purchases",
        "label": "RST por Compras — RS-3",
        "badge_color": "teal",
        "description": "RST por método de compras. DJ anual RS-3 (febrero) y obligaciones condicionales de retención y seguridad social. Exento de IT-1, IR-1/IR-2, anticipos y formatos 606-609/623.",
        "enabled_keys": ["rs3", "ir17", "ir3", "tss", "dgt3"],
    },
    "rst_agropecuario": {
        "key": "rst_agropecuario",
        "label": "RST Agropecuario — RS-4",
        "badge_color": "lime",
        "description": "RST del sector agropecuario. DJ anual RS-4 (febrero) y obligaciones condicionales de retención y seguridad social. Exento de IT-1, IR-1/IR-2, anticipos y formatos 606-609/623.",
        "enabled_keys": ["rs4", "ir17", "ir3", "tss", "dgt3"],
    },
    "exempt": {
        "key": "exempt",
        "label": "Régimen Especial / Exento",
        "badge_color": "amber",
        "description": "Empresas acogidas a incentivos fiscales u ONGs. Reportes informativos 606/607, IR-17, IR-3, TSS, DGT-3 y memoria IR-2.",
        "enabled_keys": ["form_606", "form_607", "ir17", "ir3", "tss", "dgt3", "ir2"],
    },
    "consumer": {
        "key": "consumer",
        "label": "Consumidor Final / No Contribuyente",
        "badge_color": "gray",
        "description": "No sujeto a obligaciones tributarias mensuales ante la DGII.",
        "enabled_keys": [],
    },
}


# ── Alias de claves legacy (migración) ──────────────────────────────────────
# Las claves antiguas se re-mapean a la clave canónica al leer/guardar.
LEGACY_KEY_ALIASES = {
    "ir3_ret": "anticipos_isr",
    "rst": "rs2",  # asunción: RST legacy se asume "por ingresos jurídica"; la detección re-semilla la correcta.
}


# ── Reglas que NO pudieron verificarse contra fuente oficial ────────────────
# Se documentan como pendientes; NO se emiten alertas hasta confirmar.
PENDING_CONFIRMATIONS = [
    {
        "item": "Cuotas RS-1 (RST persona física por ingresos)",
        "status": "pending",
        "note": "El Instructivo RS-1 (PDF basado en imágenes) no pudo ser extraído automáticamente. No se emiten cuotas RS-1 hasta confirmar su frecuencia y plazos.",
        "source": "dgii.gov.do/.../Instructivo RS1.pdf",
    },
    {
        "item": "Cuotas RS-3 (RST por compras)",
        "status": "pending",
        "note": "Frecuencia de cuotas/pagos no confirmada. No se emiten cuotas RS-3 hasta confirmar.",
        "source": "dgii.gov.do/.../Instructivo RS3.pdf",
    },
    {
        "item": "Cuotas RS-4 (RST agropecuario)",
        "status": "pending",
        "note": "Frecuencia de cuotas/pagos no confirmada. No se emiten cuotas RS-4 hasta confirmar.",
        "source": "dgii.gov.do/.../Instructivo RS4.pdf",
    },
    {
        "item": "Plazo de presentación DGT-3",
        "status": "pending",
        "note": "Provisional: 3er día laborable del mes siguiente (igual que el pago TSS). Periodicidad de presentación pendiente de confirmación.",
        "source": "FAQ TSS / instructivo SUIR DGT-3",
    },
    {
        "item": "Plazos exactos 608/609/623",
        "status": "pending",
        "note": "Día 15 provisional; confirmar contra Calendario del Contribuyente 2026.",
        "source": "Calendario del Contribuyente 2026 (DGII).",
    },
]
