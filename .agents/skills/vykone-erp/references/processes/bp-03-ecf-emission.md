# BP-3: Emisión de Factura Electrónica (e-CF DGII)

## Overview

Emisión de Comprobantes Fiscales Electrónicos ante la DGII de República Dominicana.
Soporta E31 (Crédito Fiscal), E32 (Consumo), E41 (Gasto Menor), E43 (Especial).

## Flow

```
Crear factura → Validar RNC cliente → Validar cuadratura ITBIS
→ Secuenciar e-NCF → Construir XML (DgiiXmlBuilder)
→ Firmar digitalmente (DgiiSigner, P12) → Emitir a DGII
   ├─ GET /autenticacion/api/Autenticacion/Semilla → seed
   ├─ POST token → JWT
   └─ POST /recepcion/api/Recepcion/Enviar → trackId
→ Consultar estado → Guardar PDF/XML
→ Reducir inventario (si aplica)
→ EventBus: InvoiceEmitted → asiento contable automático
```

## e-CF Type Rules

| Type | Client RNC | ITBIS | Use case |
|------|-----------|-------|----------|
| E31 | Required, 9 digits, not `000000000` | 18% (configurable) | B2B with tax credit |
| E32 | Any, `000000000` allowed | 18% | B2C final consumer |
| E41 | Any | 18% | Minor expenses <$250K |
| E43 | Any | Varies | Government, special regimes |

## Sequences

e-NCF sequences are consumed atomically from Firestore via `DatabaseService.consume_next_sequence()`.
Each emission consumes one sequence. The system tracks consumed sequences in `sequence_logs`.

## Fallback Modes

- **Simulation** (sandbox): `DGII_SANDBOX_MODE=local`, `DGII_ALLOW_SIMULATION=true` — no actual DGII call
- **Fallback**: If DGII unreachable, invoice stored with `contingencyEmittedAt` timestamp.
  Later synced via `ContingencySyncService`
- **Production**: Real DGII API calls with certificate authentication

## Post-Emission Effects

1. **Inventory**: stock reduced for each item (if `stockReduced=False` → sets to `True`)
2. **Accounting** (via EventBus): Debit CxC, Credit Ingresos + ITBIS por Pagar
3. **CxC**: Invoice appears in accounts receivable with initial balance = total
4. **Status**: `Emitida` (success), `Pendiente DGII` (fallback), `Rechazada` (failure)

## AI Guardrails

- `validate_invoice_before_emit`: safe, read-only
- `emit_e_cf_invoice`: high risk — fiscal document, requires confirmation
- `cancel_e_cf_invoice`: critical — fiscal cancellation with DGII, requires double confirmation
- ALWAYS validate RNC for E31 before emission
- NEVER emit E31 with generic RNC 000000000

## Related Files
- `app/services/ecf_emission.py` — orchestration
- `app/services/dgii_direct.py` — REST API client
- `app/services/dgii_signer.py` — P12 signing
- `app/services/dgii_xml_builder.py` — XML construction
- `app/services/contingency_sync_service.py` — fallback sync
- `app/models/invoice.py` — Invoice model
- `app/web/invoices.py` — UI routes
- `app/api/v1/invoices.py` — REST API
