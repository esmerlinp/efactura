# Caja — Fase 2 (Taxonomía, autorizaciones y trazabilidad): alcance

**Estado:** alcance aprobado con ajustes; pendiente de autorización de implementación.

## Objetivo
Diferenciar los tipos de movimiento de caja, establecer autorizaciones por tipo con
límites configurables por empresa, y registrar quién ejecutó y quién autorizó cada
operación, sin romper la integridad transaccional de Fase 1.

## Matriz de autorización (sin contradicciones)

| Tipo | Regla de autorización |
|---|---|
| `SALE` | Automática (sistema) |
| `CASH_IN` | Cajero; PIN de supervisor si supera el límite configurado |
| `CASH_OUT` | Siempre supervisor (PIN) |
| `CASH_DROP` | Siempre supervisor (PIN) |
| `EXPENSE` | Cajero hasta RD$50,000 (límite editable); supervisor por encima |
| `FUND_IN` | Siempre supervisor (PIN) |
| `FUND_OUT` | Siempre supervisor (PIN) |
| `TRANSFER_IN` | Siempre supervisor (PIN) |
| `TRANSFER_OUT` | Siempre supervisor (PIN) |
| `REFUND` | Reservado para Fase 3 (devoluciones/NC) |

Mapeo retrocompatible al leer: `IN→CASH_IN`, `OUT→CASH_OUT`. `Crédito` no genera movimiento.

## Decisiones aprobadas
1. **Autorización**: reglas fijas por tipo (matriz de arriba) + límites configurables por empresa.
2. **Gastos menores (EXPENSE)**: movimiento de caja simple (sin integración CxP en Fase 2).
3. **Límites**: editables por empresa, almacenados en la configuración del módulo POS.

## Ajustes funcionales (condiciones adicionales)

### 1. Transferencias atómicas entre cajas
Una transferencia genera **dos** movimientos que comparten una referencia única
(`transferId`):
- `TRANSFER_OUT` en la caja de origen.
- `TRANSFER_IN` en la caja de destino.

Deben ejecutarse **atómica e idempotentemente**: o se registran ambos o ninguno.
Se escriben en una única transacción Firestore y comparten `idempotencyKey`
(derivada del `transferId`), de modo que un reintento no duplica ninguno de los dos.

### 2. Moneda y límites (DOP vs USD)
- Los importes se conservan en su **moneda original** (campo `currency`).
- Los límites se aplican **por moneda**, de forma independiente (límite DOP ≠ límite USD).
- **No** se convierte USD→DOP con una tasa implícita para decidir autorización.
- Los saldos esperados de efectivo DOP y USD se mantienen **separados**
  (`expectedCash` vs `expectedUSD`), igual que en Fase 1.

### 3. Autorización PIN vinculada a la operación
- El PIN autoriza **una operación concreta**, no una sesión de autorización reutilizable.
- La validación queda vinculada a: `type`, `amount`, `currency`, `registerId`/`shiftId`
  y `user` solicitante (un hash/firma del contexto de la operación).
- Se **impide la auto-autorización**: el cajero no puede autorizar su propio movimiento
  que requiera supervisor (SoD).

### 4. Trazabilidad
Todo movimiento registra `performedBy` y, cuando aplique, `authorizedBy` + `authorizedAt`,
y queda en `AuditService` (log de acción).

## Campos de movimiento (`cash_transactions`)
`type`, `amount`, `currency` (DOP/USD), `reason` (estructurado), `referenceType`,
`referenceId`, `transferId` (solo transferencias), `performedBy`, `authorizedBy`,
`authorizedAt`, `shiftId`, `registerId`, `idempotencyKey`, `createdAt`,
`status` (`ACTIVE`/`VOIDED`).

## Conciliación por canal
`expectedCash/Card/Transfer/USD` actualizado por tipo con `Decimal`; `Crédito` fuera del efectivo.

## Criterios de aceptación (testables)
1. Cada movimiento registra `reason` + `performedBy` y, si aplica, `authorizedBy`.
2. Movimiento que requiere autorización se rechaza (403) sin PIN válido.
3. Movimiento por encima del límite configurado (en su moneda) se rechaza sin autorización.
4. Límites independientes DOP/USD: un monto USD no se compara contra el límite DOP.
5. `CASH_IN/CASH_OUT/CASH_DROP/EXPENSE/FUND_IN/FUND_OUT` actualizan `expectedCash` (DOP) o `expectedUSD` (USD) según su moneda, con `Decimal`.
6. Transferencia registra `TRANSFER_OUT` + `TRANSFER_IN` de forma atómica (o ambos o ninguno) con `transferId` único e idempotente.
7. Reintento con misma `idempotencyKey` no duplica el movimiento.
8. PIN de supervisor vinculado a la operación: no se reutiliza para otra operación distinta.
9. Se impide la auto-autorización (SoD).
10. Tipos legacy `IN`/`OUT` siguen leyéndose en reportes históricos.
11. Todo movimiento respeta el lock de ocupación (Fase 1).

## Fuera de alcance
- `REFUND` real (devoluciones/Notas de Crédito) → Fase 3.
- `CashDelivery`/`CashReconciliation` (entrega/conciliación de fondos) → Fase 4.

## Archivos objetivo
- `app/services/db_service.py` — `register_cash_transaction` (taxonomía + campos), constantes.
- `app/services/cash_authorization_service.py` *(nuevo)* — reglas + límites por moneda + validación PIN vinculada.
- `app/services/cash_transfer_service.py` *(nuevo)* — transferencia atómica entre cajas.
- `app/web/pos.py` — `add_manual_transaction` (tipos, PIN, límites), config de límites.
- `templates/pos/dashboard.html` — selector de tipo + modal de autorización.
- `tests/test_cash_movements.py` *(nuevo)* — taxonomía, autorización, límites, transferencias, conciliación.
