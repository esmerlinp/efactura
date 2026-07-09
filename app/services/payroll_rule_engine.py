"""PayrollRuleEngine — Evalúa y aplica reglas configurables de nómina."""

import operator as _op
import re
from datetime import date as dt_date, datetime
from typing import Optional


class PayrollRuleEngine:
    """Motor de reglas de nómina — evalúa condiciones y aplica acciones sobre líneas de cálculo."""

    _OPERATORS = {
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        "contains": lambda a, b: str(b).lower() in str(a).lower() if a else False,
        "in": lambda a, b: str(a).lower() in [x.strip().lower() for x in str(b).split(",")],
        "not_in": lambda a, b: str(a).lower() not in [x.strip().lower() for x in str(b).split(",")],
    }

    @classmethod
    def evaluate_rules(cls, rules: list, context: dict) -> dict:
        """Evalúa todas las reglas activas contra el contexto de un empleado.

        Args:
            rules: Lista de PayrollRule dicts, ordenadas por prioridad.
            context: Datos del empleado {department, position, salary, seniority_years, ...}.

        Returns:
            Dict con {bonus, commission, deduction, overtime_rate, other_income, other_deduction,
                       applied_rules: [...]}
        """
        result = {
            "bonus": 0.0,
            "commission": 0.0,
            "deduction": 0.0,
            "overtime_rate": None,
            "other_income": 0.0,
            "other_deduction": 0.0,
            "applied_rules": [],
        }

        active_rules = [r for r in rules if r.get("isActive", True)]
        active_rules.sort(key=lambda r: r.get("priority", 999))

        for rule in active_rules:
            if cls._evaluate_conditions(rule.get("conditions", []), rule.get("logic", "AND"), context):
                for action in rule.get("actions", []):
                    action_type = action.get("type", "")
                    formula = action.get("formula", "0")
                    value = cls._evaluate_formula(formula, context)

                    if action_type == "set_bonus":
                        result["bonus"] += value
                    elif action_type == "set_commission":
                        result["commission"] += value
                    elif action_type == "set_deduction":
                        result["deduction"] += value
                    elif action_type == "set_overtime_rate":
                        result["overtime_rate"] = value
                    elif action_type == "set_other_income":
                        result["other_income"] += value
                    elif action_type == "set_other_deduction":
                        result["other_deduction"] += value

                result["applied_rules"].append({
                    "ruleId": rule.get("id", ""),
                    "ruleName": rule.get("name", ""),
                    "actions": rule.get("actions", []),
                })

        return result

    @classmethod
    def _evaluate_conditions(cls, conditions: list, logic: str, context: dict) -> bool:
        """Evalúa una lista de condiciones con lógica AND/OR."""
        if not conditions:
            return True

        results = []
        for cond in conditions:
            field = cond.get("field", "")
            op = cond.get("operator", "==")
            value_str = cond.get("value", "")

            actual_value = cls._resolve_field(field, context)
            parsed_value = cls._parse_value(value_str, field, context)
            op_func = cls._OPERATORS.get(op)

            if op_func:
                results.append(op_func(actual_value, parsed_value))
            else:
                results.append(False)

        if logic.upper() == "OR":
            return any(results)
        return all(results)

    @classmethod
    def _resolve_field(cls, field: str, context: dict):
        """Resuelve el valor de un campo desde el contexto del empleado."""
        field_map = {
            "department": context.get("department", context.get("area", "")),
            "area": context.get("area", ""),
            "position": context.get("position", ""),
            "salary": float(context.get("baseSalary", context.get("salary", 0))),
            "salary_type": context.get("salaryType", "fijo"),
            "contract_type": context.get("contractType", ""),
            "status": context.get("status", ""),
            "workday": context.get("workday", ""),
            "branch": context.get("branchId", ""),
            "cost_center": context.get("costCenter", ""),
            "nationality": context.get("nationality", 1),
            "gender": context.get("gender", ""),
            "marital_status": context.get("maritalStatus", ""),
        }

        if field == "seniority_years":
            hire_date = context.get("hireDate", "")
            if hire_date:
                try:
                    hd = datetime.strptime(hire_date[:10], "%Y-%m-%d").date()
                    today = dt_date.today()
                    years = today.year - hd.year
                    if today.month < hd.month or (today.month == hd.month and today.day < hd.day):
                        years -= 1
                    return max(0, years)
                except (ValueError, TypeError):
                    pass
            return 0

        if field == "age":
            birth = context.get("birthDate", "")
            if birth:
                try:
                    bd = datetime.strptime(birth[:10], "%Y-%m-%d").date()
                    today = dt_date.today()
                    age = today.year - bd.year
                    if today.month < bd.month or (today.month == bd.month and today.day < bd.day):
                        age -= 1
                    return max(0, age)
                except (ValueError, TypeError):
                    pass
            return 0

        return field_map.get(field, context.get(field, ""))

    @classmethod
    def _parse_value(cls, value_str: str, field: str, context: dict):
        """Convierte el valor de cadena al tipo apropiado según el campo."""
        numeric_fields = {"salary", "seniority_years", "age", "weekly_hours"}
        if field in numeric_fields:
            try:
                return float(value_str)
            except (ValueError, TypeError):
                return 0.0
        return value_str

    @classmethod
    def _evaluate_formula(cls, formula: str, context: dict) -> float:
        """Evalúa una fórmula matemática simple usando el contexto del empleado.

        Soporta: salary, seniority_years, age, days_worked, y operadores + - * / ( )

        Ejemplos:
            "salary * 0.10"
            "5000"
            "salary * 0.05 + 2000"
            "days_worked * 500"
        """
        formula = formula.strip()
        if not formula:
            return 0.0

        # Reemplazar variables del contexto
        salary = float(context.get("baseSalary", context.get("salary", 0)))
        days_worked = float(context.get("daysWorked", context.get("days_worked", 23.83)))

        try:
            expr = formula
            expr = expr.replace("salary", str(salary))
            expr = expr.replace("days_worked", str(days_worked))
            expr = re.sub(r'seniority_years', str(cls._resolve_field("seniority_years", context)), expr)
            expr = re.sub(r'age', str(cls._resolve_field("age", context)), expr)

            # Solo permitir caracteres seguros para eval
            if not re.match(r'^[\d\s\+\-\*\/\.\(\)]+$', expr):
                return 0.0

            result = eval(expr, {"__builtins__": {}}, {})
            return round(float(result), 2)
        except Exception:
            return 0.0

    @classmethod
    def validate_rule(cls, rule: dict) -> dict:
        """Valida una regla antes de guardarla.

        Returns:
            Dict con {valid: bool, errors: [...]}
        """
        errors = []
        if not rule.get("name", "").strip():
            errors.append("El nombre de la regla es obligatorio.")

        conditions = rule.get("conditions", [])
        for i, cond in enumerate(conditions):
            if not cond.get("field"):
                errors.append(f"Condición {i + 1}: el campo es obligatorio.")
            if cond.get("operator") not in cls._OPERATORS:
                errors.append(f"Condición {i + 1}: operador '{cond.get('operator')}' no válido.")
            if not cond.get("value"):
                errors.append(f"Condición {i + 1}: el valor es obligatorio.")

        actions = rule.get("actions", [])
        if not actions:
            errors.append("La regla debe tener al menos una acción.")
        for i, action in enumerate(actions):
            valid_types = {"set_bonus", "set_commission", "set_deduction", "set_overtime_rate",
                           "set_other_income", "set_other_deduction"}
            if action.get("type") not in valid_types:
                errors.append(f"Acción {i + 1}: tipo '{action.get('type')}' no válido.")
            if not action.get("formula"):
                errors.append(f"Acción {i + 1}: la fórmula es obligatoria.")

        return {"valid": len(errors) == 0, "errors": errors}
