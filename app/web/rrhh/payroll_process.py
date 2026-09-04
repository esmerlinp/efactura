"""RRHH module — auto-extracted."""
"""Payroll processing — refactored with ConceptEngine, RecurringService, PayrollTransaction."""

import uuid
from datetime import date, datetime, timezone
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
    get_locked_periods,
)
from app.services import hr_data_service as hr
from app.services.payroll_service import PayrollService
from app.services.payroll_ytd_service import get_ytd, save_ytd, accumulate_ytd
from app.services.payroll_static_data import DEFAULT_PAYROLL_CONFIG
from app.services.payroll_audit_service import log_action
from app.services.overtime_service import OvertimeService
from app.services.payroll_overtime_calculator import PayrollOvertimeCalculator
from app.services.payroll_variable_catalog import (
    EXTRA_OTHER_INCOME_CONCEPTS as _EXTRA_OTHER_INCOME_CONCEPTS,
    EXTRA_OTHER_DEDUCTION_CONCEPTS as _EXTRA_OTHER_DEDUCTION_CONCEPTS,
)


def _resolve_rule_concept_code(action: dict) -> str | None:
    """Resuelve el código de concepto para una acción de regla.

    Si la acción tiene 'conceptCode' explícito, lo usa.
    Si no, usa el mapeo por defecto según el action_type.
    """
    concept_code = action.get("conceptCode", "")
    if concept_code:
        return concept_code
    action_type = action.get("type", "")
    return {
        "set_bonus": "BONIFICACION",
        "set_commission": "COMISION",
        "set_deduction": "OTRAS_DEDUCCIONES",
        "set_overtime_rate": "HORAS_EXTRA",
        "set_other_income": "OTROS_INGRESOS",
        "set_other_deduction": "OTRAS_DEDUCCIONES",
    }.get(action_type)


def _months_worked_in_year(hire_date_str: str, today: date | None = None) -> int:
    """Meses trabajados en el año en curso según fecha de ingreso (regalía pascual)."""
    today = today or date.today()
    if not hire_date_str:
        return 12
    try:
        hire_date_obj = datetime.strptime(hire_date_str[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return 12
    if hire_date_obj.year == today.year:
        return max(1, today.month - hire_date_obj.month + 1)
    return 12


def _should_skip_christmas_rule(rule: dict, include_christmas: bool) -> bool:
    """Evita doble conteo: la regla auto-generada de regalía se omite cuando la
    regalía ya se incluye explícitamente (checkbox o tipo de nómina Regalía Pascual)."""
    return include_christmas and rule.get("generatedBy") == "christmas_bonus"


def _editor_tabs(company_id: str, sandbox: bool = True) -> tuple:
    """Tabs dinámicos del editor (desde conceptos activos isManualEntry), con fallback al catálogo."""
    from app.services.payroll_variable_catalog import INGRESO_TABS, DESCUENTO_TABS
    try:
        from app.services.payroll_concept_engine import get_editor_tabs
        ing, dec = get_editor_tabs(company_id, sandbox=sandbox)
        if ing or dec:
            return ing, dec
    except Exception:
        pass
    return list(INGRESO_TABS), list(DESCUENTO_TABS)


def build_manual_other_income(transactions: list) -> float:
    """Ingresos no clasificados en columnas propias (otros ingresos + conceptos custom).

    Excluye: salario base, horas extra, comisión, bonificación, regalía,
    movimientos recurrentes y generados por reglas (se muestran en columnas dinámicas).
    """
    from app.services.payroll_variable_catalog import CLASSIFIED_EARNING_CONCEPTS
    total = 0.0
    for t in transactions:
        if t.get("type") != "earning":
            continue
        if t.get("isRecurring") or t.get("isRuleGenerated"):
            continue
        if t.get("conceptCode") in CLASSIFIED_EARNING_CONCEPTS:
            continue
        total += float(t.get("amount", 0) or 0)
    return round(total, 2)


def build_manual_other_deductions(transactions: list) -> float:
    """Deducciones manuales (otras deducciones + conceptos custom de descuento).

    Excluye: TSS/ISR, embargos, movimientos recurrentes y generados por reglas.
    """
    from app.services.payroll_variable_catalog import TSS_ISR_DEDUCTION_CONCEPTS
    total = 0.0
    for t in transactions:
        if t.get("type") != "deduction":
            continue
        if t.get("isRecurring") or t.get("isRuleGenerated"):
            continue
        if t.get("source", "") == "garnishment":
            continue
        if t.get("conceptCode") in TSS_ISR_DEDUCTION_CONCEPTS:
            continue
        total += float(t.get("amount", 0) or 0)
    return round(total, 2)


def _build_christmas_preview(employees: list) -> list:
    """Vista previa de regalía pascual por empleado (para pre-llenar el tab Regalía)."""
    preview = []
    try:
        for emp in employees:
            if emp.get("isLiquidation"):
                continue
            base = float(emp.get("baseSalary", 0) or 0)
            if base <= 0:
                continue
            months = _months_worked_in_year(emp.get("hireDate", ""))
            amount = PayrollService.calculate_christmas_bonus(base, months)
            if amount > 0:
                preview.append({"employeeId": emp.get("id", ""), "amount": amount})
    except Exception:
        pass
    return preview


def _load_existing_period_variables(company_id: str, period_key: str, group_id: str,
                                    sandbox: bool = True) -> list:
    """Variables manuales guardadas de un período existente en borrador."""
    if not period_key:
        return []
    from app.services import hr_data_service as hr
    try:
        if group_id:
            ref = hr.get_payroll_period_by_key_and_group(company_id, period_key, group_id, sandbox=sandbox)
        else:
            ref = hr.get_payroll_period_by_key(company_id, period_key, sandbox=sandbox)
        if ref and ref.get("status") == "borrador":
            return PayrollService.get_period_manual_variables(ref["id"], company_id, sandbox=sandbox)
    except Exception as e:
        print(f"⚠️ Error cargando variables del período existente: {e}")
    return []


def _extract_variable_values(form, emp_ids):
    """Extrae variables de nómina del formulario.

    Acepta entradas genéricas `var_<CONCEPTO>_<empId>` y los nombres legacy
    (overtime_, commission_, bonus_, other_income_, other_ded_).
    Retorna {emp_id: {conceptCode: float}}.
    """
    from app.services.payroll_variable_catalog import VARIABLE_CONCEPT_CODES, LEGACY_INPUT_MAP
    valid_codes = set(VARIABLE_CONCEPT_CODES)
    result = {}

    def _add(emp_id, code, raw):
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return
        if val <= 0:
            return
        result.setdefault(emp_id, {})[code] = round(val, 2)

    for key in form:
        val = form.get(key)
        if key.startswith("var_"):
            rest = key[4:]
            code, _, emp_id = rest.partition("_")
            if code in valid_codes and emp_id:
                _add(emp_id, code, val)
            continue
        for prefix, code in LEGACY_INPUT_MAP.items():
            if key.startswith(prefix + "_"):
                emp_id = key[len(prefix) + 1:]
                if emp_id:
                    _add(emp_id, code, val)
                break
    return result


def _collect_liquidation_employees(company_id, sandbox, selected_group_id,
                                   all_employees, period_employees):
    """Construye el mapa de liquidaciones pendientes para nómina tipo "liquidation".

    Un empleado con liquidación pendiente puede seguir con status "activo" (si el
    offboarding no ha llegado a "completed"), por lo que ya existe en
    ``period_employees``. Este helper garantiza que la liquidación tome prioridad
    sobre el salario regular: SIEMPRE agrega el id al mapa y solo evita duplicar
    el append a ``period_employees``.

    Returns:
        tuple[list, dict]: (period_employees actualizado, liquidation_settlements_map)
    """
    liquidation_settlements_map = {}
    if not selected_group_id:
        return period_employees, liquidation_settlements_map
    try:
        from app.services.offboarding_service import OffboardingService
        off_svc = OffboardingService(company_id, sandbox)
        all_pending = off_svc.get_pending_settlements()
        for s in all_pending:
            req = off_svc.get_request(s.get("requestId", ""))
            if not req:
                continue
            if req.get("status") in ("cancelled", "rejected"):
                continue
            emp_id = req.get("employeeId", "")
            emp = next((e for e in all_employees if e["id"] == emp_id), None)
            if not emp:
                continue
            matches_group = s.get("assignedGroupId") == selected_group_id
            matches_fallback = (
                not s.get("assignedGroupId")
                and selected_group_id in emp.get("payrollGroupIds", [])
            )
            if matches_group or matches_fallback:
                liquidation_settlements_map[emp_id] = s
                if emp_id not in [e["id"] for e in period_employees]:
                    period_employees.append(emp)
    except Exception:
        pass
    return period_employees, liquidation_settlements_map


def _get_pending_liquidation_employee_ids(company_id, sandbox):
    """Devuelve el set de employeeIds con liquidación pendiente (pendiente_pago).

    Es global: cualquier empleado con un settlement pendiente_pago activo debe
    ser excluido de TODAS las nóminas regulares, sin importar el grupo. Solo se
    omite si el offboarding está cancelled o rejected.

    Un empleado con liquidación pendiente puede seguir con status "activo" (si el
    offboarding no ha llegado a "completed"), por lo que por defecto entraría en
    las nóminas regulares. Este helper permite excluirlo de toda nómina que no
    sea tipo "liquidation".
    """
    pending_ids = set()
    try:
        from app.services.offboarding_service import OffboardingService
        off_svc = OffboardingService(company_id, sandbox)
        for s in off_svc.get_pending_settlements():
            req = off_svc.get_request(s.get("requestId", ""))
            if not req or not req.get("employeeId"):
                continue
            if req.get("status") in ("cancelled", "rejected"):
                continue
            if req.get("keepInCurrentPayroll"):
                continue
            pending_ids.add(req.get("employeeId"))
    except Exception:
        pass
    return pending_ids


def _collect_retained_employees(all_employees, period_start, period_end, selected_group_id=""):
    """Devuelve empleados inactivos con ``keepInCurrentPayroll`` cuyo último día
    trabajado cae dentro del período, para pagarles el período final por nómina regular.

    Se usan solo en nómina tipo "regular" (no "liquidation"), de modo que el salario
    prorrateado de los días trabajados se paga por nómina y las prestaciones por la
    nómina de liquidación.
    """
    retained = []
    if not period_start or not period_end:
        return retained
    try:
        from datetime import datetime as _dt
        ps = _dt.strptime(period_start, "%Y-%m-%d").date()
        pe = _dt.strptime(period_end, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return retained
    for e in all_employees:
        if not e.get("keepInCurrentPayroll"):
            continue
        if selected_group_id and selected_group_id not in e.get("payrollGroupIds", []):
            continue
        ref = e.get("lastWorkDate") or e.get("terminationDate") or ""
        if not ref:
            continue
        try:
            d = _dt.strptime(ref[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if ps <= d <= pe:
            retained.append(e)
    return retained


def _build_liquidation_columns(lines):
    """Computa las columnas dinámicas de conceptos de liquidación (LIQ_*).

    Inyecta ``liquidationMap`` (conceptCode → monto) en cada línea de liquidación
    y devuelve la lista de columnas [{code, name}] presentes en el período.
    """
    liquidation_columns = []
    for line in lines:
        if line.get("lineType") != "liquidation":
            continue
        liquidation_map = {}
        for tx in line.get("transactionSummary", []):
            if tx.get("type") != "earning":
                continue
            liquidation_map[tx.get("conceptCode", "")] = round(float(tx.get("amount", 0)), 2)
        line["liquidationMap"] = liquidation_map
        for code in liquidation_map:
            if code not in [c["code"] for c in liquidation_columns]:
                liquidation_columns.append({
                    "code": code,
                    "name": next((t.get("conceptName", code) for t in line.get("transactionSummary", []) if t.get("conceptCode") == code), code),
                })
    return liquidation_columns


def _build_liquidation_line(settlement, emp):
    """Construye la línea de nómina a partir de un settlement de liquidación.

    Usa los montos calculados en el settlement (NO el salario regular del empleado).
    El desglose ``transactionSummary`` se construye desde ``settlement["conceptos"]``
    (preaviso, cesantía, vacaciones, salario de Navidad, salario proporcional,
    asistencia económica) mapeando cada uno a su concepto de nómina LIQ_* del
    catálogo, más una deducción LIQ_DESCUENTOS por préstamos/adelantos.
    """
    emp_id = emp.get("id", "")
    totales = settlement.get("totales", {})
    liquid_total_income = round(float(totales.get("montoTotal", 0)), 2)
    liquid_net = round(float(totales.get("montoNetoAPagar", liquid_total_income)), 2)
    liquid_descuentos = round(float(totales.get("montoDescuentos", 0)), 2)

    # Mapeo de conceptos del settlement → conceptos de nómina LIQ_*
    concept_map = {
        "preaviso": ("LIQ_PREAVISO", "Preaviso"),
        "cesantia": ("LIQ_CESANTIA", "Cesantía"),
        "vacaciones": ("LIQ_VACACIONES", "Vacaciones proporcionales (Art. 177 C.T.)"),
        "salarioNavidad": ("LIQ_SALARIO_NAVIDAD", "Salario de Navidad proporcional"),
        "salarioProporcional": ("LIQ_SALARIO_PROPORCIONAL", "Salario proporcional"),
        "asistenciaEconomica": ("LIQ_ASISTENCIA_ECONOMICA", "Asistencia económica (Art. 82 C.T.)"),
    }

    liquid_tx = []
    for key, (code, name) in concept_map.items():
        c = settlement.get("conceptos", {}).get(key, {})
        if not c.get("aplica", True):
            continue
        amount = round(float(c.get("monto", 0)), 2)
        if amount <= 0:
            continue
        liquid_tx.append({
            "conceptCode": code,
            "type": "earning",
            "amount": amount,
            "source": "liquidation",
            "conceptName": name,
        })

    if liquid_descuentos > 0:
        liquid_tx.append({
            "conceptCode": "LIQ_DESCUENTOS",
            "type": "deduction",
            "amount": liquid_descuentos,
            "source": "liquidation",
            "conceptName": "Descuentos de liquidación (préstamos/adelantos)",
        })

    line = {
        "employeeId": emp_id,
        "employeeName": emp.get("fullName", ""),
        "cedula": emp.get("cedula", ""),
        "position": emp.get("position", ""),
        "department": emp.get("department", ""),
        "baseSalary": round(float(settlement.get("salarioDiarioPromedio", 0)) * 23.83, 2),
        "grossSalary": liquid_total_income,
        "totalIncome": liquid_total_income,
        "netSalary": liquid_net,
        "totalDeductions": round(max(0.0, liquid_total_income - liquid_net), 2),
        "overtimePay": 0, "overtimeHours": 0,
        "commission": 0, "bonus": 0, "otherIncome": 0,
        "afpEmployee": 0, "sfsEmployee": 0, "infotepEmployee": 0,
        "isrRetention": 0, "otherDeductions": liquid_descuentos,
        "afpEmployer": 0, "sfsEmployer": 0, "srlEmployer": 0,
        "infotepEmployer": 0, "totalEmployerContrib": 0,
        "periodType": "liquidacion",
        "transactionSummary": liquid_tx,
        "settlementId": settlement.get("id", ""),
        "lineType": "liquidation",
    }
    return line, liquid_tx


def _update_payroll_progress(company_id, job_id, index, total, employee_name,
                             sandbox=True, completed=True):
    """Actualiza el progreso al iniciar o terminar cada empleado."""
    from app.services.payroll_async_service import update_job

    processed = index + 1 if completed else index
    progress_pct = int((processed / total) * 90) if total else 90
    update_job(company_id, job_id, {
        "progress": progress_pct,
        "processedItems": processed,
        "phase": "employee_completed" if completed else "employee_calculation",
        "currentEmployeeName": employee_name,
        "message": f"Procesando {employee_name} ({index + 1}/{total})",
    }, sandbox=sandbox)


# ═══════════════════════════════════════════════════════════════════════════
# NÓMINA — Procesar
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/new", methods=["GET", "POST"])
def payroll_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService
    from app.services.payroll_ytd_service import get_ytd, save_ytd, accumulate_ytd
    from app.services.payroll_static_data import DEFAULT_PAYROLL_CONFIG

    selected_group_id = request.args.get("group", "") or request.form.get("payrollGroupId", "")
    selected_period_key = request.form.get("period_key", "").strip()
    existing_period_ref = None
    if request.method == "POST" and selected_group_id and selected_period_key:
        existing_period_ref = hr.get_payroll_period_by_key_and_group(
            company_id, selected_period_key, selected_group_id, sandbox=sandbox)
        recalculate = request.form.get("intent") == "recalculate"
        if existing_period_ref and (
                existing_period_ref.get("status") != "borrador" or not recalculate):
            flash("La nómina seleccionada ya existe. Se abrió su detalle.", "info")
            return redirect(url_for(
                "web_rrhh.payroll_view", period_id=existing_period_ref["id"]))

    # Variables importadas por CSV (draft en sesión hasta procesar)
    from app.web.rrhh.payroll_variables_import import SESSION_KEY as _VARS_SESSION_KEY
    imported_variables = session.get(_VARS_SESSION_KEY, []) or []

    # Catálogo de tabs de variables
    from app.services.payroll_variable_catalog import (
        RECURRING_MANAGED_BY_CONCEPT as _RECURRING_MANAGED_TABS,
    )
    ingreso_tabs, descuento_tabs = _editor_tabs(company_id, sandbox=sandbox)
    variable_tabs = ingreso_tabs + descuento_tabs
    recurring_managed_tabs = dict(_RECURRING_MANAGED_TABS)

    # Verificar onboarding
    config = hr.get_payroll_config(company_id, sandbox=sandbox)
    if not config.get("onboardingCompleted"):
        return redirect(url_for("web_rrhh.onboarding_guide"))

    all_employees = hr.get_employees(company_id, sandbox=sandbox)
    from app.utils.hr_utils import is_active_equivalent
    active_employees = [e for e in all_employees if is_active_equivalent(e.get("status", ""))]

    # ── Grupos de nómina ──
    payroll_groups = [g for g in hr.get_payroll_groups(company_id, sandbox=sandbox)
                      if g.get("isActive", True)]
    payroll_groups.sort(key=lambda g: g.get("name", ""))

    # Soporte de ?period_id= (retorno del job de cálculo a esta pantalla)
    period_id_arg = request.args.get("period_id", "")
    if period_id_arg:
        _period_by_id = hr.get_payroll_period(company_id, period_id_arg, sandbox=sandbox)
        if _period_by_id:
            if not selected_group_id:
                selected_group_id = _period_by_id.get("payrollGroupId", "")
            selected_period_key = request.args.get("period_key", "") or _period_by_id.get("periodKey", "")

    # Si el grupo seleccionado ya no está activo, agregarlo para no romper el reproceso
    if selected_group_id and not any(g.get("id") == selected_group_id for g in payroll_groups):
        _inactive_group = hr.get_payroll_group(company_id, selected_group_id, sandbox=sandbox)
        if _inactive_group:
            payroll_groups.append(_inactive_group)
            payroll_groups.sort(key=lambda g: g.get("name", ""))

    # Preselección de período y variables guardadas (edición desde la vista de nómina)
    selected_period_key = request.args.get("period_key", "") or selected_period_key
    if selected_period_key:
        _stored_vars = _load_existing_period_variables(company_id, selected_period_key,
                                                       selected_group_id, sandbox=sandbox)
        if _stored_vars:
            imported_variables = _stored_vars + imported_variables

    # ── Movimientos recurrentes del grupo (gestión desde tabs CxC/Seguro/Fijos) ──
    recurring_movements = []
    try:
        from app.services.recurring_service import get_recurring_movements
        if selected_group_id:
            recurring_movements = get_recurring_movements(
                company_id, payroll_group_id=selected_group_id, sandbox=sandbox)
    except Exception:
        recurring_movements = []

    # ── Líneas del período existente (sección Empleados: Resumen/Completo) ──
    period_lines = []
    if request.method == "GET" and selected_period_key:
        try:
            if selected_group_id:
                existing_period_ref = hr.get_payroll_period_by_key_and_group(
                    company_id, selected_period_key, selected_group_id, sandbox=sandbox)
            else:
                existing_period_ref = hr.get_payroll_period_by_key(
                    company_id, selected_period_key, sandbox=sandbox)
            if existing_period_ref:
                period_lines = PayrollService.get_period_lines(
                    existing_period_ref, company_id=company_id, sandbox=sandbox)
        except Exception:
            existing_period_ref = None
            period_lines = []

    # Determinar frecuencia según grupo o config global
    if selected_group_id:
        selected_group = next((g for g in payroll_groups if g["id"] == selected_group_id), None)
        group_frequency = selected_group["frequency"] if selected_group else config.get("payrollFrequency", "mensual")
    else:
        selected_group = None
        group_frequency = config.get("payrollFrequency", "mensual")

    # Filtrar empleados por grupo
    if selected_group_id:
        employees = [e for e in active_employees if selected_group_id in e.get("payrollGroupIds", [])]
        if not employees:
            flash(f"No hay empleados activos asignados al grupo «{selected_group.get('name', '')}».", "warning")
    else:
        employees = active_employees

    # ── Excluir empleados con liquidación pendiente de las nóminas regulares ──
    # Solo se incluyen en la nómina tipo "liquidation" (vía _collect_liquidation_employees).
    pending_liquidation_ids = _get_pending_liquidation_employee_ids(company_id, sandbox)
    if pending_liquidation_ids:
        employees = [e for e in employees if e.get("id") not in pending_liquidation_ids]

    # ── Vista previa de regalía (para pre-llenar el tab Regalía) ──
    christmas_preview = _build_christmas_preview(employees)

    # ── Liquidaciones pendientes (para nómina tipo "liquidation") ──
    liquidation_employees = []
    pending_liquidations = []
    unassigned_liquidations = []
    has_unassigned = False
    if selected_group_id:
        try:
            from app.services.offboarding_service import OffboardingService
            off_svc = OffboardingService(company_id, sandbox)
            all_pending = off_svc.get_pending_settlements()
            for s in all_pending:
                req = off_svc.get_request(s.get("requestId", ""))
                if not req or req.get("status") in ("cancelled", "rejected"):
                    continue
                emp_id = req.get("employeeId", "")
                emp = next((e for e in all_employees if e["id"] == emp_id), None)
                if not emp:
                    continue
                assigned = s.get("assignedGroupId")
                if assigned == selected_group_id:
                    liquidation_employees.append(emp)
                    pending_liquidations.append(s)
                elif not assigned and selected_group_id in emp.get("payrollGroupIds", []):
                    liquidation_employees.append(emp)
                    pending_liquidations.append(s)
                    has_unassigned = True
                elif not assigned:
                    unassigned_liquidations.append(s)
                    has_unassigned = True
        except Exception:
            pass

        # Merge pending-liquidation employees into the visible list for UX
        existing_ids = {e.get("id") for e in employees}
        for emp in liquidation_employees:
            emp_with_flag = dict(emp)
            emp_with_flag["isLiquidation"] = True
            if emp.get("id") not in existing_ids:
                employees.append(emp_with_flag)
                existing_ids.add(emp.get("id"))

    # Pre-validación de incidencias
    incidencias = PayrollService.validate_employees_before_payroll(employees) if employees else {"errors": [], "warnings": []}

    now = date.today()
    available_periods = _generate_periods(group_frequency, now.year)

    # ── Bloqueo secuencial: períodos posteriores al primer regular abierto ──
    locked_period_keys = set()
    lock_open_label = None
    closed_period_keys = set()
    if selected_group_id:
        try:
            locked_period_keys, lock_open_label, closed_period_keys = get_locked_periods(
                company_id, selected_group_id, available_periods, sandbox=sandbox)
        except Exception:
            locked_period_keys, lock_open_label, closed_period_keys = set(), None, set()

    if request.method == "POST":
        period_key = request.form.get("period_key", "")
        if not period_key:
            flash("Debes seleccionar un período.", "error")
            return redirect(url_for("web_rrhh.payroll_new"))

        if payroll_groups and not selected_group_id:
            flash("Debes seleccionar un grupo de nómina antes de procesar.", "error")
            return redirect(url_for("web_rrhh.payroll_new"))

        # ── Anti-duplicados ──
        if selected_group_id and existing_period_ref is None:
            existing_period_ref = hr.get_payroll_period_by_key_and_group(company_id, period_key, selected_group_id, sandbox=sandbox)
        elif not selected_group_id:
            existing_period_ref = hr.get_payroll_period_by_key(company_id, period_key, sandbox=sandbox)

        if existing_period_ref:
            if existing_period_ref.get("status") != "borrador":
                flash(
                    f"La nómina del período «{period_key}» ya existe. Se abrió su detalle.",
                    "info",
                )
                return redirect(url_for(
                    "web_rrhh.payroll_view",
                    period_id=existing_period_ref["id"],
                ))

        # Parse period key
        parts = period_key.split("-")
        year = int(parts[0])
        month = int(parts[1])

        period_info = next((p for p in available_periods if p["key"] == period_key), None)
        period_range = period_info["label"] if period_info else ""
        start_date = period_info["start"] if period_info else ""
        end_date = period_info["end"] if period_info else ""
        period_type = period_info.get("type", "mensual") if period_info else ("quincenal" if len(parts) == 3 and parts[2] != "M" else "mensual")

        # ── Bloqueo secuencial (solo nóminas regulares) ──
        period_sub_type_val = request.form.get("periodSubType", "regular")
        if (period_sub_type_val or "regular") == "regular" and period_key in locked_period_keys:
            flash(
                f"Debes cerrar el período «{lock_open_label or 'anterior'}» antes de procesar «{period_key}».",
                "error",
            )
            return render_template("rrhh/payroll_form.html", active_page="rrhh_payroll",
                                   employees=employees, now=now, now_month=now.month,
                                   available_periods=available_periods, frequency=group_frequency,
                                   locked_period_keys=locked_period_keys, lock_open_label=lock_open_label, closed_period_keys=closed_period_keys,
                                   show_christmas_bonus=(now.month >= 11),
                                   payroll_groups=payroll_groups,
                                   selected_group_id=selected_group_id,
                                   imported_variables=imported_variables,
                                   selected_period_key=selected_period_key,
                                   variable_tabs=variable_tabs,
                                   recurring_managed_tabs=recurring_managed_tabs,
                                   ingreso_tabs=ingreso_tabs,
                                   descuento_tabs=descuento_tabs,
                                   recurring_movements=recurring_movements,
                                   christmas_preview=christmas_preview,
                                   period_lines=period_lines,
                                   incidencias=incidencias)

        period_employees, excluded = _filter_employees_by_period(employees, period_key)
        # Reuse existing borrador period_id when re-processing, otherwise create new
        if existing_period_ref:
            period_id = existing_period_ref["id"]
            revision = existing_period_ref.get("revision", 0) + 1
        else:
            period_id = str(uuid.uuid4())
            revision = 1

        # ── Empleados inactivos retenidos en nómina (período final por nómina regular) ──
        if period_sub_type_val != "liquidation":
            retained = _collect_retained_employees(all_employees, start_date, end_date, selected_group_id)
            existing_ids = {e.get("id") for e in period_employees}
            for re in retained:
                if re.get("id") not in existing_ids:
                    period_employees.append(re)
                    existing_ids.add(re.get("id"))

        # ── Bloquear si no hay empleados que procesar ──
        if not period_employees:
            flash("Este grupo no tiene empleados activos para procesar. Revisa la asignación de empleados al grupo.", "error")
            return redirect(url_for("web_rrhh.payroll_new"))

        liquidation_settlements_map = {}
        if period_sub_type_val == "liquidation" and selected_group_id:
            period_employees, liquidation_settlements_map = _collect_liquidation_employees(
                company_id, sandbox, selected_group_id, all_employees, period_employees,
            )
        else:
            # Remove liquidation employees from regular payroll — they get no regular salary
            period_employees = [e for e in period_employees if not e.get("isLiquidation")]
            if has_unassigned:
                flash("Aviso: hay liquidaciones sin asignar a un grupo de nómina. Asígnalas para incluirlas en una nómina de liquidación.", "warning")

        # Pre-validación: bloquear si hay errores antes de calcular
        period_incidencias = PayrollService.validate_employees_before_payroll(period_employees)
        if period_incidencias.get("errors"):
            for err in period_incidencias["errors"]:
                flash(f"{err['employeeName']}: {err['issue']}", "error")
            flash("Corrige los errores antes de procesar la nómina.", "error")
            return render_template("rrhh/payroll_form.html", active_page="rrhh_payroll",
                                   employees=employees, now=now, now_month=now.month,
                                   available_periods=available_periods, frequency=group_frequency,
                                   locked_period_keys=locked_period_keys, lock_open_label=lock_open_label, closed_period_keys=closed_period_keys,
                                   show_christmas_bonus=(now.month >= 11),
                                   payroll_groups=payroll_groups,
                                   selected_group_id=selected_group_id,
                                   imported_variables=imported_variables,
                           selected_period_key=selected_period_key,
 variable_tabs=variable_tabs,
 recurring_managed_tabs=recurring_managed_tabs,
 ingreso_tabs=ingreso_tabs,
 descuento_tabs=descuento_tabs,
 recurring_movements=recurring_movements,
 christmas_preview=christmas_preview,
 period_lines=period_lines,
                                   incidencias=period_incidencias)
        # ── PASO 1: Resolver parámetros legales históricos ──
        from app.services.legal_parameter_resolver import resolve_all
        params = resolve_all(company_id, end_date, sandbox=sandbox)

        # Aplicar overrides del grupo
        group_overrides = {}
        if selected_group_id:
            _group = hr.get_payroll_group(company_id, selected_group_id, sandbox=sandbox)
            if _group:
                group_overrides = _group.get("groupOverrides", {})
                if group_overrides:
                    params = PayrollService.merge_group_overrides(params, group_overrides)

        # ── PASO 2: Cargar reglas ──
        active_rules = hr.get_active_rules_for_scope(company_id, "global", sandbox=sandbox)
        if selected_group_id:
            group_rules = hr.get_active_rules_for_scope(company_id, "group", selected_group_id, sandbox=sandbox)
            active_rules.extend(group_rules)
            active_rules.sort(key=lambda r: r.get("priority", 999))

        # ── PASO 3: Cargar conceptos activos ──
        from app.services.payroll_concept_engine import get_concepts
        all_concepts = get_concepts(company_id, sandbox=sandbox)
        concept_map = {c["code"]: c for c in all_concepts if c.get("active")}

        # ── PASO 4: Cargar movimientos recurrentes activos (filtrados por grupo) ──
        from app.services.recurring_service import get_recurring_movements
        from collections import defaultdict
        active_movements = []
        for emp in period_employees:
            emp_mvs = get_recurring_movements(company_id, employee_id=emp["id"],
                                              payroll_group_id=selected_group_id, sandbox=sandbox)
            active_movements.extend(emp_mvs)
        # Indexar por employeeId
        recurring_by_employee = defaultdict(list)
        for mv in active_movements:
            recurring_by_employee[mv["employeeId"]].append(mv)

        # ── PASO 5: Cargar horas extras aprobadas del período ──
        approved_overtime = OvertimeService.get_approved_for_period(
            company_id, start_date, end_date, sandbox=sandbox,
        )
        overtime_by_employee = OvertimeService.group_by_employee_and_type(approved_overtime)

        # ── Carga masiva de dependientes para reglas ──
        all_emp_ids = [e["id"] for e in period_employees if e.get("id")]
        dependents_by_employee = hr.get_dependents_for_employees(company_id, all_emp_ids, sandbox=sandbox)

        # ── Extraer valores del formulario para el thread background ──
        emp_form_values = _extract_variable_values(request.form, [e["id"] for e in period_employees])
        period_sub_type_val = request.form.get("periodSubType", "regular")
        include_christmas_bonus_val = (request.form.get("include_christmas_bonus") == "1"
                                       or period_sub_type_val == "christmas_bonus")
        scheduled_payment_date_val = request.form.get("scheduledPaymentDate", "").strip() or end_date
        notes_val = request.form.get("notes", "").strip()
        user_email = session.get("user", {}).get("email", "")

        if period_sub_type_val == "christmas_bonus":
            if month != 12:
                flash("Aviso: la regalía pascual normalmente se paga en diciembre (antes del 20). Estás procesando una nómina de regalía en otro mes.", "warning")
            elif scheduled_payment_date_val > f"{year}-12-20":
                flash("Aviso: la regalía pascual debe pagarse antes del 20 de diciembre.", "warning")

        # ── Crear job asíncrono ──
        from app.services.payroll_async_service import create_job, update_job, get_job
        redirect_to = request.form.get("redirect_to", "view")
        if redirect_to not in ("new", "view"):
            redirect_to = "new"
        job_id = create_job(company_id, "payroll_calculation",
                            total_items=len(period_employees),
                            metadata={"period_key": period_key, "period_id": period_id,
                                      "redirect_to": redirect_to},
                            sandbox=sandbox)
        if not job_id:
            flash("Error al crear la tarea asíncrona. Intenta nuevamente.", "error")
            return render_template("rrhh/payroll_form.html", active_page="rrhh_payroll",
                                   employees=employees, now=now, now_month=now.month,
                                   available_periods=available_periods, frequency=group_frequency,
                                   locked_period_keys=locked_period_keys, lock_open_label=lock_open_label, closed_period_keys=closed_period_keys,
                                   show_christmas_bonus=(now.month >= 11),
                                   payroll_groups=payroll_groups,
                                   selected_group_id=selected_group_id,
                                   imported_variables=imported_variables,
                           selected_period_key=selected_period_key,
 variable_tabs=variable_tabs,
 recurring_managed_tabs=recurring_managed_tabs,
 ingreso_tabs=ingreso_tabs,
 descuento_tabs=descuento_tabs,
 recurring_movements=recurring_movements,
 christmas_preview=christmas_preview,
 period_lines=period_lines,
                                   incidencias=incidencias)

        # El draft de variables importadas ya fue consumido por el cálculo
        session.pop(_VARS_SESSION_KEY, None)

        # ── Worker en background que ejecuta el cálculo y guarda resultados ──
        def _payroll_worker():
            try:
                now_worker = datetime.now(timezone.utc)
                update_job(company_id, job_id, {
                    "status": "running",
                    "startedAt": now_worker.isoformat(),
                    "message": "Iniciando cálculo...",
                }, sandbox=sandbox)

                lines = []
                all_transactions = []
                all_applications = []

                # ── Licencias aprobadas indexadas por empleado (para descuento) ──
                from collections import defaultdict as _dd
                leave_requests_by_employee = _dd(list)
                try:
                    for _lr in hr.get_leave_requests(company_id, sandbox=sandbox):
                        _leid = _lr.get("employeeId", "")
                        if _leid:
                            leave_requests_by_employee[_leid].append(_lr)
                except Exception:
                    pass

                # ── Posiciones (para heredar horario del puesto) ──
                positions_by_id = {}
                positions_by_name = {}
                try:
                    for _p in hr.get_catalog(company_id, "positions", sandbox=sandbox):
                        positions_by_id[_p.get("id", "")] = _p
                        positions_by_name[(_p.get("name", "") or "").strip().lower()] = _p
                except Exception:
                    pass

                for idx, emp in enumerate(period_employees):
                    job_check = get_job(company_id, job_id, sandbox=sandbox)
                    if job_check.get("status") == "cancelled":
                        return

                    emp_id = emp["id"]
                    _update_payroll_progress(
                        company_id, job_id, idx, len(period_employees),
                        emp.get("fullName", emp_id), sandbox=sandbox,
                        completed=False,
                    )

                    # ── Nómina de liquidación: si el empleado tiene liquidación pendiente ──
                    if period_sub_type_val == "liquidation" and emp_id in liquidation_settlements_map:
                        settlement = liquidation_settlements_map[emp_id]
                        line, liquid_tx = _build_liquidation_line(settlement, emp)
                        lines.append(line)
                        all_transactions.extend(liquid_tx)
                        _update_payroll_progress(
                            company_id, job_id, idx, len(period_employees),
                            emp.get("fullName", emp_id), sandbox=sandbox,
                        )
                        continue

                    emp_vars = emp_form_values.get(emp_id, {})
                    base = float(emp.get("baseSalary", 0))
                    overtime = emp_vars.get("HORAS_EXTRA", 0)
                    commission = emp_vars.get("COMISION", 0)
                    bonus = emp_vars.get("BONIFICACION", 0)
                    other_income_manual = emp_vars.get("OTROS_INGRESOS", 0)
                    other_ded_manual = emp_vars.get("OTRAS_DEDUCCIONES", 0)

                    if group_overrides.get("includeBaseSalary") is False:
                        base = 0.0
                    if group_overrides.get("includeCommission") is False:
                        commission = 0.0
                    if group_overrides.get("includeOvertime") is False:
                        overtime = 0.0
                    if group_overrides.get("includeBonus") is False:
                        bonus = 0.0
                    if group_overrides.get("includeOtherIncome") is False:
                        other_income_manual = 0.0

                    # ── Licencia no pagada (solo salario fijo) ──
                    leave_deduction = 0.0
                    leave_deduction_days = 0
                    if base > 0 and (emp.get("salaryType") or "fijo") == "fijo":
                        _position = positions_by_id.get(emp.get("positionId", "")) or \
                            positions_by_name.get((emp.get("position", "") or "").strip().lower())
                        _work_days = PayrollService.resolve_work_days(emp, _position)
                        _leave_res = PayrollService.unpaid_leave_deduction(
                            monthly_salary=base,
                            leave_requests=leave_requests_by_employee.get(emp_id, []),
                            period_start=start_date,
                            period_end=end_date,
                            company_id=company_id,
                            sandbox=sandbox,
                            working_days=float(params.get("working_days_per_month", 23.83)),
                            work_days=_work_days,
                        )
                        leave_deduction_days = int(_leave_res.get("days", 0))
                        leave_deduction = float(_leave_res.get("amount", 0.0))

                    emp_period_type = period_type
                    emp_is_quincenal = emp_period_type == "quincenal"
                    if emp_is_quincenal and base > 0:
                        base = round(base / 2, 2)
                    line_id = str(uuid.uuid4())

                    employee_transactions = []

                    # ── Horas Extras ──
                    emp_overtime_records = overtime_by_employee.get(emp_id, {})
                    overtime_records_used = []
                    overtime_breakdown = {}
                    for tcode, tdata in emp_overtime_records.items():
                        if tdata.get("minutes", 0) <= 0:
                            continue
                        hourly = float(tdata.get("hourlyRate", 0))
                        factor = float(tdata.get("factor", 1.35))
                        mins = tdata.get("minutes", 0)
                        amount = PayrollOvertimeCalculator.calculate_pay(hourly, mins, factor)
                        if amount <= 0:
                            continue
                        otype_cache = hr.get_overtime_type(company_id, tcode, sandbox=sandbox)
                        concept_code = (otype_cache.get("conceptCode", "") if otype_cache else "") or "HORAS_EXTRA"
                        concept = concept_map.get(concept_code) or concept_map.get("HORAS_EXTRA")
                        if not concept:
                            continue
                        from app.models.transaction import PayrollTransaction
                        from app.services.payroll_concept_engine import build_concept_snapshot
                        now_iso = datetime.now(timezone.utc).isoformat()
                        tx = PayrollTransaction(
                            id=str(uuid.uuid4()), periodId=period_id, periodKey=period_key,
                            payrollLineId=line_id, employeeId=emp_id,
                            conceptCode=concept_code, type="earning",
                            amount=round(amount, 2), source=f"overtime:{tcode}",
                            status="applied",
                            conceptSnapshot=build_concept_snapshot(concept),
                            periodYear=year, createdAt=now_iso, updatedAt=now_iso,
                        )
                        tx_dict = tx.model_dump()
                        tx_dict["overtimeRecordIds"] = tdata.get("records", [])
                        employee_transactions.append(tx_dict)
                        overtime_records_used.extend(tdata.get("records", []))
                        overtime_breakdown[concept_code] = overtime_breakdown.get(concept_code, 0) + amount

                    o_locked_ids = list(set(overtime_records_used))
                    for oid in o_locked_ids:
                        OvertimeService.lock(company_id, oid, user_email or "system", sandbox=sandbox)

                    # ── Prorrateo ──
                    salary_history = hr.get_salary_history(company_id, emp_id, sandbox=sandbox)
                    prorated = PayrollService.prorate_salary(
                        monthly_salary=base, period_start=start_date, period_end=end_date,
                        hire_date=emp.get("hireDate", ""),
                        termination_date=emp.get("lastWorkDate", "") or emp.get("terminationDate", ""),
                        salary_history=salary_history,
                    )

                    # ── Salario base ──
                    salario_concept = concept_map.get("SALARIO_BASE")
                    if salario_concept and base > 0:
                        from app.services.concept_engine import ConceptEngine
                        tx = ConceptEngine.evaluate(
                            concept=salario_concept,
                            context={"baseSalary": base, "proratedSalary": prorated, "isQuincenal": emp_is_quincenal},
                            params=params, period_id=period_id, period_key=period_key,
                            employee_id=emp_id, contract_id=emp.get("contractId", ""),
                            payroll_line_id=line_id, period_revision=1,
                            legal_entity_id="", group_id=selected_group_id,
                        )
                        if tx:
                            employee_transactions.append(tx.model_dump())

                    # ── Variable movements (genérico por concepto) ──
                    from app.services.payroll_variable_catalog import GROUP_OVERRIDE_BY_CONCEPT
                    for vcode, amt in emp_vars.items():
                        if amt <= 0:
                            continue
                        if vcode == "REGALIA_PASCUAL":
                            continue  # se maneja en el bloque de regalía
                        if vcode in GROUP_OVERRIDE_BY_CONCEPT:
                            flag = GROUP_OVERRIDE_BY_CONCEPT[vcode]
                            if group_overrides.get(flag) is False:
                                continue
                        concept = concept_map.get(vcode)
                        if not concept:
                            continue
                        from app.models.transaction import PayrollTransaction
                        from app.services.payroll_concept_engine import build_concept_snapshot
                        employee_transactions.append(PayrollTransaction(
                            id=str(uuid.uuid4()), periodId=period_id, periodKey=period_key,
                            payrollLineId=line_id, employeeId=emp_id,
                            conceptCode=vcode, type=concept.get("type", "earning"),
                            amount=round(amt, 2), source=f"var:{vcode}", status="applied",
                            conceptSnapshot=build_concept_snapshot(concept),
                            periodYear=year,
                            createdAt=datetime.now(timezone.utc).isoformat(),
                            updatedAt=datetime.now(timezone.utc).isoformat(),
                        ).model_dump())

                    # ── Regalía pascual (auto o override manual) ──
                    christmas = 0.0
                    if include_christmas_bonus_val or emp_vars.get("REGALIA_PASCUAL"):
                        christmas = emp_vars.get("REGALIA_PASCUAL", 0)
                        if not christmas:
                            months_worked = _months_worked_in_year(emp.get("hireDate", ""))
                            christmas = PayrollService.calculate_christmas_bonus(base, months_worked)
                        if christmas > 0:
                            christmas_concept = concept_map.get("BONIFICACION", {})
                            from app.models.transaction import PayrollTransaction
                            from app.services.payroll_concept_engine import build_concept_snapshot
                            employee_transactions.append(PayrollTransaction(
                                id=str(uuid.uuid4()), periodId=period_id, periodKey=period_key,
                                payrollLineId=line_id, employeeId=emp_id,
                                conceptCode="REGALIA_PASCUAL", type="earning",
                                amount=round(christmas, 2), source="system", status="applied",
                                conceptSnapshot=build_concept_snapshot(christmas_concept),
                                periodYear=year,
                                createdAt=datetime.now(timezone.utc).isoformat(),
                                updatedAt=datetime.now(timezone.utc).isoformat(),
                            ).model_dump())

                    # ── Reglas ──
                    if active_rules:
                        from app.services.payroll_rule_engine import PayrollRuleEngine
                        from app.utils.hr_utils import is_minor as _is_minor_dep
                        emp_rules = list(active_rules)
                        emp_specific = hr.get_active_rules_for_scope(company_id, "employee", emp_id, sandbox=sandbox)
                        if emp_specific:
                            emp_rules.extend(emp_specific)
                            emp_rules.sort(key=lambda r: r.get("priority", 999))
                        filtered_rules = []
                        for r in emp_rules:
                            trigger_month = r.get("triggerMonth", 0)
                            if trigger_month and trigger_month != month:
                                continue
                            if _should_skip_christmas_rule(r, include_christmas_bonus_val or "REGALIA_PASCUAL" in emp_vars):
                                continue
                            freq = r.get("frequency", "always")
                            if freq == "always":
                                filtered_rules.append(r)
                            elif freq in ("annual", "once"):
                                log_year = year if freq == "annual" else None
                                if not hr.rule_log_exists(company_id, r["id"], emp_id, log_year, sandbox=sandbox):
                                    filtered_rules.append(r)
                        accumulated = hr.get_ytd_transactions(company_id, emp_id, year, concept_code="SALARIO_BASE", sandbox=sandbox)
                        acc_salary = sum(tx.get("amount", 0) for tx in accumulated) + base
                        emp_context = dict(emp)
                        emp_context["accumulatedOrdinarySalary"] = acc_salary
                        hire_d = emp.get("hireDate", "")
                        emp_hire_month = int(hire_d[5:7]) if hire_d and len(hire_d) >= 7 else 0
                        emp_context["isAnniversaryMonth"] = 1 if emp_hire_month == month else 0
                        emp_context["proratedSalary"] = prorated if prorated is not None else base
                        total_overtime_mins = sum(td.get("minutes", 0) for td in emp_overtime_records.values())
                        emp_context["overtimeHours"] = round(total_overtime_mins / 60, 2)
                        emp_deps = dependents_by_employee.get(emp_id, [])
                        emp_context["dependentCount"] = len(emp_deps)
                        emp_context["dependentCountMinor"] = sum(1 for d in emp_deps if _is_minor_dep(d.get("birthDate", "")))
                        emp_context["dependentCountAdult"] = sum(1 for d in emp_deps if d.get("active", True) and not _is_minor_dep(d.get("birthDate", "")))
                        emp_context["dependentCountStudent"] = sum(1 for d in emp_deps if d.get("active", True) and d.get("isStudent"))
                        emp_context["financialDependentCount"] = sum(1 for d in emp_deps if d.get("active", True) and d.get("isFinancialDependent", True))
                        try:
                            ps_date = datetime.strptime(start_date, "%Y-%m-%d").date()
                            pe_date = datetime.strptime(end_date, "%Y-%m-%d").date()
                            emp_context["daysInPeriod"] = (pe_date - ps_date).days + 1
                        except (ValueError, TypeError):
                            emp_context["daysInPeriod"] = 23.83
                        rule_result = PayrollRuleEngine.evaluate_rules(filtered_rules, emp_context)
                        if rule_result:
                            from app.models.transaction import PayrollTransaction
                            from app.services.payroll_concept_engine import build_concept_snapshot
                            now_iso = datetime.now(timezone.utc).isoformat()
                            for applied in rule_result.get("applied_rules", []):
                                rule_name = applied.get("ruleName", "")
                                for action in applied.get("actions", []):
                                    action_desc = action.get("description", "") or rule_name
                                    formula = action.get("formula", "0")
                                    concept_code = _resolve_rule_concept_code(action)
                                    if not concept_code:
                                        continue
                                    value = PayrollRuleEngine._evaluate_formula(formula, emp_context)
                                    if value > 0:
                                        concept = concept_map.get(concept_code, {})
                                        tx_type = concept.get("type", "earning")
                                        tx = PayrollTransaction(
                                            id=str(uuid.uuid4()), periodId=period_id, periodKey=period_key,
                                            payrollLineId=line_id, employeeId=emp_id,
                                            conceptCode=concept_code, type=tx_type,
                                            amount=round(value, 2), source=f"rule:{applied.get('ruleId', '')}",
                                            status="applied",
                                            conceptSnapshot=build_concept_snapshot(concept),
                                            periodYear=year, createdAt=now_iso, updatedAt=now_iso,
                                        )
                                        tx_dict = tx.model_dump()
                                        tx_dict["isRuleGenerated"] = True
                                        tx_dict["ruleGeneratedDescription"] = action_desc
                                        employee_transactions.append(tx_dict)
                                rule_obj = next((r for r in emp_rules if r["id"] == applied["ruleId"]), None)
                                if rule_obj and rule_obj.get("frequency") in ("annual", "once"):
                                    log_year = year if rule_obj.get("frequency") == "annual" else None
                                    hr.save_rule_log(company_id, rule_obj["id"], emp_id, log_year,
                                                     period_key, 0.0, now_iso, sandbox=sandbox)

                    # ── Recurring movements ──
                    from app.services.recurring_service import apply_recurring_for_employee
                    recurring_txs, recurring_apps = apply_recurring_for_employee(
                        company_id, emp_id, emp.get("contractId", ""), base,
                        period_id, period_key, start_date, end_date, 1,
                        recurring_by_employee,
                        legal_entity_id="", group_id=selected_group_id, sandbox=sandbox,
                    )
                    for tx in recurring_txs:
                        tx["payrollLineId"] = line_id
                    employee_transactions.extend(recurring_txs)
                    all_applications.extend(recurring_apps)

                    # ── Licencia no pagada (descuento) ──
                    if leave_deduction > 0:
                        lic_concept = concept_map.get("DESC_LICENCIA")
                        if lic_concept:
                            from app.models.transaction import PayrollTransaction as _PTx
                            from app.services.payroll_concept_engine import build_concept_snapshot as _bcs
                            employee_transactions.append(_PTx(
                                id=str(uuid.uuid4()), periodId=period_id, periodKey=period_key,
                                payrollLineId=line_id, employeeId=emp_id,
                                conceptCode="DESC_LICENCIA", type="deduction",
                                amount=round(leave_deduction, 2), source="leave", status="applied",
                                conceptSnapshot=_bcs(lic_concept),
                                periodYear=year,
                                createdAt=datetime.now(timezone.utc).isoformat(),
                                updatedAt=datetime.now(timezone.utc).isoformat(),
                            ).model_dump())

                    # ── Gross income ──
                    gross_income = sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("type") == "earning")
                    cotizable_income = max(0.0, gross_income - leave_deduction)

                    # ── TSS ──
                    for tss_code in ["AFP_EMPLEADO", "SFS_EMPLEADO", "INFOTEP_EMPLEADO",
                                     "AFP_EMPLEADOR", "SFS_EMPLEADOR", "SRL_EMPLEADOR", "INFOTEP_EMPLEADOR"]:
                        concept = concept_map.get(tss_code)
                        if not concept:
                            continue
                        from app.services.concept_engine import ConceptEngine as CE
                        tx = CE.evaluate(
                            concept=concept,
                            context={"baseSalary": base, "grossIncome": cotizable_income, "isQuincenal": emp_is_quincenal},
                            params=params, period_id=period_id, period_key=period_key,
                            employee_id=emp_id, contract_id=emp.get("contractId", ""),
                            payroll_line_id=line_id, period_revision=1,
                            legal_entity_id="", group_id=selected_group_id,
                        )
                        if tx:
                            employee_transactions.append(tx.model_dump())

                    # ── ISR ──
                    isr_concept = concept_map.get("ISR_RETENCION")
                    if isr_concept:
                        from app.services.payroll_ytd_service import get_ytd
                        ytd_data = get_ytd(company_id, emp_id, year, sandbox=sandbox)
                        ytd_isr = ytd_data.get("isrRetention", 0) if ytd_data else 0
                        afp_ded = sum(float(t.get("amount", 0)) for t in employee_transactions
                                      if t.get("conceptCode") == "AFP_EMPLEADO")
                        sfs_ded = sum(float(t.get("amount", 0)) for t in employee_transactions
                                      if t.get("conceptCode") == "SFS_EMPLEADO")
                        from app.services.concept_engine import ConceptEngine as CE
                        tx = CE.evaluate(
                            concept=isr_concept,
                            context={"baseSalary": base, "grossIncome": cotizable_income,
                                     "isQuincenal": emp_is_quincenal, "ytd_isr": ytd_isr,
                                     "afpDeduction": afp_ded, "sfsDeduction": sfs_ded},
                            params=params, period_id=period_id, period_key=period_key,
                            employee_id=emp_id, contract_id=emp.get("contractId", ""),
                            payroll_line_id=line_id, period_revision=1,
                        )
                        if tx:
                            employee_transactions.append(tx.model_dump())

                    # ── Embargos ──
                    try:
                        from app.services.garnishment_service import GarnishmentService
                        from app.services.db_service import DatabaseService
                        garnishments = DatabaseService.get_employee_garnishments(company_id, emp_id, sandbox=sandbox, company_id=company_id)
                        if garnishments:
                            earn_total = sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("type") == "earning")
                            deduct_total = sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("type") == "deduction")
                            net_before_garnishments = max(0, earn_total - deduct_total)
                            garnish_result = GarnishmentService.process_all_garnishments(net_before_garnishments, garnishments)
                            for detail in garnish_result.get("details", []):
                                from app.models.transaction import PayrollTransaction
                                garnish_tx = PayrollTransaction(
                                    id=str(uuid.uuid4()), periodId=period_id, periodKey=period_key,
                                    payrollLineId=line_id, employeeId=emp_id,
                                    conceptCode=f"EMBARGO_{detail.get('type', 'JUDICIAL').upper()}",
                                    type="deduction", amount=detail.get("deduction", 0),
                                    source="garnishment", status="applied",
                                    priority=detail.get("priority", 200),
                                    conceptSnapshot={"name": f"Embargo: {detail.get('reference', '')}",
                                                     "type": "deduction", "category": "garnishment",
                                                     "isLegalMandatory": True},
                                    periodYear=year,
                                    createdAt=datetime.now(timezone.utc).isoformat(),
                                    updatedAt=datetime.now(timezone.utc).isoformat(),
                                )
                                employee_transactions.append(garnish_tx.model_dump())
                                garn_id = detail.get("garnishmentId", "")
                                if garn_id:
                                    existing = next((g for g in garnishments if g.get("id") == garn_id), None)
                                    if existing:
                                        existing["remainingBalance"] = detail.get("remainingBalance", 0)
                                        if detail.get("isCompleted"):
                                            existing["status"] = "completed"
                                        DatabaseService.save_garnishment(company_id, garn_id, existing, sandbox=sandbox, company_id=company_id)
                    except Exception:
                        pass

                    # ── Deduction priority engine ──
                    from app.services.deduction_priority_engine import DeductionPriorityEngine
                    priority_result = DeductionPriorityEngine.process(employee_transactions, params)
                    processed_deductions = {id(t): t for t in priority_result["transactions"]}
                    employee_transactions = [
                        processed_deductions.get(id(t), t) if t.get("type") == "deduction" else t
                        for t in employee_transactions
                    ]

                    # ── Build PayrollLine ──
                    from app.services.payroll_concept_engine import build_concept_snapshot
                    recurring_details = []
                    recurring_additions_details = []
                    tx_summary = []
                    for tx in employee_transactions:
                        if isinstance(tx, dict):
                            ccode = tx.get("conceptCode", "")
                            cname = concept_map.get(ccode, {}).get("name", tx.get("conceptSnapshot", {}).get("name", ccode))
                            is_rec = tx.get("isRecurring", False)
                            is_rule = tx.get("isRuleGenerated", False)
                            tx_summary.append({"conceptCode": ccode, "amount": tx.get("amount", 0),
                                               "type": tx.get("type", ""), "isRecurring": is_rec,
                                               "isRuleGenerated": is_rule, "conceptName": cname})
                            if (is_rec or is_rule) and tx.get("type") == "deduction":
                                desc = tx.get("ruleGeneratedDescription", cname) if is_rule else cname
                                recurring_details.append({"description": desc, "amount": float(tx.get("amount", 0))})
                            if (is_rec or is_rule) and tx.get("type") == "earning":
                                desc = tx.get("ruleGeneratedDescription", cname) if is_rule else cname
                                recurring_additions_details.append({"description": desc, "amount": float(tx.get("amount", 0))})
                        else:
                            tx_summary.append({"conceptCode": getattr(tx, "conceptCode", ""),
                                               "amount": getattr(tx, "amount", 0),
                                               "type": getattr(tx, "type", "")})

                    earn = sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("type") == "earning")
                    deduct = sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("type") == "deduction")
                    employer = sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("type") == "employer_contrib")
                    net = max(0, earn - deduct)
                    recurring_earnings = sum(
                        float(t.get("amount", 0)) for t in employee_transactions
                        if t.get("isRecurring") and not t.get("isRuleGenerated") and t.get("type") == "earning"
                    )

                    line = {
                        "employeeId": emp_id, "employeeName": emp.get("fullName", ""),
                        "cedula": emp.get("cedula", ""), "position": emp.get("position", ""),
                        "department": emp.get("department", ""), "baseSalary": base, "grossSalary": base,
                        "overtimePay": round(sum(overtime_breakdown.values()) + overtime, 2),
                        "overtimeHours": float(overtime),
                        "overtimeBreakdown": overtime_breakdown,
                        "commission": commission, "bonus": bonus,
                        "christmasBonus": round(christmas, 2),
                        "otherIncome": round(recurring_earnings + build_manual_other_income(employee_transactions), 2),
                        "periodType": emp_period_type, "transactionSummary": tx_summary,
                        "totalIncome": round(earn, 2), "totalDeductions": round(deduct, 2),
                        "netSalary": round(net, 2), "totalEmployerContrib": round(employer, 2),
                        "afpEmployee": sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") == "AFP_EMPLEADO"),
                        "sfsEmployee": sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") == "SFS_EMPLEADO"),
                        "infotepEmployee": sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") == "INFOTEP_EMPLEADO"),
                        "isrRetention": sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") == "ISR_RETENCION"),
                        "afpEmployer": sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") == "AFP_EMPLEADOR"),
                        "sfsEmployer": sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") == "SFS_EMPLEADOR"),
                        "srlEmployer": sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") == "SRL_EMPLEADOR"),
                        "infotepEmployer": sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") == "INFOTEP_EMPLEADOR"),
                        "otherDeductions": build_manual_other_deductions(employee_transactions),
                        "leaveDeduction": round(leave_deduction, 2),
                        "leaveDeductionDays": leave_deduction_days,
                        "recurringDeductionsBreakdown": recurring_details,
                        "recurringAdditionsBreakdown": recurring_additions_details,
                    }

                    lines.append(line)
                    all_transactions.extend(employee_transactions)

                    try:
                        from app.services.payroll_ytd_service import get_ytd, save_ytd, accumulate_ytd
                        ytd = get_ytd(company_id, emp_id, year, sandbox=sandbox)
                        ytd = accumulate_ytd(ytd, line, period_factor=24 if emp_is_quincenal else 12,
                                             period_key=period_key, period_id=period_id)
                        save_ytd(company_id, emp_id, year, ytd, sandbox=sandbox)
                    except Exception:
                        pass

                    # ── Actualizar progreso ──
                    _update_payroll_progress(
                        company_id, job_id, idx, len(period_employees),
                        emp.get("fullName", emp_id), sandbox=sandbox,
                    )

                # ── POST-PROCESAMIENTO ──
                update_job(company_id, job_id, {
                    "progress": 90,
                    "message": "Guardando resultados...",
                }, sandbox=sandbox)

                all_recurring_descs = []
                all_recurring_additions_descs = []
                for line in lines:
                    for d in line.get("recurringDeductionsBreakdown", []):
                        if d["description"] not in all_recurring_descs:
                            all_recurring_descs.append(d["description"])
                    line["recurringDeductionsMap"] = {d["description"]: d["amount"] for d in line.get("recurringDeductionsBreakdown", [])}
                    for d in line.get("recurringAdditionsBreakdown", []):
                        if d["description"] not in all_recurring_additions_descs:
                            all_recurring_additions_descs.append(d["description"])
                    line["recurringAdditionsMap"] = {d["description"]: d["amount"] for d in line.get("recurringAdditionsBreakdown", [])}

                all_overtime_cols = []
                overtime_type_names = {}
                for line in lines:
                    for code in line.get("overtimeBreakdown", {}):
                        if code not in all_overtime_cols:
                            all_overtime_cols.append(code)
                            c = concept_map.get(code) if code in concept_map else None
                            overtime_type_names[code] = c.get("name", code) if c else code
                overtime_columns = [{"code": c, "name": overtime_type_names.get(c, c)} for c in all_overtime_cols]

                total_gross = sum(l.get("totalIncome", 0) for l in lines)
                total_net = sum(l.get("netSalary", 0) for l in lines)
                total_employer = sum(l.get("totalEmployerContrib", 0) for l in lines)
                now_dt = date.today()

                period_data = {
                    "id": period_id, "periodKey": period_key, "periodType": period_type,
                    "periodSubType": period_sub_type_val, "periodRange": period_range,
                    "startDate": start_date, "endDate": end_date,
                    "scheduledPaymentDate": scheduled_payment_date_val or end_date,
                    "month": month, "year": year, "revision": revision,
                    "payrollGroupId": selected_group_id, "status": "calculada",
                    "totalGross": round(total_gross, 2), "totalNet": round(total_net, 2),
                    "totalEmployerContrib": round(total_employer, 2),
                    "processedDate": now_dt.isoformat(),
                    "notes": (existing_period_ref.get("notes", "") + "\n" + notes_val).strip() if existing_period_ref and notes_val else (notes_val or existing_period_ref.get("notes", "") if existing_period_ref else notes_val),
                    "calculatedBy": user_email, "calculatedAt": now_dt.isoformat(),
                    "taxRatesSnapshot": params, "appliedRatesDate": now_dt.isoformat(),
                    "parameterVersions": {}, "lineCount": len(lines),
                    "recurringDeductionColumns": all_recurring_descs,
                    "recurringAdditionsColumns": all_recurring_additions_descs,
                    "overtimeColumns": overtime_columns,
                    "statusHistory": (existing_period_ref.get("statusHistory", []) if existing_period_ref else []) + [
                        {"from": existing_period_ref.get("status", "borrador") if existing_period_ref else "borrador",
                         "to": "calculada", "by": user_email,
                         "at": now_dt.isoformat(), "comment": "Nómina calculada"}
                    ],
                }

                from app.services.recurring_service import save_applications_batch, delete_applications_by_period
                saved = hr.save_payroll_period(company_id, period_id, period_data, sandbox=sandbox)
                if not saved:
                    raise RuntimeError("Error al guardar el período en la base de datos.")
                # Reemplazo idempotente: borrar lo previo para no duplicar en recálculos
                hr.delete_payroll_lines(company_id, period_id, sandbox=sandbox)
                hr.delete_payroll_transactions_by_period(company_id, period_id, sandbox=sandbox)
                delete_applications_by_period(company_id, period_id, sandbox=sandbox)
                hr.save_payroll_lines_batch(company_id, period_id, lines, sandbox=sandbox)
                hr.save_payroll_transactions_batch(company_id, all_transactions, sandbox=sandbox)
                save_applications_batch(company_id, all_applications, sandbox=sandbox)

                for tx in all_transactions:
                    record_ids = tx.get("overtimeRecordIds", [])
                    if not record_ids:
                        continue
                    for oid in record_ids:
                        OvertimeService.mark_as_processed(company_id, oid, period_id, user_email or "system", sandbox=sandbox)
                        OvertimeService.create_payroll_link(
                            company_id, oid, period_id, period_key,
                            tx.get("id", ""), tx.get("conceptCode", ""),
                            tx.get("amount", 0), sandbox=sandbox,
                        )

                from app.services.payroll_audit_service import log_action
                log_action(company_id, "calculate", "payroll_period", period_id, user_email,
                           changes={"period": period_key, "employees": len(lines), "total_net": round(total_net, 2)}, sandbox=sandbox)

                update_job(company_id, job_id, {
                    "status": "completed",
                    "progress": 100,
                    "processedItems": len(period_employees),
                    "message": f"Nómina {period_range or period_key} calculada: {len(lines)} empleados, neto RD$ {total_net:,.2f}.",
                    "result": {"period_id": period_id},
                    "completedAt": datetime.now(timezone.utc).isoformat(),
                }, sandbox=sandbox)

            except Exception as e:
                import traceback
                traceback.print_exc()
                try:
                    update_job(company_id, job_id, {
                        "status": "failed",
                        "error": str(e)[:500],
                        "message": f"Error en el cálculo: {str(e)[:200]}",
                        "completedAt": datetime.now(timezone.utc).isoformat(),
                    }, sandbox=sandbox)
                except Exception:
                    pass

        import threading
        t = threading.Thread(target=_payroll_worker, daemon=True)
        t.start()

        return redirect(url_for("web_rrhh.payroll_progress", job_id=job_id))

    return render_template("rrhh/payroll_form.html", active_page="rrhh_payroll",
                           employees=employees, now=now, now_month=now.month,
                           existing_period=existing_period_ref,
                           available_periods=available_periods, frequency=group_frequency,
                           locked_period_keys=locked_period_keys, lock_open_label=lock_open_label, closed_period_keys=closed_period_keys,
                           show_christmas_bonus=(now.month >= 11),
                           payroll_groups=payroll_groups,
                           selected_group_id=selected_group_id,
                           imported_variables=imported_variables,
                           selected_period_key=selected_period_key,
 variable_tabs=variable_tabs,
 recurring_managed_tabs=recurring_managed_tabs,
 ingreso_tabs=ingreso_tabs,
 descuento_tabs=descuento_tabs,
 recurring_movements=recurring_movements,
 christmas_preview=christmas_preview,
 period_lines=period_lines,
                           incidencias=incidencias,
                           pending_liquidations=pending_liquidations,
                           unassigned_liquidations=unassigned_liquidations)


# ═══════════════════════════════════════════════════════════════════════════
# CREAR PERÍODO (borrador, sin calcular)
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/create", methods=["POST"])
def payroll_create():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    selected_group_id = request.form.get("payrollGroupId", "").strip()
    period_key = request.form.get("period_key", "").strip()
    period_sub_type = request.form.get("periodSubType", "regular").strip() or "regular"

    if not selected_group_id:
        flash("Debes seleccionar un grupo de nómina.", "error")
        return redirect(url_for("web_rrhh.payroll_new"))
    if not period_key:
        flash("Debes seleccionar un período.", "error")
        return redirect(url_for("web_rrhh.payroll_new"))

    try:
        existing = hr.get_payroll_period_by_key_and_group(
            company_id, period_key, selected_group_id, sandbox=sandbox)
        if existing:
            message = ("Este período ya tiene un borrador. Continúa editándolo."
                       if existing.get("status") == "borrador"
                       else "La nómina seleccionada ya existe. Se abrió su detalle.")
            flash(message, "info")
            return redirect(url_for("web_rrhh.payroll_view", period_id=existing["id"]))

        selected_group = hr.get_payroll_group(company_id, selected_group_id, sandbox=sandbox)
        if not selected_group:
            flash("El grupo de nómina seleccionado no existe.", "error")
            return redirect(url_for("web_rrhh.payroll_new"))

        group_frequency = selected_group.get("frequency", "mensual")
        now = date.today()
        available_periods = _generate_periods(group_frequency, now.year)
        period_info = next((p for p in available_periods if p["key"] == period_key), None)
        if not period_info:
            flash("El período seleccionado no es válido para este grupo.", "error")
            return redirect(url_for("web_rrhh.payroll_new", group=selected_group_id))

        # ── Bloqueo secuencial (solo nóminas regulares) ──
        if period_sub_type == "regular":
            locked_keys, open_label, _closed = get_locked_periods(
                company_id, selected_group_id, available_periods, sandbox=sandbox)
            if period_key in locked_keys:
                flash(
                    f"Debes cerrar el período «{open_label or 'anterior'}» antes de crear «{period_key}».",
                    "error",
                )
                return redirect(url_for("web_rrhh.payroll_new", group=selected_group_id))

        if not hr.has_active_employee_in_payroll_group(
                company_id, selected_group_id, sandbox=sandbox):
            flash("Este grupo no tiene empleados activos. Asigna empleados al grupo antes de crear la nómina.", "error")
            return redirect(url_for("web_rrhh.payroll_new", group=selected_group_id))

    except Exception as exc:
        print(f"ERROR payroll_create preparando período: {exc}")
        flash("No se pudo validar la nómina. Verifica la conexión e inténtalo nuevamente.", "error")
        return redirect(url_for("web_rrhh.payroll_new", group=selected_group_id))

    parts = period_key.split("-")
    year = int(parts[0])
    month = int(parts[1])
    period_id = str(uuid.uuid4())
    user_email = session.get("user", {}).get("email", "")
    now_iso = datetime.now(timezone.utc).isoformat()

    period_data = {
        "id": period_id,
        "periodKey": period_key,
        "periodType": period_info.get("type", "mensual"),
        "periodSubType": period_sub_type,
        "periodRange": period_info["label"],
        "startDate": period_info["start"],
        "endDate": period_info["end"],
        "scheduledPaymentDate": period_info["end"],
        "month": month,
        "year": year,
        "revision": 1,
        "payrollGroupId": selected_group_id,
        "status": "borrador",
        "totalGross": 0.0,
        "totalNet": 0.0,
        "totalEmployerContrib": 0.0,
        "processedDate": "",
        "notes": request.form.get("notes", "").strip(),
        "calculatedBy": "",
        "calculatedAt": "",
        "statusHistory": [{
            "from": "borrador", "to": "borrador",
            "by": user_email, "at": now_iso,
            "comment": "Período creado",
        }],
    }
    try:
        saved = hr.save_payroll_period(company_id, period_id, period_data, sandbox=sandbox)
        if not saved:
            raise RuntimeError("No fue posible guardar el período de nómina.")
    except Exception as exc:
        print(f"ERROR payroll_create: {exc}")
        flash("No se pudo crear la nómina. Verifica la conexión e inténtalo nuevamente.", "error")
        return redirect(url_for("web_rrhh.payroll_new", group=selected_group_id))

    flash(f"Nómina «{period_info['label']}» creada. Revisa sus variables y pulsa «Guardar y recalcular» para procesarla.", "success")
    return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))


# ═══════════════════════════════════════════════════════════════════════════
# SIMULADOR DE NÓMINA
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/simulate", methods=["GET"])
@web_rrhh_bp.route("/rrhh/payroll/preview", methods=["POST"])
def payroll_simulate():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    if request.method == "GET":
        return redirect(url_for("web_rrhh.payroll_new"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    config = hr.get_payroll_config(company_id, sandbox=sandbox)
    if not config.get("onboardingCompleted"):
        return redirect(url_for("web_rrhh.payroll_setup"))

    from app.utils.hr_utils import is_active_equivalent
    all_active = [e for e in hr.get_employees(company_id, sandbox=sandbox)
                  if is_active_equivalent(e.get("status", ""))]

    payroll_groups = [g for g in hr.get_payroll_groups(company_id, sandbox=sandbox)
                      if g.get("isActive", True)]
    payroll_groups.sort(key=lambda g: g.get("name", ""))

    selected_group_id = request.args.get("group", "") or request.form.get("payrollGroupId", "")

    if selected_group_id and not any(g.get("id") == selected_group_id for g in payroll_groups):
        _inactive_group = hr.get_payroll_group(company_id, selected_group_id, sandbox=sandbox)
        if _inactive_group:
            payroll_groups.append(_inactive_group)
            payroll_groups.sort(key=lambda g: g.get("name", ""))

    if selected_group_id:
        selected_group = next((g for g in payroll_groups if g["id"] == selected_group_id), None)
        group_frequency = selected_group["frequency"] if selected_group else config.get("payrollFrequency", "mensual")
        employees = [e for e in all_active if selected_group_id in e.get("payrollGroupIds", [])]
    else:
        selected_group = None
        group_frequency = config.get("payrollFrequency", "mensual")
        employees = all_active

    # ── Excluir empleados con liquidación pendiente de las nóminas regulares ──
    # Solo se incluyen en la nómina tipo "liquidation" (vía _collect_liquidation_employees).
    pending_liquidation_ids = _get_pending_liquidation_employee_ids(company_id, sandbox)
    if pending_liquidation_ids:
        employees = [e for e in employees if e.get("id") not in pending_liquidation_ids]

    now = date.today()
    available_periods = _generate_periods(group_frequency, now.year)

    # ── Liquidaciones pendientes del grupo (para preseleccionar subtipo "liquidation") ──
    pending_liquidations = []
    unassigned_liquidations = []
    if selected_group_id:
        try:
            from app.services.offboarding_service import OffboardingService
            off_svc = OffboardingService(company_id, sandbox)
            all_employees_full = hr.get_employees(company_id, sandbox=sandbox)
            for s in off_svc.get_pending_settlements():
                req = off_svc.get_request(s.get("requestId", ""))
                if not req or req.get("status") in ("cancelled", "rejected"):
                    continue
                emp_id = req.get("employeeId", "")
                emp = next((e for e in all_employees_full if e["id"] == emp_id), None)
                if not emp:
                    continue
                assigned = s.get("assignedGroupId")
                if assigned == selected_group_id:
                    pending_liquidations.append(s)
                elif not assigned and selected_group_id in emp.get("payrollGroupIds", []):
                    pending_liquidations.append(s)
                elif not assigned:
                    unassigned_liquidations.append(s)
        except Exception:
            pass

        # Merge pending-liquidation employees into the visible list for UX
        existing_ids = {e.get("id") for e in employees}
        for s in pending_liquidations:
            emp_id = s.get("employeeId") or ""
            if emp_id and emp_id not in existing_ids:
                emp = next((e for e in all_employees_full if e["id"] == emp_id), None)
                if emp:
                    emp_with_flag = dict(emp)
                    emp_with_flag["isLiquidation"] = True
                    employees.append(emp_with_flag)
                    existing_ids.add(emp_id)

    simulation = None
    period_sub_type_val = "regular"

    if request.method == "POST":
        period_key = request.form.get("period_key", "")
        if payroll_groups and not selected_group_id:
            return jsonify({"error": "Debes seleccionar un grupo de nómina antes de simular."}), 400
        period_info = next((p for p in available_periods if p["key"] == period_key), None)
        start_date = period_info["start"] if period_info else ""
        end_date = period_info["end"] if period_info else ""
        period_type = period_info.get("type", "mensual") if period_info else ("quincenal" if len(period_key.split("-")) == 3 and period_key.split("-")[2] != "M" else "mensual")

        period_sub_type_val = request.form.get("periodSubType", "regular")

        period_employees, _sim_excluded = _filter_employees_by_period(employees)

        # ── Empleados inactivos retenidos en nómina (período final por nómina regular) ──
        if period_sub_type_val != "liquidation":
            all_employees_full = hr.get_employees(company_id, sandbox=sandbox)
            retained = _collect_retained_employees(all_employees_full, start_date, end_date, selected_group_id)
            existing_ids = {e.get("id") for e in period_employees}
            for re in retained:
                if re.get("id") not in existing_ids:
                    period_employees.append(re)
                    existing_ids.add(re.get("id"))

        # Empleados con liquidación pendiente: igual que en el procesamiento real,
        # la liquidación toma prioridad sobre el salario regular.
        liquidation_settlements_map = {}
        if period_sub_type_val == "liquidation" and selected_group_id:
            all_employees_full = hr.get_employees(company_id, sandbox=sandbox)
            period_employees, liquidation_settlements_map = _collect_liquidation_employees(
                company_id, sandbox, selected_group_id, all_employees_full, period_employees,
            )
        else:
            period_employees = [e for e in period_employees if not e.get("isLiquidation")]

        from datetime import timezone
        from collections import defaultdict

        lines = []
        total_gross = 0.0
        total_net = 0.0
        total_employer = 0.0
        total_costo = 0.0
        total_non_tax_deductions = 0.0
        total_taxes = 0.0

        # ── PASO 1: Resolver parámetros legales ──
        from app.services.legal_parameter_resolver import resolve_all
        params = resolve_all(company_id, end_date, sandbox=sandbox)

        group_overrides = {}
        if selected_group_id:
            _g = hr.get_payroll_group(company_id, selected_group_id, sandbox=sandbox)
            if _g:
                group_overrides = _g.get("groupOverrides", {})
                if group_overrides:
                    params = PayrollService.merge_group_overrides(params, group_overrides)

        # ── PASO 2: Cargar reglas ──
        from app.services.payroll_rule_engine import PayrollRuleEngine
        active_rules = hr.get_active_rules_for_scope(company_id, "global", sandbox=sandbox)
        if selected_group_id:
            group_rules = hr.get_active_rules_for_scope(company_id, "group", selected_group_id, sandbox=sandbox)
            active_rules.extend(group_rules)
            active_rules.sort(key=lambda r: r.get("priority", 999))

        # ── PASO 3: Cargar conceptos activos ──
        from app.services.payroll_concept_engine import get_concepts, build_concept_snapshot
        all_concepts = get_concepts(company_id, sandbox=sandbox)
        concept_map = {c["code"]: c for c in all_concepts if c.get("active")}

        # ── PASO 4: Cargar movimientos recurrentes activos (filtrados por grupo) ──
        from app.services.recurring_service import (
            get_recurring_movements, is_applicable, resolve_amount, get_exception,
            _normalize_movement_type,
        )
        active_movements = []

        for emp in period_employees:
            emp_mvs = get_recurring_movements(company_id, employee_id=emp["id"],
                                             payroll_group_id=selected_group_id, sandbox=sandbox)
            active_movements.extend(emp_mvs)
        recurring_by_employee = defaultdict(list)
        for mv in active_movements:
            recurring_by_employee[mv["employeeId"]].append(mv)

        # ── PASO 5: Cargar horas extras aprobadas del período ──
        approved_overtime = OvertimeService.get_approved_for_period(
            company_id, start_date, end_date, sandbox=sandbox,
        )
        overtime_by_employee = OvertimeService.group_by_employee_and_type(approved_overtime)

        # ── Carga masiva de dependientes para reglas ──
        all_emp_ids = [e["id"] for e in period_employees if e.get("id")]
        dependents_by_employee = hr.get_dependents_for_employees(company_id, all_emp_ids, sandbox=sandbox)
        from app.utils.hr_utils import is_minor as _is_minor_dep

        # ── Licencias aprobadas indexadas por empleado (para descuento) ──
        leave_requests_by_employee = defaultdict(list)
        try:
            for _lr in hr.get_leave_requests(company_id, sandbox=sandbox):
                _leid = _lr.get("employeeId", "")
                if _leid:
                    leave_requests_by_employee[_leid].append(_lr)
        except Exception:
            pass

        # ── Posiciones (para heredar horario del puesto) ──
        positions_by_id = {}
        positions_by_name = {}
        try:
            for _p in hr.get_catalog(company_id, "positions", sandbox=sandbox):
                positions_by_id[_p.get("id", "")] = _p
                positions_by_name[(_p.get("name", "") or "").strip().lower()] = _p
        except Exception:
            pass

        emp_var_map = _extract_variable_values(request.form, [e["id"] for e in period_employees])

        for emp in period_employees:
            emp_id = emp["id"]

            # ── Nómina de liquidación: mismo cálculo que el procesamiento real ──
            if period_sub_type_val == "liquidation" and emp_id in liquidation_settlements_map:
                settlement = liquidation_settlements_map[emp_id]
                line, liquid_tx = _build_liquidation_line(settlement, emp)
                lines.append(line)
                total_gross += line["totalIncome"]
                total_net += line["netSalary"]
                total_employer += line["totalEmployerContrib"]
                total_costo += line["totalIncome"] + line["totalEmployerContrib"]
                line_taxes = line["afpEmployee"] + line["sfsEmployee"] + line["isrRetention"]
                total_taxes += line_taxes
                total_non_tax_deductions += (line["totalDeductions"] - line_taxes)
                continue

            emp_vars = emp_var_map.get(emp_id, {})
            base = float(emp.get("baseSalary", 0))
            overtime = emp_vars.get("HORAS_EXTRA", 0)
            commission = emp_vars.get("COMISION", 0)
            bonus = emp_vars.get("BONIFICACION", 0)
            other_income_manual = emp_vars.get("OTROS_INGRESOS", 0)
            other_ded_manual = emp_vars.get("OTRAS_DEDUCCIONES", 0)

            if group_overrides.get("includeBaseSalary") is False:
                base = 0.0
            if group_overrides.get("includeCommission") is False:
                commission = 0.0
            if group_overrides.get("includeOvertime") is False:
                overtime = 0.0
            if group_overrides.get("includeBonus") is False:
                bonus = 0.0
            if group_overrides.get("includeOtherIncome") is False:
                other_income_manual = 0.0

            # ── Licencia no pagada (solo salario fijo) ──
            leave_deduction = 0.0
            leave_deduction_days = 0
            if base > 0 and (emp.get("salaryType") or "fijo") == "fijo":
                _position = positions_by_id.get(emp.get("positionId", "")) or \
                    positions_by_name.get((emp.get("position", "") or "").strip().lower())
                _work_days = PayrollService.resolve_work_days(emp, _position)
                _leave_res = PayrollService.unpaid_leave_deduction(
                    monthly_salary=base,
                    leave_requests=leave_requests_by_employee.get(emp_id, []),
                    period_start=start_date,
                    period_end=end_date,
                    company_id=company_id,
                    sandbox=sandbox,
                    working_days=float(params.get("working_days_per_month", 23.83)),
                    work_days=_work_days,
                )
                leave_deduction_days = int(_leave_res.get("days", 0))
                leave_deduction = float(_leave_res.get("amount", 0.0))

            emp_period_type = period_type
            emp_is_quincenal = emp_period_type == "quincenal"
            if emp_is_quincenal and base > 0:
                base = round(base / 2, 2)

            salary_history = hr.get_salary_history(company_id, emp_id, sandbox=sandbox)
            prorated = PayrollService.prorate_salary(
                monthly_salary=base, period_start=start_date, period_end=end_date,
                hire_date=emp.get("hireDate", ""),
                termination_date=emp.get("lastWorkDate", "") or emp.get("terminationDate", ""),
                salary_history=salary_history,
            )

            sim_period_id = f"sim_{uuid.uuid4()}"
            line_id = f"line_{uuid.uuid4()}"
            employee_transactions = []

            # ── Integración con módulo Horas Extras ──
            emp_overtime_records = overtime_by_employee.get(emp_id, {})
            overtime_breakdown = {}
            for tcode, tdata in emp_overtime_records.items():
                if tdata.get("minutes", 0) <= 0:
                    continue
                hourly = float(tdata.get("hourlyRate", 0))
                factor = float(tdata.get("factor", 1.35))
                mins = tdata.get("minutes", 0)
                amount = PayrollOvertimeCalculator.calculate_pay(hourly, mins, factor)
                if amount <= 0:
                    continue
                otype_cache = hr.get_overtime_type(company_id, tcode, sandbox=sandbox)
                concept_code = (otype_cache.get("conceptCode", "") if otype_cache else "") or "HORAS_EXTRA"
                concept = concept_map.get(concept_code) or concept_map.get("HORAS_EXTRA")
                if not concept:
                    continue
                from app.models.transaction import PayrollTransaction
                from app.services.payroll_concept_engine import build_concept_snapshot
                now_iso = datetime.now(timezone.utc).isoformat()
                tx = PayrollTransaction(
                    id=str(uuid.uuid4()),
                    periodId=sim_period_id,
                    periodKey=period_key,
                    payrollLineId=line_id,
                    employeeId=emp_id,
                    conceptCode=concept_code,
                    type="earning",
                    amount=round(amount, 2),
                    source=f"overtime:{tcode}",
                    status="applied",
                    conceptSnapshot=build_concept_snapshot(concept),
                    periodYear=int(period_key[:4]) if period_key and len(period_key) >= 4 else 0,
                    createdAt=now_iso,
                    updatedAt=now_iso,
                )
                tx_dict = tx.model_dump()
                tx_dict["overtimeRecordIds"] = tdata.get("records", [])
                employee_transactions.append(tx_dict)
                overtime_breakdown[concept_code] = overtime_breakdown.get(concept_code, 0) + amount

            # ── Salario base ──
            salario_concept = concept_map.get("SALARIO_BASE")
            if salario_concept and base > 0:
                from app.services.concept_engine import ConceptEngine
                tx = ConceptEngine.evaluate(
                    concept=salario_concept,
                    context={"baseSalary": base, "proratedSalary": prorated, "isQuincenal": emp_is_quincenal},
                    params=params,
                    period_id=sim_period_id, period_key=period_key,
                    employee_id=emp_id, contract_id=emp.get("contractId", ""),
                    payroll_line_id=line_id, period_revision=1,
                    legal_entity_id="", group_id=selected_group_id,
                )
                if tx:
                    employee_transactions.append(tx.model_dump())

            # ── Variables genéricas por concepto ──
            from app.services.payroll_variable_catalog import GROUP_OVERRIDE_BY_CONCEPT as _SIM_OVERRIDES
            for vcode, amt in emp_vars.items():
                if amt <= 0:
                    continue
                if vcode == "REGALIA_PASCUAL":
                    continue  # se maneja en el bloque de regalía
                if vcode in _SIM_OVERRIDES and group_overrides.get(_SIM_OVERRIDES[vcode]) is False:
                    continue
                concept = concept_map.get(vcode)
                if not concept:
                    continue
                from app.models.transaction import PayrollTransaction
                from app.services.payroll_concept_engine import build_concept_snapshot
                tx = PayrollTransaction(
                    id=str(uuid.uuid4()),
                    periodId=sim_period_id,
                    periodKey=period_key,
                    payrollLineId=line_id,
                    employeeId=emp_id,
                    conceptCode=vcode,
                    type=concept.get("type", "earning"),
                    amount=round(amt, 2),
                    source=f"var:{vcode}",
                    status="applied",
                    conceptSnapshot=build_concept_snapshot(concept),
                    periodYear=int(period_key[:4]) if period_key and len(period_key) >= 4 else 0,
                    createdAt=datetime.now(timezone.utc).isoformat(),
                    updatedAt=datetime.now(timezone.utc).isoformat(),
                )
                employee_transactions.append(tx.model_dump())

            # ── Regalía pascual (auto o override manual) ──
            christmas = 0.0
            if (period_sub_type_val == "christmas_bonus" or emp_vars.get("REGALIA_PASCUAL")) and base > 0:
                christmas = emp_vars.get("REGALIA_PASCUAL", 0)
                if not christmas:
                    months_worked = _months_worked_in_year(emp.get("hireDate", ""))
                    christmas = PayrollService.calculate_christmas_bonus(base, months_worked)
                if christmas > 0:
                    christmas_concept = concept_map.get("BONIFICACION", {})
                    from app.models.transaction import PayrollTransaction
                    from app.services.payroll_concept_engine import build_concept_snapshot
                    tx = PayrollTransaction(
                        id=str(uuid.uuid4()),
                        periodId=sim_period_id,
                        periodKey=period_key,
                        payrollLineId=line_id,
                        employeeId=emp_id,
                        conceptCode="REGALIA_PASCUAL",
                        type="earning",
                        amount=round(christmas, 2),
                        source="system",
                        status="applied",
                        conceptSnapshot=build_concept_snapshot(christmas_concept),
                        periodYear=int(period_key[:4]) if period_key and len(period_key) >= 4 else 0,
                        createdAt=datetime.now(timezone.utc).isoformat(),
                        updatedAt=datetime.now(timezone.utc).isoformat(),
                    )
                    employee_transactions.append(tx.model_dump())

            # ── Evaluar reglas ──
            if active_rules:
                emp_rules = list(active_rules)
                emp_specific = hr.get_active_rules_for_scope(company_id, "employee", emp_id, sandbox=sandbox)
                if emp_specific:
                    emp_rules.extend(emp_specific)
                    emp_rules.sort(key=lambda r: r.get("priority", 999))
                # En simulación no se filtran por reglas ya aplicadas (what-if)
                sim_year = int(period_key[:4]) if period_key and len(period_key) >= 4 else 0
                sim_month = int(period_key[5:7]) if period_key and len(period_key) >= 7 else 0
                filtered_rules = []
                for r in emp_rules:
                    trigger_month = r.get("triggerMonth", 0)
                    if trigger_month and trigger_month != sim_month:
                        continue
                    if _should_skip_christmas_rule(r, period_sub_type_val == "christmas_bonus" or "REGALIA_PASCUAL" in emp_vars):
                        continue
                    filtered_rules.append(r)
                # Acumulado de salario ordinario anual para reglas (ej: Salario de Navidad)
                accumulated = hr.get_ytd_transactions(company_id, emp_id, sim_year,
                                                       concept_code="SALARIO_BASE", sandbox=sandbox)
                acc_salary = sum(tx.get("amount", 0) for tx in accumulated) + base
                emp_context = dict(emp)
                emp_context["accumulatedOrdinarySalary"] = acc_salary
                hire_date = emp.get("hireDate", "")
                emp_hire_month = int(hire_date[5:7]) if hire_date and len(hire_date) >= 7 else 0
                emp_context["isAnniversaryMonth"] = 1 if emp_hire_month == sim_month else 0
                emp_context["proratedSalary"] = prorated if prorated is not None else base
                total_overtime_mins = sum(td.get("minutes", 0) for td in emp_overtime_records.values())
                emp_context["overtimeHours"] = round(total_overtime_mins / 60, 2)
                emp_deps = dependents_by_employee.get(emp_id, [])
                emp_context["dependentCount"] = len(emp_deps)
                emp_context["dependentCountMinor"] = sum(1 for d in emp_deps if _is_minor_dep(d.get("birthDate", "")))
                emp_context["dependentCountAdult"] = sum(1 for d in emp_deps if d.get("active", True) and not _is_minor_dep(d.get("birthDate", "")))
                emp_context["dependentCountStudent"] = sum(1 for d in emp_deps if d.get("active", True) and d.get("isStudent"))
                emp_context["financialDependentCount"] = sum(1 for d in emp_deps if d.get("active", True) and d.get("isFinancialDependent", True))
                try:
                    ps_date = datetime.strptime(start_date, "%Y-%m-%d").date()
                    pe_date = datetime.strptime(end_date, "%Y-%m-%d").date()
                    emp_context["daysInPeriod"] = (pe_date - ps_date).days + 1
                except (ValueError, TypeError):
                    emp_context["daysInPeriod"] = 23.83
                rule_result = PayrollRuleEngine.evaluate_rules(filtered_rules, emp_context)
                if rule_result:
                    from app.models.transaction import PayrollTransaction
                    from app.services.payroll_concept_engine import build_concept_snapshot
                    now_iso = datetime.now(timezone.utc).isoformat()
                    for applied in rule_result.get("applied_rules", []):
                        rule_name = applied.get("ruleName", "")
                        for action in applied.get("actions", []):
                            action_desc = action.get("description", "") or rule_name
                            formula = action.get("formula", "0")
                            concept_code = _resolve_rule_concept_code(action)
                            if not concept_code:
                                continue
                            value = PayrollRuleEngine._evaluate_formula(formula, emp_context)
                            if value > 0:
                                concept = concept_map.get(concept_code, {})
                                tx_type = concept.get("type", "earning")
                                tx = PayrollTransaction(
                                    id=str(uuid.uuid4()), periodId=sim_period_id, periodKey=period_key,
                                    payrollLineId=line_id, employeeId=emp_id,
                                    conceptCode=concept_code, type=tx_type,
                                    amount=round(value, 2),
                                    source=f"rule:{applied.get('ruleId', '')}",
                                    status="applied",
                                    conceptSnapshot=build_concept_snapshot(concept),
                                    periodYear=sim_year, createdAt=now_iso, updatedAt=now_iso,
                                )
                                tx_dict = tx.model_dump()
                                tx_dict["isRuleGenerated"] = True
                                tx_dict["ruleGeneratedDescription"] = action_desc
                                employee_transactions.append(tx_dict)
                    # NOTA: en simulación NO se persisten rule logs para no consumir reglas one-shot/anuales

            # ── Aplicar movimientos recurrentes (simulación, sin escribir en DB) ──
            now_iso = datetime.now(timezone.utc).isoformat()
            for mv in recurring_by_employee.get(emp_id, []):
                if not is_applicable(mv, start_date, end_date):
                    continue
                mv_id = mv.get("id", "")
                concept_code = mv.get("conceptCode", "")

                exc = get_exception(company_id, mv_id, period_key, sandbox=sandbox)
                if exc and exc.get("action") == "skip":
                    continue

                amount = resolve_amount(mv, base)
                if exc and exc.get("action") == "modify":
                    amount = float(exc.get("modifiedAmount", amount))
                if amount <= 0:
                    continue

                mv_type = _normalize_movement_type(mv.get("movementType", "deduction"))
                from app.models.transaction import PayrollTransaction
                tx = PayrollTransaction(
                    id=str(uuid.uuid4()),
                    periodId=sim_period_id,
                    periodKey=period_key,
                    payrollLineId=line_id,
                    employeeId=emp_id,
                    contractId=emp.get("contractId", ""),
                    legalEntityId="",
                    groupId=selected_group_id,
                    conceptCode=concept_code,
                    type=mv_type,
                    amount=amount,
                    source=f"recurring:{mv_id}",
                    sourceId=mv_id,
                    isRecurring=True,
                    recurringMovementId=mv_id,
                    periodRevision=1,
                    status="applied",
                    conceptSnapshot={
                        "code": concept_code,
                        "name": concept_map.get(concept_code, {}).get("name", mv.get("description", concept_code)),
                        "type": mv_type,
                        "affectsISR": mv_type == "earning",
                        "affectsTSS": mv_type == "earning",
                        "affectsNet": mv_type == "deduction",
                        "accountDebit": "",
                        "accountCredit": "",
                        "conceptVersion": 1,
                        "category": "recurring",
                        "maxPercentage": 0.0,
                    },
                    priority=mv.get("priority", 50),
                    periodYear=int(period_key[:4]) if period_key and len(period_key) >= 4 else 0,
                    notes=mv.get("description", ""),
                    createdAt=now_iso,
                    updatedAt=now_iso,
                )
                employee_transactions.append(tx.model_dump())

            # ── Licencia no pagada (descuento) ──
            if leave_deduction > 0:
                lic_concept = concept_map.get("DESC_LICENCIA")
                if lic_concept:
                    from app.models.transaction import PayrollTransaction as _PTx
                    from app.services.payroll_concept_engine import build_concept_snapshot as _bcs
                    employee_transactions.append(_PTx(
                        id=str(uuid.uuid4()), periodId=sim_period_id, periodKey=period_key,
                        payrollLineId=line_id, employeeId=emp_id,
                        conceptCode="DESC_LICENCIA", type="deduction",
                        amount=round(leave_deduction, 2), source="leave", status="applied",
                        conceptSnapshot=_bcs(lic_concept),
                        periodYear=int(period_key[:4]) if period_key and len(period_key) >= 4 else 0,
                        createdAt=datetime.now(timezone.utc).isoformat(),
                        updatedAt=datetime.now(timezone.utc).isoformat(),
                    ).model_dump())

            # ── Calcular ingresos totales para TSS e ISR ──
            gross_income = sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("type") == "earning")
            cotizable_income = max(0.0, gross_income - leave_deduction)
            emp_name = emp.get("fullName", emp_id)

            # ── TSS vía ConceptEngine ──
            for tss_code in ["AFP_EMPLEADO", "SFS_EMPLEADO", "INFOTEP_EMPLEADO",
                             "AFP_EMPLEADOR", "SFS_EMPLEADOR", "SRL_EMPLEADOR", "INFOTEP_EMPLEADOR"]:
                concept = concept_map.get(tss_code)
                if not concept:
                    continue
                from app.services.concept_engine import ConceptEngine as CE
                tx = CE.evaluate(
                    concept=concept,
                    context={"baseSalary": base, "grossIncome": cotizable_income, "isQuincenal": emp_is_quincenal},
                    params=params,
                    period_id=sim_period_id, period_key=period_key,
                    employee_id=emp_id, contract_id=emp.get("contractId", ""),
                    payroll_line_id=line_id, period_revision=1,
                    legal_entity_id="", group_id=selected_group_id,
                )
                if tx:
                    employee_transactions.append(tx.model_dump())
                else:
                    pass

            # ── ISR vía ConceptEngine ──
            # Extraer AFP/SFS ya calculados para restarlos de la base imponible (consistente con PayrollService)
            afp_ded = sum(
                float(t.get("amount", 0)) for t in employee_transactions
                if t.get("conceptCode") == "AFP_EMPLEADO"
            )
            sfs_ded = sum(
                float(t.get("amount", 0)) for t in employee_transactions
                if t.get("conceptCode") == "SFS_EMPLEADO"
            )
            isr_concept = concept_map.get("ISR_RETENCION")
            if isr_concept:
                from app.services.concept_engine import ConceptEngine as CE
                tx = CE.evaluate(
                    concept=isr_concept,
                    context={
                        "baseSalary": base, "grossIncome": cotizable_income,
                        "isQuincenal": emp_is_quincenal, "ytd_isr": 0,
                        "afpDeduction": afp_ded, "sfsDeduction": sfs_ded,
                    },
                    params=params,
                    period_id=sim_period_id, period_key=period_key,
                    employee_id=emp_id, contract_id=emp.get("contractId", ""),
                    payroll_line_id=line_id, period_revision=1,
                )
                if tx:
                    employee_transactions.append(tx.model_dump())
            else:
                pass

            # ── Aplicar motor de prioridad para descuentos ──
            from app.services.deduction_priority_engine import DeductionPriorityEngine
            priority_result = DeductionPriorityEngine.process(employee_transactions, params)
            # Merge processed deductions back, preserving earnings & employer_contrib
            processed_deductions = {id(t): t for t in priority_result["transactions"]}
            employee_transactions = [
                processed_deductions.get(id(t), t)
                if t.get("type") == "deduction"
                else t
                for t in employee_transactions
            ]

            # ── Construir line dict compatible con template ──
            earn = sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("type") == "earning")
            deduct = sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("type") == "deduction")
            employer = sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("type") == "employer_contrib")

            def sum_by_concept(tx_list, *codes):
                return sum(float(t.get("amount", 0)) for t in tx_list if t.get("conceptCode") in codes and not t.get("isRuleGenerated"))

            overtime_hours_val = float(overtime)

            recurring_earnings = sum(
                float(t.get("amount", 0)) for t in employee_transactions
                if t.get("isRecurring") and not t.get("isRuleGenerated") and t.get("type") == "earning"
            )
            recurring_additions_details = []
            for t in employee_transactions:
                if (t.get("isRecurring") or t.get("isRuleGenerated")) and t.get("type") == "earning":
                    cname = concept_map.get(t.get("conceptCode", ""), {}).get("name", t.get("conceptSnapshot", {}).get("name", t.get("conceptCode", "")))
                    desc = t.get("ruleGeneratedDescription", cname) if t.get("isRuleGenerated") else cname
                    recurring_additions_details.append({"description": desc, "amount": float(t.get("amount", 0))})
            recurring_deductions_details = []
            for t in employee_transactions:
                if (t.get("isRecurring") or t.get("isRuleGenerated")) and t.get("type") == "deduction":
                    cname = concept_map.get(t.get("conceptCode", ""), {}).get("name", t.get("conceptSnapshot", {}).get("name", t.get("conceptCode", "")))
                    desc = t.get("ruleGeneratedDescription", cname) if t.get("isRuleGenerated") else cname
                    recurring_deductions_details.append({"description": desc, "amount": float(t.get("amount", 0))})

            line = {
                "employeeId": emp_id,
                "employeeName": emp.get("fullName", ""),
                "position": emp.get("position", ""),
                "periodType": emp_period_type,
                "grossSalary": sum_by_concept(employee_transactions, "SALARIO_BASE"),
                "overtimePay": round(sum(overtime_breakdown.values()) + overtime, 2),
                "overtimeHours": overtime_hours_val,
                "overtimeBreakdown": overtime_breakdown,
                "commission": sum_by_concept(employee_transactions, "COMISION"),
                "bonus": sum_by_concept(employee_transactions, "BONIFICACION"),
                "christmasBonus": round(christmas, 2),
                "otherIncome": round(recurring_earnings + build_manual_other_income(employee_transactions), 2),
                "totalIncome": round(earn, 2),
                "totalDeductions": round(deduct, 2),
                "netSalary": round(max(0, earn - deduct), 2),
                "totalEmployerContrib": round(employer, 2),
                "afpEmployee": sum_by_concept(employee_transactions, "AFP_EMPLEADO"),
                "sfsEmployee": sum_by_concept(employee_transactions, "SFS_EMPLEADO"),
                "isrRetention": sum_by_concept(employee_transactions, "ISR_RETENCION"),
                "otherDeductions": build_manual_other_deductions(employee_transactions),
                "leaveDeduction": round(leave_deduction, 2),
                "leaveDeductionDays": leave_deduction_days,
                "recurringDeductionsBreakdown": recurring_deductions_details,
                "recurringAdditionsBreakdown": recurring_additions_details,
            }

            # Ensure rule-generated amounts are excluded from fixed columns
            # (they appear in dynamic columns via the breakdown/map mechanism)
            line["bonus"] = sum_by_concept(employee_transactions, "BONIFICACION")
            line["commission"] = sum_by_concept(employee_transactions, "COMISION")
            line["otherIncome"] = round(recurring_earnings + build_manual_other_income(employee_transactions), 2)

            lines.append(line)
            total_gross += line["totalIncome"]
            total_net += line["netSalary"]
            total_employer += line["totalEmployerContrib"]
            total_costo += line["totalIncome"] + line["totalEmployerContrib"]
            line_taxes = line["afpEmployee"] + line["sfsEmployee"] + line["isrRetention"]
            total_taxes += line_taxes
            total_non_tax_deductions += (line["totalDeductions"] - line_taxes)

        all_recurring_descs = []
        all_recurring_additions_descs = []
        for line in lines:
            for d in line.get("recurringDeductionsBreakdown", []):
                if d["description"] not in all_recurring_descs:
                    all_recurring_descs.append(d["description"])
            line["recurringDeductionsMap"] = {
                d["description"]: d["amount"]
                for d in line.get("recurringDeductionsBreakdown", [])
            }
            for d in line.get("recurringAdditionsBreakdown", []):
                if d["description"] not in all_recurring_additions_descs:
                    all_recurring_additions_descs.append(d["description"])
            line["recurringAdditionsMap"] = {
                d["description"]: d["amount"]
                for d in line.get("recurringAdditionsBreakdown", [])
            }

        all_overtime_cols = []
        overtime_type_names = {}
        for line in lines:
            for code in line.get("overtimeBreakdown", {}):
                if code not in all_overtime_cols:
                    all_overtime_cols.append(code)
                    c = concept_map.get(code) if code in concept_map else None
                    overtime_type_names[code] = c.get("name", code) if c else code
        overtime_columns = [{"code": c, "name": overtime_type_names.get(c, c)} for c in all_overtime_cols]

        liquidation_columns = _build_liquidation_columns(lines)

        simulation = {
            "period_range": period_info["label"] if period_info else period_key,
            "period_type": period_type,
            "employee_count": len(period_employees),
            "excluded_count": len(_sim_excluded),
            "total_gross": round(total_gross, 2),
            "total_net": round(total_net, 2),
            "total_employer": round(total_employer, 2),
            "total_costo": round(total_costo, 2),
            "total_non_tax_deductions": round(total_non_tax_deductions, 2),
            "total_taxes": round(total_taxes, 2),
            "total_egresos": round(total_non_tax_deductions + total_taxes, 2),
            "recurringDeductionColumns": all_recurring_descs,
            "recurringAdditionsColumns": all_recurring_additions_descs,
            "overtimeColumns": overtime_columns,
            "liquidationColumns": liquidation_columns,
            "lines": lines,
        }

    return jsonify(simulation)
