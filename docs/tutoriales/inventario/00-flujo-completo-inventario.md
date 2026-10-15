# Tutorial: Flujo completo de inventario (end-to-end)

Este es un recorrido completo del módulo de inventario, de principio a fin, con
**un solo producto** y los almacenes por defecto. Sirve como prueba de humo
(smoke test) para confirmar que todo el ciclo funciona: crear producto → entrada
→ salida → transferencia → conteo físico → reportes.

Si buscas el detalle de cada pantalla por separado, consulta los demás
tutoriales de esta carpeta (`01` a `08`).

## Antes de empezar

- El módulo **Inventario** debe estar activo y tu usuario debe tener el permiso
  de gestión de inventario.
- Para el catálogo necesitas acceso a productos (permiso de clientes/catálogo).
- Recomendado: haz la prueba en **modo de pruebas (sandbox)** para no afectar el
  inventario real.

## Caso de prueba sugerido

Usaremos un único producto:

| Campo | Valor |
|---|---|
| Nombre | Producto Demo |
| Tipo | **Bien / Producto Físico** |
| Precio de venta | RD$ 180.00 |
| Precio de costo | RD$ 100.00 |
| Cantidad de la prueba | 10 |

> Importante: solo los artículos marcados como **Bien / Producto Físico** tienen
> control de almacén. Los **Servicio** no mueven inventario.

---

## Paso 0 — Almacén de trabajo

Si nunca has creado almacenes, el sistema crea automáticamente un **"Almacén
Principal"** al abrir el tablero. Puedes usar ese y saltar al Paso 1.

Para crear uno propio:

1. En el menú lateral, abre **Productos e Inventario → Tablero de Inventario**.
2. Haz clic en el botón **"Almacenes"**.
3. Haz clic en **"Nuevo Almacén"**.
4. Completa **Nombre** (obligatorio) y **Sucursal** (obligatorio). Opcional:
   descripción y dirección.
5. Haz clic en **"Guardar"**.

> No puedes eliminar el último almacén activo del sistema.

---

## Paso 1 — Crear el producto

1. En el menú lateral, abre **Productos e Inventario → Productos y Servicios**.
2. Haz clic en **"Nuevo Artículo"**.
3. Completa el formulario:
   - **Identificación e Info General**: Tipo de Elemento = **Bien / Producto
     Físico**, Nombre = *Producto Demo*.
   - **Precios e Impuestos**: Precio de Venta = `180.00`, Precio de Costo =
     `100.00`, Tasa de ITBIS = Gravado 18%.
   - **Inventario y Logística**: Unidad de Medida = Unidad. Opcional: Stock
     Mínimo de Alerta, Stock Máximo y Ubicación Física.
4. Haz clic en **"Registrar Artículo"**.

Verás el mensaje *"Artículo añadido al catálogo de ventas"*. El producto queda
con existencia `0` en todos los almacenes.

---

## Paso 2 — Registrar una entrada (abastecimiento)

Para la prueba más simple no necesitas orden de compra; puedes cargar stock
manualmente.

1. Abre **Productos e Inventario → Tablero de Inventario**.
2. Haz clic en el botón **"Ajuste / Transacción"**.
3. En la pantalla **"Nueva Transacción de Inventario"**, completa:
   - **Selecciona el Producto Físico**: *Producto Demo*.
   - **Tipo de operación**: `ENTRADA` (aparece el **Almacén de Destino**).
   - **Motivo**: *Compra a Proveedor / Reabastecimiento*.
   - **Almacén de Destino**: el almacén del Paso 0.
   - **Cantidad**: `10`.
   - Notas: opcional.
4. Haz clic en **"Registrar Ajuste"**.

### Alternativa realista (con orden de compra)

1. **Compras y Proveedores → Órdenes de compra → Nueva**. Crea la orden con el
   producto y la cantidad.
2. Aprueba la orden y haz clic en **"Recibir Mercancía"**.
3. En la pantalla **"Recibir <OC#>"**, confirma el **Almacén de Destino** y la
   **Cantidad a Recibir Ahora**. Haz clic en **"Confirmar Recepción"**.

> Ojo: usar solo el botón de "recibir" de la orden de compra (sin pasar por
> Recepciones de Mercancía) **no mueve el stock**.

---

## Paso 3 — Verificar la entrada

1. Vuelve al **Tablero de Inventario**: el producto debe mostrar `10` en la
   columna de su almacén y `10` de **Existencia Total**.
2. Abre **Productos e Inventario → Kárdex Valorizado** y filtra por *Producto
   Demo*: verás el movimiento de **entrada** con su costo (FIFO).

---

## Paso 4 — Registrar una salida (venta)

Forma más realista, mediante facturación:

1. Abre **Ventas → Facturación Electrónica → "Nueva Factura"**.
2. En el costado, selecciona el **Almacén** de donde sale la mercancía.
3. Agrega una línea: *Producto Demo*, Cantidad = `4`.
4. Completa los datos del cliente y **emite** la factura.

Al emitirse, el stock del producto baja a `6` automáticamente.

> Una factura en estado **Borrador** no descuenta inventario; hay que emitirla.

Forma manual alternativa:

1. **Tablero de Inventario → "Ajuste / Transacción"**.
2. **Tipo de operación** = `SALIDA`, **Motivo** = *Venta Directa*, **Almacén
   Origen**, **Cantidad** = `4`. Haz clic en **"Registrar Ajuste"**.

> El sistema bloquea el stock negativo por defecto; no podrás sacar más de lo
> que existe.

---

## Paso 5 — Transferir entre almacenes

Requiere al menos dos almacenes (crea uno extra en el Paso 0 si hace falta).

1. Abre **Productos e Inventario → Transferencias**.
2. Haz clic en **"Nueva Transferencia"**.
3. Selecciona **Almacén Origen** y **Almacén Destino** (deben ser distintos).
4. En la tabla de productos, escribe la **Cantidad** a mover (por ejemplo `2`).
5. Haz clic en **"Solicitar Transferencia"**; queda en estado *Pendiente*.
6. En la lista de transferencias, haz clic en **"Aprobar"** para aplicar el
   movimiento (o **"Rechazar"** con un motivo).

El stock se descuenta del origen y se suma al destino.

---

## Paso 6 — Conteo físico (ajuste por diferencia)

1. Abre **Productos e Inventario → Conteos Físicos**.
2. Haz clic en **"Iniciar Conteo"** y elige el **Almacén a contar**.
3. En la pantalla del conteo, escribe la **Cantidad Contada** real de cada
   producto y observa la columna **Diferencia**.
4. Puedes **"Guardar Líneas"** y continuar después, o hacer clic en
   **"Finalizar Conteo"**.

Al finalizar, el sistema genera automáticamente los ajustes de entrada/salida
por las diferencias.

---

## Paso 7 — Reportes

- **Kárdex Valorizado** (`Productos e Inventario → Kárdex Valorizado`): filtros
  por producto, almacén y rango de fechas. Exporta a **Excel** o **PDF**.
- **Tablero de Inventario → "Exportar CSV"**: descarga el stock actual por
  almacén.
- **Alertas de Stock**: en el tablero y en la pantalla **Alertas**, productos por
  debajo del mínimo.

---

## Resultado esperado

Tras completar los pasos con el caso de prueba:

- Entrada de 10 → stock `10`.
- Venta/salida de 4 → stock `6`.
- Transferencia de 2 → origen `-2`, destino `+2`.
- Conteo físico → ajusta diferencias contra el stock esperado.

Cada movimiento queda registrado en el **Kárdex** con su costo FIFO.

---

## Consejos y advertencias

- Solo los **Bien / Producto Físico** participan en inventario.
- Emitir la factura es lo que descuenta stock; el borrador no.
- El stock negativo está bloqueado por defecto.
- Usa **Recepciones de Mercancía** (no el botón de recibir de la orden) para que
  la compra mueva inventario.
- Las operaciones son idempotentes: un doble clic no duplica el movimiento.

## Tutoriales relacionados

1. [Flujo completo de compras (end-to-end)](../compras/00-flujo-completo-compras.md)
2. [Tablero de inventario](01-tablero-inventario.md)
3. [Almacenes](02-almacenes.md)
4. [Transferencias entre almacenes](03-transferencias.md)
5. [Conteos físicos](04-conteos-fisicos.md)
6. [Ajustes de inventario y kárdex](05-ajustes-kardex.md)
7. [Recepciones de mercancía](06-recepciones-mercancia.md)
8. [Alertas de stock y reorden](07-alertas-stock.md)
9. [Lotes de inventario](08-lotes.md)
