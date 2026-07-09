# BP-8: Conciliación Bancaria (Bank Reconciliation)

## Overview

Proceso que cruza los movimientos registrados en el libro contable de banco
contra el estado de cuenta bancario externo (CSV, Excel, o JSON), identificando
diferencias y generando partidas de ajuste cuando corresponde.

## Flow

```
1. Seleccionar cuenta bancaria + período
2. Importar extracto bancario (upload file or paste)
   ├─ Formato detectado automáticamente: CSV, XLSX, JSON
   └─ Mapping de columnas: fecha, descripción, monto, tipo (débito/crédito)
3. Matching automático
   ├─ Match por monto exacto + fecha (±2 días)
   ├─ Match por monto exacto + referencia/descripción similar
   └─ Match por monto exacto + fecha (±5 días) para montos no redondos
4. Revisión manual de no-matcheados
   ├─ Items en banco no en ERP → depósitos/cargos no registrados
   └─ Items en ERP no en banco → cheques en tránsito, depósitos en tránsito
5. Ajustes
   ├─ Registrar partidas faltantes en ERP
   ├─ Marcar cheques en tránsito
   └─ Registrar cargos bancarios (ITF, comisiones)
6. Confirmar conciliación
   ├─ Calcular diferencia (debe ser 0 o explicada)
   ├─ Guardar estado de conciliación
   └─ EventBus: BankAccountReconciled
```

## Match Rules

| Rule | Priority | Tolerance |
|------|----------|-----------|
| Exact amount + same date | 1 (highest) | 0 |
| Exact amount + date ±2 days | 2 | ±2 days |
| Exact amount + reference match | 3 | ±5 days |
| Amount ± RD$100 + date ±1 day | 4 | RD$100 ±1 day |
| Partial amount (split matches) | 5 | manual |

## ITF (Impuesto a Transferencias Financieras)

RD Law 253-12 applies 0.15% on incoming/outgoing transactions above RD$10,000.
- ITF is typically charged separately by the bank, not per-transaction
- Must be registered as a separate expense entry
- ITF amount is deductible for ISR purposes

## Reconciliation Statuses

| Status | Meaning |
|--------|---------|
| `pending` | Reconciliation started, not completed |
| `in_progress` | Matching done, awaiting adjustments |
| `reconciled` | Finalized, all differences explained |
| `dispute` | Unreconcilable difference flagged |

## Events

- `BankAccountReconciled(owner_uid, bank_account_id, period_start, period_end, reconciled_by)`
  Triggers: audit log, prerequisite check for fiscal closing

## Related Files
- `app/services/reconciliation_service.py` — BankReconciliationService
- `app/services/import_service.py` — bank statement import/parser
- `app/models/pydantic/reconciliation.py` — Reconciliation schemas
- `app/web/banking.py` — reconciliation endpoints
- `app/events/domain_events.py` — BankAccountReconciled
