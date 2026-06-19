import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, PropertyMock

from app.services.contingency_sync_service import (
    ContingencySyncService, BACKOFF_INTERVALS, CONTINGENCY_WINDOW_HOURS
)


class TestContingencySyncService:

    def test_discover_owner_uids(self):
        with patch("app.services.contingency_sync_service.db_firestore") as mock_db:
            mock_doc_1 = MagicMock()
            mock_doc_1.id = "uid_001"
            mock_doc_1.reference.collection.return_value.document.return_value.get.return_value.exists = True
            mock_doc_1.reference.collection.return_value.document.return_value.get.return_value.to_dict.return_value = {
                "companyRNC": "131111111", "regimenFiscal": "General"
            }

            mock_doc_2 = MagicMock()
            mock_doc_2.id = "uid_002"
            mock_doc_2.reference.collection.return_value.document.return_value.get.return_value.exists = True
            mock_doc_2.reference.collection.return_value.document.return_value.get.return_value.to_dict.return_value = {
                "companyRNC": "131111112", "regimenFiscal": "Simple"
            }

            mock_db.collection.return_value.limit.return_value.stream.return_value = [mock_doc_1, mock_doc_2]

            uids = ContingencySyncService._discover_all_owner_uids()
            assert "uid_001" in uids
            assert "uid_002" in uids
            assert len(uids) == 2

    def test_discover_owner_uids_skips_incomplete_profiles(self):
        with patch("app.services.contingency_sync_service.db_firestore") as mock_db:
            mock_doc = MagicMock()
            mock_doc.id = "uid_no_company"
            mock_doc.reference.collection.return_value.document.return_value.get.return_value.exists = True
            mock_doc.reference.collection.return_value.document.return_value.get.return_value.to_dict.return_value = {}

            mock_db.collection.return_value.limit.return_value.stream.return_value = [mock_doc]

            uids = ContingencySyncService._discover_all_owner_uids()
            assert "uid_no_company" not in uids

    def test_discover_owner_uids_firebase_not_initialized(self):
        with patch("app.services.contingency_sync_service.firebase_initialized", False):
            uids = ContingencySyncService._discover_all_owner_uids()
            assert uids == set()

    def test_should_retry_first_attempt(self):
        assert ContingencySyncService._should_retry(0, "") is True

    def test_should_retry_exhausted(self):
        assert ContingencySyncService._should_retry(len(BACKOFF_INTERVALS), "") is False

    def test_should_retry_waiting_period(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        assert ContingencySyncService._should_retry(0, past) is True

    def test_should_retry_still_waiting(self):
        recent = datetime.now(timezone.utc).isoformat()
        assert ContingencySyncService._should_retry(2, recent) is False

    def test_hours_since_contingency(self):
        inv = {"contingencyEmittedAt": (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()}
        hours = ContingencySyncService._hours_since_contingency(inv)
        assert hours is not None
        assert 9.5 < hours < 10.5

    def test_hours_since_contingency_missing(self):
        assert ContingencySyncService._hours_since_contingency({}) is None

    def test_hours_since_contingency_from_date_fallback(self):
        inv = {"date": (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()}
        hours = ContingencySyncService._hours_since_contingency(inv)
        assert hours is not None
        assert 4.5 < hours < 5.5

    def test_mark_synced_updates_fields(self):
        inv = {"id": "inv001", "encf": "E310000000001", "total": 1000.0, "totalPaid": "1000.0", "status": "Pendiente DGII"}
        res = {"dgiiStatus": "ACCEPTED", "xmlSignature": "<sig/>", "qrCodeURL": "http://qr.test"}

        with patch.object(ContingencySyncService, "_sync_consolidated_children"), \
             patch.object(ContingencySyncService, "_update_sequence_log"), \
             patch("app.services.contingency_sync_service.DatabaseService.save_invoice"):

            ContingencySyncService._mark_synced("owner01", "inv001", inv, res, True)

            assert inv["isSyncedWithDGII"] is True
            assert inv["emisionMode"] == "API"
            assert inv["dgiiStatus"] == "ACCEPTED"
            assert inv["contingencyEmittedAt"] is None
            assert "syncAttempts" not in inv

    def test_mark_synced_sets_cobrada_when_paid(self):
        inv = {"id": "inv001", "total": 100.0, "totalPaid": "100.0", "status": "Emitida"}
        res = {"dgiiStatus": "ACCEPTED"}

        with patch.object(ContingencySyncService, "_sync_consolidated_children"), \
             patch.object(ContingencySyncService, "_update_sequence_log"), \
             patch("app.services.contingency_sync_service.DatabaseService.save_invoice"):

            ContingencySyncService._mark_synced("owner01", "inv001", inv, res, True)

            assert inv["status"] == "Cobrada"

    def test_mark_synced_clears_pendiente_dgii(self):
        inv = {"id": "inv001", "total": 100.0, "totalPaid": "0.0", "status": "Pendiente DGII"}
        res = {"dgiiStatus": "ACCEPTED"}

        with patch.object(ContingencySyncService, "_sync_consolidated_children"), \
             patch.object(ContingencySyncService, "_update_sequence_log"), \
             patch("app.services.contingency_sync_service.DatabaseService.save_invoice"):

            ContingencySyncService._mark_synced("owner01", "inv001", inv, res, True)

            assert inv["status"] == "Emitida"

    def test_notify_admins_creates_notifications(self):
        with patch("app.services.contingency_sync_service.db_firestore") as mock_db, \
             patch("app.services.contingency_sync_service.DatabaseService.get_team_members") as mock_team, \
             patch("app.services.contingency_sync_service.DatabaseService.create_user_notification") as mock_create_notif:

            mock_team.return_value = [{"uid": "member01"}]
            ContingencySyncService._notify_admins("owner01", "E310000000001", 50, True)

            assert mock_create_notif.call_count == 2
            call_args_list = mock_create_notif.call_args_list
            uids_called = [call[0][0] for call in call_args_list]
            assert "owner01" in uids_called
            assert "member01" in uids_called

            notification = mock_create_notif.call_args_list[0][0][1]
            assert notification["type"] == "contingency_warning"
            assert "E310000000001" in notification["message"]

    def test_check_expired_contingency(self):
        invoices = [
            {"id": "a", "encf": "E31...1", "emisionMode": "FALLBACK", "isSyncedWithDGII": False,
             "contingencyEmittedAt": (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat(),
             "total": 500, "invoiceNumber": "001"},
            {"id": "b", "encf": "E31...2", "emisionMode": "FALLBACK", "isSyncedWithDGII": False,
             "contingencyEmittedAt": (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat(),
             "total": 300, "invoiceNumber": "002"},
        ]

        with patch("app.services.contingency_sync_service.DatabaseService.get_contingency_invoices") as mock_get:
            mock_get.return_value = invoices
            expired = ContingencySyncService.check_expired_contingency("owner01", sandbox=True)

            assert len(expired) == 1
            assert expired[0]["encf"] == "E31...1"
            assert expired[0]["hoursInContingency"] > 72

    def test_sync_company_pending_empty_when_none_fallback(self):
        with patch("app.services.contingency_sync_service.DatabaseService.get_contingency_invoices") as mock_get:
            mock_get.return_value = []
            synced, failed = ContingencySyncService.sync_company_pending("owner01", sandbox=True)

            assert synced == 0
            assert failed == 0

    def test_sync_company_pending_no_company_profile(self):
        invoices = [
            {"id": "a", "emisionMode": "FALLBACK", "isSyncedWithDGII": False, "status": "Emitida"},
        ]

        with patch("app.services.contingency_sync_service.DatabaseService.get_contingency_invoices") as mock_get, \
             patch("app.services.contingency_sync_service.DatabaseService.get_company_profile") as mock_profile:

            mock_get.return_value = invoices
            mock_profile.return_value = None

            synced, failed = ContingencySyncService.sync_company_pending("owner01", sandbox=True)
            assert synced == 0
            assert failed == 0

    def test_sync_consolidated_children_skips_non_consolidado(self):
        with patch("app.services.contingency_sync_service.DatabaseService.mark_invoices_consolidated") as mock_mark:
            ContingencySyncService._sync_consolidated_children("owner01", {"isConsolidado": False}, True)
            mock_mark.assert_not_called()

    def test_sync_consolidated_children_skips_no_child_ids(self):
        with patch("app.services.contingency_sync_service.DatabaseService.mark_invoices_consolidated") as mock_mark:
            ContingencySyncService._sync_consolidated_children("owner01", {"isConsolidado": True}, True)
            mock_mark.assert_not_called()

    def test_sync_consolidated_children_calls_mark(self):
        invoice = {
            "isConsolidado": True,
            "consolidatedInvoiceIds": ["child01"],
            "encf": "E31...X",
            "invoiceNumber": "CONS-001",
            "dgiiStatus": "ACCEPTED",
            "emisionMode": "API",
        }
        with patch("app.services.contingency_sync_service.DatabaseService.get_invoice") as mock_get, \
             patch("app.services.contingency_sync_service.DatabaseService.mark_invoices_consolidated") as mock_mark:
            mock_get.return_value = {"id": "child01", "total": 100}
            ContingencySyncService._sync_consolidated_children("owner01", invoice, True)
            mock_mark.assert_called_once()
            args, kwargs = mock_mark.call_args
            assert kwargs["sandbox"] is True
            assert kwargs["is_synced"] is True
            assert kwargs["dgii_status"] == "ACCEPTED"

    def test_sync_all_companies(self):
        mock_pending = [
            {"id": "a", "emisionMode": "FALLBACK", "isSyncedWithDGII": False, "status": "Emitida", "encf": "E31...1", "items": [], "total": 100},
        ]

        with patch.object(ContingencySyncService, "_discover_all_owner_uids") as mock_discover, \
             patch.object(ContingencySyncService, "sync_company_pending") as mock_sync:

            mock_discover.return_value = {"owner01", "owner02"}
            mock_sync.return_value = (1, 0)

            synced, failed = ContingencySyncService.sync_all_companies()
            assert synced == 4
            assert failed == 0
            assert mock_sync.call_count == 4

    def test_sync_all_companies_continues_on_error(self):
        with patch.object(ContingencySyncService, "_discover_all_owner_uids") as mock_discover, \
             patch.object(ContingencySyncService, "sync_company_pending") as mock_sync:

            mock_discover.return_value = {"owner01"}
            mock_sync.side_effect = [Exception("DB error"), (0, 0)]

            synced, failed = ContingencySyncService.sync_all_companies()
            assert synced == 0


MOCK_USER_PROFILE = {
    'uid': 'test-uid',
    'ownerUID': 'test-owner',
    'role': 'owner',
    'email': 'admin@test.com',
    'name': 'Admin',
    'permissions': {'canManagePOS': True, 'isPosSupervisor': True},
}

MOCK_COMPANY = {
    'companyRNC': '132-10912-2',
    'companyName': 'Test Co',
    'configured': True,
    'posEnabled': True,
    'productionEnabled': True,
    'sandboxEnabled': True,
    'sandboxIndefinite': True,
}

PROFILE_WITH_PERMS = {**MOCK_USER_PROFILE, 'canManagePOS': True, 'canInvoice': True}

class TestContingencyRoutes:

    def _login(self, client, owner_uid='test-owner'):
        with client.session_transaction() as sess:
            sess['user'] = {
                'uid': 'test-uid',
                'ownerUID': owner_uid,
                'role': 'owner',
                'email': 'admin@test.com',
                'name': 'Admin',
                'permissions': {'canManagePOS': True, 'isPosSupervisor': True},
            }
            sess['company_profile_pos_enabled'] = True
            sess['is_sandbox_mode'] = True

    def test_contingencia_route_shows_restricted_when_not_logged_in(self, client):
        resp = client.get('/pos/contingencia')
        html = resp.data.decode('utf-8')
        assert 'restricted' in html or 'Restricted' in html or 'Permiso' in html or '401' in resp.status

    def test_contingencia_route_returns_200_when_authorized(self, client):
        self._login(client)
        with patch('app.services.db_service.DatabaseService.get_contingency_invoices', return_value=[]), \
             patch('app.services.db_service.DatabaseService.get_user_profile', return_value=PROFILE_WITH_PERMS), \
             patch('app.services.db_service.DatabaseService.get_associated_companies',
                   return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
             patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY), \
             patch('app.services.contingency_sync_service.ContingencySyncService.check_expired_contingency',
                   return_value=[]):

            resp = client.get('/pos/contingencia')
            assert resp.status_code == 200

    def test_contingencia_route_shows_pending_invoices(self, client):
        self._login(client)
        fallback_invoice = {
            'id': 'inv-001',
            'invoiceNumber': 'F001',
            'encf': 'E310000000001',
            'total': 1500.00,
            'clientName': 'Juan Pérez',
            'status': 'Emitida',
            'paymentMethod': 'efectivo',
            'date': '2026-06-18T10:00:00',
            'contingencyEmittedAt': '2026-06-18T10:00:00',
            'emisionMode': 'FALLBACK',
            'isSyncedWithDGII': False,
            'syncAttempts': 2,
            'lastSyncAttempt': '2026-06-18T10:30:00',
        }

        with patch('app.services.db_service.DatabaseService.get_contingency_invoices', return_value=[fallback_invoice]), \
             patch('app.services.db_service.DatabaseService.get_user_profile', return_value=PROFILE_WITH_PERMS), \
             patch('app.services.db_service.DatabaseService.get_associated_companies',
                   return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
             patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY), \
             patch('app.services.contingency_sync_service.ContingencySyncService.check_expired_contingency',
                   return_value=[]):

            resp = client.get('/pos/contingencia')
            assert resp.status_code == 200
            html = resp.data.decode('utf-8')
            assert 'E310000000001' in html
            assert 'F001' in html
            assert 'Juan Pérez' in html

    def test_contingencia_route_empty_state(self, client):
        self._login(client)
        with patch('app.services.db_service.DatabaseService.get_contingency_invoices', return_value=[]), \
             patch('app.services.db_service.DatabaseService.get_user_profile', return_value=PROFILE_WITH_PERMS), \
             patch('app.services.db_service.DatabaseService.get_associated_companies',
                   return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
             patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY), \
             patch('app.services.contingency_sync_service.ContingencySyncService.check_expired_contingency',
                   return_value=[]):

            resp = client.get('/pos/contingencia')
            assert resp.status_code == 200
            html = resp.data.decode('utf-8')
            assert 'Sin Comprobantes en Contingencia' in html

    def test_notification_stream_returns_401_when_not_logged_in(self, client):
        resp = client.get('/notifications/stream')
        assert resp.status_code == 401

    def test_notification_stream_returns_sse_when_authenticated(self, client):
        self._login(client)
        with patch('app.services.db_service.DatabaseService.get_user_profile', return_value=PROFILE_WITH_PERMS), \
             patch('app.services.db_service.DatabaseService.get_associated_companies',
                   return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
             patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY), \
             patch('app.services.db_service.DatabaseService.get_user_notifications') as mock_notif:

            mock_notif.return_value = [{'id': 'n1', 'title': 'Test', 'message': 'Hello', 'type': 'info', 'createdAt': '2026-01-01'}]
            resp = client.get('/notifications/stream')
            assert resp.status_code == 200
            assert resp.mimetype == 'text/event-stream'
            assert resp.headers.get('Cache-Control') == 'no-cache'
