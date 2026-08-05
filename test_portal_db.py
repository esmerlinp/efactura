import sys
import traceback
sys.path.append("/Users/esmerlinpaniagua/Develop/e-Factura/portal")
from database_service import DatabaseService
try:
    companies = DatabaseService.get_all_companies()
    print("Total companies:", len(companies))
except Exception as e:
    traceback.print_exc()
