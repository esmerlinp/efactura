# app/web/import_mapper.py
import os
import csv
import uuid
import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.services.db_service import DatabaseService
from app.services.ai_service import AIService
from app.utils.decorators import check_permission

web_import_mapper_bp = Blueprint('web_import_mapper', __name__)

# Directorio temporal para archivos subidos
TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'static', 'uploads', 'temp_imports')

def get_delimiter(first_line):
    """Detecta el delimitador de un archivo CSV analizando su primera línea."""
    for delimiter in [';', '\t', ',']:
        if delimiter in first_line:
            return delimiter
    return ','

def sanitize_float(val, default=0.0):
    if not val:
        return default
    try:
        # Reemplazar comas decimales europeas/latinoamericanas por puntos
        val_clean = val.strip().replace('RD$', '').replace('$', '').replace(' ', '')
        if ',' in val_clean and '.' in val_clean:
            # Ej: 1,234.56 -> eliminar la coma
            val_clean = val_clean.replace(',', '')
        elif ',' in val_clean:
            # Ej: 1234,56 -> reemplazar coma por punto
            val_clean = val_clean.replace(',', '.')
        return float(val_clean)
    except Exception:
        return default

def sanitize_bool(val, default=None):
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    val_clean = str(val).strip().lower()
    if not val_clean:
        return default
    if val_clean in ['true', '1', 'si', 'sí', 'yes', 'y', 't']:
        return True
    if val_clean in ['false', '0', 'no', 'n', 'f']:
        return False
    return default

@web_import_mapper_bp.route('/import/upload', methods=['POST'])
def upload_file():
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json
    if 'user' not in session:
        if is_ajax: return jsonify({"success": False, "error": "No autorizado"}), 401
        return redirect(url_for('web_auth.login'))
    
    import_type = request.form.get('import_type')
    if import_type not in ['clients', 'products', 'invoices']:
        if is_ajax: return jsonify({"success": False, "error": "Tipo de importación no válido."}), 400
        flash('Tipo de importación no válido.', 'error')
        return redirect(url_for('web_dashboard.dashboard'))
        
    file = request.files.get('file')
    if not file or not file.filename.endswith('.csv'):
        if is_ajax: return jsonify({"success": False, "error": "Por favor sube un archivo CSV válido (.csv)."}), 400
        flash('Por favor sube un archivo CSV válido (.csv).', 'error')
        if import_type == 'clients':
            return redirect(url_for('web_clients.list_clients'))
        elif import_type == 'products':
            return redirect(url_for('web_invoices.list_items'))
        else:
            return redirect(url_for('web_invoices.list_invoices'))
            
    os.makedirs(TEMP_DIR, exist_ok=True)
    file_id = f"temp_{session['user']['uid']}_{import_type}_{uuid.uuid4().hex}.csv"
    temp_path = os.path.join(TEMP_DIR, file_id)
    file.save(temp_path)
    
    try:
        # Detectar el delimitador y leer cabeceras
        with open(temp_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
            first_line = f.readline()
            delimiter = get_delimiter(first_line)
            f.seek(0)
            
            reader = csv.reader(f, delimiter=delimiter)
            headers = next(reader, None)
            if not headers:
                raise ValueError("El archivo CSV está vacío.")
                
            headers = [h.strip() for h in headers]
            
            # Leer primeras 3 filas para vista previa
            preview_rows = []
            for _ in range(3):
                row = next(reader, None)
                if row:
                    preview_rows.append([cell.strip() for cell in row])
                else:
                    break
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        if is_ajax:
            return jsonify({"success": False, "error": f"Error al analizar el archivo: {str(e)}"}), 400
        flash(f'Error al analizar el archivo: {str(e)}', 'error')
        if import_type == 'clients':
            return redirect(url_for('web_clients.list_clients'))
        elif import_type == 'products':
            return redirect(url_for('web_invoices.list_items'))
        else:
            return redirect(url_for('web_invoices.list_invoices'))
            
    # Configurar campos destino del sistema
    target_fields = []
    if import_type == 'clients':
        target_fields = [
            {"id": "razonSocial", "name": "Razón Social / Nombre Completo", "required": True, "suggestions": ["razon", "nombre", "cliente", "name", "company", "social"]},
            {"id": "rnc", "name": "RNC / Cédula", "required": True, "suggestions": ["rnc", "cedula", "documento", "id", "tax", "rnc/cedula"]},
            {"id": "email", "name": "Correo Electrónico", "required": False, "suggestions": ["email", "correo", "mail", "contacto"]},
            {"id": "telefono", "name": "Teléfono", "required": False, "suggestions": ["telefono", "phone", "celular", "tel"]},
            {"id": "direccion", "name": "Dirección Física", "required": False, "suggestions": ["direccion", "address", "calle", "ciudad"]},
            {"id": "crmNotes", "name": "Notas del Cliente / CRM", "required": False, "suggestions": ["notas", "notes", "comentario", "crm"]},
            {"id": "nextContactDate", "name": "Próxima Fecha de Contacto (YYYY-MM-DD)", "required": False, "suggestions": ["contacto", "fecha", "proximo", "next"]},
            {"id": "pipelineStage", "name": "Etapa del Embudo (Prospecto, Contactado, etc.)", "required": False, "suggestions": ["etapa", "stage", "pipeline", "estado"]}
        ]
    elif import_type == 'products':
        target_fields = [
            {"id": "name", "name": "Nombre o Descripción", "required": True, "suggestions": ["nombre", "name", "producto", "servicio", "descripcion", "item"]},
            {"id": "price", "name": "Precio de Venta", "required": True, "suggestions": ["precio", "price", "venta", "monto"]},
            {"id": "itbisRate", "name": "Tasa de ITBIS (0.18, 0.16, 0.0)", "required": True, "suggestions": ["itbis", "tasa", "impuesto", "tax", "itbisrate"]},
            {"id": "type", "name": "Tipo (Bien / Servicio)", "required": True, "suggestions": ["tipo", "type"]},
            {"id": "categoryId", "name": "Categoría del Producto", "required": False, "suggestions": ["categoria", "category", "linea", "grupo"]},
            {"id": "code", "name": "Código SKU Local", "required": False, "suggestions": ["codigo", "code", "sku", "referencia"]},
            {"id": "barcode", "name": "Código de Barra", "required": False, "suggestions": ["barcode", "barra", "escaner"]},
            {"id": "unit", "name": "Unidad de Medida", "required": False, "suggestions": ["unidad", "unit", "medida"]},
            {"id": "costPrice", "name": "Precio de Costo", "required": False, "suggestions": ["costo", "cost", "compra"]},
            {"id": "minStock", "name": "Stock Mínimo Alerta", "required": False, "suggestions": ["minimo", "min", "alerta"]},
            {"id": "rackLocation", "name": "Ubicación Pasillo/Góndola", "required": False, "suggestions": ["ubicacion", "location", "pasillo", "rack"]},
            {"id": "codigoImpuesto", "name": "Código ISC DGII (Selectivo)", "required": False, "suggestions": ["isc", "selectivo", "codigoimpuesto", "impuestoadicional"]},
            {"id": "tasaImpuestoAdicional", "name": "Tasa/Monto ISC", "required": False, "suggestions": ["tasaisc", "montoisc", "tasaadicional"]},
            {"id": "supplierName", "name": "Proveedor Principal", "required": False, "suggestions": ["proveedor", "supplier", "vendor"]},
            {"id": "wholesalePrice", "name": "Precio al por Mayor", "required": False, "suggestions": ["mayorista", "wholesale", "precio_mayor"]},
            {"id": "brand", "name": "Marca", "required": False, "suggestions": ["marca", "brand", "fabricante"]},
            {"id": "maxStock", "name": "Stock Máximo", "required": False, "suggestions": ["maximo", "max", "stock_max"]},
            {"id": "imageUrl", "name": "URL de Imagen", "required": False, "suggestions": ["imagen", "image", "foto", "url"]},
            {"id": "isActive", "name": "Estado (Activo/Inactivo)", "required": False, "suggestions": ["estado", "status", "activo", "active"]}
        ]
    else: # Invoices
        target_fields = [
            {"id": "invoiceNumber", "name": "Número de Factura / Correlativo", "required": True, "suggestions": ["numero", "invoice", "factura", "id", "correlativo"]},
            {"id": "date", "name": "Fecha Emisión (YYYY-MM-DD)", "required": True, "suggestions": ["fecha", "date", "registro", "emision"]},
            {"id": "clientRNC", "name": "RNC / Cédula del Cliente", "required": True, "suggestions": ["rnc", "cedula", "cliente_rnc", "client_rnc"]},
            {"id": "clientName", "name": "Nombre / Razón Social Cliente", "required": True, "suggestions": ["cliente", "client", "nombre", "razon", "nombre_cliente"]},
            {"id": "subtotal", "name": "Subtotal Financiero", "required": True, "suggestions": ["subtotal", "sub_total", "neto"]},
            {"id": "totalITBIS", "name": "Total ITBIS", "required": True, "suggestions": ["itbis", "impuesto", "tax", "total_itbis"]},
            {"id": "total", "name": "Total General", "required": True, "suggestions": ["total", "pagar", "monto_total", "netpayable"]},
            {"id": "status", "name": "Estado (Cobrada, Emitida, Anulada)", "required": True, "suggestions": ["estado", "status", "situacion"]},
            {"id": "dueDate", "name": "Fecha de Vencimiento", "required": False, "suggestions": ["vence", "vencimiento", "duedate"]},
            {"id": "ecfType", "name": "Tipo Comprobante (Consumo, Crédito Fiscal)", "required": False, "suggestions": ["tipo", "ecftype", "comprobante"]},
            {"id": "encf", "name": "Número de Comprobante / e-NCF", "required": False, "suggestions": ["ncf", "encf", "comprobante_fiscal"]},
            {"id": "concept", "name": "Concepto / Descripción Única", "required": False, "suggestions": ["concepto", "descripcion", "detalle", "nota"]},
            {"id": "dgiiStatus", "name": "Estado DGII (ACCEPTED, PENDING, CONTINGENCY)", "required": False, "suggestions": ["dgiistatus", "estado_dgii", "dgii"]},
            {"id": "emisionMode", "name": "Modo Emisión (API, FALLBACK, IMPORT)", "required": False, "suggestions": ["emisionmode", "modo_emision", "modo"]},
            {"id": "isSyncedWithDGII", "name": "Sincronizada DGII (true/false)", "required": False, "suggestions": ["synced", "is_synced", "sincronizada"]},
            {"id": "stockReduced", "name": "Stock reducido (true/false)", "required": False, "suggestions": ["stock", "inventario", "stockreduced"]},
            {"id": "warehouseId", "name": "Almacén (ID)", "required": False, "suggestions": ["almacen", "warehouse", "warehouse_id"]}
        ]
        
    if is_ajax:
        return jsonify({
            "success": True,
            "import_type": import_type,
            "headers": headers,
            "preview_rows": preview_rows,
            "temp_filename": file_id,
            "target_fields": target_fields
        })

    return render_template(
        'import/mapper.html',
        import_type=import_type,
        headers=headers,
        preview_rows=preview_rows,
        temp_filename=file_id,
        target_fields=target_fields
    )

@web_import_mapper_bp.route('/import/ai-suggest', methods=['POST'])
def ai_suggest_mapping():
    if 'user' not in session:
        return jsonify({"success": False, "message": "No autorizado"}), 401
    
    owner_uid = session['user']['ownerUID']
    data = request.get_json() or {}
    headers = data.get('headers', [])
    target_fields = data.get('target_fields', [])
    
    if not headers or not target_fields:
        return jsonify({"success": False, "message": "Datos faltantes."}), 400
        
    res = AIService.suggest_mapping(owner_uid, headers, target_fields)
    return jsonify(res)

@web_import_mapper_bp.route('/import/process', methods=['POST'])
def process_import():
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json
    if 'user' not in session:
        if is_ajax: return jsonify({"success": False, "error": "No autorizado"}), 401
        return redirect(url_for('web_auth.login'))
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    import_type = request.form.get('import_type')
    temp_filename = request.form.get('temp_filename')
    
    if not temp_filename or not import_type:
        if is_ajax: return jsonify({"success": False, "error": "Información de importación incompleta."}), 400
        flash('Información de importación incompleta.', 'error')
        return redirect(url_for('web_dashboard.dashboard'))
        
    temp_path = os.path.join(TEMP_DIR, temp_filename)
    if not os.path.exists(temp_path):
        flash('El archivo temporal ya no existe. Intenta subirlo de nuevo.', 'error')
        return redirect(url_for('web_dashboard.dashboard'))
        
    # Obtener el mapa de campos de la solicitud
    # mapeo: { campo_efactura: indice_columna_csv }
    mapping = {}
    for key, value in request.form.items():
        if key.startswith('map_') and value:
            field_id = key.replace('map_', '')
            mapping[field_id] = int(value)
            
    count = 0
    try:
        with open(temp_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
            first_line = f.readline()
            delimiter = get_delimiter(first_line)
            f.seek(0)
            
            reader = csv.reader(f, delimiter=delimiter)
            next(reader, None) # Saltar cabecera
            
            for row in reader:
                if not row:
                    continue
                
                # Helper local para extraer valores del CSV basados en el mapa
                def get_val(field_id, default=""):
                    val = ""
                    if field_id in mapping and len(row) > mapping[field_id]:
                        val = row[mapping[field_id]].strip()
                    
                    if not val:
                        user_default = request.form.get(f'default_{field_id}', '').strip()
                        return user_default if user_default != '' else default
                    return val
                
                if import_type == 'clients':
                    rnc = get_val('rnc')
                    razon_social = get_val('razonSocial')
                    if not rnc or not razon_social:
                        continue
                        
                    client_id = str(uuid.uuid4())
                    client_dict = {
                        "rnc": rnc,
                        "razonSocial": razon_social,
                        "email": get_val('email'),
                        "telefono": get_val('telefono'),
                        "direccion": get_val('direccion'),
                        "crmNotes": get_val('crmNotes') or "Importado mediante asistente universal.",
                        "nextContactDate": get_val('nextContactDate'),
                        "pipelineStage": get_val('pipelineStage', 'Prospecto'),
                        "createdAt": datetime.utcnow().isoformat()
                    }
                    DatabaseService.save_client(owner_uid, client_id, client_dict, sandbox=sandbox)
                    count += 1
                    
                elif import_type == 'products':
                    name = get_val('name')
                    price = sanitize_float(get_val('price'))
                    if not name:
                        continue
                        
                    cat_name = get_val('categoryId')
                    if cat_name:
                        category_id = DatabaseService.get_or_create_category_by_name(owner_uid, cat_name, sandbox=sandbox)
                    else:
                        category_id = "general"

                    active_str = get_val('isActive', 'true').strip().lower()
                    is_active = active_str not in ['inactivo', 'false', '0', 'no', 'disabled']

                    item_id = str(uuid.uuid4())
                    item_dict = {
                        "code": get_val('code') or f"PROD-{uuid.uuid4().hex[:6].upper()}",
                        "barcode": get_val('barcode'),
                        "type": get_val('type', 'Bien'),
                        "name": name,
                        "price": price,
                        "unit": get_val('unit', 'Unidad'),
                        "itbisRate": sanitize_float(get_val('itbisRate'), 0.18),
                        "costPrice": sanitize_float(get_val('costPrice')),
                        "minStock": sanitize_float(get_val('minStock')),
                        "rackLocation": get_val('rackLocation'),
                        "categoryId": category_id,
                        "codigoImpuesto": get_val('codigoImpuesto'),
                        "tasaImpuestoAdicional": sanitize_float(get_val('tasaImpuestoAdicional')),
                        "totalStock": 0.0,
                        "createdAt": datetime.utcnow().isoformat(),
                        "isActive": is_active,
                        "supplierName": get_val('supplierName'),
                        "wholesalePrice": sanitize_float(get_val('wholesalePrice')),
                        "brand": get_val('brand'),
                        "maxStock": sanitize_float(get_val('maxStock')),
                        "imageUrl": get_val('imageUrl')
                    }
                    DatabaseService.save_item(owner_uid, item_id, item_dict, sandbox=sandbox)
                    count += 1
                    
                elif import_type == 'invoices':
                    inv_num = get_val('invoiceNumber')
                    date = get_val('date')
                    client_rnc = get_val('clientRNC')
                    client_name = get_val('clientName')
                    subtotal = sanitize_float(get_val('subtotal'))
                    total_itbis = sanitize_float(get_val('totalITBIS'))
                    total = sanitize_float(get_val('total'))
                    
                    if not inv_num or not date or not client_name:
                        continue
                        
                    invoice_id = str(uuid.uuid4())
                    
                    # Generar una partida única con el concepto para simular el detalle
                    concept = get_val('concept') or f"Histórico - {inv_num}"
                    items = [{
                        "id": str(uuid.uuid4()),
                        "code": "HISTORICO",
                        "type": "Servicio",
                        "name": concept,
                        "price": subtotal,
                        "quantity": 1,
                        "itbisRate": round(total_itbis / subtotal, 2) if subtotal > 0 else 0.18,
                        "subtotal": subtotal,
                        "itbisAmount": total_itbis,
                        "total": total
                    }]
                    
                    status = get_val('status', 'Cobrada')
                    net_payable = 0.0 if status == 'Cobrada' else total

                    raw_emision_mode = get_val('emisionMode', '').strip()
                    emision_mode = raw_emision_mode.upper() if raw_emision_mode else "IMPORT"
                    raw_dgii_status = get_val('dgiiStatus', '').strip()
                    dgii_status = raw_dgii_status.upper() if raw_dgii_status else ""
                    is_synced = sanitize_bool(get_val('isSyncedWithDGII', None), None)
                    stock_reduced = sanitize_bool(get_val('stockReduced', None), None)
                    warehouse_id = get_val('warehouseId', '').strip()

                    if not dgii_status:
                        if emision_mode == "FALLBACK":
                            dgii_status = "CONTINGENCY"
                        elif is_synced is True:
                            dgii_status = "ACCEPTED"
                        elif status == "Pendiente DGII":
                            dgii_status = "PENDING"

                    if is_synced is None:
                        if dgii_status in ["ACCEPTED", "ACCEPTED_CONDITIONAL"]:
                            is_synced = True
                        elif dgii_status in ["PENDING", "CONTINGENCY", "REJECTED"]:
                            is_synced = False
                        elif status == "Pendiente DGII":
                            is_synced = False
                        else:
                            is_synced = True

                    if stock_reduced is None:
                        stock_reduced = True
                    
                    inv_dict = {
                        "invoiceNumber": inv_num,
                        "date": date,
                        "dueDate": get_val('dueDate') or date,
                        "clientId": "api_client_default",
                        "clientName": client_name,
                        "clientRNC": client_rnc,
                        "status": status,
                        "ecfType": get_val('ecfType', 'Factura de Consumo (E32)'),
                        "encf": get_val('encf'),
                        "xmlSignature": "HISTORICAL_IMPORT",
                        "qrCodeURL": "",
                        "isSyncedWithDGII": bool(is_synced),
                        "emisionMode": emision_mode,
                        "dgiiStatus": dgii_status,
                        "totalPaid": total if status == 'Cobrada' else 0.0,
                        "remainingBalance": net_payable,
                        "netPayable": net_payable,
                        "subtotal": subtotal,
                        "totalITBIS": total_itbis,
                        "total": total,
                        "isQuotation": False,
                        "notes": "Registro de factura histórica importado desde sistema previo.",
                        "createdAt": datetime.utcnow().isoformat(),
                        "items": items,
                        "stockReduced": bool(stock_reduced)
                    }
                    if warehouse_id:
                        inv_dict["warehouseId"] = warehouse_id
                    DatabaseService.save_invoice(owner_uid, invoice_id, inv_dict, sandbox=sandbox)
                    count += 1
                    
        if is_ajax:
            return jsonify({"success": True, "message": f"¡Éxito! Se importaron {count} registros correctamente."})
        flash(f'¡Éxito! Se importaron {count} registros correctamente.', 'success')
    except Exception as e:
        if is_ajax:
            return jsonify({"success": False, "error": f"Error al procesar la importación: {str(e)}"}), 500
        flash(f'Error al procesar la importación: {str(e)}', 'error')
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
    if import_type == 'clients':
        return redirect(url_for('web_clients.list_clients'))
    elif import_type == 'products':
        return redirect(url_for('web_invoices.list_items'))
    else:
        return redirect(url_for('web_invoices.list_invoices'))
