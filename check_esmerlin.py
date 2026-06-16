from app import create_app
from app.services.db_service import db_firestore

app = create_app()
with app.app_context():
    doc = db_firestore.collection("users").document("5J3t4WYgI2U0eEVxTETPJ8NuCeg1").collection("config").document("user_profile").get()
    print("User Data in DB:", doc.to_dict().get('profileImageUrl', 'NOT FOUND'))
