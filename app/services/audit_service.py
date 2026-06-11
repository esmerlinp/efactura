# app/services/audit_service.py
"""
Servicio Central de Auditoría — e-Factura
==========================================
Registra todas las transacciones realizadas por los usuarios del sistema
en Firestore bajo: users/{ownerUID}/audit_logs/{log_id}

Campos registrados por evento:
  - id, ownerUID, action, module, entityId, entityLabel
  - performedBy, performedByUID, performedByEmail
  - before (snapshot antes), after (snapshot después)
  - ipAddress, userAgent, timestamp, isSandbox
"""
import uuid
import traceback
from datetime import datetime

try:
    from app.services.db_service import db_firestore, firebase_initialized
except ImportError:
    db_firestore = None
    firebase_initialized = False


# Acciones canónicas del sistema de auditoría
ACTION_CREATE = "CREATE"
ACTION_UPDATE = "UPDATE"
ACTION_DELETE = "DELETE"
ACTION_VIEW   = "VIEW"
ACTION_LOGIN  = "LOGIN"
ACTION_LOGOUT = "LOGOUT"
ACTION_EXPORT = "EXPORT"

# Módulos canónicos
MODULE_FACTURAS      = "Facturas"
MODULE_COTIZACIONES  = "Cotizaciones"
MODULE_GASTOS        = "Gastos"
MODULE_CLIENTES      = "Clientes"
MODULE_CRM           = "CRM Interacciones"
MODULE_ITEMS         = "Catálogo / Ítems"
MODULE_EMPRESA       = "Configuración Empresa"
MODULE_USUARIOS      = "Usuarios y Permisos"
MODULE_POS           = "Punto de Venta (POS)"
MODULE_CXC           = "Cuentas por Cobrar"
MODULE_CXP           = "Cuentas por Pagar"
MODULE_CONTRATOS     = "Contratos / Recurrencia"
MODULE_NOTAS         = "Notas Internas"
MODULE_SECUENCIAS    = "Secuencias Fiscales"
MODULE_AUTH          = "Autenticación"
MODULE_DOCUMENTOS    = "Documentos de Cliente"


class AuditService:
    """Servicio de Auditoría Central para e-Factura."""

    @classmethod
    def log(cls,
            owner_uid: str,
            action: str,
            module: str,
            entity_id: str = "",
            entity_label: str = "",
            performed_by_name: str = "Sistema",
            performed_by_uid: str = "",
            performed_by_email: str = "",
            before: dict = None,
            after: dict = None,
            sandbox: bool = True,
            ip_address: str = "",
            user_agent: str = "") -> str:
        """
        Registra un evento de auditoría en Firestore.

        Returns:
            str: ID del log creado, o "" si falló silenciosamente.
        """
        if not firebase_initialized or not db_firestore:
            return ""

        try:
            log_id = str(uuid.uuid4())
            timestamp = datetime.utcnow().isoformat()

            log_data = {
                "id": log_id,
                "ownerUID": owner_uid,
                "action": action,
                "module": module,
                "entityId": str(entity_id) if entity_id else "",
                "entityLabel": str(entity_label)[:200] if entity_label else "",
                "performedBy": performed_by_name,
                "performedByUID": performed_by_uid,
                "performedByEmail": performed_by_email,
                "before": cls._sanitize_snapshot(before),
                "after": cls._sanitize_snapshot(after),
                "ipAddress": ip_address,
                "userAgent": user_agent[:300] if user_agent else "",
                "timestamp": timestamp,
                "isSandbox": bool(sandbox),
            }

            db_firestore.collection("users") \
                        .document(owner_uid) \
                        .collection("audit_logs") \
                        .document(log_id) \
                        .set(log_data)

            return log_id

        except Exception as e:
            # El log de auditoría NUNCA debe interrumpir la operación principal
            print(f"⚠️ [AuditService] Error al registrar evento: {e}")
            traceback.print_exc()
            return ""

    @classmethod
    def _sanitize_snapshot(cls, data: dict) -> dict:
        """Sanitiza el snapshot eliminando campos binarios grandes y serializando fechas."""
        if not data:
            return {}
        result = {}
        EXCLUDED_KEYS = {"certificateContent", "logoBase64", "password", "token"}
        for key, val in data.items():
            if key in EXCLUDED_KEYS:
                result[key] = "[OMITIDO POR SEGURIDAD]"
            elif hasattr(val, "isoformat"):
                result[key] = val.isoformat()
            elif isinstance(val, dict):
                result[key] = cls._sanitize_snapshot(val)
            elif isinstance(val, (list, tuple)):
                result[key] = [
                    cls._sanitize_snapshot(v) if isinstance(v, dict) else str(v)
                    for v in val
                ]
            else:
                try:
                    result[key] = val
                except Exception:
                    result[key] = str(val)
        return result

    @classmethod
    def get_logs(cls,
                 owner_uid: str,
                 page: int = 1,
                 per_page: int = 25,
                 module_filter: str = None,
                 action_filter: str = None,
                 user_filter: str = None,
                 date_from: str = None,
                 date_to: str = None,
                 entity_filter: str = None,
                 sandbox_filter: str = None) -> dict:
        """
        Retorna logs de auditoría paginados con filtros avanzados.

        Returns:
            dict: { logs: list, total: int, pages: int, current_page: int }
        """
        if not firebase_initialized or not db_firestore:
            return {"logs": [], "total": 0, "pages": 0, "current_page": page}

        try:
            query = db_firestore.collection("users") \
                                .document(owner_uid) \
                                .collection("audit_logs") \
                                .order_by("timestamp", direction="DESCENDING")

            # Aplicar filtros directos de Firestore donde es posible
            if module_filter and module_filter != "Todos":
                query = query.where("module", "==", module_filter)

            if action_filter and action_filter != "Todos":
                query = query.where("action", "==", action_filter)

            # Ejecutar query y obtener todos (paginación manual para filtros combinados)
            docs = query.get()
            all_logs = []

            for doc in docs:
                data = doc.to_dict()

                # Filtros en Python para campos que no soportan índices compuestos
                if user_filter:
                    user_lower = user_filter.lower()
                    name_match = user_lower in data.get("performedBy", "").lower()
                    email_match = user_lower in data.get("performedByEmail", "").lower()
                    if not (name_match or email_match):
                        continue

                if entity_filter:
                    entity_lower = entity_filter.lower()
                    if entity_lower not in data.get("entityLabel", "").lower() and \
                       entity_lower not in data.get("entityId", "").lower():
                        continue

                if date_from:
                    try:
                        ts = data.get("timestamp", "")[:10]
                        if ts < date_from:
                            continue
                    except Exception:
                        pass

                if date_to:
                    try:
                        ts = data.get("timestamp", "")[:10]
                        if ts > date_to:
                            continue
                    except Exception:
                        pass

                if sandbox_filter == "production":
                    if data.get("isSandbox", True):
                        continue
                elif sandbox_filter == "sandbox":
                    if not data.get("isSandbox", True):
                        continue

                all_logs.append({
                    "id": data.get("id", doc.id),
                    "action": data.get("action", ""),
                    "module": data.get("module", ""),
                    "entityId": data.get("entityId", ""),
                    "entityLabel": data.get("entityLabel", ""),
                    "performedBy": data.get("performedBy", ""),
                    "performedByEmail": data.get("performedByEmail", ""),
                    "timestamp": data.get("timestamp", ""),
                    "isSandbox": data.get("isSandbox", True),
                    "ipAddress": data.get("ipAddress", ""),
                })

            total = len(all_logs)
            total_pages = max(1, (total + per_page - 1) // per_page)
            page = max(1, min(page, total_pages))
            offset = (page - 1) * per_page
            paginated = all_logs[offset:offset + per_page]

            return {
                "logs": paginated,
                "total": total,
                "pages": total_pages,
                "current_page": page,
            }

        except Exception as e:
            print(f"⚠️ [AuditService] Error al obtener logs: {e}")
            traceback.print_exc()
            return {"logs": [], "total": 0, "pages": 0, "current_page": page}

    @classmethod
    def get_log_detail(cls, owner_uid: str, log_id: str) -> dict:
        """Retorna un log específico con snapshots before/after completos."""
        if not firebase_initialized or not db_firestore:
            return {}
        try:
            doc = db_firestore.collection("users") \
                              .document(owner_uid) \
                              .collection("audit_logs") \
                              .document(log_id) \
                              .get()
            if doc.exists:
                return doc.to_dict()
        except Exception as e:
            print(f"⚠️ [AuditService] Error al obtener detalle del log: {e}")
        return {}

    @classmethod
    def export_to_csv_rows(cls, owner_uid: str, **filter_kwargs) -> list:
        """
        Retorna todos los logs (sin paginación) como lista de dicts para CSV.
        Se pasan los mismos kwargs que get_logs (sin page/per_page).
        """
        result = cls.get_logs(owner_uid, page=1, per_page=99999, **filter_kwargs)
        return result.get("logs", [])

    @classmethod
    def log_from_request(cls, owner_uid: str, action: str, module: str,
                         entity_id: str = "", entity_label: str = "",
                         user_session: dict = None,
                         before: dict = None, after: dict = None,
                         sandbox: bool = True,
                         flask_request=None) -> str:
        """
        Helper conveniente: extrae datos del usuario y request automáticamente.
        Úsalo desde las rutas Flask pasando session['user'] y request de Flask.
        """
        from flask import request as _req
        req = flask_request or _req

        ip = ""
        ua = ""
        try:
            ip = req.headers.get("X-Forwarded-For", req.remote_addr or "")
            ua = req.headers.get("User-Agent", "")
        except Exception:
            pass

        user = user_session or {}
        return cls.log(
            owner_uid=owner_uid,
            action=action,
            module=module,
            entity_id=entity_id,
            entity_label=entity_label,
            performed_by_name=user.get("name", "Desconocido"),
            performed_by_uid=user.get("uid", ""),
            performed_by_email=user.get("email", ""),
            before=before,
            after=after,
            sandbox=sandbox,
            ip_address=ip,
            user_agent=ua,
        )
