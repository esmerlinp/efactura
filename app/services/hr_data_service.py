"""
HRDataService — Capa de acceso a datos Firestore para módulo RRHH.

Usa el mismo patrón de conexión que DatabaseService pero aislado para HR.
Evita inflar aún más el DatabaseService monolítico.
"""

import uuid
from datetime import datetime, timezone
from app.services.db_service import db_firestore, firebase_initialized


def _hr_collection(owner_uid: str, collection: str, sandbox: bool = True) -> str:
    """Retorna el path de la colección: users/{owner_uid}/{sandbox_}hr_{collection}."""
    prefix = "sandbox_hr_" if sandbox else "hr_"
    return f"users/{owner_uid}/{prefix}{collection}"


def _get_all(owner_uid: str, collection: str, sandbox: bool = True) -> list:
    """Obtiene todos los documentos de una colección HR."""
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_collection(owner_uid, collection, sandbox)
        docs = db_firestore.collection(coll_path).get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ HRDataService._get_all({collection}): {e}")
        return []


def _get_paginated(owner_uid: str, collection: str, sandbox: bool = True,
                   limit: int = 100, start_after: str = None,
                   order_by: str = None, filters: dict = None) -> dict:
    """Obtiene documentos con paginación. Retorna {items, cursor, has_more}."""
    if not firebase_initialized or db_firestore is None:
        return {"items": [], "cursor": None, "has_more": False}
    try:
        coll_path = _hr_collection(owner_uid, collection, sandbox)
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


def _get_one(owner_uid: str, collection: str, doc_id: str, sandbox: bool = True) -> dict | None:
    """Obtiene un documento por ID."""
    if not firebase_initialized or db_firestore is None:
        return None
    try:
        coll_path = _hr_collection(owner_uid, collection, sandbox)
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


def _save(owner_uid: str, collection: str, doc_id: str, data: dict, sandbox: bool = True) -> bool:
    """Guarda (crea o actualiza) un documento.
    Retorna True si se guardó correctamente, False si falló.
    """
    if not firebase_initialized or db_firestore is None:
        print(f"⚠️ HRDataService._save({collection}): Firebase no inicializado o db_firestore es None")
        return False
    try:
        coll_path = _hr_collection(owner_uid, collection, sandbox)
        import json
        safe = _sanitize_for_firestore(data)
        ref = db_firestore.collection(coll_path).document(doc_id)
        # Salva todo excepto taxRatesSnapshot (guarda como JSON string)
        trs = safe.pop("taxRatesSnapshot", None) if "taxRatesSnapshot" in safe else None
        if trs is not None:
            safe["taxRatesSnapshot"] = json.dumps(trs)
        ref.set(safe)
        return True
    except Exception as e:
        print(f"⚠️ HRDataService._save({collection}): {e}")
        return False


def _delete(owner_uid: str, collection: str, doc_id: str, sandbox: bool = True):
    """Elimina un documento."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_path = _hr_collection(owner_uid, collection, sandbox)
        db_firestore.collection(coll_path).document(doc_id).delete()
    except Exception as e:
        print(f"⚠️ HRDataService._delete({collection}): {e}")


# ═══════════════════════════════════════════════════════════════════════════
# EMPLOYEES
# ═══════════════════════════════════════════════════════════════════════════

def get_employees(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "employees", sandbox)

def get_employee(owner_uid: str, employee_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "employees", employee_id, sandbox)

def save_employee(owner_uid: str, employee_id: str, data: dict, sandbox: bool = True):
    _save(owner_uid, "employees", employee_id, data, sandbox)

def delete_employee(owner_uid: str, employee_id: str, sandbox: bool = True):
    _delete(owner_uid, "employees", employee_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# ATTENDANCE
# ═══════════════════════════════════════════════════════════════════════════

def get_attendance_records(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "attendance", sandbox)

def get_attendance_record(owner_uid: str, record_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "attendance", record_id, sandbox)

def save_attendance_record(owner_uid: str, record_id: str, data: dict, sandbox: bool = True):
    _save(owner_uid, "attendance", record_id, data, sandbox)

def delete_attendance_record(owner_uid: str, record_id: str, sandbox: bool = True):
    _delete(owner_uid, "attendance", record_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# VACATIONS
# ═══════════════════════════════════════════════════════════════════════════

def get_vacation_requests(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "vacations", sandbox)

def get_vacation_request(owner_uid: str, request_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "vacations", request_id, sandbox)

def save_vacation_request(owner_uid: str, request_id: str, data: dict, sandbox: bool = True):
    _save(owner_uid, "vacations", request_id, data, sandbox)

def delete_vacation_request(owner_uid: str, request_id: str, sandbox: bool = True):
    _delete(owner_uid, "vacations", request_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# LEAVES
# ═══════════════════════════════════════════════════════════════════════════

def get_leave_requests(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "leaves", sandbox)

def get_leave_request(owner_uid: str, request_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "leaves", request_id, sandbox)

def save_leave_request(owner_uid: str, request_id: str, data: dict, sandbox: bool = True):
    _save(owner_uid, "leaves", request_id, data, sandbox)

def delete_leave_request(owner_uid: str, request_id: str, sandbox: bool = True):
    _delete(owner_uid, "leaves", request_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# PAYROLL GROUPS
# ═══════════════════════════════════════════════════════════════════════════

def get_payroll_groups(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "payroll_groups", sandbox)

def get_payroll_group(owner_uid: str, group_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "payroll_groups", group_id, sandbox)

def save_payroll_group(owner_uid: str, group_id: str, data: dict, sandbox: bool = True):
    _save(owner_uid, "payroll_groups", group_id, data, sandbox)

def delete_payroll_group(owner_uid: str, group_id: str, sandbox: bool = True):
    _delete(owner_uid, "payroll_groups", group_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# EMPLOYMENT CONTRACTS
# ═══════════════════════════════════════════════════════════════════════════

def get_contracts(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "employment_contracts", sandbox)

def get_contract(owner_uid: str, contract_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "employment_contracts", contract_id, sandbox)

def save_contract(owner_uid: str, contract_id: str, data: dict, sandbox: bool = True):
    _save(owner_uid, "employment_contracts", contract_id, data, sandbox)

def delete_contract(owner_uid: str, contract_id: str, sandbox: bool = True):
    _delete(owner_uid, "employment_contracts", contract_id, sandbox)

def get_active_contracts_for_employee(owner_uid: str, employee_id: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_collection(owner_uid, "employment_contracts", sandbox)
        docs = db_firestore.collection(coll_path) \
            .where("employeeId", "==", employee_id) \
            .where("status", "==", "activo") \
            .get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ HRDataService.get_active_contracts_for_employee: {e}")
        return []

def get_contracts_for_group(owner_uid: str, group_id: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_collection(owner_uid, "employment_contracts", sandbox)
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

def get_payroll_periods(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "payroll", sandbox)

def get_payroll_period(owner_uid: str, period_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "payroll", period_id, sandbox)

def save_payroll_period(owner_uid: str, period_id: str, data: dict, sandbox: bool = True) -> bool:
    return _save(owner_uid, "payroll", period_id, data, sandbox)

def delete_payroll_period(owner_uid: str, period_id: str, sandbox: bool = True):
    _delete(owner_uid, "payroll", period_id, sandbox)


def get_payroll_period_by_key(owner_uid: str, period_key: str, sandbox: bool = True) -> dict | None:
    if not firebase_initialized or db_firestore is None:
        return None
    try:
        coll_path = _hr_collection(owner_uid, "payroll", sandbox)
        docs = db_firestore.collection(coll_path).where("periodKey", "==", period_key).limit(1).get()
        for d in docs:
            return {"id": d.id, **d.to_dict()}
    except Exception as e:
        print(f"⚠️ HRDataService.get_payroll_period_by_key: {e}")
    return None

def get_payroll_period_by_key_and_group(owner_uid: str, period_key: str, group_id: str, sandbox: bool = True) -> dict | None:
    if not firebase_initialized or db_firestore is None:
        return None
    try:
        coll_path = _hr_collection(owner_uid, "payroll", sandbox)
        docs = db_firestore.collection(coll_path) \
            .where("periodKey", "==", period_key) \
            .where("payrollGroupId", "==", group_id) \
            .limit(1).get()
        for d in docs:
            return {"id": d.id, **d.to_dict()}
    except Exception as e:
        print(f"⚠️ HRDataService.get_payroll_period_by_key_and_group: {e}")
    return None


# ═══════════════════════════════════════════════════════════════════════════
# PAYROLL LINES — Subcolección hr_payroll/{periodId}/lines/{lineId}
# ═══════════════════════════════════════════════════════════════════════════

def _payroll_lines_subcollection(owner_uid: str, period_id: str, sandbox: bool = True) -> str:
    coll = _hr_collection(owner_uid, "payroll", sandbox)
    return f"{coll}/{period_id}/lines"


def get_payroll_lines(owner_uid: str, period_id: str, sandbox: bool = True, limit: int = None) -> list:
    """Obtiene todas las líneas de nómina de un período desde la subcolección."""
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        sub_coll = _payroll_lines_subcollection(owner_uid, period_id, sandbox)
        query = db_firestore.collection(sub_coll)
        if limit:
            query = query.limit(limit)
        docs = query.get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ HRDataService.get_payroll_lines({period_id}): {e}")
        return []


def save_payroll_lines_batch(owner_uid: str, period_id: str, lines: list, sandbox: bool = True):
    """Guarda líneas de nómina en la subcolección usando batch write (máx 500 por batch)."""
    if not firebase_initialized or db_firestore is None or not lines:
        return
    try:
        sub_coll = _payroll_lines_subcollection(owner_uid, period_id, sandbox)
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


def delete_payroll_lines(owner_uid: str, period_id: str, sandbox: bool = True):
    """Elimina todas las líneas de la subcolección de un período."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        lines = get_payroll_lines(owner_uid, period_id, sandbox=sandbox)
        sub_coll = _payroll_lines_subcollection(owner_uid, period_id, sandbox)
        for i in range(0, len(lines), 400):
            batch = db_firestore.batch()
            for line in lines[i:i + 400]:
                batch.delete(db_firestore.collection(sub_coll).document(line["id"]))
            batch.commit()
    except Exception as e:
        print(f"⚠️ HRDataService.delete_payroll_lines({period_id}): {e}")


def get_payroll_lines_unified(period: dict, owner_uid: str = "", sandbox: bool = True) -> list:
    """Obtiene líneas de nómina desde subcolección, con fallback a líneas embebidas.

    Si el período tiene líneas embebidas ('lines' en el documento) y no hay
    subcolección, las retorna directamente (compatibilidad hacia atrás).
    Si hay subcolección, las lee de allí.
    """
    embedded = period.get("lines", [])
    if embedded:
        return embedded
    period_id = period.get("id", "")
    if period_id and owner_uid:
        return get_payroll_lines(owner_uid, period_id, sandbox=sandbox)
    return embedded


# ═══════════════════════════════════════════════════════════════════════════
# EVALUATIONS
# ═══════════════════════════════════════════════════════════════════════════

def get_evaluations(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "evaluations", sandbox)

def get_evaluation(owner_uid: str, eval_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "evaluations", eval_id, sandbox)

def save_evaluation(owner_uid: str, eval_id: str, data: dict, sandbox: bool = True):
    _save(owner_uid, "evaluations", eval_id, data, sandbox)

def delete_evaluation(owner_uid: str, eval_id: str, sandbox: bool = True):
    _delete(owner_uid, "evaluations", eval_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# TRAININGS
# ═══════════════════════════════════════════════════════════════════════════

def get_trainings(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "trainings", sandbox)

def get_training(owner_uid: str, training_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "trainings", training_id, sandbox)

def save_training(owner_uid: str, training_id: str, data: dict, sandbox: bool = True):
    _save(owner_uid, "trainings", training_id, data, sandbox)

def delete_training(owner_uid: str, training_id: str, sandbox: bool = True):
    _delete(owner_uid, "trainings", training_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# PAYROLL CONFIG (frecuencia de pago, onboarding)
# ═══════════════════════════════════════════════════════════════════════════

def _config_collection(owner_uid: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"users/{owner_uid}/{prefix}hr_config"


def get_payroll_config(owner_uid: str, sandbox: bool = True) -> dict:
    if not firebase_initialized or db_firestore is None:
        return {}
    try:
        coll = _config_collection(owner_uid, sandbox)
        doc = db_firestore.collection(coll).document("payroll").get()
        if doc.exists:
            return doc.to_dict()
    except Exception as e:
        print(f"⚠️ HRDataService.get_payroll_config: {e}")
    return {}


def save_payroll_config(owner_uid: str, data: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _config_collection(owner_uid, sandbox)
        db_firestore.collection(coll).document("payroll").set(data)
    except Exception as e:
        print(f"⚠️ HRDataService.save_payroll_config: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# REFERENCE DATA (tipos de contrato, áreas configurables)
# ═══════════════════════════════════════════════════════════════════════════

def get_reference_data(owner_uid: str, sandbox: bool = True) -> dict:
    if not firebase_initialized or db_firestore is None:
        return {}
    try:
        coll = _config_collection(owner_uid, sandbox)
        doc = db_firestore.collection(coll).document("reference_data").get()
        if doc.exists:
            return doc.to_dict()
    except Exception as e:
        print(f"⚠️ HRDataService.get_reference_data: {e}")
    return {}


def save_reference_data(owner_uid: str, data: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _config_collection(owner_uid, sandbox)
        db_firestore.collection(coll).document("reference_data").set(data)
    except Exception as e:
        print(f"⚠️ HRDataService.save_reference_data: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SALARY HISTORY
# ═══════════════════════════════════════════════════════════════════════════

def get_salary_history(owner_uid: str, employee_id: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_collection(owner_uid, "salary_history", sandbox)
        docs = db_firestore.collection(coll_path).where("employeeId", "==", employee_id).get()
        results = [{"id": d.id, **d.to_dict()} for d in docs]
        results.sort(key=lambda r: r.get("effectiveDate", ""), reverse=True)
        return results
    except Exception as e:
        print(f"⚠️ HRDataService.get_salary_history: {e}")
        return []


def get_all_salary_history(owner_uid: str, sandbox: bool = True) -> list:
    """Obtiene todos los historiales salariales (sin filtrar por empleado)."""
    return _get_all(owner_uid, "salary_history", sandbox)


def get_current_salary(owner_uid: str, employee_id: str, sandbox: bool = True) -> float | None:
    history = get_salary_history(owner_uid, employee_id, sandbox=sandbox)
    active = [h for h in history if not h.get("endDate")]
    if active:
        return active[0].get("amount")
    if history:
        return history[0].get("amount")
    return None


def save_salary_history_entry(owner_uid: str, data: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_path = _hr_collection(owner_uid, "salary_history", sandbox)
        doc_id = data.get("id", str(uuid.uuid4()))
        data["id"] = doc_id
        db_firestore.collection(coll_path).document(doc_id).set(data)
    except Exception as e:
        print(f"⚠️ HRDataService.save_salary_history_entry: {e}")


def close_previous_salary(owner_uid: str, employee_id: str, new_effective_date: str, sandbox: bool = True):
    history = get_salary_history(owner_uid, employee_id, sandbox=sandbox)
    active = [h for h in history if not h.get("endDate")]
    for h in active:
        h["endDate"] = new_effective_date
        coll_path = _hr_collection(owner_uid, "salary_history", sandbox)
        db_firestore.collection(coll_path).document(h["id"]).set(h)


# ═══════════════════════════════════════════════════════════════════════════
# EMPLOYEE DOCUMENTS
# ═══════════════════════════════════════════════════════════════════════════

DOC_CATEGORIES = [
    "contract", "id", "certificate", "medical", "disciplinary", "academic", "other"
]

def get_employee_documents(owner_uid: str, employee_id: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_collection(owner_uid, "employee_documents", sandbox)
        docs = db_firestore.collection(coll_path).where("employeeId", "==", employee_id).get()
        return sorted([{"id": d.id, **d.to_dict()} for d in docs],
                      key=lambda x: x.get("uploadedAt", ""), reverse=True)
    except Exception as e:
        print(f"⚠️ get_employee_documents: {e}")
        return []


def save_employee_document(owner_uid: str, data: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_path = _hr_collection(owner_uid, "employee_documents", sandbox)
        doc_id = data.get("id", str(uuid.uuid4()))
        data["id"] = doc_id
        db_firestore.collection(coll_path).document(doc_id).set(data)
    except Exception as e:
        print(f"⚠️ save_employee_document: {e}")


def delete_employee_document(owner_uid: str, doc_id: str, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_path = _hr_collection(owner_uid, "employee_documents", sandbox)
        db_firestore.collection(coll_path).document(doc_id).delete()
    except Exception as e:
        print(f"⚠️ delete_employee_document: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# TAX RATES — Tasas y topes TSS/DGII configurables
# ═══════════════════════════════════════════════════════════════════════════

def _tax_rates_collection(owner_uid: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"users/{owner_uid}/{prefix}hr_tax_rates_history"


def get_tax_rates(owner_uid: str, sandbox: bool = True) -> dict:
    """Obtiene las tasas vigentes actualmente (documento 'tax_rates' en hr_config)."""
    if not firebase_initialized or db_firestore is None:
        return {}
    try:
        coll = _config_collection(owner_uid, sandbox)
        doc = db_firestore.collection(coll).document("tax_rates").get()
        if doc.exists:
            return doc.to_dict()
    except Exception as e:
        print(f"⚠️ HRDataService.get_tax_rates: {e}")
    return {}


def save_tax_rates(owner_uid: str, data: dict, sandbox: bool = True):
    """Guarda tasas actuales Y crea entrada en el historial."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        data["updatedAt"] = now_iso

        coll = _config_collection(owner_uid, sandbox)
        db_firestore.collection(coll).document("tax_rates").set(data)

        _close_active_tax_rates(owner_uid, sandbox)
        history_coll = _tax_rates_collection(owner_uid, sandbox)
        history_doc = dict(data)
        history_doc["effectiveFrom"] = now_iso
        history_doc["effectiveTo"] = None
        history_doc["createdAt"] = now_iso
        db_firestore.collection(history_coll).add(history_doc)
    except Exception as e:
        print(f"⚠️ HRDataService.save_tax_rates: {e}")


def _close_active_tax_rates(owner_uid: str, sandbox: bool = True):
    """Cierra (setea effectiveTo) el documento de tasas activo actual."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        history_coll = _tax_rates_collection(owner_uid, sandbox)
        active_docs = db_firestore.collection(history_coll) \
            .where("effectiveTo", "==", None) \
            .limit(1).get()
        for d in active_docs:
            d.reference.update({"effectiveTo": now_iso})
    except Exception as e:
        print(f"⚠️ HRDataService._close_active_tax_rates: {e}")


def get_tax_rates_for_date(owner_uid: str, target_date: str, sandbox: bool = True) -> dict:
    """Obtiene las tasas vigentes para una fecha específica (ISO date string)."""
    if not firebase_initialized or db_firestore is None:
        return {}
    try:
        history_coll = _tax_rates_collection(owner_uid, sandbox)
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


def get_tax_rates_history(owner_uid: str, sandbox: bool = True) -> list:
    """Obtiene el historial completo de cambios de tasas, ordenado por fecha."""
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        history_coll = _tax_rates_collection(owner_uid, sandbox)
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

def _catalog_collection(owner_uid: str, catalog_name: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"users/{owner_uid}/{prefix}hr_catalog_{catalog_name}"


def get_catalog(owner_uid: str, catalog_name: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return _default_catalog(catalog_name)
    try:
        coll = _catalog_collection(owner_uid, catalog_name, sandbox)
        docs = db_firestore.collection(coll).get()
        items = [d.to_dict() for d in docs]
        if not items:
            items = _default_catalog(catalog_name)
            for item in items:
                db_firestore.collection(coll).document(item["id"]).set(item)
        return sorted(items, key=lambda x: x.get("name", ""))
    except Exception:
        return _default_catalog(catalog_name)


def save_catalog_item(owner_uid: str, catalog_name: str, item: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _catalog_collection(owner_uid, catalog_name, sandbox)
        db_firestore.collection(coll).document(item["id"]).set(item)
    except Exception as e:
        print(f"⚠️ save_catalog_item: {e}")


def delete_catalog_item(owner_uid: str, catalog_name: str, item_id: str, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _catalog_collection(owner_uid, catalog_name, sandbox)
        db_firestore.collection(coll).document(item_id).delete()
    except Exception as e:
        print(f"⚠️ delete_catalog_item: {e}")


def find_or_create_catalog_item(owner_uid: str, catalog_name: str, name: str, sandbox: bool = True) -> dict:
    if not name or not name.strip():
        return None
    name = name.strip()
    normalized = name.lower()
    try:
        existing = get_catalog(owner_uid, catalog_name, sandbox)
        for item in existing:
            if item.get("name", "").strip().lower() == normalized:
                return item
    except Exception:
        pass
    import uuid as _uuid
    item_id = str(_uuid.uuid4())
    item = {"id": item_id, "name": name, "active": True}
    save_catalog_item(owner_uid, catalog_name, item, sandbox)
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

def get_employment_history(owner_uid: str, employee_id: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll = _hr_collection(owner_uid, "employment_history", sandbox)
        docs = db_firestore.collection(coll).where("employeeId", "==", employee_id).get()
        return sorted([d.to_dict() for d in docs], key=lambda x: x.get("changedAt", ""), reverse=True)
    except Exception:
        return []


def save_employment_history(owner_uid: str, data: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _hr_collection(owner_uid, "employment_history", sandbox)
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


def get_checklist(owner_uid: str, employee_id: str, checklist_type: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return ONBOARDING_TASKS if checklist_type == "onboarding" else OFFBOARDING_TASKS
    try:
        coll = _hr_collection(owner_uid, f"checklist_{checklist_type}", sandbox)
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


def toggle_checklist_item(owner_uid: str, employee_id: str, checklist_type: str, item_id: str,
                          completed: bool, user_email: str, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _hr_collection(owner_uid, f"checklist_{checklist_type}", sandbox)
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

def get_dgt_suspensions(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "dgt_suspensions", sandbox)

def get_dgt_suspension(owner_uid: str, suspension_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "dgt_suspensions", suspension_id, sandbox)

def save_dgt_suspension(owner_uid: str, suspension_id: str, data: dict, sandbox: bool = True):
    _save(owner_uid, "dgt_suspensions", suspension_id, data, sandbox)

def delete_dgt_suspension(owner_uid: str, suspension_id: str, sandbox: bool = True):
    _delete(owner_uid, "dgt_suspensions", suspension_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# DGT REINCORPORACIONES (DGT-12)
# ═══════════════════════════════════════════════════════════════════════════

def get_dgt_reinstatements(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "dgt_reinstatements", sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# LIQUIDACIONES (PRESTACIONES LABORALES)
# ═══════════════════════════════════════════════════════════════════════════

def get_liquidaciones(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "liquidaciones", sandbox)


def get_liquidacion(owner_uid: str, liquidacion_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "liquidaciones", liquidacion_id, sandbox)


def save_liquidacion(owner_uid: str, liquidacion_id: str, data: dict, sandbox: bool = True):
    _save(owner_uid, "liquidaciones", liquidacion_id, data, sandbox)


def get_liquidaciones_by_employee(owner_uid: str, employee_id: str, sandbox: bool = True) -> list:
    liquidaciones = _get_all(owner_uid, "liquidaciones", sandbox)
    return [l for l in liquidaciones if l.get("employeeId") == employee_id]


def delete_liquidacion(owner_uid: str, liquidacion_id: str, sandbox: bool = True):
    _delete(owner_uid, "liquidaciones", liquidacion_id, sandbox)

def get_dgt_reinstatement(owner_uid: str, reinst_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "dgt_reinstatements", reinst_id, sandbox)

def save_dgt_reinstatement(owner_uid: str, reinst_id: str, data: dict, sandbox: bool = True):
    _save(owner_uid, "dgt_reinstatements", reinst_id, data, sandbox)

def delete_dgt_reinstatement(owner_uid: str, reinst_id: str, sandbox: bool = True):
    _delete(owner_uid, "dgt_reinstatements", reinst_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# ACCIONES DE PERSONAL MASIVAS
# ═══════════════════════════════════════════════════════════════════════════

def get_mass_actions(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "mass_actions", sandbox)


def get_mass_action(owner_uid: str, action_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "mass_actions", action_id, sandbox)


def save_mass_action(owner_uid: str, action_id: str, data: dict, sandbox: bool = True):
    _save(owner_uid, "mass_actions", action_id, data, sandbox)


def delete_mass_action(owner_uid: str, action_id: str, sandbox: bool = True):
    _delete(owner_uid, "mass_actions", action_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# PAYROLL POLICIES
# ═══════════════════════════════════════════════════════════════════════════

def get_payroll_policies(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "payroll_policies", sandbox)

def get_payroll_policy(owner_uid: str, policy_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "payroll_policies", policy_id, sandbox)

def save_payroll_policy(owner_uid: str, policy_id: str, data: dict, sandbox: bool = True):
    _save(owner_uid, "payroll_policies", policy_id, data, sandbox)

def delete_payroll_policy(owner_uid: str, policy_id: str, sandbox: bool = True):
    _delete(owner_uid, "payroll_policies", policy_id, sandbox)

def get_default_payroll_policy(owner_uid: str, sandbox: bool = True) -> dict | None:
    if not firebase_initialized or db_firestore is None:
        return None
    try:
        coll_path = _hr_collection(owner_uid, "payroll_policies", sandbox)
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

def get_payroll_rules(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "payroll_rules", sandbox)

def get_payroll_rule(owner_uid: str, rule_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "payroll_rules", rule_id, sandbox)

def save_payroll_rule(owner_uid: str, rule_id: str, data: dict, sandbox: bool = True):
    _save(owner_uid, "payroll_rules", rule_id, data, sandbox)

def delete_payroll_rule(owner_uid: str, rule_id: str, sandbox: bool = True):
    _delete(owner_uid, "payroll_rules", rule_id, sandbox)

def get_active_rules_for_scope(owner_uid: str, scope: str = "global",
                                scope_id: str = "", sandbox: bool = True) -> list:
    """Obtiene reglas activas para un ámbito (global, grupo o empleado)."""
    rules = get_payroll_rules(owner_uid, sandbox=sandbox)
    active = [r for r in rules if r.get("isActive", True)]
    matching = []
    for r in active:
        r_scope = r.get("scope", "global")
        if r_scope == "global":
            matching.append(r)
        elif r_scope == scope and (not scope_id or r.get("scopeId") == scope_id):
            matching.append(r)
    matching.sort(key=lambda r: r.get("priority", 999))
    return matching


# ═══════════════════════════════════════════════════════════════════════════
# PAYROLL RULE LOG (control de one-shot / annual)
# ═══════════════════════════════════════════════════════════════════════════

def rule_log_exists(owner_uid: str, rule_id: str, employee_id: str,
                    year: int | None = None, sandbox: bool = True) -> bool:
    """Verifica si ya se aplicó una regla one-shot a un empleado.
    
    Si year es None, busca cualquier registro (one-shot forever).
    Si year tiene valor, busca solo en ese año (annual).
    """
    if not firebase_initialized or db_firestore is None:
        return False
    try:
        coll_path = _hr_collection(owner_uid, "payroll_rule_log", sandbox)
        query = db_firestore.collection(coll_path) \
            .where("ruleId", "==", rule_id) \
            .where("employeeId", "==", employee_id)
        if year is not None:
            query = query.where("year", "==", year)
        docs = query.limit(1).get()
        return len(docs) > 0
    except Exception as e:
        print(f"⚠️ HRDataService.rule_log_exists: {e}")
        return False


def save_rule_log(owner_uid: str, rule_id: str, employee_id: str,
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
    _save(owner_uid, "payroll_rule_log", log_id, data, sandbox)


def delete_rule_logs_for_rule(owner_uid: str, rule_id: str, sandbox: bool = True):
    """Elimina todos los logs de una regla (útil al eliminar la regla)."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_path = _hr_collection(owner_uid, "payroll_rule_log", sandbox)
        docs = db_firestore.collection(coll_path) \
            .where("ruleId", "==", rule_id) \
            .get()
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


def get_legal_parameters(owner_uid: str, parameter_type: str = "",
                          sandbox: bool = True) -> list:
    """Obtiene parámetros legales, opcionalmente filtrados por tipo.

    Evita usar order_by en Firestore para no requerir índices compuestos.
    El ordenamiento se hace en Python.
    """
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_collection(owner_uid, "legal_parameters", sandbox)
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


def get_legal_parameter(owner_uid: str, param_id: str,
                        sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "legal_parameters", param_id, sandbox)


def save_legal_parameter(owner_uid: str, param_id: str, data: dict,
                         sandbox: bool = True):
    _save(owner_uid, "legal_parameters", param_id, data, sandbox)


def delete_legal_parameter(owner_uid: str, param_id: str, sandbox: bool = True):
    _delete(owner_uid, "legal_parameters", param_id, sandbox)


# ═══════════════════════════════════════════════════════════════════════
# TRANSACCIONES DE NÓMINA (PayrollTransaction)
# ═══════════════════════════════════════════════════════════════════════


def get_payroll_transactions(owner_uid: str, sandbox: bool = True,
                              period_id: str = "", employee_id: str = "",
                              concept_code: str = "", limit: int = None) -> list:
    """Obtiene transacciones con filtros opcionales."""
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_collection(owner_uid, "payroll_transactions", sandbox)
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


def get_payroll_transaction(owner_uid: str, tx_id: str,
                              sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "payroll_transactions", tx_id, sandbox)


def save_payroll_transaction(owner_uid: str, tx_id: str, data: dict,
                             sandbox: bool = True):
    _save(owner_uid, "payroll_transactions", tx_id, data, sandbox)


def save_payroll_transactions_batch(owner_uid: str, transactions: list,
                                    sandbox: bool = True):
    """Guarda múltiples transacciones como batch."""
    if not firebase_initialized or db_firestore is None or not transactions:
        return
    try:
        coll_path = _hr_collection(owner_uid, "payroll_transactions", sandbox)
        batch = db_firestore.batch()
        for tx in transactions:
            tx_id = tx.get("id", str(uuid.uuid4()))
            tx["id"] = tx_id
            batch.set(db_firestore.collection(coll_path).document(tx_id), tx)
        batch.commit()
    except Exception as e:
        print(f"⚠️ HRDataService.save_payroll_transactions_batch: {e}")


def delete_payroll_transactions_by_period(owner_uid: str, period_id: str,
                                          sandbox: bool = True):
    """Elimina todas las transacciones de un período (usado en recálculos)."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_path = _hr_collection(owner_uid, "payroll_transactions", sandbox)
        docs = db_firestore.collection(coll_path)\
                           .where("periodId", "==", period_id).get()
        batch = db_firestore.batch()
        for d in docs:
            batch.delete(d.reference)
        batch.commit()
    except Exception as e:
        print(f"⚠️ HRDataService.delete_payroll_transactions_by_period: {e}")


def get_ytd_transactions(owner_uid: str, employee_id: str, year: int,
                          concept_code: str = "", sandbox: bool = True) -> list:
    """Obtiene las transacciones YTD de un empleado para un año."""
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_collection(owner_uid, "payroll_transactions", sandbox)
        query = db_firestore.collection(coll_path)\
                            .where("employeeId", "==", employee_id)\
                            .where("periodYear", "==", year)\
                            .where("status", "in", ["applied", "adjusted"])
        if concept_code:
            query = query.where("conceptCode", "==", concept_code)
        docs = query.get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ HRDataService.get_ytd_transactions: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════
# MOVIMIENTOS VARIABLES (VariableMovement)
# ═══════════════════════════════════════════════════════════════════════


def get_variable_movements(owner_uid: str, sandbox: bool = True,
                            period_id: str = "", employee_id: str = "") -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll_path = _hr_collection(owner_uid, "variable_movements", sandbox)
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


def save_variable_movement(owner_uid: str, vm_id: str, data: dict,
                           sandbox: bool = True):
    _save(owner_uid, "variable_movements", vm_id, data, sandbox)


def delete_variable_movements_by_period(owner_uid: str, period_id: str,
                                        sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll_path = _hr_collection(owner_uid, "variable_movements", sandbox)
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


def get_recurring_movements(owner_uid: str, employee_id: str = "",
                             status: str = "", movement_type: str = "",
                             payroll_group_id: str = "",
                             sandbox: bool = True) -> list:
    from app.services.recurring_service import get_recurring_movements as _rm
    return _rm(owner_uid, employee_id=employee_id, status=status,
               movement_type=movement_type, payroll_group_id=payroll_group_id,
               sandbox=sandbox)


def get_recurring_movement(owner_uid: str, movement_id: str,
                            sandbox: bool = True) -> dict | None:
    from app.services.recurring_service import get_recurring_movement as _rm
    return _rm(owner_uid, movement_id, sandbox=sandbox)


def save_recurring_movement(owner_uid: str, movement_id: str, data: dict,
                            sandbox: bool = True):
    from app.services.recurring_service import save_recurring_movement as _rm
    _rm(owner_uid, movement_id, data, sandbox=sandbox)


def delete_recurring_movement(owner_uid: str, movement_id: str,
                               sandbox: bool = True):
    from app.services.recurring_service import delete_recurring_movement as _rm
    _rm(owner_uid, movement_id, sandbox=sandbox)


# ═══════════════════════════════════════════════════════════════════════
# EMBARGOS / GARNISHMENTS (existente)
# ═══════════════════════════════════════════════════════════════════════


def get_garnishments(owner_uid: str, employee_id: str = "", sandbox: bool = True) -> list:
    if employee_id:
        if not firebase_initialized or db_firestore is None:
            return []
        try:
            coll_path = _hr_collection(owner_uid, "garnishments", sandbox)
            docs = db_firestore.collection(coll_path) \
                .where("employeeId", "==", employee_id) \
                .get()
            return [{"id": d.id, **d.to_dict()} for d in docs]
        except Exception as e:
            print(f"⚠️ HRDataService.get_garnishments: {e}")
            return []
    return _get_all(owner_uid, "garnishments", sandbox)

def get_garnishment(owner_uid: str, garnishment_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "garnishments", garnishment_id, sandbox)

def save_garnishment(owner_uid: str, garnishment_id: str, data: dict, sandbox: bool = True):
    _save(owner_uid, "garnishments", garnishment_id, data, sandbox)

def delete_garnishment(owner_uid: str, garnishment_id: str, sandbox: bool = True):
    _delete(owner_uid, "garnishments", garnishment_id, sandbox)
