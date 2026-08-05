import os
file_path = "app/services/db_service.py"
with open(file_path, "r") as f:
    content = f.read()

target = """        if not company_id:
            return False

        update_data = {"""
replacement = """        if not company_id:
            return False

        # Prevenir sobrescribir 'configured' si no viene explícitamente y la empresa ya está configurada
        is_configured = profile_dict.get("configured")
        if is_configured is None:
            # Mantener el valor actual si existe
            existing_company = cls.get_company(company_id)
            if existing_company:
                is_configured = existing_company.get("configured", False)
            else:
                is_configured = False

        update_data = {
            "configured": is_configured,"""

if target in content and "is_configured = profile_dict.get" not in content:
    # Also we need to replace the configured assignment below
    content = content.replace(target, replacement)
    
    target2 = '"configured": profile_dict.get("configured", False),'
    replacement2 = '# "configured": is_configured, # Asignado arriba'
    content = content.replace(target2, replacement2)
    
    with open(file_path, "w") as f:
        f.write(content)
    print("Patched app/services/db_service.py")
else:
    print("Already patched or target not found")
