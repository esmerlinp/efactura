# app/web/import_mapper.py
import os
import csv
import uuid
import json
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.services.db_service import DatabaseService
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

@web_import_mapper_bp.route('/import/upload', methods=['POST'])
def upload_file():
    if 'user' not in session: return redirect(url_for('login'))
    
    import_type = request.form.get('import_type')
    if import_type not in ['clients', 'products', 'invoices']:
        flash('Tipo de importación no válido.', 'error')
        return redirect(url_for('web_dashboard.dashboard'))
        
    file = request.files.get('file')
    if not file or not file.filename.endswith('.csv'):
        flash('Por favor sube un archivo CSV válido (.csv).', 'error')
        if import_type == 'clients':
            return redirect(url_for('web_clients.list_clients'))
        elif import_type == 'products':
            return redirect(url_for('list_items'))
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
        flash(f'Error al analizar el archivo: {str(e)}', 'error')
        if import_type == 'clients':
            return redirect(url_for('web_clients.list_clients'))
        elif import_type == 'products':
            return redirect(url_for('list_items'))
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
            {"id": "type", "name": "Tipo (Bien / Servicio)", "required": True, "suggestions": ["tipo", "type", "categoria"]},
            {"id": "code", "name": "Código SKU Local", "required": False, "suggestions": ["codigo", "code", "sku", "referencia"]},
            {"id": "barcode", "name": "Código de Barra", "required": False, "suggestions": ["barcode", "barra", "escaner"]},
            {"id": "unit", "name": "Unidad de Medida", "required": False, "suggestions": ["unidad", "unit", "medida"]},
            {"id": "costPrice", "name": "Precio de Costo", "required": False, "suggestions": ["costo", "cost", "compra"]},
            {"id": "minStock", "name": "Stock Mínimo Alerta", "required": False, "suggestions": ["minimo", "min", "alerta"]},
            {"id": "rackLocation", "name": "Ubicación Pasillo/Góndola", "required": False, "suggestions": ["ubicacion", "location", "pasillo", "rack"]},
            {"id": "codigoImpuesto", "name": "Código ISC DGII (Selectivo)", "required": False, "suggestions": ["isc", "selectivo", "codigoimpuesto", "impuestoadicional"]},
            {"id": "tasaImpuestoAdicional", "name": "Tasa/Monto ISC", "required": False, "suggestions": ["tasaisc", "montoisc", "tasaadicional"]}
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
            {"id": "concept", "name": "Concepto / Descripción Única", "required": False, "suggestions": ["concepto", "descripcion", "detalle", "nota"]}
        ]
        
    return render_template(
        'import/mapper.html',
        import_type=import_type,
        headers=headers,
        preview_rows=preview_rows,
        temp_filename=file_id,
        target_fields=target_fields
    )

@web_import_mapper_bp.route('/import/process', methods=['POST'])
def process_import():
    if 'user' not in session: return redirect(url_for('login'))
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    import_type = request.form.get('import_type')
    temp_filename = request.form.get('temp_filename')
    
    if not temp_filename or not import_type:
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
                    if field_id in mapping and len(row) > mapping[field_id]:
                        return row[mapping[field_id]].strip()
                    return default
                
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
                        "codigoImpuesto": get_val('codigoImpuesto'),
                        "tasaImpuestoAdicional": sanitize_float(get_val('tasaImpuestoAdicional')),
                        "totalStock": 0.0,
                        "createdAt": datetime.utcnow().isoformat()
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
                        "isSyncedWithDGII": True,
                        "emisionMode": "IMPORT",
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
                        "stockReduced": True
                    }
                    DatabaseService.save_invoice(owner_uid, invoice_id, inv_dict, sandbox=sandbox)
                    count += 1
                    
        flash(f'¡Éxito! Se importaron {count} registros correctamente.', 'success')
    except Exception as e:
        flash(f'Error al procesar la importación: {str(e)}', 'error')
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
    if import_type == 'clients':
        return redirect(url_for('web_clients.list_clients'))
    elif import_type == 'products':
        return redirect(url_for('list_items'))
    else:
        return redirect(url_for('web_invoices.list_invoices'))
