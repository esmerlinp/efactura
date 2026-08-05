import firebase_admin
from firebase_admin import credentials, firestore
import sys
sys.path.append("/Users/esmerlinpaniagua/Develop/e-Factura/portal")
from database_service import DatabaseService
import traceback

try:
    stats = DatabaseService.get_invoice_stats("dummy_uid")
    print(stats)
except Exception as e:
    traceback.print_exc()
