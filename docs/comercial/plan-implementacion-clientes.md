# PLAN DE TRABAJO DE IMPLEMENTACIÓN — CLIENTES NUEVOS

| Campo | Detalle |
|---|---|
| **Documento** | Plan estándar de implementación de VykOne ERP para clientes nuevos |
| **Código del documento** | COM-IMP-002 |
| **Versión** | 1.0 |
| **Fecha de emisión** | 17 de agosto de 2026 |
| **Responsable** | Esmerlin Paniagua Martinez — Gerente |
| **Aplica a** | Altas de clientes en los planes Esencial, Pro y Enterprise |

> **Objetivo:** llevar al cliente desde la firma del contrato hasta la operación en
> producción con facturación electrónica (e-CF) validada ante la DGII, con hitos medibles,
> responsables definidos y criterios de aceptación explícitos.
>
> **Duración objetivo:** 5 – 10 días hábiles según plan y complejidad del cliente.
> **Documentos vinculantes:** contrato de servicios (`contrato-servicios-estandar.md`) y
> anexos de políticas en `politicas/` (en particular Anexo 1.1, 1.2, 1.4 y 8).

## Roles y responsabilidades

| Rol | Responsable | Funciones clave |
|---|---|---|
| **Gerente de implementación** | VykCore | Dirige el proyecto, aprueba el go-live, escala incidentes (Anexo 1.2) |
| **Especialista de implementación** | VykCore | Ejecuta configuración, carga de datos, pruebas y capacitación |
| **Soporte técnico** | VykCore | Atiende incidentes según SLA del Anexo 1.4 durante hipercuidado |
| **Sponsor / contacto del cliente** | Cliente | Autoriza decisiones, entrega información y aprueba hitos |
| **Usuarios clave (key users)** | Cliente | Operación diaria: facturación, cobros, contabilidad/nómina según plan |

## Resumen de fases

| Fase | Nombre | Duración objetivo | Responsable principal |
|---|---|---|---|
| 0 | Contratación y preparación | 1 día | Gerente de implementación |
| 1 | Configuración fiscal (wizard de onboarding) | 1 – 2 días | Especialista de implementación |
| 2 | Datos maestros y usuarios | 1 – 3 días | Especialista + cliente |
| 3 | Pruebas en sandbox | 1 – 2 días | Especialista de implementación |
| 4 | Puesta en producción (go-live) | 1 día | Gerente de implementación |
| 5 | Capacitación y entrega | 1 – 2 días | Especialista de implementación |
| 6 | Hipercuidado y cierre | 10 días hábiles | Soporte técnico |

---

## FASE 0 — CONTRATACIÓN Y PREPARACIÓN

**Objetivo:** formalizar la relación y reunir los insumos mínimos para iniciar.

### Actividades y checklist

- [ ] Firma del contrato de servicios (`contrato-servicios-estandar.md`) con hoja de datos completa
- [ ] Confirmación del plan contratado y usuarios incluidos
- [ ] Creación de la cuenta principal (propietario/`owner`) y del entorno (tenant) del cliente
- [ ] Verificación del RNC del cliente con el algoritmo de dígito verificador
- [ ] Solicitud al cliente de: datos fiscales (Anexo a la hoja de datos), certificado PKCS#12 con contraseña, y evidencia de secuencias e-NCF autorizadas en DGII
- [ ] Agendar reunión de arranque (kick-off) con roles y calendario acordado

### Entregables
- Contrato firmado y hoja de datos completa
- Cuenta y entorno del cliente creados en sandbox
- Calendario de implementación acordado

### Criterio de aceptación
El cliente puede iniciar sesión en su entorno sandbox con 2FA habilitado y las partes
disponen de todos los insumos fiscales de la fase 1.

---

## FASE 1 — CONFIGURACIÓN FISCAL (WIZARD DE ONBOARDING)

**Objetivo:** completar el asistente de configuración inicial de la plataforma
(`onboarding_wizard`) para que el entorno quede fiscalmente habilitado en pruebas.

### Actividades y checklist (pasos del wizard)

- [ ] **Paso 1 — Tipo de contribuyente:** persona física / jurídica, sucursal y moneda
- [ ] **Paso 2 — Régimen fiscal:** régimen aplicable (RST, RIM, Régimen General, etc.)
- [ ] **Paso 3 — Datos fiscales:** razón social, RNC, dirección, teléfono, correo y logo
- [ ] **Paso 4 — Firma digital:** carga del certificado PKCS#12 y validación del mismo en la plataforma (Anexo 1.1 §4.6)
- [ ] **Paso 5 — Secuencias e-NCF:** registro de las secuencias autorizadas por la DGII y su rango
- [ ] **Paso 6 — Tasas e impuestos:** configuración de ITBIS (tasa general y tasas especiales) y retenciones según régimen
- [ ] **Paso 7 — Verificación:** confirmación visual de la configuración y cuadratura básica

> Si el cliente solo desea probar, puede omitir datos reales y operar con RNC de
> simulación en Modo Pruebas (botón del propio wizard); el go-live de la fase 4 queda
> condicionado a completar estos pasos con datos reales.

### Entregables
- Entorno fiscalmente configurado en sandbox
- Certificado de firma digital validado por la plataforma

### Criterio de aceptación
El wizard marca todos los pasos completados y una factura de prueba puede firmarse
digitalmente sin errores de certificado.

---

## FASE 2 — DATOS MAESTROS Y USUARIOS

**Objetivo:** cargar la información operativa mínima para facturar según el plan contratado.

### Actividades y checklist

- [ ] Importación o carga de **clientes** (RNC/cédula, razón social, teléfono, correo); validación de RNC por dígito verificador
- [ ] Importación o carga de **productos/servicios** (catálogo, precios, tasa ITBIS, costo según plan)
- [ ] Configuración de **listas de precios** (planes Pro/Enterprise)
- [ ] Configuración de **usuarios y roles** conforme al plan contratado, respetando la matriz de Segregación de Funciones (Anexo 1.1 §4.2):
  - [ ] Ningún usuario con permisos en conflicto (p. ej. emitir + anular comprobantes)
  - [ ] Contador con acceso de solo consulta si aplica
- [ ] Configuración de **sucursales/almacenes** (si aplica al plan)
- [ ] Configuración de **plantilla de factura** (logo, colores, pie de página)
- [ ] Configuración de **cuentas bancarias** del cliente para cobros (si aplica)

### Entregables
- Clientes, catálogo y usuarios cargados y revisados
- Roles y permisos sin conflictos SoD

### Criterio de aceptación
El key user del cliente confirma que los datos maestros cargados corresponden a su
realidad operativa y que cada usuario accede solo a los módulos de su rol.

---

## FASE 3 — PRUEBAS EN SANDBOX

**Objetivo:** validar los procesos críticos en ambiente de pruebas antes de producción.

### Actividades y checklist (casos de prueba mínimos)

- [ ] **E31 (Crédito Fiscal):** factura a cliente con RNC válido; cuadratura ITBIS (subtotal × tasa ≈ ITBIS) y MontoGravado por banda de tasa
- [ ] **E32 (Consumo):** factura a consumidor final con RNC genérico
- [ ] **E41 / E43 / E47:** compras y gastos conforme al plan contratado
- [ ] **Notas de crédito (E33) y débito (E34):** una de cada, sin exceder el comprobante original
- [ ] **Anulación de comprobante** ante DGII en pruebas (usuario con permiso de anulación)
- [ ] **Contingencia simulada:** activación del modo contingencia y sincronización posterior (Anexo 1.2)
- [ ] **Pagos y CxC:** registro de un pago y verificación del saldo del cliente
- [ ] **Reportes según plan:** 606/607 (Pro/Enterprise), exportación contable (Enterprise)
- [ ] **Backup exportable:** generación del respaldo JSON/ZIP del entorno (Anexo 8 §3)
- [ ] Revisión de la **bitácora de auditoría** (Anexo 7) con el cliente

### Entregables
- Evidencia de los casos de prueba ejecutados y aprobados
- Acta de pruebas firmada por el key user

### Criterio de aceptación
Todos los casos del plan aplican correctamente en sandbox y el cliente firma el acta de
pruebas autorizando el paso a producción.

---

## FASE 4 — PUESTA EN PRODUCCIÓN (GO-LIVE)

**Objetivo:** habilitar la emisión real ante la DGII de forma controlada.

### Actividades y checklist

- [ ] Verificación pre-go-live: wizard completado con datos reales, certificado vigente, secuencias disponibles
- [ ] Cambio del entorno de sandbox a **producción** por usuario con permiso de administración (Anexo 1.1 §4.5)
- [ ] **Primera emisión real** de un comprobante e-CF de prueba con cliente real (recomendado: E32 o factura de bajo monto)
- [ ] Verificación de **aceptación de la DGII** (TrackID, estado aceptado) y registro en la bitácora de secuencia
- [ ] Verificación del **cuadre** del comprobante: totales, ITBIS y secuencia e-NCF consumida
- [ ] Entrega del comprobante al cliente final (PDF con QR fiscal / envío por correo)

### Entregables
- Comprobante real aceptado por la DGII
- Evidencia (XML firmado, TrackID y respuesta de recepción)

### Criterio de aceptación
El primer comprobante en producción es aceptado por la DGII y queda trazable en la
bitácora. A partir de este hito el cliente puede facturar con normalidad.

---

## FASE 5 — CAPACITACIÓN Y ENTREGA

**Objetivo:** dejar al equipo del cliente operando de forma autónoma.

### Actividades y checklist (por rol)

- [ ] **Operador de facturación:** flujo completo de factura, nota de crédito, anulación, contingencia y consulta de estados DGII
- [ ] **Vendedor:** cotizaciones, CRM y conversión a factura (planes Pro/Enterprise)
- [ ] **Contador:** asientos automáticos, reportes 606/607/623, exportaciones y cierre fiscal (según plan)
- [ ] **RRHH:** nómina TSS/ISR, DGT-3/4/5/9, liquidaciones (solo Enterprise)
- [ ] **Administrador:** gestión de usuarios, permisos, secuencias e-NCF, respaldos y panel de auditoría
- [ ] Entrega de guías rápidas y referencia de canales de asistencia (Anexo 1.4)

### Entregables
- Sesiones de capacitación realizadas por rol
- Material de consulta entregado (FAQ, enlaces de ayuda)

### Criterio de aceptación
Cada key user ejecuta sin asistencia al menos un flujo completo de su rol en producción.

---

## FASE 6 — HIPERCUIDADO Y CIERRE

**Objetivo:** acompañamiento intensivo post-go-live y cierre formal del proyecto.

### Actividades y checklist

- [ ] **Semana 1:** revisión diaria con el cliente (facturas emitidas, rechazos DGII, dudas operativas)
- [ ] **Semana 2:** revisión interdiaria y verificación de cuadres (secuencias e-NCF, ITBIS, CxC)
- [ ] Atención de incidentes según SLA del **Anexo 1.4**; escalamiento inmediato de problemas de recepción DGII (Anexo 1.2)
- [ ] Verificación de que los respaldos se generan correctamente (Anexo 8)
- [ ] Encuesta de satisfacción y lecciones aprendidas
- [ ] Reunión de cierre: acta de cierre, transición a soporte regular y recordatorio de renovación (cláusula 13 del contrato)

### Entregables
- Acta de cierre firmada
- Informe de hipercuidado (incidentes, tiempos, estado fiscal)

### Criterio de aceptación
El cliente opera sin incidentes críticos durante la semana 2, los cuadres fiscales son
correctos y el acta de cierre queda firmada. El proyecto pasa a soporte regular.

---

## Escalamiento y bloqueos

| Situación | Acción |
|---|---|
| Certificado inválido o vencido | Bloqueo de go-live; el cliente renueva ante su emisor y repite fase 1 (paso 4) |
| Secuencias e-NCF agotadas o no autorizadas | El cliente solicita ante DGII; go-live queda condicionado |
| Rechazo de la DGII en producción | Escalamiento inmediato según Anexo 1.2; análisis de causa (datos vs. plataforma) y re-emisión |
| Indisponibilidad de la DGII | Modo contingencia automático; seguimiento de la ventana de 72 horas (Anexo 1.2) |
| Incumplimiento de pagos | Suspensión del servicio según cláusula 6 del contrato |
| El cliente no entrega información en 5 días hábiles | El proyecto se pausa y se reagenda con el gerente de implementación |

## Plantilla de acta de cierre

| Campo | Dato |
|---|---|
| Cliente | `[___]` |
| Plan | `[___]` |
| Fecha de contrato | `[___]` |
| Fecha de go-live | `[___]` |
| Primer comprobante aceptado por DGII | `[eNCF + TrackID]` |
| Fases completadas | 0 ☐ 1 ☐ 2 ☐ 3 ☐ 4 ☐ 5 ☐ 6 ☐ |
| Incidentes durante hipercuidado | `[cantidad y tipo]` |
| Aprobación del cliente | `[nombre, cargo, firma]` |
| Aprobación VykCore | `[nombre, cargo, firma]` |

---

## Control de versiones

| Versión | Fecha | Descripción del cambio | Elaborado por | Aprobado por |
|---|---|---|---|---|
| 1.0 | 2026-08-17 | Emisión inicial | Esmerlin Paniagua Martinez | Esmerlin Paniagua Martinez |
