import pytest
from unittest.mock import patch, MagicMock
from app.services.contingency_sync_service import ContingencySyncService
from app.services.dgii_direct import DgiiDirectService
from app.services.db_service import DatabaseService


MOCK_USER_PROFILE = {
    'uid': 'test-uid',
    'ownerUID': 'test-owner',
    'role': 'owner',
    'email': 'admin@test.com',
    'name': 'Admin',
    'permissions': {'canInvoice': True, 'canManagePOS': True},
}

MOCK_COMPANY = {
    'companyRNC': '131880681',
    'rnc': '131880681',
    'companyName': 'Test Co',
    'configured': True,
    'posEnabled': True,
    'productionEnabled': True,
    'sandboxEnabled': True,
    'sandboxIndefinite': True,
}


def test_contingency_sync_mark_synced_persists_track_id():
    invoice = {
        "id": "inv_001",
        "invoiceNumber": "INV-001",
        "status": "Pendiente DGII",
        "totalPaid": 100.0,
        "netPayable": 100.0,
        "total": 100.0,
        "encf": "E310000000001",
    }
    emission_res = {
        "success": True,
        "mode": "API",
        "dgiiStatus": "ACCEPTED",
        "trackId": "TRACK-ID-999",
        "codigoSeguridad": "SEC-777",
        "xmlSignature": "SIG-123",
        "qrCodeURL": "https://dgii.gov.do/qr",
    }

    with patch("app.services.contingency_sync_service.DatabaseService.save_invoice") as mock_save, \
         patch.object(ContingencySyncService, "_sync_consolidated_children"), \
         patch.object(ContingencySyncService, "_update_sequence_log"):
        
        ContingencySyncService._mark_synced(
            owner_uid="owner_1",
            inv_id="inv_001",
            invoice=invoice,
            res=emission_res,
            sandbox=True,
            company_id="comp_1"
        )

        mock_save.assert_called_once()
        saved_inv = mock_save.call_args[0][2]
        assert saved_inv["trackId"] == "TRACK-ID-999"
        assert saved_inv["codigoSeguridad"] == "SEC-777"
        assert saved_inv["isSyncedWithDGII"] is True
        assert saved_inv["status"] == "Cobrada"


def test_reconcile_pending_api_recovers_missing_track_id():
    inv = {
        "id": "inv_001",
        "encf": "E310000000001",
        "trackId": "",
        "pendingSyncAttempts": 0,
        "lastPendingCheckAt": "",
        "dgiiStatus": "PENDING"
    }
    company = {
        "companyRNC": "131880681"
    }

    consultar_res = {
        "success": True,
        "trackIds": ["RECOVERED-TRACK-001"]
    }
    check_status_res = {
        "success": True,
        "dgiiStatus": "ACCEPTED",
        "trackId": "RECOVERED-TRACK-001"
    }

    with patch("app.services.contingency_sync_service.DatabaseService.get_pending_api_invoices", return_value=[inv]), \
         patch("app.services.contingency_sync_service.DatabaseService.get_company_profile", return_value=company), \
         patch("app.services.contingency_sync_service.DatabaseService.get_invoice", return_value=inv), \
         patch("app.services.contingency_sync_service.DgiiDirectService.consultar_trackids", return_value=consultar_res) as mock_consultar, \
         patch("app.services.contingency_sync_service.DgiiDirectService.check_status", return_value=check_status_res) as mock_check, \
         patch.object(ContingencySyncService, "_apply_status_resolution", return_value="accepted") as mock_apply:

        synced, rejected, pending = ContingencySyncService.reconcile_pending_api("owner_1", sandbox=True, company_id="comp_1")

        assert synced == 1
        assert rejected == 0
        assert pending == 0
        mock_consultar.assert_called_once_with(company, "131880681", "E310000000001", sandbox=True)
        assert inv["trackId"] == "RECOVERED-TRACK-001"
        mock_check.assert_called_once_with(company, "RECOVERED-TRACK-001", sandbox=True)


def test_consultar_trackids_extracts_from_various_formats():
    company = {"companyRNC": "131880681"}

    # Format 1: list of dicts with trackId
    mock_resp1 = MagicMock()
    mock_resp1.status_code = 200
    mock_resp1.json.return_value = [{"trackId": "TRK-001"}, {"trackId": "TRK-002"}]
    mock_resp1.text = '[{"trackId": "TRK-001"}, {"trackId": "TRK-002"}]'

    with patch.object(DgiiDirectService, "get_dgii_token", return_value=("token", None)), \
         patch.object(DgiiDirectService, "_prepare_tls_cert", return_value=None), \
         patch.object(DgiiDirectService, "_cleanup_tls_cert"), \
         patch.object(DgiiDirectService, "_get_with_params", return_value=mock_resp1):

        res = DgiiDirectService.consultar_trackids(company, "131880681", "E310000000001", sandbox=True)
        assert res["success"] is True
        assert res["trackIds"] == ["TRK-001", "TRK-002"]

    # Format 2: dict with trackId string
    mock_resp2 = MagicMock()
    mock_resp2.status_code = 200
    mock_resp2.json.return_value = {"trackId": "SINGLE-TRK"}
    mock_resp2.text = '{"trackId": "SINGLE-TRK"}'

    with patch.object(DgiiDirectService, "get_dgii_token", return_value=("token", None)), \
         patch.object(DgiiDirectService, "_prepare_tls_cert", return_value=None), \
         patch.object(DgiiDirectService, "_cleanup_tls_cert"), \
         patch.object(DgiiDirectService, "_get_with_params", return_value=mock_resp2):

        res = DgiiDirectService.consultar_trackids(company, "131880681", "E310000000001", sandbox=True)
        assert res["success"] is True
        assert res["trackIds"] == ["SINGLE-TRK"]


def test_sync_single_invoice_auto_recovers_missing_track_id(client):
    invoice = {
        "id": "inv_test_123",
        "invoiceNumber": "B0200000001",
        "encf": "E320000000001",
        "emisionMode": "API",
        "dgiiStatus": "PENDING",
        "status": "Pendiente DGII",
        "trackId": "",
    }

    with client.session_transaction() as sess:
        sess['user'] = {
            'uid': 'test-uid',
            'ownerUID': 'test-owner',
            'role': 'owner',
            'email': 'admin@test.com',
            'name': 'Admin',
            'permissions': {'canInvoice': True},
        }
        sess['is_sandbox_mode'] = True

    with patch("app.services.db_service.DatabaseService.get_user_profile", return_value=MOCK_USER_PROFILE), \
         patch("app.services.db_service.DatabaseService.get_associated_companies", return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]), \
         patch("app.services.db_service.DatabaseService.get_company_profile", return_value=MOCK_COMPANY), \
         patch("app.services.db_service.DatabaseService.get_user_companies", return_value=[]), \
         patch("app.web.invoices.DatabaseService.get_invoice", return_value=invoice), \
         patch("app.web.invoices.DatabaseService.save_invoice") as mock_save, \
         patch("app.web.invoices.DgiiDirectService.consultar_trackids", return_value={"success": True, "trackIds": ["RECOVERED-TRK-789"]}) as mock_consultar, \
         patch("app.web.invoices.DgiiDirectService.check_status", return_value={"success": True, "dgiiStatus": "ACCEPTED", "trackId": "RECOVERED-TRK-789"}) as mock_check, \
         patch("app.services.contingency_sync_service.ContingencySyncService._apply_status_resolution", return_value="accepted") as mock_apply:

        resp = client.post("/invoices/inv_test_123/sync", follow_redirects=False)

        assert resp.status_code == 302
        mock_consultar.assert_called_once()
        assert invoice["trackId"] == "RECOVERED-TRK-789"
        mock_check.assert_called_once_with(MOCK_COMPANY, "RECOVERED-TRK-789", sandbox=True)
