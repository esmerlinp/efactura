"""Tests para flujo simplificado, extractor genérico y transiciones flexibles."""

from unittest.mock import MagicMock, patch

from app.web.rrhh.payroll_process import _extract_variable_values, _build_christmas_preview
from app.web.rrhh.payroll_workflow import _is_simple_workflow, _transition


class TestIsSimpleWorkflow:

    @patch("app.web.rrhh.payroll_workflow.hr.get_payroll_config")
    def test_default_true(self, cfg_mock):
        cfg_mock.return_value = {}
        assert _is_simple_workflow("C1") is True

    @patch("app.web.rrhh.payroll_workflow.hr.get_payroll_config")
    def test_explicit_false(self, cfg_mock):
        cfg_mock.return_value = {"simple_workflow": False}
        assert _is_simple_workflow("C1") is False

    @patch("app.web.rrhh.payroll_workflow.hr.get_payroll_config")
    def test_error_retorna_true(self, cfg_mock):
        cfg_mock.side_effect = Exception("x")
        assert _is_simple_workflow("C1") is True


class TestExtractVariableValues:

    def test_var_generico_y_legacy(self):
        form = {
            "var_COMISION_E1": "1500.50",
            "var_SEGURO_E1": "800",
            "overtime_E2": "8",
            "var_HORAS_EXTRA_E2": "0",
            "var_DESC_CXC_E3": "-5",
        }
        result = _extract_variable_values(form, ["E1", "E2", "E3"])
        assert result["E1"] == {"COMISION": 1500.5, "SEGURO": 800.0}
        assert result["E2"] == {"HORAS_EXTRA": 8.0}
        assert "E3" not in result

    def test_formulario_vacio(self):
        assert _extract_variable_values({}, ["E1"]) == {}


class TestTransitionAllowFrom:

    @patch("app.web.rrhh.payroll_workflow.session", new_callable=MagicMock)
    def test_aprobada_desde_calculada_con_allow_from(self, session_mock):
        session_mock.get.return_value = {"email": "a@b.c", "uid": "u1", "role": "owner"}
        period = {"id": "P1", "status": "calculada"}
        ok, msg = _transition(period, "aprobada", "", sandbox=True,
                              skip_sod=True, allow_from=("calculada", "validada"))
        assert ok is True
        assert period["status"] == "aprobada"

    @patch("app.web.rrhh.payroll_workflow.session", new_callable=MagicMock)
    def test_sin_allow_from_rechaza(self, session_mock):
        session_mock.get.return_value = {"email": "a@b.c", "uid": "u1", "role": "owner"}
        period = {"id": "P1", "status": "calculada"}
        ok, msg = _transition(period, "aprobada", "", sandbox=True, skip_sod=True)
        assert ok is False
        assert "Transición inválida" in msg
        assert period["status"] == "calculada"


class TestChristmasPreview:

    def test_preview_proporcional_y_excluye_sin_salario(self):
        employees = [
            {"id": "E1", "baseSalary": 30000, "hireDate": "2026-07-10"},
            {"id": "E2", "baseSalary": 0, "hireDate": "2026-01-01"},
            {"id": "E3", "baseSalary": 40000, "hireDate": "2025-06-01", "isLiquidation": True},
        ]
        with patch("app.web.rrhh.payroll_process.date") as date_mock:
            date_mock.today.return_value = __import__("datetime").date(2026, 12, 1)
            preview = _build_christmas_preview(employees)
        assert len(preview) == 1
        assert preview[0]["employeeId"] == "E1"
        # 6 meses trabajados (julio–diciembre) → 30000 * 6/12 = 15000
        assert preview[0]["amount"] == 15000.0


# ═══════════════════════════════════════════════════════════════════════
# TABS DINÁMICOS DEL EDITOR (isManualEntry)
# ═══════════════════════════════════════════════════════════════════════

class TestGetEditorTabs:

    def _concept(self, code, ctype="earning", active=True, manual=True, priority=50, name=None):
        return {"code": code, "name": name or code, "type": ctype, "category": "variable",
                "active": active, "isManualEntry": manual, "priority": priority}

    @patch("app.services.payroll_concept_engine.get_concepts")
    def test_clasifica_ingresos_y_descuentos(self, concepts_mock):
        from app.services.payroll_concept_engine import get_editor_tabs
        concepts_mock.return_value = [
            self._concept("COMISION", "earning"),
            self._concept("SEGURO", "deduction"),
            self._concept("HORAS_EXTRA", "earning"),
        ]
        ing, dec = get_editor_tabs("C1")
        assert [t["concept"] for t in ing] == ["COMISION", "HORAS_EXTRA"]
        assert [t["concept"] for t in dec] == ["SEGURO"]

    @patch("app.services.payroll_concept_engine.get_concepts")
    def test_excluye_inactivos_y_no_manuales(self, concepts_mock):
        from app.services.payroll_concept_engine import get_editor_tabs
        concepts_mock.return_value = [
            self._concept("COMISION", "earning"),
            self._concept("BONO_APAGADO", "earning", active=False),
            self._concept("SALARIO_BASE", "earning", manual=False),
            self._concept("BONO_ESCOLAR", "earning", manual=True, priority=10),
        ]
        ing, dec = get_editor_tabs("C1")
        codes = [t["concept"] for t in ing]
        assert "COMISION" in codes and "BONO_ESCOLAR" in codes
        assert "BONO_APAGADO" not in codes and "SALARIO_BASE" not in codes

    @patch("app.services.payroll_concept_engine.get_concepts")
    def test_flag_horas_y_help(self, concepts_mock):
        from app.services.payroll_concept_engine import get_editor_tabs
        concepts_mock.return_value = [self._concept("HORAS_EXTRA", "earning")]
        ing, _ = get_editor_tabs("C1")
        assert ing[0]["hours"] is True
        assert "horas" in ing[0]["help"].lower()


# ═══════════════════════════════════════════════════════════════════════
# CLASIFICACIÓN GENÉRICA DE CONCEPTOS CUSTOM (IR-13 / TSS)
# ═══════════════════════════════════════════════════════════════════════

class TestManualOtherClassification:

    def _tx(self, code, ctype="earning", amount=100, source="var:TEST", **extra):
        tx = {"conceptCode": code, "type": ctype, "amount": amount, "source": source}
        tx.update(extra)
        return tx

    def test_ingreso_custom_entra_en_otros_ingresos(self):
        from app.web.rrhh.payroll_process import build_manual_other_income
        txs = [
            self._tx("SALARIO_BASE", amount=50000),
            self._tx("COMISION", amount=1000),
            self._tx("BONIFICACION", amount=500),
            self._tx("REGALIA_PASCUAL", amount=2000, source="system"),
            self._tx("HORAS_EXTRA", amount=8),
            self._tx("COMBUSTIBLE", amount=5000),
            self._tx("OTROS_INGRESOS", amount=300),
        ]
        assert build_manual_other_income(txs) == 5300.0

    def test_excluye_recurrentes_y_reglas(self):
        from app.web.rrhh.payroll_process import build_manual_other_income
        txs = [
            self._tx("COMBUSTIBLE", amount=5000),
            self._tx("ASIGNACION", amount=1000, isRecurring=True),
            self._tx("BONO_X", amount=800, isRuleGenerated=True),
        ]
        assert build_manual_other_income(txs) == 5000.0

    def test_deduccion_custom_entra_y_excluye_tss_isr_embargo(self):
        from app.web.rrhh.payroll_process import build_manual_other_deductions
        txs = [
            self._tx("COOP_AHORRO", ctype="deduction", amount=1500),
            self._tx("OTRAS_DEDUCCIONES", ctype="deduction", amount=400),
            self._tx("SEGURO", ctype="deduction", amount=600),
            self._tx("AFP_EMPLEADO", ctype="deduction", amount=1435),
            self._tx("SFS_EMPLEADO", ctype="deduction", amount=1520),
            self._tx("ISR_RETENCION", ctype="deduction", amount=0),
            self._tx("EMBARGO_JUDICIAL", ctype="deduction", amount=900, source="garnishment"),
            self._tx("PRESTAMO", ctype="deduction", amount=2000, isRecurring=True),
        ]
        assert build_manual_other_deductions(txs) == 2500.0
