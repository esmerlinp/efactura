# app/api/v1/auth.py
import uuid
import hashlib
import pyotp
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify
from app.services.db_service import DatabaseService, db_firestore

api_auth_bp = Blueprint('api_auth', __name__)

@api_auth_bp.route('/auth/login', methods=['POST'])
def login():
    """
    Autenticar usuario de la aplicación móvil
    ---
    tags:
      - Auth
    summary: Iniciar sesión
    description: |
      Autentica un usuario por email y contraseña.
      Si el usuario tiene 2FA habilitado, devuelve `mfa_required: true` junto con un `mfa_token` temporal.
      Si no tiene 2FA, devuelve directamente la API Key de la compañía.
      Este endpoint **no requiere** el header X-API-Key.
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - email
            - password
          properties:
            email:
              type: string
              example: usuario@correo.com
              description: Email del usuario
            password:
              type: string
              example: "********"
              description: Contraseña del usuario
    responses:
      200:
        description: Login exitoso
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            mfa_required:
              type: boolean
              example: true
            mfa_token:
              type: string
              example: "uuid-del-token-mfa"
            email:
              type: string
              example: usuario@correo.com
            api_key:
              type: string
              example: "vyk_key_abc123..."
            user:
              type: object
              description: Perfil completo del usuario (solo si mfa_required=false)
      400:
        description: Faltan email o password
      401:
        description: Credenciales incorrectas
      403:
        description: Cuenta bloqueada o error de validación
      500:
        description: Error interno del servidor
    """
    try:
        data = request.json or {}
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({"success": False, "error": "Email y contraseña son requeridos."}), 400
            
        user_profile = DatabaseService.authenticate_user(email, password)
        if not user_profile:
            return jsonify({"success": False, "error": "Credenciales incorrectas."}), 401
            
        # Verificar si tiene 2FA habilitado
        if user_profile.get("two_factor_enabled"):
            mfa_token = str(uuid.uuid4())
            # Guardar temporalmente en Firestore
            db_firestore.collection("temp_mfa").document(mfa_token).set({
                "user_profile": user_profile,
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
            })
            return jsonify({
                "success": True,
                "mfa_required": True,
                "mfa_token": mfa_token,
                "email": email
            })
            
        # Si no requiere 2FA, obtener o generar API Key
        owner_uid = user_profile["ownerUID"]
        company = DatabaseService.get_company_profile(owner_uid)
        api_key = company.get("apiKey")
        
        if not api_key:
            api_key = DatabaseService.generate_api_key(owner_uid)
            
        return jsonify({
            "success": True,
            "mfa_required": False,
            "api_key": api_key,
            "user": user_profile
        })
        
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 403
    except Exception as e:
        return jsonify({"success": False, "error": f"Error interno del servidor: {str(e)}"}), 500


@api_auth_bp.route('/auth/verify-2fa', methods=['POST'])
def verify_2fa():
    """
    Verificar código 2FA
    ---
    tags:
      - Auth
    summary: Verificar segundo factor de autenticación
    description: |
      Valida el código TOTP o código de respaldo para completar la autenticación de dos factores.
      Si el código es válido, devuelve la API Key de la compañía.
      Este endpoint **no requiere** el header X-API-Key.
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - mfa_token
            - code
          properties:
            mfa_token:
              type: string
              description: Token MFA temporal recibido en el paso de login
              example: "uuid-del-token-mfa"
            code:
              type: string
              description: Código TOTP de 6 dígitos o código de respaldo
              example: "123456"
    responses:
      200:
        description: Verificación exitosa
        schema:
          type: object
          properties:
            success:
              type: boolean
              example: true
            api_key:
              type: string
              example: "vyk_key_abc123..."
            user:
              type: object
              description: Perfil completo del usuario autenticado
      400:
        description: Parámetros faltantes o código incorrecto
      401:
        description: Sesión de verificación expirada o inválida
      500:
        description: Error interno del servidor
    """
    try:
        data = request.json or {}
        mfa_token = data.get('mfa_token', '').strip()
        code = data.get('code', '').strip()
        
        if not mfa_token or not code:
            return jsonify({"success": False, "error": "Faltan parámetros requeridos (mfa_token, code)."}), 400
            
        temp_doc = db_firestore.collection("temp_mfa").document(mfa_token).get()
        if not temp_doc.exists:
            return jsonify({"success": False, "error": "Sesión de verificación expirada o inválida."}), 401
            
        temp_data = temp_doc.to_dict()
        user_profile = temp_data.get("user_profile", {})
        
        secret = user_profile.get('two_factor_secret')
        backup_codes = user_profile.get('backup_codes', [])
        uid = user_profile.get('uid')
        owner_uid = user_profile.get('ownerUID')
        
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
                    uid=uid,
                    secret=secret,
                    enabled=True,
                    backup_codes=backup_codes
                )
                user_profile['backup_codes'] = backup_codes
            
        if is_valid:
            # Eliminar token temporal
            db_firestore.collection("temp_mfa").document(mfa_token).delete()
            
            # Obtener o generar API Key
            company = DatabaseService.get_company_profile(owner_uid)
            api_key = company.get("apiKey")
            if not api_key:
                api_key = DatabaseService.generate_api_key(owner_uid)
                
            return jsonify({
                "success": True,
                "api_key": api_key,
                "user": user_profile
            })
        else:
            return jsonify({"success": False, "error": "Código incorrecto o expirado."}), 400
            
    except Exception as e:
        return jsonify({"success": False, "error": f"Error interno del servidor: {str(e)}"}), 500
