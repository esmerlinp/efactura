"""
API REST para el módulo CRM de VykOne (Fases 5.1, 5.1.1 y 5.2).

Expone las entidades, transiciones, métricas y mutations del CRM de forma segura,
multi-tenant y reutilizando estrictamente los servicios de dominio
(CRMService, ContactService, DatabaseService).
"""

import uuid
from datetime import date, datetime, timezone
from uuid import UUID
from flask import Blueprint, request, jsonify, g

from app.api.auth import require_crm_auth, gate_api_blueprint_module
from app.services.crm_service import CRMService
from app.services.contact_service import ContactService
from app.services.db_service import DatabaseService


api_crm_bp = Blueprint("api_crm", __name__)
gate_api_blueprint_module(api_crm_bp, "crm")


# ─────────────────────────────────────────────────────────────────────────────
# Serialization & Response Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value, default=0.0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    try:
        return int(float(value or default))
    except (TypeError, ValueError):
        return default


def _serialize_crm(obj):
    """Serializa estructuras de datos del CRM asegurando tipos JSON estándar y protegiendo campos sensibles."""
    if obj is None:
        return None
    if isinstance(obj, (int, float, str, bool)):
        return obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, dict):
        excluded = {"accessPin", "apiKey", "hashedPassword", "secret", "privateKey", "_private"}
        return {k: _serialize_crm(v) for k, v in obj.items() if k not in excluded and not k.startswith("_")}
    if isinstance(obj, (list, tuple, set)):
        return [_serialize_crm(item) for item in obj]
    if hasattr(obj, "model_dump"):
        return _serialize_crm(obj.model_dump())
    if hasattr(obj, "dict") and callable(obj.dict):
        return _serialize_crm(obj.dict())
    if hasattr(obj, "__dict__"):
        return _serialize_crm({k: v for k, v in obj.__dict__.items() if not k.startswith("_")})
    return str(obj)


def api_error(code: str, message: str, status_code: int = 400):
    """Genera una respuesta de error JSON estándar de la API."""
    return jsonify({
        "success": False,
        "error": {
            "code": code,
            "message": message,
        }
    }), status_code


def api_success(data: dict = None, status_code: int = 200, **kwargs):
    """Genera una respuesta exitosa JSON estándar de la API."""
    payload = {"success": True}
    if data is not None:
        if isinstance(data, dict):
            payload.update(data)
        else:
            payload["data"] = data
    payload.update(kwargs)
    return jsonify(_serialize_crm(payload)), status_code


def _get_json_body():
    """Obtiene el payload JSON del request de manera segura."""
    if not request.is_json:
        data = request.get_json(silent=True)
        if data is None:
            return None
        return data
    return request.get_json(silent=True) or {}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Contactos CRM (Read & Mutations)
# ─────────────────────────────────────────────────────────────────────────────

@api_crm_bp.route("/crm/contacts", methods=["GET"])
@require_crm_auth(required_permission="canCRMContacts")
def list_contacts():
    """
    Listar contactos y leads del CRM.
    Permite filtrar por búsqueda de texto, tipo de contacto, sucursal y proyecto.
    """
    try:
        company_id = g.company_id
        owner_uid = g.owner_uid
        sandbox = g.sandbox_mode

        search = (request.args.get("search") or "").strip()[:100].lower()
        contact_type = (request.args.get("type") or "").strip()[:50].lower()
        branch_id = (request.args.get("branch_id") or g.branch_id or "").strip()[:100] or None
        project_id = (request.args.get("project_id") or g.project_id or "").strip()[:100] or None

        # Validación estricta de paginación
        raw_limit = request.args.get("limit", 50)
        raw_offset = request.args.get("offset", 0)
        try:
            limit = int(raw_limit)
            offset = int(raw_offset)
            if limit <= 0 or offset < 0:
                return api_error("INVALID_PAGINATION", "Los parámetros 'limit' (> 0) y 'offset' (>= 0) deben ser válidos.", 400)
            limit = min(200, limit)
        except (ValueError, TypeError):
            return api_error("INVALID_PAGINATION", "Los parámetros 'limit' y 'offset' deben ser enteros válidos.", 400)

        all_contacts = ContactService.get_contacts(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id)

        filtered = []
        for c in all_contacts:
            if c.get("isDeleted"):
                continue
            if branch_id and c.get("branchId") != branch_id:
                continue
            if project_id and c.get("projectId") != project_id:
                continue
            if contact_type:
                types = [t.lower() for t in c.get("types", [])]
                if contact_type not in types:
                    continue
            if search:
                text_corpus = f"{c.get('razonSocial', '')} {c.get('rnc', '')} {c.get('email', '')} {c.get('telefono', '')}".lower()
                if search not in text_corpus:
                    continue
            filtered.append(c)

        total = len(filtered)
        paginated = filtered[offset: offset + limit]

        return api_success({
            "contacts": paginated,
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    except Exception as e:
        print(f"⚠️ Error en API CRM contacts: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al procesar la solicitud de contactos.", 500)


@api_crm_bp.route("/crm/contacts/<contact_id>", methods=["GET"])
@require_crm_auth(required_permission="canCRMContacts")
def get_contact_detail(contact_id: str):
    """Obtener el detalle de un contacto por ID."""
    try:
        contact_id = (contact_id or "").strip()[:128]
        if not contact_id:
            return api_error("INVALID_PARAMETER", "El ID del contacto es requerido.", 400)

        contact = ContactService.get_contact(
            owner_uid=g.owner_uid,
            contact_id=contact_id,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )

        if not contact or contact.get("isDeleted"):
            return api_error("CONTACT_NOT_FOUND", "Contacto no encontrado.", 404)

        return api_success({"contact": contact})
    except Exception as e:
        print(f"⚠️ Error en API CRM contact detail: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al procesar la solicitud.", 500)


@api_crm_bp.route("/crm/contacts/<contact_id>/360", methods=["GET"])
@require_crm_auth(required_permission="canCRMContacts")
def get_contact_360(contact_id: str):
    """Obtener la vista unificada Contact 360 (perfil, oportunidades, actividades, métricas y timeline)."""
    try:
        contact_id = (contact_id or "").strip()[:128]
        if not contact_id:
            return api_error("INVALID_PARAMETER", "El ID del contacto es requerido.", 400)

        data = CRMService.get_contact_360(
            owner_uid=g.owner_uid,
            contact_id=contact_id,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )

        if not data or not data.get("contact") or data["contact"].get("isDeleted"):
            return api_error("CONTACT_NOT_FOUND", "Contacto no encontrado.", 404)

        return api_success(data)
    except Exception as e:
        print(f"⚠️ Error en API CRM contact 360: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al procesar la solicitud.", 500)


@api_crm_bp.route("/crm/contacts", methods=["POST"])
@require_crm_auth(required_permission="canCRMContacts")
def create_contact():
    """Crear un nuevo contacto/lead en el CRM."""
    try:
        body = _get_json_body()
        if body is None:
            return api_error("INVALID_BODY", "El cuerpo de la petición debe ser un objeto JSON válido.", 400)

        razon_social = (body.get("razonSocial") or body.get("name") or "").strip()[:200]
        if not razon_social:
            return api_error("INVALID_PARAMETER", "El nombre o razón social ('razonSocial') es requerido.", 400)

        contact_id = (body.get("id") or str(uuid.uuid4())).strip()[:128]

        # Validar y normalizar tipos de contacto
        types = body.get("types")
        if not isinstance(types, list) or not types:
            types = ["lead"]
        else:
            types = [str(t).strip()[:50] for t in types if str(t).strip()]

        contact_dict = {
            "razonSocial": razon_social,
            "rnc": (body.get("rnc") or "").strip()[:20],
            "email": (body.get("email") or "").strip()[:100],
            "telefono": (body.get("telefono") or "").strip()[:50],
            "telefono2": (body.get("telefono2") or "").strip()[:50],
            "celular": (body.get("celular") or "").strip()[:50],
            "direccion": (body.get("direccion") or "").strip()[:300],
            "municipio": (body.get("municipio") or "").strip()[:100],
            "provincia": (body.get("provincia") or "").strip()[:100],
            "pais": (body.get("pais") or "República Dominicana").strip()[:100],
            "types": types,
            "pipelineStage": "Prospecto",  # Default inicial inmutable directamente por REST
            "responsibleId": (body.get("responsibleId") or body.get("responsible_id") or "").strip()[:128],
            "branchId": (body.get("branchId") or body.get("branch_id") or g.branch_id or "default-sucursal-principal").strip()[:100],
            "projectId": (body.get("projectId") or body.get("project_id") or g.project_id or "").strip()[:100] or None,
            "notes": (body.get("notes") or "").strip()[:5000],
            "customer_category": (body.get("customer_category") or "NORMAL").strip()[:50],
            "foreignTaxId": (body.get("foreignTaxId") or "").strip()[:50],
            "tipoPersona": (body.get("tipoPersona") or "fisica").strip()[:50],
            "supplierType": (body.get("supplierType") or "formal").strip()[:50],
            "creditDays": _safe_int(body.get("creditDays")),
            "creditLimit": _safe_float(body.get("creditLimit")),
            "paymentMethod": (body.get("paymentMethod") or "Efectivo").strip()[:50],
            "currency": (body.get("currency") or "DOP").strip()[:10],
            "itbisWithholding": bool(body.get("itbisWithholding", False)),
            "isrWithholding": bool(body.get("isrWithholding", False)),
            "tipoGastoDGII": (body.get("tipoGastoDGII") or "02").strip()[:10],
            "ecfTypeEmits": (body.get("ecfTypeEmits") or "E31").strip()[:10],
            "estado": "Activo",
        }

        saved = ContactService.save_contact(
            owner_uid=g.owner_uid,
            contact_id=contact_id,
            contact_dict=contact_dict,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )

        return api_success({"message": "Contacto creado exitosamente.", "contact": saved}, status_code=201)
    except Exception as e:
        print(f"⚠️ Error en API CRM create contact: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al crear el contacto.", 500)


@api_crm_bp.route("/crm/contacts/<contact_id>", methods=["PATCH"])
@require_crm_auth(required_permission="canCRMContacts")
def update_contact(contact_id: str):
    """Actualizar datos editables de un contacto."""
    try:
        contact_id = (contact_id or "").strip()[:128]
        if not contact_id:
            return api_error("INVALID_PARAMETER", "El ID del contacto es requerido.", 400)

        body = _get_json_body()
        if body is None:
            return api_error("INVALID_BODY", "El cuerpo de la petición debe ser un objeto JSON válido.", 400)

        existing = ContactService.get_contact(
            owner_uid=g.owner_uid,
            contact_id=contact_id,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )
        if not existing or existing.get("isDeleted"):
            return api_error("CONTACT_NOT_FOUND", "Contacto no encontrado.", 404)

        # Campos editables permitidos
        if "razonSocial" in body or "name" in body:
            existing["razonSocial"] = (body.get("razonSocial") or body.get("name") or "").strip()[:200]
        if "rnc" in body:
            existing["rnc"] = (body.get("rnc") or "").strip()[:20]
        if "email" in body:
            existing["email"] = (body.get("email") or "").strip()[:100]
        if "telefono" in body:
            existing["telefono"] = (body.get("telefono") or "").strip()[:50]
        if "telefono2" in body:
            existing["telefono2"] = (body.get("telefono2") or "").strip()[:50]
        if "celular" in body:
            existing["celular"] = (body.get("celular") or "").strip()[:50]
        if "direccion" in body:
            existing["direccion"] = (body.get("direccion") or "").strip()[:300]
        if "municipio" in body:
            existing["municipio"] = (body.get("municipio") or "").strip()[:100]
        if "provincia" in body:
            existing["provincia"] = (body.get("provincia") or "").strip()[:100]
        if "pais" in body:
            existing["pais"] = (body.get("pais") or "").strip()[:100]
        if "types" in body and isinstance(body["types"], list):
            existing["types"] = [str(t).strip()[:50] for t in body["types"] if str(t).strip()]
        if "notes" in body:
            existing["notes"] = (body.get("notes") or "").strip()[:5000]
        if "responsibleId" in body or "responsible_id" in body:
            existing["responsibleId"] = (body.get("responsibleId") or body.get("responsible_id") or "").strip()[:128]
        if "branchId" in body or "branch_id" in body:
            existing["branchId"] = (body.get("branchId") or body.get("branch_id") or "").strip()[:100]
        if "projectId" in body or "project_id" in body:
            existing["projectId"] = (body.get("projectId") or body.get("project_id") or "").strip()[:100] or None
        if "customer_category" in body:
            existing["customer_category"] = (body.get("customer_category") or "NORMAL").strip()[:50]
        if "foreignTaxId" in body:
            existing["foreignTaxId"] = (body.get("foreignTaxId") or "").strip()[:50]
        if "creditDays" in body:
            existing["creditDays"] = _safe_int(body.get("creditDays"))
        if "creditLimit" in body:
            existing["creditLimit"] = _safe_float(body.get("creditLimit"))
        if "paymentMethod" in body:
            existing["paymentMethod"] = (body.get("paymentMethod") or "Efectivo").strip()[:50]

        saved = ContactService.save_contact(
            owner_uid=g.owner_uid,
            contact_id=contact_id,
            contact_dict=existing,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )

        return api_success({"message": "Contacto actualizado exitosamente.", "contact": saved}, status_code=200)
    except Exception as e:
        print(f"⚠️ Error en API CRM update contact: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al actualizar el contacto.", 500)


@api_crm_bp.route("/crm/contacts/<contact_id>", methods=["DELETE"])
@require_crm_auth(required_permission="canCRMContacts")
def delete_contact_endpoint(contact_id: str):
    """Eliminar de forma segura (Soft Delete CRM-08) un contacto."""
    try:
        contact_id = (contact_id or "").strip()[:128]
        if not contact_id:
            return api_error("INVALID_PARAMETER", "El ID del contacto es requerido.", 400)

        user_name = getattr(g, "user_name", "API User")
        ok = ContactService.delete_contact(
            owner_uid=g.owner_uid,
            contact_id=contact_id,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
            deleted_by=user_name,
        )

        if not ok:
            return api_error("CONTACT_NOT_FOUND", "Contacto no encontrado.", 404)

        return api_success({"message": "Contacto eliminado correctamente."}, status_code=200)
    except Exception as e:
        print(f"⚠️ Error en API CRM delete contact: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al eliminar el contacto.", 500)


@api_crm_bp.route("/crm/contacts/<contact_id>/quick-note", methods=["POST"])
@require_crm_auth(required_permission="canCRMContacts")
def contact_quick_note(contact_id: str):
    """Registrar una interacción rápida en la ficha del contacto."""
    try:
        contact_id = (contact_id or "").strip()[:128]
        if not contact_id:
            return api_error("INVALID_PARAMETER", "El ID del contacto es requerido.", 400)

        body = _get_json_body()
        if body is None:
            return api_error("INVALID_BODY", "El cuerpo de la petición debe ser un objeto JSON válido.", 400)

        content = (body.get("content") or body.get("note") or "").strip()[:5000]
        if not content:
            return api_error("INVALID_PARAMETER", "El contenido de la interacción ('content' o 'note') es requerido.", 400)

        contact = ContactService.get_contact(
            owner_uid=g.owner_uid,
            contact_id=contact_id,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )
        if not contact or contact.get("isDeleted"):
            return api_error("CONTACT_NOT_FOUND", "Contacto no encontrado.", 404)

        user_name = getattr(g, "user_name", "API User")
        note_type = (body.get("type") or "Nota").strip()[:50]
        note_title = (body.get("title") or f"Interacción rápida ({note_type})").strip()[:200]

        interaction_id = str(uuid.uuid4())
        interaction_data = {
            "id": interaction_id,
            "type": note_type,
            "title": note_title,
            "content": content,
            "date": _now_iso(),
            "completed": True,
            "createdBy": user_name,
        }

        DatabaseService.save_client_interaction(
            owner_uid=g.owner_uid,
            client_id=contact_id,
            interaction_id=interaction_id,
            interaction_dict=interaction_data,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )

        return api_success({
            "message": "Interacción registrada correctamente.",
            "interaction": interaction_data,
        }, status_code=201)
    except Exception as e:
        print(f"⚠️ Error en API CRM contact quick note: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al registrar la nota en el contacto.", 500)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Oportunidades Comerciales (Read & Mutations)
# ─────────────────────────────────────────────────────────────────────────────

@api_crm_bp.route("/crm/opportunities", methods=["GET"])
@require_crm_auth(required_permission="canCRMOpportunities")
def list_opportunities():
    """
    Listar oportunidades comerciales del pipeline.
    Soporta filtros por stage, status, assigned_to, contact_id, branch_id, project_id.
    """
    try:
        company_id = g.company_id
        owner_uid = g.owner_uid
        sandbox = g.sandbox_mode

        stage = (request.args.get("stage") or "").strip()[:50] or None
        status = (request.args.get("status") or "").strip()[:50] or None
        assigned_to = (request.args.get("assigned_to") or request.args.get("assignedTo") or "").strip()[:100] or None
        contact_id = (request.args.get("contact_id") or request.args.get("contactId") or "").strip()[:128] or None
        branch_id = (request.args.get("branch_id") or g.branch_id or "").strip()[:100] or None
        project_id = (request.args.get("project_id") or g.project_id or "").strip()[:100] or None
        include_closed = request.args.get("include_closed", "true").lower() in ("true", "1")

        # Validación de paginación
        raw_limit = request.args.get("limit", 50)
        raw_offset = request.args.get("offset", 0)
        try:
            limit = int(raw_limit)
            offset = int(raw_offset)
            if limit <= 0 or offset < 0:
                return api_error("INVALID_PAGINATION", "Los parámetros 'limit' (> 0) y 'offset' (>= 0) deben ser válidos.", 400)
            limit = min(200, limit)
        except (ValueError, TypeError):
            return api_error("INVALID_PAGINATION", "Los parámetros 'limit' y 'offset' deben ser enteros válidos.", 400)

        all_opps = CRMService.get_opportunities(
            owner_uid=owner_uid,
            sandbox=sandbox,
            company_id=company_id,
            include_closed=include_closed,
            branch_id=branch_id,
            project_id=project_id,
            contact_id=contact_id,
        )

        filtered = []
        for opp in all_opps:
            if opp.get("isDeleted"):
                continue
            if stage and opp.get("stage") != stage:
                continue
            if status and opp.get("status") != status:
                continue
            if assigned_to and opp.get("assignedTo") != assigned_to:
                continue
            filtered.append(opp)

        total = len(filtered)
        paginated = filtered[offset: offset + limit]

        return api_success({
            "opportunities": paginated,
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    except Exception as e:
        print(f"⚠️ Error en API CRM opportunities: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al procesar la solicitud de oportunidades.", 500)


@api_crm_bp.route("/crm/opportunities/<opportunity_id>", methods=["GET"])
@require_crm_auth(required_permission="canCRMOpportunities")
def get_opportunity_detail(opportunity_id: str):
    """Obtener el detalle de una oportunidad comercial por ID."""
    try:
        opportunity_id = (opportunity_id or "").strip()[:128]
        if not opportunity_id:
            return api_error("INVALID_PARAMETER", "El ID de la oportunidad es requerido.", 400)

        opportunity = CRMService.get_opportunity(
            owner_uid=g.owner_uid,
            opportunity_id=opportunity_id,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )

        if not opportunity or opportunity.get("isDeleted"):
            return api_error("OPPORTUNITY_NOT_FOUND", "Oportunidad no encontrada.", 404)

        return api_success({"opportunity": opportunity})
    except Exception as e:
        print(f"⚠️ Error en API CRM opportunity detail: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al procesar la solicitud.", 500)


@api_crm_bp.route("/crm/opportunities", methods=["POST"])
@require_crm_auth(required_permission="canCRMOpportunities")
def create_opportunity():
    """Crear una nueva oportunidad comercial en el pipeline."""
    try:
        body = _get_json_body()
        if body is None:
            return api_error("INVALID_BODY", "El cuerpo de la petición debe ser un objeto JSON válido.", 400)

        title = (body.get("title") or body.get("name") or "").strip()[:200]
        contact_id = (body.get("contactId") or body.get("contact_id") or body.get("clientId") or body.get("client_id") or "").strip()[:128]

        if not title and not contact_id:
            return api_error("INVALID_PARAMETER", "Se requiere al menos un título o un contacto para crear la oportunidad.", 400)

        opportunity_id = (body.get("id") or str(uuid.uuid4())).strip()[:128]
        stage = (body.get("stage") or "Prospecto").strip()[:50]
        user_name = getattr(g, "user_name", "API User")

        opportunity_dict = {
            "title": title,
            "contactId": contact_id,
            "amount": _safe_float(body.get("amount")),
            "stage": stage,
            "probability": _safe_int(body.get("probability")) if "probability" in body else None,
            "assignedTo": (body.get("assignedTo") or body.get("assigned_to") or "").strip()[:100],
            "branchId": (body.get("branchId") or body.get("branch_id") or g.branch_id or "default-sucursal-principal").strip()[:100],
            "projectId": (body.get("projectId") or body.get("project_id") or g.project_id or "").strip()[:100] or None,
            "expectedCloseDate": (body.get("expectedCloseDate") or body.get("expected_close_date") or "").strip()[:20],
            "quotationId": (body.get("quotationId") or body.get("quotation_id") or "").strip()[:128],
            "notes": (body.get("notes") or "").strip()[:5000],
            "source": (body.get("source") or "API").strip()[:50],
            "createdBy": user_name,
        }

        # Inicializar stageHistory si se crea en etapa avanzada preservando trazabilidad
        if stage and stage != "Prospecto":
            opportunity_dict["stageHistory"] = [{
                "from": "",
                "to": stage,
                "by": user_name,
                "timestamp": _now_iso(),
                "notes": "Creación inicial en etapa",
            }]

        saved = CRMService.save_opportunity(
            owner_uid=g.owner_uid,
            opportunity_id=opportunity_id,
            opportunity_dict=opportunity_dict,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )

        return api_success({"message": "Oportunidad creada exitosamente.", "opportunity": saved}, status_code=201)
    except Exception as e:
        print(f"⚠️ Error en API CRM create opportunity: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al crear la oportunidad.", 500)


@api_crm_bp.route("/crm/opportunities/<opportunity_id>", methods=["PATCH"])
@require_crm_auth(required_permission="canCRMOpportunities")
def update_opportunity(opportunity_id: str):
    """Actualizar datos editables de una oportunidad o ejecutar transición de etapa."""
    try:
        opportunity_id = (opportunity_id or "").strip()[:128]
        if not opportunity_id:
            return api_error("INVALID_PARAMETER", "El ID de la oportunidad es requerido.", 400)

        body = _get_json_body()
        if body is None:
            return api_error("INVALID_BODY", "El cuerpo de la petición debe ser un objeto JSON válido.", 400)

        existing = CRMService.get_opportunity(
            owner_uid=g.owner_uid,
            opportunity_id=opportunity_id,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )
        if not existing or existing.get("isDeleted"):
            return api_error("OPPORTUNITY_NOT_FOUND", "Oportunidad no encontrada.", 404)

        user_name = getattr(g, "user_name", "API User")

        # 1. Si se solicita cambio de etapa, delegar estrictamente en CRMService.transition_opportunity
        if "stage" in body and body["stage"] != existing.get("stage"):
            target_stage = str(body["stage"]).strip()[:50]
            lost_reason = (body.get("lostReason") or body.get("lost_reason") or "").strip()[:500]
            invoice_id = (body.get("invoiceId") or body.get("invoice_id") or "").strip()[:128]
            invoice_number = (body.get("invoiceNumber") or body.get("invoice_number") or "").strip()[:100]
            notes = (body.get("notes") or "").strip()[:5000]

            ok, msg, transitioned = CRMService.transition_opportunity(
                owner_uid=g.owner_uid,
                opportunity_id=opportunity_id,
                target_stage=target_stage,
                sandbox=g.sandbox_mode,
                company_id=g.company_id,
                user_name=user_name,
                lost_reason=lost_reason,
                invoice_id=invoice_id,
                invoice_number=invoice_number,
                notes=notes,
            )
            if not ok:
                return api_error("INVALID_TRANSITION", msg, 400)
            existing = transitioned

        # 2. Actualizar otros campos editables
        if "title" in body or "name" in body:
            existing["title"] = (body.get("title") or body.get("name") or "").strip()[:200]
        if "amount" in body:
            existing["amount"] = _safe_float(body.get("amount"))
        if "probability" in body:
            existing["probability"] = max(0, min(100, _safe_int(body.get("probability"))))
        if "assignedTo" in body or "assigned_to" in body:
            existing["assignedTo"] = (body.get("assignedTo") or body.get("assigned_to") or "").strip()[:100]
        if "expectedCloseDate" in body or "expected_close_date" in body:
            existing["expectedCloseDate"] = (body.get("expectedCloseDate") or body.get("expected_close_date") or "").strip()[:20]
        if "branchId" in body or "branch_id" in body:
            existing["branchId"] = (body.get("branchId") or body.get("branch_id") or "").strip()[:100]
        if "projectId" in body or "project_id" in body:
            existing["projectId"] = (body.get("projectId") or body.get("project_id") or "").strip()[:100] or None
        if "notes" in body and "stage" not in body:
            existing["notes"] = (body.get("notes") or "").strip()[:5000]
        if "source" in body:
            existing["source"] = (body.get("source") or "API").strip()[:50]
        if "contactId" in body or "contact_id" in body:
            existing["contactId"] = (body.get("contactId") or body.get("contact_id") or "").strip()[:128]
        if "quotationId" in body or "quotation_id" in body:
            existing["quotationId"] = (body.get("quotationId") or body.get("quotation_id") or "").strip()[:128]

        saved = CRMService.save_opportunity(
            owner_uid=g.owner_uid,
            opportunity_id=opportunity_id,
            opportunity_dict=existing,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )

        return api_success({"message": "Oportunidad actualizada exitosamente.", "opportunity": saved}, status_code=200)
    except Exception as e:
        print(f"⚠️ Error en API CRM update opportunity: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al actualizar la oportunidad.", 500)


@api_crm_bp.route("/crm/opportunities/<opportunity_id>/stage", methods=["POST"])
@require_crm_auth(required_permission="canCRMOpportunities")
def transition_opportunity_endpoint(opportunity_id: str):
    """Transicionar formalmente de etapa una oportunidad validando la máquina de estados CRM."""
    try:
        opportunity_id = (opportunity_id or "").strip()[:128]
        if not opportunity_id:
            return api_error("INVALID_PARAMETER", "El ID de la oportunidad es requerido.", 400)

        body = _get_json_body()
        if body is None:
            return api_error("INVALID_BODY", "El cuerpo de la petición debe ser un objeto JSON válido.", 400)

        target_stage = (body.get("stage") or "").strip()[:50]
        if not target_stage:
            return api_error("INVALID_PARAMETER", "El campo 'stage' es requerido para la transición.", 400)

        user_name = getattr(g, "user_name", "API User")
        lost_reason = (body.get("lostReason") or body.get("lost_reason") or "").strip()[:500]
        invoice_id = (body.get("invoiceId") or body.get("invoice_id") or "").strip()[:128]
        invoice_number = (body.get("invoiceNumber") or body.get("invoice_number") or "").strip()[:100]
        total_amount = _safe_float(body.get("totalAmount") or body.get("total_amount") or body.get("amount") or 0.0)
        notes = (body.get("notes") or "").strip()[:5000]

        ok, msg, opp = CRMService.transition_opportunity(
            owner_uid=g.owner_uid,
            opportunity_id=opportunity_id,
            target_stage=target_stage,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
            user_name=user_name,
            lost_reason=lost_reason,
            invoice_id=invoice_id,
            invoice_number=invoice_number,
            total_amount=total_amount,
            notes=notes,
        )

        if not ok:
            if msg == "Oportunidad no encontrada.":
                return api_error("OPPORTUNITY_NOT_FOUND", msg, 404)
            return api_error("INVALID_TRANSITION", msg, 400)

        return api_success({"message": msg, "opportunity": opp}, status_code=200)
    except Exception as e:
        print(f"⚠️ Error en API CRM transition opportunity: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al procesar la transición de la oportunidad.", 500)


@api_crm_bp.route("/crm/opportunities/<opportunity_id>", methods=["DELETE"])
@require_crm_auth(required_permission="canCRMOpportunities")
def delete_opportunity_endpoint(opportunity_id: str):
    """Eliminación segura (Soft Delete CRM-08) de una oportunidad comercial."""
    try:
        opportunity_id = (opportunity_id or "").strip()[:128]
        if not opportunity_id:
            return api_error("INVALID_PARAMETER", "El ID de la oportunidad es requerido.", 400)

        user_name = getattr(g, "user_name", "API User")
        ok = CRMService.delete_opportunity(
            owner_uid=g.owner_uid,
            opportunity_id=opportunity_id,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
            deleted_by=user_name,
        )

        if not ok:
            return api_error("OPPORTUNITY_NOT_FOUND", "Oportunidad no encontrada.", 404)

        return api_success({"message": "Oportunidad eliminada correctamente."}, status_code=200)
    except Exception as e:
        print(f"⚠️ Error en API CRM delete opportunity: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al eliminar la oportunidad.", 500)


@api_crm_bp.route("/crm/opportunities/<opportunity_id>/quick-note", methods=["POST"])
@require_crm_auth(required_permission="canCRMOpportunities")
def opportunity_quick_note(opportunity_id: str):
    """Registrar una nota rápida o interacción comercial en la oportunidad."""
    try:
        opportunity_id = (opportunity_id or "").strip()[:128]
        if not opportunity_id:
            return api_error("INVALID_PARAMETER", "El ID de la oportunidad es requerido.", 400)

        body = _get_json_body()
        if body is None:
            return api_error("INVALID_BODY", "El cuerpo de la petición debe ser un objeto JSON válido.", 400)

        note_content = (body.get("content") or body.get("note") or "").strip()[:5000]
        if not note_content:
            return api_error("INVALID_PARAMETER", "El contenido de la nota ('content' o 'note') es requerido.", 400)

        opp = CRMService.get_opportunity(
            owner_uid=g.owner_uid,
            opportunity_id=opportunity_id,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )
        if not opp or opp.get("isDeleted"):
            return api_error("OPPORTUNITY_NOT_FOUND", "Oportunidad no encontrada.", 404)

        user_name = getattr(g, "user_name", "API User")
        now_stamp = _now_iso()[:10]
        updated_notes = f"{opp.get('notes', '')}\n[{now_stamp} - {user_name}]: {note_content}".strip()
        opp["notes"] = updated_notes
        saved = CRMService.save_opportunity(
            owner_uid=g.owner_uid,
            opportunity_id=opportunity_id,
            opportunity_dict=opp,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )

        if opp.get("contactId"):
            try:
                DatabaseService.save_client_interaction(
                    owner_uid=g.owner_uid,
                    client_id=opp["contactId"],
                    interaction_id=str(uuid.uuid4()),
                    interaction_dict={
                        "type": "Nota",
                        "title": f"Nota en oportunidad: {opp.get('title')}",
                        "content": note_content,
                        "date": _now_iso(),
                        "completed": True,
                        "createdBy": user_name,
                    },
                    sandbox=g.sandbox_mode,
                    company_id=g.company_id,
                )
            except Exception:
                pass

        return api_success({"message": "Nota agregada correctamente.", "opportunity": saved}, status_code=201)
    except Exception as e:
        print(f"⚠️ Error en API CRM opportunity quick note: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al registrar la nota en la oportunidad.", 500)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Actividades CRM (Read & Mutations)
# ─────────────────────────────────────────────────────────────────────────────

@api_crm_bp.route("/crm/activities", methods=["GET"])
@require_crm_auth(required_permission="canCRMActivities")
def list_activities():
    """
    Listar actividades y tareas comerciales del CRM.
    Soporta filtros por status, assigned_to, contact_id, opportunity_id, branch_id, project_id.
    """
    try:
        company_id = g.company_id
        owner_uid = g.owner_uid
        sandbox = g.sandbox_mode

        status = (request.args.get("status") or "").strip()[:50] or None
        assigned_to = (request.args.get("assigned_to") or request.args.get("assignedTo") or "").strip()[:100] or None
        contact_id = (request.args.get("contact_id") or request.args.get("contactId") or "").strip()[:128] or None
        opportunity_id = (request.args.get("opportunity_id") or request.args.get("opportunityId") or "").strip()[:128] or None
        branch_id = (request.args.get("branch_id") or g.branch_id or "").strip()[:100] or None
        project_id = (request.args.get("project_id") or g.project_id or "").strip()[:100] or None
        include_completed = request.args.get("include_completed", "true").lower() in ("true", "1")

        # Validación de paginación
        raw_limit = request.args.get("limit", 50)
        raw_offset = request.args.get("offset", 0)
        try:
            limit = int(raw_limit)
            offset = int(raw_offset)
            if limit <= 0 or offset < 0:
                return api_error("INVALID_PAGINATION", "Los parámetros 'limit' (> 0) y 'offset' (>= 0) deben ser válidos.", 400)
            limit = min(200, limit)
        except (ValueError, TypeError):
            return api_error("INVALID_PAGINATION", "Los parámetros 'limit' y 'offset' deben ser enteros válidos.", 400)

        all_acts = CRMService.get_activities(
            owner_uid=owner_uid,
            sandbox=sandbox,
            include_completed=include_completed,
            company_id=company_id,
            branch_id=branch_id,
            project_id=project_id,
            contact_id=contact_id,
            opportunity_id=opportunity_id,
        )

        filtered = []
        for act in all_acts:
            if act.get("isDeleted"):
                continue
            if status and act.get("status") != status:
                continue
            if assigned_to and act.get("assignedTo") != assigned_to:
                continue
            filtered.append(act)

        total = len(filtered)
        paginated = filtered[offset: offset + limit]

        return api_success({
            "activities": paginated,
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    except Exception as e:
        print(f"⚠️ Error en API CRM activities: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al procesar la solicitud de actividades.", 500)


@api_crm_bp.route("/crm/activities", methods=["POST"])
@require_crm_auth(required_permission="canCRMActivities")
def create_activity():
    """Crear una nueva actividad/tarea comercial en el CRM."""
    try:
        body = _get_json_body()
        if body is None:
            return api_error("INVALID_BODY", "El cuerpo de la petición debe ser un objeto JSON válido.", 400)

        activity_id = (body.get("id") or str(uuid.uuid4())).strip()[:128]
        activity_type = (body.get("type") or "Tarea").strip()[:50]
        title = (body.get("title") or activity_type).strip()[:200]
        user_name = getattr(g, "user_name", "API User")

        activity_dict = {
            "title": title,
            "type": activity_type,
            "description": (body.get("description") or "").strip()[:5000],
            "dueDate": (body.get("dueDate") or body.get("due_date") or "").strip()[:20],
            "priority": (body.get("priority") or "media").strip()[:20],
            "status": (body.get("status") or "pendiente").strip()[:20],
            "contactId": (body.get("contactId") or body.get("contact_id") or "").strip()[:128],
            "opportunityId": (body.get("opportunityId") or body.get("opportunity_id") or "").strip()[:128],
            "assignedTo": (body.get("assignedTo") or body.get("assigned_to") or "").strip()[:100],
            "branchId": (body.get("branchId") or body.get("branch_id") or g.branch_id or "default-sucursal-principal").strip()[:100],
            "projectId": (body.get("projectId") or body.get("project_id") or g.project_id or "").strip()[:100] or None,
            "createdBy": user_name,
        }

        saved = CRMService.save_activity(
            owner_uid=g.owner_uid,
            activity_id=activity_id,
            activity_dict=activity_dict,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )

        return api_success({"message": "Actividad creada exitosamente.", "activity": saved}, status_code=201)
    except Exception as e:
        print(f"⚠️ Error en API CRM create activity: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al crear la actividad.", 500)


@api_crm_bp.route("/crm/activities/<activity_id>", methods=["PATCH"])
@require_crm_auth(required_permission="canCRMActivities")
def update_activity(activity_id: str):
    """Actualizar datos editables de una actividad."""
    try:
        activity_id = (activity_id or "").strip()[:128]
        if not activity_id:
            return api_error("INVALID_PARAMETER", "El ID de la actividad es requerido.", 400)

        body = _get_json_body()
        if body is None:
            return api_error("INVALID_BODY", "El cuerpo de la petición debe ser un objeto JSON válido.", 400)

        existing = CRMService.get_activity(
            owner_uid=g.owner_uid,
            activity_id=activity_id,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )
        if not existing or existing.get("isDeleted"):
            return api_error("ACTIVITY_NOT_FOUND", "Actividad no encontrada.", 404)

        # Si se solicita completar la actividad, invocar complete_activity para preservar SLA y nextContactDate
        if body.get("status") == "completada" and existing.get("status") != "completada":
            CRMService.complete_activity(
                owner_uid=g.owner_uid,
                activity_id=activity_id,
                sandbox=g.sandbox_mode,
                company_id=g.company_id,
            )
            existing = CRMService.get_activity(
                owner_uid=g.owner_uid,
                activity_id=activity_id,
                sandbox=g.sandbox_mode,
                company_id=g.company_id,
            )

        if "title" in body:
            existing["title"] = (body.get("title") or "").strip()[:200]
        if "type" in body:
            existing["type"] = (body.get("type") or "Tarea").strip()[:50]
        if "description" in body:
            existing["description"] = (body.get("description") or "").strip()[:5000]
        if "dueDate" in body or "due_date" in body:
            existing["dueDate"] = (body.get("dueDate") or body.get("due_date") or "").strip()[:20]
        if "priority" in body:
            existing["priority"] = (body.get("priority") or "media").strip()[:20]
        if "status" in body and body["status"] != "completada":
            existing["status"] = (body.get("status") or "pendiente").strip()[:20]
        if "assignedTo" in body or "assigned_to" in body:
            existing["assignedTo"] = (body.get("assignedTo") or body.get("assigned_to") or "").strip()[:100]
        if "branchId" in body or "branch_id" in body:
            existing["branchId"] = (body.get("branchId") or body.get("branch_id") or "").strip()[:100]
        if "projectId" in body or "project_id" in body:
            existing["projectId"] = (body.get("projectId") or body.get("project_id") or "").strip()[:100] or None
        if "contactId" in body or "contact_id" in body:
            existing["contactId"] = (body.get("contactId") or body.get("contact_id") or "").strip()[:128]
        if "opportunityId" in body or "opportunity_id" in body:
            existing["opportunityId"] = (body.get("opportunityId") or body.get("opportunity_id") or "").strip()[:128]

        saved = CRMService.save_activity(
            owner_uid=g.owner_uid,
            activity_id=activity_id,
            activity_dict=existing,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )

        return api_success({"message": "Actividad actualizada exitosamente.", "activity": saved}, status_code=200)
    except Exception as e:
        print(f"⚠️ Error en API CRM update activity: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al actualizar la actividad.", 500)


@api_crm_bp.route("/crm/activities/<activity_id>/complete", methods=["POST"])
@require_crm_auth(required_permission="canCRMActivities")
def complete_activity_endpoint(activity_id: str):
    """Completar una actividad CRM preservando SLA y sincronización de nextContactDate."""
    try:
        activity_id = (activity_id or "").strip()[:128]
        if not activity_id:
            return api_error("INVALID_PARAMETER", "El ID de la actividad es requerido.", 400)

        ok, msg = CRMService.complete_activity(
            owner_uid=g.owner_uid,
            activity_id=activity_id,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )

        if not ok:
            return api_error("ACTIVITY_NOT_FOUND", msg, 404)

        act = CRMService.get_activity(
            owner_uid=g.owner_uid,
            activity_id=activity_id,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )

        return api_success({"message": msg, "activity": act}, status_code=200)
    except Exception as e:
        print(f"⚠️ Error en API CRM complete activity: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al completar la actividad.", 500)


@api_crm_bp.route("/crm/activities/<activity_id>", methods=["DELETE"])
@require_crm_auth(required_permission="canCRMActivities")
def delete_activity_endpoint(activity_id: str):
    """Eliminar de forma segura (Soft Delete CRM-08) una actividad."""
    try:
        activity_id = (activity_id or "").strip()[:128]
        if not activity_id:
            return api_error("INVALID_PARAMETER", "El ID de la actividad es requerido.", 400)

        user_name = getattr(g, "user_name", "API User")
        ok = CRMService.delete_activity(
            owner_uid=g.owner_uid,
            activity_id=activity_id,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
            deleted_by=user_name,
        )

        if not ok:
            return api_error("ACTIVITY_NOT_FOUND", "Actividad no encontrada.", 404)

        return api_success({"message": "Actividad eliminada correctamente."}, status_code=200)
    except Exception as e:
        print(f"⚠️ Error en API CRM delete activity: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al eliminar la actividad.", 500)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Métricas Comerciales y Conversión (Read)
# ─────────────────────────────────────────────────────────────────────────────

@api_crm_bp.route("/crm/metrics", methods=["GET"])
@require_crm_auth(required_permission="canCRMReports")
def get_metrics():
    """
    Obtener métricas comerciales en tiempo real, embudo de conversión y desgloses.
    Soporta filtros por sucursal, proyecto, vendedor y rango de fechas.
    """
    try:
        company_id = g.company_id
        owner_uid = g.owner_uid
        sandbox = g.sandbox_mode

        branch_id = (request.args.get("branch_id") or g.branch_id or "").strip()[:100] or None
        project_id = (request.args.get("project_id") or g.project_id or "").strip()[:100] or None
        assigned_to = (request.args.get("assigned_to") or request.args.get("assignedTo") or "").strip()[:100] or None
        date_from = (request.args.get("date_from") or request.args.get("dateFrom") or "").strip()[:20] or None
        date_to = (request.args.get("date_to") or request.args.get("dateTo") or "").strip()[:20] or None

        metrics = CRMService.get_sales_metrics(
            owner_uid=owner_uid,
            sandbox=sandbox,
            company_id=company_id,
            branch_id=branch_id,
            project_id=project_id,
            assigned_to=assigned_to,
            date_from=date_from,
            date_to=date_to,
        )

        return api_success({"metrics": metrics})
    except Exception as e:
        print(f"⚠️ Error en API CRM metrics: {e}")
        return api_error("INTERNAL_ERROR", "Error interno al procesar las métricas comerciales.", 500)
