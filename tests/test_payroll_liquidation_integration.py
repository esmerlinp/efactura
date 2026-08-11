"""Tests de la integración nómina tipo "liquidation" ↔ settlement de offboarding.

Cubre el bug crítico: cuando un empleado con liquidación pendiente sigue con
status "activo" (el offboarding no ha llegado a "completed"), la nómina de
liquidados tomaba el salario regular en vez del monto de la liquidación.
"""

import pytest
from unittest.mock import MagicMock, patch

from app.web.rrhh.payroll_process import (
    _collect_liquidation_employees,
    _get_pending_liquidation_employee_ids,
    _build_liquidation_line,
)


def _emp(eid, base, name="Empleado", groups=None):
    return {
        "id": eid,
        "fullName": name,
        "cedula": "001-0000000-0",
        "position": "Analista",
        "department": "IT",
        "baseSalary": base,
        "status": "activo",
        "payrollGroupIds": groups or ["grp-liq"],
        "hireDate": "2020-01-10",
    }


def _settlement(eid, monto_total=100000.0, neto=95000.0, exento=80000.0, sdp=1888.38,
                descuentos=5000.0, assigned_group=None):
    s = {
        "id": f"sett-{eid}",
        "requestId": f"req-{eid}",
        "totales": {
            "montoTotal": monto_total,
            "montoNetoAPagar": neto,
            "montoExento": exento,
            "montoDescuentos": descuentos,
        },
        "salarioDiarioPromedio": sdp,
        "status": "pendiente_pago",
        "conceptos": {
            "preaviso": {"aplica": True, "monto": 30000.0, "exentoTSS": True, "exentoISR": True},
            "cesantia": {"aplica": True, "monto": 50000.0, "exentoTSS": True, "exentoISR": True},
            "vacaciones": {"aplica": True, "monto": 20000.0, "exentoTSS": False, "exentoISR": False},
            "salarioNavidad": {"aplica": False, "monto": 0.0, "exentoTSS": True, "exentoISR": True},
            "salarioProporcional": {"aplica": False, "monto": 0.0, "exentoTSS": False, "exentoISR": False},
            "asistenciaEconomica": {"aplica": False, "monto": 0.0, "exentoTSS": True, "exentoISR": True},
        },
    }
    if assigned_group:
        s["assignedGroupId"] = assigned_group
    return s


def _req(eid, status="pending_payment"):
    return {"employeeId": eid, "status": status}


class TestCollectLiquidationEmployees:
    """El core del bug: el mapa debe poblarse aunque el empleado ya esté en period_employees."""

    def test_empleado_activo_ya_en_period_employees_se_agrega_al_mapa(self):
        emp = _emp("emp-1", 45000.0)
        settlement = _settlement("emp-1", assigned_group="grp-liq")
        fake_off_svc = MagicMock()
        fake_off_svc.get_pending_settlements.return_value = [settlement]
        fake_off_svc.get_request.return_value = _req("emp-1")

        period_employees = [dict(emp)]

        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=fake_off_svc) as _:
            period_employees, liquid_map = _collect_liquidation_employees(
                "co-1", True, "grp-liq", [emp], period_employees,
            )

        assert "emp-1" in liquid_map, "El empleado activo con liquidación debe estar en el mapa"
        assert liquid_map["emp-1"]["id"] == "sett-emp-1"
        assert len(period_employees) == 1
        assert period_employees[0]["id"] == "emp-1"

    def test_empleado_inactivo_no_presente_se_agrega_a_period_y_al_mapa(self):
        emp = _emp("emp-2", 40000.0)
        settlement = _settlement("emp-2", assigned_group="grp-liq")
        fake_off_svc = MagicMock()
        fake_off_svc.get_pending_settlements.return_value = [settlement]
        fake_off_svc.get_request.return_value = _req("emp-2")

        period_employees = []

        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=fake_off_svc):
            period, liquid_map = _collect_liquidation_employees(
                "company-1", "111", "grp-liq", [emp], period_employees,
            )

        assert "emp-2" in liquid_map
        assert len(period) == 1

    def test_sin_grupo_no_construye_mapa(self):
        period = [_emp("emp-3", 40000.0)]
        liquid_map = {}
        period, out_map = _collect_liquidation_employees(
            "company-1", "111", "", period, liquid_map,
        )
        assert out_map == {}

    def test_sin_liquidaciones_pendientes_mapa_vacio(self):
        fake_off_svc = MagicMock()
        fake_off_svc.get_pending_settlements.return_value = []
        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=fake_off_svc):
            period, liquid_map = _collect_liquidation_employees(
                "company-1", "111", "grp-liq", [], [],
            )
        assert liquid_map == {}

    def test_incluye_empleado_sin_assignedGroupId_pero_en_grupo(self):
        emp = _emp("emp-5", 50000.0, groups=["grp-liq"])
        settlement = _settlement("emp-5", assigned_group=None)
        fake_off_svc = MagicMock()
        fake_off_svc.get_pending_settlements.return_value = [settlement]
        fake_off_svc.get_request.return_value = _req("emp-5")

        period_employees = [dict(emp)]

        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=fake_off_svc):
            period, liquid_map = _collect_liquidation_employees(
                "co-1", True, "grp-liq", [emp], period_employees,
            )

        assert "emp-5" in liquid_map

    def test_excluye_empleado_sin_assignedGroupId_y_fuera_del_grupo(self):
        emp = _emp("emp-6", 50000.0, groups=["otro-grupo"])
        settlement = _settlement("emp-6", assigned_group=None)
        fake_off_svc = MagicMock()
        fake_off_svc.get_pending_settlements.return_value = [settlement]
        fake_off_svc.get_request.return_value = _req("emp-6")

        period_employees = [dict(emp)]

        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=fake_off_svc):
            period, liquid_map = _collect_liquidation_employees(
                "co-1", True, "grp-liq", [emp], period_employees,
            )

        assert "emp-6" not in liquid_map

    def test_ignora_requests_cancelados_o_rechazados(self):
        emp = _emp("emp-7", 50000.0, groups=["grp-liq"])
        settlement_cancelled = _settlement("emp-7", assigned_group="grp-liq")
        settlement_cancelled["requestId"] = "req-cancelled"
        settlement_rejected = _settlement("emp-7", assigned_group="grp-liq")
        settlement_rejected["requestId"] = "req-rejected"
        settlement_rejected["id"] = "sett-rej"

        fake_off_svc = MagicMock()
        fake_off_svc.get_pending_settlements.return_value = [
            settlement_cancelled, settlement_rejected,
        ]

        def _get_req(rid):
            if rid == "req-cancelled":
                return {"employeeId": "emp-7", "status": "cancelled"}
            elif rid == "req-rejected":
                return {"employeeId": "emp-7", "status": "rejected"}
            return None
        fake_off_svc.get_request.side_effect = _get_req

        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=fake_off_svc):
            period, liquid_map = _collect_liquidation_employees(
                "co-1", True, "grp-liq", [emp], [dict(emp)],
            )

        assert "emp-7" not in liquid_map


class TestGetPendingLiquidationEmployeeIds:
    """Exclusión de nóminas regulares: global, independiente del grupo."""

    def test_identifica_empleados_con_liquidacion_pendiente_global(self):
        settlement = _settlement("emp-1", assigned_group="otro-grupo")
        fake_off_svc = MagicMock()
        fake_off_svc.get_pending_settlements.return_value = [settlement]
        fake_off_svc.get_request.return_value = _req("emp-1")

        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=fake_off_svc):
            pending_ids = _get_pending_liquidation_employee_ids("co-1", True)

        assert pending_ids == {"emp-1"}

    def test_incluye_settlements_de_cualquier_grupo(self):
        settlement = _settlement("emp-1", assigned_group="otro-grupo")
        fake_off_svc = MagicMock()
        fake_off_svc.get_pending_settlements.return_value = [settlement]
        fake_off_svc.get_request.return_value = _req("emp-1")

        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=fake_off_svc):
            pending_ids = _get_pending_liquidation_employee_ids("co-1", True)

        assert "emp-1" in pending_ids

    def test_nunca_devuelve_vacio_con_settlements_activos(self):
        settlement = _settlement("emp-x")
        fake_off_svc = MagicMock()
        fake_off_svc.get_pending_settlements.return_value = [settlement]
        fake_off_svc.get_request.return_value = _req("emp-x")

        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=fake_off_svc):
            pending_ids = _get_pending_liquidation_employee_ids("co-1", True)

        assert pending_ids == {"emp-x"}

    def test_error_de_servicio_devuelve_vacio(self):
        fake_off_svc = MagicMock()
        fake_off_svc.get_pending_settlements.side_effect = Exception("boom")

        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=fake_off_svc):
            pending_ids = _get_pending_liquidation_employee_ids("co-1", True)

        assert pending_ids == set()

    def test_ignora_requests_cancelados_o_rechazados(self):
        settlement_c = _settlement("emp-c")
        settlement_c["requestId"] = "req-c"
        settlement_r = _settlement("emp-r")
        settlement_r["requestId"] = "req-r"
        settlement_r["id"] = "sett-r"

        fake_off_svc = MagicMock()
        fake_off_svc.get_pending_settlements.return_value = [settlement_c, settlement_r]

        def _get_req(rid):
            if rid == "req-c":
                return {"employeeId": "emp-c", "status": "cancelled"}
            elif rid == "req-r":
                return {"employeeId": "emp-r", "status": "rejected"}
            return None
        fake_off_svc.get_request.side_effect = _get_req

        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=fake_off_svc):
            pending_ids = _get_pending_liquidation_employee_ids("co-1", True)

        assert pending_ids == set(), "Cancelled y rejected deben ser ignorados"


class TestBuildLiquidationLine:
    def test_linea_usa_montos_del_settlement_no_salario_regular(self):
        emp = _emp("emp-1", 45000.0)
        settlement = _settlement("emp-1", monto_total=100000.0, neto=95000.0,
                                 exento=80000.0, sdp=1888.38, descuentos=5000.0)

        line, txs = _build_liquidation_line(settlement, emp)

        assert line["lineType"] == "liquidation"
        assert line["settlementId"] == "sett-emp-1"
        assert line["totalIncome"] == 100000.0
        assert line["netSalary"] == 95000.0
        assert line["grossSalary"] == 100000.0
        assert line["baseSalary"] == round(1888.38 * 23.83, 2)
        assert line["totalIncome"] != 45000.0
        assert sum(t["amount"] for t in txs if t["type"] == "earning") == 100000.0
        assert line["totalEmployerContrib"] == 0.0
        assert line["afpEmployee"] == 0.0 and line["sfsEmployee"] == 0.0 and line["isrRetention"] == 0.0

    def test_linea_desglosa_conceptos_liq_individualmente(self):
        emp = _emp("emp-1", 45000.0)
        settlement = _settlement("emp-1", monto_total=100000.0, neto=95000.0, descuentos=5000.0)

        line, txs = _build_liquidation_line(settlement, emp)

        earn_codes = {t["conceptCode"]: t["amount"] for t in txs if t["type"] == "earning"}
        assert earn_codes["LIQ_PREAVISO"] == 30000.0
        assert earn_codes["LIQ_CESANTIA"] == 50000.0
        assert earn_codes["LIQ_VACACIONES"] == 20000.0
        assert "LIQ_SALARIO_NAVIDAD" not in earn_codes, "No aplica → no debe emitirse"
        assert "LIQ_ASISTENCIA_ECONOMICA" not in earn_codes
        assert "LIQ_PRESTACIONES" not in earn_codes, "Código legacy no debe emitirse"

    def test_linea_emite_deduccion_liq_descuentos(self):
        emp = _emp("emp-1", 45000.0)
        settlement = _settlement("emp-1", monto_total=100000.0, neto=95000.0, descuentos=5000.0)

        line, txs = _build_liquidation_line(settlement, emp)

        ded_codes = {t["conceptCode"]: t["amount"] for t in txs if t["type"] == "deduction"}
        assert ded_codes.get("LIQ_DESCUENTOS") == 5000.0
        assert line["totalDeductions"] == 5000.0
        assert line["netSalary"] == 100000.0 - 5000.0
        assert line["otherDeductions"] == 5000.0

    def test_linea_sin_descuentos_no_emite_deduccion(self):
        emp = _emp("emp-1", 45000.0)
        settlement = _settlement("emp-1", monto_total=100000.0, neto=100000.0, descuentos=0.0)

        line, txs = _build_liquidation_line(settlement, emp)

        assert all(t["type"] == "earning" for t in txs)
        assert line["totalDeductions"] == 0.0
        assert line["netSalary"] == 100000.0

    def test_linea_sin_totales_cae_a_cero(self):
        emp = _emp("emp-x", 45000.0)
        settlement = {"totales": {}, "salarioDiarioPromedio": 0.0, "id": "sx"}
        line, txs = _build_liquidation_line(settlement, emp)
        assert line["totalIncome"] == 0.0
        assert line["netSalary"] == 0.0


class TestSimuladorLiquidacion:
    """El simulador debe producir el MISMO cálculo que el procesamiento real:
    usa los montos del settlement, no el salario regular."""

    def test_simulador_linea_liquidacion_usa_settlement(self):
        from datetime import date
        from types import SimpleNamespace

        import app.web.rrhh.payroll_process as pp

        emp = _emp("emp-1", 45000.0)
        settlement = _settlement("emp-1", monto_total=100000.0, neto=95000.0, assigned_group="grp-liq")

        fake_off_svc = MagicMock()
        fake_off_svc.get_pending_settlements.return_value = [settlement]
        fake_off_svc.get_request.return_value = _req("emp-1")

        year = date.today().year
        fake_request = SimpleNamespace(
            args=SimpleNamespace(get=lambda k, d="": ""),
            form={
                "payrollGroupId": "grp-liq",
                "period_key": f"{year}-08-M",
                "periodSubType": "liquidation",
            },
            method="POST",
        )
        captured = {}

        def _fake_render(*args, **kwargs):
            captured.update(kwargs)
            return ""

        with patch.object(pp, "request", fake_request), \
             patch.object(pp, "_login_required", return_value=False), \
             patch.object(pp, "_get_owner_uid_and_sandbox",
                          return_value=("u1", True, "co-1")), \
             patch.object(pp, "render_template", side_effect=_fake_render), \
             patch.object(pp, "flash"), \
             patch.object(pp, "url_for", return_value="/"), \
             patch("app.services.hr_data_service") as mock_hr, \
             patch("app.services.offboarding_service.OffboardingService",
                   return_value=fake_off_svc), \
             patch.object(pp, "PayrollService"), \
             patch.object(pp.OvertimeService, "get_approved_for_period",
                          return_value=[]), \
             patch.object(pp.OvertimeService, "group_by_employee_and_type",
                          return_value={}), \
             patch("app.services.legal_parameter_resolver.resolve_all", return_value={}), \
             patch("app.services.payroll_concept_engine.get_concepts", return_value=[]), \
             patch("app.services.payroll_concept_engine.build_concept_snapshot",
                   return_value={}), \
             patch("app.services.recurring_service.get_recurring_movements",
                   return_value=[]):
            mock_hr.get_payroll_config.return_value = {
                "onboardingCompleted": True, "payrollFrequency": "mensual",
            }
            mock_hr.get_employees.return_value = [emp]
            mock_hr.get_payroll_groups.return_value = [{
                "id": "grp-liq", "name": "Liquidados", "frequency": "mensual",
            }]
            mock_hr.get_payroll_group.return_value = {"groupOverrides": {}}
            mock_hr.get_active_rules_for_scope.return_value = []
            mock_hr.get_dependents_for_employees.return_value = {}

            pp.payroll_simulate()

        simulation = captured.get("simulation")
        assert simulation is not None, "Debe devolverse un objeto simulation"
        assert len(simulation["lines"]) == 1
        line = simulation["lines"][0]
        assert line["lineType"] == "liquidation"
        assert line["totalIncome"] == 100000.0
        assert line["netSalary"] == 95000.0
        assert line["totalIncome"] != 45000.0
        assert line["isrRetention"] == 0.0
        assert simulation["total_gross"] == 100000.0
        assert simulation["total_net"] == 95000.0

        liq_codes = [c["code"] for c in simulation.get("liquidationColumns", [])]
        assert "LIQ_PREAVISO" in liq_codes
        assert "LIQ_CESANTIA" in liq_codes
        assert "LIQ_VACACIONES" in liq_codes
        assert "LIQ_PRESTACIONES" not in liq_codes, "Código legacy no debe emitirse"
        liq_map = line.get("liquidationMap", {})
        assert liq_map.get("LIQ_PREAVISO") == 30000.0
        assert liq_map.get("LIQ_CESANTIA") == 50000.0
        assert liq_map.get("LIQ_VACACIONES") == 20000.0

    def test_simulador_regular_excluye_empleado_con_liquidacion_pendiente(self):
        """En modo "regular", un empleado con liquidación pendiente NO debe
        aparecer en las líneas de la simulación (solo va en la nómina de liquidación)."""
        from datetime import date
        from types import SimpleNamespace

        import app.web.rrhh.payroll_process as pp

        emp = _emp("emp-1", 45000.0)
        settlement = _settlement("emp-1", monto_total=100000.0, neto=95000.0)

        fake_off_svc = MagicMock()
        fake_off_svc.get_pending_settlements.return_value = [settlement]
        fake_off_svc.get_request.return_value = _req("emp-1")

        year = date.today().year
        fake_request = SimpleNamespace(
            args=SimpleNamespace(get=lambda k, d="": ""),
            form={
                "payrollGroupId": "grp-liq",
                "period_key": f"{year}-08-M",
                "periodSubType": "regular",
            },
            method="POST",
        )
        captured = {}

        def _fake_render(*args, **kwargs):
            captured.update(kwargs)
            return ""

        with patch.object(pp, "request", fake_request), \
             patch.object(pp, "_login_required", return_value=False), \
             patch.object(pp, "_get_owner_uid_and_sandbox",
                          return_value=("u1", True, "co-1")), \
             patch.object(pp, "render_template", side_effect=_fake_render), \
             patch.object(pp, "flash"), \
             patch.object(pp, "url_for", return_value="/"), \
             patch("app.services.hr_data_service") as mock_hr, \
             patch("app.services.offboarding_service.OffboardingService",
                   return_value=fake_off_svc), \
             patch.object(pp, "PayrollService"), \
             patch.object(pp.OvertimeService, "get_approved_for_period",
                          return_value=[]), \
             patch.object(pp.OvertimeService, "group_by_employee_and_type",
                          return_value={}), \
             patch("app.services.legal_parameter_resolver.resolve_all", return_value={}), \
             patch("app.services.payroll_concept_engine.get_concepts", return_value=[]), \
             patch("app.services.payroll_concept_engine.build_concept_snapshot",
                   return_value={}), \
             patch("app.services.recurring_service.get_recurring_movements",
                   return_value=[]):
            mock_hr.get_payroll_config.return_value = {
                "onboardingCompleted": True, "payrollFrequency": "mensual",
            }
            mock_hr.get_employees.return_value = [emp]
            mock_hr.get_payroll_groups.return_value = [{
                "id": "grp-liq", "name": "Liquidados", "frequency": "mensual",
            }]
            mock_hr.get_payroll_group.return_value = {"groupOverrides": {}}
            mock_hr.get_active_rules_for_scope.return_value = []
            mock_hr.get_dependents_for_employees.return_value = {}

            pp.payroll_simulate()

        simulation = captured.get("simulation")
        assert simulation is not None, "Debe devolverse un objeto simulation"
        assert simulation["lines"] == [], (
            "En nómina regular el empleado con liquidación pendiente debe quedar excluido"
        )
        assert simulation["total_gross"] == 0.0
        assert simulation["total_net"] == 0.0

    def test_simulador_liquidacion_incluye_empleado_con_unassigned_but_in_group(self):
        """Liquidación debe incluir empleado sin assignedGroupId pero en el grupo."""
        from datetime import date
        from types import SimpleNamespace

        import app.web.rrhh.payroll_process as pp

        emp = _emp("emp-1", 45000.0, groups=["grp-liq"])
        settlement = _settlement("emp-1", monto_total=100000.0, neto=95000.0, assigned_group=None)

        fake_off_svc = MagicMock()
        fake_off_svc.get_pending_settlements.return_value = [settlement]
        fake_off_svc.get_request.return_value = _req("emp-1")

        year = date.today().year
        fake_request = SimpleNamespace(
            args=SimpleNamespace(get=lambda k, d="": ""),
            form={
                "payrollGroupId": "grp-liq",
                "period_key": f"{year}-08-M",
                "periodSubType": "liquidation",
            },
            method="POST",
        )
        captured = {}

        def _fake_render(*args, **kwargs):
            captured.update(kwargs)
            return ""

        with patch.object(pp, "request", fake_request), \
             patch.object(pp, "_login_required", return_value=False), \
             patch.object(pp, "_get_owner_uid_and_sandbox",
                          return_value=("u1", True, "co-1")), \
             patch.object(pp, "render_template", side_effect=_fake_render), \
             patch.object(pp, "flash"), \
             patch.object(pp, "url_for", return_value="/"), \
             patch("app.services.hr_data_service") as mock_hr, \
             patch("app.services.offboarding_service.OffboardingService",
                   return_value=fake_off_svc), \
             patch.object(pp, "PayrollService"), \
             patch.object(pp.OvertimeService, "get_approved_for_period",
                          return_value=[]), \
             patch.object(pp.OvertimeService, "group_by_employee_and_type",
                          return_value={}), \
             patch("app.services.legal_parameter_resolver.resolve_all", return_value={}), \
             patch("app.services.payroll_concept_engine.get_concepts", return_value=[]), \
             patch("app.services.payroll_concept_engine.build_concept_snapshot",
                   return_value={}), \
             patch("app.services.recurring_service.get_recurring_movements",
                   return_value=[]):
            mock_hr.get_payroll_config.return_value = {
                "onboardingCompleted": True, "payrollFrequency": "mensual",
            }
            mock_hr.get_employees.return_value = [emp]
            mock_hr.get_payroll_groups.return_value = [{
                "id": "grp-liq", "name": "Liquidados", "frequency": "mensual",
            }]
            mock_hr.get_payroll_group.return_value = {"groupOverrides": {}}
            mock_hr.get_active_rules_for_scope.return_value = []
            mock_hr.get_dependents_for_employees.return_value = {}

            pp.payroll_simulate()

        simulation = captured.get("simulation")
        assert simulation is not None
        assert len(simulation["lines"]) == 1
        assert simulation["lines"][0]["lineType"] == "liquidation"
        assert simulation["total_gross"] == 100000.0


class TestPendingSettlementsServerSide:
    """get_pending_settlements ahora usa filtro server-side con fallback."""

    def test_llama_get_all_con_server_side_filter(self):
        with patch("app.services.offboarding_data_service.get_all") as mock_get_all:
            mock_get_all.return_value = []
            from app.services.offboarding_service import OffboardingService
            svc = OffboardingService("co-1", True)
            result = svc.get_pending_settlements()
            mock_get_all.assert_called_once()
            call_kwargs = mock_get_all.call_args.kwargs
            assert call_kwargs["apply_filters_server_side"] is True
            assert call_kwargs["limit"] == 5000
            assert call_kwargs["where_filters"] == [("status", "==", "pendiente_pago")]

    def test_server_side_fallback_filtra_clientside(self):
        with patch("app.services.offboarding_data_service.get_all") as mock_:
            pending = [
                {"id": "s1", "status": "pendiente_pago", "createdAt": "2025-01-01"},
                {"id": "s2", "status": "calculada", "createdAt": "2025-01-02"},
                {"id": "s3", "status": "pagada", "createdAt": "2025-01-03"},
            ]
            mock_.return_value = pending
            from app.services.offboarding_service import OffboardingService
            svc = OffboardingService("co-1", True)
            result = svc.get_pending_settlements()
            assert len(result) == 1
            assert result[0]["id"] == "s1"

    def test_apply_filters_server_side_intenta_query_con_where(self):
        try:
            import google.cloud.firestore
        except ImportError:
            pytest.skip("google-cloud-firestore not available")

        with patch("app.services.offboarding_data_service._collection") as mock_coll_fn:
            mock_query = MagicMock()
            mock_query.where.return_value = mock_query
            mock_query.order_by.return_value = mock_query
            mock_query.limit.return_value = mock_query
            mock_query.get.return_value = []
            mock_coll_fn.return_value = mock_query

            from app.services.offboarding_service import OffboardingService
            svc = OffboardingService("co-1", True)
            svc.get_pending_settlements()

            mock_coll_fn.assert_called_once()
            mock_query.where.assert_called_with("status", "==", "pendiente_pago")
            mock_query.order_by.assert_called_with("createdAt", direction="DESCENDING")
            mock_query.limit.assert_called_with(5000)


class TestUXLiquidationEmployeesMerge:
    """En payroll_new, los empleados con liquidación pendiente se fusionan en la lista visible."""

    def test_pending_liquidation_employees_se_agregan_a_employees(self):
        from app.services import hr_data_service as hr
        emp_active = _emp("emp-a", 45000.0, "Activo", groups=["grp-liq"])
        emp_liquid = _emp("emp-l", 50000.0, "LiquidationEmp", groups=["grp-liq"])
        emp_liquid["status"] = "terminado"

        settlement = _settlement("emp-l", assigned_group="grp-liq")

        fake_off_svc = MagicMock()
        fake_off_svc.get_pending_settlements.return_value = [settlement]
        fake_off_svc.get_request.side_effect = lambda rid: (
            _req("emp-l") if rid == "req-emp-l" else None
        )

        with patch("app.services.offboarding_service.OffboardingService",
                   return_value=fake_off_svc):
            with patch.object(hr, "get_employees",
                              return_value=[emp_active, emp_liquid]):
                with patch.object(hr, "get_payroll_config",
                                  return_value={"onboardingCompleted": True, "payrollFrequency": "mensual"}):
                    with patch.object(hr, "get_payroll_groups",
                                      return_value=[{"id":"grp-liq","name":"Liquidados","frequency":"mensual"}]):
                        from app.web.rrhh import payroll_process as pp
                        fake_request = type("Req", (), {
                            "args": {"group": "grp-liq"},
                            "form": {},
                            "method": "GET",
                        })()
                        captured = {}
                        def _fake_render(*args, **kwargs):
                            captured.update(kwargs)
                            return ""
                        with patch.object(pp, "request", fake_request), \
                             patch.object(pp, "_login_required", return_value=False), \
                             patch.object(pp, "_get_owner_uid_and_sandbox", return_value=("u1", True, "co-1")), \
                             patch.object(pp, "render_template", side_effect=_fake_render), \
                             patch.object(pp, "flash"), \
                             patch.object(pp, "url_for", return_value="/"):
                            pp.payroll_new()

                        employees = captured.get("employees", [])
                        liquid_ids = [e["id"] for e in employees if e.get("isLiquidation")]
                        assert "emp-l" in liquid_ids, "El empleado con liquidación debe aparecer con isLiquidation=True"
