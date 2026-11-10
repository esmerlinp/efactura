# app/services/audit_service.py
"""
Servicio Central de Auditoría del Sistema
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
import base64
import json
from datetime import datetime, timezone

from app.services.cache_service import CacheService

try:
    from app.services.db_service import db_firestore, firebase_initialized, _company_coll
except ImportError:
    db_firestore = None
    firebase_initialized = False
    _company_coll = None


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
MODULE_PRODUCTION_AGREEMENT = "Contrato de Producción"

# Acciones canónicas del contrato de producción
ACTION_AGREEMENT_VIEWED            = "AGREEMENT_VIEWED"
ACTION_AGREEMENT_ACCEPTED          = "AGREEMENT_ACCEPTED"
ACTION_AGREEMENT_ACKNOWLEDGED      = "AGREEMENT_ACKNOWLEDGED"
ACTION_AGREEMENT_REJECTED          = "AGREEMENT_REJECTED"
ACTION_AGREEMENT_VERSION_PUBLISHED = "AGREEMENT_VERSION_PUBLISHED"
ACTION_AGREEMENT_ACCESS_BLOCKED    = "AGREEMENT_ACCESS_BLOCKED"
ACTION_AGREEMENT_COMPANY_CHANGED   = "AGREEMENT_COMPANY_CHANGED"


class AuditService:
    """Servicio de Auditoría Central para el sistema."""

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
            user_agent: str = "",
            company_id=None) -> str:
        """
        Registra un evento de auditoría en Firestore.

        Returns:
            str: ID del log creado, o "" si falló silenciosamente.
        """
        if not firebase_initialized or not db_firestore:
            # Fallback: log local a archivo
            try:
                import os as _os
                log_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), 'logs')
                _os.makedirs(log_dir, exist_ok=True)
                log_path = _os.path.join(log_dir, 'security_audit.log')
                with open(log_path, 'a', encoding='utf-8') as _f:
                    _f.write(
                        f"[{datetime.now(timezone.utc).isoformat()}] "
                        f"ACCION={action} MODULO={module} "
                        f"USUARIO={performed_by_email or 'anónimo'} "
                        f"ENTIDAD={entity_label or entity_id}\n"
                    )
            except Exception:
                pass
            return ""

        try:
            log_id = str(uuid.uuid4())
            timestamp = datetime.now(timezone.utc).isoformat()

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

            _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name="audit_logs") \
                        .document(log_id) \
                        .set(log_data)

            if company_id:
                CacheService.invalidate_audit(company_id, sandbox=sandbox)

            return log_id

        except Exception as e:
            import logging
            logging.exception("[AuditService] Error al registrar evento")
            print(f"⚠️ [AuditService] Error al registrar evento: {e}")
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
    def get_entity_logs(cls, owner_uid: str, entity_id: str, company_id=None, sandbox=True) -> list:
        """
        Retorna logs de auditoría para una entidad específica (ej: una factura).
        Ordenados por timestamp descendente.
        """
        if not firebase_initialized or not db_firestore:
            return []
        cache = CacheService.get_cache()
        key = CacheService.domain_key("audit", company_id or owner_uid, sandbox, "entity", entity_id)
        cached = cache.get(key)
        if cached is not None:
            return cached
        try:
            docs = _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name="audit_logs") \
                                .where("entityId", "==", str(entity_id)) \
                                .get()
            logs = []
            for doc in docs:
                data = doc.to_dict()
                logs.append({
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
                    "userAgent": data.get("userAgent", ""),
                    "before": data.get("before"),
                    "after": data.get("after")
                })
            # Ordenar por timestamp descendente
            logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            cache.set(key, logs, timeout=30)
            return logs
        except Exception as e:
            import logging
            logging.exception(f"[AuditService] Error al obtener logs de entidad {entity_id}")
            print(f"⚠️ [AuditService] Error al obtener logs de entidad {entity_id}: {e}")
            return []

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
                 sandbox_filter: str = None,
                 company_id=None,
                 cursor=None) -> dict:
        """
        Retorna logs de auditoría paginados con filtros avanzados.

        Returns:
            dict: { logs: list, total: int, pages: int, current_page: int }
        """
        if not firebase_initialized or not db_firestore:
            return {"logs": [], "total": 0, "pages": 0, "current_page": page}

        try:
            sandbox_key = sandbox_filter or "all"
            sandbox_version = None if sandbox_filter in (None, "all") else sandbox_filter == "sandbox"
            cache = CacheService.get_cache()
            cache_key = CacheService.domain_key(
                "audit", company_id or owner_uid, sandbox_version,
                "list", page, per_page, module_filter or "", action_filter or "",
                tuple(user_filter or []), date_from or "", date_to or "",
                entity_filter or "", sandbox_key, cursor or "",
            )
            cached = CacheService.get_with_stats(cache_key)
            if cached is not None:
                return cached

            query = _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name="audit_logs") \
                                .order_by("timestamp", direction="DESCENDING")

            # Aplicar filtros exactos en Firestore para limitar lecturas.
            if module_filter and module_filter != "Todos":
                query = query.where("module", "==", module_filter)
            if action_filter and action_filter != "Todos":
                query = query.where("action", "==", action_filter)
            if sandbox_filter == "production":
                query = query.where("isSandbox", "==", False)
            elif sandbox_filter == "sandbox":
                query = query.where("isSandbox", "==", True)
            if date_from:
                query = query.where("timestamp", ">=", f"{date_from}T00:00:00")
            if date_to:
                query = query.where("timestamp", "<=", f"{date_to}T23:59:59")

            if cursor:
                try:
                    cursor_data = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
                    query = query.start_after({
                        "timestamp": cursor_data["timestamp"],
                        "__name__": cursor_data["id"],
                    })
                except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                    pass

            # Las búsquedas textuales parciales se mantienen en Python. El
            # límite impide que una consulta web escanee toda la auditoría.
            query = query.limit(per_page + 1)
            docs = query.get()
            all_logs = []

            for doc in docs:
                data = doc.to_dict()

                # Filtros en Python para campos que no soportan índices compuestos
                if user_filter:
                    matched = False
                    log_email = data.get("performedByEmail", "").lower()
                    log_name = data.get("performedBy", "").lower()
                    for u in user_filter:
                        u_lower = u.lower()
                        if u_lower in log_email or u_lower in log_name:
                            matched = True
                            break
                    if not matched:
                        continue

                if entity_filter:
                    entity_lower = entity_filter.lower()
                    if entity_lower not in data.get("entityLabel", "").lower() and \
                       entity_lower not in data.get("entityId", "").lower():
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

            paginated = all_logs[:per_page]
            next_cursor = None
            if len(all_logs) > per_page and paginated:
                next_cursor = base64.urlsafe_b64encode(json.dumps({
                    "timestamp": paginated[-1].get("timestamp", ""),
                    "id": paginated[-1]["id"],
                }).encode()).decode()

            result = {
                "logs": paginated,
                "total": None,
                "pages": None,
                "current_page": page,
                "next_cursor": next_cursor,
                "has_more": next_cursor is not None,
                "is_limited": next_cursor is not None,
            }
            CacheService.set_with_stats(cache_key, result, timeout=15)
            return result

        except Exception as e:
            import logging
            logging.exception("[AuditService] Error al obtener logs")
            print(f"⚠️ [AuditService] Error al obtener logs: {e}")
            return {"logs": [], "total": 0, "pages": 0, "current_page": page, "is_limited": False}

    @classmethod
    def get_log_detail(cls, owner_uid: str, log_id: str, company_id=None) -> dict:
        """Retorna un log específico con snapshots before/after completos."""
        if not firebase_initialized or not db_firestore:
            return {}
        cache = CacheService.get_cache()
        key = CacheService.domain_key("audit", company_id or owner_uid, False, "detail", log_id)
        cached = cache.get(key)
        if cached is not None:
            return cached
        try:
            doc = _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name="audit_logs") \
                              .document(log_id) \
                              .get()
            if doc.exists:
                result = doc.to_dict()
                cache.set(key, result, timeout=60)
                return result
        except Exception as e:
            print(f"⚠️ [AuditService] Error al obtener detalle del log: {e}")
        return {}

    @classmethod
    def export_to_csv_rows(cls, owner_uid: str, company_id=None, use_cache=False, **filter_kwargs) -> list:
        """
        Retorna todos los logs (sin paginación) como lista de dicts para CSV.
        Se pasan los mismos kwargs que get_logs (sin page/per_page).
        """
        rows = []
        cursor = None
        for _ in range(200):
            if use_cache:
                result = cls.get_logs(
                    owner_uid, page=1, per_page=500, company_id=company_id,
                    cursor=cursor, **filter_kwargs,
                )
            else:
                result = cls._query_logs_page(
                    owner_uid, company_id=company_id, per_page=500,
                    cursor=cursor, **filter_kwargs,
                )
            rows.extend(result.get("logs", []))
            if not result.get("has_more") or not result.get("next_cursor"):
                break
            cursor = result["next_cursor"]
        return rows

    @classmethod
    def _query_logs_page(cls, owner_uid, company_id=None, per_page=500, cursor=None,
                         module_filter=None, action_filter=None, user_filter=None,
                         date_from=None, date_to=None, entity_filter=None,
                         sandbox_filter=None):
        """Read one bounded page without using the web-list cache."""
        query = _company_coll(
            owner_uid=owner_uid, company_id=company_id, coll_name="audit_logs"
        ).order_by("timestamp", direction="DESCENDING")
        if module_filter and module_filter != "Todos":
            query = query.where("module", "==", module_filter)
        if action_filter and action_filter != "Todos":
            query = query.where("action", "==", action_filter)
        if sandbox_filter == "production":
            query = query.where("isSandbox", "==", False)
        elif sandbox_filter == "sandbox":
            query = query.where("isSandbox", "==", True)
        if date_from:
            query = query.where("timestamp", ">=", f"{date_from}T00:00:00")
        if date_to:
            query = query.where("timestamp", "<=", f"{date_to}T23:59:59")
        if cursor:
            try:
                cursor_data = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
                query = query.start_after({
                    "timestamp": cursor_data["timestamp"],
                    "__name__": cursor_data["id"],
                })
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                pass
        docs = query.limit(per_page + 1).get()
        rows = []
        for doc in docs:
            data = doc.to_dict()
            if user_filter:
                text = f"{data.get('performedByEmail', '')} {data.get('performedBy', '')}".lower()
                if not any(str(user).lower() in text for user in user_filter):
                    continue
            if entity_filter:
                text = f"{data.get('entityLabel', '')} {data.get('entityId', '')}".lower()
                if entity_filter.lower() not in text:
                    continue
            rows.append(data)
        has_extra = len(rows) > per_page
        rows = rows[:per_page]
        next_cursor = None
        if has_extra and rows:
            next_cursor = base64.urlsafe_b64encode(json.dumps({
                "timestamp": rows[-1].get("timestamp", ""),
                "id": rows[-1].get("id", ""),
            }).encode()).decode()
        return {"logs": rows, "next_cursor": next_cursor, "has_more": bool(next_cursor)}

    @classmethod
    def log_from_request(cls, owner_uid: str, action: str, module: str,
                         entity_id: str = "", entity_label: str = "",
                         user_session: dict = None,
                         before: dict = None, after: dict = None,
                         sandbox: bool = True,
                         flask_request=None, company_id=None) -> str:
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
            company_id=company_id,
        )

    @classmethod
    def get_user_recent_activity(cls, owner_uid: str, user_uid: str, limit: int = 10, company_id=None) -> list:
        """Retorna la actividad reciente de un usuario específico."""
        if not firebase_initialized or not db_firestore:
            return []
        cache = CacheService.get_cache()
        key = CacheService.domain_key(
            "audit", company_id or owner_uid, False, "user", user_uid, limit
        )
        cached = cache.get(key)
        if cached is not None:
            return cached
        try:
            docs = _company_coll(owner_uid=owner_uid, company_id=company_id, coll_name="audit_logs") \
                .where("performedByUID", "==", user_uid) \
                .order_by("timestamp", direction="DESCENDING") \
                .limit(limit) \
                .get()
            result = [{
                "id": d.id,
                "action": d.get("action"),
                "module": d.get("module"),
                "entityLabel": d.get("entityLabel", ""),
                "timestamp": d.get("timestamp", ""),
            } for d in docs if d.exists]
            cache.set(key, result, timeout=30)
            return result
        except Exception as e:
            print(f"⚠️ [AuditService] Error al obtener actividad de usuario: {e}")
            return []
