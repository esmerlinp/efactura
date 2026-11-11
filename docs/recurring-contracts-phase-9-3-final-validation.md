# Fase 9.3: Validación final de recuperación fiscal

## Interrupción certificada

El escenario se ejecutó con Firestore Emulator real:

1. Se persistió el intento `UNKNOWN` con e-NCF y `sequence_log_id`.
2. Se contabilizó un único POST DGII simulado.
3. El proveedor simuló `ACCEPTED`.
4. Se interrumpió antes de guardar `ACCEPTED` localmente.
5. El estado persistido siguió siendo `UNKNOWN`.
6. El proceso se reinició.
7. La reconciliación consultó la evidencia simulada y persistió `ACCEPTED`.

Resultado real:

```text
accepted_before_persist_status: UNKNOWN
accepted_after_reconcile_status: ACCEPTED
simulated_dgii_posts: 1
sequence_consumptions: 1
assertions: passed
```

No se realizó un segundo POST ni se consumió una segunda secuencia.

## Efectos parciales

Con Firestore Emulator:

```text
accounting_effect: COMPLETED
inventory_effect: PENDING
post_acceptance_status: pending_effects
```

En la segunda ejecución:

- contabilidad permaneció `COMPLETED` y no se repitió;
- inventario pudo reintentarse;
- la aceptación fiscal permaneció intacta;
- el procesamiento no se consideró completo mientras existió un efecto pendiente.

## Casos ambiguos

- Timeout sin `trackId`: permanece `UNKNOWN`.
- Respuesta ambigua sin `trackId`: no se consulta ni se reemite a ciegas.
- Error temporal de consulta: `QUERY_ERROR`.
- Consulta posterior con `ACCEPTED`: actualiza el intento original.
- Ningún caso ambiguo consume una nueva secuencia.

## Pruebas

Pruebas específicas nuevas:

```text
2 pruebas de efectos/reconciliación aprobadas
```

Suite acumulada:

```text
88 pruebas aprobadas antes de esta etapa
90 pruebas lógicas aprobadas tras esta etapa
```

Prueba real Firestore:

```text
scripts/run_firestore_phase93_recovery.py
assertions: passed
```

## Límites

- El proveedor DGII fue simulado.
- No se enviaron solicitudes reales.
- No se consumieron secuencias productivas.
- Los workers productivos y la emisión automática siguen bloqueados.
