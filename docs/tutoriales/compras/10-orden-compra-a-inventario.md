# Tutorial: De la orden de compra a la entrada al inventario

Este tutorial recorre el tramo completo de una compra, desde que creas la
**orden de compra** hasta que la mercancía queda **registrada en el inventario**:
crear → aprobar → recibir → verificar el stock.

Si buscas el ciclo completo (factura de proveedor, CxP y pago), consulta
[Flujo completo de compras](00-flujo-completo-compras.md).

## Antes de empezar

- Los módulos **CxP, Proveedores & Compras** e **Inventario** deben estar
  activos.
- Permisos necesarios:
  - Órdenes de compra: `canManagePurchaseOrders`.
  - Recepción de mercancía: `canInventoryReceipts`.
- Recomendado: hacer la prueba en **sandbox** para no afectar tus datos reales.

## Caso de prueba

| Dato | Valor |
| --- | --- |
| Proveedor | *Distribuidora Demo, SRL* — RNC `101001011` |
| Producto | *Producto Demo* (**Bien / Producto Físico**) |
| Cantidad comprada | `10` |
| Costo unitario | `RD$ 100.00` |
| Tasa de ITBIS | Gravado 18% |
| Almacén de destino | el **Almacén por Defecto** |

> Solo las partidas **inventariables** (Bien / Producto Físico) entran al
> inventario. Las de **Servicio** se muestran con el badge *"Servicio / No
> inventariable"* y no generan movimiento de stock.

---

## Paso 1 — Crear la orden de compra

1. En el menú lateral, abre **Compras y Proveedores → Órdenes de compra**.
2. Haz clic en **"+ Nueva Orden"**.
3. Completa el encabezado:
   - **OC #**: *auto-generado* con el formato `OC-AAAA-NNNN` (secuencial por año).
   - **Proveedor**: búscalo por nombre o RNC.
   - **Fecha de Orden**, **Fecha Esperada**, **Almacén Sugerido de Destino**,
     **Términos de Pago**, **Moneda** / **Tasa de Cambio**.
4. En la sección **Productos / Servicios**, haz clic en **"Añadir Partida"** y
   escribe en **Descripción**: el buscador sugiere los productos de tu
   catálogo; al elegirlo se completan solos la unidad, el precio y los flags de
   inventario/lotes. Ajusta cantidad, precio, descuento y tasa de ITBIS.
5. Haz clic en **"Guardar Orden de Compra"** (o **"Guardar y Nuevo"**).

La orden queda en estado **Borrador**.

> La orden de compra es un documento de **control**: por sí sola **no mueve
> inventario**. Eso ocurre únicamente en el Paso 3 (recepción).

---

## Paso 2 — Aprobar la orden

1. Abre la orden desde el listado.
2. Haz clic en **"Aprobar"**.

Si tu empresa tiene una regla de workflow activa para órdenes de compra, la
orden queda primero en **Pendiente Aprobación** y debe ser aprobada por un
autorizador; en caso contrario pasa directamente de **Borrador** a
**Aprobada**.

Detalle en [Workflows y aprobaciones](03-workflow-aprobaciones.md).

> Solo en **Borrador**, **Pendiente Aprobación** o **Rechazada** verás los
> botones **"Editar"** y **"Eliminar"**. La orden **"Aprobada"** ya no se
> edita; puedes **"Cancelar"** mientras no haya mercancía recibida.

---

## Paso 3 — Recibir la mercancía (entrada al inventario)

1. Con la orden en **Aprobada** (o **Recibida Parcial**), haz clic en
   **"Recibir Mercancía"** (parte desde el detalle de la orden).
2. En la pantalla **"Recibir \<OC\>"** (p. ej. *"Recibir OC-2026-0001"*),
   revisa **Datos de la Recepción**:
   - **Recepción #**: *auto-generado* con el formato `RC-AAAA-NNNN`.
   - **Fecha** y **Almacén de Destino** (obligatorio).
3. En **Partidas a Recibir**, por cada partida:
   - Verifica **Ordenado**, **Recibido Prev.** y escribe la cantidad a
     **Recibir Ahora**.
   - Confirma el **Ítem del Catálogo** (obligatorio para las partidas
     inventariables).
   - Si el producto controla **lotes**, indica el lote nuevo o selecciona uno
     existente.
4. Haz clic en **"Confirmar Recepción"**.

**Resultado:**

- El stock se suma al **Almacén de Destino** y aparece el movimiento de
  **entrada** en el kárdex.
- La orden pasa a **Recibida Parcial** o **Recibida Completa** según lo
  recibido.

> No podrás recibir **más de lo ordenado**: el sistema valida por partida que
> *recibido previo + nuevo ≤ ordenado*. Puedes recibir en varias veces
> (recepción parcial).

> El botón de recibir dentro de la orden que no abre la pantalla de
> Recepciones de Mercancía está **deshabilitado**: toda entrada real de
> inventario debe pasar por **"Recibir Mercancía"** / Recepciones.

---

## Paso 4 — Verificar el inventario

1. Abre **Productos e Inventario → Tablero de Inventario**: *Producto Demo*
   debe mostrar `10` de existencia.
2. Abre **Productos e Inventario → Kardex Valorizado** y filtra por el
   producto: verás el movimiento de **entrada** con su costo de compra.
3. En el detalle de la orden, la sección de **Recepciones** lista la recepción
   creada; desde ahí puedes ver su detalle (totales, ítems de catálogo y
   almacén).

---

## Paso 5 — Recepción parcial y cierre

1. Si recibiste menos de lo ordenado, la orden queda en **Recibida Parcial** y
   el botón **"Recibir Mercancía"** sigue disponible para el resto.
2. Cuando todas las partidas estén completas, la orden pasa a **Recibida
   Completa** (estado final junto con **Cancelada**).

> La **factura de proveedor** (siguiente paso del ciclo) **no** mueve
> inventario: la entrada ya la hizo la recepción. Además, solo se pueden
> facturar órdenes con recepción parcial o completa. Detalle en
> [Facturas de proveedor (CxP)](05-facturas-de-proveedor.md).

---

## Estados de una orden de compra

**Borrador → Pendiente Aprobación → Aprobada → Recibida Parcial → Recibida
Completa**, o **Rechazada / Cancelada**.

- Solo se edita/elimina en **Borrador**, **Pendiente Aprobación** o
  **Rechazada**.
- **Recibida Completa** y **Cancelada** son estados finales.
- No se puede eliminar una orden que tenga **recepciones** o **facturas**
  asociadas, ni una orden con mercancía recibida.

## Errores comunes

| Mensaje | Causa |
| --- | --- |
| *"Solo se pueden recibir órdenes aprobadas o con recepción parcial."* | La orden está en Borrador u otro estado. |
| *"Cantidad excede la orden de compra..."* | Intentas recibir más de lo pendiente. |
| *"La partida '…' no tiene ítem de catálogo asociado."* | Falta el **Ítem del Catálogo** en una partida inventariable. |
| *"Debe seleccionar un almacén de destino."* | No elegiste el almacén (obligatorio si hay partidas físicas). |
| *"…requiere control por lotes..."* | El producto controla lotes y no indicaste el lote. |
| *"Debe indicar al menos una partida con cantidad mayor a 0."* | Todas las cantidades a recibir son 0. |

## Consejos

- La **recepción de mercancía** es lo que mueve inventario (no la orden ni la
  factura).
- Verifica las cantidades reales antes de **"Confirmar Recepción"**; la
  recepción no tiene pantalla de anulación.
- El **Ítem del Catálogo** es obligatorio por partida para poder recibir.
- El proceso es **transaccional**: si el movimiento de stock falla a mitad de
  camino, se revierte todo (recepción incluida) y no queda stock "fantasma".

## Tutoriales relacionados

1. [Flujo completo de compras (end-to-end)](00-flujo-completo-compras.md)
2. [Workflows y aprobaciones](03-workflow-aprobaciones.md)
3. [Órdenes de compra](04-ordenes-de-compra.md)
4. [Recepciones de mercancía](../inventario/06-recepciones-mercancia.md)
5. [Facturas de proveedor (CxP)](05-facturas-de-proveedor.md)
6. [Flujo completo de inventario (end-to-end)](../inventario/00-flujo-completo-inventario.md)
