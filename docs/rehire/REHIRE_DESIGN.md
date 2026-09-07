# Reincorporación de empleados — Diseño (VykOne RRHH)

> `Employee` representa actualmente la identidad y snapshot operativo,
> mientras `EmploymentContract` representa cada período laboral.

## 1. Modelo de datos

### EmploymentContract (período laboral, fuente de verdad de períodos nuevos)

Campos nuevos:

```text
periodNumber: int            # 1, 2, 3... por empleado
origin: initial_hire|rehire|contract_change|legacy
previousContractId: str
rehireRequestId: str         # idempotency key
closedAt: str                # ISO cierre
seniorityPolicy: reset|preserve
seniorityBaseDate: YYYY-MM-DD (reset=startDate, preserve=fecha explícita)
vacationPolicy: reset|preserve
vacationBaseDate: YYYY-MM-DD
positionId, departmentId, reportsTo, paymentMethod, bank, accountNumber,
accountType, variableSalary, workLocation
```

Regla: nunca inferir bases desde `Employee.hireDate`. Siempre explícitas.

### Employee (identidad + snapshot operativo temporal)

```text
currentEmploymentContractId: str  # "" = legacy
```

Snapshot (`hireDate`, `baseSalary`, `position`, ...) = copia de la relación activa
para compatibilidad. La fuente del período es el contrato.

### Otros modelos con contractId (Fase 2.5)

- `SalaryHistory.contractId`
- `VacationRequest.contractId`, `LeaveRequest.contractId`
- `PayrollLine.contractId`
- `RecurringMovement.contractId` + `sourceMovementId` + `carryToRehire`
- `RecurringApplication.contractId`
- `LiquidacionOutput.contractId`

Frontera:

```text
NUEVO (desde rehire) → contractId obligatorio (cuando aplique)
LEGACY               → contractId = "" con fallback a employeeId
```

## 2. Flujo

```text
HTTP (employees.py / offboarding.py)
  → RehireService.rehire_employee()
    → validar empleado (existe, status=inactivo)
    → validar 0 contratos activos (bloquear si >1)
    → previous = último terminado (o virtual legacy sin crear registros)
    → validar startDate > previous.endDate
    → bloquear offboarding abierto
    → resolver policies + baseDates determinísticas
    → crear NUEVO EmploymentContract (origin=rehire)
    → snapshot Employee (status=activo, currentEmploymentContractId, limpiar baja)
    → salary_history con contractId
    → copiar movimientos SOLO selección explícita (préstamos nunca)
    → auditoría rehire + employment_history hito
```

## 3. Reglas

- Misma persona: mismo `employee.id`, mismo `code`.
- Relación anterior: intacta, `terminado`.
- Nueva relación: `activo`, nuevo `contractId`, `periodNumber = max+1`.
- Movimientos: no auto-copia. Préstamo liquidado nunca reaparece.
- Vacaciones: histórico intacto; nuevo período desde `vacationBaseDate`.
- Antigüedad: desde `seniorityBaseDate`.
- Nómina: elegible si `contract.startDate <= period.endDate`; sin retroactivos
  (filtro por `hireDate` snapshot + períodos cerrados bloqueados por secuencia).
- Idempotencia: `rehireRequestId` único → `get_contract_by_rehire_request`.

## 4. Validaciones

| Caso | Resultado |
|---|---|
| empleado inexistente | RECHAZADO (employee_not_found) |
| activo/vacaciones/licencia/suspendido | RECHAZADO (employee_active) |
| estado distinto de inactivo | RECHAZADO (invalid_status) |
| 1 contrato activo | RECHAZADO (active_contract_exists) |
| >1 contratos activos | BLOQUEAR (multiple_active_contracts) |
| fecha inválida | RECHAZADO (invalid_date) |
| start <= prev.end | RECHAZADO (invalid_date_order) |
| offboarding abierto | RECHAZADO (offboarding_open) |
| preserve sin base explícita | RECHAZADO (missing_*_base) |
| doble envío mismo rehireRequestId | REUTILIZA contrato existente |

## 5. Contratos

Helpers (`hr_data_service`):

- `get_contracts_for_employee` (ordenado por periodNumber/startDate)
- `get_last_terminated_contract`
- `get_next_contract_period_number`
- `get_contract_by_rehire_request` (idempotencia)
- `get_active_contract_for_employee`
- `resolve_employee_contract_id` (currentEmploymentContractId → contractId → "")
- `get_employment_context` (¿empleado o relación?)

## 6. Nómina

- Nuevas líneas: `contractId = resolve_employee_contract_id(emp)`.
- Transacciones recurrentes: filtran por contrato
  (`contractId` específico solo a su contrato; legacy `""` a todos).
- Aplicaciones: guardan `contractId`.
- YTD: clave `employeeId + contractId + year` (ya soportada).
- Elegibilidad: excluir si `hireDate > period.endDate`.

## 7. Vacaciones

- Nuevas solicitudes guardan `contractId`.
- Saldo con `vacationBaseDate` cuando hay contrato activo.
- Con `vacationPolicy=reset`: solo cuenta solicitudes del contrato actual
  (o legacy con `startDate >= vacationBaseDate`); histórico anterior intacto.

## 8. Prestaciones

- `calcular_liquidacion(..., contract_id="")` → guarda `contractId`.
- Ruta web usa `seniorityBaseDate` del contrato activo como `hire_date`
  y salario del contexto; snapshots históricos intactos.

## 9. Movimientos

- Formulario rehire sugiere no-préstamos activos/programados.
- Copia crea nuevo doc con `contractId` nuevo + `sourceMovementId`.
- `apply_recurring_for_employee` filtra por contrato.

## 10. Auditoría

`log_action("rehire", "employee", employee_id, ...)` con:

```text
previousContractId, newContractId, periodNumber,
previousHireDate, newHireDate,
seniorityPolicy/BaseDate, vacationPolicy/BaseDate,
copiedMovements, rehireRequestId
+ before/after del snapshot
```

Más hito en `employment_history` (`changeType=rehire`).

## 11. Migración

- NO masiva. Solo `scripts/rehire_migration_dry_run.py` (solo lectura).
- Reporta empleados/contratos, múltiples activos, sin contrato, huérfanos,
  vacaciones/licencias/liquidaciones/movimientos/nóminas/salarios sin contractId.
- Legacy ambiguo: no inventar relación; `contractId=""`.

## 12. Compatibilidad legacy

- Todos los consumidores nuevos usan `resolve_employee_contract_id` /
  `get_employment_context` con fallback.
- Reporte aniversario usa `seniorityBaseDate` cuando hay contrato.
- DGT/TSS/exportadores no cambian formato; solo origen de snapshot.

## 13. Permisos

- `AUTHORIZATION_DOC_TYPES["rehire"] = "Reincorporación de empleado"`.
- Rutas exigen login (patrón actual); el tipo específico permite configurar
  quorum/aprobadores sin reutilizar `employee_edit`.

## 15. Formulario de reincorporación

- Solo se listan grupos de nómina **activos** (`isActive`); un inactivo no puede
  recibir la nueva relación.
- La acción **Reincorporación** aparece en el menú "Acciones de personal" de la
  ficha (solo si `status == inactivo`), además del botón del encabezado; la
  auditoría `rehire` conserva el histórico en el timeline.
- El formulario acepta documentos adjuntos (`rehireDocs`, múltiple, 10MB c/u):
  se guardan como documentos del empleado con `category="contract"` y
  `contractId` del **nuevo** período, visibles en la pestaña Documentos.
- El tab Documentos lista todos los documentos del empleado (sin filtros) y
  distingue los de reincorporación con insignia
  "Reincorporación · Período N" más la nota guardada.

## 14. Aislamiento contractual de nómina y prestaciones

- `EmploymentContextService` (`app/services/employment_context_service.py`) es el
  resolver único: contrato por ID, activo único, o correspondiente a una fecha
  de salida (exacto → vigente → pasado reciente). Ambigüedad → error, nunca
  elección silenciosa. Sin contrato → fallback legacy (`employeeId` + fechas).
- Transacciones: `get_payroll_transactions(..., contract_id, start_date, end_date)`
  y `filter_transactions()` aíslan al período (match `contractId` + legacy
  dentro del rango por `periodKey`); el histórico anterior al rehire queda fuera.
- `calcular_salario_promedio_mensual(..., contract_id, start_date, end_date)`
  filtra antes de agrupar y su clave de deduplicación incluye `contractId`.
- `calcular_liquidacion(..., employment_context, salary_transactions_used)`
  guarda snapshot: `contractPeriodNumber`, `employmentStartDate/EndDate`,
  `seniorityBaseDate`, `vacationBaseDate`, `contractSnapshot`,
  `salaryTransactionsUsed`, `calculationVersion`.
- Rutas `liquidacion.py`, `offboarding.py` (cálculo y wizard) y API
  `/labor/settlement` resuelven el contrato por fecha de salida, usan su
  salario/`seniorityBaseDate` y filtran transacciones y recurrentes.
- Pagos: `mark_settlement_paid` rechaza liquidación ya pagada o pago duplicado
  (misma liquidación/versión) y propaga `settlementId/employeeId/contractId`;
  guard `pending_payment → pending_documents` exige pago registrado.
- Recalcular preserva `previousVersionId` e incrementa `version`.

## 15. Pregunta guía para código nuevo

```text
¿Esto representa al empleado (identidad) o a una relación laboral?
  → identidad: Employee (id, code, nombre, docs personales)
  → relación:  EmploymentContract (fechas, salario, puesto, políticas)
```
