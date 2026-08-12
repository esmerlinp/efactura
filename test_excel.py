import sys
from app.services.dgii_cert_service import DgiiCertService

# Check what get_run returns
data = DgiiCertService.get_run("fa3abfc7-5e4c-410b-bde5-b101e1a8ea10", 2, 1)
print(data.get("cases")[0].get("encf"))
