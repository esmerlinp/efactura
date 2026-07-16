"""RRHH module — auto-extracted."""
"""Payroll processing — refactored with ConceptEngine, RecurringService, PayrollTransaction."""

import uuid
from datetime import date, datetime
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.payroll_service import PayrollService
from app.services.payroll_ytd_service import get_ytd, save_ytd, accumulate_ytd
from app.services.payroll_static_data import DEFAULT_PAYROLL_CONFIG
from app.services.payroll_audit_service import log_action


# ═══════════════════════════════════════════════════════════════════════════
# NÓMINA — Procesar
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/new", methods=["GET", "POST"])
def payroll_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService
    from app.services.payroll_ytd_service import get_ytd, save_ytd, accumulate_ytd
    from app.services.payroll_static_data import DEFAULT_PAYROLL_CONFIG

    # Verificar onboarding
    config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
    if not config.get("onboardingCompleted"):
        return redirect(url_for("web_rrhh.onboarding_guide"))

    all_employees = hr.get_employees(owner_uid, sandbox=sandbox)
    active_employees = [e for e in all_employees if e.get("status") == "activo"]

    # ── Grupos de nómina ──
    payroll_groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    payroll_groups.sort(key=lambda g: g.get("name", ""))

    # Seleccionar grupo
    selected_group_id = request.args.get("group", "") or request.form.get("payrollGroupId", "")

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

    # Pre-validación de incidencias
    incidencias = PayrollService.validate_employees_before_payroll(employees) if employees else {"errors": [], "warnings": []}

    now = date.today()
    available_periods = _generate_periods(group_frequency, now.year)

    if request.method == "POST":
        period_key = request.form.get("period_key", "")
        if not period_key:
            flash("Debes seleccionar un período.", "error")
            return redirect(url_for("web_rrhh.payroll_new"))

        # ── Anti-duplicados ──
        if selected_group_id:
            existing = hr.get_payroll_period_by_key_and_group(owner_uid, period_key, selected_group_id, sandbox=sandbox)
            if existing:
                flash(f"Ya existe una nómina para el período «{period_key}» en el grupo «{selected_group.get('name', '')}».", "warning")
                return render_template("rrhh/payroll_form.html", active_page="rrhh_payroll",
               employees=employees, now=now,
                        available_periods=available_periods, frequency=group_frequency,
                        show_christmas_bonus=(now.month >= 11),
                        payroll_groups=payroll_groups,
                        selected_group_id=selected_group_id,
                        existing_period=existing,
                        incidencias=incidencias)
        else:
            existing = hr.get_payroll_period_by_key(owner_uid, period_key, sandbox=sandbox)
            if existing:
                flash(f"Ya existe una nómina para el período «{period_key}».", "warning")
                return render_template("rrhh/payroll_form.html", active_page="rrhh_payroll",
                                        employees=employees, now=now,
                                        available_periods=available_periods, frequency=group_frequency,
                                        show_christmas_bonus=(now.month >= 11),
                                        payroll_groups=payroll_groups,
                                        selected_group_id=selected_group_id,
                                        existing_period=existing,
                                        incidencias=incidencias)

        # Parse period key
        parts = period_key.split("-")
        year = int(parts[0])
        month = int(parts[1])

        period_info = next((p for p in available_periods if p["key"] == period_key), None)
        period_range = period_info["label"] if period_info else ""
        start_date = period_info["start"] if period_info else ""
        end_date = period_info["end"] if period_info else ""
        period_type = period_info.get("type", "mensual") if period_info else ("quincenal" if len(parts) == 3 and parts[2] != "M" else "mensual")

        period_employees, excluded = _filter_employees_by_period(employees, period_key)
        period_id = str(uuid.uuid4())
        lines = []

        # Pre-validación: bloquear si hay errores antes de calcular
        period_incidencias = PayrollService.validate_employees_before_payroll(period_employees)
        if period_incidencias.get("errors"):
            for err in period_incidencias["errors"]:
                flash(f"{err['employeeName']}: {err['issue']}", "error")
            flash("Corrige los errores antes de procesar la nómina.", "error")
            return render_template("rrhh/payroll_form.html", active_page="rrhh_payroll",
                                   employees=employees, now=now,
                                   available_periods=available_periods, frequency=group_frequency,
                                   show_christmas_bonus=(now.month >= 11),
                                   payroll_groups=payroll_groups,
                                   selected_group_id=selected_group_id,
                                   incidencias=period_incidencias)
        all_transactions = []
        all_applications = []

        # ── PASO 1: Resolver parámetros legales históricos ──
        from app.services.legal_parameter_resolver import resolve_all
        params = resolve_all(owner_uid, end_date, sandbox=sandbox)

        # Aplicar overrides del grupo
        group_overrides = {}
        if selected_group_id:
            _group = hr.get_payroll_group(owner_uid, selected_group_id, sandbox=sandbox)
            if _group:
                group_overrides = _group.get("groupOverrides", {})
                if group_overrides:
                    params = PayrollService.merge_group_overrides(params, group_overrides)

        # ── PASO 2: Cargar reglas ──
        active_rules = hr.get_active_rules_for_scope(owner_uid, "global", sandbox=sandbox)
        if selected_group_id:
            group_rules = hr.get_active_rules_for_scope(owner_uid, "group", selected_group_id, sandbox=sandbox)
            active_rules.extend(group_rules)
            active_rules.sort(key=lambda r: r.get("priority", 999))

        # ── PASO 3: Cargar conceptos activos ──
        from app.services.payroll_concept_engine import get_concepts, build_concept_snapshot
        all_concepts = get_concepts(owner_uid, sandbox=sandbox)
        concept_map = {c["code"]: c for c in all_concepts if c.get("active")}

        # ── PASO 4: Cargar movimientos recurrentes activos (filtrados por grupo) ──
        from app.services.recurring_service import (
            get_recurring_movements, apply_recurring_for_employee, reverse_applications
        )
        from collections import defaultdict
        active_movements = []
        for emp in period_employees:
            emp_mvs = get_recurring_movements(owner_uid, employee_id=emp["id"],
                                              payroll_group_id=selected_group_id, sandbox=sandbox)
            active_movements.extend(emp_mvs)
        # Indexar por employeeId
        recurring_by_employee = defaultdict(list)
        for mv in active_movements:
            recurring_by_employee[mv["employeeId"]].append(mv)

        total_gross = 0.0
        total_net = 0.0
        total_employer = 0.0

        for emp in period_employees:
            emp_id = emp["id"]
            base = float(emp.get("baseSalary", 0))
            overtime = float(request.form.get(f"overtime_{emp_id}", 0) or 0)
            commission = float(request.form.get(f"commission_{emp_id}", 0) or 0)
            bonus = float(request.form.get(f"bonus_{emp_id}", 0) or 0)
            other_income_manual = float(request.form.get(f"other_income_{emp_id}", 0) or 0)
            other_ded_manual = float(request.form.get(f"other_ded_{emp_id}", 0) or 0)

            # Aplicar toggles del grupo
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

            emp_period_type = period_type
            emp_is_quincenal = emp_period_type == "quincenal"
            if emp_is_quincenal and base > 0:
                base = round(base / 2, 2)
            line_id = str(uuid.uuid4())

            # Colección de transacciones para este empleado
            employee_transactions = []

            # ── Prorrateo salarial ──
            salary_history = hr.get_salary_history(owner_uid, emp_id, sandbox=sandbox)
            prorated = PayrollService.prorate_salary(
                monthly_salary=base, period_start=start_date, period_end=end_date,
                hire_date=emp.get("hireDate", ""),
                termination_date=emp.get("terminationDate", ""),
                salary_history=salary_history,
            )

            # ── Salario base ──
            salario_concept = concept_map.get("SALARIO_BASE")
            if salario_concept and base > 0:
                from app.services.concept_engine import ConceptEngine
                tx = ConceptEngine.evaluate(
                    concept=salario_concept,
                    context={"baseSalary": base, "proratedSalary": prorated, "isQuincenal": emp_is_quincenal},
                    params=params,
                    period_id=period_id, period_key=period_key,
                    employee_id=emp_id, contract_id=emp.get("contractId", ""),
                    payroll_line_id=line_id, period_revision=1,
                    legal_entity_id="", group_id=selected_group_id,
                )
                if tx:
                    employee_transactions.append(tx.model_dump())

            # ── Horas extra, comisión, bonificación (variable movements) ──
            var_items = [
                ("HORAS_EXTRA", overtime, "overtime"),
                ("COMISION", commission, "commission"),
                ("BONIFICACION", bonus, "bonus"),
                ("OTROS_INGRESOS", other_income_manual, "manual"),
            ]
            for concept_code, amount, source_type in var_items:
                if amount <= 0:
                    continue
                concept = concept_map.get(concept_code)
                if not concept:
                    continue
                from app.models.transaction import PayrollTransaction
                tx = PayrollTransaction(
                    id=str(uuid.uuid4()),
                    periodId=period_id,
                    periodKey=period_key,
                    payrollLineId=line_id,
                    employeeId=emp_id,
                    conceptCode=concept_code,
                    type="earning",
                    amount=round(amount, 2),
                    source=source_type,
                    status="applied",
                    conceptSnapshot=build_concept_snapshot(concept),
                    periodYear=year,
                    createdAt=datetime.now(timezone.utc).isoformat(),
                    updatedAt=datetime.now(timezone.utc).isoformat(),
                )
                employee_transactions.append(tx.model_dump())

            # ── Regla pascual ──
            if request.form.get("include_christmas_bonus") == "1":
                months_worked = emp.get("hireDate") and max(1, (date.today().month - int(emp["hireDate"][5:7]) + 1)) or 12
                if months_worked > 12:
                    months_worked = 12
                christmas = PayrollService.calculate_christmas_bonus(base, months_worked)
                if christmas > 0:
                    christmas_concept = concept_map.get("BONIFICACION", {})
                    tx = PayrollTransaction(
                        id=str(uuid.uuid4()),
                        periodId=period_id, periodKey=period_key, payrollLineId=line_id,
                        employeeId=emp_id, conceptCode="REGALIA_PASCUAL", type="earning",
                        amount=round(christmas, 2), source="system", status="applied",
                        conceptSnapshot=build_concept_snapshot(christmas_concept),
                        periodYear=year, createdAt=datetime.now(timezone.utc).isoformat(),
                        updatedAt=datetime.now(timezone.utc).isoformat(),
                    )
                    employee_transactions.append(tx.model_dump())

            # ── Evaluar reglas ──
            if active_rules:
                from app.services.payroll_rule_engine import PayrollRuleEngine
                emp_rules = list(active_rules)
                emp_specific = hr.get_active_rules_for_scope(owner_uid, "employee", emp_id, sandbox=sandbox)
                if emp_specific:
                    emp_rules.extend(emp_specific)
                    emp_rules.sort(key=lambda r: r.get("priority", 999))
                # Filtrar reglas one-shot ya aplicadas
                filtered_rules = []
                for r in emp_rules:
                    freq = r.get("frequency", "always")
                    if freq == "always":
                        filtered_rules.append(r)
                    elif freq in ("annual", "once"):
                        log_year = year if freq == "annual" else None
                        if not hr.rule_log_exists(owner_uid, r["id"], emp_id, log_year, sandbox=sandbox):
                            filtered_rules.append(r)
                rule_result = PayrollRuleEngine.evaluate_rules(filtered_rules, emp)
                if rule_result:
                    for rule_concept, rule_amount in [
                        ("BONIFICACION", rule_result.get("bonus", 0)),
                        ("COMISION", rule_result.get("commission", 0)),
                        ("OTROS_INGRESOS", rule_result.get("other_income", 0)),
                        ("OTRAS_DEDUCCIONES", rule_result.get("deduction", 0)),
                    ]:
                        if rule_amount > 0:
                            concept = concept_map.get(rule_concept, {})
                            tx = PayrollTransaction(
                                id=str(uuid.uuid4()), periodId=period_id, periodKey=period_key,
                                payrollLineId=line_id, employeeId=emp_id,
                                conceptCode=rule_concept,
                                type="deduction" if rule_concept == "OTRAS_DEDUCCIONES" else "earning",
                                amount=round(rule_amount, 2), source=f"rule:{rule_result.get('_ruleId', '')}",
                                status="applied", conceptSnapshot=build_concept_snapshot(concept),
                                periodYear=year, createdAt=datetime.now(timezone.utc).isoformat(),
                                updatedAt=datetime.now(timezone.utc).isoformat(),
                            )
                            employee_transactions.append(tx.model_dump())
                    # Loguear reglas one-shot aplicadas
                    now_iso = datetime.now(timezone.utc).isoformat()
                    for applied in rule_result.get("applied_rules", []):
                        rule_obj = next((r for r in emp_rules if r["id"] == applied["ruleId"]), None)
                        if rule_obj and rule_obj.get("frequency") in ("annual", "once"):
                            log_year = year if rule_obj.get("frequency") == "annual" else None
                            hr.save_rule_log(owner_uid, rule_obj["id"], emp_id, log_year,
                                             period_key, 0.0, now_iso, sandbox=sandbox)

            # ── Aplicar movimientos recurrentes ──
            recurring_txs, recurring_apps = apply_recurring_for_employee(
                owner_uid, emp_id, emp.get("contractId", ""), base,
                period_id, period_key, start_date, end_date, 1,
                recurring_by_employee,
                legal_entity_id="", group_id=selected_group_id, sandbox=sandbox,
            )
            for tx in recurring_txs:
                tx["payrollLineId"] = line_id
            employee_transactions.extend(recurring_txs)
            all_applications.extend(recurring_apps)

            # ── Calcular ingresos totales del empleado para TSS e ISR ──
            gross_income = sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("type") == "earning")

            # ── Calcular TSS e ISR como transacciones (vía ConceptEngine) ──
            for tss_code in ["AFP_EMPLEADO", "SFS_EMPLEADO", "INFOTEP_EMPLEADO",
                             "AFP_EMPLEADOR", "SFS_EMPLEADOR", "SRL_EMPLEADOR", "INFOTEP_EMPLEADOR"]:
                concept = concept_map.get(tss_code)
                if not concept:
                    continue
                from app.services.concept_engine import ConceptEngine as CE
                tx = CE.evaluate(
                    concept=concept,
                    context={"baseSalary": base, "grossIncome": gross_income, "isQuincenal": emp_is_quincenal},
                    params=params,
                    period_id=period_id, period_key=period_key,
                    employee_id=emp_id, contract_id=emp.get("contractId", ""),
                    payroll_line_id=line_id, period_revision=1,
                    legal_entity_id="", group_id=selected_group_id,
                )
                if tx:
                    employee_transactions.append(tx.model_dump())

            # ISR
            isr_concept = concept_map.get("ISR_RETENCION")
            if isr_concept:
                ytd_data = get_ytd(owner_uid, emp_id, year, sandbox=sandbox)
                ytd_isr = ytd_data.get("isrRetention", 0) if ytd_data else 0
                from app.services.concept_engine import ConceptEngine as CE
                tx = CE.evaluate(
                    concept=isr_concept,
                    context={
                        "baseSalary": base, "grossIncome": gross_income,
                        "isQuincenal": emp_is_quincenal, "ytd_isr": ytd_isr,
                    },
                    params=params,
                    period_id=period_id, period_key=period_key,
                    employee_id=emp_id, contract_id=emp.get("contractId", ""),
                    payroll_line_id=line_id, period_revision=1,
                )
                if tx:
                    employee_transactions.append(tx.model_dump())

            # ── Aplicar motor de prioridad para descuentos ──
            from app.services.deduction_priority_engine import DeductionPriorityEngine
            priority_result = DeductionPriorityEngine.process(employee_transactions, params)

            # ── Fusionar descuentos procesados preservando ingresos y contribuciones ──
            processed_deductions = {id(t): t for t in priority_result["transactions"]}
            employee_transactions = [
                processed_deductions.get(id(t), t)
                if t.get("type") == "deduction"
                else t
                for t in employee_transactions
            ]
            for warn in priority_result.get("warnings", []):
                flash(f"[{emp.get('fullName', emp_id)}] {warn}", "warning")

            # ── Construir PayrollLine con resumen ──
            recurring_details = []
            recurring_additions_details = []
            tx_summary = []
            for tx in employee_transactions:
                if isinstance(tx, dict):
                    ccode = tx.get("conceptCode", "")
                    cname = concept_map.get(ccode, {}).get("name", tx.get("conceptSnapshot", {}).get("name", ccode))
                    is_rec = tx.get("isRecurring", False)
                    tx_summary.append({
                        "conceptCode": ccode,
                        "amount": tx.get("amount", 0),
                        "type": tx.get("type", ""),
                        "isRecurring": is_rec,
                        "conceptName": cname,
                    })
                    if is_rec and tx.get("type") == "deduction":
                        recurring_details.append({"description": cname, "amount": float(tx.get("amount", 0))})
                    if is_rec and tx.get("type") == "earning":
                        recurring_additions_details.append({"description": cname, "amount": float(tx.get("amount", 0))})
                else:
                    tx_summary.append({
                        "conceptCode": getattr(tx, "conceptCode", ""),
                        "amount": getattr(tx, "amount", 0),
                        "type": getattr(tx, "type", ""),
                    })

            # Extraer totals por categoría
            earn = sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("type") == "earning")
            deduct = sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("type") == "deduction")
            employer = sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("type") == "employer_contrib")
            net = max(0, earn - deduct)
            recurring_earnings = sum(
                float(t.get("amount", 0)) for t in employee_transactions
                if t.get("isRecurring") and t.get("type") == "earning"
            )

            line = {
                "employeeId": emp_id,
                "employeeName": emp.get("fullName", ""),
                "cedula": emp.get("cedula", ""),
                "position": emp.get("position", ""),
                "department": emp.get("department", ""),
                "baseSalary": base,
                "grossSalary": base,
                "overtimePay": overtime,
                "overtimeHours": float(request.form.get(f"overtime_{emp_id}", 0) or 0),
                "commission": commission,
                "bonus": bonus,
                "otherIncome": round(other_income_manual + recurring_earnings, 2),
                "periodType": emp_period_type,
                "transactionSummary": tx_summary,
                "totalIncome": round(earn, 2),
                "totalDeductions": round(deduct, 2),
                "netSalary": round(net, 2),
                "totalEmployerContrib": round(employer, 2),

                # TSS legacy (backward compat)
                "afpEmployee": sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") == "AFP_EMPLEADO"),
                "sfsEmployee": sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") == "SFS_EMPLEADO"),
                "infotepEmployee": sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") == "INFOTEP_EMPLEADO"),
                "isrRetention": sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") == "ISR_RETENCION"),
                "afpEmployer": sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") == "AFP_EMPLEADOR"),
                "sfsEmployer": sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") == "SFS_EMPLEADOR"),
                "srlEmployer": sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") == "SRL_EMPLEADOR"),
                "infotepEmployer": sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") == "INFOTEP_EMPLEADOR"),
                "otherDeductions": round(sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") in ("OTRAS_DEDUCCIONES",) and not t.get("isRecurring")), 2),
                "recurringDeductionsBreakdown": recurring_details,
                "recurringAdditionsBreakdown": recurring_additions_details,
            }

            lines.append(line)
            all_transactions.extend(employee_transactions)
            total_gross += line["totalIncome"]
            total_net += line["netSalary"]
            total_employer += line["totalEmployerContrib"]

            # ── YTD ──
            try:
                ytd = get_ytd(owner_uid, emp_id, year, sandbox=sandbox)
                ytd = accumulate_ytd(ytd, line, period_factor=24 if emp_is_quincenal else 12, period_key=period_key)
                save_ytd(owner_uid, emp_id, year, ytd, sandbox=sandbox)
            except Exception as e:
                print(f"⚠️ YTD accumulation error for employee {emp_id}: {e}")

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

        period_data = {
            "id": period_id,
            "periodKey": period_key,
            "periodType": period_type,
            "periodSubType": request.form.get("periodSubType", "regular"),
            "periodRange": period_range,
            "startDate": start_date,
            "endDate": end_date,
            "scheduledPaymentDate": request.form.get("scheduledPaymentDate", "").strip() or end_date,
            "month": month,
            "year": year,
            "revision": 1,
            "payrollGroupId": selected_group_id,
            "status": "calculada",
            "totalGross": round(total_gross, 2),
            "totalNet": round(total_net, 2),
            "totalEmployerContrib": round(total_employer, 2),
            "processedDate": now.isoformat(),
            "notes": request.form.get("notes", "").strip(),
            "calculatedBy": session.get("user", {}).get("email", ""),
            "calculatedAt": now.isoformat(),
            "taxRatesSnapshot": params,
            "appliedRatesDate": now.isoformat(),
            "parameterVersions": {},
            "lineCount": len(lines),
            "recurringDeductionColumns": all_recurring_descs,
            "recurringAdditionsColumns": all_recurring_additions_descs,
            "statusHistory": [{
                "from": "borrador",
                "to": "calculada",
                "by": session.get("user", {}).get("email", ""),
                "at": now.isoformat(),
                "comment": "Nómina calculada",
            }],
        }
        saved = hr.save_payroll_period(owner_uid, period_id, period_data, sandbox=sandbox)
        if not saved:
            flash("Error al guardar el período en la base de datos. Intenta nuevamente.", "error")
            return render_template("rrhh/payroll_form.html", active_page="rrhh_payroll",
                                   employees=employees, now=now,
                                   available_periods=available_periods, frequency=group_frequency,
                                   show_christmas_bonus=(now.month >= 11),
                                   payroll_groups=payroll_groups,
                                   selected_group_id=selected_group_id,
                                   incidencias=incidencias)

        hr.save_payroll_lines_batch(owner_uid, period_id, lines, sandbox=sandbox)
        hr.save_payroll_transactions_batch(owner_uid, all_transactions, sandbox=sandbox)
        from app.services.recurring_service import save_applications_batch
        save_applications_batch(owner_uid, all_applications, sandbox=sandbox)

        emp_map = {e["id"]: e for e in period_employees}
        anomalies = PayrollService.detect_anomalies(lines, emp_map, owner_uid=owner_uid, sandbox=sandbox)

        log_action(owner_uid, "calculate", "payroll_period", period_id,
                   session.get("user", {}).get("email", ""),
                   changes={"period": period_key, "employees": len(lines), "total_net": round(total_net, 2)}, sandbox=sandbox)

        for err in anomalies.get("errors", []):
            flash(f"[Error] {err}", "error")
        for warn in anomalies.get("warnings", []):
            flash(f"[Advertencia] {warn}", "warning")
        flash(f"Nómina {period_range or period_key} calculada: {len(lines)} empleados, neto RD$ {total_net:,.2f}.", "success")
        return redirect(url_for("web_rrhh.payroll_view", period_id=period_id))

    return render_template("rrhh/payroll_form.html", active_page="rrhh_payroll",
                           employees=employees, now=now,
                           available_periods=available_periods, frequency=group_frequency,
                           show_christmas_bonus=(now.month >= 11),
                           payroll_groups=payroll_groups,
                           selected_group_id=selected_group_id,
                           incidencias=incidencias)


# ═══════════════════════════════════════════════════════════════════════════
# SIMULADOR DE NÓMINA
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/simulate", methods=["GET", "POST"])
def payroll_simulate():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    from app.services.payroll_service import PayrollService

    config = hr.get_payroll_config(owner_uid, sandbox=sandbox)
    if not config.get("onboardingCompleted"):
        return redirect(url_for("web_rrhh.payroll_setup"))

    all_active = [e for e in hr.get_employees(owner_uid, sandbox=sandbox) if e.get("status") == "activo"]

    payroll_groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    payroll_groups.sort(key=lambda g: g.get("name", ""))

    selected_group_id = request.args.get("group", "") or request.form.get("payrollGroupId", "")

    if selected_group_id:
        selected_group = next((g for g in payroll_groups if g["id"] == selected_group_id), None)
        group_frequency = selected_group["frequency"] if selected_group else config.get("payrollFrequency", "mensual")
        employees = [e for e in all_active if selected_group_id in e.get("payrollGroupIds", [])]
    else:
        selected_group = None
        group_frequency = config.get("payrollFrequency", "mensual")
        employees = all_active

    now = date.today()
    available_periods = _generate_periods(group_frequency, now.year)

    simulation = None

    if request.method == "POST":
        period_key = request.form.get("period_key", "")
        period_info = next((p for p in available_periods if p["key"] == period_key), None)
        start_date = period_info["start"] if period_info else ""
        end_date = period_info["end"] if period_info else ""
        period_type = period_info.get("type", "mensual") if period_info else ("quincenal" if len(period_key.split("-")) == 3 and period_key.split("-")[2] != "M" else "mensual")

        period_employees, _sim_excluded = _filter_employees_by_period(employees)

        from datetime import timezone
        from collections import defaultdict

        lines = []
        total_gross = 0.0
        total_net = 0.0
        total_employer = 0.0
        total_costo = 0.0

        # ── PASO 1: Resolver parámetros legales ──
        from app.services.legal_parameter_resolver import resolve_all
        params = resolve_all(owner_uid, end_date, sandbox=sandbox)

        group_overrides = {}
        if selected_group_id:
            _g = hr.get_payroll_group(owner_uid, selected_group_id, sandbox=sandbox)
            if _g:
                group_overrides = _g.get("groupOverrides", {})
                if group_overrides:
                    params = PayrollService.merge_group_overrides(params, group_overrides)

        # ── PASO 2: Cargar reglas ──
        from app.services.payroll_rule_engine import PayrollRuleEngine
        active_rules = hr.get_active_rules_for_scope(owner_uid, "global", sandbox=sandbox)
        if selected_group_id:
            group_rules = hr.get_active_rules_for_scope(owner_uid, "group", selected_group_id, sandbox=sandbox)
            active_rules.extend(group_rules)
            active_rules.sort(key=lambda r: r.get("priority", 999))

        # ── PASO 3: Cargar conceptos activos ──
        from app.services.payroll_concept_engine import get_concepts, build_concept_snapshot
        all_concepts = get_concepts(owner_uid, sandbox=sandbox)
        concept_map = {c["code"]: c for c in all_concepts if c.get("active")}

        # ── PASO 4: Cargar movimientos recurrentes activos (filtrados por grupo) ──
        from app.services.recurring_service import (
            get_recurring_movements, is_applicable, resolve_amount, get_exception,
            _normalize_movement_type,
        )
        active_movements = []

        for emp in period_employees:
            emp_mvs = get_recurring_movements(owner_uid, employee_id=emp["id"],
                                             payroll_group_id=selected_group_id, sandbox=sandbox)
            active_movements.extend(emp_mvs)
        recurring_by_employee = defaultdict(list)
        for mv in active_movements:
            recurring_by_employee[mv["employeeId"]].append(mv)

        for emp in period_employees:
            emp_id = emp["id"]
            base = float(emp.get("baseSalary", 0))
            overtime = float(request.form.get(f"overtime_{emp_id}", 0) or 0)
            commission = float(request.form.get(f"commission_{emp_id}", 0) or 0)
            bonus = float(request.form.get(f"bonus_{emp_id}", 0) or 0)
            other_income_manual = float(request.form.get(f"other_income_{emp_id}", 0) or 0)
            other_ded_manual = float(request.form.get(f"other_ded_{emp_id}", 0) or 0)

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

            emp_period_type = period_type
            emp_is_quincenal = emp_period_type == "quincenal"
            if emp_is_quincenal and base > 0:
                base = round(base / 2, 2)

            salary_history = hr.get_salary_history(owner_uid, emp_id, sandbox=sandbox)
            prorated = PayrollService.prorate_salary(
                monthly_salary=base, period_start=start_date, period_end=end_date,
                hire_date=emp.get("hireDate", ""),
                termination_date=emp.get("terminationDate", ""),
                salary_history=salary_history,
            )

            sim_period_id = f"sim_{uuid.uuid4()}"
            line_id = f"line_{uuid.uuid4()}"
            employee_transactions = []

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

            # ── Variables: horas extra, comisión, bonificación, otros ingresos manuales ──
            var_items = [
                ("HORAS_EXTRA", overtime, "overtime"),
                ("COMISION", commission, "commission"),
                ("BONIFICACION", bonus, "bonus"),
                ("OTROS_INGRESOS", other_income_manual, "manual"),
            ]
            for concept_code, amount, source_type in var_items:
                if amount <= 0:
                    continue
                concept = concept_map.get(concept_code)
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
                    conceptCode=concept_code,
                    type="earning",
                    amount=round(amount, 2),
                    source=source_type,
                    status="applied",
                    conceptSnapshot=build_concept_snapshot(concept),
                    periodYear=int(period_key[:4]) if period_key and len(period_key) >= 4 else 0,
                    createdAt=datetime.now(timezone.utc).isoformat(),
                    updatedAt=datetime.now(timezone.utc).isoformat(),
                )
                employee_transactions.append(tx.model_dump())

            # ── Otras deducciones manuales ──
            if other_ded_manual > 0:
                ded_concept = concept_map.get("OTRAS_DEDUCCIONES")
                if ded_concept:
                    from app.models.transaction import PayrollTransaction
                    from app.services.payroll_concept_engine import build_concept_snapshot
                    tx = PayrollTransaction(
                        id=str(uuid.uuid4()),
                        periodId=sim_period_id,
                        periodKey=period_key,
                        payrollLineId=line_id,
                        employeeId=emp_id,
                        conceptCode="OTRAS_DEDUCCIONES",
                        type="deduction",
                        amount=round(other_ded_manual, 2),
                        source="manual",
                        status="applied",
                        conceptSnapshot=build_concept_snapshot(ded_concept),
                        periodYear=int(period_key[:4]) if period_key and len(period_key) >= 4 else 0,
                        createdAt=datetime.now(timezone.utc).isoformat(),
                        updatedAt=datetime.now(timezone.utc).isoformat(),
                    )
                    employee_transactions.append(tx.model_dump())

            # ── Evaluar reglas ──
            if active_rules:
                emp_rules = list(active_rules)
                emp_specific = hr.get_active_rules_for_scope(owner_uid, "employee", emp_id, sandbox=sandbox)
                if emp_specific:
                    emp_rules.extend(emp_specific)
                    emp_rules.sort(key=lambda r: r.get("priority", 999))
                # Filtrar reglas one-shot ya aplicadas
                sim_year = int(period_key[:4]) if period_key and len(period_key) >= 4 else 0
                filtered_rules = []
                for r in emp_rules:
                    freq = r.get("frequency", "always")
                    if freq == "always":
                        filtered_rules.append(r)
                    elif freq in ("annual", "once"):
                        log_year = sim_year if freq == "annual" else None
                        if not hr.rule_log_exists(owner_uid, r["id"], emp_id, log_year, sandbox=sandbox):
                            filtered_rules.append(r)
                rule_result = PayrollRuleEngine.evaluate_rules(filtered_rules, emp)
                if rule_result:
                    for rule_concept, rule_amount in [
                        ("BONIFICACION", rule_result.get("bonus", 0)),
                        ("COMISION", rule_result.get("commission", 0)),
                        ("OTROS_INGRESOS", rule_result.get("other_income", 0)),
                        ("OTRAS_DEDUCCIONES", rule_result.get("deduction", 0)),
                    ]:
                        if rule_amount > 0:
                            from app.models.transaction import PayrollTransaction
                            from app.services.payroll_concept_engine import build_concept_snapshot
                            concept = concept_map.get(rule_concept, {})
                            tx = PayrollTransaction(
                                id=str(uuid.uuid4()), periodId=sim_period_id, periodKey=period_key,
                                payrollLineId=line_id, employeeId=emp_id,
                                conceptCode=rule_concept,
                                type="deduction" if rule_concept == "OTRAS_DEDUCCIONES" else "earning",
                                amount=round(rule_amount, 2), source=f"rule:{rule_result.get('_ruleId', '')}",
                                status="applied", conceptSnapshot=build_concept_snapshot(concept),
                                periodYear=sim_year,
                                createdAt=datetime.now(timezone.utc).isoformat(),
                                updatedAt=datetime.now(timezone.utc).isoformat(),
                            )
                            employee_transactions.append(tx.model_dump())
                    # Loguear reglas one-shot aplicadas
                    now_iso = datetime.now(timezone.utc).isoformat()
                    for applied in rule_result.get("applied_rules", []):
                        rule_obj = next((r for r in emp_rules if r["id"] == applied["ruleId"]), None)
                        if rule_obj and rule_obj.get("frequency") in ("annual", "once"):
                            log_year = sim_year if rule_obj.get("frequency") == "annual" else None
                            hr.save_rule_log(owner_uid, rule_obj["id"], emp_id, log_year,
                                             period_key, 0.0, now_iso, sandbox=sandbox)

            # ── Aplicar movimientos recurrentes (simulación, sin escribir en DB) ──
            now_iso = datetime.now(timezone.utc).isoformat()
            for mv in recurring_by_employee.get(emp_id, []):
                if not is_applicable(mv, start_date, end_date):
                    continue
                mv_id = mv.get("id", "")
                concept_code = mv.get("conceptCode", "")

                exc = get_exception(owner_uid, mv_id, period_key, sandbox=sandbox)
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

            # ── Calcular ingresos totales para TSS e ISR ──
            gross_income = sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("type") == "earning")
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
                    context={"baseSalary": base, "grossIncome": gross_income, "isQuincenal": emp_is_quincenal},
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
                        "baseSalary": base, "grossIncome": gross_income,
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
                return sum(float(t.get("amount", 0)) for t in tx_list if t.get("conceptCode") in codes)

            overtime_hours_val = float(request.form.get(f"overtime_{emp_id}", 0) or 0)

            recurring_earnings = sum(
                float(t.get("amount", 0)) for t in employee_transactions
                if t.get("isRecurring") and t.get("type") == "earning"
            )
            recurring_additions_details = [
                {
                    "description": concept_map.get(t.get("conceptCode", ""), {}).get("name", t.get("conceptSnapshot", {}).get("name", t.get("conceptCode", ""))),
                    "amount": float(t.get("amount", 0)),
                }
                for t in employee_transactions
                if t.get("isRecurring") and t.get("type") == "earning"
            ]
            recurring_deductions_details = [
                {
                    "description": concept_map.get(t.get("conceptCode", ""), {}).get("name", t.get("conceptSnapshot", {}).get("name", t.get("conceptCode", ""))),
                    "amount": float(t.get("amount", 0)),
                }
                for t in employee_transactions
                if t.get("isRecurring") and t.get("type") == "deduction"
            ]

            line = {
                "employeeId": emp_id,
                "employeeName": emp.get("fullName", ""),
                "position": emp.get("position", ""),
                "periodType": emp_period_type,
                "grossSalary": sum_by_concept(employee_transactions, "SALARIO_BASE"),
                "overtimePay": sum_by_concept(employee_transactions, "HORAS_EXTRA"),
                "overtimeHours": overtime_hours_val,
                "commission": sum_by_concept(employee_transactions, "COMISION"),
                "bonus": sum_by_concept(employee_transactions, "BONIFICACION"),
                "otherIncome": round(sum_by_concept(employee_transactions, "OTROS_INGRESOS") + recurring_earnings, 2),
                "totalIncome": round(earn, 2),
                "totalDeductions": round(deduct, 2),
                "netSalary": round(max(0, earn - deduct), 2),
                "totalEmployerContrib": round(employer, 2),
                "afpEmployee": sum_by_concept(employee_transactions, "AFP_EMPLEADO"),
                "sfsEmployee": sum_by_concept(employee_transactions, "SFS_EMPLEADO"),
                "isrRetention": sum_by_concept(employee_transactions, "ISR_RETENCION"),
                "otherDeductions": round(sum(float(t.get("amount", 0)) for t in employee_transactions if t.get("conceptCode") in ("OTRAS_DEDUCCIONES",) and not t.get("isRecurring")), 2),
                "recurringDeductionsBreakdown": recurring_deductions_details,
                "recurringAdditionsBreakdown": recurring_additions_details,
            }

            lines.append(line)
            total_gross += line["totalIncome"]
            total_net += line["netSalary"]
            total_employer += line["totalEmployerContrib"]
            total_costo += line["totalIncome"] + line["totalEmployerContrib"]

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

        simulation = {
            "period_range": period_info["label"] if period_info else period_key,
            "period_type": period_type,
            "employee_count": len(period_employees),
            "excluded_count": len(_sim_excluded),
            "total_gross": round(total_gross, 2),
            "total_net": round(total_net, 2),
            "total_employer": round(total_employer, 2),
            "total_costo": round(total_costo, 2),
            "recurringDeductionColumns": all_recurring_descs,
            "recurringAdditionsColumns": all_recurring_additions_descs,
            "lines": lines,
        }

    return render_template("rrhh/payroll_simulate.html", active_page="rrhh_payroll",
                           employees=employees, available_periods=available_periods,
                           frequency=group_frequency, simulation=simulation,
                           payroll_groups=payroll_groups,
                           selected_group_id=selected_group_id)