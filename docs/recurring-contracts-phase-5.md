# Contratos Recurrentes: Fase 5

## Alcance

Esta fase implementa los componentes aislados para emisión, reconciliación y
post-aceptación. No registra el worker en el scheduler ni activa facturación
automática.

Archivos principales:

- `app/models/recurring_contract_emission.py`
- `app/services/recurring_contract_emission_store.py`
- `app/services/recurring_contract_emission_worker.py`
- `app/services/recurring_contract_reconciliation_service.py`
- `app/services/recurring_contract_post_acceptance_service.py`
- `tests/test_recurring_contract_emission_phase5.py`

## Estados

### Intento fiscal

```text
UNKNOWN / PENDING / TIMEOUT / QUERY_ERROR
              |
              v
        reconciliación
          |       |
          v       v
       ACCEPTED  REJECTED
```

Un resultado ambiguo nunca se convierte automáticamente en rechazo y nunca
crea otra secuencia. La reconciliación consulta el `trackId` existente antes de
permitir cualquier decisión posterior.

### Post-aceptación

```text
ACCEPTED
   |
   +--> ACCOUNTING effect
   +--> INVENTORY effect
   +--> NOTIFICATION effect
```

Cada efecto utiliza una clave lógica independiente:

```text
invoice_id + event_type
```

Un efecto completado no vuelve a ejecutar su handler.

## Integración fiscal

El worker reutiliza exclusivamente:

- `EcfEmissionService.emit_electronic_comprobante()`;
- `DatabaseService.consume_next_sequence()`;
- `get_ecf_type_short_code()`.

No se creó un segundo motor DGII.

El e-NCF y `sequence_log_id` se guardan en cada intento. Un timeout, error de
consulta o respuesta desconocida conserva el intento y el e-NCF reservado.

## Almacenamiento

Las colecciones previstas son:

```text
companies/{company_id}/contract_emission_attempts
companies/{company_id}/sandbox_contract_emission_attempts
companies/{company_id}/contract_post_acceptance_effects
companies/{company_id}/sandbox_contract_post_acceptance_effects
```

La implementación de los stores valida siempre `owner_uid`, `company_id` y el
entorno seleccionado.

## Índices recomendados

Para reconciliación y monitoreo:

```text
contract_emission_attempts:
occurrence_id ASC, status ASC, updated_at ASC
company_id ASC, status ASC, response_timestamp ASC
track_id ASC

contract_post_acceptance_effects:
invoice_id ASC, event_type ASC
status ASC, updated_at ASC
```

Las operaciones por ID determinista no requieren índices compuestos.

## Evidencia de no duplicación

Las pruebas verifican que:

- una respuesta `TIMEOUT` conserva el intento y solo llama una vez al consumidor
  de secuencias;
- reconciliar un resultado `PENDING` no consume otra secuencia;
- un resultado `ACCEPTED` finaliza el comando sin reemisión;
- contabilidad u otros efectos posteriores solo ejecutan su handler una vez por
  `invoice_id + event_type`.

## Firestore Emulator

La validación real con Firestore Emulator sigue pendiente. El entorno no tiene:

- comando `firebase`;
- `firebase.json`;
- configuración de Emulator;
- SDK Firestore importable, debido al error binario de `grpc` con Python 3.14.

Las 64 pruebas de esta fase usan dobles transaccionales en memoria y no se
presentan como equivalentes a pruebas del SDK Firestore. La emisión automática
no puede habilitarse hasta ejecutar la integración real.

## Restricciones respetadas

- No se modificaron rutas ni UI.
- No se modificó el scheduler.
- No se activó el worker.
- No se migraron contratos históricos.
- No se ejecutó contabilidad ni inventario real.
- No se modificaron facturas históricas.
