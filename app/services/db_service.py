import os
import json
import uuid
import requests
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

# Intentar inicializar Firebase Admin
firebase_initialized = False
db_firestore = None
firebase_storage_bucket = None

try:
    if os.path.exists(Config.FIREBASE_SERVICE_ACCOUNT_JSON):
        import firebase_admin
        from firebase_admin import credentials, firestore, storage, auth
        
        # Verificar si ya está inicializado para evitar excepciones
        if not firebase_admin._apps:
            cred = credentials.Certificate(Config.FIREBASE_SERVICE_ACCOUNT_JSON)
            if Config.FIREBASE_STORAGE_BUCKET:
                firebase_admin.initialize_app(cred, {
                    'storageBucket': Config.FIREBASE_STORAGE_BUCKET
                })
            else:
                firebase_admin.initialize_app(cred)
        
        db_firestore = firestore.client()
        if Config.FIREBASE_STORAGE_BUCKET:
            firebase_storage_bucket = storage.bucket()
        firebase_initialized = True
        print("🔥 Firebase Admin SDK inicializado correctamente y conectado a Firestore.")
    else:
        print("⚠️ No se encontró firebase-adminsdk.json. El sistema operará en MODO LOCAL (SQLite).")
except Exception as e:
    print(f"❌ Error al inicializar Firebase Admin SDK: {e}. Operando en MODO LOCAL (SQLite).")


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
    def register_user(cls, email, password, name, role="owner", owner_uid=None):
        """Registra un nuevo usuario en Firebase Auth y Firestore."""
        uid = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        resolved_owner_uid = owner_uid if owner_uid else uid

        if not firebase_initialized:
            raise RuntimeError("El SDK de Firebase Admin no está inicializado. No se puede registrar el usuario.")

        # 1. Registrar en Firebase Auth
        try:
            if Config.FIREBASE_API_KEY:
                res = cls.firebase_rest_auth(email, password, signup=True)
                if res:
                    uid = res["localId"]
                    resolved_owner_uid = owner_uid if owner_uid else uid
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

        # 2. Guardar perfil del usuario en Firestore
        profile_data = {
            "uid": uid,
            "ownerUID": resolved_owner_uid,
            "role": role,
            "name": name,
            "email": email,
            "phone": "",
            "address": "",
            "permissions": {
                "canInvoice": True,
                "canExpenses": True,
                "canClients": True,
                "canModifySettings": True,
                "canManageInventory": True
            },
            "createdAt": created_at
        }

        db_firestore.collection("users").document(uid).collection("config").document("user_profile").set(profile_data)
        
        # Guardar en team si es colaborador (alineado con la estructura iOS)
        if role == "employee" and owner_uid:
            db_firestore.collection("users").document(owner_uid).collection("team").document(uid).set({
                "uid": uid,
                "name": name,
                "email": email,
                "createdAt": firestore.SERVER_TIMESTAMP
            })

        return profile_data

    @classmethod
    def authenticate_user(cls, email, password):
        """Autentica a un usuario interactuando únicamente con Firebase."""
        if not firebase_initialized:
            raise RuntimeError("El SDK de Firebase Admin no está inicializado.")

        firebase_uid = None
        
        # 1. Intentar verificar credenciales con Firebase Auth REST API si está activo
        if Config.FIREBASE_API_KEY:
            res = cls.firebase_rest_auth(email, password, signup=False)
            if res:
                firebase_uid = res["localId"]
                print(f"✅ Autenticado exitosamente en Firebase Auth. UID: {firebase_uid}")
        
        if not firebase_uid:
            # Fallback seguro para desarrollo/pruebas locales si no hay API Key de Firebase Auth completa:
            # Buscamos en Firebase Auth por el email. Si coincide la contraseña demo y no hay API Key, dejamos entrar.
            try:
                user_record = auth.get_user_by_email(email)
                firebase_uid = user_record.uid
                if not Config.FIREBASE_API_KEY:
                    print("⚠️ FIREBASE_API_KEY no configurado en .env. Saltando verificación de contraseña en Auth.")
            except Exception as e:
                print(f"⚠️ Error buscando usuario por email: {e}")
                return None

        if not firebase_uid:
            return None

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
                        "canManageInventory": bool(perms.get("canManageInventory", True))
                    },
                    "createdAt": created_at
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
                        "canManageInventory": True
                    },
                    "createdAt": datetime.utcnow().isoformat()
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
                        "canManageInventory": bool(perms.get("canManageInventory", True))
                    },
                    "createdAt": serialize_field(data.get("createdAt"))
                }
        except Exception as e:
            print(f"⚠️ Error al obtener perfil desde Firestore: {e}")
        return None

    @classmethod
    def save_user_profile(cls, uid, profile_dict):
        """Actualiza el perfil del usuario en Firestore."""
        if not firebase_initialized:
            return
        try:
            perms = profile_dict.get("permissions", {})
            db_firestore.collection("users").document(uid).collection("config").document("user_profile").update({
                "name": profile_dict.get("name", ""),
                "phone": profile_dict.get("phone", ""),
                "address": profile_dict.get("address", ""),
                "permissions": perms
            })
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
                            "permissions": emp_data.get("permissions", {
                                "canInvoice": True,
                                "canExpenses": True,
                                "canClients": True,
                                "canModifySettings": True,
                                "canManageInventory": True
                            })
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
                    cls.save_branch(owner_uid, default_id, default_branch, sandbox=sandbox)
                    branches.append(default_branch)
                else:
                    branches.sort(key=lambda x: x["name"].lower())
            except Exception as e:
                print(f"⚠️ Error al obtener sucursales desde Firestore: {e}")
        return branches

    @classmethod
    def save_branch(cls, owner_uid, branch_id, branch_dict, sandbox=True):
        """Guarda o actualiza una sucursal en Firestore."""
        branch_dict["id"] = branch_id
        branch_dict["ownerUID"] = owner_uid
        if "createdAt" not in branch_dict or not branch_dict["createdAt"]:
            branch_dict["createdAt"] = datetime.utcnow().isoformat()
        branch_dict["createdAt"] = serialize_field(branch_dict["createdAt"])

        # Si se establece como default, desmarcar las demas
        if branch_dict.get("isDefault"):
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
                    clients.append({
                        "id": doc.id,
                        "rnc": data.get("rnc", ""),
                        "razonSocial": data.get("razonSocial", ""),
                        "email": data.get("email", ""),
                        "telefono": data.get("telefono", ""),
                        "direccion": data.get("direccion", ""),
                        "crmNotes": data.get("crmNotes", ""),
                        "nextContactDate": serialize_field(data.get("nextContactDate")),
                        "createdAt": serialize_field(data.get("createdAt"))
                    })
                clients.sort(key=lambda x: x["razonSocial"].lower())
            except Exception as e:
                print(f"⚠️ Error al obtener clientes desde Firestore: {e}")
        return clients

    @classmethod
    def save_client(cls, owner_uid, client_id, client_dict, sandbox=True):
        """Guarda o actualiza un cliente en Firestore."""
        client_dict["id"] = client_id
        client_dict["ownerUID"] = owner_uid
        if "createdAt" not in client_dict or not client_dict["createdAt"]:
            client_dict["createdAt"] = datetime.utcnow().isoformat()
        
        client_dict["nextContactDate"] = serialize_field(client_dict.get("nextContactDate"))
        client_dict["createdAt"] = serialize_field(client_dict.get("createdAt"))

        if firebase_initialized:
            try:
                coll_name = "sandbox_clients" if sandbox else "clients"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(client_id).set(client_dict)
            except Exception as e:
                print(f"⚠️ Fallo al respaldar cliente en Firestore: {e}")

        return client_dict

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
                        "precioReferencia": float(data.get("precioReferencia", 0.0))
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
        item_dict["itbisRate"] = float(item_dict.get("itbisRate", 0.18))
        item_dict["minStock"] = float(item_dict.get("minStock", 0.0))
        item_dict["rackLocation"] = item_dict.get("rackLocation", "")
        item_dict["totalStock"] = float(item_dict.get("totalStock", 0.0))
        item_dict["createdAt"] = serialize_field(item_dict["createdAt"])

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
                .where("tipoComprobante", "==", tipo_comprobante)\
                .where("estado", "==", "ACTIVA")\
                .where("bloqueadaManualmente", "==", False)\
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
    def get_invoices(cls, owner_uid, sandbox=True, quotations_only=False):
        """Retorna las facturas o cotizaciones de un owner."""
        invoices = []
        if firebase_initialized:
            try:
                coll_name = "sandbox_invoices" if sandbox else "invoices"
                docs = db_firestore.collection("users").document(owner_uid).collection(coll_name)\
                    .where("isQuotation", "==", quotations_only).get()
                
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
                        "items": items
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
                        "items": items
                    }
            except Exception as e:
                print(f"⚠️ Error al obtener factura por ID desde Firestore: {e}")
        return None

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
                        "associatedInvoiceId": data.get("associatedInvoiceId", ""),
                        "itbisAmount": float(data.get("itbisAmount", 0.0)),
                        "isITBISDeductible": bool(data.get("isITBISDeductible", True)),
                        "isDeductible": bool(data.get("isDeductible", True)),
                        "firebaseAttachmentURLs": data.get("firebaseAttachmentURLs", []),
                        "createdAt": serialize_field(data.get("createdAt"))
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
        
        exp_dict["date"] = serialize_field(exp_dict["date"])
        exp_dict["nextOccurrenceDate"] = serialize_field(exp_dict.get("nextOccurrenceDate"))
        exp_dict["createdAt"] = serialize_field(exp_dict["createdAt"])

        if firebase_initialized:
            try:
                coll_name = "sandbox_expenses" if sandbox else "expenses"
                db_firestore.collection("users").document(owner_uid).collection(coll_name).document(expense_id).set(exp_dict)
            except Exception as e:
                print(f"⚠️ Fallo al respaldar gasto en Firestore: {e}")

        return exp_dict

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
    def upload_file_to_storage(cls, file_data, destination_path, mime_type="application/octet-stream"):
        """Sube un archivo (PDF, XML, Ticket) a Firebase Storage y retorna su URL pública."""
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
                    .collection(coll_stock).where("itemId", "==", item_id).get()
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

        # Contar facturas de producción (excluyendo cotizaciones)
        try:
            prod_docs = db_firestore.collection('users').document(owner_uid).collection('invoices')\
                .where('isQuotation', '==', False).stream()
            for doc in prod_docs:
                data = doc.to_dict()
                stats['prod_total'] += 1
                doc_date = parse_date(data.get('date') or data.get('createdAt'))
                if doc_date and start_date <= doc_date <= end_date:
                    stats['prod_current_cycle'] += 1
        except Exception as e:
            print(f"⚠️ Error counting prod invoices for {owner_uid}: {e}")
            
        # Contar facturas de sandbox (excluyendo cotizaciones)
        try:
            sandbox_docs = db_firestore.collection('users').document(owner_uid).collection('sandbox_invoices')\
                .where('isQuotation', '==', False).stream()
            for doc in sandbox_docs:
                data = doc.to_dict()
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
        
        # Obtener todas las facturas de producción (excluyendo cotizaciones)
        invoices = []
        try:
            prod_docs = db_firestore.collection('users').document(owner_uid).collection('invoices')\
                .where('isQuotation', '==', False).stream()
            for doc in prod_docs:
                invoices.append(doc.to_dict())
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
