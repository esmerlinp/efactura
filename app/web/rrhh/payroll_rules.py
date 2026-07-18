"""Payroll Rules CRUD — Motor de reglas configurables de nómina."""

from datetime import datetime
from flask import render_template, request, redirect, url_for, session, flash, jsonify
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
)
from app.services import hr_data_service as hr
from app.services.payroll_rule_engine import PayrollRuleEngine
from app.services.payroll_concept_engine import get_concepts


# ═══════════════════════════════════════════════════════════════════════════
# LISTADO DE REGLAS
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/rules")
def payroll_rules_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    rules = hr.get_payroll_rules(owner_uid, sandbox=sandbox)
    rules.sort(key=lambda r: (r.get("scope", "global"), r.get("priority", 0), r.get("name", "")))

    # Agrupar por ámbito
    global_rules = [r for r in rules if r.get("scope") == "global"]
    group_rules = [r for r in rules if r.get("scope") == "group"]
    employee_rules = [r for r in rules if r.get("scope") == "employee"]

    groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    group_map = {g["id"]: g["name"] for g in groups}

    return render_template("rrhh/payroll_rules_list.html", active_page="rrhh_settings",
                           rules=rules, global_rules=global_rules,
                           group_rules=group_rules, employee_rules=employee_rules,
                           group_map=group_map)


# ═══════════════════════════════════════════════════════════════════════════
# NUEVA REGLA
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/rules/new", methods=["GET", "POST"])
def payroll_rules_new():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    active_employees = sorted(
        [e for e in employees if e.get("status") == "activo"],
        key=lambda e: e.get("fullName", "")
    )

    if request.method == "POST":
        import uuid
        from datetime import datetime, timezone

        name = request.form.get("name", "").strip()
        desc = request.form.get("description", "").strip()
        priority = int(request.form.get("priority", 0) or 0)
        scope = request.form.get("scope", "global")
        scope_ids = []
        if scope == "group":
            raw = request.form.get("scope_group_ids", "")
            scope_ids = [s.strip() for s in raw.split(",") if s.strip()]
        elif scope == "employee":
            emp_id = request.form.get("scope_employee_id", "")
            if emp_id:
                scope_ids = [emp_id]
        logic = request.form.get("logic", "AND")
        frequency = request.form.get("frequency", "always")
        trigger_month = int(request.form.get("triggerMonth", 0) or 0)
        is_active = request.form.get("isActive") == "1"

        conditions = []
        cond_fields = request.form.getlist("cond_field[]")
        cond_ops = request.form.getlist("cond_op[]")
        cond_values = request.form.getlist("cond_value[]")
        for fld, op, val in zip(cond_fields, cond_ops, cond_values):
            if fld.strip() and val.strip():
                conditions.append({"field": fld.strip(), "operator": op.strip(), "value": val.strip()})

        actions = []
        act_types = request.form.getlist("action_type[]")
        act_formulas = request.form.getlist("action_formula[]")
        act_descs = request.form.getlist("action_desc[]")
        act_concepts = request.form.getlist("action_concept[]")
        for at, af, ad, ac in zip(act_types, act_formulas, act_descs, act_concepts):
            if at.strip() and af.strip():
                action = {"type": at.strip(), "formula": af.strip(), "description": ad.strip()}
                if ac.strip():
                    action["conceptCode"] = ac.strip()
                actions.append(action)

        concepts = get_concepts(owner_uid, sandbox=sandbox)
        active_concepts = sorted(
            [c for c in concepts if c.get("active")],
            key=lambda c: (c.get("type", ""), c.get("priority", 99))
        )

        rule_data = {
            "name": name,
            "description": desc,
            "priority": priority,
            "scope": scope,
            "scopeIds": scope_ids,
            "logic": logic,
            "frequency": frequency,
            "triggerMonth": trigger_month,
            "conditions": conditions,
            "actions": actions,
            "isActive": is_active,
        }

        validation = PayrollRuleEngine.validate_rule(rule_data)
        if not validation["valid"]:
            for err in validation["errors"]:
                flash(err, "error")
            return render_template("rrhh/payroll_rules_form.html", active_page="rrhh_settings",
                                   rule=rule_data, groups=groups, employees=active_employees,
                                   concepts=active_concepts)

        rule_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        rule_data["id"] = rule_id
        rule_data["createdBy"] = session.get("user", {}).get("email", "")
        rule_data["createdAt"] = now_iso

        hr.save_payroll_rule(owner_uid, rule_id, rule_data, sandbox=sandbox)
        flash(f"Regla «{name}» creada exitosamente.", "success")
        return redirect(url_for("web_rrhh.payroll_rules_list"))

    concepts = get_concepts(owner_uid, sandbox=sandbox)
    active_concepts = sorted(
        [c for c in concepts if c.get("active")],
        key=lambda c: (c.get("type", ""), c.get("priority", 99))
    )
    return render_template("rrhh/payroll_rules_form.html", active_page="rrhh_settings",
                           rule=None, groups=groups, employees=active_employees,
                           concepts=active_concepts)


# ═══════════════════════════════════════════════════════════════════════════
# EDITAR REGLA
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/rules/<rule_id>/edit", methods=["GET", "POST"])
def payroll_rules_edit(rule_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    rule = hr.get_payroll_rule(owner_uid, rule_id, sandbox=sandbox)
    if not rule:
        flash("Regla no encontrada.", "error")
        return redirect(url_for("web_rrhh.payroll_rules_list"))

    groups = hr.get_payroll_groups(owner_uid, sandbox=sandbox)
    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    active_employees = sorted(
        [e for e in employees if e.get("status") == "activo"],
        key=lambda e: e.get("fullName", "")
    )

    if request.method == "POST":
        from datetime import datetime, timezone

        rule["name"] = request.form.get("name", "").strip()
        rule["description"] = request.form.get("description", "").strip()
        rule["priority"] = int(request.form.get("priority", 0) or 0)
        rule["scope"] = request.form.get("scope", "global")
        scope = rule["scope"]
        scope_ids = []
        if scope == "group":
            raw = request.form.get("scope_group_ids", "")
            scope_ids = [s.strip() for s in raw.split(",") if s.strip()]
        elif scope == "employee":
            emp_id = request.form.get("scope_employee_id", "")
            if emp_id:
                scope_ids = [emp_id]
        rule["scopeIds"] = scope_ids
        rule["logic"] = request.form.get("logic", "AND")
        rule["frequency"] = request.form.get("frequency", "always")
        rule["triggerMonth"] = int(request.form.get("triggerMonth", 0) or 0)
        rule["isActive"] = request.form.get("isActive") == "1"

        conditions = []
        cond_fields = request.form.getlist("cond_field[]")
        cond_ops = request.form.getlist("cond_op[]")
        cond_values = request.form.getlist("cond_value[]")
        for fld, op, val in zip(cond_fields, cond_ops, cond_values):
            if fld.strip() and val.strip():
                conditions.append({"field": fld.strip(), "operator": op.strip(), "value": val.strip()})
        rule["conditions"] = conditions

        actions = []
        act_types = request.form.getlist("action_type[]")
        act_formulas = request.form.getlist("action_formula[]")
        act_descs = request.form.getlist("action_desc[]")
        act_concepts = request.form.getlist("action_concept[]")
        for at, af, ad, ac in zip(act_types, act_formulas, act_descs, act_concepts):
            if at.strip() and af.strip():
                action = {"type": at.strip(), "formula": af.strip(), "description": ad.strip()}
                if ac.strip():
                    action["conceptCode"] = ac.strip()
                actions.append(action)
        rule["actions"] = actions

        concepts = get_concepts(owner_uid, sandbox=sandbox)
        active_concepts = sorted(
            [c for c in concepts if c.get("active")],
            key=lambda c: (c.get("type", ""), c.get("priority", 99))
        )

        validation = PayrollRuleEngine.validate_rule(rule)
        if not validation["valid"]:
            for err in validation["errors"]:
                flash(err, "error")
            return render_template("rrhh/payroll_rules_form.html", active_page="rrhh_settings",
                                   rule=rule, groups=groups, employees=active_employees,
                                   concepts=active_concepts)

        now_iso = datetime.now(timezone.utc).isoformat()
        rule["updatedBy"] = session.get("user", {}).get("email", "")
        rule["updatedAt"] = now_iso

        hr.save_payroll_rule(owner_uid, rule_id, rule, sandbox=sandbox)
        flash(f"Regla «{rule['name']}» actualizada.", "success")
        return redirect(url_for("web_rrhh.payroll_rules_list"))

    concepts = get_concepts(owner_uid, sandbox=sandbox)
    active_concepts = sorted(
        [c for c in concepts if c.get("active")],
        key=lambda c: (c.get("type", ""), c.get("priority", 99))
    )
    return render_template("rrhh/payroll_rules_form.html", active_page="rrhh_settings",
                           rule=rule, groups=groups, employees=active_employees,
                           concepts=active_concepts)


# ═══════════════════════════════════════════════════════════════════════════
# TOGGLE / ELIMINAR REGLA
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/rules/<rule_id>/toggle", methods=["POST"])
def payroll_rules_toggle(rule_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    rule = hr.get_payroll_rule(owner_uid, rule_id, sandbox=sandbox)
    if not rule:
        flash("Regla no encontrada.", "error")
        return redirect(url_for("web_rrhh.payroll_rules_list"))

    rule["isActive"] = not rule.get("isActive", True)
    hr.save_payroll_rule(owner_uid, rule_id, rule, sandbox=sandbox)
    estado = "activada" if rule["isActive"] else "desactivada"
    flash(f"Regla «{rule.get('name', '')}» {estado}.", "success")
    return redirect(url_for("web_rrhh.payroll_rules_list"))


@web_rrhh_bp.route("/rrhh/payroll/rules/<rule_id>/delete", methods=["POST"])
def payroll_rules_delete(rule_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    rule = hr.get_payroll_rule(owner_uid, rule_id, sandbox=sandbox)
    name = rule.get("name", "") if rule else ""
    hr.delete_payroll_rule(owner_uid, rule_id, sandbox=sandbox)
    flash(f"Regla «{name}» eliminada.", "success")
    return redirect(url_for("web_rrhh.payroll_rules_list"))


# ═══════════════════════════════════════════════════════════════════════════
# LIMPIAR LOGS DE REGLAS (one-shot/anual)
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/rules/cleanup-logs", methods=["POST"])
def payroll_rules_cleanup_logs():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    hr.delete_rule_logs_for_rule(owner_uid, sandbox=sandbox)
    flash("Historial de reglas limpiado. Las reglas one-shot/anuales podrán aplicarse nuevamente.", "success")
    return redirect(url_for("web_rrhh.payroll_rules_list"))


# ═══════════════════════════════════════════════════════════════════════════
# TEST DE REGLAS
# ═══════════════════════════════════════════════════════════════════════════

@web_rrhh_bp.route("/rrhh/payroll/rules/test", methods=["GET", "POST"])
def payroll_rules_test():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    employees = hr.get_employees(owner_uid, sandbox=sandbox)
    active = [e for e in employees if e.get("status") == "activo"]
    rules = hr.get_active_rules_for_scope(owner_uid, "global", sandbox=sandbox)

    test_results = None
    selected_emp = None

    if request.method == "POST":
        emp_id = request.form.get("employee_id", "")
        selected_emp = next((e for e in active if e["id"] == emp_id), None)
        if selected_emp and rules:
            result = PayrollRuleEngine.evaluate_rules(rules, selected_emp)
            test_results = {
                "employee": selected_emp,
                "rulesEvaluated": len(rules),
                "rulesApplied": len(result.get("applied_rules", [])),
                "appliedRules": result.get("applied_rules", []),
                "bonus": result.get("bonus", 0),
                "commission": result.get("commission", 0),
                "deduction": result.get("deduction", 0),
                "overtime_rate": result.get("overtime_rate"),
                "other_income": result.get("other_income", 0),
                "other_deduction": result.get("other_deduction", 0),
            }

    return render_template("rrhh/payroll_rules_test.html", active_page="rrhh_settings",
                           employees=active, rules=rules,
                           test_results=test_results, selected_emp=selected_emp,
                           now=datetime.now())
