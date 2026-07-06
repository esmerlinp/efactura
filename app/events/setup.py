"""
Setup del Event Bus.

Se llama durante la inicialización de la aplicación Flask para:
1. Crear (o reutilizar) el EventBus global
2. Registrar los handlers predeterminados (contables, etc.)
3. Iniciar el listener de Redis si está configurado

Parte del Plan de Evolución ERP - Fase 1.2: Event Bus.
"""

import logging

logger = logging.getLogger(__name__)


def setup_event_bus(app=None, redis_client=None):
    """Inicializa el Event Bus y registra los handlers predeterminados.

    Args:
        app: Instancia de Flask (opcional, para obtener config).
        redis_client: Cliente redis.Redis opcional para modo producción.

    Returns:
        El EventBus inicializado.
    """
    from app.events.event_bus import init_event_bus, get_event_bus
    from app.events.handlers import (
        handle_invoice_emitted,
        handle_payment_registered,
        handle_expense_created,
        handle_asset_depreciated,
    )

    # Si se pasa redis_client, inicializar con Redis; si no, in-process por defecto
    if redis_client:
        bus = init_event_bus(redis_client=redis_client)
        bus.start_listener()
    else:
        bus = get_event_bus()

    # Registrar handlers contables
    bus.subscribe("InvoiceEmitted", handle_invoice_emitted)
    bus.subscribe("PaymentRegistered", handle_payment_registered)
    bus.subscribe("ExpenseCreated", handle_expense_created)
    bus.subscribe("AssetDepreciated", handle_asset_depreciated)

    logger.info(
        "Event Bus inicializado (modo: %s). Handlers registrados: %d",
        "Redis" if redis_client else "in-process",
        sum(len(h) for h in bus._handlers.values()),
    )

    return bus
