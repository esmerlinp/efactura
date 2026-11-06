# Caja POS — Fase 4.3: Conciliación de fondos (CashReconciliation) — implementación

**Estado:** **CERRADA / APROBADA**. Validación con Firestore Emulator pendiente (condición de despliegue).
Rama `feature/cash-fase4-entrega-conciliacion`.

## Componentes

### 1. `CashReconciliationService` (`app/services/cash_reconciliation_service.py`)
- `reconcile_cash(...)` — concilia efectivo DOP/USD contra el importe del `CASH_DROP` vinculado
  a la `CashDelivery` (derivado, no provisto por el cliente).
- `reconcile_channel(...)` — concilia tarjeta/transferencia contra `expectedCard`/`expectedTransfer`
  del cierre del turno.
- `approve_difference(...)` — aprueba una diferencia (`UNDER_REVIEW → RECONCILED`) consumiendo una
  autorización single-use de supervisor (F2) en la misma transacción.
- `get_reconciliation(...)`.

### 2. Estados (`CashReconciliation.status`)
`OPEN → RECONCILED`; `OPEN → UNDER_REVIEW → RECONCILED`.

### 3. Criterio de conciliación
| Canal | `expectedAmount` | `receivedAmount` |
|---|---|---|
| `CASH_DOP` | `CASH_DROP` vinculado (DOP) | efectivo recibido DOP |
| `CASH_USD` | `CASH_DROP` vinculado (USD) | efectivo recibido USD |
| `CARD` | `expectedCard` del cierre | lote del adquirente |
| `TRANSFER` | `expectedTransfer` del cierre | depósito bancario |

Diferencia inmutable: `difference = received - expected`. Si `|difference| > 0.01` → `UNDER_REVIEW`
y requiere aprobación de supervisor (autorización single-use).

### 4. Rutas (`app/web/pos.py`)
- `POST /pos/delivery/<id>/reconcile` — conciliación de efectivo.
- `POST /pos/shift/<shift_id>/reconcile` — conciliación de tarjeta/transferencia.
- `POST /pos/reconciliation/<id>/approve` — aprobación de diferencia (supervisor).

## Integración con F1–F4.2
- Reutiliza `_run_in_transaction`, `_company_coll`, `_money`, `CashAuthorizationService.consume` (F2).
- `close_cash_shift` no se modificó: `expectedCard`/`expectedTransfer` se leen del cierre.
- El esperado de efectivo NO es `expectedCash` (que es el neto en caja), sino el `CASH_DROP` vinculado.

## Pruebas
- `tests/test_cash_reconciliations.py` — 12 pruebas (conciliación DOP/USD, diferencias, canales
  card/transfer, idempotencia, reuso de clave, aprobación single-use, reuso de autorización).
- Caja/POS F1–F4.3: 161 passed, 2 skipped (emulador).
- Regresión general: 2304 passed, 278 failed (preexistentes, sin nuevos).

## Riesgos / pendientes
- Concurrencia real pendiente de Firestore Emulator (heredado).
- Reportes (4.4) quedan fuera de esta sub-fase.
