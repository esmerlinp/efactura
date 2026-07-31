# ANEXO 8 — PROCEDIMIENTOS DE RESPALDO Y RECUPERACIÓN DE LA INFORMACIÓN

| Campo | Detalle |
|---|---|
| **Empresa Proveedora** | VykCore Automation S.R.L. |
| **Producto/Servicio** | VykOne ERP — Plataforma de Facturación Electrónica (e-CF) conforme DGII |
| **Código del documento** | POL-RES-008 |
| **Versión** | 1.0 |
| **Fecha de emisión** | 31 de julio de 2026 |
| **Clasificación** | Pública |
| **Responsable** | Esmerlin Paniagua Martinez — Gerente |

---

## 1. Objetivo

Definir los procedimientos de respaldo y recuperación de la información del servicio de
Facturación Electrónica para garantizar la disponibilidad, integridad y continuidad de los
datos de los contribuyentes.

## 2. Responsabilidades

- El **administrador de la plataforma** es responsable de ejecutar los respaldos conforme a
  los procedimientos descritos.
- El **Gerente** es responsable de supervisar la ejecución y de aprobar la recuperación.

## 3. Tipos de Respaldo Disponibles

### 3.1 Respaldo íntegro exportable (funcionalidad en la plataforma)

La plataforma dispone de un **módulo de exportación de respaldo** que permite generar
respaldo de los datos del contribuyente en los siguientes formatos:

- **JSON unificado** (`respaldo_{fecha}.json`) con todos los módulos.
- **ZIP con un CSV por módulo** (`respaldo_{fecha}.zip`).

**Módulos incluidos:** facturas, gastos, clientes, productos, categorías, sucursales,
almacenes, asientos contables, cuentas, listas de precios y centros de costo.

### 3.2 Exportación de datos de la empresa

Exportación de datos en CSV (clientes, productos, cotizaciones, gastos y documentos) en
archivo único o ZIP.

### 3.3 Exportaciones contables y de nómina

- Exportación de ventas, gastos y estados financieros.
- Exportación de datos de empleados para cumplimiento DSAR.

## 4. Procedimiento de Respaldo Recomendado (Infraestructura)

La información operacional se aloja en **Firebase Firestore** (proyecto de Google Cloud). El
proveedor mantiene el siguiente procedimiento de respaldo de infraestructura:

| Paso | Acción | Frecuencia |
|---|---|---|
| 1 | Ejecutar respaldo íntegro de Firestore mediante el servicio de exportación de Google Cloud (`gcloud firestore export` a Cloud Storage) | Diario |
| 2 | Verificar la integridad y completitud del respaldo (contadores por colección) | Diario |
| 3 | Conservar copias históricas con retención mínima de 30 días | Continuo |
| 4 | Ejecutar respaldo exportable desde el módulo de la plataforma (sección 3.1) | Semanal y antes de cambios mayores |
| 5 | Probar la restauración de un respaldo en ambiente de pruebas | Trimestral y tras cambios mayores |

## 5. Procedimiento de Recuperación

| Paso | Acción | Tiempo objetivo |
|---|---|---|
| 1 | Identificar el alcance de la pérdida y el momento del último respaldo íntegro | 1 hora |
| 2 | Restaurar los datos desde el respaldo íntegro en el entorno de producción | ≤ 4 horas |
| 3 | Repoblar la información pendiente entre el último respaldo y el incidente (re-emisión e-CF y sincronización de contingencia) | ≤ 8 horas |
| 4 | Verificar la integridad de los datos restaurados (cuadre de secuencias e-NCF, totales y cuadratura ITBIS) | 2 horas |
| 5 | Notificar el restablecimiento a los contribuyentes afectados | Inmediato |

## 6. Pruebas de Recuperación

- Se realizan **pruebas de restauración** en el ambiente de pruebas de forma periódica,
  verificando la integridad de los datos restaurados y los tiempos de recuperación.

## 7. Retención de Respaldo

- Respaldo íntegro diario: retención mínima de **30 días**.
- Respaldos mensuales históricos: retención mínima de **12 meses**.
- Los registros de auditoría (bitácora) se conservan conforme al Anexo 7.

---

## 8. Control de Versiones

| Versión | Fecha | Descripción del cambio | Elaborado por | Aprobado por |
|---|---|---|---|---|
| 1.0 | 2026-07-31 | Emisión inicial para requerimiento DGII | Esmerlin Paniagua Martinez | Esmerlin Paniagua Martinez |

## 9. Aprobación y Firma

| | Nombre | Cargo | Firma | Fecha |
|---|---|---|---|---|
| Elaborado por | Esmerlin Paniagua Martinez | Gerente | ____________________ | 2026-07-31 |
| Aprobado por | Esmerlin Paniagua Martinez | Gerente | ____________________ | 2026-07-31 |
