# E45 (Gubernamental) e-CF Emission — DGII Acceptance

## Root Cause of Rejection

E45 was configured with `IndicadorMontoGravado=1` (prices include ITBIS) but stored data
uses ex-ITBIS prices (same as E31/E32). This broke three DGII cross-validations:

1. `MontoGravadoI1` — DGII computes: `sum(MontoItem - DescuentoMonto + RecargoMonto)`
   for items with `IndicadorFacturacion=1` (ITBIS 18%). With `=1` the validator expected
   ITBIS-inclusive values but received ex-ITBIS values → mismatch.

2. `TotalITBIS1 = MontoGravadoI1 × ITBIS1` — fails unless both use the same base
   (ex-ITBIS or with-ITBIS). With `=1`, `MontoGravadoI1` is interpreted as including
   ITBIS, so `TotalITBIS1 = MontoGravadoI1 × 0.18` gives a wrong inflated amount.

3. `MontoTotal` — cascading failure from incorrect subtotals.

## Three Changes Applied (`dgii_xml_builder.py`)

### 1. IndicadorMontoGravado=0 for E45 (line 238)
```python
ET.SubElement(id_doc, "IndicadorMontoGravado").text = "0" if tipo_ecf in ("31", "32", "33", "34", "41", "45") else "1"
```
Government invoices use the same pricing convention as regular invoices (ex-ITBIS).

### 2. Per-rate-band gravado breakdown (lines 398-412)
Instead of `gravado = subtotal - montoExento` (lumps all non-exento into `MontoGravadoI1`):
```python
gravado_i1 = sum of item_net for itbisRate >= 0.17
gravado_i2 = sum of item_net for itbisRate >= 0.15
gravado_i3 = sum of item_net for 0 < itbisRate < 0.15
```
Where `item_net = item.subtotal - discount_amount + recargoMonto`.

### 3. MontoItem = item.subtotal (ex-ITBIS, line 529)
```python
ET.SubElement(item_elem, "MontoItem").text = f"{float(item.get('subtotal', 0.0)):.2f}"
```

## Key Data Storage Detail

`calculate_invoice_totals()` enriches items with `subtotal_raw`, `discount_amount`, and
`subtotal`, but `save_invoice()` only persists `subtotal` (not `subtotal_raw` or
`discount_amount`). The fallback to `item.subtotal` is correct for
`IndicadorMontoGravado=0`.

## E45 Model Configuration (`fiscal_document_type.py`)

```python
E45 = _reg(FiscalDocumentType(
    code="E45", numeric_code="45",
    label="Gubernamental",
    family=Family.ECF, category=Category.GOVERNMENT,
    has_itbis=False, has_comprador=True, has_vencimiento=True,
    has_payment_schedule=True, has_discounts=True,
    has_deferred_shipping=True, has_retention=False,
    has_itbis_breakdown=True,
    in_reporte_606=True, in_reporte_607=True,
    accounting_entry_type="invoice",
    xsd_file="Schemas/e-CF 45 v1.0.xsd",
))
```

- `has_itbis=False` — ITBIS not tracked as a separate flag (but items still have itbisRate)
- `has_itbis_breakdown=True` — XML Totales must include MontoGravadoI1/I2/I3 breakdown
- `has_retention=False` — no ISR/ITBIS retentions
- `in_reporte_606/607=True` — must appear in DGII tax reports

## Emission Flow

```
sign_invoice_route (invoices.py:3527)
  → EcfEmissionService.emit_electronic_comprobante (ecf_emission.py:18)
    → DgiiDirectService.emit_direct (dgii_direct.py:348)
      → DgiiXmlBuilder.build_invoice_xml (dgii_xml_builder.py:192)
      → DgiiSigner.sign_xml (dgii_signer.py:78)
      → multipart POST to DGII recepcion endpoint
```

Invoice data is loaded from Firestore via `get_invoice()` and passed through without
recalculation. The XML must be self-consistent per DGII cross-validation rules.

## Certificación Paso 2 (Pruebas de Datos) — XML debe copiar el Excel verbatim

### Regla DGII
La DGII compara cada comprobante (API y portal) contra su conjunto de datos:
los valores del XML deben coincidir **exactamente con la fila del Excel**, caso
por caso. Esto incluye el bloque `<Comprador>` completo:
- E32 (cualquier monto) y RFCE: `RNCComprador=131880681` + `RazonSocialComprador`
  presentes (así vienen en el Excel, y así se aceptó el 28-jul).
- E43: sin `<Comprador>` (el Excel lo trae todo `#e`).
- E47: `IdentificadorExtranjero=350555123` + RazonSocial, **sin** RNCComprador.

Errores vistos del portal (ambos significan desajuste con el data set):
`el valor enviado 131880681 no coincide con el valor '' del conjunto de datos`
`el valor enviado () no coincide con el valor (131880681) del conjunto de datos`

Un rechazo reinicia TODAS las pruebas de datos de eCF. El primer patrón
(esperado `''`) también aparece si se adjunta al portal un XML en el caso
equivocado (ej. un E32 en el slot de un E43/E47) — hay que subir cada
`*_manual_signed.xml` al caso con el MISMO eNCF.

### Implementación (`dgii_test_data_loader.py`)
- `build_xml_from_row` (~línea 145): copia verbatim todos los campos del
  comprador que traiga la fila del Excel; si la fila no trae ninguno, omite
  el elemento `<Comprador>` (comportamiento original del 28-jul, commit
  7ded5ef). No aplicar reglas de "consumo < 250K" — el data set es la fuente.
- `build_rfce_xml_from_row` (~línea 625): copia verbatim los campos del
  comprador de la Hoja 2 (RFCE).

### Vínculo de firma RFCE ↔ E32 completo (DGII lo valida)
La DGII exige que el `CodigoSeguridadeCF` del RFCE (grupo 3) sea igual a los
**6 primeros caracteres del `SignatureValue` del E32 completo** que se sube al
portal (grupo 4). Error típico:
`Los 6 primeros dígitos de la propiedad signature value de la firma de la
Factura de Consumo Electrónica enviada F09z9g no coincide con el valor ZWAG6z
enviado previamente en el Resumen de este modelo de Factura de Consumo.`
Por eso ambos deben salir del MISMO `{encf}_e32_firmado.xml` (misma firma).

### Caché de corridas (`dgii_cert_service.py`)
`process_step2_generate` reutiliza `{encf}_e32_firmado.xml` entre grupos 3 y 4.
La reutilización es **por contenido** (`_cached_e32_matches`): compara c14n del
XML unsigned ignorando `FechaHoraFirma` y el `ds:Signature`. Si coincide, se
reusa (firma estable entre clics y corridas → el vínculo RFCE↔E32 se mantiene).
Si difiere (código viejo, ej. E43 con `<Comprador/>` → "El formato del XML no
es válido. en el grupo 1"), se re-firma y se marca `firma_actualizada` (la nota
del grupo 4 avisa que hay que reenviar el grupo 3).

El endpoint `step-2/generate` reusa automáticamente el run `in_progress` del
paso 2 aunque la UI no mande `resume_run` (sobrevive recargas de página y
mantiene grupos 3 y 4 en el mismo directorio). La UI envía `force_rerun: true`
por botón de grupo. Tras un reinicio de pruebas de DGII hay que re-enviar todos
los grupos (1–3 API, 4 manual), en orden y en la misma sesión.

### Verificación
- `python scripts/verify_step2_xml.py --excel <xlsx>` — genera y compara el
  bloque Comprador campo a campo contra el Excel + XSD por tipo (E32/RFCE).
- `python scripts/verify_step2_xml.py --excel <xlsx> --run-dir .../runN/xml` —
  compara también los archivos ya generados de una corrida y verifica el
  **vínculo de firma** (CodigoSeguridadeCF == SignatureValue[:6]).
- `python -m pytest tests/test_cert_excel_loader.py` — regresión (incluye
  `_cached_e32_matches` y XSD de E43 sin `<Comprador>`).

Nota: los XSD de DGII usan patrones regex no soportados por libxml2
(`[$0-9]`, `(?:...)`); el script/test los sanitiza en memoria antes de validar
con lxml (no modificar los XSD).

## Estados de Empleado — Vacaciones y Licencia (EmployeeStatusService)

El campo `status` del empleado ahora admite 5 valores:
`activo | inactivo | suspendido | vacaciones | licencia`.
Los dos últimos son **transitorios** y los gestiona exclusivamente
`app/services/employee_status_service.py` (nunca fijarlos a mano):

- **Inicio**: cuando una solicitud `aprobada` de vacaciones/licencia tiene
  `startDate <= hoy <= endDate`, el empleado pasa a `vacaciones`/`licencia`.
- **Fin**: al terminar la solicitud vigente vuelve automáticamente a `activo`.
- **Licencia gana**: aprobar una licencia solapada con vacaciones aprobadas
  revoca la vacación (`status="revocada"`), devolviendo los días no consumidos
  (solo descuenta días hábiles hasta el inicio de la licencia).
- **Anulación** (`POST /rrhh/vacations/<id>/anular`): si se anula a mitad de
  curso, `consumedDays` = días hábiles tomados hasta la fecha de anulación;
  el resto se reembolsa. Antes del inicio → reembolso total.
- **Días disponibles**: `taken_vacation_days()` suma `days` de solicitudes
  `aprobada` + `consumedDays` de `anulada/revocada` (NO sumar `days` de las
  anuladas/revocadas — ese era el bug del cálculo original).

### Ejecución
- Job APScheduler diario `hr_status_transitions` (00:15 AM RD) →
  `sync_employee_statuses()` recorre todas las empresas (sandbox + prod).
- Auto-sanación: `vacation_list`, `leave_list` y `employee_view` ejecutan el
  sync al renderizar (idempotente; si el scheduler falló, se recupera solo).

### Regla de nómina (crítica)
`vacaciones` y `licencia` **cobran y cotizan normal** (equivalente-activo).
El helper `is_active_equivalent()` (`app/utils/hr_utils.py`) debe usarse en
todo filtro que antes era `status == "activo"`. Los archivos TSS/IR-13/nómina
ya fueron ajustados:
- `payroll_service.py` (`es_ex_empleado` solo si status no está en
  activo/vacaciones/licencia/"").
- `tss_novedades_service.py` (misma regla; la novedad VC/LV/LM sale de la
  solicitud aprobada, no del status).
- `ir13_service.py` (whitelist ampliada).

### Historial
Cada transición escribe en la colección `hr_employee_status_events`
(`trigger`: vacation_start/end, leave_start/end, vacation_cancelled,
vacation_revoked) y en el log global (`log_action`, entity="employee").
Se muestra en el Tab "Acciones" de la ficha del empleado.

### Tests
`python -m pytest tests/test_employee_status_transitions.py` — regresión del
motor (transiciones, revocación, prorrateo de anulación, idempotencia).
