# Caja POS — Fase 4.2: Entrega de fondos (CashDelivery) — alcance

**Estado:** alcance preparado, **pendiente de autorización explícita** para implementar.
Rama: `feature/cash-fase4-entrega-conciliacion`.

## Objetivo
Registrar entregas físicas de efectivo (DOP y/o USD) del cajero a un responsable receptor,
creando conjuntamente su(s) movimiento(s) `CASH_DROP` y su registro `CashDelivery`, con
confirmación de recepción por PIN y trazabilidad. **No** incluye conciliación (4.3) ni reportes (4.4).

## Alcance funcional

1. **`CashDeliveryService`** (nuevo): registro de entrega, confirmación de recepción, consulta.
2. **`register_delivery`**: creación conjunta (transacción) de:
   - 1 movimiento `CASH_DROP` en DOP (si hay DOP).
   - 1 movimiento `CASH_DROP` en USD (si hay USD).
   - 1 `CashDelivery` con `cashDropTransactionIds[]` referenciando ambos.
3. **Entregas DOP, USD y combinadas**: cada movimiento conserva su moneda e importe original;
   **nunca** se combinan DOP y USD en un único movimiento.
4. **PIN de recepción**: hasheado, single-use (consumo atómico vinculado a la entrega),
   protección contra fuerza bruta (contador de intentos + bloqueo temporal).
5. **Idempotencia y concurrencia**: una clave → como máximo una entrega; reintentos devuelven
   el resultado original; sin duplicar `CASH_DROP`.
6. **Historial y auditoría**: `history[]` embebido inmutable + `AuditService`.

## Decisiones conservadas (de 4.1)

### D1 — 1..2 movimientos por entrega
Una entrega genera hasta **dos** movimientos `CASH_DROP` (uno por moneda), ambos vinculados a una
sola `CashDelivery` vía `cashDropTransactionIds[]`. Cada movimiento conserva su `currency` e
`amount` original. No se mezclan monedas en un movimiento.

### D2 — Reserva de idempotencia vs transacción de creación
- **Reserva inicial de clave** (`reserve_idempotency_key`, lease + owner) y **transacción que crea
  los movimientos + entrega** son pasos separados.
- Debe existir **recuperación segura** ante: expiración del lease, caída del proceso entre ambos
  pasos, y reintentos concurrentes.
- Una reserva abandonada/vencida **nunca** debe permitir duplicar una entrega ya creada. Para ello,
  el id del `CashDelivery` (y de sus `CASH_DROP`) se deriva **deterministicamente** de la clave, de
  modo que un reintento apunta al mismo documento (sobrescritura idempotente) o devuelve el resultado existente.

## Criterios de aceptación (testables)

1. `register_delivery` crea `CASH_DROP` + `CashDelivery` en una transacción (o ambos o ninguno).
2. Entrega solo DOP → 1 `CASH_DROP` DOP; solo USD → 1 `CASH_DROP` USD; combinada → 2 (DOP + USD).
3. Cada `CASH_DROP` conserva `currency`/`amount` originales (sin mezclar monedas).
4. `cashDropTransactionIds[]` referencia exactamente los movimientos creados.
5. Una clave de idempotencia no genera más de una entrega; reintento devuelve el resultado original.
6. Un crash entre la reserva y la transacción no duplica la entrega (recuperación determinista).
7. El PIN de recepción es single-use y vinculado a una entrega; el receptor ≠ entregador (SoD).
8. Dos solicitudes concurrentes no generan dos entregas ni duplican `CASH_DROP`.
9. El registro de entrega es inmutable; historial y auditoría trazables.
10. Aislamiento por empresa/entorno; sin tocar `close_cash_shift` ni F1–F3.

## Fuera de alcance
- Conciliación (4.3), reportes (4.4), integración con pasarela de pagos.

## Archivos objetivo (al autorizar)
- `app/services/cash_delivery_service.py` *(nuevo)*.
- `app/services/db_service.py` — `validate_reception_pin`, `get/save_reception_pin` (hash), colección `cash_deliveries`.
- `app/web/pos.py` — rutas `POST /pos/delivery`, `POST /pos/delivery/<id>/receive`.
- `tests/test_cash_deliveries.py` *(nuevo)* + integración con Firestore Emulator (gated).
