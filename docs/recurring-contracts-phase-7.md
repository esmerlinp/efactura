# Contratos Recurrentes: Fase 7

## Arquitectura de transición

```text
Ruta manual ───────┐
                   ├─> RecurringContractService
Scheduler legacy ──┘       |
                            +─ feature flag por company/environment
                            |
                disabled ──+──> flujo legacy existente
                enabled  ─────> BillingService
                                  -> OccurrenceService
                                  -> OutboxCommandService
                                  -> worker fiscal explícito
```

El worker fiscal no se registra ni activa automáticamente en esta fase.

## Feature flag

Clave:

```text
recurring_contract_engine_v2
```

Ámbito:

```text
companies/{company_id}/config/feature_flags
companies/{company_id}/sandbox_config/feature_flags
```

Valor ausente o falso significa `legacy_required`.

| Compañía | Entorno | Flag | Comportamiento |
|---|---|---|---|
| cualquiera | sandbox | falso/ausente | legacy |
| cualquiera | producción | falso/ausente | legacy |
| habilitada | sandbox | verdadero | ocurrencia + outbox |
| habilitada | producción | verdadero | coordinador, sin activación automática |

## Coordinación

`RecurringContractService.prepare_and_enqueue()`:

1. Valida propietario y compañía.
2. Comprueba el feature flag.
3. Reutiliza `RecurringContractBillingService`.
4. Crea la ocurrencia determinista.
5. Prepara el snapshot.
6. Crea el comando Outbox idempotente.

No construye facturas directamente y no emite e-CF.

## Reversión

1. Cambiar el flag a `false`.
2. No borrar ocurrencias ni comandos existentes.
3. Revisar comandos `processing` antes de reanudar legacy.
4. Mantener facturas históricas intactas.

## Pruebas y limitaciones

Las pruebas verifican flag deshabilitado, convergencia manual/scheduler y
validación de ámbito. La persistencia real con Firestore Emulator continúa
pendiente; los dobles en memoria no se consideran equivalentes.
