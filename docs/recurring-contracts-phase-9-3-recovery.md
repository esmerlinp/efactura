# Fase 9.3: Recuperación ante fallos fiscales

## Implementación

Se reforzó `RecurringContractEmissionWorker` para consultar primero los
intentos existentes de la ocurrencia antes de consumir una secuencia:

- intento `ACCEPTED`: finaliza el Outbox sin reemitir;
- intento `PENDING`, `TIMEOUT`, `UNKNOWN` o `QUERY_ERROR`: exige reconciliación;
- no se consume una nueva secuencia para resultados ambiguos.

También se añadió consulta de intentos por `occurrence_id` al store de emisión.

## Pruebas unitarias

```text
12 pruebas ejecutadas
12 aprobadas
0 fallidas
```

Se verificó:

- recuperación después de reinicio con `ACCEPTED` persistido;
- ausencia de segunda secuencia;
- ausencia de segundo POST DGII;
- recuperación de intento ambiguo sin reemisión;
- reconciliación `UNKNOWN`/`QUERY_ERROR`;
- efectos post-aceptación idempotentes.

## Prueba real Firestore Emulator

El script real:

```bash
PYTHONPATH=. FIRESTORE_EMULATOR_HOST=127.0.0.1:8088 \
  .venv-cert/bin/python scripts/run_firestore_contract_certification.py
```

produjo:

```text
assertions: passed
fencing_token: 3
recovered_status: retry_wait
reconciled_attempt_status: ACCEPTED
post_acceptance_effect_status: COMPLETED
```

La prueba utilizó Firestore Emulator real para:

- ocurrencias concurrentes;
- comandos Outbox concurrentes;
- leases y fencing;
- persistencia de intentos;
- reconciliación a `ACCEPTED`;
- efecto post-aceptación persistido y no duplicado.

## Límites

- DGII fue simulado; no se enviaron solicitudes reales.
- No se consumieron secuencias fiscales productivas.
- La caída entre POST DGII real y persistencia se simuló mediante estados y
  proveedores controlados, no mediante tráfico DGII real.
- La emisión automática y los workers productivos siguen bloqueados.
