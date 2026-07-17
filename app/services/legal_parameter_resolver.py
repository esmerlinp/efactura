"""LegalParameterResolver — Resolución de parámetros legales con vigencia histórica y versiones.

Permite:
  - Resolver un parámetro vigente para una fecha específica.
  - Resolver todos los parámetros vigentes para una fecha (snapshot).
  - Crear nuevos parámetros cerrando automáticamente el anterior vigente.
  - Obtener el historial de cambios de un tipo de parámetro.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from google.cloud.firestore import FieldFilter
from app.services.db_service import db_firestore, firebase_initialized
from app.models.legal_parameter import LegalParameter, PARAM_TYPES, get_default_params


def _legal_params_collection(owner_uid: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"users/{owner_uid}/{prefix}hr_legal_parameters"


def _doc_to_param(doc) -> dict:
    d = doc.to_dict() if hasattr(doc, 'to_dict') else doc
    d["id"] = doc.id if hasattr(doc, 'id') else d.get("id", "")
    return d


def _parse_date(date_str: str) -> Optional[date]:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _is_in_range(target_date: str, effective_from: str, effective_to: str) -> bool:
    try:
        td = _parse_date(target_date)
        if not td:
            return False
        eff_from = _parse_date(effective_from)
        if eff_from and td < eff_from:
            return False
        eff_to = _parse_date(effective_to) if effective_to else None
        if eff_to and td > eff_to:
            return False
        return True
    except Exception:
        return False


def resolve_parameter(owner_uid: str, parameter_type: str, target_date: str,
                      legal_entity_id: str = "", sandbox: bool = True) -> Optional[dict]:
    """Busca el parámetro vigente en target_date.

    Lógica: effectiveFrom <= target_date AND (effectiveTo >= target_date OR effectiveTo == "")
    """
    if not firebase_initialized or db_firestore is None:
        return None

    try:
        coll = _legal_params_collection(owner_uid, sandbox)
        collection_ref = db_firestore.collection(coll)

        query = collection_ref.where(filter=FieldFilter("parameterType", "==", parameter_type))\
                              .where(filter=FieldFilter("isActive", "==", True))
        docs = query.get()

        matched = []
        for d in docs:
            doc_data = d.to_dict()
            ent_id = doc_data.get("legalEntityId", "")
            if legal_entity_id and ent_id and ent_id != legal_entity_id:
                continue
            eff_from = doc_data.get("effectiveFrom", "")
            eff_to = doc_data.get("effectiveTo", "")
            if _is_in_range(target_date, eff_from, eff_to):
                matched.append((doc_data, d.id))

        if not matched:
            return None

        matched.sort(key=lambda x: (x[0].get("version", 1), x[0].get("effectiveFrom", "")), reverse=True)
        return {**matched[0][0], "id": matched[0][1]}

    except Exception as e:
        print(f"⚠️ LegalParameterResolver.resolve_parameter({parameter_type}): {e}")
        return None


def resolve_all(owner_uid: str, target_date: str,
                legal_entity_id: str = "", sandbox: bool = True) -> dict:
    """Resuelve TODOS los parámetros vigentes en target_date.

    Retorna un dict con el mismo formato que PayrollService.get_rates().
    Si no hay parámetros configurados, retorna valores por defecto.
    """
    result = get_default_params()

    for param_type in PARAM_TYPES:
        param = resolve_parameter(owner_uid, param_type, target_date,
                                   legal_entity_id=legal_entity_id, sandbox=sandbox)
        if param:
            value = param.get("value")
            if value is not None:
                key = param_type
                if param_type == "isr_annual_table":
                    key = "isr_table"
                result[key] = value

    return result


def set_parameter(owner_uid: str, parameter_type: str, value: Any,
                  effective_from: str, effective_to: str = "",
                  legal_entity_id: str = "", user_email: str = "",
                  notes: str = "", sandbox: bool = True) -> Optional[str]:
    """Crea un nuevo parámetro. Si hay uno vigente sin effectiveTo, lo cierra.

    Auto-incrementa la versión. Retorna el ID del nuevo parámetro o None si falla.
    """
    if not firebase_initialized or db_firestore is None:
        return None

    try:
        coll = _legal_params_collection(owner_uid, sandbox)
        db = db_firestore.collection(coll)

        # Encontrar el registro activo con el version más alto
        current_version = 0
        docs = db.where("parameterType", "==", parameter_type)\
                 .where("isActive", "==", True).get()

        for d in docs:
            doc_data = d.to_dict()
            if legal_entity_id:
                if doc_data.get("legalEntityId", "") != legal_entity_id:
                    continue
            else:
                if doc_data.get("legalEntityId", ""):
                    continue

            # No tiene effectiveTo o aún está vigente
            eff_to = doc_data.get("effectiveTo", "")
            if not eff_to or _parse_date(eff_to) >= _parse_date(effective_from):
                ver = doc_data.get("version", 0)
                if ver > current_version:
                    current_version = ver
                    # Cerrar este registro
                    close_date = (_parse_date(effective_from) - timedelta(days=1)).isoformat()
                    if not eff_to:
                        d.reference.update({
                            "effectiveTo": close_date,
                            "isActive": False,
                            "updatedAt": datetime.now(timezone.utc).isoformat(),
                        })

        # Crear nuevo parámetro con version incrementada
        new_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        param = LegalParameter(
            id=new_id,
            parameterType=parameter_type,
            parameterName=PARAM_TYPE_INFO.get(parameter_type, {}).get("name", parameter_type),
            version=current_version + 1,
            value=value,
            effectiveFrom=effective_from,
            effectiveTo=effective_to or "",
            isActive=True,
            legalEntityId=legal_entity_id,
            supersedesVersion=current_version,
            createdBy=user_email,
            createdAt=now_iso,
            updatedBy=user_email,
            updatedAt=now_iso,
            notes=notes,
        )

        db.document(new_id).set(param.model_dump())
        return new_id

    except Exception as e:
        print(f"⚠️ LegalParameterResolver.set_parameter({parameter_type}): {e}")
        return None


def get_parameter_history(owner_uid: str, parameter_type: str,
                          legal_entity_id: str = "", sandbox: bool = True) -> list:
    """Retorna el historial completo de versiones de un tipo de parámetro."""
    if not firebase_initialized or db_firestore is None:
        return []

    try:
        coll = _legal_params_collection(owner_uid, sandbox)
        query = db_firestore.collection(coll)\
                            .where("parameterType", "==", parameter_type)\
                            .order_by("version", direction="DESCENDING")
        docs = query.get()
        return [_doc_to_param(d) for d in docs]

    except Exception as e:
        print(f"⚠️ LegalParameterResolver.get_parameter_history({parameter_type}): {e}")
        return []


def seed_default_parameters(owner_uid: str, sandbox: bool = True):
    """Siembra los parámetros por defecto si no existen ya."""
    if not firebase_initialized or db_firestore is None:
        return

    today = date.today().isoformat()
    for param_type, info in PARAM_TYPE_INFO.items():
        existing = resolve_parameter(owner_uid, param_type, today, sandbox=sandbox)
        if existing:
            continue
        set_parameter(
            owner_uid=owner_uid,
            parameter_type=param_type,
            value=info["default"],
            effective_from="2024-01-01",
            legal_entity_id="",
            user_email="system",
            notes="Parámetro inicial por defecto",
            sandbox=sandbox,
        )


PARAM_TYPE_INFO = PARAM_TYPES