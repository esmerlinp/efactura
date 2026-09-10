import app.services.mass_action_service as service


def test_resolve_employee_payload_uses_row_override():
    payload = {
        "amount": 25000,
        "effectiveDate": "2026-09-01",
        "perEmployee": {"emp-1": {"amount": 31000}},
    }

    resolved = service.resolve_employee_payload("salary_change", payload, "emp-1")
    other = service.resolve_employee_payload("salary_change", payload, "emp-2")

    assert resolved["amount"] == 31000
    assert other["amount"] == 25000


def test_resolve_employee_payload_supports_all_action_fields():
    payload = {
        "newPosition": "Analista",
        "perEmployee": {
            "emp-1": {"newPosition": "Coordinador", "newDepartment": "Finanzas"},
        },
    }

    resolved = service.resolve_employee_payload("position_change", payload, "emp-1")

    assert resolved["newPosition"] == "Coordinador"
    assert resolved["newDepartment"] == "Finanzas"
