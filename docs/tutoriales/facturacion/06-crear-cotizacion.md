# Tutorial: Crear una cotización y convertirla a factura

Una cotización te permite enviar un presupuesto a tu cliente y, cuando lo
apruebe, convertirlo en factura con un solo clic.

## Crear una cotización

1. En el menú lateral, abre **Ventas** y haz clic en **"Cotizaciones"**.
2. Haz clic en **"Nueva Cotización"** y elige:
   - **"Cotización Rápida"** — formulario simple y directo.
   - **"Cotización Personalizada"** — con IA, cronograma, términos y vista
     previa.
3. Completa:
   - **Cliente** (usa **"+ Nuevo"** si no existe).
   - **RNC / Cédula**, **Fecha de emisión** y **Fecha de vencimiento**.
   - **Condición**: Contado o Crédito.
4. En **Productos y servicios**, haz clic en **"Agregar línea"** y añade los
   productos, cantidades y precios.
5. Haz clic en **"Guardar Borrador"**.

## Enviar y aprobar

1. Abre la cotización desde el listado.
2. Usa **"Enviar Cotización al Cliente"** para que la revise y acepte.
3. Cuando el cliente apruebe, puedes usar **"Aprobar Cotización"** (o esperar la
   aprobación del cliente).

## Convertir a factura

1. Abre la cotización aprobada.
2. Busca la tarjeta **"Convertir a Factura Fiscal"**.
3. Elige el tipo de comprobante según el cliente:
   - **"Emitir como Consumo (E32)"** — cliente final.
   - **"Emitir como Crédito Fiscal (E31)"** — cliente con RNC.
   - Otras opciones: Gubernamental (E45), Exportación (E46), etc.
4. Confirma en la ventana **"Convertir Cotización"** con **"Sí, Convertir"**.

Verás el mensaje *"¡Cotización convertida exitosamente!"* con el número de
documento asignado. La cotización pasará al estado **"Facturada"** y la nueva
factura quedará lista para firmar.

## Puntos a tener en cuenta

- **E31** siempre requiere RNC/Cédula del cliente.
- **E32** requiere RNC solo si el monto supera RD$250,000.
- Puedes crear una copia de una cotización desde su menú de acciones.
