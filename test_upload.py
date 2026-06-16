import os
from app import create_app
from app.services.db_service import DatabaseService, firebase_storage_bucket

app = create_app()
with app.app_context():
    if firebase_storage_bucket:
        try:
            url = DatabaseService.upload_file_to_storage(b"test", "users/test/avatars/test.txt", "text/plain")
            print("URL:", url)
        except Exception as e:
            print("Error:", e)
    else:
        print("Firebase storage not initialized")
