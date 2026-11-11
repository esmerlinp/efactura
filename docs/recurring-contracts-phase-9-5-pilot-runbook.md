# Fase 9.5: Preparación del Piloto Controlado

## Estado

Este documento prepara el piloto, pero no selecciona ni activa ninguna
compañía. La emisión automática y los workers productivos permanecen
bloqueados.

## 1. Selección y autorización de compañía

La compañía piloto queda como:

```text
PILOT_COMPANY_ID: PENDIENTE DE SELECCIÓN
PILOT_OWNER_UID: PENDIENTE DE SELECCIÓN
PILOT_ENVIRONMENT: sandbox primero; producción solo con aprobación posterior
```

### Criterios de selección

La compañía propuesta debe:

- aceptar participar en el piloto;
- tener un responsable funcional identificado;
- tener un responsable técnico y canal de incidentes;
- contar con contratos V2 completos y con líneas;
- tener clientes y RNC verificados;
- tener tipos e-CF elegibles y revisados;
- no depender inicialmente de tipos fiscales condicionados;
- no tener contratos con `needs_fiscal_review=true` entre los candidatos;
- disponer de secuencias sandbox autorizadas para pruebas;
- aceptar pruebas controladas sin emisión productiva.

### Ficha obligatoria

Antes de aprobar la compañía se debe completar:

```text
company_id:
owner_uid:
entorno:
responsable_funcional:
responsable_tecnico:
canal_incidentes:
fecha_de_aprobacion:
aprobador:
```

### Contratos candidatos

Para cada contrato candidato:

- ID y número contractual.
- Cliente y RNC.
- `schemaVersion=2`.
- Estado `active`.
- Líneas y precios revisados.
- Moneda revisada.
- Vigencia y próximo período revisados.
- Tipo e-CF revisado.
- `needs_fiscal_review=false`.
- Ausencia de ocurrencias o comandos V2 en curso, o plan explícito de recuperación.
- Ausencia de factura histórica que pueda confundirse con la ocurrencia piloto.

## 2. Responsables y escalamiento

| Rol | Responsabilidad | Sustituto |
|---|---|---|
| Responsable técnico | Activación, métricas, workers y rollback | Por designar |
| Responsable funcional | Valida cliente, contrato, importes y resultado fiscal | Por designar |
| Responsable DGII/fiscal | Valida tipo e-CF, RNC, respuesta y reconciliación | Por designar |
| Atención de incidentes | Recibe alertas y coordina escalamiento | Por designar |
| Aprobador operativo | Autoriza cada cambio de entorno | Por designar |

### Severidades

| Severidad | Casos | Acción |
|---|---|---|
| SEV-1 | Duplicidad fiscal, doble secuencia, aislamiento roto | Suspender nuevas operaciones V2 inmediatamente; escalar técnico y fiscal |
| SEV-2 | `ACCEPTED` sin efectos, Outbox agotado, persistencia inconsistente | Pausar nuevas operaciones; reconciliar individualmente |
| SEV-3 | `UNKNOWN`, `TIMEOUT`, `QUERY_ERROR`, lease vencido | Abrir caso y reconciliar según SLA |
| SEV-4 | Error de lectura de flag, alerta informativa, datos incompletos | Registrar y corregir antes del siguiente período |

### Canales

Los canales reales deben completarse antes de activar:

```text
alertas técnicas:
incidentes:
escalamiento fiscal:
ventana de soporte:
```

## 3. Validación DGII controlada

### Sandbox

1. Confirmar certificado y endpoints sandbox.
2. Confirmar secuencia sandbox disponible.
3. Validar cliente y RNC.
4. Preparar snapshot y período.
5. Crear ocurrencia y comando Outbox.
6. Ejecutar el worker únicamente bajo autorización.
7. Registrar e-NCF, `sequenceLogId`, `trackId`, XML y estado.
8. Probar aceptación, rechazo, pendiente y timeout con proveedor simulado o
   endpoint autorizado.
9. Reconciliar estados ambiguos.
10. Verificar efectos post-aceptación individualmente.

### Producción

No se ejecuta durante esta fase. Requiere aprobación formal independiente,
secuencia autorizada y ventana operativa.

## 4. Runbook de activación

### Precondiciones

- Ficha de compañía aprobada.
- Pruebas sandbox aprobadas.
- Firestore Emulator y pruebas de integración aprobadas.
- Contratos candidatos revisados.
- Responsables y canales confirmados.
- Snapshot/backups operativos disponibles.
- Plan de suspensión probado.

### Activación controlada

1. Registrar solicitud de cambio con compañía, entorno y aprobador.
2. Verificar que no existan operaciones V2 activas pendientes sin plan.
3. Confirmar que contratos legacy no serán procesados por el motor nuevo.
4. Establecer el flag únicamente en el documento de la compañía y entorno
   autorizados.
5. Leer nuevamente el flag y registrar evidencia.
6. Crear una sola ocurrencia de prueba.
7. Confirmar que el scheduler y la ruta manual convergen en la misma clave.
8. No registrar workers productivos sin aprobación posterior.

## 5. Suspensión y rollback

El rollback no consiste simplemente en cambiar el flag a `false` si existen
operaciones V2 en curso.

### Suspensión segura

1. Detener la creación de nuevas ocurrencias/comandos para la compañía.
2. No iniciar nuevos workers para esa compañía.
3. Esperar o recuperar leases activos.
4. Inspeccionar comandos `processing`, `retry_wait` y `failed`.
5. Reconciliar intentos `UNKNOWN`, `TIMEOUT` y `QUERY_ERROR`.
6. Completar o marcar explícitamente los efectos pendientes.
7. Confirmar que no haya secuencias o e-NCF sin clasificación.
8. Solo después, cambiar el flag a `false` si el aprobador lo autoriza.
9. No permitir que legacy procese una ocurrencia V2 existente.
10. Registrar el estado final y el responsable.

### Recuperación de workers

- Lease vigente: no tomar control.
- Lease vencido: adquirir con fencing nuevo.
- Worker obsoleto: rechazar cualquier escritura.
- Comando `UNKNOWN`: reconciliar antes de reemitir.
- Comando `FAILED` permanente: intervención funcional/fiscal.
- Efecto `COMPLETED`: no repetir.
- Efecto `PENDING`: reanudar individualmente.

## 6. Observabilidad

Alertas obligatorias:

- `UNKNOWN`.
- `TIMEOUT`.
- `QUERY_ERROR`.
- Outbox `failed`.
- Reintentos agotados.
- Leases vencidos.
- Efectos post-aceptación pendientes.
- Intento `ACCEPTED` con Outbox no completado.
- Contrato con revisión fiscal pendiente intentando procesar.
- Error de lectura del feature flag.

El servicio `RecurringContractObservabilityService` genera candidatos; antes
del piloto deben conectarse a un canal operativo y a responsables concretos.

## 7. Checklist de aprobación

### Funcional

- [ ] Contratos candidatos revisados.
- [ ] Líneas, impuestos, descuentos y moneda confirmados.
- [ ] Cliente y RNC confirmados.
- [ ] Tipo e-CF confirmado.
- [ ] Períodos y vencimientos confirmados.
- [ ] Reconciliación aprobada.

### Técnica

- [ ] Emulator certificado.
- [ ] Concurrencia certificada.
- [ ] Fencing certificado.
- [ ] Recuperación fiscal certificada.
- [ ] Rollback probado.
- [ ] No hay worker productivo registrado.
- [ ] No hay doble motor para la misma ocurrencia.

### Operativa

- [ ] RACI completado.
- [ ] Canales confirmados.
- [ ] SLA de incidentes definido.
- [ ] Aprobador identificado.
- [ ] Ventana de piloto definida.
- [ ] Evidencia y backups preparados.

## Riesgos restantes

- Aún no se autoriza emisión productiva.
- La validación DGII productiva requiere autorización fiscal explícita.
- Las alertas aún requieren conectar un canal operativo real.
- No se ha seleccionado una compañía piloto.
- El scheduler no debe activar workers fiscales automáticamente durante esta
  fase.
