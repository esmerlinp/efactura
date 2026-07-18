"""Tests para PayrollRuleEngine — evaluación de reglas configurables de nómina."""

import pytest
from datetime import date as dt_date
from unittest.mock import MagicMock, patch

from app.services.payroll_rule_engine import PayrollRuleEngine


def _rule(name: str, conditions: list = None, actions: list = None,
          is_active: bool = True, priority: int = 999, logic: str = "AND",
          rule_id: str = None, **kw) -> dict:
    return {
        "id": rule_id or name.lower().replace(" ", "_"),
        "name": name,
        "isActive": is_active,
        "priority": priority,
        "logic": logic,
        "conditions": conditions or [],
        "actions": actions or [],
        **kw,
    }


def _cond(field: str, operator: str = "==", value: str = "") -> dict:
    return {"field": field, "operator": operator, "value": value}


def _action(action_type: str, formula: str = "0") -> dict:
    return {"type": action_type, "formula": formula}


# ═══════════════════════════════════════════════════════════════════════
# evaluate_rules
# ═══════════════════════════════════════════════════════════════════════

class TestEvaluateRules:
    """Pruebas para evaluate_rules()."""

    def test_sin_reglas(self):
        """Lista vacía → solo defaults (0s)"""
        result = PayrollRuleEngine.evaluate_rules([], {"department": "Ventas"})
        assert result["bonus"] == 0.0
        assert result["commission"] == 0.0
        assert result["deduction"] == 0.0
        assert result["overtime_rate"] is None
        assert result["other_income"] == 0.0
        assert result["other_deduction"] == 0.0
        assert result["applied_rules"] == []

    def test_bonus_por_departamento(self):
        """Regla: dept=Ventas → set_bonus=5000 → aplica a empleado en Ventas"""
        rules = [_rule(
            "Bono Ventas",
            conditions=[_cond("department", "==", "Ventas")],
            actions=[_action("set_bonus", "5000")],
        )]
        context = {"department": "Ventas", "salary": 50000.0}
        result = PayrollRuleEngine.evaluate_rules(rules, context)
        assert result["bonus"] == pytest.approx(5000.0, abs=0.01)
        assert len(result["applied_rules"]) == 1

    def test_bonus_no_aplica_otro_departamento(self):
        """Misma regla para Ventas → no aplica a empleado en Admin"""
        rules = [_rule(
            "Bono Ventas",
            conditions=[_cond("department", "==", "Ventas")],
            actions=[_action("set_bonus", "5000")],
        )]
        context = {"department": "Admin", "salary": 50000.0}
        result = PayrollRuleEngine.evaluate_rules(rules, context)
        assert result["bonus"] == 0.0
        assert result["applied_rules"] == []

    def test_commission_por_salario(self):
        """Regla: salary > 50000 → set_commission=salary*0.05"""
        rules = [_rule(
            "Comisión alta",
            conditions=[_cond("salary", ">", "50000")],
            actions=[_action("set_commission", "salary * 0.05")],
        )]
        context = {"baseSalary": 80000.0}
        result = PayrollRuleEngine.evaluate_rules(rules, context)
        assert result["commission"] == pytest.approx(4000.0, abs=0.01)

    def test_deduction_por_antiguedad(self):
        """Regla: seniority_years > 5 → set_deduction=2000"""
        rules = [_rule(
            "Deducción antigüedad",
            conditions=[_cond("seniority_years", ">", "5")],
            actions=[_action("set_deduction", "2000")],
        )]
        context = {"hireDate": "2015-06-15"}
        result = PayrollRuleEngine.evaluate_rules(rules, context)
        assert result["deduction"] == pytest.approx(2000.0, abs=0.01)

    def test_overtime_rate_personalizado(self):
        """Regla para área específica → overtime_rate diferente"""
        rules = [_rule(
            "Tasa HE Producción",
            conditions=[_cond("area", "==", "Produccion")],
            actions=[_action("set_overtime_rate", "2.0")],
        )]
        context = {"area": "Produccion"}
        result = PayrollRuleEngine.evaluate_rules(rules, context)
        assert result["overtime_rate"] == pytest.approx(2.0, abs=0.01)

    def test_multiples_acciones(self):
        """Una regla con 2 acciones"""
        rules = [_rule(
            "Bono + Comisión",
            conditions=[_cond("department", "==", "Ventas")],
            actions=[_action("set_bonus", "3000"), _action("set_commission", "salary * 0.02")],
        )]
        context = {"department": "Ventas", "salary": 60000.0}
        result = PayrollRuleEngine.evaluate_rules(rules, context)
        assert result["bonus"] == pytest.approx(3000.0, abs=0.01)
        assert result["commission"] == pytest.approx(1200.0, abs=0.01)

    def test_multiples_reglas(self):
        """2 reglas, ambas aplican"""
        rules = [
            _rule("Bono Ventas", conditions=[_cond("department", "==", "Ventas")],
                  actions=[_action("set_bonus", "2000")], priority=1),
            _rule("Comisión global", conditions=[_cond("salary", ">", "0")],
                  actions=[_action("set_commission", "1000")], priority=2),
        ]
        context = {"department": "Ventas", "salary": 50000.0}
        result = PayrollRuleEngine.evaluate_rules(rules, context)
        assert result["bonus"] == pytest.approx(2000.0, abs=0.01)
        assert result["commission"] == pytest.approx(1000.0, abs=0.01)
        assert len(result["applied_rules"]) == 2

    def test_regla_inactiva(self):
        """Regla isActive=False → no se aplica"""
        rules = [_rule(
            "Bono Inactivo",
            conditions=[_cond("department", "==", "Ventas")],
            actions=[_action("set_bonus", "9999")],
            is_active=False,
        )]
        context = {"department": "Ventas"}
        result = PayrollRuleEngine.evaluate_rules(rules, context)
        assert result["bonus"] == 0.0
        assert result["applied_rules"] == []

    def test_prioridad(self):
        """Regla con priority menor se evalúa primero"""
        rules = [
            _rule("Segunda", conditions=[_cond("salary", ">", "0")],
                  actions=[_action("set_bonus", "100")], priority=10),
            _rule("Primera", conditions=[_cond("salary", ">", "0")],
                  actions=[_action("set_bonus", "200")], priority=5),
        ]
        context = {"salary": 50000.0}
        result = PayrollRuleEngine.evaluate_rules(rules, context)
        # Ambas aplican, bonus se acumula: 200 + 100 = 300
        assert result["bonus"] == pytest.approx(300.0, abs=0.01)
        assert result["applied_rules"][0]["ruleName"] == "Primera"
        assert result["applied_rules"][1]["ruleName"] == "Segunda"


# ═══════════════════════════════════════════════════════════════════════
# _evaluate_conditions
# ═══════════════════════════════════════════════════════════════════════

class TestEvaluateConditions:
    """Pruebas para _evaluate_conditions()."""

    def test_and_logico(self):
        """2 condiciones con AND → ambas deben cumplirse"""
        conds = [_cond("department", "==", "Ventas"), _cond("salary", ">", "30000")]
        result = PayrollRuleEngine._evaluate_conditions(conds, "AND", {
            "department": "Ventas", "salary": 50000.0,
        })
        assert result is True

    def test_and_falla(self):
        """AND con una condición falsa → False"""
        conds = [_cond("department", "==", "Ventas"), _cond("salary", ">", "80000")]
        result = PayrollRuleEngine._evaluate_conditions(conds, "AND", {
            "department": "Ventas", "salary": 50000.0,
        })
        assert result is False

    def test_or_logico(self):
        """2 condiciones con OR → una debe cumplirse"""
        conds = [_cond("department", "==", "Admin"), _cond("salary", ">", "30000")]
        result = PayrollRuleEngine._evaluate_conditions(conds, "OR", {
            "department": "Ventas", "salary": 50000.0,
        })
        assert result is True

    def test_or_ambas_falsas(self):
        """OR con ambas falsas → False"""
        conds = [_cond("department", "==", "Admin"), _cond("salary", "<", "10000")]
        result = PayrollRuleEngine._evaluate_conditions(conds, "OR", {
            "department": "Ventas", "salary": 15000.0,
        })
        assert result is False

    def test_operador_contains(self):
        """contains en department"""
        conds = [_cond("department", "contains", "Venta")]
        result = PayrollRuleEngine._evaluate_conditions(conds, "AND", {
            "department": "Ventas",
        })
        assert result is True

    def test_operador_contains_falso(self):
        conds = [_cond("department", "contains", "Admin")]
        result = PayrollRuleEngine._evaluate_conditions(conds, "AND", {
            "department": "Ventas",
        })
        assert result is False

    def test_operador_in(self):
        """in en valores separados por coma"""
        conds = [_cond("department", "in", "Ventas,Admin,RRHH")]
        result = PayrollRuleEngine._evaluate_conditions(conds, "AND", {
            "department": "Admin",
        })
        assert result is True

    def test_operador_not_in(self):
        """not_in"""
        conds = [_cond("department", "not_in", "Ventas,Admin")]
        result = PayrollRuleEngine._evaluate_conditions(conds, "AND", {
            "department": "Produccion",
        })
        assert result is True

    def test_sin_condiciones(self):
        """Sin condiciones → True"""
        result = PayrollRuleEngine._evaluate_conditions([], "AND", {})
        assert result is True

    def test_operador_desconocido(self):
        """Operador no válido → False"""
        conds = [_cond("salary", "???", "5000")]
        result = PayrollRuleEngine._evaluate_conditions(conds, "AND", {
            "salary": 5000.0,
        })
        assert result is False


# ═══════════════════════════════════════════════════════════════════════
# _resolve_field
# ═══════════════════════════════════════════════════════════════════════

class TestResolveField:
    """Pruebas para _resolve_field()."""

    def test_seniority_years(self):
        """hireDate calcula años correctamente"""
        val = PayrollRuleEngine._resolve_field("seniority_years", {
            "hireDate": "2020-01-01",
        })
        today = dt_date.today()
        expected = today.year - 2020
        if today.month < 1 or (today.month == 1 and today.day < 1):
            expected -= 1
        assert val == max(0, expected)

    def test_age(self):
        """birthDate calcula edad"""
        val = PayrollRuleEngine._resolve_field("age", {
            "birthDate": "1990-06-15",
        })
        today = dt_date.today()
        expected = today.year - 1990
        if today.month < 6 or (today.month == 6 and today.day < 15):
            expected -= 1
        assert val == max(0, expected)

    def test_hire_month(self):
        """hireDate → mes"""
        val = PayrollRuleEngine._resolve_field("hire_month", {
            "hireDate": "2023-11-05",
        })
        assert val == 11

    def test_hire_day(self):
        """hireDate → día"""
        val = PayrollRuleEngine._resolve_field("hire_day", {
            "hireDate": "2023-11-05",
        })
        assert val == 5

    def test_field_map_department(self):
        """Mapeo estándar: department"""
        val = PayrollRuleEngine._resolve_field("department", {
            "department": "Ventas",
        })
        assert val == "Ventas"

    def test_field_map_salary(self):
        """Mapeo estándar: salary"""
        val = PayrollRuleEngine._resolve_field("salary", {
            "baseSalary": 60000.0,
        })
        assert val == 60000.0

    def test_field_map_fallback(self):
        """Campo no mapeado → se lee directo del context"""
        val = PayrollRuleEngine._resolve_field("custom_field", {
            "custom_field": "valor_test",
        })
        assert val == "valor_test"

    def test_field_map_empty(self):
        """Campo no existente → string vacío"""
        val = PayrollRuleEngine._resolve_field("inexistente", {})
        assert val == ""


# ═══════════════════════════════════════════════════════════════════════
# _evaluate_formula
# ═══════════════════════════════════════════════════════════════════════

class TestEvaluateFormula:
    """Pruebas para _evaluate_formula()."""

    def test_formula_simple(self):
        """"5000" → 5000"""
        val = PayrollRuleEngine._evaluate_formula("5000", {})
        assert val == pytest.approx(5000.0, abs=0.01)

    def test_formula_salary_pct(self):
        """"salary * 0.10" con salary=50000 → 5000"""
        val = PayrollRuleEngine._evaluate_formula("salary * 0.10", {
            "baseSalary": 50000.0,
        })
        assert val == pytest.approx(5000.0, abs=0.01)

    def test_formula_expression(self):
        """"salary * (weekly_hours / 40)" con salary=60000, weekly_hours=45 → 67500"""
        val = PayrollRuleEngine._evaluate_formula("salary * (weekly_hours / 40)", {
            "baseSalary": 60000.0, "weeklyHours": 45,
        })
        assert val == pytest.approx(67500.0, abs=0.01)

    def test_formula_invalida(self):
        """Caracteres no seguros → 0"""
        val = PayrollRuleEngine._evaluate_formula("__import__('os')", {})
        assert val == 0.0

    def test_formula_vacia(self):
        """Fórmula vacía → 0"""
        val = PayrollRuleEngine._evaluate_formula("", {})
        assert val == 0.0

    def test_formula_solo_espacios(self):
        """Fórmula con espacios → 0"""
        val = PayrollRuleEngine._evaluate_formula("   ", {})
        assert val == 0.0


# ═══════════════════════════════════════════════════════════════════════
# validate_rule
# ═══════════════════════════════════════════════════════════════════════

class TestValidateRule:
    """Pruebas para validate_rule()."""

    def test_regla_valida(self):
        """Regla completa → valid=True"""
        rule = _rule(
            "Bono Ventas",
            conditions=[_cond("department", "==", "Ventas")],
            actions=[_action("set_bonus", "5000")],
        )
        result = PayrollRuleEngine.validate_rule(rule)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_sin_nombre(self):
        """Sin nombre → error"""
        rule = _rule("", conditions=[_cond("department", "==", "Ventas")],
                     actions=[_action("set_bonus", "5000")])
        result = PayrollRuleEngine.validate_rule(rule)
        assert result["valid"] is False
        assert any("nombre" in e for e in result["errors"])

    def test_sin_acciones(self):
        """Sin acciones → error"""
        rule = _rule("Bono Vacío", conditions=[_cond("department", "==", "Ventas")], actions=[])
        result = PayrollRuleEngine.validate_rule(rule)
        assert result["valid"] is False
        assert any("acción" in e.lower() for e in result["errors"])

    def test_condicion_sin_campo(self):
        """Condición sin field → error"""
        rule = _rule(
            "Mala condición",
            conditions=[{"operator": "==", "value": "Ventas"}],
            actions=[_action("set_bonus", "1000")],
        )
        result = PayrollRuleEngine.validate_rule(rule)
        assert result["valid"] is False
        assert any("campo" in e.lower() for e in result["errors"])

    def test_accion_tipo_invalido(self):
        """Tipo de acción no válido → error"""
        rule = _rule(
            "Acción inválida",
            conditions=[_cond("department", "==", "Ventas")],
            actions=[_action("set_salary", "9999")],
        )
        result = PayrollRuleEngine.validate_rule(rule)
        assert result["valid"] is False
        assert any("no válido" in e for e in result["errors"])

    def test_accion_sin_formula(self):
        """Acción sin fórmula → error"""
        rule = _rule(
            "Sin fórmula",
            conditions=[_cond("department", "==", "Ventas")],
            actions=[{"type": "set_bonus"}],
        )
        result = PayrollRuleEngine.validate_rule(rule)
        assert result["valid"] is False
        assert any("fórmula" in e.lower() for e in result["errors"])

    def test_frecuencia_invalida(self):
        """Frecuencia no válida → error"""
        rule = _rule(
            "Frecuencia mala",
            conditions=[_cond("department", "==", "Ventas")],
            actions=[_action("set_bonus", "1000")],
            frequency="diaria",
        )
        result = PayrollRuleEngine.validate_rule(rule)
        assert result["valid"] is False
        assert any("frecuencia" in e.lower() for e in result["errors"])

    def test_trigger_month_invalido(self):
        """Mes de ejecución fuera de rango → error"""
        rule = _rule(
            "Mes inválido",
            conditions=[_cond("department", "==", "Ventas")],
            actions=[_action("set_bonus", "1000")],
            triggerMonth=13,
        )
        result = PayrollRuleEngine.validate_rule(rule)
        assert result["valid"] is False
        assert any("mes" in e.lower() for e in result["errors"])
