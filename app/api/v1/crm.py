"""
API REST para el módulo CRM de VykOne (Fase 5.1 Foundation & Read-Only Endpoints).

Expone las entidades y métricas del CRM de forma segura, multi-tenant y reutilizando
estrictamente los servicios de dominio (CRMService, ContactService, DatabaseService).
"""

from datetime import date, datetime
from uuid import UUID
from flask import Blueprint, request, jsonify, g

from app.api.auth import require_crm_auth
from app.services.crm_service import CRMService
from app.services.contact_service import ContactService


api_crm_bp = Blueprint("api_crm", __name__)


# ─────────────────────────────────────────────────────────────────────────────
# Serialization & Response Helpers
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# 1. Contactos CRM
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

        search = (request.args.get("search") or "").strip().lower()
        contact_type = (request.args.get("type") or "").strip().lower()
        branch_id = request.args.get("branch_id") or g.branch_id
        project_id = request.args.get("project_id") or g.project_id

        try:
            limit = min(200, max(1, int(request.args.get("limit", 50))))
            offset = max(0, int(request.args.get("offset", 0)))
        except (ValueError, TypeError):
            return api_error("INVALID_PAGINATION", "Los parámetros 'limit' y 'offset' deben ser enteros positivos.", 400)

        all_contacts = ContactService.get_contacts(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id)

        # Filtros en memoria respetando multi-tenant
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
        return api_error("INTERNAL_ERROR", f"Error al consultar contactos: {str(e)}", 500)


@api_crm_bp.route("/crm/contacts/<contact_id>", methods=["GET"])
@require_crm_auth(required_permission="canCRMContacts")
def get_contact_detail(contact_id: str):
    """Obtener el detalle de un contacto por ID."""
    try:
        contact_id = (contact_id or "").strip()
        if not contact_id:
            return api_error("INVALID_PARAMETER", "El ID del contacto es requerido.", 400)

        contact = ContactService.get_contact(
            owner_uid=g.owner_uid,
            contact_id=contact_id,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )

        if not contact:
            return api_error("CONTACT_NOT_FOUND", f"El contacto '{contact_id}' no existe o no pertenece a la empresa.", 404)

        return api_success({"contact": contact})
    except Exception as e:
        return api_error("INTERNAL_ERROR", f"Error al consultar el contacto: {str(e)}", 500)


@api_crm_bp.route("/crm/contacts/<contact_id>/360", methods=["GET"])
@require_crm_auth(required_permission="canCRMContacts")
def get_contact_360(contact_id: str):
    """Obtener la vista unificada Contact 360 (perfil, oportunidades, actividades, métricas y timeline)."""
    try:
        contact_id = (contact_id or "").strip()
        if not contact_id:
            return api_error("INVALID_PARAMETER", "El ID del contacto es requerido.", 400)

        data = CRMService.get_contact_360(
            owner_uid=g.owner_uid,
            contact_id=contact_id,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )

        if not data or not data.get("contact"):
            return api_error("CONTACT_NOT_FOUND", f"El contacto '{contact_id}' no existe o no pertenece a la empresa.", 404)

        return api_success(data)
    except Exception as e:
        return api_error("INTERNAL_ERROR", f"Error al consultar Contact 360: {str(e)}", 500)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Oportunidades Comerciales
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

        stage = request.args.get("stage")
        status = request.args.get("status")
        assigned_to = request.args.get("assigned_to") or request.args.get("assignedTo")
        contact_id = request.args.get("contact_id") or request.args.get("contactId")
        branch_id = request.args.get("branch_id") or g.branch_id
        project_id = request.args.get("project_id") or g.project_id
        include_closed = request.args.get("include_closed", "true").lower() in ("true", "1")

        try:
            limit = min(200, max(1, int(request.args.get("limit", 50))))
            offset = max(0, int(request.args.get("offset", 0)))
        except (ValueError, TypeError):
            return api_error("INVALID_PAGINATION", "Los parámetros 'limit' y 'offset' deben ser enteros positivos.", 400)

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
        return api_error("INTERNAL_ERROR", f"Error al consultar oportunidades: {str(e)}", 500)


@api_crm_bp.route("/crm/opportunities/<opportunity_id>", methods=["GET"])
@require_crm_auth(required_permission="canCRMOpportunities")
def get_opportunity_detail(opportunity_id: str):
    """Obtener el detalle de una oportunidad comercial por ID."""
    try:
        opportunity_id = (opportunity_id or "").strip()
        if not opportunity_id:
            return api_error("INVALID_PARAMETER", "El ID de la oportunidad es requerido.", 400)

        opportunity = CRMService.get_opportunity(
            owner_uid=g.owner_uid,
            opportunity_id=opportunity_id,
            sandbox=g.sandbox_mode,
            company_id=g.company_id,
        )

        if not opportunity or opportunity.get("isDeleted"):
            return api_error("OPPORTUNITY_NOT_FOUND", f"La oportunidad '{opportunity_id}' no existe o no pertenece a la empresa.", 404)

        return api_success({"opportunity": opportunity})
    except Exception as e:
        return api_error("INTERNAL_ERROR", f"Error al consultar la oportunidad: {str(e)}", 500)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Actividades CRM
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

        status = request.args.get("status")
        assigned_to = request.args.get("assigned_to") or request.args.get("assignedTo")
        contact_id = request.args.get("contact_id") or request.args.get("contactId")
        opportunity_id = request.args.get("opportunity_id") or request.args.get("opportunityId")
        branch_id = request.args.get("branch_id") or g.branch_id
        project_id = request.args.get("project_id") or g.project_id
        include_completed = request.args.get("include_completed", "true").lower() in ("true", "1")

        try:
            limit = min(200, max(1, int(request.args.get("limit", 50))))
            offset = max(0, int(request.args.get("offset", 0)))
        except (ValueError, TypeError):
            return api_error("INVALID_PAGINATION", "Los parámetros 'limit' y 'offset' deben ser enteros positivos.", 400)

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
        return api_error("INTERNAL_ERROR", f"Error al consultar actividades: {str(e)}", 500)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Métricas Comerciales y Conversión
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

        branch_id = request.args.get("branch_id") or g.branch_id
        project_id = request.args.get("project_id") or g.project_id
        assigned_to = request.args.get("assigned_to") or request.args.get("assignedTo")
        date_from = request.args.get("date_from") or request.args.get("dateFrom")
        date_to = request.args.get("date_to") or request.args.get("dateTo")

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
        return api_error("INTERNAL_ERROR", f"Error al calcular métricas comerciales: {str(e)}", 500)
