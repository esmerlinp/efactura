from app import create_app
from flask import session
import json
import base64

app = create_app()
with app.test_request_context('/'):
    app.config['SECRET_KEY'] = 'dev'
    from flask.sessions import SecureCookieSessionInterface
    si = SecureCookieSessionInterface()
    
    # Mock a typical session
    mock_session = {
        "user": {
            "uid": "TFUN07ZPQaXIiOzFg336NKHhHK33",
            "ownerUID": "TFUN07ZPQaXIiOzFg336NKHhHK33",
            "role": "owner",
            "name": "Propietario Demo",
            "email": "propietario@vykcore.com",
            "phone": "1234567890",
            "address": "Santo Domingo",
            "permissions": {
                "canInvoice": True,
                "canExpenses": True,
                "canClients": True,
                "canModifySettings": True,
                "canManageInventory": True,
                "canManagePOS": True,
                "canViewDashboard": True,
                "canManageCXC": True,
                "canManageCXP": True,
                "canManageContracts": True,
                "canManageCommissions": True,
                "canViewBI": True,
                "canViewAuditLog": False,
                "isPosSupervisor": False,
                "canViewSubscription": True,
                "canToggleSandbox": True,
                "canManageNotes": True
            },
            "createdAt": "2026-06-16T12:00:00",
            "two_factor_enabled": False,
            "profileImageUrl": "https://storage.googleapis.com/vykcore.firebasestorage.app/users/TFUN07ZPQaXIiOzFg336NKHhHK33/avatars/4f1b3b24c8b3400ab95a5f1a5f1b3b2_avatar.jpg"
        },
        "associated_companies": [
            {
                "ownerUID": "TFUN07ZPQaXIiOzFg336NKHhHK33",
                "companyName": "Empresa 1",
                "role": "owner"
            }
        ],
        "user_has_multiple_companies": False,
        "selected_owner_uid": "TFUN07ZPQaXIiOzFg336NKHhHK33",
        "is_sandbox_mode": False
    }
    
    from flask.sessions import SessionMixin
    class MockSession(dict, SessionMixin):
        pass
    
    s = MockSession(mock_session)
    val = si.get_signing_serializer(app).dumps(dict(s))
    print("Session Cookie Size:", len(val), "bytes")
