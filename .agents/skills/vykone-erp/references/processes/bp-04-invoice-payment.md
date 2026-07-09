# BP-4: Pago de Factura (Invoice Payment)

## Overview

Registro de pagos recibidos de clientes contra facturas pendientes (CxC).
Soporta pago parcial, pago múltiple (un pago cubre varias facturas), y
pago con retención (ISR/ITBIS). Integra con conciliación bancaria.

## Flow

```
Registrar pago(owner_uid, payment)
  │
  ├─ Validar monto > 0
  ├─ Validar método de pago:
  │   ├─ transferencia: requiere referencia_bancaria + banco_origen + banco_destino
  │   ├─ efectivo: sin requisitos adicionales
  │   ├─ cheque: requiere numero_cheque + banco
  │   └─ tarjeta: requiere ultimos_4_digitos + tipo_tarjeta + autorizacion
  │
  ├─ Para cada invoice_id en el pago:
  │   ├─ Validar factura existe y está en estado "Pendiente" o "Vencida"
  │   ├─ Validar balance_pendiente = total - sum(pagos_aplicados)
  │   ├─ Validar amount_to_apply <= balance_pendiente
  │   ├─ Registrar payment_application:
  │   │   ├─ amount_applied
  │   │   ├─ retencion_isr (si aplica)
  │   │   └─ retencion_itbis (si aplica)
  │   ├─ Actualizar balance factura
  │   └─ Si balance == 0 → marcar factura como "Pagada"
  │
  ├─ Registrar pago en payment_method register (caja/banco)
  │
  ├─ Generar asiento contable:
  │   Debit:  Banco/Caja (monto neto)
  │   Debit:  Retención ISR por Cobrar (si aplica)
  │   Debit:  ITBIS Retenido por Cobrar (si aplica)
  │   Credit: Cuentas por Cobrar (total aplicado a facturas)
  │
  ├─ EventBus: InvoicePaid(invoice_id, amount_paid, remaining_balance)
  │
  └─ Retornar payment_id + resumen de facturas afectadas
```

## Payment Distribution

Cuando un pago aplica a múltiples facturas, la distribución sigue prioridad:
1. Factura más antigua primero (FIFO)
2. Factura vencida > factura pendiente
3. Si amount no cubre el total de una factura → pago parcial

## Retention Handling

| Tipo | Retención ISR | Retención ITBIS |
|------|--------------|-----------------|
| Servicios profesionales | 10% | 100% del ITBIS |
| Alquileres | 10% | 100% del ITBIS |
| Comisiones | 10% | 100% del ITBIS |
| Otros (bienes) | N/A | 30% del ITBIS |

Los comprobantes de retención se emiten como e-CF tipo 07 (Comprobante de
Retención) o 05 (Comprobante para Gastos Menores) según corresponda.

## Payment Method Registry

Cada método de pago registra en el módulo correspondiente:
- `transferencia` → `BankTransaction` en cuenta bancaria destino
- `efectivo` → `CashRegister` en caja seleccionada
- `cheque` → `CheckRegister` con número y estado
- `tarjeta` → `CardBatch` para conciliación de lote

## Events

- `InvoicePaid(owner_uid, invoice_id, amount, remaining, payment_id)`
- `PaymentRegistered(owner_uid, payment_id, total_amount, invoices_paid, method)`

## Related Files
- `app/services/payment_service.py` — register_payment()
- `app/services/invoice_service.py` — update_balance(), check_status()
- `app/services/accounting_service.py` — generate_payment_entry()
- `app/models/pydantic/payment.py` — Payment, PaymentApplication schemas
- `app/web/payments.py` — payment endpoints
- `app/events/domain_events.py` — InvoicePaid, PaymentRegistered
