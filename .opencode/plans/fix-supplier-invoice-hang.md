# Fix: Supplier Invoice Save Hangs

## Root Cause

When saving a supplier invoice (`new_supplier_invoice_direct` or `register_supplier_invoice`), the POST handler does **7+ synchronous Firebase operations** sequentially before returning the response. The main bottlenecks:

1. **`upload_file_to_storage`** (db_service.py:3392) — calls `list_blobs()` to check storage usage (5–20s on cold cache), then `blob.upload_from_string()` with **no timeout** (can hang 60–120s+)
2. **File upload blocks invoice creation** — the file is uploaded BEFORE the invoice is saved to Firestore, so if the upload hangs, the entire request hangs and the invoice is never created

## Changes

### 1. `app/services/db_service.py:3429` — Add upload timeout

```
- blob.upload_from_string(file_data, content_type=mime_type)
+ blob.upload_from_string(file_data, content_type=mime_type, timeout=30)
```

Prevents `upload_from_string()` from hanging indefinitely. 30s is enough for files up to 10MB over a reasonable connection.

### 2. `app/web/purchase_orders.py:997–1085` — Reorder `new_supplier_invoice_direct`

**Before**: Validate → check NCF → **upload file** → find/create contact → build data → save invoice → bank update → audit → redirect

**After**: Validate → check NCF → find/create contact → build data (without attachmentUrls) → **save invoice** → try upload (via `add_attachment`) → bank update → audit → redirect

Concrete changes in the POST handler (lines 997–1113):

**a)** Remove the inline file upload block (lines 997–1016) from its current position.

**b)** Remove `attachment_urls` from `inv_data` (line 1069), or set it to `[]` initially:
```python
inv_data = {
    ...
    "attachmentUrls": [],
    ...
}
```

**c)** After `SupplierInvoiceService.create(owner_uid, inv_data, sandbox=sandbox)` (line 1085), add the file upload:
```python
attachment_file = request.files.get('attachment')
file_upload_error = None
if attachment_file and attachment_file.filename:
    try:
        attachment_file.seek(0)
        file_data = attachment_file.read()
        if len(file_data) <= MAX_FILE_SIZE:
            mime_type = attachment_file.content_type or "application/octet-stream"
            if mime_type in ALLOWED_MIME_TYPES:
                public_url = SupplierInvoiceService.add_attachment(
                    owner_uid, inv_data["id"], file_data,
                    attachment_file.filename, mime_type, sandbox=sandbox
                )
                if not public_url:
                    file_upload_error = "El archivo no pudo subirse."
            else:
                file_upload_error = "Tipo de archivo no permitido."
        else:
            file_upload_error = "El archivo excede el límite de 10 MB."
    except Exception as e:
        file_upload_error = str(e)
```

Also handle `ocr_attachment_url`:
```python
ocr_attachment_url = request.form.get('ocr_attachment_url', '').strip()
if ocr_attachment_url:
    try:
        SupplierInvoiceService._update_attachment_urls(
            owner_uid, inv_data["id"], [ocr_attachment_url], sandbox=sandbox
        )
    except Exception as e:
        print(f"Error al adjuntar OCR URL: {e}")
```

**Note**: `SupplierInvoiceService.add_attachment()` already exists (line 237) and internally calls `upload_file_to_storage()`. But it does NOT add the `timeout=30` — that must be added in step 1.

### 3. `app/web/purchase_orders.py:1197–1213` — Reorder `register_supplier_invoice`

Same pattern as #2. The POST handler at line 1170 currently uploads the file at lines 1197–1216, then saves at line 1273.

**Move the file upload block to AFTER `SupplierInvoiceService.create()`** (line 1273), and use `add_attachment()`.

### 4. (Optional) `app/services/db_service.py:3368–3386` — Skip storage limit check

Since `get_storage_usage_mb()` does a full `list_blobs()` which can take 5–20s on cold cache, and the file upload already has a local fallback, the storage limit check adds more pain than value on the write path. Either:

- **Option A**: Comment out the storage limit check (lines 3400–3414)
- **Option B**: Move the check to only run when `len(file_data) > 1MB` (only flag large uploads)
- **Option C**: Use a short timeout on `list_blobs()` — but `google-cloud-storage` doesn't support timeout on `list_blobs` directly

## Testing

1. Create a supplier invoice with a 1MB PDF attachment — should save in < 3 seconds
2. Create a supplier invoice without any attachment — should save in < 2 seconds
3. Create a supplier invoice with Contado payment — verify bank balance decreases
4. Verify the invoice detail page shows the uploaded attachment correctly
5. Test `save_and_new` flow still works
