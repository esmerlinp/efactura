# Caja — Fase 1 (Integridad transaccional): cierre

**Estado:** aprobada a nivel de diseño y pruebas unitarias. **Validación de plataforma pendiente.**

## Alcance implementado (rama `feature/cash-integridad-fase1`)

1. **Ocupación de caja física**: una sola sesión activa por caja mediante documento de lock `cash_register_locks/{registerId}` / `sandbox_cash_register_locks/{registerId}` creado atómicamente (`create()`). Doble apertura → `CashRegisterOccupiedError` → HTTP 409.
2. **Idempotencia de venta**: reserva atómica de clave con lease (`PENDING/COMPLETED/FAILED`, `leaseOwner`, `leaseExpiresAt`); `invoice_id` derivado de la key; validación del propietario del lease al confirmar/fallar.
3. **Cierre transaccional**: lock `ACTIVE→CLOSING` bloquea ventas/movimientos; finalización atómica (shift + register + delete lock); guard de cierre duplicado idempotente.
4. **Corrección del reporte Z**: se excluyen las facturas individuales `Consolidada` para no contar dos veces junto al consolidado.
5. **Precisión monetaria**: `Decimal` + `ROUND_HALF_UP` en el cálculo del cierre.
6. **Movimientos manuales**: también protegidos por el lock (ausencia de lock = error, no autorización).

### Reglas de seguridad clave
- La **ausencia de lock** bloquea ventas y movimientos (no hay autorización implícita legacy).
- La **reversión de venta** por fallo de caja ocurre **antes** de emitir e-CF a DGII y usa idempotencia (`INVOICE_CANCEL/{invoice_id}_{item_id}`) para no duplicar el reingreso de inventario.
- La **confirmación de idempotencia** solo procede si el `leaseOwner` coincide (un proceso viejo no puede confirmar tras perder su lease).

## Pruebas

- `tests/test_cash_integrity.py` — 18 pruebas (ocupación, concurrencia, idempotencia, lock, cierre, Z).
- `tests/test_pos_checkout.py` — 17 pruebas (incluye reversión de venta bloqueada).
- `tests/test_pos_warehouse_resolution.py` — 6 pruebas.
- `tests/test_cash_emulator_integration.py` — gated (skip sin `FIRESTORE_EMULATOR_HOST`).

Resultado: **41 passed, 2 skipped (emulador)**.

## Limitación documentada

**La concurrencia NO se ha validado contra Firestore Emulator ni contra una instancia real.**
El doble en memoria (`tests/cash_firestore_double.py`) valida la lógica de guardas de forma
determinista, pero la atomicidad real depende de las primitivas de Firestore
(`DocumentReference.create()` y `db.transaction()`). No debe afirmarse que la integridad
transaccional está comprobada en producción hasta completar la validación de plataforma.

## Checklist de validación de plataforma (obligatorio antes de desplegar)

1. Ejecutar `tests/test_cash_emulator_integration.py` contra Firestore Emulator
   (`gcloud beta emulators firestore start` + `FIRESTORE_EMULATOR_HOST`).
2. Ejecutar `python scripts/backfill_cash_register_locks.py --mode lock` en **dry-run**
   y revisar los turnos que detecta (turnos `OPEN/CLOSING/REOPENED` sin lock).
3. Respaldar datos y ejecutar el backfill con `--apply` **con el módulo POS detenido**.
4. Validar apertura, venta, movimiento manual, cierre y reintentos en un entorno de pruebas.
5. Confirmar que producción y sandbox usan sus respectivas colecciones de locks
   (`cash_register_locks` vs `sandbox_cash_register_locks`).

## Archivos

- Modificados: `app/services/db_service.py`, `app/web/pos.py`, `tests/test_pos_checkout.py`.
- Nuevos: `tests/cash_firestore_double.py`, `tests/test_cash_integrity.py`,
  `tests/test_cash_emulator_integration.py`, `scripts/backfill_cash_register_locks.py`.
- Diff completo: `/var/folders/h3/pr9t_5_j61gb0thjvcn0t53m0000gn/T/opencode/fase1_diff_review.txt`.
