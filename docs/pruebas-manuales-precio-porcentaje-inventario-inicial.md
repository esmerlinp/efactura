# Casos de Prueba Manuales — Precio por porcentaje e Inventario inicial por importación

> Ámbito: VykOne ERP · Módulo Productos e Inventario.
> Estado: para ejecución manual en **entorno sandbox** (nunca en producción en esta etapa).
> No se realizan despliegues, commits ni push como parte de esta fase.

---

## 0. Preparación del entorno

1. Iniciar sesión con un usuario con permisos `canManageCatalog` y `canManageInventory`
   (o equivalente de ajuste de inventario).
2. Activar el **modo sandbox**.
3. Seleccionar una empresa de prueba.
4. Verificar que existe al menos un almacén (Inventario → Almacenes). Si no hay, crear
   `Principal` (id sugerido `default-almacen-principal`).

---

## 1. Precio por porcentaje (formulario de producto)

### CP-1.1 — Crear producto por monto
1. Ir a Productos → Nuevo artículo.
2. En "Precios e Impuestos" seleccionar **Por monto**.
3. Costo `100.00`, Precio `150.00`.
4. Guardar.
- **Esperado:** se guarda con `price = 150.00`; en el listado se muestra RD$150.00.

### CP-1.2 — Crear producto por porcentaje (markup)
1. Nuevo artículo → seleccionar **Por porcentaje**.
2. Costo `100.00`, Incremento `10`.
- **Esperado en vivo:** el campo "Precio calculado" muestra `110.00` (readonly) y se
  actualiza al cambiar costo o porcentaje.

3. Guardar.
- **Esperado:** `price = 110.00`, `pricingMode = markup`, `markupPercentage = 10`.

### CP-1.3 — Verificar nota de markup vs margen
- **Esperado:** bajo el campo de porcentaje aparece el texto que aclara que es un
  **incremento sobre el costo**, no un margen sobre el precio de venta.

### CP-1.4 — Cambiar costo no altera el precio existente
1. Tomar el producto de CP-1.2 (costo 100, precio 110, markup 10).
2. Editar solo el costo a `200`.
3. Guardar (sin tocar el porcentaje; si aparece la opción de recálculo, NO recalc).
- **Esperado:** el precio se mantiene en `110.00` (no se recalcula automáticamente).

### CP-1.5 — Producto legacy (sin modalidad)
1. Ver un producto creado antes de esta funcionalidad (o crear uno por monto).
2. Editarlo.
- **Esperado:** la modalidad "Por monto" aparece seleccionada por defecto; no hay errores.

### CP-1.6 — Validaciones de porcentaje
1. Intentar porcentaje negativo (`-5`) en la UI.
- **Esperado:** el navegador bloquea (`min=0`) y/o el backend rechaza con error.

2. Por API (si aplica) enviar `pricingMode=markup` sin porcentaje.
- **Esperado:** error claro indicando que falta el porcentaje.

### CP-1.7 — Precio mayorista removido de la UI
1. Abrir el formulario de un artículo.
- **Esperado:** el campo "Precio al por Mayor (RD$)" **ya no aparece**.

---

## 2. Importación con precios (monto / porcentaje)

Descargar la plantilla en Productos → Importar → Descargar plantilla y verificar
que incluye las columnas: `tipo_precio` y `porcentaje` (y las de inventario del §4).

### CP-2.1 — Plantilla antigua (compatibilidad)
Subir un CSV con solo `name` y `price` (sin columnas nuevas).
- **Esperado:** se importa con precio fijo (modalidad "monto" implícita); sin errores.

### CP-2.2 — Importación con markup
CSV:

```csv
name;price;costPrice;pricingMode;markupPercentage
Camiseta Algodón;;100;PORCENTAJE;10
```

- **Esperado:** el producto se crea con `price = 110.00` y modalidad markup.

### CP-2.3 — Importación con monto
CSV:

```csv
name;price;costPrice;pricingMode;markupPercentage
Mouse USB;250;150;MONTO;
```

- **Esperado:** `price = 250.00`, modalidad monto.

### CP-2.4 — Error por fila y columna
CSV con una fila `PORCENTAJE` sin porcentaje, y otra con `costPrice` vacío:

```csv
name;price;costPrice;pricingMode;markupPercentage
A;;
;;;PORCENTAJE;10
```

- **Esperado:** el reporte muestra **fila y columna** del error (`costPrice`,
  `markupPercentage`) y no se crea un precio inconsistente.

### CP-2.5 — Precio y porcentaje simultáneos en markup
- **Esperado:** en modalidad `PORCENTAJE` se calcula desde el costo+porcentaje
  (el `price` de la fila se ignora en el cálculo).

---

## 3. Previsualización

### CP-3.1 — Resumen de previsualización
1. Subir un CSV con 10 filas (varias nuevas, 2 con `code` ya existente, 1 duplicado
   dentro del archivo, 1 con error).
2. Llegar al paso de previsualización.
- **Esperado:** se muestra cantidad de productos nuevos, existentes (a actualizar),
  duplicados y errores; **sin** escribir nada aún (verificar en el listado que no
  aparecieron productos nuevos).

### CP-3.2 — Previsualización no persiste
- **Esperado:** tras previsualizar, no hay movimientos de inventario ni productos
  nuevos en Firestore/catálogo.

---

## 4. Existencias iniciales

### CP-4.1 — Importación con existencia inicial
CSV (asumiendo un almacén `Principal` existente):

```csv
name;price;costPrice;pricingMode;markupPercentage;initialStock;warehouseId;initialUnitCost
Laptop Dell;45000;35000;MONTO;;10;Principal;35000
```

1. Previsualizar y confirmar.
- **Esperado:**
  - El producto se crea.
  - Se genera **1 movimiento** de inventario tipo `ENTRADA` con motivo `SALDO_INICIAL`.
  - El stock del producto en el almacén `Principal` es `10`.
  - El `totalStock` del producto es `10` (no se escribió directamente).

### CP-4.2 — Verificación en Kardex
1. Ir a Inventario → Kardex del producto importado.
- **Esperado:** aparece la entrada `SALDO_INICIAL` con cantidad 10 y costo 35000.

### CP-4.3 — Existencia inicial sin almacén
CSV con `initialStock=5` pero `warehouseId` vacío.
- **Esperado:** la fila se marca como error en la previsualización (columna
  `warehouseId`) y **no** se confirma.

### CP-4.4 — Almacén inexistente
CSV con `warehouseId=Bodega-Fantasma`.
- **Esperado:** error en confirmación ("Almacén no encontrado"); no se genera movimiento.

### CP-4.5 — Costo inicial distinto del costo de compra
`costPrice=100`, `initialUnitCost=90`, `initialStock=10`.
- **Esperado:** el movimiento se valora a `90` (no a 100). Verificar en Kardex/valoración.

### CP-4.6 — Costo inicial omiso (fallback)
`initialStock=10` sin `initialUnitCost`.
- **Esperado:** se valora con `costPrice` como fallback.

### CP-4.7 — Múltiples almacenes
Dos filas del mismo producto en almacenes distintos (si la plantilla lo permite por
fila) o dos productos en almacenes distintos.
- **Esperado:** un movimiento por fila, cada uno en su almacén correspondiente.

---

## 5. Confirmación, idempotencia y recuperación

### CP-5.1 — Confirmación explícita
- **Esperado:** los movimientos **solo** se generan tras una acción de confirmación
  explícita; la previsualización por sí sola no confirma.

### CP-5.2 — Reprocesar un lote confirmado
Intentar confirmar de nuevo el mismo lote.
- **Esperado:** el sistema rechaza ("ya fue confirmado") y **no** duplica existencias.

### CP-5.3 — Reimportar el mismo archivo (idempotencia)
Volver a importar/confirmar el mismo CSV con los mismos `code`.
- **Esperado:** no se duplican productos ni movimientos; el stock no aumenta dos veces.

### CP-5.4 — Recuperación de fallo parcial
1. Importar un CSV donde una fila falla (almacén inexistente) y las demás son válidas.
2. Confirmar.
- **Esperado:** las filas válidas se crean; la fila con error queda reportada y no se crea.
3. Corregir la fila y reintentar el mismo lote.
- **Esperado:** solo se procesa la fila corregida; las ya completadas se omiten.

---

## 6. Escenario de migración integral (2000 productos)

1. Preparar un CSV con 2,000 productos: `code`, `name`, `costPrice`, `pricingMode`
   (mezcla monto/markup), `price` o `markupPercentage`, `initialStock`, `warehouseId`,
   `initialUnitCost`.
2. Previsualizar y revisar el resumen (nuevos, existentes, movimientos, unidades, valor total).
3. Confirmar.
- **Esperado:**
  - El procesamiento termina con resumen correcto.
  - 2,000 productos y 2,000 movimientos `SALDO_INICIAL`.
  - El valor total del inventario inicial coincide con `sum(cantidad × costo)`.
  - Kardex y conciliación de inventario son consistentes.

---

## 7. Seguridad y permisos

### CP-7.1 — Usuario sin permiso de catálogo
- **Esperado:** no puede importar ni crear productos (403 o redirección a "restringido").

### CP-7.2 — Aislamiento entre empresas
- **Esperado:** los productos y movimientos se guardan solo en la empresa/entorno
  activos (sandbox vs producción no se mezclan).

### CP-7.3 — Trazabilidad del lote
1. Tras confirmar, revisar el detalle del lote (o la colección `product_import_batches`).
- **Esperado:** registra `createdBy`, `confirmedBy`, `createdAt`, `confirmedAt`,
  nombre de archivo y resumen.

---

## 8. Criterios de aceptación globales

- No se modifica el stock directamente; todo pasa por movimientos formales.
- Los precios por markup se calculan con aritmética decimal y redondeo a 2 decimales
  (ej. `100 × 1.075 = 107.50`).
- Las plantillas antiguas siguen funcionando.
- Los errores reportan fila y columna.
- La reimportación y los reintentos son idempotentes.
- La contabilidad/kardex/conciliación no quedan inconsistentes tras una importación.
