"""
Eventos de dominio del Event Bus.

Cada evento representa una operación de negocio significativa que otros
módulos pueden necesitar escuchar. Los eventos son inmutables y contienen
toda la información necesaria para que los handlers reaccionen.

Parte del Plan de Evolución ERP - Fase 1.2: Event Bus.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import json


class EventEncoder(json.JSONEncoder):
    """Codificador JSON que serializa dataclasses y datetime."""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)
        return super().default(obj)


@dataclass(frozen=True)
class DomainEvent:
    """Evento base del dominio. Todos los eventos heredan de esta clase."""

    event_type: str
    owner_uid: str
    sandbox: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Serializa el evento a diccionario para transmisión."""
        return asdict(self)

    def to_json(self) -> str:
        """Serializa el evento a JSON string para Redis Pub/Sub."""
        return json.dumps(asdict(self), cls=EventEncoder)


@dataclass(frozen=True)
class InvoiceEmitted(DomainEvent):
    """Emitido cuando una factura de venta se crea/emite exitosamente.

    El handler contable generará automáticamente el asiento de venta.
    """

    invoice_id: str = ""
    invoice_number: str = ""
    invoice_data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "event_type", "InvoiceEmitted")


@dataclass(frozen=True)
class PaymentRegistered(DomainEvent):
    """Emitido cuando se registra un pago de un cliente (CxC).

    El handler contable actualizará los asientos correspondientes.
    """

    payment_id: str = ""
    invoice_id: str = ""
    invoice_number: str = ""
    payment_data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "event_type", "PaymentRegistered")


@dataclass(frozen=True)
class ExpenseCreated(DomainEvent):
    """Emitido cuando se registra una compra/gasto (CxP).

    El handler contable generará automáticamente el asiento de gasto.
    """

    expense_id: str = ""
    ncf: str = ""
    expense_data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "event_type", "ExpenseCreated")


@dataclass(frozen=True)
class AssetDepreciated(DomainEvent):
    """Emitido cuando se calcula la depreciación de un activo fijo.

    El handler contable generará los asientos de depreciación.
    """

    asset_id: str = ""
    asset_name: str = ""
    depreciation_data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "event_type", "AssetDepreciated")


# ── Eventos de Acciones Masivas de Personal ──────────────────────────


@dataclass(frozen=True)
class BulkSalaryChanged(DomainEvent):
    """Emitido cuando se aplica un cambio salarial masivo."""
    mass_action_id: str = ""
    action_data: Dict[str, Any] = field(default_factory=dict)
    affected_ids: list = field(default_factory=list)
    payroll_period_key: str = ""

    def __post_init__(self):
        object.__setattr__(self, "event_type", "BulkSalaryChanged")


@dataclass(frozen=True)
class BulkPositionChanged(DomainEvent):
    """Emitido cuando se aplica un cambio de puesto masivo."""
    mass_action_id: str = ""
    action_data: Dict[str, Any] = field(default_factory=dict)
    affected_ids: list = field(default_factory=list)

    def __post_init__(self):
        object.__setattr__(self, "event_type", "BulkPositionChanged")


@dataclass(frozen=True)
class BulkSupervisorChanged(DomainEvent):
    """Emitido cuando se reasignan supervisores masivamente."""
    mass_action_id: str = ""
    action_data: Dict[str, Any] = field(default_factory=dict)
    affected_ids: list = field(default_factory=list)

    def __post_init__(self):
        object.__setattr__(self, "event_type", "BulkSupervisorChanged")


@dataclass(frozen=True)
class BulkPromotionApplied(DomainEvent):
    """Emitido cuando se aplica una promoción masiva."""
    mass_action_id: str = ""
    action_data: Dict[str, Any] = field(default_factory=dict)
    affected_ids: list = field(default_factory=list)
    payroll_period_key: str = ""

    def __post_init__(self):
        object.__setattr__(self, "event_type", "BulkPromotionApplied")


@dataclass(frozen=True)
class BulkAbsenceApplied(DomainEvent):
    """Emitido cuando se aplica una ausencia masiva."""
    mass_action_id: str = ""
    action_data: Dict[str, Any] = field(default_factory=dict)
    affected_ids: list = field(default_factory=list)

    def __post_init__(self):
        object.__setattr__(self, "event_type", "BulkAbsenceApplied")


def event_from_dict(data: Dict[str, Any]) -> DomainEvent:
    """Reconstruye un evento a partir de un diccionario (ej. desde Redis)."""
    event_type = data.get("event_type", "")
    event_map = {
        "InvoiceEmitted": InvoiceEmitted,
        "PaymentRegistered": PaymentRegistered,
        "ExpenseCreated": ExpenseCreated,
        "AssetDepreciated": AssetDepreciated,
        "BulkSalaryChanged": BulkSalaryChanged,
        "BulkPositionChanged": BulkPositionChanged,
        "BulkSupervisorChanged": BulkSupervisorChanged,
        "BulkPromotionApplied": BulkPromotionApplied,
        "BulkAbsenceApplied": BulkAbsenceApplied,
    }
    cls = event_map.get(event_type)
    if cls is None:
        raise ValueError(f"Tipo de evento desconocido: {event_type}")
    # Filtramos solo los campos que acepta el dataclass
    valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return cls(**filtered)


def event_from_json(json_str: str) -> DomainEvent:
    """Reconstruye un evento desde JSON (ej. mensaje de Redis)."""
    return event_from_dict(json.loads(json_str))
