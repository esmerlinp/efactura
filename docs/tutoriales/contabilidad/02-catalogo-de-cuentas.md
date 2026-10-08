# Tutorial: Catálogo de cuentas

El catálogo de cuentas es tu plan de cuentas contable, organizado en una
estructura de árbol.

## Cómo entrar

1. En el menú lateral, abre **Finanzas → Contabilidad** y haz clic en **"Catálogo de
   Cuentas"**.

## Explorar el catálogo

- Usa **"Expandir todo"** / **"Contraer todo"** para abrir o cerrar el árbol.
- Filtra por nombre o código, grupo y tipo (**Control** / **Movimiento**).

## Agregar una cuenta

Las cuentas se crean como subcuentas de una cuenta padre:

1. En la fila de la cuenta padre, abre el menú (⋮) y haz clic en **"Agregar sub
   cuenta"**.
2. Completa:
   - **Nombre** (obligatorio) y **Código** (ej. `1.1.1.04`).
   - **Tipo de cuenta**: Cuenta de movimiento o Cuenta de control.
   - **Naturaleza**: Deudora o Acreedora.
   - **Descripción** y **Uso de la cuenta** (Bancos, CxC, Ventas, etc.).
   - **Ver saldo por terceros** (opcional).
3. Haz clic en **"Crear Cuenta"**.

## Editar o eliminar

- **Editar**: menú (⋮) → **"Editar"** → **"Guardar"**.
- **Eliminar**: menú (⋮) → **"Eliminar cuenta"**. Puedes elegir
  **"Reclasificar movimientos a"** otra cuenta (o dejar "No reclasificar").
- Las cuentas de **sistema** no se pueden editar ni eliminar.

## Ver movimientos y exportar

- **"Ver movimientos"** — detalle de movimientos y saldo de una cuenta.
- **"Exportar"** — descarga el catálogo en CSV (`catalogo_cuentas.csv`).

## Nota

El sistema usa 7 grupos de cuentas: Activos, Pasivos, Patrimonio, Ingresos,
Costos, Gastos y Cuentas de Orden.
