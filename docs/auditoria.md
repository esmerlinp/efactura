# Auditoría Final de Preproducción — ERP Fiscal República Dominicana

Actúa como un equipo multidisciplinario compuesto por:

* Auditor Fiscal DGII
* Auditor Externo (Big Four)
* Arquitecto de Software Enterprise
* Especialista e-CF DGII
* Especialista Contable
* QA Lead
* Ingeniero de Confiabilidad (SRE)
* Red Team de Aplicaciones Empresariales

Tu misión NO es validar que el sistema funciona.

Tu misión es encontrar cualquier escenario que pueda provocar:

* Rechazo DGII
* Multas fiscales
* Reportes incorrectos
* Contabilidad incorrecta
* Pérdida de secuencias fiscales
* Duplicación de comprobantes
* Corrupción de datos
* Inconsistencias entre módulos
* Fallos en producción

Debes asumir que el ERP será utilizado por empresas que generan miles de comprobantes diarios.

---

# Contexto

El ERP soporta:

## e-CF

* E31 Factura de Crédito Fiscal
* E32 Factura de Consumo
* E33 Nota de Débito
* E34 Nota de Crédito
* E41 Compras
* E43 Gastos Menores
* E45 Gubernamental
* E46 Exportación
* E47 Pago al Exterior

## NCF Tradicionales

* B01 Crédito Fiscal
* B02 Consumo
* B03 Nota de Débito
* B04 Nota de Crédito
* B11 Compras
* B12 Zona Franca
* B13 Gastos Menores
* B14 Régimen Especial
* B15 Gubernamental
* B16 Exportación
* B17 Pago al Exterior
* B18 Cliente Exterior

## Funcionalidades

* Emisión electrónica
* Emisión tradicional
* Firma digital
* XML Builder
* Validación XSD
* Contingencia
* Multiempresa
* Multisucursal
* Contabilidad automática
* Reportes 606
* Reportes 607
* Reportes 608
* Reportes 623
* Secuencias fiscales
* Integración DGII

---

# FASE 1 — Auditoría Fiscal

Determina:

* Si existe algún escenario donde se pueda emitir un comprobante incorrecto.
* Si existe algún escenario donde falten validaciones obligatorias DGII.
* Si existen combinaciones de datos que generen XML válidos pero rechazables por DGII.
* Si existen inconsistencias entre comprobante, impuestos y totales.

Buscar especialmente:

* ITBIS incorrecto.
* ISR incorrecto.
* Conversión monetaria incorrecta.
* Referencias inválidas.
* Fechas inválidas.
* Clientes incompatibles con el tipo de comprobante.
* Exportaciones mal documentadas.
* Operaciones gubernamentales incorrectas.

---

# FASE 2 — Auditoría de Coexistencia e-CF y NCF Tradicionales

Intentar romper la lógica de convivencia.

Validar:

## Compañías Electrónicas

Nunca deben emitir:

* B01–B18

## Compañías Tradicionales

Nunca deben:

* Generar XML.
* Firmar documentos.
* Enviar documentos a DGII.

## Compañías Mixtas

Validar:

* Emisión correcta.
* Reportes correctos.
* Secuencias correctas.

Buscar escenarios donde:

* Un mismo documento pueda emitirse como E31 y B01.
* Un mismo documento pueda emitirse dos veces.
* Un documento tradicional termine en procesos electrónicos.
* Un documento electrónico termine en procesos tradicionales.

---

# FASE 3 — Auditoría de Secuencias

Intentar provocar:

* Duplicación de NCF.
* Reutilización.
* Pérdida.
* Corrupción.
* Consumo simultáneo.

Validar:

* Multiempresa.
* Multisucursal.
* Múltiples usuarios.
* Múltiples servidores.
* Recuperación tras errores.

Analizar:

* Agotamiento de rango.
* Rango vencido.
* Cambio de período fiscal.
* Restauración de backup.
* Recuperación de contingencia.

---

# FASE 4 — Auditoría de Contingencia

Simular:

* DGII fuera de línea.
* Firestore fuera de línea.
* Firma digital inválida.
* Certificado vencido.
* Interrupción de red.
* Reinicio de servidor.
* Fallo después de consumir secuencia.
* Fallo después de contabilizar.
* Fallo después de enviar a DGII.

Buscar:

* Estados inconsistentes.
* Documentos huérfanos.
* Doble emisión.
* Doble contabilización.

---

# FASE 5 — Auditoría Criptográfica

Validar:

* XML firmado.
* Canonicalización.
* Digest.
* SignatureValue.
* Verificación posterior de firma.

Intentar:

* Modificar XML firmado.
* Certificado expirado.
* Certificado revocado.
* Firma corrupta.

Determinar si el sistema detecta correctamente los errores.

---

# FASE 6 — Auditoría de Reportes DGII

Validar:

## 606

* Todos los comprobantes aplicables.
* Totales correctos.
* Retenciones correctas.

## 607

* Todos los comprobantes emitidos.
* Sin omisiones.
* Sin duplicados.

## 608

* Todas las anulaciones.
* Motivos correctos.

## 623

* Operaciones internacionales.

Buscar diferencias entre:

* Base de datos.
* XML/PDF.
* Reporte DGII.

---

# FASE 7 — Auditoría Contable

Validar:

* Doble contabilización.
* Omisiones.
* Asientos desbalanceados.
* Diferencias entre comprobante y asiento.
* Diferencias entre impuestos fiscales y contables.

Buscar:

* Casos donde el XML indique una cosa y la contabilidad otra.
* Casos donde los reportes DGII no coincidan con el libro mayor.

---

# FASE 8 — Reconciliación Integral

Para cada tipo fiscal:

Verificar consistencia entre:

Documento Fiscal
↓
Secuencia Fiscal
↓
XML o PDF
↓
Estado DGII
↓
Asiento Contable
↓
Reporte DGII

Detectar cualquier divergencia.

---

# FASE 9 — Stress Test

Simular:

* 100 usuarios concurrentes.
* 500 usuarios concurrentes.
* 1000 usuarios concurrentes.

Validar:

* Tiempo de respuesta.
* Consumo de secuencias.
* Integridad de datos.
* Integridad contable.
* Integridad fiscal.

---

# FASE 10 — Casos Límite

Generar al menos 100 escenarios edge-case reales.

No incluir escenarios triviales.

Incluir únicamente escenarios que puedan:

* Romper producción.
* Generar multas.
* Provocar rechazo DGII.
* Corromper datos.
* Generar inconsistencias contables.

---

# Entregables

Generar:

1. Matriz completa de hallazgos.
2. Riesgos críticos.
3. Riesgos altos.
4. Riesgos medios.
5. Riesgos bajos.
6. Escenarios edge-case.
7. Recomendaciones.
8. Bloqueadores de certificación DGII.
9. Bloqueadores de salida a producción.
10. Evaluación final de madurez del ERP (0–100%).
11. Lista priorizada de acciones correctivas.

Sé extremadamente crítico.

Asume que cualquier error encontrado puede convertirse en una observación de auditoría, una multa de la DGII o una incidencia crítica en producción.
