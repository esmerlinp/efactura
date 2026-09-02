from unittest.mock import MagicMock, patch


def _request(period_key="2026-09"):
    return type("Req", (), {
        "form": {
            "payrollGroupId": "group-1",
            "period_key": period_key,
            "periodSubType": "regular",
            "notes": "",
        },
    })()


def _periods(_frequency, _year):
    return [{
        "key": "2026-09",
        "label": "Septiembre 2026",
        "type": "mensual",
        "start": "2026-09-01",
        "end": "2026-09-30",
    }]


def test_payroll_create_uses_limited_employee_check():
    from app.services import hr_data_service as hr
    from app.web.rrhh import payroll_process as pp

    with patch.object(pp, "request", _request()), \
         patch.object(pp, "_login_required", return_value=False), \
         patch.object(pp, "_get_owner_uid_and_sandbox", return_value=("u1", True, "co-1")), \
         patch.object(pp, "_generate_periods", side_effect=_periods), \
         patch.object(pp, "url_for", side_effect=lambda endpoint, **kwargs: f"/{endpoint}"), \
         patch.object(pp, "redirect", side_effect=lambda location: location), \
         patch.object(pp, "flash"), \
         patch.object(pp, "session", {"user": {"email": "user@example.com"}}), \
         patch.object(hr, "get_payroll_group", return_value={"id": "group-1", "frequency": "mensual"}), \
         patch.object(hr, "has_active_employee_in_payroll_group", return_value=True) as active_check, \
         patch.object(hr, "get_payroll_period_by_key_and_group", return_value=None), \
         patch.object(hr, "save_payroll_period", return_value=True), \
         patch.object(hr, "get_employees") as get_employees:
        result = pp.payroll_create()

    assert result == "/web_rrhh.payroll_view"
    active_check.assert_called_once_with("co-1", "group-1", sandbox=True)
    get_employees.assert_not_called()


def test_payroll_create_handles_validation_service_failure():
    from app.services import hr_data_service as hr
    from app.web.rrhh import payroll_process as pp

    flash = MagicMock()
    with patch.object(pp, "request", _request()), \
         patch.object(pp, "_login_required", return_value=False), \
         patch.object(pp, "_get_owner_uid_and_sandbox", return_value=("u1", True, "co-1")), \
         patch.object(pp, "_generate_periods", side_effect=_periods), \
         patch.object(pp, "url_for", side_effect=lambda endpoint, **kwargs: f"/{endpoint}"), \
         patch.object(pp, "redirect", side_effect=lambda location: location), \
         patch.object(pp, "flash", flash), \
         patch.object(hr, "get_payroll_group", return_value={"id": "group-1", "frequency": "mensual"}), \
         patch.object(hr, "get_payroll_period_by_key_and_group", return_value=None), \
         patch.object(hr, "has_active_employee_in_payroll_group", side_effect=RuntimeError("Firestore unavailable")), \
         patch.object(hr, "save_payroll_period") as save_period:
        result = pp.payroll_create()

    assert result == "/web_rrhh.payroll_new"
    flash.assert_called_with(
        "No se pudo validar la nómina. Verifica la conexión e inténtalo nuevamente.",
        "error",
    )
    save_period.assert_not_called()


def test_has_active_employee_in_payroll_group_limits_query():
    from app.services import hr_data_service as hr

    query = MagicMock()
    query.where.return_value = query
    query.limit.return_value = query
    query.get.return_value = [MagicMock()]
    firestore = MagicMock()
    firestore.collection.return_value = query

    with patch.object(hr, "firebase_initialized", True), \
         patch.object(hr, "db_firestore", firestore):
        assert hr.has_active_employee_in_payroll_group("co-1", "group-1") is True

    assert query.where.call_count == 2
    query.limit.assert_called_once_with(1)


def test_payroll_new_redirects_existing_calculated_period_to_detail():
    from app.services import hr_data_service as hr
    from app.web.rrhh import payroll_process as pp

    existing = {
        "id": "period-1",
        "periodKey": "2026-09",
        "payrollGroupId": "group-1",
        "status": "calculada",
    }
    request = type("Req", (), {
        "method": "POST",
        "args": {"group": "group-1"},
        "form": {
            "payrollGroupId": "group-1",
            "period_key": "2026-09",
            "periodSubType": "regular",
        },
    })()

    with patch.object(pp, "request", request), \
         patch.object(pp, "_login_required", return_value=False), \
         patch.object(pp, "_get_owner_uid_and_sandbox", return_value=("u1", True, "co-1")), \
         patch.object(pp, "_editor_tabs") as editor_tabs, \
         patch.object(pp, "url_for", side_effect=lambda endpoint, **kwargs: f"/{endpoint}/{kwargs.get('period_id', '')}"), \
         patch.object(pp, "redirect", side_effect=lambda location: location), \
         patch.object(pp, "flash"), \
         patch.object(hr, "get_payroll_period_by_key_and_group", return_value=existing), \
         patch.object(hr, "get_employees") as get_employees, \
         patch.object(hr, "get_payroll_groups") as get_groups:
        result = pp.payroll_new()

    assert result == "/web_rrhh.payroll_view/period-1"
    editor_tabs.assert_not_called()
    get_employees.assert_not_called()
    get_groups.assert_not_called()


def test_payroll_create_opens_existing_before_group_and_employee_queries():
    from app.services import hr_data_service as hr
    from app.web.rrhh import payroll_process as pp

    existing = {"id": "period-1", "status": "borrador"}
    with patch.object(pp, "request", _request()), \
         patch.object(pp, "_login_required", return_value=False), \
         patch.object(pp, "_get_owner_uid_and_sandbox", return_value=("u1", True, "co-1")), \
         patch.object(pp, "url_for", side_effect=lambda endpoint, **kwargs: f"/{endpoint}/{kwargs.get('period_id', '')}"), \
         patch.object(pp, "redirect", side_effect=lambda location: location), \
         patch.object(pp, "flash"), \
         patch.object(hr, "get_payroll_period_by_key_and_group", return_value=existing), \
         patch.object(hr, "get_payroll_group") as get_group, \
         patch.object(hr, "has_active_employee_in_payroll_group") as active_check, \
         patch.object(hr, "save_payroll_period") as save_period:
        result = pp.payroll_create()

    assert result == "/web_rrhh.payroll_view/period-1"
    get_group.assert_not_called()
    active_check.assert_not_called()
    save_period.assert_not_called()
