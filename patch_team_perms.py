import re

file_path = 'app/web/invoices.py'
with open(file_path, 'r') as f:
    content = f.read()

# Replace the specific pattern
# if session['user'].get('role') != 'owner':
# to
# if session['user'].get('role') != 'owner' and not session['user'].get('permissions', {}).get('canModifySettings', False):

content = content.replace(
    "if session['user'].get('role') != 'owner':",
    "if session['user'].get('role') != 'owner' and not session['user'].get('permissions', {}).get('canModifySettings', False):"
)

with open(file_path, 'w') as f:
    f.write(content)

print("invoices.py patched successfully!")
