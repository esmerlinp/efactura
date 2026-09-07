"""Pruebas de EmploymentContextService: resolución contractual y aislamiento.

Escenario base (sin Firestore, con hr simulado):
  Contrato 1: 2022-01-10 → 2024-06-30, terminado, RD$50,000
  Contrato 2: 2026-09-15 → activo, RD$65,000
"""
import pytest

from app.services.employment_context_service import (
    EmploymentContextError,
    build_context,
    filter_movements,
    filter_transactions,
    resolve_active,
    resolve_for_termination,
)


def _c1():
    return {"id": "ctr_001", "employeeId": "emp_125", "periodNumber": 1,
            "startDate": "2022-01-10", "endDate": "2024-06-30",
            "terminationDate": "2024-06-30", "status": "terminado",
            "salary": 50000.0, "position": "Analista",
            "seniorityPolicy": "reset", "seniorityBaseDate": "2022-01-10",
            "vacationPolicy": "reset", "vacationBaseDate": "2022-01-10"}


def _c2():
    return {"id": "ctr_002", "employeeId": "emp_125", "periodNumber": 2,
            "startDate": "2026-09-15", "endDate": "",
            "status": "activo", "salary": 65000.0, "position": "Analista Senior",
            "seniorityPolicy": "reset", "seniorityBaseDate": "2026-09-15",
            "vacationPolicy": "reset", "vacationBaseDate": "2026-09-15"}


def _emp():
    return {"id": "emp_125", "code": 125, "status": "activo",
            "hireDate": "2026-09-15", "baseSalary": 65000.0, "position": "Analista Senior"}


def _patch_contracts(monkeypatch, contracts):
    import app.services.employment_context_service as ecs
    import app.services.hr_data_service as hr

    def _all(company_id, employee_id, sandbox=True):
        return [dict(c) for c in contracts if c.get("employeeId") == employee_id]

    def _active(company_id, employee_id, sandbox=True):
        return [dict(c) for c in contracts
                if c.get("employeeId") == employee_id and c.get("status") == "activo"]

    monkeypatch.setattr(hr, "get_contracts_for_employee", _all)
    monkeypatch.setattr(hr, "get_active_contracts_for_employee", _active)
    return ecs


def _tx(tid, period_key, amount, contract_id="", status="applied"):
    return {"id": tid, "periodId": "p-" + period_key, "periodKey": period_key,
            "employeeId": "emp_125", "contractId": contract_id,
            "conceptCode": "SALARIO_BASE", "type": "earning", "amount": amount,
            "source": "payroll", "sourceId": "", "status": status,
            "conceptSnapshot": {"affectsTSS": True}}


class TestResolveForTermination:
    def test_exact_terminated_match(self, monkeypatch):
        ecs = _patch_contracts(monkeypatch, [_c1(), _c2()])
        out = ecs.resolve_for_termination("c", "emp_125", "2024-06-30")
        assert out["id"] == "ctr_001"

    def test_covering_active_contract(self, monkeypatch):
        ecs = _patch_contracts(monkeypatch, [_c1(), _c2()])
        out = ecs.resolve_for_termination("c", "emp_125", "2026-10-01")
        assert out["id"] == "ctr_002"

    def test_most_recent_past_when_no_cover(self, monkeypatch):
        ecs = _patch_contracts(monkeypatch, [_c1()])
        out = ecs.resolve_for_termination("c", "emp_125", "2025-01-15")
        assert out["id"] == "ctr_001"

    def test_no_contracts_returns_none(self, monkeypatch):
        ecs = _patch_contracts(monkeypatch, [])
        assert ecs.resolve_for_termination("c", "emp_125", "2024-06-30") is None

    def test_ambiguous_exact_raises(self, monkeypatch):
        dup = _c1()
        dup["id"] = "ctr_001b"
        ecs = _patch_contracts(monkeypatch, [_c1(), dup, _c2()])
        with pytest.raises(EmploymentContextError):
            ecs.resolve_for_termination("c", "emp_125", "2024-06-30")

    def test_invalid_date_raises(self, monkeypatch):
        ecs = _patch_contracts(monkeypatch, [_c1()])
        with pytest.raises(EmploymentContextError):
            ecs.resolve_for_termination("c", "emp_125", "no-fecha")


class TestResolveActive:
    def test_single_active(self, monkeypatch):
        ecs = _patch_contracts(monkeypatch, [_c1(), _c2()])
        assert ecs.resolve_active("c", "emp_125")["id"] == "ctr_002"

    def test_none_when_no_active(self, monkeypatch):
        ecs = _patch_contracts(monkeypatch, [_c1()])
        assert ecs.resolve_active("c", "emp_125") is None

    def test_multiple_active_raises(self, monkeypatch):
        other = _c2()
        other["id"] = "ctr_003"
        ecs = _patch_contracts(monkeypatch, [_c2(), other])
        with pytest.raises(EmploymentContextError):
            ecs.resolve_active("c", "emp_125")


class TestFilterTransactions:
    def _ctx2(self):
        return build_context(_emp(), _c2())

    def test_new_contract_excludes_old_period(self):
        txs = [_tx("a", "2024-05-M", 50000.0, "ctr_001"),
               _tx("b", "2026-09-M", 65000.0, "ctr_002"),
               _tx("c", "2026-10-M", 65000.0, "ctr_002")]
        out = filter_transactions(txs, self._ctx2())
        assert {t["id"] for t in out} == {"b", "c"}

    def test_old_contract_excludes_new_period(self):
        ctx = build_context(_emp(), _c1())
        txs = [_tx("a", "2024-05-M", 50000.0, "ctr_001"),
               _tx("b", "2026-09-M", 65000.0, "ctr_002")]
        out = filter_transactions(txs, ctx)
        assert [t["id"] for t in out] == ["a"]

    def test_legacy_tx_inside_range_included(self):
        txs = [_tx("old", "2024-05-M", 50000.0, ""),
               _tx("new", "2026-09-M", 65000.0, "")]
        out = filter_transactions(txs, self._ctx2())
        assert [t["id"] for t in out] == ["new"]

    def test_legacy_context_keeps_everything(self):
        ctx = build_context(_emp(), None)
        assert ctx["isLegacy"] is True
        txs = [_tx("a", "2024-05-M", 50000.0, "ctr_001"),
               _tx("b", "2026-09-M", 65000.0, "")]
        assert len(filter_transactions(txs, ctx)) == 2


class TestFilterMovements:
    def test_scope_by_contract(self):
        ctx = build_context(_emp(), _c2())
        movs = [{"id": "m1", "contractId": "ctr_001"},
                {"id": "m2", "contractId": "ctr_002"},
                {"id": "m3", "contractId": ""}]
        out = filter_movements(movs, ctx)
        assert {m["id"] for m in out} == {"m2", "m3"}

    def test_legacy_keeps_all(self):
        ctx = build_context(_emp(), None)
        movs = [{"id": "m1", "contractId": "ctr_001"}]
        assert filter_movements(movs, ctx) == movs
