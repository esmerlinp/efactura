"""Clientes (CRM) — Importación masiva CSV con asistente de mapeo inteligente.

Replica el esquema de 4 pasos usado en Catálogo (app/web/items_import.py) y
RRHH (app/web/rrhh/employee_import.py):
Plantilla → Subir → Mapeo (auto-detectar + Sugerir con IA) → Procesar.
"""

import csv
import html
import io
import json
import os
import random
import re
import threading
import uuid
from datetime import datetime, timezone

from flask import (
    render_template, request, redirect, url_for, session, jsonify, send_file,
)
from app.web.clients import web_clients_bp
from app.services.db_service import DatabaseService
from app.services.ai_service import AIService
from app.utils.decorators import check_permission
from app.extensions import limiter

TEMP_IMPORT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'uploads', 'temp_imports'
)
JOB_DIR = os.path.join(TEMP_IMPORT_DIR, 'jobs')

CLIENT_CSV_FIELDS = [
    ("*razonSocial", "Razón Social / Nombre Completo", True, ["razon", "nombre", "cliente", "name", "company", "social", "razon_social", "razón social"]),
    ("*rnc", "RNC / Cédula", True, ["rnc", "cedula", "cédula", "documento", "id", "tax", "rnc/cedula", "identificacion", "identificación"]),
    ("email", "Correo Electrónico", False, ["email", "correo", "mail", "contacto", "correo_electronico"]),
    ("companyEmail", "Correo Empresarial", False, ["correo_empresa", "companyemail", "email_empresa", "correo empresarial"]),
    ("telefono", "Teléfono", False, ["telefono", "teléfono", "phone", "celular", "tel"]),
    ("direccion", "Dirección Física", False, ["direccion", "dirección", "address", "calle", "ciudad"]),
    ("customer_category", "Categoría (NORMAL / FOREIGN)", False, ["categoria_cliente", "customer_category", "categoria", "categoría", "tipo_cliente"]),
    ("foreignTaxId", "Identificador Extranjero", False, ["foreign", "foreigntaxid", "identificador_extranjero", "tax_extranjero", "extranjero"]),
    ("crmNotes", "Notas CRM", False, ["notas", "notes", "comentario", "crm", "observaciones"]),
    ("nextContactDate", "Próxima Fecha de Contacto", False, ["contacto", "fecha", "proximo", "próximo", "next", "nextcontactdate", "proximo_contacto"]),
    ("pipelineStage", "Etapa del Embudo", False, ["etapa", "stage", "pipeline", "estado", "embudo"]),
    ("creditLimit", "Límite de Crédito", False, ["credito", "crédito", "credit", "limite", "límite", "creditlimit"]),
    ("regimenDgii", "Régimen DGII", False, ["regimen", "régimen", "regimendgii", "regimen_dgii"]),
    ("regimenDgiiNormalized", "Régimen DGII Normalizado", False, ["regimen_normalizado", "regimendgiinormalized"]),
    ("estadoDgii", "Estado DGII", False, ["estadodgii", "estado_dgii", "estado_dgi"]),
    ("categoriaDgii", "Categoría DGII", False, ["categoriadgii", "categoria_dgii"]),
    ("actividadDgii", "Actividad DGII", False, ["actividaddgii", "actividad_dgii"]),
]

CLIENT_REQUIRED_FIELDS = [f[0].lstrip("*") for f in CLIENT_CSV_FIELDS if f[2]]
CLIENT_TARGET_FIELDS = [
    {"id": f[0].lstrip("*"), "name": f"{f[1]}{' *' if f[2] else ''}", "required": f[2], "suggestions": f[3]}
    for f in CLIENT_CSV_FIELDS
]
CLIENT_CSV_HEADERS = [f[0] for f in CLIENT_CSV_FIELDS]
CLIENT_EXAMPLE_ROW = [
    "Comercial Ejemplo SRL", "131880681", "contacto@ejemplo.com.do", "",
    "8095551234", "Av. Winston Churchill #45, Santo Domingo", "NORMAL", "",
    "Cliente de ejemplo para importación masiva.", "2026-01-15", "Cliente Activo",
    "50000", "", "", "", "", "",
]

PIPELINE_STAGE_OPTIONS = ["Prospecto", "Contactado", "En Negociación", "Cliente Activo"]
CUSTOMER_CATEGORY_OPTIONS = ["NORMAL", "FOREIGN"]


def _get_delimiter(first_line):
    for delimiter in [';', '\t', ',']:
        if delimiter in first_line:
            return delimiter
    return ','


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


def _normalize_date(val):
    """Normaliza fechas DD/MM/AAAA o AAAA-MM-DD a AAAA-MM-DD; vacío si no reconoce."""
    v = (val or "").strip()
    if not v:
        return ""
    if ' ' in v:
        v = v.split(' ')[0]
    try:
        if re.match(r'^\d{2}/\d{2}/\d{4}$', v):
            return datetime.strptime(v, "%d/%m/%Y").strftime("%Y-%m-%d")
        if re.match(r'^\d{4}-\d{2}-\d{2}$', v):
            datetime.strptime(v, "%Y-%m-%d")
            return v
        if re.match(r'^\d{2}-\d{2}-\d{4}$', v):
            return datetime.strptime(v, "%d-%m-%Y").strftime("%Y-%m-%d")
    except Exception:
        return ""
    return v


@web_clients_bp.route('/clients/import')
def clients_import():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not (check_permission('canCreateClient') or check_permission('canClients')):
        return render_template('auth/restricted.html', feature_name="Importar Clientes CSV",
                               required_permission="canCreateClient"), 403

    system_defaults = {
        "pipelineStage": PIPELINE_STAGE_OPTIONS,
        "customer_category": CUSTOMER_CATEGORY_OPTIONS,
    }

    return render_template('clients/import.html', active_page='clients',
                           target_fields=CLIENT_TARGET_FIELDS,
                           required_fields=CLIENT_REQUIRED_FIELDS,
                           system_defaults=system_defaults)


@web_clients_bp.route('/clients/import/template')
def clients_import_template():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not (check_permission('canCreateClient') or check_permission('canClients')):
        return render_template('auth/restricted.html', feature_name="Descargar Plantilla CSV",
                               required_permission="canCreateClient"), 403
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(CLIENT_CSV_HEADERS)
    writer.writerow(CLIENT_EXAMPLE_ROW)
    buf = io.BytesIO(csv_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    return send_file(buf, mimetype="text/csv", as_attachment=True,
                     download_name="plantilla_clientes.csv")


@web_clients_bp.route('/clients/import/upload', methods=['POST'])
def clients_import_upload():
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    if not (check_permission('canCreateClient') or check_permission('canClients')):
        return jsonify({"success": False, "error": "Sin permiso para importar clientes."}), 403

    file = request.files.get("file")
    if not file:
        return jsonify({"success": False, "error": "Por favor sube un archivo CSV válido."}), 400

    from app.utils.security import validate_uploaded_file, sanitize_filename

    valid, err_msg = validate_uploaded_file(file, allowed_extensions={'csv'})
    if not valid:
        return jsonify({"success": False, "error": err_msg}), 400

    os.makedirs(TEMP_IMPORT_DIR, exist_ok=True)
    safe_name = sanitize_filename(file.filename)
    file_id = f"temp_client_{session['user']['uid']}_{uuid.uuid4().hex}_{safe_name}"
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
            row_count = len([r for r in data_rows if r])
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
        "target_fields": CLIENT_TARGET_FIELDS,
    })


@web_clients_bp.route('/clients/import/ai-suggest', methods=['POST'])
def clients_import_ai_suggest():
    if 'user' not in session:
        return jsonify({"success": False, "message": "No autorizado"}), 401

    owner_uid = session['user']['ownerUID']
    data = request.get_json() or {}
    headers = data.get("headers", [])
    target_fields = data.get("target_fields", [])

    if not headers or not target_fields:
        return jsonify({"success": False, "message": "Datos faltantes."}), 400

    res = AIService.suggest_mapping(owner_uid, headers, target_fields,
                                    company_id=session.get('selected_company_id'))
    return jsonify(res)


@web_clients_bp.route('/clients/import/process', methods=['POST'])
def clients_import_process():
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    if not (check_permission('canCreateClient') or check_permission('canClients')):
        return jsonify({"success": False, "error": "Sin permiso para importar clientes."}), 403

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

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

    field_defaults = {}
    for key, value in request.form.items():
        if key.startswith("default_") and value.strip():
            field_defaults[key.replace("default_", "")] = value.strip()

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

    existing_rncs = set()
    try:
        existing_clients = DatabaseService.get_clients(
            owner_uid, company_id=company_id, sandbox=sandbox) or []
        for c in existing_clients:
            r = (c.get("rnc") or "").strip()
            if r:
                existing_rncs.add(r)
    except Exception as e:
        print(f"⚠️ [clients-import] No se pudo cargar RNCs existentes: {e}")

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
        used_rncs = set()
        try:
            update_every = max(1, total // 20)

            for row_idx, row_data in enumerate(rows):
                if not row_data or not any(c.strip() for c in row_data):
                    continue
                processed += 1
                row_num = row_idx + 2

                try:
                    rnc = re.sub(r'\D', '', _get_val(row_data, "rnc"))
                    razon_social = _get_val(row_data, "razonSocial").strip()

                    if not razon_social:
                        errors.append({"row": row_num, "reason": "Falta Razón Social (razonSocial)."})
                        skipped += 1
                        continue
                    if not rnc:
                        errors.append({"row": row_num, "reason": "Falta RNC / Cédula (rnc)."})
                        skipped += 1
                        continue
                    if rnc in existing_rncs or rnc in used_rncs:
                        errors.append({"row": row_num, "reason": f"El RNC {rnc} ya está registrado."})
                        skipped += 1
                        continue

                    customer_category = (_get_val(row_data, "customer_category", "NORMAL") or "NORMAL").strip().upper()
                    if customer_category not in ("NORMAL", "FOREIGN"):
                        customer_category = "NORMAL"
                    foreign_tax_id = _get_val(row_data, "foreignTaxId").strip() or (rnc if customer_category == "FOREIGN" else "")
                    access_pin = "".join([str(random.randint(0, 9)) for _ in range(6)])
                    credit_limit = _sanitize_float_import(_get_val(row_data, "creditLimit"), 0.0)
                    next_contact_date = _normalize_date(_get_val(row_data, "nextContactDate"))

                    client_id = str(uuid.uuid4())
                    client_dict = {
                        "rnc": rnc,
                        "razonSocial": razon_social,
                        "email": _get_val(row_data, "email").strip(),
                        "companyEmail": _get_val(row_data, "companyEmail").strip(),
                        "telefono": _get_val(row_data, "telefono").strip(),
                        "direccion": _get_val(row_data, "direccion").strip(),
                        "foreignTaxId": foreign_tax_id,
                        "crmNotes": _get_val(row_data, "crmNotes").strip() or "Importado masivamente desde CSV.",
                        "nextContactDate": next_contact_date,
                        "pipelineStage": _get_val(row_data, "pipelineStage", "Cliente Activo").strip() or "Cliente Activo",
                        "creditLimit": credit_limit,
                        "accessPin": access_pin,
                        "customer_category": customer_category,
                        "regimenDgii": _get_val(row_data, "regimenDgii").strip(),
                        "regimenDgiiNormalized": _get_val(row_data, "regimenDgiiNormalized").strip(),
                        "estadoDgii": _get_val(row_data, "estadoDgii").strip(),
                        "categoriaDgii": _get_val(row_data, "categoriaDgii").strip(),
                        "actividadDgii": _get_val(row_data, "actividadDgii").strip(),
                        "createdAt": datetime.now(timezone.utc).isoformat(),
                    }

                    DatabaseService.save_client(owner_uid, client_id, client_dict,
                                                company_id=company_id, sandbox=sandbox)

                    try:
                        from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_CLIENTES
                        AuditService.log_from_request(
                            owner_uid=owner_uid,
                            action=ACTION_CREATE,
                            module=MODULE_CLIENTES,
                            entity_id=client_id,
                            entity_label=f"Cliente importado (CSV): {razon_social} (RNC: {rnc})",
                            user_session=session.get('user', {}),
                            after=client_dict,
                            sandbox=sandbox,
                        )
                    except Exception as e:
                        print(f"⚠️ [clients-import] Error al auditar cliente: {e}")

                    used_rncs.add(rnc)
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
                        print(f"⚠️ [clients-import] Error escribiendo progreso: {e}")

            final_state = {
                "job_id": job_id, "status": "completed", "total": total,
                "processed": processed, "imported": imported, "skipped": skipped,
                "errors": errors,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            try:
                _write_job(final_state)
            except Exception as e:
                print(f"⚠️ [clients-import] Error escribiendo estado final: {e}")
        except Exception as e:
            print(f"⚠️ [clients-import] Error fatal en process_rows: {e}")
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


@web_clients_bp.route('/clients/import/status/<job_id>')
@limiter.exempt
def clients_import_status(job_id):
    if 'user' not in session:
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
