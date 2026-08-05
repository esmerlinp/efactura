import sys
sys.path.append('.')
from app.services.db_service import db_firestore

users = db_firestore.collection('users').stream()
print("Users in DB:")
for u in users:
    profile = db_firestore.collection('users').document(u.id).collection('config').document('user_profile').get()
    if profile.exists:
        data = profile.to_dict()
        print(f"UID: {u.id}, Email: {data.get('email')}, Name: {data.get('name')}")
    else:
        print(f"UID: {u.id}, No profile")
