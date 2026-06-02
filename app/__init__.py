import flask
import flask.helpers

# Guardar la referencia al url_for original para evitar recursión
_original_url_for = flask.helpers.url_for

def custom_url_for(endpoint, **values):
    try:
        return _original_url_for(endpoint, **values)
    except Exception:
        # Si falla el endpoint global, intentar con el prefijo de nuestros Blueprints web
        for bp_name in ['web_auth', 'web_dashboard', 'web_clients', 'web_invoices']:
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
        if 'user' in session:
            if 'is_sandbox_mode' not in session:
                session['is_sandbox_mode'] = False
            # Cargar perfil fresco en tiempo real de Firestore para sincronización reactiva
            fresh_profile = DatabaseService.get_user_profile(session['user']['uid'])
            if fresh_profile:
                session['user'] = fresh_profile
            
            # En modo producción, obligar al propietario a configurar el perfil si no lo ha hecho
            if not session.get('is_sandbox_mode', True):
                owner_uid = session['user'].get('ownerUID')
                if owner_uid:
                    company_profile = DatabaseService.get_company_profile(owner_uid)
                    
                    # Bloqueo por Suspensión de Cuenta (Módulo Portal Administrativo)
                    if company_profile.get('status') == 'Suspendido':
                        restricted_endpoints = ['web_invoices.new_invoice_route', 'web_invoices.new_expense_route', 'web_clients.ajax_create_client', 'web_invoices.delete_expense_route']
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
        logo_url = ''
        gradient_enabled = True
        color_marca = ''
        apply_ui = True
        apply_reports = True
        if 'user' in session:
            owner_uid = session['user'].get('ownerUID')
            if owner_uid:
                company = DatabaseService.get_company_profile(owner_uid)
                logo_url = company.get('logoUrl', '')
                color_marca = company.get('colorMarca', '')
                gradient_enabled = company.get('gradientEnabled', True)
                apply_ui = company.get('applyColorMarcaUI', True)
                apply_reports = company.get('applyColorMarcaReports', True)
        return dict(
            company_logo_url=logo_url, 
            company_color_marca=color_marca, 
            company_gradient_enabled=gradient_enabled, 
            company_apply_color_marca_ui=apply_ui, 
            company_apply_color_marca_reports=apply_reports
        )

    # Inyectar helper de verificación de permisos globales
    @app.context_processor
    def utility_processor():
        def check_permission(permission_name):
            if 'user' not in session:
                return False
            user = session['user']
            if user.get('role') == 'owner':
                return True
            return user.get('permissions', {}).get(permission_name, True)
        return dict(check_permission=check_permission)

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
                for bp_name in ['web_auth', 'web_dashboard', 'web_clients', 'web_invoices']:
                    try:
                        return flask_url_for(f"{bp_name}.{endpoint}", **values)
                    except Exception:
                        pass
                # Si de todas formas falla, relanzar el error original de Flask BuildError
                raise
        return dict(url_for=custom_url_for)

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

    app.register_blueprint(web_auth_bp)
    app.register_blueprint(web_dashboard_bp)
    app.register_blueprint(web_clients_bp)
    app.register_blueprint(web_invoices_bp)

    return app
