"""Servicio de autorización de movimientos de caja (Fase 2).

Responsabilidades:
- Reglas de autorización por tipo de movimiento.
- Límites monetarios configurables por empresa y moneda.
- Validación de PIN de supervisor vinculada a una operación concreta y de un solo uso.
- Separación de funciones (SoD): el cajero no puede autorizar su propia operación.
"""
import hashlib
from datetime import datetime, timedelta, timezone

from app.services.db_service import (
    DatabaseService,
    CASH_SUPERVISOR_TYPES,
    CASH_LIMIT_TYPES,
    POS_CASH_CURRENCIES,
    normalize_cash_type,
    CashAuthorizationError,
    _money,
)
from app.services import db_service as _db


# Vigencia de una autorización reservada (PENDING). Pasado este tiempo, una
# autorización huérfana ya no puede consumirse (se rechaza como expirada).
# La limpieza física de documentos PENDING vencidos se delega a la política TTL
# de Firestore (configuración de despliegue, no de código).
AUTH_TTL_SECONDS = 300


class CashAuthorizationService:
    """Reglas y validación de autorizaciones de caja."""

    STATUS_PENDING = "PENDING"
    STATUS_CONSUMED = "CONSUMED"

    @staticmethod
    def _auth_coll_name(sandbox):
        return "sandbox_cash_authorizations" if sandbox else "cash_authorizations"

    @staticmethod
    def _to_utc(value):
        """Normaliza un valor de fecha a datetime UTC (o None si es inválido).

        Acepta: datetime (aware/naive), Firestore Timestamp (con to_datetime) y
        cadenas ISO legacy. Devuelve None si el valor es ausente o malformado.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        to_datetime = getattr(value, "to_datetime", None)
        if callable(to_datetime):
            try:
                dt = to_datetime()
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                return None
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                return None
        return None

    @staticmethod
    def _to_iso(value):
        dt = CashAuthorizationService._to_utc(value)
        return dt.isoformat() if dt else ""

    @classmethod
    def get_limits(cls, owner_uid, company_id, sandbox=True):
        return DatabaseService.get_pos_cash_limits(owner_uid, company_id=company_id, sandbox=sandbox)

    @staticmethod
    def movement_requires_supervisor(movement_type, amount, currency, limits=None):
        """Retorna (requires: bool, reason: str|None)."""
        movement_type = normalize_cash_type(movement_type)
        currency = (currency or "DOP").upper()
        limits = limits or {}
        if movement_type in CASH_SUPERVISOR_TYPES:
            return True, f"El movimiento {movement_type} requiere autorización de supervisor."
        if movement_type in CASH_LIMIT_TYPES:
            limit = (limits.get(movement_type) or {}).get(currency)
            if limit is not None and _money(amount) > _money(limit):
                return True, (
                    f"El movimiento {movement_type} supera el límite de "
                    f"{currency} {float(_money(limit)):,.2f}."
                )
        return False, None

    @staticmethod
    def context_signature(auth_request_id, movement_type, amount, currency, register_id, shift_id, performer_uid):
        canonical = "|".join([
            str(auth_request_id),
            normalize_cash_type(movement_type),
            f"{_money(amount):.2f}",
            (currency or "DOP").upper(),
            str(register_id or ""),
            str(shift_id or ""),
            str(performer_uid or ""),
        ])
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def authorize(cls, owner_uid, company_id, sandbox, performer_uid, supervisor_uid, pin,
                  auth_request_id, movement_type, amount, currency, register_id, shift_id):
        """Valida PIN + SoD y reserva la autorización (PENDING) de forma atómica.

        El PIN autoriza UNA operación concreta: el registro queda vinculado al
        contexto (tipo, monto, moneda, caja, sesión y usuario) y su documento se
        crea con `create()` (single-use). `createdAt` y `expiresAt` se guardan como
        datetime UTC (Firestore Timestamp).
        """
        movement_type = normalize_cash_type(movement_type)
        currency = (currency or "DOP").upper()
        if not auth_request_id:
            raise CashAuthorizationError("Falta el identificador de solicitud de autorización.")
        if supervisor_uid == performer_uid:
            raise CashAuthorizationError("No puede autorizar su propia operación.")

        pin_check = DatabaseService.validate_pos_supervisor_pin(owner_uid, company_id, supervisor_uid, pin)
        if not pin_check.get("valid"):
            raise CashAuthorizationError("PIN de supervisor inválido.")

        signature = cls.context_signature(
            auth_request_id, movement_type, amount, currency, register_id, shift_id, performer_uid
        )
        coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._auth_coll_name(sandbox))
        if coll is None:
            raise CashAuthorizationError("No se pudo registrar la autorización.")

        now = datetime.now(timezone.utc)
        record = {
            "id": auth_request_id,
            "status": cls.STATUS_PENDING,
            "contextSignature": signature,
            "movementType": movement_type,
            "amount": float(_money(amount)),
            "currency": currency,
            "registerId": register_id,
            "shiftId": shift_id,
            "performedBy": performer_uid,
            "authorizedByUid": supervisor_uid,
            "authorizedByName": pin_check.get("name"),
            "createdAt": now,
            "expiresAt": now + timedelta(seconds=AUTH_TTL_SECONDS),
        }
        try:
            coll.document(auth_request_id).create(record)
        except Exception as e:
            if DatabaseService._is_already_exists(e):
                raise CashAuthorizationError("La autorización ya fue utilizada.")
            raise CashAuthorizationError(f"No se pudo registrar la autorización: {e}")

        return {
            "name": pin_check.get("name"),
            "email": pin_check.get("email"),
            "uid": supervisor_uid,
            "signature": signature,
        }

    @classmethod
    def verify(cls, txn, owner_uid, company_id, sandbox, auth_request_id,
               movement_type, amount, currency, register_id, shift_id, performer_uid):
        """Lee y valida la autorización SIN escribir. Retorna (auth_data, ref).

        Uso: cuando la transacción necesita hacer más lecturas después de validar
        la autorización (p. ej. la transferencia), para respetar la regla de
        Firestore de "todas las lecturas antes de las escrituras".
        """
        coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._auth_coll_name(sandbox))
        if coll is None:
            raise CashAuthorizationError("No se pudo leer la autorización.")
        ref = coll.document(auth_request_id)
        snap = txn.get(ref)
        if not snap.exists:
            raise CashAuthorizationError("La autorización no existe.")
        data = snap.to_dict() or {}
        if data.get("status") != cls.STATUS_PENDING:
            raise CashAuthorizationError("La autorización ya fue consumida.")
        if data.get("authorizedByUid") == performer_uid:
            raise CashAuthorizationError("No puede autorizar su propia operación.")

        # Vigencia estricta: expiresAt debe existir y ser válido (datetime/timestamp).
        exp = cls._to_utc(data.get("expiresAt"))
        if exp is None:
            raise CashAuthorizationError("La autorización no tiene vigencia válida (expiresAt).")
        if datetime.now(timezone.utc) > exp:
            raise CashAuthorizationError("La autorización ha expirado.")

        expected = cls.context_signature(
            auth_request_id, movement_type, amount, currency, register_id, shift_id, performer_uid
        )
        if data.get("contextSignature") != expected:
            raise CashAuthorizationError("La autorización no coincide con la operación solicitada.")

        return {
            "name": data.get("authorizedByName", ""),
            "uid": data.get("authorizedByUid", ""),
            "authorizedAt": cls._to_iso(data.get("createdAt")),
        }, ref

    @classmethod
    def consume(cls, txn, owner_uid, company_id, sandbox, auth_request_id,
                movement_type, amount, currency, register_id, shift_id, performer_uid):
        """Valida y consume la autorización DENTRO de la transacción del movimiento.

        Verifica (existencia, PENDING, vigencia, contextSignature, SoD) y marca
        CONSUMED. Debe invocarse cuando no quedan más lecturas en la transacción;
        si hay lecturas posteriores, usar `verify()` + escritura manual del CONSUMED.
        """
        auth_data, ref = cls.verify(
            txn, owner_uid, company_id, sandbox, auth_request_id,
            movement_type, amount, currency, register_id, shift_id, performer_uid,
        )
        txn.update(ref, {"status": cls.STATUS_CONSUMED, "consumedAt": datetime.now(timezone.utc)})
        return auth_data
