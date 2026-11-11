# Fase 9.4: Auditoría de preparación productiva

## Estado

La fase permanece en auditoría. No se activan workers ni emisión automática.

## Checklist

### Integración comercial-fiscal

- [x] El billing service construye desde snapshots.
- [x] Fiscalidad se valida antes del consumo de secuencia.
- [x] Contratos con revisión fiscal son rechazados.
- [ ] Prueba de emisión DGII real controlada.
- [ ] Validación de todos los descuentos/recargos del catálogo en producción.

### Secuencias

- [x] Consumo delegado al mecanismo central.
- [x] No se reconsume ante estados ambiguos.
- [x] Pruebas de límites en Emulator.
- [ ] Certificación operativa de secuencias productivas sin consumo real.

### Migración

- [x] Fingerprint determinista.
- [x] Dry-run.
- [x] Reversión no destructiva.
- [ ] Procedimiento aprobado para contratos modificados después de migración.
- [ ] Reconciliación de dependencias existentes antes de rollback.

### Feature flags

- [x] Flag por compañía y entorno.
- [x] Deshabilitado por defecto.
- [x] La UI no modifica flags.
- [ ] Activación piloto con doble motor bloqueado por operación.
- [ ] Procedimiento de suspensión de emergencia.

### Observabilidad

Se añadió `RecurringContractObservabilityService` para resumir y alertar sobre:

- `UNKNOWN`, `TIMEOUT`, `QUERY_ERROR`;
- pendientes de reconciliación;
- Outbox en retry o failed;
- leases vencidos;
- efectos pendientes.

Falta conectar estos candidatos a un canal operativo de alertas antes de
producción.

## Dependencias pendientes

- Prueba DGII controlada de extremo a extremo.
- Política de alertas y responsables.
- Runbook de activación, rollback y pausa.
- Aprobación de compañía piloto.

La preparación operativa detallada se encuentra en
`docs/recurring-contracts-phase-9-5-pilot-runbook.md`. La compañía piloto no
ha sido seleccionada ni activada.

La emisión automática productiva permanece bloqueada.
