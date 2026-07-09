---
name: vykone-erp
description: |
  Operate and reason about the VykOne ERP system — a Dominican Republic-compliant
  ERP for electronic invoicing (e-CF DGII), payroll (TSS/ISR), accounting,
  CRM, inventory, bank reconciliation, and HR. Use this skill whenever the user
  asks about VykOne ERP architecture, business processes (nómina, facturación
  electrónica, contabilidad, CxC/CxP, liquidaciones, cierres fiscales), DGII
  compliance, or needs to understand how to interact with the ERP codebase.
  Also use it when the user mentions Dominican tax compliance (ITBIS, ISR, NCF,
  e-CF, DGT forms 2/3/4/5/9/12), TSS calculations, or labor law (Ley 16-92).
---

# VykOne ERP — AI Agent Knowledge Skill

## Purpose

This skill teaches an AI agent to understand, navigate, and operate the VykOne ERP
system. It documents the architecture, 12 core business processes, 22 AI-ready
tools with complete JSON schemas, and all validation/authorization guardrails.

VykOne is a multi-tenant Flask 3.x ERP with Firebase Firestore persistence,
designed specifically for Dominican Republic regulatory compliance.

## How to use this skill

1. **Start here** — this file gives you the big picture
2. **Read `references/architecture/overview.md`** for the full dependency map,
   service inventory, event bus, and module relationships
3. **Read `references/processes/`** for detailed end-to-end business process
   flows — one file per process. Read the process relevant to the user's task
4. **Read `references/tools/`** for complete JSON schemas of each AI tool,
   with parameters, permissions, validations, and example invocations

## System Overview

- **Stack**: Flask 3.x, Jinja2 templates, Firebase Firestore, Pydantic models,
  Redis (optional), APScheduler, WeasyPrint PDF, lxml XML signing
- **Architecture**: Factory pattern with layered design
  - `app/web/` — 33 Blueprint route files (Jinja2 UI)
  - `app/api/v1/` — 9 REST API Blueprints
  - `app/services/` — 60+ domain service files
  - `app/models/` — Pydantic models for all entities
  - `app/repositories/` — Typed Firestore access layer
  - `app/events/` — Event Bus (in-process/Redis Pub/Sub) with 9 domain events
  - `app/utils/` — Security, decorators, module gating, currency helpers
- **Multi-tenancy**: Every document scoped to `owner_uid` with sandbox/production
  environment split (`sandbox_` prefix on collections)
- **Auth**: Firebase Authentication, role-based (owner/member), granular
  permissions, Segregation of Duties (SoD) conflict matrix
- **Key integrations**: DGII REST API (e-CF emission/cancellation), SMTP/Microsoft
  Graph for emails, OpenAI for chatbot, Azul payment gateway

## Module Map

| Module | Key | Category | Services | Web Routes | API |
|--------|-----|----------|----------|------------|-----|
| e-CF Invoicing | `e_cf` | core | dgii_direct, dgii_signer, dgii_xml_builder, ecf_emission | invoices, notes, fiscal_notes | invoices, dgii |
| Dashboard | `dashboard` | core | aggregation, bi_drilldown, cash_flow | dashboard, bi | — |
| Product Catalog | `catalogo` | core | db_service (items) | invoices (items) | — |
| CRM | `crm` | sales | crm_service | crm, contacts, clients | prospects |
| POS | `pos` | sales | — | pos | — |
| Inventory | `inventario` | logistics | inventory_costing, inventory_alert, physical_count, warehouse_transfer | inventory | — |
| CxC | `cxc` | finance | — | invoices (cxc), operations | — |
| CxP/Suppliers | `cxp_compras` | finance | supplier, supplier_invoice, purchase_order, goods_receipt, purchase_credit_note | suppliers, purchase_orders | expenses |
| Banking | `banks` | finance | bank_export, bank_statement_parser | banks | — |
| Accounting | `contabilidad` | finance | accounting, accounting_export, fiscal_closing, fiscal_period, fixed_asset, financial_ratios, ledger_audit, tax_engine | accounting | accounting |
| Payroll/HR | `nomina` | hr | payroll, payroll_async, payroll_audit, payroll_concept_engine, payroll_static_data, payroll_ytd, liquidacion, hr_data, hr_notifications, mass_action, dgt, dgt_export | rrhh, dgt | liquidacion |
| Contracts | `contratos` | ops | recurrence | operations | — |
| Reports 606/607/608/623 | `reporte_606` | compliance | — | reports_606, reports_607, reports_608, reports_623 | — |
| Workflows | `gastos` | ops | approval | workflows | — |
| Budgets | `ia_bi` | enterprise | budget | budgets | — |
| Audit | `auditoria` | enterprise | audit, closing_checklist | audit, system_jobs | — |

## Business Processes at a Glance

| ID | Process | Trigger Event | Key Modules |
|----|---------|---------------|-------------|
| BP-1 | Hiring (Prospect → Active Employee) | CRM stage → Won | CRM, Sales, HR, Payroll |
| BP-2 | Payroll Cycle (Calculate → Post → DGT-3) | Period selection | Payroll, Accounting, CxP, DGT |
| BP-3 | e-CF Invoice Emission (E31/E32/E41/E43) | Invoice creation | Invoicing, DGII, Inventory, CxC, Accounting |
| BP-4 | Invoice Payment Collection (CxC) | Payment registration | CxC, Banking, Accounting |
| BP-5 | Expense with Approval Workflow (CxP) | Expense creation | CxP, Workflows, Accounting |
| BP-6 | Employee Settlement (Liquidación Ley 16-92) | Termination | HR, Payroll, Accounting |
| BP-7 | Fiscal Year Closing | Year-end trigger | Accounting, Fiscal Periods |
| BP-8 | Bank Reconciliation | Statement import | Banking, CxC, CxP |
| BP-9 | Contract Recurring Billing | APScheduler daily | Contracts, Invoicing, DGII, Accounting |
| BP-10 | Warehouse Transfer | Transfer request | Inventory, Costing |
| BP-11 | Physical Inventory Count & Adjustment | Count initiation | Inventory, Costing, Accounting |
| BP-12 | Fixed Asset Depreciation | Monthly schedule | Accounting, Fixed Assets |

### When to read process details

- User asks to "run payroll" → read `references/processes/bp-02-payroll.md`
- User asks to "emitir factura" or "e-CF" → read `references/processes/bp-03-ecf-emission.md`
- User asks about "liquidación" or "despido" → read `references/processes/bp-06-liquidacion.md`
- User asks to "cerrar el año fiscal" → read `references/processes/bp-07-fiscal-closing.md`

## AI Tool Catalog

Each tool has a complete JSON Schema in `references/tools/<tool-name>.json`.
All schemas include: parameters, type constraints, required fields, enum values,
validation rules, risk classification, required permissions, and example payloads.

| Tool | BP | Risk | Confirm | Schema File |
|------|----|------|---------|-------------|
| `start_hiring_process` | BP-1 | medium | yes | `tools/start_hiring_process.json` |
| `simulate_payroll` | BP-2 | low | no | `tools/simulate_payroll.json` |
| `calculate_payroll_period` | BP-2 | medium | yes | `tools/calculate_payroll_period.json` |
| `approve_payroll_period` | BP-2 | high | yes | `tools/approve_payroll_period.json` |
| `post_payroll_to_accounting` | BP-2 | high | yes | `tools/post_payroll_to_accounting.json` |
| `generate_dgt3_report` | BP-2 | low | no | `tools/generate_dgt3_report.json` |
| `emit_e_cf_invoice` | BP-3 | high | yes | `tools/emit_e_cf_invoice.json` |
| `validate_invoice_before_emit` | BP-3 | low | no | `tools/validate_invoice_before_emit.json` |
| `cancel_e_cf_invoice` | BP-3 | critical | yes (x2) | `tools/cancel_e_cf_invoice.json` |
| `check_dgii_status` | BP-3 | low | no | `tools/check_dgii_status.json` |
| `register_invoice_payment` | BP-4 | medium | yes | `tools/register_invoice_payment.json` |
| `register_expense_with_approval` | BP-5 | medium | yes | `tools/register_expense_with_approval.json` |
| `approve_pending_request` | BP-5 | high | yes | `tools/approve_pending_request.json` |
| `get_pending_approvals` | BP-5 | low | no | `tools/get_pending_approvals.json` |
| `calculate_employee_liquidacion` | BP-6 | high | yes | `tools/calculate_employee_liquidacion.json` |
| `preview_fiscal_closing` | BP-7 | low | no | `tools/preview_fiscal_closing.json` |
| `execute_fiscal_closing` | BP-7 | critical | yes (x2) | `tools/execute_fiscal_closing.json` |
| `reconcile_bank_account` | BP-8 | medium | yes | `tools/reconcile_bank_account.json` |
| `manage_contract_recurrence` | BP-9 | medium | yes | `tools/manage_contract_recurrence.json` |
| `manage_warehouse_transfer` | BP-10 | medium | yes | `tools/manage_warehouse_transfer.json` |
| `perform_physical_inventory_count` | BP-11 | high | yes | `tools/perform_physical_inventory_count.json` |
| `calculate_asset_depreciation` | BP-12 | low | no | `tools/calculate_asset_depreciation.json` |

## Risk Classification & Guardrails

### Critical risk — requires double confirmation + mandatory justification
Applies to operations that are fiscally or legally irreversible:
- Canceling an e-CF invoice with DGII (`cancel_e_cf_invoice`)
- Executing annual fiscal closing (`execute_fiscal_closing`)
- Deleting a posted journal entry
- Irreversibly closing a payroll period with status `cerrada`

The agent must:
1. Explain exactly what will happen and why
2. Ask the user to type a confirmation phrase (e.g., the invoice number)
3. Only proceed after receiving explicit confirmation

### High risk — requires single confirmation
- Payroll approval, payroll accounting posting, employee settlement calculation
- Workflow approval/rejection decisions
- e-CF invoice emission
- Inventory adjustment from physical count

### Medium risk — requires confirmation for write operations
- Payroll calculation, payment registration, expense registration, contract management
- Warehouse transfer approval

### Low risk — no confirmation needed (read-only)
- Simulations, queries, reports, status checks, previews

## Permissions Map

| Permission | Tools that require it |
|------------|----------------------|
| `canHR` | start_hiring_process, calculate_payroll_period, simulate_payroll, approve_payroll_period, post_payroll_to_accounting, generate_dgt3_report, calculate_employee_liquidacion |
| `canInvoice` | emit_e_cf_invoice, validate_invoice_before_emit, check_dgii_status |
| `canVoidInvoice` | cancel_e_cf_invoice |
| `canAccounting` | preview_fiscal_closing, execute_fiscal_closing, calculate_asset_depreciation, post_payroll_to_accounting |
| `canExpenses` | register_expense_with_approval, get_pending_approvals |
| `canApproveExpenses` | approve_pending_request |
| `canApprovePayments` | reconcile_bank_account |
| `canModifySettings` | manage_contract_recurrence |
| `canInventory` | manage_warehouse_transfer, perform_physical_inventory_count |

### SoD (Segregation of Duties) Conflicts

The ERP enforces these conflict pairs at the permission level:

- Creating suppliers (`canCreateSupplier`) vs approving payments (`canApprovePayments`)
- Emitting invoices (`canInvoice`) vs voiding invoices (`canVoidInvoice`)
- Managing payroll (`canHR`) vs authorizing payroll payments (`canApprovePayroll`)
- Registering expenses (`canExpenses`) vs approving expenses (`canApproveExpenses`)
- Modifying settings (`canModifySettings`) vs viewing audit logs (`canViewAuditLog`)

If the user has both permissions in a conflict pair, the agent must warn them and
suggest delegating one of the roles to another team member.

## Key Domain Events

Events are published via the Event Bus and automatically trigger handlers:

| Event | Trigger | Handler | Effect |
|-------|---------|---------|--------|
| `InvoiceEmitted` | e-CF invoice creation | `handle_invoice_emitted` | Auto-generates accounting entry (debit CxC, credit Income + ITBIS payable) |
| `ExpenseCreated` | Expense/gasto registration | `handle_expense_created` | Auto-generates accounting entry (debit Expense/ITBIS, credit CxP) |
| `PaymentRegistered` | Payment registration | `handle_payment_registered` | Logs payment, updates CxC balance |
| `AssetDepreciated` | Depreciation calculation | `handle_asset_depreciated` | Auto-generates depreciation journal entry |
| `BulkSalaryChanged` | Mass salary change | _(future)_ | Triggers payroll recalculation |
| `BulkPositionChanged` | Mass position change | _(future)_ | Updates employee records |
| `BulkPromotionApplied` | Mass promotion | _(future)_ | Updates salary and position |
| `BulkAbsenceApplied` | Mass absence | _(future)_ | Updates attendance records |

## DGII Compliance Notes

When working with Dominican e-CF (Comprobantes Fiscales Electrónicos):

- **E31 (Crédito Fiscal)**: Requires valid client RNC (9 digits). Cannot use generic RNC
  `999999999`. Validates that client RNC exists.
- **E32 (Consumo)**: For final consumers. Can use generic RNC `999999999`.
- **E41 (Gasto Menor)**: For minor expenses under RD$250,000. Simpler XML.
- **E43 (Comprobante Especial)**: For government entities and special regimes.
- **ITBIS**: Default 18%. Invoice must validate cuadratura (subtotal × rate ≈ ITBIS amount).
- **e-NCF sequencing**: Atomic counter in Firestore. Each emission consumes one sequence number.
- **Digital signing**: Uses P12 certificate via DgiiSigner. Certificate must be valid.
- **DGII API flow**: GET semilla → POST token → POST recepción (signed XML) → trackId → status poll.
- **Contingency mode**: If DGII unreachable, invoice is stored with `contingencyEmittedAt` timestamp
  and synced later via ContingencySyncService.

## TSS and ISR Reference (2026)

These rates are hardcoded in `app/services/payroll_service.py` with overrides from Firestore config:

| Concept | Employee Rate | Employer Rate | Cap |
|---------|--------------|---------------|-----|
| AFP | 2.87% | 7.10% | RD$464,460/mo |
| SFS | 3.04% | 7.09% | RD$232,230/mo |
| SRL | — | 1.20% | Same as SFS cap |
| INFOTEP | 1.00% (if income > 5× min salary) | 1.00% | No cap |
| ISR | Progressive table (4 brackets, 0-25%) | — | Annualized |

ISR Annual Table:
- RD$0 – RD$416,220: Exempt
- RD$416,220.01 – RD$624,329: 15%
- RD$624,329.01 – RD$867,123: 20% (fixed quota RD$31,216)
- RD$867,123.01+: 25% (fixed quota RD$79,775)

Minimum monthly salary: RD$23,223. Annual education deduction: RD$50,000.

ISR is calculated by annualizing the period income (×12 for monthly, ×24 for biweekly),
subtracting AFP, SFS, and education deductions, applying the progressive table,
then dividing back by the period factor.

## Labor Law Reference (Ley 16-92)

Key articles for employee settlements (`LiquidacionService`):

- **Art. 76 (Preaviso)**: 7 days (3-6 months), 14 days (6-12 months), 28 days (>1 year)
- **Art. 80 (Cesantía)**: 6 days (3-6 months), 13 days (6-12 months), 21 days/year (1-5 years), 23 days/year (>5 years)
- **Art. 85 (SDP)**: Salario Diario Promedio = average of last 12 months' salaries / 23.83
- **Art. 177, 182 (Vacaciones)**: 14 days/year (1-5 years), 18 days/year (>5 years)
- **Art. 219 (Regalía)**: 1/12 of annual salary, paid before Dec 20
- **Tax treatment**: Preaviso and cesantía are EXEMPT from TSS and ISR. Vacation pay is taxable.

## Inventory Costing Methods

Configured at the item level via `InventoryCostingService`:

- **FIFO**: Tracks cost layers in `inventory_cost_ledger` collection. Consumption
  draws from oldest layers first. `get_fifo_cost()` calculates total cost for a
  given quantity by walking the ledger.
- **Weighted Average**: `get_weighted_average_cost()` = Σ(qty_in × unit_cost) / Σ(qty_in)
- **Standard**: Uses `costPrice` field directly from the item.

## Reading Guide by User Task

| User says... | Read these files |
|-------------|-----------------|
| "How does the ERP work?" | This file + `references/architecture/overview.md` |
| "Calculate payroll for July" | `references/processes/bp-02-payroll.md` + `tools/calculate_payroll_period.json` |
| "Emit an invoice for client X" | `references/processes/bp-03-ecf-emission.md` + `tools/emit_e_cf_invoice.json` |
| "Register this payment" | `references/processes/bp-04-payment.md` + `tools/register_invoice_payment.json` |
| "Approve pending expense" | `references/processes/bp-05-expense-approval.md` + `tools/approve_pending_request.json` |
| "Calculate termination pay" | `references/processes/bp-06-liquidacion.md` + `tools/calculate_employee_liquidacion.json` |
| "Close fiscal year 2025" | `references/processes/bp-07-fiscal-closing.md` + `tools/execute_fiscal_closing.json` |
| "Reconcile bank account" | `references/processes/bp-08-reconciliation.md` + `tools/reconcile_bank_account.json` |
| "Transfer stock between warehouses" | `references/processes/bp-10-warehouse-transfer.md` + `tools/manage_warehouse_transfer.json` |
| "Do physical inventory count" | `references/processes/bp-11-physical-count.md` + `tools/perform_physical_inventory_count.json` |
