# app/web/auth.py
import os
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

@web_auth_bp.route('/api/solicitar-demo', methods=['POST'])
def api_solicitar_demo():
    try:
        data = request.json or {}
        name = data.get('name')
        email = data.get('email')
        phone = data.get('phone')
        rnc = data.get('rnc', '')
        volumen = data.get('volumen_facturas', '100')
        
        # Registrar solicitud de demo y cotización en consola
        print(f"INFO [Landing Lead]: Nueva solicitud de demo/cotización recibida. Nombre: {name}, Email: {email}, Teléfono: {phone}, RNC: {rnc}, Volumen: {volumen} e-CF/mes", flush=True)
        
        return jsonify({"success": True, "message": "¡Solicitud registrada con éxito!"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@web_auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        return redirect(url_for('web_dashboard.dashboard'))
        
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user_profile = DatabaseService.authenticate_user(email, password)
        if user_profile:
            # Si tiene MFA activo, guardar perfil temporal y redirigir
            if user_profile.get("two_factor_enabled"):
                session['mfa_pending_uid'] = user_profile['uid']
                session['mfa_pending_email'] = user_profile['email']
                session['mfa_pending_profile'] = user_profile
                return redirect(url_for('web_auth.verify_2fa'))
                
            session['user'] = user_profile
            session['is_sandbox_mode'] = False  # Producción por defecto al iniciar
            
            from app.services.audit_service import AuditService, ACTION_LOGIN, MODULE_AUTH
            AuditService.log_from_request(
                owner_uid=user_profile['ownerUID'],
                action=ACTION_LOGIN,
                module=MODULE_AUTH,
                entity_id=user_profile['uid'],
                entity_label=f"Inicio de sesión exitoso — {user_profile['email']}",
                user_session=user_profile,
                sandbox=False
            )
            
            flash('¡Sesión iniciada exitosamente!', 'success')
            return redirect(url_for('web_dashboard.dashboard'))
        else:
            flash('Credenciales incorrectas. Inténtalo de nuevo.', 'error')
            
    return render_template('auth/login.html')

@web_auth_bp.route('/login/verify-2fa', methods=['GET', 'POST'])
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
                
        # 2. Verificar códigos de respaldo
        if not is_valid and code in backup_codes:
            is_valid = True
            backup_codes.remove(code)
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
            
            # Limpiar estado temporal de MFA
            session.pop('mfa_pending_uid', None)
            session.pop('mfa_pending_email', None)
            session.pop('mfa_pending_profile', None)
            
            from app.services.audit_service import AuditService, ACTION_LOGIN, MODULE_AUTH
            AuditService.log_from_request(
                owner_uid=user_profile['ownerUID'],
                action=ACTION_LOGIN,
                module=MODULE_AUTH,
                entity_id=user_profile['uid'],
                entity_label=f"Inicio de sesión exitoso con 2FA — {user_profile['email']}",
                user_session=user_profile,
                sandbox=False
            )
            
            flash('¡Sesión iniciada exitosamente con 2FA!', 'success')
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
    provisioning_uri = totp.provisioning_uri(name=email, issuer_name="e-Factura RD")
    
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
    flash('Sesión cerrada correctamente.', 'success')
    return redirect(url_for('web_auth.login'))


@web_auth_bp.route('/forgot-password', methods=['POST'])
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

    return render_template(
        'user_profile.html',
        active_page='profile',
        user=session['user'],
        info_success=info_success,
        info_error=info_error,
        pwd_success=pwd_success,
        pwd_error=pwd_error,
    )


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
        before_profile = session['user'].copy()
        updated_profile = {
            "name": name,
            "phone": phone,
            "address": address,
            "permissions": session['user'].get('permissions', {})
        }
        DatabaseService.save_user_profile(uid, updated_profile)

        # Actualizar la sesión activa para reflejar los cambios de inmediato
        session['user']['name'] = name
        session['user']['phone'] = phone
        session['user']['address'] = address
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
