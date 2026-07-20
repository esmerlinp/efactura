"""One-time fix: marca como inactivos los empleados con offboarding completado.

Uso (dentro de flask shell):
    >>> exec(open('scripts/fix_employee_status.py').read())

O desde la terminal del proyecto:
    $ flask shell < scripts/fix_employee_status.py
"""

from app.services.db_service import db_firestore, firebase_initialized
from app.services import hr_data_service as hr

if not firebase_initialized:
    print("❌ Firebase no inicializado")
    exit(1)

user_docs = db_firestore.collection("users").get()
fixed = 0
skipped = 0
errors = 0

print(f"🔍 Revisando {len(user_docs)} usuarios...")

for user in user_docs:
    owner_uid = user.id
    for prefix in ("", "sandbox_"):
        coll_path = f"users/{owner_uid}/{prefix}hr_offboarding_requests"
        try:
            req_docs = db_firestore.collection(coll_path)\
                .where("status", "==", "completed").get()
        except Exception:
            continue

        for doc in req_docs:
            req = doc.to_dict()
            emp_id = req.get("employeeId", "")
            if not emp_id:
                skipped += 1
                continue

            sandbox = prefix == "sandbox_"
            try:
                emp = hr.get_employee(owner_uid, emp_id, sandbox=sandbox)
                if not emp:
                    print(f"  ⚠️ Empleado {emp_id} no encontrado (owner={owner_uid})")
                    errors += 1
                    continue

                if emp.get("status") == "inactivo":
                    skipped += 1
                    continue

                emp["status"] = "inactivo"
                emp["terminationDate"] = req.get("effectiveDate", "")
                emp["terminationType"] = req.get("terminationType", "")
                hr.save_employee(owner_uid, emp_id, emp, sandbox=sandbox)
                print(f"  ✅ {emp.get('fullName','?')} ({emp_id}) → inactivo")
                fixed += 1
            except Exception as e:
                print(f"  ❌ Error con {emp_id}: {e}")
                errors += 1

print(f"\n📊 Resumen:")
print(f"  Corregidos: {fixed}")
print(f"  Saltados (ya inactivos/sin emp): {skipped}")
print(f"  Errores: {errors}")
