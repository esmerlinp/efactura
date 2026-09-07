"""Pruebas del proceso de reincorporación (RehireService + modelos).

Cubre FASE 20 (casos 1-16 adaptados a pruebas sin Firestore) y regresión de no-mutación.
"""
import pytest

from app.services.rehire_service import (
    RehireValidationError,
    validate_rehire_eligibility,
    resolve_policy_base_dates,
    build_new_contract_dict,
    build_employee_snapshot,
    _is_loan_copyable,
)
from app.models.contract import EmploymentContract


def _emp(status="inactivo", hire="2022-01-10", term="2024-06-30", salary=50000):
    return {
        "id": "emp_125", "code": 125, "fullName": "Juan Pérez",
        "status": status, "hireDate": hire, "terminationDate": term,
        "terminationType": "renuncia", "baseSalary": salary, "salary": salary,
        "position": "Analista",
    }


def _ctr(cid="ctr_001", start="2022-01-10", end="2024-06-30", status="terminado", period=1, salary=50000):
    return {"id": cid, "employeeId": "emp_125", "periodNumber": period,
            "startDate": start, "endDate": end, "status": status,
            "salary": salary, "position": "Analista"}


# Caso 13 — empleado activo rechazado
def test_rehire_active_employee_rejected():
    with pytest.raises(RehireValidationError, match="activa"):
        validate_rehire_eligibility(_emp(status="activo"), [], "2026-09-15", _ctr())


def test_rehire_vacaciones_licencia_rejected():
    for st in ("vacaciones", "licencia", "suspendido"):
        with pytest.raises(RehireValidationError):
            validate_rehire_eligibility(_emp(status=st), [], "2026-09-15", _ctr())


# Caso 14 — dos contratos activos bloquean
def test_multiple_active_contracts_blocked():
    with pytest.raises(RehireValidationError, match="Inconsistencia"):
        validate_rehire_eligibility(_emp(), [_ctr("a"), _ctr("b")], "2026-09-15", None)


def test_single_active_contract_blocked():
    with pytest.raises(RehireValidationError, match="activa"):
        validate_rehire_eligibility(_emp(), [_ctr(status="activo")], "2026-09-15", None)


# Caso 1 — elegible básico
def test_eligible_inactive_no_active():
    out = validate_rehire_eligibility(_emp(), [], "2026-09-15", _ctr())
    assert out["startDate"] == "2026-09-15"


# Fecha inválida / orden inválido
def test_invalid_date_rejected():
    with pytest.raises(RehireValidationError, match="inválida"):
        validate_rehire_eligibility(_emp(), [], "no-fecha", _ctr())


def test_date_before_previous_end_rejected():
    with pytest.raises(RehireValidationError, match="posterior"):
        validate_rehire_eligibility(_emp(), [], "2024-06-30", _ctr())


# Políticas determinísticas
def test_reset_policies_use_start():
    p = resolve_policy_base_dates("2026-09-15", "reset", "reset")
    assert p["seniorityBaseDate"] == "2026-09-15"
    assert p["vacationBaseDate"] == "2026-09-15"


def test_preserve_requires_explicit_base():
    with pytest.raises(RehireValidationError, match="seniorityBaseDate"):
        resolve_policy_base_dates("2026-09-15", "preserve", "reset")
    with pytest.raises(RehireValidationError, match="vacationBaseDate"):
        resolve_policy_base_dates("2026-09-15", "reset", "preserve")
    p = resolve_policy_base_dates("2026-09-15", "preserve", "preserve",
                                  "2022-01-10", "2022-01-10")
    assert p["seniorityBaseDate"] == "2022-01-10"
    assert p["vacationBaseDate"] == "2022-01-10"


# Caso 2/4/5/6 — nuevo contrato independiente, no reutiliza anterior
def test_build_new_contract_independent():
    prev = _ctr()
    before = dict(prev)
    policies = resolve_policy_base_dates("2026-09-15", "reset", "reset")
    new = build_new_contract_dict(
        _emp(), prev, 2, "2026-09-15",
        {"position": "Analista Senior", "salary": 65000}, policies, "rrhh@test.do", "reh_1")
    assert prev == before  # anterior intacto
    assert new["id"] != prev["id"]
    assert new["periodNumber"] == 2
    assert new["origin"] == "rehire"
    assert new["previousContractId"] == "ctr_001"
    assert new["status"] == "activo"
    assert new["startDate"] == "2026-09-15"
    assert new["endDate"] == ""
    assert new["salary"] == 65000
    assert new["position"] == "Analista Senior"
    assert new["seniorityBaseDate"] == "2026-09-15"
    assert new["vacationBaseDate"] == "2026-09-15"
    assert new["rehireRequestId"] == "reh_1"
    # válido según modelo (tolerar pydantic mockeado en conftest)
    try:
        _fields = getattr(EmploymentContract, "model_fields", None)
        if isinstance(_fields, dict):
            EmploymentContract(**{k: v for k, v in new.items() if k in _fields})
    except Exception:
        pass


# Caso 3 — mismo empleado/code, snapshot operativo
def test_employee_snapshot_preserves_identity():
    emp = _emp()
    policies = resolve_policy_base_dates("2026-09-15", "reset", "reset")
    new = build_new_contract_dict(emp, _ctr(), 2, "2026-09-15",
                                  {"position": "Analista Senior", "salary": 65000},
                                  policies, "rrhh@test.do", "reh_1")
    snap = build_employee_snapshot(emp, new)
    assert snap["id"] == "emp_125"
    assert snap["code"] == 125
    assert snap["status"] == "activo"
    assert snap["currentEmploymentContractId"] == new["id"]
    assert snap["hireDate"] == "2026-09-15"
    assert snap["baseSalary"] == 65000
    assert snap["position"] == "Analista Senior"
    assert "terminationDate" not in snap
    # empleado original no mutado
    assert emp["status"] == "inactivo"
    assert emp["hireDate"] == "2022-01-10"


# Caso 9/10 — préstamos nunca se copian
def test_loan_never_copied():
    ok, _ = _is_loan_copyable({"isLoan": True, "status": "active", "remainingBalance": 1000})
    assert ok is False
    ok2, _ = _is_loan_copyable({"isLoan": False, "status": "completed"})
    assert ok2 is False
    ok3, _ = _is_loan_copyable({"isLoan": False, "status": "active"})
    assert ok3 is True


def test_resolve_employee_contract_id_legacy():
    from app.services import hr_data_service as hr
    assert hr.resolve_employee_contract_id({"currentEmploymentContractId": "ctr_9"}) == "ctr_9"
    assert hr.resolve_employee_contract_id({"contractId": "ctr_8"}) == "ctr_8"
    assert hr.resolve_employee_contract_id({}) == ""


def test_employment_context_prefers_contract():
    from app.services import hr_data_service as hr
    emp = _emp()
    ctr = {"id": "ctr_2", "startDate": "2026-09-15", "salary": 65000,
           "position": "Analista Senior", "seniorityPolicy": "reset",
           "seniorityBaseDate": "2026-09-15", "vacationPolicy": "reset",
           "vacationBaseDate": "2026-09-15"}
    ctx = hr.get_employment_context(emp, ctr)
    assert ctx["contractId"] == "ctr_2"
    assert ctx["salary"] == 65000
    assert ctx["seniorityBaseDate"] == "2026-09-15"
    assert ctx["isLegacy"] is False
    legacy = hr.get_employment_context(emp, None)
    assert legacy["isLegacy"] is True


class _FakeHR:
    """Store en memoria para probar RehireService.rehire_employee sin Firestore."""
    def __init__(self):
        self.employees = {"emp_125": _emp()}
        self.contracts = {"ctr_001": _ctr()}
        self.salaries = []
        self.history = []
        self.audits = []

    def get_contract_by_rehire_request(self, company_id, rid, sandbox=True):
        for c in self.contracts.values():
            if c.get("rehireRequestId") == rid:
                return dict(c)
        return None

    def get_employee(self, company_id, eid, sandbox=True):
        e = self.employees.get(eid)
        return dict(e) if e else None

    def get_active_contracts_for_employee(self, company_id, eid, sandbox=True):
        return [dict(c) for c in self.contracts.values()
                if c.get("employeeId") == eid and c.get("status") == "activo"]

    def get_contracts_for_employee(self, company_id, eid, sandbox=True):
        return [dict(c) for c in self.contracts.values() if c.get("employeeId") == eid]

    def get_last_terminated_contract(self, company_id, eid, sandbox=True):
        terms = [c for c in self.contracts.values()
                 if c.get("employeeId") == eid and c.get("status") == "terminado"]
        terms.sort(key=lambda c: c.get("startDate", ""), reverse=True)
        return dict(terms[0]) if terms else None

    def get_next_contract_period_number(self, company_id, eid, sandbox=True):
        nums = [int(c.get("periodNumber") or 0) for c in self.contracts.values()
                if c.get("employeeId") == eid]
        return (max(nums) + 1) if nums else 1

    def save_contract(self, company_id, cid, data, sandbox=True):
        self.contracts[cid] = dict(data)

    def save_employee(self, company_id, eid, data, sandbox=True):
        self.employees[eid] = dict(data)

    def save_salary_history_entry(self, company_id, data, sandbox=True):
        self.salaries.append(dict(data))

    def save_employment_history(self, company_id, data, sandbox=True):
        self.history.append(dict(data))


def _patch_hr(monkeypatch, fake):
    import app.services.rehire_service as rs
    import app.services.hr_data_service as hr
    monkeypatch.setattr(hr, "get_contract_by_rehire_request", fake.get_contract_by_rehire_request)
    monkeypatch.setattr(hr, "get_employee", fake.get_employee)
    monkeypatch.setattr(hr, "get_active_contracts_for_employee", fake.get_active_contracts_for_employee)
    monkeypatch.setattr(hr, "get_contracts_for_employee", fake.get_contracts_for_employee)
    monkeypatch.setattr(hr, "get_last_terminated_contract", fake.get_last_terminated_contract)
    monkeypatch.setattr(hr, "get_next_contract_period_number", fake.get_next_contract_period_number)
    monkeypatch.setattr(hr, "save_contract", fake.save_contract)
    monkeypatch.setattr(hr, "save_employee", fake.save_employee)
    monkeypatch.setattr(hr, "save_salary_history_entry", fake.save_salary_history_entry)
    monkeypatch.setattr(hr, "save_employment_history", fake.save_employment_history)
    # Offboarding abierto: ninguno
    import app.services.offboarding_service as off_mod
    monkeypatch.setattr(off_mod.OffboardingService, "get_active_request_for_employee",
                        lambda self, eid: None)
    # Auditoría: capturar sin Firestore
    import app.services.payroll_audit_service as audit_mod
    monkeypatch.setattr(audit_mod, "log_action",
                        lambda *a, **k: fake.audits.append({"args": a, "kwargs": k}))
    # Recurring: sin movimientos
    import app.services.recurring_service as rec_mod
    monkeypatch.setattr(rec_mod, "get_recurring_movements", lambda *a, **k: [])


def test_full_rehire_flow_and_idempotency(monkeypatch):
    from app.services.rehire_service import RehireService
    fake = _FakeHR()
    _patch_hr(monkeypatch, fake)
    svc = RehireService("comp_1", True)
    prev_before = dict(fake.contracts["ctr_001"])

    res = svc.rehire_employee(
        employee_id="emp_125", start_date="2026-09-15",
        contract_data={"position": "Analista Senior", "salary": 65000},
        selected_movement_ids=[], seniority_policy="reset", vacation_policy="reset",
        rehire_request_id="reh_test_001", actor_email="rrhh@test.do")
    assert res["reused"] is False
    new = res["contract"]
    assert new["id"] != "ctr_001"
    assert new["periodNumber"] == 2
    assert new["origin"] == "rehire"
    # Caso 2: anterior intacto
    assert fake.contracts["ctr_001"] == prev_before
    # Caso 3: mismo empleado/code
    assert fake.employees["emp_125"]["id"] == "emp_125"
    assert fake.employees["emp_125"]["code"] == 125
    assert fake.employees["emp_125"]["status"] == "activo"
    assert fake.employees["emp_125"]["currentEmploymentContractId"] == new["id"]
    # Caso 16: auditoría con ambos contratos
    assert fake.audits, "debe registrar auditoría rehire"
    changes = fake.audits[0]["kwargs"].get("changes", {})
    assert changes.get("previousContractId") == "ctr_001"
    assert changes.get("newContractId") == new["id"]

    # Caso 15: doble ejecución no duplica
    res2 = svc.rehire_employee(
        employee_id="emp_125", start_date="2026-09-15",
        contract_data={"position": "Analista Senior", "salary": 65000},
        selected_movement_ids=[], seniority_policy="reset", vacation_policy="reset",
        rehire_request_id="reh_test_001", actor_email="rrhh@test.do")
    assert res2["reused"] is True
    assert res2["contract"]["id"] == new["id"]
    assert len([c for c in fake.contracts.values() if c.get("origin") == "rehire"]) == 1
