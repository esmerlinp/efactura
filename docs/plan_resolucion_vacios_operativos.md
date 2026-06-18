# Plan de Resolución — Vacíos Operativos

> Excluye P0 (homologación DGII, firma digital real, e-NCF real, reporte 607) por estar a la espera de autorización DGII para emisión en producción.

---

## P1 — Bloqueantes (deben resolverse antes de producción)

### 1. Validaciones CxP Proveedor (Supplier Invoice)

**Archivos afectados:** `app/services/supplier_invoice_service.py`, `app/web/purchase_orders.py`

| # | Tarea | Descripción | Detalle Técnico |
|---|---|---|---|
| 1.1 | **Contador atómico** | Reemplazar `get_next_invoice_number()` O(n) scan | Crear documento `users/{uid}/config/supplier_invoice_counter` con campo `lastNumber`. Usar `transaction.get()` + `transaction.set()` para incremento atómico. Formato: `FI-{year}-{counter:04d}` |
| 1.2 | **NCF único por compañía** | Validar `supplierInvoiceNumber` no duplicado | Query `.where("supplierInvoiceNumber", "==", value).where("companyId", "==", company_id).limit(1)` antes de crear. Si existe, flash error. |
| 1.3 | **Server-side guard pago** | Bloquear pago si `cxpStatus == 'Pagado'` | En `pay_supplier_invoice()`, leer `cxpStatus` del doc, si `Pagado` retornar 400 |
| 1.4 | **Overpayment warning** | Alertar si monto > saldo restante | Si `amount > cxpRemainingBalance`, flash warning "El monto excede el saldo pendiente (RD$ X). Solo se aplicarán RD$ Y." |
| 1.5 | **Validar PO status** | Solo permitir invoice si PO está `recibida_parcial` o `recibida_completa` | Agregar check en `register_supplier_invoice()` |
| 1.6 | **Validar receivedQuantity > 0** | No permitir invoice sin al menos un ítem recibido | Verificar que `sum(item.get('receivedQuantity', 0) for item in po_items) > 0` |
| 1.7 | **Validar fechas** | `dueDate >= date` y `date <= today` | Validación server-side antes de guardar |
| 1.8 | **Upload robusto** | Feedback visible al usuario | Separar creación de factura del upload. Si upload falla, flash error "Factura creada pero el PDF no pudo subirse. Puede adjuntarlo después." No ocultar error en `except Exception`. |
| 1.9 | **Poblar `receiptId`** | Al crear invoice, guardar `receiptId` | Tomar del último receipt asociado al PO |

---

### 2. Régimen Fiscal Funcional

**Archivos afectados:** `app/services/dgii.py`, `app/services/db_service.py`, `app/web/invoices.py`, `templates/company_settings.html`

| # | Tarea | Descripción |
|---|---|---|
| 2.1 | **Mapa régimen → reglas** | Crear diccionario `REGIMEN_RULES`: `General` → permite E31/E32/E41/E43/E33/E34, ITBIS normal. `RST` → solo E32, sin ITBIS, límite RD$ 12,060,000. `RIM` → solo E32, ITBIS mínimo por cuota |
| 2.2 | **Validar régimen al emitir** | En `_new_document_helper()`, si `RST` y tipo e-CF = E31, rechazar. Si `RST` e invoice tiene ITBIS > 0, forzar ITBIS = 0 |
| 2.3 | **Dashboard RST real** | Dashboard ya tiene barra de progreso. Conectarla al límite real del año actual |
| 2.4 | **RIM en selector** | Agregar `RIM` al dropdown en `company_settings.html` |
| 2.5 | **Bloquear emisión sin régimen** | En `before_request` (o al crear invoice), verificar que `regimenFiscal` esté configurado. Si no, redirigir a configuración. |

---

### 3. Supplier Invoice — Edge Cases Restantes

**Archivos afectados:** `app/web/purchase_orders.py`, `app/services/supplier_invoice_service.py`, `templates/purchase_orders/`

| # | Tarea | Descripción |
|---|---|---|
| 3.1 | **Edición de factura** | Agregar `update()` route para campos no fiscales (notas, fechas, referencias). No permitir cambio de monto ni NCF. |
| 3.2 | **Reversión de pago** | Agregar `void_payment(invoice_id, payment_id)`: eliminar doc de subcollection, revertir `cxpRemainingBalance`, recalcular `cxpStatus` |
| 3.3 | **Persistir Vencido** | En `save_payment()` y `create()`, calcular si `dueDate < today` y persistir `cxpStatus = 'Vencido'`. También en un cron diario. |
| 3.4 | **Método de pago** | Agregar campo `paymentMethod`: `["Efectivo", "Cheque", "Transferencia", "Tarjeta", "Otro"]`. Almacenar en el subdoc `cxp_payments`. |
| 3.5 | **Orphan files cleanup** | En `delete()`, iterar `attachmentUrls` y llamar `DatabaseService.delete_file_from_storage()` |
| 3.6 | **Límite de tamaño archivo** | Check `len(file_data) > 10 * 1024 * 1024` (10MB) → rechazar |
| 3.7 | **Tipo archivo server-side** | Verificar `content_type in ['application/pdf', 'image/jpeg', 'image/png']` |
| 3.8 | **Múltiples attachments** | Permitir agregar más archivos a factura existente (nueva route `add_attachment`) |

---

## P2 — Alto Impacto

### 4. Exportación Contable

**Archivos afectados:** Nuevo `app/services/accounting_export_service.py`, `app/web/invoices.py`, `templates/reports/`

| # | Tarea | Descripción |
|---|---|---|
| 4.1 | **Plan de cuentas default** | Crear cuenta por defecto por compañía: 1.1.1.01 Caja, 1.1.2.01 Bancos, 4.1.1.01 Ventas, 5.1.1.01 Costos, etc. |
| 4.2 | **Generar asiento por factura** | Al emitir factura, generar asiento: Débito CxC / Crédito Ventas + ITBIS por pagar |
| 4.3 | **Exportar Digiflow** | CSV en formato Digiflow: fecha, cuenta, débito, crédito, referencia |
| 4.4 | **Exportar AP/Soft** | CSV en formato AP/Soft de RD |
| 4.5 | **Exportar CSV genérico** | Columnas configurables para cualquier software |

---

### 5. Notas de Crédito/Débito — UI Dedicada

**Archivos afectados:** Nuevo `app/web/fiscal_notes.py` (o renombrar `notes.py`), nuevos templates en `templates/fiscal_notes/`

| # | Tarea | Descripción |
|---|---|---|
| 5.1 | **Separar fiscal notes de sticky notes** | Crear blueprint `web_fiscal_notes`. El actual `notes.py` es sticky notes genéricas, NO notas fiscales. |
| 5.2 | **Formulario E34 (Crédito)** | Route `/credit-notes/new` con: referencia a factura original, monto, razón (devolución/descuento/corrección), items |
| 5.3 | **Formulario E33 (Débito)** | Route `/debit-notes/new` con: referencia, monto adicional, razón |
| 5.4 | **Enforce reglas DGII** | Crédito ≤ monto original. Débito solo si hay saldo pendiente. 30 días sin recargo. |
| 5.5 | **Conectar Alanube payload** | El builder para E33/E34 ya existe en `alanube.py`. Solo conectar la nueva UI. |

---

### 6. 606 — Formato Oficial DGII

**Archivos afectados:** `app/web/reports_606.py`

| # | Tarea | Descripción |
|---|---|---|
| 6.1 | **Validar columnas DGII** | Comparar CSV generado vs especificación DGII: RNC Comprador, Período, RNC Proveedor, Tipo Identificación, Nombre, Tipo Comprobante, NCF/e-CF, Monto, ITBIS, Fecha, Tipo Gasto |
| 6.2 | **Encoding + BOM** | Asegurar UTF-8 BOM para Excel |
| 6.3 | **Quoting de campos** | Usar `csv.writer` con `quoting=csv.QUOTE_ALL` en lugar de join manual |

---

## P3 — Medio

### 7. Onboarding Fiscal Guiado

**Archivos afectados:** `app/web/auth.py`, `templates/onboarding_wizard.html`

| # | Tarea | Descripción |
|---|---|---|
| 7.1 | **Wizard paso a paso** | Paso 1: "¿Eres persona física o empresa?" → Paso 2: "¿Tu régimen?" (RST/General/RIM) con descripciones simples → Paso 3: Configurar RNC → Paso 4: Cargar firma o indicar que usará simulación |
| 7.2 | **Defaults inteligentes** | Si RST: default E32, sin ITBIS. Si General: default E31. |
| 7.3 | **Tooltips fiscales** | En formularios, tooltips: "ITBIS: 16% para la mayoría de productos", "E31: Factura de Crédito Fiscal (B2B)" |

---

### 8. Multi-moneda Automática

**Archivos afectados:** `app/web/invoices.py`, `app/services/currency.py`

| # | Tarea | Descripción |
|---|---|---|
| 8.1 | **Tasa automática en factura** | Al seleccionar moneda distinta a DOP, obtener tasa de `CurrencyService` y prellenar |
| 8.2 | **Mostrar DOP equivalente** | En dashboard y reportes, columna "Monto DOP" con conversión |
| 8.3 | **Reportes multi-moneda** | 606/IT-1 deben convertir a DOP con tasa del período |

---

### 9. Mejoras Técnicas

| # | Tarea | Archivos | Descripción |
|---|---|---|---|
| 9.1 | **Paginación** | `db_service.py`, `invoices.py` routes | Agregar `.limit(page_size).offset(page * page_size)` en queries de listas |
| 9.2 | **CSV quoting** | Todos los exports | Reemplazar string join con `csv.writer` + `QUOTE_ALL` |
| 9.3 | **Rate limiting** | `app/api/v1/` | Agregar decorador `@rate_limit(100, 60)` (100 requests/min) |
| 9.4 | **Reemplazar bare except** | Todos los archivos | `except Exception as e: log.error(...); flash(...)` en lugar de `except: pass` |
| 9.5 | **Tests de rutas** | `tests/test_routes.py` | Flask test client para CxP, suppliers, invoices, notas crédito |

---

## Estimación de Esfuerzo

| Prioridad | Módulo | Días Estimados |
|---|---|---|
| **P1** | 1. Validaciones CxP (9 subtareas) | 3-4 |
| **P1** | 2. Régimen Fiscal Funcional (5 subtareas) | 2-3 |
| **P1** | 3. Edge Cases Supplier Invoice (8 subtareas) | 3-4 |
| **P2** | 4. Exportación Contable (5 subtareas) | 3-5 |
| **P2** | 5. Notas Crédito/Débito UI (5 subtareas) | 3-4 |
| **P2** | 6. 606 Formato Oficial (3 subtareas) | 1 |
| **P3** | 7. Onboarding Fiscal (3 subtareas) | 2-3 |
| **P3** | 8. Multi-moneda (3 subtareas) | 1-2 |
| **P3** | 9. Mejoras Técnicas (5 subtareas) | 2-3 |
| | **Total** | **20-29 días** |

---

## Orden de Implementación Sugerido

### Fase 1 (Semana 1-2) — P1 Completo
```
Día 1-4:   1. Validaciones CxP (contador atómico, NCF único, guards)
Día 2-5:   3. Edge Cases Supplier Invoice (edición, reversión, Vencido, upload)
            (puede ir en paralelo con 1)
Día 3-5:   2. Régimen Fiscal Funcional
```

### Fase 2 (Semana 3-4) — P2
```
Día 6-10:  4. Exportación Contable
Día 6-9:   5. Notas Crédito/Débito UI
Día 8:     6. 606 Formato Oficial
```

### Fase 3 (Semana 5) — P3 + Bugfixes
```
Día 11-13: 7. Onboarding Fiscal
Día 11-12: 8. Multi-moneda
Día 11-13: 9. Mejoras Técnicas + Tests
```

---

## Preguntas Abiertas

1. **Exportación contable:** ¿A qué software específico necesitan llegar los datos? Digiflow, AP/Soft, otro? ¿Formato exacto (columnas, delimitadores)?
2. **Régimen RIM:** ¿Es necesario ahora o puede esperar a la fase de homologación DGII? Muy pocos contribuyentes están en RIM.
3. **Notas crédito/débito:** El blueprint `notes.py` actual es sticky notes — ¿prefieres renombrarlo y crear uno nuevo, o crear `fiscal_notes.py` aparte?
4. **Onboarding:** ¿Wizard tipo "paso 1 de 5" o tooltips contextuales en cada formulario?
