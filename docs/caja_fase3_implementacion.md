# Caja — Fase 3 (Devoluciones y reembolsos del POS): implementación

**Estado:** **APROBADA** (cierre formal en desarrollo). Validación de plataforma pendiente.
Rama `feature/cash-fase3-refunds` (derivada de `feature/cash-fase2-taxonomia`).

## Acta de cierre

| Concepto | Estado |
|---|---|
| Implementación | Aprobada (06/11/2026) |
| Pruebas unitarias | 127 passed Caja/POS + inventario; 2270 passed regresión general |
| Firestore Emulator | **Pendiente** (condición de despliegue) |
| Sandbox DGII (escenarios fiscales) | Pendiente |
| Commit / merge / deploy | No autorizados |

## Condiciones previas a producción

1. Ejecutar `tests/test_cash_emulator_integration.py` contra Firestore Emulator
   (concurrencia, transacciones, resolución simultánea de devoluciones).
2. Validar los escenarios fiscales en sandbox DGII (emisión E34, reconciliación por
   trackId/e-NCF, rechazos y timeouts).
3. Verificar la política TTL de `cash_authorizations`/`sandbox_cash_authorizations`.
4. Ejecutar `scripts/backfill_cash_register_locks.py` (dry-run → aplicar con POS detenido).

## Flujo de devolución

```
 POST /pos/refund  (invoiceId, items[], refundMethod, currency, idempotencyKey, supervisor PIN, allowPendingRefund)
        │
        ▼
 1. preview_refund()          ── calcula importe y valida cantidades (sin escribir)
        │
        ▼
 2. authorize(PIN, REFUND)    ── reserva autorización PENDING (Fase 2)
        │
        ▼
 3. process_refund()
        ├─ 3.1 reserve_refund()      ── TRANSACCIÓN: valida returnedQty, actualiza returnedQty,
        │                                crea cash_refunds/{id} RESERVED (firma de idempotencia completa)
        ├─ 3.2 emit_credit_note()     ── save_invoice (reingresa inventario E34) + emit E34
        │                                → ncStatus según resultado DGII
        └─ 3.3 record_refund_movement()── solo si ncStatus lo permite → register_cash_transaction(REFUND)
                                              → estado COMPLETED
```

## Separación de eventos (E34 ↔ inventario ↔ reembolso)

El reingreso de inventario **no** se ejecuta al guardar la NC: se guarda en `Borrador`
(sin reingreso) y solo pasa a `Emitida` (disparando el reingreso de `CreditNoteInventoryService`)
cuando la E34 es **aceptada** por DGII. Así:

| Evento | Cuándo ocurre |
|---|---|
| Recepción física | implícita (la mercancía vuelve al negocio) |
| Reingreso disponible (`save_invoice` → `CreditNoteInventoryService`) | solo al aceptar la E34 |
| Documento fiscal (E34 aceptada) | tras emisión DGII |
| Reembolso (`REFUND`) | tras E34 aceptada (o contingencia autorizada) |

Una E34 rechazada **no** reingresa inventario ni permite reembolso.

## Política de contingencia (reembolso con NC pendiente)

El reembolso con `NC_PENDING_DGII` está **bloqueado por defecto**. La excepción
(`allowPendingRefund`) **no** se activa desde el frontend: se lee de la configuración
de la empresa (`pos_refund_policy`, editable solo por owner/supervisor vía
`POST /pos/refund/policy`) y queda auditada. El cajero no puede activarla por request.

## Resolución manual de NC_RECONCILING

Cuando la emisión es ambigua (timeout), la devolución queda `NC_RECONCILING` y **no se
reemite automáticamente**. Un supervisor puede resolverla (`POST /pos/refund/resolve`),
en una **transacción** con historial y contador de intentos:

- **Idempotencia por `resolutionKey`** (no reejecuta la misma resolución).
- **`reemit`** — bloqueado si hay evidencia de que la solicitud pudo ser recibida por DGII:
  en el documento de devolución (`creditNoteId`/`trackId`/`e-NCF`) o en el documento NC
  determinista (`emissionAttempted`/`emissionCompleted`/`encf`/`trackId`). La ausencia de
  identificadores NO demuestra no-procesamiento.
- **`abandon`** — bloqueado si hay evidencia fiscal (mismos campos); exige factura original,
  líneas válidas y `returnedQty` suficiente con `Decimal` (3 decimales, sin `max`); libera
  exactamente una vez en la misma transacción; cualquier inconsistencia aborta TODO.
- **Múltiples ciclos**: si la devolución vuelve a quedar ambigua tras un nuevo intento,
  puede resolverse de nuevo; el historial queda trazado (`resolutionHistory`).

## Aceptación fiscal estricta (R1/R5)

- `_classify_emission` exige `success=True` y estado DGII concluyente para `NC_ACCEPTED`;
  una consulta fallida/incompleta NUNCA produce aceptación (aunque el cuerpo aparente
  aceptación). Error técnico (timeout/red) → `NC_RECONCILING`, nunca rechazo.
- `CreditNoteInventoryService._is_fiscally_accepted` bloquea el reingreso salvo
  aceptación explícita (`ncStatus=NC_ACCEPTED`, `isSyncedWithDGII` o `dgiiStatus`
  aceptado) o fallback legacy restringido a `Emitida`/`Cobrada`. Estados desconocidos
  bloquean.

## Precisión de cantidades (R3)

Las cantidades usan `Decimal` con precisión de 3 decimales (`QUANTITY_QUANTUM`),
independiente de la precisión monetaria de 2 decimales.

## Importe y política de reembolso (R6)

- `refund_amount` debe ser mayor a cero e **igual exacto** (redondeado a 2 decimales)
  al total de la devolución; no se soportan reembolsos monetarios parciales sobre una NC.
- `allow_pending_refund` solo proviene de la política persistida de la empresa
  (`pos_refund_policy`), nunca de un parámetro del frontend.

## Modelo de estados

### Ciclo de vida (`cash_refunds.status`)
| Estado | Significado |
|---|---|
| `RESERVED` | `returnedQty` reservado; NC no confirmada |
| `COMPLETED` | Reembolso (`REFUND`) registrado |
| `FAILED` | Fallo duro (`failureStep`: `nc` o `refund`), recuperable |

### Estado de emisión de la NC (`cash_refunds.ncStatus`)
| Estado | Significado | Reembolso permitido |
|---|---|---|
| `NC_ACCEPTED` | DGII aceptó (se tiene e-NCF) | ✅ |
| `NC_PENDING_DGII` | Enviada sin confirmación (fallback, con trackId) | ❌ por defecto; ✅ con contingencia autorizada |
| `NC_REJECTED` | DGII rechazó | ❌ |
| `NC_RECONCILING` | Resultado ambiguo (timeout) | ❌ (no se reemite automáticamente) |

### Campos de reconciliación (`cash_refunds`)
`sincAttempts`, `lastSyncAt`, `reconciliationStatus`, `lastReconciliationError`, `trackId`.

## Recuperación de emisión ambigua (R3)

Si la emisión es ambigua (timeout), la NC queda `NC_RECONCILING` y **no se reemite**.
`reconcile_credit_note()` consulta DGII usando una referencia inequívoca:
- Si hay `eNCF` → `DgiiDirectService.consultar_estado_ecf`.
- Si hay `trackId` → `DgiiDirectService.check_status`.

Resultado concluyente (aceptado/rechazado) se persiste; si sigue ambiguo, permanece
`NC_RECONCILING` y el reembolso se bloquea. No se asume que un timeout equivalga a rechazo.

## Matriz de operaciones por canal de pago (reembolso)

| Canal | `REFUND.paymentMethod` | Efecto en conciliación |
|---|---|---|
| `Efectivo` | `Efectivo` | `expectedCash -= monto` |
| `Efectivo USD` | `Efectivo` (currency USD) | `expectedUSD -= monto` |
| `Tarjeta` | `Tarjeta` | `expectedCard -= monto` (NO afecta `expectedCash`) |
| `Transferencia` | `Transferencia` | `expectedTransfer -= monto` (NO afecta `expectedCash`) |

## Distinción de operaciones

| Operación | Mecanismo |
|---|---|
| **Devolución comercial** | `CashRefundService.process_refund` → NC E34 + `REFUND` + inventario |
| **Anulación técnica** | `void_invoice_route` (existente, NO modificado) |

## Componentes reutilizados
- `CreditNoteInventoryService` — reingreso/reversión de inventario E34 (idempotente).
- `EcfEmissionService` — emisión de NC E34.
- `DgiiDirectService.check_status` / `consultar_estado_ecf` — reconciliación de emisión ambigua.
- `CashAuthorizationService` / `register_cash_transaction` — autorización y `REFUND` (Fase 2).

## Archivos
- `app/services/cash_refund_service.py` *(nuevo)*.
- `app/web/pos.py` — rutas `POST /pos/refund` y `POST /pos/refund/preview`.
- `app/services/db_service.py` — `REFUND` en `CASH_SUPERVISOR_TYPES`; conciliación por canal.
- `tests/test_cash_refunds.py` *(nuevo)* — 19 pruebas.

## Pruebas
- `tests/test_cash_refunds.py` — 19 (reserva `returnedQty`, sobre-devolución, parcial, concurrencia,
  idempotencia, reuso de clave con items/importe/moneda distintos, E34 aceptada/rechazada/pendiente/
  timeout, reconciliación por trackId, recuperación de NC existente sin reemitir, canal tarjeta/efectivo).
- Regresión caja/POS: 89 passed, 2 skipped (emulador).
- Regresión general: 2238 passed, 278 failed (preexistentes, no relacionados).

## Limitaciones y riesgos
- La reconciliación usa las APIs DGII existentes (`check_status`/`consultar_estado_ecf`); si DGII no
  devuelve un resultado concluyente, la NC queda `NC_RECONCILING` y el reembolso se bloquea (no se
  reemite automáticamente). No se inventó ninguna API de consulta.
- Reembolso en tarjeta/transferencia es registro de caja, no reversión en pasarela (Azul).
- El `REFUND` se registra en el turno actual del cajero.
- Concurrencia validada con doble en memoria; Firestore Emulator pendiente.
