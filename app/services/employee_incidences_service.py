"""EmployeeIncidencesService — Vista de incidencias de datos de empleados.

Detecta, para cada empleado vigente (activo/vacaciones/licencia), los campos
faltantes o inválidos que impiden o degradan los procesos de nómina y la
generación de reportes obligatorios (TSS, DGT, IR-13/IR-18).

Cada regla declara:
    key        — identificador estable (para filtros/tests)
    label      — nombre del campo legible
    process    — proceso/reporte afectado (agrupador visual y de filtro)
    severity   — "bloqueante" | "requerido" | "advertencia"
    description— mensaje mostrado al usuario
    check(emp) — True si el campo FALTA (hay incidencia)

No se duplica lógica de cálculo de negocio: las reglas sólo verifican presencia
y validez de datos de entrada, en línea con las validaciones existentes
(validate_employees_before_payroll, validate_ir18_readiness, validate_rd_export).
"""

from app.utils.hr_utils import is_active_equivalent

# ── Severidades ─────────────────────────────────────────────────────────────
BLOQUEANTE = "bloqueante"     # impide calcular/pagar la nómina
REQUERIDO = "requerido"       # impide generar un archivo TSS/DGT/IR válido
ADVERTENCIA = "advertencia"   # recomendado, no bloquea ningún proceso

SEVERITY_ORDER = {BLOQUEANTE: 0, REQUERIDO: 1, ADVERTENCIA: 2}

SEVERITY_LABELS = {
    BLOQUEANTE: "Bloqueante",
    REQUERIDO: "Requerido para reporte",
    ADVERTENCIA: "Advertencia",
}


def _clean_doc(doc) -> str:
    """Limpia documento: solo dígitos, sin guiones ni espacios."""
    return "".join(c for c in (doc or "") if c.isdigit())


def _has(emp, field) -> bool:
    """True si el campo existe y no está vacío (cadena/numérico distinto de cero)."""
    val = emp.get(field)
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    return bool(val)


def _missing(emp, field) -> bool:
    return not _has(emp, field)


def _is_transfer(emp) -> bool:
    pm = (emp.get("paymentMethod") or "").strip().lower()
    return pm in ("transferencia", "ach")


def _is_temporal(emp) -> bool:
    return (emp.get("contractType") or "") in ("tiempo_definido", "temporal", "obra_servicio")


# ── Catálogo de reglas (empleado) ───────────────────────────────────────────
EMPLOYEE_RULES = [
    # ── Bloqueantes: nómina ──
    {
        "key": "afp_provider", "label": "AFP", "process": "Nómina", "severity": BLOQUEANTE,
        "description": "No tiene AFP asignada. La nómina no puede calcularse sin AFP.",
        "check": lambda e: _missing(e, "afpProvider"),
    },
    {
        "key": "tss_key", "label": "Clave nómina TSS", "process": "Nómina", "severity": BLOQUEANTE,
        "description": "Falta la clave de nómina TSS. Necesaria para generar archivos de pago y reportes.",
        "check": lambda e: _missing(e, "tssKey"),
    },
    {
        "key": "base_salary", "label": "Salario base", "process": "Nómina", "severity": BLOQUEANTE,
        "description": "Salario base en cero o no definido.",
        "check": lambda e: float(e.get("baseSalary") or e.get("salary", 0) or 0) <= 0,
    },
    {
        "key": "payment_method", "label": "Método de pago", "process": "Nómina", "severity": BLOQUEANTE,
        "description": "No tiene un método de pago asignado.",
        "check": lambda e: _missing(e, "paymentMethod"),
    },
    {
        "key": "bank_account", "label": "Cuenta / banco", "process": "Nómina", "severity": BLOQUEANTE,
        "description": "Seleccionó transferencia pero no tiene número de cuenta y/o banco.",
        "check": lambda e: _is_transfer(e) and (_missing(e, "accountNumber") or _missing(e, "bank")),
    },

    # ── Requeridos para reportes TSS / DGT / IR ──
    {
        "key": "cedula", "label": "Cédula / documento", "process": "TSS / DGT / IR", "severity": REQUERIDO,
        "description": "Sin cédula/documento de identidad (11 dígitos). Requerido para TSS, DGT e IR.",
        "check": lambda e: len(_clean_doc(e.get("cedula") or e.get("idNumber"))) < 11,
    },
    {
        "key": "occupation_code", "label": "Código ocupación (CNO-2019)", "process": "DGT / IR-18", "severity": REQUERIDO,
        "description": "Sin código de ocupación CNO-2019. Requerido para DGT-3 y IR-18.",
        "check": lambda e: _missing(e, "occupationCode"),
    },
    {
        "key": "sirla_education_code", "label": "Nivel educativo SIRLA", "process": "DGT (SIRLA)", "severity": REQUERIDO,
        "description": "Sin código educativo oficial SIRLA. Requerido para DGT-2/3/4/5.",
        "check": lambda e: _missing(e, "sirlaEducationCode"),
    },
    {
        "key": "sdss_number", "label": "Nº Seguridad Social (SDSS)", "process": "DGT / TSS", "severity": REQUERIDO,
        "description": "Sin número SDSS ni registro TSS. Requerido para DGT-2 y DGT-3.",
        "check": lambda e: _missing(e, "sdssNumber") and _missing(e, "tssRegistrationNumber"),
    },
    {
        "key": "nationality", "label": "Nacionalidad", "process": "DGT / IR-18", "severity": REQUERIDO,
        "description": "Sin nacionalidad. Requerida para DGT-3 y IR-18.",
        "check": lambda e: not _has(e, "nationality"),
    },
    {
        "key": "gender", "label": "Género", "process": "DGT / TSS", "severity": REQUERIDO,
        "description": "Sin género. Requerido para DGT-3 y archivo de novedades TSS.",
        "check": lambda e: _missing(e, "gender"),
    },
    {
        "key": "birth_date", "label": "Fecha de nacimiento", "process": "DGT / TSS", "severity": REQUERIDO,
        "description": "Sin fecha de nacimiento. Requerida para DGT-3 y archivo de novedades TSS.",
        "check": lambda e: _missing(e, "birthDate"),
    },
    {
        "key": "marital_status", "label": "Estado civil", "process": "DGT-3", "severity": REQUERIDO,
        "description": "Sin estado civil. Requerido para DGT-3.",
        "check": lambda e: _missing(e, "maritalStatus"),
    },
    {
        "key": "hire_date", "label": "Fecha de ingreso", "process": "DGT", "severity": REQUERIDO,
        "description": "Sin fecha de ingreso. Requerida para DGT-3/4/5.",
        "check": lambda e: _missing(e, "hireDate"),
    },
    {
        "key": "contract_type", "label": "Tipo de contrato", "process": "DGT", "severity": REQUERIDO,
        "description": "Sin tipo de contrato. Requerido para clasificar DGT-3 y DGT-5.",
        "check": lambda e: _missing(e, "contractType"),
    },
    {
        "key": "weekly_hours", "label": "Horas semanales", "process": "DGT-2/3", "severity": REQUERIDO,
        "description": "Sin horas semanales. Requeridas para DGT-2 y DGT-3.",
        "check": lambda e: not _has(e, "weeklyHours"),
    },
    {
        "key": "work_shift", "label": "Turno de trabajo", "process": "DGT-3", "severity": REQUERIDO,
        "description": "Sin turno de trabajo. Requerido para DGT-3.",
        "check": lambda e: not _has(e, "workShift"),
    },
    {
        "key": "vacation_granted", "label": "Concesión de vacaciones", "process": "DGT-3", "severity": REQUERIDO,
        "description": "Sin concesión de vacaciones. Requerida para DGT-3.",
        "check": lambda e: not _has(e, "vacationGranted"),
    },
    {
        "key": "temporal_days_salary", "label": "Días trabajados / salario diario", "process": "DGT-5", "severity": REQUERIDO,
        "description": "Personal temporal sin días trabajados ni salario diario. Requerido para DGT-5.",
        "check": lambda e: _is_temporal(e) and (not _has(e, "daysWorked") or not _has(e, "dailySalary")),
    },

    # ── Advertencias: datos de contacto ──
    {
        "key": "email", "label": "Correo electrónico", "process": "Datos de contacto", "severity": ADVERTENCIA,
        "description": "Sin correo electrónico.",
        "check": lambda e: _missing(e, "email"),
    },
    {
        "key": "phone", "label": "Teléfono", "process": "Datos de contacto", "severity": ADVERTENCIA,
        "description": "Sin teléfono.",
        "check": lambda e: _missing(e, "phone"),
    },
    {
        "key": "address", "label": "Dirección", "process": "Datos de contacto", "severity": ADVERTENCIA,
        "description": "Sin dirección.",
        "check": lambda e: _missing(e, "address"),
    },
    {
        "key": "municipality", "label": "Municipio", "process": "Datos de contacto", "severity": ADVERTENCIA,
        "description": "Sin municipio.",
        "check": lambda e: _missing(e, "municipality"),
    },
    {
        "key": "emergency_contact", "label": "Contacto de emergencia", "process": "Datos de contacto", "severity": ADVERTENCIA,
        "description": "Sin contacto de emergencia.",
        "check": lambda e: _missing(e, "emergencyContact"),
    },
]


# ── Reglas de dependientes (archivo TSS RD) ─────────────────────────────────
_DEPENDENT_RULES = [
    {
        "key": "dependent_doc_type", "label": "Tipo de documento del dependiente", "process": "TSS RD (Dependientes)", "severity": REQUERIDO,
        "description": "Dependiente con tipo de documento inválido (debe ser C o N).",
        "check": lambda d: (d.get("docType") or "") not in ("C", "N"),
    },
    {
        "key": "dependent_id", "label": "Documento del dependiente", "process": "TSS RD (Dependientes)", "severity": REQUERIDO,
        "description": "Dependiente sin documento de identidad.",
        "check": lambda d: not _clean_doc(d.get("idNumber")),
    },
    {
        "key": "dependent_relationship", "label": "Parentesco del dependiente", "process": "TSS RD (Dependientes)", "severity": REQUERIDO,
        "description": "Dependiente sin parentesco registrado.",
        "check": lambda d: _missing(d, "relationshipCode"),
    },
]


def _evaluate_employee(emp: dict) -> list:
    """Evalúa todas las reglas de empleado y devuelve la lista de incidencias."""
    incidences = []
    for rule in EMPLOYEE_RULES:
        try:
            if rule["check"](emp):
                incidences.append({
                    "key": rule["key"],
                    "field": rule["label"],
                    "process": rule["process"],
                    "severity": rule["severity"],
                    "description": rule["description"],
                })
        except Exception:
            continue
    return incidences


def _evaluate_dependents(dependents: list) -> list:
    """Evalúa las reglas de dependientes (solo dependientes activos)."""
    incidences = []
    for dep in dependents:
        if not dep.get("active", True):
            continue
        for rule in _DEPENDENT_RULES:
            try:
                if rule["check"](dep):
                    name = " ".join(p for p in [dep.get("firstName", ""), dep.get("firstLastName", "")] if p).strip()
                    incidences.append({
                        "key": rule["key"],
                        "field": rule["label"],
                        "process": rule["process"],
                        "severity": rule["severity"],
                        "description": rule["description"] + (f" ({name})" if name else ""),
                        "dependent": name or dep.get("id", ""),
                    })
            except Exception:
                continue
    return incidences


def get_incidences(company_id: str, sandbox: bool = True) -> dict:
    """Calcula las incidencias de todos los empleados vigentes.

    Returns:
        {
            "items": [{"employeeId", "name", "code", "cedula", "status",
                       "incidences": [...], "count", "blocking"}],
            "summary": {"totalActive", "withIncidences", "blocking", "required",
                        "advertencia", "byProcess": [...], "bySeverity": [...]},
        }
    """
    from app.services import hr_data_service as hr

    employees = hr.get_employees(company_id, sandbox=sandbox)
    active = [e for e in employees if is_active_equivalent(e.get("status", ""))]
    active_ids = [e.get("id", "") for e in active if e.get("id")]

    dependents_map = hr.get_dependents_for_employees(company_id, active_ids, sandbox=sandbox) if active_ids else {}

    items = []
    for emp in active:
        emp_id = emp.get("id", "")
        name = emp.get("fullName") or " ".join(
            p for p in [emp.get("firstName", ""), emp.get("firstLastName", emp.get("lastName", ""))] if p
        ).strip() or emp_id

        incidences = _evaluate_employee(emp)
        incidences.extend(_evaluate_dependents(dependents_map.get(emp_id, [])))
        incidences.sort(key=lambda i: (SEVERITY_ORDER.get(i["severity"], 9), i["process"], i["field"]))

        has_blocking = any(i["severity"] == BLOQUEANTE for i in incidences)
        items.append({
            "employeeId": emp_id,
            "name": name,
            "code": emp.get("code", ""),
            "cedula": emp.get("cedula") or emp.get("idNumber", ""),
            "status": emp.get("status", ""),
            "incidences": incidences,
            "count": len(incidences),
            "blocking": has_blocking,
        })

    items.sort(key=lambda i: (-i["blocking"], -i["count"], i["name"]))

    total_active = len(items)
    with_incidences = [i for i in items if i["count"] > 0]
    blocking = sum(1 for i in items if i["blocking"])
    required = sum(
        1 for i in items
        if any(inc["severity"] == REQUERIDO for inc in i["incidences"])
        and not i["blocking"]
    )
    advertencia = sum(
        1 for i in items
        if i["count"] > 0 and not i["blocking"]
        and all(inc["severity"] == ADVERTENCIA for inc in i["incidences"])
    )

    by_process = {}
    by_severity = {BLOQUEANTE: 0, REQUERIDO: 0, ADVERTENCIA: 0}
    for i in with_incidences:
        for inc in i["incidences"]:
            by_severity[inc["severity"]] = by_severity.get(inc["severity"], 0) + 1
            by_process[inc["process"]] = by_process.get(inc["process"], 0) + 1

    summary = {
        "totalActive": total_active,
        "withIncidences": len(with_incidences),
        "blocking": blocking,
        "required": required,
        "advertencia": advertencia,
        "byProcess": [{"process": k, "count": v} for k, v in
                      sorted(by_process.items(), key=lambda x: -x[1])],
        "bySeverity": by_severity,
    }

    return {"items": items, "summary": summary}


def get_employee_incidences(company_id: str, employee_id: str, sandbox: bool = True) -> list:
    """Incidencias de un empleado puntual (incluye dependientes activos)."""
    from app.services import hr_data_service as hr

    emp = hr.get_employee(company_id, employee_id, sandbox=sandbox)
    if not emp:
        return []

    dependents_map = hr.get_dependents_for_employees(company_id, [employee_id], sandbox=sandbox)
    incidences = _evaluate_employee(emp)
    incidences.extend(_evaluate_dependents(dependents_map.get(employee_id, [])))
    incidences.sort(key=lambda i: (SEVERITY_ORDER.get(i["severity"], 9), i["process"], i["field"]))
    return incidences
