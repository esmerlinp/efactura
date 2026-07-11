# app/web/auth.py
import os
import hashlib
import requests as http_requests
import pyotp
import qrcode
import io
import base64
import secrets
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from config import Config
from app.services.db_service import DatabaseService
from app.services.mailer import Mailer
from app.utils.decorators import check_permission
from app.extensions import limiter
from app.brand import get_product_name

web_auth_bp = Blueprint('web_auth', __name__)

@web_auth_bp.route('/')
def home():
    is_logged_in = 'user' in session
    return render_template('landing.html', is_logged_in=is_logged_in)

@web_auth_bp.route('/api-docs')
def api_docs():
    return render_template('api_docs.html')

@web_auth_bp.route('/faqs')
def faqs():
    return render_template('faqs.html')

@web_auth_bp.route('/contacto-embed')
def contact_embed():
    return render_template('landing_contact_embed.html')

@web_auth_bp.route('/api/solicitar-demo', methods=['POST'])
def api_solicitar_demo():
    try:
        data = request.json or {}
        name = data.get('name')
        email = data.get('email')
        phone = data.get('phone')
        rnc = data.get('rnc', '')
        volumen = data.get('volumen_facturas', '100')
        transactions_qty = data.get('transactions_qty', 'No especificado')
        comments = data.get('comments', '')
        
        # Registrar solicitud de demo y cotización en consola
        print(f"INFO [Landing Lead]: Nueva solicitud de demo/cotización recibida. Nombre: {name}, Email: {email}, Teléfono: {phone}, RNC: {rnc}, Volumen: {volumen} e-CF/mes, Transacciones: {transactions_qty}, Comentarios: {comments}", flush=True)
        
        # Enviar email internamente con la solicitud a dev.esmerlin@gmail.com
        from flask import current_app

        if current_app.config.get("SMTP_USER") and current_app.config.get("SMTP_PASSWORD"):
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px;">
                <div style="text-align: center; margin-bottom: 20px; border-bottom: 2px solid #10b981; padding-bottom: 10px;">
                    <h2 style="color: #10b981; margin: 0;">Nueva Solicitud de Demo / Cotización</h2>
                </div>
                <p>Se ha recibido un nuevo lead desde la página de aterrizaje (Landing Page):</p>
                <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold; width: 35%;">Nombre:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #eee;">{name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold;">Correo:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #eee;"><a href="mailto:{email}">{email}</a></td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold;">Teléfono:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #eee;">{phone}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold;">RNC Comercial:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #eee;">{rnc if rnc else 'No provisto'}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold;">Volumen e-CF/mes:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #eee;">{volumen}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold;">Transacciones/mes:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #eee;">{transactions_qty}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border-bottom: 1px solid #eee; font-weight: bold;">Comentarios:</td>
                        <td style="padding: 8px; border-bottom: 1px solid #eee;">{comments if comments else 'Sin comentarios'}</td>
                    </tr>
                </table>
                <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
                <div style="font-size: 0.8rem; color: #999; text-align: center;">
                    Notificación automática del sistema de Landing Page de {get_product_name()}.
                </div>
            </body>
            </html>
            """

            try:
                success = Mailer.send(
                    app=current_app._get_current_object(),
                    to_email="dev.esmerlin@gmail.com",
                    subject=f"🔔 Nueva Solicitud de Demo: {name}",
                    html_body=html_body,
                    from_name=f"{get_product_name()} Landing",
                    category='support'
                )
                if success:
                    print("INFO [Landing Lead]: Email enviado exitosamente a dev.esmerlin@gmail.com", flush=True)
            except Exception as mail_err:
                print(f"WARNING [Landing Lead]: Fallo al enviar email a dev.esmerlin@gmail.com: {mail_err}", flush=True)
        else:
            print("WARNING [Landing Lead]: SMTP no configurado. No se envió el correo interno.", flush=True)
        
        return jsonify({"success": True, "message": "¡Solicitud registrada con éxito!"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


from app.cache import cache

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION = 900  # 15 minutos en segundos

@web_auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10/minute;30/hour;100/day")
def login():
    if 'user' in session:
        return redirect(url_for('web_dashboard.dashboard'))
        
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        
        # Verificar bloqueo temporal por intentos fallidos
        lockout_key = f"login_lockout_{email}"
        lockout_until = cache.get(lockout_key)
        if lockout_until:
            remaining = int(lockout_until - datetime.now().timestamp())
            if remaining > 0:
                flash(f'Demasiados intentos fallidos. Intenta de nuevo en {remaining} segundos.', 'error')
                return render_template('auth/login.html')
            else:
                cache.delete(lockout_key)
        
        try:
            user_profile = DatabaseService.authenticate_user(email, password)
            if user_profile:
                # Restablecer contador de intentos fallidos
                cache.delete(f"login_attempts_{email}")
                
                # Si tiene MFA activo, guardar perfil temporal y redirigir
                # Si tiene MFA activo, guardar perfil temporal y redirigir
                if user_profile.get("two_factor_enabled"):
                    session['mfa_pending_uid'] = user_profile['uid']
                    session['mfa_pending_email'] = user_profile['email']
                    session['mfa_pending_profile'] = user_profile
                    return redirect(url_for('web_auth.verify_2fa'))
                    
                session['user'] = user_profile
                session['is_sandbox_mode'] = False  # Producción por defecto al iniciar
                
                # Cargar empresas asociadas
                associated = DatabaseService.get_associated_companies(user_profile['uid'])
                session['associated_companies'] = associated
                session['user_has_multiple_companies'] = len(associated) > 1
                
                if len(associated) > 1:
                    session.pop('selected_owner_uid', None)
                else:
                    session['selected_owner_uid'] = associated[0]['ownerUID'] if len(associated) == 1 else user_profile.get('ownerUID')
                    session['user']['ownerUID'] = session['selected_owner_uid']
                
                from app.services.audit_service import AuditService, ACTION_LOGIN, MODULE_AUTH
                AuditService.log_from_request(
                    owner_uid=session.get('selected_owner_uid') or user_profile.get('ownerUID'),
                    action=ACTION_LOGIN,
                    module=MODULE_AUTH,
                    entity_id=user_profile['uid'],
                    entity_label=f"Inicio de sesión exitoso — {user_profile['email']}",
                    user_session=user_profile,
                    sandbox=False
                )
                
                flash('¡Sesión iniciada exitosamente!', 'success')
                if session.get('user_has_multiple_companies'):
                    return redirect(url_for('web_auth.select_company'))
                return redirect(url_for('web_dashboard.dashboard'))
            else:
                from app.services.audit_service import AuditService, ACTION_LOGIN, MODULE_AUTH
                AuditService.log_from_request(
                    owner_uid=email,
                    action=ACTION_LOGIN,
                    module=MODULE_AUTH,
                    entity_id=email,
                    entity_label=f"Inicio de sesión fallido — {email}",
                    user_session={},
                    sandbox=False
                )
                att_key = f"login_attempts_{email}"
                attempts = cache.get(att_key) or 0
                attempts += 1
                cache.set(att_key, attempts, timeout=LOCKOUT_DURATION)
                if attempts >= MAX_LOGIN_ATTEMPTS:
                    lockout_key = f"login_lockout_{email}"
                    lockout_until = datetime.now().timestamp() + LOCKOUT_DURATION
                    cache.set(lockout_key, lockout_until, timeout=LOCKOUT_DURATION)
                    flash(f'Cuenta bloqueada temporalmente. Intenta de nuevo en {LOCKOUT_DURATION // 60} minutos.', 'error')
                else:
                    remaining = MAX_LOGIN_ATTEMPTS - attempts
                    flash(f'Credenciales incorrectas. Te quedan {remaining} intento(s).', 'error')
        except ValueError as e:
            flash(str(e), 'error')
            
    return render_template('auth/login.html')

@web_auth_bp.route('/login/verify-2fa', methods=['GET', 'POST'])
@limiter.limit("10/minute;30/hour")
def verify_2fa():
    if 'user' in session:
        return redirect(url_for('web_dashboard.dashboard'))
        
    if 'mfa_pending_uid' not in session or 'mfa_pending_profile' not in session:
        flash('Sesión expirada o inválida.', 'error')
        return redirect(url_for('web_auth.login'))
        
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        user_profile = session['mfa_pending_profile']
        secret = user_profile.get('two_factor_secret')
        backup_codes = user_profile.get('backup_codes', [])
        
        is_valid = False
        
        # 1. Verificar TOTP
        if secret:
            totp = pyotp.TOTP(secret)
            if totp.verify(code, valid_window=1):
                is_valid = True
                
        # 2. Verificar códigos de respaldo (hasheados en Firestore)
        if not is_valid:
            hashed_input = hashlib.sha256(code.encode()).hexdigest()
            if hashed_input in backup_codes:
                is_valid = True
                backup_codes.remove(hashed_input)
                DatabaseService.save_user_2fa_config(
                    uid=user_profile['uid'],
                    secret=secret,
                    enabled=True,
                    backup_codes=backup_codes
                )
                user_profile['backup_codes'] = backup_codes
            
        if is_valid:
            session['user'] = user_profile
            session['is_sandbox_mode'] = False
            
            # Cargar empresas asociadas
            associated = DatabaseService.get_associated_companies(user_profile['uid'])
            session['associated_companies'] = associated
            session['user_has_multiple_companies'] = len(associated) > 1
            
            if len(associated) > 1:
                session.pop('selected_owner_uid', None)
            else:
                session['selected_owner_uid'] = associated[0]['ownerUID'] if len(associated) == 1 else user_profile.get('ownerUID')
                session['user']['ownerUID'] = session['selected_owner_uid']
            
            # Limpiar estado temporal de MFA
            session.pop('mfa_pending_uid', None)
            session.pop('mfa_pending_email', None)
            session.pop('mfa_pending_profile', None)
            
            from app.services.audit_service import AuditService, ACTION_LOGIN, MODULE_AUTH
            AuditService.log_from_request(
                owner_uid=session.get('selected_owner_uid') or user_profile.get('ownerUID'),
                action=ACTION_LOGIN,
                module=MODULE_AUTH,
                entity_id=user_profile['uid'],
                entity_label=f"Inicio de sesión exitoso con 2FA — {user_profile['email']}",
                user_session=user_profile,
                sandbox=False
            )
            
            flash('¡Sesión iniciada exitosamente con 2FA!', 'success')
            if session.get('user_has_multiple_companies'):
                return redirect(url_for('web_auth.select_company'))
            return redirect(url_for('web_dashboard.dashboard'))
        else:
            flash('Código incorrecto o inválido. Inténtalo de nuevo.', 'error')
            
    return render_template('auth/verify_2fa.html', email=session.get('mfa_pending_email'))

@web_auth_bp.route('/profile/2fa/setup', methods=['POST'])
def setup_2fa():
    """Genera la clave secreta y el código QR para el usuario."""
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
        
    user = session['user']
    email = user.get('email')
    
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=email, issuer_name=f"{get_product_name()} RD")
    
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    
    return jsonify({
        "success": True,
        "secret": secret,
        "qr_code": f"data:image/png;base64,{qr_base64}"
    })

@web_auth_bp.route('/profile/2fa/enable', methods=['POST'])
def enable_2fa():
    """Verifica el primer token y activa 2FA."""
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
        
    data = request.get_json(silent=True) or {}
    secret = data.get('secret')
    code = data.get('code')
    
    if not secret or not code:
        return jsonify({"success": False, "error": "Faltan parámetros requeridos."}), 400
        
    totp = pyotp.TOTP(secret)
    if totp.verify(code, valid_window=1):
        user = session['user']
        uid = user['uid']
        
        backup_codes = [secrets.token_hex(4).upper() for _ in range(8)]
        
        success = DatabaseService.save_user_2fa_config(uid, secret, True, backup_codes)
        if success:
            session['user']['two_factor_enabled'] = True
            session['user']['two_factor_secret'] = secret
            session['user']['backup_codes'] = backup_codes
            session.modified = True
            
            from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_AUTH
            AuditService.log_from_request(
                owner_uid=user['ownerUID'],
                action=ACTION_UPDATE,
                module=MODULE_AUTH,
                entity_id=uid,
                entity_label=f"Habilitó verificación en dos pasos (2FA) — {user['email']}",
                user_session=user,
                sandbox=session.get('is_sandbox_mode', False)
            )
            
            return jsonify({
                "success": True,
                "message": "Autenticación de dos factores activada con éxito.",
                "backup_codes": backup_codes
            })
        else:
            return jsonify({"success": False, "error": "Error al guardar en base de datos."}), 500
    else:
        return jsonify({"success": False, "error": "El código ingresado es incorrecto o ha expirado."}), 400

@web_auth_bp.route('/profile/2fa/disable', methods=['POST'])
def disable_2fa():
    """Desactiva 2FA para el usuario."""
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
        
    data = request.get_json(silent=True) or {}
    password = data.get('password')
    
    if not password:
        return jsonify({"success": False, "error": "Se requiere ingresar su contraseña actual."}), 400
        
    user = session['user']
    email = user.get('email')
    
    if Config.FIREBASE_API_KEY:
        try:
            verify_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={Config.FIREBASE_API_KEY}"
            verify_res = http_requests.post(verify_url, json={
                "email": email,
                "password": password,
                "returnSecureToken": True
            }, timeout=10)
            if verify_res.status_code != 200:
                return jsonify({"success": False, "error": "La contraseña ingresada es incorrecta."}), 400
        except Exception as e:
            return jsonify({"success": False, "error": f"Error al verificar contraseña: {e}"}), 500
            
    uid = user['uid']
    success = DatabaseService.save_user_2fa_config(uid, None, False, [])
    if success:
        session['user']['two_factor_enabled'] = False
        session['user']['two_factor_secret'] = None
        session['user']['backup_codes'] = []
        session.modified = True
        
        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_AUTH
        AuditService.log_from_request(
            owner_uid=user['ownerUID'],
            action=ACTION_UPDATE,
            module=MODULE_AUTH,
            entity_id=uid,
            entity_label=f"Deshabilitó verificación en dos pasos (2FA) — {user['email']}",
            user_session=user,
            sandbox=session.get('is_sandbox_mode', False)
        )
        return jsonify({"success": True, "message": "Autenticación de dos factores desactivada con éxito."})
    else:
        return jsonify({"success": False, "error": "Error al guardar en base de datos."}), 500


@web_auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("3/hour;10/day")
def register():
    flash('El registro público de cuentas está deshabilitado. Comuníquese con ventas para crear su cuenta.', 'error')
    return redirect(url_for('web_auth.login'))

@web_auth_bp.route('/logout')
def logout():
    user = session.get('user')
    if user:
        from app.services.audit_service import AuditService, ACTION_LOGOUT, MODULE_AUTH
        AuditService.log_from_request(
            owner_uid=user['ownerUID'],
            action=ACTION_LOGOUT,
            module=MODULE_AUTH,
            entity_id=user['uid'],
            entity_label=f"Cierre de sesión — {user['email']}",
            user_session=user,
            sandbox=session.get('is_sandbox_mode', False)
        )
    session.pop('user', None)
    session.pop('is_sandbox_mode', None)
    session.pop('selected_owner_uid', None)
    session.pop('selected_branch_id', None)
    session.pop('available_branches', None)
    session.pop('selected_project_id', None)
    session.pop('available_projects', None)
    session.pop('associated_companies', None)
    session.pop('user_has_multiple_companies', None)
    flash('Sesión cerrada correctamente.', 'success')
    return redirect(url_for('web_auth.login'))

@web_auth_bp.route('/select-company', methods=['GET', 'POST'])
def select_company():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
        
    # Siempre obtener de la base de datos para asegurar que los logos y nombres estén actualizados
    associated = DatabaseService.get_associated_companies(session['user']['uid'])
    session['associated_companies'] = associated
    session['user_has_multiple_companies'] = len(associated) > 1

    associated_companies = associated
    
    if len(associated_companies) <= 1:
        if len(associated_companies) == 1:
            session['selected_owner_uid'] = associated_companies[0]['ownerUID']
        else:
            session['selected_owner_uid'] = session['user'].get('uid')
        return redirect(url_for('web_dashboard.dashboard'))
        
    if request.method == 'POST':
        selected_uid = request.form.get('owner_uid')
        if any(c['ownerUID'] == selected_uid for c in associated_companies):
            session['selected_owner_uid'] = selected_uid
            session['user']['ownerUID'] = selected_uid
            session.pop('selected_branch_id', None)
            session.pop('available_branches', None)
            session.pop('selected_project_id', None)
            session.pop('available_projects', None)
            
            # Registrar cambio de empresa en auditoría
            from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_AUTH
            AuditService.log_from_request(
                owner_uid=selected_uid,
                action=ACTION_UPDATE,
                module=MODULE_AUTH,
                entity_id=session['user']['uid'],
                entity_label=f"Colaborador cambió de empresa activa a {selected_uid}",
                user_session=session['user'],
                sandbox=session.get('is_sandbox_mode', False)
            )
            
            flash('Empresa seleccionada con éxito.', 'success')
            return redirect(url_for('web_dashboard.dashboard'))
        else:
            flash('Selección de empresa inválida o no autorizada.', 'error')
            
    return render_template('auth/select_company.html', associated_companies=associated_companies)


@web_auth_bp.route('/select-branch', methods=['GET', 'POST'])
def select_branch():
    if 'user' not in session:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({"success": False, "error": "No autenticado"}), 401
        return redirect(url_for('web_auth.login'))
    
    owner_uid = session.get('selected_owner_uid') or session['user'].get('ownerUID')
    sandbox = session.get('is_sandbox_mode', False)
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
    
    if request.method == 'POST':
        selected_branch = request.form.get('branch_id') or (request.json or {}).get('branch_id')
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json
        if selected_branch == '__all__':
            session['selected_branch_id'] = None
            if not is_ajax: flash('Vista de todas las sucursales activada.', 'success')
        elif any(b['id'] == selected_branch for b in branches):
            session['selected_branch_id'] = selected_branch
            session.pop('selected_project_id', None)
            session.pop('available_projects', None)
            if not is_ajax: flash('Sucursal seleccionada con éxito.', 'success')
        else:
            if is_ajax:
                return jsonify({"success": False, "error": "Selección de sucursal inválida."}), 400
            flash('Selección de sucursal inválida.', 'error')
        if is_ajax:
            return jsonify({"success": True})
        return redirect(url_for('web_dashboard.dashboard'))
    
    return render_template('auth/select_branch.html', branches=branches)


@web_auth_bp.route('/select-project', methods=['GET', 'POST'])
def select_project():
    if 'user' not in session:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({"success": False, "error": "No autenticado"}), 401
        return redirect(url_for('web_auth.login'))
    
    owner_uid = session.get('selected_owner_uid') or session['user'].get('ownerUID')
    sandbox = session.get('is_sandbox_mode', False)
    selected_bid = session.get('selected_branch_id')
    projects = DatabaseService.get_projects(owner_uid, branch_id=selected_bid, sandbox=sandbox)
    
    if request.method == 'POST':
        selected_project = request.form.get('project_id') or (request.json or {}).get('project_id')
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json
        if selected_project == '__all__':
            session['selected_project_id'] = None
            if not is_ajax: flash('Vista de todos los proyectos activada.', 'success')
        elif selected_project == '__no_project__':
            session['selected_project_id'] = '__no_project__'
            if not is_ajax: flash('Vista de registros sin proyecto activada.', 'success')
        elif any(p['id'] == selected_project for p in projects):
            session['selected_project_id'] = selected_project
            if not is_ajax: flash('Proyecto seleccionado con éxito.', 'success')
        else:
            if is_ajax:
                return jsonify({"success": False, "error": "Selección de proyecto inválida."}), 400
            flash('Selección de proyecto inválida.', 'error')
        if is_ajax:
            return jsonify({"success": True})
        return redirect(url_for('web_dashboard.dashboard'))
    
    return render_template('auth/select_project.html', projects=projects)


@web_auth_bp.route('/forgot-password', methods=['POST'])
@limiter.limit("3/minute;10/hour;30/day")
def forgot_password():
    """Envía un correo de recuperación de contraseña usando Firebase Auth REST API."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()

    if not email:
        return jsonify({"success": False, "error": "El correo electrónico es requerido."}), 400

    if not Config.FIREBASE_API_KEY:
        return jsonify({"success": False, "error": "La función de recuperación de contraseña no está disponible en este momento."}), 503

    try:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={Config.FIREBASE_API_KEY}"
        res = http_requests.post(url, json={
            "requestType": "PASSWORD_RESET",
            "email": email
        }, timeout=10)

        if res.status_code == 200:
            print(f"INFO [ForgotPassword]: Correo de recuperación enviado a {email}", flush=True)
            return jsonify({"success": True})
        else:
            error_data = res.json().get("error", {})
            error_code = error_data.get("message", "")
            print(f"⚠️ [ForgotPassword] Firebase error para {email}: {error_code}", flush=True)

            if error_code in ("EMAIL_NOT_FOUND", "INVALID_EMAIL"):
                return jsonify({"success": True})

            return jsonify({"success": False, "error": "Error al enviar el correo. Verifica la dirección e inténtalo de nuevo."})

    except Exception as e:
        print(f"❌ [ForgotPassword] Excepción: {e}", flush=True)
        return jsonify({"success": False, "error": "Error de conexión. Por favor intenta más tarde."}), 500


@web_auth_bp.route('/toggle-sandbox', methods=['POST'])
def toggle_sandbox():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    if not check_permission('canToggleSandbox'):
        return jsonify({"success": False, "error": "No tienes permisos para alternar el modo Sandbox"}), 403
    
    data = request.get_json(silent=True) or {}
    if 'sandbox' in data:
        session['is_sandbox_mode'] = bool(data['sandbox'])
    else:
        current_mode = session.get('is_sandbox_mode', False)
        session['is_sandbox_mode'] = not current_mode
    return jsonify({"success": True, "sandbox": session['is_sandbox_mode']})

# =========================================================================
# PERFIL DE USUARIO
# =========================================================================
@web_auth_bp.route('/profile', methods=['GET'])
def user_profile_page():
    """Muestra la pantalla de perfil del usuario autenticado."""
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    
    info_success = request.args.get('info_success')
    info_error = request.args.get('info_error')
    pwd_success = request.args.get('pwd_success')
    pwd_error = request.args.get('pwd_error')
    pin_success = request.args.get('pin_success')
    pin_error = request.args.get('pin_error')

    return render_template(
        'user_profile.html',
        active_page='profile',
        user=session['user'],
        info_success=info_success,
        info_error=info_error,
        pwd_success=pwd_success,
        pwd_error=pwd_error,
        pin_success=pin_success,
        pin_error=pin_error,
    )


@web_auth_bp.route('/profile/update-pin', methods=['POST'])
def update_supervisor_pin():
    """Procesa el registro o actualización del PIN de supervisor de caja del usuario."""
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
        
    user = session['user']
    is_owner = user.get('role') == 'owner'
    is_supervisor = user.get('permissions', {}).get('isPosSupervisor', False)
    
    if not is_owner and not is_supervisor:
        return redirect(url_for('web_auth.user_profile_page', pin_error='No tienes permisos de supervisor o propietario.'))
        
    pin = request.form.get('supervisor_pin', '').strip()
    if not pin.isdigit() or len(pin) < 4 or len(pin) > 6:
        return redirect(url_for('web_auth.user_profile_page', pin_error='El PIN de supervisor debe ser numérico y tener entre 4 y 6 dígitos.'))
        
    uid = user['uid']
    try:
        from app.services.db_service import db_firestore
        db_firestore.collection("users").document(uid).collection("config").document("user_profile").update({
            "posSupervisorPin": pin
        })
        session['user']['posSupervisorPin'] = pin
        session.modified = True
        
        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_AUTH
        AuditService.log_from_request(
            owner_uid=user['ownerUID'],
            action=ACTION_UPDATE,
            module=MODULE_AUTH,
            entity_id=uid,
            entity_label=f"Actualizó PIN de supervisor POS — {user['email']}",
            user_session=user,
            sandbox=session.get('is_sandbox_mode', False)
        )
        return redirect(url_for('web_auth.user_profile_page', pin_success='¡PIN de supervisor de caja actualizado exitosamente!'))
    except Exception as e:
        return redirect(url_for('web_auth.user_profile_page', pin_error=f'Error al guardar PIN: {str(e)}'))


@web_auth_bp.route('/profile/update', methods=['POST'])
def update_user_profile():
    """Procesa la actualización de información personal del usuario (nombre, teléfono, dirección)."""
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))

    uid = session['user']['uid']
    name = request.form.get('name', '').strip()
    phone = request.form.get('phone', '').strip()
    address = request.form.get('address', '').strip()

    if not name:
        return redirect(url_for('web_auth.user_profile_page', info_error='El nombre no puede estar vacío.'))

    try:
        profile_image_url = session['user'].get('profileImageUrl')
        avatar_file = request.files.get('avatar')
        
        print(f"DEBUG PROFILE UPDATE: name={name}, avatar_file_present={bool(avatar_file)}")
        if avatar_file:
            print(f"DEBUG PROFILE UPDATE: avatar_filename='{avatar_file.filename}'")
        else:
            print("DEBUG PROFILE UPDATE: no avatar file attached")
            
        if avatar_file and avatar_file.filename:
            print("DEBUG PROFILE UPDATE: File attached, starting upload...")
            from werkzeug.utils import secure_filename
            import uuid
            
            filename = secure_filename(avatar_file.filename)
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            owner_uid = session['user'].get('ownerUID', uid)
            destination_path = f"users/{owner_uid}/avatars/{unique_filename}"
            
            avatar_file.seek(0)
            file_bytes = avatar_file.read()
            content_type = avatar_file.content_type
            
            print(f"DEBUG PROFILE UPDATE: uploading {len(file_bytes)} bytes to {destination_path}")

            
            profile_image_url = DatabaseService.upload_file_to_storage(
                file_bytes, destination_path, content_type
            )
            
        before_profile = session['user'].copy()
        updated_profile = {
            "name": name,
            "phone": phone,
            "address": address,
            "permissions": session['user'].get('permissions', {})
        }
        
        if profile_image_url:
            updated_profile["profileImageUrl"] = profile_image_url

        DatabaseService.save_user_profile(uid, updated_profile)

        # Actualizar la sesión activa para reflejar los cambios de inmediato
        session['user']['name'] = name
        session['user']['phone'] = phone
        session['user']['address'] = address
        if profile_image_url:
            session['user']['profileImageUrl'] = profile_image_url
        session.modified = True

        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_AUTH
        AuditService.log_from_request(
            owner_uid=session['user']['ownerUID'],
            action=ACTION_UPDATE,
            module=MODULE_AUTH,
            entity_id=uid,
            entity_label=f"Actualización de perfil de usuario — {session['user']['email']}",
            user_session=session['user'],
            before=before_profile,
            after=session['user'],
            sandbox=session.get('is_sandbox_mode', False)
        )

        return redirect(url_for('web_auth.user_profile_page', info_success='¡Información personal actualizada con éxito!'))
    except Exception as e:
        return redirect(url_for('web_auth.user_profile_page', info_error=f'Error al guardar: {str(e)}'))


@web_auth_bp.route('/profile/change-password', methods=['POST'])
def change_user_password():
    """Cambia la contraseña del usuario verificando primero la contraseña actual con Firebase Auth REST API."""
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))

    email = session['user'].get('email', '')
    current_password = request.form.get('current_password', '').strip()
    new_password = request.form.get('new_password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()

    if not current_password or not new_password or not confirm_password:
        return redirect(url_for('web_auth.user_profile_page', pwd_error='Todos los campos de contraseña son obligatorios.'))

    if new_password != confirm_password:
        return redirect(url_for('web_auth.user_profile_page', pwd_error='Las contraseñas nuevas no coinciden.'))

    if len(new_password) < 6:
        return redirect(url_for('web_auth.user_profile_page', pwd_error='La nueva contraseña debe tener al menos 6 caracteres.'))

    if new_password == current_password:
        return redirect(url_for('web_auth.user_profile_page', pwd_error='La nueva contraseña debe ser diferente a la contraseña actual.'))

    if not Config.FIREBASE_API_KEY:
        return redirect(url_for('web_auth.user_profile_page', pwd_error='La función de cambio de contraseña no está disponible (FIREBASE_API_KEY no configurada).'))

    try:
        # Verificar credenciales actuales
        verify_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={Config.FIREBASE_API_KEY}"
        verify_res = http_requests.post(verify_url, json={
            "email": email,
            "password": current_password,
            "returnSecureToken": True
        }, timeout=10)

        if verify_res.status_code != 200:
            error_msg = verify_res.json().get('error', {}).get('message', 'Contraseña actual incorrecta.')
            if 'INVALID_LOGIN_CREDENTIALS' in error_msg or 'WRONG_PASSWORD' in error_msg or 'INVALID_PASSWORD' in error_msg:
                error_msg = 'La contraseña actual es incorrecta. Por favor verifica e inténtalo de nuevo.'
            return redirect(url_for('web_auth.user_profile_page', pwd_error=error_msg))

        id_token = verify_res.json().get('idToken')
        if not id_token:
            return redirect(url_for('web_auth.user_profile_page', pwd_error='No se pudo verificar la sesión con Firebase. Intenta de nuevo.'))

        # Cambiar la contraseña usando el idToken válido
        update_url = f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={Config.FIREBASE_API_KEY}"
        update_res = http_requests.post(update_url, json={
            "idToken": id_token,
            "password": new_password,
            "returnSecureToken": True
        }, timeout=10)

        if update_res.status_code == 200:
            from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_AUTH
            AuditService.log_from_request(
                owner_uid=session['user']['ownerUID'],
                action=ACTION_UPDATE,
                module=MODULE_AUTH,
                entity_id=session['user']['uid'],
                entity_label=f"Cambio de contraseña exitoso — {session['user']['email']}",
                user_session=session['user'],
                sandbox=session.get('is_sandbox_mode', False)
            )
            return redirect(url_for('web_auth.user_profile_page', pwd_success='¡Contraseña actualizada exitosamente! Tu nueva contraseña está activa.'))
        else:
            error_detail = update_res.json().get('error', {}).get('message', 'Error desconocido.')
            return redirect(url_for('web_auth.user_profile_page', pwd_error=f'No se pudo actualizar la contraseña: {error_detail}'))

    except Exception as e:
        return redirect(url_for('web_auth.user_profile_page', pwd_error=f'Error de conexión con Firebase: {str(e)}'))
