# Caja POS — Fase 4.2: Entrega de fondos (CashDelivery) — implementación

**Estado:** **CERRADA / APROBADA** (revisión técnica final superada). Validación con Firestore
Emulator pendiente como condición de despliegue. Rama `feature/cash-fase4-entrega-conciliacion`.

## Componentes

### 1. `CashDeliveryService` (`app/services/cash_delivery_service.py`)
- `register_delivery(...)` — crea **conjuntamente** en una transacción Firestore el/los
  movimiento(s) `CASH_DROP` (1..2, uno por moneda DOP/USD) y el registro `CashDelivery`
  (`cashDropTransactionIds[]`), validando el lock `ACTIVE` y tocándolo.
- `create_receipt_authorization(...)` — emite una autorización de recepción `PENDING` con id
  seguro (`secrets.token_hex`), vinculada a `deliveryId`/`receiverUid`/`companyId`/`sandbox`,
  con `createdAt` y `expiresAt` (TTL 300 s). Impide sobrescribir (`create` atómico).
- `confirm_receipt(...)` — consume la autorización (`PENDING→CONSUMED`) y transiciona la entrega
  (`PENDING_RECEIPT→RECEIVED`) en **una transacción**, validando propiedad (delivery/receptor/
  empresa/entorno), estado, vigencia y PIN. El PIN incorrecto incrementa intentos atómicamente
  sin consumir la autorización.
- `set_reception_pin(...)` — PIN con **PBKDF2-SHA256 (100k iteraciones) + salt aleatorio** y
  comparación con `hmac.compare_digest`; contador de intentos + bloqueo persistidos (5 intentos
  → 300 s, no reiniciable).

### 2. Integridad monetaria y denominaciones
- Sin `declaredTotal`: importes separados en `amounts.dop`/`amounts.usd`.
- Validación estricta de denominaciones: solo DOP/USD, denominaciones permitidas por moneda,
  cantidades enteras no negativas (sin truncar con `int()`), rechazo de fraccionarias/negativas/
  desconocidas, y coherencia entre desglose e importe cuando se proporciona.
- `usdRate` normalizado una sola vez (mismo valor en validación, firma y persistencia); la firma
  usa representación canónica (`Decimal.normalize()`) para no confundir valores económicos distintos.

### 3. Rutas (`app/web/pos.py`)
- `POST /pos/delivery` — registra entrega (crea CASH_DROP + CashDelivery).
- `POST /pos/delivery/<id>/receipt-auth` — emite autorización de recepción.
- `POST /pos/delivery/<id>/receive` — confirma recepción (PIN + `authorizationId`).
- `POST /pos/reception-pin` — establece el PIN de recepción propio.

## Decisiones obligatorias (D1/D2)

- **D1**: una entrega genera 1..2 `CASH_DROP` (uno por moneda), conservando `currency`/`amount`
  individuales; nunca se mezclan monedas.
- **D2**: el id de la entrega (y de sus movimientos) se deriva **deterministicamente** de la
  `idempotencyKey`; un reintento apunta al mismo documento (idempotente) y nunca duplica.

## Integridad monetaria

- No hay `declaredTotal`: los importes se conservan separados en `amounts.dop` y `amounts.usd`.
- Validaciones: DOP ≥ 0, USD ≥ 0, al menos una moneda > 0, `usd_rate` positivo/finito cuando
  hay USD, denominaciones como objeto válido.
- La firma de idempotencia incluye `company_id`, `sandbox`, `shift_id`, `register_id`, DOP/USD
  normalizados, `usd_rate` y denominaciones (serialización canónica).

## Integración con F1–F3

- `close_cash_shift` **no se modificó**: los `CASH_DROP` creados por la entrega ya reducen
  `expectedCash`/`expectedUSD`.
- Reutiliza `_run_in_transaction`, `_company_coll`, `_money`, `CashShiftLockError` (F1/F2).

## Pruebas
- `tests/test_cash_deliveries.py` — 22 pruebas (registro DOP/USD/combinada, integridad monetaria,
  denominaciones estrictas, idempotencia con firma completa, autorización PENDING/CONSUMED/expiración/
  propiedad/concurrencia, PIN hasheado + anti-fuerza bruta, lock CLOSING).
- Caja/POS F1–F3 + inventario: 149 passed, 2 skipped (emulador).
- Regresión general: 2292 passed, 278 failed (preexistentes, sin nuevos).

## Riesgos / pendientes
- `posSupervisorPin` (F2) sigue en texto plano (heredado); el nuevo `receptionPin` usa PBKDF2+salt.
- Concurrencia real pendiente de Firestore Emulator (heredado de F1–F3).
- Conciliación (4.3) y reportes (4.4) quedan fuera de esta sub-fase.
