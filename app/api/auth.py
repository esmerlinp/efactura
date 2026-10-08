# app/api/auth.py
import functools
from flask import request, jsonify, g
from app.services.db_service import DatabaseService
from app.utils.module_gate import MODULE_MAP, get_module_label


def check_company_module_enabled(company, module_key):
    """Verifica si una empresa tiene un módulo habilitado en su plan (Fail-Closed)."""
    if not company or not module_key or module_key not in MODULE_MAP:
        return False
    
    # 1. Obtener módulos desde el plan de la empresa
    plan_id = company.get('planId') or company.get('plan_id')
    plan_version = company.get('plan_version', 0) or 0
    modules = {}

    if plan_id:
        plan_data = DatabaseService.get_plan(plan_id, plan_version=plan_version)
        if plan_data and isinstance(plan_data.get('modules'), dict):
            modules = plan_data.get('modules', {})
    
    # Fallback a modules incrustados en company si no hay planId
    if not modules and isinstance(company.get('modules'), dict):
        modules = company.get('modules', {})

    if not modules or module_key not in modules:
        return False

    module_info = modules[module_key]
    if isinstance(module_info, dict):
        is_enabled = bool(module_info.get('enabled', False))
    elif isinstance(module_info, bool):
        is_enabled = module_info
    else:
        is_enabled = False

    if not is_enabled:
        return False

    if module_key == 'pos':
        return bool(company.get('posEnabled', True))

    return True


def gate_api_blueprint_module(bp, module_key, feature_name=None):
    """Registra un hook before_request en un Blueprint de API REST v1 para validar API Key y Entitlement (Fail-Closed)."""
    @bp.before_request
    def _api_blueprint_module_guard():
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

        g.company = company
        g.company_id = company.get("id") or company.get("ownerUID")
        g.owner_uid = company.get("ownerUID")
        g.sandbox_mode = request.headers.get('X-Sandbox-Mode', 'true').lower() == 'true'

        if not check_company_module_enabled(company, module_key):
            label = feature_name or get_module_label(module_key)
            return jsonify({
                "success": False,
                "error": {
                    "code": "MODULE_DISABLED",
                    "message": f"El módulo '{label}' no está contratado en el plan de tu empresa."
                }
            }), 403


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

        # Almacenar en el contexto global de Flask 'g' para ser accesible en las rutas
        g.company = company
        g.company_id = company.get("id") or company.get("ownerUID")
        g.owner_uid = company.get("ownerUID")
        g.sandbox_mode = request.headers.get('X-Sandbox-Mode', 'true').lower() == 'true'

        return f(*args, **kwargs)
    return decorated_function


def require_api_module(module_key, required_permission=None):
    """
    Decorador para autenticar y validar el derecho comercial (Entitlement)
    de un módulo en peticiones REST API.
    
    1. Valida API Key.
    2. Valida que la empresa tenga el módulo contratado en su plan (Fail-Closed: 403 MODULE_DISABLED).
    3. Si se especifica required_permission, valida RBAC para usuarios que no sean owner.
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

            # 2. Validar Entitlement de Módulo en el Plan de la Empresa
            if not check_company_module_enabled(company, module_key):
                return jsonify({
                    "success": False,
                    "error": {
                        "code": "MODULE_DISABLED",
                        "message": f"El módulo '{module_key}' no está habilitado en el plan de esta empresa."
                    }
                }), 403

            # 3. Validar permisos RBAC si aplica
            user_role = company.get("role", "owner")
            user_perms = company.get("permissions")
            if required_permission and user_role != "owner" and user_perms is not None:
                has_perm = bool(user_perms.get(required_permission, False))
                if not has_perm:
                    return jsonify({
                        "success": False,
                        "error": {
                            "code": "FORBIDDEN_PERMISSION",
                            "message": f"Permisos insuficientes para realizar esta operación. Requiere '{required_permission}'."
                        }
                    }), 403

            g.company = company
            g.company_id = company.get("id") or company.get("ownerUID")
            g.owner_uid = company.get("ownerUID")
            g.sandbox_mode = request.headers.get('X-Sandbox-Mode', 'true').lower() == 'true'

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_crm_auth(required_permission="canCRM"):
    """
    Decorador para autenticar y autorizar peticiones a la API REST de CRM.
    Garantiza:
    1. Autenticación por X-API-Key o Authorization: Bearer.
    2. Validación de Entitlement del módulo 'crm'.
    3. Aislamiento estricto de empresa: La API Key solo puede operar dentro de la empresa
       específicamente asignada a la credencial o listada en 'allowed_company_ids'.
    4. Permisos granulares de CRM (canCRM, canCRMContacts, canCRMOpportunities, canCRMActivities, canCRMReports).
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

            # Validar Entitlement comercial de CRM
            if not check_company_module_enabled(company, 'crm'):
                return jsonify({
                    "success": False,
                    "error": {
                        "code": "MODULE_DISABLED",
                        "message": "El módulo 'crm' no está habilitado en el plan de esta empresa."
                    }
                }), 403

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
                allowed_ids = {auth_company_id}
                for cid in company.get("allowed_company_ids", []):
                    if cid:
                        allowed_ids.add(str(cid).strip())

                if requested_company_id not in allowed_ids:
                    return jsonify({
                        "success": False,
                        "error": {
                            "code": "FORBIDDEN_COMPANY",
                            "message": "La credencial provista no está autorizada para operar en la empresa solicitada."
                        }
                    }), 403
                resolved_company_id = requested_company_id
            else:
                resolved_company_id = auth_company_id

            # Validar permisos RBAC
            user_perms = company.get("permissions")
            user_role = company.get("role", "owner")
            if user_role != "owner" and user_perms is not None:
                has_perm = False
                if required_permission in user_perms:
                    has_perm = bool(user_perms[required_permission])
                elif 'canCRM' in user_perms and bool(user_perms['canCRM']):
                    has_perm = True
                elif required_permission in ('canCRMContacts', 'canCRMOpportunities') and 'canClients' in user_perms:
                    has_perm = bool(user_perms['canClients'])
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
            g.user_name = company.get("userName") or company.get("name") or company.get("email") or "API User"
            g.sandbox_mode = request.headers.get('X-Sandbox-Mode', request.args.get('sandbox', 'true')).lower() in ('true', '1')
            g.branch_id = request.headers.get('X-Branch-ID') or request.args.get('branch_id') or None
            g.project_id = request.headers.get('X-Project-ID') or request.args.get('project_id') or None

            return f(*args, **kwargs)
        return decorated_function
    return decorator
