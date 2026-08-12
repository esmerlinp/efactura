import json
import os
import sys
# Set up simple environment without importing app
from app.services.dgii_cert_service import DgiiCertService

class Dummy:
    pass

with open('/Users/esmerlinpaniagua/Develop/e-Factura/e-FacturaWeb/uploads/certificacion/fa3abfc7-5e4c-410b-bde5-b101e1a8ea10/step2/run34/parsed_data.json', 'r') as f:
    parsed_data = json.load(f)

# look at the first case of group 4
g4_cases = parsed_data.get("_grupos_raw", {}).get("4", [])
if not g4_cases:
    print("NO GROUP 4 CASES")
    sys.exit(1)

caso = g4_cases[0]
tag = caso["tag"]
is_rfce = (tag == "rfce")
print(f"ENCF: {caso['encf']}, TAG: {tag}, is_rfce={is_rfce}")
