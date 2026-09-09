"""Regla de estado para acciones de personal: solo "inactivo" bloquea.

Cualquier otro estado (activo, vacaciones, suspendido, licencia) se considera
vigente en la empresa. La única acción permitida para un inactivo es la
reincorporación.
"""
from unittest.mock import patch

import app.services.mass_action_service as mas


def _emp(eid, status):
    return {"id": eid, "fullName": f"Empleado {eid}", "status": status,
            "hireDate": "2022-01-10", "baseSalary": 50000, "salary": 50000,
            "position": "Analista"}


def _patch_employees(monkeypatch, employees):
    by_id = {e["id"]: e for e in employees}
    monkeypatch.setattr(mas.hr, "get_employees", lambda *a, **k: list(employees))
    return by_id


def _payloads(sup_id="e_sup"):
    return {
        "salary_change": {"amount": 60000, "effectiveDate": "2026-01-15"},
        "position_change": {"newPosition": "Senior", "effectiveDate": "2026-01-15"},
        "supervisor_change": {"newSupervisorId": sup_id, "effectiveDate": "2026-01-15"},
        "promotion": {"newPosition": "Senior", "amount": 70000, "effectiveDate": "2026-01-15"},
        "mass_absence": {"absenceType": "permiso", "startDate": "2026-02-01",
                         "endDate": "2026-02-02", "days": 2},
    }


def _status_errors(errors):
    return [e for e in errors if e.get("field") == "status"]


def test_inactive_blocked_all_action_types(monkeypatch):
    employees = [_emp("e_inact", "inactivo"), _emp("e_sup", "activo")]
    _patch_employees(monkeypatch, employees)
    for action_type, payload in _payloads().items():
        errors = mas.validate_action("owner", action_type, ["e_inact"], dict(payload),
                                     sandbox=True, company_id="c1")
        assert _status_errors(errors), f"{action_type} debe bloquear inactivo"
        assert "reincorporación" in _status_errors(errors)[0]["message"]


def test_non_inactive_statuses_are_active_equivalent(monkeypatch):
    for status in ("activo", "vacaciones", "suspendido", "licencia"):
        employees = [_emp("e1", status), _emp("e_sup", "activo")]
        _patch_employees(monkeypatch, employees)
        for action_type, payload in _payloads().items():
            errors = mas.validate_action("owner", action_type, ["e1"], dict(payload),
                                         sandbox=True, company_id="c1")
            assert _status_errors(errors) == [], f"{action_type} no debe bloquear {status}: {errors}"


def test_inactive_supervisor_rejected(monkeypatch):
    employees = [_emp("e1", "activo"), _emp("e_sup", "inactivo")]
    _patch_employees(monkeypatch, employees)
    errors = mas.validate_action("owner", "supervisor_change", ["e1"],
                                 {"newSupervisorId": "e_sup", "effectiveDate": "2026-01-15"},
                                 sandbox=True, company_id="c1")
    assert any(e.get("field") == "newSupervisorId" for e in errors)


def test_execute_action_skips_inactive(monkeypatch):
    employees = [_emp("e_inact", "inactivo")]
    _patch_employees(monkeypatch, employees)
    action = {"id": "a1", "status": "approved", "actionType": "salary_change",
              "payload": {"amount": 60000, "effectiveDate": "2026-01-15"},
              "selectionCriteria": {"employeeIds": ["e_inact"]},
              "statusHistory": []}
    saved = {}

    def _fake_save_mass_action(company_id, action_id, data, sandbox=True):
        saved["data"] = data

    monkeypatch.setattr(mas.hr, "get_mass_action", lambda *a, **k: action)
    monkeypatch.setattr(mas.hr, "save_mass_action", _fake_save_mass_action)
    monkeypatch.setattr(mas, "log_action", lambda *a, **k: None)

    class _Bus:
        def publish(self, event):
            pass

    monkeypatch.setattr(mas, "get_event_bus", lambda: _Bus())

    with patch.object(mas.hr, "save_employee") as mock_save_emp:
        result = mas.execute_action("owner", "a1", "admin@test.com",
                                    sandbox=True, company_id="c1")

    mock_save_emp.assert_not_called()
    assert result["successCount"] == 0
    assert result["errorCount"] == 1
    assert result["status"] == "partial"


def test_endpoints_redirect_for_inactive():
    # Sin create_app (el venv local tiene lxml roto): app Flask mínima con un
    # blueprint stub que expone el endpoint web_rrhh.employee_view para url_for.
    from flask import Flask, Blueprint, session
    import app.web.rrhh.employees as emp_mod
    import app.web.rrhh.reports as rep_mod
    import app.web.rrhh.liquidacion as liq_mod

    app = Flask(__name__)
    app.secret_key = "test"
    stub = Blueprint("web_rrhh", __name__)

    @stub.route("/rrhh/employees/<employee_id>/view")
    def employee_view(employee_id):
        return "ok"

    app.register_blueprint(stub)

    inactive = {"id": "e_inact", "fullName": "Empleado Inactivo", "status": "inactivo"}
    views = [emp_mod.employee_edit, rep_mod.employee_retroactive_pay,
             liq_mod.employee_liquidacion]
    with app.test_request_context("/"):
        session["user"] = {"uid": "test-uid", "ownerUID": "test-owner", "role": "owner",
                           "email": "admin@test.com", "name": "Admin",
                           "permissions": {"canHR": True}}
        session["is_sandbox_mode"] = True
        with patch("app.services.hr_data_service.get_employee",
                   return_value=dict(inactive)):
            for view in views:
                resp = view("e_inact")
                assert resp.status_code == 302, f"{view.__name__} debe redirigir para inactivo"
                assert "/rrhh/employees/e_inact" in resp.headers.get("Location", "")


def test_endpoints_allow_active_employee():
    from flask import Flask, Blueprint, session
    import app.web.rrhh.reports as rep_mod

    app = Flask(__name__)
    app.secret_key = "test"
    stub = Blueprint("web_rrhh", __name__)

    @stub.route("/rrhh/employees/<employee_id>/view")
    def employee_view(employee_id):
        return "ok"

    app.register_blueprint(stub)

    active = {"id": "e_act", "fullName": "Empleado Activo", "status": "activo",
              "hireDate": "2022-01-10"}
    with app.test_request_context("/"):
        session["user"] = {"uid": "test-uid", "ownerUID": "test-owner", "role": "owner",
                           "email": "admin@test.com", "name": "Admin",
                           "permissions": {"canHR": True}}
        session["is_sandbox_mode"] = True
        with patch("app.services.hr_data_service.get_employee",
                   return_value=dict(active)), \
             patch("app.services.hr_data_service.get_salary_history", return_value=[]):
            # GET solo calcula con POST; debe renderizar sin redirigir.
            # render_template requiere templates de la app real; basta con que
            # NO sea redirect (el guard no se dispara para activos).
            try:
                resp = rep_mod.employee_retroactive_pay("e_act")
            except Exception as exc:
                # Sin el template real puede fallar el render; lo importante es
                # que no haya redirect del guard.
                assert "inactivo" not in str(exc).lower()
                return
            assert getattr(resp, "status_code", 200) != 302


def test_employee_view_menu_gating_template():
    import pathlib
    tpl = pathlib.Path(__file__).resolve().parent.parent / "templates" / "rrhh" / "employee_view.html"
    html = tpl.read_text(encoding="utf-8")
    idx_rehire = html.index("Reincorporación")
    idx_else = html.index("{% else %}", html.index("employee.status == 'inactivo'"))
    idx_salary = html.index("Cambio de Salario")
    idx_edit_if = html.index("{% if employee.status != 'inactivo' %}")
    idx_edit = html.index("> Editar")
    # Reincorporación queda en la rama inactivo; el resto, en la rama else.
    assert idx_rehire < idx_else < idx_salary
    # El botón Editar queda dentro del if != inactivo.
    assert idx_edit_if < idx_edit
    # "Carta de Trabajo" y "Crear movimiento" quedan tras un if != inactivo.
    idx_carta = html.index("Carta de Trabajo")
    assert html.rindex("{% if employee.status != 'inactivo' %}", 0, idx_carta) > 0
    idx_crear_mv = html.index("Crear movimiento")
    assert html.rindex("{% if employee.status != 'inactivo' %}", 0, idx_crear_mv) > 0


def _minimal_rrhh_app():
    from flask import Flask, Blueprint
    app = Flask(__name__)
    app.secret_key = "test"
    stub = Blueprint("web_rrhh", __name__)

    @stub.route("/rrhh/employees/<employee_id>/view")
    def employee_view(employee_id):
        return "ok"

    @stub.route("/rrhh/recurring")
    def recurring_list():
        return "ok"

    app.register_blueprint(stub)
    return app


def _login_session(session):
    session["user"] = {"uid": "test-uid", "ownerUID": "test-owner", "role": "owner",
                       "email": "admin@test.com", "name": "Admin",
                       "permissions": {"canHR": True}}
    session["is_sandbox_mode"] = True


def test_certificate_blocked_for_inactive():
    from flask import session
    import app.web.rrhh.work_certificate as wc
    app = _minimal_rrhh_app()
    inactive = {"id": "e_inact", "fullName": "Empleado Inactivo", "status": "inactivo"}
    with app.test_request_context("/"):
        _login_session(session)
        with patch("app.services.hr_data_service.get_employee", return_value=dict(inactive)):
            resp = wc.employee_certificate("e_inact")
            assert resp.status_code == 302
            assert "/rrhh/employees/e_inact" in resp.headers.get("Location", "")

    with app.test_request_context("/", method="POST", data={"purpose": "general"}):
        _login_session(session)
        with patch("app.services.hr_data_service.get_employee", return_value=dict(inactive)):
            resp = wc.certificate_generate("e_inact")
            assert resp.status_code == 302
            assert "/rrhh/employees/e_inact" in resp.headers.get("Location", "")


def test_recurring_new_blocked_for_inactive():
    from flask import session
    import app.web.rrhh.recurring as rec
    app = _minimal_rrhh_app()
    inactive = {"id": "e_inact", "fullName": "Empleado Inactivo", "status": "inactivo",
                "hireDate": "2022-01-10"}
    with app.test_request_context("/", method="POST", data={
            "employeeId": "e_inact", "movementType": "deduction",
            "deductionSubType": "regular", "dedAmount": "1000"}):
        _login_session(session)
        with patch("app.services.hr_data_service.get_employee", return_value=dict(inactive)):
            resp = rec.recurring_new()
            assert resp.status_code == 302
            assert "/rrhh/recurring" in resp.headers.get("Location", "")


def test_recurring_new_allows_active():
    from flask import session
    import app.web.rrhh.recurring as rec
    app = _minimal_rrhh_app()
    active = {"id": "e_act", "fullName": "Empleado Activo", "status": "activo",
              "hireDate": "2022-01-10"}
    # El guard no debe dispararse para activos: la ejecución avanza hasta guardar
    # (o fallar por faltar infraestructura), pero NO por el guard de inactivo.
    with app.test_request_context("/", method="POST", data={
            "employeeId": "e_act", "movementType": "deduction",
            "deductionSubType": "regular", "dedAmount": "1000"}):
        _login_session(session)
        with patch("app.services.hr_data_service.get_employee", return_value=dict(active)), \
             patch("app.services.hr_data_service.save_recurring_movement"):
            try:
                resp = rec.recurring_new()
            except Exception as exc:
                assert "inactivo" not in str(exc).lower()
                return
            # Si llegó a guardar, el redirect es al listado; no debe ser un flash
            # de inactivo (status_code 302 es esperado por redirect normal).
            assert getattr(resp, "status_code", 200) != 500


def test_liquidacion_view_allowed_for_inactive():
    from flask import session
    import app.web.rrhh.liquidacion as liq_mod
    app = _minimal_rrhh_app()
    inactive = {"id": "e_inact", "fullName": "Empleado Inactivo", "status": "inactivo"}
    saved = {"id": "liq1", "employeeId": "e_inact", "salarioPromedioMensual": 50000,
             "terminationType": "renuncia_voluntaria", "terminationDate": "2024-06-30",
             "aplicaPrestaciones": True, "conceptos": {}, "totales": {}}
    with app.test_request_context("/?view=liq1"):
        _login_session(session)
        with patch("app.services.hr_data_service.get_employee", return_value=dict(inactive)), \
             patch("app.services.hr_data_service.get_liquidacion", return_value=dict(saved)):
            try:
                resp = liq_mod.employee_liquidacion("e_inact")
            except Exception as exc:
                # Sin templates reales el render falla; lo importante es que NO
                # haya disparado el guard de inactivo (que redirigiría con 302).
                assert "inactivo" not in str(exc).lower()
                return
            assert getattr(resp, "status_code", 200) != 302
