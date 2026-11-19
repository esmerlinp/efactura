"""Pruebas de visibilidad del formulario 'Registrar Pago' en el detalle de factura de proveedor."""

from unittest.mock import patch

import pytest

from app.services.db_service import DatabaseService
from app.services.supplier_invoice_service import SupplierInvoiceService


@pytest.fixture(autouse=True)
def _reads(app):
    from flask import session as fs
    def _profile(uid):
        u = fs.get("user") or {}
        p = {"uid": uid or u.get("uid", ""), "ownerUID": u.get("ownerUID", "") or u.get("uid", ""), "email": u.get("email", ""), "role": u.get("role", "employee"), "permissions": dict(u.get("permissions") or {})}
        cid = fs.get("selected_company_id") or u.get("company_id")
        if cid:
            p["default_company_id"] = cid
        return p
    def _membership(uid, cid):
        u = fs.get("user") or {}
        return {"uid": uid, "company_id": cid, "role": u.get("role", "employee"), "permissions": dict(u.get("permissions") or {}), "status": "active"}
    def _company(cid):
        return {"id": cid, "owner_uid": "o1", "status": "active", "plan_id": "plan-test", "plan_version": 1, "configured": True, "country": "DO", "company_name": "Test Co", "companyRNC": "132109122"}
    def _ctx(uid, cid):
        u = fs.get("user") or {}
        return {"company_id": cid, "owner_uid": u.get("ownerUID", "") or u.get("uid", ""), "role": u.get("role", "employee"), "permissions": dict(u.get("permissions") or {}), "company_name": "Test Co", "rnc": "132109122", "plan_name": "Plan Activo", "billing_type": "Pago por uso"}
    import app as app_pkg
    from app.services import company_context as cc
    with patch.object(app_pkg, "get_current_company", return_value=None), \
         patch.object(cc, "get_current_company", return_value=None), \
         patch.object(DatabaseService, "get_user_profile", side_effect=_profile), \
         patch.object(DatabaseService, "get_membership", side_effect=_membership), \
         patch.object(DatabaseService, "get_company", side_effect=_company), \
         patch.object(DatabaseService, "get_company_context", side_effect=_ctx), \
         patch.object(DatabaseService, "get_company_profile", return_value={"companyRnc": "132109122"}), \
         patch.object(DatabaseService, "get_plan", return_value={"name": "Plan", "plan_version": 1}), \
         patch.object(DatabaseService, "get_branches", return_value=[]), \
         patch.object(DatabaseService, "get_default_branch", return_value=None), \
         patch.object(DatabaseService, "get_projects", return_value=[]), \
         patch.object(DatabaseService, "get_user_companies", return_value=[]):
        yield


def _invoice(**kw):
    inv = {
        "id": "i1",
        "invoiceNumber": "FI-2026-0005",
        "supplierName": "Proveedor SRL",
        "supplierRnc": "123456789",
        "supplierType": "formal",
        "paymentType": "Crédito",
        "total": 23600.0,
        "subtotal": 23600.0,
        "itbis": 0.0,
        "discount": 0.0,
        "retainedISR": 0.0,
        "retainedITBIS": 0.0,
        "netPayable": 20600.0,
        "cxpStatus": "Pendiente",
        "cxpRemainingBalance": 20600.0,
        "currency": "DOP",
        "exchangeRate": 1.0,
        "date": "2026-01-05",
        "dueDate": "2026-02-05",
        "ncf": "",
        "poNumber": "",
        "isrAsumido": False,
        "items": [],
    }
    inv.update(kw)
    return inv


def _login(client, role="owner", perms=None, modules=None):
    with client.session_transaction() as s:
        s["user"] = {"uid": "o1" if role == "owner" else "u1", "ownerUID": "o1", "role": role, "permissions": perms or {}}
        s["selected_company_id"] = "c1"
        s["selected_owner_uid"] = "o1"
        s["company_country"] = "DO"
        s["is_sandbox_mode"] = True
        s["company_modules"] = modules or {}
        s["company_report_groups"] = {}
        s["company_plan_id"] = "plan-test"
        s["company_plan_version"] = 1


def _get_detail(client, invoice, payments=None):
    with patch.object(SupplierInvoiceService, "get", return_value=invoice), \
         patch.object(SupplierInvoiceService, "get_payments", return_value=payments or []), \
         patch.object(SupplierInvoiceService, "is_emitted", return_value=False), \
         patch.object(SupplierInvoiceService, "fiscal_void_block_reason", return_value=None), \
         patch.object(DatabaseService, "get_bank_accounts", return_value=[]), \
         patch.object(DatabaseService, "get_resource_comments", return_value=[]), \
         patch.object(DatabaseService, "get_accounting_entries", return_value=[]), \
         patch("app.web.purchase_orders._get_taggable_users", return_value=[]), \
         patch("app.web.purchase_orders._resolve_supplier_email", return_value=""), \
         patch("app.services.audit_service.AuditService.get_entity_logs", return_value=[]):
        return client.get("/purchase-orders/invoices/i1")


class TestPaymentFormVisibility:
    def _modules(self):
        return {"cxp_compras": {"enabled": True}}

    def test_credit_no_payments_shows_form(self, app, client):
        _login(client, role="owner", modules=self._modules())
        resp = _get_detail(client, _invoice(), payments=[])
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "Registrar Pago de RD$" in body
        assert 'id="supplier-pay-modal"' in body
        assert 'name="amount"' in body

    def test_partial_payments_show_history_and_form(self, app, client):
        _login(client, role="owner", modules=self._modules())
        pay = [{"id": "p1", "amount": 10000.0, "paymentDate": "2026-01-10", "method": "Efectivo", "approvalStatus": "approved"}]
        resp = _get_detail(client, _invoice(cxpRemainingBalance=10600.0), payments=pay)
        body = resp.get_data(as_text=True)
        assert "Abonos" in body
        assert "Registrar Pago de RD$" in body

    def test_fully_paid_hides_form(self, app, client):
        _login(client, role="owner", modules=self._modules())
        pay = [{"id": "p1", "amount": 20600.0, "paymentDate": "2026-01-10", "method": "Efectivo", "approvalStatus": "approved"}]
        resp = _get_detail(client, _invoice(cxpRemainingBalance=0.0), payments=pay)
        assert "Registrar Pago de RD$" not in resp.get_data(as_text=True)

    def test_voided_hides_form(self, app, client):
        _login(client, role="owner", modules=self._modules())
        resp = _get_detail(client, _invoice(status="anulada"), payments=[])
        assert "Registrar Pago de RD$" not in resp.get_data(as_text=True)

    def test_contado_no_form(self, app, client):
        _login(client, role="owner", modules=self._modules())
        resp = _get_detail(client, _invoice(paymentType="Contado"), payments=[])
        assert "Registrar Pago de RD$" not in resp.get_data(as_text=True)

    def test_button_shows_net_balance_after_retention(self, app, client):
        _login(client, role="owner", modules=self._modules())
        resp = _get_detail(client, _invoice(cxpRemainingBalance=20600.0), payments=[])
        body = resp.get_data(as_text=True)
        assert "Registrar Pago de RD$ 20,600.00" in body
        assert "23,600.00" in body  # el total original sigue visible

    def test_pending_payment_has_approval_pills_and_revert_menu(self, app, client):
        _login(client, role="owner", modules=self._modules())
        pay = [{"id": "p1", "amount": 10000.0, "paymentDate": "2026-01-10", "method": "Efectivo", "approvalStatus": "pending"}]
        resp = _get_detail(client, _invoice(cxpRemainingBalance=10600.0), payments=pay)
        body = resp.get_data(as_text=True)
        assert "Aprobar" in body
        assert "Rechazar" in body
        assert "Revertir" in body
        assert "action-menu" in body

    def test_user_without_permission_gets_403(self, app, client):
        _login(client, role="employee", perms={}, modules=self._modules())
        resp = _get_detail(client, _invoice(), payments=[])
        assert resp.status_code == 403


class TestPayMultiple:
    def test_nota_credito_option_present(self, app, client):
        _login(client, role="owner", modules={"cxp_compras": {"enabled": True}})
        inv = {
            "id": "i1", "invoiceNumber": "F-1", "supplierId": "s1", "supplierName": "Prov",
            "supplierRnc": "123", "total": 23600.0, "cxpRemainingBalance": 20600.0,
            "cxpStatus": "Pendiente", "dueDate": "2026-02-01",
        }
        with patch.object(SupplierInvoiceService, "get_all", return_value=[inv]), \
             patch.object(DatabaseService, "get_bank_accounts", return_value=[]):
            resp = client.get("/purchase-orders/invoices/pay-multiple")
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "Nota Crédito" in body
