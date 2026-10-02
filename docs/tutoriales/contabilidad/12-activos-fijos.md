# Tutorial: Activos fijos

Registra tus activos fijos y ejecuta su depreciación (método lineal) generando
asientos contables automáticos.

## Registrar un activo

1. En el menú lateral, abre **Contabilidad → Activos Fijos → Nuevo Activo**.
2. En **Información General**, completa:
   - **Nombre del activo**.
   - **Tipo** (Tangible / Intangible) y **Categoría** (terreno, edificio,
     mobiliario, computación, vehículo, etc.).
   - **Cuenta contable del activo**, **de depreciación acumulada** y **de gasto
     por depreciación**.
3. En **Datos de Adquisición y Depreciación**, indica:
   - **Fecha de compra** y **Costo de adquisición**.
   - **Valor residual** y **Vida útil (meses)**.
   - **Período de depreciación** (Mensual / Anual).
   - Proveedor, ubicación y responsable (opcional).
4. Haz clic en **"Guardar Activo"**.

## Depreciar un activo

1. Abre el activo desde el listado.
2. Haz clic en **"Registrar Depreciación"**.
3. Indica los **Períodos (meses)** y haz clic en **"Depreciar"**.

Se genera un asiento de depreciación automático (gasto vs. depreciación
acumulada). El panel muestra costo, valor residual, método (Lineal), depreciación
acumulada, valor actual y el % depreciado.

## Dar de baja

1. Abre el activo y haz clic en **"Dar de Baja"**.
2. Indica **Fecha de baja**, **Valor de venta/desecho** y **Motivo** (Venta,
   Donación, Pérdida, Retiro).
3. Haz clic en **"Confirmar Baja"**.

## Consejos

- La depreciación se ejecuta también automáticamente (job diario) para los
  activos con fecha de depreciación vencida.
- Verifica el ítem **"Ejecutar depreciación de activos fijos"** en el checklist
  de cierre mensual.
