# Caja — Fase 2 (Taxonomía, autorizaciones y trazabilidad): implementación

**Estado:** **APROBADA** (funcional y unitarias). Validación de plataforma pendiente.
Rama `feature/cash-fase2-taxonomia` (derivada de `feature/cash-integridad-fase1`).

## Acta de cierre

| Concepto | Estado |
|---|---|
| Estado funcional | Aprobada |
| Pruebas unitarias | Aprobadas (70 passed caja/POS; 2219 passed regresión) |
| Validación de plataforma (Firestore Emulator) | **Pendiente** |
| Commit | No realizado |
| Despliegue | No realizado |

## Condiciones antes de producción (obligatorias)

1. Ejecutar las pruebas de integración contra Firestore Emulator
   (`tests/test_cash_emulator_integration.py` con `FIRESTORE_EMULATOR_HOST`).
2. Confirmar transacciones concurrentes: apertura, cierre, transferencias y movimientos autorizados.
3. Verificar la política TTL para `cash_authorizations` y `sandbox_cash_authorizations` (campo `expiresAt`).
4. Ejecutar `scripts/backfill_cash_register_locks.py --mode lock` en `--dry-run`.
5. Backup y ejecutar el backfill definitivo con el módulo POS detenido.
6. Validar los flujos completos en sandbox antes del despliegue.

> Nota: la aprobación se fundamenta en los cambios y fragmentos compartidos; el diff
> completo (2660 líneas) queda preservado en la rama como evidencia de cierre.

## Arquitectura implementada

### 1. Taxonomía (`app/services/db_service.py`)
Constantes y helper `normalize_cash_type()`:
- `SALE`, `CASH_IN`, `CASH_OUT`, `CASH_DROP`, `EXPENSE`, `FUND_IN`, `FUND_OUT`,
  `TRANSFER_IN`, `TRANSFER_OUT`, `REFUND`.
- Mapeo retrocompatible al leer: `IN→CASH_IN`, `OUT→CASH_OUT` (sin migración destructiva).
- `CASH_INFLOW_TYPES` / `CASH_OUTFLOW_TYPES` — determinan el signo en el saldo esperado.

### 2. Movimientos (`register_cash_transaction`)
- Normaliza el tipo y conserva `currency`, `performedBy`, `authorizedBy`, `reason`,
  `referenceId`, `transferId`, `idempotencyKey`, `status`.
- Sigue protegido por el lock de ocupación (Fase 1).

### 3. Autorización (`app/services/cash_authorization_service.py`)
- `movement_requires_supervisor(type, amount, currency, limits)` — matriz aprobada.
- `authorize(...)` — valida PIN y SoD, y **reserva** la autorización
  (`cash_authorizations/{authRequestId}` con `status=PENDING`, creado con `create()`
  atómico). `createdAt` y `expiresAt` se guardan como **datetime UTC** (Firestore Timestamp),
  no como cadenas ISO.
- `verify(txn, ...)` — lee y valida la autorización **sin escribir** (existencia, `PENDING`,
  vigencia `expiresAt`, `contextSignature` y SoD). Devuelve los datos y la referencia.
- `consume(txn, ...)` — `verify()` + marca `CONSUMED` dentro de la transacción del movimiento.
- **Vigencia estricta**: una autorización sin `expiresAt`, con `expiresAt` malformado o
  expirado se rechaza (no se ignora el error de parsing).
- Límites por moneda (DOP ≠ USD), sin conversión implícita.

### 4. Transferencias (`app/services/cash_transfer_service.py`)
- `register_transfer(...)` — escribe `TRANSFER_OUT` + `TRANSFER_IN` en una única
  transacción Firestore, validando ambos locks `ACTIVE` y sus `shiftId` (origen y destino).
- **Orden de Firestore respetado**: todas las lecturas (locks, movimientos existentes,
  autorización) ocurren **antes** de cualquier escritura; no hay `txn.get()` tras un `set/update`.
- **Idempotencia (R1)**: si se provee `idempotency_key`, el `transfer_id` se deriva SIEMPRE
  de forma determinista (ámbito empresa+entorno). Un `transfer_id` explícito incompatible
  con la clave se rechaza. Un reintento con la misma clave y mismos parámetros devuelve la
  transferencia existente **sin consumir una autorización nueva**; si existe una transferencia
  parcial previa, o los parámetros/firmas difieren, se rechaza.

### 5. Conciliación por moneda (`close_cash_shift`)
- Los movimientos manuales en `USD` actualizan `expectedUSD`; en `DOP` actualizan
  `expectedCash`. Las ventas mantienen su ruteo por `paymentMethod`.

### 6. Configuración de límites
- `DatabaseService.get_pos_cash_limits` / `save_pos_cash_limits` leen/escriben
  `pos_cash_limits` en el documento de la empresa (`companies/{id}`).
- Endpoint `GET/POST /pos/cash-limits` (owner/supervisor) para editarlos.
- Valores por defecto: `EXPENSE` DOP 50,000; resto sin límite.

### 7. Rutas (`app/web/pos.py`)
- `POST /pos/shift/transaction` — movimientos manuales con taxonomía, moneda,
  autorización (PIN) y trazabilidad (acepta form y JSON).
- `POST /pos/shift/transfer` — transferencia entre cajas (requiere PIN).
- `GET/POST /pos/cash-limits` — configuración de límites.

### 8. UI (`templates/pos/dashboard.html`)
- Selector de tipo (taxonomía), moneda, motivo y campos de supervisor (PIN) que se
  muestran solo para tipos que requieren autorización. Envío por AJAX.

## Aislamiento y compatibilidad
- Todo bajo `companies/{companyId}/` + prefijo `sandbox_` (heredado de `_company_coll`).
- Los movimientos legacy `IN`/`OUT` se siguen leyendo (reportes históricos intactos).
- No se modificó emisión DGII, secuencia e-NCF ni el flujo de venta.

## Migración
No se requiere migración destructiva: la taxonomía es read-compatible y los límites
usan valores por defecto. (Opcional: preconfigurar `pos_cash_limits` por empresa.)

## Política TTL de Firestore (requerida en el despliegue)

Para limpiar físicamente las autorizaciones reservadas (`PENDING`) que nunca se
consumen, debe configurarse una política TTL sobre el campo `expiresAt` (que se
guarda como Timestamp UTC) en las colecciones:

- `cash_authorizations`
- `sandbox_cash_authorizations`

La TTL de Firestore elimina documentos de forma **eventual** (no instantánea); la
validación en código (`verify`) impide consumir una autorización ya expirada aunque
el documento aún no haya sido borrado. Verificar en la consola que `expiresAt` se
reconoce como campo timestamp por la política.

## Pruebas
- `tests/test_cash_movements.py` — 25 (taxonomía, matriz, límites por moneda, PIN
  single-use/SoD, contexto incorrecto, consumo concurrente, atomicidad consumo+movimiento,
  expiración/malformado/ausencia de `expiresAt`, conciliación DOP/USD, transferencia
  atómica/idempotente/reintento por clave/reutilización con parámetros distintos/
  transfer_id explícito incompatible/ámbito empresa+entorno/sesión destino distinta/
  idempotencia sin consumir autorización nueva/transferencia parcial preexistente).
- `tests/test_pos_movements_route.py` — 4 (ruta: sin autorización, 403 sin PIN, 403
  por límite, normalización legacy).
- Regresión caja/POS: 70 passed, 2 skipped (emulador).
- Regresión general: 2219 passed, 278 failed (los 278 son preexistentes, no relacionados).

## Riesgos y limitaciones
- El PIN se valida contra `posSupervisorPin` existente; no hay bloqueo por intentos
  fallidos (pendiente de endurecer en una fase posterior).
- La UI de configuración de límites (admin) aún no tiene pantalla dedicada; se edita
  vía el endpoint `/pos/cash-limits` (la UI de movimientos ya está conectada).
- Una autorización reservada (`PENDING`) que nunca se consume queda huérfana hasta que
  la política TTL de Firestore la elimine (eventual).
- Concurrencia validada con doble en memoria; pendiente Firestore Emulator (igual que Fase 1).
