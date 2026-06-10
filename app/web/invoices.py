import os
import io
import csv
import json
import uuid
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file, make_response
import qrcode
try:
    from weasyprint import HTML as WeasyprintHTML
    WEASYPRINT_AVAILABLE = True
    print("✅ WeasyPrint cargado correctamente en invoices.py")
except Exception as e:
    import traceback
    print("❌ ERROR AL CARGAR WEASYPRINT en invoices.py:")
    traceback.print_exc()
    WEASYPRINT_AVAILABLE = False
import random
from config import Config
from app.services.db_service import DatabaseService
from app.services.dgii import DGIIService
from app.utils.currency import CurrencyService
from app.services.ecf_emission import EcfEmissionService
from app.services.alanube import AlanubeService
from app.services.recurrence import RecurrenceService
from app.utils.decorators import check_permission, require_permission


from flask import Blueprint
web_invoices_bp = Blueprint('web_invoices', __name__)



# =========================================================================
# CONTROLADORES DE RUTA - AUTENTICACIÓN
# =========================================================================
# =========================================================================
# CATÁLOGO DE ARTÍCULOS
# =========================================================================
@web_invoices_bp.route('/items')
def list_items():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Catálogo de Productos", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
    return render_template('items/list.html', active_page='items', items=items)

@web_invoices_bp.route('/items/new', methods=['GET', 'POST'])
def new_item():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Nuevo Artículo", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    if request.method == 'POST':
        item_id = str(uuid.uuid4())
        item_dict = {
            "code": request.form.get('code', ''),
            "barcode": request.form.get('barcode', '').strip(),
            "costPrice": float(request.form.get('costPrice') or 0.0),
            "categoryId": request.form.get('categoryId', 'general').strip(),
            "type": request.form.get('type', 'Bien'),
            "name": request.form['name'],
            "price": float(request.form['price']),
            "unit": request.form.get('unit', 'Unidad'),
            "itbisRate": float(request.form.get('itbisRate', 0.18)),
            "minStock": float(request.form.get('minStock') or 0.0),
            "rackLocation": request.form.get('rackLocation', ''),
            "totalStock": 0.0,
            "codigoImpuesto": request.form.get('codigoImpuesto', '').strip(),
            "tasaImpuestoAdicional": float(request.form.get('tasaImpuestoAdicional') or 0.0),
            "gradosAlcohol": float(request.form.get('gradosAlcohol') or 0.0),
            "cantidadReferencia": float(request.form.get('cantidadReferencia') or 0.0),
            "subcantidad": float(request.form.get('subcantidad') or 0.0),
            "precioReferencia": float(request.form.get('precioReferencia') or 0.0),
            "isActive": 'isActive' in request.form or request.form.get('isActive') == 'true',
            "supplierName": request.form.get('supplierName', '').strip(),
            "wholesalePrice": float(request.form.get('wholesalePrice') or 0.0),
            "brand": request.form.get('brand', '').strip(),
            "maxStock": float(request.form.get('maxStock') or 0.0),
            "imageUrl": request.form.get('imageUrl', '').strip()
        }
        
        DatabaseService.save_item(owner_uid, item_id, item_dict, sandbox=sandbox)
        flash('Artículo añadido al catálogo de ventas.', 'success')
        return redirect(url_for('list_items'))
        
    categories = DatabaseService.get_categories(owner_uid, sandbox=sandbox)
    return render_template('items/form.html', active_page='items', item=None, categories=categories)

@web_invoices_bp.route('/items/<item_id>/edit', methods=['GET', 'POST'])
def edit_item(item_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Editar Artículo", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
    item = next((it for it in items if it['id'] == item_id), None)
    
    if not item:
        flash('Artículo no encontrado.', 'error')
        return redirect(url_for('list_items'))
        
    if request.method == 'POST':
        item_dict = {
            "code": request.form.get('code', ''),
            "barcode": request.form.get('barcode', '').strip(),
            "costPrice": float(request.form.get('costPrice') or 0.0),
            "categoryId": request.form.get('categoryId', 'general').strip(),
            "type": request.form.get('type', 'Bien'),
            "name": request.form['name'],
            "price": float(request.form['price']),
            "unit": request.form.get('unit', 'Unidad'),
            "itbisRate": float(request.form.get('itbisRate', 0.18)),
            "minStock": float(request.form.get('minStock') or 0.0),
            "rackLocation": request.form.get('rackLocation', ''),
            "totalStock": float(item.get("totalStock", 0.0)),
            "createdAt": item["createdAt"],
            "codigoImpuesto": request.form.get('codigoImpuesto', '').strip(),
            "tasaImpuestoAdicional": float(request.form.get('tasaImpuestoAdicional') or 0.0),
            "gradosAlcohol": float(request.form.get('gradosAlcohol') or 0.0),
            "cantidadReferencia": float(request.form.get('cantidadReferencia') or 0.0),
            "subcantidad": float(request.form.get('subcantidad') or 0.0),
            "precioReferencia": float(request.form.get('precioReferencia') or 0.0),
            "isActive": 'isActive' in request.form or request.form.get('isActive') == 'true',
            "supplierName": request.form.get('supplierName', '').strip(),
            "wholesalePrice": float(request.form.get('wholesalePrice') or 0.0),
            "brand": request.form.get('brand', '').strip(),
            "maxStock": float(request.form.get('maxStock') or 0.0),
            "imageUrl": request.form.get('imageUrl', '').strip()
        }
        DatabaseService.save_item(owner_uid, item_id, item_dict, sandbox=sandbox)
        flash('Artículo del catálogo actualizado.', 'success')
        return redirect(url_for('list_items'))
        
    categories = DatabaseService.get_categories(owner_uid, sandbox=sandbox)
    return render_template('items/form.html', active_page='items', item=item, categories=categories)

@web_invoices_bp.route('/items/<item_id>/delete', methods=['POST'])
def delete_item_route(item_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Eliminar Artículo", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    DatabaseService.delete_item(owner_uid, item_id, sandbox=sandbox)
    flash('Artículo eliminado del catálogo.', 'success')
    return redirect(url_for('list_items'))

@web_invoices_bp.route('/items/import-csv', methods=['POST'])
def import_items_csv():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Importar Catálogo CSV", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    file = request.files.get('csv_file')
    if not file or not file.filename.endswith('.csv'):
        flash('Por favor sube un archivo con formato .csv válido.', 'error')
        return redirect(url_for('list_items'))
        
    try:
        stream = io.StringIO(file.stream.read().decode("utf-8"), newline=None)
        csv_reader = csv.reader(stream)
        
        # Omitir cabecera si existe
        header = next(csv_reader, None)
        
        count = 0
        for row in csv_reader:
            if not row or len(row) < 3: continue
            
            # Formato esperado: code, type, name, price, unit, itbisRate
            code = row[0].strip() if len(row) > 0 else ""
            item_type = row[1].strip() if len(row) > 1 else "Bien"
            name = row[2].strip() if len(row) > 2 else ""
            price = float(row[3].strip()) if len(row) > 3 and row[3].strip() else 0.0
            unit = row[4].strip() if len(row) > 4 else "Unidad"
            itbis_rate = float(row[5].strip()) if len(row) > 5 and row[5].strip() else 0.18
            
            if not name: continue
            
            item_id = str(uuid.uuid4())
            item_dict = {
                "code": code,
                "type": item_type,
                "name": name,
                "price": price,
                "unit": unit,
                "itbisRate": itbis_rate
            }
            DatabaseService.save_item(owner_uid, item_id, item_dict, sandbox=sandbox)
            count += 1
            
        flash(f'¡Éxito! Se importaron {count} artículos masivamente al catálogo.', 'success')
    except Exception as e:
        flash(f'Fallo al parsear archivo CSV: {str(e)}', 'error')
        
    return redirect(url_for('list_items'))

@web_invoices_bp.route('/items/download-template')
def download_csv_template():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Descargar Plantilla CSV", required_permission="canClients")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["codigo", "tipo_bien_o_servicio", "nombre", "precio", "unidad_medida", "tasa_itbis", "precio_costo", "categoria", "codigo_barra", "codigo_impuesto_selectivo", "tasa_impuesto_selectivo", "proveedor", "precio_mayorista", "marca", "stock_maximo", "imagen_url", "estado"])
    writer.writerow(["PROD-001", "Bien", "Laptop Dell Latitude", "45000.00", "Unidad", "0.18", "35000.00", "Electrónica", "7460123456789", "", "0.0", "Dell SRL", "42000.00", "Dell", "50", "https://example.com/dell.jpg", "Activo"])
    writer.writerow(["SERV-002", "Servicio", "Asesoría Legal por Hora", "3500.00", "Hora", "0.0", "1500.00", "Servicios", "", "", "0.0", "", "3500.00", "", "0", "", "Activo"])
    
    dest = io.BytesIO(output.getvalue().encode('utf-8'))
    return send_file(
        dest,
        mimetype="text/csv",
        as_attachment=True,
        download_name="plantilla_items_efactura.csv"
    )

@web_invoices_bp.route('/inventory/export-stock')
def export_stock_report():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Reporte de Existencia", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    products = DatabaseService.get_items(owner_uid, sandbox=sandbox)
    goods = [p for p in products if p.get('type', 'Bien') == 'Bien']
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Codigo SKU", "Nombre / Descripcion", "Categoria", "Marca", 
        "Proveedor Principal", "Ubicacion Pasillo", "Existencia/Stock", 
        "Costo Unitario", "Precio Venta", "Valor Total Inventario (Costo)", 
        "Valor Total Inventario (Venta)", "Estado"
    ])
    
    for p in goods:
        qty = float(p.get("totalStock", 0.0))
        cost = float(p.get("costPrice", 0.0))
        price = float(p.get("price", 0.0))
        val_cost = qty * cost
        val_sale = qty * price
        
        writer.writerow([
            p.get("code", "S/C"),
            p.get("name", ""),
            p.get("categoryId", "general"),
            p.get("brand", ""),
            p.get("supplierName", ""),
            p.get("rackLocation", ""),
            f"{qty:.2f}",
            f"{cost:.2f}",
            f"{price:.2f}",
            f"{val_cost:.2f}",
            f"{val_sale:.2f}",
            "Activo" if p.get("isActive", True) else "Inactivo"
        ])
        
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    dest = io.BytesIO(output.getvalue().encode('utf-8'))
    return send_file(
        dest,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"reporte_existencias_{timestamp}.csv"
    )


# =========================================================================
# GESTIÓN DE INVENTARIO Y ALMACENES
# =========================================================================
@web_invoices_bp.route('/inventory')
def inventory_dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canManageInventory'):
        return render_template('auth/restricted.html', feature_name="Inventario y Almacén", required_permission="canManageInventory")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    # Obtener almacenes, productos y existencias
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox)
    items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
    stocks = DatabaseService.get_inventory_stock(owner_uid, sandbox=sandbox)
    
    # Cruzar datos de existencias para cada item y almacén
    stock_map = {}
    for st in stocks:
        stock_map[f"{st['itemId']}_{st['warehouseId']}"] = st['quantity']
        
    items_with_stock = []
    low_stock_alerts = []
    
    for it in items:
        # Solo controlamos inventario para ítems de tipo 'Bien'
        if it.get('type', 'Bien') == 'Bien':
            wh_stocks = {}
            for wh in warehouses:
                wh_stocks[wh['id']] = stock_map.get(f"{it['id']}_{wh['id']}", 0.0)
            
            it['warehouse_stocks'] = wh_stocks
            items_with_stock.append(it)
            
            # Alerta si totalStock es menor o igual a minStock y minStock > 0
            if it.get('totalStock', 0.0) <= it.get('minStock', 0.0) and it.get('minStock', 0.0) > 0:
                low_stock_alerts.append(it)
                
    return render_template(
        'inventario/dashboard.html',
        active_page='inventory',
        warehouses=warehouses,
        items=items_with_stock,
        low_stock_alerts=low_stock_alerts
    )

@web_invoices_bp.route('/inventory/warehouses')
def inventory_warehouses():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canManageInventory'):
        return render_template('auth/restricted.html', feature_name="Almacenes", required_permission="canManageInventory")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox)
    return render_template('inventario/almacenes.html', active_page='inventory', warehouses=warehouses)

@web_invoices_bp.route('/inventory/warehouses/new', methods=['GET', 'POST'])
def new_warehouse():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canManageInventory'):
        return render_template('auth/restricted.html', feature_name="Nuevo Almacén", required_permission="canManageInventory")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    if request.method == 'POST':
        warehouse_id = str(uuid.uuid4())
        wh_dict = {
            "name": request.form['name'],
            "description": request.form.get('description', ''),
            "address": request.form.get('address', ''),
            "branchId": request.form.get('branchId', 'default-sucursal-principal')
        }
        DatabaseService.save_warehouse(owner_uid, warehouse_id, wh_dict, sandbox=sandbox)
        flash('Almacén registrado exitosamente.', 'success')
        return redirect(url_for('inventory_warehouses'))
        
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
    return render_template('inventario/warehouse_form.html', active_page='inventory', warehouse=None, branches=branches)

@web_invoices_bp.route('/inventory/warehouses/<warehouse_id>/edit', methods=['GET', 'POST'])
def edit_warehouse(warehouse_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canManageInventory'):
        return render_template('auth/restricted.html', feature_name="Editar Almacén", required_permission="canManageInventory")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox)
    warehouse = next((w for w in warehouses if w['id'] == warehouse_id), None)
    if not warehouse:
        flash('Almacén no encontrado.', 'error')
        return redirect(url_for('inventory_warehouses'))
        
    if request.method == 'POST':
        wh_dict = {
            "name": request.form['name'],
            "description": request.form.get('description', ''),
            "address": request.form.get('address', ''),
            "branchId": request.form.get('branchId', 'default-sucursal-principal'),
            "createdAt": warehouse["createdAt"]
        }
        DatabaseService.save_warehouse(owner_uid, warehouse_id, wh_dict, sandbox=sandbox)
        flash('Almacén actualizado correctamente.', 'success')
        return redirect(url_for('inventory_warehouses'))
        
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
    return render_template('inventario/warehouse_form.html', active_page='inventory', warehouse=warehouse, branches=branches)

@web_invoices_bp.route('/inventory/warehouses/<warehouse_id>/delete', methods=['POST'])
def delete_warehouse_route(warehouse_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canManageInventory'):
        return render_template('auth/restricted.html', feature_name="Eliminar Almacén", required_permission="canManageInventory")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    # Evitar borrar el almacén predeterminado si es el único
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox)
    if len(warehouses) <= 1:
        flash('Debe mantener al menos un almacén activo en el sistema.', 'error')
        return redirect(url_for('inventory_warehouses'))
        
    DatabaseService.delete_warehouse(owner_uid, warehouse_id, sandbox=sandbox)
    flash('Almacén eliminado correctamente.', 'success')
    return redirect(url_for('inventory_warehouses'))

@web_invoices_bp.route('/inventory/transactions')
def inventory_transactions():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canManageInventory'):
        return render_template('auth/restricted.html', feature_name="Movimientos de Inventario", required_permission="canManageInventory")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    txs = DatabaseService.get_inventory_transactions(owner_uid, sandbox=sandbox)
    items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox)
    
    item_map = {it['id']: it['name'] for it in items}
    wh_map = {wh['id']: wh['name'] for wh in warehouses}
    
    for t in txs:
        t['itemName'] = t.get('itemName') or item_map.get(t['itemId'], 'Producto Eliminado')
        t['originWarehouseName'] = t.get('originWarehouseName') or wh_map.get(t['originWarehouseId'], '')
        t['destinationWarehouseName'] = t.get('destinationWarehouseName') or wh_map.get(t['destinationWarehouseId'], '')
        
    return render_template('inventario/movimientos.html', active_page='inventory', transactions=txs)

@web_invoices_bp.route('/inventory/transactions/new', methods=['GET', 'POST'])
def new_inventory_transaction():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canManageInventory'):
        return render_template('auth/restricted.html', feature_name="Nuevo Ajuste de Inventario", required_permission="canManageInventory")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    if request.method == 'POST':
        item_id = request.form['itemId']
        tx_type = request.form['type']
        qty = float(request.form['quantity'])
        reason = request.form['reason']
        notes = request.form.get('notes', '')
        
        items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
        item = next((it for it in items if it['id'] == item_id), None)
        item_name = item['name'] if item else 'Producto'
        
        warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox)
        wh_map = {wh['id']: wh['name'] for wh in warehouses}
        
        tx_dict = {
            "itemId": item_id,
            "itemName": item_name,
            "type": tx_type,
            "quantity": qty,
            "reason": reason,
            "notes": notes,
            "originWarehouseId": request.form.get('originWarehouseId', ''),
            "originWarehouseName": wh_map.get(request.form.get('originWarehouseId', ''), '') if tx_type in ['SALIDA', 'TRANSFERENCIA'] else '',
            "destinationWarehouseId": request.form.get('destinationWarehouseId', ''),
            "destinationWarehouseName": wh_map.get(request.form.get('destinationWarehouseId', ''), '') if tx_type in ['ENTRADA', 'TRANSFERENCIA'] else '',
            "performedBy": session['user']['email']
        }
        
        res = DatabaseService.register_inventory_transaction(owner_uid, tx_dict, sandbox=sandbox)
        if res:
            flash('Movimiento de inventario registrado y existencias actualizadas.', 'success')
        else:
            flash('Fallo al registrar el movimiento de inventario.', 'error')
            
        return redirect(url_for('inventory_dashboard'))
        
    items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
    goods = [it for it in items if it.get('type', 'Bien') == 'Bien']
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox)
    
    return render_template(
        'inventario/nueva_transaccion.html',
        active_page='inventory',
        items=goods,
        warehouses=warehouses
    )

# =========================================================================
# MESAS DE EMISIÓN DE COMPROBANTES FISCALES (e-CF)
# =========================================================================
@web_invoices_bp.route('/invoices')
def list_invoices():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Documentos y Facturación", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    q = request.args.get('q', '').strip()
    status = request.args.get('status', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    per_page = request.args.get('per_page', '5').strip()
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
        
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=False)
    
    # Filtrar
    filtered = []
    for inv in invoices:
        if q:
            q_lower = q.lower()
            if (q_lower not in inv.get('invoiceNumber', '').lower() and 
                q_lower not in inv.get('clientName', '').lower() and 
                q_lower not in inv.get('clientRNC', '').lower() and 
                q_lower not in inv.get('encf', '').lower()):
                continue
        if status:
            if status == "Pendiente DGII":
                if not (inv.get('emisionMode') == 'FALLBACK' and not inv.get('isSyncedWithDGII') and inv.get('status') != 'Anulada'):
                    continue
            elif status == "Con Saldo Pendiente":
                if not (inv.get('netPayable', 0.0) > 0.0 and inv.get('status') not in ['Anulada', 'Borrador', 'Cobrada']):
                    continue
            elif inv.get('status') != status:
                continue
        inv_date = inv.get('date', '')[:10]
        if start_date and inv_date < start_date:
            continue
        if end_date and inv_date > end_date:
            continue
        filtered.append(inv)
        
    total_items = len(filtered)
    if per_page == 'all':
        per_page_val = max(1, total_items)
    else:
        try:
            per_page_val = int(per_page)
            if per_page_val not in [5, 10, 15, 20]:
                per_page_val = 5
        except ValueError:
            per_page_val = 5
            
    total_pages = max(1, (total_items + per_page_val - 1) // per_page_val)
    if page < 1: page = 1
    if page > total_pages: page = total_pages
    
    start_idx = (page - 1) * per_page_val
    end_idx = start_idx + per_page_val
    paginated_invoices = filtered[start_idx:end_idx]
    
    start_count = ((page - 1) * per_page_val) + 1 if total_items > 0 else 0
    end_count = min(page * per_page_val, total_items)
    
    return render_template(
        'invoices/list.html', 
        active_page='invoices', 
        invoices=paginated_invoices,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
        pages_range=range(1, total_pages + 1),
        has_prev=page > 1,
        has_next=page < total_pages,
        start_count=start_count,
        end_count=end_count,
        per_page=per_page,
        q=q,
        status=status,
        start_date=start_date,
        end_date=end_date
    )

@web_invoices_bp.route('/quotations')
def list_quotations():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Cotizaciones", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    q = request.args.get('q', '').strip()
    status = request.args.get('status', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    per_page = request.args.get('per_page', '10').strip()
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
        
    quotations = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=True)
    
    # Filtrar
    filtered = []
    for inv in quotations:
        if q:
            q_lower = q.lower()
            if (q_lower not in inv.get('invoiceNumber', '').lower() and 
                q_lower not in inv.get('clientName', '').lower() and 
                q_lower not in inv.get('clientRNC', '').lower() and 
                q_lower not in inv.get('encf', '').lower()):
                continue
        if status:
            if inv.get('status') != status:
                continue
        inv_date = inv.get('date', '')[:10]
        if start_date and inv_date < start_date:
            continue
        if end_date and inv_date > end_date:
            continue
        filtered.append(inv)
        
    total_items = len(filtered)
    if per_page == 'all':
        per_page_val = max(1, total_items)
    else:
        try:
            per_page_val = int(per_page)
            if per_page_val not in [5, 10, 15, 20]:
                per_page_val = 10
        except ValueError:
            per_page_val = 10
            
    total_pages = max(1, (total_items + per_page_val - 1) // per_page_val)
    if page < 1: page = 1
    if page > total_pages: page = total_pages
    
    start_idx = (page - 1) * per_page_val
    end_idx = start_idx + per_page_val
    paginated_quotations = filtered[start_idx:end_idx]
    
    start_count = ((page - 1) * per_page_val) + 1 if total_items > 0 else 0
    end_count = min(page * per_page_val, total_items)
    
    return render_template(
        'invoices/list.html', 
        active_page='quotations', 
        invoices=paginated_quotations,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
        pages_range=range(1, total_pages + 1),
        has_prev=page > 1,
        has_next=page < total_pages,
        start_count=start_count,
        end_count=end_count,
        per_page=per_page,
        q=q,
        status=status,
        start_date=start_date,
        end_date=end_date
    )

@web_invoices_bp.route('/invoices/new', methods=['GET', 'POST'])
@web_invoices_bp.route('/invoices/<invoice_id>/edit', methods=['GET', 'POST'])
def new_invoice_route(invoice_id=None):
    return _new_document_helper(invoice_id=invoice_id, is_quotation=False)

@web_invoices_bp.route('/quotations/new', methods=['GET', 'POST'])
@web_invoices_bp.route('/quotations/<invoice_id>/edit', methods=['GET', 'POST'])
def new_quotation_route(invoice_id=None):
    return _new_document_helper(invoice_id=invoice_id, is_quotation=True)

@web_invoices_bp.route('/invoices/<invoice_id>/update_status', methods=['POST'])
def update_invoice_status_ajax(invoice_id):
    if 'user' not in session: return jsonify({'success': False, 'error': 'No autorizado'}), 401
    if not check_permission('canInvoice'): return jsonify({'success': False, 'error': 'Sin permisos'}), 403
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.json
    new_status = data.get('status')
    
    if not new_status:
        return jsonify({'success': False, 'error': 'Estado no proporcionado'}), 400
        
    DatabaseService.update_invoice_status_simple(owner_uid, invoice_id, new_status, sandbox=sandbox)
    return jsonify({'success': True})

def _new_document_helper(invoice_id=None, is_quotation=False):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Emisión de Documentos", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    existing_invoice = None
    if invoice_id:
        existing_invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
        if not existing_invoice:
            flash('Documento no encontrado.', 'error')
            return redirect(url_for('web_invoices.list_invoices'))
        if existing_invoice.get('status') not in ['Borrador', 'Rechazada']:
            flash('Solo se pueden editar documentos en estado Borrador.', 'error')
            return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
    else:
        if request.method == 'GET':
            ref_id = request.args.get('reference_invoice_id')
            if ref_id:
                ref_inv = DatabaseService.get_invoice(owner_uid, ref_id, sandbox=sandbox)
                if ref_inv:
                    note_type = request.args.get('note_type', 'E34')
                    ecf_type_str = "Nota de Crédito (E34)" if note_type == 'E34' else "Nota de Débito (E33)"
                    
                    # Clone original document information and items
                    existing_invoice = {
                        "clientId": ref_inv.get("clientId", ""),
                        "clientRNC": ref_inv.get("clientRNC", ""),
                        "clientName": ref_inv.get("clientName") or ref_inv.get("razonSocial", ""),
                        "razonSocial": ref_inv.get("razonSocial") or ref_inv.get("clientName", ""),
                        "currency": ref_inv.get("currency", "DOP"),
                        "exchangeRate": ref_inv.get("exchangeRate", 1.0),
                        "items": ref_inv.get("items", []),
                        "discountRate": ref_inv.get("discountRate", 0.0),
                        "ecfType": ecf_type_str,
                        "incomeType": ref_inv.get("incomeType", "01 - Ingresos por operaciones"),
                        "isQuotation": False,
                        "referencedInvoiceTotal": ref_inv.get("netPayable", 0.0),
                        "informationReference": {
                            "modificationCode": 3,
                            "ncfModified": ref_inv.get("encf", ""),
                            "ncfModifiedDate": ref_inv.get("date", "")[:10] if ref_inv.get("date") else datetime.utcnow().strftime("%Y-%m-%d"),
                            "reasonForModification": "Corrección de importes"
                        }
                    }

    if existing_invoice:
        is_quotation_route = existing_invoice.get('isQuotation', False)
    else:
        is_quotation_route = is_quotation
        
    active_page = 'quotations' if is_quotation_route else 'invoices'
    
    if request.method == 'POST':
        # 1. Obtener campos principales
        client_id = request.form.get('clientId')
        ecf_type = request.form.get('ecfType', 'Factura de Consumo (E32)')
        if is_quotation_route:
            ecf_type = "Cotización"
        currency = request.form.get('currency', 'DOP')
        payment_method = request.form.get('paymentMethod', 'Efectivo')
        due_date = request.form['dueDate']
        discount_rate = float(request.form.get('discountRate', 0.0))
        retained_isr_rate = float(request.form.get('retainedISRRate', 0.0))
        retained_itbis_rate = float(request.form.get('retainedITBISRate', 0.0))
        income_type = request.form.get('incomeType', '01 - Ingresos por operaciones')
        comentario = request.form.get('comentario', '').strip()
        
        # Parámetros de recurrencia
        is_recurring = request.form.get('isRecurring') == 'true'
        recurrence_interval = request.form.get('recurrenceInterval', 'mensual')
        next_occurrence = request.form.get('nextOccurrenceDate')

        # Parámetros de acuerdos de pago
        agreement_enabled = request.form.get('agreementEnabled') == 'true'
        try:
            installments_count = int(request.form.get('installmentsCount', 1))
        except ValueError:
            installments_count = 1
        agreement_frequency = request.form.get('agreementFrequency', 'mensual')
        try:
            late_fee_percentage = float(request.form.get('lateFeePercentage', 5.0))
        except ValueError:
            late_fee_percentage = 5.0

        # Buscar datos del cliente
        client_name = "Consumidor Final"
        client_rnc = request.form.get('clientRNC', '')
        if client_id:
            clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
            client = next((c for c in clients if c['id'] == client_id), None)
            if client:
                client_name = client['razonSocial']
                client_rnc = client['rnc']
                
        # 2. Reconstruir items dinámicos enviados por el cliente en el DOM
        parsed_items = []
        form_keys = request.form.keys()
        
        # Encontrar los índices válidos de items
        item_indices = set()
        for k in form_keys:
            if k.startswith('items['):
                parts = k.split(']')
                idx = parts[0].replace('items[', '')
                if idx.isdigit():
                    item_indices.add(int(idx))
                    
        # Obtener el catálogo para resolver automáticamente si es un Bien o Servicio e Impuestos Adicionales
        catalog = DatabaseService.get_items(owner_uid, sandbox=sandbox)
        catalog_types = {it['name'].lower().strip(): it.get('type', 'Bien') for it in catalog}
        catalog_tax_data = {
            it['name'].lower().strip(): {
                "codigoImpuesto": it.get("codigoImpuesto", ""),
                "tasaImpuestoAdicional": float(it.get("tasaImpuestoAdicional") or 0.0),
                "gradosAlcohol": float(it.get("gradosAlcohol") or 0.0),
                "cantidadReferencia": float(it.get("cantidadReferencia") or 0.0),
                "subcantidad": float(it.get("subcantidad") or 1.0),
                "precioReferencia": float(it.get("precioReferencia") or 0.0),
                "unit": it.get("unit", "Unidad")
            } for it in catalog
        }

        for idx in sorted(item_indices):
            name = request.form.get(f'items[{idx}][name]')
            price = float(request.form.get(f'items[{idx}][price]', 0.0))
            qty = int(request.form.get(f'items[{idx}][quantity]', 1))
            itbis_rate = float(request.form.get(f'items[{idx}][itbisRate]', 0.18))
            item_disc = float(request.form.get(f'items[{idx}][discountRate]', 0.0))
            
            if name:
                # Detección inteligente del tipo
                item_type = catalog_types.get(name.lower().strip())
                if not item_type:
                    if any(x in name.lower() for x in ['asesoria', 'asesoría', 'consultoria', 'consultoría', 'servicio', 'honorarios', 'soporte', 'mantenimiento']):
                        item_type = 'Servicio'
                    else:
                        item_type = 'Bien'
                
                tax_data = catalog_tax_data.get(name.lower().strip(), {})
                parsed_items.append({
                    "name": name,
                    "price": price,
                    "quantity": qty,
                    "itbisRate": itbis_rate,
                    "discountRate": item_disc,
                    "type": item_type,
                    "codigoImpuesto": tax_data.get("codigoImpuesto", ""),
                    "tasaImpuestoAdicional": tax_data.get("tasaImpuestoAdicional", 0.0),
                    "gradosAlcohol": tax_data.get("gradosAlcohol", 0.0),
                    "cantidadReferencia": tax_data.get("cantidadReferencia", 0.0),
                    "subcantidad": tax_data.get("subcantidad", 1.0),
                    "precioReferencia": tax_data.get("precioReferencia", 0.0),
                    "unit": tax_data.get("unit", "Unidad")
                })

        if not parsed_items:
            flash('Debes añadir al menos una partida a la factura.', 'error')
            return redirect(request.path)

        # Calcular totales exactos usando la lógica fiscal dgii_service
        calcs = DGIIService.calculate_invoice_totals(
            parsed_items,
            discount_rate=discount_rate,
            retained_isr_rate=retained_isr_rate,
            retained_itbis_rate=retained_itbis_rate
        )
        
        # Determinar si es Cotización o Factura Real
        is_quotation = "cotizacion" in request.path or ecf_type == "Cotización"
        
        # Generar acuerdo de pagos y cuotas
        agreement = {
            "enabled": agreement_enabled if (not is_quotation and ecf_type != "Cotización") else False,
            "installmentsCount": installments_count if agreement_enabled else 1,
            "frequency": agreement_frequency,
            "lateFeePercentage": late_fee_percentage
        }
        
        installments = []
        if agreement["enabled"] and agreement["installmentsCount"] > 1:
            base_amount = round(calcs["net_payable"] / agreement["installmentsCount"], 2)
            total_allocated = 0.0
            
            for i in range(agreement["installmentsCount"]):
                inst_num = i + 1
                if inst_num == agreement["installmentsCount"]:
                    inst_amount = round(calcs["net_payable"] - total_allocated, 2)
                else:
                    inst_amount = base_amount
                    total_allocated = round(total_allocated + inst_amount, 2)
                
                if agreement["frequency"] == 'semanal':
                    days_add = 7 * inst_num
                elif agreement["frequency"] == 'quincenal':
                    days_add = 15 * inst_num
                else:  # mensual
                    days_add = 30 * inst_num
                    
                due_date_inst = (datetime.utcnow() + timedelta(days=days_add)).strftime("%Y-%m-%d")
                
                installments.append({
                    "id": str(uuid.uuid4()),
                    "installmentNumber": inst_num,
                    "amount": inst_amount,
                    "dueDate": due_date_inst,
                    "status": "Pendiente",
                    "paidAmount": 0.0,
                    "remainingBalance": inst_amount
                })
        else:
            # Cuota única
            installments = [{
                "id": "cuota-unica-default",
                "installmentNumber": 1,
                "amount": calcs["net_payable"],
                "dueDate": due_date,
                "status": "Pendiente",
                "paidAmount": 0.0,
                "remainingBalance": calcs["net_payable"]
            }]
            
        if existing_invoice:
            target_invoice_id = invoice_id
            invoice_dict = existing_invoice
            invoice_dict["dueDate"] = due_date
            invoice_dict["clientId"] = client_id
            invoice_dict["clientName"] = client_name
            invoice_dict["clientRNC"] = client_rnc
            invoice_dict["ecfType"] = ecf_type
            invoice_dict["retainedISR"] = calcs["retained_isr"]
            invoice_dict["retainedITBIS"] = calcs["retained_itbis"]
            invoice_dict["netPayable"] = calcs["net_payable"]
            invoice_dict["subtotal"] = calcs["subtotal"]
            invoice_dict["totalITBIS"] = calcs["total_itbis"]
            invoice_dict["total"] = calcs["total"]
            invoice_dict["totalISCEspecifico"] = calcs["total_isc_especifico"]
            invoice_dict["totalISCAdValorem"] = calcs["total_isc_advalorem"]
            invoice_dict["totalOtrosImpuestos"] = calcs["total_otros_impuestos"]
            invoice_dict["isQuotation"] = is_quotation
            invoice_dict["notes"] = request.form.get('notes', '')
            invoice_dict["comentario"] = comentario
            invoice_dict["isRecurring"] = is_recurring
            invoice_dict["recurrenceInterval"] = recurrence_interval
            invoice_dict["nextOccurrenceDate"] = next_occurrence if is_recurring else None
            invoice_dict["currency"] = currency
            invoice_dict["paymentType"] = request.form.get('paymentType') or ("Crédito" if due_date > datetime.utcnow().strftime("%Y-%m-%d") else "Contado")
            invoice_dict["paymentMethod"] = payment_method
            invoice_dict["warehouseId"] = request.form.get('warehouseId', '')
            invoice_dict["branchId"] = request.form.get('branchId', 'default-sucursal-principal')
            invoice_dict["incomeType"] = income_type
            invoice_dict["items"] = calcs["items"]
            # Balances
            invoice_dict["totalPaid"] = float(existing_invoice.get("totalPaid", calcs["net_payable"] if existing_invoice.get("status") == "Cobrada" else 0.0))
            invoice_dict["remainingBalance"] = float(existing_invoice.get("remainingBalance", 0.0 if existing_invoice.get("status") == "Cobrada" else calcs["net_payable"]))
            invoice_dict["paymentAgreement"] = agreement
            invoice_dict["installments"] = installments
        else:
            random_num = f"{random.randint(1, 999999):06d}"
            inv_number = f"COT-{random_num}" if is_quotation else f"FAC-{random_num}"
            target_invoice_id = str(uuid.uuid4())
            invoice_dict = {
                "invoiceNumber": inv_number,
                "date": datetime.now(timezone(timedelta(hours=-4))).strftime("%Y-%m-%d %H:%M:%S"),
                "dueDate": due_date,
                "clientId": client_id,
                "clientName": client_name,
                "clientRNC": client_rnc,
                "status": "Borrador",
                "ecfType": ecf_type,
                "encf": "",
                "xmlSignature": "",
                "qrCodeURL": "",
                "isSyncedWithDGII": False,
                "creditedAmount": 0.0,
                "retainedISR": calcs["retained_isr"],
                "retainedITBIS": calcs["retained_itbis"],
                "netPayable": calcs["net_payable"],
                "subtotal": calcs["subtotal"],
                "totalITBIS": calcs["total_itbis"],
                "total": calcs["total"],
                "totalISCEspecifico": calcs["total_isc_especifico"],
                "totalISCAdValorem": calcs["total_isc_advalorem"],
                "totalOtrosImpuestos": calcs["total_otros_impuestos"],
                "isQuotation": is_quotation,
                "isConvertedToInvoice": False,
                "notes": request.form.get('notes', ''),
                "comentario": comentario,
                "isRecurring": is_recurring,
                "recurrenceInterval": recurrence_interval,
                "nextOccurrenceDate": next_occurrence if is_recurring else None,
                "firebasePDFURL": "",
                "firebaseXMLURL": "",
                "currency": currency,
                "paymentType": request.form.get('paymentType') or ("Crédito" if due_date > datetime.utcnow().strftime("%Y-%m-%d") else "Contado"),
                "paymentMethod": payment_method,
                "incomeType": income_type,
                "customFields": [],
                "exchangeRate": CurrencyService.get_rate(currency),
                "warehouseId": request.form.get('warehouseId', ''),
                "branchId": request.form.get('branchId', 'default-sucursal-principal'),
                "items": calcs["items"],
                "totalPaid": 0.0,
                "remainingBalance": calcs["net_payable"],
                "paymentAgreement": agreement,
                "installments": installments
            }
        
        # Guardar información de referencia para Notas de Crédito / Débito (Ley 32-23)
        if ecf_type in ["Nota de Débito (E33)", "Nota de Crédito (E34)"]:
            ref_ncf = request.form.get("refNcfModified", "").strip()
            ref_date = request.form.get("refNcfModifiedDate", "").strip()
            ref_code = request.form.get("refModificationCode", "3")
            ref_reason = request.form.get("refReasonForModification", "").strip() or "Corrección de importes"
            
            if ref_ncf and ref_date:
                invoice_dict["informationReference"] = {
                    "modificationCode": int(ref_code),
                    "ncfModified": ref_ncf,
                    "ncfModifiedDate": ref_date,
                    "reasonForModification": ref_reason
                }
                # Copiar llaves de compatibilidad a nivel superior
                invoice_dict["ncfModified"] = ref_ncf
                invoice_dict["ncfModifiedDate"] = ref_date
                invoice_dict["modificationCode"] = int(ref_code)
                invoice_dict["reasonForModification"] = ref_reason
                
            if request.form.get("referencedInvoiceTotal"):
                invoice_dict["referencedInvoiceTotal"] = float(request.form.get("referencedInvoiceTotal", 0.0))

        DatabaseService.save_invoice(owner_uid, target_invoice_id, invoice_dict, sandbox=sandbox)
        
        action = request.form.get('action')
        
        if is_quotation:
            flash('Cotización creada exitosamente como borrador.', 'success')
            return redirect(url_for('list_quotations'))
        elif action in ['emitir_cobrar', 'emitir_credito']:
            company = DatabaseService.get_company_profile(owner_uid)
            try:
                if not invoice_dict.get("encf"):
                    ecf_short = AlanubeService.get_ecf_type_short_code(invoice_dict["ecfType"])
                    user_email = session['user']['email']
                    encf, log_id = DatabaseService.consume_next_sequence(owner_uid, ecf_short, user_email, sandbox=sandbox)
                    invoice_dict["encf"] = encf
                    
                res = EcfEmissionService.emit_electronic_comprobante(company, invoice_dict, sandbox=sandbox)
                
                if res.get("success"):
                    invoice_dict["encf"] = res.get("encf", invoice_dict.get("encf", ""))
                    invoice_dict["xmlSignature"] = res.get("xmlSignature", "")
                    invoice_dict["qrCodeURL"] = res.get("qrCodeURL", "")
                    invoice_dict["firebasePDFURL"] = res.get("pdfUrl", "")
                    invoice_dict["firebaseXMLURL"] = res.get("xmlUrl", "")
                    # FALLBACK = emitido offline, aún pendiente de sincronizar con la DGII
                    invoice_dict["isSyncedWithDGII"] = (res.get("mode", "API") == "API")
                    invoice_dict["emisionMode"] = res.get("mode", "API")
                    invoice_dict["contingencyEmittedAt"] = datetime.utcnow().isoformat() if res.get("mode") == "FALLBACK" else None
                    
                    if action == 'emitir_cobrar':
                        invoice_dict["status"] = "Cobrada"
                        invoice_dict["totalPaid"] = invoice_dict["netPayable"]
                        invoice_dict["remainingBalance"] = 0.0
                        invoice_dict["paymentDate"] = datetime.utcnow().isoformat()
                        
                        # Registrar pago inmediato en subcolección para el historial
                        payment_dict = {
                            "amount": invoice_dict["netPayable"],
                            "paymentMethod": invoice_dict["paymentMethod"],
                            "bank": invoice_dict.get("bank") or ("Caja Efectivo" if invoice_dict["paymentMethod"] == "Efectivo" else "Banco Popular Dominicano"),
                            "referenceNumber": invoice_dict.get("referenceNumber") or ("Pago en Efectivo" if invoice_dict["paymentMethod"] == "Efectivo" else "Cobro Inmediato"),
                            "paymentDate": invoice_dict["paymentDate"],
                            "registeredBy": session['user']['email']
                        }
                        # La factura se guardará al registrar el pago
                        DatabaseService.register_invoice_payment(owner_uid, target_invoice_id, payment_dict, sandbox=sandbox)
                    else:
                        invoice_dict["status"] = "Pendiente DGII" if res.get("status") == "PENDING" else "Emitida"
                        invoice_dict["totalPaid"] = 0.0
                        invoice_dict["remainingBalance"] = invoice_dict["netPayable"]
                        DatabaseService.save_invoice(owner_uid, target_invoice_id, invoice_dict, sandbox=sandbox)
                    
                    logs = DatabaseService.get_sequence_logs(owner_uid, sandbox=sandbox)
                    log = next((l for l in logs if l["encf"] == res.get("encf")), None)
                    if log:
                        # Verificar cuadratura y regla de tolerancia
                        cuadratura = DGIIService.check_tolerancia_cuadratura(invoice_dict["items"], invoice_dict["total"])
                        estado_dgii = "ACCEPTED" if cuadratura["within_tolerance"] else "ACCEPTED_CONDITIONAL"
                        
                        sig_show = res.get("xmlSignature") or res.get("trackId") or "N/A"
                        motivo = f"Aprobado por la DGII. Firma/TrackID: {sig_show[:12]}"
                        if estado_dgii == "ACCEPTED_CONDITIONAL":
                            motivo = f"Aceptado Condicional por tolerancia: {', '.join(cuadratura['warnings'])}"
                        
                        DatabaseService.update_sequence_log(owner_uid, log["id"], {
                            "estado": estado_dgii,
                            "motivo": motivo,
                            "xmlEnviado": json.dumps(res.get("requestPayload"), indent=2) if res.get("requestPayload") else "",
                            "respuestaDGII": json.dumps(res.get("responseBody"), indent=2) if res.get("responseBody") else ""
                        }, sandbox=sandbox)
                        
                    msg = f"¡Comprobante emitido y cobrado con éxito! e-NCF: {res.get('encf')}"
                    if res.get("mode") == "FALLBACK":
                        msg = f"⚠️ ¡Comprobante emitido en modalidad de contingencia (sin conexión a Alanube)! e-NCF: {res.get('encf')}. Recuerde sincronizarlo con la DGII en un plazo máximo de 72 horas."
                    flash(msg, "success")
                else:
                    flash(f"Borrador creado, pero error al emitir: {res.get('message')}", "warning")
            except Exception as e:
                flash(f"Borrador creado, pero fallo en emisión: {str(e)}", "error")
            return redirect(url_for('invoice_detail', invoice_id=target_invoice_id))
        else:
            flash('Borrador de documento guardado exitosamente.', 'success')
            return redirect(url_for('invoice_detail', invoice_id=target_invoice_id))

    # Cargar catálogo de ítems, clientes y almacenes para alimentar form
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
    catalog = [it for it in DatabaseService.get_items(owner_uid, sandbox=sandbox) if it.get('isActive', True)]
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox)
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
    catalog_json = json.dumps(catalog)
    clients_json = json.dumps(clients)
    
    default_due_date = existing_invoice.get('dueDate', (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d")) if existing_invoice else (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d")
    
    return render_template(
        'invoices/new.html',
        active_page=active_page,
        clients=clients,
        catalog_json=catalog_json,
        clients_json=clients_json,
        default_due_date=default_due_date,
        warehouses=warehouses,
        branches=branches,
        invoice=existing_invoice
    )

def _get_client_email(owner_uid, invoice, sandbox):
    """Retorna el email del cliente de la factura, si está disponible."""
    try:
        client_id = invoice.get("clientId", "")
        if client_id:
            clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
            client = next((c for c in clients if c["id"] == client_id), None)
            if client:
                return client.get("email", "")
    except Exception:
        pass
    return ""

def _enrich_invoice_totals(invoice):
    """Calcula y agrega totales de impuestos adicionales de forma dinámica para compatibilidad y visualización."""
    if not invoice:
        return invoice
        
    total_propina = 0.0
    total_cdt = 0.0
    total_isc_especifico = 0.0
    total_isc_advalorem = 0.0
    total_otros_selectivos = 0.0
    
    for item in invoice.get("items", []):
        isc_esp = float(item.get("isc_especifico_amount") or 0.0)
        isc_adv = float(item.get("isc_advalorem_amount") or 0.0)
        otros_imp = float(item.get("otros_impuestos_amount") or 0.0)
        cod_imp = str(item.get("codigoImpuesto") or "").strip().zfill(3)
        
        total_isc_especifico += isc_esp
        total_isc_advalorem += isc_adv
        
        if cod_imp == "001":
            total_propina += otros_imp
        elif cod_imp == "002":
            total_cdt += otros_imp
        elif cod_imp in ["003", "004", "005"]:
            total_otros_selectivos += otros_imp
            
    invoice["totalPropina"] = round(total_propina, 2)
    invoice["totalCDT"] = round(total_cdt, 2)
    invoice["totalISCEspecifico"] = round(total_isc_especifico, 2)
    invoice["totalISCAdValorem"] = round(total_isc_advalorem, 2)
    invoice["totalOtrosSelectivos"] = round(total_otros_selectivos, 2)
    invoice["totalISCTotal"] = round(total_isc_especifico + total_isc_advalorem + total_otros_selectivos, 2)
    invoice["totalImpuestosAdicionales"] = round(invoice["totalISCTotal"] + total_propina + total_cdt, 2)
    
    return invoice

@web_invoices_bp.route('/invoices/<invoice_id>')
def invoice_detail(invoice_id):
    if 'user' not in session: return redirect(url_for('login'))

    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Detalle de Factura", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Factura no encontrada.', 'error')
        return redirect(url_for('list_invoices'))
    
    invoice = _enrich_invoice_totals(invoice)
        
    payments = DatabaseService.get_invoice_payments(owner_uid, invoice_id, sandbox=sandbox)
    company = DatabaseService.get_company_profile(owner_uid)
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
    branch = next((b for b in branches if b['id'] == invoice.get("branchId")), None)
    if not branch and branches:
        branch = branches[0]
        
    # Motor de Mora dinámico
    agreement = invoice.get("paymentAgreement") or {"enabled": False, "lateFeePercentage": 5.0}
    late_fee_percentage = float(agreement.get("lateFeePercentage", 5.0))
    
    total_mora = 0.0
    installments_with_mora = []
    
    hoy = datetime.utcnow()
    
    for inst in invoice.get("installments", []):
        inst_rem = float(inst.get("remainingBalance", 0.0))
        inst_due_str = inst.get("dueDate", "")
        
        dias_retraso = 0
        mora_cuota = 0.0
        
        if inst.get("status") == "Pendiente" and inst_due_str:
            try:
                due_date_dt = datetime.strptime(inst_due_str[:10], "%Y-%m-%d")
                if hoy > due_date_dt:
                    dias_retraso = (hoy - due_date_dt).days
                    # Recargo mensual de mora calculado por día
                    tasa_diaria = (late_fee_percentage / 100.0) / 30.0
                    mora_cuota = round(inst_rem * tasa_diaria * dias_retraso, 2)
            except Exception as e:
                print(f"Error parseando vencimiento de cuota: {e}")
                
        inst["diasRetraso"] = dias_retraso
        inst["mora"] = mora_cuota
        total_mora += mora_cuota
        
        installments_with_mora.append(inst)
        
    invoice["installments"] = installments_with_mora
    invoice["totalMora"] = round(total_mora, 2)
    invoice["overdue"] = (total_mora > 0.0)
        
    return render_template('invoices/detail.html', active_page='invoices', invoice=invoice, company=company, branch=branch, payments=payments, client_email=_get_client_email(owner_uid, invoice, sandbox))

@web_invoices_bp.route('/invoices/<invoice_id>/send-receipt', methods=['POST'])
def send_receipt_email(invoice_id):
    """Envía un Recibo de Ingreso por email al cliente."""
    if 'user' not in session:
        return jsonify({"success": False, "message": "No autenticado."}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    data = request.get_json(silent=True) or {}
    recipient_email = (data.get("email") or "").strip()
    if not recipient_email:
        return jsonify({"success": False, "message": "Dirección de email no especificada."}), 400

    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        return jsonify({"success": False, "message": "Factura no encontrada."}), 404

    company = DatabaseService.get_company_profile(owner_uid)

    # Payment data sent from the client
    payment_id      = data.get("paymentId", "")
    payment_date    = data.get("paymentDate", "")
    payment_method  = data.get("paymentMethod", "")
    payment_bank    = data.get("bank", "")
    payment_ref     = data.get("referenceNumber", "")
    payment_amount  = float(data.get("amount", 0.0))

    # Build receipt number (short suffix of payment id)
    receipt_no = (payment_id[-8:].upper() if payment_id else "N/A")

    smtp_server   = app.config.get("SMTP_SERVER", "")
    smtp_port     = int(app.config.get("SMTP_PORT", 587))
    smtp_user     = app.config.get("SMTP_USER", "")
    smtp_password = app.config.get("SMTP_PASSWORD", "")

    if not smtp_user or not smtp_password:
        return jsonify({"success": False, "message": "El servidor de correo no está configurado. Configura SMTP_USER y SMTP_PASSWORD en el servidor."}), 503

    company_name    = company.get("tradeName") or company.get("companyName", "e-Factura")
    company_rnc     = company.get("companyRNC", "")
    company_address = company.get("companyAddress", "")
    company_phone   = company.get("companyPhone", "")
    company_email   = company.get("companyEmail", smtp_user)

    html_body = f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f8fafc; color: #1e293b; margin: 0; padding: 0; }}
    .wrapper {{ max-width: 600px; margin: 30px auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(135deg, #1e3a8a 0%, #7c3aed 100%); padding: 32px 36px; text-align: center; }}
    .header h1 {{ color: #ffffff; font-size: 1.6rem; margin: 0 0 4px; font-weight: 800; letter-spacing: -0.5px; }}
    .header p {{ color: rgba(255,255,255,0.75); font-size: 0.88rem; margin: 0; }}
    .receipt-badge {{ display: inline-block; background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.3); color: #fff; padding: 6px 16px; border-radius: 20px; font-size: 0.78rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; margin-top: 14px; }}
    .body {{ padding: 32px 36px; }}
    .section-label {{ font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: #94a3b8; margin-bottom: 6px; }}
    .info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }}
    .info-item {{ background: #f8fafc; border-radius: 8px; padding: 14px 16px; }}
    .info-item .label {{ font-size: 0.72rem; color: #64748b; margin-bottom: 3px; }}
    .info-item .value {{ font-size: 0.92rem; font-weight: 500; color: #0f172a; }}
    .amount-box {{ background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); border: 2px solid #16a34a; border-radius: 10px; padding: 20px 24px; text-align: center; margin: 24px 0; }}
    .amount-box .label {{ font-size: 0.78rem; color: #166534; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }}
    .amount-box .amount {{ font-size: 2.1rem; font-weight: 800; color: #15803d; }}
    .footer-note {{ font-size: 0.78rem; color: #94a3b8; text-align: center; border-top: 1px solid #e2e8f0; padding-top: 20px; margin-top: 24px; line-height: 1.6; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      {f'<img src="{company.get("logoUrl")}" alt="Logo" style="max-height: 50px; margin-bottom: 15px;">' if company.get("logoUrl") else ''}
      <h1>{company_name}</h1>
      <p>RNC: {company_rnc} &nbsp;|&nbsp; {company_address}</p>
      <span class="receipt-badge">✓ Recibo de Ingreso</span>
    </div>
    <div class="body">
      <p style="font-size:0.92rem; color:#475569; margin-top:0;">Estimado cliente, se confirma el registro del siguiente abono:</p>

      <div class="info-grid">
        <div class="info-item">
          <div class="label">No. Recibo</div>
          <div class="value" style="font-family:monospace;">{receipt_no}</div>
        </div>
        <div class="info-item">
          <div class="label">Fecha de Pago</div>
          <div class="value">{payment_date}</div>
        </div>
        <div class="info-item">
          <div class="label">Factura de Referencia</div>
          <div class="value" style="font-family:monospace;">{invoice.get('invoiceNumber','')}</div>
        </div>
        <div class="info-item">
          <div class="label">Cliente</div>
          <div class="value">{invoice.get('clientName','')}</div>
        </div>
        <div class="info-item">
          <div class="label">Forma de Pago</div>
          <div class="value">{payment_method}</div>
        </div>
        <div class="info-item">
          <div class="label">{"Banco / Referencia" if payment_bank else "Referencia"}</div>
          <div class="value">{(payment_bank + " · " + payment_ref) if payment_bank else (payment_ref or "—")}</div>
        </div>
      </div>

      <div class="amount-box">
        <div class="label">Monto Recibido</div>
        <div class="amount">RD$ {payment_amount:,.2f}</div>
      </div>

      <div class="footer-note">
        Este recibo es un comprobante administrativo de pago emitido por {company_name}.<br>
        Para consultas: {company_phone} &nbsp;|&nbsp; {company_email}<br>
        Emitido el: {datetime.utcnow().strftime('%d/%m/%Y %H:%M')} UTC
      </div>
    </div>
  </div>
</body>
</html>
"""

    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Recibo de Pago - Factura {invoice.get('invoiceNumber', '')} | {company_name}"
        msg["From"]    = f"{company_name} <{smtp_user}>"
        msg["To"]      = recipient_email

        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, recipient_email, msg.as_string())

        return jsonify({"success": True, "message": f"Recibo enviado exitosamente a {recipient_email}"})
    except Exception as e:
        print(f"⚠️ Error enviando recibo por email: {e}")
        return jsonify({"success": False, "message": f"Error al enviar el correo: {str(e)}"}), 500

def send_invoice_email(owner_uid, invoice, recipient_email, sandbox=True, base_url=None):
    """Función auxiliar para enviar factura electrónica por correo usando SMTP y Weasyprint."""
    try:
        company = DatabaseService.get_company_profile(owner_uid)

        # 1. Preparar SMTP
        from flask import current_app as app
        smtp_server   = app.config.get("SMTP_SERVER", "")
        smtp_port     = int(app.config.get("SMTP_PORT", 587))
        smtp_user     = app.config.get("SMTP_USER", "")
        smtp_password = app.config.get("SMTP_PASSWORD", "")

        if not smtp_server or not smtp_user or not smtp_password:
            return False, "Servidor de correo no configurado (SMTP)."

        # 2. Generar XML
        xml_content = invoice.get('xmlContent') or ''
        if not xml_content or not (xml_content.strip().startswith('<?xml') or xml_content.strip().startswith('<ECF') or xml_content.strip().startswith('<eCF')):
            try:
                from app.services.dgii_xml_builder import DgiiXmlBuilder
                from app.services.dgii_signer import DgiiSigner
                raw_xml = DgiiXmlBuilder.build_invoice_xml(company, invoice)
                signed_xml_bytes = DgiiSigner.sign_xml(raw_xml, company)
                xml_content = signed_xml_bytes.decode('utf-8')
            except Exception as e:
                xml_content = invoice.get('xmlContent') or invoice.get('xmlSignature') or ''
                
        if not xml_content:
            return False, "No se pudo generar el XML de la factura."

        # 3. Generar PDF
        import io
        import base64
        import qrcode
        import urllib.parse
        from datetime import datetime

        qr_url = invoice.get("qrCodeURL")
        fecha_firma_str = ""

        if invoice.get("encf") and invoice.get("xmlSignature"):
            try:
                fecha_emision_dt = datetime.strptime(invoice.get("date", "")[:10], "%Y-%m-%d")
                fecha_emision_str = fecha_emision_dt.strftime("%d-%m-%Y")
            except:
                fecha_emision_str = ""
                
            if invoice.get("paymentDate"):
                try:
                    dt = datetime.fromisoformat(invoice["paymentDate"].replace('Z', '+00:00'))
                    fecha_firma_str = dt.strftime("%d-%m-%Y %H:%M:%S")
                except:
                    fecha_firma_str = fecha_emision_str + " 12:00:00"
            else:
                fecha_firma_str = fecha_emision_str + " 12:00:00"

            codigo_seg = invoice.get("xmlSignature", "")[:6]
            rnc_emisor = company.get("companyRNC", "").replace("-", "").strip()
            rnc_comprador = invoice.get("clientRNC", "").replace("-", "").strip()
            if not rnc_comprador: rnc_comprador = "999999999"
            monto_total = f"{invoice.get('total', 0.0):.2f}"
            
            is_consumo = 'Consumo' in invoice.get("ecfType", "")
            if is_consumo and invoice.get("total", 0.0) < 250000:
                query_params = {
                    "RncEmisor": rnc_emisor,
                    "ENCF": invoice.get("encf"),
                    "MontoTotal": monto_total,
                    "CodigoSeguridad": codigo_seg
                }
                qs = urllib.parse.urlencode(query_params, quote_via=urllib.parse.quote)
                qr_url = "https://fc.dgii.gov.do/eCF/ConsultaTimbreFC?" + qs
            else:
                query_params = {
                    "RncEmisor": rnc_emisor,
                    "RncComprador": rnc_comprador,
                    "ENCF": invoice.get("encf"),
                    "FechaEmision": fecha_emision_str,
                    "MontoTotal": monto_total,
                    "FechaFirma": fecha_firma_str,
                    "CodigoSeguridad": codigo_seg
                }
                qs = urllib.parse.urlencode(query_params, quote_via=urllib.parse.quote)
                qr_url = "https://ecf.dgii.gov.do/ecf/ConsultaTimbre?" + qs

        if not qr_url:
            qr_url = "https://dgii.gov.do/validaecf"

        qr = qrcode.QRCode(version=1, box_size=10, border=0)
        qr.add_data(qr_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        stream = io.BytesIO()
        img.save(stream, format="PNG")
        qr_base64 = base64.b64encode(stream.getvalue()).decode('utf-8')

        branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
        branch = next((b for b in branches if b['id'] == invoice.get("branchId")), None)
        if not branch and branches:
            branch = branches[0]

        invoice_enriched = _enrich_invoice_totals(invoice.copy())
        rendered_html = render_template('invoices/pdf.html', invoice=invoice_enriched, company=company, branch=branch, auto_print=False, qr_base64=qr_base64, fecha_firma_str=fecha_firma_str, sandbox=sandbox)
        
        pdf_bytes = None
        if WEASYPRINT_AVAILABLE:
            pdf_bytes = WeasyprintHTML(string=rendered_html, base_url=base_url).write_pdf()
            
        # 4. Construir correo
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.mime.application import MIMEApplication

        msg = MIMEMultipart()
        
        encf = invoice.get('encf', 'N/A')
        company_name = company.get("tradeName") or company.get("companyName", "EMISOR")
        ecf_type = invoice.get('ecfType', 'Factura de Consumo Electrónica')
        date_str = invoice.get('date', '')[:10]
        total_str = f"$ {invoice.get('total', 0.0):.2f} {invoice.get('currency', 'DOP')}"
        client_name = invoice.get('clientName') or invoice.get('razonSocial', 'Consumidor Final')
        
        msg["Subject"] = f"{ecf_type} No. [{encf}] - [{company_name}]"
        msg["From"] = f"{company_name} <{smtp_user}>"
        msg["To"] = recipient_email

        logo_url = company.get('logoUrl', '')
        
        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #f4f7f6; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 30px auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }}
                .header {{ background-color: #1a365d; color: #ffffff; padding: 30px 40px; text-align: center; }}
                .header h1 {{ margin: 0; font-size: 24px; font-weight: 500; letter-spacing: 1px; }}
                .content {{ padding: 40px; color: #333333; line-height: 1.6; }}
                .greeting {{ font-size: 18px; margin-bottom: 20px; color: #2d3748; }}
                .message {{ margin-bottom: 30px; font-size: 15px; color: #4a5568; }}
                .summary-box {{ background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 20px; margin-bottom: 30px; }}
                .summary-title {{ font-size: 16px; font-weight: 500; color: #2d3748; margin-bottom: 15px; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; }}
                .summary-table {{ width: 100%; border-collapse: collapse; }}
                .summary-table td {{ padding: 10px 0; border-bottom: 1px solid #edf2f7; font-size: 14px; }}
                .summary-table td:first-child {{ color: #718096; font-weight: 500; width: 45%; }}
                .summary-table td:last-child {{ color: #2d3748; font-weight: 500; text-align: right; }}
                .summary-table tr:last-child td {{ border-bottom: none; }}
                .footer {{ background-color: #edf2f7; padding: 20px; text-align: center; font-size: 13px; color: #718096; border-top: 1px solid #e2e8f0; }}
                .verify-link {{ color: #3182ce; text-decoration: none; font-weight: 500; }}
                .verify-link:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    {f'<img src="{logo_url}" alt="Logo" style="max-height: 60px; margin-bottom: 15px;">' if logo_url else ''}
                    <h1>{company_name}</h1>
                </div>
                <div class="content">
                    <div class="greeting">Estimado cliente: {client_name},</div>
                    <div class="message">
                        Ha generado un comprobante electrónico utilizando el nuevo sistema de Factura Electrónica de República Dominicana.<br><br>
                        Adjunto podrá descargar un archivo XML el cual está firmado electrónicamente y aceptado en la DGII. Adicionalmente su representación impresa en formato PDF.<br><br>
                        En <a href="{qr_url}" class="verify-link">este enlace</a> podrá verificar la aceptación en la DGII del comprobante electrónico adjunto.
                    </div>
                    
                    <div class="summary-box">
                        <div class="summary-title">Resumen del comprobante electrónico</div>
                        <table class="summary-table">
                            <tr>
                                <td>Tipo de documento</td>
                                <td>{ecf_type}</td>
                            </tr>
                            <tr>
                                <td>Número eCF</td>
                                <td>{encf}</td>
                            </tr>
                            <tr>
                                <td>Fecha de emisión</td>
                                <td>{date_str}</td>
                            </tr>
                            <tr>
                                <td>Estado en DGII</td>
                                <td>Aceptado</td>
                            </tr>
                            <tr>
                                <td>Total Importe</td>
                                <td>{total_str}</td>
                            </tr>
                        </table>
                    </div>
                </div>
                <div class="footer">
                    Este es un mensaje generado automáticamente, por favor no responda a este correo.
                </div>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html_body, "html"))

        # Adjuntar XML
        xml_attachment = MIMEApplication(xml_content.encode('utf-8'), _subtype="xml")
        xml_attachment.add_header('Content-Disposition', 'attachment', filename=f"{encf}.xml")
        msg.attach(xml_attachment)

        # Adjuntar PDF
        if pdf_bytes:
            pdf_attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
            pdf_attachment.add_header('Content-Disposition', 'attachment', filename=f"{encf}.pdf")
            msg.attach(pdf_attachment)

        # 5. Enviar Correo
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, recipient_email, msg.as_string())
        
        return True, f"Factura enviada exitosamente por correo a {recipient_email}."
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"⚠️ Error enviando factura por email: {e}")
        return False, str(e)

@web_invoices_bp.route('/invoices/<invoice_id>/notify-email', methods=['POST'])
def notify_invoice_email(invoice_id):
    """Notifica la factura electrónica por email usando SMTP."""
    if 'user' not in session:
        return jsonify({"success": False, "message": "No autenticado."}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    data = request.get_json(silent=True) or {}
    recipient_email = (data.get("email") or "").strip()
    if not recipient_email:
        return jsonify({"success": False, "message": "Dirección de correo no especificada."}), 400

    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        return jsonify({"success": False, "message": "Factura no encontrada."}), 404

    success, message = send_invoice_email(owner_uid, invoice, recipient_email, sandbox=sandbox, base_url=request.host_url)
    if success:
        return jsonify({"success": True, "message": message})
    else:
        return jsonify({"success": False, "message": f"Error al enviar el correo: {message}"}), 500

@web_invoices_bp.route('/invoices/<invoice_id>/pay', methods=['POST'])
def pay_invoice_route(invoice_id):
    if 'user' not in session: return redirect(url_for('login'))

    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Registrar Pago", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Factura no encontrada.', 'error')
        return redirect(url_for('list_invoices'))
        
    try:
        amount = float(request.form.get('amount', invoice.get('remainingBalance', 0.0)))
    except ValueError:
        amount = 0.0
        
    remaining_balance = float(invoice.get('remainingBalance', invoice.get('netPayable', 0.0) if invoice.get('status') == 'Cobrada' else 0.0))
    
    if amount <= 0.0:
        flash('El monto a abonar debe ser mayor a cero.', 'error')
        return redirect(url_for('invoice_detail', invoice_id=invoice_id))
        
    payment_method = request.form.get('paymentMethod', 'Cheque / Transferencia')
    
    if payment_method == 'Efectivo':
        bank = 'Caja Efectivo'
        reference_number = 'Pago en Efectivo'
    else:
        bank = request.form.get('bank', 'Banco Popular Dominicano')
        reference_number = request.form.get('referenceNumber', 'Abono Registrado')
        
    mora_action = request.form.get('moraAction', 'perdonar')
    try:
        mora_amount = float(request.form.get('moraAmount', 0.0))
    except ValueError:
        mora_amount = 0.0

    payment_dict = {
        "paymentMethod": payment_method,
        "bank": bank,
        "referenceNumber": reference_number,
        "paymentDate": datetime.utcnow().isoformat(),
        "registeredBy": session['user']['email']
    }

    if mora_action == 'cobrar' and mora_amount > 0:
        capital_amount = max(0.0, amount - mora_amount)
        if capital_amount > remaining_balance + 0.01:
            flash(f'El monto de capital del abono (RD$ {capital_amount:,.2f}) no puede superar el balance pendiente (RD$ {remaining_balance:,.2f}).', 'error')
            return redirect(url_for('invoice_detail', invoice_id=invoice_id))
            
        payment_dict["amount"] = capital_amount
        payment_dict["moraAction"] = "cobrado_separado"
        payment_dict["moraAmount"] = mora_amount
        
        try:
            DatabaseService.register_invoice_payment(owner_uid, invoice_id, payment_dict, sandbox=sandbox)
            new_balance = max(0.0, remaining_balance - capital_amount)
            if new_balance <= 0.01:
                flash(f'¡Abono de RD$ {capital_amount:,.2f} + RD$ {mora_amount:,.2f} de mora cobrado! ¡Factura liquidada y saldada al 100% con éxito!', 'success')
            else:
                flash(f'¡Abono de RD$ {capital_amount:,.2f} + RD$ {mora_amount:,.2f} de mora cobrado con éxito! Pendiente restante: RD$ {new_balance:,.2f}.', 'success')
            flash(f'⚠️ Mora de RD$ {mora_amount:,.2f} cobrada. Debe emitir un e-CF (B02/E32) adicional por el recargo de mora.', 'warning')
        except Exception as e:
            flash(f'Error al registrar el cobro: {str(e)}', 'error')
    else:
        if amount > remaining_balance + 0.01:
            flash(f'El monto del abono (RD$ {amount:,.2f}) no puede superar el balance pendiente (RD$ {remaining_balance:,.2f}).', 'error')
            return redirect(url_for('invoice_detail', invoice_id=invoice_id))
            
        payment_dict["amount"] = amount
        if mora_amount > 0:
            payment_dict["moraAction"] = "perdonado"
            payment_dict["moraForgiven"] = mora_amount
            payment_dict["moraForgivenNote"] = request.form.get('moraNote', '').strip() or 'Mora perdonada por acuerdo comercial'
            
        try:
            DatabaseService.register_invoice_payment(owner_uid, invoice_id, payment_dict, sandbox=sandbox)
            new_balance = max(0.0, remaining_balance - amount)
            if new_balance <= 0.01:
                flash('¡Factura liquidada y saldada al 100% con éxito!', 'success')
            else:
                flash(f'¡Abono de RD$ {amount:,.2f} registrado con éxito! Pendiente restante: RD$ {new_balance:,.2f}.', 'success')
                
            if mora_amount > 0:
                flash(f'🤝 Mora de RD$ {mora_amount:,.2f} perdonada. Se registró solo el capital.', 'info')
        except Exception as e:
            flash(f'Error al registrar el cobro: {str(e)}', 'error')
            
    return redirect(url_for('invoice_detail', invoice_id=invoice_id))

@web_invoices_bp.route('/invoices/<invoice_id>/sign', methods=['POST'])
def sign_invoice_route(invoice_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Firmar Comprobante", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Factura no encontrada.', 'error')
        return redirect(url_for('list_invoices'))
        
    company = DatabaseService.get_company_profile(owner_uid)
    
    try:
        # Consumir el siguiente consecutivo del rango fiscal DGII si no se ha asignado
        if not invoice.get("encf"):
            ecf_short = AlanubeService.get_ecf_type_short_code(invoice["ecfType"])
            user_email = session['user']['email']
            
            # Bloquear secuencia y generar consecutivo
            encf, log_id = DatabaseService.consume_next_sequence(owner_uid, ecf_short, user_email, sandbox=sandbox)
            invoice["encf"] = encf
            
        # Llamada asíncrona simulada al emisor Alanube (con Fallback de contingencia)
        res = EcfEmissionService.emit_electronic_comprobante(company, invoice, sandbox=sandbox)
        
        if res.get("success"):
            invoice["status"] = "Pendiente DGII" if res.get("status") == "PENDING" else "Emitida"
            invoice["encf"] = res.get("encf", invoice.get("encf", ""))
            invoice["xmlSignature"] = res.get("xmlSignature", "")
            invoice["qrCodeURL"] = res.get("qrCodeURL", "")
            invoice["firebasePDFURL"] = res.get("pdfUrl", "")
            invoice["firebaseXMLURL"] = res.get("xmlUrl", "")
            # FALLBACK = emitido offline, aún pendiente de sincronizar con la DGII
            invoice["isSyncedWithDGII"] = (res.get("mode", "API") == "API" and res.get("status") != "PENDING")
            invoice["emisionMode"] = res.get("mode", "API")
            invoice["contingencyEmittedAt"] = datetime.utcnow().isoformat() if res.get("mode") == "FALLBACK" else None
            invoice["date"] = datetime.now(timezone(timedelta(hours=-4))).strftime("%Y-%m-%d %H:%M:%S")
            
            DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
            
            # Sincronizar en log de auditoría
            logs = DatabaseService.get_sequence_logs(owner_uid, sandbox=sandbox)
            log = next((l for l in logs if l["encf"] == res.get("encf")), None)
            if log:
                # Verificar cuadratura y regla de tolerancia
                cuadratura = DGIIService.check_tolerancia_cuadratura(invoice["items"], invoice["total"])
                estado_dgii = "ACCEPTED" if cuadratura["within_tolerance"] else "ACCEPTED_CONDITIONAL"
                
                sig_show = res.get("xmlSignature") or res.get("trackId") or "N/A"
                motivo = f"Aprobado por la DGII. Firma/TrackID: {sig_show[:12]}"
                if estado_dgii == "ACCEPTED_CONDITIONAL":
                    motivo = f"Aceptado Condicional por tolerancia: {', '.join(cuadratura['warnings'])}"
                
                # Guardar actualización
                DatabaseService.update_sequence_log(owner_uid, log["id"], {
                    "estado": estado_dgii,
                    "motivo": motivo,
                    "xmlEnviado": json.dumps(res.get("requestPayload"), indent=2) if res.get("requestPayload") else "",
                    "respuestaDGII": json.dumps(res.get("responseBody"), indent=2) if res.get("responseBody") else ""
                }, sandbox=sandbox)
                
            msg = f"¡Comprobante firmado digitalmente con éxito! e-NCF: {res.get('encf')} (Modo: {res.get('mode', 'API')})"
            if res.get("mode") == "FALLBACK":
                msg = f"⚠️ ¡Comprobante firmado en modalidad de contingencia (sin conexión a Alanube)! e-NCF: {res.get('encf')}. Recuerde sincronizarlo con la DGII en un plazo máximo de 72 horas."
            flash(msg, "success")
        else:
            flash(f"Error al certificar comprobante: {res.get('message')}", "error")
            
    except Exception as e:
        flash(f"Fallo en la emisión de comprobante: {str(e)}", "error")
        
    return redirect(url_for('invoice_detail', invoice_id=invoice_id))

@web_invoices_bp.route('/invoices/<invoice_id>/convert', methods=['POST'])
def convert_quotation_route(invoice_id):
    """Convierte una Cotización (COT-) en un Comprobante Fiscal Electrónico real (FAC-)."""
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Convertir Cotización", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Cotización no encontrada.', 'error')
        return redirect(url_for('list_quotations'))

    if not invoice.get('isQuotation'):
        flash('Este documento ya es una factura real. No necesita conversión.', 'info')
        return redirect(url_for('invoice_detail', invoice_id=invoice_id))

    target_ecf_type = request.form.get('targetEcfType', 'Factura de Consumo (E32)')

    # Validaciones fiscales DGII
    client_rnc = invoice.get('clientRNC', '').strip()
    total = invoice.get('total', 0.0)

    if target_ecf_type == 'Factura de Crédito Fiscal (E31)' and not client_rnc:
        flash('Las facturas de Crédito Fiscal (E31) siempre requieren el RNC/Cédula del cliente. Edita la cotización y agrega un cliente antes de convertir.', 'error')
        return redirect(url_for('invoice_detail', invoice_id=invoice_id))

    if target_ecf_type == 'Factura de Consumo (E32)' and total >= 250000 and not client_rnc:
        flash(f'Por Ley 32-23 de la DGII, las facturas de consumo que superen RD$ 250,000 deben identificar al comprador. El total de esta cotización es RD$ {total:,.2f}. Agrega un cliente con RNC antes de convertir.', 'error')
        return redirect(url_for('invoice_detail', invoice_id=invoice_id))

    # Realizar la conversión
    random_num = f"{random.randint(1, 999999):06d}"
    invoice['invoiceNumber'] = f"FAC-{random_num}"
    invoice['ecfType'] = target_ecf_type
    invoice['isQuotation'] = False
    invoice['isConvertedToInvoice'] = True
    invoice['status'] = 'Borrador'  # Queda como borrador hasta firmarse

    DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)

    flash(f'¡Cotización convertida exitosamente a {target_ecf_type}! El número de documento es {invoice["invoiceNumber"]}. Procede a firmar digitalmente el comprobante.', 'success')
    return redirect(url_for('invoice_detail', invoice_id=invoice_id))


@web_invoices_bp.route('/quotations/<invoice_id>/approve', methods=['POST'])
def approve_quotation_route(invoice_id):
    """Aprueba manualmente una cotización cambiándole el estado a 'Aprobada'."""
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Aprobar Cotización", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice or not invoice.get('isQuotation'):
        flash('Cotización no encontrada.', 'error')
        return redirect(url_for('list_quotations'))
        
    invoice['status'] = 'Aprobada'
    DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
    flash('Cotización aprobada manualmente con éxito.', 'success')
    return redirect(url_for('invoice_detail', invoice_id=invoice_id))



@web_invoices_bp.route('/invoices/<invoice_id>/qr-image')
def invoice_qr_image(invoice_id):
    if 'user' not in session: return "No autorizado", 401
    if not check_permission('canInvoice'):
        return "Acceso denegado: requiere permiso de facturación", 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice or not invoice.get("qrCodeURL"):
        # Retornar QR vacío
        qr_url = "https://dgii.gov.do/validaecf"
    else:
        qr_url = invoice["qrCodeURL"]
        
    # Generar código QR PNG en memoria
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(qr_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    stream = io.BytesIO()
    img.save(stream, format="PNG")
    stream.seek(0)
    
    return send_file(stream, mimetype="image/png")

@web_invoices_bp.route('/invoices/<invoice_id>/pdf')
def invoice_pdf_download(invoice_id):
    """Genera y descarga el PDF de la factura.
    Si WeasyPrint está disponible genera un PDF binario.
    Si no, devuelve el HTML listo para imprimir (el navegador lo convierte a PDF).
    """
    if 'user' not in session: return "No autorizado", 401
    if not check_permission('canInvoice'):
        return "Acceso denegado: requiere permiso de facturación", 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        return "Factura no encontrada", 404

    invoice = _enrich_invoice_totals(invoice)

    company = DatabaseService.get_company_profile(owner_uid)
    inv_num = invoice.get('invoiceNumber', invoice_id).replace('/', '-').replace(' ', '_')

    action = request.args.get('action', 'download')

    import io
    import base64
    import qrcode
    import urllib.parse
    from datetime import datetime

    qr_url = invoice.get("qrCodeURL")
    fecha_firma_str = ""

    if invoice.get("encf") and invoice.get("xmlSignature"):
        try:
            fecha_emision_dt = datetime.strptime(invoice.get("date", "")[:10], "%Y-%m-%d")
            fecha_emision_str = fecha_emision_dt.strftime("%d-%m-%Y")
        except:
            fecha_emision_str = ""
            
        if invoice.get("paymentDate"):
            try:
                dt = datetime.fromisoformat(invoice["paymentDate"].replace('Z', '+00:00'))
                fecha_firma_str = dt.strftime("%d-%m-%Y %H:%M:%S")
            except:
                fecha_firma_str = fecha_emision_str + " 12:00:00"
        else:
            fecha_firma_str = fecha_emision_str + " 12:00:00"

        codigo_seg = invoice.get("xmlSignature", "")[:6]
        rnc_emisor = company.get("companyRNC", "").replace("-", "").strip()
        rnc_comprador = invoice.get("clientRNC", "").replace("-", "").strip()
        if not rnc_comprador: rnc_comprador = "999999999"
        monto_total = f"{invoice.get('total', 0.0):.2f}"
        
        # DGII exception: Facturas de Consumo (E32) menores a RD$250,000
        is_consumo = 'Consumo' in invoice.get("ecfType", "")
        if is_consumo and invoice.get("total", 0.0) < 250000:
            query_params = {
                "RncEmisor": rnc_emisor,
                "ENCF": invoice.get("encf"),
                "MontoTotal": monto_total,
                "CodigoSeguridad": codigo_seg
            }
            qs = urllib.parse.urlencode(query_params, quote_via=urllib.parse.quote)
            qr_url = "https://fc.dgii.gov.do/eCF/ConsultaTimbreFC?" + qs
        else:
            query_params = {
                "RncEmisor": rnc_emisor,
                "RncComprador": rnc_comprador,
                "ENCF": invoice.get("encf"),
                "FechaEmision": fecha_emision_str,
                "MontoTotal": monto_total,
                "FechaFirma": fecha_firma_str,
                "CodigoSeguridad": codigo_seg
            }
            qs = urllib.parse.urlencode(query_params, quote_via=urllib.parse.quote)
            qr_url = "https://ecf.dgii.gov.do/ecf/ConsultaTimbre?" + qs

    if not qr_url:
        qr_url = "https://dgii.gov.do/validaecf"

    qr = qrcode.QRCode(version=1, box_size=10, border=0)
    qr.add_data(qr_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    stream = io.BytesIO()
    img.save(stream, format="PNG")
    qr_base64 = base64.b64encode(stream.getvalue()).decode('utf-8')

    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
    branch = next((b for b in branches if b['id'] == invoice.get("branchId")), None)
    if not branch and branches:
        branch = branches[0]

    if WEASYPRINT_AVAILABLE and action == 'download':
        # Generar PDF binario con WeasyPrint
        rendered_html = render_template('invoices/pdf.html', invoice=invoice, company=company, branch=branch, auto_print=False, qr_base64=qr_base64, fecha_firma_str=fecha_firma_str, sandbox=sandbox)
        pdf_bytes = WeasyprintHTML(string=rendered_html, base_url=request.host_url).write_pdf()
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="{inv_num}.pdf"'
        return response
    else:
        # Fallback sin dependencias externas o si action es 'print':
        # devolver HTML optimizado para impresión y auto-disparar el diálogo Imprimir del navegador
        rendered_html = render_template('invoices/pdf.html', invoice=invoice, company=company, branch=branch, auto_print=True, qr_base64=qr_base64, fecha_firma_str=fecha_firma_str, sandbox=sandbox)
        response = make_response(rendered_html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        return response

@web_invoices_bp.route('/invoices/<invoice_id>/xml')
def invoice_xml_download(invoice_id):
    """Descarga el XML firmado de la factura electrónica (e-CF)."""
    if 'user' not in session: return "No autorizado", 401
    if not check_permission('canInvoice'):
        return "Acceso denegado: requiere permiso de facturación", 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        return "Factura no encontrada", 404

    xml_content = invoice.get('xmlContent') or ''
    
    # Si no tiene el contenido del XML guardado, lo construimos y firmamos dinámicamente 
    # utilizando el perfil de la compañía para que siempre se descargue un XML válido
    if not xml_content or not (xml_content.strip().startswith('<?xml') or xml_content.strip().startswith('<ECF') or xml_content.strip().startswith('<eCF')):
        try:
            from app.services.dgii_xml_builder import DgiiXmlBuilder
            from app.services.dgii_signer import DgiiSigner
            company = DatabaseService.get_company_profile(owner_uid)
            raw_xml = DgiiXmlBuilder.build_invoice_xml(company, invoice)
            signed_xml_bytes = DgiiSigner.sign_xml(raw_xml, company)
            xml_content = signed_xml_bytes.decode('utf-8')
        except Exception as e:
            # Fallback secundario
            xml_content = invoice.get('xmlContent') or invoice.get('xmlSignature') or ''
            if not xml_content:
                return f"No se pudo generar el XML de comprobante: {str(e)}", 500

    if not xml_content:
        return "No hay XML disponible para este comprobante", 404

    inv_num = invoice.get('invoiceNumber', invoice_id).replace('/', '-').replace(' ', '_')
    
    # Asegurar que tenga la cabecera de declaración XML estándar
    if not xml_content.strip().startswith('<?xml'):
        xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_content

    response = make_response(xml_content)
    response.headers['Content-Type'] = 'application/xml; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{inv_num}.xml"'
    return response

@web_invoices_bp.route('/invoices/<invoice_id>/void', methods=['POST'])
def void_invoice_route(invoice_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Anular Comprobante", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Factura no encontrada.', 'error')
        return redirect(url_for('list_invoices'))
        
    company = DatabaseService.get_company_profile(owner_uid)
    
    # Intentar enviar anulación a Alanube
    if invoice.get("encf"):
        canc_dict = {
            "series": invoice["encf"][:3],
            "startSequence": int(invoice["encf"][3:]),
            "endSequence": int(invoice["encf"][3:]),
            "reason": "Anulación de comprobante por solicitud del cliente / error de digitación"
        }
        res = EcfEmissionService.emit_cancellation(company, canc_dict, sandbox=sandbox)
        if res.get("success"):
            invoice["status"] = "Anulada"
            DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
            
            # Registrar anulación local
            cancellation_code = res.get("cancellationCode", f"CAN-{uuid.uuid4().hex[:8].upper()}")
            DatabaseService.save_cancellation(owner_uid, str(uuid.uuid4()), {
                "series": canc_dict["series"],
                "startSequence": canc_dict["startSequence"],
                "endSequence": canc_dict["endSequence"],
                "reason": canc_dict["reason"],
                "status": "Aceptado",
                "cancellationCode": cancellation_code,
                "responseMessage": res.get("message", "")
            }, sandbox=sandbox)
            
            flash(f"Comprobante anulado y reportado a la DGII. Código: {cancellation_code}", "success")
        else:
            flash(f"Fallo al anular comprobante en la API: {res.get('message')}", "error")
    else:
        invoice["status"] = "Anulada"
        DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
        flash('Borrador de factura anulado correctamente.', 'success')
        
    return redirect(url_for('list_invoices'))

@web_invoices_bp.route('/api/invoices/sync-contingency', methods=['POST'])
def sync_contingency_invoices():
    """
    Sincroniza las facturas emitidas en Modo Contingencia (FALLBACK) con la DGII/Alanube.
    Busca todas las facturas con isSyncedWithDGII=False y emisionMode=FALLBACK
    e intenta reenviarlas al servicio de Alanube una vez restablecida la conexión.
    Este endpoint puede ser llamado manualmente desde el Dashboard o por un Cron Job.
    """
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    if not check_permission('canInvoice'):
        return jsonify({"error": "Permiso insuficiente"}), 403

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    company = DatabaseService.get_company_profile(owner_uid)

    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    pending = [
        inv for inv in invoices
        if inv.get('emisionMode') == 'FALLBACK' and not inv.get('isSyncedWithDGII', True)
        and inv.get('status') in ['Emitida', 'Cobrada']
    ]

    synced_count = 0
    failed_count = 0
    results = []

    for inv in pending:
        inv_id = inv['id']
        try:
            # Re-emitir a Alanube con el mismo encf ya asignado
            res = EcfEmissionService.emit_electronic_comprobante(company, inv, sandbox=sandbox)
            if res.get("success") and res.get("mode", "API") == "API":
                inv["isSyncedWithDGII"] = True
                inv["emisionMode"] = "API"
                inv["xmlSignature"] = res.get("xmlSignature", inv.get("xmlSignature", ""))
                inv["qrCodeURL"] = res.get("qrCodeURL", inv.get("qrCodeURL", ""))
                inv["contingencyEmittedAt"] = None
                DatabaseService.save_invoice(owner_uid, inv_id, inv, sandbox=sandbox)

                # Registrar en Log de Auditoría que pasó de FALLBACK a sincronizado
                logs = DatabaseService.get_sequence_logs(owner_uid, sandbox=sandbox)
                log = next((l for l in logs if l.get("encf") == inv.get("encf")), None)
                if log:
                    cuadratura = DGIIService.check_tolerancia_cuadratura(inv.get("items", []), inv.get("total", 0))
                    estado_dgii = "ACCEPTED" if cuadratura["within_tolerance"] else "ACCEPTED_CONDITIONAL"
                    DatabaseService.update_sequence_log(owner_uid, log["id"], {
                        "estado": estado_dgii,
                        "motivo": f"Regularizado por Sincronización Post-Contingencia. Firma: {res['xmlSignature'][:12] if res.get('xmlSignature') else 'N/A'}",
                        "xmlEnviado": json.dumps(res.get("requestPayload"), indent=2) if res.get("requestPayload") else "",
                        "respuestaDGII": json.dumps(res.get("responseBody"), indent=2) if res.get("responseBody") else ""
                    }, sandbox=sandbox)

                synced_count += 1
                results.append({"encf": inv.get("encf"), "status": "synced"})
            else:
                failed_count += 1
                results.append({"encf": inv.get("encf"), "status": "still_offline", "mode": res.get("mode")})
        except Exception as e:
            failed_count += 1
            results.append({"encf": inv.get("encf"), "status": "error", "message": str(e)})

    return jsonify({
        "success": True,
        "total_pending": len(pending),
        "synced": synced_count,
        "failed": failed_count,
        "results": results
    })

@web_invoices_bp.route('/invoices/<invoice_id>/sync', methods=['POST'])
def sync_single_invoice_route(invoice_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Sincronizar Comprobante", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Factura no encontrada.', 'error')
        return redirect(url_for('list_invoices'))
        
    company = DatabaseService.get_company_profile(owner_uid)
    
    try:
        res = EcfEmissionService.emit_electronic_comprobante(company, invoice, sandbox=sandbox)
        if res.get("success") and res.get("mode", "API") == "API":
            invoice["isSyncedWithDGII"] = True
            invoice["emisionMode"] = "API"
            invoice["xmlSignature"] = res.get("xmlSignature", invoice.get("xmlSignature", ""))
            invoice["qrCodeURL"] = res.get("qrCodeURL", invoice.get("qrCodeURL", ""))
            invoice["contingencyEmittedAt"] = None
            if res.get("pdfUrl"): invoice["firebasePDFURL"] = res["pdfUrl"]
            if res.get("xmlUrl"): invoice["firebaseXMLURL"] = res["xmlUrl"]
            
            DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
            
            # Registrar en Log de Auditoría
            logs = DatabaseService.get_sequence_logs(owner_uid, sandbox=sandbox)
            log = next((l for l in logs if l.get("encf") == invoice.get("encf")), None)
            if log:
                cuadratura = DGIIService.check_tolerancia_cuadratura(invoice.get("items", []), invoice.get("total", 0))
                estado_dgii = "ACCEPTED" if cuadratura["within_tolerance"] else "ACCEPTED_CONDITIONAL"
                DatabaseService.update_sequence_log(owner_uid, log["id"], {
                    "estado": estado_dgii,
                    "motivo": f"Regularizado por Sincronización Manual. Firma: {res['xmlSignature'][:12] if res.get('xmlSignature') else 'N/A'}",
                    "xmlEnviado": json.dumps(res.get("requestPayload"), indent=2) if res.get("requestPayload") else "",
                    "respuestaDGII": json.dumps(res.get("responseBody"), indent=2) if res.get("responseBody") else ""
                }, sandbox=sandbox)
                
            flash(f"¡Factura {invoice.get('invoiceNumber')} sincronizada con la DGII exitosamente! e-NCF: {invoice.get('encf')}", 'success')
        else:
            flash(f"No se pudo sincronizar: {res.get('message') or 'Sigue en modalidad de contingencia (sin conexión a Alanube).'}", 'warning')
    except Exception as e:
        flash(f"Error durante la sincronización: {str(e)}", 'error')
        
    return redirect(url_for('invoice_detail', invoice_id=invoice_id))

# =========================================================================
# CONTROL DE GASTOS Y RENTABILIDAD
# =========================================================================
@web_invoices_bp.route('/expenses')
def list_expenses():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Control de Gastos", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    
    # Calcular márgenes y enriquecer con números de facturas
    for exp in expenses:
        inv_id = exp.get("associatedInvoiceId")
        if inv_id:
            inv = next((i for i in invoices if i["id"] == inv_id), None)
            if inv:
                exp["invoice_number"] = inv["invoiceNumber"]
                exp["invoice_total"] = inv["total"]
                
                # Tarjeta de Rentabilidad por Factura/Proyecto:
                # Margen Neto % = ((Ingreso - Costo Gasto) / Ingreso) * 100
                if inv["total"] > 0:
                    exp["margin_pct"] = ((inv["total"] - exp["amount"]) / inv["total"]) * 100
                else:
                    exp["margin_pct"] = 0.0
                    
    return render_template('expenses/list.html', active_page='expenses', expenses=expenses)

@web_invoices_bp.route('/expenses/new', methods=['GET', 'POST'])
def new_expense_route():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Registrar Gasto", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    if request.method == 'POST':
        expense_id = str(uuid.uuid4())
        
        # Procesar archivo subido (recibo/ticket/XML) a Storage
        attachment_file = request.files.get('attachment')
        attachment_urls = []
        if attachment_file and attachment_file.filename:
            file_data = attachment_file.read()
            mime_type = attachment_file.content_type or "image/jpeg"
            dest_path = f"users/{owner_uid}/expenses/{expense_id}/{attachment_file.filename}"
            
            public_url = DatabaseService.upload_file_to_storage(file_data, dest_path, mime_type)
            attachment_urls.append(public_url)
            
        amount = float(request.form['amount'])
        is_recurring = request.form.get('isRecurring') == 'true'
        is_deductible = request.form.get('isDeductible') == 'true'
        recurrence_interval = request.form.get('recurrenceInterval', 'mensual')
        next_occurrence = request.form.get('nextOccurrenceDate')
        recurrence_end_date = request.form.get('recurrenceEndDate')
        
        payment_type = request.form.get('paymentType', 'Contado')
        due_date = request.form.get('dueDate', '')
        
        # CxP Status
        cxp_status = 'Pagado'
        if payment_type == 'Crédito':
            cxp_status = 'Pendiente'

        expense_dict = {
            "concept": request.form['concept'],
            "category": request.form['category'],
            "amount": amount,
            "date": request.form['date'],
            "rncEmisor": request.form.get('rncEmisor', ''),
            "providerName": request.form.get('providerName', ''),
            "ncf": request.form.get('ncf', ''),
            "isMinorExpense": "E43" in request.form.get('ncf', '') or "B13" in request.form.get('ncf', ''),
            "isSyncedWithDGII": False,
            "qrCodeURL": "",
            "xmlSignature": "",
            "notes": request.form.get('notes', ''),
            "isRecurring": is_recurring,
            "recurrenceInterval": recurrence_interval,
            "nextOccurrenceDate": next_occurrence if is_recurring else None,
            "recurrenceEndDate": recurrence_end_date if is_recurring else None,
            "associatedInvoiceId": request.form.get('associatedInvoiceId', ''),
            "itbisAmount": float(request.form.get('itbisAmount', amount * 0.18 / 1.18)),
            "isITBISDeductible": is_deductible,
            "isDeductible": is_deductible,
            "firebaseAttachmentURLs": attachment_urls,
            # Nuevos campos e-CF y CxP:
            "ecfType": request.form.get('ecfType', 'E31'),
            "ecfNumber": request.form.get('ncf', ''),
            "cne": request.form.get('cne', ''),
            "tipoGastoDGII": request.form.get('tipoGastoDGII', '02'),
            "paymentType": payment_type,
            "cxpStatus": cxp_status,
            "cxpRemainingBalance": 0.0 if payment_type == 'Contado' else amount,
            "approvalStatus": request.form.get('approvalStatus', 'Aprobado'),
            "requestedBy": session['user'].get('name', 'Usuario'),
            "approvedBy": session['user'].get('name', 'Usuario') if request.form.get('approvalStatus', 'Aprobado') == 'Aprobado' else '',
            "dueDate": due_date
        }
        
        DatabaseService.save_expense(owner_uid, expense_id, expense_dict, sandbox=sandbox)
        flash('Gasto operativo registrado exitosamente.', 'success')
        return redirect(url_for('list_expenses'))
        
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    
    return render_template(
        'expenses/new.html',
        active_page='expenses',
        invoices=invoices,
        today_str=today_str
    )

@web_invoices_bp.route('/expenses/<expense_id>/delete', methods=['POST'])
def delete_expense_route(expense_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Eliminar Gasto", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    DatabaseService.delete_expense(owner_uid, expense_id, sandbox=sandbox)
    flash('Gasto eliminado.', 'success')
    return redirect(url_for('list_expenses'))

@web_invoices_bp.route('/expenses/<expense_id>/edit', methods=['GET', 'POST'])
def edit_expense_route(expense_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Editar Gasto", required_permission="canExpenses")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    # Obtener el gasto existente
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    expense = None
    for exp in expenses:
        if exp['id'] == expense_id:
            expense = exp
            break
            
    if not expense:
        flash('Gasto no encontrado.', 'error')
        return redirect(url_for('list_expenses'))
        
    if request.method == 'POST':
        attachment_file = request.files.get('attachment')
        attachment_urls = expense.get('firebaseAttachmentURLs', [])
        if attachment_file and attachment_file.filename:
            file_data = attachment_file.read()
            mime_type = attachment_file.content_type or "image/jpeg"
            dest_path = f"users/{owner_uid}/expenses/{expense_id}/{attachment_file.filename}"
            public_url = DatabaseService.upload_file_to_storage(file_data, dest_path, mime_type)
            attachment_urls = [public_url]
            
        amount = float(request.form['amount'])
        is_recurring = request.form.get('isRecurring') == 'true'
        is_deductible = request.form.get('isDeductible') == 'true'
        recurrence_interval = request.form.get('recurrenceInterval', 'mensual')
        next_occurrence = request.form.get('nextOccurrenceDate')
        recurrence_end_date = request.form.get('recurrenceEndDate')
        
        payment_type = request.form.get('paymentType', 'Contado')
        due_date = request.form.get('dueDate', '')
        
        cxp_status = expense.get('cxpStatus', 'Pagado')
        if payment_type == 'Crédito' and cxp_status == 'Pagado':
            cxp_status = 'Pendiente'
        elif payment_type == 'Contado':
            cxp_status = 'Pagado'
            
        current_rem = float(expense.get('cxpRemainingBalance', 0.0))
        if payment_type == 'Contado':
            rem_bal = 0.0
        else:
            if amount != expense.get('amount', 0.0):
                rem_bal = amount
            else:
                rem_bal = current_rem

        expense_dict = {
            "concept": request.form['concept'],
            "category": request.form['category'],
            "amount": amount,
            "date": request.form['date'],
            "rncEmisor": request.form.get('rncEmisor', ''),
            "providerName": request.form.get('providerName', ''),
            "ncf": request.form.get('ncf', ''),
            "isMinorExpense": "E43" in request.form.get('ncf', '') or "B13" in request.form.get('ncf', ''),
            "isSyncedWithDGII": expense.get('isSyncedWithDGII', False),
            "qrCodeURL": expense.get('qrCodeURL', ''),
            "xmlSignature": expense.get('xmlSignature', ''),
            "notes": request.form.get('notes', ''),
            "isRecurring": is_recurring,
            "recurrenceInterval": recurrence_interval,
            "nextOccurrenceDate": next_occurrence if is_recurring else None,
            "recurrenceEndDate": recurrence_end_date if is_recurring else None,
            "associatedInvoiceId": request.form.get('associatedInvoiceId', ''),
            "itbisAmount": float(request.form.get('itbisAmount', amount * 0.18 / 1.18)),
            "isITBISDeductible": is_deductible,
            "isDeductible": is_deductible,
            "firebaseAttachmentURLs": attachment_urls,
            "ecfType": request.form.get('ecfType', 'E31'),
            "ecfNumber": request.form.get('ncf', ''),
            "cne": request.form.get('cne', ''),
            "tipoGastoDGII": request.form.get('tipoGastoDGII', '02'),
            "paymentType": payment_type,
            "cxpStatus": cxp_status,
            "cxpRemainingBalance": rem_bal,
            "approvalStatus": request.form.get('approvalStatus', 'Aprobado'),
            "requestedBy": expense.get('requestedBy', session['user'].get('name', 'Usuario')),
            "approvedBy": session['user'].get('name', 'Usuario') if request.form.get('approvalStatus', 'Aprobado') == 'Aprobado' else '',
            "dueDate": due_date,
            "createdAt": expense.get('createdAt')
        }
        
        DatabaseService.save_expense(owner_uid, expense_id, expense_dict, sandbox=sandbox)
        flash('Gasto operativo actualizado exitosamente.', 'success')
        return redirect(url_for('list_expenses'))
        
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    
    return render_template(
        'expenses/edit.html',
        active_page='expenses',
        expense=expense,
        invoices=invoices
    )

@web_invoices_bp.route('/api/expenses/ocr-upload', methods=['POST'])
def api_expenses_ocr_upload():
    if 'user' not in session: return jsonify({"success": False, "error": "No autorizado"}), 401
    
    upload_file = request.files.get('file')
    if not upload_file:
        return jsonify({"success": False, "error": "No se recibió ningún archivo."}), 400
        
    filename = upload_file.filename.lower()
    from app.services.ocr_service import OCRService
    
    if filename.endswith('.xml'):
        xml_content = upload_file.read()
        res = OCRService.process_xml_ecf(xml_content)
    else:
        # En una app real, usaríamos PIL y pytesseract.
        # Aquí procesamos como imagen simulada
        res = OCRService.process_image_ocr(upload_file.read())
        
    return jsonify(res)

@web_invoices_bp.route('/expenses/cxp')
def list_cxp():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canManageCXP'):
        return render_template('auth/restricted.html', feature_name="Cuentas por Pagar (CxP)", required_permission="canManageCXP")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    
    cxp_list = []
    total_cxp_pending = 0.0
    total_cxp_vencido = 0.0
    
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    
    for exp in expenses:
        if exp.get('paymentType') == 'Crédito':
            due_date = exp.get('dueDate', '')
            status = exp.get('cxpStatus', 'Pendiente')
            rem_bal = float(exp.get('cxpRemainingBalance', exp.get('amount', 0.0)))
            
            if status in ['Pendiente', 'Abonado'] and due_date and due_date < today_str:
                status = 'Vencido'
                exp['cxpStatus'] = 'Vencido'
                
            cxp_list.append(exp)
            
            if status in ['Pendiente', 'Abonado', 'Vencido']:
                total_cxp_pending += rem_bal
                if status == 'Vencido' or (due_date and due_date < today_str):
                    total_cxp_vencido += rem_bal
                    
    return render_template(
        'expenses/cxp.html',
        active_page='expenses_cxp',
        cxp_list=cxp_list,
        total_cxp_pending=total_cxp_pending,
        total_cxp_vencido=total_cxp_vencido,
        today_str=today_str
    )

@web_invoices_bp.route('/expenses/cxp/<expense_id>/pay', methods=['POST'])
def pay_cxp_route(expense_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canManageCXP'):
        return jsonify({"success": False, "message": "No autorizado"}), 403
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.get_json(silent=True) or {}
    amount = float(data.get("amount", 0.0))
    
    if amount <= 0:
        return jsonify({"success": False, "message": "Monto no válido."}), 400
        
    registered_by = session['user'].get('name', 'Usuario Admin')
    success, message = DatabaseService.save_cxp_payment(owner_uid, expense_id, amount, registered_by=registered_by, sandbox=sandbox)
    
    if success:
        return jsonify({"success": True, "message": message})
    else:
        return jsonify({"success": False, "message": message}), 500

# =========================================================================
# SECUENCIAS FISCALES
# =========================================================================
@web_invoices_bp.route('/sequences')
def list_sequences():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canModifySettings'):
        return render_template('auth/restricted.html', feature_name="Secuencias Fiscales", required_permission="canModifySettings")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    sequences = DatabaseService.get_sequences(owner_uid, sandbox=sandbox)
    sequence_logs = DatabaseService.get_sequence_logs(owner_uid, sandbox=sandbox)
    cancellations = DatabaseService.get_cancellations(owner_uid, sandbox=sandbox)
    
    default_exp_date = (datetime.utcnow() + timedelta(days=730)).strftime("%Y-%m-%d") # 2 años
    
    return render_template(
        'sequences/list.html',
        active_page='sequences',
        sequences=sequences,
        sequence_logs=sequence_logs,
        cancellations=cancellations,
        default_exp_date=default_exp_date
    )

@web_invoices_bp.route('/sequences/new', methods=['POST'])
def new_sequence_route():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canModifySettings'):
        return render_template('auth/restricted.html', feature_name="Crear Secuencia Fiscal", required_permission="canModifySettings")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    seq_id = str(uuid.uuid4())
    seq_dict = {
        "tipoComprobante": request.form['tipoComprobante'],
        "prefijo": request.form['tipoComprobante'],
        "secuenciaInicial": int(request.form['secuenciaInicial']),
        "secuenciaFinal": int(request.form['secuenciaFinal']),
        "ultimoConsecutivoUsado": int(request.form['secuenciaInicial']) - 1,
        "alertaMinimoDisponible": int(request.form['alertaMinimoDisponible']),
        "fechaAutorizacion": datetime.utcnow().strftime("%Y-%m-%d"),
        "fechaExpiracion": request.form['fechaExpiracion'],
        "numeroAutorizacionDgii": request.form['numeroAutorizacionDgii'],
        "estado": "ACTIVA",
        "ambiente": "SANDBOX" if sandbox else "PRODUCCION",
        "bloqueadaManualmente": False
    }
    
    DatabaseService.save_sequence(owner_uid, seq_id, seq_dict, sandbox=sandbox)
    flash('Secuencia fiscal autorizada por la DGII registrada con éxito.', 'success')
    return redirect(url_for('list_sequences'))

@web_invoices_bp.route('/cancellations/new', methods=['POST'])
def new_cancellation_route():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canModifySettings'):
        return render_template('auth/restricted.html', feature_name="Anulación de Rangos", required_permission="canModifySettings")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    company = DatabaseService.get_company_profile(owner_uid)
    
    canc_id = str(uuid.uuid4())
    canc_dict = {
        "series": request.form['series'].upper(),
        "startSequence": int(request.form['startSequence']),
        "endSequence": int(request.form['endSequence']),
        "reason": request.form['reason']
    }
    
    res = EcfEmissionService.emit_cancellation(company, canc_dict, sandbox=sandbox)
    
    if res.get("success"):
        DatabaseService.save_cancellation(owner_uid, canc_id, {
            "series": canc_dict["series"],
            "startSequence": canc_dict["startSequence"],
            "endSequence": canc_dict["endSequence"],
            "reason": canc_dict["reason"],
            "status": "Aceptado",
            "cancellationCode": res["cancellationCode"],
            "responseMessage": res["message"]
        }, sandbox=sandbox)
        flash(f"¡Anulación de rango procesada exitosamente en la DGII! Código: {res['cancellationCode']}", 'success')
    else:
        flash(f"Fallo al enviar anulación: {res.get('message')}", 'error')
        
    return redirect(url_for('list_sequences'))

# =========================================================================
# CONFIGURACIÓN DE EMPRESA Y EQUIPO
# =========================================================================
@web_invoices_bp.route('/settings/company', methods=['GET', 'POST'])
def company_settings():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canModifySettings'):
        return render_template('auth/restricted.html', feature_name="Configuración de la Empresa", required_permission="canModifySettings")
    owner_uid = session['user']['ownerUID']
    
    if request.method == 'POST':
        # Preservar logoUrl y configuraciones de marca existentes
        existing_profile = DatabaseService.get_company_profile(owner_uid)
        
        # Procesar certificado nuevo si se carga
        cert_file = request.files.get('certificateFile')
        cert_name = existing_profile.get('certificateName', '')
        cert_ext = existing_profile.get('certificateExtension', '')
        cert_content = existing_profile.get('certificateContent', '')
        
        if cert_file and cert_file.filename:
            import base64
            file_data = cert_file.read()
            filename = cert_file.filename
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'p12'
            cert_name = filename.rsplit('.', 1)[0]
            cert_ext = f".{ext}"
            cert_content = base64.b64encode(file_data).decode('utf-8')

        cert_password = request.form.get('certificatePassword', '').strip()
        if not cert_password:
            cert_password = existing_profile.get('certificatePassword', '')

        profile_dict = {
            "companyName": request.form['companyName'],
            "companyRNC": request.form['companyRNC'],
            "companyAddress": request.form.get('companyAddress', ''),
            "companyPhone": request.form.get('companyPhone', ''),
            "companyEmail": request.form.get('companyEmail', ''),
            "tradeName": request.form.get('tradeName', ''),
            "companyType": "associated",
            "province": request.form.get('province', ''),
            "municipality": request.form.get('municipality', ''),
            "certificateName": cert_name,
            "certificateExtension": cert_ext,
            "certificateContent": cert_content,
            "certificatePassword": cert_password,
            "colorMarca": existing_profile.get('colorMarca', '#10b981'),
            "gradientEnabled": existing_profile.get('gradientEnabled', True),
            "applyColorMarcaUI": existing_profile.get('applyColorMarcaUI', True),
            "applyColorMarcaReports": existing_profile.get('applyColorMarcaReports', True),
            "logoUrl": existing_profile.get('logoUrl', ''),
            "regimenFiscal": request.form.get('regimenFiscal', 'General'),
            "openaiApiKey": request.form.get('openaiApiKey', ''),
            "alanubeCompanyIDSandbox": request.form.get('alanubeCompanyIDSandbox', '').strip(),
            "alanubeCompanyIDProduction": request.form.get('alanubeCompanyIDProduction', '').strip(),
            "theme": request.form.get('theme', existing_profile.get('theme', 'moderno')),
            "consolidationEnabled": request.form.get('consolidationEnabled') == 'true',
            "consolidationThreshold": float(request.form.get('consolidationThreshold') or 250000.0),
            "configured": True
        }
        DatabaseService.save_company_profile(owner_uid, profile_dict)

        # Si se presionó el botón de registrar en Alanube o importar desde Alanube
        if request.form.get('registerAlanube') == 'true':
            if not profile_dict.get("certificateContent"):
                flash("Error: Se requiere cargar y guardar un archivo de Certificado Digital (.p12 o .pfx) con su contraseña antes de poder activarlo.", "error")
            else:
                sandbox = session.get('is_sandbox_mode', True)
                res = AlanubeService.register_company(profile_dict, sandbox=sandbox)
                if res.get("success"):
                    flash("¡Certificado digital habilitado y activado exitosamente para la emisión de e-CF!", "success")
                else:
                    flash(f"Error al habilitar el certificado digital: {res.get('message')}", "error")
        elif request.form.get('importAlanube') == 'true':
            sandbox = session.get('is_sandbox_mode', True)
            target_rnc = request.form.get('companyRNC', '').replace("-", "").strip()
            if not target_rnc:
                flash("Por favor, introduce un RNC válido para realizar la importación.", "error")
            else:
                res = AlanubeService.get_company_from_alanube(target_rnc, sandbox=sandbox)
                if res.get("success") and res.get("data"):
                    data = res["data"]
                    # Sincronizar todos los campos recuperados de Alanube
                    profile_dict["companyName"] = data.get("name") or profile_dict["companyName"]
                    profile_dict["tradeName"] = data.get("tradeName") or profile_dict["tradeName"]
                    profile_dict["companyAddress"] = data.get("address") or profile_dict["companyAddress"]
                    profile_dict["companyEmail"] = data.get("email") or profile_dict["companyEmail"]
                    profile_dict["companyType"] = data.get("type") or profile_dict["companyType"]
                    profile_dict["province"] = data.get("province") or profile_dict["province"]
                    profile_dict["municipality"] = data.get("municipality") or profile_dict["municipality"]
                    
                    # Certificado
                    cert_data = data.get("certificate")
                    if cert_data:
                        profile_dict["certificateName"] = cert_data.get("name", "firma_digital")
                        profile_dict["certificateExtension"] = cert_data.get("extension", ".p12")
                        profile_dict["certificateContent"] = cert_data.get("content", "")
                        profile_dict["certificatePassword"] = cert_data.get("password", "")
                    
                    # Logo
                    if data.get("logo"):
                        profile_dict["logoBase64"] = data.get("logo")
                    
                    # Guardar en Firestore con la información actualizada
                    DatabaseService.save_company_profile(owner_uid, profile_dict)
                    flash("¡Sincronización exitosa! La información de la empresa y el certificado digital se han descargado de Alanube y guardado de forma segura en Firestore.", "success")
                else:
                    flash(f"Error al sincronizar desde Alanube: {res.get('message', 'No se encontraron datos')}", "error")
        else:
            flash('Ajustes y perfil de empresa actualizados correctamente.', 'success')

        if request.form.get('is_wizard') == 'true':
            # PROCESAR ACTIVOS OPCIONALES DEL WIZARD ONBOARDING
            sandbox = session.get('is_sandbox_mode', True)
            
            # 1. Primer Producto
            w_prod_name = request.form.get('wizard_product_name', '').strip()
            if w_prod_name:
                w_prod_price = float(request.form.get('wizard_product_price') or 0.0)
                w_prod_itbis = float(request.form.get('wizard_product_itbis') or 0.18)
                item_id = str(uuid.uuid4())
                item_dict = {
                    "code": "PROD-001",
                    "type": "Bien",
                    "name": w_prod_name,
                    "price": w_prod_price,
                    "unit": "Unidad",
                    "itbisRate": w_prod_itbis,
                    "minStock": 0.0,
                    "rackLocation": "",
                    "totalStock": 100.0
                }
                DatabaseService.save_item(owner_uid, item_id, item_dict, sandbox=sandbox)
                
            # 2. Primer Almacén / Sucursal
            w_branch_name = request.form.get('wizard_branch_name', '').strip()
            if w_branch_name:
                w_branch_code = request.form.get('wizard_branch_code', '').strip() or "001"
                w_branch_address = request.form.get('wizard_branch_address', '').strip() or profile_dict.get("companyAddress", "")
                branch_id = str(uuid.uuid4())
                branch_dict = {
                    "name": w_branch_name,
                    "code": w_branch_code,
                    "address": w_branch_address,
                    "isDefault": True
                }
                DatabaseService.save_branch(owner_uid, branch_id, branch_dict, sandbox=sandbox)
                
            # 3. Primer Cliente
            w_client_name = request.form.get('wizard_client_name', '').strip()
            if w_client_name:
                w_client_rnc = request.form.get('wizard_client_rnc', '').strip() or "00300749256"
                w_client_email = request.form.get('wizard_client_email', '').strip()
                client_id = str(uuid.uuid4())
                client_dict = {
                    "rnc": w_client_rnc,
                    "razonSocial": w_client_name,
                    "email": w_client_email,
                    "telefono": "",
                    "direccion": "",
                    "crmNotes": "Cliente creado mediante asistente de Onboarding",
                    "nextContactDate": ""
                }
                DatabaseService.save_client(owner_uid, client_id, client_dict, sandbox=sandbox)
                
            return redirect(url_for('company_settings', onboarding_success='true'))

        return redirect(url_for('company_settings'))
        
    profile = DatabaseService.get_company_profile(owner_uid)

    # Obtener sucursales
    branches = DatabaseService.get_branches(owner_uid, sandbox=session.get('is_sandbox_mode', True))

    onboarding_success = request.args.get('onboarding_success') == 'true'
    show_wizard = not profile.get('configured', False)
    return render_template('company_settings.html', active_page='settings', profile=profile, branches=branches, show_wizard=show_wizard, onboarding_success=onboarding_success, e_cf_provider=Config.E_CF_PROVIDER.lower())

@web_invoices_bp.route('/settings/company/generate-api-key', methods=['POST'])
def generate_company_api_key():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canModifySettings'):
        return render_template('auth/restricted.html', feature_name="Configuración de la Empresa", required_permission="canModifySettings")
    
    owner_uid = session['user']['ownerUID']
    new_key = DatabaseService.generate_api_key(owner_uid)
    if new_key:
        flash('¡Nueva API Key generada con éxito!', 'success')
    else:
        flash('Ocurrió un error al generar la API Key.', 'error')
    return redirect(url_for('company_settings'))

@web_invoices_bp.route('/settings/company/brand', methods=['POST'])
def save_company_brand_settings():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    if not check_permission('canModifySettings'): return jsonify({"error": "No autorizado"}), 403
    
    owner_uid = session['user']['ownerUID']
    existing_profile = DatabaseService.get_company_profile(owner_uid)
    
    if 'colorMarca' in request.form:
        existing_profile['colorMarca'] = request.form.get('colorMarca')
    if 'gradientEnabled' in request.form:
        existing_profile['gradientEnabled'] = request.form.get('gradientEnabled') == 'true'
    if 'applyColorMarcaUI' in request.form:
        existing_profile['applyColorMarcaUI'] = request.form.get('applyColorMarcaUI') == 'true'
    if 'applyColorMarcaReports' in request.form:
        existing_profile['applyColorMarcaReports'] = request.form.get('applyColorMarcaReports') == 'true'
    if 'theme' in request.form:
        existing_profile['theme'] = request.form.get('theme')
        
    logo_file = request.files.get('logoFile')
    if logo_file and logo_file.filename:
        import base64
        file_data = logo_file.read()
        mime_type = logo_file.content_type or "image/png"
        ext = logo_file.filename.rsplit('.', 1)[-1].lower() if '.' in logo_file.filename else 'png'
        dest_path = f"users/{owner_uid}/company/logo_{uuid.uuid4().hex[:8]}.{ext}"
        existing_profile['logoUrl'] = DatabaseService.upload_file_to_storage(file_data, dest_path, mime_type)
        existing_profile['logoBase64'] = base64.b64encode(file_data).decode('utf-8')
        
    if request.form.get('removeLogo') == 'true':
        existing_profile['logoUrl'] = ''
        existing_profile['logoBase64'] = ''
        
    DatabaseService.save_company_profile(owner_uid, existing_profile)
    return jsonify({"success": True, "profile": existing_profile})

@web_invoices_bp.route('/settings/team', methods=['GET'])
def team_settings():
    if 'user' not in session: return redirect(url_for('login'))
    if session['user'].get('role') != 'owner':
        flash('No tienes permisos de propietario.', 'error')
        return redirect(url_for('dashboard'))
    owner_uid = session['user']['ownerUID']
    team = DatabaseService.get_team_members(owner_uid)
    return render_template('team_settings.html', active_page='team_settings', team=team)

@web_invoices_bp.route('/settings/team/new', methods=['POST'])
def add_team_member():
    if 'user' not in session: return redirect(url_for('login'))
    if session['user'].get('role') != 'owner':
        flash('No tienes permisos de propietario.', 'error')
        return redirect(url_for('team_settings'))
    
    owner_uid = session['user']['ownerUID']
    
    name = request.form['name']
    email = request.form['email']
    password = request.form['password']
    
    permissions = {
        "canInvoice": 'canInvoice' in request.form,
        "canExpenses": 'canExpenses' in request.form,
        "canClients": 'canClients' in request.form,
        "canModifySettings": 'canModifySettings' in request.form,
        "canManageInventory": 'canManageInventory' in request.form,
        "canManagePOS": 'canManagePOS' in request.form,
        "canViewDashboard": 'canViewDashboard' in request.form,
        "canManageCXC": 'canManageCXC' in request.form,
        "canManageCXP": 'canManageCXP' in request.form,
        "canManageContracts": 'canManageContracts' in request.form,
        "canManageCommissions": 'canManageCommissions' in request.form,
        "canViewBI": 'canViewBI' in request.form
    }
    
    try:
        # Registrar usuario en Firebase Auth & Firestore
        profile = DatabaseService.register_user(
            email=email,
            password=password,
            name=name,
            role="employee",
            owner_uid=owner_uid
        )
        # Actualizar permisos a los configurados
        DatabaseService.update_employee_permissions(profile['uid'], permissions)
        flash(f'Colaborador {name} registrado y vinculado exitosamente.', 'success')
    except Exception as e:
        flash(f'Error al registrar colaborador: {str(e)}', 'error')
        
    return redirect(url_for('team_settings'))

@web_invoices_bp.route('/settings/branches/save', methods=['POST'])
def save_branch_route():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canModifySettings'):
        flash('No tienes permisos.', 'error')
        return redirect(url_for('company_settings'))
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    branch_id = request.form.get('id') or str(uuid.uuid4())
    branch_dict = {
        "name": request.form.get('name', ''),
        "code": request.form.get('code', ''),
        "address": request.form.get('address', ''),
        "isDefault": request.form.get('isDefault') == 'true'
    }
    
    DatabaseService.save_branch(owner_uid, branch_id, branch_dict, sandbox=sandbox)
    flash(f"Sucursal '{branch_dict['name']}' guardada correctamente.", 'success')
    return redirect(url_for('company_settings'))

@web_invoices_bp.route('/settings/branches/<branch_id>/delete', methods=['POST'])
def delete_branch_route(branch_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canModifySettings'):
        flash('No tienes permisos.', 'error')
        return redirect(url_for('company_settings'))
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    # Prevenir eliminar la sucursal predeterminada si es la unica, o si isDefault
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
    branch = next((b for b in branches if b['id'] == branch_id), None)
    if not branch:
        flash("Sucursal no encontrada.", 'error')
        return redirect(url_for('company_settings'))
        
    if branch.get('isDefault') and len(branches) > 1:
        flash("No puedes eliminar la sucursal principal. Marca otra como principal primero.", 'error')
        return redirect(url_for('company_settings'))
        
    if len(branches) <= 1:
        flash("No puedes eliminar la única sucursal.", 'error')
        return redirect(url_for('company_settings'))

    DatabaseService.delete_branch(owner_uid, branch_id, sandbox=sandbox)
    flash("Sucursal eliminada.", 'success')
    return redirect(url_for('company_settings'))

@web_invoices_bp.route('/settings/team/<employee_uid>/permissions', methods=['POST'])
def update_team_member_permissions(employee_uid):
    if 'user' not in session: return redirect(url_for('login'))
    if session['user'].get('role') != 'owner':
        flash('No tienes permisos de propietario.', 'error')
        return redirect(url_for('team_settings'))
    
    permissions = {
        "canInvoice": 'canInvoice' in request.form,
        "canExpenses": 'canExpenses' in request.form,
        "canClients": 'canClients' in request.form,
        "canModifySettings": 'canModifySettings' in request.form,
        "canManageInventory": 'canManageInventory' in request.form,
        "canManagePOS": 'canManagePOS' in request.form,
        "canViewDashboard": 'canViewDashboard' in request.form,
        "canManageCXC": 'canManageCXC' in request.form,
        "canManageCXP": 'canManageCXP' in request.form,
        "canManageContracts": 'canManageContracts' in request.form,
        "canManageCommissions": 'canManageCommissions' in request.form,
        "canViewBI": 'canViewBI' in request.form
    }
    
    if DatabaseService.update_employee_permissions(employee_uid, permissions):
        flash('Permisos del colaborador actualizados con éxito.', 'success')
    else:
        flash('Error al actualizar permisos.', 'error')
        
    return redirect(url_for('team_settings'))

@web_invoices_bp.route('/settings/team/<employee_uid>/delete', methods=['POST'])
def delete_team_member_route(employee_uid):
    if 'user' not in session: return redirect(url_for('login'))
    if session['user'].get('role') != 'owner':
        flash('No tienes permisos de propietario.', 'error')
        return redirect(url_for('team_settings'))
    
    owner_uid = session['user']['ownerUID']
    
    if DatabaseService.delete_team_member(owner_uid, employee_uid):
        flash('Colaborador desvinculado de tu equipo.', 'success')
    else:
        flash('Error al desvincular colaborador.', 'error')
        
    return redirect(url_for('team_settings'))

@web_invoices_bp.route('/settings/company/export', methods=['POST'])
def export_company_data():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canModifySettings'):
        return render_template('auth/restricted.html', feature_name="Exportación de Datos", required_permission="canModifySettings")
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    selected_sections = request.form.getlist('sections')
    if not selected_sections:
        flash('Debes seleccionar al menos una sección para exportar.', 'error')
        return redirect(url_for('company_settings'))
    
    import io
    import csv
    import zipfile
    from datetime import datetime
    
    def build_clients_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "RNC/Cedula", "Razon Social", "Email", "Telefono", "Direccion", "Notas CRM", "Proximo Contacto", "Creado En"])
        clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
        for c in clients:
            writer.writerow([
                c.get("id", ""),
                c.get("rnc", ""),
                c.get("razonSocial", ""),
                c.get("email", ""),
                c.get("telefono", ""),
                c.get("direccion", ""),
                c.get("crmNotes", ""),
                c.get("nextContactDate", ""),
                c.get("createdAt", "")
            ])
        return output.getvalue()

    def build_products_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Codigo", "Tipo", "Nombre", "Precio", "Unidad", "Tasa ITBIS", "Stock Minimo", "Ubicacion Estanteria", "Stock Total", "Creado En", "Precio Costo", "Categoria", "Codigo de Barra", "Codigo Impuesto Selectivo", "Tasa Impuesto Selectivo", "Proveedor", "Precio Mayorista", "Marca", "Stock Maximo", "Imagen URL", "Estado"])
        products = DatabaseService.get_items(owner_uid, sandbox=sandbox)
        for p in products:
            writer.writerow([
                p.get("id", ""),
                p.get("code", ""),
                p.get("type", ""),
                p.get("name", ""),
                f"{p.get('price', 0.0):.2f}",
                p.get("unit", ""),
                f"{p.get('itbisRate', 0.18):.2f}",
                f"{p.get('minStock', 0.0):.2f}",
                p.get("rackLocation", ""),
                f"{p.get('totalStock', 0.0):.2f}",
                p.get("createdAt", ""),
                f"{p.get('costPrice', 0.0):.2f}",
                p.get("categoryId", "general"),
                p.get("barcode", ""),
                p.get("codigoImpuesto", ""),
                f"{p.get('tasaImpuestoAdicional', 0.0):.2f}",
                p.get("supplierName", ""),
                f"{p.get('wholesalePrice', 0.0):.2f}",
                p.get("brand", ""),
                f"{p.get('maxStock', 0.0):.2f}",
                p.get("imageUrl", ""),
                "Activo" if p.get("isActive", True) else "Inactivo"
            ])
        return output.getvalue()

    def build_quotes_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Numero Cotizacion", "Fecha", "Fecha Vencimiento", "ID Cliente", "Nombre Cliente", "RNC Cliente", "Estado", "Monto Neto a Pagar", "Total ITBIS", "Subtotal", "Total"])
        quotes = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=True)
        for q in quotes:
            writer.writerow([
                q.get("id", ""),
                q.get("invoiceNumber", ""),
                q.get("date", ""),
                q.get("dueDate", ""),
                q.get("clientId", ""),
                q.get("clientName", ""),
                q.get("clientRNC", ""),
                q.get("status", ""),
                f"{q.get('netPayable', 0.0):.2f}",
                f"{q.get('totalITBIS', 0.0):.2f}",
                f"{q.get('subtotal', 0.0):.2f}",
                f"{q.get('total', 0.0):.2f}"
            ])
        return output.getvalue()

    def build_expenses_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Concepto", "Categoria", "Monto", "Monto ITBIS", "Fecha", "RNC Emisor", "NCF", "Notas", "Recurrente", "Deducible"])
        expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
        for e in expenses:
            writer.writerow([
                e.get("id", ""),
                e.get("concept", ""),
                e.get("category", ""),
                f"{e.get('amount', 0.0):.2f}",
                f"{e.get('itbisAmount', 0.0):.2f}",
                e.get("date", ""),
                e.get("rncEmisor", ""),
                e.get("ncf", ""),
                e.get("notes", ""),
                "Si" if e.get("isRecurring") else "No",
                "Si" if e.get("isDeductible") else "No"
            ])
        return output.getvalue()

    def build_documents_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Numero Documento", "Fecha", "Fecha Vencimiento", "ID Cliente", "Nombre Cliente", "RNC Cliente", "Estado", "Tipo e-CF", "e-NCF", "Sincronizado DGII", "Monto Neto a Pagar", "Total ITBIS", "Subtotal", "Total"])
        documents = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=False)
        for d in documents:
            writer.writerow([
                d.get("id", ""),
                d.get("invoiceNumber", ""),
                d.get("date", ""),
                d.get("dueDate", ""),
                d.get("clientId", ""),
                d.get("clientName", ""),
                d.get("clientRNC", ""),
                d.get("status", ""),
                d.get("ecfType", ""),
                d.get("encf", ""),
                "Si" if d.get("isSyncedWithDGII") else "No",
                f"{d.get('netPayable', 0.0):.2f}",
                f"{d.get('totalITBIS', 0.0):.2f}",
                f"{d.get('subtotal', 0.0):.2f}",
                f"{d.get('total', 0.0):.2f}"
            ])
        return output.getvalue()

    csv_generators = {
        "clients": ("clientes.csv", build_clients_csv),
        "products": ("productos.csv", build_products_csv),
        "quotes": ("cotizaciones.csv", build_quotes_csv),
        "expenses": ("gastos.csv", build_expenses_csv),
        "documents": ("documentos.csv", build_documents_csv)
    }

    if len(selected_sections) == 1:
        sec = selected_sections[0]
        if sec in csv_generators:
            filename, generator_fn = csv_generators[sec]
            csv_data = generator_fn()
            
            dest = io.BytesIO()
            dest.write(b'\xef\xbb\xbf')
            dest.write(csv_data.encode('utf-8'))
            dest.seek(0)
            
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            download_name = f"{filename.split('.')[0]}_{timestamp}.csv"
            
            return send_file(
                dest,
                mimetype="text/csv",
                as_attachment=True,
                download_name=download_name
            )
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for sec in selected_sections:
            if sec in csv_generators:
                filename, generator_fn = csv_generators[sec]
                csv_data = generator_fn()
                content_bytes = b'\xef\xbb\xbf' + csv_data.encode('utf-8')
                zip_file.writestr(filename, content_bytes)
                
    zip_buffer.seek(0)
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    zip_filename = f"export_datos_empresa_{timestamp}.zip"
    
    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=zip_filename
    )

# =========================================================================================
# REPORTES FISCALES (IT-1, 606, 607)
# =========================================================================
@web_invoices_bp.route('/reports')
def reports_dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Reportería DGII", required_permission="canInvoice")
    return render_template('reports/reports_dashboard.html', active_page='reports')

@web_invoices_bp.route('/reports/it1')
def it1_diagnostic():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Diagnóstico de IT-1", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    
    # Filtrar reales (excluyendo cotizaciones y borradores)
    real_invoices = [inv for inv in invoices if not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador']]
    
    sales_subtotal = sum(inv['subtotal'] for inv in real_invoices)
    total_itbis_sales = sum(inv['totalITBIS'] for inv in real_invoices)
    total_retained_itbis = sum(inv['retainedITBIS'] for inv in real_invoices)
    total_retained_isr = sum(inv['retainedISR'] for inv in real_invoices)
    
    expenses_subtotal = sum(exp['amount'] - exp['itbisAmount'] for exp in expenses)
    total_itbis_expenses = sum(exp['itbisAmount'] for exp in expenses if exp.get('isITBISDeductible', True))
    
    it1 = {
        "sales_subtotal": sales_subtotal,
        "total_itbis_sales": total_itbis_sales,
        "total_retained_itbis": total_retained_itbis,
        "total_retained_isr": total_retained_isr,
        "expenses_subtotal": expenses_subtotal,
        "total_itbis_expenses": total_itbis_expenses
    }
    
    current_period = datetime.utcnow().strftime("%Y-%m")
    return render_template('reports/it1.html', active_page='reports', it1=it1, current_period=current_period)


@web_invoices_bp.route('/reports/dgii-tools', methods=['GET'])
def dgii_tools():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Herramientas DGII", required_permission="canInvoice")
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    company = DatabaseService.get_company_profile(owner_uid)
    
    # Obtener estado de DGII por defecto al cargar la página
    dgii_status = AlanubeService.check_dgii_status(company, sandbox=sandbox)
    
    return render_template('reports/dgii_tools.html', active_page='reports', dgii_status=dgii_status)

@web_invoices_bp.route('/reports/check-directory-ajax', methods=['POST'])
def check_directory_ajax():
    if 'user' not in session: return jsonify({"success": False, "message": "No autenticado"}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.get_json(silent=True) or {}
    rnc = data.get("rnc", "").strip()
    if not rnc:
        return jsonify({"success": False, "message": "Debe especificar un RNC válido."}), 400
        
    company = DatabaseService.get_company_profile(owner_uid)
    res = AlanubeService.check_directory(company, rnc, sandbox=sandbox)
    return jsonify(res)

@web_invoices_bp.route('/reports/check-dgii-status-ajax', methods=['POST'])
def check_dgii_status_ajax():
    if 'user' not in session: return jsonify({"success": False, "message": "No autenticado"}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.get_json(silent=True) or {}
    env = data.get("environment")
    maint = data.get("maintenance")
    
    company = DatabaseService.get_company_profile(owner_uid)
    res = AlanubeService.check_dgii_status(company, environment=env, maintenance=maint, sandbox=sandbox)
    return jsonify(res)


@web_invoices_bp.route('/help')
def help_center():
    if 'user' not in session: return redirect(url_for('login'))
    return render_template('help.html', active_page='help')

@web_invoices_bp.route('/api/chatbot', methods=['POST'])
def chatbot_api():
    if 'user' not in session:
        return jsonify({"success": False, "message": "Debes iniciar sesión para interactuar con el chatbot."}), 401
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.get_json() or {}
    message = data.get("message", "").strip()
    history = data.get("history", [])
    
    if not message:
        return jsonify({"success": False, "message": "El mensaje no puede estar vacío."}), 400
        
    from chatbot_service import ChatbotService
    result = ChatbotService.ask_chatbot(owner_uid, message, history, sandbox=sandbox)
    return jsonify(result)

@web_invoices_bp.route('/suscripcion')
def client_subscription_page():
    if 'user' not in session: return redirect(url_for('login'))
    owner_uid = session['user']['ownerUID']
    
    # 1. Obtener perfil de la empresa
    profile = DatabaseService.get_company_profile(owner_uid)
    
    # 2. Cargar datos del plan
    plan_name = "Plan Personalizado"
    from app.services.db_service import db_firestore
    try:
        plan_id = profile.get('planId')
        if plan_id:
            plan_doc = db_firestore.collection('plans').document(plan_id).get()
            if plan_doc.exists:
                plan_data = plan_doc.to_dict()
                plan_name = plan_data.get('name', 'Plan Registrado')
    except Exception as e:
        print(f"⚠️ Error al obtener plan en suscripción del cliente: {e}")

    # 3. Obtener estadísticas de consumo
    billing_day = profile.get('billingDay', 1)
    stats = DatabaseService.get_invoice_stats(owner_uid, billing_day)
    
    # 4. Obtener historial de pagos
    payments = DatabaseService.get_payments(owner_uid)
    
    # 5. Obtener historial de facturación de meses anteriores (filtrado por fecha de registro)
    user_profile = DatabaseService.get_user_profile(session['user']['uid'])
    created_at = user_profile.get('createdAt') if user_profile else None
    
    monthly_payment = float(profile.get('monthlyPayment', 0))
    additional_cost = float(profile.get('additionalDocumentCost', 0))
    document_limit = int(profile.get('documentLimit', 0)) if profile.get('documentLimit') else 0
    billing_history = DatabaseService.get_billing_history(
        owner_uid, 
        billing_day=billing_day,
        monthly_payment=monthly_payment,
        additional_document_cost=additional_cost,
        document_limit=document_limit,
        created_at=created_at
    )
    
    return render_template(
        'subscription.html', 
        active_page='subscription',
        profile=profile,
        plan_name=plan_name,
        stats=stats,
        payments=payments,
        billing_history=billing_history
    )


# -------------------------------------------------------------
# CxC (Cuentas por Cobrar) and Payment Promises Module
# -------------------------------------------------------------

@web_invoices_bp.route('/cxc')
def cxc_dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canManageCXC'):
        return render_template('auth/restricted.html', feature_name="Dashboard CxC", required_permission="canManageCXC")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    # Procesar automáticamente recordatorios programados al abrir el módulo de CxC
    try:
        from app.services.notifications import NotificationService
        NotificationService.process_automatic_reminders(owner_uid, sandbox=sandbox)
    except Exception as e:
        print(f"⚠️ Error al procesar recordatorios automáticos en CxC Dashboard: {e}")
        
    # 1. Obtener todas las facturas
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=False)
    
    # 2. Filtrar facturas pendientes o vencidas
    # Estados de cobro: Emitida, Parcialmente Cobrada, Vencida (dinámico en get_invoices)
    cxc_invoices = []
    total_outstanding = 0.0
    total_vencido = 0.0
    total_cobrado_periodo = 0.0
    
    for inv in invoices:
        status = inv.get('status')
        # Si es cobrada, sumar al total cobrado para KPIs
        if status == "Cobrada":
            total_cobrado_periodo += float(inv.get('totalPaid', inv.get('netPayable', 0.0)))
        elif status in ["Emitida", "Parcialmente Cobrada", "Vencida"]:
            # Excluir Consumidor Final o facturas sin cliente asociado de la cartera de CxC
            client_name = inv.get('clientName', '')
            client_id = inv.get('clientId', '')
            if not client_id or 'consumidor final' in client_name.lower():
                continue
                
            cxc_invoices.append(inv)
            rem_bal = float(inv.get('remainingBalance', inv.get('netPayable', 0.0)))
            total_outstanding += rem_bal
            if status == "Vencida":
                total_vencido += rem_bal
                
    # 3. Obtener promesas de pago
    promises = DatabaseService.get_payment_promises(owner_uid, sandbox=sandbox)
    active_promises = [p for p in promises if p.get('estado') == 'Pendiente']
    total_prometido = sum(float(p.get('montoPrometido', 0.0)) for p in active_promises)
    
    # Obtener listado de clientes para el formulario de promesas/búsquedas si es necesario
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
    company = DatabaseService.get_company_profile(owner_uid) or {}
    
    return render_template(
        'cxc/dashboard.html',
        active_page='cxc',
        invoices=cxc_invoices,
        promises=promises,
        clients=clients,
        total_outstanding=total_outstanding,
        total_vencido=total_vencido,
        total_cobrado=total_cobrado_periodo,
        total_prometido=total_prometido,
        active_promises_count=len(active_promises),
        company=company
    )

@web_invoices_bp.route('/cxc/settings/reminders', methods=['POST'])
def save_cxc_reminders_settings():
    if 'user' not in session: return jsonify({"success": False, "message": "No autorizado"}), 401
    if not check_permission('canManageCXC'):
        return jsonify({"success": False, "message": "Permiso insuficiente"}), 403
        
    owner_uid = session['user']['ownerUID']
    data = request.get_json(silent=True) or {}
    
    existing_profile = DatabaseService.get_company_profile(owner_uid) or {}
    existing_profile['autoRemindersEnabled'] = data.get('enabled') is True or data.get('enabled') == 'true'
    try:
        existing_profile['autoRemindersDays'] = int(data.get('days', 0))
    except ValueError:
        existing_profile['autoRemindersDays'] = 0
    existing_profile['autoRemindersMethod'] = data.get('method', 'email')
    existing_profile['autoRemindersTone'] = data.get('tone', 'formal')
    
    DatabaseService.save_company_profile(owner_uid, existing_profile)
    return jsonify({"success": True, "message": "Configuración de recordatorios actualizada correctamente."})

@web_invoices_bp.route('/cxc/promises/add', methods=['POST'])
def add_payment_promise():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canManageCXC'):
        flash("No tienes permiso para gestionar promesas de pago.", "error")
        return redirect(url_for('cxc_dashboard'))
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice_id = request.form.get('invoiceId')
    fecha_promesa = request.form.get('fechaPromesa')
    monto_prometido = request.form.get('montoPrometido', 0.0)
    notas = request.form.get('notas', '')
    
    if not invoice_id or not fecha_promesa:
        flash("Factura y fecha de promesa son campos obligatorios.", "error")
        return redirect(url_for('cxc_dashboard'))
        
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash("Factura no encontrada.", "error")
        return redirect(url_for('cxc_dashboard'))
        
    promise_id = str(uuid.uuid4())
    promise_dict = {
        "clientId": invoice.get("clientId", ""),
        "clientName": invoice.get("clientName", "Cliente General"),
        "invoiceId": invoice_id,
        "invoiceNumber": invoice.get("invoiceNumber", ""),
        "fechaPromesa": fecha_promesa,
        "montoPrometido": float(monto_prometido),
        "estado": "Pendiente",
        "notas": notas
    }
    
    DatabaseService.save_payment_promise(owner_uid, promise_id, promise_dict, sandbox=sandbox)
    
    # Registrar también en el CRM del cliente como interacción programada
    if invoice.get("clientId"):
        interaction_dict = {
            "type": "Promesa de Pago",
            "title": f"Promesa de Pago Registrada",
            "content": f"El cliente prometió pagar RD$ {float(monto_prometido):,.2f} el {fecha_promesa}. Notas: {notas}",
            "date": datetime.utcnow().isoformat(),
            "nextContactDate": fecha_promesa,
            "completed": False,
            "registeredBy": session['user'].get('name', 'Usuario')
        }
        DatabaseService.save_client_interaction(owner_uid, invoice["clientId"], str(uuid.uuid4()), interaction_dict, sandbox=sandbox)
        
    flash("Promesa de pago registrada exitosamente.", "success")
    return redirect(url_for('cxc_dashboard'))

@web_invoices_bp.route('/cxc/promises/<promise_id>/update-status', methods=['POST'])
def update_payment_promise_status(promise_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canManageCXC'):
        return jsonify({"success": False, "message": "No autorizado"}), 403
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.get_json(silent=True) or {}
    new_estado = data.get("estado", "Cumplida") # Cumplida o Incumplida
    
    promises = DatabaseService.get_payment_promises(owner_uid, sandbox=sandbox)
    target_promise = None
    for p in promises:
        if p['id'] == promise_id:
            target_promise = p
            break
            
    if not target_promise:
        return jsonify({"success": False, "message": "Promesa no encontrada"}), 404
        
    target_promise['estado'] = new_estado
    DatabaseService.save_payment_promise(owner_uid, promise_id, target_promise, sandbox=sandbox)
    
    # Registrar en CRM
    if target_promise.get("clientId"):
        interaction_dict = {
            "type": "CRM",
            "title": f"Promesa de Pago - {new_estado}",
            "content": f"La promesa de pago por RD$ {float(target_promise.get('montoPrometido', 0.0)):,.2f} fue marcada como {new_estado}.",
            "date": datetime.utcnow().isoformat(),
            "completed": True,
            "registeredBy": session['user'].get('name', 'Usuario')
        }
        DatabaseService.save_client_interaction(owner_uid, target_promise["clientId"], str(uuid.uuid4()), interaction_dict, sandbox=sandbox)
        
    return jsonify({"success": True, "message": f"Promesa marcada como {new_estado}."})

@web_invoices_bp.route('/cxc/remind/<invoice_id>/<method>', methods=['POST'])
def send_invoice_cxc_reminder(invoice_id, method):
    if 'user' not in session:
        return jsonify({"success": False, "message": "No autorizado"}), 401
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        return jsonify({"success": False, "message": "Factura no encontrada"}), 404
        
    data = request.get_json(silent=True) or {}
    recipient = data.get("recipient", "").strip()
    custom_message = data.get("message", "").strip() or None
    
    if not recipient:
        if method == 'email':
            recipient = invoice.get("clientEmail", "")
        else:
            recipient = invoice.get("clientPhone", "")
            
    if not recipient:
        return jsonify({"success": False, "message": "No se especificó contacto de destino."}), 400
        
    from app.services.notifications import NotificationService
    portal_url = f"{request.host_url.rstrip('/')}/portal/cliente/{owner_uid}/{invoice.get('clientId')}?sandbox={'true' if sandbox else 'false'}"
    
    success, message = NotificationService.send_cxc_reminder(
        owner_uid=owner_uid,
        invoice=invoice,
        recipient_contact=recipient,
        method=method,
        sandbox=sandbox,
        portal_url=portal_url,
        custom_message=custom_message
    )
    
    if success:
        return jsonify({"success": True, "message": message})
    else:
        return jsonify({"success": False, "message": message}), 500



@web_invoices_bp.route('/reports/bi')
def bi_dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    if not check_permission('canViewBI'):
        return render_template('auth/restricted.html', feature_name="Inteligencia de Negocios (BI)", required_permission="canViewBI")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
    profile = DatabaseService.get_company_profile(owner_uid)
    
    # Filtrar facturas reales
    real_invoices = [inv for inv in invoices if not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador']]
    
    # 1. Ganancia Neta Real
    total_sales_net = sum(inv.get('subtotal', 0.0) for inv in real_invoices)
    total_expenses_net = sum(exp.get('amount', 0.0) - exp.get('itbisAmount', 0.0) for exp in expenses)
    net_profit_real = total_sales_net - total_expenses_net
    profit_margin = (net_profit_real / total_sales_net * 100) if total_sales_net > 0 else 0.0
    
    # Mapa de costos del catálogo
    catalog_cost = {}
    for it in items:
        cost = float(it.get('costPrice', 0.0))
        name_key = it.get('name', '').lower().strip()
        code_key = it.get('code', '').lower().strip()
        if name_key:
            catalog_cost[name_key] = cost
        if code_key:
            catalog_cost[code_key] = cost
            
    # 2. Margen de Beneficio por Producto/Servicio
    product_stats = {}
    for inv in real_invoices:
        for it in inv.get('items', []):
            name = it.get('name', '')
            code = it.get('code', '')
            price = float(it.get('price', 0.0))
            qty = int(it.get('quantity', 1))
            subtotal = float(it.get('subtotal', price * qty))
            
            cost = 0.0
            if code and code.lower().strip() in catalog_cost:
                cost = catalog_cost[code.lower().strip()]
            elif name and name.lower().strip() in catalog_cost:
                cost = catalog_cost[name.lower().strip()]
                
            total_cost = cost * qty
            key = name or code or "Producto Desconocido"
            
            if key not in product_stats:
                product_stats[key] = {
                    "name": key,
                    "qty": 0,
                    "revenue": 0.0,
                    "cost": 0.0
                }
            product_stats[key]["qty"] += qty
            product_stats[key]["revenue"] += subtotal
            product_stats[key]["cost"] += total_cost
            
    for key, stats in product_stats.items():
        rev = stats["revenue"]
        cst = stats["cost"]
        profit = rev - cst
        stats["profit"] = profit
        stats["margin"] = (profit / rev * 100) if rev > 0 else 0.0
        
    products_by_profit = sorted(product_stats.values(), key=lambda x: x["profit"], reverse=True)
    
    # 3. Clientes más rentables
    client_stats = {}
    for inv in real_invoices:
        client_id = inv.get('clientId') or 'Consumidor Final'
        client_name = inv.get('clientName') or 'Consumidor Final'
        subtotal = float(inv.get('subtotal', 0.0))
        
        inv_cost = 0.0
        for it in inv.get('items', []):
            name = it.get('name', '')
            code = it.get('code', '')
            qty = int(it.get('quantity', 1))
            cost = 0.0
            if code and code.lower().strip() in catalog_cost:
                cost = catalog_cost[code.lower().strip()]
            elif name and name.lower().strip() in catalog_cost:
                cost = catalog_cost[name.lower().strip()]
            inv_cost += cost * qty
            
        if client_id not in client_stats:
            client_stats[client_id] = {
                "name": client_name,
                "revenue": 0.0,
                "cost": 0.0,
                "invoice_count": 0
            }
        client_stats[client_id]["revenue"] += subtotal
        client_stats[client_id]["cost"] += inv_cost
        client_stats[client_id]["invoice_count"] += 1
        
    for c_id, stats in client_stats.items():
        rev = stats["revenue"]
        cst = stats["cost"]
        profit = rev - cst
        stats["profit"] = profit
        stats["margin"] = (profit / rev * 100) if rev > 0 else 0.0
        
    clients_by_profit = sorted(client_stats.values(), key=lambda x: x["profit"], reverse=True)
    
    # 4. Flujo de Caja y Presupuestos (Proyección Futura 4 meses)
    now = datetime.now()
    months_projection = []
    
    # Determinar meses
    for i in range(4):
        future_date = now + timedelta(days=30 * i)
        m_label = future_date.strftime("%Y-%m")
        months_projection.append({
            "key": m_label,
            "label": future_date.strftime("%B %Y").capitalize(),
            "inflow": 0.0,
            "outflow": 0.0,
            "net": 0.0
        })
        
    # Agrupar CxC pendientes por mes de vencimiento
    for inv in real_invoices:
        if inv.get('status') in ['Emitida', 'Vencida', 'Parcialmente Cobrada']:
            due_str = inv.get('dueDate', '')[:7] # YYYY-MM
            for m in months_projection:
                if m["key"] == due_str:
                    m["inflow"] += float(inv.get('remainingBalance', 0.0))
                    
    # Agrupar CxP pendientes por mes de vencimiento
    for exp in expenses:
        if exp.get('paymentType') == 'Crédito' and exp.get('cxpStatus') != 'Pagado':
            due_str = exp.get('dueDate', '')[:7] # YYYY-MM
            for m in months_projection:
                if m["key"] == due_str:
                    m["outflow"] += float(exp.get('cxpRemainingBalance', 0.0))
                    
    cumulative = 0.0
    liquidity_warning_month = None
    for m in months_projection:
        m["net"] = m["inflow"] - m["outflow"]
        cumulative += m["net"]
        m["cumulative"] = cumulative
        if cumulative < 0 and not liquidity_warning_month:
            liquidity_warning_month = m["label"]
            
    # 5. Indicadores Tributarios
    total_itbis_sales = sum(float(inv.get('totalITBIS', 0.0)) for inv in real_invoices)
    total_itbis_expenses = sum(float(exp.get('itbisAmount', 0.0)) for exp in expenses if exp.get('isITBISDeductible', True))
    itbis_to_pay = total_itbis_sales - total_itbis_expenses
    
    isr_base = max(0.0, total_sales_net - total_expenses_net)
    isr_estimated = isr_base * 0.27
    anticipos_estimated = isr_estimated / 12.0
    
    # RST Ingresos Simulación
    rst_taxable_base = total_sales_net * 0.60
    # Escala progresiva ISR PF RD 2026 (Exento hasta 416,220, 15% hasta 624,329, 20% hasta 867,123, 25% superior)
    def calc_rst_tax(annual_income):
        if annual_income <= 416220.0:
            return 0.0
        elif annual_income <= 624329.0:
            return (annual_income - 416220.0) * 0.15
        elif annual_income <= 867123.0:
            return 31216.0 + (annual_income - 624329.0) * 0.20
        else:
            return 79775.0 + (annual_income - 867123.0) * 0.25
            
    rst_isr_estimated = calc_rst_tax(rst_taxable_base)
    
    # 6. Smart Insights IA
    insights = []
    
    # A. Reducción de compras de clientes
    client_monthly_sales = {}
    for inv in real_invoices:
        client_name = inv.get('clientName') or 'Consumidor Final'
        if client_name == 'Consumidor Final':
            continue
        date_str = inv.get('date', '')[:7] # YYYY-MM
        if client_name not in client_monthly_sales:
            client_monthly_sales[client_name] = {}
        if date_str not in client_monthly_sales[client_name]:
            client_monthly_sales[client_name][date_str] = 0.0
        client_monthly_sales[client_name][date_str] += float(inv.get('subtotal', 0.0))
        
    current_month_str = now.strftime("%Y-%m")
    for c_name, monthly_data in client_monthly_sales.items():
        if len(monthly_data) >= 2:
            current_sales = monthly_data.get(current_month_str, 0.0)
            other_months = [v for k, v in monthly_data.items() if k != current_month_str]
            avg_historical = sum(other_months) / len(other_months)
            if avg_historical > 10000 and current_sales < (avg_historical * 0.60):
                drop_pct = int((1 - (current_sales / avg_historical)) * 100)
                insights.append({
                    "type": "warning",
                    "text": f"Atención: El cliente {c_name} ha reducido sus compras un {drop_pct}% este mes comparado con su promedio histórico."
                })
                
    # B. Facturas vencidas acumuladas en categoría B2B
    overdue_b2b_total = 0.0
    for inv in real_invoices:
        if inv.get('status') == 'Vencida' and len(inv.get('clientRNC', '').replace('-', '').strip()) >= 9:
            overdue_b2b_total += float(inv.get('remainingBalance', 0.0))
            
    if overdue_b2b_total > 50000:
        insights.append({
            "type": "danger",
            "text": f"Alerta: Tienes RD$ {overdue_b2b_total:,.2f} en facturas vencidas acumuladas de clientes B2B (con RNC)."
        })
        
    # C. Alerta de falta de liquidez
    if liquidity_warning_month:
        insights.append({
            "type": "danger",
            "text": f"Alerta de liquidez: Proyección de flujo de caja neto acumulado negativo detectado para el mes de {liquidity_warning_month}."
        })
        
    # D. Productos con bajo margen
    low_margin_count = 0
    for key, stats in product_stats.items():
        if stats["cost"] > 0 and stats["margin"] < 15.0:
            low_margin_count += 1
            
    if low_margin_count > 0:
        insights.append({
            "type": "info",
            "text": f"Optimización: Detectamos {low_margin_count} productos/servicios con margen de beneficio inferior al 15%."
        })
        
    # Garantizar al menos un insight genérico si la base de datos está vacía
    if not insights:
        insights.append({
            "type": "success",
            "text": "Salud financiera estable. No se detectan anomalías en las compras de clientes ni riesgos de liquidez inmediatos."
        })
        
    return render_template(
        'reports/bi_dashboard.html',
        active_page='bi_dashboard',
        total_sales_net=total_sales_net,
        total_expenses_net=total_expenses_net,
        net_profit_real=net_profit_real,
        profit_margin=profit_margin,
        products_by_profit=products_by_profit[:5],
        clients_by_profit=clients_by_profit[:5],
        months_projection=months_projection,
        total_itbis_sales=total_itbis_sales,
        total_itbis_expenses=total_itbis_expenses,
        itbis_to_pay=itbis_to_pay,
        isr_estimated=isr_estimated,
        anticipos_estimated=anticipos_estimated,
        rst_isr_estimated=rst_isr_estimated,
        insights=insights
    )


@web_invoices_bp.route('/api/ai/receipt-ocr', methods=['POST'])
def api_ai_receipt_ocr():
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    
    file = request.files.get('file')
    if not file:
        return jsonify({"success": False, "error": "No se recibió ningún archivo"}), 400
        
    owner_uid = session['user']['ownerUID']
    file_bytes = file.read()
    mime_type = file.mimetype or "image/jpeg"
    
    from app.services.ai_service import AIService
    res = AIService.analyze_receipt_ocr(owner_uid, file_bytes, mime_type)
    return jsonify(res)


@web_invoices_bp.route('/api/ai/classify-expense', methods=['POST', 'GET'])
def api_ai_classify_expense():
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
        
    concept = request.values.get('concept', '').strip()
    if not concept:
        return jsonify({"success": False, "error": "El concepto es requerido"}), 400
        
    owner_uid = session['user']['ownerUID']
    from app.services.ai_service import AIService
    code = AIService.classify_dgii_expense(owner_uid, concept)
    return jsonify({"success": True, "code": code})


@web_invoices_bp.route('/api/ai/draft-collection', methods=['POST'])
def api_ai_draft_collection():
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
        
    if request.is_json:
        data = request.json
    else:
        data = request.form
        
    client_name = data.get('client_name', '').strip()
    amount_str = data.get('amount', '0.00').strip()
    due_date = data.get('due_date', '').strip()
    status = data.get('status', '').strip()
    tone = data.get('tone', 'formal').strip()
    
    try:
        amount = float(amount_str.replace(',', ''))
    except ValueError:
        amount = 0.00
        
    owner_uid = session['user']['ownerUID']
    from app.services.ai_service import AIService
    message = AIService.draft_collection_message(owner_uid, client_name, amount, due_date, status, tone)
    return jsonify({"success": True, "message": message})


@web_invoices_bp.route('/api/dgii/rnc/<rnc>', methods=['GET'])
def web_lookup_rnc(rnc):
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    try:
        from app.services.dgii import DGIIService
        res = DGIIService.validate_and_fetch_rnc(rnc)
        return jsonify(res)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5001)


