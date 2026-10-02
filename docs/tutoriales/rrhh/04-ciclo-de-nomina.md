# Tutorial: Ciclo de vida de la nómina

Una vez calculada la nómina, sigue este ciclo de estados hasta cerrarla:

`Borrador → Calculada → Aprobada → Pagada → Contabilizada → Cerrada`

## Aprobar la nómina

1. Con la nómina en estado **Calculada**, revisa los valores.
2. Haz clic en **"Aprobar"**.
3. El estado pasa a **Aprobada**.

> Si tu empresa usa el flujo completo (sin "nómina simplificada"), verás un paso
> previo **"Validar"** antes de **"Aprobar"**.

## Registrar el pago

1. Con la nómina **Aprobada**, haz clic en **"Registrar Pago"**.
2. Confirma *"¿Confirmar pago de nómina?"* e indica la fecha de pago.
3. El estado pasa a **Pagada**.

## Contabilizar

1. Con la nómina **Pagada**, haz clic en **"Contabilizar"**.
2. Confirma *"¿Contabilizar la nómina? Se generará el asiento contable
   automáticamente."*
3. El estado pasa a **Contabilizada**.

## Cerrar el período

1. Con la nómina **Contabilizada**, haz clic en **"Cerrar Período"**.
2. Confirma *"¿Cerrar definitivamente el período? No se podrá modificar."*
3. El estado pasa a **Cerrada** y ya no admite cambios.

## Revertir pasos

Si te equivocas, puedes volver atrás:

- **"Recalcular"** o **"Editar valores"** — vuelve a **Borrador**.
- **"Revertir pago"** — revierte el pago (deberás escribir `RECALCULAR`).
- **"Revertir contabilización"** — revierte el asiento contable.
- **"Eliminar"** — elimina el período (solo en Borrador; escribe `ELIMINAR`).

## Exportaciones disponibles

Según el estado de la nómina, puedes:

- **Autodeterminación** (AM mensual / AR retroactiva).
- **Novedades (NV)** y **Rectificativa (RT)** — formatos TSS.
- **TSS Resumen** y **Exportar CSV**.
- **Archivo Banco** (Banco Popular, Reservas o BHD).
- **Enviar volantes** de pago a los empleados por correo.
