# Fase 9.7: Gestión de habilitación del piloto controlado

## Estado administrativo

```text
estado: PENDIENTE DE INSUMOS
company_id: PENDIENTE
owner_uid: PENDIENTE
entorno: sandbox
feature_flag: NO MODIFICAR
workers: NO REGISTRAR
emisión: NO EJECUTAR
```

Esta fase prepara la recepción y validación de insumos. No selecciona una
compañía por inferencia y no realiza cambios productivos.

## 1. Ficha de habilitación

Debe completarse y aprobarse fuera del código antes de ejecutar pruebas DGII:

```text
pilot_id:
company_id:
owner_uid:
company_name:
company_rnc:
environment: sandbox

functional_owner:
technical_owner:
fiscal_dgii_owner:
operational_approver:
incident_owner:

functional_authorization_reference:
technical_authorization_reference:
fiscal_authorization_reference:
approved_at:
approved_by:

alert_channel:
alert_test_recipient:
support_window:
test_window:
rollback_approver:
```

Los valores faltantes permanecen literalmente como `PENDIENTE`; no deben
rellenarse con datos inferidos de Firestore, `.env` o sesiones locales.

## 2. Checklist de recepción

### Compañía y responsables

- [ ] `company_id` recibido de la autorización formal.
- [ ] `owner_uid` confirmado contra el documento de compañía.
- [ ] Razón social y RNC verificados.
- [ ] Responsable funcional designado.
- [ ] Responsable técnico designado.
- [ ] Responsable fiscal/DGII designado.
- [ ] Aprobador operativo designado.
- [ ] Canal de incidentes probado.
- [ ] Ventana de pruebas aprobada.

### Certificado DGII sandbox

- [ ] Archivo recibido por canal seguro.
- [ ] Formato `.p12`/`.pfx` validado sin copiarlo al repositorio.
- [ ] Contraseña entregada por canal separado.
- [ ] Contraseña nunca escrita en documentos, logs, tickets ni variables
  persistentes del proyecto.
- [ ] Vigencia verificada.
- [ ] Titular del certificado verificado.
- [ ] RNC/titular corresponde a la compañía piloto.
- [ ] Prueba de carga realizada en memoria o entorno efímero.
- [ ] Archivo eliminado del espacio temporal después de la prueba.
- [ ] Hash o referencia de auditoría registrada sin revelar el secreto.

### Endpoint sandbox

- [ ] Endpoint de autenticación autorizado.
- [ ] Endpoint de recepción autorizado.
- [ ] Endpoint de consulta autorizado.
- [ ] Endpoint RFCE autorizado si aplica.
- [ ] Ambiente confirmado como `testecf`/sandbox.
- [ ] No se utilizan endpoints de producción.

La presencia de URLs en `.env` no constituye por sí sola autorización.

### Secuencias sandbox

- [ ] Tipo e-CF autorizado para el piloto.
- [ ] Rango sandbox identificado.
- [ ] Documento de autorización recibido.
- [ ] Estado de la secuencia `ACTIVA` confirmado.
- [ ] Rango inicial y final registrados sin modificarlo.
- [ ] Próximo consecutivo documentado antes de la prueba.
- [ ] Secuencia separada de producción.
- [ ] Aprobación fiscal para consumirla durante la ventana.

## 3. Contratos candidatos

Cada candidato debe registrarse en una tabla de control externa:

| Campo | Estado |
|---|---|
| contract_id | PENDIENTE |
| contract_number | PENDIENTE |
| client_id/RNC | PENDIENTE |
| schemaVersion=2 | PENDIENTE |
| status=active | PENDIENTE |
| líneas/precios/descuentos | PENDIENTE |
| moneda | PENDIENTE |
| ecfType | PENDIENTE |
| needsFiscalReview=false | PENDIENTE |
| período candidato | PENDIENTE |
| facturas históricas revisadas | PENDIENTE |
| autorización funcional | PENDIENTE |

No se deben incluir contratos legacy sin migración validada ni contratos con
revisión fiscal pendiente.

## 4. Matriz de pruebas DGII sandbox

| ID | Escenario | Proveedor | Evidencia requerida | Secuencia |
|---|---|---|---|---|
| S-01 | Aceptación | DGII sandbox autorizado | e-NCF, trackId, respuesta, ocurrencia, Outbox | Una sandbox |
| S-02 | Rechazo | DGII sandbox autorizado/simulado | motivo, intento terminal, sin reintento ciego | Una sandbox |
| S-03 | Pendiente | Simulado o sandbox | `PENDING`, trackId, Outbox retry | Una sandbox |
| S-04 | Timeout | Simulado | `TIMEOUT`, intento conservado | Una sandbox |
| S-05 | Sin trackId | Simulado | `UNKNOWN`, sin nueva secuencia | Una sandbox |
| S-06 | Error consulta | Simulado/sandbox | `QUERY_ERROR`, sin rechazo automático | Ninguna adicional |
| S-07 | Consulta aceptada | Sandbox/simulado | intento original pasa a `ACCEPTED` | Ninguna adicional |
| S-08 | Interrupción post-respuesta | Simulado | un POST, una secuencia, recuperación | Una sandbox |
| S-09 | Efectos parciales | Proveedores internos simulados | estados individuales y reanudación | Ninguna adicional |

Cada fila debe registrar ejecutor, fecha, compañía, entorno, IDs y resultado.

## 5. Alertas y evidencia de recepción

Canal de prueba:

```text
alert_channel: PENDIENTE
test_recipient: PENDIENTE
delivery_reference: PENDIENTE
tested_at: PENDIENTE
received_by: PENDIENTE
```

Debe probarse recepción de alertas para:

- `UNKNOWN`;
- `TIMEOUT`;
- `QUERY_ERROR`;
- Outbox fallido;
- reintentos agotados;
- lease vencido;
- efecto post-aceptación pendiente.

No debe guardarse información sensible de certificados o contraseñas en el
contenido de las alertas.

## 6. Registro de insumos

| Insumo | Estado actual | Evidencia |
|---|---|---|
| Compañía piloto | Pendiente | No recibida |
| Autorización funcional | Pendiente | No recibida |
| Autorización técnica | Pendiente | No recibida |
| Responsable fiscal | Pendiente | No designado |
| Certificado sandbox | Pendiente | No recibido |
| Endpoint autorizado | Pendiente | `.env` no es autorización |
| Secuencia sandbox | Pendiente | No identificada |
| Canal de alertas | Pendiente | No configurado |
| Ventana de pruebas | Pendiente | No aprobada |

## Criterio de salida

La fase se puede cerrar administrativamente cuando todos los insumos críticos
estén recibidos y verificados. La ejecución DGII sandbox será una fase posterior
con autorización expresa.

Producción queda fuera del alcance.
