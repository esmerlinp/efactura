"""
Handlers que reaccionan a eventos del dominio.

Cada handler se suscribe a un tipo de evento y ejecuta la lógica
de negocio correspondiente de forma asíncrona (sin bloquear al emisor).

Parte del Plan de Evolución ERP - Fase 1.2: Event Bus.
"""

import logging

from app.events.events import (
    DomainEvent,
    InvoiceEmitted,
    PaymentRegistered,
    ExpenseCreated,
    AssetDepreciated,
)

logger = logging.getLogger(__name__)


# ── Accounting Handlers ──────────────────────────────────────────


def handle_invoice_emitted(event: DomainEvent) -> None:
    """Genera asiento contable automático cuando se emite una factura.

    Reemplaza la llamada directa a AccountingService.auto_generate_invoice_entry().
    """
    if not isinstance(event, InvoiceEmitted):
        return

    from app.services.accounting_service import AccountingService

    try:
        invoice_data = event.invoice_data or {}
        # Asegurar que el ID viaje en los datos
        if "id" not in invoice_data and event.invoice_id:
            invoice_data["id"] = event.invoice_id
        if "invoiceNumber" not in invoice_data and event.invoice_number:
            invoice_data["invoiceNumber"] = event.invoice_number

        result = AccountingService.auto_generate_invoice_entry(
            event.owner_uid, invoice_data, sandbox=event.sandbox
        )
        if result:
            logger.info(
                "Asiento contable generado para factura %s (owner=%s)",
                event.invoice_number,
                event.owner_uid,
            )
        else:
            logger.debug(
                "Asiento contable no generado para factura %s (ya existe o sin cuentas)",
                event.invoice_number,
            )
    except Exception:
        logger.exception(
            "Error al generar asiento contable para factura %s",
            event.invoice_number,
        )


def handle_expense_created(event: DomainEvent) -> None:
    """Genera asiento contable automático cuando se registra un gasto.

    Reemplaza la llamada directa a AccountingService.auto_generate_expense_entry().
    """
    if not isinstance(event, ExpenseCreated):
        return

    from app.services.accounting_service import AccountingService

    try:
        expense_data = event.expense_data or {}
        if "id" not in expense_data and event.expense_id:
            expense_data["id"] = event.expense_id
        if "ncf" not in expense_data and event.ncf:
            expense_data["ncf"] = event.ncf

        result = AccountingService.auto_generate_expense_entry(
            event.owner_uid, expense_data, sandbox=event.sandbox
        )
        if result:
            logger.info(
                "Asiento contable generado para gasto %s (owner=%s)",
                event.ncf,
                event.owner_uid,
            )
        else:
            logger.debug(
                "Asiento contable no generado para gasto %s (ya existe o sin cuentas)",
                event.ncf,
            )
    except Exception:
        logger.exception(
            "Error al generar asiento contable para gasto %s",
            event.ncf,
        )


def handle_payment_registered(event: DomainEvent) -> None:
    """Actualiza estado de CxC cuando se registra un pago.

    No genera asiento nuevo (el pago en sí es movimiento de caja/banco),
    pero actualiza el estado financiero del cliente.
    """
    if not isinstance(event, PaymentRegistered):
        return

    try:
        payment_data = event.payment_data or {}
        amount = payment_data.get("amount", 0)
        logger.info(
            "Pago registrado: factura %s, monto RD$ %.2f (owner=%s)",
            event.invoice_number,
            float(amount),
            event.owner_uid,
        )
        # En el futuro, aquí se puede:
        # - Actualizar saldo CxC del cliente
        # - Generar asiento de caja/banco
        # - Disparar notificaciones
    except Exception:
        logger.exception(
            "Error al procesar pago para factura %s",
            event.invoice_number,
        )


def handle_asset_depreciated(event: DomainEvent) -> None:
    """Genera asiento de depreciación cuando se deprecia un activo.

    Reemplaza la llamada directa desde FixedAssetService.
    """
    if not isinstance(event, AssetDepreciated):
        return

    from app.services.accounting_service import AccountingService

    try:
        dep_data = event.depreciation_data or {}
        result = AccountingService.auto_generate_depreciation_entry(
            event.owner_uid, dep_data, sandbox=event.sandbox
        )
        if result:
            logger.info(
                "Asiento de depreciación generado para activo %s (owner=%s)",
                event.asset_name,
                event.owner_uid,
            )
    except Exception:
        logger.exception(
            "Error al generar asiento de depreciación para activo %s",
            event.asset_name,
        )
