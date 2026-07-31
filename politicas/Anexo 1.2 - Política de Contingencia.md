# ANEXO 1.2 — POLÍTICA DE CONTINGENCIA

| Campo | Detalle |
|---|---|
| **Empresa Proveedora** | VykCore Automation S.R.L. |
| **Producto/Servicio** | VykOne ERP — Plataforma de Facturación Electrónica (e-CF) conforme DGII |
| **Código del documento** | POL-CONT-002 |
| **Versión** | 1.0 |
| **Fecha de emisión** | 31 de julio de 2026 |
| **Clasificación** | Pública |
| **Responsable** | Esmerlin Paniagua Martinez — Gerente |

---

## 1. Objetivo

Definir los procedimientos y controles que garantizan la continuidad operativa del servicio de
Facturación Electrónica (e-CF) ante eventos disruptivos, en particular la indisponibilidad del
servicio de recepción de la Dirección General de Impuestos Internos (DGII), de la plataforma o
de la infraestructura de soporte.

## 2. Escenarios de Contingencia Cubiertos

| # | Evento disruptivo | Respuesta |
|---|---|---|
| 1 | Servicio DGII no disponible (caída o sobrecarga) | Modo contingencia local con sincronización posterior |
| 2 | Fallo de red entre la plataforma y DGII | Reintentos con retroceso exponencial |
| 3 | Caída de la plataforma web | Redundancia en la infraestructura Cloud; verificación de disponibilidad |
| 4 | Error en la firma digital / certificado | Validación preventiva del certificado PKCS#12; alerta al administrador |

## 3. Modo de Contingencia para la Emisión e-CF

### 3.1 Activación

Cuando la recepción de la DGII no responde dentro de los parámetros establecidos, la
plataforma activa el **modo contingencia**: el comprobante se genera y firma
localmente, se registra con la marca de contingencia (fecha y hora), quedando pendiente de
sincronización con la DGII. Esto aplica en:

- Emisión web.
- Emisión POS.
- Facturación recurrente de contratos.
- Re-emisión.

### 3.2 Ventana Legal y Alertas

- **Ventana legal DGII**: 72 horas para transmitir los comprobantes en contingencia.
- **Alerta temprana**: a partir de las **48 horas** se notifica automáticamente al
  administrador y al equipo.
- El panel POS de contingencia muestra horas transcurridas/restantes y marca estado crítico
  a menos de 12 horas.

### 3.3 Sincronización Posterior (Recuperación)

- **Automática**: reintentos con retroceso exponencial de 1 min → 5 min → 15 min → 1 h → 6 h
  → 24 h, hasta **20 intentos**; al agotarse el comprobante se marca como fallido en
  sincronización.
- **Manual**: el administrador puede ejecutar la sincronización desde el panel
  administrativo de la plataforma (individual o masiva) o mediante el disparador de
  trabajos.
- Al sincronizar, el comprobante se actualiza como **sincronizado con la DGII** (aceptado,
  con emisión vía API), y se actualiza la bitácora de secuencia con el TrackID de la DGII.

## 4. Controles de Continuidad Operativa

- **Monitoreo de disponibilidad** de la plataforma en la nube con redundancia de instancias
  (configuración multi-proceso).
- **Bitácora de ejecución de trabajos**: cada proceso programado registra su resultado y
  queda disponible para consulta.
- **Respaldo y recuperación**: ver documento **Anexo 8 — Procedimientos de Respaldo y
  Recuperación de la Información**.

## 5. Roles y Responsabilidades

| Rol | Responsabilidad en contingencia |
|---|---|
| Gerente | Supervisión de la activación, escalamiento y comunicación |
| Administrador de la plataforma | Ejecución de la sincronización de comprobantes en contingencia |
| Soporte técnico | Atención a los contribuyentes afectados (Anexo 1.4) |

## 6. Pruebas de Contingencia

Se realizan pruebas periódicas de los procedimientos de contingencia en el ambiente de
pruebas, verificando: activación del modo contingencia, reintentos, sincronización posterior y
cuadre con la DGII.

---

## 7. Control de Versiones

| Versión | Fecha | Descripción del cambio | Elaborado por | Aprobado por |
|---|---|---|---|---|
| 1.0 | 2026-07-31 | Emisión inicial para requerimiento DGII | Esmerlin Paniagua Martinez | Esmerlin Paniagua Martinez |

## 8. Aprobación y Firma

| | Nombre | Cargo | Firma | Fecha |
|---|---|---|---|---|
| Elaborado por | Esmerlin Paniagua Martinez | Gerente | ____________________ | 2026-07-31 |
| Aprobado por | Esmerlin Paniagua Martinez | Gerente | ____________________ | 2026-07-31 |
