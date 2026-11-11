# Sustitución raíz del flujo legacy

La creación nueva y el listado administrativo utilizan exclusivamente el
modelo `RecurringContract` V2.

Durante el desarrollo el motor queda activo por defecto:
`RECURRING_CONTRACT_ENGINE_V2_DEFAULT` (`config.py`) es `true` fuera de
producción. El documento `companies/{id}/[sandbox_]config/feature_flags`
sigue mandando cuando existe; en producción el default es `false` y requiere
activación explícita. Los errores de lectura del flag siguen fallando cerrado.

Las acciones del detalle de contrato (activar, suspender, cancelar) se
traducen de etiquetas españolas al enum V2, respetan la máquina de estados y
guardan el documento de dominio completo (conservando campos extra como
`legacySource` o `signatureInfo`). El detalle y el listado muestran las
etiquetas en español.

El repositorio `RecurringContractRepository` filtra por `schemaVersion=2`.
Los documentos legacy se conservan para lectura histórica y migración, pero no
se consideran contratos activos del dominio nuevo.

El scheduler legacy excluye contratos V2 para impedir doble procesamiento.

Al preparar una ocurrencia, `RecurringContractService` persiste una factura en
estado `Borrador` enlazada por `contractId`/`contractNumber`/`occurrenceId`.
Así el detalle del contrato y el listado de facturas la muestran de inmediato.
La preparación es idempotente: la ocurrencia reutiliza el mismo `invoice_id` y
el hash se calcula solo sobre el snapshot facturable (sin IDs ni timestamps
volátiles). No se consume secuencia NCF ni se emite e-CF; eso queda para el
worker fiscal cuando exista autorización sandbox.

No se eliminan documentos legacy ni facturas históricas. La migración sigue
siendo explícita, idempotente y reversible.
