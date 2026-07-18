"""PayrollRuleEngine — Evalúa y aplica reglas configurables de nómina."""

import operator as _op
import re
from datetime import date as dt_date, datetime
from typing import Optional


class PayrollRuleEngine:
    """Motor de reglas de nómina — evalúa condiciones y aplica acciones sobre líneas de cálculo."""

    # Mapeo por defecto de action_type → concepto (cuando no se especifica conceptCode)
    _DEFAULT_ACTION_CONCEPT = {
        "set_bonus": "BONIFICACION",
        "set_commission": "COMISION",
        "set_deduction": "OTRAS_DEDUCCIONES",
        "set_overtime_rate": "HORAS_EXTRA",
        "set_other_income": "OTROS_INGRESOS",
        "set_other_deduction": "OTRAS_DEDUCCIONES",
        "add_concept": None,
    }

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
    def get_action_concept_code(cls, action: dict) -> str | None:
        """Resuelve el código de concepto para una acción.

        Si la acción tiene conceptCode explícito, lo usa.
        Si no, usa el mapeo por defecto según el action_type.
        """
        concept_code = action.get("conceptCode", "")
        if concept_code:
            return concept_code
        action_type = action.get("type", "")
        return cls._DEFAULT_ACTION_CONCEPT.get(action_type)

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
                    elif action_type == "add_concept":
                        concept_code = cls.get_action_concept_code(action)
                        # Default to other_income bucket for backward compat;
                        # the actual type is resolved in payroll_process.py
                        result["other_income"] += value

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
            "weekly_hours": int(context.get("weeklyHours", 44)),
            "education_level": int(context.get("educationLevel", 0)),
            "payment_method": context.get("paymentMethod", ""),
            "work_shift": int(context.get("workShift", 1)),
            "prorated_salary": float(context.get("proratedSalary", 0)),
            "overtime_hours": float(context.get("overtimeHours", 0)),
            "days_in_period": float(context.get("daysInPeriod", 23.83)),
            "dependent_count": int(context.get("dependentCount", 0)),
            "dependent_count_minor": int(context.get("dependentCountMinor", 0)),
            "dependent_count_adult": int(context.get("dependentCountAdult", 0)),
            "dependent_count_student": int(context.get("dependentCountStudent", 0)),
            "financial_dependent_count": int(context.get("financialDependentCount", 0)),
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

        if field == "hire_month":
            hire_date = context.get("hireDate", "")
            if hire_date:
                try:
                    return int(hire_date[5:7])
                except (ValueError, TypeError):
                    pass
            return 0

        if field == "hire_day":
            hire_date = context.get("hireDate", "")
            if hire_date:
                try:
                    return int(hire_date[8:10])
                except (ValueError, TypeError):
                    pass
            return 0

        if field == "is_anniversary_month":
            return int(context.get("isAnniversaryMonth", 0))

        if field == "months_since_hire":
            hire_date = context.get("hireDate", "")
            if hire_date:
                try:
                    hd = datetime.strptime(hire_date[:10], "%Y-%m-%d").date()
                    today = dt_date.today()
                    return (today.year - hd.year) * 12 + (today.month - hd.month)
                except (ValueError, TypeError):
                    pass
            return 0

        if field == "accumulated_ordinary_salary":
            return float(context.get("accumulatedOrdinarySalary", 0))

        return field_map.get(field, context.get(field, ""))

    @classmethod
    def _parse_value(cls, value_str: str, field: str, context: dict):
        """Convierte el valor de cadena al tipo apropiado según el campo."""
        numeric_fields = {"salary", "seniority_years", "age", "weekly_hours", "hire_month", "hire_day", "accumulated_ordinary_salary", "is_anniversary_month", "nationality", "education_level", "work_shift", "months_since_hire", "prorated_salary", "overtime_hours", "days_in_period", "dependent_count", "dependent_count_minor", "dependent_count_adult", "dependent_count_student", "financial_dependent_count"}
        if field in numeric_fields:
            try:
                return float(value_str)
            except (ValueError, TypeError):
                return 0.0
        return value_str

    @classmethod
    def _evaluate_formula(cls, formula: str, context: dict) -> float:
        """Evalúa una fórmula matemática simple usando el contexto del empleado.

        Soporta: salary, seniority_years, age, days_worked, weekly_hours,
                 education_level, hourly_rate, months_since_hire,
                 prorated_salary, overtime_hours, days_in_period,
                 y operadores + - * / ( )

        Ejemplos:
            "salary * 0.10"
            "5000"
            "hourly_rate * days_worked * 8"
            "salary * (weekly_hours / 40)"
            "overtime_hours * hourly_rate * 1.35"
        """
        formula = formula.strip()
        if not formula:
            return 0.0

        # Reemplazar variables del contexto
        salary = float(context.get("baseSalary", context.get("salary", 0)))
        days_worked = float(context.get("daysWorked", context.get("days_worked", 23.83)))

        try:
            expr = formula
            # Reemplazar primero variables compuestas (contienen substring de otras)
            expr = expr.replace("accumulated_ordinary_salary", str(float(context.get("accumulatedOrdinarySalary", 0))))
            expr = expr.replace("prorated_salary", str(float(context.get("proratedSalary", 0))))
            expr = expr.replace("overtime_hours", str(float(context.get("overtimeHours", 0))))
            expr = expr.replace("days_in_period", str(float(context.get("daysInPeriod", 23.83))))
            expr = expr.replace("weekly_hours", str(float(context.get("weeklyHours", 44))))
            expr = expr.replace("education_level", str(float(context.get("educationLevel", 0))))
            expr = expr.replace("hourly_rate", str(float(context.get("hourlyRate", 0))))
            expr = expr.replace("months_since_hire", str(float(cls._resolve_field("months_since_hire", context))))
            expr = expr.replace("dependent_count", str(int(context.get("dependentCount", 0))))
            expr = expr.replace("dependent_count_minor", str(int(context.get("dependentCountMinor", 0))))
            expr = expr.replace("dependent_count_adult", str(int(context.get("dependentCountAdult", 0))))
            expr = expr.replace("dependent_count_student", str(int(context.get("dependentCountStudent", 0))))
            expr = expr.replace("financial_dependent_count", str(int(context.get("financialDependentCount", 0))))
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
                           "set_other_income", "set_other_deduction", "add_concept"}
            if action.get("type") not in valid_types:
                errors.append(f"Acción {i + 1}: tipo '{action.get('type')}' no válido.")
            if not action.get("formula"):
                errors.append(f"Acción {i + 1}: la fórmula es obligatoria.")
            if action.get("type") == "add_concept" and not action.get("conceptCode"):
                errors.append(f"Acción {i + 1}: debe seleccionar un concepto para 'add_concept'.")

        frequency = rule.get("frequency", "always")
        valid_frequencies = {"once", "annual", "always"}
        if frequency not in valid_frequencies:
            errors.append(f"Frecuencia '{frequency}' no válida.")

        trigger_month = rule.get("triggerMonth", 0)
        if not isinstance(trigger_month, int) or trigger_month < 0 or trigger_month > 12:
            errors.append("Mes de ejecución debe ser un número entre 0 y 12.")

        return {"valid": len(errors) == 0, "errors": errors}
