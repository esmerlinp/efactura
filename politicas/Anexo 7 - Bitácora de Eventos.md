# ANEXO 7 — BITÁCORA DE EVENTOS (LOGS)

| Campo | Detalle |
|---|---|
| **Empresa Proveedora** | VykCore Automation S.R.L. |
| **Producto/Servicio** | VykOne ERP — Plataforma de Facturación Electrónica (e-CF) conforme DGII |
| **Código del documento** | POL-BIT-007 |
| **Versión** | 1.0 |
| **Fecha de emisión** | 31 de julio de 2026 |
| **Clasificación** | Pública |
| **Responsable** | Esmerlin Paniagua Martinez — Gerente |

---

## 1. Objetivo

Documentar la existencia de una bitácora de eventos (logs) que permita la **trazabilidad y el
control de cambios** de la plataforma de Facturación Electrónica, conforme a los requisitos
técnicos del proveedor de servicios de Facturación Electrónica.

## 2. Bitácora Central de Auditoría

La plataforma dispone de un **servicio central de auditoría** que registra todas las
acciones relevantes sobre los datos.

### 2.1 Acciones registradas (canónicas)

- `CREATE` — creación de registros (facturas, clientes, gastos, etc.).
- `UPDATE` — modificación de registros.
- `DELETE` — eliminación de registros.
- `VIEW` — consulta de registros sensibles.
- `LOGIN` / `LOGOUT` — inicio y cierre de sesión.
- `EXPORT` — exportaciones de datos.

Adicionalmente se registran las acciones específicas de emisión ante la DGII (aceptación o
rechazo, con TrackID y modo de emisión), envío de correos y las operaciones de secuencias
fiscales.

### 2.2 Información capturada por cada evento

| Campo | Descripción |
|---|---|
| Acción | Tipo de operación (CREATE/UPDATE/DELETE/...) |
| Módulo | Módulo afectado (Facturas, Clientes, Contabilidad, POS, etc.) |
| Entidad | Identificador y descripción de la entidad afectada |
| Usuario | Nombre, UID y correo del usuario que ejecutó la acción |
| Antes/Después | Estado del dato antes y después del cambio (datos sensibles omitidos) |
| IP y agente de usuario | Origen de la solicitud |
| Marca de tiempo | Fecha y hora exacta del evento |
| Ambiente | Indicador de sandbox o producción |

### 2.3 Seguridad de la bitácora

- Los datos sensibles (contenido de certificados, contraseñas, tokens, logos) se omiten de
  los registros y se sustituyen por `[OMITIDO POR SEGURIDAD]`.
- En caso de indisponibilidad del almacenamiento principal, los eventos se registran en un
  archivo de respaldo local de seguridad.

## 3. Bitácoras Especializadas

| Bitácora | Propósito | Ubicación |
|---|---|---|
| **Secuencia fiscal (e-NCF)** | Trazabilidad de cada secuencia consumida: comprobante, consecutivo, estado (generado → aceptado/fallido), XML enviado, respuesta DGII, duración | Registro de secuencias fiscales (consultable por API) |
| **Auditoría contable** | Registro de creación, modificación y anulación de asientos con diferencia antes/después | Registro de auditoría contable |
| **Auditoría de nómina (RRHH)** | Acciones sobre datos de empleados y nómina con cambios y comentarios | Registro de auditoría de RRHH |
| **Auditoría de caja POS** | Arqueos y cierres de caja con responsable y resultado | Registro de auditoría de caja |
| **Ejecución de trabajos programados** | Registro de cada corrida de los trabajos automáticos (depreciación, facturación recurrente, etc.) | Bitácora de trabajos programados |

## 4. Acceso y Control de Cambios

- El **panel de auditoría web** permite filtrar, revisar el detalle (antes/después) y
  **exportar en CSV** los registros; la exportación está restringida al propietario.
- Los cambios de configuración y permisos de usuarios también se registran en la bitácora.
- La **matriz de segregación de funciones (SoD)** registra las acciones de usuarios con
  roles en conflicto.

## 5. Conservación

- Los registros de auditoría se conservan en el almacenamiento de la plataforma sin
  eliminación automática, de forma que se garantice la trazabilidad histórica requerida por
  la normativa.

---

## 6. Control de Versiones

| Versión | Fecha | Descripción del cambio | Elaborado por | Aprobado por |
|---|---|---|---|---|
| 1.0 | 2026-07-31 | Emisión inicial para requerimiento DGII | Esmerlin Paniagua Martinez | Esmerlin Paniagua Martinez |

## 7. Aprobación y Firma

| | Nombre | Cargo | Firma | Fecha |
|---|---|---|---|---|
| Elaborado por | Esmerlin Paniagua Martinez | Gerente | ____________________ | 2026-07-31 |
| Aprobado por | Esmerlin Paniagua Martinez | Gerente | ____________________ | 2026-07-31 |
