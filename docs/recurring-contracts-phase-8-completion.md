# Cierre de Fase 8

## Funcionalidades completadas

Se añadió `RecurringContractAdminService` para centralizar mutaciones
administrativas:

- creación;
- edición de condiciones mediante nuevas versiones temporales;
- administración de líneas a través de snapshots de términos;
- suspensión y reactivación;
- solicitud de cancelación;
- renovación contractual;
- resolución de revisión fiscal mediante catálogo elegible.

Las rutas administrativas delegan estas operaciones en el servicio y no
calculan períodos, importes ni reglas fiscales.

## Funcionalidades verificadas que ya existían

- listado filtrable del dominio nuevo;
- detalle contractual;
- consulta de versiones;
- consulta de ocurrencias y comandos Outbox;
- validación de permisos;
- aislamiento por compañía y entorno;
- lectura del feature flag sin posibilidad de activarlo desde la UI;
- bloqueo de emisión para contratos con revisión fiscal pendiente.

## Versionado e inmutabilidad

Cada edición crea una nueva `ContractTermsVersion`. La versión anterior se
cierra mediante `effective_to`, sin modificar sus líneas ni sus condiciones.

Las pruebas verifican:

- la versión original sigue abierta en el objeto original;
- la copia actualizada cierra la versión anterior;
- existe una nueva versión consecutiva;
- los snapshots históricos no se reescriben.

Las solicitudes de cancelación y renovaciones se registran como metadatos del
contrato. Las facturas y ocurrencias históricas no se modifican.

## Revisión fiscal

La resolución usa `RecurringContractFiscalService`. No acepta E43 ni otros
tipos no elegibles. Un contrato sin tipo fiscal mantiene
`needs_fiscal_review=true` y no puede entrar al flujo de emisión.

## Pruebas

Resultado final de la suite acumulada:

```text
81 pruebas ejecutadas
81 aprobadas
0 fallidas
```

Incluye pruebas nuevas para:

- creación y consulta mediante repositorio;
- versionado temporal;
- inmutabilidad histórica;
- líneas contractuales;
- suspensión/reactivación;
- solicitud de cancelación;
- renovación;
- resolución fiscal;
- permisos y aislamiento cubiertos por el blueprint y servicios existentes.

## Firestore

La integración real con Firestore Emulator continúa pendiente. Las pruebas en
memoria no se presentan como equivalentes a Firestore. No se realizó migración
masiva ni se habilitó persistencia productiva adicional.

## Emisión automática

No se registraron workers, no se activó emisión automática, no se consumieron
secuencias fiscales y no se modificaron facturas históricas.
