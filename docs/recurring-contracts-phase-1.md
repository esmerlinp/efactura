# Contratos Recurrentes: Fase 1

## Alcance

Esta fase define únicamente el dominio comercial de contratos recurrentes.
No modifica rutas, formularios, scheduler, persistencia existente, facturas,
secuencias ni emisión e-CF.

## Modelo

`app/models/recurring_contract.py` es independiente de
`app/models/contract.py`, que representa contratos laborales.

El contrato comercial separa:

- Vigencia contractual: `start_date` y `end_date`.
- Programación: frecuencia, ancla, día de facturación y zona horaria.
- Modalidad: facturación anticipada o vencida.
- Condiciones de pago: días de crédito y política de vencimiento.
- Fiscalidad: tipo e-CF, moneda y política de impuestos.
- Versiones de condiciones: términos que aplican por fecha.

Los nombres están en `snake_case` en el modelo nuevo. La adaptación a los
campos legacy (`startDate`, `nextBillingDate`, `recurrenceInterval`) queda
para la fase de migración.

## Estados y transiciones

```text
draft -> pending_approval -> active
draft -> active
pending_approval -> draft
active -> suspended -> active
active -> cancelled
active -> expired
suspended -> cancelled
suspended -> expired
expired -> active
expired -> cancelled
```

`cancelled` es terminal. Los estados no se infieren de fechas en este dominio;
la transición explícita será responsabilidad de la fase administrativa.

## Catálogo fiscal elegible

El filtro usa `app.models.fiscal_document_type` como fuente central.

| Código | Tratamiento en contrato |
|---|---|
| E31 | Generalmente elegible |
| E32 | Generalmente elegible |
| E44 | Condicionado; requiere validación adicional |
| E45 | Condicionado; requiere validación adicional |
| E46 | Condicionado; requiere validación adicional |
| E47 | Condicionado; requiere validación adicional |
| E48 | Condicionado; requiere validación adicional |
| E49 | Condicionado; requiere validación adicional |
| E41 | Excluido: comprobante de compras |
| E43 | Excluido: gastos menores |
| E33/E34 | Excluidos: notas de débito/crédito |
| E50 | Excluido: retención |

La elegibilidad de dominio no sustituye la validación DGII. Los contratos sin
tipo fiscal se consideran `needs_fiscal_review` y no son fiscalmente elegibles.

## Calendario

- Los cálculos usan fechas calendario, no sumas fijas de 30 días.
- El día 31 se ajusta al último día del mes cuando el mes destino es más corto.
- `last_day_of_month` fuerza el último día de cada mes.
- Los períodos son inclusivos en ambos extremos.
- `advance`: el período comienza en la fecha de ocurrencia.
- `arrears`: el período termina en la fecha de ocurrencia.
- `same_day`: vencimiento el día de ocurrencia.
- `occurrence_plus_credit_days`: vencimiento desde la ocurrencia.
- `period_end_plus_credit_days`: vencimiento desde el fin del período.
- El prorrateo diario incluye la fecha inicial y la fecha final.
- Las fechas no se desplazan automáticamente por fines de semana en esta fase;
  esa política queda explícita para una futura regla de calendario laboral.

## Versionado y snapshots

`ContractTermsVersion` es inmutable y tiene vigencia temporal. Las versiones
son consecutivas y no se pueden solapar.

`ContractPeriodSnapshot` congela las condiciones aplicables a un período:

- versión contractual;
- período;
- fecha de ocurrencia;
- vencimiento;
- e-CF;
- moneda;
- crédito;
- modalidad;
- líneas y tasas.

La fase posterior podrá persistir este snapshot junto con la ocurrencia sin
volver a consultar condiciones modificadas del contrato.

## Compatibilidad actual

Los contratos existentes usan diccionarios, estados en español, camelCase y
`amount` ambiguo respecto a ITBIS. Este modelo no los convierte ni los modifica.
La migración deberá marcar los registros sin configuración fiscal para revisión
manual y conservar las facturas históricas intactas.

## Validación de esta fase

Los nuevos módulos pasan compilación sintáctica y `git diff --check`.
La ejecución de pytest no fue posible en el entorno actual porque no están
instalados `pytest` ni las dependencias de la aplicación (`flask`). Por tanto,
la suite debe ejecutarse en el entorno de desarrollo/CI del proyecto antes de
aprobar la fase.
