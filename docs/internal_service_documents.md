# Documentos internos de servicios gratuitos

## Propósito

Los documentos internos registran promociones comerciales, servicios gratuitos y períodos de prueba. No son comprobantes fiscales, no generan NCF ni e-CF y no afectan cuentas por cobrar, pagos, inventario o contabilidad.

## Almacenamiento

Cada empresa y entorno tiene colecciones independientes:

- `internal_service_documents`
- `sandbox_internal_service_documents`
- `internal_service_document_counter`
- `sandbox_internal_service_document_counter`
- `internal_service_document_idempotency`
- `sandbox_internal_service_document_idempotency`

La creación es transaccional. La misma clave de idempotencia devuelve el documento existente y no consume otra numeración.

## Datos congelados

El documento guarda snapshots de empresa, cliente y catálogo. El PDF usa únicamente esos snapshots, por lo que cambiar el catálogo posteriormente no modifica la evidencia emitida.

Los importes se almacenan en centavos enteros y se calculan con `Decimal` antes de persistirse.

## Estados

`persistedState` solo admite `active` o `voided`. El vencimiento no modifica este estado. `calculatedState` se calcula al consultar con base en las fechas y puede ser `proximo`, `vigente`, `vencido` o `anulado`.

## Vencimiento y facturación formal

El scheduler diario genera alertas idempotentes para promociones que vencen en 30, 7 o 0 días. Nunca crea facturas ni contratos automáticamente. El responsable comercial debe revisar el documento y crear manualmente el contrato recurrente en **Contratos y Facturación Recurrente**, confirmando precio, periodicidad, fecha inicial y condiciones fiscales.

## Permisos

- `canCreateInternalServiceDocument`
- `canViewInternalServiceDocuments`
- `canVoidInternalServiceDocument`
- `canDownloadInternalServiceDocument`

La anulación es lógica y exige motivo. Los documentos no se eliminan físicamente.

## Portal de clientes

Después de verificar la identidad del cliente mediante el enlace oficial, RNC/cédula y código de acceso, el portal muestra una sección de promociones comerciales. Cada consulta exige coincidencia simultánea de `companyId`, `clientId` y entorno sandbox/producción. El cliente solo puede consultar y descargar el PDF; no puede editar, anular ni convertir automáticamente la promoción en una factura.

## Rutas web

- `GET /internal-documents`
- `GET|POST /internal-documents/new`
- `GET /internal-documents/<id>`
- `GET /internal-documents/<id>/pdf`
- `GET /internal-documents/<id>/download`
- `POST /internal-documents/<id>/void`
