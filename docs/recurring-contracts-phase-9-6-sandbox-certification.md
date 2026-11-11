# Fase 9.6: Certificación Operativa del Piloto Sandbox

## Resultado

**Bloqueada por falta de autorización y datos operativos verificables.**

Auditoría repetida: el bloqueo permanece sin cambios.

No se seleccionó compañía piloto, no se modificó ningún feature flag, no se
registraron workers y no se emitieron comprobantes reales.

## Compañía piloto

```text
company_id: PENDIENTE
owner_uid: PENDIENTE
entorno: sandbox
autorización funcional: NO PRESENTADA
autorización técnica: NO PRESENTADA
responsables: NO DESIGNADOS
canal de alertas: NO CONFIGURADO
```

No se inventaron autorizaciones ni se usó una compañía encontrada en datos
locales como piloto.

## Endpoints y certificados

El archivo `.env` contiene endpoints `testecf` configurados, pero esta fase no
considera eso evidencia suficiente de autorización operativa. No se expusieron
secretos ni se verificó un certificado sandbox autorizado para una compañía
piloto.

Se requiere completar antes de continuar:

- RNC/compañía autorizada.
- certificado sandbox vigente.
- responsable fiscal.
- secuencia sandbox autorizada.
- ventana de prueba.

## Evidencia simulada disponible

Las fases anteriores certificaron con proveedores simulados y Firestore Emulator:

- preparación de snapshots;
- ocurrencias idempotentes;
- Outbox;
- concurrencia;
- fencing;
- recuperación fiscal;
- efectos parciales.

Estas pruebas no equivalen a una emisión DGII sandbox real.

## Pruebas de esta fase

No se ejecutó ciclo DGII sandbox real porque faltan compañía, autorización,
certificado y secuencia sandbox confirmados.

No se contabilizan pruebas simuladas como integración DGII real.

## Alertas

El servicio de observabilidad identifica candidatos para:

- `UNKNOWN`;
- `TIMEOUT`;
- `QUERY_ERROR`;
- Outbox fallido;
- reintentos agotados;
- leases vencidos;
- efectos pendientes.

No existe todavía un canal operativo real ni evidencia de entrega, por lo que
la certificación de alertas queda bloqueada.

## Criterio de desbloqueo

La fase podrá reanudarse cuando se entregue la ficha de compañía y:

1. Se autorice explícitamente el piloto sandbox.
2. Se confirme certificado y endpoint autorizado.
3. Se confirme secuencia sandbox.
4. Se asignen responsables y canal de incidentes.
5. Se complete el inventario de contratos candidatos.
6. Se apruebe la ventana de pruebas.

## Estado productivo

- Feature flags productivos: sin cambios.
- Workers productivos: no registrados.
- Secuencias productivas: no consumidas.
- Comprobantes reales: ninguno emitido.
- Migraciones masivas: ninguna ejecutada.

## Auditoría repetida

Se confirmó nuevamente:

- `PILOT_COMPANY_ID` y `PILOT_OWNER_UID` continúan pendientes de selección.
- No existe certificado sandbox (`.p12`/`.pfx`) disponible en el repositorio.
- Los endpoints `testecf` están configurados en `.env`, pero no constituyen una
  autorización operativa por sí solos.
- No se encontró secuencia sandbox autorizada asociada a una compañía piloto.
- No hay responsables ni canal de alertas registrados.
- El Firestore Emulator está disponible para pruebas técnicas, pero no sustituye
  la autorización DGII sandbox.

La fase no puede producir las evidencias obligatorias de emisión, e-NCF,
`trackId` y recepción de alertas sin esos insumos. No se simula una autorización
ni se ejecuta un POST DGII real.

La recepción y validación administrativa de dichos insumos queda formalizada
en `docs/recurring-contracts-phase-9-7-pilot-enablement.md`.
