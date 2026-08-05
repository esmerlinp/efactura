import os
file_path = "app/services/hr_authorization_service.py"
with open(file_path, "r") as f:
    content = f.read()

target = """    except Exception as e:
        logger.error("Authorization transaction FAILED %s approver=%s: %s",
                     request_id, approver_id, e)
        return {"success": False, "error": "Conflicto de concurrencia. Intenta de nuevo."}"""
replacement = """    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error("Authorization transaction FAILED %s approver=%s: %s",
                     request_id, approver_id, e)
        return {"success": False, "error": "Conflicto de concurrencia. Intenta de nuevo. Detalles en consola."}"""

if target in content:
    with open(file_path, "w") as f:
        f.write(content.replace(target, replacement))
    print("Patched app/services/hr_authorization_service.py")
else:
    print("Already patched or target not found")
