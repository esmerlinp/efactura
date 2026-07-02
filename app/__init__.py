import flask.helpers

flask_url_for = flask.helpers.url_for

from flask import Flask, request, session, jsonify, flash, redirect, render_template, url_for
from flask_wtf.csrf import CSRFError
from config import Config
from app.extensions import init_extensions, csrf
from app.cache import cache
from app.services.db_service import DatabaseService

def create_app():
    """Application Factory de Flask."""
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.config.from_object(Config)

    # Cache de assets estáticos por 1 año con hash en URL para invalidación
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000

    # Inicializar base de datos local, caché y filtros Jinja2
    init_extensions(app)

    # Validar que secretos críticos estén configurados
    _required_secrets = ['SECRET_KEY', 'FIREBASE_API_KEY']
    for _key in _required_secrets:
        if not app.config.get(_key):
            raise RuntimeError(
                f"❌ Variable de entorno {_key} no está configurada. "
                f"Debe definirse en .env o en las variables de entorno del sistema."
            )

    if not app.config.get('FIELD_ENCRYPTION_KEY'):
        print("⚠️ FIELD_ENCRYPTION_KEY no configurada — campos sensibles en Firestore se guardarán en texto plano")

    # =========================================================================
    # LIFECYCLE HOOKS & SEGURIDAD DE PERMISOS
    # =========================================================================
    @app.before_request
    def load_fresh_user_profile():
        session.permanent = True
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

                    plan_version = company_profile.get('plan_version', 0) or 0
                    cached_plan_version = session.get('company_plan_version', -1)
                    if cached_plan_version != plan_version:
                        plan_id = company_profile.get('planId', '')
                        if plan_id:
                            plan_data = DatabaseService.get_plan(plan_id)
                            if plan_data:
                                session['company_modules'] = plan_data.get('modules', {})
                                session['company_plan_version'] = plan_version
                                plan_limits = {}
                                for f in ['documentLimit','userLimit','storageLimitMB','monthlyPayment',
                                          'additionalDocumentCost','additionalUserCost','branchLimit',
                                          'boxLimit','additionalBoxCost','posEnabled']:
                                    if f in plan_data:
                                        plan_limits[f] = plan_data[f]
                                if plan_limits:
                                    from app.services.db_service import db_firestore, _cached_company_profile
                                    db_firestore.collection('users').document(owner_uid)\
                                        .collection('config').document('profile')\
                                        .update(plan_limits)
                                    cache.delete_memoized(_cached_company_profile, owner_uid)
                                    company_profile.update(plan_limits)
                            else:
                                session.pop('company_modules', None)
                        else:
                            session.pop('company_modules', None)
                        session['company_plan_version'] = plan_version

                    # Auto-cancelación: si cancel_at_period_end y la fecha pasó, aplicar cancelación
                    if company_profile.get('cancel_at_period_end') and company_profile.get('cancel_scheduled_date'):
                        from datetime import datetime, timezone, timedelta
                        try:
                            cancel_date = datetime.strptime(company_profile['cancel_scheduled_date'], '%d/%m/%Y').date()
                            if datetime.now(timezone.utc).date() >= cancel_date:
                                from app.services.db_service import db_firestore, _cached_company_profile
                                company_profile['status'] = 'Cancelado'
                                company_profile['cancel_at_period_end'] = False
                                company_profile.pop('cancel_scheduled_date', None)
                                db_firestore.collection('users').document(owner_uid)\
                                    .collection('config').document('profile')\
                                    .update({'status': 'Cancelado', 'cancel_at_period_end': False, 'cancel_scheduled_date': ''})
                                cache.delete_memoized(_cached_company_profile, owner_uid)
                        except (ValueError, TypeError):
                            pass
                
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
                    from datetime import datetime, timedelta, timezone
                    now_utc = datetime.now(timezone.utc)
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
                            return render_template('auth/restricted.html', feature_name="Entorno Sandbox", required_permission="sandboxEnabled", custom_message=f"El entorno sandbox de pruebas para esta cuenta está desactivado. Por favor, comunícate con el administrador de {app.config.get('PRODUCT_NAME', 'VykOne')}.", force_logout=True)
                    
                    if sandbox_expired:
                        if request.endpoint not in allowed_endpoints:
                            return render_template('auth/restricted.html', feature_name="Prueba Sandbox", required_permission="sandboxTrialDate", custom_message=f"El período de prueba en el entorno Sandbox ha concluido. Si desea solicitar una extensión de su período de prueba, comuníquese con el personal de {app.config.get('PRODUCT_NAME', 'VykOne')}.", force_logout=True)
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

                module_restricted = {
                    'web_notes.credit_notes': 'e_cf',
                    'web_notes.debit_notes': 'e_cf',
                    'web_invoices.new_quotation_route': 'cotizaciones',
                    'web_invoices.quotations_list': 'cotizaciones',
                    'web_clients.manage_clients': 'crm',
                    'web_clients.manage_clients_route': 'crm',
                    'web_clients.ajax_create_client': 'crm',
                    'web_invoices.inventory_view': 'inventario',
                    'web_invoices.items': 'catalogo',
                    'web_invoices.new_item': 'catalogo',
                    'web_invoices.manage_cxc': 'cxc',
                    'web_suppliers.manage_suppliers': 'cxp_compras',
                    'web_purchase_orders.manage_purchase_orders': 'cxp_compras',
                    'web_operations.contracts': 'contratos',
                    'web_operations.commissions': 'comisiones',
                    'web_reports_606.report_606': 'reporte_606',
                    'web_audit.audit_view': 'auditoria',
                    'web_dashboard.bi_page': 'ia_bi',
                    'web_clients.client_insights': 'ia_bi',
                }
                ep = request.endpoint
                if ep in module_restricted:
                    from app.utils.module_gate import module_enabled as _mod_check
                    if not _mod_check(module_restricted[ep]):
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                            return jsonify({"success": False, "error": "Este módulo no está disponible en tu plan actual."}), 403
                        flash("Este módulo no está incluido en tu plan actual. Contacta a soporte para información sobre mejoras de plan.", "warning")
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
    def inject_global_brand():
        """Inyecta el nombre del producto y la marca de la empresa en todos los templates."""
        from flask import current_app, has_request_context
        product_name = current_app.config.get('PRODUCT_NAME', 'VykOne')
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
            product_name=product_name,
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
                    from app.services.db_service import DatabaseService
                    sandbox = session.get('is_sandbox_mode', False)
                    
                    # Cargar notificaciones del usuario
                    if user_uid:
                        user_notifications = DatabaseService.get_user_notifications(user_uid, limit=10)
                        
                    crm_contacts = DatabaseService.get_crm_contacts(owner_uid, sandbox=sandbox)
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

        import os as _os
        _static_dir = _os.path.join(app.root_path, '..', 'static')

        def static_hash(filename):
            """Retorna un hash corto basado en la fecha de modificación del archivo estático."""
            try:
                filepath = _os.path.join(_static_dir, filename.lstrip('/'))
                mtime = int(_os.path.getmtime(filepath))
                return hex(mtime)[2:]
            except OSError:
                return '0'

        def module_enabled(module_key):
            from app.utils.module_gate import module_enabled as _me
            return _me(module_key)

        return dict(check_permission=check_permission, static_hash=static_hash, module_enabled=module_enabled)

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
                        plan_data = DatabaseService.get_plan(plan_id)
                        if plan_data:
                            plan_name_global = plan_data.get('name', '')
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
    # SEGURIDAD: HEADERS HTTP
    # =========================================================================
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        response.headers['X-Permitted-Cross-Domain-Policies'] = 'none'
        response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
        response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
        if request.is_secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

        # CSP: restringir orígenes de recursos a conocidos
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' "
            "cdn.jsdelivr.net cdn.tailwindcss.com npmcdn.com unpkg.com "
            "cdnjs.cloudflare.com "
            "https://www.googletagmanager.com "
            "https://www.google-analytics.com; "
            "script-src-elem 'self' 'unsafe-inline' "
            "cdn.jsdelivr.net cdn.tailwindcss.com npmcdn.com unpkg.com "
            "cdnjs.cloudflare.com "
            "https://www.googletagmanager.com "
            "https://www.google-analytics.com; "
            "style-src 'self' 'unsafe-inline' "
            "cdnjs.cloudflare.com cdn.jsdelivr.net "
            "fonts.googleapis.com; "
            "font-src 'self' cdnjs.cloudflare.com fonts.gstatic.com; "
            "img-src 'self' data: "
            "storage.googleapis.com firebasestorage.googleapis.com "
            "*.googleusercontent.com; "
            "connect-src 'self' "
            "https://identitytoolkit.googleapis.com "
            "https://securetoken.googleapis.com "
            "https://firestore.googleapis.com "
            "https://ecf.dgii.gov.do "
            "https://api.openai.com; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "base-uri 'self'"
        )
        response.headers['Content-Security-Policy'] = csp

        # Remover Server header para no revelar versión de servidor
        if 'Server' in response.headers:
            del response.headers['Server']
        return response

    # =========================================================================
    # CACHÉ DE ASSETS ESTÁTICOS
    # =========================================================================
    @app.after_request
    def add_static_cache(response):
        if request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return response

    # =========================================================================
    # LOG DE FALLOS EN APIS
    # =========================================================================
    @app.after_request
    def log_failed_api_calls(response):
        if request.path.startswith('/api/') and response.status_code >= 400:
            import os
            import re
            from datetime import datetime, timezone
            
            log_file_path = os.path.join(app.root_path, '../api_errores.log')
            
            raw_payload = ""
            if request.is_json:
                raw_payload = request.get_data(as_text=True)
            elif request.form:
                raw_payload = str(request.form.to_dict())
            elif request.data:
                raw_payload = request.get_data(as_text=True)
            
            sanitized = re.sub(
                r'"(password|secret|token|private_key|api_key|authorization)"\s*:\s*"[^"]*"',
                r'"\1":"[REDACTED]"',
                raw_payload,
                flags=re.IGNORECASE
            )
            sanitized = re.sub(
                r'(password|secret|token|api_key)=[^&\s]+',
                r'\1=[REDACTED]',
                sanitized,
                flags=re.IGNORECASE
            )
            
            resp_data = ""
            try:
                resp_data = response.get_data(as_text=True)
            except Exception:
                resp_data = "No se pudo leer la respuesta"
            
            log_entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR API:\n"
            log_entry += f"Ruta: {request.method} {request.path}\n"
            log_entry += f"HTTP Code: {response.status_code}\n"
            log_entry += f"Payload: {sanitized}\n"
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
    from app.api.v1.prospects import api_prospects_bp
    
    app.register_blueprint(api_invoices_bp, url_prefix='/api/v1')
    app.register_blueprint(api_clients_bp, url_prefix='/api/v1')
    app.register_blueprint(api_dgii_bp, url_prefix='/api/v1')
    app.register_blueprint(api_auth_bp, url_prefix='/api/v1')
    app.register_blueprint(metadata_bp, url_prefix='/api/v1')
    app.register_blueprint(api_prospects_bp, url_prefix='/api/v1')

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
    from app.web.notifications import web_notifications_bp
    from app.web.vykcore import web_vykcore_bp

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
    app.register_blueprint(web_vykcore_bp)
    app.register_blueprint(web_notifications_bp)

    # Eximir rutas /api/ de validación CSRF (los blueprints de API se registraron arriba)
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith('/api/'):
            view_func = app.view_functions.get(rule.endpoint)
            if view_func:
                csrf.exempt(view_func)

    # =========================================================================
    # RATE LIMITER — inicializar después de registrar todos los blueprints
    # =========================================================================
    from app.extensions import limiter
    limiter.init_app(app)

    # =========================================================================
    # SERVIDOR DE ARCHIVOS SUBIDOS (autenticado, fuera de static/)
    # =========================================================================
    from flask import send_from_directory, abort
    import os as _os

    @app.route('/uploads/<path:filename>')
    def serve_uploaded_file(filename):
        user_id = session.get('user_id')
        if not user_id:
            abort(401)
        uploads_dir = app.config.get('UPLOAD_FOLDER', _os.path.join(app.root_path, '..', 'uploads'))
        safe_path = _os.path.normpath(_os.path.join(uploads_dir, filename))
        if not safe_path.startswith(_os.path.normpath(uploads_dir)):
            abort(403)
        return send_from_directory(uploads_dir, filename)

    # =========================================================================
    # CSRF Error Handler — Muestra mensaje amigable en lugar de error 400 crudo
    # =========================================================================
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        flash('Tu sesión expiró o el token de seguridad es inválido. Por favor recarga la página y vuelve a intentarlo.', 'error')
        return redirect(url_for('web_dashboard.dashboard'))

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
