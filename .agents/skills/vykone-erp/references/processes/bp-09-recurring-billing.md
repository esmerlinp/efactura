# BP-9: Facturación Recurrente por Contrato

## Overview

Facturación automática de contratos con recurrencia configurable (mensual,
trimestral, anual). Cada contrato define cliente, servicio, frecuencia, fecha
de corte, y plantilla de factura. El sistema detecta contratos próximos a vencer
y genera las e-CF automáticamente.

## Flow

```
Scheduler (diario, 6 AM) → ContractService.find_contracts_to_bill(today)
  │
  ├─ Filtro: contracts where next_billing_date <= today
  │           AND is_active == True
  │           AND billing_suspended == False
  │
  ├─ Para cada contrato:
  │   ├─ Validar cliente activo (no inactivo/bloqueado)
  │   ├─ Validar precio de servicio vigente
  │   ├─ Generar e-CF (API DGII)
  │   │   ├─ Tipo: Factura de Crédito Fiscal (01)
  │   │   ├─ Secuencia NCF según DGII range asignado
  │   │   └─ Monto base + ITBIS 18%
  │   ├─ Guardar factura en Firestore
  │   ├─ Generar asiento contable (Ingreso + ITBIS por Pagar)
  │   ├─ Actualizar next_billing_date según frecuencia
  │   │   ├─ monthly: date + 1 mes (mismo día o ajustado por cierre de mes)
  │   │   ├─ quarterly: date + 3 meses
  │   │   └─ yearly: date + 1 año
  │   ├─ EventBus: RecurringInvoiceCreated(contract_id, invoice_id, amount)
  │   └─ Email: notificación al cliente (opcional)
  │
  └─ Retorna reporte: total_facturas, total_monto, errores[]
```

## Contract Model

```
Contract:
  - contract_id
  - client_id (references Cliente)
  - service_id (references Servicio)
  - frecuencia: "monthly" | "quarterly" | "yearly"
  - billing_day: int (1-28, día del mes para facturar)
  - next_billing_date: Date
  - end_date: Date | null (null = indefinido)
  - unit_price: Decimal
  - itbis_apply: bool (default: true)
  - retencion_isr: Decimal | null (1-100%, si aplica)
  - template_id: ID de plantilla e-CF
  - is_active: bool
  - billing_suspended: bool
  - suspended_reason: str | null
```

## Error Handling per Contract

| Error | Behavior |
|-------|----------|
| Cliente inactivo | Skip, log error, notify admin |
| Sin NCF disponibles | Skip ALL remaining contracts, alert admin |
| DGII API timeout/rechazo | Retry 3x with exponential backoff, then skip |
| Precio de servicio no encontrado | Skip, log error |

## Events

- `RecurringInvoiceCreated(owner_uid, contract_id, invoice_id, amount)`
- `ContractBillingCompleted(owner_uid, total_processed, total_amount, errors)`

## Related Files
- `app/services/contract_service.py` — ContractService, find_contracts_to_bill()
- `app/services/scheduler_service.py` — Scheduler (daily cron)
- `app/services/e_cf_service.py` — Generar e-CF via DGII
- `app/models/pydantic/contract.py` — Contract schemas
- `app/events/domain_events.py` — RecurringInvoiceCreated
