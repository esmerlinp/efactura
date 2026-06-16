from app import create_app
from app.services.db_service import DatabaseService

app = create_app()
with app.app_context():
    uid = "TFUN07ZPQaXIiOzFg336NKHhHK33"
    updated_profile = {
        "name": "Propietario Demo",
        "phone": "1234567890",
        "address": "Test",
        "permissions": {},
        "profileImageUrl": "https://example.com/test.jpg"
    }
    DatabaseService.save_user_profile(uid, updated_profile)
    print("Saved profile!")
