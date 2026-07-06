"""PayrollConceptService — Motor de conceptos configurables para nómina."""

from app.services.db_service import db_firestore, firebase_initialized

DEFAULT_CONCEPTS = [
    {"code": "SALARIO_BASE", "name": "Salario base", "type": "earning", "category": "fixed",
     "taxable": True, "affects_afp": True, "affects_sfs": True, "affects_isr": True,
     "account_debit": "6.2.1.01", "account_credit": "2.1.2.1.02", "priority": 1, "active": True},
    {"code": "HORAS_EXTRA", "name": "Horas extra", "type": "earning", "category": "variable",
     "taxable": True, "affects_afp": True, "affects_sfs": True, "affects_isr": True,
     "account_debit": "6.2.1.02", "account_credit": "2.1.2.1.02", "priority": 10, "active": True},
    {"code": "COMISION", "name": "Comisión", "type": "earning", "category": "variable",
     "taxable": True, "affects_afp": True, "affects_sfs": True, "affects_isr": True,
     "account_debit": "6.2.1.03", "account_credit": "2.1.2.1.02", "priority": 20, "active": True},
    {"code": "BONIFICACION", "name": "Bonificación", "type": "earning", "category": "variable",
     "taxable": True, "affects_afp": True, "affects_sfs": True, "affects_isr": True,
     "account_debit": "6.2.1.04", "account_credit": "2.1.2.1.02", "priority": 30, "active": True},
    {"code": "OTROS_INGRESOS", "name": "Otros ingresos", "type": "earning", "category": "variable",
     "taxable": True, "affects_afp": True, "affects_sfs": True, "affects_isr": True,
     "account_debit": "6.2.1.01", "account_credit": "2.1.2.1.02", "priority": 40, "active": True},
    {"code": "AFP_EMPLEADO", "name": "AFP empleado", "type": "deduction", "category": "fixed",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "account_debit": "2.1.2.1.05", "account_credit": "2.1.2.1.02", "priority": 100, "active": True},
    {"code": "SFS_EMPLEADO", "name": "SFS empleado", "type": "deduction", "category": "fixed",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "account_debit": "2.1.2.1.06", "account_credit": "2.1.2.1.02", "priority": 110, "active": True},
    {"code": "ISR_RETENCION", "name": "ISR retención", "type": "deduction", "category": "formula",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "account_debit": "2.1.2.1.08", "account_credit": "2.1.2.1.02", "priority": 120, "active": True},
    {"code": "OTRAS_DEDUCCIONES", "name": "Otras deducciones", "type": "deduction", "category": "variable",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "account_debit": "2.1.2.1.02", "account_credit": "2.1.2.1.02", "priority": 200, "active": True},
    {"code": "AFP_EMPLEADOR", "name": "AFP empleador", "type": "employer_contrib", "category": "fixed",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "account_debit": "6.2.1.01", "account_credit": "2.1.2.1.10", "priority": 300, "active": True},
    {"code": "SFS_EMPLEADOR", "name": "SFS empleador", "type": "employer_contrib", "category": "fixed",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "account_debit": "6.2.1.01", "account_credit": "2.1.2.1.09", "priority": 310, "active": True},
    {"code": "SRL_EMPLEADOR", "name": "SRL empleador", "type": "employer_contrib", "category": "fixed",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "account_debit": "6.2.1.01", "account_credit": "2.1.2.1.11", "priority": 320, "active": True},
    {"code": "INFOTEP_EMPLEADOR", "name": "INFOTEP empleador", "type": "employer_contrib", "category": "fixed",
     "taxable": False, "affects_afp": False, "affects_sfs": False, "affects_isr": False,
     "account_debit": "6.2.1.01", "account_credit": "2.1.2.1.12", "priority": 330, "active": True},
]


def _concepts_collection(owner_uid: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"users/{owner_uid}/{prefix}hr_payroll_concepts"


def get_concepts(owner_uid: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return DEFAULT_CONCEPTS
    try:
        coll = _concepts_collection(owner_uid, sandbox)
        docs = db_firestore.collection(coll).get()
        concepts = [d.to_dict() for d in docs]
        if not concepts:
            seed_default_concepts(owner_uid, sandbox=sandbox)
            return DEFAULT_CONCEPTS
        return sorted(concepts, key=lambda c: c.get("priority", 99))
    except Exception as e:
        print(f"⚠️ PayrollConceptService.get_concepts: {e}")
        return DEFAULT_CONCEPTS


def get_concept(owner_uid: str, concept_id: str, sandbox: bool = True) -> dict | None:
    if not firebase_initialized or db_firestore is None:
        return None
    try:
        coll = _concepts_collection(owner_uid, sandbox)
        doc = db_firestore.collection(coll).document(concept_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        print(f"⚠️ PayrollConceptService.get_concept: {e}")
        return None


def save_concept(owner_uid: str, data: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _concepts_collection(owner_uid, sandbox)
        db_firestore.collection(coll).document(data["code"]).set(data)
    except Exception as e:
        print(f"⚠️ PayrollConceptService.save_concept: {e}")


def delete_concept(owner_uid: str, concept_code: str, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _concepts_collection(owner_uid, sandbox)
        db_firestore.collection(coll).document(concept_code).delete()
    except Exception as e:
        print(f"⚠️ PayrollConceptService.delete_concept: {e}")


def seed_default_concepts(owner_uid: str, sandbox: bool = True):
    for c in DEFAULT_CONCEPTS:
        save_concept(owner_uid, c, sandbox=sandbox)
