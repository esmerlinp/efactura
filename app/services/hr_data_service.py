"""
HRDataService — Capa de acceso a datos Firestore para módulo RRHH.

Usa el mismo patrón de conexión que DatabaseService pero aislado para HR.
Evita inflar aún más el DatabaseService monolítico.
"""

import uuid
from datetime import datetime, timezone
from google.cloud.firestore import FieldFilter
from app.services.db_service import db_firestore, firebase_initialized, DatabaseService


def _hr_company_path(company_id: str, collection: str, sandbox: bool = True) -> str | None:
    """Retorna el path companies/{companyId}/{sandbox_}hr_{collection}."""
    if not company_id:
        return None
    prefix = "sandbox_hr_" if sandbox else "hr_"
    return f"companies/{company_id}/{prefix}{collection}"


def _get_all(company_id: str, collection: str, sandbox: bool = True) -> list:
    """Obtiene todos los documentos de una colección HR desde companies/{companyId}/hr_*."""
    if not firebase_initialized or db_firestore is None:
        return []
    coll_path = _hr_company_path(company_id, collection, sandbox)
    if not coll_path:
        return []
    try:
        docs = db_firestore.collection(coll_path).get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ HRDataService._get_all({collection}): {e}")
        return []


def _get_paginated(company_id: str, collection: str, sandbox: bool = True,
                   limit: int = 100, start_after: str = None,
                   order_by: str = None, filters: dict = None) -> dict:
    """Obtiene documentos con paginación desde companies/{companyId}/hr_*."""
    if not firebase_initialized or db_firestore is None:
        return {"items": [], "cursor": None, "has_more": False}

    coll_path = _hr_company_path(company_id, collection, sandbox)
    if not coll_path:
        return {"items": [], "cursor": None, "has_more": False}

    try:
        query = db_firestore.collection(coll_path)

        if filters:
            for field, value in filters.items():
                query = query.where(field, "==", value)

        if order_by:
            query = query.order_by(order_by)
        elif start_after:
            query = query.order_by("__name__")

        if start_after:
            try:
                start_doc = db_firestore.collection(coll_path).document(start_after).get()
                if start_doc.exists:
                    query = query.start_after(start_doc)
            except Exception:
                pass

        query = query.limit(limit + 1)
        docs = query.get()
        doc_list = list(docs)
        has_more = len(doc_list) > limit
        items = [{"id": d.id, **d.to_dict()} for d in doc_list[:limit]]
        cursor = items[-1]["id"] if items else None

        return {"items": items, "cursor": cursor, "has_more": has_more}
    except Exception as e:
        print(f"⚠️ HRDataService._get_paginated({collection}): {e}")
        return {"items": [], "cursor": None, "has_more": False}


def _get_one(company_id: str, collection: str, doc_id: str, sandbox: bool = True) -> dict | None:
    """Obtiene un documento por ID desde companies/{companyId}/hr_*."""
    if not firebase_initialized or db_firestore is None:
        return None
    coll_path = _hr_company_path(company_id, collection, sandbox)
    if not coll_path:
        return None
    try:
        doc = db_firestore.collection(coll_path).document(doc_id).get()
        if doc.exists:
            return {"id": doc.id, **doc.to_dict()}
        return None
    except Exception as e:
        print(f"⚠️ HRDataService._get_one({collection}): {e}")
        return None


def _sanitize_for_firestore(obj, _path=""):
    """Convierte tipos no compatibles con Firestore: inf/nan/Decimal etc."""
    import math
    from decimal import Decimal
    if isinstance(obj, float):
        if math.isinf(obj) and obj > 0:
            return 999999999.0
        if math.isinf(obj) and obj < 0:
            return -999999999.0
        if math.isnan(obj):
            return 0.0
        return obj
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    if isinstance(obj, dict):
        return {k: _sanitize_for_firestore(v, f"{_path}.{k}") for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_firestore(item, f"{_path}[{i}]") for i, item in enumerate(obj)]
    if type(obj) not in (type(None), bool, int, str, bytes):
        print(f"  ⚠️ _sanitize: unexpected type at {_path}: {type(obj).__name__} = {obj!r:.200}")
    return obj


def get_tax_rates_snapshot(payroll_period: dict) -> dict:
    """Retorna taxRatesSnapshot como dict, compatible con guardado como JSON string."""
    import json
    trs = payroll_period.get("taxRatesSnapshot", {})
    if isinstance(trs, str):
        return json.loads(trs)
    return trs if isinstance(trs, dict) else {}


def _save(company_id: str, collection: str, doc_id: str, data: dict, sandbox: bool = True) -> bool:
    """Guarda (crea o actualiza) un documento en companies/{companyId}/hr_*."""
    if not firebase_initialized or db_firestore is None:
        print(f"⚠️ HRDataService._save({collection}): Firebase no inicializado")
        return False
    coll_path = _hr_company_path(company_id, collection, sandbox)
    if not coll_path:
        return False
    try:
        import json
        safe = _sanitize_for_firestore(data)
        ref = db_firestore.collection(coll_path).document(doc_id)
        trs = safe.pop("taxRatesSnapshot", None) if "taxRatesSnapshot" in safe else None
        if trs is not None:
            safe["taxRatesSnapshot"] = json.dumps(trs)
        ref.set(safe)
        return True
    except Exception as e:
        print(f"⚠️ HRDataService._save({collection}): {e}")
        return False


def _delete(company_id: str, collection: str, doc_id: str, sandbox: bool = True):
    """Elimina un documento de companies/{companyId}/hr_*."""
    if not firebase_initialized or db_firestore is None:
        return
    coll_path = _hr_company_path(company_id, collection, sandbox)
    if not coll_path:
        return
    try:
        db_firestore.collection(coll_path).document(doc_id).delete()
    except Exception as e:
        print(f"⚠️ HRDataService._delete({collection}): {e}")


# ═══════════════════════════════════════════════════════════════════════════
# EMPLOYEES
# ═══════════════════════════════════════════════════════════════════════════

def get_employees(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "employees", sandbox)

def get_employee(company_id: str, employee_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "employees", employee_id, sandbox)

def save_employee(company_id: str, employee_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "employees", employee_id, data, sandbox)

def delete_employee(company_id: str, employee_id: str, sandbox: bool = True):
    _delete(company_id, "employees", employee_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# ATTENDANCE
# ═══════════════════════════════════════════════════════════════════════════

def get_attendance_records(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "attendance", sandbox)

def get_attendance_record(company_id: str, record_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "attendance", record_id, sandbox)

def save_attendance_record(company_id: str, record_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "attendance", record_id, data, sandbox)

def delete_attendance_record(company_id: str, record_id: str, sandbox: bool = True):
    _delete(company_id, "attendance", record_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# VACATIONS
# ═══════════════════════════════════════════════════════════════════════════

def get_vacation_requests(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "vacations", sandbox)

def get_vacation_request(company_id: str, request_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "vacations", request_id, sandbox)

def save_vacation_request(company_id: str, request_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "vacations", request_id, data, sandbox)

def delete_vacation_request(company_id: str, request_id: str, sandbox: bool = True):
    _delete(company_id, "vacations", request_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# LEAVES
# ═══════════════════════════════════════════════════════════════════════════

def get_leave_requests(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "leaves", sandbox)

def get_leave_request(company_id: str, request_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "leaves", request_id, sandbox)

def save_leave_request(company_id: str, request_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "leaves", request_id, data, sandbox)

def delete_leave_request(company_id: str, request_id: str, sandbox: bool = True):
    _delete(company_id, "leaves", request_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# PAYROLL GROUPS
# ═══════════════════════════════════════════════════════════════════════════

def get_payroll_groups(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "payroll_groups", sandbox)

def get_payroll_group(company_id: str, group_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "payroll_groups", group_id, sandbox)

def save_payroll_group(company_id: str, group_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "payroll_groups", group_id, data, sandbox)

def delete_payroll_group(company_id: str, group_id: str, sandbox: bool = True):
    _delete(company_id, "payroll_groups", group_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# EMPLOYMENT CONTRACTS
# ═══════════════════════════════════════════════════════════════════════════

def get_contracts(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "employment_contracts", sandbox)

def get_contract(company_id: str, contract_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "employment_contracts", contract_id, sandbox)

def save_contract(company_id: str, contract_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "employment_contracts", contract_id, data, sandbox)

def delete_contract(company_id: str, contract_id: str, sandbox: bool = True):
    _delete(company_id, "employment_contracts", contract_id, sandbox)

def get_active_contracts_for_employee(company_id: str, employee_id: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_company_path(company_id, "employment_contracts", sandbox)
        docs = db_firestore.collection(coll_path) \
            .where("employeeId", "==", employee_id) \
            .where("status", "==", "activo") \
            .get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ HRDataService.get_active_contracts_for_employee: {e}")
        return []

def get_contracts_for_group(company_id: str, group_id: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_company_path(company_id, "employment_contracts", sandbox)
        docs = db_firestore.collection(coll_path) \
            .where("payrollGroupIds", "array_contains", group_id) \
            .where("status", "==", "activo") \
            .get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ HRDataService.get_contracts_for_group: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# PAYROLL
# ═══════════════════════════════════════════════════════════════════════════

def get_payroll_periods(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "payroll", sandbox)

def get_payroll_period(company_id: str, period_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "payroll", period_id, sandbox)

def save_payroll_period(company_id: str, period_id: str, data: dict, sandbox: bool = True) -> bool:
    return _save(company_id, "payroll", period_id, data, sandbox)

def delete_payroll_period(company_id: str, period_id: str, sandbox: bool = True):
    _delete(company_id, "payroll", period_id, sandbox)


def get_payroll_period_by_key(company_id: str, period_key: str, sandbox: bool = True) -> dict | None:
    if not firebase_initialized or db_firestore is None:
        return None
    try:
        coll_path = _hr_company_path(company_id, "payroll", sandbox)
        docs = db_firestore.collection(coll_path).where("periodKey", "==", period_key).limit(1).get()
        for d in docs:
            return {"id": d.id, **d.to_dict()}
    except Exception as e:
        print(f"⚠️ HRDataService.get_payroll_period_by_key: {e}")
    return None

def get_payroll_period_by_key_and_group(company_id: str, period_key: str, group_id: str, sandbox: bool = True) -> dict | None:
    if not firebase_initialized or db_firestore is None:
        return None
    try:
        coll_path = _hr_company_path(company_id, "payroll", sandbox)
        docs = db_firestore.collection(coll_path) \
            .where(filter=FieldFilter("periodKey", "==", period_key)) \
            .where(filter=FieldFilter("payrollGroupId", "==", group_id)) \
            .limit(1).get()
        for d in docs:
            return {"id": d.id, **d.to_dict()}
    except Exception as e:
        print(f"⚠️ HRDataService.get_payroll_period_by_key_and_group: {e}")
    return None


# ═══════════════════════════════════════════════════════════════════════════
# PAYROLL LINES — Subcolección hr_payroll/{periodId}/lines/{lineId}
# ═══════════════════════════════════════════════════════════════════════════

def _payroll_lines_subcollection(company_id: str, period_id: str, sandbox: bool = True) -> str:
    coll = _hr_company_path(company_id, "payroll", sandbox)
    return f"{coll}/{period_id}/lines"


def get_payroll_lines(company_id: str, period_id: str, sandbox: bool = True, limit: int = None) -> list:
    """Obtiene todas las líneas de nómina de un período desde la subcolección."""
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        sub_coll = _payroll_lines_subcollection(company_id, period_id, sandbox)
        query = db_firestore.collection(sub_coll)
        if limit:
            query = query.limit(limit)
        docs = query.get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ HRDataService.get_payroll_lines({period_id}): {e}")
        return []


def save_payroll_lines_batch(company_id: str, period_id: str, lines: list, sandbox: bool = True):
    """Guarda líneas de nómina en la subcolección usando batch write (máx 500 por batch)."""
    if not firebase_initialized or db_firestore is None or not lines:
        return
    try:
        sub_coll = _payroll_lines_subcollection(company_id, period_id, sandbox)
        batch_size = 400
        for i in range(0, len(lines), batch_size):
            batch = db_firestore.batch()
            chunk = lines[i:i + batch_size]
            for line in chunk:
                line_id = line.get("employeeId", str(uuid.uuid4().hex[:12]))
                doc_ref = db_firestore.collection(sub_coll).document(line_id)
                batch.set(doc_ref, line)
            batch.commit()
    except Exception as e:
        print(f"⚠️ HRDataService.save_payroll_lines_batch({period_id}): {e}")


def delete_payroll_lines(company_id: str, period_id: str, sandbox: bool = True):
    """Elimina todas las líneas de la subcolección de un período."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        lines = get_payroll_lines(company_id, period_id, sandbox=sandbox)
        sub_coll = _payroll_lines_subcollection(company_id, period_id, sandbox)
        for i in range(0, len(lines), 400):
            batch = db_firestore.batch()
            for line in lines[i:i + 400]:
                batch.delete(db_firestore.collection(sub_coll).document(line["id"]))
            batch.commit()
    except Exception as e:
        print(f"⚠️ HRDataService.delete_payroll_lines({period_id}): {e}")


def get_payroll_lines_unified(period: dict, company_id: str = "", sandbox: bool = True) -> list:
    if not company_id:
        return period.get("lines", [])
    period_id = period.get("id", "")
    if period_id:
        return get_payroll_lines(company_id, period_id, sandbox=sandbox)
    return period.get("lines", [])


# ═══════════════════════════════════════════════════════════════════════════
# EVALUATIONS
# ═══════════════════════════════════════════════════════════════════════════

def get_evaluations(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "evaluations", sandbox)

def get_evaluation(company_id: str, eval_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "evaluations", eval_id, sandbox)

def save_evaluation(company_id: str, eval_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "evaluations", eval_id, data, sandbox)

def delete_evaluation(company_id: str, eval_id: str, sandbox: bool = True):
    _delete(company_id, "evaluations", eval_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# TRAININGS
# ═══════════════════════════════════════════════════════════════════════════

def get_trainings(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "trainings", sandbox)

def get_training(company_id: str, training_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "trainings", training_id, sandbox)

def save_training(company_id: str, training_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "trainings", training_id, data, sandbox)

def delete_training(company_id: str, training_id: str, sandbox: bool = True):
    _delete(company_id, "trainings", training_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# PAYROLL CONFIG (frecuencia de pago, onboarding)
# ═══════════════════════════════════════════════════════════════════════════

def _config_collection(company_id: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"companies/{company_id}/{prefix}hr_config"


def get_payroll_config(company_id: str, sandbox: bool = True) -> dict:
    if not firebase_initialized or db_firestore is None:
        return {}
    try:
        coll = _config_collection(company_id, sandbox)
        doc = db_firestore.collection(coll).document("payroll").get()
        if doc.exists:
            return doc.to_dict()
    except Exception as e:
        print(f"⚠️ HRDataService.get_payroll_config: {e}")
    return {}


def save_payroll_config(company_id: str, data: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _config_collection(company_id, sandbox)
        db_firestore.collection(coll).document("payroll").set(data)
    except Exception as e:
        print(f"⚠️ HRDataService.save_payroll_config: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# REFERENCE DATA (tipos de contrato, áreas configurables)
# ═══════════════════════════════════════════════════════════════════════════

def get_reference_data(company_id: str, sandbox: bool = True) -> dict:
    if not firebase_initialized or db_firestore is None:
        return {}
    try:
        coll = _config_collection(company_id, sandbox)
        doc = db_firestore.collection(coll).document("reference_data").get()
        if doc.exists:
            return doc.to_dict()
    except Exception as e:
        print(f"⚠️ HRDataService.get_reference_data: {e}")
    return {}


def save_reference_data(company_id: str, data: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _config_collection(company_id, sandbox)
        db_firestore.collection(coll).document("reference_data").set(data)
    except Exception as e:
        print(f"⚠️ HRDataService.save_reference_data: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SALARY HISTORY
# ═══════════════════════════════════════════════════════════════════════════

def get_salary_history(company_id: str, employee_id: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_company_path(company_id, "salary_history", sandbox)
        docs = db_firestore.collection(coll_path).where("employeeId", "==", employee_id).get()
        results = [{"id": d.id, **d.to_dict()} for d in docs]
        results.sort(key=lambda r: r.get("effectiveDate", ""), reverse=True)
        return results
    except Exception as e:
        print(f"⚠️ HRDataService.get_salary_history: {e}")
        return []


def get_all_salary_history(company_id: str, sandbox: bool = True) -> list:
    """Obtiene todos los historiales salariales (sin filtrar por empleado)."""
    return _get_all(company_id, "salary_history", sandbox)


def get_current_salary(company_id: str, employee_id: str, sandbox: bool = True) -> float | None:
    history = get_salary_history(company_id, employee_id, sandbox=sandbox)
    active = [h for h in history if not h.get("endDate")]
    if active:
        return active[0].get("amount")
    if history:
        return history[0].get("amount")
    return None


def save_salary_history_entry(company_id: str, data: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_path = _hr_company_path(company_id, "salary_history", sandbox)
        doc_id = data.get("id", str(uuid.uuid4()))
        data["id"] = doc_id
        db_firestore.collection(coll_path).document(doc_id).set(data)
    except Exception as e:
        print(f"⚠️ HRDataService.save_salary_history_entry: {e}")


def close_previous_salary(company_id: str, employee_id: str, new_effective_date: str, sandbox: bool = True):
    history = get_salary_history(company_id, employee_id, sandbox=sandbox)
    active = [h for h in history if not h.get("endDate")]
    for h in active:
        h["endDate"] = new_effective_date
        coll_path = _hr_company_path(company_id, "salary_history", sandbox)
        db_firestore.collection(coll_path).document(h["id"]).set(h)


# ═══════════════════════════════════════════════════════════════════════════
# EMPLOYEE DOCUMENTS
# ═══════════════════════════════════════════════════════════════════════════

DOC_CATEGORIES = [
    "contract", "id", "certificate", "medical", "disciplinary", "academic", "other"
]

def get_employee_documents(company_id: str, employee_id: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_company_path(company_id, "employee_documents", sandbox)
        docs = db_firestore.collection(coll_path).where("employeeId", "==", employee_id).get()
        return sorted([{"id": d.id, **d.to_dict()} for d in docs],
                      key=lambda x: x.get("uploadedAt", ""), reverse=True)
    except Exception as e:
        print(f"⚠️ get_employee_documents: {e}")
        return []


def save_employee_document(company_id: str, data: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_path = _hr_company_path(company_id, "employee_documents", sandbox)
        doc_id = data.get("id", str(uuid.uuid4()))
        data["id"] = doc_id
        db_firestore.collection(coll_path).document(doc_id).set(data)
    except Exception as e:
        print(f"⚠️ save_employee_document: {e}")


def delete_employee_document(company_id: str, doc_id: str, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_path = _hr_company_path(company_id, "employee_documents", sandbox)
        db_firestore.collection(coll_path).document(doc_id).delete()
    except Exception as e:
        print(f"⚠️ delete_employee_document: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# EMPLOYEE DEPENDENTS
# ═══════════════════════════════════════════════════════════════════════════

DEPENDENT_RELATIONSHIPS = [
    {"code": "hijo", "name": "Hijo"},
    {"code": "hija", "name": "Hija"},
    {"code": "conyuge", "name": "Cónyuge"},
    {"code": "padre", "name": "Padre"},
    {"code": "madre", "name": "Madre"},
    {"code": "hijastro", "name": "Hijastro"},
    {"code": "hijastra", "name": "Hijastra"},
    {"code": "nieto", "name": "Nieto"},
    {"code": "nieta", "name": "Nieta"},
    {"code": "hermano", "name": "Hermano"},
    {"code": "hermana", "name": "Hermana"},
    {"code": "tutor", "name": "Tutor"},
    {"code": "otro", "name": "Otro"},
]


def get_employee_dependents(company_id: str, employee_id: str, sandbox: bool = True) -> list:
    """Retorna todos los dependientes de un empleado, ordenados por fecha de creación descendente."""
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_company_path(company_id, "employee_dependents", sandbox)
        docs = db_firestore.collection(coll_path)\
            .where("employeeId", "==", employee_id).get()
        return sorted([{"id": d.id, **d.to_dict()} for d in docs],
                      key=lambda x: x.get("createdAt", ""), reverse=True)
    except Exception as e:
        print(f"⚠️ get_employee_dependents: {e}")
        return []


def get_employee_dependents_active(company_id: str, employee_id: str, sandbox: bool = True) -> list:
    """Retorna solo dependientes activos."""
    all_deps = get_employee_dependents(company_id, employee_id, sandbox=sandbox)
    return [d for d in all_deps if d.get("active", True)]


def save_employee_dependent(company_id: str, data: dict, sandbox: bool = True):
    """Crea o actualiza un dependiente."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_path = _hr_company_path(company_id, "employee_dependents", sandbox)
        doc_id = data.get("id", str(uuid.uuid4()))
        data["id"] = doc_id
        db_firestore.collection(coll_path).document(doc_id).set(data)
    except Exception as e:
        print(f"⚠️ save_employee_dependent: {e}")


def deactivate_employee_dependent(company_id: str, dep_id: str, sandbox: bool = True,
                                  updated_by: str = "", end_date: str = ""):
    """Desactiva un dependiente en lugar de eliminarlo físicamente."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_path = _hr_company_path(company_id, "employee_dependents", sandbox)
        update_data = {"active": False}
        if end_date:
            update_data["endDate"] = end_date
        if updated_by:
            update_data["updatedBy"] = updated_by
        update_data["updatedAt"] = datetime.now(timezone.utc).isoformat()
        db_firestore.collection(coll_path).document(dep_id).update(update_data)
    except Exception as e:
        print(f"⚠️ deactivate_employee_dependent: {e}")


def get_dependents_for_employees(company_id: str, employee_ids: list, sandbox: bool = True) -> dict:
    """Carga todos los dependientes activos para múltiples empleados.

    Firestore limita 'in' a 30 valores. Se particiona en lotes.

    Returns:
        Dict {employee_id: [dependent_dict, ...]}
    """
    if not firebase_initialized or db_firestore is None or not employee_ids:
        return {}
    try:
        coll_path = _hr_company_path(company_id, "employee_dependents", sandbox)
        result: dict[str, list] = {}
        batch_size = 30
        for i in range(0, len(employee_ids), batch_size):
            chunk = employee_ids[i:i + batch_size]
            docs = db_firestore.collection(coll_path)\
                .where("active", "==", True)\
                .where("employeeId", "in", chunk)\
                .get()
            for d in docs:
                dep = {"id": d.id, **d.to_dict()}
                emp_id = dep.get("employeeId", "")
                result.setdefault(emp_id, []).append(dep)
        return result
    except Exception as e:
        print(f"⚠️ get_dependents_for_employees: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════════════
# TAX RATES — Tasas y topes TSS/DGII configurables
# ═══════════════════════════════════════════════════════════════════════════

def _tax_rates_collection(company_id: str, sandbox: bool = True) -> str:
    company_id = company_id
    prefix = "sandbox_" if sandbox else ""
    if company_id:
        return f"companies/{company_id}/{prefix}hr_tax_rates_history"
    return _hr_company_path(company_id, "tax_rates_history", sandbox)


def get_tax_rates(company_id: str, sandbox: bool = True) -> dict:
    """Obtiene las tasas vigentes actualmente (documento 'tax_rates' en hr_config)."""
    if not firebase_initialized or db_firestore is None:
        return {}
    try:
        coll = _config_collection(company_id, sandbox)
        doc = db_firestore.collection(coll).document("tax_rates").get()
        if doc.exists:
            return doc.to_dict()
    except Exception as e:
        print(f"⚠️ HRDataService.get_tax_rates: {e}")
    return {}


def save_tax_rates(company_id: str, data: dict, sandbox: bool = True):
    """Guarda tasas actuales Y crea entrada en el historial."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        data["updatedAt"] = now_iso

        coll = _config_collection(company_id, sandbox)
        db_firestore.collection(coll).document("tax_rates").set(data)

        _close_active_tax_rates(company_id, sandbox)
        history_coll = _tax_rates_collection(company_id, sandbox)
        history_doc = dict(data)
        history_doc["effectiveFrom"] = now_iso
        history_doc["effectiveTo"] = None
        history_doc["createdAt"] = now_iso
        db_firestore.collection(history_coll).add(history_doc)
    except Exception as e:
        print(f"⚠️ HRDataService.save_tax_rates: {e}")


def _close_active_tax_rates(company_id: str, sandbox: bool = True):
    """Cierra (setea effectiveTo) el documento de tasas activo actual."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        history_coll = _tax_rates_collection(company_id, sandbox)
        active_docs = db_firestore.collection(history_coll) \
            .where("effectiveTo", "==", None) \
            .limit(1).get()
        for d in active_docs:
            d.reference.update({"effectiveTo": now_iso})
    except Exception as e:
        print(f"⚠️ HRDataService._close_active_tax_rates: {e}")


def get_tax_rates_for_date(company_id: str, target_date: str, sandbox: bool = True) -> dict:
    """Obtiene las tasas vigentes para una fecha específica (ISO date string)."""
    if not firebase_initialized or db_firestore is None:
        return {}
    try:
        history_coll = _tax_rates_collection(company_id, sandbox)
        docs = db_firestore.collection(history_coll) \
            .where("effectiveFrom", "<=", target_date) \
            .order_by("effectiveFrom", direction="DESCENDING") \
            .limit(1).get()
        for d in docs:
            data = d.to_dict()
            eff_to = data.get("effectiveTo")
            if eff_to is None or eff_to >= target_date:
                return data
    except Exception as e:
        print(f"⚠️ HRDataService.get_tax_rates_for_date: {e}")
    return {}


def get_tax_rates_history(company_id: str, sandbox: bool = True) -> list:
    """Obtiene el historial completo de cambios de tasas, ordenado por fecha."""
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        history_coll = _tax_rates_collection(company_id, sandbox)
        docs = db_firestore.collection(history_coll) \
            .order_by("effectiveFrom", direction="DESCENDING") \
            .get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ HRDataService.get_tax_rates_history: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# CATALOGS: Positions, Departments
# ═══════════════════════════════════════════════════════════════════════════

def _catalog_coll_path(company_id: str, catalog_name: str, sandbox: bool = True) -> str | None:
    """Retorna companies/{companyId}/{sandbox_}hr_catalog_{name}."""
    if not company_id:
        return None
    try:
        companies = DatabaseService.get_companies_by_owner(company_id)
        if not companies:
            return None
        prefix = "sandbox_" if sandbox else ""
        return f"companies/{companies[0]['id']}/{prefix}hr_catalog_{catalog_name}"
    except Exception:
        return None


def get_catalog(company_id: str, catalog_name: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return _default_catalog(catalog_name)
    coll_path = _catalog_coll_path(company_id, catalog_name, sandbox)
    if not coll_path:
        return _default_catalog(catalog_name)
    try:
        docs = db_firestore.collection(coll_path).get()
        items = [d.to_dict() for d in docs]
        if not items:
            items = _default_catalog(catalog_name)
            for item in items:
                db_firestore.collection(coll_path).document(item["id"]).set(item)
        return sorted(items, key=lambda x: x.get("name", ""))
    except Exception:
        return _default_catalog(catalog_name)


def save_catalog_item(company_id: str, catalog_name: str, item: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    coll_path = _catalog_coll_path(company_id, catalog_name, sandbox)
    if not coll_path:
        return
    try:
        db_firestore.collection(coll_path).document(item["id"]).set(item)
    except Exception as e:
        print(f"⚠️ save_catalog_item: {e}")


def delete_catalog_item(company_id: str, catalog_name: str, item_id: str, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    coll_path = _catalog_coll_path(company_id, catalog_name, sandbox)
    if not coll_path:
        return
    try:
        db_firestore.collection(coll_path).document(item_id).delete()
    except Exception as e:
        print(f"⚠️ delete_catalog_item: {e}")


def find_or_create_catalog_item(company_id: str, catalog_name: str, name: str, sandbox: bool = True) -> dict:
    if not name or not name.strip():
        return None
    name = name.strip()
    normalized = name.lower()
    try:
        existing = get_catalog(company_id, catalog_name, sandbox)
        for item in existing:
            if item.get("name", "").strip().lower() == normalized:
                return item
    except Exception:
        pass
    import uuid as _uuid
    item_id = str(_uuid.uuid4())
    item = {"id": item_id, "name": name, "active": True}
    save_catalog_item(company_id, catalog_name, item, sandbox)
    return item


def _default_catalog(catalog_name: str) -> list:
    defaults = {
        "positions": [
            {"id": "pos-1", "name": "Gerente General", "active": True},
            {"id": "pos-2", "name": "Gerente de Área", "active": True},
            {"id": "pos-3", "name": "Supervisor", "active": True},
            {"id": "pos-4", "name": "Analista", "active": True},
            {"id": "pos-5", "name": "Asistente", "active": True},
            {"id": "pos-6", "name": "Vendedor", "active": True},
            {"id": "pos-7", "name": "Contador", "active": True},
            {"id": "pos-8", "name": "Desarrollador", "active": True},
            {"id": "pos-9", "name": "Diseñador", "active": True},
            {"id": "pos-10", "name": "Recepcionista", "active": True},
        ],
        "departments": [
            {"id": "dept-1", "name": "Gerencia General", "active": True},
            {"id": "dept-2", "name": "Administración", "active": True},
            {"id": "dept-3", "name": "Ventas", "active": True},
            {"id": "dept-4", "name": "Operaciones", "active": True},
            {"id": "dept-5", "name": "Finanzas", "active": True},
            {"id": "dept-6", "name": "Contabilidad", "active": True},
            {"id": "dept-7", "name": "Recursos Humanos", "active": True},
            {"id": "dept-8", "name": "Tecnología", "active": True},
        ],
    }
    return defaults.get(catalog_name, [])


# ═══════════════════════════════════════════════════════════════════════════
# EMPLOYMENT HISTORY (transfers, promotions)
# ═══════════════════════════════════════════════════════════════════════════

def get_employment_history(company_id: str, employee_id: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll = _hr_company_path(company_id, "employment_history", sandbox)
        docs = db_firestore.collection(coll).where("employeeId", "==", employee_id).get()
        return sorted([d.to_dict() for d in docs], key=lambda x: x.get("changedAt", ""), reverse=True)
    except Exception:
        return []


def save_employment_history(company_id: str, data: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _hr_company_path(company_id, "employment_history", sandbox)
        doc_id = data.get("id", str(uuid.uuid4()))
        data["id"] = doc_id
        db_firestore.collection(coll).document(doc_id).set(data)
    except Exception as e:
        print(f"⚠️ save_employment_history: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# ONBOARDING / OFFBOARDING CHECKLISTS
# ═══════════════════════════════════════════════════════════════════════════

ONBOARDING_TASKS = [
    {"id": "onb-1", "task": "Firmar contrato de trabajo", "category": "legal"},
    {"id": "onb-2", "task": "Entregar documentos de identidad (cédula, RNC)", "category": "legal"},
    {"id": "onb-3", "task": "Registrar en TSS (AFP, SFS, SRL)", "category": "legal"},
    {"id": "onb-4", "task": "Crear correo electrónico corporativo", "category": "systems"},
    {"id": "onb-5", "task": "Asignar equipo (laptop, teléfono)", "category": "assets"},
    {"id": "onb-6", "task": "Configurar accesos a sistemas", "category": "systems"},
    {"id": "onb-7", "task": "Presentación al equipo", "category": "hr"},
    {"id": "onb-8", "task": "Entrenamiento inicial / inducción", "category": "hr"},
]

OFFBOARDING_TASKS = [
    {"id": "off-1", "task": "Recibir carta de renuncia o notificación de despido", "category": "legal"},
    {"id": "off-2", "task": "Calcular liquidación y prestaciones", "category": "payroll"},
    {"id": "off-3", "task": "Recoger equipo asignado (laptop, teléfono, llaves)", "category": "assets"},
    {"id": "off-4", "task": "Desactivar accesos a sistemas", "category": "systems"},
    {"id": "off-5", "task": "Desactivar correo electrónico", "category": "systems"},
    {"id": "off-6", "task": "Notificar a TSS baja del empleado", "category": "legal"},
    {"id": "off-7", "task": "Entrevista de salida", "category": "hr"},
    {"id": "off-8", "task": "Archivar expediente", "category": "hr"},
]


def get_checklist(company_id: str, employee_id: str, checklist_type: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return ONBOARDING_TASKS if checklist_type == "onboarding" else OFFBOARDING_TASKS
    try:
        coll = _hr_company_path(company_id, f"checklist_{checklist_type}", sandbox)
        docs = db_firestore.collection(coll).where("employeeId", "==", employee_id).get()
        items = [d.to_dict() for d in docs]
        if not items:
            templates = ONBOARDING_TASKS if checklist_type == "onboarding" else OFFBOARDING_TASKS
            for t in templates:
                entry = {**t, "employeeId": employee_id, "completed": False, "completedBy": "", "completedAt": ""}
                db_firestore.collection(coll).document(t["id"] + "_" + employee_id).set(entry)
                items.append(entry)
        return items
    except Exception:
        return ONBOARDING_TASKS if checklist_type == "onboarding" else OFFBOARDING_TASKS


def toggle_checklist_item(company_id: str, employee_id: str, checklist_type: str, item_id: str,
                          completed: bool, user_email: str, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _hr_company_path(company_id, f"checklist_{checklist_type}", sandbox)
        doc_id = item_id + "_" + employee_id
        db_firestore.collection(coll).document(doc_id).set({
            "employeeId": employee_id, "id": item_id, "completed": completed,
            "completedBy": user_email if completed else "",
            "completedAt": datetime.now(timezone.utc).isoformat() if completed else "",
        }, merge=True)
    except Exception as e:
        print(f"⚠️ toggle_checklist_item: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# DGT SUSPENSIONES (DGT-9)
# ═══════════════════════════════════════════════════════════════════════════

def get_dgt_suspensions(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "dgt_suspensions", sandbox)

def get_dgt_suspension(company_id: str, suspension_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "dgt_suspensions", suspension_id, sandbox)

def save_dgt_suspension(company_id: str, suspension_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "dgt_suspensions", suspension_id, data, sandbox)

def delete_dgt_suspension(company_id: str, suspension_id: str, sandbox: bool = True):
    _delete(company_id, "dgt_suspensions", suspension_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# DGT REINCORPORACIONES (DGT-12)
# ═══════════════════════════════════════════════════════════════════════════

def get_dgt_reinstatements(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "dgt_reinstatements", sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# LIQUIDACIONES (PRESTACIONES LABORALES)
# ═══════════════════════════════════════════════════════════════════════════

def get_liquidaciones(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "liquidaciones", sandbox)


def get_liquidacion(company_id: str, liquidacion_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "liquidaciones", liquidacion_id, sandbox)


def save_liquidacion(company_id: str, liquidacion_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "liquidaciones", liquidacion_id, data, sandbox)


def get_liquidaciones_by_employee(company_id: str, employee_id: str, sandbox: bool = True) -> list:
    liquidaciones = _get_all(company_id, "liquidaciones", sandbox)
    return [l for l in liquidaciones if l.get("employeeId") == employee_id]


def delete_liquidacion(company_id: str, liquidacion_id: str, sandbox: bool = True):
    _delete(company_id, "liquidaciones", liquidacion_id, sandbox)

def get_dgt_reinstatement(company_id: str, reinst_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "dgt_reinstatements", reinst_id, sandbox)

def save_dgt_reinstatement(company_id: str, reinst_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "dgt_reinstatements", reinst_id, data, sandbox)

def delete_dgt_reinstatement(company_id: str, reinst_id: str, sandbox: bool = True):
    _delete(company_id, "dgt_reinstatements", reinst_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# ACCIONES DE PERSONAL MASIVAS
# ═══════════════════════════════════════════════════════════════════════════

def get_mass_actions(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "mass_actions", sandbox)


def get_mass_action(company_id: str, action_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "mass_actions", action_id, sandbox)


def save_mass_action(company_id: str, action_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "mass_actions", action_id, data, sandbox)


def delete_mass_action(company_id: str, action_id: str, sandbox: bool = True):
    _delete(company_id, "mass_actions", action_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# PAYROLL POLICIES
# ═══════════════════════════════════════════════════════════════════════════

def get_payroll_policies(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "payroll_policies", sandbox)

def get_payroll_policy(company_id: str, policy_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "payroll_policies", policy_id, sandbox)

def save_payroll_policy(company_id: str, policy_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "payroll_policies", policy_id, data, sandbox)

def delete_payroll_policy(company_id: str, policy_id: str, sandbox: bool = True):
    _delete(company_id, "payroll_policies", policy_id, sandbox)

def get_default_payroll_policy(company_id: str, sandbox: bool = True) -> dict | None:
    if not firebase_initialized or db_firestore is None:
        return None
    try:
        coll_path = _hr_company_path(company_id, "payroll_policies", sandbox)
        docs = db_firestore.collection(coll_path) \
            .where("isDefault", "==", True) \
            .limit(1).get()
        for d in docs:
            return {"id": d.id, **d.to_dict()}
    except Exception as e:
        print(f"⚠️ HRDataService.get_default_payroll_policy: {e}")
    return None


# ═══════════════════════════════════════════════════════════════════════════
# PAYROLL RULES (reglas configurables)
# ═══════════════════════════════════════════════════════════════════════════

def get_payroll_rules(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "payroll_rules", sandbox)

def get_payroll_rule(company_id: str, rule_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "payroll_rules", rule_id, sandbox)

def save_payroll_rule(company_id: str, rule_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "payroll_rules", rule_id, data, sandbox)

def delete_payroll_rule(company_id: str, rule_id: str, sandbox: bool = True):
    _delete(company_id, "payroll_rules", rule_id, sandbox)

def get_active_rules_for_scope(company_id: str, scope: str = "global",
                                scope_id: str = "", sandbox: bool = True) -> list:
    """Obtiene reglas activas para un ámbito (global, grupo o empleado)."""
    rules = get_payroll_rules(company_id, sandbox=sandbox)
    active = [r for r in rules if r.get("isActive", True)]
    matching = []
    for r in active:
        r_scope = r.get("scope", "global")
        if r_scope == "global":
            matching.append(r)
        elif r_scope == scope and (not scope_id or scope_id == r.get("scopeId") or scope_id in r.get("scopeIds", [])):
            matching.append(r)
    matching.sort(key=lambda r: r.get("priority", 999))
    return matching


# ═══════════════════════════════════════════════════════════════════════════
# PAYROLL RULE LOG (control de one-shot / annual)
# ═══════════════════════════════════════════════════════════════════════════

def rule_log_exists(company_id: str, rule_id: str, employee_id: str,
                    year: int | None = None, sandbox: bool = True) -> bool:
    """Verifica si ya se aplicó una regla one-shot a un empleado.
    
    Si year es None, busca cualquier registro (one-shot forever).
    Si year tiene valor, busca solo en ese año (annual).
    """
    if not firebase_initialized or db_firestore is None:
        return False
    try:
        coll_path = _hr_company_path(company_id, "payroll_rule_log", sandbox)
        query = db_firestore.collection(coll_path) \
            .where(filter=FieldFilter("ruleId", "==", rule_id)) \
            .where(filter=FieldFilter("employeeId", "==", employee_id))
        if year is not None:
            query = query.where(filter=FieldFilter("year", "==", year))
        docs = query.limit(1).get()
        return len(docs) > 0
    except Exception as e:
        print(f"⚠️ HRDataService.rule_log_exists: {e}")
        return False


def save_rule_log(company_id: str, rule_id: str, employee_id: str,
                  year: int | None, period_key: str, amount: float,
                  applied_at: str, sandbox: bool = True):
    """Registra la aplicación de una regla one-shot para un empleado."""
    import uuid
    log_id = str(uuid.uuid4())
    data = {
        "ruleId": rule_id,
        "employeeId": employee_id,
        "periodKey": period_key,
        "amount": amount,
        "appliedAt": applied_at,
    }
    if year is not None:
        data["year"] = year
    _save(company_id, "payroll_rule_log", log_id, data, sandbox)


def delete_rule_logs_for_rule(company_id: str, rule_id: str | None = None, sandbox: bool = True):
    """Elimina logs de una regla específica o todos los logs si rule_id es None."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_path = _hr_company_path(company_id, "payroll_rule_log", sandbox)
        query = db_firestore.collection(coll_path)
        if rule_id:
            query = query.where(filter=FieldFilter("ruleId", "==", rule_id))
        docs = query.get()
        for d in docs:
            d.reference.delete()
    except Exception as e:
        print(f"⚠️ HRDataService.delete_rule_logs: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# GARNISHMENTS (embargos salariales)
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════
# PARÁMETROS LEGALES CON VIGENCIA HISTÓRICA
# ═══════════════════════════════════════════════════════════════════════


def get_legal_parameters(company_id: str, parameter_type: str = "",
                          sandbox: bool = True) -> list:
    """Obtiene parámetros legales, opcionalmente filtrados por tipo.

    Evita usar order_by en Firestore para no requerir índices compuestos.
    El ordenamiento se hace en Python.
    """
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_company_path(company_id, "legal_parameters", sandbox)
        query = db_firestore.collection(coll_path)
        if parameter_type:
            query = query.where("parameterType", "==", parameter_type)
        docs = query.get()
        results = [{"id": d.id, **d.to_dict()} for d in docs]
        results.sort(key=lambda p: p.get("version", 0), reverse=True)
        return results
    except Exception as e:
        print(f"⚠️ HRDataService.get_legal_parameters: {e}")
        return []


def get_legal_parameter(company_id: str, param_id: str,
                        sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "legal_parameters", param_id, sandbox)


def save_legal_parameter(company_id: str, param_id: str, data: dict,
                         sandbox: bool = True):
    _save(company_id, "legal_parameters", param_id, data, sandbox)


def delete_legal_parameter(company_id: str, param_id: str, sandbox: bool = True):
    _delete(company_id, "legal_parameters", param_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════
# TRANSACCIONES DE NÓMINA (PayrollTransaction)
# ═══════════════════════════════════════════════════════════════════════


def get_payroll_transactions(company_id: str, sandbox: bool = True,
                              period_id: str = "", employee_id: str = "",
                              concept_code: str = "", limit: int = None) -> list:
    """Obtiene transacciones con filtros opcionales."""
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_company_path(company_id, "payroll_transactions", sandbox)
        query = db_firestore.collection(coll_path)
        if period_id:
            query = query.where("periodId", "==", period_id)
        if employee_id:
            query = query.where("employeeId", "==", employee_id)
        if concept_code:
            query = query.where("conceptCode", "==", concept_code)
        if limit:
            query = query.limit(limit)
        docs = query.get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ HRDataService.get_payroll_transactions: {e}")
        return []


def get_payroll_transaction(company_id: str, tx_id: str,
                              sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "payroll_transactions", tx_id, sandbox)


def save_payroll_transaction(company_id: str, tx_id: str, data: dict,
                             sandbox: bool = True):
    _save(company_id, "payroll_transactions", tx_id, data, sandbox)


def save_payroll_transactions_batch(company_id: str, transactions: list,
                                    sandbox: bool = True):
    """Guarda múltiples transacciones como batch."""
    if not firebase_initialized or db_firestore is None or not transactions:
        return
    try:
        coll_path = _hr_company_path(company_id, "payroll_transactions", sandbox)
        batch = db_firestore.batch()
        for tx in transactions:
            tx_id = tx.get("id", str(uuid.uuid4()))
            tx["id"] = tx_id
            batch.set(db_firestore.collection(coll_path).document(tx_id), tx)
        batch.commit()
    except Exception as e:
        print(f"⚠️ HRDataService.save_payroll_transactions_batch: {e}")


def delete_payroll_transactions_by_period(company_id: str, period_id: str,
                                          sandbox: bool = True):
    """Elimina todas las transacciones de un período (usado en recálculos)."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_path = _hr_company_path(company_id, "payroll_transactions", sandbox)
        docs = db_firestore.collection(coll_path)\
                           .where("periodId", "==", period_id).get()
        batch = db_firestore.batch()
        for d in docs:
            batch.delete(d.reference)
        batch.commit()
    except Exception as e:
        print(f"⚠️ HRDataService.delete_payroll_transactions_by_period: {e}")


def get_ytd_transactions(company_id: str, employee_id: str, year: int,
                          concept_code: str = "", sandbox: bool = True) -> list:
    """Obtiene las transacciones YTD de un empleado para un año."""
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_company_path(company_id, "payroll_transactions", sandbox)
        query = db_firestore.collection(coll_path)\
                            .where(filter=FieldFilter("employeeId", "==", employee_id))\
                            .where(filter=FieldFilter("periodYear", "==", year))\
                            .where(filter=FieldFilter("status", "in", ["applied", "adjusted"]))
        if concept_code:
            query = query.where(filter=FieldFilter("conceptCode", "==", concept_code))
        docs = query.get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ HRDataService.get_ytd_transactions: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════
# MOVIMIENTOS VARIABLES (VariableMovement)
# ═══════════════════════════════════════════════════════════════════════


def get_variable_movements(company_id: str, sandbox: bool = True,
                            period_id: str = "", employee_id: str = "") -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_company_path(company_id, "variable_movements", sandbox)
        query = db_firestore.collection(coll_path)
        if period_id:
            query = query.where("periodId", "==", period_id)
        if employee_id:
            query = query.where("employeeId", "==", employee_id)
        docs = query.get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ HRDataService.get_variable_movements: {e}")
        return []


def save_variable_movement(company_id: str, vm_id: str, data: dict,
                           sandbox: bool = True):
    _save(company_id, "variable_movements", vm_id, data, sandbox)


def delete_variable_movements_by_period(company_id: str, period_id: str,
                                        sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_path = _hr_company_path(company_id, "variable_movements", sandbox)
        docs = db_firestore.collection(coll_path)\
                           .where("periodId", "==", period_id).get()
        batch = db_firestore.batch()
        for d in docs:
            batch.delete(d.reference)
        batch.commit()
    except Exception as e:
        print(f"⚠️ HRDataService.delete_variable_movements_by_period: {e}")


# ═══════════════════════════════════════════════════════════════════════
# MOVIMIENTOS RECURRENTES (delegar a RecurringService)
# ═══════════════════════════════════════════════════════════════════════


def get_recurring_movements(company_id: str, employee_id: str = "",
                             status: str = "", movement_type: str = "",
                             payroll_group_id: str = "",
                             sandbox: bool = True) -> list:
    from app.services.recurring_service import get_recurring_movements as _rm
    return _rm(company_id, employee_id=employee_id, status=status,
               movement_type=movement_type, payroll_group_id=payroll_group_id,
               sandbox=sandbox)


def get_recurring_movement(company_id: str, movement_id: str,
                            sandbox: bool = True) -> dict | None:
    from app.services.recurring_service import get_recurring_movement as _rm
    return _rm(company_id, movement_id, sandbox=sandbox)


def save_recurring_movement(company_id: str, movement_id: str, data: dict,
                            sandbox: bool = True):
    from app.services.recurring_service import save_recurring_movement as _rm
    _rm(company_id, movement_id, data, sandbox=sandbox)


def delete_recurring_movement(company_id: str, movement_id: str,
                               sandbox: bool = True):
    from app.services.recurring_service import delete_recurring_movement as _rm
    _rm(company_id, movement_id, sandbox=sandbox)


# ═══════════════════════════════════════════════════════════════════════
# EMBARGOS / GARNISHMENTS (existente)
# ═══════════════════════════════════════════════════════════════════════


def get_garnishments(company_id: str, employee_id: str = "", sandbox: bool = True) -> list:
    if employee_id:
        if not firebase_initialized or db_firestore is None:
            return []
        try:
            coll_path = _hr_company_path(company_id, "garnishments", sandbox)
            docs = db_firestore.collection(coll_path) \
                .where("employeeId", "==", employee_id) \
                .get()
            return [{"id": d.id, **d.to_dict()} for d in docs]
        except Exception as e:
            print(f"⚠️ HRDataService.get_garnishments: {e}")
            return []
    return _get_all(company_id, "garnishments", sandbox)

def get_garnishment(company_id: str, garnishment_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "garnishments", garnishment_id, sandbox)

def save_garnishment(company_id: str, garnishment_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "garnishments", garnishment_id, data, sandbox)

def delete_garnishment(company_id: str, garnishment_id: str, sandbox: bool = True):
    _delete(company_id, "garnishments", garnishment_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════
# HORAS EXTRAS — Types
# ═══════════════════════════════════════════════════════════════════════

def get_overtime_types(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "overtime_types", sandbox)


def get_overtime_type(company_id: str, code: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "overtime_types", code, sandbox)


def save_overtime_type(company_id: str, code: str, data: dict, sandbox: bool = True):
    _save(company_id, "overtime_types", code, data, sandbox)


# ═══════════════════════════════════════════════════════════════════════
# HORAS EXTRAS — Records
# ═══════════════════════════════════════════════════════════════════════

def get_overtime_records(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "overtime_records", sandbox)


def get_overtime_record(company_id: str, record_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "overtime_records", record_id, sandbox)


def save_overtime_record(company_id: str, record_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "overtime_records", record_id, data, sandbox)


def get_overtime_records_by_status(company_id: str, status: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_company_path(company_id, "overtime_records", sandbox)
        docs = db_firestore.collection(coll_path) \
            .where("status", "==", status) \
            .get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ HRDataService.get_overtime_records_by_status: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════
# HORAS EXTRAS — Payroll Links
# ═══════════════════════════════════════════════════════════════════════

def get_overtime_payroll_links(company_id: str, payroll_id: str = "", sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_company_path(company_id, "overtime_payroll_links", sandbox)
        query = db_firestore.collection(coll_path)
        if payroll_id:
            query = query.where("payrollId", "==", payroll_id)
        docs = query.get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ HRDataService.get_overtime_payroll_links: {e}")
        return []


def save_overtime_payroll_link(company_id: str, link_id: str, data: dict, sandbox: bool = True):
    _save(company_id, "overtime_payroll_links", link_id, data, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# WORK CERTIFICATES (CARTAS DE TRABAJO)
# ═══════════════════════════════════════════════════════════════════════════

def get_work_certificates(company_id: str, sandbox: bool = True) -> list:
    return _get_all(company_id, "work_certificates", sandbox)


def get_work_certificate(company_id: str, cert_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(company_id, "work_certificates", cert_id, sandbox)


def save_work_certificate(company_id: str, data: dict, sandbox: bool = True):
    cert_id = data.get("id", str(uuid.uuid4()))
    data["id"] = cert_id
    _save(company_id, "work_certificates", cert_id, data, sandbox)


def get_work_certificate_by_verification_code(verification_code: str) -> dict | None:
    """Busca un certificado por verificationCode en TODOS los owner_uids.
    Usado por la página pública de verificación (sin auth)."""
    if not firebase_initialized or db_firestore is None:
        return None
    try:
        users_coll = db_firestore.collection("users")
        user_docs = users_coll.list_documents()
        for user_ref in user_docs:
            for prefix in ("sandbox_hr_work_certificates", "hr_work_certificates"):
                coll_ref = user_ref.collection(prefix)
                docs = coll_ref.where("verificationCode", "==", verification_code).limit(1).get()
                for d in docs:
                    return {"id": d.id, **d.to_dict(), "_owner_uid": user_ref.id}
    except Exception as e:
        print(f"⚠️ get_work_certificate_by_verification_code: {e}")
    return None
