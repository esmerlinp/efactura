"""PayrollConceptService — Motor de conceptos configurables para nómina.

Cada concepto define:
  - Cómo se clasifica (earning/deduction/employer_contrib)
  - Su impacto fiscal (ISR, TSS)
  - Sus cuentas contables
  - Si es protegido por el sistema (no se puede eliminar)
  - Si soporta movimientos recurrentes
"""

from datetime import datetime, timezone

from app.services.db_service import db_firestore, firebase_initialized, DatabaseService

# ── Conceptos del sistema (no pueden eliminarse, solo desactivarse) ──
SYSTEM_CONCEPT_CODES = {
    "SALARIO_BASE", "AFP_EMPLEADO", "SFS_EMPLEADO", "ISR_RETENCION",
    "AFP_EMPLEADOR", "SFS_EMPLEADOR", "SRL_EMPLEADOR", "INFOTEP_EMPLEADOR",
    "INFOTEP_EMPLEADO",     "HORAS_EXTRA", "HE_DIURNA", "HE_NOCTURNA", "HE_FERIADO",
    "COMISION", "BONIFICACION",
    "OTROS_INGRESOS", "OTRAS_DEDUCCIONES",
}

# ── Conceptos que pueden vincularse a movimientos recurrentes ──
RECURRING_CAPABLE_CODES = {
    "INCENTIVO_FIJO", "ASIGNACION", "BENEFICIO_FIJO", "INGRESO_RECURRENTE",
    "PRESTAMO", "COOPERATIVA", "SEGURO", "FONDO_AHORRO",
    "EMBARGO", "DESCUENTO_RECURRENTE", "APORTE_ESPECIAL", "BENEFICIO_CORP",
}

DEFAULT_CONCEPTS = [
    # ═══════════════════════════════════════════════════════════════════
    # INGRESOS (earning)
    # ═══════════════════════════════════════════════════════════════════
    {"code": "SALARIO_BASE",        "name": "Salario base",
     "type": "earning", "category": "fixed",
     "taxable": True, "affects_afp": True, "affects_sfs": True, "affects_isr": True,
     "account_debit": "6.2.1.01", "account_credit": "2.1.2.1.02",
     "priority": 1, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": False, "maxPercentage": 0.0},

    {"code": "HORAS_EXTRA",        "name": "Horas extra",
     "type": "earning", "category": "variable",
     "taxable": True, "affects_afp": True, "affects_sfs": True, "affects_isr": True,
     "accountDebit": "6.2.1.02", "account_credit": "2.1.2.1.02",
     "priority": 10, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": False, "maxPercentage": 0.0},

    {"code": "HE_DIURNA",          "name": "Hora extra diurna",
     "type": "earning", "category": "variable",
     "taxable": True, "affects_afp": True, "affects_sfs": True, "affects_isr": True,
     "accountDebit": "6.2.1.02", "account_credit": "2.1.2.1.02",
     "priority": 11, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": False, "maxPercentage": 0.0,
     "calculationMethod": "overtime", "factor": 1.35},

    {"code": "HE_NOCTURNA",        "name": "Hora extra nocturna",
     "type": "earning", "category": "variable",
     "taxable": True, "affects_afp": True, "affects_sfs": True, "affects_isr": True,
     "accountDebit": "6.2.1.02", "account_credit": "2.1.2.1.02",
     "priority": 12, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": False, "maxPercentage": 0.0,
     "calculationMethod": "overtime", "factor": 1.50},

    {"code": "HE_FERIADO",         "name": "Hora extra feriado / descanso",
     "type": "earning", "category": "variable",
     "taxable": True, "affects_afp": True, "affects_sfs": True, "affects_isr": True,
     "accountDebit": "6.2.1.02", "account_credit": "2.1.2.1.02",
     "priority": 13, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": False, "maxPercentage": 0.0,
     "calculationMethod": "overtime", "factor": 2.00},

    {"code": "COMISION",           "name": "Comisión",
     "type": "earning", "category": "variable",
     "taxable": True, "affects_afp": True, "affects_sfs": True, "affects_isr": True,
     "accountDebit": "6.2.1.03", "account_credit": "2.1.2.1.02",
     "priority": 20, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": False, "maxPercentage": 0.0},

    {"code": "BONIFICACION",       "name": "Bonificación",
     "type": "earning", "category": "variable",
     "taxable": True, "affects_afp": True, "affects_sfs": True, "affects_isr": True,
     "accountDebit": "6.2.1.04", "account_credit": "2.1.2.1.02",
     "priority": 30, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": False, "maxPercentage": 0.0},

    {"code": "OTROS_INGRESOS",     "name": "Otros ingresos",
     "type": "earning", "category": "variable",
     "taxable": True, "affects_afp": True, "affects_sfs": True, "affects_isr": True,
     "accountDebit": "6.2.1.01", "account_credit": "2.1.2.1.02",
     "priority": 40, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": False, "maxPercentage": 0.0},

    # ═══════════════════════════════════════════════════════════════════
    # INGRESOS RECURRENTES (earning, pueden usarse en mov. recurrentes)
    # ═══════════════════════════════════════════════════════════════════
    {"code": "INCENTIVO_FIJO",     "name": "Incentivo fijo",
     "type": "earning", "category": "recurring",
     "taxable": True, "affects_afp": True, "affects_sfs": True, "affects_isr": True,
     "accountDebit": "6.2.1.01", "account_credit": "2.1.2.1.02",
     "priority": 5, "active": True, "isSystem": False,
     "isRecurringCapable": True, "isLegalMandatory": False, "maxPercentage": 0.0},

    {"code": "ASIGNACION",         "name": "Asignación",
     "type": "earning", "category": "recurring",
     "taxable": True, "affects_afp": False, "affects_sfs": False, "affects_isr": True,
     "accountDebit": "6.2.1.01", "account_credit": "2.1.2.1.02",
     "priority": 6, "active": True, "isSystem": False,
     "isRecurringCapable": True, "isLegalMandatory": False, "maxPercentage": 0.0},

    {"code": "BENEFICIO_FIJO",     "name": "Beneficio fijo",
     "type": "earning", "category": "recurring",
     "taxable": True, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "6.2.1.01", "account_credit": "2.1.2.1.02",
     "priority": 7, "active": True, "isSystem": False,
     "isRecurringCapable": True, "isLegalMandatory": False, "maxPercentage": 0.0},

    {"code": "INGRESO_RECURRENTE", "name": "Ingreso recurrente",
     "type": "earning", "category": "recurring",
     "taxable": True, "affects_afp": True, "affects_sfs": True, "affects_isr": True,
     "accountDebit": "6.2.1.01", "account_credit": "2.1.2.1.02",
     "priority": 8, "active": True, "isSystem": False,
     "isRecurringCapable": True, "isLegalMandatory": False, "maxPercentage": 0.0},

    # ═══════════════════════════════════════════════════════════════════
    # DESCUENTOS (deduction)
    # ═══════════════════════════════════════════════════════════════════
    {"code": "AFP_EMPLEADO",       "name": "AFP empleado",
     "type": "deduction", "category": "tss",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "2.1.2.1.05", "account_credit": "2.1.2.1.02",
     "priority": 100, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": True, "maxPercentage": 0.0},

    {"code": "SFS_EMPLEADO",       "name": "SFS empleado",
     "type": "deduction", "category": "tss",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "2.1.2.1.06", "account_credit": "2.1.2.1.02",
     "priority": 110, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": True, "maxPercentage": 0.0},

    {"code": "ISR_RETENCION",      "name": "ISR retención",
     "type": "deduction", "category": "isr",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "2.1.2.1.08", "account_credit": "2.1.2.1.02",
     "priority": 120, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": True, "maxPercentage": 0.0},

    {"code": "INFOTEP_EMPLEADO",   "name": "INFOTEP empleado",
     "type": "deduction", "category": "tss",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "2.1.2.1.12", "account_credit": "2.1.2.1.02",
     "priority": 130, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": True, "maxPercentage": 0.0},

    {"code": "OTRAS_DEDUCCIONES",  "name": "Otras deducciones",
     "type": "deduction", "category": "variable",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "2.1.2.1.02", "account_credit": "2.1.2.1.02",
     "priority": 200, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": False, "maxPercentage": 0.0},

    # ═══════════════════════════════════════════════════════════════════
    # DESCUENTOS RECURRENTES (pueden moverse a RecurringMovement)
    # ═══════════════════════════════════════════════════════════════════
    {"code": "PRESTAMO",           "name": "Préstamo (cuota)",
     "type": "deduction", "category": "recurring",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "2.1.2.1.13", "account_credit": "2.1.2.1.02",
     "priority": 300, "active": True, "isSystem": False,
     "isRecurringCapable": True, "isLegalMandatory": False, "maxPercentage": 0.15},

    {"code": "COOPERATIVA",        "name": "Cooperativa",
     "type": "deduction", "category": "recurring",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "2.1.2.1.13", "account_credit": "2.1.2.1.02",
     "priority": 400, "active": True, "isSystem": False,
     "isRecurringCapable": True, "isLegalMandatory": False, "maxPercentage": 0.20},

    {"code": "SEGURO",             "name": "Seguro",
     "type": "deduction", "category": "recurring",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "2.1.2.1.13", "account_credit": "2.1.2.1.02",
     "priority": 350, "active": True, "isSystem": False,
     "isRecurringCapable": True, "isLegalMandatory": False, "maxPercentage": 0.0},

    {"code": "FONDO_AHORRO",       "name": "Fondo de ahorro",
     "type": "deduction", "category": "recurring",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "2.1.2.1.13", "account_credit": "2.1.2.1.02",
     "priority": 500, "active": True, "isSystem": False,
     "isRecurringCapable": True, "isLegalMandatory": False, "maxPercentage": 0.0},

    {"code": "EMBARGO",            "name": "Embargo",
     "type": "deduction", "category": "garnishment",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "2.1.2.1.13", "account_credit": "2.1.2.1.02",
     "priority": 250, "active": True, "isSystem": False,
     "isRecurringCapable": True, "isLegalMandatory": False, "maxPercentage": 0.30},

    {"code": "DESCUENTO_RECURRENTE", "name": "Descuento recurrente",
     "type": "deduction", "category": "recurring",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "2.1.2.1.13", "account_credit": "2.1.2.1.02",
     "priority": 450, "active": True, "isSystem": False,
     "isRecurringCapable": True, "isLegalMandatory": False, "maxPercentage": 0.0},

    # ═══════════════════════════════════════════════════════════════════
    # APORTES PATRONALES (employer_contrib)
    # ═══════════════════════════════════════════════════════════════════
    {"code": "AFP_EMPLEADOR",      "name": "AFP empleador",
     "type": "employer_contrib", "category": "tss",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "6.2.1.01", "account_credit": "2.1.2.1.10",
     "priority": 300, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": True, "maxPercentage": 0.0},

    {"code": "SFS_EMPLEADOR",      "name": "SFS empleador",
     "type": "employer_contrib", "category": "tss",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "6.2.1.01", "account_credit": "2.1.2.1.09",
     "priority": 310, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": True, "maxPercentage": 0.0},

    {"code": "SRL_EMPLEADOR",      "name": "SRL empleador",
     "type": "employer_contrib", "category": "tss",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "6.2.1.01", "account_credit": "2.1.2.1.11",
     "priority": 320, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": True, "maxPercentage": 0.0},

    {"code": "INFOTEP_EMPLEADOR",  "name": "INFOTEP empleador",
     "type": "employer_contrib", "category": "tss",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "6.2.1.01", "account_credit": "2.1.2.1.12",
     "priority": 330, "active": True, "isSystem": True,
     "isRecurringCapable": False, "isLegalMandatory": True, "maxPercentage": 0.0},

    # ═══════════════════════════════════════════════════════════════════
    # APORTES PATRONALES RECURRENTES
    # ═══════════════════════════════════════════════════════════════════
    {"code": "APORTE_ESPECIAL",    "name": "Aporte patronal especial",
     "type": "employer_contrib", "category": "recurring",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "6.2.1.01", "account_credit": "2.1.2.1.02",
     "priority": 340, "active": True, "isSystem": False,
     "isRecurringCapable": True, "isLegalMandatory": False, "maxPercentage": 0.0},

    {"code": "BENEFICIO_CORP",     "name": "Beneficio corporativo",
     "type": "employer_contrib", "category": "recurring",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "accountDebit": "6.2.1.01", "account_credit": "2.1.2.1.02",
     "priority": 350, "active": True, "isSystem": False,
     "isRecurringCapable": True, "isLegalMandatory": False, "maxPercentage": 0.0},
]


def _concepts_collection(company_id: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"companies/{company_id}/{prefix}hr_payroll_concepts"


def get_concepts(company_id: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return [dict(c) for c in DEFAULT_CONCEPTS]
    try:
        coll = _concepts_collection(company_id, sandbox)
        docs = db_firestore.collection(coll).get()
        concepts = [{"id": d.id, **d.to_dict()} for d in docs]
        if not concepts:
            seed_default_concepts(company_id, sandbox=sandbox)
            return [dict(c) for c in DEFAULT_CONCEPTS]

        default_by_code = {c["code"]: c for c in DEFAULT_CONCEPTS if c.get("isSystem")}
        existing_codes = {c["code"] for c in concepts}

        for c in concepts:
            if c["code"] in default_by_code:
                default = default_by_code[c["code"]]
                c["category"] = default["category"]

        for code, dc in default_by_code.items():
            if code not in existing_codes:
                c = dict(dc)
                c["id"] = code
                concepts.append(c)
                try:
                    db_firestore.collection(coll).document(code).set(dict(dc))
                except Exception:
                    pass

        return sorted(concepts, key=lambda c: c.get("priority", 99))
    except Exception as e:
        print(f"⚠️ PayrollConceptService.get_concepts: {e}")
        return [dict(c) for c in DEFAULT_CONCEPTS]


def get_active_recurring_concepts(company_id: str, sandbox: bool = True) -> list:
    """Retorna solo conceptos que soportan movimientos recurrentes y están activos."""
    all_concepts = get_concepts(company_id, sandbox=sandbox)
    return [c for c in all_concepts
            if c.get("isRecurringCapable") and c.get("active")]


def get_concept(company_id: str, concept_id: str, sandbox: bool = True) -> dict | None:
    if not firebase_initialized or db_firestore is None:
        return next((c for c in DEFAULT_CONCEPTS if c["code"] == concept_id), None)
    try:
        coll = _concepts_collection(company_id, sandbox)
        doc = db_firestore.collection(coll).document(concept_id).get()
        return {"id": doc.id, **doc.to_dict()} if doc.exists else None
    except Exception as e:
        print(f"⚠️ PayrollConceptService.get_concept: {e}")
        return next((c for c in DEFAULT_CONCEPTS if c["code"] == concept_id), None)


def get_concept_by_code(company_id: str, code: str, sandbox: bool = True) -> dict | None:
    """Busca un concepto por su código (el id es el mismo que el code)."""
    return get_concept(company_id, code, sandbox=sandbox)


def save_concept(company_id: str, data: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _concepts_collection(company_id, sandbox)
        concept_id = data.get("code", data.get("id", ""))
        if not concept_id:
            return

        # Proteger conceptos de sistema
        existing_doc = db_firestore.collection(coll).document(concept_id).get()
        existing = existing_doc.to_dict() if existing_doc.exists else None
        if existing and existing.get("isSystem") is True:
            protected = {"code", "type", "category", "isSystem", "isLegalMandatory"}
            for field in protected:
                data.pop(field, None)

        now_iso = datetime.now(timezone.utc).isoformat()
        if data.get("createdAt") is None:
            data["createdAt"] = now_iso
        data["updatedAt"] = now_iso
        data["code"] = concept_id

        db_firestore.collection(coll).document(concept_id).set(data)
    except Exception as e:
        print(f"⚠️ PayrollConceptService.save_concept: {e}")


def delete_concept(company_id: str, concept_code: str, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _concepts_collection(company_id, sandbox)
        doc = db_firestore.collection(coll).document(concept_code).get()
        if doc.exists:
            data = doc.to_dict()
            if data.get("isSystem"):
                print(f"⚠️ No se puede eliminar el concepto de sistema: {concept_code}")
                return
        db_firestore.collection(coll).document(concept_code).delete()
    except Exception as e:
        print(f"⚠️ PayrollConceptService.delete_concept: {e}")


def seed_default_concepts(company_id: str, sandbox: bool = True):
    for c in DEFAULT_CONCEPTS:
        save_concept(company_id, dict(c), sandbox=sandbox)


def build_concept_snapshot(concept: dict) -> dict:
    """Construye el snapshot de un concepto para almacenar en PayrollTransaction.

    Este snapshot congela el estado del concepto al momento de la transacción,
    garantizando que las nóminas históricas sean auditables aunque el concepto
    cambie años después.
    """
    return {
        "code": concept.get("code", ""),
        "name": concept.get("name", ""),
        "type": concept.get("type", ""),
        "category": concept.get("category", "fixed"),
        "affectsISR": concept.get("affects_isr", concept.get("affectsISR", True)),
        "affectsTSS": concept.get("affects_sfs", concept.get("affectsTSS", True)),
        "affectsNet": concept.get("type") == "deduction",
        "isLegalMandatory": concept.get("isLegalMandatory", False),
        "accountDebit": concept.get("account_debit", concept.get("accountDebit", "")),
        "accountCredit": concept.get("account_credit", concept.get("accountCredit", "")),
        "conceptVersion": concept.get("version", 1),
        "maxPercentage": concept.get("maxPercentage", 0.0),
    }