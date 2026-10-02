# Tutorial: Crear una factura electrónica de Consumidor Final (E32)

La factura de Consumo (E32) se usa para ventas al público general, sin un RNC
de cliente.

## Crear la factura

1. En el menú lateral, abre **Ingresos** y haz clic en **"Facturas de Venta"**.
2. Haz clic en el botón **"+ Documento"**.
3. En el selector de tipo de documento, elige **"E32 — Factura de Consumo"**.

## Cliente

- Al elegir E32, el sistema asigna automáticamente **"Consumidor Final"** y
  bloquea el campo RNC (se envía `000000000` a la DGII).
- No necesitas seleccionar ni registrar ningún cliente.

## Agregar productos o servicios

1. En la tabla, haz clic en **"Agregar línea"**.
2. Busca y selecciona el producto o servicio. Se llenan automáticamente el
   precio y el ITBIS.
3. Ajusta la **Cantidad** y el **Precio** si es necesario. Los totales se
   recalculan solos.

## Fechas y condiciones

1. Define la **Fecha de emisión** y la **Fecha de vencimiento**.
2. Elige la **Condición**: Contado o Crédito.

## Emitir la factura

1. Revisa el resumen de **Totales** (Subtotal, ITBIS, Total).
2. Opcional: haz clic en **"Vista Previa"** para ver el PDF.
3. Haz clic en **"Emitir Documento"**.

Verás el mensaje *"¡Comprobante emitido con éxito!"* con el número e-NCF
asignado.

## Puntos a tener en cuenta

- Si el total es **menor a RD$250,000**, la emisión es simplificada (no se
  requiere RNC).
- Si el total es **RD$250,000 o más**, la DGII exige un RNC/Cédula válido; el
  sistema te pedirá esos datos antes de emitir.
- Si aún no estás listo, usa **"Guardar Borrador"** y emite más tarde.
