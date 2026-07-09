# BP-5: Compra/Gasto con Aprobación (CxP)

## Overview

Registro de gastos/compras con integración al motor de workflows de aprobación.
El ApprovalService evalúa reglas configurables por tipo de documento y monto
para determinar si un gasto requiere aprobación antes de contabilizarse.

## Flow

```
Registrar gasto → ApprovalService.check_needs_approval(owner_uid, "expense", amount)
  ├─ No requiere aprobación → Guardar con approvalStatus="Aprobado"
  │                           → EventBus: ExpenseCreated
  │                           → Asiento contable automático
  └─ Sí requiere aprobación → Guardar con approvalStatus="Pendiente"
                              → Crear approval_request
                              → Notificar aprobadores
                              → Esperar decisiones
                                ├─ Aprobado → approvalStatus="Aprobado"
                                │            → EventBus: ExpenseCreated
                                │            → Asiento contable automático
                                └─ Rechazado → approvalStatus="Rechazado"
                                              → Sin asiento contable
```

## Approval Rules

Rules are stored per owner_uid in `approval_rules` collection. Each rule specifies:
- `document_type`: "expense", "purchase_order", or "supplier_invoice"
- `min_amount`: threshold above which approval is required
- `approvers`: list of {id, name, email}
- `require_all`: if true, ALL approvers must approve. If false, ANY one approval suffices
- `is_active`: enable/disable the rule

The system finds the rule with the highest min_amount ≤ the expense amount
for the matching document_type.

## Approval Request Lifecycle

```
pending → (approver decides) → approved | rejected
                                 │
                                 └─ apply_decision_to_document()
                                    ├─ expense: sets approvalStatus + approvedBy
                                    └─ purchase_order: calls PurchaseOrderService.update_status()
```

## Document Types

| Type | Description | Triggers accounting on |
|------|-------------|----------------------|
| `expense` | General expense/gasto | ExpenseCreated |
| `purchase_order` | Purchase order | Manual (via PO workflow) |
| `supplier_invoice` | Supplier invoice | Manual |

## Accounting Entry (auto-generated on approval)

When `ExpenseCreated` event fires, `handle_expense_created` calls
`AccountingService.auto_generate_expense_entry()`:

- **Debit**: Expense account (based on category/tipo_gasto_dgii) + ITBIS creditable (if deductible)
- **Credit**: Accounts Payable (CxP)

## Related Files
- `app/services/approval_service.py` — ApprovalService
- `app/web/workflows.py` — Workflow UI and decision endpoints
- `app/events/handlers.py` — handle_expense_created
- `app/services/accounting_service.py` — auto_generate_expense_entry
