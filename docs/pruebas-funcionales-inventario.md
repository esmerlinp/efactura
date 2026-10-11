# VykOne ERP — Documento Formal de Flujo de Trabajo y Pruebas Funcionales del Módulo de Inventario (Guía de Usuario Final y Manual QA)

**Documento ID:** DOC-QA-INV-2026-V2  
**Versión del Sistema:** VykOne ERP v2.4 (Multi-Tenant, Firestore, Cumplimiento Fiscal Dominicano DGII)  
**Módulo Evaluado:** Productos e Inventario (Almacenes, Kardex Valorizado FIFO, Recepciones, Transferencias, Conteos Físicos y Contabilidad Integrada)  
**Fecha de Actualización:** 11 de Octubre de 2026  
**Autor:** Antigravity AI — Quality Assurance & Functional Testing  
**Enfoque del Documento:** **100% Interfaz de Usuario (UI)** — Navegación visual paso a paso, menús, botones, formularios y mensajes en pantalla sin rutas técnicas de URL.

---

## 1. Objetivo y Alcance

### 1.1 Objetivo General
Proveer una **guía práctica, formal y visual de pruebas funcionales manuales** para que cualquier usuario final, analista de calidad (QA), encargado de almacén o auditor contable pueda validar de punta a punta el funcionamiento del módulo de Inventario en **VykOne ERP**. 

Todas las instrucciones de este documento están redactadas exclusivamente desde la perspectiva de la **interfaz gráfica de usuario (UI)**: navegación a través del menú lateral (sidebar), menús desplegables, pestañas, botones de acción, ventanas modales y formularios visuales, sin requerir conocimientos técnicos ni el uso de URLs directas en el navegador.

### 1.2 Alcance del Módulo
El alcance comprende el ciclo de vida completo de los artículos en la empresa:
- Registro y mantenimiento de productos físicos (`Bien`), servicios y categorías en el catálogo comercial.
- Configuración y control de almacenes múltiples y ubicaciones de estantería/pasillo.
- Entradas de mercancía (recepción total y parcial de órdenes de compra aprobadas y ajustes de entrada manual).
- Salidas de inventario (despacho automático en facturas electrónicas e-CF, consumo interno y mermas por daño o pérdida).
- Devoluciones y notas de crédito de clientes (e-CF E34) con reingreso físico al almacén.
- Traslados y transferencias entre almacenes con circuito de solicitud y aprobación.
- Auditorías físicas de existencias mediante sesiones de conteo con captura de snapshot y aplicación de ajustes automáticos por diferencias.
- Control de costeo determinista bajo método **FIFO / PEPS continuo** y consulta del **Kardex Valorizado** con exportación a Excel y PDF.
- Monitoreo de alertas visuales de stock bajo, puntos de reorden sugeridos y vencimiento de lotes.
- Integración contable automática en tiempo real con el Libro Diario / Mayor General.

---

## 2. Mapa de Navegación en la Interfaz de Usuario (UI)

La navegación dentro de VykOne ERP se realiza a través de la barra de navegación lateral izquierda (**Menú Lateral / Sidebar**) y la barra superior de acciones:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              MAPA DE NAVEGACIÓN VISUAL EN UI                           │
├──────────────────────────────────┬─────────────────────────────────────────────────────┤
│ Sección del Menú Lateral         │ Submenú / Pantalla Destino en la Interfaz           │
├──────────────────────────────────┼─────────────────────────────────────────────────────┤
│ 📁 Productos e Inventario        │ • Productos y Servicios (Catálogo General)          │
│                                  │ • Tablero de Inventario (Existencias por Almacén)   │
│                                  │ • Kardex Valorizado (Auditoría Continua FIFO)       │
│                                  │ • Recepciones de Mercancía (Entradas por Compras)   │
│                                  │ • Transferencias (Traslados entre Almacenes)        │
│                                  │ • Conteos Físicos (Auditorías y Ajustes de Merma)   │
│                                  │ • Lotes y Vencimientos (Seguimiento de Caducidad)   │
├──────────────────────────────────┼─────────────────────────────────────────────────────┤
│ 💳 Compras y Proveedores         │ • Órdenes de compra (Creación y Recepción)          │
│                                  │ • Facturas de proveedores (Cuentas por Pagar)       │
│                                  │ • Notas de crédito en compras                       │
│                                  │ • Proveedores (Directorio de Contactos)             │
├──────────────────────────────────┼─────────────────────────────────────────────────────┤
│ 📊 Ventas                        │ • Facturación Electrónica (Emisión e-CF)            │
│                                  │ • Notas de Crédito/Débito (Devoluciones)            │
│                                  │ • Cotizaciones                                      │
│                                  │ • Punto de Venta (POS)                              │
├──────────────────────────────────┼─────────────────────────────────────────────────────┤
│ 💰 Finanzas                      │ • Contabilidad > Entradas de Diario (Libro Diario)  │
│                                  │ • Bancos y Cajas                                    │
│                                  │ • Cuentas por Cobrar                                │
└──────────────────────────────────┴─────────────────────────────────────────────────────┘
```

### 2.1 Botones de Acción Clave en las Pantallas Principales

| Pantalla en el Sistema | Botones y Acciones Visibles para el Usuario |
|---|---|
| **Productos y Servicios** | Botón azul `+ Nuevo Artículo`, botón `Exportar CSV`, botones de fila `Editar` (ícono lápiz) y `Eliminar` (ícono papelera). |
| **Tablero de Inventario** | Botones superiores de cabecera: `Gestionar Almacenes`, `Nuevo Ajuste`, `Ver Movimientos`, `Exportar Stock (Excel)`. |
| **Gestionar Almacenes** | Botón superior `+ Nuevo Almacén`, botones de fila `Editar` y `Eliminar`. |
| **Recepciones de Mercancía** | Tabla de historial con botón `Ver Detalle`, botón `+ Nueva Recepción` o botón `Recibir Mercancía` dentro de la Orden de Compra aprobada. |
| **Transferencias** | Botón superior `+ Nueva Transferencia`, botones de acción por fila: botón verde `Aprobar` y botón rojo `Rechazar`. |
| **Conteos Físicos** | Botón superior `+ Iniciar Conteo`. En la sesión activa: botón `Guardar Conteos` y botón principal `Finalizar y Aplicar Ajustes`. |
| **Kardex Valorizado** | Barra de filtros: selector de `Artículo`, selector de `Almacén`, fechas `Desde` / `Hasta`, botón `Consultar / Filtrar`. Botones de reporte: `Exportar a Excel` y `Exportar a PDF`. |
| **Facturación Electrónica** | Botón `+ Nueva Factura`, botón `Emitir Factura`, botón `Guardar como Borrador`, y en el detalle de factura emitida: botón `Anular Factura`. |

---

## 3. Momentos de Actualización de Existencias Visibles en UI

Para un usuario que opera el sistema, es fundamental entender **cuándo cambian los números en pantalla**:

1. **Creación de un Producto:** Al registrar un artículo en **Productos y Servicios**, el sistema lo crea con existencia `0.00`. No aumenta el stock físico hasta que se reciba una compra o se registre un ajuste de entrada inicial.
2. **Recepción de Mercancía:** Al abrir una Orden de Compra aprobada y hacer clic en **"Registrar Recepción"**, el stock aumenta de inmediato en el almacén receptor seleccionado y se refleja en el **Tablero de Inventario**.
3. **Facturación de Venta:** 
   - Si la factura se guarda con el botón **"Guardar como Borrador"**, el inventario **NO se descuenta**.
   - Cuando se presiona **"Emitir Factura"** y la factura pasa a estado `Emitida` o `Cobrada`, las unidades se descuentan de forma automática e inmediata del almacén seleccionado.
4. **Transferencias de Almacén:** Al presionar **"Solicitar Transferencia"**, la solicitud queda en estado `Pendiente` sin mover unidades. El inventario se descuenta del almacén origen y se suma al almacén destino **únicamente en el momento en que el supervisor hace clic en el botón verde "Aprobar"**.
5. **Conteos Físicos:** Al iniciar un conteo o guardar conteos parciales, las existencias teóricas no cambian. El stock en el sistema se actualiza **únicamente al hacer clic en el botón "Finalizar y Aplicar Ajustes"**, generando los movimientos de merma o sobrante en ese instante.

---

## 4. Datos de Prueba Reproducibles (Dataset Base)

Para que el evaluador de QA pueda ejecutar las pruebas con total coherencia y comprobar los resultados numéricos exactos, se utilizarán los siguientes datos:

| Campo del Formulario | Valor Ficticio de Prueba |
|---|---|
| **Código SKU** | `PROD-001` |
| **Nombre del Producto** | Teclado USB Ergonómico Vyk |
| **Tipo de Producto** | `Bien` (Físico inventariable) |
| **Categoría** | `Electrónica` |
| **Unidad de Medida** | `Unidad` |
| **Precio de Venta** | RD$ 850.00 |
| **Tasa ITBIS** | 18% |
| **Costo Unitario Referencial** | RD$ 500.00 |
| **Stock Mínimo** | 5.00 unidades |
| **Stock Máximo** | 30.00 unidades |
| **Ubicación Pasillo** | Pasillo A - Estante 2 |
| **Almacén Origen (Almacén A)** | Almacén Principal |
| **Almacén Destino (Almacén B)** | Almacén Secundario B |

---

## 5. Matriz Matemática de Resultados Esperados (Control Paso a Paso)

La siguiente tabla refleja la evolución de existencias, capas FIFO y saldos valorizados que el usuario debe observar en la pantalla del **Kardex Valorizado** y en el **Tablero de Inventario** a medida que completa cada operación:

| Paso | Operación Ejecutada en UI | Documento / Acción | Cantidad Movida | Costo Unitario | Stock Alm. A | Stock Alm. B | Stock Total | Capas FIFO Activas en Sistema | Valor Total Inv. (RD$) | Asiento Contable Automático en Libro Diario |
|:---:|---|---|:---:|:---:|:---:|:---:|:---:|---|:---:|---|
| **0** | Crear producto en catálogo | Guardar Artículo | 0.00 | RD$ 0.00 | 0.00 | 0.00 | **0.00** | Sin capas | **RD$ 0.00** | Sin movimiento contable. |
| **1** | Recibir Compra 1 en Alm. A | Recepción OC-001 | +10.00 | RD$ 500.00 | 10.00 | 0.00 | **10.00** | Capa 1: 10 u @ RD$ 500.00 | **RD$ 5,000.00** | Débito: Inventario RD$ 5,000.00<br>Crédito: Mercancía en Tránsito RD$ 5,000.00 |
| **2** | Recibir Compra 2 en Alm. A | Recepción OC-002 | +10.00 | RD$ 600.00 | 20.00 | 0.00 | **20.00** | Capa 1: 10 u @ RD$ 500.00<br>Capa 2: 10 u @ RD$ 600.00 | **RD$ 11,000.00** | Débito: Inventario RD$ 6,000.00<br>Crédito: Mercancía en Tránsito RD$ 6,000.00 |
| **3** | Vender 5 u desde Alm. A | Emitir Factura FAC-001 | -5.00 | RD$ 500.00 | 15.00 | 0.00 | **15.00** | Capa 1: 5 u @ RD$ 500.00<br>Capa 2: 10 u @ RD$ 600.00 | **RD$ 8,500.00** | Débito: Costo de Ventas RD$ 2,500.00<br>Crédito: Inventario RD$ 2,500.00 |
| **4** | Trasladar 4 u de Alm. A a B | Aprobar Transferencia TR-001 | 4.00 | RD$ 500.00 | 11.00 | 4.00 | **15.00** | **Alm A:** Capa 1: 1 u @ 500; Capa 2: 10 u @ 600<br>**Alm B:** Capa T1: 4 u @ 500 | **RD$ 8,500.00** | Neutral dentro de la empresa.<br>(Mismo activo consolidado). |
| **5** | Conteo Físico en Alm. A (-2 u) | Finalizar Conteo CF-001 | -2.00 | Ponderado RD$ 550.00 | 9.00 | 4.00 | **13.00** | **Alm A:** Capa 2: 9 u @ 600.00<br>**Alm B:** Capa T1: 4 u @ 500.00 | **RD$ 7,400.00** | Débito: Pérdida/Merma RD$ 1,100.00<br>Crédito: Inventario RD$ 1,100.00 |

---

## 6. Plan Detallado de Pruebas Funcionales Manuales (Guía UI Paso a Paso)

---

### Casos de Prueba — Fase 1: Configuración Inicial y Almacenes

#### INV-001: Verificación Visual de Categorías Preconfiguradas
- **Prioridad:** Media | **Tipo:** Positivo
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Productos y Servicios` > Botón superior `+ Nuevo Artículo`.
- **Procedimiento Paso a Paso:**
  1. En el menú lateral izquierdo, haz clic en la sección **Productos e Inventario**.
  2. En el submenú desplegado, selecciona **Productos y Servicios**.
  3. En la parte superior derecha de la pantalla, haz clic en el botón azul **"+ Nuevo Artículo"**.
  4. En el formulario, localiza el campo desplegable **"Categoría"** y haz clic sobre él para desplegar las opciones.
- **Resultado Esperado:**
  - El selector visual contiene al menos las opciones: `General`, `Alimentos y Bebidas`, `Electrónica`, `Servicios`, `Ferretería`, `Otros`.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia / Captura de Pantalla:  
  - Observaciones:

---

#### INV-002: Creación de un Nuevo Almacén desde la Interfaz
- **Prioridad:** Alta | **Tipo:** Positivo
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Tablero de Inventario` > Botón `Gestionar Almacenes`.
- **Procedimiento Paso a Paso:**
  1. En el menú lateral izquierdo, haz clic en **Productos e Inventario** > **Tablero de Inventario**.
  2. En la barra de botones superiores, haz clic en el botón **"Gestionar Almacenes"**.
  3. En la pantalla de almacenes, haz clic en el botón verde superior **"+ Nuevo Almacén"**.
  4. Completa los campos del formulario:
     - **Nombre del Almacén:** `Almacén Secundario B`
     - **Descripción:** `Almacén para pruebas de transferencia y logística`
     - **Dirección:** `Av. Luperón No. 45, Santo Domingo`
     - **Sucursal:** Selecciona la sucursal activa en el selector.
  5. Haz clic en el botón inferior **"Guardar Almacén"**.
- **Resultado Esperado:**
  - Aparece un mensaje verde de confirmación en la parte superior: `"Almacén registrado exitosamente."`.
  - La pantalla regresa a la lista de almacenes y muestra `Almacén Secundario B` como activo.
  - Al regresar al **Tablero de Inventario**, aparece una nueva columna con el nombre del nuevo almacén.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-003: Prevención de Eliminación del Único Almacén Activo
- **Prioridad:** Alta | **Tipo:** Negativo / Control de Integridad
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Tablero de Inventario` > Botón `Gestionar Almacenes`.
- **Procedimiento Paso a Paso:**
  1. Accede a la lista de almacenes a través de **Gestionar Almacenes**.
  2. Asegúrate de tener un solo almacén en la lista (o intenta borrar el último disponible).
  3. En la fila del almacén, haz clic en el botón rojo **"Eliminar"** (ícono de papelera) y confirma la acción en el cuadro emergente.
- **Resultado Esperado:**
  - El sistema no elimina el almacén y muestra un mensaje de alerta rojo: `"Debe mantener al menos un almacén activo en el sistema."`.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-004: Control de Acceso por Permisos en el Menú Lateral
- **Prioridad:** Crítica | **Tipo:** Seguridad / Permisos
- **Procedimiento Paso a Paso:**
  1. Inicia sesión con un usuario estándar que no tenga asignado el permiso de inventario (`canManageInventory`).
  2. Observa la barra de navegación lateral izquierda.
- **Resultado Esperado:**
  - Las opciones `Tablero de Inventario`, `Kardex Valorizado`, `Recepciones de Mercancía`, `Transferencias` y `Conteos Físicos` **NO aparecen visibles** en el menú.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

### Casos de Prueba — Fase 2: Catálogo y Productos

#### INV-005: Registro de Producto Físico ("Bien") con Stock Inicial Cero
- **Prioridad:** Crítica | **Tipo:** Positivo
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Productos y Servicios` > Botón `+ Nuevo Artículo`.
- **Procedimiento Paso a Paso:**
  1. En el menú lateral, dirígete a **Productos e Inventario** > **Productos y Servicios**.
  2. Haz clic en el botón azul **"+ Nuevo Artículo"**.
  3. Completa los campos de la ficha del producto:
     - **Código SKU:** `PROD-001`
     - **Nombre del Producto:** `Teclado USB Ergonómico Vyk`
     - **Tipo:** En el selector, elige **`Bien`**.
     - **Categoría:** Selecciona `Electrónica`.
     - **Unidad de Medida:** Selecciona `Unidad`.
     - **Precio de Venta:** Digita `850.00`.
     - **Costo Unitario:** Digita `500.00`.
     - **Tasa ITBIS:** Selecciona `18%`.
     - **Stock Mínimo:** Digita `5.00`.
     - **Stock Máximo:** Digita `30.00`.
     - **Ubicación Pasillo:** Digita `Pasillo A - Estante 2`.
     - **Estado:** Asegúrate de que la casilla `Activo` esté marcada.
  4. Haz clic en el botón **"Guardar Artículo"**.
  5. En el menú lateral, haz clic en **Tablero de Inventario**.
- **Resultado Esperado:**
  - Aparece la notificación: `"Artículo añadido al catálogo de ventas."`.
  - En la lista de **Productos y Servicios**, el artículo muestra Existencia = `0.00`.
  - En el **Tablero de Inventario**, el artículo aparece con existencia `0.00` en todos los almacenes.
  - En la parte superior del Tablero, el producto aparece listado en la tarjeta de **Alertas de Stock Bajo** (porque `0 <= 5.00`).
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-006: Intento de Registro Omitiendo Campos Obligatorios
- **Prioridad:** Media | **Tipo:** Negativo
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Productos y Servicios` > Botón `+ Nuevo Artículo`.
- **Procedimiento Paso a Paso:**
  1. En el formulario de nuevo artículo, deja el campo **"Nombre del Producto"** completamente vacío.
  2. Deja el campo **"Precio de Venta"** vacío.
  3. Haz clic directamente en el botón **"Guardar Artículo"**.
- **Resultado Esperado:**
  - El formulario no se envía; el navegador resalta en rojo los campos obligatorios con un mensaje de validación visual (*"Completa este campo"*).
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-007: Prueba de Registro con Código SKU Duplicado (Hallazgo)
- **Prioridad:** Alta | **Tipo:** Negativo / Control de Catálogo
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Productos y Servicios` > Botón `+ Nuevo Artículo`.
- **Procedimiento Paso a Paso:**
  1. Con el producto `PROD-001` ya guardado, haz clic de nuevo en **"+ Nuevo Artículo"**.
  2. En el campo **Código SKU**, ingresa exactamente el mismo código: `PROD-001`.
  3. En Nombre, ingresa: `Teclado Copia Duplicado`.
  4. En Precio de Venta, ingresa: `900.00`.
  5. Haz clic en **"Guardar Artículo"**.
- **Resultado Esperado por Estándar QA:**
  - El sistema debería mostrar una alerta roja: `"El código SKU PROD-001 ya está asignado a otro producto."`.
- **Comportamiento Actual del Sistema (Hallazgo):**
  - El sistema permite guardar el duplicado sin advertencia.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-008: Ítem de Tipo "Servicio" vs Control de Inventario
- **Prioridad:** Alta | **Tipo:** Positivo / Diferenciación
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Productos y Servicios` > Botón `+ Nuevo Artículo`.
- **Procedimiento Paso a Paso:**
  1. Crea un producto con Código `SRV-001`, Nombre `Mantenimiento Preventivo`, y en el selector **Tipo**, elige **`Servicio`**.
  2. Guarda el artículo.
  3. En el menú lateral, dirígete a **Tablero de Inventario**.
  4. Luego, haz clic en el botón superior **"Nuevo Ajuste"**.
- **Resultado Esperado:**
  - El servicio `SRV-001` **NO aparece** en la lista de existencias del **Tablero de Inventario**.
  - En la pantalla de **Nuevo Ajuste**, el servicio **NO aparece disponible** en el menú desplegable para mover stock.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

### Casos de Prueba — Fase 3: Ingreso de Mercancías

#### INV-009: Recepción Total de Compra vinculada a Orden de Compra (OC-001)
- **Prioridad:** Crítica | **Tipo:** Positivo / Integración Compras
- **Requisitos Previos:** Disponer de una Orden de Compra aprobada (`OC-001`) al proveedor "Suplidora Tech" por 10 unidades de `PROD-001` a costo unitario RD$ 500.00.
- **Pantalla en la Interfaz:** Menú Lateral > `Compras y Proveedores` > `Órdenes de compra`.
- **Procedimiento Paso a Paso:**
  1. En el menú lateral, haz clic en **Compras y Proveedores** > **Órdenes de compra**.
  2. En la lista, localiza la orden `OC-001` (en estado `Aprobada`) y haz clic sobre ella para abrir su detalle.
  3. En la barra superior del detalle de la orden, haz clic en el botón verde **"Recibir Mercancía"**.
  4. En el formulario de recepción que se abre en pantalla:
     - Verifica que la fecha de recepción corresponda al día de hoy.
     - En el selector **"Almacén de Destino"**, selecciona **`Almacén Principal`**.
     - En la tabla de partidas, en el campo editable **"Cantidad Recibida"**, ingresa **`10.00`**.
     - En Notas, ingresa: `Recepción completa según factura física de entrega`.
  5. Haz clic en el botón inferior **"Registrar Recepción"**.
- **Resultado Esperado:**
  - Aparece la notificación verde: `"Recepción RC-XXXX registrada exitosamente."`.
  - La Orden de Compra cambia automáticamente su estado a **`Recibida Completa`**.
  - En el menú lateral > **Productos e Inventario** > **Tablero de Inventario**, la columna de `Almacén Principal` para `PROD-001` muestra ahora **`10.00`** unidades.
  - En el menú lateral > **Productos e Inventario** > **Kardex Valorizado**, se muestra la entrada:
    - Cantidad Entrada: `10.00` | Costo Unitario: `RD$ 500.00` | Valor Total: `RD$ 5,000.00`.
  - En el menú lateral > **Finanzas** > **Contabilidad** > **Entradas de Diario**, aparece un nuevo asiento contable:
    - Débito: `Inventario de Mercancías` = RD$ 5,000.00.
    - Crédito: `Mercancía Recibida no Facturada / Tránsito` = RD$ 5,000.00.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-010: Segunda Entrada con Costo Diferente (OC-002 / Capa FIFO 2)
- **Prioridad:** Crítica | **Tipo:** Positivo / Capas de Costo
- **Requisitos Previos:** Prueba INV-009 ejecutada previamente.
- **Pantalla en la Interfaz:** Menú Lateral > `Compras y Proveedores` > `Órdenes de compra`.
- **Procedimiento Paso a Paso:**
  1. Abre la orden `OC-002` aprobada por 10 unidades de `PROD-001` a costo unitario **RD$ 600.00**.
  2. Haz clic en el botón **"Recibir Mercancía"**.
  3. Selecciona **`Almacén Principal`**, ingresa cantidad recibida = **`10.00`** y presiona **"Registrar Recepción"**.
  4. En el menú lateral, dirígete a **Productos e Inventario** > **Kardex Valorizado**, selecciona `PROD-001` y presiona **"Consultar / Filtrar"**.
- **Resultado Esperado:**
  - En el **Tablero de Inventario**, las existencias en Almacén Principal aumentan a **`20.00`** unidades.
  - En el **Kardex Valorizado**, se muestra el acumulado:
    - Entrada 1: 10 u @ RD$ 500.00 (RD$ 5,000.00).
    - Entrada 2: 10 u @ RD$ 600.00 (RD$ 6,000.00).
    - **Saldo Total Acumulado:** `20.00` unidades con un **Valor Monetario Total** de **`RD$ 11,000.00`**.
    - El costo promedio ponderado de catálogo se actualiza automáticamente a **`RD$ 550.00`**.
  - Se genera automáticamente el asiento contable en el Libro Diario por RD$ 6,000.00.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-011: Recepción Parcial de Mercancía
- **Prioridad:** Alta | **Tipo:** Positivo / Ciclo Parcial
- **Pantalla en la Interfaz:** Menú Lateral > `Compras y Proveedores` > `Órdenes de compra`.
- **Procedimiento Paso a Paso:**
  1. En una orden de compra aprobada por 20 unidades, haz clic en **"Recibir Mercancía"**.
  2. En el campo de cantidad recibida, ingresa únicamente **`8.00`** unidades.
  3. Haz clic en **"Registrar Recepción"**.
- **Resultado Esperado:**
  - El inventario aumenta en 8.00 unidades en el almacén seleccionado.
  - La Orden de Compra cambia su etiqueta de estado a **`Recibida Parcial`** (badge amarillo).
  - En el detalle de la orden se indica claramente: `Recibidas: 8.00 / Pendientes: 12.00`.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-012: Prueba de Sobre-recepción de Mercancía (Hallazgo)
- **Prioridad:** Media | **Tipo:** Negativo / Control de Cantidades
- **Pantalla en la Interfaz:** Menú Lateral > `Compras y Proveedores` > `Órdenes de compra`.
- **Procedimiento Paso a Paso:**
  1. En una orden donde queden 10 unidades pendientes, haz clic en **"Recibir Mercancía"**.
  2. En el campo de cantidad recibida, digita **`15.00`** unidades (5 unidades por encima de lo ordenado).
  3. Haz clic en **"Registrar Recepción"**.
- **Resultado Esperado por Estándar QA:**
  - El sistema debería impedir el registro y mostrar una advertencia: *"La cantidad recibida no puede ser mayor a la cantidad pendiente de la orden."*.
- **Comportamiento Actual del Sistema (Hallazgo):**
  - El sistema procesa la recepción completa de 15 unidades sin bloquear la operación.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-013: Entrada Manual con Cantidad Cero o Negativa
- **Prioridad:** Alta | **Tipo:** Negativo
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Tablero de Inventario` > Botón `Nuevo Ajuste`.
- **Procedimiento Paso a Paso:**
  1. En el Tablero de Inventario, haz clic en el botón superior **"Nuevo Ajuste"**.
  2. En el formulario:
     - Selecciona el producto `PROD-001`.
     - En **Tipo de Operación**, selecciona **`ENTRADA (+)`**.
     - En **Motivo**, selecciona `Compra a Proveedor / Reabastecimiento`.
     - En **Almacén de Destino**, selecciona `Almacén Principal`.
     - En **Cantidad**, ingresa `0.00` o `-5.00`.
  3. Haz clic en el botón **"Registrar Ajuste"**.
- **Resultado Esperado:**
  - La validación del formulario impide el envío indicando que el valor debe ser mayor o igual a `0.01`.
  - No se modifica ninguna existencia en el sistema.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

### Casos de Prueba — Fase 4: Salidas de Mercancías

#### INV-014: Venta Facturada y Descargo Automático FIFO (FAC-001)
- **Prioridad:** Crítica | **Tipo:** Positivo / Integración Facturación
- **Requisitos Previos:** `PROD-001` con 20 unidades en Almacén Principal (10 u a RD$ 500 y 10 u a RD$ 600).
- **Pantalla en la Interfaz:** Menú Lateral > `Ventas` > `Facturación Electrónica`.
- **Procedimiento Paso a Paso:**
  1. En el menú lateral, haz clic en **Ventas** > **Facturación Electrónica**.
  2. Haz clic en el botón azul superior **"+ Nueva Factura"**.
  3. En la cabecera de la factura:
     - Selecciona un Cliente con RNC válido.
     - En Tipo de Comprobante, selecciona `Factura de Crédito Fiscal (E31)` o `Consumo (E32)`.
     - En el selector **"Almacén de Despacho"**, asegúrate de elegir **`Almacén Principal`**.
  4. En la tabla de productos, agrega una fila:
     - Selecciona `PROD-001 - Teclado USB Ergonómico Vyk`.
     - En Cantidad, ingresa **`5.00`**.
     - Verifica que el Precio unitario sea `RD$ 850.00`.
  5. Haz clic en el botón principal **"Emitir Factura"**.
  6. En el menú lateral, dirígete a **Productos e Inventario** > **Tablero de Inventario**.
  7. Luego, haz clic en **Kardex Valorizado** y consulta `PROD-001`.
- **Resultado Esperado:**
  - La factura se emite exitosamente con su número fiscal e-NCF.
  - En el **Tablero de Inventario**, la existencia de `PROD-001` en Almacén Principal se reduce automáticamente de 20.00 a **`15.00`** unidades.
  - En el **Kardex Valorizado**, se registra la fila de salida:
    - Tipo: `SALIDA` | Motivo: `VENTA` | Cantidad Salida: `5.00`.
    - **Costo Unitario de Salida:** Se descuenta a **`RD$ 500.00`** (utiliza la Capa 1 más antigua por FIFO).
    - **Costo de Venta Total (COGS):** `RD$ 2,500.00` (5 × RD$ 500.00).
    - **Saldo Restante Valorizado:** **`RD$ 8,500.00`** (5 u @ 500 + 10 u @ 600).
  - En el menú lateral > **Finanzas** > **Contabilidad** > **Entradas de Diario**, se generó automáticamente el asiento de Costo de Ventas:
    - Débito: `Costo de Ventas` = **RD$ 2,500.00**.
    - Crédito: `Inventario de Mercancías` = **RD$ 2,500.00**.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-015: Factura Guardada como Borrador (No Afectación de Stock)
- **Prioridad:** Alta | **Tipo:** Positivo / Regla de Negocio
- **Pantalla en la Interfaz:** Menú Lateral > `Ventas` > `Facturación Electrónica` > Botón `+ Nueva Factura`.
- **Procedimiento Paso a Paso:**
  1. Inicia una nueva factura con 3 unidades de `PROD-001`.
  2. En lugar de emitir, haz clic en el botón secundario **"Guardar como Borrador"**.
  3. En el menú lateral, abre el **Tablero de Inventario**.
- **Resultado Esperado:**
  - La factura queda listada con la etiqueta gris `Borrador`.
  - Las existencias físicas en el almacén **NO disminuyen** (permanecen idénticas).
  - No se genera ningún movimiento en el Kardex ni en la contabilidad.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-016: Venta con Stock Insuficiente (Bloqueo de Saldo Negativo)
- **Prioridad:** Crítica | **Tipo:** Negativo / Control de Existencias
- **Requisitos Previos:** `PROD-001` cuenta con 15 unidades disponibles en Almacén Principal.
- **Pantalla en la Interfaz:** Menú Lateral > `Ventas` > `Facturación Electrónica` > Botón `+ Nueva Factura`.
- **Procedimiento Paso a Paso:**
  1. En una nueva factura, selecciona Almacén Principal.
  2. En la partida de `PROD-001`, intenta colocar una cantidad de **`25.00`** unidades.
  3. Haz clic en el botón **"Emitir Factura"**.
- **Resultado Esperado:**
  - El sistema detiene la emisión y muestra un mensaje de error en pantalla: `"Stock insuficiente en almacén 'Almacén Principal'. Disponible: 15.0, Solicitado: 25.0"`.
  - La factura no se emite y no se descuenta ningún inventario.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-017: Anulación de Factura y Reversión Automática al Almacén
- **Prioridad:** Crítica | **Tipo:** Integración / Reversión
- **Requisitos Previos:** Disponer de una factura emitida donde se hayan descontado unidades físicas.
- **Pantalla en la Interfaz:** Menú Lateral > `Ventas` > `Facturación Electrónica`.
- **Procedimiento Paso a Paso:**
  1. En la lista de facturas, haz clic sobre la factura para abrir su vista de detalle.
  2. En las acciones superiores, haz clic en el botón **"Anular Factura"**.
  3. En la ventana emergente, selecciona el motivo de anulación y presiona **"Confirmar Anulación"**.
  4. En el menú lateral, dirígete a **Productos e Inventario** > **Tablero de Inventario**.
- **Resultado Esperado:**
  - La factura cambia su estado a `Anulada` (badge rojo).
  - Las unidades vendidas regresan de inmediato al almacén original de despacho.
  - En el **Kardex Valorizado**, se muestra una entrada con motivo `DEVOLUCION_CLIENTE / ANULACION_FACTURA`.
  - En **Entradas de Diario**, se reversa el asiento de costo de ventas.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-018: Devolución con Nota de Crédito E34 (`reingresoStock = Sí`)
- **Prioridad:** Alta | **Tipo:** Positivo / Devoluciones
- **Pantalla en la Interfaz:** Menú Lateral > `Ventas` > `Notas de Crédito/Débito`.
- **Procedimiento Paso a Paso:**
  1. En el menú lateral, haz clic en **Ventas** > **Notas de Crédito/Débito**.
  2. Haz clic en el botón superior **"+ Nueva Nota de Crédito"**.
  3. Selecciona la factura original afectada.
  4. Marca obligatoriamente la casilla de verificación: **"Reingresar mercancía al inventario"**.
  5. Haz clic en **"Emitir Nota de Crédito"**.
- **Resultado Esperado:**
  - El stock físico aumenta en el almacén de despacho original.
  - El Kardex registra el reingreso al costo unitario histórico de la salida original.
  - Contablemente se genera el reverso correspondiente del costo de ventas.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-019: Salida Manual por Merma / Daño de Mercancía
- **Prioridad:** Alta | **Tipo:** Positivo / Operación Manual
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Tablero de Inventario` > Botón `Nuevo Ajuste`.
- **Procedimiento Paso a Paso:**
  1. En el Tablero de Inventario, haz clic en el botón superior **"Nuevo Ajuste"**.
  2. En el formulario:
     - Selecciona `PROD-001`.
     - Tipo de Operación: Selecciona **`SALIDA (-)`**.
     - Motivo: Selecciona **`Pérdida / Daño / Rotura / Robo`**.
     - Almacén de Origen: Selecciona `Almacén Principal`.
     - Cantidad: Ingresa `1.00`.
     - Notas: Digita `Empaque mojado y producto dañado en estantería`.
  3. Haz clic en **"Registrar Ajuste"**.
- **Resultado Esperado:**
  - Notificación de confirmación: `"Movimiento de inventario registrado y existencias actualizadas exitosamente."`.
  - El stock en Almacén Principal disminuye en 1 unidad.
  - En Contabilidad > Entradas de Diario, se registra:
    - Débito: `Pérdida o Merma en Inventario`.
    - Crédito: `Inventario de Mercancías`.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

### Casos de Prueba — Fase 5: Transferencias entre Almacenes

#### INV-020: Solicitud y Aprobación de Transferencia (TR-001)
- **Prioridad:** Crítica | **Tipo:** Positivo / Logística
- **Requisitos Previos:** `PROD-001` cuenta con 15 unidades en Almacén Principal y 0 unidades en Almacén Secundario B.
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Transferencias`.
- **Procedimiento Paso a Paso:**
  1. En el menú lateral, haz clic en **Productos e Inventario** > **Transferencias**.
  2. Haz clic en el botón superior **"+ Nueva Transferencia"**.
  3. En el formulario de traslado:
     - En **Almacén Origen**, selecciona **`Almacén Principal`**.
     - En **Almacén Destino**, selecciona **`Almacén Secundario B`**.
     - En la tabla de productos, busca `PROD-001` y en el campo de cantidad ingresa **`4.00`**.
     - En Notas, ingresa: `Traslado de stock para vitrina de sucursal B`.
  4. Haz clic en el botón **"Solicitar Transferencia"**.
  5. En la lista de transferencias, verifica que la nueva solicitud aparezca con la etiqueta amarilla **`Pendiente`**.
  6. En la misma fila de la tabla, en la columna de acciones, haz clic en el botón verde **"Aprobar"**.
  7. En el menú lateral, dirígete a **Tablero de Inventario**.
- **Resultado Esperado:**
  - Aparece la notificación verde: `"Transferencia completada."` y el estado cambia a **`Completada`** (badge verde).
  - En el **Tablero de Inventario**:
    - `Almacén Principal` disminuye de 15.00 a **`11.00`** unidades.
    - `Almacén Secundario B` aumenta de 0.00 a **`4.00`** unidades.
    - La columna de **Existencia Total Empresa** se mantiene en **`15.00`** unidades (principio de conservación).
  - Trazabilidad de Costos FIFO:
    - En Almacén Principal se consumen 4 unidades de la Capa 1 (@ RD$ 500.00).
    - En Almacén Secundario B ingresan 4 unidades a costo exacto de **`RD$ 500.00`** cada una.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-021: Transferencia con Almacén Origen y Destino Idénticos
- **Prioridad:** Alta | **Tipo:** Negativo / Validación
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Transferencias` > Botón `+ Nueva Transferencia`.
- **Procedimiento Paso a Paso:**
  1. En el formulario de nueva transferencia, selecciona `Almacén Principal` tanto en Origen como en Destino.
  2. Ingresa cantidad = 2.00 para cualquier producto.
  3. Haz clic en el botón **"Solicitar Transferencia"**.
- **Resultado Esperado:**
  - La pantalla rechaza la acción con un mensaje de alerta rojo: `"El almacén origen y destino deben ser diferentes."`.
  - No se genera ninguna transferencia en la lista.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-022: Transferencia por Cantidad Superior a Existencias en Origen
- **Prioridad:** Alta | **Tipo:** Negativo
- **Requisitos Previos:** Almacén Principal dispone de 11 unidades de `PROD-001`.
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Transferencias`.
- **Procedimiento Paso a Paso:**
  1. Crea una solicitud de transferencia desde Almacén Principal hacia Almacén Secundario por una cantidad de **`30.00`** unidades.
  2. En la lista de transferencias, localiza la solicitud pendiente y haz clic en el botón verde **"Aprobar"**.
- **Resultado Esperado:**
  - El sistema detiene la operación y muestra un error indicando que no hay suficiente stock en el origen.
  - Ningún almacén sufre modificaciones en sus existencias.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-023: Rechazo de Solicitud de Transferencia
- **Prioridad:** Media | **Tipo:** Positivo / Flujo de Cancelación
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Transferencias`.
- **Procedimiento Paso a Paso:**
  1. Con una transferencia en estado `Pendiente`, haz clic en el botón rojo **"Rechazar"**.
  2. En la ventana modal de confirmación, digita en el motivo: `Sin vehículo de traslado disponible`.
  3. Confirma el rechazo.
- **Resultado Esperado:**
  - La transferencia pasa al estado **`Rechazada`** (badge rojo).
  - Las existencias de ambos almacenes permanecen completamente inalteradas.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

### Casos de Prueba — Fase 6: Conteo Físico de Inventario

#### INV-024: Inicio de Conteo Físico y Snapshot Teórico
- **Prioridad:** Crítica | **Tipo:** Positivo / Auditoría
- **Requisitos Previos:** Almacén Principal cuenta con 11 unidades de `PROD-001`.
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Conteos Físicos`.
- **Procedimiento Paso a Paso:**
  1. En el menú lateral, haz clic en **Productos e Inventario** > **Conteos Físicos**.
  2. Haz clic en el botón azul superior **"+ Iniciar Conteo"**.
  3. En la pantalla de inicio, selecciona en el menú desplegable: **`Almacén Principal`**.
  4. Haz clic en el botón **"Iniciar Conteo"**.
- **Resultado Esperado:**
  - Se abre la pantalla de detalle de la sesión de conteo con estado **`En Progreso`**.
  - En la tabla de conteo, la fila de `PROD-001` muestra en la columna **"Cantidad Esperada"** el valor congelado: **`11.00`**.
  - La columna **"Cantidad Contada"** inicia con un campo editable en `0.00`.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-025: Conteo Físico con Faltante (-2 u) y Ajuste Automático (CF-001)
- **Prioridad:** Crítica | **Tipo:** Positivo / Ajuste Financiero
- **Requisitos Previos:** Conteo INV-024 abierto en pantalla con 11 unidades esperadas de `PROD-001`.
- **Pantalla en la Interfaz:** Detalle de la sesión de conteo físico en pantalla.
- **Procedimiento Paso a Paso:**
  1. En la fila de `PROD-001 - Teclado USB Ergonómico Vyk`, ubica la casilla de texto en la columna **"Cantidad Contada"**.
  2. Digita la cantidad física realmente encontrada en las estanterías: **`9.00`** (2 unidades menos de lo esperado).
  3. Haz clic en el botón secundario **"Guardar Conteos"**.
  4. Verifica que la columna **"Diferencia"** muestre en rojo el valor **`-2.0000`**.
  5. Haz clic en el botón principal superior **"Finalizar y Aplicar Ajustes"**.
  6. En el menú lateral, abre **Tablero de Inventario** y **Kardex Valorizado**.
- **Resultado Esperado:**
  - Notificación verde: `"Conteo finalizado. 1 líneas con diferencia, 1 ajustes generados."`.
  - La sesión de conteo pasa al estado definitivo **`Ajustado`**.
  - En el **Tablero de Inventario**, las existencias de `PROD-001` en Almacén Principal se actualizan de 11.00 a **`9.00`** unidades.
  - En el **Kardex Valorizado**, se genera una fila:
    - Tipo: `SALIDA` | Motivo: `RECUENTO_FISICO` | Cantidad: `2.00`.
    - **Consumo FIFO:** Consume 1 u de Capa 1 (@ RD$ 500.00) + 1 u de Capa 2 (@ RD$ 600.00).
    - **Valor Total del Faltante (Merma):** **`RD$ 1,100.00`**.
    - **Saldo Final Empresa:** **`13.00`** unidades con valor monetario total de **`RD$ 7,400.00`**.
  - En el menú lateral > **Finanzas** > **Contabilidad** > **Entradas de Diario**, aparece el asiento contable:
    - Débito: `Pérdida o Merma en Inventario` = **RD$ 1,100.00**.
    - Crédito: `Inventario de Mercancías` = **RD$ 1,100.00**.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-026: Conteo Físico con Sobrante de Mercancía
- **Prioridad:** Alta | **Tipo:** Positivo / Ganancia en Ajuste
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Conteos Físicos`.
- **Procedimiento Paso a Paso:**
  1. Inicia un conteo en un almacén donde un producto tenga stock esperado de 5 unidades.
  2. En la casilla de cantidad contada, ingresa **`7.00`** (diferencia positiva = `+2.00`).
  3. Haz clic en **"Finalizar y Aplicar Ajustes"**.
- **Resultado Esperado:**
  - El stock físico en el almacén aumenta a 7.00 unidades.
  - En Contabilidad > Entradas de Diario, se registra el asiento:
    - Débito: `Inventario de Mercancías`
    - Crédito: `Ganancia o Ajuste Positivo de Inventario`.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-027: Prevención de Re-finalización en Conteos ya Cerrados
- **Prioridad:** Crítica | **Tipo:** Negativo / Control Anti-duplicidad
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Conteos Físicos`.
- **Procedimiento Paso a Paso:**
  1. Abre una sesión de conteo que ya esté en estado `Ajustado` o `Finalizado`.
  2. Intenta hacer clic de nuevo en el botón de finalizar (o refrescar la página tras el envío).
- **Resultado Esperado:**
  - El botón está deshabilitado en pantalla o el sistema muestra un mensaje de advertencia indicando que el conteo ya fue cerrado previamente.
  - No se vuelven a aplicar movimientos ni asientos contables duplicados.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

### Casos de Prueba — Fase 7: Kardex y Reportes

#### INV-028: Auditoría Integral del Kardex Valorizado Continuo
- **Prioridad:** Crítica | **Tipo:** Positivo / Cuadratura de Costos
- **Requisitos Previos:** Haber completado los pasos 1 al 5 del dataset base (INV-009, INV-010, INV-014, INV-020, INV-025).
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Kardex Valorizado`.
- **Procedimiento Paso a Paso:**
  1. En el menú lateral, haz clic en **Productos e Inventario** > **Kardex Valorizado**.
  2. En la barra superior de filtros:
     - En el menú desplegable **Artículo**, selecciona `PROD-001 - Teclado USB Ergonómico Vyk`.
     - En **Almacén**, selecciona `Todos los Almacenes`.
     - Deja los campos de fecha en blanco para ver todo el historial.
  3. Haz clic en el botón azul **"Consultar / Filtrar"**.
  4. Revisa la tabla de movimientos generada en pantalla.
- **Resultado Esperado:**
  - La tabla presenta en orden cronológico perfecto las operaciones:
    1. `Recepción OC-001`: Entrada 10 u @ RD$ 500.00 | Saldo = 10 u (RD$ 5,000.00).
    2. `Recepción OC-002`: Entrada 10 u @ RD$ 600.00 | Saldo = 20 u (RD$ 11,000.00).
    3. `Factura FAC-001`: Salida 5 u @ RD$ 500.00 | Saldo = 15 u (RD$ 8,500.00).
    4. `Transferencia TR-001`: Movimiento interno equilibrado.
    5. `Ajuste CF-001`: Salida 2 u por merma (RD$ 1,100.00) | Saldo = 13 u (RD$ 7,400.00).
  - En la parte inferior, el cuadro de **Saldo Final** resume con exactitud:
    - **Cantidad Total:** **`13.00`** unidades.
    - **Valor Total del Inventario:** **`RD$ 7,400.00`**.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-029: Exportación del Kardex a Archivos Excel y PDF
- **Prioridad:** Alta | **Tipo:** Positivo / Exportación
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Kardex Valorizado`.
- **Procedimiento Paso a Paso:**
  1. En la vista del Kardex filtrado con `PROD-001`, localiza la barra de herramientas superior.
  2. Haz clic en el botón verde **"Exportar a Excel"**.
  3. Abre el archivo `.xlsx` descargado en tu computadora y revisa sus columnas y fórmulas.
  4. Regresa a la pantalla y haz clic en el botón rojo **"Exportar a PDF"**.
  5. Revisa el documento PDF que se abre en una nueva pestaña del navegador.
- **Resultado Esperado:**
  - El archivo Excel descargado contiene el membrete formal de VykOne ERP, columnas ordenadas de entradas, salidas y saldos con formato monetario.
  - El archivo PDF presenta diseño profesional, encabezado fiscal con RNC de la empresa, paginación y totales perfectamente alineados.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

### Casos de Prueba — Fase 8: Alertas y Controles Visuales

#### INV-030: Activación Visual de Alerta por Stock Bajo
- **Prioridad:** Alta | **Tipo:** Positivo / Notificación Visual
- **Requisitos Previos:** `PROD-001` tiene stock mínimo configurado en 5.00 unidades.
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Tablero de Inventario`.
- **Procedimiento Paso a Paso:**
  1. Realiza salidas hasta que la existencia total de `PROD-001` sea igual o menor a 4 unidades.
  2. En el menú lateral, haz clic en **Tablero de Inventario**.
  3. Observa la tarjeta superior de **"Alertas de Stock Bajo"**.
- **Resultado Esperado:**
  - El producto aparece resaltado en el panel de alertas con una insignia roja (*badge*).
  - Indica claramente: `Existencia Actual: 4.00 / Mínimo Requerido: 5.00`.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-031: Consulta de Sugerencias de Reorden y Compras
- **Prioridad:** Media | **Tipo:** Positivo / Inteligencia Logística
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Tablero de Inventario` > Enlace o botón `Inventario Avanzado / Alertas`.
- **Procedimiento Paso a Paso:**
  1. Con al menos 3 ventas registradas en los últimos 90 días para un producto, ingresa a la vista de alertas avanzadas.
  2. Revisa la tabla de **"Sugerencias de Reorden y Puntos de Pedido"**.
- **Resultado Esperado:**
  - La tabla calcula y muestra de forma clara: `Consumo Mensual Promedio`, `Meses de Stock Restante`, `Pedido Sugerido` y el nivel de `Severidad` (Crítico, Alto, Medio o Bajo).
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

#### INV-032: Prevención de Movimiento Duplicado por Doble Clic Rápido
- **Prioridad:** Crítica | **Tipo:** Negativo / Integridad Transaccional
- **Pantalla en la Interfaz:** Menú Lateral > `Productos e Inventario` > `Tablero de Inventario` > Botón `Nuevo Ajuste`.
- **Procedimiento Paso a Paso:**
  1. En el formulario de Nuevo Ajuste, completa los datos para ingresar 5 unidades de un producto.
  2. Al presionar el botón **"Registrar Ajuste"**, haz un doble clic intencional muy rápido sobre el botón antes de que la página recargue.
- **Resultado Esperado:**
  - El sistema procesa la transacción una sola vez.
  - En el Tablero de Inventario y en la lista de movimientos, las existencias aumentan únicamente en 5 unidades (no en 10).
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

### Casos de Prueba — Fase 9: Integración Contable Visual

#### INV-033: Verificación del Asiento Automático en el Libro Diario
- **Prioridad:** Crítica | **Tipo:** Positivo / Auditoría Contable
- **Pantalla en la Interfaz:** Menú Lateral > `Finanzas` > `Contabilidad` > `Entradas de Diario`.
- **Procedimiento Paso a Paso:**
  1. Luego de emitir una factura de venta (ej. `FAC-001` de la prueba INV-014), abre el menú lateral.
  2. Haz clic en **Finanzas** > **Contabilidad** > **Entradas de Diario**.
  3. En la barra de búsqueda o en la lista de asientos recientes, localiza el asiento con concepto: `Costo de Ventas - Factura FAC-001` (o con tipo `inventory`).
  4. Haz clic en la fila del asiento para ver su detalle en pantalla.
- **Resultado Esperado:**
  - El asiento se encuentra en estado **`Activo`**.
  - La tabla de líneas muestra:
    - Línea Débito: `Costo de Ventas` = **RD$ 2,500.00**.
    - Línea Crédito: `Inventario de Mercancías` = **RD$ 2,500.00**.
  - Los totales cuadran al centavo: `Total Débito: RD$ 2,500.00` / `Total Crédito: RD$ 2,500.00`.
- **Resultado Obtenido:**  
  - Estado: `[ ] Aprobado  [ ] Fallido  [ ] Bloqueado  [ ] No Ejecutado`  
  - Evidencia:  
  - Observaciones:

---

## 7. Matriz de Trazabilidad de Requisitos (RTM Visual)

| Funcionalidad en UI | Navegación en Pantalla | Caso de Prueba | Resultado Esperado Principal | Riesgo Cubierto | Evidencia Requerida en QA |
|---|---|---|---|---|---|
| **Catálogo de Almacenes** | `Productos e Inventario > Tablero > Gestionar Almacenes` | INV-002, INV-003 | Registro de almacenes y bloqueo de borrado del último | Pérdida de estructura logística | Captura de tabla de almacenes |
| **Permisos de Menú** | `Barra Lateral Izquierda (Sidebar)` | INV-004 | Ocultamiento visual de opciones a usuarios no autorizados | Brecha de seguridad / manipulación | Captura del menú colapsado |
| **Alta de Artículos** | `Productos e Inventario > Productos y Servicios > + Nuevo Artículo` | INV-005, INV-008 | Existencia inicial en 0.00; exclusión de servicios | Existencias ficticias al crear ítems | Ficha de producto en catálogo |
| **Unicidad de SKU** | `Productos e Inventario > Productos y Servicios > + Nuevo Artículo` | INV-007 | Validación de código duplicado | Confusión de productos en ventas | Mensaje de validación SKU |
| **Recepción de Compras** | `Compras y Proveedores > Órdenes de compra > Recibir Mercancía` | INV-009, INV-010, INV-011 | Ingreso de unidades a almacén y creación de capas FIFO | Compras no reflejadas en stock | Detalle de recepción y kardex |
| **Control de Sobreejecución** | `Compras y Proveedores > Órdenes de compra > Recibir Mercancía` | INV-012 | Alerta o restricción ante recepciones mayores a ordenadas | Pagos excesivos / descontrol | Formulario de recepción |
| **Venta y Descargo e-CF** | `Ventas > Facturación Electrónica > + Nueva Factura` | INV-014, INV-015 | Descuento automático FIFO solo al emitir factura | Evasión de costo de venta / descuadre | Detalle de factura y movimiento |
| **Bloqueo Stock Negativo** | `Ventas > Facturación Electrónica > + Nueva Factura` | INV-016 | Bloqueo en pantalla ante falta de existencias físicas | Ventas con saldos negativos | Mensaje de error en pantalla |
| **Reversión por Anulación** | `Ventas > Facturación Electrónica > Detalle > Anular Factura` | INV-017 | Reingreso automático de unidades al almacén | Pérdida de inventario anulado | Movimiento de reingreso |
| **Devoluciones Clientes E34** | `Ventas > Notas de Crédito/Débito > + Nueva Nota de Crédito` | INV-018 | Reingreso físico al costo histórico original | Distorsión del costo de ventas | Kardex y nota de crédito |
| **Transferencias de Almacén** | `Productos e Inventario > Transferencias > + Nueva Transferencia` | INV-020, INV-021, INV-022 | Traslado atómico, conservación del inventario total | Pérdida de mercancía en traslado | Saldos en ambos almacenes |
| **Conteo Físico y Auditoría** | `Productos e Inventario > Conteos Físicos > + Iniciar Conteo` | INV-024, INV-025, INV-026 | Snapshot teórica y ajustes automáticos FIFO | Mermas ocultas / desajustes físicos | Detalle de conteo y asiento |
| **Anti-duplicidad en Conteos**| `Productos e Inventario > Conteos Físicos > Detalle de Sesión` | INV-027 | Bloqueo de re-finalización en sesiones cerradas | Doble contabilización de ajustes | Alerta al reintentar finalizar |
| **Kardex Continuo FIFO** | `Productos e Inventario > Kardex Valorizado` | INV-028, INV-029 | Visión cronológica inmutable y reportes Excel / PDF | Incumplimiento DGII / falta de auditoría | Archivo Excel y reporte PDF |
| **Alertas de Reorden** | `Productos e Inventario > Tablero > Alertas de Stock` | INV-030, INV-031 | Notificación visual de mínimos y sugerencia de compra | Desabastecimiento operativo | Tablero de alertas |
| **Control Transaccional** | `Productos e Inventario > Tablero > Nuevo Ajuste` | INV-032 | Deduplicación por doble clic | Transacciones repetidas por red | Tabla de movimientos |
| **Contabilidad Integrada** | `Finanzas > Contabilidad > Entradas de Diario` | INV-033 | Asiento automático de inventario y costo de ventas | Desfase contable vs stock físico | Asiento contable balanceado |

---

## 8. Registro Formal de Hallazgos y Defectos Potenciales

Durante la auditoría visual y funcional del sistema se identificaron las siguientes oportunidades de mejora y riesgos operativos para el usuario final:

### Hallazgo 1: Falta de Validación de Unicidad en Código SKU
- **Severidad:** Media  
- **Ubicación en Pantalla:** Menú Lateral > `Productos e Inventario` > `Productos y Servicios` > Formulario `+ Nuevo Artículo`.  
- **Descripción:** El formulario permite registrar múltiples productos distintos con el mismo texto en el campo **Código SKU**. Cuando el vendedor busca el producto por código en la pantalla de Facturación, el sistema puede seleccionar automáticamente el primero que encuentre, generando riesgo de despachar un artículo equivocado.  
- **Recomendación:** Agregar una validación visual en el formulario que alerte al usuario si el código ingresado ya está asignado a otro artículo en la empresa.

### Hallazgo 2: Posibilidad de Recibir Cantidades Superiores a la Orden de Compra
- **Severidad:** Alta  
- **Ubicación en Pantalla:** Menú Lateral > `Compras y Proveedores` > `Órdenes de compra` > Pantalla de `Recibir Mercancía`.  
- **Descripción:** Al recibir mercancía de una orden de compra, el usuario puede digitar una cantidad superior a la que se solicitó al proveedor (ej. 50 unidades cuando la orden fue de 10). El sistema acepta el valor y suma las 50 unidades al inventario sin solicitar una confirmación especial de sobre-recepción.  
- **Recomendación:** Bloquear o solicitar autorización de supervisor si la cantidad digitada supera la cantidad pendiente de la orden.

### Hallazgo 3: Inputs de Costo y Precio sin Restricción Estricta de Negativos
- **Severidad:** Baja  
- **Ubicación en Pantalla:** Menú Lateral > `Productos e Inventario` > `Productos y Servicios` > Formulario de Artículo.  
- **Descripción:** Los campos de precio y costo permiten escribir números con signo negativo en algunos navegadores antes de validar el formulario.  
- **Recomendación:** Forzar el límite `min="0.00"` en las casillas numéricas del formulario.

### Hallazgo 4: Manejo Visual de Stock Insuficiente en Transferencias de Múltiples Líneas
- **Severidad:** Media  
- **Ubicación en Pantalla:** Menú Lateral > `Productos e Inventario` > `Transferencias` > Botón de fila `Aprobar`.  
- **Descripción:** Si una solicitud de traslado contiene 3 productos diferentes y el segundo producto no cuenta con existencias suficientes en el almacén de origen al momento de presionar "Aprobar", la operación se interrumpe y muestra un mensaje de error, pero el usuario no cuenta con un informe detallado en pantalla de qué producto específico originó la falta de stock.  
- **Recomendación:** Mostrar un mensaje detallado indicando: *"No se pudo aprobar la transferencia: El artículo [Nombre del Artículo] solo tiene X unidades disponibles en origen."*.

---

## 9. Checklist de Certificación de Salida a Producción (Go / No-Go)

El analista de QA y el responsable del área operativa deben verificar y firmar cada uno de los siguientes controles directamente en la interfaz de usuario antes de certificar el módulo para su uso productivo:

| No. | Control Crítico de Certificación en UI | Criterio de Aprobación Visible en Pantalla | Estado (Cumple / No Cumple) |
|:---:|---|---|:---:|
| **1** | **Aislamiento de Empresas** | Al cambiar de empresa en el selector superior, las existencias y almacenes corresponden estrictamente a la empresa seleccionada. | `[  ]` |
| **2** | **Segregación Sandbox / Prod** | El banner de Sandbox identifica claramente el entorno de pruebas sin mezclar datos con la operación real. | `[  ]` |
| **3** | **Cuadratura del Kardex** | En la pantalla de Kardex, la ecuación `Saldo Inicial + Entradas - Salidas = Saldo Final` cuadra exactamente al centavo. | `[  ]` |
| **4** | **Consumo Cronológico FIFO** | Las salidas reflejan sistemáticamente el costo de la capa de entrada más antigua en la tabla del Kardex. | `[  ]` |
| **5** | **Bloqueo de Venta sin Stock** | Ninguna factura electrónica puede ser emitida si la cantidad supera la existencia del almacén seleccionado. | `[  ]` |
| **6** | **Facturas en Borrador Inactivas** | Las facturas en Borrador no modifican los números de existencias en el Tablero de Inventario. | `[  ]` |
| **7** | **Reversión Visual por Anulaciones** | Al anular una factura e-CF, las unidades regresan de forma inmediata y automática al almacén de origen. | `[  ]` |
| **8** | **Generación de Asientos Contables** | Las recepciones, ventas y ajustes generan sus asientos automáticos en la pantalla de Entradas de Diario. | `[  ]` |
| **9** | **Idempotencia y Anti-duplicidad** | Doble clic o reintentos no duplican movimientos ni asientos contables en el sistema. | `[  ]` |
| **10** | **Trazabilidad en Pantalla** | La tabla de movimientos registra fecha, usuario responsable, motivo claro y documento asociado. | `[  ]` |
| **11** | **Descarga de Reportes Operativos** | Las exportaciones a Excel (.xlsx) y PDF se generan de forma instantánea con diseño y cifras legibles. | `[  ]` |
| **12** | **Resolución de Bloqueos Críticos** | Los hallazgos con severidad Alta o Crítica cuentan con procedimiento de control operativo validado. | `[  ]` |

---

### Dictamen Final de Certificación QA

- **Resultado Global de la Evaluación:** `[  ] APROBADO PARA PRODUCCIÓN  |  [  ] RECHAZADO / BLOQUEADO`  
- **Evaluador de QA / Auditor:** __________________________________________________  
- **Firma de Aprobación:** _____________________________________________________  
- **Fecha de Dictamen:** ______ / ______ / 2026  
