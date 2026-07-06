"""
Módulo de Eventos del ERP VykOne.

Proporciona el Event Bus (híbrido in-process/Redis Pub/Sub) y los
eventos de dominio para desacoplar los bounded contexts.

Uso básico:
    from app.events import get_event_bus, InvoiceEmitted

    bus = get_event_bus()
    bus.publish(InvoiceEmitted(
        owner_uid=owner_uid,
        invoice_id=invoice_id,
        invoice_data=invoice_dict,
    ))

Parte del Plan de Evolución ERP - Fase 1.2: Event Bus.
"""

from app.events.event_bus import EventBus, get_event_bus, init_event_bus
from app.events.events import (
    DomainEvent,
    InvoiceEmitted,
    PaymentRegistered,
    ExpenseCreated,
    AssetDepreciated,
    event_from_dict,
    event_from_json,
)

__all__ = [
    "EventBus",
    "get_event_bus",
    "init_event_bus",
    "DomainEvent",
    "InvoiceEmitted",
    "PaymentRegistered",
    "ExpenseCreated",
    "AssetDepreciated",
    "event_from_dict",
    "event_from_json",
]
