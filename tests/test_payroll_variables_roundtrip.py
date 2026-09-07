"""Round-trip de variables manuales: lo que envía el editor (var_<CODE>_<empId>)
debe sobrevivir extracción → transacción (source var:) → recarga del editor.

Cubre la regresión donde los ingresos/descuentos manuales no persistían
luego de calcular (códigos con underscore mal parseados y conceptos custom
descartados al recargar).
"""

from unittest.mock import patch

from app.web.rrhh.payroll_process import _extract_variable_values
from app.services.payroll_service import PayrollService
from app.services.payroll_variable_catalog import (
    VARIABLE_CONCEPT_CODES, GROUP_OVERRIDE_BY_CONCEPT,
)
from app.services.payroll_concept_engine import DEFAULT_CONCEPTS


def _concept_map():
    return {c["code"]: c for c in DEFAULT_CONCEPTS if c.get("active")}


def _tx_for_var(vcode, emp_id, amt, concept_map, group_overrides=None):
    """Replica el loop 'Variable movements (genérico por concepto)' del worker."""
    group_overrides = group_overrides or {}
    if amt <= 0:
        return None
    if vcode == "REGALIA_PASCUAL":
        return None
    if vcode in GROUP_OVERRIDE_BY_CONCEPT:
        if group_overrides.get(GROUP_OVERRIDE_BY_CONCEPT[vcode]) is False:
            return None
    concept = concept_map.get(vcode)
    if not concept:
        return None
    return {
        "id": f"tx-{emp_id}-{vcode}",
        "employeeId": emp_id,
        "conceptCode": vcode,
        "type": concept.get("type", "earning"),
        "amount": round(amt, 2),
        "source": f"var:{vcode}",
        "status": "applied",
    }


def _extract_then_build(form, emp_ids, concept_map):
    valid = [t for t in VARIABLE_CONCEPT_CODES]
    emp_vars = _extract_variable_values(form, emp_ids, valid_codes=valid)
    txs = []
    for emp_id, codes in emp_vars.items():
        for vcode, amt in codes.items():
            tx = _tx_for_var(vcode, emp_id, amt, concept_map)
            if tx:
                txs.append(tx)
    return emp_vars, txs


class TestManualVariablesRoundTrip:

    def _reload(self, txs):
        with patch(
            "app.services.hr_data_service.get_payroll_transactions",
            return_value=txs,
        ):
            return PayrollService.get_period_manual_variables("P1", "C1")

    def test_ingresos_con_underscore_persisten(self):
        form = {
            "var_INGRESO_VARIABLE_E1": "2500",
            "var_COMISION_E1": "1500.50",
            "var_BONIFICACION_E1": "2000",
            "var_INCENTIVO_BENEFICIO_E1": "750",
        }
        emp_vars, txs = _extract_then_build(form, ["E1"], _concept_map())
        assert set(emp_vars["E1"]) == {
            "INGRESO_VARIABLE", "COMISION", "BONIFICACION", "INCENTIVO_BENEFICIO",
        }
        assert len(txs) == 4
        rows = self._reload(txs)
        fields = {(r["employeeId"], r["conceptField"], r["amount"]) for r in rows}
        assert ("E1", "INGRESO_VARIABLE", 2500.0) in fields
        assert ("E1", "COMISION", 1500.5) in fields
        assert ("E1", "BONIFICACION", 2000.0) in fields
        assert ("E1", "INCENTIVO_BENEFICIO", 750.0) in fields

    def test_descuentos_con_underscore_persisten(self):
        form = {
            "var_OTRAS_DEDUCCIONES_E1": "400",
            "var_DESCUENTO_RECURRENTE_E1": "1000",
            "var_DESC_CXC_E1": "600",
            "var_SEGURO_E1": "350",
        }
        emp_vars, txs = _extract_then_build(form, ["E1"], _concept_map())
        assert set(emp_vars["E1"]) == {
            "OTRAS_DEDUCCIONES", "DESCUENTO_RECURRENTE", "DESC_CXC", "SEGURO",
        }
        assert len(txs) == 4
        rows = self._reload(txs)
        fields = {(r["employeeId"], r["conceptField"], r["amount"]) for r in rows}
        assert ("E1", "OTRAS_DEDUCCIONES", 400.0) in fields
        assert ("E1", "DESCUENTO_RECURRENTE", 1000.0) in fields
        assert ("E1", "DESC_CXC", 600.0) in fields
        assert ("E1", "SEGURO", 350.0) in fields

    def test_horas_extra_y_regalia_persisten(self):
        form = {
            "var_HORAS_EXTRA_E1": "8",
            "var_REGALIA_PASCUAL_E1": "5000",
            "var_DIF_VACACIONES_E1": "1200",
            "var_SALARIO_RETROACTIVO_E1": "3000",
        }
        emp_vars, txs = _extract_then_build(form, ["E1"], _concept_map())
        # REGALIA_PASCUAL se maneja en bloque aparte (source system)
        assert set(emp_vars["E1"]) == {
            "HORAS_EXTRA", "REGALIA_PASCUAL", "DIF_VACACIONES", "SALARIO_RETROACTIVO",
        }
        txs.append({
            "id": "tx-reg", "employeeId": "E1", "conceptCode": "REGALIA_PASCUAL",
            "type": "earning", "amount": 5000.0, "source": "system", "status": "applied",
        })
        rows = self._reload(txs)
        fields = {(r["employeeId"], r["conceptField"], r["amount"]) for r in rows}
        assert ("E1", "HORAS_EXTRA", 8.0) in fields
        assert ("E1", "REGALIA_PASCUAL", 5000.0) in fields
        assert ("E1", "DIF_VACACIONES", 1200.0) in fields
        assert ("E1", "SALARIO_RETROACTIVO", 3000.0) in fields
