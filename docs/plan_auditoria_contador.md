# Plan de Auditoría: Sistema de Facturación Electrónica e-FacturaWeb

**Dirigido a:** Contador Público Autorizado (CPA) dominicano
**Objetivo:** Verificar que el sistema cumple con la Ley 32-23 de Facturación Electrónica de la DGII, que los datos contables y fiscales son correctos, y que los procesos operativos no presentan riesgos de incumplimiento.

---

## 1. Alcance de la Auditoría

El contador debe probar los siguientes módulos y validar su correcto funcionamiento fiscal, contable y operativo:

### Módulos a auditar
1. **Facturación Electrónica (e-CF)** — Emisión de facturas E31, E32 y notas de crédito/débito E33, E34
2. **Gestión de Gastos y Compras** — Registro de gastos con proveedores, comprobantes E41, E43, E45, E47
3. **Reportes Fiscales DGII** — Reportes 606 (compras), 607 (ventas), 608 (retenciones), 623 (gastos menores)
4. **Contabilidad** — Plan de cuentas, asientos contables, balance general, estado de resultados
5. **Gestión de Clientes y Proveedores** — Registro de RNC, validación fiscal
6. **Configuración de la Empresa** — Régimen fiscal, secuencias NCF, firma digital, datos DGII
7. **Portal de Cliente** — Acceso de clientes a sus facturas y saldos
8. **Auditoría Interna del Sistema** — Log de acciones y trazabilidad

---

## 2. Pruebas a Realizar

### 2.1 Facturación Electrónica

**Objetivo:** Validar que las facturas se emiten correctamente según el régimen fiscal configurado y que los cálculos de ITBIS, retenciones y totales son exactos.

| # | Prueba | Resultado esperado |
|---|--------|--------------------|
| 1 | Emitir factura E31 (Crédito Fiscal) con RNC de cliente válido de 9 dígitos | La factura se emite, el XML se genera, se firma digitalmente y se envía a DGII con TrackID de respuesta |
| 2 | Emitir factura E32 (Consumo) para consumidor final | La factura se emite sin exigir RNC, permite RNC genérico 000000000 |
| 3 | Emitir factura con productos grabados al 18% ITBIS | El cálculo de ITBIS (subtotal × 0.18) es correcto, el total neto refleja subtotal + ITBIS |
| 4 | Emitir factura con productos al 16% ITBIS (tasa reducida) | El ITBIS se calcula al 16%, el XML especifica código de impuesto correcto |
| 5 | Emitir factura con productos exentos de ITBIS | ITBIS = 0, el XML refleja la exención correctamente |
| 6 | Emitir factura con retención de ISR (2% bienes/servicios) | El monto retenido se descuenta del neto a pagar y aparece en el XML |
| 7 | Emitir factura con retención de ITBIS (30% bienes corporativos) | Igual que arriba, la retención se registra correctamente |
| 8 | Emitir factura con descuento porcentual por línea | El subtotal por línea descuenta el % indicado, el ITBIS se recalcula sobre el precio con descuento |
| 9 | Emitir factura con descuento global | El descuento global se aplica después de sumar subtotales e ITBIS (según norma DGII) |
| 10 | Emitir factura en modo sandbox | El documento lleva marca de sandbox, no consume secuencia real |
| 11 | Emitir factura en modo producción | La factura consume secuencia real y se envía a endpoint productivo DGII |
| 12 | Anular factura emitida | El proceso de anulación genera un evento de cancelación y el documento queda en estado "Anulada" |
| 13 | Intentar emitir E31 sin RNC o con RNC inválido | El sistema rechaza la emisión con mensaje de error claro |
| 14 | Verificar el PDF generado | Contiene logo (si configurado), QR fiscal, datos del emisor/receptor, detalle de ítems, totales, NCF/e-CF |

### 2.2 Notas de Crédito (E34) y Notas de Débito (E33)

| # | Prueba | Resultado esperado |
|---|--------|--------------------|
| 15 | Crear nota de crédito E34 referenciando una factura E31 emitida | La NC se asocia a la factura origen, los totales no exceden la factura original, se envía a DGII |
| 16 | Crear nota de débito E33 referenciando una factura E31 emitida | La ND incrementa el saldo, se envía a DGII |
| 17 | Validar códigos de modificación (devolución, corrección de texto, descuento, descuento por volumen, otros) | Cada código genera la nota con el propósito correcto en el XML |
| 18 | Intentar crear NC por monto mayor a la factura original | El sistema rechaza la operación |
| 19 | Intentar crear NC sobre factura anulada o borrador | El sistema rechaza la operación |

### 2.3 Gestión de Gastos y Compras

| # | Prueba | Resultado esperado |
|---|--------|--------------------|
| 20 | Registrar un gasto con proveedor formal (RNC) y comprobante E41 | El gasto queda registrado con NCF, RNC del proveedor, ITBIS discriminado, y permite marcarlo como deducible |
| 21 | Registrar un gasto menor (E43) con proveedor informal | El gasto se registra sin RNC, con tipo de proveedor "informal" |
| 22 | Registrar un gasto del exterior (E47) | El gasto se registra con proveedor extranjero, sin ITBIS |
| 23 | Validar cálculo de retención ISR en gastos | Si el proveedor tiene marcada retención ISR, el sistema la calcula automáticamente (2% por defecto) |
| 24 | Validar cálculo de retención ITBIS en gastos | Si el proveedor tiene marcada retención ITBIS, se aplica el 30% |
| 25 | Verificar que los gastos se puedan filtrar por período (año/mes) | Los filtros funcionan correctamente en el módulo de gastos |

### 2.4 Reportes Fiscales DGII

| # | Prueba | Resultado esperado |
|---|--------|--------------------|
| 26 | Generar Reporte 606 (Compras) para un período | El reporte lista todas las compras del período con RNC, NCF, monto, ITBIS, tipo de gasto DGII. Los totales coinciden con el módulo de gastos. |
| 27 | Exportar 606 en formato DGII | Las columnas coinciden con el formato oficial: RNC comprador, período, RNC proveedor, tipo ID, nombre, tipo comprobante (01-05), NCF, monto facturado, ITBIS facturado, fecha, tipo gasto (01-07) |
| 28 | Generar Reporte 607 (Ventas) para un período | El reporte lista todas las ventas con RNC cliente, NCF/e-CF, monto, ITBIS, retenciones. Los totales coinciden con el módulo de facturación |
| 29 | Exportar 607 en formato DGII | Columnas oficiales: RNC emisor, período, RNC cliente, tipo ID, nombre, tipo comprobante (01-04), NCF, monto, ITBIS, retenciones, fecha, tipo ingreso (01-06) |
| 30 | Generar Reporte 608 (Retenciones) para un período | Lista todas las retenciones ISR e ITBIS practicadas, agrupadas por cliente retenido. Totales discriminados correctos |
| 31 | Generar Reporte 623 (Gastos Menores) | Lista gastos informales, E43, y compras < RD$50,000 con formato DGII correcto |
| 32 | Validar que los totales de reportes coinciden con los totales de los módulos origen (facturación, gastos) | Consistencia: total 607 = total facturación, total 606 = total gastos |

### 2.5 Contabilidad

| # | Prueba | Resultado esperado |
|---|--------|--------------------|
| 33 | Revisar el plan de cuentas (catálogo) | Las cuentas están organizadas por grupos (activos, pasivos, patrimonio, ingresos, costos, gastos) con códigos y naturaleza correcta (deudora/acreedora) |
| 34 | Crear un asiento contable manual | El asiento se registra con fecha, cuenta contable, débito/crédito, y el balance del asiento es 0 |
| 35 | Verificar que las facturas de venta generan asientos contables automáticos | Cada factura emitida registra: débito a CxC o Banco, crédito a Ventas e ITBIS por pagar |
| 36 | Verificar que los gastos generan asientos contables automáticos | Cada gasto registra: débito a Gasto e ITBIS acreditable, crédito a CxP o Banco |
| 37 | Generar balance general | Activos = Pasivos + Patrimonio |
| 38 | Generar estado de resultados | Ingresos - Costos - Gastos = Utilidad neta. Las cifras coinciden con facturación y gastos |
| 39 | Generar balanza de comprobación | Suma de débitos = Suma de créditos |

### 2.6 Clientes y Proveedores

| # | Prueba | Resultado esperado |
|---|--------|--------------------|
| 40 | Crear un cliente con RNC válido | El sistema valida el dígito verificador del RNC (algoritmo DGII) |
| 41 | Crear un cliente con cédula (11 dígitos) | El sistema valida el dígito verificador de la cédula |
| 42 | Verificar que un proveedor se configura con tipo de gasto DGII | El tipo de gasto (01-07) queda asignado al proveedor para el 606 |
| 43 | Verificar que un proveedor se configura con retenciones | Las banderas de retención ISR e ITBIS se aplican automáticamente en los gastos asociados |
| 44 | Activar/desactivar proveedor | El estado "Inactivo" oculta al proveedor de nuevas transacciones |

### 2.7 Configuración de Empresa

| # | Prueba | Resultado esperado |
|---|--------|--------------------|
| 45 | Verificar que el perfil de la empresa tiene RNC, razón social, régimen fiscal, y actividad económica configurados | Estos datos aparecen en el XML del e-CF |
| 46 | Verificar que el régimen fiscal limita los tipos de e-CF disponibles | Ordinario: todos los ECF. RST: E32, E33, E34, E41, E43. Exento: solo E32 sin ITBIS |
| 47 | Verificar secuencias fiscales (NCF) | Las secuencias están aprobadas por DGII, con rango de números y estado Activa/Inactiva |
| 48 | Verificar que el certificado de firma digital está cargado | Sin certificado, la emisión en producción debe fallar con error claro |
| 49 | Verificar facturación recurrente (contratos) | Un contrato activo genera facturas automáticamente en la fecha programada |

### 2.8 Auditoría Interna del Sistema

| # | Prueba | Resultado esperado |
|---|--------|--------------------|
| 50 | Acceder al log de auditoría | Todos los eventos CREATE, UPDATE, DELETE, LOGIN, LOGOUT, EXPORT están registrados con timestamp, usuario, módulo, entidad |
| 51 | Ver detalle de un evento (before/after) | Se muestran los valores antes y después del cambio |
| 52 | Filtrar por módulo, acción, usuario, fecha | Los filtros funcionan y los resultados son precisos |
| 53 | Exportar auditoría a CSV | El CSV incluye todas las columnas requeridas con codificación UTF-8 BOM |

### 2.9 Portal de Cliente

| # | Prueba | Resultado esperado |
|---|--------|--------------------|
| 54 | Acceder al portal mediante enlace con token | El cliente ve sus facturas, contratos y saldos CxC sin necesidad de login de usuario del sistema |
| 55 | Verificar que el portal muestra facturas con estado correcto (Emitida, Vencida, Cobrada) | El estado se evalúa correctamente según fecha de vencimiento |

---

## 3. Resultados y Entregables Esperados

El contador debe producir al finalizar la auditoría:

1. **Matriz de hallazgos**: Para cada prueba fallida, describir el problema encontrado, su impacto fiscal/contable, y una recomendación de corrección
2. **Certificación de cumplimiento fiscal**: Documento firmado indicando si el sistema cumple o no con la Ley 32-23 y las normas DGII para emisión de e-CF
3. **Informe de diferencias**: Cualquier discrepancia entre los totales de facturación vs reportes, o entre ingresos declarables vs lo reflejado en contabilidad
4. **Recomendaciones de mejora**: Funcionalidades faltantes o configuraciones necesarias para optimizar el cumplimiento fiscal

---

## 4. Guía Rápida de Flujos para el Contador

### Flujo 1: Emitir una Factura de Venta
1. Iniciar sesión → verificar que estás en el entorno correcto (Sandbox para pruebas)
2. Ir a **Facturación → Nueva Factura**
3. Seleccionar tipo de e-CF (E31 con RNC / E32 consumidor final)
4. Seleccionar o crear cliente (validar RNC automáticamente)
5. Agregar ítems del catálogo (nombre, cantidad, precio, tasa ITBIS)
6. Revisar panel "Más ajustes": secuencia NCF, vendedor, almacén, fecha de vencimiento
7. Opcional: configurar retenciones (ISR, ITBIS) y descuentos
8. **Emitir** → El sistema genera XML, firma digitalmente, comprime y envía a DGII
9. Verificar TrackID de respuesta de DGII
10. El PDF se genera automáticamente con QR fiscal

### Flujo 2: Registrar un Gasto/Compra
1. Ir a **Gastos → Nuevo Gasto**
2. Seleccionar proveedor (debe existir en el directorio)
3. Ingresar NCF/e-CF del comprobante del proveedor, fecha, monto, ITBIS
4. Marcar si es deducible y el tipo de gasto DGII (01 al 07)
5. Si aplica, verificar que el sistema calcula retenciones automáticamente
6. Guardar → el gasto queda disponible para el 606

### Flujo 3: Generar Reportes DGII
1. Ir a **Reportes → 606 (Compras) / 607 (Ventas) / 608 (Retenciones) / 623 (Gastos Menores)**
2. Seleccionar año y mes
3. Usar filtros por proveedor, cliente, tipo de comprobante, tipo de ingreso/gasto
4. Revisar que los totales mostrados coinciden con los módulos origen
5. Exportar en formato "DGII" (columnas oficiales) o "simple" (columnas resumidas)
6. El CSV se descarga con codificación UTF-8 BOM para compatibilidad con Excel

### Flujo 4: Revisar Contabilidad
1. Ir a **Contabilidad → Panel**
2. Ver resumen: total activos, pasivos, patrimonio, resultado neto, cantidad de asientos
3. Ir a **Catálogo de Cuentas** para revisar la estructura contable
4. Ir a **Asientos Contables** para ver el libro diario
5. Verificar que las facturas y gastos generaron asientos automáticos
6. Generar **Balance General** y **Estado de Resultados** para el período

### Flujo 5: Crear una Nota de Crédito
1. Ir a **Notas Fiscales → Nueva Nota**
2. Seleccionar tipo E34 (Crédito) o E33 (Débito)
3. Seleccionar factura de referencia (debe estar emitida, no anulada, no en contingencia)
4. Elegir código de modificación (devolución, corrección, descuento...)
5. Ajustar ítems y precios — el total de la NC no puede exceder el total de la factura original
6. Emitir → se envía a DGII vinculada a la factura original

### Flujo 6: Portal del Cliente
1. Desde el módulo de clientes, generar enlace de portal
2. El cliente recibe un enlace con token de acceso
3. El cliente verifica su identidad con RNC/Cédula + PIN de 6 dígitos
4. Accede a: lista de facturas, contratos, saldos pendientes (CxC)

---

## 5. Puntos Críticos de Atención

Estos son los aspectos que el contador debe revisar con especial detenimiento:

1. **Cálculo de ITBIS**: Verificar con calculadora que el ITBIS facturado = subtotal × tasa (0.18 o 0.16). El redondeo debe ser a 2 decimales según regla DGII (el tercer decimal redondea al segundo).
2. **Validación de RNC**: El sistema debe validar el dígito verificador antes de emitir un E31. Probar con un RNC inválido a propósito.
3. **Secuencias NCF**: Verificar que las secuencias no se solapan, que el consecutivo avanza correctamente, y que no hay huecos sin justificación.
4. **Retenciones**: Las retenciones de ISR (2%) e ITBIS (30%) deben reflejarse tanto en el XML como en el reporte 608.
5. **Cruce de información**: El total del 607 debe coincidir con la suma de facturas emitidas en el período. El total del 606 debe coincidir con los gastos registrados.
6. **Contabilidad**: Verificar que la ecuación contable fundamental se cumple (Activo = Pasivo + Patrimonio) en el balance general.
7. **Notas de crédito**: Verificar que modifican correctamente los saldos de CxC y que se reflejan en el 607 como documentos que reducen los ingresos.
8. **Entorno Sandbox vs Producción**: Asegurarse de que el contador entiende que las pruebas en sandbox no tienen validez fiscal. La auditoría final debe incluir pruebas en producción con al menos un documento real.
9. **Firma digital**: El certificado debe estar vigente, emitido por una entidad certificadora acreditada ante la DGII.
10. **Homologación DGII**: Cada e-CF debe recibir un TrackID de la DGII como comprobante de recepción exitosa.

---

## 6. Criterios de Aceptación

El sistema se considera **APROBADO** si:
- El 100% de las pruebas de facturación (E31, E32) pasan correctamente (cálculos fiscales, emisión DGII, PDF)
- El 100% de las pruebas de notas de crédito/débito pasan (referencia, límites, códigos de modificación)
- Los totales de los reportes 606, 607, 608 y 623 coinciden con los datos fuente
- La ecuación contable fundamental se cumple en el balance general
- El log de auditoría registra consistentemente todas las operaciones
- Las validaciones de RNC y límites de NC funcionan correctamente

El sistema se considera **APROBADO CON OBSERVACIONES** si:
- Falla alguna prueba no crítica que no afecta el cumplimiento fiscal (ej. formato de exportación CSV, etiqueta de un campo)
- Se detectan oportunidades de mejora que no invalidan la emisión fiscal

El sistema se considera **RECHAZADO** si:
- Alguna factura emitida tiene cálculos fiscales incorrectos
- El envío a DGII falla o no genera TrackID
- Los reportes DGII no reflejan la realidad fiscal
- La firma digital no se aplica correctamente
- El balance contable no cuadra

---

## 7. Instrucciones para el Contador

1. **Antes de iniciar**: Solicitar acceso al sistema con rol de administrador. Configurar el perfil de empresa con datos reales (RNC, razón social, régimen fiscal).
2. **Usar sandbox para la mayoría de pruebas**: Realizar las pruebas en el entorno sandbox primero. Solo pasar a producción para 1-2 pruebas de verificación final.
3. **Documentar cada prueba**: Tomar capturas de pantalla de cada paso. Anotar TrackID de cada envío DGII.
4. **Usar una hoja de cálculo paralela**: Recalcular manualmente ITBIS, subtotales y totales para comparar contra lo que arroja el sistema.
5. **Probar casos borde**: RNC inválidos, montos cero, cantidades negativas, facturas sin ítems, NC que excedan la factura original.
6. **Revisar la integridad de los datos**: Verificar que al eliminar o modificar un registro, el sistema mantiene la integridad referencial (no deja huérfanos).

---

> **Nota para el equipo de desarrollo:** Preparar datos de prueba antes de la sesión con el contador: empresa configurada, catálogo de productos, clientes con RNC válidos, proveedores, secuencias NCF activas, y al menos 5 facturas emitidas en sandbox.
