# tests/test_attendance_import.py
import io
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from app.web.rrhh.attendance_import import (
    ATTENDANCE_CSV_HEADERS,
    _get_delimiter,
    _normalize_date,
    _normalize_status,
    _resolve_employee,
    _map_headers,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers puros
# ─────────────────────────────────────────────────────────────────────────────

def test_template_headers():
    assert ATTENDANCE_CSV_HEADERS == ["empleadoCedula", "fecha", "estado", "entrada", "salida", "notas"]


def test_get_delimiter():
    assert _get_delimiter("cedula,fecha,estado") == ","
    assert _get_delimiter("cedula;fecha;estado") == ";"
    assert _get_delimiter("cedula\tfecha\testado") == "\t"
    assert _get_delimiter("cedula") == ","


def test_normalize_date():
    assert _normalize_date("2026-03-02") == "2026-03-02"
    assert _normalize_date("02/03/2026") == "2026-03-02"
    assert _normalize_date("02-03-2026") == "2026-03-02"
    assert _normalize_date("02/03/26") == "2026-03-02"
    assert _normalize_date("2026-03-02 00:00:00") == "2026-03-02"
    assert _normalize_date("") is None
    assert _normalize_date("hola") is None


def test_normalize_status():
    assert _normalize_status("presente") == "presente"
    assert _normalize_status("P") == "presente"
    assert _normalize_status("ausente") == "ausente"
    assert _normalize_status("tardia") == "tarde"
    assert _normalize_status("T") == "tarde"
    assert _normalize_status("permiso") == "permiso"
    assert _normalize_status("pe") == "permiso"
    assert _normalize_status("xx") is None
    assert _normalize_status("") is None


def test_resolve_employee_by_id():
    emp = {"id": "emp-1", "fullName": "Juan Perez", "cedula": "40212345678"}
    assert _resolve_employee("emp-1", {"emp-1": emp}, {}, []) == emp


def test_resolve_employee_by_cedula():
    emp = {"id": "emp-1", "fullName": "Juan Perez", "cedula": "402-1234567-8"}
    assert _resolve_employee("402-1234567-8", {}, {"40212345678": emp}, []) == emp


def test_resolve_employee_by_name():
    emp = {"id": "emp-1", "fullName": "Juan Perez"}
    assert _resolve_employee("juan perez", {}, {}, [emp]) == emp


def test_resolve_employee_not_found():
    assert _resolve_employee("", {}, {}, []) is None
    assert _resolve_employee("99999999999", {}, {}, []) is None


def test_map_headers_by_name():
    mapping = _map_headers(["empleadoCedula", "fecha", "estado", "entrada", "salida", "notas"])
    assert mapping == {f: i for i, f in enumerate(ATTENDANCE_CSV_HEADERS)}


def test_map_headers_synonyms_and_fallback():
    mapping = _map_headers(["CEDULA", "FECHA", "ESTADO"])
    assert mapping["empleadoCedula"] == 0
    assert mapping["fecha"] == 1
    assert mapping["estado"] == 2
    assert mapping["entrada"] is None
    assert mapping["salida"] is None
    assert mapping["notas"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Flujo de importación (síncrono)
# ─────────────────────────────────────────────────────────────────────────────

EMP = {"id": "e1", "fullName": "Juan Perez", "cedula": "40212345678", "idNumber": "40212345678"}

CSV_GOOD = ("empleadoCedula,fecha,estado,entrada,salida,notas\n"
            "40212345678,02/03/2026,presente,08:00,17:00,\n"
            "40212345678,2026-03-03,tardia,09:15,18:00,Tarde por trafico\n")


def _login(client):
    with client.session_transaction() as sess:
        sess["user"] = {"uid": "u1", "email": "rh@test.com", "role": "owner", "ownerUID": "u1"}
        sess["selected_owner_uid"] = "u1"
        sess["selected_company_id"] = "c1"
        sess["is_sandbox_mode"] = True


def test_import_flow(client):
    saved = []
    with ExitStack() as stack:
        hr = stack.enter_context(patch("app.web.rrhh.attendance_import.hr"))
        hr.get_employees.return_value = [EMP]
        hr.get_attendance_records.return_value = []
        hr.save_attendance_record.side_effect = lambda cid, rid, data, sandbox=True: saved.append((rid, data))

        _login(client)

        resp = client.post(
            "/rrhh/attendance/import",
            data={"file": (io.BytesIO(CSV_GOOD.encode("utf-8-sig")), "asistencia.csv")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200

        assert len(saved) == 2
        _, doc1 = saved[0]
        assert doc1["employeeId"] == "e1"
        assert doc1["date"] == "2026-03-02"
        assert doc1["status"] == "presente"
        assert doc1["checkIn"] == "08:00"
        assert doc1["checkOut"] == "17:00"

        _, doc2 = saved[1]
        assert doc2["date"] == "2026-03-03"
        assert doc2["status"] == "tarde"  # "tardia" normalizado


def test_import_upsert_reuses_existing_record(client):
    saved = []
    existing = [{"id": "existing-1", "employeeId": "e1", "date": "2026-03-02", "status": "presente"}]
    with ExitStack() as stack:
        hr = stack.enter_context(patch("app.web.rrhh.attendance_import.hr"))
        hr.get_employees.return_value = [EMP]
        hr.get_attendance_records.return_value = existing
        hr.save_attendance_record.side_effect = lambda cid, rid, data, sandbox=True: saved.append((rid, data))

        _login(client)
        client.post(
            "/rrhh/attendance/import",
            data={"file": (io.BytesIO(CSV_GOOD.encode("utf-8-sig")), "asistencia.csv")},
            content_type="multipart/form-data",
        )

        # La fila del 02/03 reutiliza el id existente; la del 03/03 crea uno nuevo
        rid1 = saved[0][0]
        rid2 = saved[1][0]
        assert rid1 == "existing-1"
        assert rid2 != "existing-1"
        assert len(saved) == 2


def test_import_skips_invalid_rows(client):
    csv_invalid = ("empleadoCedula,fecha,estado\n"
                   "99999999999,02/03/2026,presente\n"
                   "40212345678,fecha-mala,presente\n"
                   "40212345678,02/03/2026,volando\n")
    saved = []
    with ExitStack() as stack:
        hr = stack.enter_context(patch("app.web.rrhh.attendance_import.hr"))
        hr.get_employees.return_value = [EMP]
        hr.get_attendance_records.return_value = []
        hr.save_attendance_record.side_effect = lambda cid, rid, data, sandbox=True: saved.append((rid, data))

        _login(client)
        client.post(
            "/rrhh/attendance/import",
            data={"file": (io.BytesIO(csv_invalid.encode("utf-8-sig")), "asistencia.csv")},
            content_type="multipart/form-data",
        )

        assert len(saved) == 0
        hr.save_attendance_record.assert_not_called()


def test_import_template_download(client):
    _login(client)
    resp = client.get("/rrhh/attendance/import/template")
    assert resp.status_code == 200
    assert "plantilla_asistencia.csv" in resp.headers.get("Content-Disposition", "")
    body = resp.data.decode("utf-8-sig")
    assert "empleadoCedula" in body
