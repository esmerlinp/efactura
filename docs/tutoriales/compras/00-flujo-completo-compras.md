# Tutorial: Flujo completo de compras (orden de compra → recepción → factura → pago)

Este es un recorrido completo del ciclo de compras, de principio a fin, con
**un solo proveedor** y **un solo producto**. Sirve como prueba de humo
(smoke test) para confirmar que todo el ciclo funciona: proveedor → orden de
compra → aprobación → recepción de mercancía → factura de proveedor → cuentas
por pagar → pago.

Si buscas el detalle de cada pantalla por separado, consulta los demás
tutoriales de esta carpeta (`01` a `09`).

## Antes de empezar

- El módulo **Compras y Proveedores (CxP & Compras)** debe estar activo.
- Permisos necesarios según el paso:
  - Órdenes de compra: `canExpenses`.
  - Facturas de proveedor y CxP: `canManagePurchaseCXP`.
  - Recepción de mercancía: `canManageInventory` (módulo Inventario).
- Recomendado: hacer la prueba en **sandbox** para no afectar tus datos reales.

## Caso de prueba

| Dato | Valor |
| --- | --- |
| Proveedor | *Distribuidora Demo, SRL* — RNC `101001011` |
| Producto | *Producto Demo* (**Bien / Producto Físico**) |
- Cantidad comprada: `10`
- Costo unitario: `RD$ 100.00`
- Tasa de ITBIS: Gravado 18%
- Almacén de destino: el **Almacén por Defecto**

> Solo los artículos **Bien / Producto Físico** entran al inventario. Si la
> partida es un **Servicio**, la orden y la factura funcionan igual, pero la
> recepción no mueve stock.

---

## Paso 0 — Crear el proveedor (opcional)

Si ya tienes el proveedor, sáltate este paso.

1. Abre **Compras y Proveedores → Proveedores**.
2. Haz clic en **"Nuevo Proveedor"**.
- Completa RNC/Razón Social, tipo de comprobante y condiciones de pago.
- Haz clic en **"Guardar Proveedor"**.

Detalle en [Crear un proveedor](01-crear-proveedor.md).

---

## Paso 1 — Crear la orden de compra

1. Abre **Compras y Proveedores → Órdenes de compra**.
2. Haz clic en **"Nueva Orden"**.
3. Completa el encabezado:
   - **OC #**: *(auto-generado)*.
   - **Estado**: *Borrador* (solo lectura al crear).
   - **Fecha de Orden** y **Fecha Esperada de Entrega**.
   - **Proveedor**: búscalo por nombre o RNC (opcional; puedes escribirlo a mano).
   - **Términos de Pago**, **Moneda** / **Tasa de Cambio** y **Proyecto** (opcional).
4. En **Partidas**, usa **"Añadir Partida"** y agrega:
   - Descripción = *Producto Demo*, Cantidad = `10`, Precio Unitario = `100.00`,
     Tasa de ITBIS = Gravado 18%.
5. Opcional: completa **Notas** (visibles para el proveedor) y **Notas Internas**.
6. Haz clic en **"Guardar Orden de Compra"**.

> La orden de compra es un documento de **control**: por sí sola **no mueve
> inventario** ni genera CxP. Eso ocurre al recibir y al facturar.

Detalle en [Órdenes de compra](04-ordenes-de-compra.md).

---

## Paso 2 — Aprobar la orden

1. Abre la orden y haz clic en **"Aprobar"**.

Según tu flujo de aprobaciones, la orden puede quedar primero en
*Pendiente de Aprobación* y requerir el visto bueno de un autorizador.

Detalle en [Workflows y aprobaciones](03-workflow-aprobaciones.md).

> Solo las órdenes en **Borrador** o **Pendiente** se pueden aprobar o editar.
> Una orden ya **Recibida** o **Cancelada** no admite más cambios de estado.

---

## Paso 3 — Recibir la mercancía (mueve el inventario)

1. En el detalle de la orden **Aprobada**, haz clic en **"Recibir Mercancía"**
   (o entra por **Productos e Inventario → Recepciones de Mercancía**).
2. En la pantalla **"Recibir &lt;OC#&gt;"**, revisa:
   - **Datos de la Recepción**: número de recepción, fecha y **Almacén de
     Destino**.
   - **Partidas a Recibir**: lo ordenado, lo recibido previamente y la
     **Cantidad a Recibir Ahora**.
3. Confirma el **Ítem del Catálogo** de cada partida (obligatorio para afectar
   inventario) y ajusta las cantidades.
4. Haz clic en **"Confirmar Recepción"**.

**Resultado:**

- El stock se suma al **Almacén de Destino**.
- La orden pasa a **Rec. Parcial** o **Recibida** según lo recibido.

> Puedes recibir en varias veces (recepción parcial). No podrás recibir más de
> lo ordenado. El botón antiguo de "recibir" de la orden (sin pasar por
> Recepciones de Mercancía) **no mueve el stock**.

Detalle en [Recepciones de mercancía](../inventario/06-recepciones-mercancia.md).

---

## Paso 4 — Verificar el inventario

1. Abre **Productos e Inventario → Tablero de Inventario**: *Producto Demo*
   debe mostrar `10` de existencia.
2. Abre **Productos e Inventario → Kárdex Valorizado** y filtra por *Producto
   Demo*: verás el movimiento de **entrada** con su costo (FIFO).

---

## Paso 5 — Registrar la factura de proveedor

1. En el detalle de la orden recibida, haz clic en **"Registrar Factura
   Proveedor"** (o crea una factura directa en **Compras y Proveedores →
   Facturas de proveedores → "Nueva Factura de Compra"**).
2. Completa:
   - Proveedor, **NCF** y fechas.
   - **Partidas** con las cantidades recibidas.
   - **Estado del Pago**: *Pagado (Contado)* o *Pendiente (Crédito / CxP)*.
   - Cuenta bancaria/efectivo si es al contado.
   - Si aplica, el modal **"Retenciones, Descuentos y Recargos"** (ISR / ITBIS).
3. Haz clic en **"Registrar Factura de Compra"**.

**Resultado:**

- Si el pago es **Pendiente**, la factura alimenta tus **cuentas por pagar
  (CxP)**.
- La factura **no** vuelve a mover inventario: la entrada ya la hizo la
  recepción del Paso 3.

Detalle en [Facturas de proveedor (CxP)](05-facturas-de-proveedor.md).

> Registrar la factura **no** descuenta ni suma stock. Evita el doble conteo
> recibiendo en el Paso 3 y facturando aquí una sola vez.

---

## Paso 6 — Consultar el CxP y pagar

1. Abre **Compras y Proveedores → Facturas de proveedores → Estado de cuentas
   por pagar**.
2. Filtra por **tipo** y **estado**; verás el saldo pendiente por proveedor.
3. Para abonar o pagar: en el listado de facturas abre la factura del proveedor
   y usa **"Registrar Pago"** (sección *Pagos*), indicando monto, método y
   referencia. Un pago mal registrado se puede revertir con **"Anular"**.

Detalle en [Estado de cuentas por pagar](09-estado-cuentas-por-pagar.md) y
[Bancos y cajas](../finanzas/05-bancos-y-cajas.md).

---

## Paso 7 — Notas de crédito en compras (opcional)

Si hubo un error o una devolución, crea una **nota de crédito en compras** para
disminuir el saldo por pagar al proveedor.

Detalle en [Notas de crédito en compras](06-notas-de-credito-en-compras.md).

---

## Paso 8 — Reportes

- **Reporte 606 (Compras y Gastos)**: en **Contabilidad → Reporte 606**. La
  factura de compra del Paso 5 debe aparecer.
- **Estado de cuentas por pagar**: consolidado de compras y gastos con su saldo.

Detalle en [Reporte 606 (Compras y Gastos)](../contabilidad/18-reporte-606.md).

---

## Resultado esperado

Tras completar los pasos con el caso de prueba:

- Orden de compra: **Borrador → Aprobada → Recibida**.
- Inventario: entrada de `10` unidades con su costo FIFO.
- Factura de proveedor registrada con su **NCF**; si es a crédito, aparece en el
  **CxP** con saldo pendiente.
- El pago (total o parcial) actualiza el saldo de CxP.
- La compra aparece en el **Reporte 606**.

---

## Estados de una orden de compra

**Borrador → Pendiente → Aprobada → Rec. Parcial → Recibida**, o **Cancelada /
Rechazada**.

- Solo se edita/aprueba en **Borrador** o **Pendiente**.
- **Recibida** y **Cancelada** son estados finales.
- No se puede eliminar una orden que ya tenga **recepciones** o **facturas**
  asociadas.

## Consejos y advertencias

- La **recepción de mercancía** es lo que mueve inventario (no la orden ni la
  factura).
- Solo los **Bien / Producto Físico** afectan inventario.
- El **Ítem del Catálogo es obligatorio** por partida para poder recibir.
- No se puede recibir más de lo ordenado; puedes recibir por partes.
- No se puede eliminar una orden con recepciones o facturas asociadas.
- Las operaciones son **idempotentes**: un doble clic no duplica el movimiento.

## Tutoriales relacionados

1. [Crear un proveedor](01-crear-proveedor.md)
2. [Workflows y aprobaciones](03-workflow-aprobaciones.md)
3. [Órdenes de compra](04-ordenes-de-compra.md)
4. [Recepciones de mercancía](../inventario/06-recepciones-mercancia.md)
5. [Facturas de proveedor (CxP)](05-facturas-de-proveedor.md)
6. [Estado de cuentas por pagar](09-estado-cuentas-por-pagar.md)
7. [Flujo completo de inventario (end-to-end)](../inventario/00-flujo-completo-inventario.md)
