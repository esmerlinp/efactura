from app import create_app
from app.services.db_service import db_firestore
import json
import base64

app = create_app()
with app.app_context():
    doc = db_firestore.collection("users").document("5J3t4WYgI2U0eEVxTETPJ8NuCeg1").collection("config").document("user_profile").get()
    profile = doc.to_dict()
    
    mock_session = {
        "user": profile,
        "associated_companies": profile.get("associated_companies", []),
        "user_has_multiple_companies": len(profile.get("associated_companies", [])) > 1,
        "selected_owner_uid": profile.get("ownerUID", "5J3t4WYgI2U0eEVxTETPJ8NuCeg1"),
        "is_sandbox_mode": False
    }
    
    app.config['SECRET_KEY'] = 'dev'
    from flask.sessions import SecureCookieSessionInterface
    si = SecureCookieSessionInterface()
    from flask.sessions import SessionMixin
    class MockSession(dict, SessionMixin):
        pass
    
    s = MockSession(mock_session)
    val = si.get_signing_serializer(app).dumps(dict(s))
    print("Real Session Cookie Size:", len(val), "bytes")
