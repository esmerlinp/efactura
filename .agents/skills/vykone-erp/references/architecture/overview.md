# VykOne Architecture Reference

## Directory Structure

```
e-FacturaWeb/
├── app.py                    # Entry point — creates Flask app via factory
├── config.py                 # Configuration from .env, DGII endpoints, CSRF, CORS
├── requirements.txt          # 80+ dependencies
├── app/
│   ├── __init__.py           # create_app() factory, blueprint registration, middleware
│   ├── api/v1/               # REST API (9 blueprints)
│   │   ├── accounting.py     # /api/v1/accounting/*
│   │   ├── auth.py           # /api/v1/auth/*
│   │   ├── clients.py        # /api/v1/clients/*
│   │   ├── dgii.py           # /api/v1/dgii/*
│   │   ├── expenses.py       # /api/v1/expenses/*
│   │   ├── invoices.py       # /api/v1/invoices/*
│   │   ├── liquidacion.py    # /api/v1/liquidacion/*
│   │   ├── metadata.py       # /api/v1/metadata/*
│   │   └── prospects.py      # /api/v1/prospects/*
│   ├── web/                  # Web UI Blueprints (33 files)
│   │   ├── accounting.py     # Chart of accounts, journal entries, financial statements
│   │   ├── audit.py          # Audit log viewer
│   │   ├── auth.py           # Login, register, profile, MFA, password reset
│   │   ├── banks.py          # Bank accounts, reconciliations
│   │   ├── bi.py             # BI drilldown
│   │   ├── budgets.py        # Budget management
│   │   ├── clients.py        # Client management, insights
│   │   ├── contacts.py       # Contact/lead management
│   │   ├── crm.py            # CRM pipeline, opportunities, activities
│   │   ├── dashboard.py      # Main dashboard with KPIs
│   │   ├── dgt.py            # DGT forms (Ministry of Labor)
│   │   ├── fiscal_notes.py   # Fiscal note sequences
│   │   ├── i18n.py           # Internationalization
│   │   ├── import_mapper.py  # CSV/Excel data import
│   │   ├── inventory.py      # Inventory management, items, stock
│   │   ├── invoices.py       # Invoices, quotations, expenses, CxC
│   │   ├── notes.py          # Credit/debit notes
│   │   ├── notifications.py  # User notifications
│   │   ├── operations.py     # Contracts, commissions
│   │   ├── portal.py         # Client portal
│   │   ├── pos.py            # Point of Sale
│   │   ├── purchase_orders.py# Purchase orders
│   │   ├── reports_606.py    # DGII 606 report (purchases)
│   │   ├── reports_607.py    # DGII 607 report (sales)
│   │   ├── reports_608.py    # DGII 608 report (withholdings)
│   │   ├── reports_623.py    # DGII 623 report
│   │   ├── reports_sales.py  # Sales reports
│   │   ├── rrhh.py           # HR: employees, payroll, attendance
│   │   ├── suppliers.py      # Supplier management
│   │   ├── system_jobs.py    # Background job monitoring
│   │   ├── vykcore.py        # Internal routes
│   │   └── workflows.py      # Approval workflow management
│   ├── services/             # Domain services (60+ files)
│   │   ├── accounting_service.py       # Journal entries, auto-generation, trial balance, financial statements
│   │   ├── accounting_export_service.py# Export to external accounting systems
│   │   ├── aggregation_service.py      # Dashboard KPI aggregation
│   │   ├── ai_classifier_service.py    # AI-based document classification
│   │   ├── ai_quotation_service.py     # AI-powered quotation generation
│   │   ├── ai_service.py               # Chatbot/AI assistant
│   │   ├── approval_service.py         # Workflow approval engine
│   │   ├── audit_service.py            # Audit trail
│   │   ├── azul_service.py             # Azul payment gateway integration
│   │   ├── bank_export_service.py      # Bank statement export
│   │   ├── bank_statement_parser.py    # Bank statement import/parsing
│   │   ├── bi_drilldown_service.py     # BI deep-dive analytics
│   │   ├── budget_service.py           # Budget planning
│   │   ├── cache_service.py            # Caching utilities
│   │   ├── cash_flow_service.py        # Cash flow projections
│   │   ├── chatbot.py                  # Chatbot logic
│   │   ├── closing_checklist_service.py # Month-end closing checklist
│   │   ├── contact_service.py          # Contact management
│   │   ├── contingency_sync_service.py # DGII contingency sync
│   │   ├── crm_service.py              # CRM operations (289KB)
│   │   ├── db_service.py               # Firestore CRUD (289KB)
│   │   ├── dgii.py                     # DGII integration (legacy)
│   │   ├── dgii_direct.py              # DGII direct REST API
│   │   ├── dgii_signer.py              # XML digital signing (P12)
│   │   ├── dgii_xml_builder.py         # e-CF XML construction
│   │   ├── dgt_export_service.py       # DGT export utilities
│   │   ├── dgt_service.py              # DGT form generation
│   │   ├── ecf_emission.py             # e-CF emission orchestration
│   │   ├── excel_export_service.py     # Excel report generation
│   │   ├── financial_ratios_service.py # Financial ratio calculation
│   │   ├── fiscal_closing_service.py   # Year-end fiscal closing
│   │   ├── fiscal_period_service.py    # Fiscal period management
│   │   ├── fixed_asset_service.py      # Fixed asset management
│   │   ├── goods_receipt_service.py    # Goods receipt (PO fulfillment)
│   │   ├── hr_data_service.py          # HR data management
│   │   ├── hr_notifications.py         # HR email notifications
│   │   ├── i18n_service.py             # Translation service
│   │   ├── inventory_alert_service.py  # Low stock alerts
│   │   ├── inventory_costing_service.py# FIFO, Weighted Avg, Standard costing
│   │   ├── job_service.py              # Background job management
│   │   ├── ledger_audit_service.py     # Accounting ledger audit
│   │   ├── liquidacion_service.py      # Employee settlement (Ley 16-92)
│   │   ├── mailer.py                   # Email sending (SMTP/Graph API)
│   │   ├── mass_action_service.py      # Bulk HR operations
│   │   ├── multi_currency_service.py   # Multi-currency support
│   │   ├── notifications.py            # In-app notification engine
│   │   ├── ocr_service.py              # OCR document scanning
│   │   ├── payment_scheduler_service.py# Payment scheduling
│   │   ├── payroll_async_service.py    # Async payroll processing
│   │   ├── payroll_audit_service.py    # Payroll audit trail
│   │   ├── payroll_concept_engine.py   # Payroll concept definitions
│   │   ├── payroll_service.py          # Payroll calculation engine (TSS/ISR)
│   │   ├── payroll_static_data.py      # Payroll static configuration
│   │   ├── payroll_ytd_service.py      # Year-to-date payroll aggregation
│   │   ├── physical_count_service.py   # Physical inventory counting
│   │   ├── purchase_credit_note_service.py # Purchase credit notes
│   │   ├── purchase_order_service.py   # Purchase order management
│   │   ├── recurrence.py               # Recurrence engine (contracts/invoices)
│   │   ├── scheduler.py                # APScheduler jobs
│   │   ├── state_machine.py            # State machine for workflows
│   │   ├── supplier_invoice_service.py # Supplier invoice processing
│   │   ├── supplier_service.py         # Supplier management
│   │   ├── tax_engine.py               # Tax calculation engine
│   │   ├── warehouse_transfer_service.py # Warehouse transfers
│   │   ├── webhook_service.py          # Webhook dispatching
│   │   └── xml_import_service.py       # XML import (DGII responses)
│   ├── models/               # Pydantic domain models
│   │   ├── accounting.py     # JournalEntry, JournalEntryLine, ChartAccount, FixedAsset, FiscalPeriod
│   │   ├── bank.py           # BankAccount, BankReconciliation, BankReconciliationTransaction
│   │   ├── contact.py        # Contact/Client
│   │   ├── crm.py            # CRMOpportunity, CRMActivity, CRMAutomationRule
│   │   ├── dgt.py            # DGTLine, DGT3Report, DGT4Report, DGT4Change, DGT9Suspension, etc.
│   │   ├── employee.py       # Employee, PayrollPeriod, PayrollLine, PayrollGroup, Evaluation, Training, etc.
│   │   ├── expense.py        # Expense, CxPPayment
│   │   ├── inventory.py      # LotBatch, SerialNumber, WarehouseTransfer, PhysicalCount
│   │   ├── invoice.py        # Invoice, InvoiceItem, InvoicePayment, InvoiceInstallment
│   │   └── liquidacion.py    # LiquidacionInput, LiquidacionOutput, ConceptoResult, Antiguedad, Totales
│   ├── repositories/         # Firestore typed access layer
│   │   ├── base.py           # BaseRepository with CRUD over Firestore
│   │   ├── accounting_repository.py
│   │   ├── bank_repository.py
│   │   ├── contact_repository.py
│   │   └── invoice_repository.py
│   ├── events/               # Domain Event Bus
│   │   ├── event_bus.py      # Hybrid in-process/Redis pub/sub
│   │   ├── events.py         # DomainEvent, InvoiceEmitted, PaymentRegistered, etc.
│   │   ├── handlers.py       # Accounting auto-generation handlers
│   │   └── setup.py          # Bus initialization and handler registration
│   └── utils/                # Cross-cutting utilities
│       ├── decorators.py     # check_permission, require_permission, SoD matrix
│       ├── module_gate.py    # Module enablement checks
│       ├── security.py       # File validation, Fernet encryption, portal tokens
│       └── cache_utils.py    # Caching helpers
├── templates/                # Jinja2 HTML templates
├── static/                   # Static assets (CSS, JS, images)
├── tests/                    # Test suite
└── docs/                     # Documentation
```

## Layer Dependency Flow

```
HTTP Request
    │
    ├─► Web Blueprint (app/web/*.py)
    │       │
    │       ├─► @require_permission decorator → check_permission() → SoD matrix
    │       ├─► @require_module decorator → module_gate.module_enabled()
    │       └─► Service layer (app/services/*.py)
    │               │
    │               ├─► Firestore via DatabaseService.get_*/save_*/delete_*
    │               │       │
    │               │       └─► Firebase Admin SDK → Firestore (users/{uid}/collections)
    │               │
    │               ├─► EventBus.publish(event) → handlers (async threads)
    │               │       │
    │               │       └─► Accounting auto-generation
    │               │           Payment status updates
    │               │
    │               └─► External integrations
    │                       ├─► DGII REST API (auth → recepción → status)
    │                       ├─► SMTP / Microsoft Graph API (emails)
    │                       ├─► OpenAI API (chatbot)
    │                       └─► Azul Payment Gateway
    │
    └─► API Blueprint (app/api/v1/*.py)
            │
            ├─► @require_auth decorator → Firebase token verification
            └─► Service layer (same as above)
```

## Event Bus Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Event Bus                               │
│                                                              │
│  Publishers                     Subscribers                  │
│  ─────────                      ───────────                  │
│  InvoiceEmitted ──────────► handle_invoice_emitted           │
│  (ecf_emission.py)           └─► AccountingService           │
│                                   .auto_generate_invoice_entry│
│                                                              │
│  ExpenseCreated ──────────► handle_expense_created           │
│  (expense creation)          └─► AccountingService           │
│                                   .auto_generate_expense_entry│
│                                                              │
│  PaymentRegistered ───────► handle_payment_registered        │
│  (payment registration)      └─► Log + future: journal entry │
│                                                              │
│  AssetDepreciated ────────► handle_asset_depreciated         │
│  (fixed_asset_service)       └─► AccountingService           │
│                                   .auto_generate_depreciation│
│                                                              │
│  BulkSalaryChanged ───────► (future handler)                 │
│  BulkPositionChanged ─────► (future handler)                 │
│  BulkSupervisorChanged ───► (future handler)                 │
│  BulkPromotionApplied ────► (future handler)                 │
│  BulkAbsenceApplied ──────► (future handler)                 │
└─────────────────────────────────────────────────────────────┘
```

Modes:
- **In-process**: Handlers run in daemon threads. Default for development.
- **Redis Pub/Sub**: Events published to `vykone:events:<EventType>` channels.
  Handlers run in separate workers. For production multi-process.

## Permission Model

Roles: `owner` (full access, subject to SoD) or `member` (granular).

SoD (Segregation of Duties) conflict matrix from `app/utils/decorators.py`:
- `canCreateSupplier` ↔ `canApprovePayments`
- `canInvoice` ↔ `canVoidInvoice`
- `canHR` ↔ `canApprovePayroll`
- `canExpenses` ↔ `canApproveExpenses`
- `canModifySettings` ↔ `canViewAuditLog`

## Multi-Tenancy & Environment Isolation

```
Firestore Structure:
users/
  {owner_uid}/
    config/profile           — company profile, plan, branding
    config/modules           — enabled modules per plan
    config/approval_rules    — workflow approval rules
    sandbox_invoices/        — sandbox environment collections
    sandbox_expenses/
    sandbox_accounting_entries/
    sandbox_payroll_periods/
    sandbox_employees/
    invoices/                — production environment collections
    expenses/
    accounting_entries/
    payroll_periods/
    employees/
    approval_requests/
    clients/
    items/
    contacts/
    contracts/
    bank_accounts/
    chart_of_accounts/
    ...
```

The `is_sandbox_mode` session flag determines which prefixed collections to use.
All services accept a `sandbox=True` parameter.
