import sys
sys.path.append("/Users/esmerlinpaniagua/Develop/e-Factura/portal")
from database_service import DatabaseService
companies = DatabaseService._get_all_companies_legacy()
print("Total legacy companies:", len(companies))
for c in companies:
    print(c.get("ownerUID"), c.get("companyName"))
