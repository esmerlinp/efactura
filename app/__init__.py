import flask
import flask.helpers

# Guardar la referencia al url_for original para evitar recursión
_original_url_for = flask.helpers.url_for

def custom_url_for(endpoint, **values):
    try:
        return _original_url_for(endpoint, **values)
    except Exception:
        # Si falla el endpoint global, intentar con el prefijo de nuestros Blueprints web
        for bp_name in ['web_auth', 'web_dashboard', 'web_clients', 'web_invoices', 'web_pos', 'web_operations', 'portal', 'web_audit']:
            try:
                return _original_url_for(f"{bp_name}.{endpoint}", **values)
            except Exception:
                pass
        # Si de todas formas falla, relanzar el error original
        raise

flask.helpers.url_for = custom_url_for
flask.url_for = custom_url_for

flask_url_for = _original_url_for

from flask import Flask, request, session, jsonify, flash, redirect
from config import Config
from app.extensions import init_extensions
from app.services.db_service import DatabaseService

def create_app():
    """Application Factory de Flask."""
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.config.from_object(Config)

    # Inicializar base de datos local y filtros Jinja2
    init_extensions(app)

    # =========================================================================
    # LIFECYCLE HOOKS & SEGURIDAD DE PERMISOS
    # =========================================================================
    @app.before_request
    def load_fresh_user_profile():
        # Saltar carga para llamadas de archivos estáticos
        if request.endpoint == 'static':
            return
        # Permitir acceso al portal del cliente sin requerir login de usuario administrador
        if request.blueprint == 'portal':
            return
        if 'user' in session:
            if 'is_sandbox_mode' not in session:
                session['is_sandbox_mode'] = False
            # Cargar perfil fresco en tiempo real de Firestore para sincronización reactiva
            fresh_profile = DatabaseService.get_user_profile(session['user']['uid'])
            if fresh_profile:
                session['user'] = fresh_profile
            
            # En modo producción, obligar al propietario a configurar el perfil si no lo ha hecho
            if not session.get('is_sandbox_mode', False):
                owner_uid = session['user'].get('ownerUID')
                if owner_uid:
                    company_profile = DatabaseService.get_company_profile(owner_uid)
                    
                    # Bloqueo por Suspensión de Cuenta (Módulo Portal Administrativo)
                    if company_profile.get('status') == 'Suspendido':
                        restricted_endpoints = ['web_invoices.new_invoice_route', 'web_invoices.new_quotation_route', 'web_invoices.new_expense_route', 'web_clients.ajax_create_client', 'web_invoices.delete_expense_route']
                        if request.endpoint in restricted_endpoints:
                            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                                return jsonify({"success": False, "error": "Tu cuenta está suspendida por falta de pago."}), 403
                            flash("Tu cuenta está suspendida por falta de pago. No puedes emitir nuevas facturas, cotizaciones ni registrar gastos.", "error")
                            return redirect(flask_url_for('web_dashboard.dashboard'))

                    if not company_profile.get('configured', False):
                        # Evitar bucle de redirección en páginas esenciales
                        allowed = ['web_invoices.company_settings', 'web_auth.logout', 'web_auth.toggle_sandbox', 'static', 'web_auth.user_profile_page', 'web_auth.update_user_profile', 'web_auth.change_user_password', None]
                        if request.endpoint not in allowed:
                            flash("Para poder operar en Modo de Producción, debes primero configurar y guardar los datos reales de tu empresa.", "warning")
                            return redirect(flask_url_for('web_invoices.company_settings'))

    @app.context_processor
    def inject_company_brand():
        """Inyecta el logo y color de marca de la empresa en todos los templates."""
        from flask import has_request_context
        logo_url = ''
        gradient_enabled = True
        color_marca = ''
        apply_ui = True
        apply_reports = True
        theme = 'moderno'
        if has_request_context() and 'user' in session:
            owner_uid = session['user'].get('ownerUID')
            if owner_uid:
                company = DatabaseService.get_company_profile(owner_uid)
                logo_url = company.get('logoUrl', '')
                color_marca = company.get('colorMarca', '')
                gradient_enabled = company.get('gradientEnabled', True)
                apply_ui = company.get('applyColorMarcaUI', True)
                apply_reports = company.get('applyColorMarcaReports', True)
                theme = company.get('theme', 'moderno')
        return dict(
            company_logo_url=logo_url, 
            company_color_marca=color_marca, 
            company_gradient_enabled=gradient_enabled, 
            company_apply_color_marca_ui=apply_ui, 
            company_apply_color_marca_reports=apply_reports,
            company_theme=theme
        )

    @app.context_processor
    def inject_crm_commitments():
        """Inyecta los compromisos CRM agendados para hoy para todos los templates."""
        from flask import has_request_context
        crm_contacts = []
        if has_request_context() and 'user' in session:
            owner_uid = session['user'].get('ownerUID')
            if owner_uid:
                try:
                    from datetime import datetime
                    from app.services.db_service import DatabaseService
                    sandbox = session.get('is_sandbox_mode', False)
                    today_str = datetime.utcnow().strftime("%Y-%m-%d")
                    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
                    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
                    real_invoices = [inv for inv in invoices if not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador']]
                    
                    for c in clients:
                        c_id = c['id']
                        c_sales = [inv for inv in real_invoices if inv['clientId'] == c_id]
                        c['total_cxc'] = sum(inv['netPayable'] for inv in c_sales if inv['status'] in ['Emitida', 'Vencida'])

                    crm_contacts = [
                        c for c in clients 
                        if (c.get('nextContactDate') and c['nextContactDate'][:10] == today_str) or c.get('total_cxc', 0.0) > 0.0
                    ]
                except Exception as e:
                    print(f"⚠️ Error al inyectar compromisos CRM en el contexto global: {e}")
        return dict(crm_contacts=crm_contacts)

    # Inyectar helper de verificación de permisos globales
    @app.context_processor
    def utility_processor():
        def check_permission(permission_name):
            from flask import has_request_context
            if not has_request_context() or 'user' not in session:
                return False
            user = session['user']
            if user.get('role') == 'owner':
                return True
            return user.get('permissions', {}).get(permission_name, True)
        return dict(check_permission=check_permission)

    @app.context_processor
    def inject_plan_info():
        """Inyecta el nombre y tipo de facturación del plan activo en todos los templates."""
        from flask import has_request_context
        plan_name_global = ''
        plan_billing_type = ''
        if has_request_context() and 'user' in session:
            owner_uid = session['user'].get('ownerUID')
            if owner_uid:
                try:
                    company = DatabaseService.get_company_profile(owner_uid)
                    plan_id = company.get('planId')
                    plan_billing_type = company.get('billingType', 'Pago por uso')
                    if plan_id:
                        from app.services.db_service import db_firestore
                        plan_doc = db_firestore.collection('plans').document(plan_id).get()
                        if plan_doc.exists:
                            plan_name_global = plan_doc.to_dict().get('name', '')
                    if not plan_name_global:
                        plan_name_global = company.get('planName', 'Plan Activo')
                except Exception:
                    plan_name_global = 'Plan Activo'
        return dict(global_plan_name=plan_name_global, global_plan_billing_type=plan_billing_type)

    # =========================================================================
    # INTERCEPTOR DE URL_FOR RETROCOMPATIBLE
    # =========================================================================
    @app.context_processor
    def inject_url_for():
        """Sobrescribe url_for en Jinja2 para buscar automáticamente en Blueprints si falla el global."""
        def custom_url_for(endpoint, **values):
            # Intentar resolver endpoint original (global o con prefijo explícito)
            try:
                return flask_url_for(endpoint, **values)
            except Exception:
                # Si falla, intentar buscar agregando el prefijo de nuestros Blueprints web
                for bp_name in ['web_auth', 'web_dashboard', 'web_clients', 'web_invoices', 'web_pos', 'web_operations', 'portal', 'web_audit']:
                    try:
                        return flask_url_for(f"{bp_name}.{endpoint}", **values)
                    except Exception:
                        pass
                # Si de todas formas falla, relanzar el error original de Flask BuildError
                raise
        return dict(url_for=custom_url_for)

    # =========================================================================
    # LOG DE FALLOS EN APIS
    # =========================================================================
    @app.after_request
    def log_failed_api_calls(response):
        if request.path.startswith('/api/') and response.status_code >= 400:
            import os
            from datetime import datetime
            
            # root_path is typically the 'app' folder, so we go one level up for the main folder
            log_file_path = os.path.join(app.root_path, '../api_errores.log')
            
            payload = ""
            if request.is_json:
                payload = request.get_data(as_text=True)
            elif request.form:
                payload = str(request.form.to_dict())
            elif request.data:
                payload = request.get_data(as_text=True)
                
            resp_data = ""
            try:
                resp_data = response.get_data(as_text=True)
            except Exception:
                resp_data = "No se pudo leer la respuesta"
            
            log_entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR API:\n"
            log_entry += f"Ruta: {request.method} {request.path}\n"
            log_entry += f"HTTP Code: {response.status_code}\n"
            log_entry += f"Payload: {payload}\n"
            log_entry += f"Response: {resp_data}\n"
            log_entry += ("-" * 60) + "\n"
            
            try:
                with open(log_file_path, 'a', encoding='utf-8') as f:
                    f.write(log_entry)
            except Exception as e:
                print(f"Error escribiendo en api_errores.log: {e}")
                
        return response

    # =========================================================================
    # REGISTRO DE BLUEPRINTS
    # =========================================================================
    
    # 1. API Blueprints
    from app.api.v1.invoices import api_invoices_bp
    from app.api.v1.clients import api_clients_bp
    from app.api.v1.dgii import api_dgii_bp
    
    app.register_blueprint(api_invoices_bp, url_prefix='/api/v1')
    app.register_blueprint(api_clients_bp, url_prefix='/api/v1')
    app.register_blueprint(api_dgii_bp, url_prefix='/api/v1')

    # 2. Web UI Blueprints
    from app.web.auth import web_auth_bp
    from app.web.dashboard import web_dashboard_bp
    from app.web.clients import web_clients_bp
    from app.web.invoices import web_invoices_bp
    from app.web.notes import web_notes_bp
    from app.web.pos import web_pos_bp
    from app.web.import_mapper import web_import_mapper_bp
    from app.web.operations import web_operations_bp
    from app.web.portal import portal_bp
    from app.web.audit import web_audit_bp

    app.register_blueprint(web_auth_bp)
    app.register_blueprint(web_dashboard_bp)
    app.register_blueprint(web_clients_bp)
    app.register_blueprint(web_invoices_bp)
    app.register_blueprint(web_notes_bp)
    app.register_blueprint(web_pos_bp)
    app.register_blueprint(web_import_mapper_bp)
    app.register_blueprint(web_operations_bp)
    app.register_blueprint(portal_bp)
    app.register_blueprint(web_audit_bp)

    return app
