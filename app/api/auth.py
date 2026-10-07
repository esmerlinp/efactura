# app/api/auth.py
import functools
from flask import request, jsonify, g
from app.services.db_service import DatabaseService


def require_api_key(f):
    """
    Decorador para autenticar peticiones de API utilizando una clave única de API.
    Espera la cabecera 'X-API-Key' o 'Authorization: Bearer <key>'.
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                api_key = auth_header.replace('Bearer ', '').strip()

        if not api_key:
            return jsonify({
                "success": False,
                "error": "Falta la cabecera de autenticación 'X-API-Key' o 'Authorization: Bearer <key>'."
            }), 401

        company = DatabaseService.get_company_by_api_key(api_key)

        if not company:
            return jsonify({
                "success": False,
                "error": "La API Key provista es inválida o ha expirado."
            }), 401

        # Almacenar en el contexto global de Flask 'g' para ser accesible en las rutas
        g.company = company
        g.company_id = company.get("id")
        g.owner_uid = company.get("ownerUID")
        g.sandbox_mode = request.headers.get('X-Sandbox-Mode', 'true').lower() == 'true'

        return f(*args, **kwargs)
    return decorated_function


def require_crm_auth(required_permission="canCRM"):
    """
    Decorador para autenticar y autorizar peticiones a la API REST de CRM.
    Garantiza:
    1. Autenticación por X-API-Key o Authorization: Bearer.
    2. Aislamiento estricto de empresa: Si se envía X-Company-ID / company_id, valida que pertenezca a la empresa autenticada.
       Si no coincide, retorna 403 Forbidden.
    3. Permisos granulares de CRM (canCRM, canCRMContacts, canCRMOpportunities, canCRMActivities, canCRMReports).
    """
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            api_key = request.headers.get('X-API-Key')
            if not api_key:
                auth_header = request.headers.get('Authorization', '')
                if auth_header.startswith('Bearer '):
                    api_key = auth_header.replace('Bearer ', '').strip()

            if not api_key:
                return jsonify({
                    "success": False,
                    "error": {
                        "code": "AUTH_REQUIRED",
                        "message": "Falta la cabecera de autenticación 'X-API-Key' o 'Authorization: Bearer <key>'."
                    }
                }), 401

            company = DatabaseService.get_company_by_api_key(api_key)
            if not company:
                return jsonify({
                    "success": False,
                    "error": {
                        "code": "AUTH_INVALID",
                        "message": "La API Key provista es inválida o ha expirado."
                    }
                }), 401

            auth_company_id = str(company.get("id") or company.get("ownerUID") or "").strip()
            owner_uid = company.get("ownerUID")

            # Validar Company Context
            requested_company_id = (
                request.headers.get('X-Company-ID')
                or request.args.get('company_id')
                or request.args.get('companyId')
            )
            if requested_company_id:
                requested_company_id = str(requested_company_id).strip()
                if requested_company_id != auth_company_id:
                    owned_companies = DatabaseService.get_companies_by_owner(owner_uid) or []
                    allowed_ids = {str(c.get("id")).strip() for c in owned_companies if c.get("id")}
                    if requested_company_id not in allowed_ids:
                        return jsonify({
                            "success": False,
                            "error": {
                                "code": "FORBIDDEN_COMPANY",
                                "message": "Acceso no autorizado a la empresa especificada."
                            }
                        }), 403
                    resolved_company_id = requested_company_id
                else:
                    resolved_company_id = auth_company_id
            else:
                resolved_company_id = auth_company_id

            # Validar permisos si el perfil contiene permisos granulares
            user_perms = company.get("permissions")
            user_role = company.get("role", "owner")
            if user_role != "owner" and user_perms is not None:
                has_perm = False
                if required_permission in user_perms:
                    has_perm = bool(user_perms[required_permission])
                elif 'canClients' in user_perms:
                    has_perm = bool(user_perms['canClients'])
                elif 'canCRM' in user_perms:
                    has_perm = bool(user_perms['canCRM'])
                else:
                    has_perm = False

                if not has_perm:
                    return jsonify({
                        "success": False,
                        "error": {
                            "code": "FORBIDDEN_PERMISSION",
                            "message": f"Permisos insuficientes para realizar esta operación. Requiere '{required_permission}'."
                        }
                    }), 403

            g.company = company
            g.company_id = resolved_company_id
            g.owner_uid = owner_uid
            g.sandbox_mode = request.headers.get('X-Sandbox-Mode', request.args.get('sandbox', 'true')).lower() in ('true', '1')
            g.branch_id = request.headers.get('X-Branch-ID') or request.args.get('branch_id') or None
            g.project_id = request.headers.get('X-Project-ID') or request.args.get('project_id') or None

            return f(*args, **kwargs)
        return decorated_function
    return decorator
