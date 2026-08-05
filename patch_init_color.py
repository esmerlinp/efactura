import os
file_path = "app/__init__.py"
with open(file_path, "r") as f:
    content = f.read()

target = """        logo_url = ''
        gradient_enabled = False
        color_marca = ''
        apply_ui = True"""
replacement = """        logo_url = ''
        gradient_enabled = False
        color_marca = ''
        color_on_accent = '#FFFFFF'
        apply_ui = True"""

if target in content and "color_on_accent = '#FFFFFF'" not in content:
    content = content.replace(target, replacement)
    
    target2 = """                apply_reports = company.apply_color_marca_reports
                theme = company.theme
                is_configured = company.is_configured"""
    replacement2 = """                apply_reports = company.apply_color_marca_reports
                theme = company.theme
                is_configured = company.is_configured
                if color_marca:
                    from app.utils.color_utils import _contrast_text_color
                    color_on_accent = _contrast_text_color(color_marca)"""
    content = content.replace(target2, replacement2)
    
    target3 = "            'company_color_marca': color_marca,"
    replacement3 = "            'company_color_marca': color_marca,\n            'company_color_on_accent': color_on_accent,"
    
    content = content.replace(target3, replacement3)

    with open(file_path, "w") as f:
        f.write(content)
    print("Patched app/__init__.py with color_on_accent")
else:
    print("Already patched or target not found")
