import os
import json
import uuid
import requests
import traceback
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

# Intentar inicializar Firebase Admin
firebase_initialized = False
db_firestore = None
firebase_storage_bucket = None

try:
    import firebase_admin
    from firebase_admin import credentials, firestore, storage, auth
    
    # Verificar si ya está inicializado para evitar excepciones
    if not firebase_admin._apps:
        if os.path.exists(Config.FIREBASE_SERVICE_ACCOUNT_JSON):
            cred = credentials.Certificate(Config.FIREBASE_SERVICE_ACCOUNT_JSON)
            if Config.FIREBASE_STORAGE_BUCKET:
                firebase_admin.initialize_app(cred, {
                    'storageBucket': Config.FIREBASE_STORAGE_BUCKET
                })
            else:
                firebase_admin.initialize_app(cred)
        else:
            # Fallback para entornos GCP (App Engine, Cloud Run, etc.) usando credenciales por defecto de la aplicación (ADC)
            if Config.FIREBASE_STORAGE_BUCKET:
                firebase_admin.initialize_app(options={
                    'storageBucket': Config.FIREBASE_STORAGE_BUCKET
                })
            else:
                firebase_admin.initialize_app()
    
    db_firestore = firestore.client()
    if Config.FIREBASE_STORAGE_BUCKET:
        firebase_storage_bucket = storage.bucket()
    firebase_initialized = True
    print("🔥 Firebase Admin SDK inicializado correctamente y conectado a Firestore.")
except Exception as e:
    print(f"❌ Error al inicializar Firebase Admin SDK: {e}. Operando en MODO LOCAL (SQLite).")
    traceback.print_exc()


def serialize_field(val):
    """Convierte campos de Firestore (como DatetimeWithNanoseconds o Timestamp) a strings."""
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%dT%H:%M:%S")
    return str(val)


class DatabaseService:

    @classmethod
    def init_local_db(cls):
        """Verifica la conexión con Firebase y registra el usuario Administrador Demo en la nube si no existe."""
        if not firebase_initialized:
            raise RuntimeError("El SDK de Firebase Admin NO está inicializado. Coloca el archivo firebase-adminsdk.json en la raíz del proyecto para poder operar.")
            
        print("🔥 Firebase Admin SDK verificado exitosamente.")
        
        try:
            demo_email = "propietario@efactura.com.do"
            try:
                auth.get_user_by_email(demo_email)
                print(f"👤 Usuario Administrador Demo '{demo_email}' ya está registrado en Firebase Auth.")
            except auth.UserNotFoundError:
                print(f"👤 Registrando Usuario Administrador Demo '{demo_email}' en Firebase Auth...")
                cls.register_user(
                    email=demo_email,
                    password="password123",
                    name="Propietario Demo",
                    role="owner"
                )
                print(f"👤 Usuario Administrador Demo '{demo_email}' registrado exitosamente en Firebase Auth y Firestore.")
        except Exception as e:
            print(f"⚠️ Error al inicializar el usuario demo en Firebase: {e}")

    @classmethod
    def firebase_rest_auth(cls, email, password, signup=False):
        """Interactúa con la API REST de Firebase Auth usando la clave de API del cliente."""
        if not Config.FIREBASE_API_KEY:
            return None
        
        endpoint = "signUp" if signup else "signInWithPassword"
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:{endpoint}?key={Config.FIREBASE_API_KEY}"
        payload = {
            "email": email,
            "password": password,
            "returnSecureToken": True
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"⚠️ Firebase REST Auth {endpoint} error: {response.text}")
        except Exception as e:
            print(f"❌ Error conectando con API REST de Firebase Auth: {e}")
        return None

    @classmethod
    def register_user(cls, email, password, name, role="owner", owner_uid=None, can_manage_own_company=None):
        """Registra un nuevo usuario en Firebase Auth y Firestore."""
        uid = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        resolved_owner_uid = owner_uid if owner_uid else uid

        if can_manage_own_company is None:
            can_manage_own_company = True if role == "owner" else False

        if not firebase_initialized:
            raise RuntimeError("El SDK de Firebase Admin no está inicializado. No se puede registrar el usuario.")

        # 1. Registrar o recuperar en Firebase Auth
        existing_auth_user = None
        try:
            existing_auth_user = auth.get_user_by_email(email)
            uid = existing_auth_user.uid
            resolved_owner_uid = owner_uid if owner_uid else uid
            print(f"ℹ️ El usuario con email '{email}' ya existe en Firebase Auth con UID '{uid}'. Se asociará esta cuenta.")
        except auth.UserNotFoundError:
            pass
        except Exception as e:
            print(f"⚠️ Error al buscar usuario por email en Firebase Auth: {e}")

        if not existing_auth_user:
            try:
                if Config.FIREBASE_API_KEY:
                    res = cls.firebase_rest_auth(email, password, signup=True)
                    if res:
                        uid = res["localId"]
                        resolved_owner_uid = owner_uid if owner_uid else uid
                    else:
                        # Si falló la API REST, podría ser por email duplicado. Intentar buscarlo de todos modos.
                        try:
                            existing_auth_user = auth.get_user_by_email(email)
                            uid = existing_auth_user.uid
                            resolved_owner_uid = owner_uid if owner_uid else uid
                        except Exception:
                            raise ValueError("No se pudo registrar el usuario a través de la API REST de Firebase y tampoco se encontró por email.")
                else:
                    user_record = auth.create_user(
                        email=email,
                        password=password,
                        display_name=name,
                        uid=uid
                    )
                    uid = user_record.uid
                    resolved_owner_uid = owner_uid if owner_uid else uid
            except Exception as e:
                if "EMAIL_EXISTS" in str(e) or "already in use" in str(e):
                    try:
                        user_record = auth.get_user_by_email(email)
                        uid = user_record.uid
                        resolved_owner_uid = owner_uid if owner_uid else uid
                    except Exception:
                        raise e
                else:
                    raise e


        # 2. Guardar/Actualizar perfil del usuario en Firestore sin sobrescribir si ya existe
        doc_ref = db_firestore.collection("users").document(uid).collection("config").document("user_profile")
        doc_snap = doc_ref.get()
        
        if doc_snap.exists:
            existing_data = doc_snap.to_dict()
            # Conservar ownerUID y rol original
            resolved_owner_uid = existing_data.get("ownerUID", uid)
            role = existing_data.get("role", "owner")
            
            # Obtener nombre de la empresa invitadora
            inviting_comp_name = "Empresa Invitadora"
            if owner_uid:
                comp_prof = cls.get_company_profile(owner_uid)
                inviting_comp_name = comp_prof.get("companyName", "Empresa Invitadora")
                
            associated_companies = existing_data.get("associated_companies", [])
            
            # Obtener can_manage_own_company actual o nuevo
            current_can_manage = existing_data.get("canManageOwnCompany", can_manage_own_company)
            
            # Si se le permite administrar su propia empresa, asegurar que esté en la lista
            if current_can_manage:
                if not any(c.get("ownerUID") == resolved_owner_uid for c in associated_companies):
                    own_comp = cls.get_company_profile(resolved_owner_uid)
                    associated_companies.insert(0, {
                        "ownerUID": resolved_owner_uid,
                        "companyName": own_comp.get("companyName", "Mi Empresa"),
                        "role": role
                    })
            else:
                # Si no está permitido, remover su propia empresa de la lista si está
                associated_companies = [c for c in associated_companies if c.get("ownerUID") != resolved_owner_uid]
                
            # Agregar la nueva empresa invitadora a la lista si no está ya
            if owner_uid and not any(c.get("ownerUID") == owner_uid for c in associated_companies):
                associated_companies.append({
                    "ownerUID": owner_uid,
                    "companyName": inviting_comp_name,
                    "role": "employee"
                })
                
            doc_ref.update({
                "associated_companies": associated_companies,
                "canManageOwnCompany": current_can_manage
            })
            
            profile_data = existing_data
            profile_data["uid"] = uid
            profile_data["associated_companies"] = associated_companies
            profile_data["canManageOwnCompany"] = current_can_manage
        else:
            # Crear perfil nuevo para nuevo usuario
            profile_data = {
                "uid": uid,
                "ownerUID": resolved_owner_uid,
                "role": role,
                "name": name,
                "email": email,
                "phone": "",
                "address": "",
                "canManageOwnCompany": can_manage_own_company,
                "permissions": {
                    "canInvoice": True,
                    "canExpenses": True,
                    "canClients": True,
                    "canModifySettings": True,
                    "canManageInventory": True,
                    "canManagePOS": True,
                    "canViewDashboard": True,
                    "canManageCXC": True,
                    "canManageCXP": True,
                    "canManageContracts": True,
                    "canManageCommissions": True,
                    "canViewBI": True,
                    "canViewAuditLog": False,
                    "isPosSupervisor": False,
                    "canViewSubscription": True,
                    "canToggleSandbox": True,
                    "canManageNotes": True
                },
                "createdAt": created_at,
                "associated_companies": [],
                "posSupervisorPin": ""
            }
            
            # Inicializar su propia empresa
            if can_manage_own_company:
                own_comp = cls.get_company_profile(resolved_owner_uid)
                profile_data["associated_companies"].append({
                    "ownerUID": resolved_owner_uid,
                    "companyName": own_comp.get("companyName", "Mi Empresa"),
                    "role": role
                })
            
            # Si fue invitado, agregar también la empresa invitadora
            if owner_uid and owner_uid != resolved_owner_uid:
                inv_comp = cls.get_company_profile(owner_uid)
                profile_data["associated_companies"].append({
                    "ownerUID": owner_uid,
                    "companyName": inv_comp.get("companyName", "Empresa Invitadora"),
                    "role": "employee"
                })
                
            doc_ref.set(profile_data)
        
        # Guardar en team si es colaborador (alineado con la estructura iOS)
        if owner_uid:
            db_firestore.collection("users").document(owner_uid).collection("team").document(uid).set({
                "uid": uid,
                "name": name,
                "email": email,
                "role": "employee",
                "permissions": profile_data.get("permissions", {}),
                "createdAt": created_at
            })
            
        return profile_data

    @classmethod
    def authenticate_user(cls, email, password):
        """Autentica a un usuario interactuando únicamente con Firebase."""
        if not firebase_initialized:
            raise RuntimeError("El SDK de Firebase Admin no está inicializado.")

        firebase_uid = None
        user_record = None
        
        # 1. Intentar verificar credenciales con Firebase Auth REST API si está activo
        if Config.FIREBASE_API_KEY:
            res = cls.firebase_rest_auth(email, password, signup=False)
            if res:
                firebase_uid = res["localId"]
                print(f"✅ Autenticado exitosamente en Firebase Auth. UID: {firebase_uid}")
                try:
                    user_record = auth.get_user(firebase_uid)
                except Exception as e:
                    print(f"⚠️ Error al obtener UserRecord de Firebase: {e}")
        
        if not firebase_uid:
            # Si FIREBASE_API_KEY está configurado y la REST API falló, no permitir fallback.
            # Pero antes, verificar si el usuario está inhabilitado para dar el mensaje de error adecuado.
            if Config.FIREBASE_API_KEY:
                try:
                    user_record = auth.get_user_by_email(email)
                    if user_record.disabled:
                        raise ValueError("Tu cuenta está inhabilitada.")
                except ValueError:
                    raise
                except Exception:
                    pass
                return None
            else:
                # Fallback seguro para desarrollo/pruebas locales si no hay API Key de Firebase Auth completa:
                # Buscamos en Firebase Auth por el email. Si coincide la contraseña demo y no hay API Key, dejamos entrar.
                try:
                    user_record = auth.get_user_by_email(email)
                    firebase_uid = user_record.uid
                    print("⚠️ FIREBASE_API_KEY no configurado en .env. Saltando verificación de contraseña en Auth.")
                except Exception as e:
                    print(f"⚠️ Error buscando usuario por email: {e}")
                    return None

        # Verificar si la cuenta de Firebase está deshabilitada/inhabilitada
        if user_record and user_record.disabled:
            print(f"🚫 Acceso denegado: El usuario '{email}' está inhabilitado en Firebase Authentication.")
            raise ValueError("Tu cuenta está inhabilitada.")

        # 2. Descargar el perfil del usuario desde Firestore
        try:
            doc = db_firestore.collection("users").document(firebase_uid).collection("config").document("user_profile").get()
            if doc.exists:
                data = doc.to_dict()
                created_at = serialize_field(data.get("createdAt"))
                perms = data.get("permissions", {})
                
                profile = {
                    "uid": firebase_uid,
                    "ownerUID": data.get("ownerUID", firebase_uid),
                    "role": data.get("role", "owner"),
                    "name": data.get("name", ""),
                    "email": email,
                    "phone": data.get("phone", ""),
                    "address": data.get("address", ""),
                    "permissions": {
                        "canInvoice": bool(perms.get("canInvoice", True)),
                        "canExpenses": bool(perms.get("canExpenses", True)),
                        "canClients": bool(perms.get("canClients", True)),
                        "canModifySettings": bool(perms.get("canModifySettings", True)),
                        "canManageInventory": bool(perms.get("canManageInventory", True)),
                        "canManagePOS": bool(perms.get("canManagePOS", True)),
                        "canViewDashboard": bool(perms.get("canViewDashboard", True)),
                        "canManageCXC": bool(perms.get("canManageCXC", True)),
                        "canManageCXP": bool(perms.get("canManageCXP", True)),
                        "canManageContracts": bool(perms.get("canManageContracts", True)),
                        "canManageCommissions": bool(perms.get("canManageCommissions", True)),
                        "canViewBI": bool(perms.get("canViewBI", True)),
                        "canViewAuditLog": bool(perms.get("canViewAuditLog", False)),
                        "isPosSupervisor": bool(perms.get("isPosSupervisor", False)),
                        "canViewSubscription": bool(perms.get("canViewSubscription", True)),
                        "canToggleSandbox": bool(perms.get("canToggleSandbox", True)),
                        "canManageNotes": bool(perms.get("canManageNotes", True))
                    },
                    "createdAt": created_at,
                    "two_factor_enabled": bool(data.get("two_factor_enabled", False)),
                    "two_factor_secret": data.get("two_factor_secret"),
                    "backup_codes": data.get("backup_codes", []),
                    "posSupervisorPin": data.get("posSupervisorPin", ""),
                    "profileImageUrl": data.get("profileImageUrl", "")
                }
                return profile
            else:
                profile = {
                    "uid": firebase_uid,
                    "ownerUID": firebase_uid,
                    "role": "owner",
                    "name": email.split('@')[0],
                    "email": email,
                    "phone": "",
                    "address": "",
                    "permissions": {
                        "canInvoice": True,
                        "canExpenses": True,
                        "canClients": True,
                        "canModifySettings": True,
                        "canManageInventory": True,
                        "canManagePOS": True,
                        "canViewDashboard": True,
                        "canManageCXC": True,
                        "canManageCXP": True,
                        "canManageContracts": True,
                        "canManageCommissions": True,
                        "canViewBI": True,
                        "canViewAuditLog": True,
                        "isPosSupervisor": False,
                        "canViewSubscription": True,
                        "canToggleSandbox": True,
                        "canManageNotes": True
                    },
                    "createdAt": datetime.utcnow().isoformat(),
                    "two_factor_enabled": False,
                    "two_factor_secret": None,
                    "backup_codes": [],
                    "posSupervisorPin": ""
                }
                db_firestore.collection("users").document(firebase_uid).collection("config").document("user_profile").set(profile)
                return profile
        except Exception as e:
            print(f"❌ Error al recuperar perfil de Firestore en autenticación: {e}")
            return None

    @classmethod
    def get_user_profile(cls, uid):
        """Retorna el perfil del usuario."""
        if not firebase_initialized:
            return None
        try:
            # Verificar en Firebase Auth si el usuario está inhabilitado
            try:
                user_record = auth.get_user(uid)
                if user_record.disabled:
                    print(f"🚫 get_user_profile: El usuario con UID '{uid}' está inhabilitado en Firebase Auth.")
                    return None
            except Exception as e:
                print(f"⚠️ get_user_profile: Error al obtener registro de Firebase Auth para UID '{uid}': {e}")
                return None

            doc = db_firestore.collection("users").document(uid).collection("config").document("user_profile").get()
            if doc.exists:
                data = doc.to_dict()
                perms = data.get("permissions", {})
                return {
                    "uid": uid,
                    "ownerUID": data.get("ownerUID", uid),
                    "role": data.get("role", "owner"),
                    "name": data.get("name", ""),
                    "email": data.get("email", ""),
                    "phone": data.get("phone", ""),
                    "address": data.get("address", ""),
                    "permissions": {
                        "canInvoice": bool(perms.get("canInvoice", True)),
                        "canExpenses": bool(perms.get("canExpenses", True)),
                        "canClients": bool(perms.get("canClients", True)),
                        "canModifySettings": bool(perms.get("canModifySettings", True)),
                        "canManageInventory": bool(perms.get("canManageInventory", True)),
                        "canManagePOS": bool(perms.get("canManagePOS", True)),
                        "canViewDashboard": bool(perms.get("canViewDashboard", True)),
                        "canManageCXC": bool(perms.get("canManageCXC", True)),
                        "canManageCXP": bool(perms.get("canManageCXP", True)),
                        "canManageContracts": bool(perms.get("canManageContracts", True)),
                        "canManageCommissions": bool(perms.get("canManageCommissions", True)),
                        "canViewBI": bool(perms.get("canViewBI", True)),
                        "canViewAuditLog": bool(perms.get("canViewAuditLog", False)),
                        "isPosSupervisor": bool(perms.get("isPosSupervisor", False)),
                        "canViewSubscription": bool(perms.get("canViewSubscription", True)),
                        "canToggleSandbox": bool(perms.get("canToggleSandbox", True)),
                        "canManageNotes": bool(perms.get("canManageNotes", True))
                    },
                    "createdAt": serialize_field(data.get("createdAt")),
                    "two_factor_enabled": bool(data.get("two_factor_enabled", False)),
                    "two_factor_secret": data.get("two_factor_secret"),
                    "backup_codes": data.get("backup_codes", []),
                    "posSupervisorPin": data.get("posSupervisorPin", ""),
                    "profileImageUrl": data.get("profileImageUrl")
                }
        except Exception as e:
            print(f"⚠️ Error al obtener perfil desde Firestore: {e}")
        return None

    @classmethod
    def save_user_2fa_config(cls, uid, secret, enabled, backup_codes=None):
        """Actualiza la configuración de autenticación en dos pasos en Firestore."""
        if not firebase_initialized:
            return False
        try:
            data = {
                "two_factor_enabled": bool(enabled),
                "two_factor_secret": secret
            }
            if backup_codes is not None:
                data["backup_codes"] = backup_codes
            db_firestore.collection("users").document(uid).collection("config").document("user_profile").update(data)
            return True
        except Exception as e:
            print(f"⚠️ Fallo al actualizar configuración 2FA en Firestore: {e}")
            return False

    @classmethod
    def save_user_profile(cls, uid, profile_dict):
        """Actualiza el perfil del usuario en Firestore."""
        if not firebase_initialized:
            return
        try:
            perms = profile_dict.get("permissions", {})
            update_data = {
                "name": profile_dict.get("name", ""),
                "phone": profile_dict.get("phone", ""),
                "address": profile_dict.get("address", ""),
                "permissions": perms
            }
            if "profileImageUrl" in profile_dict:
                update_data["profileImageUrl"] = profile_dict["profileImageUrl"]
            
            db_firestore.collection("users").document(uid).collection("config").document("user_profile").update(update_data)
        except Exception as e:
            print(f"⚠️ Fallo al guardar perfil en Firestore: {e}")

    @classmethod
    def get_team_members(cls, owner_uid):
        """Retorna el listado de miembros del equipo del owner desde Firestore."""
        team = []
        if firebase_initialized:
            try:
                docs = db_firestore.collection("users").document(owner_uid).collection("team").get()
                for doc in docs:
                    emp_uid = doc.id
                    emp_doc = db_firestore.collection("users").document(emp_uid).collection("config").document("user_profile").get()
                    if emp_doc.exists:
                        emp_data = emp_doc.to_dict()
                        team.append({
                            "uid": emp_uid,
                            "name": emp_data.get("name", ""),
                            "email": emp_data.get("email", ""),
                            "profileImageUrl": emp_data.get("profileImageUrl", ""),
                            "permissions": {
                                "canInvoice": bool(emp_data.get("permissions", {}).get("canInvoice", True)),
                                "canExpenses": bool(emp_data.get("permissions", {}).get("canExpenses", True)),
                                "canClients": bool(emp_data.get("permissions", {}).get("canClients", True)),
                                "canModifySettings": bool(emp_data.get("permissions", {}).get("canModifySettings", True)),
                                "canManageInventory": bool(emp_data.get("permissions", {}).get("canManageInventory", True)),
                                "canManagePOS": bool(emp_data.get("permissions", {}).get("canManagePOS", True)),
                                "canViewDashboard": bool(emp_data.get("permissions", {}).get("canViewDashboard", True)),
                                "canManageCXC": bool(emp_data.get("permissions", {}).get("canManageCXC", True)),
                                "canManageCXP": bool(emp_data.get("permissions", {}).get("canManageCXP", True)),
                                "canManageContracts": bool(emp_data.get("permissions", {}).get("canManageContracts", True)),
                                "canManageCommissions": bool(emp_data.get("permissions", {}).get("canManageCommissions", True)),
                                "canViewBI": bool(emp_data.get("permissions", {}).get("canViewBI", True)),
                                "canViewAuditLog": bool(emp_data.get("permissions", {}).get("canViewAuditLog", False)),
                                "isPosSupervisor": bool(emp_data.get("permissions", {}).get("isPosSupervisor", False)),
                                "canViewSubscription": bool(emp_data.get("permissions", {}).get("canViewSubscription", True)),
                                "canToggleSandbox": bool(emp_data.get("permissions", {}).get("canToggleSandbox", True)),
                                "canManageNotes": bool(emp_data.get("permissions", {}).get("canManageNotes", True))
                            }
                        })
            except Exception as e:
                print(f"⚠️ Error al obtener miembros del equipo: {e}")
        return team

    @classmethod
    def update_employee_permissions(cls, employee_uid, permissions):
        """Actualiza los permisos granulares de un colaborador en Firestore."""
        if not firebase_initialized:
            return False
        try:
            db_firestore.collection("users").document(employee_uid).collection("config").document("user_profile").update({
                "permissions": permissions
            })
            return True
        except Exception as e:
            print(f"⚠️ Fallo al actualizar permisos del empleado: {e}")
            return False

    @classmethod
    def delete_team_member(cls, owner_uid, employee_uid):
        """Desvincula un colaborador del equipo del propietario."""
        if not firebase_initialized:
            return False
        try:
            db_firestore.collection("users").document(owner_uid).collection("team").document(employee_uid).delete()
            return True
        except Exception as e:
            print(f"⚠️ Error al eliminar colaborador del equipo: {e}")
            return False

    @classmethod
    def get_company_profile(cls, owner_uid):
        """Obtiene el perfil de empresa del owner."""
        profile = {
            "ownerUID": owner_uid,
            "companyName": "Mi Empresa SRL",
            "tradeName": "Mi Empresa",
            "companyRNC": "132109122",
            "companyType": "associated",
            "companyAddress": "Santo Domingo, RD",
            "province": "Santo Domingo",
            "municipality": "Santo Domingo de Guzmán",
            "companyPhone": "809-555-0199",
            "companyEmail": "factura@miempresa.com.do",
            "colorMarca": "#10b981",
            "gradientEnabled": True,
            "logoUrl": "",
            "logoBase64": "",
            "regimenFiscal": "General",
            "certificateName": "",
            "certificateExtension": "",
            "certificateContent": "",
            "certificatePassword": ""
        }

        if firebase_initialized:
            try:
                doc = db_firestore.collection("users").document(owner_uid).collection("config").document("profile").get()
                if doc.exists:
                    data = doc.to_dict()
                    profile.update(data)
                    # Asegurar que regimenFiscal exista
                    if "regimenFiscal" not in profile:
                        profile["regimenFiscal"] = "General"
                else:
                    cls.save_company_profile(owner_uid, profile)
            except Exception as e:
                print(f"⚠️ Error al obtener perfil de empresa desde Firestore: {e}")

        return profile

    @classmethod
    def save_company_profile(cls, owner_uid, profile_dict, upload_to_firestore=True):
        """Guarda el perfil de la empresa."""
        if firebase_initialized and upload_to_firestore:
            try:
                db_firestore.collection("users").document(owner_uid).collection("config").document("profile").set(profile_dict)
            except Exception as e:
                print(f"⚠️ Fallo al guardar perfil de empresa en Firestore: {e}")

    # =========================================================================
    # GESTIÓN DE SUCURSALES (BRANCHES)
    # =========================================================================

    @classmethod
    def get_branches(cls, owner_uid, sandbox=True):
        """Retorna la lista de sucursales del owner."""
        branches = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_branches" if sandbox else "branches"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                for doc in docs:
                    data = doc.to_dict()
                    branches.append({
                        "id": doc.id,
                        "name": data.get("name", ""),
                        "code": data.get("code", ""),
                        "address": data.get("address", ""),
                        "isDefault": bool(data.get("isDefault", False)),
                        "createdAt": serialize_field(data.get("createdAt"))
                    })
                
                # Create a default branch if it doesn't exist
                if not branches:
                    default_id = "default-sucursal-principal"
                    default_branch = {
                        "id": default_id,
                        "name": "Sucursal Principal",
                        "code": "0001",
                        "address": "Sede Principal",
                        "isDefault": True,
                        "createdAt": datetime.utcnow().isoformat()
                    }
                    cls.save_branch(owner_uid, default_id, default_branch, sandbox=sandbox, update_defaults=False)
                    branches.append(default_branch)
                else:
                    branches.sort(key=lambda x: x["name"].lower())
            except Exception as e:
                print(f"⚠️ Error al obtener sucursales desde Firestore: {e}")
        return branches

    @classmethod
    def save_branch(cls, owner_uid, branch_id, branch_dict, sandbox=True, update_defaults=True):
        """Guarda o actualiza una sucursal en Firestore."""
        branch_dict["id"] = branch_id
        branch_dict["ownerUID"] = owner_uid
        if "createdAt" not in branch_dict or not branch_dict["createdAt"]:
            branch_dict["createdAt"] = datetime.utcnow().isoformat()
        branch_dict["createdAt"] = serialize_field(branch_dict["createdAt"])

        # Si se establece como default, desmarcar las demas
        if branch_dict.get("isDefault") and update_defaults:
            branches = cls.get_branches(owner_uid, sandbox=sandbox)
            for b in branches:
                if b["id"] != branch_id and b.get("isDefault"):
                    b["isDefault"] = False
                    try:
                        coll_name = "sandbox_branches" if sandbox else "branches"
                        db_firestore.collection("users").document(owner_uid).collection(coll_name).document(b["id"]).update({"isDefault": False})
                    except Exception:
                        pass

        if firebase_initialized:
            try:
                coll_name = "sandbox_branches" if sandbox else "branches"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(branch_id).set(branch_dict)
            except Exception as e:
                print(f"⚠️ Fallo al guardar sucursal en Firestore: {e}")
        return branch_dict

    @classmethod
    def delete_branch(cls, owner_uid, branch_id, sandbox=True):
        """Elimina una sucursal en Firestore."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_branches" if sandbox else "branches"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(branch_id).delete()
            except Exception as e:
                print(f"⚠️ Fallo al borrar sucursal de Firestore: {e}")

    # =========================================================================
    # GESTIÓN DE CLIENTES
    # =========================================================================

    @classmethod
    def get_clients(cls, owner_uid, sandbox=True):
        """Retorna la lista de clientes del owner."""
        clients = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_clients" if sandbox else "clients"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                for doc in docs:
                    data = doc.to_dict()
                    client_dict = {
                        "id": doc.id,
                        "ownerUID": owner_uid,
                        "rnc": data.get("rnc", ""),
                        "razonSocial": data.get("razonSocial", ""),
                        "email": data.get("email", ""),
                        "telefono": data.get("telefono", ""),
                        "direccion": data.get("direccion", ""),
                        "crmNotes": data.get("crmNotes", ""),
                        "nextContactDate": serialize_field(data.get("nextContactDate")),
                        "pipelineStage": data.get("pipelineStage", "Prospecto"),
                        "responsibleId": data.get("responsibleId", ""),
                        "createdAt": serialize_field(data.get("createdAt")),
                        "imageUrl": data.get("imageUrl", ""),
                        "accessPin": data.get("accessPin", ""),
                        "disableAutoReminders": data.get("disableAutoReminders", False)
                    }
                    for k, v in data.items():
                        if k not in client_dict:
                            client_dict[k] = v
                    clients.append(client_dict)
                clients.sort(key=lambda x: x["razonSocial"].lower())
            except Exception as e:
                print(f"⚠️ Error al obtener clientes desde Firestore: {e}")
        return clients

    @classmethod
    def get_client(cls, owner_uid, client_id, sandbox=True):
        """Retorna un cliente específico por su ID."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_clients" if sandbox else "clients"
                doc = db_firestore.collection("users").document(owner_uid).collection(coll_name).document(client_id).get()
                if doc.exists:
                    data = doc.to_dict()
                    client_dict = {
                        "id": doc.id,
                        "ownerUID": owner_uid,
                        "rnc": data.get("rnc", ""),
                        "razonSocial": data.get("razonSocial", ""),
                        "email": data.get("email", ""),
                        "telefono": data.get("telefono", ""),
                        "direccion": data.get("direccion", ""),
                        "crmNotes": data.get("crmNotes", ""),
                        "responsibleId": data.get("responsibleId", ""),
                        "nextContactDate": data.get("nextContactDate", ""),
                        "pipelineStage": data.get("pipelineStage", "Prospecto"),
                        "createdAt": serialize_field(data.get("createdAt")),
                        "imageUrl": data.get("imageUrl", ""),
                        "accessPin": data.get("accessPin", ""),
                        "disableAutoReminders": data.get("disableAutoReminders", False)
                    }
                    for k, v in data.items():
                        if k not in client_dict:
                            client_dict[k] = v
                    return client_dict
            except Exception as e:
                print(f"⚠️ Error al obtener cliente específico desde Firestore: {e}")
        return None

    @classmethod
    def get_client_by_rnc(cls, owner_uid, rnc, sandbox=True):
        """Busca un cliente por su RNC localmente en Firestore."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_clients" if sandbox else "clients"
                clean_rnc = str(rnc).replace("-", "").strip()
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).where("rnc", "==", clean_rnc).get()
                for doc in docs:
                    data = doc.to_dict()
                    client_dict = {
                        "id": doc.id,
                        "ownerUID": owner_uid,
                        "rnc": data.get("rnc", ""),
                        "razonSocial": data.get("razonSocial", ""),
                        "email": data.get("email", ""),
                        "telefono": data.get("telefono", ""),
                        "direccion": data.get("direccion", ""),
                        "crmNotes": data.get("crmNotes", ""),
                        "responsibleId": data.get("responsibleId", ""),
                        "nextContactDate": data.get("nextContactDate", ""),
                        "pipelineStage": data.get("pipelineStage", "Prospecto"),
                        "createdAt": serialize_field(data.get("createdAt")),
                        "imageUrl": data.get("imageUrl", ""),
                        "accessPin": data.get("accessPin", ""),
                        "disableAutoReminders": data.get("disableAutoReminders", False)
                    }
                    for k, v in data.items():
                        if k not in client_dict:
                            client_dict[k] = v
                    return client_dict
                # Intentar también con guiones por si acaso
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).where("rnc", "==", rnc).get()
                for doc in docs:
                    data = doc.to_dict()
                    client_dict = {
                        "id": doc.id,
                        "ownerUID": owner_uid,
                        "rnc": data.get("rnc", ""),
                        "razonSocial": data.get("razonSocial", ""),
                        "email": data.get("email", ""),
                        "telefono": data.get("telefono", ""),
                        "direccion": data.get("direccion", ""),
                        "crmNotes": data.get("crmNotes", ""),
                        "responsibleId": data.get("responsibleId", ""),
                        "nextContactDate": data.get("nextContactDate", ""),
                        "pipelineStage": data.get("pipelineStage", "Prospecto"),
                        "createdAt": serialize_field(data.get("createdAt")),
                        "imageUrl": data.get("imageUrl", ""),
                        "accessPin": data.get("accessPin", ""),
                        "disableAutoReminders": data.get("disableAutoReminders", False)
                    }
                    for k, v in data.items():
                        if k not in client_dict:
                            client_dict[k] = v
                    return client_dict
            except Exception as e:
                print(f"⚠️ Error al obtener cliente por RNC desde Firestore: {e}")
        return None

    @classmethod
    def save_client(cls, owner_uid, client_id, client_dict, sandbox=True):
        """Guarda o actualiza un cliente en Firestore."""
        client_dict["id"] = client_id
        client_dict["ownerUID"] = owner_uid
        if "createdAt" not in client_dict or not client_dict["createdAt"]:
            client_dict["createdAt"] = datetime.utcnow().isoformat()
        
        client_dict["nextContactDate"] = serialize_field(client_dict.get("nextContactDate"))
        client_dict["createdAt"] = serialize_field(client_dict.get("createdAt"))
        client_dict["pipelineStage"] = client_dict.get("pipelineStage", "Prospecto")

        if firebase_initialized:
            try:
                coll_name = "sandbox_clients" if sandbox else "clients"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(client_id).set(client_dict)
            except Exception as e:
                print(f"⚠️ Fallo al respaldar cliente en Firestore: {e}")

        return client_dict

    @classmethod
    def update_client_pipeline(cls, owner_uid, client_id, pipeline_stage, sandbox=True):
        """Actualiza la etapa del pipeline CRM de un cliente."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_clients" if sandbox else "clients"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(client_id).update({
                    "pipelineStage": pipeline_stage, 
                    "updatedAt": firestore.SERVER_TIMESTAMP
                })
            except Exception as e:
                print(f"⚠️ Fallo al actualizar pipeline de cliente: {e}")

    @classmethod
    def delete_client(cls, owner_uid, client_id, sandbox=True):
        """Elimina un cliente en Firestore."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_clients" if sandbox else "clients"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(client_id).delete()
            except Exception as e:
                print(f"⚠️ Fallo al borrar cliente de Firestore: {e}")

    @classmethod
    def get_client_interactions(cls, owner_uid, client_id, sandbox=True):
        """Retorna la lista de comentarios e interacciones de un cliente, ordenados por fecha."""
        interactions = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_clients" if sandbox else "clients"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).document(client_id).collection("interactions").get()
                for doc in docs:
                    data = doc.to_dict()
                    interactions.append({
                        "id": doc.id,
                        "type": data.get("type", "Nota"),
                        "content": data.get("content", ""),
                        "date": serialize_field(data.get("date")),
                        "nextContactDate": serialize_field(data.get("nextContactDate")),
                        "completed": bool(data.get("completed", False)),
                        "createdBy": data.get("createdBy", ""),
                        "attachmentUrl": data.get("attachmentUrl", ""),
                        "attachmentName": data.get("attachmentName", ""),
                        "createdAt": serialize_field(data.get("createdAt"))
                    })
                # Ordenar por fecha o createdAt descendente (el más nuevo primero)
                interactions.sort(key=lambda x: x["createdAt"] or x["date"] or "", reverse=True)
            except Exception as e:
                print(f"⚠️ Error al obtener interacciones de cliente desde Firestore: {e}")
        return interactions

    @classmethod
    def save_client_interaction(cls, owner_uid, client_id, interaction_id, interaction_dict, sandbox=True):
        """Guarda una interacción y actualiza el próximo contacto del cliente principal en Firestore."""
        interaction_dict["id"] = interaction_id
        if "createdAt" not in interaction_dict or not interaction_dict["createdAt"]:
            interaction_dict["createdAt"] = datetime.utcnow().isoformat()
        
        interaction_dict["date"] = serialize_field(interaction_dict.get("date"))
        interaction_dict["nextContactDate"] = serialize_field(interaction_dict.get("nextContactDate"))
        interaction_dict["createdAt"] = serialize_field(interaction_dict.get("createdAt"))

        if firebase_initialized:
            try:
                coll_name = "sandbox_clients" if sandbox else "clients"
                # Guardar en la subcolección
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(client_id).collection("interactions").document(interaction_id).set(interaction_dict)
                
                # Si es un seguimiento programado, o si se especificó nextContactDate, actualizar la ficha principal del cliente
                if interaction_dict.get("nextContactDate") and not interaction_dict.get("completed"):
                    db_firestore.collection("users").document(owner_uid).collection(coll_name).document(client_id).update({
                        "nextContactDate": interaction_dict["nextContactDate"],
                        "crmNotes": interaction_dict.get("content", "")[:100]  # Resumen breve
                    })
            except Exception as e:
                print(f"⚠️ Fallo al respaldar interacción en Firestore: {e}")

        return interaction_dict

    @classmethod
    def delete_client_interaction(cls, owner_uid, client_id, interaction_id, sandbox=True):
        """Elimina una interacción de un cliente."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_clients" if sandbox else "clients"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(client_id).collection("interactions").document(interaction_id).delete()
            except Exception as e:
                print(f"⚠️ Fallo al borrar interacción de Firestore: {e}")

    # =========================================================================
    # GESTIÓN DE CATÁLOGO (ITEMS)
    # =========================================================================

    @classmethod
    def get_items(cls, owner_uid, sandbox=True):
        """Retorna la lista de productos del catálogo."""
        items = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_items" if sandbox else "items"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                for doc in docs:
                    data = doc.to_dict()
                    items.append({
                        "id": doc.id,
                        "code": data.get("code", ""),
                        "type": data.get("type", "Bien"),
                        "name": data.get("name", ""),
                        "price": float(data.get("price", 0.0)),
                        "costPrice": float(data.get("costPrice", 0.0)),
                        "barcode": data.get("barcode", ""),
                        "categoryId": data.get("categoryId", "general"),
                        "unit": data.get("unit", "Unidad"),
                        "itbisRate": float(data.get("itbisRate", 0.18)),
                        "minStock": float(data.get("minStock", 0.0)),
                        "rackLocation": data.get("rackLocation", ""),
                        "totalStock": float(data.get("totalStock", 0.0)),
                        "createdAt": serialize_field(data.get("createdAt")),
                        "codigoImpuesto": data.get("codigoImpuesto", ""),
                        "tasaImpuestoAdicional": float(data.get("tasaImpuestoAdicional", 0.0)),
                        "gradosAlcohol": float(data.get("gradosAlcohol", 0.0)),
                        "cantidadReferencia": float(data.get("cantidadReferencia", 0.0)),
                        "subcantidad": float(data.get("subcantidad", 1.0)),
                        "precioReferencia": float(data.get("precioReferencia", 0.0)),
                        "isActive": bool(data.get("isActive", True)),
                        "supplierName": data.get("supplierName", ""),
                        "wholesalePrice": float(data.get("wholesalePrice", 0.0)),
                        "brand": data.get("brand", ""),
                        "maxStock": float(data.get("maxStock", 0.0)),
                        "imageUrl": data.get("imageUrl", "")
                    })
                items.sort(key=lambda x: x["name"].lower())
            except Exception as e:
                print(f"⚠️ Error al obtener artículos desde Firestore: {e}")
        return items

    @classmethod
    def save_item(cls, owner_uid, item_id, item_dict, sandbox=True):
        """Guarda o actualiza un producto en el catálogo en Firestore."""
        item_dict["id"] = item_id
        item_dict["ownerUID"] = owner_uid
        if "createdAt" not in item_dict or not item_dict["createdAt"]:
            item_dict["createdAt"] = datetime.utcnow().isoformat()
        
        item_dict["price"] = float(item_dict.get("price", 0.0))
        item_dict["costPrice"] = float(item_dict.get("costPrice", 0.0))
        item_dict["barcode"] = item_dict.get("barcode", "")
        item_dict["categoryId"] = item_dict.get("categoryId", "general")
        item_dict["itbisRate"] = float(item_dict.get("itbisRate", 0.18))
        item_dict["minStock"] = float(item_dict.get("minStock", 0.0))
        item_dict["rackLocation"] = item_dict.get("rackLocation", "")
        item_dict["totalStock"] = float(item_dict.get("totalStock", 0.0))
        item_dict["createdAt"] = serialize_field(item_dict["createdAt"])
        item_dict["isActive"] = bool(item_dict.get("isActive", True))
        item_dict["supplierName"] = item_dict.get("supplierName", "")
        item_dict["wholesalePrice"] = float(item_dict.get("wholesalePrice", 0.0))
        item_dict["brand"] = item_dict.get("brand", "")
        item_dict["maxStock"] = float(item_dict.get("maxStock", 0.0))
        item_dict["imageUrl"] = item_dict.get("imageUrl", "")

        if firebase_initialized:
            try:
                coll_name = "sandbox_items" if sandbox else "items"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(item_id).set(item_dict)
            except Exception as e:
                print(f"⚠️ Fallo al respaldar producto en Firestore: {e}")

        return item_dict

    @classmethod
    def delete_item(cls, owner_uid, item_id, sandbox=True):
        """Elimina un producto del catálogo en Firestore."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_items" if sandbox else "items"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(item_id).delete()
            except Exception as e:
                print(f"⚠️ Fallo al borrar producto de Firestore: {e}")

    # =========================================================================
    # GESTIÓN DE CATEGORÍAS (CATEGORIES)
    # =========================================================================
    @classmethod
    def get_categories(cls, owner_uid, sandbox=True):
        """Retorna la lista de categorías del catálogo."""
        categories = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_categories" if sandbox else "categories"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                for doc in docs:
                    data = doc.to_dict()
                    categories.append({
                        "id": doc.id,
                        "name": data.get("name", ""),
                        "createdAt": serialize_field(data.get("createdAt"))
                    })
                
                # Sembrar categorías por defecto si está vacío
                if not categories:
                    defaults = [
                        {"id": "general", "name": "General"},
                        {"id": "alimentos", "name": "Alimentos y Bebidas"},
                        {"id": "electronica", "name": "Electrónica"},
                        {"id": "servicios", "name": "Servicios"},
                        {"id": "ferreteria", "name": "Ferretería"},
                        {"id": "otros", "name": "Otros"}
                    ]
                    for cat in defaults:
                        cat["createdAt"] = datetime.utcnow().isoformat()
                        cls.save_category(owner_uid, cat["id"], cat, sandbox=sandbox)
                        categories.append(cat)
                
                categories.sort(key=lambda x: x["name"].lower())
            except Exception as e:
                print(f"⚠️ Error al obtener categorías desde Firestore: {e}")
        return categories

    @classmethod
    def save_category(cls, owner_uid, category_id, category_dict, sandbox=True):
        """Guarda o actualiza una categoría en Firestore."""
        category_dict["id"] = category_id
        category_dict["ownerUID"] = owner_uid
        if "createdAt" not in category_dict or not category_dict["createdAt"]:
            category_dict["createdAt"] = datetime.utcnow().isoformat()
        category_dict["createdAt"] = serialize_field(category_dict["createdAt"])

        if firebase_initialized:
            try:
                coll_name = "sandbox_categories" if sandbox else "categories"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(category_id).set(category_dict)
            except Exception as e:
                print(f"⚠️ Fallo al guardar categoría en Firestore: {e}")
        return category_dict

    @classmethod
    def get_or_create_category_by_name(cls, owner_uid, name, sandbox=True):
        """Busca una categoría por nombre (insensible a mayúsculas/minúsculas). Si no existe, la crea."""
        name_clean = name.strip()
        if not name_clean:
            return "general"
            
        categories = cls.get_categories(owner_uid, sandbox=sandbox)
        
        # Buscar coincidencia exacta insensible a mayúsculas
        for cat in categories:
            if cat["name"].lower() == name_clean.lower():
                return cat["id"]
                
        # Si no existe, crearla
        import unicodedata
        import re
        slug = unicodedata.normalize('NFKD', name_clean).encode('ascii', 'ignore').decode('ascii')
        slug = re.sub(r'[^\w\s-]', '', slug).strip().lower()
        slug = re.sub(r'[-\s]+', '-', slug)
        if not slug:
            slug = str(uuid.uuid4())[:8]
            
        existing_ids = {cat["id"] for cat in categories}
        if slug in existing_ids:
            slug = f"{slug}-{uuid.uuid4().hex[:4]}"
            
        new_cat = {
            "id": slug,
            "name": name_clean,
            "createdAt": datetime.utcnow().isoformat()
        }
        cls.save_category(owner_uid, slug, new_cat, sandbox=sandbox)
        return slug

    # =========================================================================
    # GESTIÓN DE SECUENCIAS FISCALES
    # =========================================================================

    @classmethod
    def get_sequences(cls, owner_uid, sandbox=True):
        """Retorna las secuencias fiscales del owner."""
        seqs = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_sequences" if sandbox else "sequences"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                for doc in docs:
                    data = doc.to_dict()
                    secuenciaInicial = int(data.get("secuenciaInicial", 1))
                    secuenciaFinal = int(data.get("secuenciaFinal", 1))
                    ultimoConsecutivoUsado = int(data.get("ultimoConsecutivoUsado", secuenciaInicial - 1))
                    
                    seqs.append({
                        "id": doc.id,
                        "tipoComprobante": data.get("tipoComprobante", ""),
                        "prefijo": data.get("prefijo", data.get("tipoComprobante", "")),
                        "secuenciaInicial": secuenciaInicial,
                        "secuenciaFinal": secuenciaFinal,
                        "ultimoConsecutivoUsado": ultimoConsecutivoUsado,
                        "alertaMinimoDisponible": int(data.get("alertaMinimoDisponible", 100)),
                        "fechaAutorizacion": data.get("fechaAutorizacion", ""),
                        "fechaExpiracion": data.get("fechaExpiracion", ""),
                        "numeroAutorizacionDgii": data.get("numeroAutorizacionDgii", ""),
                        "estado": data.get("estado", "ACTIVA"),
                        "ambiente": data.get("ambiente", "SANDBOX"),
                        "bloqueadaManualmente": bool(data.get("bloqueadaManualmente", False)),
                        "creadoEn": serialize_field(data.get("creadoEn")),
                        "cantidadDisponible": max(0, secuenciaFinal - ultimoConsecutivoUsado),
                        "porcentajeUsado": min(1.0, max(0.0, (ultimoConsecutivoUsado - secuenciaInicial + 1) / max(1.0, float(secuenciaFinal - secuenciaInicial + 1))))
                    })
                seqs.sort(key=lambda x: x["tipoComprobante"])
            except Exception as e:
                print(f"⚠️ Error al obtener secuencias desde Firestore: {e}")
        return seqs

    @classmethod
    def save_sequence(cls, owner_uid, seq_id, seq_dict, sandbox=True):
        """Guarda o actualiza una secuencia fiscal."""
        seq_dict["id"] = seq_id
        seq_dict["ownerUID"] = owner_uid
        if "creadoEn" not in seq_dict or not seq_dict["creadoEn"]:
            seq_dict["creadoEn"] = datetime.utcnow().isoformat()
        
        seq_dict["secuenciaInicial"] = int(seq_dict["secuenciaInicial"])
        seq_dict["secuenciaFinal"] = int(seq_dict["secuenciaFinal"])
        seq_dict["ultimoConsecutivoUsado"] = int(seq_dict.get("ultimoConsecutivoUsado", seq_dict["secuenciaInicial"] - 1))
        seq_dict["alertaMinimoDisponible"] = int(seq_dict.get("alertaMinimoDisponible", 100))
        seq_dict["bloqueadaManualmente"] = bool(seq_dict.get("bloqueadaManualmente", False))
        seq_dict["creadoEn"] = serialize_field(seq_dict["creadoEn"])

        if firebase_initialized:
            try:
                coll_name = "sandbox_sequences" if sandbox else "sequences"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(seq_id).set(seq_dict)
            except Exception as e:
                print(f"⚠️ Fallo al respaldar secuencia en Firestore: {e}")
        return seq_dict

    @classmethod
    def consume_next_sequence(cls, owner_uid, tipo_comprobante, usuario_email, sandbox=True):
        """
        Bloquea y consume el siguiente consecutivo de una secuencia fiscal en Firestore.
        Garantiza consistencia mutua usando transacciones nativas de Firestore.
        """
        if not firebase_initialized:
            raise RuntimeError("El SDK de Firebase Admin no está inicializado.")

        coll_seq = "sandbox_sequences" if sandbox else "sequences"
        coll_log = "sandbox_sequence_logs" if sandbox else "sequence_logs"

        transaction = db_firestore.transaction()

        @firestore.transactional
        def run_in_transaction(transaction):
            seq_ref_query = db_firestore.collection("users").document(owner_uid).collection(coll_seq)\
                .where(filter=firestore.FieldFilter("tipoComprobante", "==", tipo_comprobante))\
                .where(filter=firestore.FieldFilter("estado", "==", "ACTIVA"))\
                .where(filter=firestore.FieldFilter("bloqueadaManualmente", "==", False))\
                .limit(1)
            
            seq_docs = seq_ref_query.get(transaction=transaction)
            if not seq_docs:
                raise ValueError(f"No hay una secuencia fiscal ACTIVA autorizada por la DGII para {tipo_comprobante}.")
            
            seq_doc = seq_docs[0]
            seq_data = seq_doc.to_dict()
            seq_id = seq_doc.id

            secuenciaInicial = int(seq_data.get("secuenciaInicial", 1))
            secuenciaFinal = int(seq_data.get("secuenciaFinal", 1))
            ultimoConsecutivoUsado = int(seq_data.get("ultimoConsecutivoUsado", secuenciaInicial - 1))

            next_consecutivo = ultimoConsecutivoUsado + 1
            if next_consecutivo > secuenciaFinal:
                transaction.update(db_firestore.collection("users").document(owner_uid).collection(coll_seq).document(seq_id), {
                    "estado": "AGOTADA"
                })
                raise ValueError(f"La secuencia fiscal autorizada para {tipo_comprobante} se ha AGOTADO.")

            encf = f"{tipo_comprobante}{next_consecutivo:010d}"

            status = "ACTIVA"
            if next_consecutivo >= secuenciaFinal:
                status = "AGOTADA"
            
            transaction.update(db_firestore.collection("users").document(owner_uid).collection(coll_seq).document(seq_id), {
                "ultimoConsecutivoUsado": next_consecutivo,
                "estado": status
            })

            log_id = str(uuid.uuid4())
            fecha_registro = datetime.utcnow().isoformat()
            
            log_data = {
                "id": log_id,
                "encf": encf,
                "tipoComprobante": tipo_comprobante,
                "consecutivo": next_consecutivo,
                "idSecuenciaOrigen": seq_id,
                "estado": "GENERATED",
                "motivo": "Emisión automatizada",
                "fechaRegistro": fecha_registro,
                "usuario": usuario_email,
                "ambiente": "SANDBOX" if sandbox else "PRODUCCION",
                "xmlEnviado": "",
                "respuestaDGII": "",
                "duracionTransaccionMs": 0
            }
            
            transaction.set(db_firestore.collection("users").document(owner_uid).collection(coll_log).document(log_id), log_data)
            
            return encf, log_id

        try:
            encf, log_id = run_in_transaction(transaction)
            return encf, log_id
        except Exception as e:
            if isinstance(e, ValueError):
                raise e
            raise RuntimeError(f"Error al consumir secuencia en Firestore: {e}")

    @classmethod
    def update_sequence_log(cls, owner_uid, log_id, updates, sandbox=True):
        """Actualiza un log de secuencia específico en Firestore."""
        if firebase_initialized:
            try:
                coll_log = "sandbox_sequence_logs" if sandbox else "sequence_logs"
                db_firestore.collection("users").document(owner_uid).collection(coll_log).document(log_id).update(updates)
            except Exception as e:
                print(f"⚠️ Error al actualizar log de secuencia: {e}")

    @classmethod
    def get_sequence_logs(cls, owner_uid, sandbox=True):
        """Retorna el registro histórico inmutable de consecutivos consumidos desde Firestore."""
        logs = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_sequence_logs" if sandbox else "sequence_logs"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                for doc in docs:
                    data = doc.to_dict()
                    logs.append({
                        "id": doc.id,
                        "encf": data.get("encf", ""),
                        "tipoComprobante": data.get("tipoComprobante", ""),
                        "consecutivo": int(data.get("consecutivo", 0)),
                        "idSecuenciaOrigen": data.get("idSecuenciaOrigen", ""),
                        "estado": data.get("estado", "GENERATED"),
                        "motivo": data.get("motivo", ""),
                        "fechaRegistro": serialize_field(data.get("fechaRegistro")),
                        "usuario": data.get("usuario", ""),
                        "ambiente": data.get("ambiente", ""),
                        "xmlEnviado": data.get("xmlEnviado", ""),
                        "respuestaDGII": data.get("respuestaDGII", ""),
                        "duracionTransaccionMs": int(data.get("duracionTransaccionMs", 0))
                    })
                logs.sort(key=lambda x: x["fechaRegistro"] or "", reverse=True)
            except Exception as e:
                print(f"⚠️ Error al obtener logs de secuencias de Firestore: {e}")
        return logs

    @classmethod
    def get_cancellations(cls, owner_uid, sandbox=True):
        """Retorna el listado de rangos anulados desde Firestore."""
        cancs = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_cancellations" if sandbox else "cancellations"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                for doc in docs:
                    data = doc.to_dict()
                    cancs.append({
                        "id": doc.id,
                        "idCompany": data.get("idCompany", ""),
                        "series": data.get("series", ""),
                        "startSequence": int(data.get("startSequence", 0)),
                        "endSequence": int(data.get("endSequence", 0)),
                        "reason": data.get("reason", ""),
                        "status": data.get("status", "Borrador"),
                        "date": serialize_field(data.get("date")),
                        "responseMessage": data.get("responseMessage", ""),
                        "cancellationCode": data.get("cancellationCode", "")
                    })
                cancs.sort(key=lambda x: x["date"] or "", reverse=True)
            except Exception as e:
                print(f"⚠️ Error al obtener anulaciones desde Firestore: {e}")
        return cancs

    @classmethod
    def save_cancellation(cls, owner_uid, cancellation_id, canc_dict, sandbox=True):
        """Registra una anulación en Firestore."""
        canc_dict["id"] = cancellation_id
        canc_dict["ownerUID"] = owner_uid
        if "date" not in canc_dict or not canc_dict["date"]:
            canc_dict["date"] = datetime.utcnow().isoformat()
        
        canc_dict["startSequence"] = int(canc_dict["startSequence"])
        canc_dict["endSequence"] = int(canc_dict["endSequence"])
        canc_dict["date"] = serialize_field(canc_dict["date"])

        if firebase_initialized:
            try:
                coll_name = "sandbox_cancellations" if sandbox else "cancellations"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(cancellation_id).set(canc_dict)
            except Exception as e:
                print(f"⚠️ Fallo al respaldar anulación en Firestore: {e}")
        return canc_dict

    # =========================================================================
    # GESTIÓN DE FACTURAS (INVOICES)
    # =========================================================================

    @classmethod
    def get_invoices(cls, owner_uid, sandbox=True, quotations_only=False, include_all=False):
        """Retorna las facturas o cotizaciones de un owner."""
        invoices = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_invoices" if sandbox else "invoices"
                coll_ref = db_firestore.collection("users").document(owner_uid).collection(coll_name)
                if include_all:
                    docs = coll_ref.get()
                else:
                    docs = coll_ref.where(filter=firestore.FieldFilter("isQuotation", "==", quotations_only)).get()
                
                for doc in docs:
                    data = doc.to_dict()
                    
                    # Cargar partidas
                    items = []
                    for it in data.get("items", []):
                        items.append({
                            "id": it.get("id", ""),
                            "code": it.get("code", ""),
                            "type": it.get("type", "Bien"),
                            "name": it.get("name", ""),
                            "price": float(it.get("price", 0.0)),
                            "quantity": int(it.get("quantity", 1)),
                            "itbisRate": float(it.get("itbisRate", 0.18)),
                            "discountRate": float(it.get("discountRate", 0.0)),
                            "subtotal": float(it.get("subtotal", 0.0)),
                            "itbisAmount": float(it.get("itbisAmount", it.get("itbis_amount", 0.0))),
                            "total": float(it.get("total", 0.0)),
                            "codigoImpuesto": it.get("codigoImpuesto", ""),
                            "tasaImpuestoAdicional": float(it.get("tasaImpuestoAdicional", 0.0)),
                            "gradosAlcohol": float(it.get("gradosAlcohol", 0.0)),
                            "cantidadReferencia": float(it.get("cantidadReferencia", 0.0)),
                            "subcantidad": float(it.get("subcantidad", 1.0)),
                            "precioReferencia": float(it.get("precioReferencia", 0.0)),
                            "isc_especifico_amount": float(it.get("isc_especifico_amount", it.get("iscEspecificoAmount", 0.0))),
                            "isc_advalorem_amount": float(it.get("isc_advalorem_amount", it.get("iscAdValoremAmount", 0.0))),
                            "otros_impuestos_amount": float(it.get("otros_impuestos_amount", it.get("otrosImpuestosAmount", 0.0)))
                        })

                    # Cargar acuerdo y cuotas con retrocompatibilidad
                    agreement = data.get("paymentAgreement") or {
                        "enabled": False,
                        "installmentsCount": 1,
                        "frequency": "mensual",
                        "lateFeePercentage": 5.0
                    }
                    
                    net_payable = float(data.get("netPayable", 0.0))
                    status = data.get("status", "Borrador")
                    
                    # Evaluar vencimiento de facturas
                    due_date_str = serialize_field(data.get("dueDate"))
                    if status in ["Emitida", "Parcialmente Cobrada"] and due_date_str:
                        due_date_clean = due_date_str[:10]
                        today_str = datetime.utcnow().strftime("%Y-%m-%d")
                        if due_date_clean < today_str:
                            status = "Vencida"
                            
                    total_paid = float(data.get("totalPaid", data.get("netPayable", 0.0) if status == "Cobrada" else 0.0))
                    remaining_balance = float(data.get("remainingBalance", 0.0 if status == "Cobrada" else data.get("netPayable", 0.0)))
                    
                    installments = data.get("installments")
                    if not installments:
                        # Generar cuota única retrocompatible
                        installments = [{
                            "id": "cuota-unica-default",
                            "installmentNumber": 1,
                            "amount": net_payable,
                            "dueDate": serialize_field(data.get("dueDate")),
                            "status": "Saldada" if status == "Cobrada" else "Pendiente",
                            "paidAmount": total_paid,
                            "remainingBalance": remaining_balance
                        }]
                    else:
                        # Asegurar tipos correctos
                        formatted_installments = []
                        for inst in installments:
                            formatted_installments.append({
                                "id": inst.get("id", str(uuid.uuid4())),
                                "installmentNumber": int(inst.get("installmentNumber", 1)),
                                "amount": float(inst.get("amount", 0.0)),
                                "dueDate": serialize_field(inst.get("dueDate")),
                                "status": inst.get("status", "Pendiente"),
                                "paidAmount": float(inst.get("paidAmount", 0.0)),
                                "remainingBalance": float(inst.get("remainingBalance", 0.0))
                            })
                        installments = formatted_installments

                    invoices.append({
                        "id": doc.id,
                        "invoiceNumber": data.get("invoiceNumber", ""),
                        "date": serialize_field(data.get("date")),
                        "dueDate": serialize_field(data.get("dueDate")),
                        "clientId": data.get("clientId", ""),
                        "clientName": data.get("clientName", ""),
                        "clientRNC": data.get("clientRNC", ""),
                        "status": data.get("status", "Borrador"),
                        "ecfType": data.get("ecfType", "Factura de Consumo (E32)"),
                        "encf": data.get("encf", ""),
                        "xmlSignature": data.get("xmlSignature", ""),
                        "qrCodeURL": data.get("qrCodeURL", ""),
                        "isSyncedWithDGII": bool(data.get("isSyncedWithDGII", False)),
                        "emisionMode": data.get("emisionMode", ""),
                        "contingencyEmittedAt": serialize_field(data.get("contingencyEmittedAt")),
                        "creditedAmount": float(data.get("creditedAmount", 0.0)),
                        "retainedISR": float(data.get("retainedISR", 0.0)),
                        "retainedITBIS": float(data.get("retainedITBIS", 0.0)),
                        "netPayable": net_payable,
                        "subtotal": float(data.get("subtotal", 0.0)),
                        "totalITBIS": float(data.get("totalITBIS", 0.0)),
                        "total": float(data.get("total", 0.0)),
                        "isQuotation": bool(data.get("isQuotation", False)),
                        "isConvertedToInvoice": bool(data.get("isConvertedToInvoice", False)),
                        "notes": data.get("notes", ""),
                        "comentario": data.get("comentario", ""),
                        "isRecurring": bool(data.get("isRecurring", False)),
                        "recurrenceInterval": data.get("recurrenceInterval", "mensual"),
                        "nextOccurrenceDate": serialize_field(data.get("nextOccurrenceDate")),
                        "firebasePDFURL": data.get("firebasePDFURL", ""),
                        "firebaseXMLURL": data.get("firebaseXMLURL", ""),
                        "currency": data.get("currency", "DOP"),
                        "paymentType": data.get("paymentType", "Contado"),
                        "paymentMethod": data.get("paymentMethod", "Efectivo"),
                        "incomeType": data.get("incomeType", "01 - Ingresos por operaciones"),
                        "customFields": data.get("customFields", []),
                        "exchangeRate": float(data.get("exchangeRate", 1.0)),
                        "bank": data.get("bank", ""),
                        "referenceNumber": data.get("referenceNumber", ""),
                        "paymentDate": serialize_field(data.get("paymentDate")),
                        "totalPaid": total_paid,
                        "remainingBalance": remaining_balance,
                        "paymentAgreement": agreement,
                        "installments": installments,
                        "branchId": data.get("branchId", "default-sucursal-principal"),
                        "createdAt": serialize_field(data.get("createdAt")),
                        "items": items,
                        "pendingPaymentProof": data.get("pendingPaymentProof")
                    })
                invoices.sort(key=lambda x: x["date"] or "", reverse=True)
            except Exception as e:
                print(f"⚠️ Error al obtener facturas desde Firestore: {e}")
        return invoices

    @classmethod
    def get_invoice(cls, owner_uid, invoice_id, sandbox=True):
        """Retorna una única factura por ID desde Firestore."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_invoices" if sandbox else "invoices"
                doc = db_firestore.collection("users").document(owner_uid).collection(coll_name).document(invoice_id).get()
                if doc.exists:
                    data = doc.to_dict()
                    
                    items = []
                    for it in data.get("items", []):
                        items.append({
                            "id": it.get("id", ""),
                            "code": it.get("code", ""),
                            "type": it.get("type", "Bien"),
                            "name": it.get("name", ""),
                            "price": float(it.get("price", 0.0)),
                            "quantity": int(it.get("quantity", 1)),
                            "itbisRate": float(it.get("itbisRate", 0.18)),
                            "discountRate": float(it.get("discountRate", 0.0)),
                            "subtotal": float(it.get("subtotal", 0.0)),
                            "itbisAmount": float(it.get("itbisAmount", it.get("itbis_amount", 0.0))),
                            "total": float(it.get("total", 0.0)),
                            "codigoImpuesto": it.get("codigoImpuesto", ""),
                            "tasaImpuestoAdicional": float(it.get("tasaImpuestoAdicional", 0.0)),
                            "gradosAlcohol": float(it.get("gradosAlcohol", 0.0)),
                            "cantidadReferencia": float(it.get("cantidadReferencia", 0.0)),
                            "subcantidad": float(it.get("subcantidad", 1.0)),
                            "precioReferencia": float(it.get("precioReferencia", 0.0)),
                            "isc_especifico_amount": float(it.get("isc_especifico_amount", it.get("iscEspecificoAmount", 0.0))),
                            "isc_advalorem_amount": float(it.get("isc_advalorem_amount", it.get("iscAdValoremAmount", 0.0))),
                            "otros_impuestos_amount": float(it.get("otros_impuestos_amount", it.get("otrosImpuestosAmount", 0.0)))
                        })


                    # Cargar acuerdo y cuotas con retrocompatibilidad
                    agreement = data.get("paymentAgreement") or {
                        "enabled": False,
                        "installmentsCount": 1,
                        "frequency": "mensual",
                        "lateFeePercentage": 5.0
                    }
                    
                    net_payable = float(data.get("netPayable", 0.0))
                    status = data.get("status", "Borrador")
                    
                    # Evaluar vencimiento de facturas
                    due_date_str = serialize_field(data.get("dueDate"))
                    if status in ["Emitida", "Parcialmente Cobrada"] and due_date_str:
                        due_date_clean = due_date_str[:10]
                        today_str = datetime.utcnow().strftime("%Y-%m-%d")
                        if due_date_clean < today_str:
                            status = "Vencida"
                            
                    total_paid = float(data.get("totalPaid", data.get("netPayable", 0.0) if status == "Cobrada" else 0.0))
                    remaining_balance = float(data.get("remainingBalance", 0.0 if status == "Cobrada" else data.get("netPayable", 0.0)))
                    
                    installments = data.get("installments")
                    if not installments:
                        # Generar cuota única retrocompatible
                        installments = [{
                            "id": "cuota-unica-default",
                            "installmentNumber": 1,
                            "amount": net_payable,
                            "dueDate": serialize_field(data.get("dueDate")),
                            "status": "Saldada" if status == "Cobrada" else "Pendiente",
                            "paidAmount": total_paid,
                            "remainingBalance": remaining_balance
                        }]
                    else:
                        # Asegurar tipos correctos
                        formatted_installments = []
                        for inst in installments:
                            formatted_installments.append({
                                "id": inst.get("id", str(uuid.uuid4())),
                                "installmentNumber": int(inst.get("installmentNumber", 1)),
                                "amount": float(inst.get("amount", 0.0)),
                                "dueDate": serialize_field(inst.get("dueDate")),
                                "status": inst.get("status", "Pendiente"),
                                "paidAmount": float(inst.get("paidAmount", 0.0)),
                                "remainingBalance": float(inst.get("remainingBalance", 0.0))
                            })
                        installments = formatted_installments

                    return {
                        "id": doc.id,
                        "invoiceNumber": data.get("invoiceNumber", ""),
                        "date": serialize_field(data.get("date")),
                        "dueDate": serialize_field(data.get("dueDate")),
                        "clientId": data.get("clientId", ""),
                        "clientName": data.get("clientName", ""),
                        "clientRNC": data.get("clientRNC", ""),
                        "status": data.get("status", "Borrador"),
                        "ecfType": data.get("ecfType", "Factura de Consumo (E32)"),
                        "encf": data.get("encf", ""),
                        "xmlSignature": data.get("xmlSignature", ""),
                        "qrCodeURL": data.get("qrCodeURL", ""),
                        "isSyncedWithDGII": bool(data.get("isSyncedWithDGII", False)),
                        "emisionMode": data.get("emisionMode", ""),
                        "contingencyEmittedAt": serialize_field(data.get("contingencyEmittedAt")),
                        "creditedAmount": float(data.get("creditedAmount", 0.0)),
                        "retainedISR": float(data.get("retainedISR", 0.0)),
                        "retainedITBIS": float(data.get("retainedITBIS", 0.0)),
                        "netPayable": net_payable,
                        "subtotal": float(data.get("subtotal", 0.0)),
                        "totalITBIS": float(data.get("totalITBIS", 0.0)),
                        "total": float(data.get("total", 0.0)),
                        "isQuotation": bool(data.get("isQuotation", False)),
                        "isConvertedToInvoice": bool(data.get("isConvertedToInvoice", False)),
                        "notes": data.get("notes", ""),
                        "comentario": data.get("comentario", ""),
                        "isRecurring": bool(data.get("isRecurring", False)),
                        "recurrenceInterval": data.get("recurrenceInterval", "mensual"),
                        "nextOccurrenceDate": serialize_field(data.get("nextOccurrenceDate")),
                        "firebasePDFURL": data.get("firebasePDFURL", ""),
                        "firebaseXMLURL": data.get("firebaseXMLURL", ""),
                        "currency": data.get("currency", "DOP"),
                        "paymentType": data.get("paymentType", "Contado"),
                        "paymentMethod": data.get("paymentMethod", "Efectivo"),
                        "incomeType": data.get("incomeType", "01 - Ingresos por operaciones"),
                        "customFields": data.get("customFields", []),
                        "exchangeRate": float(data.get("exchangeRate", 1.0)),
                        "bank": data.get("bank", ""),
                        "referenceNumber": data.get("referenceNumber", ""),
                        "paymentDate": serialize_field(data.get("paymentDate")),
                        "totalPaid": total_paid,
                        "remainingBalance": remaining_balance,
                        "paymentAgreement": agreement,
                        "installments": installments,
                        "branchId": data.get("branchId", "default-sucursal-principal"),
                        "createdAt": serialize_field(data.get("createdAt")),
                        "items": items,
                        "pendingPaymentProof": data.get("pendingPaymentProof")
                    }
            except Exception as e:
                print(f"⚠️ Error al obtener factura por ID desde Firestore: {e}")
    @classmethod
    def search_invoices_by_number(cls, owner_uid, search_term, sandbox=True, limit=15):
        """Busca facturas específicas por prefijo de número de factura o cliente sin requerir índices complejos."""
        results = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_invoices" if sandbox else "invoices"
                coll_ref = db_firestore.collection("users").document(owner_uid).collection(coll_name)
                
                search_term = search_term.strip()
                if search_term:
                    docs = coll_ref.order_by("invoiceNumber").start_at({"invoiceNumber": search_term}).end_at({"invoiceNumber": search_term + "\uf8ff"}).limit(limit).get()
                    for doc in docs:
                        data = doc.to_dict()
                        if not data.get("isQuotation"):
                            results.append({
                                "id": doc.id,
                                "invoiceNumber": data.get("invoiceNumber", ""),
                                "clientName": data.get("clientName", ""),
                                "total": float(data.get("total", 0.0))
                            })
                            
                    if len(results) < limit:
                        docs2 = coll_ref.order_by("clientName").start_at({"clientName": search_term}).end_at({"clientName": search_term + "\uf8ff"}).limit(limit - len(results)).get()
                        for doc in docs2:
                            data = doc.to_dict()
                            if not data.get("isQuotation") and doc.id not in [r["id"] for r in results]:
                                results.append({
                                    "id": doc.id,
                                    "invoiceNumber": data.get("invoiceNumber", ""),
                                    "clientName": data.get("clientName", ""),
                                    "total": float(data.get("total", 0.0))
                                })
            except Exception as e:
                print(f"⚠️ Error al buscar facturas por número en Firestore: {e}")
        return results

    @classmethod
    def update_invoice_status_simple(cls, owner_uid, invoice_id, new_status, sandbox=True):
        """Actualiza únicamente el estado de una factura (usado en Kanban de Cotizaciones)."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_invoices" if sandbox else "invoices"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(invoice_id).update({"status": new_status, "updatedAt": firestore.SERVER_TIMESTAMP})
            except Exception as e:
                print(f"⚠️ Fallo al actualizar estado de la factura/cotización: {e}")

    @classmethod
    def save_invoice(cls, owner_uid, invoice_id, inv_dict, sandbox=True):
        """Guarda o actualiza una factura y sus partidas en Firestore."""
        inv_dict["id"] = invoice_id
        inv_dict["ownerUID"] = owner_uid
        
        if "createdAt" not in inv_dict or not inv_dict["createdAt"]:
            inv_dict["createdAt"] = datetime.utcnow().isoformat()
            
        items = inv_dict.get("items", [])
        
        fs_items = []
        for item in items:
            fs_items.append({
                "id": item.get("id") or str(uuid.uuid4()),
                "code": item.get("code", ""),
                "type": item.get("type", "Bien"),
                "name": item["name"],
                "price": float(item["price"]),
                "quantity": int(item["quantity"]),
                "itbisRate": float(item.get("itbisRate", 0.18)),
                "discountRate": float(item.get("discountRate", 0.0)),
                "subtotal": float(item["subtotal"]),
                "itbisAmount": float(item.get("itbisAmount", item.get("itbis_amount", 0.0))),
                "total": float(item["total"]),
                "codigoImpuesto": item.get("codigoImpuesto", ""),
                "tasaImpuestoAdicional": float(item.get("tasaImpuestoAdicional", 0.0)),
                "gradosAlcohol": float(item.get("gradosAlcohol", 0.0)),
                "cantidadReferencia": float(item.get("cantidadReferencia", 0.0)),
                "subcantidad": float(item.get("subcantidad", 1.0)),
                "precioReferencia": float(item.get("precioReferencia", 0.0)),
                "isc_especifico_amount": float(item.get("isc_especifico_amount", item.get("iscEspecificoAmount", 0.0))),
                "isc_advalorem_amount": float(item.get("isc_advalorem_amount", item.get("iscAdValoremAmount", 0.0))),
                "otros_impuestos_amount": float(item.get("otros_impuestos_amount", item.get("otrosImpuestosAmount", 0.0)))
            })
        
        inv_dict["items"] = fs_items
        inv_dict["date"] = serialize_field(inv_dict["date"])
        inv_dict["dueDate"] = serialize_field(inv_dict["dueDate"])
        inv_dict["nextOccurrenceDate"] = serialize_field(inv_dict.get("nextOccurrenceDate"))
        inv_dict["createdAt"] = serialize_field(inv_dict["createdAt"])

        # Descontar inventario automáticamente si la factura está en estado final y no ha sido descontada aún
        status = inv_dict.get("status", "Borrador")
        is_quotation = inv_dict.get("isQuotation", False)
        
        if not is_quotation and status in ["Emitida", "Cobrada", "Pagada", "Vencida"] and not inv_dict.get("stockReduced"):
            wh_id = inv_dict.get("warehouseId")
            if not wh_id:
                whs = cls.get_warehouses(owner_uid, sandbox=sandbox)
                wh_id = whs[0]["id"] if whs else "default-almacen-principal"
                inv_dict["warehouseId"] = wh_id
            
            for it in fs_items:
                if it.get("type", "Bien") == "Bien" and it.get("id"):
                    # Verificar que el item existe en el catálogo para descontar su stock
                    items_catalog = cls.get_items(owner_uid, sandbox=sandbox)
                    catalog_ids = {cit["id"] for cit in items_catalog}
                    if it["id"] in catalog_ids:
                        tx_dict = {
                            "itemId": it["id"],
                            "itemName": it["name"],
                            "type": "SALIDA",
                            "quantity": float(it["quantity"]),
                            "reason": "VENTA",
                            "referenceId": inv_dict.get("invoiceNumber") or invoice_id,
                            "originWarehouseId": wh_id,
                            "destinationWarehouseId": "",
                            "notes": f"Venta en Factura {inv_dict.get('invoiceNumber')}",
                            "performedBy": "Sistema e-Factura"
                        }
                        cls.register_inventory_transaction(owner_uid, tx_dict, sandbox=sandbox)
            
            inv_dict["stockReduced"] = True

        elif status == "Anulada":
            if inv_dict.get("stockReduced") and not inv_dict.get("stockReverted"):
                wh_id = inv_dict.get("warehouseId")
                if not wh_id:
                    whs = cls.get_warehouses(owner_uid, sandbox=sandbox)
                    wh_id = whs[0]["id"] if whs else "default-almacen-principal"
                    inv_dict["warehouseId"] = wh_id
                    
                for it in fs_items:
                    if it.get("type", "Bien") == "Bien" and it.get("id"):
                        items_catalog = cls.get_items(owner_uid, sandbox=sandbox)
                        catalog_ids = {cit["id"] for cit in items_catalog}
                        if it["id"] in catalog_ids:
                            tx_dict = {
                                "itemId": it["id"],
                                "itemName": it["name"],
                                "type": "ENTRADA",
                                "quantity": float(it["quantity"]),
                                "reason": "AJUSTE",
                                "referenceId": inv_dict.get("invoiceNumber") or invoice_id,
                                "originWarehouseId": "",
                                "destinationWarehouseId": wh_id,
                                "notes": f"Reversión de Venta (Anulación de Factura {inv_dict.get('invoiceNumber')})",
                                "performedBy": "Sistema e-Factura (Automático)"
                            }
                            cls.register_inventory_transaction(owner_uid, tx_dict, sandbox=sandbox)
                            
                inv_dict["stockReverted"] = True

            # Anular siempre la transacción de caja asociada si existe en el turno actual (independiente del stock de productos)
            if firebase_initialized:
                try:
                    coll_txs = "sandbox_cash_transactions" if sandbox else "cash_transactions"
                    txs_ref = db_firestore.collection("users").document(owner_uid).collection(coll_txs)\
                        .where(filter=firestore.FieldFilter("referenceId", "==", invoice_id)).get()
                    for doc in txs_ref:
                        t_data = doc.to_dict()
                        notes = t_data.get("notes", "")
                        if not notes.startswith("[ANULADA]"):
                            notes = f"[ANULADA] {notes}"
                        doc.reference.update({
                            "status": "VOIDED",
                            "notes": notes
                        })
                except Exception as e:
                    print(f"⚠️ Error al marcar como anulada la transacción de caja asociada: {e}")

        if not is_quotation and status in ["Emitida", "Cobrada", "Pagada", "Vencida"]:
            client_id = inv_dict.get("clientId")
            if client_id:
                try:
                    client = cls.get_client(owner_uid, client_id, sandbox=sandbox)
                    if client:
                        current_stage = client.get("pipelineStage", "Prospecto")
                        if current_stage.lower() in ["prospecto", "en negociación", "en negociacion"]:
                            cls.update_client_pipeline(owner_uid, client_id, "Cliente Activo", sandbox=sandbox)
                except Exception as e:
                    print(f"⚠️ Error al actualizar automáticamente el pipelineStage del cliente {client_id}: {e}")

        if firebase_initialized:
            try:
                coll_name = "sandbox_invoices" if sandbox else "invoices"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(invoice_id).set(inv_dict)
            except Exception as e:
                print(f"⚠️ Fallo al respaldar factura en Firestore: {e}")
        return inv_dict

    @classmethod
    def get_invoice_payments(cls, owner_uid, invoice_id, sandbox=True):
        """Retorna el listado de abonos registrados para una factura."""
        payments = []
        if firebase_initialized:
            try:
                coll_inv = "sandbox_invoices" if sandbox else "invoices"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_inv).document(invoice_id).collection("payments").get()
                for doc in docs:
                    data = doc.to_dict()
                    payments.append({
                        "id": doc.id,
                        "amount": float(data.get("amount", 0.0)),
                        "paymentMethod": data.get("paymentMethod", ""),
                        "bank": data.get("bank", ""),
                        "referenceNumber": data.get("referenceNumber", ""),
                        "paymentDate": serialize_field(data.get("paymentDate")),
                        "registeredBy": data.get("registeredBy", "")
                    })
                # Ordenar por fecha de pago ascendente
                payments.sort(key=lambda x: x["paymentDate"] or "")
            except Exception as e:
                print(f"⚠️ Error al obtener abonos de factura: {e}")
        return payments

    @classmethod
    def register_invoice_payment(cls, owner_uid, invoice_id, payment_dict, sandbox=True):
        """Registra un nuevo abono para una factura y actualiza los balances del documento."""
        if not firebase_initialized:
            return None
        try:
            coll_inv = "sandbox_invoices" if sandbox else "invoices"
            
            # Obtener factura actual
            inv_ref = db_firestore.collection("users").document(owner_uid).collection(coll_inv).document(invoice_id)
            inv_doc = inv_ref.get()
            if not inv_doc.exists:
                raise ValueError("Factura no encontrada.")
            
            inv_data = inv_doc.to_dict()
            net_payable = float(inv_data.get("netPayable", 0.0))
            
            # Si totalPaid o remainingBalance no existen en Firestore para esta factura antigua, inicializarlos con fallbacks
            current_status = inv_data.get("status")
            current_total_paid = float(inv_data.get("totalPaid", net_payable if current_status == "Cobrada" else 0.0))
            
            amount = float(payment_dict["amount"])
            new_total_paid = current_total_paid + amount
            new_remaining_balance = max(0.0, net_payable - new_total_paid)
            
            # Cargar cuotas existentes o generar cuota única retrocompatible
            installments = inv_data.get("installments")
            if not installments:
                installments = [{
                    "id": "cuota-unica-default",
                    "installmentNumber": 1,
                    "amount": net_payable,
                    "dueDate": serialize_field(inv_data.get("dueDate")),
                    "status": "Saldada" if current_status == "Cobrada" else "Pendiente",
                    "paidAmount": current_total_paid,
                    "remainingBalance": float(inv_data.get("remainingBalance", 0.0 if current_status == "Cobrada" else net_payable))
                }]
            
            # Distribución en cascada del abono de forma ordenada
            amount_left_to_allocate = amount
            updated_installments = []
            
            for inst in installments:
                inst_id = inst.get("id") or str(uuid.uuid4())
                inst_num = int(inst.get("installmentNumber", 1))
                inst_amount = float(inst.get("amount", 0.0))
                inst_due = serialize_field(inst.get("dueDate"))
                inst_status = inst.get("status", "Pendiente")
                inst_paid = float(inst.get("paidAmount", 0.0))
                inst_rem = float(inst.get("remainingBalance", inst_amount - inst_paid))
                
                if amount_left_to_allocate > 0 and inst_status == "Pendiente":
                    allocable = min(amount_left_to_allocate, inst_rem)
                    amount_left_to_allocate = max(0.0, amount_left_to_allocate - allocable)
                    inst_paid += allocable
                    inst_rem = max(0.0, inst_rem - allocable)
                    
                    if inst_rem <= 0.01:
                        inst_status = "Saldada"
                        inst_rem = 0.0
                
                updated_installments.append({
                    "id": inst_id,
                    "installmentNumber": inst_num,
                    "amount": inst_amount,
                    "dueDate": inst_due,
                    "status": inst_status,
                    "paidAmount": inst_paid,
                    "remainingBalance": inst_rem
                })
            
            # Registrar el abono en la subcolección
            payment_id = payment_dict.get("id") or str(uuid.uuid4())
            payment_dict["id"] = payment_id
            if "paymentDate" not in payment_dict or not payment_dict["paymentDate"]:
                payment_dict["paymentDate"] = datetime.utcnow().isoformat()
            payment_dict["paymentDate"] = serialize_field(payment_dict["paymentDate"])
            
            inv_ref.collection("payments").document(payment_id).set(payment_dict)
            
            # Determinar nuevo estado de factura
            if new_remaining_balance <= 0.01:  # tolerancia de centavos
                new_status = "Cobrada"
                new_remaining_balance = 0.0
            else:
                new_status = "Parcialmente Cobrada"
                
            # Actualizar ficha principal
            inv_ref.update({
                "totalPaid": new_total_paid,
                "remainingBalance": new_remaining_balance,
                "status": new_status,
                "paymentMethod": payment_dict["paymentMethod"], # Mostrar el último método usado
                "bank": payment_dict["bank"],
                "referenceNumber": payment_dict["referenceNumber"],
                "paymentDate": payment_dict["paymentDate"],
                "installments": updated_installments
            })
            
            return payment_dict
        except Exception as e:
            print(f"❌ Error al registrar abono en Firestore: {e}")
            raise e

    # =========================================================================
    # GESTIÓN DE GASTOS Y EGRESOS (EXPENSES)
    # =========================================================================

    @classmethod
    def get_expense(cls, owner_uid, expense_id, sandbox=True):
        """Retorna un gasto específico por ID."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_expenses" if sandbox else "expenses"
                doc = db_firestore.collection("users").document(owner_uid).collection(coll_name).document(expense_id).get()
                if doc.exists:
                    data = doc.to_dict()
                    data["id"] = doc.id
                    data["amount"] = float(data.get("amount", 0.0))
                    data["itbisAmount"] = float(data.get("itbisAmount", 0.0))
                    data["date"] = serialize_field(data.get("date"))
                    data["nextOccurrenceDate"] = serialize_field(data.get("nextOccurrenceDate"))
                    data["recurrenceEndDate"] = serialize_field(data.get("recurrenceEndDate"))
                    data["createdAt"] = serialize_field(data.get("createdAt"))
                    data["dueDate"] = serialize_field(data.get("dueDate", ""))
                    data["cxpRemainingBalance"] = float(data.get("cxpRemainingBalance", 0.0))
                    return data
            except Exception as e:
                print(f"⚠️ Error al obtener gasto {expense_id} desde Firestore: {e}")
        return None

    @classmethod
    def get_expenses(cls, owner_uid, sandbox=True):
        """Retorna la lista de gastos desde Firestore."""
        expenses = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_expenses" if sandbox else "expenses"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                for doc in docs:
                    data = doc.to_dict()
                    expenses.append({
                        "id": doc.id,
                        "concept": data.get("concept", ""),
                        "category": data.get("category", ""),
                        "amount": float(data.get("amount", 0.0)),
                        "date": serialize_field(data.get("date")),
                        "rncEmisor": data.get("rncEmisor", ""),
                        "ncf": data.get("ncf", ""),
                        "isMinorExpense": bool(data.get("isMinorExpense", False)),
                        "isSyncedWithDGII": bool(data.get("isSyncedWithDGII", False)),
                        "qrCodeURL": data.get("qrCodeURL", ""),
                        "xmlSignature": data.get("xmlSignature", ""),
                        "notes": data.get("notes", ""),
                        "isRecurring": bool(data.get("isRecurring", False)),
                        "recurrenceInterval": data.get("recurrenceInterval", "mensual"),
                        "nextOccurrenceDate": serialize_field(data.get("nextOccurrenceDate")),
                        "recurrenceEndDate": serialize_field(data.get("recurrenceEndDate")),
                        "associatedInvoiceId": data.get("associatedInvoiceId", ""),
                        "itbisAmount": float(data.get("itbisAmount", 0.0)),
                        "isITBISDeductible": bool(data.get("isITBISDeductible", True)),
                        "isDeductible": bool(data.get("isDeductible", True)),
                        "firebaseAttachmentURLs": data.get("firebaseAttachmentURLs", []),
                        "createdAt": serialize_field(data.get("createdAt")),
                        # Nuevos campos e-CF y CxP:
                        "ecfType": data.get("ecfType", ""),
                        "ecfNumber": data.get("ecfNumber", ""),
                        "cne": data.get("cne", ""),
                        "tipoGastoDGII": data.get("tipoGastoDGII", ""),
                        "paymentType": data.get("paymentType", "Contado"),
                        "cxpStatus": data.get("cxpStatus", "Pagado"),
                        "cxpRemainingBalance": float(data.get("cxpRemainingBalance", 0.0)),
                        "approvalStatus": data.get("approvalStatus", "Aprobado"),
                        "requestedBy": data.get("requestedBy", ""),
                        "approvedBy": data.get("approvedBy", ""),
                        "dueDate": serialize_field(data.get("dueDate", ""))
                    })
                expenses.sort(key=lambda x: x["date"] or "", reverse=True)
            except Exception as e:
                print(f"⚠️ Error al obtener gastos desde Firestore: {e}")
        return expenses

    @classmethod
    def save_expense(cls, owner_uid, expense_id, exp_dict, sandbox=True):
        """Guarda o actualiza un gasto en Firestore."""
        exp_dict["id"] = expense_id
        exp_dict["ownerUID"] = owner_uid
        if "createdAt" not in exp_dict or not exp_dict["createdAt"]:
            exp_dict["createdAt"] = datetime.utcnow().isoformat()
        
        exp_dict["amount"] = float(exp_dict["amount"])
        exp_dict["itbisAmount"] = float(exp_dict.get("itbisAmount", exp_dict["amount"] * 0.18 / 1.18))
        exp_dict["isMinorExpense"] = bool(exp_dict.get("isMinorExpense", False))
        exp_dict["isSyncedWithDGII"] = bool(exp_dict.get("isSyncedWithDGII", False))
        exp_dict["isRecurring"] = bool(exp_dict.get("isRecurring", False))
        exp_dict["isITBISDeductible"] = bool(exp_dict.get("isITBISDeductible", True))
        exp_dict["isDeductible"] = bool(exp_dict.get("isDeductible", True))
        
        # Nuevos campos e-CF y CxP:
        exp_dict["ecfType"] = exp_dict.get("ecfType", "")
        exp_dict["ecfNumber"] = exp_dict.get("ecfNumber", "")
        exp_dict["cne"] = exp_dict.get("cne", "")
        exp_dict["tipoGastoDGII"] = exp_dict.get("tipoGastoDGII", "")
        exp_dict["paymentType"] = exp_dict.get("paymentType", "Contado")
        exp_dict["cxpStatus"] = exp_dict.get("cxpStatus", "Pagado")
        exp_dict["cxpRemainingBalance"] = float(exp_dict.get("cxpRemainingBalance", 0.0 if exp_dict["paymentType"] == "Contado" else exp_dict["amount"]))
        exp_dict["approvalStatus"] = exp_dict.get("approvalStatus", "Aprobado")
        exp_dict["requestedBy"] = exp_dict.get("requestedBy", "")
        exp_dict["approvedBy"] = exp_dict.get("approvedBy", "")
        exp_dict["dueDate"] = serialize_field(exp_dict.get("dueDate", ""))
        
        exp_dict["date"] = serialize_field(exp_dict["date"])
        exp_dict["nextOccurrenceDate"] = serialize_field(exp_dict.get("nextOccurrenceDate"))
        exp_dict["recurrenceEndDate"] = serialize_field(exp_dict.get("recurrenceEndDate"))
        exp_dict["createdAt"] = serialize_field(exp_dict["createdAt"])

        if firebase_initialized:
            try:
                coll_name = "sandbox_expenses" if sandbox else "expenses"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(expense_id).set(exp_dict)
            except Exception as e:
                print(f"⚠️ Fallo al respaldar gasto en Firestore: {e}")

        return exp_dict

    @classmethod
    def save_cxp_payment(cls, owner_uid, expense_id, payment_amount, registered_by="Usuario", sandbox=True):
        """Registra un abono/pago a una cuenta por pagar (gasto a crédito)."""
        if not firebase_initialized:
            return False, "Firebase no inicializado."
        try:
            coll_name = "sandbox_expenses" if sandbox else "expenses"
            doc_ref = db_firestore.collection("users").document(owner_uid).collection(coll_name).document(expense_id)
            doc = doc_ref.get()
            if not doc.exists:
                return False, "Gasto/Factura no encontrado."
                
            data = doc.to_dict()
            amount = float(data.get("amount", 0.0))
            current_rem = float(data.get("cxpRemainingBalance", amount))
            
            new_rem = max(0.0, current_rem - payment_amount)
            new_status = "Pagado" if new_rem <= 0.01 else "Abonado"
            
            # Registrar el pago en una subcolección del gasto
            payment_id = str(uuid.uuid4())
            payment_doc = {
                "id": payment_id,
                "amount": payment_amount,
                "paymentDate": datetime.utcnow().isoformat(),
                "registeredBy": registered_by
            }
            doc_ref.collection("cxp_payments").document(payment_id).set(payment_doc)
            
            # Actualizar gasto principal
            doc_ref.update({
                "cxpRemainingBalance": new_rem,
                "cxpStatus": new_status
            })
            return True, f"Pago de RD$ {payment_amount:,.2f} registrado con éxito. Nuevo balance: RD$ {new_rem:,.2f}."
        except Exception as e:
            print(f"⚠️ Error en save_cxp_payment: {e}")
            return False, str(e)
            
    @classmethod
    def get_cxp_payments(cls, owner_uid, expense_id, sandbox=True):
        """Retorna todos los abonos realizados a una cuenta por pagar."""
        payments = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_expenses" if sandbox else "expenses"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).document(expense_id).collection("cxp_payments").get()
                for doc in docs:
                    data = doc.to_dict()
                    payments.append({
                        "id": doc.id,
                        "amount": float(data.get("amount", 0.0)),
                        "paymentDate": data.get("paymentDate", ""),
                        "registeredBy": data.get("registeredBy", "")
                    })
                payments.sort(key=lambda x: x["paymentDate"], reverse=True)
            except Exception as e:
                print(f"⚠️ Error al obtener pagos de CxP: {e}")
        return payments

    @classmethod
    def delete_expense(cls, owner_uid, expense_id, sandbox=True):
        """Elimina un gasto en Firestore."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_expenses" if sandbox else "expenses"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(expense_id).delete()
            except Exception as e:
                print(f"⚠️ Fallo al borrar gasto de Firestore: {e}")

    # =========================================================================
    # GESTIÓN DE ARCHIVOS EN FIREBASE STORAGE
    # =========================================================================

    @classmethod
    def get_storage_usage_mb(cls, owner_uid):
        """Calcula el espacio consumido por la empresa en Firebase Storage en MB."""
        if not firebase_initialized or not firebase_storage_bucket:
            # Simulación local o cálculo de static/uploads
            return 15.4 # Valor simulado por defecto para desarrollo local
        
        try:
            total_bytes = 0
            # Listar todos los blobs con el prefijo users/{owner_uid}/
            blobs = firebase_storage_bucket.list_blobs(prefix=f"users/{owner_uid}/")
            for blob in blobs:
                total_bytes += blob.size or 0
            return round(total_bytes / (1024 * 1024), 2)
        except Exception as e:
            print(f"⚠️ Error al calcular uso de almacenamiento para {owner_uid}: {e}")
            return 0.0

    @classmethod
    def upload_file_to_storage(cls, file_data, destination_path, mime_type="application/octet-stream"):
        """Sube un archivo (PDF, XML, Ticket) a Firebase Storage y retorna su URL pública."""
        # Validar límite de almacenamiento
        owner_uid = None
        parts = destination_path.split('/')
        if len(parts) > 1 and parts[0] == 'users':
            owner_uid = parts[1]
            
        if owner_uid:
            try:
                profile = cls.get_company_profile(owner_uid)
                if profile:
                    storage_limit = profile.get('storageLimitMB')
                    if storage_limit:
                        current_usage = cls.get_storage_usage_mb(owner_uid)
                        new_file_mb = len(file_data) / (1024 * 1024)
                        if (current_usage + new_file_mb) > float(storage_limit):
                            raise ValueError(f"Límite de almacenamiento excedido. Límite: {storage_limit} MB. Consumo actual: {current_usage:.2f} MB.")
            except ValueError as ve:
                print(f"❌ {ve}")
                raise ve
            except Exception as ex:
                print(f"⚠️ Error validando límite de almacenamiento: {ex}")

        if not firebase_initialized or not firebase_storage_bucket:
            # En modo local, simulamos una ruta local en uploads
            uploads_dir = os.path.join("static", "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            filename = os.path.basename(destination_path)
            local_path = os.path.join(uploads_dir, filename)
            with open(local_path, "wb") as f:
                f.write(file_data)
            return f"/static/uploads/{filename}"

        try:
            blob = firebase_storage_bucket.blob(destination_path)
            blob.upload_from_string(file_data, content_type=mime_type)
            blob.make_public()
            return blob.public_url
        except Exception as e:
            print(f"❌ Error al subir archivo a Firebase Storage: {e}")
            # Fallback a guardado local en static/uploads
            uploads_dir = os.path.join("static", "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            filename = os.path.basename(destination_path)
            local_path = os.path.join(uploads_dir, filename)
            with open(local_path, "wb") as f:
                f.write(file_data)
            return f"/static/uploads/{filename}"

    # =========================================================================
    # GESTIÓN DE INVENTARIO Y ALMACENES
    # =========================================================================

    @classmethod
    def get_warehouses(cls, owner_uid, sandbox=True):
        """Retorna la lista de almacenes del owner."""
        warehouses = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_warehouses" if sandbox else "warehouses"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                for doc in docs:
                    data = doc.to_dict()
                    warehouses.append({
                        "id": doc.id,
                        "name": data.get("name", ""),
                        "description": data.get("description", ""),
                        "address": data.get("address", ""),
                        "branchId": data.get("branchId", "default-sucursal-principal"),
                        "createdAt": serialize_field(data.get("createdAt"))
                    })
                
                # Crear almacén principal predeterminado si está vacío (UX Onboarding)
                if not warehouses:
                    default_id = "default-almacen-principal"
                    default_wh = {
                        "id": default_id,
                        "name": "Almacén Principal",
                        "description": "Depósito central de existencias predeterminado",
                        "address": "Sede Principal",
                        "branchId": "default-sucursal-principal",
                        "createdAt": datetime.utcnow().isoformat()
                    }
                    cls.save_warehouse(owner_uid, default_id, default_wh, sandbox=sandbox)
                    warehouses.append(default_wh)
                else:
                    warehouses.sort(key=lambda x: x["name"].lower())
            except Exception as e:
                print(f"⚠️ Error al obtener almacenes desde Firestore: {e}")
        return warehouses

    @classmethod
    def save_warehouse(cls, owner_uid, warehouse_id, wh_dict, sandbox=True):
        """Guarda o actualiza un almacén físico en Firestore."""
        wh_dict["id"] = warehouse_id
        wh_dict["ownerUID"] = owner_uid
        if "createdAt" not in wh_dict or not wh_dict["createdAt"]:
            wh_dict["createdAt"] = datetime.utcnow().isoformat()
        wh_dict["createdAt"] = serialize_field(wh_dict["createdAt"])

        if firebase_initialized:
            try:
                coll_name = "sandbox_warehouses" if sandbox else "warehouses"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(warehouse_id).set(wh_dict)
            except Exception as e:
                print(f"⚠️ Fallo al guardar almacén en Firestore: {e}")
        return wh_dict

    @classmethod
    def delete_warehouse(cls, owner_uid, warehouse_id, sandbox=True):
        """Elimina un almacén en Firestore."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_warehouses" if sandbox else "warehouses"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(warehouse_id).delete()
            except Exception as e:
                print(f"⚠️ Fallo al borrar almacén de Firestore: {e}")

    @classmethod
    def get_inventory_stock(cls, owner_uid, sandbox=True):
        """Retorna la lista de existencias por almacén en Firestore."""
        stocks = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_inventory_stock" if sandbox else "inventory_stock"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                for doc in docs:
                    data = doc.to_dict()
                    stocks.append({
                        "id": doc.id,
                        "itemId": data.get("itemId", ""),
                        "warehouseId": data.get("warehouseId", ""),
                        "quantity": float(data.get("quantity", 0.0)),
                        "updatedAt": serialize_field(data.get("updatedAt"))
                    })
            except Exception as e:
                print(f"⚠️ Error al obtener existencias de Firestore: {e}")
        return stocks

    @classmethod
    def get_inventory_transactions(cls, owner_uid, sandbox=True):
        """Retorna el listado histórico de movimientos de inventario."""
        txs = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_inventory_transactions" if sandbox else "inventory_transactions"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                for doc in docs:
                    data = doc.to_dict()
                    txs.append({
                        "id": doc.id,
                        "itemId": data.get("itemId", ""),
                        "itemName": data.get("itemName", ""),
                        "type": data.get("type", "ENTRADA"),
                        "quantity": float(data.get("quantity", 0.0)),
                        "originWarehouseId": data.get("originWarehouseId", ""),
                        "originWarehouseName": data.get("originWarehouseName", ""),
                        "originBranchId": data.get("originBranchId", ""),
                        "destinationWarehouseId": data.get("destinationWarehouseId", ""),
                        "destinationWarehouseName": data.get("destinationWarehouseName", ""),
                        "destinationBranchId": data.get("destinationBranchId", ""),
                        "reason": data.get("reason", "AJUSTE_MANUAL"),
                        "referenceId": data.get("referenceId", ""),
                        "notes": data.get("notes", ""),
                        "date": serialize_field(data.get("date")),
                        "performedBy": data.get("performedBy", "")
                    })
                txs.sort(key=lambda x: x["date"] or "", reverse=True)
            except Exception as e:
                print(f"⚠️ Error al obtener transacciones de inventario: {e}")
        return txs

    @classmethod
    def register_inventory_transaction(cls, owner_uid, tx_dict, sandbox=True):
        """
        Registra un movimiento físico de inventario y actualiza las existencias.
        IMPORTANTE: Todas las lecturas se hacen ANTES de cualquier escritura dentro
        de la transacción Firestore para evitar el error 'read-after-write'.
        El recálculo de totalStock se hace fuera de la transacción (post-commit).
        """
        if not firebase_initialized:
            return None

        coll_stock = "sandbox_inventory_stock" if sandbox else "inventory_stock"
        coll_tx = "sandbox_inventory_transactions" if sandbox else "inventory_transactions"
        coll_items = "sandbox_items" if sandbox else "items"

        tx_id = tx_dict.get("id") or str(uuid.uuid4())
        tx_dict["id"] = tx_id
        tx_dict["ownerUID"] = owner_uid
        if "date" not in tx_dict or not tx_dict["date"]:
            tx_dict["date"] = datetime.utcnow().isoformat()

        item_id = tx_dict["itemId"]
        tx_type = tx_dict["type"]
        qty = float(tx_dict["quantity"])

        whs = cls.get_warehouses(owner_uid, sandbox=sandbox)
        wh_map = {w["id"]: w.get("branchId", "default-sucursal-principal") for w in whs}

        if tx_dict.get("originWarehouseId"):
            tx_dict["originBranchId"] = wh_map.get(tx_dict["originWarehouseId"], "default-sucursal-principal")
        if tx_dict.get("destinationWarehouseId"):
            tx_dict["destinationBranchId"] = wh_map.get(tx_dict["destinationWarehouseId"], "default-sucursal-principal")

        transaction = db_firestore.transaction()

        @firestore.transactional
        def run_in_transaction(transaction):
            # ── FASE 1: TODAS LAS LECTURAS PRIMERO ──────────────────────────
            stock_updates = []  # lista de (ref, new_qty, wh_id)

            if tx_type == "ENTRADA":
                dest_wh_id = tx_dict["destinationWarehouseId"]
                ref = db_firestore.collection("users").document(owner_uid)\
                    .collection(coll_stock).document(f"{item_id}_{dest_wh_id}")
                doc = ref.get(transaction=transaction)
                old_qty = float(doc.to_dict().get("quantity", 0.0)) if doc.exists else 0.0
                stock_updates.append((ref, old_qty + qty, dest_wh_id))

            elif tx_type == "SALIDA":
                orig_wh_id = tx_dict["originWarehouseId"]
                ref = db_firestore.collection("users").document(owner_uid)\
                    .collection(coll_stock).document(f"{item_id}_{orig_wh_id}")
                doc = ref.get(transaction=transaction)
                old_qty = float(doc.to_dict().get("quantity", 0.0)) if doc.exists else 0.0
                stock_updates.append((ref, old_qty - qty, orig_wh_id))

            elif tx_type == "TRANSFERENCIA":
                orig_wh_id = tx_dict["originWarehouseId"]
                dest_wh_id = tx_dict["destinationWarehouseId"]
                ref_orig = db_firestore.collection("users").document(owner_uid)\
                    .collection(coll_stock).document(f"{item_id}_{orig_wh_id}")
                ref_dest = db_firestore.collection("users").document(owner_uid)\
                    .collection(coll_stock).document(f"{item_id}_{dest_wh_id}")
                # Ambas lecturas antes de cualquier write
                doc_orig = ref_orig.get(transaction=transaction)
                doc_dest = ref_dest.get(transaction=transaction)
                old_orig = float(doc_orig.to_dict().get("quantity", 0.0)) if doc_orig.exists else 0.0
                old_dest = float(doc_dest.to_dict().get("quantity", 0.0)) if doc_dest.exists else 0.0
                stock_updates.append((ref_orig, old_orig - qty, orig_wh_id))
                stock_updates.append((ref_dest, old_dest + qty, dest_wh_id))

            # ── FASE 2: TODAS LAS ESCRITURAS DESPUÉS DE LAS LECTURAS ────────
            for ref, new_qty, wh_id in stock_updates:
                transaction.set(ref, {
                    "id": f"{item_id}_{wh_id}",
                    "itemId": item_id,
                    "warehouseId": wh_id,
                    "quantity": new_qty,
                    "updatedAt": firestore.SERVER_TIMESTAMP
                })

            # Registrar el movimiento en el historial
            tx_ref = db_firestore.collection("users").document(owner_uid)\
                .collection(coll_tx).document(tx_id)
            transaction.set(tx_ref, tx_dict)

            return tx_dict

        try:
            res = run_in_transaction(transaction)
            # Post-transacción: recalcular totalStock real fuera de la transacción.
            # No se puede hacer query-read después de writes dentro de Firestore.
            try:
                all_stocks = db_firestore.collection("users").document(owner_uid)\
                    .collection(coll_stock).where(filter=firestore.FieldFilter("itemId", "==", item_id)).get()
                real_total = sum(float(s.to_dict().get("quantity", 0.0)) for s in all_stocks)
                db_firestore.collection("users").document(owner_uid)\
                    .collection(coll_items).document(item_id).update({"totalStock": real_total})
            except Exception as recalc_err:
                print(f"⚠️ No se pudo recalcular totalStock post-transacción: {recalc_err}")
            return res
        except Exception as e:
            print(f"❌ Error al registrar transacción de inventario: {e}")
            return None

    @classmethod
    def get_company_by_api_key(cls, api_key):
        """Busca una compañía y su propietario usando una API Key en la colección raíz 'api_keys'."""
        if not firebase_initialized:
            return None
        try:
            doc = db_firestore.collection("api_keys").document(api_key).get()
            if doc.exists:
                data = doc.to_dict()
                owner_uid = data.get("ownerUID")
                if owner_uid:
                    # Retornar el perfil de la compañía completo
                    return cls.get_company_profile(owner_uid)
        except Exception as e:
            print(f"⚠️ Error al buscar compañía por API Key: {e}")
        return None

    @classmethod
    def generate_api_key(cls, owner_uid):
        """Genera una nueva API Key única para un owner_uid y la guarda en la colección api_keys y en su perfil."""
        if not firebase_initialized:
            return None
        try:
            # Generar API Key
            new_key = f"ef_{uuid.uuid4().hex}"
            
            # 1. Guardar en la colección raíz api_keys para búsqueda ultra rápida
            db_firestore.collection("api_keys").document(new_key).set({
                "ownerUID": owner_uid,
                "createdAt": datetime.utcnow().isoformat()
            })
            
            # 2. Actualizar el perfil de empresa de la compañía para que pueda verla en la UI
            company_profile = cls.get_company_profile(owner_uid)
            
            # Si ya tenía una API Key anterior, podemos opcionalmente borrar la anterior
            old_key = company_profile.get("apiKey")
            if old_key:
                try:
                    db_firestore.collection("api_keys").document(old_key).delete()
                except Exception:
                    pass
            
            company_profile["apiKey"] = new_key
            cls.save_company_profile(owner_uid, company_profile)
            return new_key
        except Exception as e:
            print(f"⚠️ Error al generar API Key: {e}")
            return None

    @classmethod
    def get_invoice_stats(cls, owner_uid, billing_day=1):
        """Calcula estadísticas de facturas emitidas en producción y sandbox para el ciclo actual."""
        if not firebase_initialized:
            return {
                'prod_total': 0, 'prod_current_cycle': 0,
                'sandbox_total': 0, 'sandbox_current_cycle': 0,
                'current_cycle_start': None, 'current_cycle_end': None
            }
        
        import datetime
        stats = {
            'prod_total': 0,
            'prod_current_cycle': 0,
            'sandbox_total': 0,
            'sandbox_current_cycle': 0,
            'current_cycle_start': None,
            'current_cycle_end': None
        }
        
        now = datetime.datetime.now()
        try:
            billing_day = int(billing_day) if billing_day else 1
            if billing_day < 1 or billing_day > 28:
                billing_day = 1
        except Exception:
            billing_day = 1
            
        if now.day >= billing_day:
            start_date = datetime.datetime(now.year, now.month, billing_day, 0, 0, 0)
            if now.month == 12:
                end_date = datetime.datetime(now.year + 1, 1, billing_day, 23, 59, 59)
            else:
                end_date = datetime.datetime(now.year, now.month + 1, billing_day, 23, 59, 59)
        else:
            if now.month == 1:
                start_date = datetime.datetime(now.year - 1, 12, billing_day, 0, 0, 0)
            else:
                start_date = datetime.datetime(now.year, now.month - 1, billing_day, 0, 0, 0)
            end_date = datetime.datetime(now.year, now.month, billing_day, 23, 59, 59)
            
        stats['current_cycle_start'] = start_date.strftime('%Y-%m-%d')
        stats['current_cycle_end'] = end_date.strftime('%Y-%m-%d')
        
        def parse_date(date_val):
            if not date_val:
                return None
            if hasattr(date_val, 'year'):
                if hasattr(date_val, 'to_datetime'):
                    try:
                        date_val = date_val.to_datetime()
                    except Exception:
                        pass
                if hasattr(date_val, 'replace'):
                    try:
                        return date_val.replace(tzinfo=None)
                    except Exception:
                        pass
                return date_val
            if isinstance(date_val, str):
                try:
                    return datetime.datetime.fromisoformat(date_val.split('Z')[0].split('+')[0]).replace(tzinfo=None)
                except Exception:
                    try:
                        return datetime.datetime.strptime(date_val[:10], '%Y-%m-%d').replace(tzinfo=None)
                    except Exception:
                        pass
            return None

        # Contar facturas de producción (excluyendo cotizaciones y borradores)
        try:
            prod_docs = db_firestore.collection('users').document(owner_uid).collection('invoices')\
                .where(filter=firestore.FieldFilter('isQuotation', '==', False)).stream()
            for doc in prod_docs:
                data = doc.to_dict()
                if data.get('status') == 'Borrador':
                    continue
                stats['prod_total'] += 1
                doc_date = parse_date(data.get('date') or data.get('createdAt'))
                if doc_date and start_date <= doc_date <= end_date:
                    stats['prod_current_cycle'] += 1
        except Exception as e:
            print(f"⚠️ Error counting prod invoices for {owner_uid}: {e}")
            
        # Contar facturas de sandbox (excluyendo cotizaciones y borradores)
        try:
            sandbox_docs = db_firestore.collection('users').document(owner_uid).collection('sandbox_invoices')\
                .where(filter=firestore.FieldFilter('isQuotation', '==', False)).stream()
            for doc in sandbox_docs:
                data = doc.to_dict()
                if data.get('status') == 'Borrador':
                    continue
                stats['sandbox_total'] += 1
                doc_date = parse_date(data.get('date') or data.get('createdAt'))
                if doc_date and start_date <= doc_date <= end_date:
                    stats['sandbox_current_cycle'] += 1
        except Exception as e:
            print(f"⚠️ Error counting sandbox invoices for {owner_uid}: {e}")
            
        return stats

    @classmethod
    def get_payments(cls, company_id):
        """Retorna el historial de pagos de una empresa."""
        if not firebase_initialized:
            return []
        try:
            docs = db_firestore.collection('users').document(company_id)\
                .collection('payments').order_by('date', direction=firestore.Query.DESCENDING).stream()
            payments = []
            for doc in docs:
                data = doc.to_dict()
                payments.append(data)
            return payments
        except Exception as e:
            print(f"❌ Error en get_payments({company_id}): {e}")
            return []

    @classmethod
    def get_billing_history(cls, owner_uid, billing_day=1, monthly_payment=0, additional_document_cost=0, document_limit=0, created_at=None):
        """
        Genera el historial de ciclos de facturación, consumo y pagos de los últimos 6 meses.
        """
        import datetime
        if not firebase_initialized:
            return []
            
        history = []
        payments_list = cls.get_payments(owner_uid)
        
        # Obtener todas las facturas de producción (excluyendo cotizaciones y borradores)
        invoices = []
        try:
            prod_docs = db_firestore.collection('users').document(owner_uid).collection('invoices')\
                .where(filter=firestore.FieldFilter('isQuotation', '==', False)).stream()
            for doc in prod_docs:
                data = doc.to_dict()
                if data.get('status') == 'Borrador':
                    continue
                invoices.append(data)
        except Exception as e:
            print(f"⚠️ Error al obtener facturas para historial: {e}")
            
        def parse_date(date_val):
            if not date_val:
                return None
            if hasattr(date_val, 'year'):
                if hasattr(date_val, 'to_datetime'):
                    try:
                        date_val = date_val.to_datetime()
                    except Exception:
                        pass
                if hasattr(date_val, 'replace'):
                    try:
                        return date_val.replace(tzinfo=None)
                    except Exception:
                        pass
                return date_val
            if isinstance(date_val, str):
                try:
                    return datetime.datetime.fromisoformat(date_val.split('Z')[0].split('+')[0]).replace(tzinfo=None)
                except Exception:
                    try:
                        return datetime.datetime.strptime(date_val[:10], '%Y-%m-%d').replace(tzinfo=None)
                    except Exception:
                        pass
            return None

        # Calcular los últimos 6 ciclos finalizados
        now = datetime.datetime.now()
        try:
            billing_day = int(billing_day) if billing_day else 1
            if billing_day < 1 or billing_day > 28:
                billing_day = 1
        except Exception:
            billing_day = 1

        current_year = now.year
        current_month = now.month
        
        if now.day >= billing_day:
            anchor_date = datetime.datetime(current_year, current_month, billing_day)
        else:
            if current_month == 1:
                anchor_date = datetime.datetime(current_year - 1, 12, billing_day)
            else:
                anchor_date = datetime.datetime(current_year, current_month - 1, billing_day)

        reg_date = parse_date(created_at)

        # Generar los últimos 6 ciclos finalizados
        for i in range(1, 7):
            year = anchor_date.year
            month = anchor_date.month - i
            while month <= 0:
                month += 12
                year -= 1
                
            cycle_start = datetime.datetime(year, month, billing_day, 0, 0, 0)
            
            next_month = month + 1
            next_year = year
            if next_month > 12:
                next_month -= 12
                next_year += 1
            cycle_end = datetime.datetime(next_year, next_month, billing_day, 23, 59, 59)
            
            # Omitir ciclos que finalizaron antes de la fecha de registro del cliente
            if reg_date and cycle_end < reg_date:
                continue
            
            # Contar documentos en este rango
            count = 0
            for inv in invoices:
                d_date = parse_date(inv.get('date') or inv.get('createdAt'))
                if d_date and cycle_start <= d_date <= cycle_end:
                    count += 1
            
            # Calcular cargos
            excess = max(0, count - document_limit) if document_limit > 0 else 0
            excess_charge = excess * additional_document_cost
            total_charge = monthly_payment + excess_charge
            
            # Buscar si hay algún pago en este periodo
            paid = False
            payment_ref = ""
            payment_date = None
            
            payment_grace_end = cycle_end + datetime.timedelta(days=15)
            for p in payments_list:
                p_date = parse_date(p.get('date'))
                if p_date and (cycle_start <= p_date <= payment_grace_end):
                    paid = True
                    payment_ref = p.get('reference', p.get('method', 'Manual'))
                    payment_date = p_date.strftime('%Y-%m-%d')
                    break
                    
            history.append({
                'period_label': f"{cycle_start.strftime('%B %Y')} ({cycle_start.strftime('%d/%m')} - {cycle_end.strftime('%d/%m')})",
                'start_date': cycle_start.strftime('%Y-%m-%d'),
                'end_date': cycle_end.strftime('%Y-%m-%d'),
                'consumed_docs': count,
                'excess_docs': excess,
                'monthly_fee': monthly_payment,
                'excess_charge': excess_charge,
                'total_charge': total_charge,
                'status': 'Saldado' if paid else 'Pendiente',
                'payment_ref': payment_ref,
                'payment_date': payment_date
            })
            
        meses_en = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
        meses_es = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
        for h in history:
            for en, es in zip(meses_en, meses_es):
                h['period_label'] = h['period_label'].replace(en, es)
                h['period_label'] = h['period_label'].replace(en.lower(), es.lower())
                
        return history

    # =========================================================================
    # GESTIÓN DE NOTAS (NOTES)
    # =========================================================================

    @classmethod
    def get_notes(cls, owner_uid, user_uid, sandbox=True):
        """Retorna la lista de notas (compartidas + privadas del usuario)."""
        notes = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_notes" if sandbox else "notes"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                for doc in docs:
                    data = doc.to_dict()
                    visibility = data.get("visibility", "shared")
                    created_by = data.get("createdBy", "")
                    
                    # Filtrar: Mostrar si es compartida, o si es privada y el creador es el usuario actual
                    if visibility == "shared" or (visibility == "private" and created_by == user_uid):
                        notes.append({
                            "id": doc.id,
                            "title": data.get("title", "Nota sin título"),
                            "content": data.get("content", ""),
                            "color": data.get("color", "default"),
                            "visibility": visibility,
                            "createdBy": created_by,
                            "status": data.get("status", "abierta"),
                            "createdAt": serialize_field(data.get("createdAt")),
                            "updatedAt": serialize_field(data.get("updatedAt"))
                        })
                notes.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
            except Exception as e:
                print(f"⚠️ Error al obtener notas desde Firestore: {e}")
        return notes

    @classmethod
    def save_note(cls, owner_uid, note_id, note_dict, sandbox=True):
        """Guarda o actualiza una nota en Firestore."""
        note_dict["id"] = note_id
        note_dict["ownerUID"] = owner_uid
        if "createdAt" not in note_dict or not note_dict["createdAt"]:
            note_dict["createdAt"] = datetime.utcnow().isoformat()
        
        note_dict["updatedAt"] = datetime.utcnow().isoformat()
        
        note_dict["createdAt"] = serialize_field(note_dict["createdAt"])
        note_dict["updatedAt"] = serialize_field(note_dict["updatedAt"])
        note_dict["visibility"] = note_dict.get("visibility", "shared")
        note_dict["status"] = note_dict.get("status", "abierta")

        if firebase_initialized:
            try:
                coll_name = "sandbox_notes" if sandbox else "notes"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(note_id).set(note_dict)
            except Exception as e:
                print(f"⚠️ Fallo al guardar nota en Firestore: {e}")

        return note_dict

    @classmethod
    def update_note_status(cls, owner_uid, note_id, status, sandbox=True):
        """Actualiza solo el estado de una nota en Firestore."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_notes" if sandbox else "notes"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(note_id).update({"status": status})
            except Exception as e:
                print(f"⚠️ Fallo al actualizar estado de nota en Firestore: {e}")

    @classmethod
    def delete_note(cls, owner_uid, note_id, sandbox=True):
        """Elimina una nota en Firestore."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_notes" if sandbox else "notes"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(note_id).delete()
            except Exception as e:
                print(f"⚠️ Fallo al borrar nota de Firestore: {e}")

    @classmethod
    def get_note_statuses(cls, owner_uid, sandbox=True):
        """Retorna las columnas/estados configurados para el tablero de notas."""
        default_statuses = [
            {"id": "abierta", "name": "Abierta", "color": "var(--accent-purple)", "order": 1},
            {"id": "in_progress", "name": "En Proceso", "color": "var(--accent-blue)", "order": 2},
            {"id": "done", "name": "Cerrado", "color": "var(--text-muted)", "order": 3}
        ]
        if not firebase_initialized:
            return default_statuses
        try:
            coll_name = "sandbox_settings" if sandbox else "settings"
            doc_ref = db_firestore.collection("users").document(owner_uid).collection(coll_name).document("note_board")
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                if "statuses" in data and isinstance(data["statuses"], list):
                    return data["statuses"]
            
            # Save and return defaults if not exists
            doc_ref.set({"statuses": default_statuses})
            return default_statuses
        except Exception as e:
            print(f"⚠️ Error get_note_statuses: {e}")
            return default_statuses

    @classmethod
    def save_note_statuses(cls, owner_uid, statuses, sandbox=True):
        """Guarda la lista de columnas/estados para las notas."""
        if not firebase_initialized:
            return
        try:
            coll_name = "sandbox_settings" if sandbox else "settings"
            doc_ref = db_firestore.collection("users").document(owner_uid).collection(coll_name).document("note_board")
            doc_ref.set({"statuses": statuses}, merge=True)
        except Exception as e:
            print(f"⚠️ Error save_note_statuses: {e}")

    # =========================================================================
    # GESTIÓN DE CAJA Y TURNOS POS
    # =========================================================================

    @classmethod
    def get_cash_registers(cls, owner_uid, sandbox=True):
        """Retorna la lista de cajas registradoras de la empresa."""
        registers = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_cash_registers" if sandbox else "cash_registers"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                for doc in docs:
                    data = doc.to_dict()
                    registers.append({
                        "id": doc.id,
                        "name": data.get("name", "Caja"),
                        "status": data.get("status", "CLOSED"),  # OPEN o CLOSED
                        "consolidationMode": data.get("consolidationMode", False),
                        "createdAt": serialize_field(data.get("createdAt"))
                    })
                
                # Crear caja por defecto si está vacía
                if not registers:
                    default_id = "default-caja-principal"
                    default_reg = {
                        "id": default_id,
                        "name": "Caja Principal 01",
                        "status": "CLOSED",
                        "createdAt": datetime.utcnow().isoformat()
                    }
                    cls.save_cash_register(owner_uid, default_id, default_reg, sandbox=sandbox)
                    registers.append(default_reg)
                else:
                    registers.sort(key=lambda x: x["name"].lower())
            except Exception as e:
                print(f"⚠️ Error al obtener cajas registradoras: {e}")
        return registers

    @classmethod
    def save_cash_register(cls, owner_uid, register_id, reg_dict, sandbox=True):
        """Guarda o actualiza una caja registradora en Firestore."""
        reg_dict["id"] = register_id
        reg_dict["ownerUID"] = owner_uid
        if "createdAt" not in reg_dict or not reg_dict["createdAt"]:
            reg_dict["createdAt"] = datetime.utcnow().isoformat()
        reg_dict["createdAt"] = serialize_field(reg_dict["createdAt"])
        # Normalizar bandera de modo consolidado
        if "consolidationMode" not in reg_dict:
            reg_dict["consolidationMode"] = False

        if firebase_initialized:
            try:
                coll_name = "sandbox_cash_registers" if sandbox else "cash_registers"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(register_id).set(reg_dict)
            except Exception as e:
                print(f"⚠️ Fallo al guardar caja registradora en Firestore: {e}")
        return reg_dict


    @classmethod
    def get_cash_shifts(cls, owner_uid, sandbox=True):
        """Retorna el listado completo de turnos de caja registrados."""
        shifts = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_cash_shifts" if sandbox else "cash_shifts"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                for doc in docs:
                    data = doc.to_dict()
                    shift_item = {
                        "id": doc.id,
                        "registerId": data.get("registerId"),
                        "openedByUserId": data.get("openedByUserId"),
                        "openedByUserEmail": data.get("openedByUserEmail", "cajero@efactura.com.do"),
                        "openingTime": serialize_field(data.get("openingTime")),
                        "closingTime": serialize_field(data.get("closingTime")),
                        "openingAmount": float(data.get("openingAmount", 0.0)),
                        "closingAmountExpected": float(data.get("closingAmountExpected", 0.0)) if data.get("closingAmountExpected") is not None else None,
                        "closingAmountDeclared": float(data.get("closingAmountDeclared", 0.0)) if data.get("closingAmountDeclared") is not None else None,
                        "difference": float(data.get("difference", 0.0)) if data.get("difference") is not None else None,
                        "status": data.get("status", "CLOSED"),
                        "auditedByUserId": data.get("auditedByUserId"),
                        "auditedByUserEmail": data.get("auditedByUserEmail"),
                        "auditedAt": serialize_field(data.get("auditedAt")),
                        "auditNotes": data.get("auditNotes", "")
                    }
                    # Incluir todos los demás campos personalizados (desgloses, diferencias por moneda, resoluciones, etc.)
                    shift_item.update({k: v for k, v in data.items() if k not in shift_item})
                    shifts.append(shift_item)
                # Ordenar por fecha de apertura descendente
                shifts.sort(key=lambda x: x["openingTime"] or "", reverse=True)
            except Exception as e:
                print(f"⚠️ Error al obtener turnos de caja: {e}")
        return shifts

    @classmethod
    def get_open_shift(cls, owner_uid, user_uid, sandbox=True):
        """Retorna el turno de caja abierto del usuario actual (si existe)."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_cash_shifts" if sandbox else "cash_shifts"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name)\
                    .where(filter=firestore.FieldFilter("openedByUserId", "==", user_uid))\
                    .where(filter=firestore.FieldFilter("status", "in", ["OPEN", "CLOSING", "REOPENED"])).limit(1).get()
                for doc in docs:
                    data = doc.to_dict()
                    return {
                        "id": doc.id,
                        "registerId": data.get("registerId", ""),
                        "openedByUserId": data.get("openedByUserId", ""),
                        "openingTime": serialize_field(data.get("openingTime")),
                        "openingAmount": float(data.get("openingAmount", 0.0)),
                        "status": data.get("status", "OPEN")
                    }
            except Exception as e:
                print(f"⚠️ Error al obtener turno abierto: {e}")
        return None

    @classmethod
    def open_cash_shift(cls, owner_uid, shift_dict, sandbox=True):
        """Abre un nuevo turno de caja registradora."""
        shift_id = shift_dict.get("id") or str(uuid.uuid4())
        shift_dict["id"] = shift_id
        shift_dict["status"] = "OPEN"
        shift_dict["openingTime"] = datetime.utcnow().isoformat()
        shift_dict["openingAmount"] = float(shift_dict.get("openingAmount", 0.0))
        
        if firebase_initialized:
            try:
                # 1. Guardar turno de caja
                coll_shifts = "sandbox_cash_shifts" if sandbox else "cash_shifts"
                db_firestore.collection("users").document(owner_uid).collection(coll_shifts).document(shift_id).set(shift_dict)
                
                # 2. Actualizar estado de la caja registradora a OPEN
                coll_regs = "sandbox_cash_registers" if sandbox else "cash_registers"
                db_firestore.collection("users").document(owner_uid).collection(coll_regs).document(shift_dict["registerId"]).update({
                    "status": "OPEN"
                })
            except Exception as e:
                print(f"⚠️ Error al abrir turno de caja: {e}")
                return None
        return shift_dict

    @classmethod
    def close_cash_shift(cls, owner_uid, shift_id, declared_amount, sandbox=True, status="CLOSED", supervisor_uid=None, supervisor_email=None, declared_data=None):
        """Cierra el turno de caja especificado y calcula descuadres."""
        if not firebase_initialized:
            return None
        try:
            coll_shifts = "sandbox_cash_shifts" if sandbox else "cash_shifts"
            coll_regs = "sandbox_cash_registers" if sandbox else "cash_registers"
            coll_txs = "sandbox_cash_transactions" if sandbox else "cash_transactions"
            coll_invoices = "sandbox_invoices" if sandbox else "invoices"

            # 1. Obtener datos del turno actual
            shift_ref = db_firestore.collection("users").document(owner_uid).collection(coll_shifts).document(shift_id)
            shift_doc = shift_ref.get()
            if not shift_doc.exists:
                return None
            shift_data = shift_doc.to_dict()

            opening_amount = float(shift_data.get("openingAmount", 0.0))
            register_id = shift_data.get("registerId")

            # 2. Calcular esperado por método de pago
            tx_docs = db_firestore.collection("users").document(owner_uid).collection(coll_txs)\
                .where(filter=firestore.FieldFilter("shiftId", "==", shift_id)).get()
            
            expected_cash = opening_amount
            expected_card = 0.0
            expected_transfer = 0.0
            expected_usd = 0.0

            for doc in tx_docs:
                t_data = doc.to_dict()
                if t_data.get("status") == "VOIDED":
                    continue
                t_amount = float(t_data.get("amount", 0.0))
                t_type = t_data.get("type", "SALE")
                pm = t_data.get("paymentMethod", "Efectivo")

                if t_type == "SALE":
                    if "Efectivo USD" in pm:
                        expected_usd += float(t_data.get("usdAmount", 0.0))
                    elif "Efectivo" in pm:
                        expected_cash += t_amount
                    elif "Tarjeta" in pm:
                        expected_card += t_amount
                    else:
                        expected_transfer += t_amount
                elif t_type == "IN":
                    expected_cash += t_amount
                elif t_type == "OUT":
                    expected_cash -= t_amount

            # Fallback si no viene declared_data
            if declared_data is None:
                declared_data = {
                    "declaredCash": declared_amount,
                    "declaredCard": 0.0,
                    "declaredTransfer": 0.0,
                    "declaredUSD": 0.0,
                    "usdExchangeRate": 58.50,
                    "cashDenominations": {},
                    "cardLoteNumber": ""
                }

            usd_rate = float(declared_data.get("usdExchangeRate") or 58.50)
            closing_expected = expected_cash + expected_card + expected_transfer + (expected_usd * usd_rate)
            difference = declared_amount - closing_expected

            # Diferencias por canal
            diff_cash = float(declared_data.get("declaredCash", 0.0)) - expected_cash
            diff_card = float(declared_data.get("declaredCard", 0.0)) - expected_card
            diff_transfer = float(declared_data.get("declaredTransfer", 0.0)) - expected_transfer
            diff_usd = float(declared_data.get("declaredUSD", 0.0)) - expected_usd

            # 3. Consultar facturas para generar resumen fiscal (e-CF)
            inv_docs = db_firestore.collection("users").document(owner_uid).collection(coll_invoices)\
                .where(filter=firestore.FieldFilter("posShiftId", "==", shift_id)).get()
            
            fiscal_summary = {
                "E31": {"count": 0, "total": 0.0, "itbis": 0.0},
                "E32": {"count": 0, "total": 0.0, "itbis": 0.0},
                "Otros": {"count": 0, "total": 0.0, "itbis": 0.0},
                "Anulados": {"count": 0, "total": 0.0}
            }
            
            for doc in inv_docs:
                inv_data = doc.to_dict()
                ecf_type = inv_data.get("ecfType", "")
                total = float(inv_data.get("total", 0.0))
                itbis = float(inv_data.get("totalITBIS", 0.0))
                status = inv_data.get("status", "")
                
                if status == "ANULADA" or status == "VOIDED":
                    fiscal_summary["Anulados"]["count"] += 1
                    fiscal_summary["Anulados"]["total"] += total
                    continue
                
                if "E31" in ecf_type or "Crédito Fiscal" in ecf_type:
                    fiscal_summary["E31"]["count"] += 1
                    fiscal_summary["E31"]["total"] += total
                    fiscal_summary["E31"]["itbis"] += itbis
                elif "E32" in ecf_type or "Consumo" in ecf_type:
                    fiscal_summary["E32"]["count"] += 1
                    fiscal_summary["E32"]["total"] += total
                    fiscal_summary["E32"]["itbis"] += itbis
                else:
                    fiscal_summary["Otros"]["count"] += 1
                    fiscal_summary["Otros"]["total"] += total
                    fiscal_summary["Otros"]["itbis"] += itbis

            # 4. Guardar cierre
            # Si hay descuadre de caja (diferencia), el estado del turno debe quedar como PENDING_AUDIT
            # para obligar a registrar la resolución de auditoría, sin importar quién cierre el turno.
            final_status = status
            if abs(difference) > 0.01:
                final_status = "PENDING_AUDIT"

            update_data = {
                "status": final_status,
                "closingTime": datetime.utcnow().isoformat(),
                "closingAmountExpected": closing_expected,
                "closingAmountDeclared": declared_amount,
                "difference": difference,
                
                # Detalle de arqueo
                "declaredCash": float(declared_data.get("declaredCash", 0.0)),
                "declaredCard": float(declared_data.get("declaredCard", 0.0)),
                "declaredTransfer": float(declared_data.get("declaredTransfer", 0.0)),
                "declaredUSD": float(declared_data.get("declaredUSD", 0.0)),
                "usdExchangeRate": usd_rate,
                "expectedCash": expected_cash,
                "expectedCard": expected_card,
                "expectedTransfer": expected_transfer,
                "expectedUSD": expected_usd,
                "differenceCash": diff_cash,
                "differenceCard": diff_card,
                "differenceTransfer": diff_transfer,
                "differenceUSD": diff_usd,
                "cashDenominations": declared_data.get("cashDenominations", {}),
                "usdDenominations": declared_data.get("usdDenominations", {}),
                "cardLoteNumber": declared_data.get("cardLoteNumber", ""),
                
                # Resumen fiscal
                "fiscalSummary": fiscal_summary
            }

            if supervisor_uid and final_status == "CLOSED":
                update_data["auditedByUserId"] = supervisor_uid
                update_data["auditedByUserEmail"] = supervisor_email
                update_data["auditedAt"] = datetime.utcnow().isoformat()

            shift_ref.update(update_data)

            # 5. Cambiar estado de la caja registradora física a CLOSED
            db_firestore.collection("users").document(owner_uid).collection(coll_regs).document(register_id).update({
                "status": "CLOSED"
            })

            # Retornar objeto completo actualizado
            result = shift_data.copy()
            result.update(update_data)
            return result
        except Exception as e:
            print(f"⚠️ Error al cerrar turno de caja: {e}")
            return None

    @classmethod
    def audit_cash_shift(cls, owner_uid, shift_id, audited_amount, supervisor_uid, supervisor_email, notes="", resolution_type=None, sandbox=True):
        """Audita y finaliza un turno de caja que estaba en PENDING_AUDIT."""
        if not firebase_initialized:
            return None
        try:
            coll_shifts = "sandbox_cash_shifts" if sandbox else "cash_shifts"
            shift_ref = db_firestore.collection("users").document(owner_uid).collection(coll_shifts).document(shift_id)
            shift_doc = shift_ref.get()
            if not shift_doc.exists:
                return None
            shift_data = shift_doc.to_dict()

            closing_expected = float(shift_data.get("closingAmountExpected", 0.0))
            difference = audited_amount - closing_expected

            update_data = {
                "status": "CLOSED",
                "closingAmountDeclared": audited_amount,
                "difference": difference,
                "auditedByUserId": supervisor_uid,
                "auditedByUserEmail": supervisor_email,
                "auditedAt": datetime.utcnow().isoformat(),
                "auditNotes": notes,
                "auditResolutionType": resolution_type
            }
            shift_ref.update(update_data)
            return update_data
        except Exception as e:
            print(f"⚠️ Error al auditar turno de caja: {e}")
            return None

    @classmethod
    def initiate_close_cash_shift(cls, owner_uid, shift_id, sandbox=True):
        """Cambia el estado de un turno a CLOSING mientras se realiza el arqueo."""
        if not firebase_initialized: return False
        try:
            coll_shifts = "sandbox_cash_shifts" if sandbox else "cash_shifts"
            shift_ref = db_firestore.collection("users").document(owner_uid).collection(coll_shifts).document(shift_id)
            shift_ref.update({"status": "CLOSING"})
            return True
        except Exception as e:
            print(f"⚠️ Error al iniciar cierre de caja: {e}")
            return False

    @classmethod
    def take_control_shift(cls, owner_uid, shift_id, supervisor_uid, supervisor_name, reason, comments, sandbox=True):
        """Transfiere el control del turno al supervisor bloqueando al cajero actual."""
        if not firebase_initialized: return False
        try:
            coll_shifts = "sandbox_cash_shifts" if sandbox else "cash_shifts"
            shift_ref = db_firestore.collection("users").document(owner_uid).collection(coll_shifts).document(shift_id)
            doc = shift_ref.get()
            if not doc.exists: return False
            shift_data = doc.to_dict()
            
            # Guardamos el cajero original si no existía el campo
            original_user = shift_data.get("originalOpenedByUserId", shift_data.get("openedByUserId"))
            
            update_data = {
                "openedByUserId": supervisor_uid,
                "openedByUserEmail": supervisor_name, # Guardamos el nombre o email en el mismo campo para mantener compatibilidad
                "originalOpenedByUserId": original_user,
                "takenOverBySupervisor": True,
                "takenOverReason": reason,
                "takenOverComments": comments,
                "takenOverAt": datetime.utcnow().isoformat()
            }
            shift_ref.update(update_data)
            return True
        except Exception as e:
            print(f"⚠️ Error al tomar control de turno: {e}")
            return False

    @classmethod
    def force_close_shift(cls, owner_uid, shift_id, supervisor_uid, supervisor_name, reason, comments, sandbox=True):
        """Cierra administrativamente un turno (ej. fallo eléctrico)."""
        if not firebase_initialized: return False
        try:
            coll_shifts = "sandbox_cash_shifts" if sandbox else "cash_shifts"
            coll_regs = "sandbox_cash_registers" if sandbox else "cash_registers"
            shift_ref = db_firestore.collection("users").document(owner_uid).collection(coll_shifts).document(shift_id)
            doc = shift_ref.get()
            if not doc.exists: return False
            shift_data = doc.to_dict()
            
            update_data = {
                "status": "FORCED_CLOSED",
                "closingTime": datetime.utcnow().isoformat(),
                "forcedClosedBy": supervisor_uid,
                "forcedClosedReason": reason,
                "forcedClosedComments": comments
            }
            shift_ref.update(update_data)
            
            # Liberar la caja
            register_id = shift_data.get("registerId")
            db_firestore.collection("users").document(owner_uid).collection(coll_regs).document(register_id).update({
                "status": "CLOSED"
            })
            return True
        except Exception as e:
            print(f"⚠️ Error al forzar cierre de turno: {e}")
            return False

    @classmethod
    def close_shift_under_review(cls, owner_uid, shift_id, supervisor_uid, supervisor_name, reason, comments, declared_amount=0.0, sandbox=True):
        """Cierra el turno bajo investigación (diferencias graves)."""
        # Aprovechamos el close_cash_shift normal pero le forzamos el estado a CLOSED_UNDER_REVIEW
        res = cls.close_cash_shift(owner_uid, shift_id, declared_amount, sandbox=sandbox, status="CLOSED_UNDER_REVIEW", supervisor_uid=supervisor_uid, supervisor_email=supervisor_name)
        if res:
            try:
                coll_shifts = "sandbox_cash_shifts" if sandbox else "cash_shifts"
                shift_ref = db_firestore.collection("users").document(owner_uid).collection(coll_shifts).document(shift_id)
                shift_ref.update({
                    "underReviewReason": reason,
                    "underReviewComments": comments
                })
            except Exception:
                pass
        return res

    @classmethod
    def reopen_shift(cls, owner_uid, shift_id, supervisor_uid, supervisor_name, reason, comments, sandbox=True):
        """Reabre un turno (solo del mismo día y no auditado)."""
        if not firebase_initialized: return False
        try:
            coll_shifts = "sandbox_cash_shifts" if sandbox else "cash_shifts"
            coll_regs = "sandbox_cash_registers" if sandbox else "cash_registers"
            shift_ref = db_firestore.collection("users").document(owner_uid).collection(coll_shifts).document(shift_id)
            doc = shift_ref.get()
            if not doc.exists: return False
            shift_data = doc.to_dict()
            
            # Validar mismo día
            closing_time_str = shift_data.get("closingTime")
            if not closing_time_str:
                return False
                
            closing_date = datetime.fromisoformat(closing_time_str.replace("Z", "+00:00")).date()
            if closing_date != datetime.utcnow().date():
                return False
                
            # Validar si ya fue auditado
            if shift_data.get("auditedAt"):
                return False

            update_data = {
                "status": "REOPENED", # Lo trataremos igual que OPEN en get_open_shift y otros
                "reopenedBy": supervisor_uid,
                "reopenedReason": reason,
                "reopenedComments": comments,
                "reopenedAt": datetime.utcnow().isoformat()
            }
            
            # Quitar datos de cierre
            shift_ref.update(update_data)
            
            # Ocupar la caja
            register_id = shift_data.get("registerId")
            db_firestore.collection("users").document(owner_uid).collection(coll_regs).document(register_id).update({
                "status": "OPEN"
            })
            
            return True
        except Exception as e:
            print(f"⚠️ Error al reabrir turno: {e}")
            return False

    @classmethod
    def transfer_shift(cls, owner_uid, shift_id, supervisor_uid, supervisor_name, new_cashier_uid, new_cashier_email, reason, comments, sandbox=True):
        """Transfiere un turno de un cajero a otro."""
        if not firebase_initialized: return False
        try:
            coll_shifts = "sandbox_cash_shifts" if sandbox else "cash_shifts"
            shift_ref = db_firestore.collection("users").document(owner_uid).collection(coll_shifts).document(shift_id)
            doc = shift_ref.get()
            if not doc.exists: return False
            shift_data = doc.to_dict()
            
            original_user = shift_data.get("originalOpenedByUserId", shift_data.get("openedByUserId"))
            
            update_data = {
                "openedByUserId": new_cashier_uid,
                "openedByUserEmail": new_cashier_email,
                "originalOpenedByUserId": original_user,
                "transferredBySupervisor": supervisor_uid,
                "transferredReason": reason,
                "transferredComments": comments,
                "transferredAt": datetime.utcnow().isoformat()
            }
            shift_ref.update(update_data)
            return True
        except Exception as e:
            print(f"⚠️ Error al transferir turno: {e}")
            return False

    @classmethod
    def log_shift_incident(cls, owner_uid, shift_id, supervisor_uid, supervisor_name, reason, comments, sandbox=True):
        """Registra una incidencia en el turno sin cerrarlo."""
        if not firebase_initialized: return False
        try:
            coll_shifts = "sandbox_cash_shifts" if sandbox else "cash_shifts"
            shift_ref = db_firestore.collection("users").document(owner_uid).collection(coll_shifts).document(shift_id)
            
            # Podemos agregarlo como un arreglo de incidencias
            incident = {
                "supervisorId": supervisor_uid,
                "supervisorName": supervisor_name,
                "reason": reason,
                "comments": comments,
                "date": datetime.utcnow().isoformat()
            }
            shift_ref.update({
                "incidents": firestore.ArrayUnion([incident])
            })
            return True
        except Exception as e:
            print(f"⚠️ Error al registrar incidencia: {e}")
            return False

    @classmethod
    def authorize_shift_extension(cls, owner_uid, shift_id, supervisor_uid, supervisor_name, reason, comments, sandbox=True):
        """Autoriza extender un turno de caja."""
        if not firebase_initialized: return False
        try:
            coll_shifts = "sandbox_cash_shifts" if sandbox else "cash_shifts"
            shift_ref = db_firestore.collection("users").document(owner_uid).collection(coll_shifts).document(shift_id)
            
            update_data = {
                "extensionAuthorizedBy": supervisor_uid,
                "extensionReason": reason,
                "extensionComments": comments,
                "extensionAuthorizedAt": datetime.utcnow().isoformat()
            }
            shift_ref.update(update_data)
            return True
        except Exception as e:
            print(f"⚠️ Error al autorizar extensión: {e}")
            return False

    @classmethod
    def get_cash_transactions(cls, owner_uid, shift_id, sandbox=True):
        """Retorna las transacciones asociadas a un turno de caja."""
        txs = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_cash_transactions" if sandbox else "cash_transactions"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name)\
                    .where(filter=firestore.FieldFilter("shiftId", "==", shift_id)).get()
                for doc in docs:
                    data = doc.to_dict()
                    txs.append({
                        "id": doc.id,
                        "shiftId": data.get("shiftId", ""),
                        "type": data.get("type", "SALE"),
                        "amount": float(data.get("amount", 0.0)),
                        "paymentMethod": data.get("paymentMethod", "Efectivo"),
                        "referenceId": data.get("referenceId", ""),
                        "notes": data.get("notes", ""),
                        "status": data.get("status", "ACTIVE"),
                        "date": serialize_field(data.get("date"))
                    })
                txs.sort(key=lambda x: x["date"] or "")
            except Exception as e:
                print(f"⚠️ Error al obtener transacciones de caja: {e}")
        return txs

    @classmethod
    def register_cash_transaction(cls, owner_uid, tx_dict, sandbox=True):
        """Registra una transacción manual o de venta en la caja registradora."""
        tx_id = tx_dict.get("id") or str(uuid.uuid4())
        tx_dict["id"] = tx_id
        tx_dict["ownerUID"] = owner_uid
        if "date" not in tx_dict or not tx_dict["date"]:
            tx_dict["date"] = datetime.utcnow().isoformat()
        tx_dict["date"] = serialize_field(tx_dict["date"])
        tx_dict["amount"] = float(tx_dict["amount"])

        if firebase_initialized:
            try:
                coll_name = "sandbox_cash_transactions" if sandbox else "cash_transactions"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(tx_id).set(tx_dict)
            except Exception as e:
                print(f"⚠️ Fallo al registrar transacción de caja: {e}")
                return None
        return tx_dict

    @classmethod
    def get_pending_consolidation_invoices(cls, owner_uid, shift_id, sandbox=True):
        """Retorna todas las facturas con status PENDING_CONSOLIDATION del turno indicado."""
        invoices = []
        if not firebase_initialized:
            return invoices
        try:
            coll_name = "sandbox_invoices" if sandbox else "invoices"
            docs = db_firestore.collection("users").document(owner_uid).collection(coll_name)\
                .where(filter=firestore.FieldFilter("posShiftId", "==", shift_id))\
                .where(filter=firestore.FieldFilter("status", "==", "PENDING_CONSOLIDATION")).get()
            for doc in docs:
                data = doc.to_dict()
                invoices.append({
                    "id": doc.id,
                    "invoiceNumber": data.get("invoiceNumber", ""),
                    "date": serialize_field(data.get("date")),
                    "total": float(data.get("total", 0.0)),
                    "subtotal": float(data.get("subtotal", 0.0)),
                    "totalITBIS": float(data.get("totalITBIS", 0.0)),
                    "items": data.get("items", []),
                    "paymentMethod": data.get("paymentMethod", "Efectivo"),
                })
        except Exception as e:
            print(f"⚠️ Error al obtener facturas pendientes de consolidación: {e}")
        return invoices

    @classmethod
    def mark_invoices_consolidated(cls, owner_uid, invoice_ids, encf_consolidado, invoice_number_consolidado, sandbox=True):
        """Marca masivamente facturas como Consolidada y guarda referencia al ENCF del consolidado."""
        if not firebase_initialized or not invoice_ids:
            return
        try:
            coll_name = "sandbox_invoices" if sandbox else "invoices"
            batch = db_firestore.batch()
            for inv_id in invoice_ids:
                ref = db_firestore.collection("users").document(owner_uid).collection(coll_name).document(inv_id)
                batch.update(ref, {
                    "status": "Consolidada",
                    "encfConsolidado": encf_consolidado,
                    "invoiceNumberConsolidado": invoice_number_consolidado,
                    "consolidadoAt": datetime.utcnow().isoformat(),
                    "isSyncedWithDGII": True,
                })
            batch.commit()
        except Exception as e:
            print(f"⚠️ Error al marcar facturas como consolidadas: {e}")

    @classmethod
    def update_cash_register_settings(cls, owner_uid, register_id, settings_dict, sandbox=True):
        """Actualiza campos de configuración de una caja registradora sin sobreescribir todo el documento."""
        if not firebase_initialized:
            return
        try:
            coll_name = "sandbox_cash_registers" if sandbox else "cash_registers"
            db_firestore.collection("users").document(owner_uid).collection(coll_name).document(register_id).update(settings_dict)
        except Exception as e:
            print(f"⚠️ Error al actualizar configuración de caja: {e}")

    @classmethod
    def save_payment_promise(cls, owner_uid, promise_id, promise_dict, sandbox=True):
        """Guarda o actualiza una promesa de pago en Firestore."""
        promise_dict["id"] = promise_id
        promise_dict["ownerUID"] = owner_uid
        if "createdAt" not in promise_dict or not promise_dict["createdAt"]:
            promise_dict["createdAt"] = datetime.utcnow().isoformat()
        
        if firebase_initialized:
            try:
                coll_name = "sandbox_payment_promises" if sandbox else "payment_promises"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(promise_id).set(promise_dict)
            except Exception as e:
                print(f"⚠️ Fallo al guardar promesa de pago: {e}")
        return promise_dict

    @classmethod
    def get_payment_promises(cls, owner_uid, sandbox=True):
        """Retorna todas las promesas de pago del owner."""
        promises = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_payment_promises" if sandbox else "payment_promises"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                for doc in docs:
                    data = doc.to_dict()
                    promises.append({
                        "id": doc.id,
                        "clientId": data.get("clientId", ""),
                        "clientName": data.get("clientName", ""),
                        "invoiceId": data.get("invoiceId", ""),
                        "invoiceNumber": data.get("invoiceNumber", ""),
                        "fechaPromesa": data.get("fechaPromesa", ""),
                        "montoPrometido": float(data.get("montoPrometido", 0.0)),
                        "estado": data.get("estado", "Pendiente"),
                        "notas": data.get("notas", ""),
                        "createdAt": data.get("createdAt", "")
                    })
                promises.sort(key=lambda x: x["fechaPromesa"] or "")
            except Exception as e:
                print(f"⚠️ Error al obtener promesas de pago: {e}")
        return promises

    # =========================================================================
    # GESTIÓN DE CONTRATOS (FACTURACIÓN RECURRENTE)
    # =========================================================================

    @classmethod
    def get_contract(cls, owner_uid, contract_id, sandbox=True):
        """Retorna un contrato específico por ID."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_contracts" if sandbox else "contracts"
                doc = db_firestore.collection("users").document(owner_uid).collection(coll_name).document(contract_id).get()
                if doc.exists:
                    data = doc.to_dict()
                    data["id"] = doc.id
                    data["amount"] = float(data.get("amount", 0.0))
                    return data
            except Exception as e:
                print(f"⚠️ Error al obtener contrato {contract_id}: {e}")
        return None

    @classmethod
    def get_contracts(cls, owner_uid, sandbox=True):
        """Retorna todos los contratos registrados del owner."""
        contracts = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_contracts" if sandbox else "contracts"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                for doc in docs:
                    data = doc.to_dict()
                    contracts.append({
                        "id": doc.id,
                        "contractNumber": data.get("contractNumber", ""),
                        "clientId": data.get("clientId", ""),
                        "clientName": data.get("clientName", ""),
                        "clientRNC": data.get("clientRNC", ""),
                        "amount": float(data.get("amount", 0.0)),
                        "recurrenceInterval": data.get("recurrenceInterval", "mensual"),
                        "status": data.get("status", "Activo"),
                        "startDate": data.get("startDate", ""),
                        "endDate": data.get("endDate", ""),
                        "nextBillingDate": data.get("nextBillingDate", ""),
                        "notes": data.get("notes", ""),
                        "createdAt": data.get("createdAt", ""),
                        "updatedAt": data.get("updatedAt", "")
                    })
                contracts.sort(key=lambda x: x["contractNumber"] or "")
            except Exception as e:
                print(f"⚠️ Error al obtener contratos: {e}")
        return contracts

    @classmethod
    def save_contract(cls, owner_uid, contract_id, contract_dict, sandbox=True):
        """Guarda o actualiza un contrato en Firestore."""
        contract_dict["id"] = contract_id
        contract_dict["ownerUID"] = owner_uid
        if "createdAt" not in contract_dict or not contract_dict["createdAt"]:
            contract_dict["createdAt"] = datetime.utcnow().isoformat()
        contract_dict["updatedAt"] = datetime.utcnow().isoformat()
        
        if firebase_initialized:
            try:
                coll_name = "sandbox_contracts" if sandbox else "contracts"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(contract_id).set(contract_dict)
            except Exception as e:
                print(f"⚠️ Fallo al guardar contrato: {e}")
        return contract_dict

    @classmethod
    def get_invoices_by_contract(cls, owner_uid, contract_id, sandbox=True):
        """Retorna todas las facturas generadas desde un contrato específico."""
        all_invoices = cls.get_invoices(owner_uid, sandbox=sandbox)
        return [inv for inv in all_invoices if inv.get('contractId') == contract_id]

    @classmethod
    def delete_contract(cls, owner_uid, contract_id, sandbox=True):
        """Elimina un contrato de Firestore."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_contracts" if sandbox else "contracts"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(contract_id).delete()
            except Exception as e:
                print(f"⚠️ Fallo al eliminar contrato: {e}")

    # =========================================================================
    # COMISIONES Y RENDIMIENTO
    # =========================================================================

    @classmethod
    def get_commission_settings(cls, owner_uid):
        """Retorna la configuración de comisiones de la empresa."""
        settings = {"percentage": 5.0, "payOn": "cobrada"}
        if firebase_initialized:
            try:
                doc = db_firestore.collection("users").document(owner_uid).collection("config").document("commission_settings").get()
                if doc.exists:
                    data = doc.to_dict()
                    settings.update(data)
            except Exception as e:
                print(f"⚠️ Error al obtener configuración de comisiones: {e}")
        return settings

    @classmethod
    def save_commission_settings(cls, owner_uid, settings_dict):
        """Guarda la configuración de comisiones."""
        if firebase_initialized:
            try:
                db_firestore.collection("users").document(owner_uid).collection("config").document("commission_settings").set(settings_dict)
            except Exception as e:
                print(f"⚠️ Error al guardar configuración de comisiones: {e}")
        return settings_dict

    @classmethod
    def get_sales_goals(cls, owner_uid):
        """Retorna las metas de venta mensuales de la empresa."""
        goals = {"monthlyGoal": 500000.0}
        if firebase_initialized:
            try:
                doc = db_firestore.collection("users").document(owner_uid).collection("config").document("sales_goals").get()
                if doc.exists:
                    goals.update(doc.to_dict())
            except Exception as e:
                print(f"⚠️ Error al obtener metas de venta: {e}")
        return goals

    @classmethod
    def save_sales_goals(cls, owner_uid, goals_dict):
        """Guarda las metas de venta de la empresa."""
        if firebase_initialized:
            try:
                db_firestore.collection("users").document(owner_uid).collection("config").document("sales_goals").set(goals_dict)
            except Exception as e:
                print(f"⚠️ Error al guardar metas de venta: {e}")
        return goals_dict

    # =========================================================================
    # GESTIÓN DOCUMENTAL CENTRALIZADA POR CLIENTE
    # =========================================================================

    @classmethod
    def get_client_documents(cls, owner_uid, client_id, sandbox=True):
        """Obtiene el historial documental de un cliente."""
        docs_list = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_clients" if sandbox else "clients"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).document(client_id).collection("documents").get()
                for doc in docs:
                    data = doc.to_dict()
                    docs_list.append({
                        "id": doc.id,
                        "documentType": data.get("documentType", "Contrato Legal"),
                        "name": data.get("name", ""),
                        "url": data.get("url", ""),
                        "uploadedBy": data.get("uploadedBy", "Sistema"),
                        "createdAt": data.get("createdAt", ""),
                        "notes": data.get("notes", "")
                    })
                docs_list.sort(key=lambda x: x["createdAt"] or "", reverse=True)
            except Exception as e:
                print(f"⚠️ Error al obtener documentos del cliente: {e}")
        return docs_list

    @classmethod
    def save_client_document(cls, owner_uid, client_id, doc_id, doc_dict, sandbox=True):
        """Guarda un documento clasificado para un cliente."""
        doc_dict["id"] = doc_id
        if "createdAt" not in doc_dict or not doc_dict["createdAt"]:
            doc_dict["createdAt"] = datetime.utcnow().isoformat()
        
        if firebase_initialized:
            try:
                coll_name = "sandbox_clients" if sandbox else "clients"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(client_id).collection("documents").document(doc_id).set(doc_dict)
            except Exception as e:
                print(f"⚠️ Fallo al respaldar documento de cliente: {e}")
        return doc_dict

    @classmethod
    def delete_client_document(cls, owner_uid, client_id, doc_id, sandbox=True):
        """Elimina un documento del cliente."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_clients" if sandbox else "clients"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(client_id).collection("documents").document(doc_id).delete()
            except Exception as e:
                print(f"⚠️ Fallo al borrar documento de cliente de Firestore: {e}")

    @classmethod
    def get_associated_companies(cls, uid):
        """Retorna una lista de todas las empresas asociadas al usuario (UID)."""
        companies = []
        if not firebase_initialized:
            return companies

        try:
            # 1. Obtener la propia empresa del usuario si es propietario e-Factura y lo tiene permitido
            profile = cls.get_user_profile(uid)
            if profile and profile.get("canManageOwnCompany", False):
                own_owner_uid = profile.get("uid")
                # Intentar obtener el nombre de su propia empresa
                own_company = cls.get_company_profile(own_owner_uid)
                companies.append({
                    "ownerUID": own_owner_uid,
                    "companyName": own_company.get("tradeName") or own_company.get("companyName", "Mi Empresa"),
                    "role": profile.get("role", "owner"),
                    "logoUrl": own_company.get("logoUrl"),
                    "logoBase64": own_company.get("logoBase64")
                })
        except Exception as e:
            print(f"⚠️ Error al obtener propia empresa: {e}")

        try:
            # 2. Obtener empresas desde la lista explícita associated_companies en el perfil de usuario
            doc = db_firestore.collection("users").document(uid).collection("config").document("user_profile").get()
            if doc.exists:
                data = doc.to_dict()
                assoc = data.get("associated_companies", [])
                for item in assoc:
                    owner_uid = item.get("ownerUID") if isinstance(item, dict) else item
                    if owner_uid and not any(c["ownerUID"] == owner_uid for c in companies):
                        comp_prof = cls.get_company_profile(owner_uid)
                        role = item.get("role", "employee") if isinstance(item, dict) else "employee"
                        companies.append({
                            "ownerUID": owner_uid,
                            "companyName": comp_prof.get("tradeName") or comp_prof.get("companyName", "Empresa Asociada"),
                            "role": role,
                            "logoUrl": comp_prof.get("logoUrl"),
                            "logoBase64": comp_prof.get("logoBase64")
                        })
        except Exception as e:
            print(f"⚠️ Error al leer associated_companies de Firestore: {e}")

        try:
            # 3. Descubrimiento automático buscando en las colecciones 'team'
            # Consulta de grupo de colecciones 'team' donde el miembro es el UID especificado
            team_docs = db_firestore.collection_group("team").where(filter=firestore.FieldFilter("uid", "==", uid)).get()
            for doc in team_docs:
                parent_ref = doc.reference.parent.parent
                if parent_ref:
                    owner_uid = parent_ref.id
                    if not any(c["ownerUID"] == owner_uid for c in companies):
                        comp_prof = cls.get_company_profile(owner_uid)
                        companies.append({
                            "ownerUID": owner_uid,
                            "companyName": comp_prof.get("tradeName") or comp_prof.get("companyName", "Empresa Colaboradora"),
                            "role": "employee",
                            "logoUrl": comp_prof.get("logoUrl"),
                            "logoBase64": comp_prof.get("logoBase64")
                        })
        except Exception as e:
            print(f"⚠️ Error en consulta de grupo de colección team: {e}. Iniciando búsqueda de contingencia sin índices...")
            try:
                # Búsqueda de contingencia sin índices usando el grupo de colecciones 'config'
                config_docs = db_firestore.collection_group("config").get()
                for doc in config_docs:
                    if doc.id == "user_profile":
                        parent_ref = doc.reference.parent.parent
                        if parent_ref:
                            owner_uid = parent_ref.id
                            # Evitar redundancia si ya fue agregada
                            if not any(c["ownerUID"] == owner_uid for c in companies):
                                team_doc = db_firestore.collection("users").document(owner_uid).collection("team").document(uid).get()
                                if team_doc.exists:
                                    comp_prof = cls.get_company_profile(owner_uid)
                                    companies.append({
                                        "ownerUID": owner_uid,
                                        "companyName": comp_prof.get("tradeName") or comp_prof.get("companyName", "Empresa Colaboradora"),
                                        "role": "employee",
                                        "logoUrl": comp_prof.get("logoUrl"),
                                        "logoBase64": comp_prof.get("logoBase64")
                                    })
            except Exception as ex:
                print(f"⚠️ Fallo crítico en búsqueda de contingencia de empresas: {ex}")

        return companies

    @classmethod
    def get_invoice_comments(cls, owner_uid, invoice_id, sandbox=True):
        """Retorna la lista de comentarios de una factura, ordenados por fecha de creación descendente."""
        comments = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_invoices" if sandbox else "invoices"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).document(invoice_id).collection("comments").get()
                for doc in docs:
                    data = doc.to_dict()
                    comments.append({
                        "id": doc.id,
                        "content": data.get("content", ""),
                        "createdBy": data.get("createdBy", ""),
                        "createdByName": data.get("createdByName", ""),
                        "createdByUid": data.get("createdByUid", ""),
                        "createdAt": serialize_field(data.get("createdAt")),
                        "attachmentUrl": data.get("attachmentUrl", ""),
                        "attachmentName": data.get("attachmentName", ""),
                        "edited": bool(data.get("edited", False)),
                        "editedAt": serialize_field(data.get("editedAt"))
                    })
                comments.sort(key=lambda x: x["createdAt"] or "", reverse=True)
            except Exception as e:
                print(f"⚠️ Error al obtener comentarios de factura desde Firestore: {e}")
        return comments

    @classmethod
    def save_invoice_comment(cls, owner_uid, invoice_id, comment_id, comment_dict, sandbox=True):
        """Guarda o actualiza un comentario de factura en Firestore."""
        comment_dict["id"] = comment_id
        if "createdAt" not in comment_dict or not comment_dict["createdAt"]:
            comment_dict["createdAt"] = datetime.utcnow().isoformat()
        
        comment_dict["createdAt"] = serialize_field(comment_dict.get("createdAt"))
        if comment_dict.get("editedAt"):
            comment_dict["editedAt"] = serialize_field(comment_dict.get("editedAt"))

        if firebase_initialized:
            try:
                coll_name = "sandbox_invoices" if sandbox else "invoices"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(invoice_id).collection("comments").document(comment_id).set(comment_dict)
            except Exception as e:
                print(f"⚠️ Fallo al guardar comentario de factura en Firestore: {e}")
        return comment_dict

    @classmethod
    def delete_invoice_comment(cls, owner_uid, invoice_id, comment_id, sandbox=True):
        """Elimina un comentario de factura en Firestore."""
        if firebase_initialized:
            try:
                coll_name = "sandbox_invoices" if sandbox else "invoices"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(invoice_id).collection("comments").document(comment_id).delete()
            except Exception as e:
                print(f"⚠️ Fallo al borrar comentario de factura de Firestore: {e}")

    @classmethod
    def create_user_notification(cls, user_uid, notification_dict):
        """Crea una notificación para un usuario en Firestore."""
        if firebase_initialized:
            try:
                notif_id = notification_dict.get("id") or str(uuid.uuid4())
                notification_dict["id"] = notif_id
                if "createdAt" not in notification_dict:
                    notification_dict["createdAt"] = datetime.utcnow().isoformat()
                notification_dict["read"] = False
                
                db_firestore.collection("users").document(user_uid).collection("notifications").document(notif_id).set(notification_dict)
                return True
            except Exception as e:
                print(f"⚠️ Fallo al guardar notificación de usuario en Firestore: {e}")
        return False

    @classmethod
    def get_user_notifications(cls, user_uid, limit=10):
        """Obtiene las últimas notificaciones del usuario de Firestore."""
        notifications = []
        if firebase_initialized:
            try:
                docs = db_firestore.collection("users").document(user_uid).collection("notifications").order_by("createdAt", direction="DESCENDING").limit(limit).get()
                for doc in docs:
                    data = doc.to_dict()
                    data["id"] = doc.id
                    notifications.append(data)
            except Exception as e:
                print(f"⚠️ Fallo al obtener notificaciones de usuario de Firestore: {e}")
        return notifications

    @classmethod
    def mark_user_notifications_read(cls, user_uid):
        """Marca todas las notificaciones pendientes del usuario como leídas."""
        if firebase_initialized:
            try:
                # Obtener notificaciones unread
                docs = db_firestore.collection("users").document(user_uid).collection("notifications").where("read", "==", False).get()
                batch = db_firestore.batch()
                for doc in docs:
                    batch.update(doc.reference, {"read": True})
                batch.commit()
                return True
            except Exception as e:
                print(f"⚠️ Fallo al marcar notificaciones como leídas en Firestore: {e}")
        return False

    @classmethod
    def get_resource_comments(cls, owner_uid, resource_type, resource_id, sandbox=True):
        """Retorna la lista de comentarios de cualquier recurso, ordenados por fecha descendente."""
        comments = []
        if firebase_initialized:
            try:
                coll_map = {
                    "invoices": "sandbox_invoices" if sandbox else "invoices",
                    "shifts": "sandbox_cash_shifts" if sandbox else "cash_shifts",
                    "expenses": "sandbox_expenses" if sandbox else "expenses",
                    "contracts": "sandbox_contracts" if sandbox else "contracts"
                }
                coll_name = coll_map.get(resource_type)
                if not coll_name:
                    return []
                    
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).document(resource_id).collection("comments").get()
                for doc in docs:
                    data = doc.to_dict()
                    comments.append({
                        "id": doc.id,
                        "content": data.get("content", ""),
                        "createdBy": data.get("createdBy", ""),
                        "createdByName": data.get("createdByName", ""),
                        "createdByUid": data.get("createdByUid", ""),
                        "createdAt": serialize_field(data.get("createdAt")),
                        "attachmentUrl": data.get("attachmentUrl", ""),
                        "attachmentName": data.get("attachmentName", ""),
                        "edited": bool(data.get("edited", False)),
                        "editedAt": serialize_field(data.get("editedAt")),
                        "reactions": data.get("reactions", {})
                    })
                comments.sort(key=lambda x: x["createdAt"] or "", reverse=True)
            except Exception as e:
                print(f"⚠️ Error al obtener comentarios de {resource_type} desde Firestore: {e}")
        return comments

    @classmethod
    def save_resource_comment(cls, owner_uid, resource_type, resource_id, comment_id, comment_dict, sandbox=True):
        """Guarda o actualiza un comentario de cualquier recurso en Firestore."""
        comment_dict["id"] = comment_id
        if "createdAt" not in comment_dict or not comment_dict["createdAt"]:
            comment_dict["createdAt"] = datetime.utcnow().isoformat()
        
        comment_dict["createdAt"] = serialize_field(comment_dict.get("createdAt"))
        if comment_dict.get("editedAt"):
            comment_dict["editedAt"] = serialize_field(comment_dict.get("editedAt"))

        if firebase_initialized:
            try:
                coll_map = {
                    "invoices": "sandbox_invoices" if sandbox else "invoices",
                    "shifts": "sandbox_cash_shifts" if sandbox else "cash_shifts",
                    "expenses": "sandbox_expenses" if sandbox else "expenses",
                    "contracts": "sandbox_contracts" if sandbox else "contracts"
                }
                coll_name = coll_map.get(resource_type)
                if coll_name:
                    db_firestore.collection("users").document(owner_uid).collection(coll_name).document(resource_id).collection("comments").document(comment_id).set(comment_dict)
            except Exception as e:
                print(f"⚠️ Fallo al guardar comentario de {resource_type} en Firestore: {e}")
        return comment_dict

    @classmethod
    def toggle_comment_reaction(cls, owner_uid, resource_type, resource_id, comment_id, user_uid, emoji, sandbox=True):
        """Alterna una reacción en un comentario."""
        if firebase_initialized:
            try:
                coll_map = {
                    "invoices": "sandbox_invoices" if sandbox else "invoices",
                    "shifts": "sandbox_cash_shifts" if sandbox else "cash_shifts",
                    "expenses": "sandbox_expenses" if sandbox else "expenses",
                    "contracts": "sandbox_contracts" if sandbox else "contracts"
                }
                coll_name = coll_map.get(resource_type)
                if coll_name:
                    doc_ref = db_firestore.collection("users").document(owner_uid).collection(coll_name).document(resource_id).collection("comments").document(comment_id)
                    
                    # Usar una transacción simple de lectura y escritura ya que arrayRemove y arrayUnion para diccionarios
                    # anidados puede ser verboso si no sabemos si el campo existe.
                    # Primero leemos:
                    doc = doc_ref.get()
                    if doc.exists:
                        data = doc.to_dict()
                        reactions = data.get("reactions", {})
                        if emoji not in reactions:
                            reactions[emoji] = []
                            
                        # Alternar el usuario
                        if user_uid in reactions[emoji]:
                            reactions[emoji].remove(user_uid)
                            # Si queda vacío, podríamos eliminar la llave, pero lo dejamos por consistencia
                        else:
                            reactions[emoji].append(user_uid)
                            
                        # Guardar de vuelta
                        doc_ref.update({"reactions": reactions})
                        return {"success": True, "reactions": reactions}
            except Exception as e:
                print(f"⚠️ Fallo al actualizar reacción de {resource_type} en Firestore: {e}")
        return {"success": False}

    @classmethod
    def delete_resource_comment(cls, owner_uid, resource_type, resource_id, comment_id, sandbox=True):
        """Elimina un comentario de cualquier recurso en Firestore."""
        if firebase_initialized:
            try:
                coll_map = {
                    "invoices": "sandbox_invoices" if sandbox else "invoices",
                    "shifts": "sandbox_cash_shifts" if sandbox else "cash_shifts",
                    "expenses": "sandbox_expenses" if sandbox else "expenses",
                    "contracts": "sandbox_contracts" if sandbox else "contracts"
                }
                coll_name = coll_map.get(resource_type)
                if coll_name:
                    db_firestore.collection("users").document(owner_uid).collection(coll_name).document(resource_id).collection("comments").document(comment_id).delete()
            except Exception as e:
                print(f"⚠️ Fallo al borrar comentario de {resource_type} de Firestore: {e}")



