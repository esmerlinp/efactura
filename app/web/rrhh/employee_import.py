"""RRHH module — auto-extracted."""

from datetime import date, datetime, timezone
from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.ai_service import AIService
import csv, html, io, json, os, re, uuid, threading


# ═══════════════════════════════════════════════════════════════════════════
# IMPORTACIÓN MASIVA DE EMPLEADOS — Onboarding de 4 pasos
# ═══════════════════════════════════════════════════════════════════════════

TEMP_IMPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'uploads', 'temp_imports')
JOB_DIR = os.path.join(TEMP_IMPORT_DIR, 'jobs')

EMPLOYEE_CSV_FIELDS = [
    ("*firstName", "Primer nombre", True, ["nombre", "name", "primer_nombre", "firstname", "primer nombre"]),
    ("middleName", "Segundo nombre", False, ["segundo_nombre", "middlename", "segundo nombre"]),
    ("*firstLastName", "Primer apellido", True, ["apellido", "lastname", "primer_apellido", "firstlastname", "primer apellido"]),
    ("secondLastName", "Segundo apellido", False, ["segundo_apellido", "secondlastname", "segundo apellido"]),
    ("*idType", "Tipo de identificación", True, ["tipo", "type", "idtype", "tipo_id", "tipo identificación", "tipo_identificacion"]),
    ("*idNumber", "Número de identificación", True, ["cedula", "rnc", "documento", "identificacion", "identificación", "idnumber", "id", "num_identificacion"]),
    ("*email", "Correo electrónico", True, ["email", "correo", "mail", "correo_electronico"]),
    ("phone", "Teléfono", False, ["telefono", "teléfono", "phone", "celular"]),
    ("*municipality", "Municipio", True, ["municipio", "ciudad", "municipality"]),
    ("*address", "Dirección", True, ["direccion", "dirección", "address", "calle"]),
    ("gender", "Género", False, ["genero", "género", "gender", "sexo"]),
    ("birthDate", "Fecha de nacimiento", False, ["nacimiento", "fecha_nac", "birth", "birthdate", "fecha nacimiento", "fecha_nacimiento"]),
    ("maritalStatus", "Estado civil", False, ["estado_civil", "civil", "marital", "maritalstatus"]),
    ("educationLevel", "Grado de instrucción", False, ["instruccion", "educacion", "educación", "education", "educationlevel", "grado"]),
    ("emergencyContact", "Contacto de emergencia", False, ["emergencia", "emergency", "contacto_emergencia", "emergencycontact"]),
    ("emergencyPhone", "Teléfono de emergencia", False, ["tel_emergencia", "emergencyphone", "telefono_emergencia"]),
    ("afpProvider", "AFP", False, ["afp", "afpprovider", "afp_provider"]),
    ("notes", "Notas", False, ["notas", "notes", "comentario", "comentarios", "observaciones"]),
    ("*hireDate", "Fecha de contratación", True, ["contratacion", "contratación", "hire", "hiredate", "fecha_ingreso", "fecha contratación", "ingreso"]),
    ("*contractType", "Tipo de contrato", True, ["contrato", "contract", "contracttype", "tipo_contrato", "tipo contrato"]),
    ("probationEndDate", "Fin período de prueba", False, ["prueba", "probation", "probationenddate", "fin_prueba"]),
    ("reportsTo", "Supervisor directo", False, ["supervisor", "reportsto", "jefe", "reporta"]),
    ("paymentFrequency", "Frecuencia de pago", False, ["frecuencia", "frequency", "paymentfrequency", "pago_frecuencia"]),
    ("*salary", "Valor salario", True, ["salario", "salary", "sueldo", "salario_base"]),
    ("*workday", "Jornada", True, ["jornada", "workday", "jornada_laboral", "tipo_jornada"]),
    ("isVigilante", "¿Trabaja como vigilante?", False, ["vigilante", "isvigilante", "vigilancia"]),
    ("weeklyHours", "Horas semanales", False, ["horas", "weeklyhours", "horas_semanales", "semanales"]),
    ("workShift", "Turno de trabajo", False, ["turno", "workshift", "turno_trabajo"]),
    ("occupationCode", "Código ocupación (CNO-2019)", False, ["ocupacion", "ocupación", "occupation", "occupationcode", "cno"]),
    ("vacationGranted", "Concesión de vacaciones", False, ["vacaciones", "vacation", "vacationgranted"]),
    ("*tssKey", "TSS Clave nómina", True, ["tss", "tsskey", "clave", "clave_nomina", "clave_tss"]),
    ("*position", "Cargo", True, ["cargo", "position", "puesto", "posicion"]),
    ("department_catalog", "Departamento", False, ["departamento", "department", "depto"]),
    ("*area", "Área", True, ["area", "área", "area_trabajo"]),
    ("costCenter", "Centro de costo", False, ["costo", "costcenter", "centro_costo", "cc"]),
    ("*paymentMethod", "Método de pago", True, ["metodo", "metodo_pago", "paymentmethod", "método", "forma_pago"]),
    ("*accountNumber", "Número de cuenta", True, ["cuenta", "account", "accountnumber", "numero_cuenta", "num_cuenta"]),
    ("*bank", "Banco", True, ["banco", "bank", "entidad", "entidad_bancaria"]),
    ("*accountType", "Tipo de cuenta", True, ["tipo_cuenta", "accounttype", "tipo"]),
]

EMPLOYEE_REQUIRED_FIELDS = [f[0].lstrip("*") for f in EMPLOYEE_CSV_FIELDS if f[2]]
EMPLOYEE_TARGET_FIELDS = [
    {"id": f[0].lstrip("*"), "name": f"{f[1]}{' *' if f[2] else ''}", "required": f[2], "suggestions": f[3]}
    for f in EMPLOYEE_CSV_FIELDS
]

EMPLOYEE_CSV_HEADERS = [f[0] for f in EMPLOYEE_CSV_FIELDS]
EMPLOYEE_EXAMPLE_ROW = [
    "Juan", "Carlos", "Pérez", "Gómez",
    "cedula", "40212345678", "juan.perez@example.com", "8095551234",
    "Santo Domingo Este", "Calle Primera #45, Los Prados", "masculino", "1990-05-15",
    "S", "4", "María Pérez", "8095555678",
    "AFP Popular", "Empleado ejemplar con buen desempeño.", "2024-01-15", "tiempo_indefinido",
    "2024-04-15", "", "quincenal", "35000",
    "completa", "no", "44", "1",
    "2411", "1", "001", "Analista de Sistemas",
    "Tecnología", "Tecnología", "CC-TEC-01", "transferencia",
    "00123456789", "Banco Popular Dominicano", "ahorro",
]


def _get_delimiter(first_line):
    for delimiter in [';', '\t', ',']:
        if delimiter in first_line:
            return delimiter
    return ','


def _strip_asterisk(h):
    return h[1:] if h.startswith('*') else h


def _sanitize_float_import(val, default=0.0):
    if not val:
        return default
    try:
        val_clean = str(val).strip().replace('RD$', '').replace('$', '').replace(' ', '')
        if ',' in val_clean and '.' in val_clean:
            val_clean = val_clean.replace(',', '')
        elif ',' in val_clean:
            val_clean = val_clean.replace(',', '.')
        return float(val_clean)
    except Exception:
        return default


@web_rrhh_bp.route("/rrhh/employees/import")
def employee_import():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()

    positions = hr.get_catalog(owner_uid, "positions", sandbox)
    departments = hr.get_catalog(owner_uid, "departments", sandbox)

    from app.services.payroll_static_data import (
        AREAS, CONTRACT_TYPES, PAYMENT_METHODS, WORKDAYS,
        BANCOS_RD, ACCOUNT_TYPES, ID_TYPES, PAYROLL_FREQUENCIES
    )

    system_defaults = {
        "position": [p["name"] for p in positions],
        "department_catalog": [d["name"] for d in departments],
        "area": [a["value"] for a in AREAS],
        "contractType": [c["value"] for c in CONTRACT_TYPES],
        "paymentMethod": [p["value"] for p in PAYMENT_METHODS],
        "workday": [w["value"] for w in WORKDAYS],
        "bank": BANCOS_RD,
        "accountType": [a["value"] for a in ACCOUNT_TYPES],
        "idType": [t["value"] for t in ID_TYPES],
        "paymentFrequency": [f["value"] for f in PAYROLL_FREQUENCIES],
    }

    return render_template("rrhh/employee_import.html", active_page="rrhh_employees",
                           target_fields=EMPLOYEE_TARGET_FIELDS,
                           required_fields=EMPLOYEE_REQUIRED_FIELDS,
                           system_defaults=system_defaults)


@web_rrhh_bp.route("/rrhh/employees/import/template")
def employee_import_template():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(EMPLOYEE_CSV_HEADERS)
    writer.writerow(EMPLOYEE_EXAMPLE_ROW)
    buf = io.BytesIO(csv_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    return send_file(buf, mimetype="text/csv", as_attachment=True,
                     download_name="plantilla_empleados.csv")


@web_rrhh_bp.route("/rrhh/employees/import/upload", methods=["POST"])
def employee_import_upload():
    if _login_required():
        return jsonify({"success": False, "error": "No autorizado"}), 401

    import_type = request.form.get("import_type", "employees")
    file = request.files.get("file")
    if not file:
        return jsonify({"success": False, "error": "Por favor sube un archivo CSV válido."}), 400

    from app.utils.security import validate_uploaded_file, sanitize_filename

    valid, err_msg = validate_uploaded_file(file, allowed_extensions={'csv'})
    if not valid:
        return jsonify({"success": False, "error": err_msg}), 400

    os.makedirs(TEMP_IMPORT_DIR, exist_ok=True)
    safe_name = sanitize_filename(file.filename)
    file_id = f"temp_emp_{session['user']['uid']}_{uuid.uuid4().hex}_{safe_name}"
    temp_path = os.path.join(TEMP_IMPORT_DIR, file_id)
    file.save(temp_path)

    try:
        with open(temp_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
            first_line = f.readline()
            delimiter = _get_delimiter(first_line)
            f.seek(0)
            reader = csv.reader(f, delimiter=delimiter)
            headers = next(reader, None)
            if not headers:
                raise ValueError("El archivo CSV está vacío.")
            headers = [h.strip() for h in headers]
            data_rows = list(reader)
            row_count = len(data_rows)
            preview_rows = []
            for row in data_rows[:5]:
                if row:
                    preview_rows.append([cell.strip() for cell in row])
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({"success": False, "error": f"Error al analizar el archivo: {html.escape(str(e))}"}), 400

    if row_count == 0:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({"success": False, "error": "El archivo CSV no contiene filas de datos. Solo se encontró la cabecera."}), 400

    return jsonify({
        "success": True,
        "headers": headers,
        "preview_rows": preview_rows,
        "temp_filename": file_id,
        "row_count": row_count,
        "delimiter": delimiter,
        "target_fields": EMPLOYEE_TARGET_FIELDS,
    })


@web_rrhh_bp.route("/rrhh/employees/import/ai-suggest", methods=["POST"])
def employee_import_ai_suggest():
    if _login_required():
        return jsonify({"success": False, "message": "No autorizado"}), 401

    owner_uid, _ = _get_owner_uid_and_sandbox()
    data = request.get_json() or {}
    headers = data.get("headers", [])
    target_fields = data.get("target_fields", [])

    if not headers or not target_fields:
        return jsonify({"success": False, "message": "Datos faltantes."}), 400

    res = AIService.suggest_mapping(owner_uid, headers, target_fields)
    return jsonify(res)


@web_rrhh_bp.route("/rrhh/employees/import/process", methods=["POST"])
def employee_import_process():
    if _login_required():
        return jsonify({"success": False, "error": "No autorizado"}), 401

    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    user_email = session.get("user", {}).get("email", "")

    temp_filename = request.form.get("temp_filename")
    if not temp_filename:
        return jsonify({"success": False, "error": "Información de importación incompleta."}), 400

    temp_path = os.path.join(TEMP_IMPORT_DIR, temp_filename)
    if not os.path.exists(temp_path):
        return jsonify({"success": False, "error": "El archivo temporal ya no existe. Intenta subirlo de nuevo."}), 400

    mapping = {}
    for key, value in request.form.items():
        if key.startswith("map_") and value:
            field_id = key.replace("map_", "")
            try:
                mapping[field_id] = int(value)
            except ValueError:
                pass

    os.makedirs(JOB_DIR, exist_ok=True)
    job_id = str(uuid.uuid4())
    job_file = os.path.join(JOB_DIR, f"{job_id}.json")

    def _write_job(state):
        with open(job_file, 'w') as jf:
            json.dump(state, jf, default=str)

    try:
        with open(temp_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
            first_line = f.readline()
            delimiter = _get_delimiter(first_line)
            f.seek(0)
            reader = csv.reader(f, delimiter=delimiter)
            next(reader, None)
            rows = list(reader)
    except Exception as e:
        return jsonify({"success": False, "error": f"Error al leer el archivo: {html.escape(str(e))}"}), 500

    total = len([r for r in rows if r])
    if total == 0:
        return jsonify({"success": False, "error": "No hay filas de datos para procesar."}), 400

    state = {
        "job_id": job_id, "status": "processing", "total": total,
        "processed": 0, "imported": 0, "skipped": 0, "errors": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _write_job(state)

    from app.services import hr_data_service as hr
    from app.services.payroll_audit_service import log_action

    existing_candidates = hr.get_employees(owner_uid, sandbox=sandbox)
    existing_cedulas = set()
    for e in existing_candidates:
        c = (e.get("cedula") or e.get("idNumber") or "").strip()
        if c:
            existing_cedulas.add(c)

    field_defaults = {}
    for key, value in request.form.items():
        if key.startswith("default_") and value.strip():
            field_defaults[key.replace("default_", "")] = value.strip()

    def _get_val(row_data, field_id, default=""):
        if field_id in mapping and len(row_data) > mapping[field_id]:
            val = row_data[mapping[field_id]].strip()
            if val:
                return val
        return field_defaults.get(field_id, default)

    def process_rows():
        imported = 0
        skipped = 0
        errors = []
        processed = 0
        try:
            update_every = max(1, total // 20)

            for row_idx, row_data in enumerate(rows):
                if not row_data:
                    continue
                processed += 1
                row_num = row_idx + 2

                try:
                    first_name = _get_val(row_data, "firstName")
                    first_last_name = _get_val(row_data, "firstLastName")
                    id_number = re.sub(r'\D', '', _get_val(row_data, "idNumber"))
                    email = _get_val(row_data, "email")
                    municipality = _get_val(row_data, "municipality")
                    address = _get_val(row_data, "address")
                    hire_date = _get_val(row_data, "hireDate")
                    contract_type = _get_val(row_data, "contractType")
                    salary = _sanitize_float_import(_get_val(row_data, "salary"))
                    workday = _get_val(row_data, "workday", "completa")
                    tss_key = _get_val(row_data, "tssKey")
                    position = _get_val(row_data, "position")
                    area = _get_val(row_data, "area")
                    department_catalog = _get_val(row_data, "department_catalog")
                    payment_method = _get_val(row_data, "paymentMethod")
                    account_number = _get_val(row_data, "accountNumber")
                    bank = _get_val(row_data, "bank")
                    account_type = _get_val(row_data, "accountType")

                    if not first_name:
                        errors.append({"row": row_num, "reason": "Falta primer nombre (firstName)"})
                        skipped += 1
                        continue
                    if not first_last_name:
                        errors.append({"row": row_num, "reason": "Falta primer apellido (firstLastName)"})
                        skipped += 1
                        continue
                    if not id_number:
                        errors.append({"row": row_num, "reason": "Falta número de identificación (idNumber)"})
                        skipped += 1
                        continue
                    if not email:
                        errors.append({"row": row_num, "reason": "Falta correo electrónico (email)"})
                        skipped += 1
                        continue
                    if not municipality:
                        errors.append({"row": row_num, "reason": "Falta municipio (municipality)"})
                        skipped += 1
                        continue
                    if not address:
                        errors.append({"row": row_num, "reason": "Falta dirección (address)"})
                        skipped += 1
                        continue
                    if not hire_date:
                        errors.append({"row": row_num, "reason": "Falta fecha de contratación (hireDate)"})
                        skipped += 1
                        continue
                    try:
                        if re.match(r'^\d{2}/\d{2}/\d{4}$', hire_date):
                            dt = datetime.strptime(hire_date, "%d/%m/%Y")
                            hire_date = dt.strftime("%Y-%m-%d")
                        elif re.match(r'^\d{4}-\d{2}-\d{2}$', hire_date):
                            datetime.strptime(hire_date, "%Y-%m-%d")
                        elif re.match(r'^\d{2}-\d{2}-\d{4}$', hire_date):
                            dt = datetime.strptime(hire_date, "%d-%m-%Y")
                            hire_date = dt.strftime("%Y-%m-%d")
                        elif re.match(r'^\d{2}/\d{2}/\d{2}$', hire_date):
                            dt = datetime.strptime(hire_date, "%d/%m/%y")
                            hire_date = dt.strftime("%Y-%m-%d")
                        else:
                            raise ValueError
                    except Exception:
                        errors.append({"row": row_num, "reason": f"Fecha de contratación inválida: '{hire_date}'. Use DD/MM/AAAA o AAAA-MM-DD."})
                        skipped += 1
                        continue
                    if not contract_type:
                        errors.append({"row": row_num, "reason": "Falta tipo de contrato (contractType)"})
                        skipped += 1
                        continue
                    if salary <= 0:
                        errors.append({"row": row_num, "reason": "Salario inválido o faltante (salary)"})
                        skipped += 1
                        continue
                    if not workday:
                        errors.append({"row": row_num, "reason": "Falta jornada (workday)"})
                        skipped += 1
                        continue
                    if not tss_key or not re.match(r'^\d{3}$', tss_key):
                        errors.append({"row": row_num, "reason": "Falta o es inválida la clave TSS (tssKey). Debe ser 3 dígitos."})
                        skipped += 1
                        continue
                    if not position:
                        errors.append({"row": row_num, "reason": "Falta cargo (position)"})
                        skipped += 1
                        continue
                    if not area:
                        errors.append({"row": row_num, "reason": "Falta área (area)"})
                        skipped += 1
                        continue

                    hr.find_or_create_catalog_item(owner_uid, "positions", position, sandbox=sandbox)
                    if department_catalog:
                        hr.find_or_create_catalog_item(owner_uid, "departments", department_catalog, sandbox=sandbox)

                    if not payment_method:
                        errors.append({"row": row_num, "reason": "Falta método de pago (paymentMethod)"})
                        skipped += 1
                        continue
                    if not account_number:
                        errors.append({"row": row_num, "reason": "Falta número de cuenta (accountNumber)"})
                        skipped += 1
                        continue
                    if not bank:
                        errors.append({"row": row_num, "reason": "Falta banco (bank)"})
                        skipped += 1
                        continue
                    if not account_type:
                        errors.append({"row": row_num, "reason": "Falta tipo de cuenta (accountType)"})
                        skipped += 1
                        continue

                    if id_number in existing_cedulas:
                        errors.append({"row": row_num, "reason": f"La cédula {id_number} ya está registrada en el sistema."})
                        skipped += 1
                        continue

                    middle_name = _get_val(row_data, "middleName")
                    second_last_name = _get_val(row_data, "secondLastName")

                    emp_id = str(uuid.uuid4())
                    data = {
                        "id": emp_id,
                        "idType": _get_val(row_data, "idType", "cedula"),
                        "idNumber": id_number,
                        "cedula": id_number,
                        "firstName": first_name,
                        "middleName": middle_name,
                        "lastName": first_last_name,
                        "firstLastName": first_last_name,
                        "secondLastName": second_last_name,
                        "fullName": " ".join(p for p in [first_name, middle_name, first_last_name, second_last_name] if p),
                        "position": position,
                        "area": area,
                        "costCenter": _get_val(row_data, "costCenter", area),
                        "department": department_catalog or area,
                        "branchId": _get_val(row_data, "branchId", ""),
                        "hireDate": hire_date,
                        "salary": salary,
                        "baseSalary": salary,
                        "salaryType": "fijo",
                        "status": "activo",
                        "email": email,
                        "phone": re.sub(r'\D', '', _get_val(row_data, "phone")),
                        "address": address,
                        "municipality": municipality,
                        "contractType": contract_type,
                        "paymentFrequency": _get_val(row_data, "paymentFrequency"),
                        "workday": workday,
                        "isVigilante": _get_val(row_data, "isVigilante").lower() == "si",
                        "tssKey": tss_key,
                        "paymentMethod": payment_method,
                        "accountNumber": account_number,
                        "bank": bank,
                        "accountType": account_type,
                        "emergencyContact": _get_val(row_data, "emergencyContact"),
                        "emergencyPhone": re.sub(r'\D', '', _get_val(row_data, "emergencyPhone")),
                        "afpProvider": _get_val(row_data, "afpProvider"),
                        "notes": _get_val(row_data, "notes") or "Importado masivamente desde CSV.",
                        "gender": _get_val(row_data, "gender"),
                        "birthDate": _get_val(row_data, "birthDate"),
                        "probationEndDate": _get_val(row_data, "probationEndDate"),
                        "reportsTo": _get_val(row_data, "reportsTo"),
                        "maritalStatus": _get_val(row_data, "maritalStatus"),
                        "occupationCode": _get_val(row_data, "occupationCode"),
                        "weeklyHours": int(_get_val(row_data, "weeklyHours", "44") or 44),
                        "workShift": int(_get_val(row_data, "workShift", "1") or 1),
                        "educationLevel": int(_get_val(row_data, "educationLevel", "0") or 0),
                        "vacationGranted": int(_get_val(row_data, "vacationGranted", "1") or 1),
                        "nationality": 1,
                    }

                    hr.save_employee(owner_uid, emp_id, data, sandbox=sandbox)

                    if salary > 0:
                        history_id = str(uuid.uuid4())
                        hr.save_salary_history_entry(owner_uid, {
                            "id": history_id,
                            "employeeId": emp_id,
                            "amount": salary,
                            "previousAmount": 0.0,
                            "effectiveDate": hire_date,
                            "endDate": "",
                            "reason": "Salario inicial (importación masiva)",
                            "approvedBy": user_email,
                            "createdAt": date.today().isoformat(),
                        }, sandbox=sandbox)

                    log_action(owner_uid, "create", "employee", emp_id, user_email,
                               changes={"name": data["fullName"], "salary": salary, "source": "csv_import"},
                               sandbox=sandbox)

                    existing_cedulas.add(id_number)
                    imported += 1

                except Exception as e:
                    errors.append({"row": row_num, "reason": f"Error inesperado: {html.escape(str(e))}"})
                    skipped += 1

                if processed % update_every == 0 or processed == total:
                    current_state = {
                        "job_id": job_id, "status": "processing", "total": total,
                        "processed": processed, "imported": imported, "skipped": skipped,
                        "errors": errors[-30:],
                    }
                    try:
                        _write_job(current_state)
                    except Exception as e:
                        print(f"⚠️ [import] Error escribiendo progreso: {e}")

            final_state = {
                "job_id": job_id, "status": "completed", "total": total,
                "processed": processed, "imported": imported, "skipped": skipped,
                "errors": errors,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            try:
                _write_job(final_state)
            except Exception as e:
                print(f"⚠️ [import] Error escribiendo estado final: {e}")
        except Exception as e:
            print(f"⚠️ [import] Error fatal en process_rows: {e}")
            error_state = {
                "job_id": job_id, "status": "failed", "total": total,
                "processed": processed, "imported": imported, "skipped": skipped,
                "errors": errors[-30:] if errors else [{"row": 0, "reason": f"Error fatal: {html.escape(str(e))}"}],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            }
            try:
                _write_job(error_state)
            except Exception:
                pass

    thread = threading.Thread(target=process_rows)
    thread.daemon = True
    thread.start()

    return jsonify({"success": True, "job_id": job_id, "total": total})


@web_rrhh_bp.route("/rrhh/employees/import/status/<job_id>")
def employee_import_status(job_id):
    if _login_required():
        return jsonify({"status": "not_found", "error": "No autorizado"}), 401
    job_file = os.path.join(JOB_DIR, job_id + ".json")
    if os.path.exists(job_file):
        try:
            with open(job_file, 'r') as jf:
                state = json.load(jf)
            return jsonify(state)
        except Exception:
            return jsonify({"status": "not_found", "error": "Error al leer el estado del job"}), 500
    return jsonify({"status": "not_found", "error": "Job no encontrado"}), 404


