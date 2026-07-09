# BP-7: Cierre Fiscal (Fiscal Closing)

## Overview

Proceso de cierre de período fiscal (mensual/anual) que bloquea transacciones,
genera reportes DGII (IT-1, IR-17/DC4), y prepara el siguiente período.
Es el proceso de MÁS ALTO RIESGO en el ERP. Debe ejecutarse con doble confirmación.

## Prerequisites (all must pass)

1. All e-CF invoices for the period must be in `Aceptado` status (DGII)
2. No pending approval workflows exist (expenses/POs in `Pendiente`)
3. All bank accounts reconciled up to the closing date
4. Accounting period is open (not previously closed)
5. Trial balance is balanced (total_debit == total_credit)

## Flow

```
ejecutar_cierre(owner_uid, period_start, period_end, dry_run=False)
  │
  ├─ dry_run=True → Simula el cierre, reporta errores, NO aplica cambios
  │                  Retorna: warnings[], errors[], estimated_tax_liability
  │
  └─ dry_run=False → ALWAYS requires double-confirmation token
                      │
                      ├─ Step 1: Validate prerequisites
                      │   ├─ Check e-CF status (all accepted)
                      │   ├─ Check approval workflows (none pending)
                      │   ├─ Check bank reconciliations (all done)
                      │   └─ Check trial balance (balanced)
                      │
                      ├─ Step 2: Generate DGII reports
                      │   ├─ IT-1: Ingresos Totales del período
                      │   ├─ IR-17/DC4: Compras/Gastos con NCF
                      │   └─ ITBIS summary (collectable vs creditable)
                      │
                      ├─ Step 3: Calculate tax provisions
                      │   ├─ ISR: ingresos_gravados × tasa_efectiva
                      │   ├─ ITBIS: (collectable - creditable)
                      │   └─ Activos (1% Ley 6-86)
                      │
                      ├─ Step 4: Generate closing entries
                      │   ├─ Income accounts → zero (close to P&L)
                      │   ├─ Expense accounts → zero (close to P&L)
                      │   ├─ Tax provisions → liability accounts
                      │   └─ Net result → Retained Earnings / Accumulated
                      │
                      ├─ Step 5: Lock period
                      │   ├─ Set accounting_period.is_closed = True
                      │   ├─ Set accounting_period.closed_at = now()
                      │   └─ Prevent ALL transactions in closed period
                      │
                      └─ Step 6: Open next period
                          ├─ Create next accounting_period entry
                          └─ EventBus: FiscalPeriodClosed(period)
```

## Double Confirmation

```
1. Agent calls execute_fiscal_closing(dry_run=True)
2. Agent presents results to user for approval
3. User confirms by generating confirmation_token
4. Agent calls execute_fiscal_closing(dry_run=False, confirmation_token=token)
5. Token is single-use, expires in 5 minutes
```

## Reversal (Emergency)

If a closing was erroneous, a `reverse_fiscal_closing` exists with:
- **Guard**: Only allowed if no DGII submission was made for the period
- Requires admin-level permission (`fiscal:reverse`)
- Reopens the period, reverses auto-entries

## Events

- `FiscalPeriodClosed(owner_uid, period_start, period_end, closed_by)`
  Triggers: emails to admin, audit log, dashboard update

## Related Files
- `app/services/fiscal_service.py` — execute_fiscal_closing(), reverse_fiscal_closing()
- `app/services/accounting_service.py` — generate_closing_entries()
- `app/models/pydantic/fiscal.py` — FiscalClosingRequest, FiscalClosingResponse
- `app/web/reports.py` — IT-1, IR-17 endpoints
- `app/events/domain_events.py` — FiscalPeriodClosed
