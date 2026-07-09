# BP-2: Ciclo de Nómina Completo

## Overview

El ciclo de nómina procesa el cálculo de salarios, descuentos TSS, ISR, aportes
patronales, y transita por un workflow de 7 estados hasta su cierre, culminando
con la generación del DGT-3.

## Actors

- **Usuario de RRHH**: inicia el período, ejecuta cálculo, solicita aprobación
- **Aprobador**: revisa y aprueba la nómina (rol con `canApprovePayroll`, SoD: no
  puede ser quien la calculó si también tiene `canHR`)
- **Contador**: contabiliza la nómina aprobada (`canAccounting`)
- **Sistema**: ejecuta cálculos automáticos y EventBus

## Prerequisites

- Payroll group must exist and be active (`PayrollGroup.isActive = True`)
- Employees assigned to the group with `payrollGroupIds` containing the group ID
- Employees must have status = `activo`
- Employees must have valid: `baseSalary`, `salaryType`, `tssKey`, `afpProvider`
- Tax rates configured (or defaults from `PayrollService.get_rates()`)
- Chart of accounts with payroll-specific accounts configured

## State Machine

```
borrador → calculada → validada → aprobada → contabilizada → pagada → cerrada
    │          │           │          │            │           │        │
    │          │           │          │            │           │        └─ irreversible
    │          │           │          │            │           └─ marks payment date
    │          │           │          │            └─ generates journal entry
    │          │           │          └─ sets approvedBy, approvedAt
    │          │           └─ sets validatedBy, validatedAt
    │          └─ populates payroll lines with calculations
    └─ initial state, editable
```

## Flow Steps

### Step 1: Create Period
- Select `payrollGroupId` and `periodKey` (e.g., "2026-07")
- Determine `periodType`: "mensual" or "quincenal"
- Set `startDate` and `endDate`
- Initial state: `borrador`

### Step 2: Load Active Employees
- Query employees where `status = "activo"` and `payrollGroupIds` contains the group ID
- Create snapshot in `employeeSnapshot` for DGT-3 later

### Step 3: Calculate Payroll Lines
For each employee, `PayrollService.calculate_payroll_line()` computes:

**Income**:
- `grossSalary` = base salary (or prorated if partial period)
- `overtimePay` = (base_salary / 23.83 / 8) × 1.35 × overtime_hours
- `commission`, `bonus`, `otherIncome`
- `totalIncome` = sum of all income

**TSS Deductions** (capped):
- `afpEmployee` = min(totalIncome, AFP_CAP) × 2.87%
- `sfsEmployee` = min(totalIncome, SFS_CAP) × 3.04%
- `infotepEmployee` = totalIncome × 1% if totalIncome > 5 × min_salary

**ISR** (annualized progressive):
- Annualize: gross × period_factor (12 monthly, 24 biweekly)
- Deduct: afp × period_factor + sfs × period_factor + education (max 50,000/yr)
- Apply progressive table:
  - 0-416,220: exempt
  - 416,220-624,329: 15%
  - 624,329-867,123: 20% + fixed 31,216
  - 867,123+: 25% + fixed 79,775
- Divide by period_factor for monthly ISR

**Employer Contributions** (expense, not deducted from employee):
- `afpEmployer` = min(totalIncome, AFP_CAP) × 7.10%
- `sfsEmployer` = min(totalIncome, SFS_CAP) × 7.09%
- `srlEmployer` = min(totalIncome, SFS_CAP) × 1.20%
- `infotepEmployer` = totalIncome × 1%

**Net**: `netSalary` = totalIncome - totalDeductions

### Step 4: Simulate (optional, read-only)
- Run calculation without persisting
- Show totals: `totalGross`, `totalNet`, `totalEmployerContrib`
- User can adjust overtime, commissions before committing

### Step 5: Validate
- State → `validada`
- Records `validatedBy`, `validatedAt`
- Freezes payroll lines

### Step 6: Approve
- State → `aprobada`
- Records `approvedBy`, `approvedAt`
- Requires permission: `canApprovePayroll` (SoD: not the calculator)

### Step 7: Post to Accounting
- Generate journal entry debiting salary expense accounts per cost center
  and crediting payable/retention accounts
- Account mapping from `PayrollService.get_rates()`:
  - Debit: cost center accounts (6.2.1.01, 6.2.1.01.01 for sales, etc.)
  - Credit: Salaries Payable (2.1.2.1.02)
  - Credit: AFP Employee Payable (2.1.2.1.05)
  - Credit: SFS Employee Payable (2.1.2.1.06)
  - Credit: ISR Payable (2.1.2.1.08)
- State → `contabilizada`

### Step 8: Pay
- Records `paidDate` — no journal entry, just marks as paid
- State → `pagada`

### Step 9: Close
- State → `cerrada` (irreversible)
- Records `closedBy`, `closedAt`

### Step 10: Generate DGT-3
- Uses `employeeSnapshot` to generate DGT-3 lines
- Each line: document type, ID, name, salary, nationality, occupation code
- Export format: SIRLA flat file (22 fields per line)

## AI Guardrails for this Process

- `simulate_payroll`: safe, no persistence, no confirmation needed
- `calculate_payroll_period`: writes payroll lines, requires confirmation
- `approve_payroll_period`: SoD check — verify the approver is not the calculator
- `post_payroll_to_accounting`: generates journal entries, high risk, requires confirmation
- `generate_dgt3_report`: read-only export, safe

## Related Files
- `app/services/payroll_service.py` — calculation engine
- `app/services/payroll_concept_engine.py` — concept definitions
- `app/services/payroll_async_service.py` — async processing
- `app/services/payroll_audit_service.py` — audit trail
- `app/services/payroll_ytd_service.py` — year-to-date aggregation
- `app/services/dgt_service.py` — DGT form generation
- `app/models/employee.py` — PayrollPeriod, PayrollLine, PayrollGroup
- `app/web/rrhh.py` — HR web routes
