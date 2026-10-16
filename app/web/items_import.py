"""Catálogo de Artículos — Importación masiva CSV con asistente de mapeo inteligente.

Replica el esquema de 4 pasos usado en RRHH (app/web/rrhh/employee_import.py):
Plantilla → Subir → Mapeo (auto-detectar + Sugerir con IA) → Procesar.
"""

from datetime import datetime, timezone
from flask import (
    render_template, request, redirect, url_for, session, jsonify, send_file, g,
)
from app.web.invoices import web_invoices_bp
from app.services.db_service import DatabaseService
from app.services.ai_service import AIService
from app.utils.decorators import check_permission
from app.extensions import limiter
import csv, html, io, json, os, uuid, threading

TEMP_IMPORT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'uploads', 'temp_imports'
)
JOB_DIR = os.path.join(TEMP_IMPORT_DIR, 'jobs')

ITEM_CSV_FIELDS = [
    ("*name", "Nombre o Descripción", True, ["nombre", "name", "producto", "servicio", "descripcion", "item", "articulo", "artículo"]),
    ("*price", "Precio de Venta", True, ["precio", "price", "venta", "monto", "precio_venta", "precio de venta"]),
    ("itbisRate", "Tasa de ITBIS", False, ["itbis", "tasa", "impuesto", "tax", "itbisrate", "tasa_itbis", "tasa itbis"]),
    ("type", "Tipo (Bien / Servicio)", False, ["tipo", "type", "tipo_bien_o_servicio", "tipo bien o servicio", "bien_servicio"]),
    ("categoryId", "Categoría", False, ["categoria", "categoría", "category", "linea", "línea", "grupo"]),
    ("code", "Código SKU Local", False, ["codigo", "código", "code", "sku", "referencia", "codigo_sku"]),
    ("barcode", "Código de Barra", False, ["barcode", "barra", "codigo_barra", "código de barra", "escaner"]),
    ("unit", "Unidad de Medida", False, ["unidad", "unit", "medida", "unidad_medida", "unidad de medida"]),
    ("costPrice", "Precio de Costo", False, ["costo", "cost", "compra", "precio_costo", "precio costo"]),
    ("minStock", "Stock Mínimo Alerta", False, ["minimo", "mínimo", "min", "alerta", "stock_minimo"]),
    ("maxStock", "Stock Máximo", False, ["maximo", "máximo", "max", "stock_maximo"]),
    ("rackLocation", "Ubicación Física", False, ["ubicacion", "ubicación", "location", "pasillo", "rack", "gondola", "góndola"]),
    ("codigoImpuesto", "Código ISC DGII (Selectivo)", False, ["isc", "selectivo", "codigoimpuesto", "impuestoadicional", "codigo_impuesto_selectivo"]),
    ("tasaImpuestoAdicional", "Tasa/Monto ISC", False, ["tasaisc", "montoisc", "tasaadicional", "tasa_impuesto_selectivo"]),
    ("supplierName", "Proveedor Principal", False, ["proveedor", "supplier", "vendor", "suplidor"]),
    ("wholesalePrice", "Precio al por Mayor", False, ["mayorista", "wholesale", "precio_mayor", "precio_mayorista"]),
    ("brand", "Marca", False, ["marca", "brand", "fabricante"]),
    ("imageUrl", "URL de Imagen", False, ["imagen", "image", "foto", "url", "imagen_url"]),
    ("isActive", "Estado (Activo/Inactivo)", False, ["estado", "status", "activo", "active"]),
]

ITEM_REQUIRED_FIELDS = [f[0].lstrip("*") for f in ITEM_CSV_FIELDS if f[2]]
ITEM_TARGET_FIELDS = [
    {"id": f[0].lstrip("*"), "name": f"{f[1]}{' *' if f[2] else ''}", "required": f[2], "suggestions": f[3]}
    for f in ITEM_CSV_FIELDS
]
ITEM_CSV_HEADERS = [f[0] for f in ITEM_CSV_FIELDS]
ITEM_EXAMPLE_ROWS = [
    ["Laptop Dell Latitude", "45000.00", "0.18", "Bien", "Electrónica", "PROD-001",
     "7460123456789", "Unidad", "35000.00", "5", "50", "Pasillo 3, Góndola A", "", "0.0",
     "Dell SRL", "42000.00", "Dell", "https://example.com/dell.jpg", "Activo"],
    ["Asesoría Legal por Hora", "3500.00", "0.0", "Servicio", "Servicios", "SERV-002",
     "", "Hora", "1500.00", "0", "0", "", "", "0.0",
     "", "3500.00", "", "", "Activo"],
]

ITEM_TYPE_OPTIONS = ["Bien", "Servicio"]
ITEM_ITBIS_OPTIONS = ["0.18", "0.16", "0.0"]
ITEM_UNIT_OPTIONS = ["Unidad", "Hora", "Servicio", "Caja", "Mes", "Otros"]


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


def _normalize_type(val):
    v = (val or "").strip().lower()
    if v in ("servicio", "servicios", "service", "s"):
        return "Servicio"
    return "Bien"


def _parse_is_active(val):
    v = (val or "").strip().lower()
    if not v:
        return True
    return v not in ['inactivo', 'false', '0', 'no', 'disabled', 'inactive']


@web_invoices_bp.route('/items/import')
def items_import():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageCatalog'):
        return render_template('auth/restricted.html', feature_name="Importar Catálogo CSV",
                               required_permission="canManageCatalog"), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    categories_list = DatabaseService.get_categories(
        owner_uid, company_id=company_id, sandbox=sandbox,
        branch_id=g.get('branch_id'), project_id=g.get('project_id'),
    )
    category_names = sorted({c.get('name', '') for c in categories_list if c.get('name')})

    system_defaults = {
        "type": ITEM_TYPE_OPTIONS,
        "itbisRate": ITEM_ITBIS_OPTIONS,
        "unit": ITEM_UNIT_OPTIONS,
        "categoryId": category_names,
        "isActive": ["Activo", "Inactivo"],
    }

    return render_template('items/import.html', active_page='items',
                           target_fields=ITEM_TARGET_FIELDS,
                           required_fields=ITEM_REQUIRED_FIELDS,
                           system_defaults=system_defaults)


@web_invoices_bp.route('/items/import/template')
def items_import_template():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageCatalog'):
        return render_template('auth/restricted.html', feature_name="Descargar Plantilla CSV",
                               required_permission="canManageCatalog"), 403
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(ITEM_CSV_HEADERS)
    for row in ITEM_EXAMPLE_ROWS:
        writer.writerow(row)
    buf = io.BytesIO(csv_buf.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    return send_file(buf, mimetype="text/csv", as_attachment=True,
                     download_name="plantilla_articulos.csv")


@web_invoices_bp.route('/items/import/upload', methods=['POST'])
def items_import_upload():
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    if not check_permission('canManageCatalog'):
        return jsonify({"success": False, "error": "Sin permiso para importar catálogo."}), 403

    file = request.files.get("file")
    if not file:
        return jsonify({"success": False, "error": "Por favor sube un archivo CSV válido."}), 400

    from app.utils.security import validate_uploaded_file, sanitize_filename

    valid, err_msg = validate_uploaded_file(file, allowed_extensions={'csv'})
    if not valid:
        return jsonify({"success": False, "error": err_msg}), 400

    os.makedirs(TEMP_IMPORT_DIR, exist_ok=True)
    safe_name = sanitize_filename(file.filename)
    file_id = f"temp_item_{session['user']['uid']}_{uuid.uuid4().hex}_{safe_name}"
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
        "target_fields": ITEM_TARGET_FIELDS,
    })


@web_invoices_bp.route('/items/import/ai-suggest', methods=['POST'])
def items_import_ai_suggest():
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


@web_invoices_bp.route('/items/import/process', methods=['POST'])
def items_import_process():
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    if not check_permission('canManageCatalog'):
        return jsonify({"success": False, "error": "Sin permiso para importar catálogo."}), 403

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
                if not row_data or not any(c.strip() for c in row_data):
                    continue
                processed += 1
                row_num = row_idx + 2

                try:
                    name = _get_val(row_data, "name").strip()
                    if not name:
                        errors.append({"row": row_num, "reason": "Falta el nombre o descripción del artículo (name)."})
                        skipped += 1
                        continue

                    price = _sanitize_float_import(_get_val(row_data, "price"), 0.0)
                    if price < 0:
                        errors.append({"row": row_num, "reason": f"Precio inválido: '{_get_val(row_data, 'price')}'."})
                        skipped += 1
                        continue

                    cat_name = _get_val(row_data, "categoryId").strip()
                    if cat_name:
                        category_id = DatabaseService.get_or_create_category_by_name(
                            owner_uid, cat_name, company_id=company_id, sandbox=sandbox)
                    else:
                        category_id = "general"

                    item_id = str(uuid.uuid4())
                    item_dict = {
                        "code": _get_val(row_data, "code").strip() or f"PROD-{uuid.uuid4().hex[:6].upper()}",
                        "barcode": _get_val(row_data, "barcode").strip(),
                        "type": _normalize_type(_get_val(row_data, "type")),
                        "name": name,
                        "price": price,
                        "unit": _get_val(row_data, "unit", "Unidad").strip() or "Unidad",
                        "itbisRate": _sanitize_float_import(_get_val(row_data, "itbisRate"), 0.18),
                        "costPrice": _sanitize_float_import(_get_val(row_data, "costPrice")),
                        "minStock": _sanitize_float_import(_get_val(row_data, "minStock")),
                        "maxStock": _sanitize_float_import(_get_val(row_data, "maxStock")),
                        "rackLocation": _get_val(row_data, "rackLocation").strip(),
                        "categoryId": category_id,
                        "codigoImpuesto": _get_val(row_data, "codigoImpuesto").strip(),
                        "tasaImpuestoAdicional": _sanitize_float_import(_get_val(row_data, "tasaImpuestoAdicional")),
                        "supplierName": _get_val(row_data, "supplierName").strip(),
                        "wholesalePrice": _sanitize_float_import(_get_val(row_data, "wholesalePrice")),
                        "brand": _get_val(row_data, "brand").strip(),
                        "imageUrl": _get_val(row_data, "imageUrl").strip(),
                        "totalStock": 0.0,
                        "createdAt": datetime.now(timezone.utc).isoformat(),
                        "isActive": _parse_is_active(_get_val(row_data, "isActive")),
                    }
                    DatabaseService.save_item(owner_uid, item_id, item_dict,
                                              company_id=company_id, sandbox=sandbox)
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
                        print(f"⚠️ [items-import] Error escribiendo progreso: {e}")

            final_state = {
                "job_id": job_id, "status": "completed", "total": total,
                "processed": processed, "imported": imported, "skipped": skipped,
                "errors": errors,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            try:
                _write_job(final_state)
            except Exception as e:
                print(f"⚠️ [items-import] Error escribiendo estado final: {e}")
        except Exception as e:
            print(f"⚠️ [items-import] Error fatal en process_rows: {e}")
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


@web_invoices_bp.route('/items/import/status/<job_id>')
@limiter.exempt
def items_import_status(job_id):
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
