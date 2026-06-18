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

from flask import Flask, request, session, jsonify, flash, redirect, render_template
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
                # Inicializar o refrescar datos de empresas asociadas si es necesario
                if 'associated_companies' not in session or 'user_has_multiple_companies' not in session:
                    associated = DatabaseService.get_associated_companies(session['user']['uid'])
                    session['associated_companies'] = associated
                    session['user_has_multiple_companies'] = len(associated) > 1

                # Asignar o sobreescribir ownerUID según la selección de la sesión
                if 'selected_owner_uid' in session:
                    fresh_profile['ownerUID'] = session['selected_owner_uid']
                else:
                    associated = session.get('associated_companies', [])
                    if len(associated) == 1:
                        session['selected_owner_uid'] = associated[0]['ownerUID']
                        fresh_profile['ownerUID'] = session['selected_owner_uid']
                    elif len(associated) == 0:
                        session['selected_owner_uid'] = fresh_profile.get('ownerUID')
                
                session['user'] = fresh_profile
            else:
                session.pop('user', None)
                session.pop('is_sandbox_mode', None)
                session.pop('selected_owner_uid', None)
                session.pop('associated_companies', None)
                session.pop('user_has_multiple_companies', None)
                flash("Tu cuenta está inhabilitada.", "error")
                return redirect(flask_url_for('web_auth.login'))
            
            # Si tiene múltiples empresas asociadas y aún no ha seleccionado una, obligar a seleccionar
            if 'selected_owner_uid' not in session and session.get('user_has_multiple_companies'):
                allowed_auth_endpoints = [
                    'web_auth.select_company',
                    'web_auth.logout',
                    'static'
                ]
                if request.endpoint not in allowed_auth_endpoints:
                    return redirect(flask_url_for('web_auth.select_company'))
                return
            
            # Obligar al propietario a configurar el perfil si no lo ha hecho (incluso en sandbox)
            owner_uid = session['user'].get('ownerUID')
            if owner_uid:
                company_profile = DatabaseService.get_company_profile(owner_uid)
                if company_profile:
                    session['company_profile_pos_enabled'] = company_profile.get('posEnabled', True)
                    session['company_production_enabled'] = company_profile.get('productionEnabled', True)
                    session['company_sandbox_enabled'] = company_profile.get('sandboxEnabled', True)
                    session['company_sandbox_indefinite'] = company_profile.get('sandboxIndefinite', True)
                    session['company_sandbox_start_date'] = company_profile.get('sandboxStartDate', '')
                    session['company_sandbox_end_date'] = company_profile.get('sandboxEndDate', '')
                    session['company_plan_id'] = company_profile.get('planId', '')
                
                # Lista de páginas permitidas para evitar bucles de redirección
                allowed_endpoints = [
                    'web_auth.logout', 
                    'web_auth.toggle_sandbox', 
                    'static', 
                    'web_auth.user_profile_page', 
                    'web_auth.update_user_profile', 
                    'web_auth.change_user_password',
                    None
                ]

                # 1. Validaciones por Entorno
                is_sandbox = session.get('is_sandbox_mode', False)
                prod_enabled = session.get('company_production_enabled', True)
                sandbox_enabled = session.get('company_sandbox_enabled', True)

                # Validar si sandbox está expirado
                sandbox_expired = False
                if not session.get('company_sandbox_indefinite', True):
                    from datetime import datetime, timedelta
                    now_utc = datetime.utcnow()
                    now_sd = now_utc - timedelta(hours=4)
                    today_str = now_sd.strftime("%Y-%m-%d")
                    start_date = session.get('company_sandbox_start_date', '')
                    end_date = session.get('company_sandbox_end_date', '')
                    if (start_date and today_str < start_date) or (end_date and today_str > end_date):
                        sandbox_expired = True

                if not prod_enabled and not is_sandbox:
                    # El usuario está en producción pero producción está deshabilitado
                    if sandbox_enabled and not sandbox_expired:
                        # Si sandbox está activo, cambiar automáticamente a sandbox y redirigir
                        session['is_sandbox_mode'] = True
                        flash("El entorno de producción está desactivado. Has sido redirigido al entorno Sandbox.", "warning")
                        return redirect(flask_url_for('web_dashboard.dashboard'))
                    else:
                        # Ambos deshabilitados / expirados
                        if request.endpoint not in allowed_endpoints:
                            return render_template('auth/restricted.html', feature_name="Acceso Completo", required_permission="productionAndSandboxDisabled", custom_message="Tu cuenta no cuenta con ningún entorno habilitado en el sistema (Producción y Sandbox están desactivados o su período de prueba ha concluido).", force_logout=True)

                if is_sandbox:
                    # Entorno Sandbox
                    if not sandbox_enabled:
                        if request.endpoint not in allowed_endpoints:
                            return render_template('auth/restricted.html', feature_name="Entorno Sandbox", required_permission="sandboxEnabled", custom_message="El entorno sandbox de pruebas para esta cuenta está desactivado. Por favor, comunícate con el administrador de e-Factura.", force_logout=True)
                    
                    if sandbox_expired:
                        if request.endpoint not in allowed_endpoints:
                            return render_template('auth/restricted.html', feature_name="Prueba Sandbox", required_permission="sandboxTrialDate", custom_message="El período de prueba en el entorno Sandbox ha concluido. Si desea solicitar una extensión de su período de prueba, comuníquese con el personal de e-Factura.", force_logout=True)
                else:
                    # Entorno de Producción
                    if not prod_enabled:
                        if request.endpoint not in allowed_endpoints:
                            return render_template('auth/restricted.html', feature_name="Entorno de Producción", required_permission="productionEnabled", custom_message="El entorno de producción para esta cuenta está desactivado. Comuníquese con soporte si desea activarlo.", force_logout=True)
                    
                    # Validación: Falta de Plan en producción (bloquear operaciones de escritura)
                    if not session.get('company_plan_id'):
                        # Rutas de operaciones de escritura (invoices, cotizaciones, gastos, pos, clientes, etc.)
                        restricted_ops = [
                            'web_invoices.new_invoice_route', 'web_invoices.new_quotation_route',
                            'web_invoices.new_expense_route', 'web_clients.ajax_create_client',
                            'web_invoices.delete_expense_route', 'web_invoices.delete_multiple_expenses_route', 'web_pos.pos_dashboard',
                            'web_pos.create_pos_invoice', 'web_import_mapper.process_import',
                            'web_operations.register_payment_route', 'web_notes.create_credit_note_route',
                            'web_notes.create_debit_note_route'
                        ]
                        if request.endpoint in restricted_ops:
                            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                                return jsonify({"success": False, "error": "No puedes realizar operaciones hasta que no se te asigne un plan."}), 403
                            flash("No puedes realizar operaciones en producción hasta que no se te asigne un plan en el sistema.", "error")
                            return redirect(flask_url_for('web_dashboard.dashboard'))

                # Bloqueo por Cuenta Cancelada (Módulo Portal Administrativo)
                if company_profile.get('status') == 'Cancelado':
                    if request.endpoint not in allowed_endpoints:
                        return render_template('auth/restricted.html', feature_name="Cuenta Cancelada", required_permission="statusCancelado", custom_message="Esta cuenta ha sido cancelada en el sistema. Comuníquese con soporte si considera que es un error.", force_logout=True)

                # Bloqueo por Suspensión de Cuenta (Módulo Portal Administrativo)
                if company_profile.get('status') == 'Suspendido':
                    restricted_endpoints = ['web_invoices.new_invoice_route', 'web_invoices.new_quotation_route', 'web_invoices.new_expense_route', 'web_clients.ajax_create_client', 'web_invoices.delete_expense_route', 'web_invoices.delete_multiple_expenses_route']
                    if request.endpoint in restricted_endpoints:
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                            return jsonify({"success": False, "error": "Tu cuenta está suspendida por falta de pago."}), 403
                        flash("Tu cuenta está suspendida por falta de pago. No puedes emitir nuevas facturas, cotizaciones ni registrar gastos.", "error")
                        return redirect(flask_url_for('web_dashboard.dashboard'))

                if not company_profile.get('configured', False):
                    # Evitar bucle de redirección en páginas esenciales
                    allowed = [
                        'web_invoices.onboarding_wizard', 
                        'web_auth.logout', 
                        'web_auth.toggle_sandbox', 
                        'static', 
                        'web_auth.user_profile_page', 
                        'web_auth.update_user_profile', 
                        'web_auth.change_user_password',
                        'web_import_mapper.upload_file',
                        'web_import_mapper.ai_suggest_mapping',
                        'web_import_mapper.process_import',
                        None
                    ]
                    # Incluir endpoints de validación de entornos también para no interferir
                    if request.endpoint not in allowed and request.endpoint not in allowed_endpoints:
                        flash("Para poder operar en la plataforma, debes primero configurar los datos requeridos de tu empresa.", "warning")
                        return redirect(flask_url_for('web_invoices.onboarding_wizard'))

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
        is_configured = True
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
                is_configured = company.get('configured', False)
        return dict(
            company_logo_url=logo_url, 
            company_color_marca=color_marca, 
            company_gradient_enabled=gradient_enabled, 
            company_apply_color_marca_ui=apply_ui, 
            company_apply_color_marca_reports=apply_reports,
            company_theme=theme,
            is_company_configured=is_configured
        )

    @app.context_processor
    def inject_crm_commitments():
        """Inyecta los compromisos CRM agendados para hoy y las notificaciones del usuario para todos los templates."""
        from flask import has_request_context
        crm_contacts = []
        user_notifications = []
        if has_request_context() and 'user' in session:
            owner_uid = session['user'].get('ownerUID')
            user_uid = session['user'].get('uid')
            if owner_uid:
                try:
                    from datetime import datetime
                    from app.services.db_service import DatabaseService
                    sandbox = session.get('is_sandbox_mode', False)
                    
                    # Cargar notificaciones del usuario
                    if user_uid:
                        user_notifications = DatabaseService.get_user_notifications(user_uid, limit=10)
                        
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
                    print(f"⚠️ Error al inyectar compromisos CRM o notificaciones en el contexto global: {e}")
        return dict(crm_contacts=crm_contacts, user_notifications=user_notifications)

    # Inyectar helper de verificación de permisos globales
    @app.context_processor
    def utility_processor():
        def check_permission(permission_name):
            from flask import has_request_context
            if not has_request_context() or 'user' not in session:
                return False
            if permission_name == 'canManagePOS' and not session.get('company_profile_pos_enabled', True):
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

    @app.context_processor
    def inject_companies_info():
        """Inyecta información de las empresas asociadas al usuario actual."""
        from flask import has_request_context
        companies = []
        has_mult = False
        act_name = "Mi Empresa"
        if has_request_context() and 'user' in session:
            companies = session.get('associated_companies', [])
            has_mult = session.get('user_has_multiple_companies', False)
            active_owner_uid = session['user'].get('ownerUID')
            for c in companies:
                if c.get('ownerUID') == active_owner_uid:
                    act_name = c.get('companyName', 'Mi Empresa')
                    break
        return dict(
            associated_companies=companies,
            user_has_multiple_companies=has_mult,
            active_company_name=act_name
        )

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
                for bp_name in ['web_auth', 'web_dashboard', 'web_clients', 'web_invoices', 'web_suppliers', 'web_purchase_orders', 'web_reports_606', 'web_pos', 'web_operations', 'portal', 'web_audit']:
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
    from app.api.v1.auth import api_auth_bp
    from app.api.v1.metadata import metadata_bp
    
    app.register_blueprint(api_invoices_bp, url_prefix='/api/v1')
    app.register_blueprint(api_clients_bp, url_prefix='/api/v1')
    app.register_blueprint(api_dgii_bp, url_prefix='/api/v1')
    app.register_blueprint(api_auth_bp, url_prefix='/api/v1')
    app.register_blueprint(metadata_bp, url_prefix='/api/v1')

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
    from app.web.suppliers import web_suppliers_bp
    from app.web.purchase_orders import web_purchase_orders_bp
    from app.web.reports_606 import web_reports_606_bp
    from app.web.fiscal_notes import web_fiscal_notes_bp

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
    app.register_blueprint(web_suppliers_bp)
    app.register_blueprint(web_purchase_orders_bp)
    app.register_blueprint(web_reports_606_bp)
    app.register_blueprint(web_fiscal_notes_bp)

    # =========================================================================
    # APScheduler — Facturación automática diaria de contratos recurrentes
    # Se activa solo si no estamos en el proceso secundario del reloader de Flask
    # =========================================================================
    import os
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        try:
            from app.services.scheduler import init_scheduler
            init_scheduler(app)
        except Exception as _sched_err:
            import logging
            logging.getLogger(__name__).warning(
                f"⚠️ APScheduler no pudo inicializarse: {_sched_err}"
            )

    return app
