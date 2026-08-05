import os
file_path = "app/__init__.py"
with open(file_path, "r") as f:
    content = f.read()

target = "if not company_profile.get('configured', False):"
replacement = """print(f"DEBUG BEFORE REQUEST: company_profile={company_profile}")
                if not company_profile.get('configured', False):"""

if target in content and "DEBUG BEFORE REQUEST" not in content:
    with open(file_path, "w") as f:
        f.write(content.replace(target, replacement))
    print("Patched app/__init__.py")
else:
    print("Already patched or target not found")
