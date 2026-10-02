# Tutorial: Entradas de diario

Las entradas de diario (asientos contables) registran los movimientos manuales.
Muchas entradas se generan automáticamente (facturas, gastos, nómina,
depreciación), pero aquí puedes crear las tuyas.

## Crear una entrada

1. En el menú lateral, abre **Contabilidad → Registros Contables → Entradas de
   Diario**.
2. Haz clic en **"Nueva Entrada"**.
3. En **Encabezado**, define:
   - **Fecha**.
   - **Prefijo**: ED (Entrada de Diario), SI (Saldo Inicial), AJ (Ajuste) o DP
     (Depreciación).
   - **Tipo de entrada** (por defecto "Estándar").
   - **Concepto / Descripción** (obligatorio).
4. En **"Movimientos (Débito = Crédito)"**, haz clic en **"Agregar línea"** y
   por cada línea:
   - Elige la **Cuenta Contable**.
   - Escribe la **Descripción**.
   - Indica el **Débito** o el **Crédito**.
5. Verifica que el indicador muestre **"Balanceado"** y la **Diferencia** sea
   0.00.
6. Haz clic en **"Guardar Entrada"**.

## Gestionar entradas

Desde el listado puedes filtrar por fecha, tipo y estado, y usar el menú (⋮):

- **"Ver Detalle"** — abre la entrada.
- **"Clonar"** — crea una copia con número nuevo.
- **"Anular"** — anula la entrada (irreversible).

## Anular una entrada

1. Haz clic en **"Anular"** (o **"Anular Esta Entrada"** en el detalle).
2. Escribe el **Motivo de anulación**.
3. Haz clic en **"Confirmar Anulación"** o **"Anular"**.

La entrada queda en estado **Anulada** y se excluye de reportes y saldos.

## Puntos a tener en cuenta

- Los asientos no se pueden **eliminar**, solo **anular**.
- El período fiscal debe estar **abierto** para registrar la entrada.
- Las entradas automáticas muestran su **Tipo** y una **Referencia** al
  documento de origen.
