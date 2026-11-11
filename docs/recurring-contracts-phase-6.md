# Contratos Recurrentes: Fase 6

## Objetivo

Migrar de forma conservadora contratos comerciales legacy al dominio
`RecurringContract`, sin modificar ni eliminar documentos fuente, facturas
históricas o contratos laborales.

## Variantes legacy auditadas

### Alta manual

Campos observados:

```text
id
contractNumber
clientId
clientName
clientRNC
contractLines
amount
totalSubtotal
totalITBIS
recurrenceInterval
status
startDate
endDate
nextBillingDate
autoRenew
autoSendEmail
proratedFirstAmount
version
versionHistory
branchId
projectId
notes
```

### Conversión desde cotización

Campos observados:

```text
quotationId
frequency
recurrenceInterval
startDate
nextBillingDate
endDate
contractLines
amount
autoRenew
autoSendEmail
notes
```

### Legacy sin líneas

Algunos documentos solo tienen `amount` e `itemId`. Su interpretación como
importe con o sin ITBIS no es inequívoca, por lo que no se migran
automáticamente. Se conserva el documento fuente y se informa como
`incompatible`.

## Reglas de mapeo

| Legacy | Nuevo | Regla |
|---|---|---|
| `id` | `id` | Se conserva exactamente |
| `contractNumber` | `contract_number` | Se conserva |
| `clientId` | `client_id` | Se conserva |
| `clientName` | `client_name_snapshot` | Snapshot |
| `clientRNC` | `client_rnc_snapshot` | Snapshot |
| `quotationId` | `quotation_id` | Se conserva si existe |
| `status` | `status` | Solo estados conocidos |
| `startDate` | `start_date` | Debe ser ISO válido |
| `endDate` | `end_date` | Vacío permanece `None` |
| `nextBillingDate` | `billing_anchor_date` | Debe ser ISO válido |
| `recurrenceInterval`/`frequency` | `frequency` | Catálogo explícito |
| `contractLines` | `lines` | Todas las líneas deben ser válidas |
| `ecfType` | `ecf_type` | Nunca se infiere |
| ausencia de `ecfType` | `needs_fiscal_review` | Se marca `true` |
| `currency` | `currency` | Default histórico DOP solo si no había moneda distinta |
| `amount` | total calculado | Se compara; no reemplaza líneas |
| campos desconocidos | `legacyUnmappedFields` | Se conservan |

Los 30 días usados históricamente por la facturación no se convierten en
`credit_days` ni en una condición de pago contractual.

## Disposiciones

### `migratable`

La equivalencia es suficiente para crear el modelo nuevo. Si falta fiscalidad,
se conserva el target con `needs_fiscal_review=true`, por lo que no puede
emitir.

### `needs_review`

La estructura es utilizable, pero hay advertencias, por ejemplo:

- falta `ecfType`;
- `amount` no coincide con las líneas;
- existe información económica que requiere confirmación.

### `incompatible`

No se crea target parcial. Se conserva el documento fuente y se registran los
errores, por ejemplo:

- falta ID;
- falta fecha obligatoria;
- frecuencia desconocida;
- líneas inválidas o ausentes;
- estado desconocido.

### `already_migrated`

La combinación de compañía, entorno, ID fuente y fingerprint ya fue migrada.

## Dry-run

```python
report = service.dry_run(
    contracts,
    owner_uid="...",
    company_id="...",
    sandbox=True,
)
```

El dry-run no escribe. El informe contiene:

- total;
- migrables;
- pendientes de revisión;
- incompatibles;
- ya migrados;
- documento fuente;
- target proyectado;
- advertencias y errores.

## Idempotencia y reversión

La clave determinista usa:

```text
company_id + entorno + source_id
```

El fingerprint evita considerar idénticos dos documentos con el mismo ID pero
contenido distinto.

La estrategia de reversión elimina únicamente el registro de migración creado
por el servicio. Nunca elimina ni modifica el documento legacy fuente.

## Firestore

Esta fase incluye un store en memoria para pruebas. No ejecuta migración masiva
ni escribe en producción.

La integración real con Firestore Emulator continúa pendiente porque el entorno
no tiene `firebase`, `firebase.json` ni un SDK Firestore importable debido a la
incompatibilidad de `grpc` con Python 3.14.

## Pruebas

Se verifican:

- contratos completos;
- ausencia de tipo e-CF;
- ausencia de líneas;
- importe discrepante;
- frecuencia desconocida;
- dry-run sin escritura;
- reejecución idempotente;
- aislamiento multiempresa;
- separación sandbox/producción;
- reversión no destructiva.
