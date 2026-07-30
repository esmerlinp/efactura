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
