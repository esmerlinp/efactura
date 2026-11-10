"""
test_notification_center.py — Pruebas del Centro de Notificaciones unificado.

Cubre: autorización fiscal en backend, aislamiento, deduplicación, separación de
estados (tributario vs lectura), contadores separados, badge y regresión del poll.
"""
from unittest.mock import patch, MagicMock
from contextlib import ExitStack
import pytest

from app.services.notification_center import (
    NotificationAggregator,
    NotificationStateService,
    can_view_fiscal,
)


def _access(role="member", permissions=None, owner_uid="owner_1"):
    a = MagicMock()
    a.role = role
    a.permissions = permissions or {}
    a.owner_uid = owner_uid
    return a


class TestFiscalAuthorization:
    def test_can_view_fiscal_owner(self):
        assert can_view_fiscal(_access(role="owner")) is True

    def test_can_view_fiscal_member_with_permission(self):
        assert can_view_fiscal(_access(permissions={"canAccounting": True})) is True

    def test_can_view_fiscal_member_without_permission(self):
        assert can_view_fiscal(_access(permissions={})) is False

    def test_can_view_fiscal_none(self):
        assert can_view_fiscal(None) is False

    @patch("app.services.tax_obligation_service.TaxObligationService.get_status")
    @patch("app.services.company_authorization.get_company_access")
    @patch("app.services.notification_center.NotificationStateService.get_read_item_ids", return_value=set())
    @patch("app.services.db_service.DatabaseService.get_user_notifications", return_value=[])
    @patch("app.services.db_service.DatabaseService.get_crm_contacts", return_value=[])
    def test_fiscal_not_queried_without_permission(self, mock_crm, mock_notif, mock_read, mock_access, mock_status):
        mock_access.return_value = _access(role="member", permissions={})
        items, counters = NotificationAggregator.aggregate("u1", "owner_1", "comp_1", sandbox=False)
        mock_status.assert_not_called()
        assert counters["fiscal_allowed"] is False
        assert counters["fiscal_overdue"] == 0
        assert counters["fiscal_upcoming"] == 0
        assert not any(i["category"] == "fiscal" for i in items)

    @patch("app.services.tax_obligation_service.TaxObligationService.get_status")
    @patch("app.services.company_authorization.get_company_access")
    @patch("app.services.notification_center.NotificationStateService.get_read_item_ids", return_value=set())
    @patch("app.services.db_service.DatabaseService.get_user_notifications", return_value=[])
    @patch("app.services.db_service.DatabaseService.get_crm_contacts", return_value=[])
    def test_fiscal_queried_with_permission(self, mock_crm, mock_notif, mock_read, mock_access, mock_status):
        mock_access.return_value = _access(role="owner")
        mock_status.return_value = [
            {"key": "rs2", "label": "Declaración RS2", "status": "overdue", "period_key": "2026",
             "next_due_date": "2026-02-27", "description": "", "action_url": "", "action_label": ""},
            {"key": "rst_cuota_mar", "label": "Cuota RST Marzo", "status": "due_soon", "period_key": "2026-03",
             "next_due_date": "2026-03-31", "description": "", "action_url": "", "action_label": ""},
            {"key": "it1", "label": "IT-1", "status": "ok", "period_key": "2026-03",
             "next_due_date": "2026-03-20", "description": "", "action_url": "", "action_label": ""},
        ]
        items, counters = NotificationAggregator.aggregate("u1", "owner_1", "comp_1", sandbox=False)
        assert counters["fiscal_allowed"] is True
        assert counters["fiscal_overdue"] == 1
        assert counters["fiscal_upcoming"] == 1
        fiscal = [i for i in items if i["category"] == "fiscal"]
        assert len(fiscal) == 2  # la 'ok' se excluye
        assert fiscal[0]["id"] == "fiscal:rs2:2026"
        assert fiscal[0]["severity"] == "critical"
        assert fiscal[1]["id"] == "fiscal:rst_cuota_mar:2026-03"
        assert fiscal[1]["severity"] == "warning"


class TestDedupAndIds:
    @patch("app.services.tax_obligation_service.TaxObligationService.get_status")
    @patch("app.services.company_authorization.get_company_access")
    @patch("app.services.notification_center.NotificationStateService.get_read_item_ids", return_value=set())
    @patch("app.services.db_service.DatabaseService.get_user_notifications", return_value=[])
    @patch("app.services.db_service.DatabaseService.get_crm_contacts", return_value=[])
    def test_fiscal_ids_stable_between_calls(self, mock_crm, mock_notif, mock_read, mock_access, mock_status):
        mock_access.return_value = _access(role="owner")
        mock_status.return_value = [
            {"key": "rs2", "label": "RS2", "status": "overdue", "period_key": "2026",
             "next_due_date": "2026-02-27", "description": "", "action_url": "", "action_label": ""},
        ]
        items1, _ = NotificationAggregator.aggregate("u1", "owner_1", "comp_1", sandbox=False)
        items2, _ = NotificationAggregator.aggregate("u1", "owner_1", "comp_1", sandbox=False)
        assert [i["id"] for i in items1] == [i["id"] for i in items2]


class TestMentionMapping:
    """Las notificaciones in-app usan dos convenciones de campos:
    menciones de comentarios (`message`/`link`) y acciones de portal/pagos
    (`body`/`documentUrl`). El centro debe normalizar ambas."""

    @patch("app.services.tax_obligation_service.TaxObligationService.get_status")
    @patch("app.services.company_authorization.get_company_access")
    @patch("app.services.notification_center.NotificationStateService.get_read_item_ids", return_value=set())
    @patch("app.services.db_service.DatabaseService.get_user_notifications")
    @patch("app.services.db_service.DatabaseService.get_crm_contacts", return_value=[])
    def test_portal_notification_uses_body_and_document_url(self, mock_crm, mock_notif, mock_read, mock_access, mock_status):
        mock_access.return_value = _access(role="member", permissions={})
        mock_notif.return_value = [
            {
                "id": "n1",
                "type": "portal_firma",
                "icon": "✅",
                "title": "Cliente S.A. aprobó la Cotización",
                "body": "Cliente S.A. autorizó cotización COT-100.",
                "documentType": "Cotización",
                "documentNumber": "COT-100",
                "clientName": "Cliente S.A.",
                "documentUrl": "/invoices/inv-1",
                "createdAt": "2026-11-10T00:00:00+00:00",
                "read": False,
                "sandbox": False,
            },
        ]
        items, counters = NotificationAggregator.aggregate("u1", "owner_1", "comp_1", sandbox=False)
        assert counters["mentions_unread"] == 1
        assert len(items) == 1
        item = items[0]
        assert item["description"] == "Cliente S.A. autorizó cotización COT-100."
        assert item["action_url"] == "/invoices/inv-1"
        assert item["action_label"] == "Ver"

    @patch("app.services.tax_obligation_service.TaxObligationService.get_status")
    @patch("app.services.company_authorization.get_company_access")
    @patch("app.services.notification_center.NotificationStateService.get_read_item_ids", return_value=set())
    @patch("app.services.db_service.DatabaseService.get_user_notifications")
    @patch("app.services.db_service.DatabaseService.get_crm_contacts", return_value=[])
    def test_mention_notification_uses_message_and_link(self, mock_crm, mock_notif, mock_read, mock_access, mock_status):
        mock_access.return_value = _access(role="member", permissions={})
        mock_notif.return_value = [
            {
                "id": "n2",
                "type": "mention",
                "title": "Nueva mención en un comentario",
                "message": "A te mencionó en un comentario de la factura F-1.",
                "documentNumber": "F-1",
                "link": "/invoices/inv-2",
                "createdAt": "2026-11-10T00:00:00+00:00",
                "read": False,
                "sandbox": False,
            },
        ]
        items, counters = NotificationAggregator.aggregate("u1", "owner_1", "comp_1", sandbox=False)
        assert counters["mentions_unread"] == 1
        assert items[0]["description"] == "A te mencionó en un comentario de la factura F-1."
        assert items[0]["action_url"] == "/invoices/inv-2"


class TestReadStateIsolation:
    def test_mark_read_does_not_touch_tax_service(self):
        with patch.object(NotificationStateService, "_read_items_ref") as mock_ref:
            doc = MagicMock()
            coll = MagicMock()
            coll.document.return_value = doc
            mock_ref.return_value = coll
            with patch("app.services.notification_center.datetime") as _:
                NotificationStateService.mark_read("u1", "comp_1", "fiscal:rs2:2026")
            coll.document.assert_called_once()
            doc.set.assert_called_once()


class TestBadgeCounters:
    @patch("app.services.notification_center.NotificationAggregator._fiscal_counts_cached")
    @patch("app.services.notification_center.NotificationStateService.get_read_item_ids")
    @patch("app.services.company_authorization.get_company_access")
    @patch("app.services.db_service.DatabaseService.get_crm_contacts")
    @patch("app.services.db_service.DatabaseService.get_user_notifications")
    def test_badge_separated_counters(self, mock_notif, mock_crm, mock_access, mock_read, mock_fiscal):
        mock_access.return_value = _access(role="owner")
        mock_notif.return_value = [
            {"id": "n1", "read": False},
            {"id": "n2", "read": True},
        ]
        mock_crm.return_value = [
            {"activityId": "a1", "razonSocial": "X", "isOverdue": False},
            {"activityId": "a2", "razonSocial": "Y", "isOverdue": True},
        ]
        mock_read.return_value = {"commitment:a1"}  # a1 ya leído
        mock_fiscal.return_value = {"fiscal_overdue": 3, "fiscal_upcoming": 2}

        badge = NotificationAggregator.get_badge_counts("u1", "comp_1", sandbox=False)

        assert badge["mentions_unread"] == 1      # solo n1
        assert badge["commitments_pending"] == 1  # solo a2 (a1 leído)
        assert badge["fiscal_overdue"] == 3
        assert badge["fiscal_upcoming"] == 2
        assert badge["total"] == 7                # 1 + 1 + 3 + 2, sin duplicar


COMPANY_DOC = {
    "id": "comp_1",
    "status": "Activo",
    "owner_uid": "owner_1",
    "country": "DO",
    "configured": True,
    "planId": "plan_test",
    "plan_id": "plan_test",
    "plan_version": 1,
}


def _login(client):
    user_dict = {
        "uid": "u1",
        "ownerUID": "owner_1",
        "role": "owner",
        "email": "a@b.c",
        "name": "A",
        "status": "active",
        "permissions": {},
    }
    with client.session_transaction() as sess:
        sess.clear()
        sess["user"] = dict(user_dict)
        sess["selected_company_id"] = "comp_1"
        sess["selected_owner_uid"] = "owner_1"
        sess["company_country"] = "DO"
        sess["company_plan_id"] = "plan_test"
        sess["company_plan_version"] = 1
    return user_dict


def _patch_before_request(user_dict):
    """Parchea las dependencias de load_fresh_user_profile + context processors."""
    patches = (
        patch('app.services.db_service.DatabaseService.get_user_profile', return_value=user_dict),
        patch('app.services.db_service.DatabaseService.get_company', return_value=COMPANY_DOC),
        patch('app.services.db_service.DatabaseService.get_company_profile', return_value=COMPANY_DOC),
        patch('app.services.db_service.DatabaseService.get_membership', return_value={'status': 'active', 'role': 'owner', 'permissions': {}}),
        patch('app.services.db_service.DatabaseService.get_company_context', return_value={'company_id': 'comp_1', 'owner_uid': 'owner_1', 'company_name': 'Test Co', 'role': 'owner', 'permissions': {}, 'company': COMPANY_DOC}),
        patch('app.services.db_service.DatabaseService.get_user_companies', return_value=[]),
        patch('app.services.db_service.DatabaseService.get_branches', return_value=[]),
        patch('app.services.db_service.DatabaseService.get_projects', return_value=[]),
        patch('app.services.db_service.DatabaseService.get_plan', return_value={'id': 'p', 'plan_version': 1, 'modules': {}}),
        patch('app.services.db_service.DatabaseService.get_user_notifications', return_value=[]),
        patch('app.services.db_service.DatabaseService.get_crm_contacts', return_value=[]),
        patch('app.services.notification_center.NotificationStateService.get_read_item_ids', return_value=set()),
        patch('app.services.company_authorization.get_company_access', return_value=_access(role='owner')),
        patch('app.services.notification_center.NotificationAggregator._fiscal_counts_cached', return_value={'fiscal_overdue': 0, 'fiscal_upcoming': 0}),
        patch('app.services.production_agreement_guard.ProductionAgreementGuard.evaluate', return_value=MagicMock(blocked=False)),
    )
    stack = ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


class TestRoutes:
    def test_center_requires_login(self, client):
        resp = client.get("/notifications/center")
        assert resp.status_code == 302

    def test_poll_requires_login(self, client):
        resp = client.get("/notifications/poll")
        assert resp.status_code == 401

    def test_center_renders(self, client):
        user_dict = _login(client)
        with _patch_before_request(user_dict) as _:
            with patch("app.services.notification_center.NotificationAggregator.aggregate") as mock_agg:
                mock_agg.return_value = ([], {
                    "mentions_unread": 0, "commitments_pending": 0,
                    "fiscal_overdue": 0, "fiscal_upcoming": 0,
                    "total": 0, "fiscal_allowed": True,
                })
                resp = client.get("/notifications/center")
                assert resp.status_code == 200
                assert b"Centro de Notificaciones" in resp.data

    def test_mark_read_requires_login(self, client):
        resp = client.post("/notifications/center/mark-read", json={"item_id": "x"})
        assert resp.status_code == 401

    def test_mark_read_success(self, client):
        user_dict = _login(client)
        with _patch_before_request(user_dict) as _:
            with patch("app.services.notification_center.NotificationStateService.mark_read", return_value=True) as mock_mark:
                resp = client.post("/notifications/center/mark-read", json={"item_id": "fiscal:rs2:2026"})
                assert resp.status_code == 200
                assert resp.get_json()["success"] is True
                mock_mark.assert_called_once_with("u1", "comp_1", "fiscal:rs2:2026")
