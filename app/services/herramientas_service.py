"""
HerramientasService — Capa de acceso a datos Firestore para Gestión de Activos/Herramientas.
Usa el mismo patrón que HRDataService.
"""

import uuid
from datetime import datetime, timezone
from app.services.db_service import db_firestore, firebase_initialized


def _coll_path(owner_uid: str, collection: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"users/{owner_uid}/{prefix}{collection}"


def _get_all(owner_uid: str, collection: str, sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        docs = db_firestore.collection(_coll_path(owner_uid, collection, sandbox)).get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ herramientas_service._get_all({collection}): {e}")
        return []


def _get_one(owner_uid: str, collection: str, doc_id: str, sandbox: bool = True) -> dict | None:
    if not firebase_initialized or db_firestore is None:
        return None
    try:
        doc = db_firestore.collection(_coll_path(owner_uid, collection, sandbox)).document(doc_id).get()
        if doc.exists:
            return {"id": doc.id, **doc.to_dict()}
        return None
    except Exception as e:
        print(f"⚠️ herramientas_service._get_one({collection}): {e}")
        return None


def _save(owner_uid: str, collection: str, doc_id: str, data: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        data["id"] = doc_id
        data["ownerUID"] = owner_uid
        db_firestore.collection(_coll_path(owner_uid, collection, sandbox)).document(doc_id).set(data)
    except Exception as e:
        print(f"⚠️ herramientas_service._save({collection}): {e}")


def _delete(owner_uid: str, collection: str, doc_id: str, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        db_firestore.collection(_coll_path(owner_uid, collection, sandbox)).document(doc_id).delete()
    except Exception as e:
        print(f"⚠️ herramientas_service._delete({collection}): {e}")


def _query(owner_uid: str, collection: str, sandbox: bool = True, filters: dict = None) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        query = db_firestore.collection(_coll_path(owner_uid, collection, sandbox))
        if filters:
            for field, value in filters.items():
                query = query.where(field, "==", value)
        docs = query.get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ herramientas_service._query({collection}): {e}")
        return []


# ─── Herramientas ───────────────────────────────────────────────────────────

def get_herramientas(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "herramientas", sandbox)


def get_herramienta(owner_uid: str, herramienta_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "herramientas", herramienta_id, sandbox)


def save_herramienta(owner_uid: str, herramienta_id: str, data: dict, sandbox: bool = True):
    data["updatedAt"] = datetime.now(timezone.utc).isoformat()
    if "createdAt" not in data or not data.get("createdAt"):
        data["createdAt"] = data["updatedAt"]
    _save(owner_uid, "herramientas", herramienta_id, data, sandbox)


def delete_herramienta(owner_uid: str, herramienta_id: str, sandbox: bool = True):
    _delete(owner_uid, "herramientas", herramienta_id, sandbox)


def get_next_code(owner_uid: str, category: str, sandbox: bool = True) -> str:
    prefix_map = {
        "computadora": "EQ",
        "telefono": "TEL",
        "software": "SW",
        "vehiculo": "VEH",
        "herramienta": "HER",
        "mobiliario": "MOB",
        "otro": "OTRO",
    }
    prefix = prefix_map.get(category, "ACT")
    herramientas = get_herramientas(owner_uid, sandbox)
    max_num = 0
    for h in herramientas:
        code = h.get("code", "")
        if code.startswith(f"{prefix}-"):
            try:
                num = int(code.split("-")[1])
                if num > max_num:
                    max_num = num
            except (ValueError, IndexError):
                pass
    return f"{prefix}-{max_num + 1:06d}"


def get_next_asset_tag(owner_uid: str, sandbox: bool = True) -> str:
    herramientas = get_herramientas(owner_uid, sandbox)
    max_num = 0
    for h in herramientas:
        tag = h.get("assetTag", "")
        if tag.startswith("INV-"):
            try:
                year, num = tag.replace("INV-", "").split("-")
                if year == str(datetime.now().year):
                    n = int(num)
                    if n > max_num:
                        max_num = n
            except (ValueError, IndexError):
                pass
    return f"INV-{datetime.now().year}-{max_num + 1:05d}"


# ─── Asignaciones ───────────────────────────────────────────────────────────

def get_asignaciones(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "asignaciones_herramientas", sandbox)


def get_asignacion(owner_uid: str, asignacion_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "asignaciones_herramientas", asignacion_id, sandbox)


def save_asignacion(owner_uid: str, asignacion_id: str, data: dict, sandbox: bool = True):
    if "createdAt" not in data or not data.get("createdAt"):
        data["createdAt"] = datetime.now(timezone.utc).isoformat()
    _save(owner_uid, "asignaciones_herramientas", asignacion_id, data, sandbox)


def get_asignaciones_por_empleado(owner_uid: str, empleado_id: str, sandbox: bool = True) -> list:
    return _query(owner_uid, "asignaciones_herramientas", sandbox, filters={"empleadoId": empleado_id})


def get_asignaciones_por_herramienta(owner_uid: str, herramienta_id: str, sandbox: bool = True) -> list:
    return _query(owner_uid, "asignaciones_herramientas", sandbox, filters={"herramientaId": herramienta_id})


# ─── Mantenimientos ─────────────────────────────────────────────────────────

def get_mantenimientos(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "mantenimientos_herramientas", sandbox)


def get_mantenimiento(owner_uid: str, mantenimiento_id: str, sandbox: bool = True) -> dict | None:
    return _get_one(owner_uid, "mantenimientos_herramientas", mantenimiento_id, sandbox)


def save_mantenimiento(owner_uid: str, mantenimiento_id: str, data: dict, sandbox: bool = True):
    if "createdAt" not in data or not data.get("createdAt"):
        data["createdAt"] = datetime.now(timezone.utc).isoformat()
    _save(owner_uid, "mantenimientos_herramientas", mantenimiento_id, data, sandbox)


def delete_mantenimiento(owner_uid: str, mantenimiento_id: str, sandbox: bool = True):
    _delete(owner_uid, "mantenimientos_herramientas", mantenimiento_id, sandbox)


def get_mantenimientos_por_herramienta(owner_uid: str, herramienta_id: str, sandbox: bool = True) -> list:
    return _query(owner_uid, "mantenimientos_herramientas", sandbox, filters={"herramientaId": herramienta_id})


# ─── Categorías personalizadas ──────────────────────────────────────────────

def get_categorias_herramienta(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "herramienta_categorias", sandbox)


def save_categoria_herramienta(owner_uid: str, cat_id: str, data: dict, sandbox: bool = True):
    if "createdAt" not in data or not data.get("createdAt"):
        data["createdAt"] = datetime.now(timezone.utc).isoformat()
    _save(owner_uid, "herramienta_categorias", cat_id, data, sandbox)


# ─── Movimientos (Bitácora) ─────────────────────────────────────────────────

def get_movimientos(owner_uid: str, sandbox: bool = True) -> list:
    return _get_all(owner_uid, "herramienta_movimientos", sandbox)


def get_movimientos_por_herramienta(owner_uid: str, herramienta_id: str, sandbox: bool = True) -> list:
    return _query(owner_uid, "herramienta_movimientos", sandbox, filters={"herramientaId": herramienta_id})


def save_movimiento(owner_uid: str, data: dict, sandbox: bool = True):
    mov_id = str(uuid.uuid4())
    if "createdAt" not in data or not data.get("createdAt"):
        data["createdAt"] = datetime.now(timezone.utc).isoformat()
    _save(owner_uid, "herramienta_movimientos", mov_id, data, sandbox)
    return mov_id
