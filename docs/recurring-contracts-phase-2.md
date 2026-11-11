# Contratos Recurrentes: Fase 2

## Objetivo

Esta fase implementa `RecurringContractBillingService`, un servicio puro para
preparar la representación de una factura recurrente a partir de un contrato.

La fase no persiste datos, no crea ocurrencias, no adquiere locks, no crea
outbox, no consume secuencias y no emite e-CF.

## Interfaz

```python
RecurringContractBillingService.prepare_invoice(
    contract,
    occurrence_date=None,
    now=None,
) -> PreparedRecurringInvoice
```

`PreparedRecurringInvoice` contiene:

- `invoice`: instancia de `app.models.invoice.Invoice` lista para una fase
  posterior de persistencia/emisión.
- `snapshot`: condiciones congeladas aplicables al período.
- `period`: inicio, fin, ocurrencia y clave determinista del período.

El argumento `now` existe para que la creación sea determinista en pruebas y
no dependa de la fecha del servidor.

## Validaciones

El servicio rechaza:

- contratos que no estén `active`;
- contratos marcados `needs_fiscal_review`;
- contratos sin líneas;
- períodos fuera de la vigencia contractual;
- períodos que excedan el fin de un contrato sin renovación;
- períodos sin versión contractual aplicable;
- tipos fiscales no elegibles;
- monedas no soportadas por el dominio actual;
- snapshots sin líneas o con fechas inválidas.

Los tipos fiscales se validan mediante `RecurringContractFiscalService`, que a
su vez utiliza `app.models.fiscal_document_type` como catálogo central.

## Representación producida

La factura preparada conserva:

- cliente y snapshots de identificación;
- fecha de ocurrencia;
- fecha de vencimiento separada de la vigencia contractual;
- tipo e-CF con etiqueta y código;
- líneas y cálculos de subtotal, ITBIS y total;
- moneda y condiciones de pago;
- referencia textual al contrato.

Los campos fiscales que requieren emisión permanecen vacíos:

```text
encf = ""
xmlSignature = ""
isSyncedWithDGII = false
```

## Dependencias reutilizadas

- `RecurringContract` y `ContractPeriodSnapshot` de Fase 1.
- `RecurringContractScheduleService` para períodos y vencimientos.
- `RecurringContractFiscalService` para elegibilidad fiscal.
- `FiscalDocumentType` para etiquetas fiscales centralizadas.
- `Invoice` e `InvoiceItem` existentes como representación compatible.

No se duplican cálculos de calendario ni reglas fiscales.

## Límites deliberados

No se implementó todavía:

- persistencia;
- `contract_billing_occurrences`;
- intentos fiscales;
- outbox;
- locks distribuidos;
- consumo de secuencias;
- llamadas a DGII;
- integración con rutas o scheduler;
- contabilidad o inventario;
- modificación de contratos o facturas históricas.

## Pruebas

Se ejecutaron:

```bash
venv/bin/python -m pytest \
  tests/test_recurring_contract_domain.py \
  tests/test_recurring_contract_billing_service.py -q
```

Resultado: 43 pruebas aprobadas.
