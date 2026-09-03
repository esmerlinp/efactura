"""Catálogo de tabs de variables de nómina (conceptos por tab).

Neutro (sin imports de web) para poder usarse desde servicios y rutas.
"""

VARIABLE_TABS = [
    {"tab": "comisiones",            "concept": "COMISION",             "label": "Comisiones",              "hours": False,
     "help": "Comisión del período (RD$). Tributa TSS e ISR. Para comisiones fijas mensuales usa movimientos recurrentes."},
    {"tab": "incentivos",            "concept": "INCENTIVO_BENEFICIO",  "label": "Incentivos y beneficios", "hours": False,
     "help": "Incentivos, bonos de productividad o beneficios de este período (RD$). Tributa TSS e ISR."},
    {"tab": "horas_trabajadas",      "concept": "HORAS_EXTRA",          "label": "Horas trabajadas",        "hours": True,
     "help": "Horas adicionales del período. El valor se captura en HORAS (ej. 8). Tributa TSS e ISR. Las HE aprobadas en el módulo de Horas Extras se suman automáticamente."},
    {"tab": "diferencial_vacaciones","concept": "DIF_VACACIONES",       "label": "Diferencial de vacaciones", "hours": False,
     "help": "Pago extra por vacaciones (diferencial). Se captura en RD$ y tributa TSS e ISR."},
    {"tab": "salario_retroactivo",   "concept": "SALARIO_RETROACTIVO",  "label": "Salario retroactivo",     "hours": False,
     "help": "Ajuste retroactivo de salario del período (RD$). Tributa TSS e ISR."},
    {"tab": "bonificacion",          "concept": "BONIFICACION",         "label": "Bonificación",            "hours": False,
     "help": "Bonificación extraordinaria (RD$). Tributa TSS e ISR."},
    {"tab": "regalia",               "concept": "REGALIA_PASCUAL",      "label": "Regalía pascual",         "hours": False,
     "help": "Salario de Navidad (Art. 219): 1/12 del salario anual. Se calcula automáticamente según meses trabajados; aquí puedes ajustar el monto de cada empleado. Debe pagarse antes del 20 de diciembre."},
    {"tab": "ingresos_variables",    "concept": "INGRESO_VARIABLE",     "label": "Ingresos variables",      "hours": False,
     "help": "Cualquier otro ingreso del período (RD$). Tributa TSS e ISR."},
    {"tab": "cxc",                   "concept": "DESC_CXC",             "label": "Cuentas por cobrar",      "hours": False,
     "help": "Descuento de cuentas por cobrar de la empresa (adelantos, préstamos internos). No afecta TSS/ISR. Para cuotas fijas mensuales crea un movimiento recurrente."},
    {"tab": "seguro",                "concept": "SEGURO",               "label": "Seguro",                  "hours": False,
     "help": "Descuento de seguros (médico, vida). No afecta TSS/ISR. Para descuentos fijos usa un movimiento recurrente."},
    {"tab": "otros_fijos",           "concept": "DESCUENTO_RECURRENTE", "label": "Otros descuentos fijos",   "hours": False,
     "help": "Otros descuentos fijos del período (cooperativa, fondo de ahorro, etc.). No afecta TSS/ISR."},
    {"tab": "descuentos_variables",  "concept": "OTRAS_DEDUCCIONES",    "label": "Descuentos variables",    "hours": False,
     "help": "Cualquier otro descuento puntual del período. No afecta TSS/ISR."},
]

VARIABLE_TAB_BY_CONCEPT = {t["concept"]: t for t in VARIABLE_TABS}
# Alias legacy: OTROS_INGRESOS (manual) se muestra en el tab Ingresos variables
VARIABLE_TAB_BY_CONCEPT["OTROS_INGRESOS"] = next(t for t in VARIABLE_TABS if t["tab"] == "ingresos_variables")
VARIABLE_CONCEPT_CODES = [t["concept"] for t in VARIABLE_TABS]

# Conceptos con gestión de movimientos recurrentes desde el tab (clave por concepto)
RECURRING_MANAGED_BY_CONCEPT = {
    "DESC_CXC": ["DESC_CXC", "PRESTAMO", "COOPERATIVA"],
    "SEGURO": ["SEGURO"],
    "DESCUENTO_RECURRENTE": ["DESCUENTO_RECURRENTE", "OTRAS_DEDUCCIONES", "FONDO_AHORRO", "APORTE_ESPECIAL"],
}

# Ayuda contextual por concepto (semilla; los conceptos pueden traer help propio)
HELP_BY_CONCEPT = {t["concept"]: t.get("help", "") for t in VARIABLE_TABS if t.get("help")}

# Conceptos cuyo valor se captura en horas
HOURS_CONCEPTS = {"HORAS_EXTRA"}

# Compatibilidad: RECURRING_MANAGED_TABS (clave por tab legacy)
RECURRING_MANAGED_TABS = {
    "cxc": RECURRING_MANAGED_BY_CONCEPT["DESC_CXC"],
    "seguro": RECURRING_MANAGED_BY_CONCEPT["SEGURO"],
    "otros_fijos": RECURRING_MANAGED_BY_CONCEPT["DESCUENTO_RECURRENTE"],
}

INGRESO_TABS = [t for t in VARIABLE_TABS if t["concept"] not in
                ("DESC_CXC", "SEGURO", "DESCUENTO_RECURRENTE", "OTRAS_DEDUCCIONES")]
DESCUENTO_TABS = [t for t in VARIABLE_TABS if t["concept"] in
                  ("DESC_CXC", "SEGURO", "DESCUENTO_RECURRENTE", "OTRAS_DEDUCCIONES")]

# Conceptos de ingreso que YA se reportan en columnas propias de la línea
# (salario base, horas extra, comisión, bonificación, regalía).
# Todo lo demás (OTROS_INGRESOS, INGRESO_VARIABLE, conceptos custom, etc.)
# se clasifica como "otros ingresos".
CLASSIFIED_EARNING_CONCEPTS = {
    "SALARIO_BASE", "HORAS_EXTRA", "HE_DIURNA", "HE_FERIADO", "NOCTURNIDAD",
    "COMISION", "BONIFICACION", "REGALIA_PASCUAL",
}

# Deducciones legales que se reportan en columnas propias (TSS/ISR).
TSS_ISR_DEDUCTION_CONCEPTS = {
    "AFP_EMPLEADO", "SFS_EMPLEADO", "ISR_RETENCION", "INFOTEP_EMPLEADO",
    "DESC_LICENCIA",
}

# Conceptos de ingreso variable que se reportan como "otros ingresos" en la línea
EXTRA_OTHER_INCOME_CONCEPTS = (
    "INCENTIVO_BENEFICIO", "DIF_VACACIONES", "SALARIO_RETROACTIVO", "INGRESO_VARIABLE",
)

# Conceptos de descuento variable que se reportan como "otras deducciones" en la línea
EXTRA_OTHER_DEDUCTION_CONCEPTS = ("DESC_CXC", "SEGURO", "DESCUENTO_RECURRENTE")

# Mapeo de override de grupo → concepto estándar
GROUP_OVERRIDE_BY_CONCEPT = {
    "HORAS_EXTRA": "includeOvertime",
    "COMISION": "includeCommission",
    "BONIFICACION": "includeBonus",
    "OTROS_INGRESOS": "includeOtherIncome",
}

# Nombres legacy de inputs → concepto estándar
LEGACY_INPUT_MAP = {
    "overtime": "HORAS_EXTRA",
    "commission": "COMISION",
    "bonus": "BONIFICACION",
    "other_income": "OTROS_INGRESOS",
    "other_ded": "OTRAS_DEDUCCIONES",
}
