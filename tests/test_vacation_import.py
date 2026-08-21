# tests/test_vacation_import.py
import io
import time
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from app.web.rrhh.vacation_import import (
    VACATION_CSV_FIELDS,
    VACATION_REQUIRED_FIELDS,
    VACATION_TARGET_FIELDS,
    _get_delimiter,
    _normalize_date,
    _resolve_employee,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers puros
# ─────────────────────────────────────────────────────────────────────────────

def test_field_definitions():
    ids = [f[0].lstrip("*") for f in VACATION_CSV_FIELDS]
    assert ids == ["employeeCedula", "startDate", "endDate", "days", "notes"]
    required = [f[0].lstrip("*") for f in VACATION_CSV_FIELDS if f[2]]
    assert required == ["employeeCedula", "startDate", "endDate"]
    assert VACATION_REQUIRED_FIELDS == required
    assert len(VACATION_TARGET_FIELDS) == len(VACATION_CSV_FIELDS)
    for t in VACATION_TARGET_FIELDS:
        assert "id" in t
        assert "required" in t
        assert "suggestions" in t


def test_get_delimiter():
    assert _get_delimiter("cedula,fecha,fin") == ","
    assert _get_delimiter("cedula;fecha;fin") == ";"
    assert _get_delimiter("cedula\tfecha\tfin") == "\t"
    assert _get_delimiter("cedula") == ","


def test_normalize_date_iso():
    assert _normalize_date("2026-03-02") == "2026-03-02"


def test_normalize_date_slashes():
    assert _normalize_date("02/03/2026") == "2026-03-02"
    assert _normalize_date("02/03/26") == "2026-03-02"


def test_normalize_date_dashes():
    assert _normalize_date("02-03-2026") == "2026-03-02"


def test_normalize_date_with_time():
    assert _normalize_date("2026-03-02 00:00:00") == "2026-03-02"


def test_normalize_date_invalid():
    assert _normalize_date("") is None
    assert _normalize_date("hola") is None
    assert _normalize_date("31/02/2026") is None
    assert _normalize_date("2026/03/02") is None


def test_resolve_employee_by_id():
    emp = {"id": "emp-1", "fullName": "Juan Perez", "cedula": "40212345678"}
    assert _resolve_employee("emp-1", {"emp-1": emp}, {}, []) == emp


def test_resolve_employee_by_cedula_normalized():
    emp = {"id": "emp-1", "fullName": "Juan Perez", "cedula": "402-1234567-8"}
    cedula_map = {"40212345678": emp}
    assert _resolve_employee("402-1234567-8", {}, cedula_map, []) == emp


def test_resolve_employee_by_name_fallback():
    emp = {"id": "emp-1", "fullName": "Juan Perez"}
    assert _resolve_employee("juan perez", {}, {}, [emp]) == emp


def test_resolve_employee_not_found():
    assert _resolve_employee("", {}, {}, []) is None
    assert _resolve_employee("99999999999", {}, {}, []) is None


# ─────────────────────────────────────────────────────────────────────────────
# Flujo completo (upload → process → status)
# ─────────────────────────────────────────────────────────────────────────────

CSV_FULL = ("*employeeCedula,*startDate,*endDate,days,notes\n"
            "40212345678,02/03/2026,13/03/2026,10,Migrado del sistema anterior\n")

EMP = {"id": "e1", "fullName": "Juan Perez", "cedula": "40212345678",
       "idNumber": "40212345678", "hireDate": "2022-01-10"}

MOCK_USER_PROFILE = {
    "uid": "u1",
    "email": "rh@test.com",
    "name": "RH",
    "role": "owner",
    "ownerUID": "u1",
    "status": "active",
    "permissions": {"canHR": True},
}

MOCK_COMPANY = {
    "companyRNC": "132-10912-2",
    "companyName": "Test Co",
    "configured": True,
    "posEnabled": True,
    "productionEnabled": True,
    "sandboxEnabled": True,
    "sandboxIndefinite": True,
    "planId": "plan123",
}

DB_PATCHES = (
    patch("app.services.db_service.DatabaseService.get_user_profile", return_value=MOCK_USER_PROFILE),
    patch("app.services.db_service.DatabaseService.get_associated_companies",
          return_value=[{"ownerUID": "u1", "companyName": "Test Co", "role": "owner"}]),
    patch("app.services.db_service.DatabaseService.get_company_profile", return_value=MOCK_COMPANY),
    patch("app.services.db_service.DatabaseService.get_company", return_value=None),
    patch("app.services.db_service.DatabaseService.get_membership",
          return_value={"status": "active"}),
    patch("app.services.db_service.DatabaseService.get_plan",
          return_value={"modules": {"nomina": {"enabled": True}}}),
    patch("app.services.db_service.DatabaseService.get_company_context",
          return_value={"permissions": {}}),
    patch("app.services.db_service.DatabaseService.get_projects", return_value=[]),
)


def _login(client):
    with client.session_transaction() as sess:
        sess["user"] = {"uid": "u1", "email": "rh@test.com", "role": "owner", "ownerUID": "u1"}
        sess["selected_owner_uid"] = "u1"
        sess["selected_company_id"] = "c1"
        sess["is_sandbox_mode"] = True


def _wait_job(client, job_id, timeout=15):
    status = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/rrhh/vacations/import/status/{job_id}").get_json()
        if status.get("status") in ("completed", "failed"):
            return status
        time.sleep(0.1)
    return status


def test_full_import_flow(client, tmp_path):
    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        hr = stack.enter_context(patch("app.web.rrhh.vacation_import.hr"))
        stack.enter_context(patch("app.web.rrhh.vacation_import.log_action"))
        stack.enter_context(patch("app.web.rrhh.vacation_import.TEMP_IMPORT_DIR", str(tmp_path)))
        stack.enter_context(patch("app.web.rrhh.vacation_import.JOB_DIR", str(tmp_path / "jobs")))
        hr.get_employees.return_value = [EMP]
        hr.get_vacation_requests.return_value = []
        hr.save_vacation_request.return_value = None

        _login(client)

        resp = client.post(
            "/rrhh/vacations/import/upload",
            data={"file": (io.BytesIO(CSV_FULL.encode("utf-8-sig")), "historial.csv")},
            content_type="multipart/form-data",
        )
        up = resp.get_json()
        assert resp.status_code == 200
        assert up["success"] is True
        assert up["row_count"] == 1
        assert up["headers"][0] == "*employeeCedula"

        resp2 = client.post("/rrhh/vacations/import/process", data={
            "temp_filename": up["temp_filename"],
            "map_employeeCedula": "0",
            "map_startDate": "1",
            "map_endDate": "2",
            "map_days": "3",
            "map_notes": "4",
        })
        job = resp2.get_json()
        assert job["success"] is True

        status = _wait_job(client, job["job_id"])
        assert status["status"] == "completed"
        assert status["imported"] == 1
        assert status["skipped"] == 0
        assert status["errors"] == []

        doc = hr.save_vacation_request.call_args[0][2]
        assert doc["employeeId"] == "e1"
        assert doc["employeeName"] == "Juan Perez"
        assert doc["startDate"] == "2026-03-02"
        assert doc["endDate"] == "2026-03-13"
        assert doc["days"] == 10
        assert doc["status"] == "aprobada"
        assert doc["source"] == "masivo"
        assert doc["approvedBy"] == "rh@test.com"
        assert doc["remainingDaysBefore"] >= 0
        assert doc["notes"] == "Migrado del sistema anterior"


def test_import_computes_business_days_and_dedups(client, tmp_path):
    csv_no_days = ("*employeeCedula,*startDate,*endDate\n"
                   "40212345678,02/03/2026,13/03/2026\n")

    existing = [{"employeeId": "e1", "startDate": "2025-01-06", "days": 5, "status": "aprobada"}]
    saved_docs = []

    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        hr = stack.enter_context(patch("app.web.rrhh.vacation_import.hr"))
        stack.enter_context(patch("app.web.rrhh.vacation_import.log_action"))
        stack.enter_context(patch("app.web.rrhh.vacation_import.TEMP_IMPORT_DIR", str(tmp_path)))
        stack.enter_context(patch("app.web.rrhh.vacation_import.JOB_DIR", str(tmp_path / "jobs")))
        hr.get_employees.return_value = [EMP]
        hr.get_vacation_requests.return_value = existing
        hr.save_vacation_request.side_effect = lambda cid, rid, data, sandbox=True: saved_docs.append(data)

        _login(client)

        up = client.post(
            "/rrhh/vacations/import/upload",
            data={"file": (io.BytesIO(csv_no_days.encode("utf-8-sig")), "historial.csv")},
            content_type="multipart/form-data",
        ).get_json()
        assert up["success"] is True

        job = client.post("/rrhh/vacations/import/process", data={
            "temp_filename": up["temp_filename"],
            "map_employeeCedula": "0",
            "map_startDate": "1",
            "map_endDate": "2",
        }).get_json()

        status = _wait_job(client, job["job_id"])
        assert status["status"] == "completed"
        assert status["imported"] == 1
        assert saved_docs[0]["days"] == 10  # lun-vie entre 02/03 y 13/03

        # Re-ejecutar el mismo archivo: debe omitirse por duplicado
        hr.get_vacation_requests.return_value = existing + [saved_docs[0]]
        up2 = client.post(
            "/rrhh/vacations/import/upload",
            data={"file": (io.BytesIO(csv_no_days.encode("utf-8-sig")), "historial.csv")},
            content_type="multipart/form-data",
        ).get_json()
        job2 = client.post("/rrhh/vacations/import/process", data={
            "temp_filename": up2["temp_filename"],
            "map_employeeCedula": "0",
            "map_startDate": "1",
            "map_endDate": "2",
        }).get_json()
        status2 = _wait_job(client, job2["job_id"])
        assert status2["status"] == "completed"
        assert status2["imported"] == 0
        assert status2["skipped"] == 1
        assert len(saved_docs) == 1
        assert any("Ya existe una solicitud" in e["reason"] for e in status2["errors"])


def test_import_rejects_unknown_employee(client, tmp_path):
    csv_unknown = ("*employeeCedula,*startDate,*endDate\n"
                   "99999999999,02/03/2026,13/03/2026\n")

    with ExitStack() as stack:
        for p in DB_PATCHES:
            stack.enter_context(p)
        hr = stack.enter_context(patch("app.web.rrhh.vacation_import.hr"))
        stack.enter_context(patch("app.web.rrhh.vacation_import.log_action"))
        stack.enter_context(patch("app.web.rrhh.vacation_import.TEMP_IMPORT_DIR", str(tmp_path)))
        stack.enter_context(patch("app.web.rrhh.vacation_import.JOB_DIR", str(tmp_path / "jobs")))
        hr.get_employees.return_value = [EMP]
        hr.get_vacation_requests.return_value = []

        _login(client)
        up = client.post(
            "/rrhh/vacations/import/upload",
            data={"file": (io.BytesIO(csv_unknown.encode("utf-8-sig")), "historial.csv")},
            content_type="multipart/form-data",
        ).get_json()
        job = client.post("/rrhh/vacations/import/process", data={
            "temp_filename": up["temp_filename"],
            "map_employeeCedula": "0",
            "map_startDate": "1",
            "map_endDate": "2",
        }).get_json()

        status = _wait_job(client, job["job_id"])
        assert status["status"] == "completed"
        assert status["imported"] == 0
        assert status["skipped"] == 1
        assert any("No se encontro empleado" in e["reason"] for e in status["errors"])
        hr.save_vacation_request.assert_not_called()
