"""Servicio de entrega de fondos (Fase 4.2) — CashDelivery.

Registra la transferencia física de efectivo (DOP y/o USD) del cajero a un responsable
receptor, creando conjuntamente su(s) movimiento(s) `CASH_DROP` y su registro `CashDelivery`
en una única transacción Firestore.

Autorización de recepción (single-use con vigencia):
  1. `create_receipt_authorization` — emite una autorización PENDING (id seguro, vinculada a
     deliveryId/receiverUid/companyId/sandbox, con `createdAt` y `expiresAt`).
  2. `confirm_receipt` — consume la autorización (PENDING→CONSUMED) y transiciona la entrega
     (PENDING_RECEIPT→RECEIVED) en UNA transacción, validando vigencia, propiedad y PIN.

PIN de recepción: PBKDF2-SHA256 (100k iteraciones) + salt aleatorio + `hmac.compare_digest`;
contador de intentos persistido y actualizado atómicamente (bloqueo no reiniciable).
"""
import hashlib
import hmac
import math
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from app.services.db_service import (
    DatabaseService,
    firebase_initialized,
    CASH_TYPE_CASH_DROP,
    CASH_LOCK_ACTIVE,
    CashShiftLockError,
    _money,
    _money_round,
)
from app.services import db_service as _db


DELIVERY_PENDING_RECEIPT = "PENDING_RECEIPT"
DELIVERY_RECEIVED = "RECEIVED"
DELIVERY_PENDING_RECONCILIATION = "PENDING_RECONCILIATION"
DELIVERY_RECONCILED = "RECONCILED"
DELIVERY_UNDER_REVIEW = "UNDER_REVIEW"

RECEPTION_PIN_MAX_ATTEMPTS = 5
RECEPTION_PIN_LOCK_SECONDS = 300
RECEPTION_PIN_ITERATIONS = 100_000

RECEIPT_AUTH_TTL_SECONDS = 300

DOP_DENOMINATIONS = {2000, 1000, 500, 200, 100, 50, 25, 10, 5, 1}
USD_DENOMINATIONS = {100, 50, 20, 10, 5, 1}


class CashDeliveryError(Exception):
    """Error de negocio en una entrega de fondos (PIN, SoD, cantidad, etc.)."""


def _pbkdf2(pin, salt_hex):
    salt = bytes.fromhex(salt_hex)
    return hashlib.pbkdf2_hmac("sha256", str(pin).encode("utf-8"), salt, RECEPTION_PIN_ITERATIONS).hex()


def _secure_equals(a, b):
    return hmac.compare_digest(str(a).encode(), str(b).encode())


def _canon(value):
    """Representación canónica (sin ceros triviales ni notación científica) para firmar."""
    return format(_money(value).normalize(), 'f')


def _parse_denom_key(k):
    if isinstance(k, bool):
        raise CashDeliveryError("Denominación inválida.")
    if isinstance(k, int):
        return k
    if isinstance(k, float):
        if not k.is_integer():
            raise CashDeliveryError("Denominación fraccionaria no permitida.")
        return int(k)
    if isinstance(k, str):
        s = k.strip()
        if not s.isdigit():
            raise CashDeliveryError("Denominación inválida.")
        return int(s)
    raise CashDeliveryError("Denominación inválida.")


def _parse_denom_count(v):
    if isinstance(v, bool):
        raise CashDeliveryError("Cantidad de denominación inválida.")
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if not v.is_integer():
            raise CashDeliveryError("Cantidad de denominación fraccionaria no permitida.")
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if not s.isdigit():
            raise CashDeliveryError("Cantidad de denominación inválida.")
        return int(s)
    raise CashDeliveryError("Cantidad de denominación inválida.")


class CashDeliveryService:
    """Registro y recepción de entregas físicas de efectivo."""

    @staticmethod
    def _coll_name(sandbox):
        return "sandbox_cash_deliveries" if sandbox else "cash_deliveries"

    @staticmethod
    def _pin_coll_name(sandbox):
        return "sandbox_cash_reception_pins" if sandbox else "cash_reception_pins"

    @staticmethod
    def _auth_coll_name(sandbox):
        return "sandbox_cash_receipt_authorizations" if sandbox else "cash_receipt_authorizations"

    @staticmethod
    def _derive_delivery_id(company_id, sandbox, idempotency_key):
        return "dlv-" + hashlib.sha256(f"{company_id}:{1 if sandbox else 0}:{idempotency_key}".encode()).hexdigest()[:24]

    @classmethod
    def _normalize_denominations(cls, denominations, dop_amount, usd_amount):
        """Valida y normaliza las denominaciones (claves/cantidades enteras, coherentes)."""
        if denominations is None:
            return {"dop": {}, "usd": {}}
        if not isinstance(denominations, dict):
            raise CashDeliveryError("Las denominaciones deben ser un objeto.")
        result = {}
        for cur, allowed, amount in (("dop", DOP_DENOMINATIONS, dop_amount), ("usd", USD_DENOMINATIONS, usd_amount)):
            d = denominations.get(cur)
            if d is None or d == {}:
                result[cur] = {}
                continue
            if not isinstance(d, dict):
                raise CashDeliveryError(f"Las denominaciones de {cur.upper()} deben ser un objeto.")
            total = _money(0)
            norm = {}
            for k, v in d.items():
                denom = _parse_denom_key(k)
                if denom not in allowed:
                    raise CashDeliveryError(f"Denominación desconocida para {cur.upper()}: {k}")
                count = _parse_denom_count(v)
                if count < 0:
                    raise CashDeliveryError("Cantidad de denominación negativa no permitida.")
                norm[str(denom)] = count
                total += _money(denom) * _money(count)
            if abs(total - _money(amount)) > _money("0.01"):
                raise CashDeliveryError(f"El desglose de {cur.upper()} no coincide con el importe declarado.")
            result[cur] = norm
        return result

    @staticmethod
    def _canonical_denominations(normalized):
        def norm(cur):
            d = normalized.get(cur) or {}
            return "{" + ",".join(f"{k}:{v}" for k, v in sorted(d.items(), key=lambda x: int(x[0]))) + "}"
        return f"dop={norm('dop')};usd={norm('usd')}"

    @classmethod
    def _content_signature(cls, company_id, sandbox, shift_id, register_id, dop, usd, rate, denoms):
        canonical = "|".join([
            str(company_id), str(1 if sandbox else 0), str(shift_id), str(register_id),
            f"dop={_canon(dop)}", f"usd={_canon(usd)}", f"rate={_canon(rate)}",
            cls._canonical_denominations(denoms),
        ])
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_amounts(dop, usd, rate):
        if dop < 0 or usd < 0:
            raise CashDeliveryError("Los importes no pueden ser negativos.")
        if dop <= 0 and usd <= 0:
            raise CashDeliveryError("La entrega debe tener al menos una moneda con monto mayor a cero.")
        if usd > 0:
            if not (rate > 0) or not math.isfinite(float(rate)):
                raise CashDeliveryError("El tipo de cambio USD debe ser positivo y finito.")

    @classmethod
    def _build_drops(cls, delivery_id, shift_id, register_id, amounts, delivered_by_name, delivered_by_uid, now_iso):
        drops = []
        for cur, amt, suffix in (("DOP", amounts["dop"], "dop"), ("USD", amounts["usd"], "usd")):
            if amt > 0:
                drops.append({
                    "id": f"dlv-{delivery_id}-drop-{suffix}",
                    "shiftId": shift_id, "registerId": register_id,
                    "type": CASH_TYPE_CASH_DROP, "amount": amt, "currency": cur,
                    "paymentMethod": "Efectivo", "reason": f"Entrega de efectivo {delivery_id[:8]}",
                    "referenceId": delivery_id, "performedBy": delivered_by_name,
                    "performedByUid": delivered_by_uid, "status": "ACTIVE",
                    "date": now_iso, "idempotencyKey": f"delivery-{delivery_id}",
                })
        return drops

    @classmethod
    def register_delivery(cls, owner_uid, company_id, sandbox, shift_id, register_id, amounts,
                          usd_rate, denominations, delivered_by_uid, delivered_by_name,
                          notes, idempotency_key):
        if not firebase_initialized:
            raise CashDeliveryError("Firebase no está inicializado.")
        if not idempotency_key:
            raise CashDeliveryError("Falta la clave de idempotencia.")
        if not shift_id or not register_id:
            raise CashDeliveryError("Turno y caja son obligatorios.")

        # Normalizar UNA sola vez (validación, firma y persistencia usan el mismo valor).
        dop = _money_round(amounts.get("dop", 0))
        usd = _money_round(amounts.get("usd", 0))
        rate = _money(usd_rate or 0)
        cls._validate_amounts(dop, usd, rate)
        denoms = cls._normalize_denominations(denominations, dop, usd)

        delivery_id = cls._derive_delivery_id(company_id, sandbox, idempotency_key)
        content_sig = cls._content_signature(company_id, sandbox, shift_id, register_id, dop, usd, rate, denoms)

        deliveries_coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._coll_name(sandbox))
        txs_coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid,
                                     coll_name="sandbox_cash_transactions" if sandbox else "cash_transactions")
        locks_coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid,
                                       coll_name=DatabaseService._cash_lock_coll_name(sandbox))
        if deliveries_coll is None or txs_coll is None or locks_coll is None:
            raise CashDeliveryError("No se pudo resolver las colecciones de entrega.")

        delivery_ref = deliveries_coll.document(delivery_id)
        lock_ref = locks_coll.document(register_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        amounts_norm = {"dop": dop, "usd": usd}
        drops = cls._build_drops(delivery_id, shift_id, register_id, amounts_norm,
                                 delivered_by_name, delivered_by_uid, now_iso)

        def _run(txn):
            snap = txn.get(delivery_ref)
            if snap.exists:
                existing = snap.to_dict() or {}
                if existing.get("contentSignature") == content_sig:
                    return {"already": True, "delivery": existing}
                raise CashDeliveryError("La clave de idempotencia ya fue usada con parámetros distintos.")

            lock_snap = txn.get(lock_ref)
            if not lock_snap.exists:
                raise CashShiftLockError("La caja no tiene lock de ocupación.")
            lock = lock_snap.to_dict() or {}
            if lock.get("status") != CASH_LOCK_ACTIVE or lock.get("shiftId") != shift_id:
                raise CashShiftLockError("La caja no está activa para esta sesión.")

            for drop in drops:
                txn.set(txs_coll.document(drop["id"]), drop)

            delivery = {
                "id": delivery_id, "idempotencyKey": idempotency_key, "contentSignature": content_sig,
                "ownerUID": owner_uid, "companyId": company_id, "shiftId": shift_id, "registerId": register_id,
                "cashDropTransactionIds": [d["id"] for d in drops],
                "deliveredBy": {"uid": delivered_by_uid, "name": delivered_by_name},
                "receivedBy": None, "receivedAt": "", "receivedPinVerified": False,
                "amounts": amounts_norm, "usdRate": float(rate),
                "denominations": denoms, "difference": None, "status": DELIVERY_PENDING_RECEIPT,
                "notes": notes or "", "createdAt": now_iso, "updatedAt": now_iso,
                "history": [{"event": "CREATED", "by": delivered_by_uid, "at": now_iso,
                             "fromStatus": None, "toStatus": DELIVERY_PENDING_RECEIPT, "notes": notes or ""}],
            }
            txn.set(delivery_ref, delivery)
            txn.update(lock_ref, {"updatedAt": now_iso})
            return {"already": False, "delivery": delivery}

        try:
            return DatabaseService._run_in_transaction(_run)
        except (CashDeliveryError, CashShiftLockError):
            raise
        except Exception as e:
            raise CashDeliveryError(f"Error al registrar la entrega: {e}")

    @classmethod
    def set_reception_pin(cls, owner_uid, company_id, sandbox, uid, pin):
        if not pin or len(str(pin)) < 4:
            raise CashDeliveryError("El PIN debe tener al menos 4 caracteres.")
        pins_coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._pin_coll_name(sandbox))
        if pins_coll is None:
            raise CashDeliveryError("No se pudo resolver la colección de PIN.")
        now = datetime.now(timezone.utc).isoformat()
        salt = secrets.token_hex(16)
        pins_coll.document(uid).set({
            "uid": uid, "pinSalt": salt, "pinHash": _pbkdf2(pin, salt),
            "failures": 0, "lockedUntil": None, "updatedAt": now,
        })

    @classmethod
    def create_receipt_authorization(cls, owner_uid, company_id, sandbox, delivery_id, receiver_uid):
        """Emite una autorización de recepción PENDING (id seguro, con vigencia)."""
        delivery = cls.get_delivery(owner_uid, company_id, sandbox, delivery_id)
        if not delivery:
            raise CashDeliveryError("Entrega no encontrada.")
        if delivery.get("status") != DELIVERY_PENDING_RECEIPT:
            raise CashDeliveryError(f"No se puede autorizar una entrega en estado {delivery.get('status')}.")
        if (delivery.get("deliveredBy") or {}).get("uid") == receiver_uid:
            raise CashDeliveryError("No puede autorizar la recepción de una entrega que usted mismo registró.")

        auths_coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._auth_coll_name(sandbox))
        if auths_coll is None:
            raise CashDeliveryError("No se pudo resolver la colección de autorizaciones.")
        auth_id = secrets.token_hex(16)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=RECEIPT_AUTH_TTL_SECONDS)
        auths_coll.document(auth_id).create({
            "id": auth_id,
            "deliveryId": delivery_id,
            "receiverUid": receiver_uid,
            "companyId": company_id,
            "sandbox": bool(sandbox),
            "status": "PENDING",
            "createdAt": now.isoformat(),
            "expiresAt": expires.isoformat(),
        })
        return {"authorizationId": auth_id, "expiresAt": expires.isoformat()}

    @classmethod
    def confirm_receipt(cls, owner_uid, company_id, sandbox, delivery_id, receiver_uid,
                        receiver_name, pin, notes, authorization_id):
        deliveries_coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._coll_name(sandbox))
        pins_coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._pin_coll_name(sandbox))
        auths_coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._auth_coll_name(sandbox))
        if deliveries_coll is None or pins_coll is None or auths_coll is None:
            raise CashDeliveryError("No se pudo resolver las colecciones.")
        if not authorization_id:
            raise CashDeliveryError("Falta el identificador de autorización.")

        delivery_ref = deliveries_coll.document(delivery_id)
        pin_ref = pins_coll.document(receiver_uid)
        auth_ref = auths_coll.document(authorization_id)
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        def _run(txn):
            d_snap = txn.get(delivery_ref)
            if not d_snap.exists:
                raise CashDeliveryError("Entrega no encontrada.")
            d = d_snap.to_dict() or {}
            status = d.get("status")
            if status in (DELIVERY_RECEIVED, DELIVERY_RECONCILED, DELIVERY_PENDING_RECONCILIATION):
                return {"ok": True, "delivery": d}
            if status != DELIVERY_PENDING_RECEIPT:
                raise CashDeliveryError(f"No se puede confirmar una entrega en estado {status}.")
            if (d.get("deliveredBy") or {}).get("uid") == receiver_uid:
                raise CashDeliveryError("No puede confirmar una entrega que usted mismo registró.")

            a_snap = txn.get(auth_ref)
            if not a_snap.exists:
                raise CashDeliveryError("Autorización de recepción no encontrada.")
            a = a_snap.to_dict() or {}
            # Propiedad (delivery/receptor/empresa/entorno) antes que el estado.
            if a.get("deliveryId") != delivery_id:
                raise CashDeliveryError("La autorización no corresponde a esta entrega.")
            if a.get("receiverUid") != receiver_uid:
                raise CashDeliveryError("La autorización no corresponde a este receptor.")
            if a.get("companyId") != company_id or a.get("sandbox") != bool(sandbox):
                raise CashDeliveryError("La autorización no pertenece a esta empresa/entorno.")
            if a.get("status") != "PENDING":
                raise CashDeliveryError("La autorización de recepción ya fue consumida.")
            expires_at = a.get("expiresAt")
            if expires_at:
                try:
                    exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                    if now > exp:
                        raise CashDeliveryError("La autorización de recepción ha expirado.")
                except (ValueError, TypeError):
                    pass

            p_snap = txn.get(pin_ref)
            if not p_snap.exists:
                raise CashDeliveryError("El usuario no tiene PIN de recepción configurado.")
            p = p_snap.to_dict() or {}

            locked_until = p.get("lockedUntil")
            if locked_until:
                try:
                    lock_dt = datetime.fromisoformat(str(locked_until).replace("Z", "+00:00"))
                    if now < lock_dt:
                        raise CashDeliveryError("PIN bloqueado temporalmente por intentos fallidos.")
                except (ValueError, TypeError):
                    pass

            if _secure_equals(p.get("pinHash"), _pbkdf2(pin, p.get("pinSalt", ""))):
                # Consumo (PENDING→CONSUMED) + transición RECEIVED + reset de intentos (atómico).
                txn.set(auth_ref, {**a, "status": "CONSUMED", "consumedAt": now_iso})
                txn.set(pin_ref, {"uid": receiver_uid, "pinSalt": p.get("pinSalt", ""),
                                  "pinHash": p.get("pinHash", ""), "failures": 0,
                                  "lockedUntil": None, "updatedAt": now_iso})
                history = list(d.get("history") or [])
                history.append({"event": "RECEIVED", "by": receiver_uid, "at": now_iso,
                                "fromStatus": DELIVERY_PENDING_RECEIPT, "toStatus": DELIVERY_RECEIVED,
                                "notes": notes or ""})
                d["receivedBy"] = {"uid": receiver_uid, "name": receiver_name}
                d["receivedAt"] = now_iso
                d["receivedPinVerified"] = True
                d["receiptAuthorizationId"] = authorization_id
                d["status"] = DELIVERY_RECEIVED
                d["history"] = history
                d["updatedAt"] = now_iso
                txn.set(delivery_ref, d)
                return {"ok": True, "delivery": d}

            failures = int(p.get("failures", 0)) + 1
            locked_iso = None
            if failures >= RECEPTION_PIN_MAX_ATTEMPTS:
                locked_iso = (now + timedelta(seconds=RECEPTION_PIN_LOCK_SECONDS)).isoformat()
            txn.set(pin_ref, {"uid": receiver_uid, "pinSalt": p.get("pinSalt", ""),
                              "pinHash": p.get("pinHash", ""), "failures": failures,
                              "lockedUntil": locked_iso, "updatedAt": now_iso})
            return {"ok": False, "error": "PIN de recepción incorrecto."}

        result = DatabaseService._run_in_transaction(_run)
        if not result["ok"]:
            raise CashDeliveryError(result["error"])
        return result["delivery"]

    @classmethod
    def get_delivery(cls, owner_uid, company_id, sandbox, delivery_id):
        deliveries_coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._coll_name(sandbox))
        if deliveries_coll is None:
            return None
        snap = deliveries_coll.document(delivery_id).get()
        return snap.to_dict() if snap and snap.exists else None
