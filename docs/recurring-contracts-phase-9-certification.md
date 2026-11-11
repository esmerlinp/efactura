# Fase 9: Certificación Integral

## Inicio

La Fase 9 fue iniciada sin habilitar emisión automática en producción.

## Matriz de certificación inicial

| Área | Resultado |
|---|---|
| Dominio y reglas | Aprobado en fases anteriores |
| Coordinación manual/scheduler | Aprobado en memoria |
| Ocurrencias y Outbox | Aprobado en memoria |
| Emisión ambigua | En pruebas unitarias |
| Reconciliación sin `trackId` | Verificado: permanece `UNKNOWN` |
| Error de consulta DGII | Verificado: `QUERY_ERROR`, no rechazo |
| Post-aceptación idempotente | Verificado en pruebas |
| Firestore Emulator | Pendiente bloqueante |
| Concurrencia Firestore real | Pendiente bloqueante |
| Recuperación DGII + persistencia real | Pendiente de integración |

## Bloqueo de entorno

El repositorio no contiene configuración de Firestore Emulator ni el comando
`firebase`. El entorno actual usa Python 3.14 y el SDK Firestore falla al
importar por incompatibilidad binaria de `grpc` (`cygrpc`).

No se modificaron dependencias de producción para ocultar este problema. Las
pruebas en memoria no se presentan como equivalentes a Firestore.

## Criterio de producción

La emisión automática permanece bloqueada hasta validar:

- transacciones Firestore reales;
- carreras manual/scheduler;
- leases y fencing reales;
- recuperación de persistencia después de aceptación DGII;
- efectos parciales post-aceptación;
- feature flags ante errores de lectura;
- aislamiento real de compañías y entornos.

## Integración Firestore ejecutada

Se creó un entorno aislado `.venv-cert` sin modificar el runtime principal:

```text
Python 3.13.15
google-cloud-firestore 2.21.0
grpcio-status 1.69.0
protobuf 5.29.6
pytest 8.3.4
Firestore Emulator 1.22.0
Java 21.0.13
```

El Emulator se ejecutó en:

```text
FIRESTORE_EMULATOR_HOST=127.0.0.1:8088
```

Comando reproducible:

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
gcloud beta emulators firestore start --host-port=127.0.0.1:8088

PYTHONPATH=. FIRESTORE_EMULATOR_HOST=127.0.0.1:8088 \
  .venv-cert/bin/python scripts/run_firestore_contract_certification.py
```

Resultado real:

```text
assertions: passed
occurrence_id: aaaf375ee70ac4e7dfdcb20a3a30848df9d8e9f2fd3927166edf5a9429bd8398
command_id: 55dbd87ff4d13aa1c20f1f4f426d3c498c6041a0ff3fbdf86e364e1bcd9a16b9
fencing_token: 2
recovered_status: retry_wait
reconciled_attempt_status: ACCEPTED
post_acceptance_effect_status: COMPLETED
```

La prueba real verificó:

- 32 creaciones concurrentes de una ocurrencia con un único ID lógico;
- 32 creaciones concurrentes de un comando Outbox con un único ID lógico;
- lease vencido y recuperación;
- fencing token incrementado;
- persistencia de intento fiscal y reconciliación a `ACCEPTED`;
- persistencia y no duplicación de efecto post-aceptación;
- aislamiento por compañía y sandbox.

## Limitaciones de integración

- La suite `pytest` de integración no se ejecuta dentro del entorno principal,
  porque su `conftest.py` inicializa módulos Firebase/mock incompatibles con el
  bootstrap mínimo. La certificación real se ejecutó mediante el script en un
  intérprete limpio, usando el SDK Firestore real.
- No se enviaron solicitudes DGII reales ni se consumieron secuencias fiscales.
- No se certificó la caída entre un POST DGII real y la persistencia local; se
  requiere un harness de red controlado en la siguiente iteración.
- No se inició ningún worker productivo ni se modificó el scheduler.
