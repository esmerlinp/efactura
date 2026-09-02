"""Tests para OvertimeService — edición en borrador, liberación por reversión de nómina."""

import pytest
from unittest.mock import MagicMock, patch

from app.services.overtime_service import OvertimeService


def _make_record(status, **overrides):
    record = {
        "id": "HE-001",
        "number": "HE-000001",
        "employeeId": "E1",
        "employeeSnapshot": {"code": "1", "name": "Juan Pérez"},
        "date": "2026-08-10",
        "overtimeTypeCode": "HE01",
        "totalMinutes": 120,
        "comment": "",
        "source": "manual",
        "sourceReference": "",
        "details": [{"date": "2026-08-10", "fromTime": "18:00", "toTime": "20:00", "minutes": 120}],
        "status": status,
        "hourlyRateAtApproval": 150.0,
        "factorAtApproval": 1.35,
        "approvedBy": "approver@example.com",
        "approvedAt": "2026-08-11T00:00:00+00:00",
        "processedPayrollId": "PAY-1",
        "processedAt": "2026-08-12T00:00:00+00:00",
        "statusHistory": [{"status": status, "by": "x", "at": "2026-08-10T00:00:00+00:00", "comment": "Creado"}],
    }
    record.update(overrides)
    return record


# ═══════════════════════════════════════════════════════════════════════
# UPDATE RECORD (solo borrador)
# ═══════════════════════════════════════════════════════════════════════

class TestUpdateRecord:

    @patch("app.services.overtime_service.hr")
    def test_edita_solo_en_borrador(self, hr_mock):
        hr_mock.get_overtime_record.return_value = _make_record("draft")
        result = OvertimeService.update_record("C1", "HE-001", {
            "employeeId": "E2",
            "employeeCode": "2",
            "employeeName": "Ana Rosa",
            "date": "2026-08-15",
            "overtimeTypeCode": "HE03",
            "totalMinutes": 60,
            "details": [{"date": "2026-08-15", "fromTime": "09:00", "toTime": "10:00", "minutes": 60}],
        }, "editor@example.com")

        assert result["status"] == "draft"
        assert result["employeeId"] == "E2"
        assert result["employeeSnapshot"]["name"] == "Ana Rosa"
        assert result["totalMinutes"] == 60
        assert result["hourlyRateAtApproval"] == 0.0
        assert result["factorAtApproval"] == 0.0
        assert result["statusHistory"][-1]["comment"] == "Editado"
        hr_mock.save_overtime_record.assert_called_once()

    @patch("app.services.overtime_service.hr")
    def test_rechaza_estado_aprobada(self, hr_mock):
        hr_mock.get_overtime_record.return_value = _make_record("approved")
        result = OvertimeService.update_record("C1", "HE-001", {}, "editor@example.com")
        assert isinstance(result, tuple)
        assert result[1] == 400
        assert "borrador" in result[0]["error"]
        hr_mock.save_overtime_record.assert_not_called()

    @patch("app.services.overtime_service.hr")
    def test_rechaza_estado_procesada(self, hr_mock):
        hr_mock.get_overtime_record.return_value = _make_record("processed")
        result = OvertimeService.update_record("C1", "HE-001", {}, "editor@example.com")
        assert isinstance(result, tuple)
        assert result[1] == 400
        hr_mock.save_overtime_record.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# RELEASE PROCESSED (reversión de nómina)
# ═══════════════════════════════════════════════════════════════════════

class TestReleaseProcessed:

    @patch("app.services.overtime_service.hr")
    def test_libera_procesada_a_borrador(self, hr_mock):
        hr_mock.get_overtime_record.return_value = _make_record("processed")
        result = OvertimeService.release_processed("C1", "HE-001", "admin@example.com")

        assert result["status"] == "draft"
        assert result["processedPayrollId"] == ""
        assert result["processedAt"] is None
        assert result["hourlyRateAtApproval"] == 0.0
        assert result["factorAtApproval"] == 0.0
        assert result["approvedBy"] == ""
        assert result["approvedAt"] is None
        statuses = [h["status"] for h in result["statusHistory"]]
        assert "reopened" in statuses
        assert statuses[-1] == "draft"
        hr_mock.save_overtime_record.assert_called_once()

    @patch("app.services.overtime_service.hr")
    def test_libera_bloqueada_a_borrador(self, hr_mock):
        hr_mock.get_overtime_record.return_value = _make_record("locked")
        result = OvertimeService.release_processed("C1", "HE-001", "admin@example.com")
        assert result["status"] == "draft"

    @patch("app.services.overtime_service.hr")
    def test_rechaza_estado_draft(self, hr_mock):
        hr_mock.get_overtime_record.return_value = _make_record("draft")
        result = OvertimeService.release_processed("C1", "HE-001", "admin@example.com")
        assert isinstance(result, tuple)
        assert result[1] == 400
        hr_mock.save_overtime_record.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# GET PROCESSED FOR PAYROLL
# ═══════════════════════════════════════════════════════════════════════

class TestGetProcessedForPayroll:

    @patch("app.services.overtime_service.hr")
    def test_filtra_por_payroll_id(self, hr_mock):
        hr_mock.get_overtime_records.return_value = [
            _make_record("processed", id="HE-001", processedPayrollId="PAY-1"),
            _make_record("processed", id="HE-002", processedPayrollId="PAY-2"),
            _make_record("approved", id="HE-003", processedPayrollId=""),
        ]
        result = OvertimeService.get_processed_for_payroll("C1", "PAY-1")
        assert [r["id"] for r in result] == ["HE-001"]


# ═══════════════════════════════════════════════════════════════════════
# HELPER DE REVERSIÓN EN payroll_workflow
# ═══════════════════════════════════════════════════════════════════════

class TestReleasePayrollOvertime:

    @patch("app.services.hr_data_service.delete_overtime_payroll_links")
    @patch("app.services.overtime_service.OvertimeService.release_processed")
    @patch("app.services.overtime_service.OvertimeService.get_processed_for_payroll")
    @patch("app.web.rrhh.payroll_workflow.session", new_callable=MagicMock)
    def test_libera_y_borra_links(self, session_mock, get_mock, release_mock, delete_mock):
        from app.web.rrhh.payroll_workflow import _release_payroll_overtime

        get_mock.return_value = [
            _make_record("processed", id="HE-001"),
            _make_record("processed", id="HE-002"),
        ]
        release_mock.return_value = _make_record("draft", id="HE-001")
        session_mock.get.return_value = {"email": "admin@example.com"}

        released = _release_payroll_overtime("C1", "PAY-1", sandbox=True)

        assert released == 2
        assert release_mock.call_count == 2
        delete_mock.assert_called_once_with("C1", "PAY-1", sandbox=True)

    @patch("app.services.hr_data_service.delete_overtime_payroll_links")
    @patch("app.services.overtime_service.OvertimeService.release_processed")
    @patch("app.services.overtime_service.OvertimeService.get_processed_for_payroll")
    @patch("app.web.rrhh.payroll_workflow.session", new_callable=MagicMock)
    def test_sin_registros_no_libera(self, session_mock, get_mock, release_mock, delete_mock):
        from app.web.rrhh.payroll_workflow import _release_payroll_overtime

        get_mock.return_value = []
        released = _release_payroll_overtime("C1", "PAY-1", sandbox=True)
        assert released == 0
        release_mock.assert_not_called()
        delete_mock.assert_called_once_with("C1", "PAY-1", sandbox=True)
