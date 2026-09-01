"""Tests para EmployeeStatusService — estados transitorios vacaciones/licencia.

Cubre: días efectivos del balance, transiciones automáticas de estado,
prioridad de licencia sobre vacaciones, revocación con reembolso, anulación
a mitad de curso con prorrateo, idempotencia y respeto a inactivo/suspendido.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.services.employee_status_service import EmployeeStatusService
from app.utils.hr_utils import is_active_equivalent, ACTIVE_EQUIVALENT_STATUSES

COMPANY = "company-test"


def _emp(emp_id="e1", status="activo"):
    return {"id": emp_id, "fullName": "Ana Pérez", "status": status}


def _vac(emp_id="e1", status="aprobada", start="2026-01-05", end="2026-01-16", days=10):
    return {
        "id": "v1", "employeeId": emp_id, "status": status,
        "startDate": start, "endDate": end, "days": days,
    }


def _leave(emp_id="e1", status="aprobada", start="2026-01-12", end="2026-01-14",
           leave_type="medica"):
    return {
        "id": "l1", "employeeId": emp_id, "status": status,
        "leaveType": leave_type, "startDate": start, "endDate": end, "days": 3,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Helper is_active_equivalent
# ═══════════════════════════════════════════════════════════════════════════

class TestActiveEquivalent:
    def test_statuses(self):
        assert is_active_equivalent("activo")
        assert is_active_equivalent("vacaciones")
        assert is_active_equivalent("licencia")
        assert not is_active_equivalent("inactivo")
        assert not is_active_equivalent("suspendido")
        assert not is_active_equivalent("")
        assert not is_active_equivalent(None)

    def test_constant(self):
        assert set(ACTIVE_EQUIVALENT_STATUSES) == {"activo", "vacaciones", "licencia"}


# ═══════════════════════════════════════════════════════════════════════════
# Días disponibles
# ═══════════════════════════════════════════════════════════════════════════

class TestTakenVacationDays:
    def test_aprobada_cuenta_dias_completos(self):
        reqs = [_vac(days=10), _vac(days=5)]
        assert EmployeeStatusService.taken_vacation_days(reqs) == 15

    def test_anulada_solo_consumidos(self):
        reqs = [_vac(days=10), {**_vac(days=10), "status": "anulada", "consumedDays": 4}]
        assert EmployeeStatusService.taken_vacation_days(reqs) == 14

    def test_revocada_solo_consumidos(self):
        reqs = [{**_vac(days=8), "status": "revocada", "consumedDays": 0}]
        assert EmployeeStatusService.taken_vacation_days(reqs) == 0

    def test_pendiente_y_rechazada_no_cuentan(self):
        reqs = [
            {**_vac(days=10), "status": "pendiente"},
            {**_vac(days=10), "status": "rechazada"},
        ]
        assert EmployeeStatusService.taken_vacation_days(reqs) == 0

    def test_lista_vacia(self):
        assert EmployeeStatusService.taken_vacation_days([]) == 0
        assert EmployeeStatusService.taken_vacation_days(None) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Sincronización de estado
# ═══════════════════════════════════════════════════════════════════════════

class TestSyncEmployee:
    @patch("app.services.employee_status_service.hr")
    def test_inicio_vacaciones(self, mock_hr):
        mock_hr.get_employee.return_value = _emp()
        mock_hr.get_vacation_requests.return_value = [_vac()]
        mock_hr.get_leave_requests.return_value = []

        res = EmployeeStatusService.sync_employee(
            COMPANY, "e1", sandbox=True, today=date(2026, 1, 6))

        assert res["to"] == "vacaciones"
        saved = mock_hr.save_employee.call_args.args[2]
        assert saved["status"] == "vacaciones"
        assert mock_hr.save_employee_status_event.called

    @patch("app.services.employee_status_service.hr")
    def test_fin_vacaciones_vuelve_activo(self, mock_hr):
        mock_hr.get_employee.return_value = _emp(status="vacaciones")
        mock_hr.get_vacation_requests.return_value = [_vac(end="2026-01-10")]
        mock_hr.get_leave_requests.return_value = []

        res = EmployeeStatusService.sync_employee(
            COMPANY, "e1", sandbox=True, today=date(2026, 1, 11))

        assert res["to"] == "activo"
        saved = mock_hr.save_employee.call_args.args[2]
        assert saved["status"] == "activo"

    @patch("app.services.employee_status_service.hr")
    def test_licencia_gana_y_revoca_vacaciones(self, mock_hr):
        mock_hr.get_employee.return_value = _emp(status="activo")
        vac = _vac(start="2026-01-05", end="2026-01-16", days=10)
        mock_hr.get_vacation_requests.return_value = [vac]
        mock_hr.get_leave_requests.return_value = [
            _leave(start="2026-01-12", end="2026-01-14")]

        with patch.object(EmployeeStatusService, "_business_days", return_value=5):
            res = EmployeeStatusService.sync_employee(
                COMPANY, "e1", sandbox=True, today=date(2026, 1, 13))

        assert res["to"] == "licencia"
        # La vacación fue revocada con prorrateo
        saved_vac = mock_hr.save_vacation_request.call_args.args[2]
        assert saved_vac["status"] == "revocada"
        assert saved_vac["consumedDays"] == 5
        assert saved_vac["refundedDays"] == 5
        assert saved_vac["revokedByLeaveId"] == "l1"

    @patch("app.services.employee_status_service.hr")
    def test_sin_solicitud_vigente_y_ya_activo_no_op(self, mock_hr):
        mock_hr.get_employee.return_value = _emp(status="activo")
        mock_hr.get_vacation_requests.return_value = [_vac(end="2026-01-10")]
        mock_hr.get_leave_requests.return_value = []

        res = EmployeeStatusService.sync_employee(
            COMPANY, "e1", sandbox=True, today=date(2026, 1, 11))

        assert res is None
        mock_hr.save_employee.assert_not_called()

    @patch("app.services.employee_status_service.hr")
    @pytest.mark.parametrize("status", ["inactivo", "suspendido"])
    def test_no_toca_inactivo_ni_suspendido(self, mock_hr, status):
        mock_hr.get_employee.return_value = _emp(status=status)
        mock_hr.get_vacation_requests.return_value = [_vac()]

        res = EmployeeStatusService.sync_employee(
            COMPANY, "e1", sandbox=True, today=date(2026, 1, 6))

        assert res is None
        mock_hr.save_employee.assert_not_called()

    @patch("app.services.employee_status_service.hr")
    def test_idempotencia(self, mock_hr):
        mock_hr.get_employee.return_value = _emp(status="vacaciones")
        mock_hr.get_vacation_requests.return_value = [_vac()]
        mock_hr.get_leave_requests.return_value = []

        res = EmployeeStatusService.sync_employee(
            COMPANY, "e1", sandbox=True, today=date(2026, 1, 6))
        assert res is None
        mock_hr.save_employee.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# Anulación de vacaciones con prorrateo
# ═══════════════════════════════════════════════════════════════════════════

class TestCancelVacation:
    @patch("app.services.employee_status_service.hr")
    def test_anulacion_antes_de_inicio_reembolsa_todo(self, mock_hr):
        vac = _vac(start="2026-01-05", end="2026-01-16", days=10)
        mock_hr.get_vacation_request.return_value = vac
        mock_hr.get_employee.return_value = _emp()
        mock_hr.get_vacation_requests.return_value = []
        mock_hr.get_leave_requests.return_value = []

        res = EmployeeStatusService.cancel_vacation_request(
            COMPANY, "v1", cancel_date="2026-01-02", actor="rrrhh@x.com",
            sandbox=True, today=date(2026, 1, 3))

        assert res["success"] is True
        assert res["consumedDays"] == 0
        assert res["refundedDays"] == 10
        saved = mock_hr.save_vacation_request.call_args.args[2]
        assert saved["status"] == "anulada"
        assert saved["consumedDays"] == 0

    @patch("app.services.employee_status_service.hr")
    def test_anulacion_a_mitad_prorratea(self, mock_hr):
        vac = _vac(start="2026-01-05", end="2026-01-16", days=10)
        mock_hr.get_vacation_request.return_value = vac
        mock_hr.get_employee.return_value = _emp(status="vacaciones")
        mock_hr.get_vacation_requests.return_value = [vac]
        mock_hr.get_leave_requests.return_value = []

        with patch.object(EmployeeStatusService, "_business_days", return_value=6):
            res = EmployeeStatusService.cancel_vacation_request(
                COMPANY, "v1", cancel_date="2026-01-12", actor="rrrhh@x.com",
                sandbox=True, today=date(2026, 1, 12))

        assert res["success"] is True
        assert res["consumedDays"] == 6
        assert res["refundedDays"] == 4
        saved = mock_hr.save_vacation_request.call_args.args[2]
        assert saved["status"] == "anulada"
        # El empleado queda sin vacación vigente → sync lo devuelve a activo
        emp_saved = mock_hr.save_employee.call_args.args[2]
        assert emp_saved["status"] == "activo"

    @patch("app.services.employee_status_service.hr")
    def test_no_se_puede_anular_vacacion_concluida(self, mock_hr):
        vac = _vac(start="2026-01-05", end="2026-01-16", days=10)
        mock_hr.get_vacation_request.return_value = vac

        res = EmployeeStatusService.cancel_vacation_request(
            COMPANY, "v1", actor="rrrhh@x.com", sandbox=True,
            today=date(2026, 1, 20))

        assert res["success"] is False
        assert "concluyó" in res["error"]
        mock_hr.save_vacation_request.assert_not_called()

    @patch("app.services.employee_status_service.hr")
    def test_no_se_puede_anular_pendiente(self, mock_hr):
        mock_hr.get_vacation_request.return_value = _vac(status="pendiente")

        res = EmployeeStatusService.cancel_vacation_request(
            COMPANY, "v1", actor="rrrhh@x.com", sandbox=True,
            today=date(2026, 1, 10))

        assert res["success"] is False


# ═══════════════════════════════════════════════════════════════════════════
# Revocación por licencia
# ═══════════════════════════════════════════════════════════════════════════

class TestRevokeForLeave:
    @patch("app.services.employee_status_service.hr")
    def test_licencia_desde_inicio_vacaciones_no_consume_dias(self, mock_hr):
        vac = _vac(start="2026-01-05", end="2026-01-16", days=10)
        leave = _leave(start="2026-01-04", end="2026-01-06")
        mock_hr.get_employee.return_value = _emp()

        with patch.object(EmployeeStatusService, "_business_days", return_value=0):
            res = EmployeeStatusService.revoke_vacation_for_leave(
                COMPANY, vac, leave, actor="Sistema", sandbox=True)

        assert res["success"] is True
        assert res["consumedDays"] == 0
        assert res["refundedDays"] == 10

    @patch("app.services.employee_status_service.hr")
    def test_licencia_a_mitad_consume_dias_hasta_licencia(self, mock_hr):
        vac = _vac(start="2026-01-05", end="2026-01-16", days=10)
        leave = _leave(start="2026-01-12", end="2026-01-14")
        mock_hr.get_employee.return_value = _emp()

        with patch.object(EmployeeStatusService, "_business_days", return_value=5):
            res = EmployeeStatusService.revoke_vacation_for_leave(
                COMPANY, vac, leave, actor="Sistema", sandbox=True)

        assert res["success"] is True
        assert res["consumedDays"] == 5
        assert res["refundedDays"] == 5
        saved = mock_hr.save_vacation_request.call_args.args[2]
        assert saved["status"] == "revocada"

    @patch("app.services.employee_status_service.hr")
    def test_revoke_solo_aplicable_a_aprobada(self, mock_hr):
        vac = _vac(status="rechazada")
        res = EmployeeStatusService.revoke_vacation_for_leave(
            COMPANY, vac, _leave(), actor="Sistema", sandbox=True)
        assert res["success"] is False

    @patch("app.services.employee_status_service.hr")
    def test_revoke_overlapping_vacations(self, mock_hr):
        vacs = [
            _vac(start="2026-01-05", end="2026-01-16", days=10),
            {**_vac(), "id": "v2", "startDate": "2026-02-01", "endDate": "2026-02-10"},
        ]
        mock_hr.get_vacation_requests.return_value = vacs
        mock_hr.get_employee.return_value = _emp()
        leave = _leave(start="2026-01-12", end="2026-01-14")

        with patch.object(EmployeeStatusService, "_business_days", return_value=5):
            revoked = EmployeeStatusService.revoke_overlapping_vacations(
                COMPANY, leave, actor="Sistema", sandbox=True)

        assert len(revoked) == 1
        assert revoked[0]["requestId"] == "v1"
