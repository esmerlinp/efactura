# Contratos Recurrentes: Fase 3

## Alcance implementado

Esta fase agrega la persistencia y coordinación de ocurrencias de facturación.
No emite e-CF, no consume secuencias, no usa scheduler, no crea outbox y no
ejecuta contabilidad ni inventario.

Archivos:

- `app/models/recurring_contract_occurrence.py`
- `app/services/recurring_contract_occurrence_service.py`
- `tests/test_recurring_contract_occurrence_service.py`

## Colección

La colección se ubica bajo el ámbito de la compañía:

```text
companies/{company_id}/contract_billing_occurrences
companies/{company_id}/sandbox_contract_billing_occurrences
```

La combinación lógica se transforma en un ID determinista SHA-256:

```text
company_id + ":" + contract_id + ":" + billing_period_key
```

Esto hace que la creación idempotente no dependa de una consulta previa.

## Transacciones

`create_idempotent`, `acquire_lease` y `transition_with_fencing` leen y
actualizan el documento dentro de una transacción Firestore.

La creación usa `transaction.create`, por lo que dos escritores que compitan
por el mismo ID lógico no pueden crear dos documentos.

## Estados

```text
reserved -> prepared -> processing
processing -> pending_reconciliation
processing -> completed
processing -> failed
```

Los estados terminales `completed` y `cancelled` no pueden reutilizarse.

## Leases y fencing

Cada lease guarda:

- `lease_owner`;
- `lease_expires_at`;
- `fencing_token` monotónico;
- `attempt_count`.

Un lease vencido puede ser tomado por otro worker, incrementando el fencing
token. Un worker anterior no puede modificar la ocurrencia porque su token ya

## Factura preparada

La preparación delega completamente en `RecurringContractBillingService` de
Fase 2. El servicio de ocurrencias no duplica las reglas comerciales,
calendario ni fiscalidad.

## Índices Firestore

La creación y lectura por ID no requiere índices compuestos. Para consultas
operativas futuras, se recomienda crear:

```text
owner_uid ASC, status ASC, lease_expires_at ASC
contract_id ASC, period_start ASC
status ASC, updated_at ASC
```

La creación de estos índices debe hacerse al activar consultas de lista o
reconciliación; esta fase no ejecuta esas consultas.

## Pruebas

Se prueban 64 creaciones concurrentes con `ThreadPoolExecutor`, además de:

- idempotencia secuencial;
- aislamiento de compañía y propietario;
- lease vigente;
- recuperación de lease vencido;
- fencing monotónico;
- rechazo de worker obsoleto;
- transiciones válidas.

Las pruebas en memoria usan un backend transaccional con lock real entre hilos
y detección de conflictos de lectura/escritura. No son equivalentes a pruebas
del SDK Firestore.

Se añadió `tests/test_recurring_contract_outbox_firestore.py`, que se ejecuta
solo cuando `FIRESTORE_EMULATOR_HOST` está configurado. En el entorno actual no
existe el comando `firebase`, no hay configuración de Emulator en el repositorio
y el SDK Firestore no importa por incompatibilidad binaria de `grpc` con Python
3.14 (`cannot import name 'cygrpc'`). La validación real contra Firestore
Emulator queda pendiente y no se presenta como ejecutada.
