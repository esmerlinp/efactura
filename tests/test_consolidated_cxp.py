"""Pruebas de la proyección consolidada de Cuentas por Pagar (lectura)."""

from unittest.mock import patch

import pytest

from app.services.cxp_consolidation_service import (
    CxpConsolidationService,
    DOC_PENDING,
    STATUS_OVERDUE,
    STATUS_PAID,
    STATUS_PARTIAL,
    STATUS_PENDING,
    STATUS_VOIDED,
)
from app.services.db_service import DatabaseService


@pytest.fixture(autouse=True)
def _mock_before_request_reads(app):
    from flask import session as flask_session

    def _profile(uid):
        user = flask_session.get("user") or {}
        p = {
            "uid": uid or user.get("uid", ""),
            "ownerUID": user.get("ownerUID", "") or user.get("uid", ""),
            "email": user.get("email", ""),
            "role": user.get("role", "employee"),
            "permissions": dict(user.get("permissions") or {}),
        }
        cid = flask_session.get("selected_company_id") or user.get("company_id")
        if cid:
            p["default_company_id"] = cid
        return p

    def _membership(uid, company_id):
        user = flask_session.get("user") or {}
        return {
            "uid": uid,
            "company_id": company_id,
            "role": user.get("role", "employee"),
            "permissions": dict(user.get("permissions") or {}),
            "status": "active",
        }

    def _company(company_id):
        return {
            "id": company_id,
            "owner_uid": "o1",
            "status": "active",
            "plan_id": "plan-test",
            "plan_version": 1,
            "configured": True,
            "country": "DO",
            "company_name": "Test Co",
            "companyRNC": "132109122",
        }

    def _ctx(uid, company_id):
        user = flask_session.get("user") or {}
        return {
            "company_id": company_id,
            "owner_uid": user.get("ownerUID", "") or user.get("uid", ""),
            "role": user.get("role", "employee"),
            "permissions": dict(user.get("permissions") or {}),
            "company_name": "Test Co",
            "rnc": "132109122",
            "plan_name": "Plan Activo",
            "billing_type": "Pago por uso",
        }

    import app as app_package
    from app.services import company_context as company_context_module

    with patch.object(app_package, "get_current_company", return_value=None), \
         patch.object(company_context_module, "get_current_company", return_value=None), \
         patch.object(DatabaseService, "get_user_profile", side_effect=_profile), \
         patch.object(DatabaseService, "get_membership", side_effect=_membership), \
         patch.object(DatabaseService, "get_company", side_effect=_company), \
         patch.object(DatabaseService, "get_company_context", side_effect=_ctx), \
         patch.object(DatabaseService, "get_company_profile", return_value={"companyRnc": "132109122"}), \
         patch.object(DatabaseService, "get_plan", return_value={"name": "Plan Activo", "plan_version": 1}), \
         patch.object(DatabaseService, "get_branches", return_value=[]), \
         patch.object(DatabaseService, "get_default_branch", return_value=None), \
         patch.object(DatabaseService, "get_projects", return_value=[]), \
         patch.object(DatabaseService, "get_user_companies", return_value=[]):
        yield


def _provider(**kw):
    inv = {
        "id": "i1",
        "invoiceNumber": "F-1",
        "supplierName": "Proveedor SRL",
        "supplierRnc": "123456789",
        "total": 1000.0,
        "cxpRemainingBalance": 1000.0,
        "dueDate": "2026-01-10",
        "date": "2026-01-01",
        "currency": "DOP",
    }
    inv.update(kw)
    return inv


def _expense(**kw):
    exp = {
        "id": "e1",
        "amount": 500.0,
        "cxpRemainingBalance": 500.0,
        "approvalStatus": "Aprobado",
        "paymentType": "Crédito",
        "dueDate": "2026-01-10",
        "date": "2026-01-01",
        "providerName": "Beneficiario",
        "rncEmisor": "",
        "currency": "DOP",
    }
    exp.update(kw)
    return exp


def _pay(amount, status="approved"):
    return {"id": "p1", "amount": amount, "approvalStatus": status, "paymentDate": "2026-01-05"}


class TestNormalization:
    def test_provider_overdue(self):
        rec = CxpConsolidationService._provider_record(_provider(), [], "2026-02-01")
        assert rec["source"] == "provider"
        assert rec["status"] == STATUS_OVERDUE
        assert rec["balance"] == 1000.0
        assert rec["paid"] == 0.0
        assert rec["balance_mismatch"] is False

    def test_provider_paid(self):
        rec = CxpConsolidationService._provider_record(
            _provider(cxpRemainingBalance=0.0), [_pay(1000.0)], "2026-02-01"
        )
        assert rec["status"] == STATUS_PAID
        assert rec["paid"] == 1000.0

    def test_provider_partial(self):
        rec = CxpConsolidationService._provider_record(
            _provider(cxpRemainingBalance=700.0), [_pay(300.0)], "2026-02-01"
        )
        assert rec["status"] == STATUS_PARTIAL
        assert rec["paid"] == 300.0
        assert rec["balance_mismatch"] is False

    def test_balance_mismatch_detected_not_corrected(self):
        rec = CxpConsolidationService._provider_record(
            _provider(cxpRemainingBalance=800.0), [_pay(300.0)], "2026-02-01"
        )
        assert rec["balance_mismatch"] is True
        assert rec["balance"] == 800.0  # no se corrige silenciosamente
        assert rec["paid"] == 300.0

    def test_voided_provider(self):
        rec = CxpConsolidationService._provider_record(
            _provider(status="anulada"), [], "2026-02-01"
        )
        assert rec["status"] == STATUS_VOIDED

    def test_expense_document_pending(self):
        rec = CxpConsolidationService._expense_record(
            _expense(approvalStatus="Pendiente"), [], "2026-02-01"
        )
        assert rec["source"] == "expense"
        assert rec["document_approval"] == DOC_PENDING


class TestSummarize:
    def _obl(self, cur="DOP", status=STATUS_PENDING, balance=0.0, due_date="", pending_payment=0.0):
        return {
            "currency": cur,
            "status": status,
            "balance": balance,
            "due_date": due_date,
            "pending_payment_amount": pending_payment,
            "total": balance,
        }

    def test_currencies_not_mixed(self):
        obligations = [
            self._obl(cur="DOP", status=STATUS_OVERDUE, balance=1000.0),
            self._obl(cur="USD", status=STATUS_PENDING, balance=500.0),
        ]
        kpis = CxpConsolidationService.summarize(
            obligations, [], [], period="2026-01", today="2026-01-15"
        )
        assert kpis["DOP"]["overdue"] == 1000.0
        assert kpis["DOP"]["pending"] == 0.0
        assert kpis["USD"]["pending"] == 500.0
        assert kpis["USD"]["overdue"] == 0.0

    def test_due_soon_30_days(self):
        obligations = [
            self._obl(cur="DOP", status=STATUS_PENDING, balance=100.0, due_date="2026-01-20"),
            self._obl(cur="DOP", status=STATUS_PENDING, balance=200.0, due_date="2026-03-01"),
        ]
        kpis = CxpConsolidationService.summarize(
            obligations, [], [], period="2026-01", today="2026-01-01"
        )
        assert kpis["DOP"]["due_soon"] == 100.0

    def test_separate_doc_and_payment_pending(self):
        obligations = [
            self._obl(cur="DOP", status=STATUS_PENDING, balance=500.0, pending_payment=100.0)
        ]
        pending_documents = [{"currency": "DOP", "total": 300.0}]
        kpis = CxpConsolidationService.summarize(
            obligations, pending_documents, [], period="2026-01", today="2026-01-15"
        )
        assert kpis["DOP"]["pending"] == 500.0
        assert kpis["DOP"]["pending_payment_approval"] == 100.0
        assert kpis["DOP"]["pending_doc_approval"] == 300.0

    def test_paid_in_period(self):
        payments = [
            {"approval_status": "approved", "payment_date": "2026-01-10", "amount": 200.0, "currency": "DOP"},
            {"approval_status": "approved", "payment_date": "2025-12-31", "amount": 50.0, "currency": "DOP"},
            {"approval_status": "pending", "payment_date": "2026-01-11", "amount": 999.0, "currency": "DOP"},
        ]
        kpis = CxpConsolidationService.summarize(
            [], [], payments, period="2026-01", today="2026-01-15"
        )
        assert kpis["DOP"]["paid_in_period"] == 200.0


class TestBuild:
    def test_build_merges_providers_and_expenses(self):
        with patch(
            "app.services.supplier_invoice_service.SupplierInvoiceService.get_all",
            return_value=[_provider()],
        ), patch(
            "app.services.supplier_invoice_service.SupplierInvoiceService.get_payments",
            return_value=[],
        ), patch(
            "app.services.db_service.DatabaseService.get_expenses",
            return_value=[_expense()],
        ), patch(
            "app.services.db_service.DatabaseService.get_cxp_payments",
            return_value=[],
        ):
            data = CxpConsolidationService.build(owner_uid="u", company_id="c", sandbox=True)

        sources = {o["source"] for o in data["obligations"]}
        assert sources == {"provider", "expense"}
        assert data["kpis"]["DOP"]["overdue"] == 1500.0


class TestApproveExpensePermission:
    def test_non_owner_without_permission_gets_403(self, app, client):
        with client.session_transaction() as sess:
            sess["user"] = {
                "uid": "u1",
                "ownerUID": "o1",
                "role": "employee",
                "permissions": {"canExpenses": True, "canApproveExpenses": False},
            }
            sess["selected_company_id"] = "c1"
            sess["selected_owner_uid"] = "o1"
            sess["company_country"] = "DO"
            sess["is_sandbox_mode"] = True
            sess["company_modules"] = {"gastos": {"enabled": True}}
            sess["company_report_groups"] = {}
            sess["company_plan_id"] = "plan-test"
            sess["company_plan_version"] = 1

        with patch(
            "app.services.db_service.DatabaseService.get_expenses",
            return_value=[_expense(id="e1")],
        ):
            resp = client.post("/expenses/e1/approve")
        assert resp.status_code == 403

    def test_owner_can_approve(self, app, client):
        with client.session_transaction() as sess:
            sess["user"] = {
                "uid": "o1",
                "ownerUID": "o1",
                "role": "owner",
                "permissions": {},
            }
            sess["selected_company_id"] = "c1"
            sess["selected_owner_uid"] = "o1"
            sess["company_country"] = "DO"
            sess["is_sandbox_mode"] = True
            sess["company_modules"] = {"gastos": {"enabled": True}}
            sess["company_report_groups"] = {}
            sess["company_plan_id"] = "plan-test"
            sess["company_plan_version"] = 1

        with patch(
            "app.services.db_service.DatabaseService.get_expenses",
            return_value=[_expense(id="e1")],
        ), patch(
            "app.services.db_service.DatabaseService.save_expense",
            return_value=None,
        ):
            resp = client.post("/expenses/e1/approve")
        assert resp.status_code == 200


class TestConsolidatedRoute:
    def _login(self, client, *, role="owner", perms=None, modules=None):
        with client.session_transaction() as sess:
            sess["user"] = {
                "uid": "u1" if role != "owner" else "o1",
                "ownerUID": "o1",
                "role": role,
                "permissions": perms or {},
            }
            sess["selected_company_id"] = "c1"
            sess["selected_owner_uid"] = "o1"
            sess["company_country"] = "DO"
            sess["is_sandbox_mode"] = True
            sess["company_modules"] = modules or {}
            sess["company_report_groups"] = {}
            sess["company_plan_id"] = "plan-test"
            sess["company_plan_version"] = 1

    def test_owner_with_both_modules_renders(self, app, client):
        self._login(client, role="owner", modules={
            "cxp_compras": {"enabled": True},
            "gastos": {"enabled": True},
        })
        with patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_all", return_value=[]), \
             patch("app.services.db_service.DatabaseService.get_expenses", return_value=[]):
            resp = client.get("/purchase-orders/cxp/consolidado")
        assert resp.status_code == 200

    def test_gastos_only_user_can_access(self, app, client):
        self._login(client, role="employee", perms={"canManageCXP": True}, modules={
            "gastos": {"enabled": True},
        })
        with patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_all", return_value=[]), \
             patch("app.services.db_service.DatabaseService.get_expenses", return_value=[]):
            resp = client.get("/purchase-orders/cxp/consolidado")
        assert resp.status_code == 200

    def test_user_without_permission_gets_403(self, app, client):
        self._login(client, role="employee", perms={}, modules={
            "cxp_compras": {"enabled": True},
            "gastos": {"enabled": True},
        })
        with patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_all", return_value=[]), \
             patch("app.services.db_service.DatabaseService.get_expenses", return_value=[]):
            resp = client.get("/purchase-orders/cxp/consolidado")
        assert resp.status_code == 403
