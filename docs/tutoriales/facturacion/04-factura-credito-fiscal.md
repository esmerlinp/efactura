# Tutorial: Crear una factura electrónica de Crédito Fiscal (E31)

La factura de Crédito Fiscal (E31) se usa cuando tu cliente tiene un RNC o
cédula y puede utilizar el crédito del ITBIS.

## Crear la factura

1. En el menú lateral, abre **Ingresos** y haz clic en **"Facturas de Venta"**.
2. Haz clic en el botón **"+ Documento"**.
3. En el selector de tipo de documento, elige **"E31 — Factura de Crédito
   Fiscal"**.
   *Nota: si seleccionas un cliente con RNC, el sistema suele elegir E31 por
   ti.*

## Seleccionar el cliente

1. En el campo **Cliente**, escribe el nombre, RNC o correo y elige al cliente
   de la lista. Si no existe, haz clic en **"+ Nuevo"** para registrarlo.
2. El campo **RNC / Cédula** es **obligatorio** para este tipo de factura. El
   sistema lo valida en vivo contra la DGII:
   - *"⚠️ Para Crédito Fiscal (E31) se requiere un RNC de 9 dígitos o Cédula de
     11 dígitos"* si está incompleto.
   - *"✅ RNC Registrado"* cuando es válido. **No podrás emitir** hasta que el
     RNC sea válido.

## Agregar productos o servicios

1. En la tabla, haz clic en **"Agregar línea"**.
2. Busca y selecciona el producto o servicio. Se llenan automáticamente el
   precio y el ITBIS.
3. Ajusta la **Cantidad** y el **Precio** si es necesario. Los subtotales y el
   total se recalculan solos.

## Fechas y condiciones

1. Define la **Fecha de emisión** y la **Fecha de vencimiento**.
2. Elige la **Condición**: Contado o Crédito. Si es Crédito, configura las
   cuotas y el acuerdo de pago.

## Emitir la factura

1. Revisa el resumen de **Totales** (Subtotal, ITBIS, Total).
2. Opcional: haz clic en **"Vista Previa"** para ver el PDF.
3. Haz clic en **"Emitir Documento"**.

Verás el mensaje *"¡Comprobante emitido con éxito!"* con el número e-NCF
asignado.

## Consejos

- Si aún no estás listo, usa **"Guardar Borrador"** y emite más tarde.
- Si la DGII rechaza el documento, el estado cambiará a **"Rechazado DGII"** y
  verás el motivo.
