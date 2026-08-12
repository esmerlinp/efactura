import re

with open("app/services/dgii_cert_service.py", "r") as f:
    text = f.read()

# Fix success_map
text = text.replace(
    'success_map = {c["encf"]: c for c in results if c.get("success")}',
    'success_map = {f"{c[\'encf\']}_{c.get(\'grupo\')}": c for c in results if c.get("success")}'
)

# Fix check in success_map
text = text.replace(
    'if caso["encf"] in success_map and not dry_run:',
    'if f"{caso[\'encf\']}_{g}" in success_map and not dry_run:'
)

# Fix idx_in_results
text = text.replace(
    'idx_in_results = next((i for i, r in enumerate(results) if r["encf"] == encf), -1)',
    'idx_in_results = next((i for i, r in enumerate(results) if r["encf"] == encf and str(r.get("grupo", "")) == str(g)), -1)'
)

with open("app/services/dgii_cert_service.py", "w") as f:
    f.write(text)

print("Backend fixed")
