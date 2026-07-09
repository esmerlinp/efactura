import os
import io
import csv
import json
import uuid
import html
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file, make_response
import qrcode
try:
    from weasyprint import HTML as WeasyprintHTML
    WEASYPRINT_AVAILABLE = True
    print("✅ WeasyPrint cargado correctamente en invoices.py")
except Exception as e:
    import logging
    logging.exception("Error al cargar WeasyPrint en invoices.py")
    print("❌ ERROR AL CARGAR WEASYPRINT en invoices.py:")
    WEASYPRINT_AVAILABLE = False
import random
from config import Config
from app.services.db_service import DatabaseService
from app.services.mailer import Mailer
from app.services.dgii import DGIIService
from app.utils.currency import CurrencyService
from app.services.ecf_emission import EcfEmissionService
from app.services.dgii_direct import DgiiDirectService
from app.services.recurrence import RecurrenceService
from app.utils.decorators import check_permission, require_permission
from app.utils.module_gate import require_module
from app.utils.ecf_utils import get_ecf_type_short_code
from app.brand import get_product_name


from flask import Blueprint
web_invoices_bp = Blueprint('web_invoices', __name__)

def check_document_limit_exceeded(owner_uid, sandbox=True):
    """
    Verifica si la empresa ha excedido su límite de documentos emitidos.
    Retorna (excedido, mensaje_advertencia_o_error).
    """
    if sandbox:
        return False, ""
        
    profile = DatabaseService.get_company_profile(owner_uid)
    if not profile:
        return False, ""
        
    document_limit = profile.get('documentLimit')
    if not document_limit:
        return False, ""
        
    try:
        document_limit = int(document_limit)
    except ValueError:
        return False, ""
        
    billing_day = profile.get('billingDay', 1)
    stats = DatabaseService.get_invoice_stats(owner_uid, billing_day)
    docs_used = stats['prod_current_cycle']
    
    if docs_used >= document_limit:
        additional_cost = float(profile.get('additionalDocumentCost', 0.0))
        if additional_cost > 0:
            return False, f"Advertencia: Has alcanzado el límite de {document_limit} documentos. Este y los siguientes documentos tendrán un costo adicional de RD$ {additional_cost:.2f}."
        else:
            return True, f"Límite de documentos excedido ({document_limit} documentos en tu plan). Por favor, contacta al administrador del portal para actualizar tu plan."
            
    return False, ""


def _company_has_issued_documents(owner_uid, sandbox=True):
    """Retorna True si la empresa tiene al menos un documento emitido (no borrador, no cotización)."""
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    for inv in invoices:
        if not inv.get('isQuotation') and inv.get('status') not in ('Borrador', 'Anulada', 'Pagado pero no emitido'):
            return True
    return False


# =========================================================================
# CONTROLADORES DE RUTA - AUTENTICACIÓN
# =========================================================================
# =========================================================================
# CATÁLOGO DE ARTÍCULOS
# =========================================================================
@web_invoices_bp.route('/items')
def list_items():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Catálogo de Productos", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
    
    if request.args.get('export') == 'csv':
        import io
        from datetime import datetime
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["Código SKU", "Código de Barra", "Nombre / Descripción", "Categoría", "Tipo", "Medida", "Ubicación Pasillo", "Tasa ITBIS", "Costo Unitario", "Precio Venta", "Existencia/Stock", "Estado"])
        for item in items:
            writer.writerow([
                item.get("code", "S/C"),
                item.get("barcode", ""),
                item.get("name", ""),
                item.get("categoryId", "general"),
                item.get("type", "Bien"),
                item.get("unit", "Unidad"),
                item.get("rackLocation", ""),
                f"{item.get('itbisRate', 0.18):.2%}",
                f"{item.get('costPrice', 0.0):.2f}",
                f"{item.get('price', 0.0):.2f}",
                f"{item.get('totalStock', 0.0):.2f}" if item.get('type', 'Bien') == 'Bien' else "N/A",
                "Activo" if item.get("isActive", True) else "Inactivo"
            ])
        dest = io.BytesIO()
        dest.write(b'\xef\xbb\xbf')  # UTF-8 BOM
        dest.write(output.getvalue().encode('utf-8'))
        dest.seek(0)
        filename = f"catalogo_general_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(
            dest,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )

    return render_template('items/list.html', active_page='items', items=items)

@web_invoices_bp.route('/items/new', methods=['GET', 'POST'])
def new_item():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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
        return redirect(url_for('web_invoices.list_items'))
        
    categories = DatabaseService.get_categories(owner_uid, sandbox=sandbox)
    return render_template('items/form.html', active_page='items', item=None, categories=categories)

@web_invoices_bp.route('/items/<item_id>/edit', methods=['GET', 'POST'])
def edit_item(item_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Editar Artículo", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
    item = next((it for it in items if it['id'] == item_id), None)
    
    if not item:
        flash('Artículo no encontrado.', 'error')
        return redirect(url_for('web_invoices.list_items'))
        
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
        return redirect(url_for('web_invoices.list_items'))
        
    categories = DatabaseService.get_categories(owner_uid, sandbox=sandbox)
    return render_template('items/form.html', active_page='items', item=item, categories=categories)

@web_invoices_bp.route('/items/<item_id>/delete', methods=['POST'])
def delete_item_route(item_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Eliminar Artículo", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    DatabaseService.delete_item(owner_uid, item_id, sandbox=sandbox)
    flash('Artículo eliminado del catálogo.', 'success')
    return redirect(url_for('web_invoices.list_items'))

@web_invoices_bp.route('/items/upload-image', methods=['POST'])
def upload_item_image():
    if 'user' not in session: return jsonify({"success": False, "error": "No autorizado"}), 401
    
    owner_uid = session['user']['ownerUID']
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({"success": False, "error": "Archivo no válido"}), 400
        
    try:
        file_data = file.read()
        mime_type = file.mimetype or "image/jpeg"
        filename = f"img_{str(uuid.uuid4())[:8]}_{file.filename}"
        destination_path = f"users/{owner_uid}/item_images/{filename}"
        
        # Guardar en Firebase Storage
        url = DatabaseService.upload_file_to_storage(
            file_data=file_data,
            destination_path=destination_path,
            mime_type=mime_type
        )
        return jsonify({"success": True, "url": url})
    except Exception as e:
        return jsonify({"success": False, "error": html.escape(str(e))}), 500

@web_invoices_bp.route('/items/import-csv', methods=['POST'])
def import_items_csv():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Importar Catálogo CSV", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    file = request.files.get('csv_file')
    if not file or not file.filename.endswith('.csv'):
        flash('Por favor sube un archivo con formato .csv válido.', 'error')
        return redirect(url_for('web_invoices.list_items'))
        
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
        
    return redirect(url_for('web_invoices.list_items'))

@web_invoices_bp.route('/items/download-template')
def download_csv_template():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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
        download_name="plantilla_items_vykone.csv"
    )

@web_invoices_bp.route('/inventory/export-stock')
def export_stock_report():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageInventory'):
        return render_template('auth/restricted.html', feature_name="Reporte de Existencia", required_permission="canManageInventory")
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
        
    goods = [p for p in items if p.get('type', 'Bien') == 'Bien']
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    headers = ["Codigo SKU", "Nombre / Descripcion", "Categoria", "Marca", "Proveedor Principal", "Ubicacion Pasillo"]
    for wh in warehouses:
        headers.append(f"Stock ({wh.get('name')})")
    headers.extend(["Existencia Total", "Costo Unitario", "Precio Venta", "Valor Total Inventario (Costo)", "Valor Total Inventario (Venta)", "Estado"])
    writer.writerow(headers)
    
    for p in goods:
        qty = float(p.get("totalStock", 0.0))
        cost = float(p.get("costPrice", 0.0))
        price = float(p.get("price", 0.0))
        val_cost = qty * cost
        val_sale = qty * price
        
        row = [
            p.get("code", "S/C"),
            p.get("name", ""),
            p.get("categoryId", "general"),
            p.get("brand", ""),
            p.get("supplierName", ""),
            p.get("rackLocation", ""),
        ]
        # Stock de cada almacén
        for wh in warehouses:
            wh_qty = stock_map.get(f"{p['id']}_{wh['id']}", 0.0)
            row.append(f"{wh_qty:.2f}")
            
        row.extend([
            f"{qty:.2f}",
            f"{cost:.2f}",
            f"{price:.2f}",
            f"{val_cost:.2f}",
            f"{val_sale:.2f}",
            "Activo" if p.get("isActive", True) else "Inactivo"
        ])
        writer.writerow(row)
        
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    dest = io.BytesIO()
    dest.write(b'\xef\xbb\xbf')  # UTF-8 BOM
    dest.write(output.getvalue().encode('utf-8'))
    dest.seek(0)
    return send_file(
        dest,
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"inventario_almacen_{timestamp}.csv"
    )


# =========================================================================
# LISTAS DE PRECIOS (PRICE LISTS)
# =========================================================================
@web_invoices_bp.route('/price-lists')
def list_price_lists():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    price_lists = DatabaseService.get_price_lists(owner_uid, sandbox=sandbox)
    return render_template('price_lists/list.html', active_page='price_lists', price_lists=price_lists)

@web_invoices_bp.route('/price-lists/new', methods=['GET', 'POST'])
def new_price_list():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    if request.method == 'POST':
        list_id = str(uuid.uuid4())
        list_dict = {
            "name": request.form.get('name', '').strip(),
            "description": request.form.get('description', '').strip(),
            "isDefault": 'isDefault' in request.form,
            "isActive": True
        }
        if not list_dict["name"]:
            flash('El nombre de la lista de precios es obligatorio.', 'error')
            return render_template('price_lists/form.html', active_page='price_lists', price_list=None)

        DatabaseService.save_price_list(owner_uid, list_id, list_dict, sandbox=sandbox)
        flash('Lista de precios creada exitosamente.', 'success')
        return redirect(url_for('web_invoices.list_price_lists'))

    return render_template('price_lists/form.html', active_page='price_lists', price_list=None)

@web_invoices_bp.route('/price-lists/<list_id>/edit', methods=['GET', 'POST'])
def edit_price_list(list_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    price_list = DatabaseService.get_price_list(owner_uid, list_id, sandbox=sandbox)
    if not price_list:
        flash('Lista de precios no encontrada.', 'error')
        return redirect(url_for('web_invoices.list_price_lists'))

    if request.method == 'POST':
        list_dict = {
            "name": request.form.get('name', '').strip(),
            "description": request.form.get('description', '').strip(),
            "isDefault": 'isDefault' in request.form,
            "isActive": 'isActive' in request.form,
            "createdAt": price_list.get("createdAt")
        }
        if not list_dict["name"]:
            flash('El nombre de la lista de precios es obligatorio.', 'error')
            return render_template('price_lists/form.html', active_page='price_lists', price_list=price_list)

        DatabaseService.save_price_list(owner_uid, list_id, list_dict, sandbox=sandbox)
        flash('Lista de precios actualizada exitosamente.', 'success')
        return redirect(url_for('web_invoices.list_price_lists'))

    return render_template('price_lists/form.html', active_page='price_lists', price_list=price_list)

@web_invoices_bp.route('/price-lists/<list_id>/delete', methods=['POST'])
def delete_price_list(list_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    DatabaseService.delete_price_list(owner_uid, list_id, sandbox=sandbox)
    flash('Lista de precios eliminada.', 'success')
    return redirect(url_for('web_invoices.list_price_lists'))

@web_invoices_bp.route('/price-lists/<list_id>/items', methods=['GET', 'POST'])
def manage_price_list_items(list_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    price_list = DatabaseService.get_price_list(owner_uid, list_id, sandbox=sandbox)
    if not price_list:
        flash('Lista de precios no encontrada.', 'error')
        return redirect(url_for('web_invoices.list_price_lists'))

    if request.method == 'POST':
        item_id = request.form.get('item_id', '')

        if not item_id:
            flash('Debes seleccionar un producto.', 'error')
        elif request.form.get('delete_price') == '1':
            DatabaseService.delete_price_list_item(owner_uid, list_id, item_id, sandbox=sandbox)
            flash('Precio eliminado de la lista.', 'success')
        else:
            price = float(request.form.get('price') or 0.0)
            cost_price = float(request.form.get('costPrice') or 0.0)
            wholesale_price = float(request.form.get('wholesalePrice') or 0.0)
            price_dict = {
                "price": price,
                "costPrice": cost_price,
                "wholesalePrice": wholesale_price
            }
            DatabaseService.save_price_list_item(owner_uid, list_id, item_id, price_dict, sandbox=sandbox)
            flash('Precio asignado exitosamente.', 'success')
        return redirect(url_for('web_invoices.manage_price_list_items', list_id=list_id))

    items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
    price_list_items = DatabaseService.get_price_list_items(owner_uid, list_id, sandbox=sandbox)

    # Combinar items con sus precios en la lista
    catalog = []
    for item in items:
        item_copy = dict(item)
        price_data = price_list_items.get(item['id'], {})
        item_copy['listPrice'] = price_data.get('price', 0.0)
        item_copy['listCostPrice'] = price_data.get('costPrice', 0.0)
        item_copy['listWholesalePrice'] = price_data.get('wholesalePrice', 0.0)
        item_copy['hasPrice'] = item['id'] in price_list_items
        catalog.append(item_copy)

    return render_template('price_lists/items.html', active_page='price_lists',
                          price_list=price_list, catalog=catalog)

@web_invoices_bp.route('/price-lists/ajax_get_price', methods=['POST'])
def ajax_get_price_list_price():
    if 'user' not in session: return jsonify({"success": False, "error": "No autorizado"}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    price_list_id = request.form.get('price_list_id', '')
    item_id = request.form.get('item_id', '')

    if not price_list_id or not item_id:
        return jsonify({"success": False, "error": "Faltan parámetros"}), 400

    price_list_items = DatabaseService.get_price_list_items(owner_uid, price_list_id, sandbox=sandbox)
    price_data = price_list_items.get(item_id, {})

    return jsonify({
        "success": True,
        "price": price_data.get('price', 0.0),
        "costPrice": price_data.get('costPrice', 0.0),
        "wholesalePrice": price_data.get('wholesalePrice', 0.0)
    })


@web_invoices_bp.route('/price-lists/ajax_create', methods=['POST'])
def ajax_create_price_list():
    """Endpoint AJAX para crear una lista de precios desde el formulario de documento."""
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    tipo = (data.get('tipo') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'El nombre es obligatorio'}), 400
    if not tipo:
        return jsonify({'success': False, 'error': 'El tipo es obligatorio'}), 400
    list_id = str(uuid.uuid4())
    list_dict = {
        'name': name,
        'tipo': tipo,
        'description': (data.get('description') or '').strip(),
        'isDefault': False,
        'isActive': True,
    }
    DatabaseService.save_price_list(owner_uid, list_id, list_dict, sandbox=sandbox)
    return jsonify({'success': True, 'id': list_id, 'name': name, 'tipo': tipo})


@web_invoices_bp.route('/api/quick-create-product', methods=['POST'])
def quick_create_product():
    """Endpoint AJAX para crear un producto rápido desde el formulario de documento."""
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'El nombre es obligatorio'}), 400
    price = float(data.get('price', 0))
    if price < 0:
        return jsonify({'success': False, 'error': 'El precio no puede ser negativo'}), 400
    item_type = data.get('type', 'Bien')
    itbis_rate = float(data.get('itbisRate', 0.18))
    cost_price = float(data.get('costPrice', 0))
    item_id = str(uuid.uuid4())
    code = data.get('code') or ('ITEM-' + item_id[:6].upper())
    item_dict = {
        'code': code,
        'type': item_type,
        'name': name,
        'price': price,
        'unit': data.get('unit', 'Unidad'),
        'itbisRate': itbis_rate,
        'costPrice': cost_price,
        'categoryId': data.get('categoryId', 'general'),
        'totalStock': 0.0,
        'minStock': 0.0,
        'isActive': True,
    }
    DatabaseService.save_item(owner_uid, item_id, item_dict, sandbox=sandbox)
    return jsonify({'success': True, 'item': {'id': item_id, 'code': code, 'name': name, 'price': price, 'type': item_type, 'itbisRate': itbis_rate, 'costPrice': cost_price}})


# =========================================================================
# GESTIÓN DE INVENTARIO Y ALMACENES
# =========================================================================
@web_invoices_bp.route('/inventory')
def inventory_dashboard():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageInventory'):
        return render_template('auth/restricted.html', feature_name="Almacenes", required_permission="canManageInventory")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox)
    return render_template('inventario/almacenes.html', active_page='inventory', warehouses=warehouses)

@web_invoices_bp.route('/inventory/warehouses/new', methods=['GET', 'POST'])
def new_warehouse():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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
        return redirect(url_for('web_invoices.inventory_warehouses'))
        
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
    return render_template('inventario/warehouse_form.html', active_page='inventory', warehouse=None, branches=branches)

@web_invoices_bp.route('/inventory/warehouses/<warehouse_id>/edit', methods=['GET', 'POST'])
def edit_warehouse(warehouse_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageInventory'):
        return render_template('auth/restricted.html', feature_name="Editar Almacén", required_permission="canManageInventory")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox)
    warehouse = next((w for w in warehouses if w['id'] == warehouse_id), None)
    if not warehouse:
        flash('Almacén no encontrado.', 'error')
        return redirect(url_for('web_invoices.inventory_warehouses'))
        
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
        return redirect(url_for('web_invoices.inventory_warehouses'))
        
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
    return render_template('inventario/warehouse_form.html', active_page='inventory', warehouse=warehouse, branches=branches)

@web_invoices_bp.route('/inventory/warehouses/<warehouse_id>/delete', methods=['POST'])
def delete_warehouse_route(warehouse_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageInventory'):
        return render_template('auth/restricted.html', feature_name="Eliminar Almacén", required_permission="canManageInventory")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    # Evitar borrar el almacén predeterminado si es el único
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox)
    if len(warehouses) <= 1:
        flash('Debe mantener al menos un almacén activo en el sistema.', 'error')
        return redirect(url_for('web_invoices.inventory_warehouses'))
        
    DatabaseService.delete_warehouse(owner_uid, warehouse_id, sandbox=sandbox)
    flash('Almacén eliminado correctamente.', 'success')
    return redirect(url_for('web_invoices.inventory_warehouses'))

@web_invoices_bp.route('/inventory/transactions')
def inventory_transactions():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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
            
        return redirect(url_for('web_invoices.inventory_dashboard'))
        
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
@web_invoices_bp.route('/invoices', strict_slashes=False)
def list_invoices():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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
    
    # Incluir gastos E41/E43 como documentos en la misma lista
    all_expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    ecf_expenses = []
    for exp in all_expenses:
        if exp.get("ecfType") in ("E41", "E43") and exp.get("encf"):
            ecf_expenses.append({
                "id": exp["id"],
                "invoiceNumber": exp.get("encf", ""),
                "encf": exp.get("encf", ""),
                "ecfType": "Comprobante de Compras (E41)" if exp.get("ecfType") == "E41" else "Gastos Menores (E43)",
                "ecfShortType": exp.get("ecfType", ""),
                "date": exp.get("date", ""),
                "dueDate": exp.get("dueDate", ""),
                "clientName": exp.get("providerName", "Proveedor"),
                "clientRNC": exp.get("rncEmisor", ""),
                "total": exp.get("amount", 0.0),
                "subtotal": (exp.get("amount", 0.0) or 0.0) - (exp.get("itbisAmount", 0.0) or 0.0),
                "paymentType": exp.get("paymentType", "Contado"),
                "status": "Emitida",
                "isSyncedWithDGII": exp.get("isSyncedWithDGII", False),
                "emisionMode": exp.get("emisionMode", ""),
                "xmlSignature": exp.get("xmlSignature", ""),
                "qrCodeURL": exp.get("qrCodeURL", ""),
                "isExpense": True,
                "netPayable": exp.get("amount", 0.0),
                "remainingBalance": 0.0,
                "providerName": exp.get("providerName", ""),
                "rncEmisor": exp.get("rncEmisor", ""),
                "concept": exp.get("concept", ""),
                "notes": exp.get("notes", "")
            })
    all_docs = invoices + ecf_expenses
    all_docs.sort(key=lambda d: d.get("date", "") or "", reverse=True)
    
    # Filtrar
    filtered = []
    for inv in all_docs:
        if q:
            q_lower = q.lower()
            if (q_lower not in inv.get('invoiceNumber', '').lower() and 
                q_lower not in inv.get('clientName', '').lower() and 
                q_lower not in inv.get('clientRNC', '').lower() and 
                q_lower not in inv.get('encf', '').lower()):
                continue
        if status:
            if status == "Pendiente DGII":
                if not (
                    (inv.get('emisionMode') == 'FALLBACK' and not inv.get('isSyncedWithDGII') and inv.get('status') != 'Anulada')
                    or inv.get('status') == 'Pendiente DGII'
                    or inv.get('dgiiStatus') in ['PENDING', 'CONTINGENCY']
                ):
                    continue
            elif status == "Con Saldo Pendiente":
                if not (inv.get('netPayable', 0.0) > 0.0 and inv.get('status') not in ['Anulada', 'Borrador', 'Cobrada', 'Pagado pero no emitido']):
                    continue
            elif inv.get('status') != status:
                continue
        inv_date = inv.get('date', '')[:10]
        if start_date and inv_date < start_date:
            continue
        if end_date and inv_date > end_date:
            continue
        filtered.append(inv)

    # Exportar a CSV si se solicita
    if request.args.get('export') == 'csv':
        import io
        from datetime import datetime
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["Número de Factura", "Cliente", "RNC", "Fecha", "Fecha Vencimiento", "Subtotal (RD$)", "Total (RD$)", "Pendiente (RD$)", "Estatus", "NCF / e-CF", "Tipo e-CF"])
        for inv in filtered:
            writer.writerow([
                inv.get("invoiceNumber", ""),
                inv.get("clientName", ""),
                inv.get("clientRNC", ""),
                inv.get("date", "")[:10],
                inv.get("dueDate", "")[:10],
                f"{inv.get('subtotal', 0.0):.2f}",
                f"{inv.get('total', 0.0):.2f}",
                f"{inv.get('remainingBalance', inv.get('netPayable', 0.0)):.2f}",
                inv.get("status", ""),
                inv.get("encf", ""),
                inv.get("ecfType", "")
            ])
        dest = io.BytesIO()
        dest.write(b'\xef\xbb\xbf')  # UTF-8 BOM
        dest.write(output.getvalue().encode('utf-8'))
        dest.seek(0)
        filename = f"documentos_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(
            dest,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )
        
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
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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

    # Exportar a CSV si se solicita
    if request.args.get('export') == 'csv':
        import io
        from datetime import datetime
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["Número de Cotización", "Cliente", "RNC", "Fecha", "Subtotal (RD$)", "Total (RD$)", "Estatus"])
        for inv in filtered:
            writer.writerow([
                inv.get("invoiceNumber", ""),
                inv.get("clientName", ""),
                inv.get("clientRNC", ""),
                inv.get("date", "")[:10],
                f"{inv.get('subtotal', 0.0):.2f}",
                f"{inv.get('total', 0.0):.2f}",
                inv.get("status", "")
            ])
        dest = io.BytesIO()
        dest.write(b'\xef\xbb\xbf')  # UTF-8 BOM
        dest.write(output.getvalue().encode('utf-8'))
        dest.seek(0)
        filename = f"cotizaciones_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(
            dest,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )
        
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
    if invoice_id and 'user' in session:
        owner_uid = session['user']['ownerUID']
        sandbox = session.get('is_sandbox_mode', True)
        source = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
        if source and source.get('isProfessional'):
            return redirect(url_for('web_invoices.professional_quotation_route', clone=invoice_id))
    return _new_document_helper(invoice_id=invoice_id, is_quotation=False)

@web_invoices_bp.route('/quotations/new', methods=['GET', 'POST'])
@web_invoices_bp.route('/quotations/<invoice_id>/edit', methods=['GET', 'POST'])
def new_quotation_route(invoice_id=None):
    # Redirect professional quotations to the professional wizard
    if invoice_id and 'user' in session:
        owner_uid = session['user']['ownerUID']
        sandbox = session.get('is_sandbox_mode', True)
        source = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
        if source and source.get('isProfessional'):
            return redirect(url_for('web_invoices.professional_quotation_route', clone=invoice_id))
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
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    # Redirect professional quotations to the professional wizard
    if invoice_id:
        owner_uid = session['user']['ownerUID']
        sandbox = session.get('is_sandbox_mode', True)
        source = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
        if source and source.get('isProfessional'):
            return redirect(url_for('web_invoices.professional_quotation_route', clone=invoice_id))
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
        if existing_invoice.get('status') not in ['Borrador', 'Rechazada', 'Pagado pero no emitido']:
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
                            "ncfModifiedDate": ref_inv.get("date", "")[:10] if ref_inv.get("date") else datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                            "reasonForModification": "Corrección de importes"
                        }
                    }
            
            # Clone quotation
            clone_id = request.args.get('clone')
            if clone_id:
                source = DatabaseService.get_invoice(owner_uid, clone_id, sandbox=sandbox)
                if source:
                    existing_invoice = source.copy()
                    existing_invoice.pop('id', None)
                    existing_invoice['isQuotation'] = True
                    existing_invoice['status'] = 'Borrador'
                    existing_invoice['encf'] = ''
                    existing_invoice.pop('convertedToInvoiceId', None)
                    existing_invoice.pop('convertedInvoiceNumber', None)
                    existing_invoice.pop('createdAt', None)
                    existing_invoice.pop('createdBy', None)
 
    if existing_invoice:
        is_quotation_route = existing_invoice.get('isQuotation', False)
    else:
        is_quotation_route = is_quotation
        
    active_page = 'quotations' if is_quotation_route else 'invoices'
    
    if request.method == 'POST':
        idempotency_key = request.headers.get('Idempotency-Key') or request.form.get('idempotency_key')
        if idempotency_key:
            record = DatabaseService.get_idempotency_record(owner_uid, idempotency_key, sandbox=sandbox)
            if record and record.get("invoiceId"):
                return redirect(url_for('web_invoices.invoice_detail', invoice_id=record["invoiceId"]))

        # 0. Validar período fiscal abierto (bloquea modificaciones en períodos cerrados)
        from app.services.fiscal_period_service import FiscalPeriodService
        invoice_date = request.form.get('date') or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            FiscalPeriodService.validate_period_open(owner_uid, invoice_date)
        except ValueError as e:
            flash(str(e), 'error')
            return redirect(request.path)

        # 1. Validar régimen fiscal
        profile = DatabaseService.get_company_profile(owner_uid)
        regimen = DGIIService.normalize_regimen(profile.get("regimenFiscal", "ordinary")) if profile else "ordinary"
        regimen_rules = DGIIService.get_regimen_rules(regimen)
        ecf_code_from_form = request.form.get('ecfType', 'Factura de Consumo (E32)')

        # 1. Obtener campos principales
        client_id = request.form.get('clientId')
        ecf_type = ecf_code_from_form
        if is_quotation_route:
            ecf_type = "Cotización"
        elif regimen_rules.get("allowed_ecf_types"):
            ecf_code = ecf_type.split("(")[-1].replace(")", "").strip() if "(" in ecf_type else ecf_type
            if ecf_code not in regimen_rules["allowed_ecf_types"]:
                flash(f'❌ Su régimen ({regimen}) no permite el tipo de comprobante {ecf_type}. Tipos permitidos: {", ".join(regimen_rules["allowed_ecf_types"])}', 'error')
                return redirect(url_for('web_invoices.list_invoices'))
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
            if not regimen_rules.get("itbis_enabled", True):
                itbis_rate = 0.0
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
                    
                due_date_inst = (datetime.now(timezone.utc) + timedelta(days=days_add)).strftime("%Y-%m-%d")
                
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
            invoice_dict["footer"] = request.form.get('footer', '')
            invoice_dict["isRecurring"] = is_recurring
            invoice_dict["recurrenceInterval"] = recurrence_interval
            invoice_dict["nextOccurrenceDate"] = next_occurrence if is_recurring else None
            invoice_dict["currency"] = currency
            invoice_dict["paymentType"] = request.form.get('paymentType') or ("Crédito" if due_date > datetime.now(timezone.utc).strftime("%Y-%m-%d") else "Contado")
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
            invoice_dict["costCenterId"] = request.form.get('costCenterId', '') or ''
            invoice_dict["priceListId"] = request.form.get('priceListId', '') or ''
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
                "footer": request.form.get('footer', ''),
                "isRecurring": is_recurring,
                "recurrenceInterval": recurrence_interval,
                "nextOccurrenceDate": next_occurrence if is_recurring else None,
                "firebasePDFURL": "",
                "firebaseXMLURL": "",
                "currency": currency,
                "paymentType": request.form.get('paymentType') or ("Crédito" if due_date > datetime.now(timezone.utc).strftime("%Y-%m-%d") else "Contado"),
                "paymentMethod": payment_method,
                "incomeType": income_type,
                "customFields": [],
                "exchangeRate": float(request.form.get('exchangeRate', 0) or 0) or CurrencyService.get_rate(currency),
                "warehouseId": request.form.get('warehouseId', ''),
                "branchId": request.form.get('branchId', 'default-sucursal-principal'),
                "items": calcs["items"],
                "totalPaid": 0.0,
                "remainingBalance": calcs["net_payable"],
                "paymentAgreement": agreement,
                "installments": installments,
                "costCenterId": request.form.get('costCenterId', '') or '',
                "priceListId": request.form.get('priceListId', '') or '',
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
        if idempotency_key:
            DatabaseService.save_idempotency_record(owner_uid, idempotency_key, {
                "response": {
                    "invoiceId": target_invoice_id
                },
                "statusCode": 200,
                "invoiceId": target_invoice_id
            }, sandbox=sandbox)
        
        from app.services.audit_service import AuditService, ACTION_CREATE, ACTION_UPDATE, MODULE_FACTURAS, MODULE_COTIZACIONES
        audit_action = ACTION_UPDATE if existing_invoice else ACTION_CREATE
        audit_module = MODULE_COTIZACIONES if is_quotation else MODULE_FACTURAS
        label_prefix = "Cotización" if is_quotation else f"Documento ({invoice_dict.get('ecfType') or 'Factura'})"
        verb = "modificada" if existing_invoice else "creada"
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=audit_action,
            module=audit_module,
            entity_id=target_invoice_id,
            entity_label=f"{label_prefix} {invoice_dict['invoiceNumber']} {verb} — Cliente: {client_name} (Total: RD$ {calcs['total']:,.2f})",
            user_session=session.get('user', {}),
            before=existing_invoice if existing_invoice else None,
            after=invoice_dict,
            sandbox=sandbox
        )
        
        action = request.form.get('action')
        
        if is_quotation:
            flash('Cotización creada exitosamente como borrador.', 'success')
            return redirect(url_for('web_invoices.list_quotations'))
        elif action in ['emitir_cobrar', 'emitir_credito']:
            exceeded, limit_msg = check_document_limit_exceeded(owner_uid, sandbox=sandbox)
            if exceeded:
                flash(limit_msg, 'error')
                return redirect(url_for('web_invoices.list_invoices'))
            elif limit_msg:
                flash(limit_msg, 'warning')
                
            company = DatabaseService.get_company_profile(owner_uid)
            try:
                if not invoice_dict.get("encf"):
                    ecf_short = get_ecf_type_short_code(invoice_dict["ecfType"])
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
                    invoice_dict["isSyncedWithDGII"] = (res.get("mode", "API") == "API" and res.get("status") != "PENDING")
                    invoice_dict["emisionMode"] = res.get("mode", "API")
                    pending_dgii = res.get("status") == "PENDING" or res.get("mode") == "FALLBACK"
                    invoice_dict["dgiiStatus"] = res.get("dgiiStatus") or ("PENDING" if pending_dgii else "ACCEPTED")
                    invoice_dict["contingencyEmittedAt"] = datetime.now(timezone.utc).isoformat() if res.get("mode") == "FALLBACK" else None
                    
                    if action == 'emitir_cobrar':
                        invoice_dict["status"] = "Pendiente DGII" if pending_dgii else "Cobrada"
                        invoice_dict["totalPaid"] = invoice_dict["netPayable"]
                        invoice_dict["remainingBalance"] = 0.0
                        invoice_dict["paymentDate"] = datetime.now(timezone.utc).isoformat()
                        
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
                        # Generar asiento contable automático
                        from app.services.accounting_service import AccountingService
                        entry = AccountingService.auto_generate_invoice_entry(owner_uid, invoice_dict, sandbox=sandbox)
                        if entry:
                            flash(f'✅ Asiento contable {entry["number"]} generado automáticamente.', 'info')
                        else:
                            import logging
                            logging.getLogger(__name__).warning(f"Asiento contable no generado para factura {invoice_dict.get('invoiceNumber')}")

                        # Event Bus: notificar emisión de factura cobrada
                        try:
                            from app.events import get_event_bus, InvoiceEmitted
                            get_event_bus().publish(InvoiceEmitted(
                                owner_uid=owner_uid,
                                invoice_id=target_invoice_id,
                                invoice_number=invoice_dict.get("invoiceNumber", ""),
                                invoice_data=invoice_dict,
                                sandbox=sandbox,
                            ))
                        except Exception:
                            pass
                    else:
                        invoice_dict["status"] = "Pendiente DGII" if pending_dgii else "Emitida"
                        invoice_dict["totalPaid"] = 0.0
                        invoice_dict["remainingBalance"] = invoice_dict["netPayable"]
                        DatabaseService.save_invoice(owner_uid, target_invoice_id, invoice_dict, sandbox=sandbox)
                        # Generar asiento contable automático para notas de crédito/débito
                        from app.services.accounting_service import AccountingService
                        if ecf_type in ["Nota de Crédito (E34)", "Nota de Débito (E33)"]:
                            entry = AccountingService.auto_generate_credit_note_entry(owner_uid, invoice_dict, sandbox=sandbox)
                        else:
                            entry = AccountingService.auto_generate_invoice_entry(owner_uid, invoice_dict, sandbox=sandbox)
                        if entry:
                            flash(f'✅ Asiento contable {entry["number"]} generado automáticamente.', 'info')
                        else:
                            import logging
                            logging.getLogger(__name__).warning(f"Asiento contable no generado para {invoice_dict.get('invoiceNumber')}")

                        # Event Bus: notificar emisión de factura
                        try:
                            from app.events import get_event_bus, InvoiceEmitted
                            get_event_bus().publish(InvoiceEmitted(
                                owner_uid=owner_uid,
                                invoice_id=target_invoice_id,
                                invoice_number=invoice_dict.get("invoiceNumber", ""),
                                invoice_data=invoice_dict,
                                sandbox=sandbox,
                            ))
                        except Exception:
                            pass
                    
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
                        msg = f"⚠️ ¡Comprobante emitido en modalidad de contingencia (sin conexión a DGII)! e-NCF: {res.get('encf')}. Recuerde sincronizarlo con la DGII en un plazo máximo de 72 horas."
                    flash(msg, "success")
                else:
                    flash(f"Borrador creado, pero error al emitir: {res.get('message')}", "warning")
            except Exception as e:
                flash(f"Borrador creado, pero fallo en emisión: {str(e)}", "error")
            return redirect(url_for('web_invoices.invoice_detail', invoice_id=target_invoice_id))
        else:
            flash('Borrador de documento guardado exitosamente.', 'success')
            return redirect(url_for('web_invoices.invoice_detail', invoice_id=target_invoice_id))

    # Cargar catálogo de ítems, clientes y almacenes para alimentar form
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
    catalog = [it for it in DatabaseService.get_items(owner_uid, sandbox=sandbox) if it.get('isActive', True)]
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox)
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
    catalog_json = json.dumps(catalog)
    clients_json = json.dumps(clients)

    # Cargar listas de precios para integración en facturación
    price_lists = DatabaseService.get_price_lists(owner_uid, sandbox=sandbox)
    active_price_lists = [pl for pl in price_lists if pl.get('isActive', True)]
    price_list_prices = {}
    for pl in price_lists:
        if pl.get('isActive', True):
            prices = DatabaseService.get_price_list_items(owner_uid, pl['id'], sandbox=sandbox)
            if prices:
                price_list_prices[pl['id']] = {}
                for item_id, price_data in prices.items():
                    price_list_prices[pl['id']][item_id] = {
                        "price": price_data.get('price', 0.0),
                        "costPrice": price_data.get('costPrice', 0.0),
                        "wholesalePrice": price_data.get('wholesalePrice', 0.0)
                    }
    price_list_prices_json = json.dumps(price_list_prices)

    # Cargar centros de costo para el formulario de documento
    cost_centers = DatabaseService.get_cost_centers(owner_uid, sandbox=sandbox)
    active_cost_centers = [cc for cc in cost_centers if cc.get('isActive', True)]

    default_due_date = existing_invoice.get('dueDate', (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")) if existing_invoice else (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

    return render_template(
        'invoices/new.html',
        active_page=active_page,
        clients=clients,
        catalog_json=catalog_json,
        clients_json=clients_json,
        default_due_date=default_due_date,
        warehouses=warehouses,
        branches=branches,
        invoice=existing_invoice,
        price_list_prices_json=price_list_prices_json,
        price_lists=active_price_lists,
        cost_centers=active_cost_centers,
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

import html
from markupsafe import Markup
import re

def format_mentions(content, users):
    if not content:
        return ""
    escaped_content = html.escape(content)
    sorted_users = sorted(users, key=lambda x: len(x.get("name", "")), reverse=True)
    for u in sorted_users:
        name = u.get("name", "")
        email = u.get("email", "")
        if not name:
            continue
        escaped_name = re.escape(html.escape(name))
        escaped_email = re.escape(html.escape(email))
        pattern = rf"@({escaped_name}|{escaped_email})\b"
        replacement = r'<span class="mention-tag" style="background-color: rgba(124, 58, 237, 0.15); color: var(--accent-purple); font-weight: 600; padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(124, 58, 237, 0.25);">@\1</span>'
        escaped_content = re.sub(pattern, replacement, escaped_content, flags=re.IGNORECASE)
    return Markup(escaped_content)

def process_comment_mentions(owner_uid, content, entity_id, entity_name, entity_type, entity_url_path, sandbox):
    taggable_users = []
    owner_prof = DatabaseService.get_user_profile(owner_uid)
    if owner_prof:
        taggable_users.append({
            "uid": owner_uid,
            "name": owner_prof.get("name", "Propietario"),
            "email": owner_prof.get("email", ""),
            "role": "owner"
        })
    team = DatabaseService.get_team_members(owner_uid) or []
    for member in team:
        taggable_users.append({
            "uid": member.get("uid"),
            "name": member.get("name", ""),
            "email": member.get("email", ""),
            "role": member.get("role", "collaborator")
        })
        
    for u in taggable_users:
        name = u.get("name", "")
        email = u.get("email", "")
        uid = u.get("uid")
        if not uid or not email:
            continue
            
        if 'user' in session and session['user'].get('uid') == uid:
            continue
            
        escaped_name = re.escape(name)
        escaped_email = re.escape(email)
        pattern = rf"@({escaped_name}|{escaped_email})\b"
        if re.search(pattern, content, re.IGNORECASE):
            notif_id = str(uuid.uuid4())
            
            # Map entity types to display names
            entity_type_display = {
                "invoice": "del documento",
                "expense": "del gasto",
                "contract": "del contrato",
                "shift": "del turno de caja"
            }.get(entity_type, "del documento")

            notif_dict = {
                "id": notif_id,
                "title": "Nueva mención en un comentario",
                "message": f"{session['user'].get('name', session['user']['email'])} te mencionó en un comentario {entity_type_display} {entity_name}.",
                "documentId": entity_id,
                "documentNumber": entity_name,
                "link": f"{entity_url_path}",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "read": False,
                "type": "mention"
            }
            DatabaseService.create_user_notification(uid, notif_dict)
            
            from flask import request
            try:
                base_url = request.host_url.rstrip('/')
            except Exception:
                base_url = os.environ.get("PORTAL_BASE_URL", "http://localhost:5001").rstrip('/')
            doc_url = f"{base_url}{entity_url_path}"
            
            from app.services.notifications import NotificationService
            
            # Obtener el nombre comercial de la empresa
            company = DatabaseService.get_company(owner_uid) or {}
            issuer_company_name = company.get("tradeName") or company.get("companyName") or get_product_name()
            
            NotificationService.send_mention_notification(
                recipient_email=email,
                recipient_name=name,
                commenter_name=session['user'].get('name', session['user']['email']),
                comment_snippet=content[:150] + ("..." if len(content) > 150 else ""),
                doc_number=entity_name,
                doc_url=doc_url,
                issuer_company_name=issuer_company_name,
                sandbox=sandbox
            )

@web_invoices_bp.route('/notifications/mark-read', methods=['POST'])
def mark_notifications_read():
    if 'user' not in session:
        return jsonify({"success": False, "message": "No autenticado"}), 401
    user_uid = session['user']['uid']
    success = DatabaseService.mark_user_notifications_read(user_uid)
    return jsonify({"success": success})

@web_invoices_bp.route('/invoices/<invoice_id>')
def invoice_detail(invoice_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))

    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Detalle de Factura", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Factura no encontrada.', 'error')
        return redirect(url_for('web_invoices.list_invoices'))
    
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
    
    hoy = datetime.now(timezone.utc)
    
    for inst in invoice.get("installments", []):
        inst_rem = float(inst.get("remainingBalance", 0.0))
        inst_due_str = inst.get("dueDate", "")
        
        dias_retraso = 0
        mora_cuota = 0.0
        
        if inst.get("status") == "Pendiente" and inst_due_str:
            try:
                due_date_dt = datetime.strptime(inst_due_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
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
    
    comments = DatabaseService.get_invoice_comments(owner_uid, invoice_id, sandbox=sandbox)
    
    # Obtener el historial de auditoría
    try:
        from app.services.audit_service import AuditService
        history_logs = AuditService.get_entity_logs(owner_uid, invoice_id)
    except Exception as e:
        print(f"⚠️ Error al obtener logs de auditoría: {e}")
        history_logs = []
        
    # Load taggable users
    taggable_users = []
    owner_prof = DatabaseService.get_user_profile(owner_uid)
    if owner_prof:
        taggable_users.append({
            "uid": owner_uid,
            "name": owner_prof.get("name", "Propietario"),
            "email": owner_prof.get("email", ""),
            "role": "owner"
        })
    team = DatabaseService.get_team_members(owner_uid) or []
    for member in team:
        taggable_users.append({
            "uid": member.get("uid"),
            "name": member.get("name", ""),
            "email": member.get("email", ""),
            "role": member.get("role", "collaborator")
        })
        
    bank_accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox)

    return render_template('invoices/detail.html', active_page='quotations' if invoice.get('isQuotation') else 'invoices', invoice=invoice, company=company, branch=branch, payments=payments, client_email=_get_client_email(owner_uid, invoice, sandbox), comments=comments, taggable_users=taggable_users, format_mentions=format_mentions, history_logs=history_logs, bank_accounts=bank_accounts)

@web_invoices_bp.route('/invoices/<invoice_id>/comments/new', methods=['POST'])
def add_invoice_comment(invoice_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    content = request.form.get('content', '').strip()
    if not content:
        flash('El comentario no puede estar vacío.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
        
    attachment_url = ""
    attachment_name = ""
    
    file = request.files.get('attachment')
    if file and file.filename:
        try:
            file_data = file.read()
            mime_type = file.mimetype or "application/octet-stream"
            filename = f"comment_{invoice_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
            destination_path = f"users/{owner_uid}/comments/{filename}"
            
            attachment_url = DatabaseService.upload_file_to_storage(
                file_data=file_data,
                destination_path=destination_path,
                mime_type=mime_type
            )
            attachment_name = file.filename
        except Exception as e:
            flash(f"Advertencia: No se pudo cargar el archivo adjunto: {html.escape(str(e))}", 'warning')
            
    comment_id = str(uuid.uuid4())
    comment_dict = {
        "content": content,
        "createdBy": session['user']['email'],
        "createdByName": session['user'].get('name', session['user']['email']),
        "createdByUid": session['user']['uid'],
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "attachmentUrl": attachment_url,
        "attachmentName": attachment_name,
        "edited": False
    }
    
    DatabaseService.save_invoice_comment(owner_uid, invoice_id, comment_id, comment_dict, sandbox=sandbox)
    
    # Process mentions
    try:
        invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox) or {}
        invoice_number = invoice.get('invoiceNumber', invoice_id)
        entity_url = f"/invoices/{invoice_id}?sandbox={'true' if sandbox else 'false'}"
        process_comment_mentions(owner_uid, content, invoice_id, invoice_number, "invoice", entity_url, sandbox)
    except Exception as ex:
        print(f"⚠️ Error al procesar menciones en add_invoice_comment: {ex}")
        
    flash('Comentario agregado exitosamente.', 'success')
    return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

@web_invoices_bp.route('/invoices/<invoice_id>/comments/<comment_id>/edit', methods=['POST'])
def edit_invoice_comment(invoice_id, comment_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    comments = DatabaseService.get_invoice_comments(owner_uid, invoice_id, sandbox=sandbox)
    comment = next((c for c in comments if c['id'] == comment_id), None)
    if not comment:
        flash('Comentario no encontrado.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
        
    # Validar permisos
    is_owner = session['user'].get('role') == 'owner'
    is_author = session['user']['uid'] == comment.get('createdByUid')
    if not (is_owner or is_author):
        flash('No tienes permiso para editar este comentario.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
        
    content = request.form.get('content', '').strip()
    if not content:
        flash('El comentario no puede estar vacío.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
        
    comment['content'] = content
    comment['edited'] = True
    comment['editedAt'] = datetime.now(timezone.utc).isoformat()
    
    file = request.files.get('attachment')
    if file and file.filename:
        try:
            file_data = file.read()
            mime_type = file.mimetype or "application/octet-stream"
            filename = f"comment_{invoice_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
            destination_path = f"users/{owner_uid}/comments/{filename}"
            
            attachment_url = DatabaseService.upload_file_to_storage(
                file_data=file_data,
                destination_path=destination_path,
                mime_type=mime_type
            )
            comment['attachmentUrl'] = attachment_url
            comment['attachmentName'] = file.filename
        except Exception as e:
            flash(f"Advertencia: No se pudo cargar el archivo adjunto: {html.escape(str(e))}", 'warning')
            
    DatabaseService.save_invoice_comment(owner_uid, invoice_id, comment_id, comment, sandbox=sandbox)
    
    # Process mentions
    try:
        invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox) or {}
        invoice_number = invoice.get('invoiceNumber', invoice_id)
        entity_url = f"/invoices/{invoice_id}?sandbox={'true' if sandbox else 'false'}"
        process_comment_mentions(owner_uid, content, invoice_id, invoice_number, "invoice", entity_url, sandbox)
    except Exception as ex:
        print(f"⚠️ Error al procesar menciones en edit_invoice_comment: {ex}")
        
    flash('Comentario editado exitosamente.', 'success')
    return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))


@web_invoices_bp.route('/invoices/<invoice_id>/comments/<comment_id>/delete', methods=['POST'])
def delete_invoice_comment(invoice_id, comment_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    comments = DatabaseService.get_invoice_comments(owner_uid, invoice_id, sandbox=sandbox)
    comment = next((c for c in comments if c['id'] == comment_id), None)
    if not comment:
        flash('Comentario no encontrado.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
        
    # Validar permisos
    is_owner = session['user'].get('role') == 'owner'
    is_author = session['user']['uid'] == comment.get('createdByUid')
    if not (is_owner or is_author):
        flash('No tienes permiso para eliminar este comentario.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
        
    DatabaseService.delete_invoice_comment(owner_uid, invoice_id, comment_id, sandbox=sandbox)
    flash('Comentario eliminado exitosamente.', 'success')
    return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

@web_invoices_bp.route('/invoices/comments/ai-polish', methods=['POST'])
def ai_polish_comment():
    if 'user' not in session:
        return jsonify({"success": False, "message": "No autenticado"}), 401
    owner_uid = session['user']['ownerUID']
    data = request.get_json() or {}
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"success": False, "message": "Contenido vacío"}), 400
        
    from app.services.ai_service import AIService
    res = AIService.polish_comment(owner_uid, content)
    if res.get("success"):
        return jsonify({"success": True, "text": res["text"]})
    else:
        return jsonify({"success": False, "message": res.get("message", "Error al procesar con IA")})



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

    if not app.config.get("SMTP_USER") or not app.config.get("SMTP_PASSWORD"):
        return jsonify({"success": False, "message": "El servidor de correo no está configurado. Configura SMTP_USER y SMTP_PASSWORD en el servidor."}), 503

    company_name    = company.get("tradeName") or company.get("companyName", get_product_name())
    company_rnc     = company.get("companyRNC", "")
    company_address = company.get("companyAddress", "")
    company_phone   = company.get("companyPhone", "")
    company_email   = company.get("companyEmail", app.config.get("SMTP_USER", ""))

    company_name    = company.get("tradeName") or company.get("companyName", get_product_name())
    brand_color     = company.get("colorMarca", "#10b981")

    html_body = f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f8fafc; color: #1e293b; margin: 0; padding: 0; }}
    .wrapper {{ max-width: 600px; margin: 30px auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.08); }}
    .header {{ background: {brand_color}; padding: 32px 36px; text-align: center; }}
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
        Emitido el: {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC
      </div>
    </div>
  </div>
</body>
</html>
"""

    subject = f"Recibo de Pago - Factura {invoice.get('invoiceNumber', '')} | {company_name}"

    success = Mailer.send(
        app=app._get_current_object(),
        to_email=recipient_email,
        subject=subject,
        html_body=html_body,
        from_name=company_name,
        category='receipt'
    )

    if success:
        return jsonify({"success": True, "message": f"Recibo enviado exitosamente a {recipient_email}"})
    else:
        return jsonify({"success": False, "message": "Error al enviar el correo."}), 500

def send_invoice_email(owner_uid, invoice, recipient_email, sandbox=True, base_url=None):
    """Función auxiliar para enviar factura electrónica por correo usando SMTP y Weasyprint."""
    try:
        company = DatabaseService.get_company_profile(owner_uid)

        from flask import current_app as app
        if not app.config.get("SMTP_USER") or not app.config.get("SMTP_PASSWORD"):
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
            
        # 4. Construir y enviar correo
        encf = invoice.get('encf', 'N/A')
        company_name = company.get("tradeName") or company.get("companyName", "EMISOR")
        brand_color  = company.get("colorMarca", "#1a365d")
        ecf_type = invoice.get('ecfType', 'Factura de Consumo Electrónica')
        date_str = invoice.get('date', '')[:10]
        total_str = f"$ {invoice.get('total', 0.0):.2f} {invoice.get('currency', 'DOP')}"
        client_name = invoice.get('clientName') or invoice.get('razonSocial', 'Consumidor Final')

        logo_url = company.get('logoUrl', '')

        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #f4f7f6; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 30px auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }}
                .header {{ background-color: {brand_color}; color: #ffffff; padding: 30px 40px; text-align: center; }}
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

        subject = f"{ecf_type} No. [{encf}] - [{company_name}]"

        attachments = []
        attachments.append({
            'filename': f"{encf}.xml",
            'data': xml_content.encode('utf-8'),
            'mimetype': 'xml'
        })
        if pdf_bytes:
            attachments.append({
                'filename': f"{encf}.pdf",
                'data': pdf_bytes,
                'mimetype': 'pdf'
            })

        success = Mailer.send(
            app=app._get_current_object(),
            to_email=recipient_email,
            subject=subject,
            html_body=html_body,
            from_name=company_name,
            category='invoice',
            attachments=attachments
        )

        if not success:
            return False, "Error al enviar el correo."

        return True, f"Factura enviada exitosamente por correo a {recipient_email}."
    except Exception as e:
        import logging
        logging.exception("Error enviando factura por email")
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
    if 'user' not in session: return redirect(url_for('web_auth.login'))

    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Registrar Pago", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Factura no encontrada.', 'error')
        return redirect(url_for('web_invoices.list_invoices'))
        
    before_invoice = invoice.copy()
    try:
        amount = float(request.form.get('amount', invoice.get('remainingBalance', 0.0)))
    except ValueError:
        amount = 0.0
        
    remaining_balance = float(invoice.get('remainingBalance', invoice.get('netPayable', 0.0) if invoice.get('status') == 'Cobrada' else 0.0))
    
    if amount <= 0.0:
        flash('El monto a abonar debe ser mayor a cero.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
        
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

    bank_account_id = request.form.get('bankAccountId', '')

    payment_dict = {
        "paymentMethod": payment_method,
        "bank": bank,
        "referenceNumber": reference_number,
        "paymentDate": datetime.now(timezone.utc).isoformat(),
        "registeredBy": session['user']['email'],
        "bankAccountId": bank_account_id
    }

    if mora_action == 'cobrar' and mora_amount > 0:
        capital_amount = max(0.0, amount - mora_amount)
        if capital_amount > remaining_balance + 0.01:
            flash(f'El monto de capital del abono (RD$ {capital_amount:,.2f}) no puede superar el balance pendiente (RD$ {remaining_balance:,.2f}).', 'error')
            return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
            
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
            
            # Registrar evento de auditoría
            try:
                updated_invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
                from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_FACTURAS
                AuditService.log_from_request(
                    owner_uid=owner_uid,
                    action="PAYMENT",
                    module=MODULE_FACTURAS,
                    entity_id=invoice_id,
                    entity_label=f"Cobro registrado: RD$ {capital_amount:,.2f} (Capital) + RD$ {mora_amount:,.2f} (Mora) - {payment_method}",
                    user_session=session.get('user', {}),
                    before=before_invoice,
                    after=updated_invoice,
                    sandbox=sandbox
                )
            except Exception as ae:
                print(f"⚠️ Error al registrar auditoría de cobro manual con mora: {ae}")
        except Exception as e:
            flash(f'Error al registrar el cobro: {str(e)}', 'error')
    else:
        if amount > remaining_balance + 0.01:
            flash(f'El monto del abono (RD$ {amount:,.2f}) no puede superar el balance pendiente (RD$ {remaining_balance:,.2f}).', 'error')
            return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
            
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
                
            # Registrar evento de auditoría
            try:
                updated_invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
                from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_FACTURAS
                AuditService.log_from_request(
                    owner_uid=owner_uid,
                    action="PAYMENT",
                    module=MODULE_FACTURAS,
                    entity_id=invoice_id,
                    entity_label=f"Cobro registrado: RD$ {amount:,.2f} - {payment_method}",
                    user_session=session.get('user', {}),
                    before=before_invoice,
                    after=updated_invoice,
                    sandbox=sandbox
                )
            except Exception as ae:
                print(f"⚠️ Error al registrar auditoría de cobro manual: {ae}")
        except Exception as e:
            flash(f'Error al registrar el cobro: {str(e)}', 'error')
            
    return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

@web_invoices_bp.route('/invoices/<invoice_id>/pay/advanced', methods=['GET', 'POST'])
def pay_advanced_route(invoice_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Registrar Pago", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Factura no encontrada.', 'error')
        return redirect(url_for('web_invoices.list_invoices'))
        
    company = DatabaseService.get_company_profile(owner_uid) or {}
    bank_accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox)
    cost_centers = DatabaseService.get_cost_centers(owner_uid, sandbox=sandbox)
    payments = DatabaseService.get_invoice_payments(owner_uid, invoice_id, sandbox=sandbox) or []
    
    receipt_no = len(payments) + 1
    
    if request.method == 'POST':
        bank_account_id = request.form.get('bankAccountId', '')
        payment_date = request.form.get('paymentDate') or datetime.now(timezone.utc).isoformat()
        payment_method = request.form.get('paymentMethod', 'Transferencia')
        cost_center_id = request.form.get('costCenterId', '')
        income_type = request.form.get('incomeType', 'Pago a factura de cliente')
        notes = request.form.get('notes', '')
        
        try:
            monto_recibido = float(request.form.get('monto_recibido', invoice.get('remainingBalance', 0.0)))
            retenciones = float(request.form.get('retenciones', 0.0))
        except ValueError:
            monto_recibido = 0.0
            retenciones = 0.0
            
        remaining_balance = float(invoice.get('remainingBalance', invoice.get('netPayable', 0.0)))
        
        if monto_recibido <= 0:
            flash('El monto recibido debe ser mayor a cero.', 'error')
            return redirect(url_for('web_invoices.pay_advanced_route', invoice_id=invoice_id))
            
        account = next((acc for acc in bank_accounts if acc['id'] == bank_account_id), None)
        bank_name = account['name'] if account else 'Banco General'
        
        payment_dict = {
            "paymentMethod": payment_method,
            "bank": bank_name,
            "referenceNumber": f"Recibo de Caja No. {receipt_no}",
            "paymentDate": payment_date,
            "registeredBy": session['user']['email'],
            "bankAccountId": bank_account_id,
            "amount": monto_recibido,
            "moraAction": "perdonado",
            "moraForgiven": 0.0,
            "costCenterId": cost_center_id,
            "incomeType": income_type,
            "retenciones": retenciones,
            "notes": notes
        }
        
        before_invoice = invoice.copy()
        
        try:
            DatabaseService.register_invoice_payment(owner_uid, invoice_id, payment_dict, sandbox=sandbox)
            
            try:
                updated_invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
                from app.services.audit_service import AuditService, MODULE_FACTURAS
                AuditService.log_from_request(
                    owner_uid=owner_uid,
                    action="PAYMENT",
                    module=MODULE_FACTURAS,
                    entity_id=invoice_id,
                    entity_label=f"Cobro avanzado registrado: RD$ {monto_recibido:,.2f} - Recibo No. {receipt_no}",
                    user_session=session.get('user', {}),
                    before=before_invoice,
                    after=updated_invoice,
                    sandbox=sandbox
                )
            except Exception as ae:
                print(f"⚠️ Error al registrar auditoría de cobro avanzado: {ae}")
                
            flash(f"✅ ¡Pago de RD$ {monto_recibido:,.2f} recibido con éxito! Recibo de caja No. {receipt_no} guardado.", "success")
        except Exception as e:
            flash(f"❌ Error al registrar el pago: {str(e)}", "error")
            
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
        
    default_date = datetime.now(timezone(timedelta(hours=-4))).strftime("%Y-%m-%d")
    
    return render_template(
        'invoices/pay_advanced.html',
        active_page='invoices',
        invoice=invoice,
        company=company,
        bank_accounts=bank_accounts,
        cost_centers=cost_centers,
        receipt_no=receipt_no,
        default_date=default_date
    )


@web_invoices_bp.route('/invoices/<invoice_id>/approve_payment_proof', methods=['POST'])
def approve_payment_proof(invoice_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Aprobar Pago", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Factura no encontrada.', 'error')
        return redirect(url_for('web_invoices.list_invoices'))
        
    before_invoice = invoice.copy()
    try:
        amount = float(request.form.get('amount', 0.0))
    except ValueError:
        amount = 0.0
        
    if amount <= 0.0:
        flash('El monto del cobro debe ser mayor a cero.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
        
    payment_method = request.form.get('paymentMethod', 'Transferencia Bancaria')
    bank = request.form.get('bank', 'Banco Popular Dominicano')
    reference_number = request.form.get('referenceNumber', 'Abono Registrado')
    payment_date = request.form.get('paymentDate') or datetime.now(timezone.utc).isoformat()
    bank_account_id = request.form.get('bankAccountId', '')
    
    payment_dict = {
        "amount": amount,
        "paymentMethod": payment_method,
        "bank": bank,
        "referenceNumber": reference_number,
        "paymentDate": payment_date,
        "registeredBy": session['user']['email'],
        "bankAccountId": bank_account_id
    }
    
    try:
        # Registrar el pago oficial y recalcular balances
        DatabaseService.register_invoice_payment(owner_uid, invoice_id, payment_dict, sandbox=sandbox)
        
        # Eliminar el comprobante pendiente
        coll_inv = "sandbox_invoices" if sandbox else "invoices"
        from firebase_admin import firestore
        from app.services.db_service import db_firestore
        db_firestore.collection("users").document(owner_uid).collection(coll_inv).document(invoice_id).update({
            "pendingPaymentProof": firestore.DELETE_FIELD
        })
        
        # Registrar evento de auditoría
        try:
            updated_invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
            from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_FACTURAS
            AuditService.log_from_request(
                owner_uid=owner_uid,
                action="APPROVE_PAYMENT",
                module=MODULE_FACTURAS,
                entity_id=invoice_id,
                entity_label=f"Comprobante de pago aprobado: RD$ {amount:,.2f} ({payment_method} - {bank})",
                user_session=session.get('user', {}),
                before=before_invoice,
                after=updated_invoice,
                sandbox=sandbox
            )
        except Exception as ae:
            print(f"⚠️ Error al registrar auditoría de aprobación de pago: {ae}")
        
        # Notificar al cliente por email e in-app
        try:
            client_id = invoice.get('clientId')
            client_email = invoice.get('clientEmail', '')
            client_name = invoice.get('clientName', 'Cliente')

            if client_email:
                from app.services.notifications import NotificationService
                NotificationService.send_client_payment_notification(
                    owner_uid=owner_uid,
                    action='aprobado',
                    invoice=invoice,
                    client_email=client_email,
                    client_name=client_name,
                    sandbox=sandbox
                )

            # Notificación in-app (guardada bajo el owner para que aparezca en el sistema)
            if client_id:
                import uuid as _uuid2
                from app.services.db_service import DatabaseService as _DS
                _DS.create_user_notification(owner_uid, {
                    "id": str(_uuid2.uuid4()),
                    "type": "pago_aprobado",
                    "icon": "✅",
                    "title": f"Pago aprobado — {invoice.get('invoiceNumber', invoice_id)}",
                    "body": f"El pago de {client_name} fue aprobado y registrado exitosamente.",
                    "clientName": client_name,
                    "documentNumber": invoice.get('invoiceNumber', invoice_id),
                    "documentUrl": f"/invoices/{invoice_id}",
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "read": False
                })
        except Exception as _ne:
            print(f"⚠️ Error al notificar al cliente sobre aprobación de pago: {_ne}")

        flash('El comprobante de pago ha sido aprobado y el pago ha sido registrado exitosamente.', 'success')

    except Exception as e:
        flash(f'Error al aprobar el pago: {str(e)}', 'error')
        
    return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

@web_invoices_bp.route('/invoices/<invoice_id>/reject_payment_proof', methods=['POST'])
def reject_payment_proof(invoice_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Rechazar Pago", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Factura no encontrada.', 'error')
        return redirect(url_for('web_invoices.list_invoices'))
        
    before_invoice = invoice.copy()
    rejection_reason = request.form.get('rejectionReason', '').strip()
    
    try:
        coll_inv = "sandbox_invoices" if sandbox else "invoices"
        from firebase_admin import firestore
        from app.services.db_service import db_firestore
        
        # Devolver el estado a "Emitida" (o su estado previo) y eliminar pendingPaymentProof
        total_paid = float(invoice.get('totalPaid', 0.0))
        new_status = "Parcialmente Cobrada" if total_paid > 0.01 else "Emitida"
        
        db_firestore.collection("users").document(owner_uid).collection(coll_inv).document(invoice_id).update({
            "status": new_status,
            "pendingPaymentProof": firestore.DELETE_FIELD
        })
        
        # Registrar evento de auditoría
        try:
            updated_invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
            from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_FACTURAS
            AuditService.log_from_request(
                owner_uid=owner_uid,
                action="REJECT_PAYMENT",
                module=MODULE_FACTURAS,
                entity_id=invoice_id,
                entity_label=f"Comprobante de pago rechazado. Motivo: {rejection_reason or 'Sin especificar'}",
                user_session=session.get('user', {}),
                before=before_invoice,
                after=updated_invoice,
                sandbox=sandbox
            )
        except Exception as ae:
            print(f"⚠️ Error al registrar auditoría de rechazo de pago: {ae}")
        
        # Si se especificó un motivo de rechazo, registrarlo como comentario interno
        if rejection_reason:
            comment_id = str(uuid.uuid4())
            comment_dict = {
                "content": f"❌ [PAGO RECHAZADO] Se rechazó el comprobante de pago reportado. Motivo: {rejection_reason}",
                "createdBy": session['user']['email'],
                "createdByName": session['user'].get('name', session['user']['email']),
                "createdByUid": session['user']['uid'],
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "attachmentUrl": "",
                "attachmentName": "",
                "edited": False
            }
            DatabaseService.save_invoice_comment(owner_uid, invoice_id, comment_id, comment_dict, sandbox=sandbox)
            
        # Notificar al cliente por email e in-app
        try:
            client_email = invoice.get('clientEmail', '')
            client_name = invoice.get('clientName', 'Cliente')
            client_id = invoice.get('clientId')

            if client_email:
                from app.services.notifications import NotificationService
                NotificationService.send_client_payment_notification(
                    owner_uid=owner_uid,
                    action='rechazado',
                    invoice=invoice,
                    client_email=client_email,
                    client_name=client_name,
                    sandbox=sandbox,
                    rejection_reason=rejection_reason
                )

            if client_id:
                import uuid as _uuid3
                from app.services.db_service import DatabaseService as _DS2
                _DS2.create_user_notification(owner_uid, {
                    "id": str(_uuid3.uuid4()),
                    "type": "pago_rechazado",
                    "icon": "❌",
                    "title": f"Pago rechazado — {invoice.get('invoiceNumber', invoice_id)}",
                    "body": f"Se rechazó el comprobante de {client_name}. Motivo: {rejection_reason}" if rejection_reason else f"Se rechazó el comprobante de {client_name}.",
                    "clientName": client_name,
                    "documentNumber": invoice.get('invoiceNumber', invoice_id),
                    "documentUrl": f"/invoices/{invoice_id}",
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "read": False
                })
        except Exception as _ne2:
            print(f"⚠️ Error al notificar al cliente sobre rechazo de pago: {_ne2}")

        flash('El comprobante de pago ha sido rechazado y el estado de la factura ha sido restablecido.', 'warning')

    except Exception as e:
        flash(f'Error al rechazar el pago: {str(e)}', 'error')
        
    return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

@web_invoices_bp.route('/invoices/<invoice_id>/sign', methods=['POST'])
def sign_invoice_route(invoice_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Firmar Comprobante", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Factura no encontrada.', 'error')
        return redirect(url_for('web_invoices.list_invoices'))
        
    exceeded, limit_msg = check_document_limit_exceeded(owner_uid, sandbox=sandbox)
    if exceeded:
        flash(limit_msg, 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
    elif limit_msg:
        flash(limit_msg, 'warning')
        
    company = DatabaseService.get_company_profile(owner_uid)
    
    try:
        # Consumir el siguiente consecutivo del rango fiscal DGII si no se ha asignado
        if not invoice.get("encf"):
            ecf_short = get_ecf_type_short_code(invoice["ecfType"])
            user_email = session['user']['email']
            
            # Bloquear secuencia y generar consecutivo
            encf, log_id = DatabaseService.consume_next_sequence(owner_uid, ecf_short, user_email, sandbox=sandbox)
            invoice["encf"] = encf
            
        # Emitir a través de DGII Direct (con Fallback de contingencia)
        res = EcfEmissionService.emit_electronic_comprobante(company, invoice, sandbox=sandbox)
        
        if res.get("success"):
            pending_dgii = res.get("status") == "PENDING" or res.get("mode") == "FALLBACK"
            rem_bal = float(invoice.get("remainingBalance", 0.0))
            tot_paid = float(invoice.get("totalPaid", 0.0))
            if rem_bal <= 0.01 and tot_paid > 0.0:
                invoice["status"] = "Cobrada"
            elif tot_paid > 0.0:
                invoice["status"] = "Parcialmente Cobrada"
            else:
                invoice["status"] = "Pendiente DGII" if pending_dgii else "Emitida"
            invoice["encf"] = res.get("encf", invoice.get("encf", ""))
            invoice["xmlSignature"] = res.get("xmlSignature", "")
            invoice["qrCodeURL"] = res.get("qrCodeURL", "")
            invoice["firebasePDFURL"] = res.get("pdfUrl", "")
            invoice["firebaseXMLURL"] = res.get("xmlUrl", "")
            # FALLBACK = emitido offline, aún pendiente de sincronizar con la DGII
            invoice["isSyncedWithDGII"] = (res.get("mode", "API") == "API" and res.get("status") != "PENDING")
            invoice["emisionMode"] = res.get("mode", "API")
            invoice["dgiiStatus"] = res.get("dgiiStatus") or ("PENDING" if pending_dgii else "ACCEPTED")
            invoice["contingencyEmittedAt"] = datetime.now(timezone.utc).isoformat() if res.get("mode") == "FALLBACK" else None
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
                msg = f"⚠️ ¡Comprobante firmado en modalidad de contingencia (sin conexión a DGII)! e-NCF: {res.get('encf')}. Recuerde sincronizarlo con la DGII en un plazo máximo de 72 horas."
            flash(msg, "success")
        else:
            flash(f"Error al certificar comprobante: {res.get('message')}", "error")
            
    except Exception as e:
        flash(f"Fallo en la emisión de comprobante: {str(e)}", "error")
        
    return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

@web_invoices_bp.route('/invoices/<invoice_id>/convert', methods=['POST'])
def convert_quotation_route(invoice_id):
    """Convierte una Cotización (COT-) en un Comprobante Fiscal Electrónico real (FAC-)."""
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Convertir Cotización", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Cotización no encontrada.', 'error')
        return redirect(url_for('web_invoices.list_quotations'))

    if not invoice.get('isQuotation'):
        flash('Este documento ya es una factura real. No necesita conversión.', 'info')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

    if invoice.get('convertedToInvoiceId'):
        flash(f'Esta cotización ya fue convertida a la factura {invoice.get("convertedInvoiceNumber", "")}. No se puede convertir nuevamente.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

    target_ecf_type = request.form.get('targetEcfType', 'Factura de Consumo (E32)')

    # Validaciones fiscales DGII
    client_rnc = invoice.get('clientRNC', '').strip()
    total = invoice.get('total', 0.0)

    if target_ecf_type == 'Factura de Crédito Fiscal (E31)' and not client_rnc:
        flash('Las facturas de Crédito Fiscal (E31) siempre requieren el RNC/Cédula del cliente. Edita la cotización y agrega un cliente antes de convertir.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

    if target_ecf_type == 'Factura de Consumo (E32)' and total >= 250000 and not client_rnc:
        flash(f'Por Ley 32-23 de la DGII, las facturas de consumo que superen RD$ 250,000 deben identificar al comprador. El total de esta cotización es RD$ {total:,.2f}. Agrega un cliente con RNC antes de convertir.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

    # Realizar la conversión
    import uuid
    new_invoice_id = str(uuid.uuid4())

    # 1. Crear la nueva factura fiscal (FAC-) a partir de los datos de la cotización
    new_invoice = invoice.copy()
    new_invoice['id'] = new_invoice_id
    random_num = f"{random.randint(1, 999999):06d}"
    new_invoice['invoiceNumber'] = f"FAC-{random_num}"
    new_invoice['ecfType'] = target_ecf_type
    new_invoice['isQuotation'] = False
    new_invoice['isConvertedToInvoice'] = True
    new_invoice['status'] = 'Borrador'  # Queda como borrador hasta firmarse
    
    # 2. Auto-crear productos en el catálogo si la partida no existe o no tiene catalogId
    for idx, inv_item in enumerate(new_invoice.get('items', [])):
        catalog_id = inv_item.get('catalogId', '')
        if not catalog_id:
            new_item_id = str(uuid.uuid4())
            new_item = {
                "code": inv_item.get('code', ''),
                "name": inv_item.get('name', 'Partida sin nombre'),
                "price": float(inv_item.get('price', 0)),
                "itbisRate": float(inv_item.get('itbisRate', 0.18)),
                "type": "Servicio",
                "unit": "Unidad",
                "isActive": True
            }
            DatabaseService.save_item(owner_uid, new_item_id, new_item, sandbox=sandbox)
            new_invoice['items'][idx]['catalogId'] = new_item_id
        # If catalogId exists, the item already exists in the catalog — leave as is

    # 3. Mantener la cotización original (isQuotation=True) pero actualizar su estado a 'Facturada'
    before_invoice = invoice.copy()
    invoice['status'] = 'Facturada'
    invoice['convertedToInvoiceId'] = new_invoice_id
    invoice['convertedInvoiceNumber'] = new_invoice['invoiceNumber']

    # Guardar ambos documentos en la base de datos
    DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
    DatabaseService.save_invoice(owner_uid, new_invoice_id, new_invoice, sandbox=sandbox)

    # Registrar evento de auditoría en la cotización
    try:
        from app.services.audit_service import AuditService, MODULE_COTIZACIONES
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action="CONVERT_DOCUMENT",
            module=MODULE_COTIZACIONES,
            entity_id=invoice_id,
            entity_label=f"Cotización {invoice['invoiceNumber']} convertida a {target_ecf_type} ({new_invoice['invoiceNumber']})",
            user_session=session.get('user', {}),
            before=before_invoice,
            after=invoice,
            sandbox=sandbox
        )
    except Exception as ae:
        print(f"⚠️ Error al registrar auditoría de conversión de cotización: {ae}")

    # Registrar evento de auditoría en la nueva factura
    try:
        from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_FACTURAS
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_CREATE,
            module=MODULE_FACTURAS,
            entity_id=new_invoice_id,
            entity_label=f"Factura {new_invoice['invoiceNumber']} creada a partir de cotización {invoice['invoiceNumber']}",
            user_session=session.get('user', {}),
            before=None,
            after=new_invoice,
            sandbox=sandbox
        )
    except Exception as ae:
        print(f"⚠️ Error al registrar auditoría de creación de factura convertida: {ae}")

    flash(f'¡Cotización convertida exitosamente a {target_ecf_type}! El número de documento es {new_invoice["invoiceNumber"]}. Procede a firmar digitalmente el comprobante.', 'success')
    return redirect(url_for('web_invoices.invoice_detail', invoice_id=new_invoice_id))


@web_invoices_bp.route('/quotations/<invoice_id>/approve', methods=['POST'])
def approve_quotation_route(invoice_id):
    """Aprueba manualmente una cotización cambiándole el estado a 'Aprobada'."""
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Aprobar Cotización", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice or not invoice.get('isQuotation'):
        flash('Cotización no encontrada.', 'error')
        return redirect(url_for('web_invoices.list_quotations'))
        
    before_invoice = invoice.copy()
    invoice['status'] = 'Aprobada'
    DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
    
    # Registrar evento de auditoría
    try:
        updated_invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
        from app.services.audit_service import AuditService, MODULE_FACTURAS
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action="APPROVE_QUOTATION",
            module=MODULE_FACTURAS,
            entity_id=invoice_id,
            entity_label="Cotización aprobada manualmente por administrador",
            user_session=session.get('user', {}),
            before=before_invoice,
            after=updated_invoice,
            sandbox=sandbox
        )
    except Exception as ae:
        print(f"⚠️ Error al registrar auditoría de aprobación manual de cotización: {ae}")

    flash('Cotización aprobada manualmente con éxito.', 'success')
    return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

@web_invoices_bp.route('/quotations/<invoice_id>/send-to-client', methods=['POST'])
def send_quotation_to_client(invoice_id):
    """Envía cotización al cliente — por portal (con enlace) o por PDF según el plan."""
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Enviar Cotización", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    recipient_email = request.form.get("email", "").strip()
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice or not invoice.get('isQuotation'):
        flash('Cotización no encontrada.', 'error')
        return redirect(url_for('web_invoices.list_quotations'))
        
    if not recipient_email:
        recipient_email = _get_client_email(owner_uid, invoice, sandbox)
        
    if not recipient_email:
        flash('El cliente no tiene un correo registrado. Especifique un correo de destino.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
        
    company = DatabaseService.get_company_profile(owner_uid)
    company_name = company.get("tradeName") or company.get("companyName", get_product_name())
    
    from flask import current_app as app
    if not app.config.get("SMTP_USER") or not app.config.get("SMTP_PASSWORD"):
        flash('El servidor de correo no está configurado (SMTP).', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
    
    from app.utils.module_gate import module_enabled
    portal_enabled = module_enabled('portal_cliente')
    
    if portal_enabled:
        # ── RUTA PORTAL: enviar enlace de aprobación ──
        client = DatabaseService.get_client(owner_uid, invoice['clientId'], sandbox=sandbox)
        if not client or not client.get('accessPin'):
            session['pin_missing_client'] = invoice['clientId']
            return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
        
        portal_link = url_for('portal.client_portal', owner_uid=owner_uid, client_id=invoice['clientId'], sandbox='true' if sandbox else 'false', _external=True)
        brand_color = company.get("colorMarca", "#1e3a8a")
        
        html_body = f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f8fafc; color: #1e293b; margin: 0; padding: 0; }}
    .wrapper {{ max-width: 600px; margin: 30px auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.08); }}
    .header {{ background: {brand_color}; padding: 32px 36px; text-align: center; }}
    .header h1 {{ color: #ffffff; font-size: 1.6rem; margin: 0 0 4px; font-weight: 800; }}
    .header p {{ color: rgba(255,255,255,0.75); font-size: 0.88rem; margin: 0; }}
    .body {{ padding: 32px 36px; }}
    .btn-container {{ text-align: center; margin: 30px 0; }}
    .btn-link {{ display: inline-block; background-color: {brand_color}; color: #ffffff !important; padding: 14px 28px; border-radius: 8px; text-decoration: none; font-weight: 700; font-size: 0.95rem; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
    .footer-note {{ font-size: 0.78rem; color: #94a3b8; text-align: center; border-top: 1px solid #e2e8f0; padding-top: 20px; margin-top: 24px; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      {f'<img src="{company.get("logoUrl")}" alt="Logo" style="max-height: 50px; margin-bottom: 15px;">' if company.get("logoUrl") else ''}
      <h1>Propuesta Comercial</h1>
      <p>{company_name}</p>
    </div>
    <div class="body">
      <p style="font-size:1.05rem; font-weight: 600; color:#0f172a; margin-top:0;">Estimado cliente ({invoice.get('clientName', '')}):</p>
      <p style="font-size:0.92rem; color:#475569; line-height: 1.6;">
        Hemos preparado una propuesta comercial para usted con el número de documento <strong>{invoice.get('invoiceNumber', '')}</strong> por un monto total de <strong>RD$ {invoice.get('total', 0.0):,.2f}</strong>.
      </p>
      <p style="font-size:0.92rem; color:#475569; line-height: 1.6;">
        Puede revisar la propuesta completa y proceder a su firma y aprobación electrónica certificada haciendo clic en el siguiente botón:
      </p>

      <div style="background:#f1f5f9; border-radius:8px; padding:16px 20px; margin:20px 0; text-align:center;">
        <p style="font-size:0.82rem; color:#64748b; margin:0 0 8px;">Sus credenciales de acceso al portal:</p>
        <p style="font-size:1.15rem; font-weight:700; color:#0f172a; margin:0; letter-spacing:0.15em;">
          RNC/Cédula: {client.get('rnc', '')} &nbsp;·&nbsp; Código: {client.get('accessPin', '')}
        </p>
      </div>

      <div class="btn-container">
        <a href="{portal_link}" class="btn-link" target="_blank">Revisar y Firmar Cotización</a>
      </div>

      <p style="font-size:0.85rem; color:#64748b; text-align: center;">
        Si el botón no funciona, copie y pegue el siguiente enlace en su navegador:<br>
        <a href="{portal_link}" style="color: {brand_color}; word-break: break-all;">{portal_link}</a>
      </p>

      <div class="footer-note">
        Para consultas adicionales, comuníquese con nosotros.<br>
        Generado automáticamente por la plataforma {get_product_name()}.
      </div>
    </div>
  </div>
</body>
</html>
"""
        subject = f"Propuesta Comercial - Cotización {invoice.get('invoiceNumber', '')} | {company_name}"
        success = Mailer.send(app=app._get_current_object(), to_email=recipient_email, subject=subject, html_body=html_body, from_name=company_name, category='noreply')

        if not success:
            flash("Error al enviar correo.", "error")
            return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

        before_invoice = invoice.copy()
        invoice['status'] = 'Pendiente Aut. Cliente'
        DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)

        try:
            updated_invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
            from app.services.audit_service import AuditService, MODULE_FACTURAS
            AuditService.log_from_request(owner_uid=owner_uid, action="SEND_EMAIL", module=MODULE_FACTURAS, entity_id=invoice_id, entity_label=f"Cotización enviada al correo {recipient_email} para aprobación", user_session=session.get('user', {}), before=before_invoice, after=updated_invoice, sandbox=sandbox)
        except Exception as ae:
            print(f"⚠️ Error al registrar auditoría de envío de correo: {ae}")

        flash(f"Enlace de aprobación enviado con éxito a {recipient_email}.", "success")
    else:
        # ── RUTA PDF: enviar cotización como PDF adjunto (o HTML inline) ──
        import io
        invoice_enriched = _enrich_invoice_totals(invoice.copy())
        branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
        branch = next((b for b in branches if b['id'] == invoice.get("branchId")), None)
        if not branch and branches:
            branch = branches[0]
        
        rendered_html = render_template('invoices/pdf.html', invoice=invoice_enriched, company=company, branch=branch, auto_print=False, qr_base64=None, fecha_firma_str='', sandbox=sandbox)
        
        pdf_bytes = None
        if WEASYPRINT_AVAILABLE:
            try:
                pdf_bytes = WeasyprintHTML(string=rendered_html, base_url=request.host_url).write_pdf()
            except Exception as e:
                print(f"⚠️ WeasyPrint falló para cotización PDF: {e}")
        
        brand_color = company.get("colorMarca", "#1e3a8a")
        total_str = f"RD$ {invoice.get('total', 0.0):,.2f}"
        
        html_body = f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f8fafc; color: #1e293b; margin: 0; padding: 0; }}
    .wrapper {{ max-width: 600px; margin: 30px auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.08); }}
    .header {{ background: {brand_color}; padding: 32px 36px; text-align: center; }}
    .header h1 {{ color: #ffffff; font-size: 1.6rem; margin: 0 0 4px; font-weight: 800; }}
    .header p {{ color: rgba(255,255,255,0.75); font-size: 0.88rem; margin: 0; }}
    .body {{ padding: 32px 36px; }}
    .footer-note {{ font-size: 0.78rem; color: #94a3b8; text-align: center; border-top: 1px solid #e2e8f0; padding-top: 20px; margin-top: 24px; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      {f'<img src="{company.get("logoUrl")}" alt="Logo" style="max-height: 50px; margin-bottom: 15px;">' if company.get("logoUrl") else ''}
      <h1>Cotización</h1>
      <p>{company_name}</p>
    </div>
    <div class="body">
      <p style="font-size:1.05rem; font-weight: 600; color:#0f172a; margin-top:0;">Estimado cliente ({invoice.get('clientName', '')}):</p>
      <p style="font-size:0.92rem; color:#475569; line-height: 1.6;">
        Hemos preparado una cotización para usted con el número <strong>{invoice.get('invoiceNumber', '')}</strong> por un monto total de <strong>{total_str}</strong>.
      </p>
      <p style="font-size:0.92rem; color:#475569; line-height: 1.6;">
        Adjunto encontrará el detalle completo de la propuesta en formato PDF.
      </p>
      <div class="footer-note">
        Para consultas adicionales, comuníquese con nosotros.<br>
        Generado automáticamente por la plataforma {get_product_name()}.
      </div>
    </div>
  </div>
</body>
</html>
"""
        subject = f"Cotización {invoice.get('invoiceNumber', '')} | {company_name}"
        
        attachments = []
        if pdf_bytes:
            attachments.append({
                'filename': f"cotizacion-{invoice.get('invoiceNumber', '')}.pdf",
                'data': pdf_bytes,
                'mimetype': 'pdf'
            })
        
        success = Mailer.send(app=app._get_current_object(), to_email=recipient_email, subject=subject, html_body=html_body, from_name=company_name, category='noreply', attachments=attachments if attachments else None)
        
        if not success:
            flash("Error al enviar correo.", "error")
            return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
        
        try:
            from app.services.audit_service import AuditService, MODULE_FACTURAS
            AuditService.log_from_request(owner_uid=owner_uid, action="SEND_EMAIL", module=MODULE_FACTURAS, entity_id=invoice_id, entity_label=f"Cotización enviada por PDF al correo {recipient_email}", user_session=session.get('user', {}), before=invoice, after=invoice, sandbox=sandbox)
        except Exception as ae:
            print(f"⚠️ Error al registrar auditoría de envío de cotización PDF: {ae}")
        
        flash(f"Cotización enviada con éxito a {recipient_email}.", "success")
        
    return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))


@web_invoices_bp.route('/invoices/contract-terms/ai-polish', methods=['POST'])
def contract_terms_ai_polish():
    """Mejora términos contractuales o notas comerciales con IA."""
    if 'user' not in session:
        return jsonify({"success": False, "message": "No autenticado"}), 401
    owner_uid = session['user']['ownerUID']
    data = request.get_json() or {}
    content = data.get("content", "").strip()
    context = data.get("context", "")
    content_type = data.get("type", "terms")
    if not content:
        return jsonify({"success": False, "message": "Contenido vacío"}), 400

    from app.services.ai_service import AIService
    res = AIService.polish_contract_terms(owner_uid, content, context, content_type)
    if res.get("success"):
        return jsonify({"success": True, "text": res["text"]})
    else:
        return jsonify({"success": False, "message": res.get("message", "Error al procesar con IA")})


@web_invoices_bp.route('/quotations/<invoice_id>/prepare-contract', methods=['GET'])
def prepare_contract_page(invoice_id):
    """Muestra formulario para preparar un contrato recurrente a partir de una cotización aprobada."""
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageContracts'):
        return render_template('auth/restricted.html',
                               feature_name="Preparar Contrato",
                               required_permission="canManageContracts")

    owner_uid = session['user']['ownerUID']
    sandbox   = session.get('is_sandbox_mode', True)

    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Cotización no encontrada.', 'error')
        return redirect(url_for('web_invoices.list_quotations'))

    if not invoice.get('isQuotation'):
        flash('Este documento no es una cotización.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

    if invoice.get('status') != 'Aprobada':
        flash('Solo se pueden convertir cotizaciones con estado "Aprobada".', 'warning')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

    if invoice.get('isConvertedToContract'):
        flash('Esta cotización ya fue convertida a un contrato recurrente.', 'info')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

    # Extraer datos profesionales para contexto AI
    pd = invoice.get('professionalData', {})
    scope_lines = []
    if pd.get('subject'):
        scope_lines.append(f"Proyecto: {pd['subject']}")
    if pd.get('scopeIncluded'):
        scope_lines.append("Alcance incluye: " + "; ".join(pd['scopeIncluded']))
    if pd.get('scopeExcluded'):
        scope_lines.append("Alcance NO incluye: " + "; ".join(pd['scopeExcluded']))
    scope_text = "\n".join(scope_lines)

    ai_context_lines = []

    total_amount = sum(
        round(float(item.get('quantity', 1)) * float(item.get('price', 0)) *
              (1 + float(item.get('itbisRate', 0.18))), 2)
        for item in invoice.get('items', [])
    )

    ai_context_lines = [
        f"Cliente: {invoice.get('clientName', '')} (RNC: {invoice.get('clientRNC', '')})",
        f"Cotización: {invoice.get('invoiceNumber', '')}",
        f"Monto total: RD$ {total_amount:,.2f}",
    ]
    if scope_text:
        ai_context_lines.append(scope_text)
    ai_context = "\n".join(ai_context_lines)

    # Pre-llenar términos desde professionalData + notes
    default_terms = ""
    if pd.get('termsAndConditions'):
        default_terms += pd['termsAndConditions'] + "\n\n"
    if pd.get('intellectualProperty'):
        default_terms += "Propiedad Intelectual:\n" + pd['intellectualProperty'] + "\n\n"
    if pd.get('confidentiality'):
        default_terms += "Confidencialidad:\n" + pd['confidentiality'] + "\n\n"
    if pd.get('supportTerms'):
        default_terms += "Soporte Post-Entrega:\n" + pd['supportTerms'] + "\n\n"
    if pd.get('warrantyTerms'):
        default_terms += "Garantía:\n" + pd['warrantyTerms']
    if not default_terms.strip():
        default_terms = invoice.get('notes', '')

    default_notes = invoice.get('notes', '')
    if default_notes and default_notes.strip() == default_terms.strip():
        default_notes = ""

    return render_template(
        'contracts/prepare_contract.html',
        active_page='quotations',
        invoice=invoice,
        default_terms=default_terms,
        default_notes=default_notes,
        default_frequency='mensual',
        default_start_date=datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        total_amount=total_amount,
        ai_context=ai_context,
        pd=pd
    )


@web_invoices_bp.route('/quotations/<invoice_id>/prepare-contract', methods=['POST'])
def prepare_contract_submit(invoice_id):
    """Crea el contrato con los términos modificados por el usuario."""
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageContracts'):
        return render_template('auth/restricted.html',
                               feature_name="Preparar Contrato",
                               required_permission="canManageContracts")

    owner_uid = session['user']['ownerUID']
    sandbox   = session.get('is_sandbox_mode', True)

    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice or not invoice.get('isQuotation') or invoice.get('status') != 'Aprobada' or invoice.get('isConvertedToContract'):
        flash('No se puede convertir esta cotización.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

    terms = request.form.get('contract_terms', '').strip()
    notes = request.form.get('contract_notes', '').strip()
    frequency = request.form.get('frequency', 'mensual')
    start_date = request.form.get('start_date', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
    auto_renew = request.form.get('auto_renew') == 'on'
    auto_send_email = request.form.get('auto_send_email') == 'on'

    # ── Mapear ítems de la cotización a contractLines ─────────────────────────
    contract_lines = []
    total_amount   = 0.0

    for item in invoice.get('items', []):
        qty        = float(item.get('quantity', 1))
        unit_price = float(item.get('price', 0))
        itbis_rate = float(item.get('itbisRate', 0.18))
        subtotal   = round(qty * unit_price, 2)
        itbis_amt  = round(subtotal * itbis_rate, 2)
        line_total = round(subtotal + itbis_amt, 2)
        total_amount += line_total
        contract_lines.append({
            'itemId':      item.get('id', ''),
            'name':        item.get('name', 'Servicio'),
            'code':        item.get('code', 'SERV-REC'),
            'type':        item.get('type', 'Servicio'),
            'quantity':    qty,
            'unitPrice':   unit_price,
            'itbisRate':   itbis_rate,
            'subtotal':    subtotal,
            'itbisAmount': itbis_amt,
            'total':       line_total,
        })

    # ── Construir contrato ────────────────────────────────────────────────────
    from app.services.recurrence import RecurrenceService
    import random

    now_iso       = datetime.now(timezone.utc).isoformat()
    random_num    = f"{random.randint(1, 999999):06d}"
    contract_id   = str(uuid.uuid4())
    contract_num  = f"CONT-{random_num}"

    first_billing = RecurrenceService.calculate_next_date(start_date, frequency)

    combined_notes = terms
    if notes:
        combined_notes += "\n\n--- Notas Comerciales ---\n" + notes

    contract_dict = {
        'id':              contract_id,
        'contractNumber':  contract_num,
        'quotationId':     invoice_id,
        'clientId':        invoice.get('clientId', ''),
        'clientName':      invoice.get('clientName', ''),
        'clientRNC':       invoice.get('clientRNC', ''),
        'status':          'Activo',
        'frequency':       frequency,
        'recurrenceInterval': frequency,
        'startDate':       start_date,
        'nextBillingDate': first_billing,
        'endDate':         '',
        'autoRenew':       auto_renew,
        'autoSendEmail':   auto_send_email,
        'contractLines':   contract_lines,
        'amount':          round(total_amount, 2),
        'itemId':          contract_lines[0]['itemId'] if contract_lines else '',
        'notes':           combined_notes,
        'createdAt':       now_iso,
        'updatedAt':       now_iso,
    }

    DatabaseService.save_contract(owner_uid, contract_id, contract_dict, sandbox=sandbox)

    # ── Marcar cotización como convertida ─────────────────────────────────────
    invoice['isConvertedToContract'] = True
    DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)

    flash(
        f'¡Cotización convertida exitosamente al Contrato Recurrente {contract_num}! '
        f'Primera factura programada para {first_billing}.',
        'success'
    )
    return redirect(url_for('web_operations.contract_detail', contract_id=contract_id))


@web_invoices_bp.route('/quotations/<invoice_id>/convert-to-contract', methods=['POST'])
def convert_quotation_to_contract(invoice_id):
    """Redirige al formulario de preparación de contrato."""
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageContracts'):
        return render_template('auth/restricted.html',
                               feature_name="Convertir a Contrato",
                               required_permission="canManageContracts")
    return redirect(url_for('web_invoices.prepare_contract_page', invoice_id=invoice_id))


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

    from app.services.audit_service import AuditService, ACTION_EXPORT, MODULE_FACTURAS, MODULE_COTIZACIONES
    audit_module = MODULE_COTIZACIONES if invoice.get('isQuotation') else MODULE_FACTURAS
    AuditService.log_from_request(
        owner_uid=owner_uid,
        action=ACTION_EXPORT,
        module=audit_module,
        entity_id=invoice_id,
        entity_label=f"PDF Descargado: {invoice.get('invoiceNumber', '')}",
        user_session=session.get('user', {}),
        sandbox=sandbox
    )

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

@web_invoices_bp.route('/invoices/preview', methods=['POST'])
def invoice_preview_route():
    if 'user' not in session: return "No autorizado", 401
    if not check_permission('canInvoice'):
        return "Acceso denegado: requiere permiso de facturación", 403
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    company = DatabaseService.get_company_profile(owner_uid) or {}
    branch_id = request.form.get('branchId')
    branch = {}
    if branch_id:
        branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox) or []
        branch = next((b for b in branches if b['id'] == branch_id), {})
        
    client_id = request.form.get('clientId')
    ecf_type = request.form.get('ecfType', 'Factura de Consumo (E32)')
    
    is_quotation = ecf_type == "Cotización"
        
    currency = request.form.get('currency', 'DOP')
    payment_method = request.form.get('paymentMethod', 'Efectivo')
    payment_type = request.form.get('paymentType', 'Crédito')
    due_date = request.form.get('dueDate')
    discount_rate = float(request.form.get('discountRate', 0.0) or 0.0)
    retained_isr_rate = float(request.form.get('retainedISRRate', 0.0) or 0.0)
    retained_itbis_rate = float(request.form.get('retainedITBISRate', 0.0) or 0.0)
    notes = request.form.get('notes', '').strip()
    comentario = request.form.get('comentario', '').strip()
    footer = request.form.get('footer', '').strip()
    
    client_name = "Consumidor Final"
    client_rnc = request.form.get('clientRNC', '')
    client_contact = ""
    client_email = ""
    client_phone = ""
    client_address = ""
    if client_id:
        clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
        client = next((c for c in clients if c['id'] == client_id), None)
        if client:
            client_name = client.get('razonSocial', 'Consumidor Final')
            client_rnc = client.get('rnc', '')
            client_contact = client.get('contactName', '')
            client_email = client.get('email', '')
            client_phone = client.get('phone', '')
            client_address = client.get('address', '')
            
    parsed_items = []
    form_keys = request.form.keys()
    item_indices = set()
    for k in form_keys:
        if k.startswith('items['):
            parts = k.split(']')
            idx = parts[0].replace('items[', '')
            if idx.isdigit():
                item_indices.add(int(idx))
                
    catalog = DatabaseService.get_items(owner_uid, sandbox=sandbox) or []
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

    regimen = DGIIService.normalize_regimen(company.get("regimenFiscal", "ordinary")) if company else "ordinary"
    regimen_rules = DGIIService.get_regimen_rules(regimen)

    for idx in sorted(item_indices):
        name = request.form.get(f'items[{idx}][name]')
        price = float(request.form.get(f'items[{idx}][price]', 0.0) or 0.0)
        qty = int(request.form.get(f'items[{idx}][quantity]', 1) or 1)
        itbis_rate = float(request.form.get(f'items[{idx}][itbisRate]', 0.18) or 0.18)
        if not regimen_rules.get("itbis_enabled", True):
            itbis_rate = 0.0
        item_disc = float(request.form.get(f'items[{idx}][discountRate]', 0.0) or 0.0)
        
        if name:
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
        return "<h3>Debes añadir al menos una partida a la factura para ver la vista previa.</h3>", 400

    calcs = DGIIService.calculate_invoice_totals(
        parsed_items,
        discount_rate=discount_rate,
        retained_isr_rate=retained_isr_rate,
        retained_itbis_rate=retained_itbis_rate
    )
    
    invoice_number = "VISTA-PREVIA"
    from datetime import datetime
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    invoice = {
        "invoiceNumber": invoice_number,
        "date": now_str,
        "dueDate": due_date,
        "isQuotation": is_quotation,
        "clientName": client_name,
        "clientRNC": client_rnc,
        "clientContact": client_contact,
        "clientEmail": client_email,
        "clientPhone": client_phone,
        "clientAddress": client_address,
        "currency": currency,
        "paymentMethod": payment_method,
        "paymentType": payment_type,
        "items": calcs["items"],
        "subtotal": calcs["subtotal"],
        "totalITBIS": calcs["total_itbis"],
        "totalISCEspecifico": calcs["total_isc_especifico"],
        "totalISCAdValorem": calcs["total_isc_advalorem"],
        "totalOtrosImpuestos": calcs["total_otros_impuestos"],
        "discountAmount": calcs["global_discount"],
        "retainedISR": calcs["retained_isr"],
        "retainedITBIS": calcs["retained_itbis"],
        "total": calcs["total"],
        "netPayable": calcs["net_payable"],
        "notes": notes,
        "comentario": comentario,
        "footer": footer,
        "status": "Borrador",
        "encf": "",
        "xmlSignature": "",
        "emisionMode": "API"
    }

    if WEASYPRINT_AVAILABLE:
        try:
            rendered_html = render_template(
                'invoices/pdf.html',
                invoice=invoice,
                company=company,
                branch=branch,
                auto_print=False,
                qr_base64=None,
                fecha_firma_str=None,
                sandbox=sandbox
            )
            pdf_bytes = WeasyprintHTML(string=rendered_html, base_url=request.host_url).write_pdf()
            response = make_response(pdf_bytes)
            response.headers['Content-Type'] = 'application/pdf'
            response.headers['Content-Disposition'] = 'inline; filename="preview.pdf"'
            return response
        except Exception as e:
            print(f"⚠️ Error al generar preview de PDF con WeasyPrint: {e}")

    rendered_html = render_template(
        'invoices/pdf.html',
        invoice=invoice,
        company=company,
        branch=branch,
        auto_print=True,
        qr_base64=None,
        fecha_firma_str=None,
        sandbox=sandbox
    )
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

    from app.services.audit_service import AuditService, ACTION_EXPORT, MODULE_FACTURAS
    AuditService.log_from_request(
        owner_uid=owner_uid,
        action=ACTION_EXPORT,
        module=MODULE_FACTURAS,
        entity_id=invoice_id,
        entity_label=f"XML Descargado: {invoice.get('invoiceNumber', '')}",
        user_session=session.get('user', {}),
        sandbox=sandbox
    )

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

@web_invoices_bp.route('/expenses/<expense_id>/xml')
def expense_xml_download(expense_id):
    if 'user' not in session: return "No autorizado", 401
    if not check_permission('canExpenses'):
        return "Acceso denegado: requiere permiso de gastos", 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    expense = DatabaseService.get_expense(owner_uid, expense_id, sandbox=sandbox)
    if not expense:
        return "Gasto no encontrado", 404

    xml_content = expense.get('xmlContent') or ''

    if not xml_content or not (xml_content.strip().startswith('<?xml') or xml_content.strip().startswith('<ECF')):
        try:
            from app.services.dgii_xml_builder import DgiiXmlBuilder
            from app.services.dgii_signer import DgiiSigner
            company = DatabaseService.get_company_profile(owner_uid)
            ecf_full_type = "Comprobante de Compras (E41)" if expense.get("ecfType") == "E41" else "Gastos Menores (E43)"
            invoice_payload = _build_expense_ecf_payload(expense, ecf_full_type)
            raw_xml = DgiiXmlBuilder.build_invoice_xml(company, invoice_payload)
            signed_xml_bytes = DgiiSigner.sign_xml(raw_xml, company)
            xml_content = signed_xml_bytes.decode('utf-8')
        except Exception as e:
            xml_content = expense.get('xmlContent') or expense.get('xmlSignature') or ''
            if not xml_content:
                return f"No se pudo generar el XML: {str(e)}", 500

    if not xml_content:
        return "No hay XML disponible para este comprobante", 404

    encf = expense.get('encf') or expense.get('ncf') or expense_id
    inv_num = encf.replace('/', '-').replace(' ', '_')

    if not xml_content.strip().startswith('<?xml'):
        xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_content

    response = make_response(xml_content)
    response.headers['Content-Type'] = 'application/xml; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{inv_num}.xml"'
    return response

@web_invoices_bp.route('/expenses/<expense_id>/pdf')
def expense_pdf_download(expense_id):
    if 'user' not in session: return "No autorizado", 401
    if not check_permission('canExpenses'):
        return "Acceso denegado: requiere permiso de gastos", 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    expense = DatabaseService.get_expense(owner_uid, expense_id, sandbox=sandbox)
    if not expense:
        return "Gasto no encontrado", 404

    company = DatabaseService.get_company_profile(owner_uid)
    encf = expense.get('encf') or expense.get('ncf') or expense_id
    inv_num = encf.replace('/', '-').replace(' ', '_')

    import io
    import base64
    import qrcode
    import urllib.parse
    from datetime import datetime

    qr_url = expense.get("qrCodeURL")
    if expense.get("encf") and expense.get("xmlSignature"):
        try:
            fecha_emision_dt = datetime.strptime(expense.get("date", "")[:10], "%Y-%m-%d")
            fecha_emision_str = fecha_emision_dt.strftime("%d-%m-%Y")
        except:
            fecha_emision_str = ""
        codigo_seg = expense.get("xmlSignature", "")[:6]
        rnc_emisor = company.get("companyRNC", "").replace("-", "").strip()
        monto_total = f"{expense.get('amount', 0.0):.2f}"
        query_params = {
            "RncEmisor": rnc_emisor,
            "ENCF": expense.get("encf"),
            "MontoTotal": monto_total,
            "FechaEmision": fecha_emision_str,
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

    if WEASYPRINT_AVAILABLE:
        rendered_html = render_template('expenses/pdf.html', expense=expense, company=company, auto_print=False, qr_base64=qr_base64, sandbox=sandbox)
        pdf_bytes = WeasyprintHTML(string=rendered_html, base_url=request.host_url).write_pdf()
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="{inv_num}.pdf"'
        return response
    else:
        rendered_html = render_template('expenses/pdf.html', expense=expense, company=company, auto_print=True, qr_base64=qr_base64, sandbox=sandbox)
        response = make_response(rendered_html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        return response

@web_invoices_bp.route('/invoices/<invoice_id>/void', methods=['POST'])
def void_invoice_route(invoice_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Anular Comprobante", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Factura no encontrada.', 'error')
        return redirect(url_for('web_invoices.list_invoices'))
        
    company = DatabaseService.get_company_profile(owner_uid)
    
    # Intentar enviar anulación a DGII
    if invoice.get("encf"):
        canc_dict = {
            "series": invoice["encf"][:3],
            "startSequence": int(invoice["encf"][3:]),
            "endSequence": int(invoice["encf"][3:]),
            "reason": "Anulación de comprobante por solicitud del cliente / error de digitación"
        }
        res = EcfEmissionService.emit_cancellation(company, canc_dict, sandbox=sandbox)
        if res.get("success"):
            before_invoice = invoice.copy()
            invoice["status"] = "Anulada"
            DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)

            # Generar asiento contable reverso automático
            try:
                from app.services.accounting_service import AccountingService
                rev_entry = AccountingService.auto_reverse_invoice_entry(
                    owner_uid, before_invoice,
                    reason="Anulación de comprobante DGII",
                    user_id=session.get('user', {}).get('uid', 'system'),
                    sandbox=sandbox
                )
                if rev_entry:
                    flash(f'✅ Asiento reverso {rev_entry["number"]} generado.', 'info')
                else:
                    import logging
                    logging.getLogger(__name__).warning(f"No se generó reverso contable para {before_invoice.get('invoiceNumber')}")
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Error al generar reverso contable: {e}")
                flash('⚠️ No se pudo generar el asiento contable reverso. Revise el diario manualmente.', 'warning')

            from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_FACTURAS
            AuditService.log_from_request(
                owner_uid=owner_uid,
                action=ACTION_UPDATE,
                module=MODULE_FACTURAS,
                entity_id=invoice_id,
                entity_label=f"Comprobante anulado y reportado a DGII: {invoice['invoiceNumber']}",
                user_session=session.get('user', {}),
                before=before_invoice,
                after=invoice,
                sandbox=sandbox
            )
            
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
        before_invoice = invoice.copy()
        invoice["status"] = "Anulada"
        DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)

        # Generar asiento contable reverso para borradores si fueron emitidos previamente
        if before_invoice.get("status") not in ("Borrador", "Rechazada", "Pagado pero no emitido"):
            try:
                from app.services.accounting_service import AccountingService
                rev_entry = AccountingService.auto_reverse_invoice_entry(
                    owner_uid, before_invoice,
                    reason="Anulación manual",
                    user_id=session.get('user', {}).get('uid', 'system'),
                    sandbox=sandbox
                )
                if rev_entry:
                    flash(f'✅ Asiento reverso {rev_entry["number"]} generado.', 'info')
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Error al generar reverso contable: {e}")

        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_FACTURAS
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_UPDATE,
            module=MODULE_FACTURAS,
            entity_id=invoice_id,
            entity_label=f"Borrador de factura anulado: {invoice['invoiceNumber']}",
            user_session=session.get('user', {}),
            before=before_invoice,
            after=invoice,
            sandbox=sandbox
        )
        flash('Borrador de factura anulado correctamente.', 'success')
        
    return redirect(url_for('web_invoices.list_invoices'))


@web_invoices_bp.route('/invoices/<invoice_id>/delete', methods=['POST'])
def delete_invoice_route(invoice_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Eliminar Documento", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Documento no encontrado.', 'error')
        return redirect(url_for('web_invoices.list_invoices'))

    if invoice.get('status') not in ['Borrador', 'Rechazada', 'Pagado pero no emitido'] and not invoice.get('isQuotation'):
        flash('Solo se pueden eliminar documentos en Borrador o Rechazados.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

    before_invoice = invoice.copy()
    DatabaseService.delete_invoice(owner_uid, invoice_id, sandbox=sandbox)

    from app.services.audit_service import AuditService, ACTION_DELETE, MODULE_FACTURAS, MODULE_COTIZACIONES
    audit_module = MODULE_COTIZACIONES if invoice.get('isQuotation') else MODULE_FACTURAS
    entity_label = f"Cotización eliminada: {invoice.get('invoiceNumber', 'N/A')}" if invoice.get('isQuotation') else f"Factura eliminada: {invoice.get('invoiceNumber', 'N/A')}"
    AuditService.log_from_request(
        owner_uid=owner_uid, action=ACTION_DELETE, module=audit_module,
        entity_id=invoice_id, entity_label=entity_label,
        user_session=session.get('user', {}),
        before=before_invoice, sandbox=sandbox
    )

    flash('Documento eliminado.', 'success')
    return redirect(url_for('web_invoices.list_invoices'))


@web_invoices_bp.route('/api/invoices/sync-contingency', methods=['POST'])
def sync_contingency_invoices():
    """
    Sincroniza las facturas emitidas en Modo Contingencia (FALLBACK) con la DGII.
    Busca todas las facturas con isSyncedWithDGII=False y emisionMode=FALLBACK
    e intenta reenviarlas al servicio DGII Direct una vez restablecida la conexión.
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
        and inv.get('status') in ['Emitida', 'Cobrada', 'Pendiente DGII']
    ]

    synced_count = 0
    failed_count = 0
    results = []

    for inv in pending:
        inv_id = inv['id']
        try:
            # Re-emitir a DGII Direct con el mismo encf ya asignado
            full_inv = DatabaseService.get_invoice(owner_uid, inv_id, sandbox=sandbox)
            target_invoice = full_inv or inv
            res = EcfEmissionService.emit_electronic_comprobante(company, target_invoice, sandbox=sandbox)
            if res.get("success") and res.get("mode", "API") == "API":
                target_invoice["isSyncedWithDGII"] = True
                target_invoice["emisionMode"] = "API"
                target_invoice["dgiiStatus"] = res.get("dgiiStatus") or "ACCEPTED"
                target_invoice["xmlSignature"] = res.get("xmlSignature", target_invoice.get("xmlSignature", ""))
                target_invoice["qrCodeURL"] = res.get("qrCodeURL", target_invoice.get("qrCodeURL", ""))
                target_invoice["contingencyEmittedAt"] = None
                if float(target_invoice.get("totalPaid", 0.0)) >= float(target_invoice.get("netPayable", target_invoice.get("total", 0.0))) and float(target_invoice.get("totalPaid", 0.0)) > 0:
                    target_invoice["status"] = "Cobrada"
                elif target_invoice.get("status") == "Pendiente DGII":
                    target_invoice["status"] = "Emitida"
                DatabaseService.save_invoice(owner_uid, inv_id, target_invoice, sandbox=sandbox)

                # Registrar en Log de Auditoría que pasó de FALLBACK a sincronizado
                logs = DatabaseService.get_sequence_logs(owner_uid, sandbox=sandbox)
                log = next((l for l in logs if l.get("encf") == target_invoice.get("encf")), None)
                if log:
                    cuadratura = DGIIService.check_tolerancia_cuadratura(target_invoice.get("items", []), target_invoice.get("total", 0))
                    estado_dgii = "ACCEPTED" if cuadratura["within_tolerance"] else "ACCEPTED_CONDITIONAL"
                    DatabaseService.update_sequence_log(owner_uid, log["id"], {
                        "estado": estado_dgii,
                        "motivo": f"Regularizado por Sincronización Post-Contingencia. Firma: {res['xmlSignature'][:12] if res.get('xmlSignature') else 'N/A'}",
                        "xmlEnviado": json.dumps(res.get("requestPayload"), indent=2) if res.get("requestPayload") else "",
                        "respuestaDGII": json.dumps(res.get("responseBody"), indent=2) if res.get("responseBody") else ""
                    }, sandbox=sandbox)

                if target_invoice.get("isConsolidado") and target_invoice.get("consolidatedInvoiceIds"):
                    pending_children = []
                    for child_id in target_invoice.get("consolidatedInvoiceIds", []):
                        child_inv = DatabaseService.get_invoice(owner_uid, child_id, sandbox=sandbox)
                        if child_inv:
                            pending_children.append(child_inv)
                    if pending_children:
                        DatabaseService.mark_invoices_consolidated(
                            owner_uid,
                            target_invoice.get("consolidatedInvoiceIds", []),
                            target_invoice.get("encf", ""),
                            target_invoice.get("invoiceNumber", ""),
                            pending_invoices=pending_children,
                            is_synced=True,
                            dgii_status=target_invoice.get("dgiiStatus") or "ACCEPTED",
                            emision_mode=target_invoice.get("emisionMode") or "API",
                            sandbox=sandbox
                        )

                synced_count += 1
                results.append({"encf": target_invoice.get("encf"), "status": "synced"})
            else:
                failed_count += 1
                results.append({"encf": target_invoice.get("encf"), "status": "still_offline", "mode": res.get("mode")})
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
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Sincronizar Comprobante", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Factura no encontrada.', 'error')
        return redirect(url_for('web_invoices.list_invoices'))
        
    company = DatabaseService.get_company_profile(owner_uid)
    
    try:
        res = EcfEmissionService.emit_electronic_comprobante(company, invoice, sandbox=sandbox)
        if res.get("success") and res.get("mode", "API") == "API":
            invoice["isSyncedWithDGII"] = True
            invoice["emisionMode"] = "API"
            invoice["dgiiStatus"] = res.get("dgiiStatus") or "ACCEPTED"
            invoice["xmlSignature"] = res.get("xmlSignature", invoice.get("xmlSignature", ""))
            invoice["qrCodeURL"] = res.get("qrCodeURL", invoice.get("qrCodeURL", ""))
            invoice["contingencyEmittedAt"] = None
            if res.get("pdfUrl"): invoice["firebasePDFURL"] = res["pdfUrl"]
            if res.get("xmlUrl"): invoice["firebaseXMLURL"] = res["xmlUrl"]
            if float(invoice.get("totalPaid", 0.0)) >= float(invoice.get("netPayable", invoice.get("total", 0.0))) and float(invoice.get("totalPaid", 0.0)) > 0:
                invoice["status"] = "Cobrada"
            elif invoice.get("status") == "Pendiente DGII":
                invoice["status"] = "Emitida"
            
            DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)

            if invoice.get("isConsolidado") and invoice.get("consolidatedInvoiceIds"):
                pending_children = []
                for child_id in invoice.get("consolidatedInvoiceIds", []):
                    child_inv = DatabaseService.get_invoice(owner_uid, child_id, sandbox=sandbox)
                    if child_inv:
                        pending_children.append(child_inv)
                if pending_children:
                    DatabaseService.mark_invoices_consolidated(
                        owner_uid,
                        invoice.get("consolidatedInvoiceIds", []),
                        invoice.get("encf", ""),
                        invoice.get("invoiceNumber", ""),
                        pending_invoices=pending_children,
                        is_synced=True,
                        dgii_status=invoice.get("dgiiStatus") or "ACCEPTED",
                        emision_mode=invoice.get("emisionMode") or "API",
                        sandbox=sandbox
                    )
            
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
            flash(f"No se pudo sincronizar: {res.get('message') or 'Sigue en modalidad de contingencia (sin conexión a DGII).'}", 'warning')
    except Exception as e:
        flash(f"Error durante la sincronización: {str(e)}", 'error')
        
    return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

# =========================================================================
# CONTROL DE GASTOS Y RENTABILIDAD
# =========================================================================
@web_invoices_bp.route('/expenses')
def list_expenses():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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

    # Filtros
    category_filter = request.args.get('category', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    search_query = request.args.get('search', '').strip().lower()
    tab = request.args.get('tab', 'all').strip()
    
    filtered_expenses = []
    for exp in expenses:
        if category_filter and exp.get('category') != category_filter:
            continue
        if start_date and exp.get('date', '')[:10] < start_date:
            continue
        if end_date and exp.get('date', '')[:10] > end_date:
            continue
        if search_query:
            concept = exp.get('concept', '').lower()
            ncf = exp.get('ncf', '').lower()
            rnc = exp.get('rncEmisor', '').lower()
            provider = exp.get('providerName', '').lower()
            if search_query not in concept and search_query not in ncf and search_query not in rnc and search_query not in provider:
                continue
        if tab == 'recurring' and not exp.get('isRecurring'):
            continue
        if tab == 'minor' and exp.get('ecfType') != 'E43':
            continue
        filtered_expenses.append(exp)

    # Exportar a CSV si se solicita
    if request.args.get('export') == 'csv':
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["Fecha", "Concepto", "Categoría", "NCF", "RNC Emisor", "Proveedor", "Monto Total (RD$)", "ITBIS (RD$)", "Factura Imputada", "Recurrente", "Estatus Aprobación"])
        for exp in filtered_expenses:
            writer.writerow([
                exp.get("date", "")[:10],
                exp.get("concept", ""),
                exp.get("category", ""),
                exp.get("ncf", ""),
                exp.get("rncEmisor", ""),
                exp.get("providerName", ""),
                f"{exp.get('amount', 0.0):.2f}",
                f"{exp.get('itbisAmount', 0.0):.2f}",
                exp.get("invoice_number", ""),
                "Sí" if exp.get("isRecurring") else "No",
                exp.get("approvalStatus", "")
            ])
            
        dest = io.BytesIO()
        dest.write(b'\xef\xbb\xbf')  # UTF-8 BOM
        dest.write(output.getvalue().encode('utf-8'))
        dest.seek(0)
        
        filename = f"reporte_gastos_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(
            dest,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )
                    
    total_items = len(filtered_expenses)
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    per_page = request.args.get('per_page', '10').strip()
    if per_page == 'all':
        per_page_val = max(1, total_items)
    else:
        try:
            per_page_val = int(per_page)
            if per_page_val not in [10, 25, 50, 100]:
                per_page_val = 10
        except ValueError:
            per_page_val = 10
    total_pages = max(1, (total_items + per_page_val - 1) // per_page_val)
    if page < 1: page = 1
    if page > total_pages: page = total_pages
    start_idx = (page - 1) * per_page_val
    end_idx = start_idx + per_page_val
    paginated = filtered_expenses[start_idx:end_idx]
    start_count = ((page - 1) * per_page_val) + 1 if total_items > 0 else 0
    end_count = min(page * per_page_val, total_items)

    return render_template(
        'expenses/list.html', 
        active_page='expenses', 
        expenses=paginated,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
        pages_range=range(1, total_pages + 1),
        has_prev=page > 1,
        has_next=page < total_pages,
        start_count=start_count,
        end_count=end_count,
        category_filter=category_filter,
        start_date=start_date,
        end_date=end_date,
        search_query=search_query,
        tab=tab
    )

@web_invoices_bp.route('/expenses/api/next-ecf', methods=['GET'])
def expense_next_ecf_api():
    """
    API: Devuelve el próximo número de e-CF disponible para un tipo dado (E41, E43, etc.)
    sin consumirlo. Útil para pre-rellenar el campo NCF en el formulario de gasto.
    Query param: ?tipo=E43
    """
    if 'user' not in session:
        return jsonify({"error": "No autenticado"}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    tipo = request.args.get('tipo', '').upper().strip()

    if not tipo:
        return jsonify({"error": "Parámetro 'tipo' requerido"}), 400

    try:
        sequences = DatabaseService.get_sequences(owner_uid, sandbox=sandbox)
        # Buscar la secuencia ACTIVA para ese tipo
        seq = next(
            (s for s in sequences
             if s.get('tipoComprobante', '').upper() == tipo
             and s.get('estado', '').upper() == 'ACTIVA'
             and not s.get('bloqueadaManualmente', False)),
            None
        )
        if not seq:
            return jsonify({"error": f"No hay una secuencia ACTIVA para {tipo}"}), 404

        ultimo = int(seq.get('ultimoConsecutivoUsado', seq.get('secuenciaInicial', 1) - 1))
        siguiente = ultimo + 1
        final = int(seq.get('secuenciaFinal', siguiente))
        disponibles = max(0, final - ultimo)

        if siguiente > final:
            return jsonify({"error": f"La secuencia de {tipo} está AGOTADA"}), 409

        encf = f"{tipo}{siguiente:010d}"
        return jsonify({
            "encf": encf,
            "tipo": tipo,
            "consecutivo": siguiente,
            "disponibles": disponibles,
            "secuenciaFinal": final
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================================================================
# FUNCIONES AUXILIARES PARA EMISIÓN e-CF DE GASTOS (E41 / E43)
# =========================================================================

def _build_expense_ecf_payload(expense_dict, ecf_full_type):
    """
    Adapta un expense_dict al formato invoice_dict que espera EcfEmissionService.
    Usado para emitir E41 (Comprobante de Compras) y E43 (Gastos Menores) desde
    el módulo de gastos.
    """
    amount   = float(expense_dict.get("amount", 0.0))
    itbis    = float(expense_dict.get("itbisAmount", 0.0))
    subtotal = round(amount - itbis, 2)
    if subtotal < 0:
        subtotal = amount

    date_str = expense_dict.get("date", datetime.now(timezone.utc).isoformat())
    due_str  = expense_dict.get("dueDate") or date_str

    return {
        "id":             expense_dict.get("id", ""),
        "ecfType":        ecf_full_type,
        "encf":           expense_dict.get("encf", "PENDIENTE"),
        "date":           date_str,
        "dueDate":        due_str,
        "clientName":     expense_dict.get("providerName") or "Proveedor Genérico",
        "clientRNC":      expense_dict.get("rncEmisor", ""),
        "paymentType":    expense_dict.get("paymentType", "Contado"),
        "paymentMethod":  "Efectivo",
        "subtotal":       subtotal,
        "totalITBIS":     itbis,
        "total":          amount,
        "netPayable":     amount,
        "retainedITBIS":  float(expense_dict.get("retainedITBIS", 0.0)),
        "retainedISR":    float(expense_dict.get("retainedISR", 0.0)),
        "notes":          expense_dict.get("notes", ""),
        "invoiceNumber":  expense_dict.get("ecfNumber") or expense_dict.get("ncf", ""),
        "items": [{
            "id":        expense_dict.get("id", "item-gasto-1"),
            "code":      "GASTO-01",
            "name":      expense_dict.get("concept", "Gasto Operativo"),
            "type":      "Servicio",
            "quantity":  1,
            "price":     subtotal,
            "subtotal":  subtotal,
            "itbisRate": round(itbis / subtotal, 4) if subtotal > 0 else 0.0,
            "total":     amount
        }]
    }


def _update_expense_sequence_log(owner_uid, log_id, emission_res, expense_dict, sandbox):
    """
    Actualiza el log de secuencia (trazabilidad fiscal) con el resultado
    de la emisión del e-CF del gasto (E41 o E43).
    """
    try:
        if not log_id:
            return
        items = expense_dict.get("items") or [{
            "subtotal": expense_dict.get("amount", 0.0),
            "itbisAmount": expense_dict.get("itbisAmount", 0.0)
        }]
        cuadratura = DGIIService.check_tolerancia_cuadratura(items, expense_dict.get("amount", 0.0))
        estado_dgii = "ACCEPTED" if cuadratura["within_tolerance"] else "ACCEPTED_CONDITIONAL"

        sig_show = emission_res.get("xmlSignature") or emission_res.get("trackId") or "N/A"
        motivo   = f"Aprobado (Gasto e-CF). Firma/TrackID: {str(sig_show)[:16]}"
        if estado_dgii == "ACCEPTED_CONDITIONAL":
            motivo = f"Aceptado Condicional: {', '.join(cuadratura.get('warnings', []))}"
        if emission_res.get("mode") == "FALLBACK":
            estado_dgii = "CONTINGENCY"
            motivo = "Emitido en modo contingencia. Pendiente de sincronización con DGII."
        elif emission_res.get("status") == "PENDING":
            estado_dgii = "PENDING"
            motivo = "En proceso de validación por la DGII."

        DatabaseService.update_sequence_log(owner_uid, log_id, {
            "estado":       estado_dgii,
            "motivo":       motivo,
            "xmlEnviado":   json.dumps(emission_res.get("requestPayload"), indent=2) if emission_res.get("requestPayload") else "",
            "respuestaDGII": json.dumps(emission_res.get("responseBody"), indent=2) if emission_res.get("responseBody") else ""
        }, sandbox=sandbox)
    except Exception as e:
        print(f"⚠️ Error al actualizar log de secuencia para gasto e-CF: {e}")


@web_invoices_bp.route('/expenses/new', methods=['GET', 'POST'])
def new_expense_route():
    return redirect(url_for('web_invoices.payments_new_route'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    if request.method == 'POST':
        expense_id = str(uuid.uuid4())
        
        # Procesar MÚLTIPLES archivos subidos a Storage
        attachment_files = request.files.getlist('attachments[]')
        attachment_types = request.form.getlist('attachmentTypes[]')
        attachment_urls = []      # retrocompatibilidad: lista de URLs simples
        attachments = []          # nuevo: lista de {url, type, name}
        
        for i, att_file in enumerate(attachment_files):
            if att_file and att_file.filename:
                file_data = att_file.read()
                mime_type = att_file.content_type or "image/jpeg"
                safe_name = att_file.filename.replace(' ', '_')
                dest_path = f"users/{owner_uid}/expenses/{expense_id}/{safe_name}"
                try:
                    public_url = DatabaseService.upload_file_to_storage(file_data, dest_path, mime_type)
                    att_type = attachment_types[i] if i < len(attachment_types) else 'otro'
                    attachment_urls.append(public_url)
                    attachments.append({'url': public_url, 'type': att_type, 'name': att_file.filename})
                except Exception as e:
                    print(f"⚠️ Error al subir adjunto {att_file.filename}: {e}")

        currency = request.form.get('currency', 'DOP')
        exchange_rate = float(request.form.get('exchangeRate', 1.0)) if currency != 'DOP' else 1.0
        amount_original = float(request.form['amount'])
        amount = amount_original * exchange_rate
        
        raw_itbis = request.form.get('itbisAmount', '').strip()
        itbis_amount_original = float(raw_itbis) if raw_itbis else 0.0
        is_recurring = request.form.get('isRecurring') == 'true'
        is_deductible = request.form.get('isDeductible') == 'true'
        recurrence_interval = request.form.get('recurrenceInterval', 'mensual')
        next_occurrence = request.form.get('nextOccurrenceDate')
        recurrence_end_date = request.form.get('recurrenceEndDate')
        
        payment_type = request.form.get('paymentType', 'Contado')
        due_date = request.form.get('dueDate', '')
        

        assigned_approver_id = request.form.get('assignedApproverId', '')
        assigned_approver_name = ""
        assigned_approver_email = ""
        if assigned_approver_id:
            team_members = DatabaseService.get_team_members(owner_uid)
            owner_profile = DatabaseService.get_user_profile(owner_uid)
            if owner_profile and not any(m.get('uid') == owner_uid for m in team_members):
                team_members.insert(0, {
                    "uid": owner_profile.get("uid"),
                    "name": f"{owner_profile.get('name', 'Usuario Principal')} (Tú)",
                    "email": owner_profile.get("email", "")
                })
            for m in team_members:
                if m.get('uid') == assigned_approver_id:
                    assigned_approver_name = m.get('name', '')
                    assigned_approver_email = m.get('email', '')
                    break
        

        assigned_approver_id = request.form.get('assignedApproverId', '')
        assigned_approver_name = ""
        assigned_approver_email = ""
        if assigned_approver_id:
            team_members = DatabaseService.get_team_members(owner_uid)
            owner_profile = DatabaseService.get_user_profile(owner_uid)
            if owner_profile and not any(m.get('uid') == owner_uid for m in team_members):
                team_members.insert(0, {
                    "uid": owner_profile.get("uid"),
                    "name": f"{owner_profile.get('name', 'Usuario Principal')} (Tú)",
                    "email": owner_profile.get("email", "")
                })
            for m in team_members:
                if m.get('uid') == assigned_approver_id:
                    assigned_approver_name = m.get('name', '')
                    assigned_approver_email = m.get('email', '')
                    break
        
        # CxP Status
        cxp_status = 'Pagado'
        if payment_type == 'Crédito':
            cxp_status = 'Pendiente'

        expense_dict = {
            "supplierType": request.form.get('supplierType', 'formal'),
            "concept": request.form['concept'],
            "category": request.form['category'],
            "currency": currency,
            "exchangeRate": exchange_rate,
            "amountOriginal": amount_original,
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
            "itbisAmountOriginal": itbis_amount_original,
            "itbisAmount": itbis_amount_original * exchange_rate,
            "isITBISDeductible": is_deductible,
            "isDeductible": is_deductible,
            "assignedApproverId": assigned_approver_id,
            "assignedApproverName": assigned_approver_name,
            "assignedApproverEmail": assigned_approver_email,
            "firebaseAttachmentURLs": attachment_urls,
            "attachments": attachments,
            # Nuevos campos e-CF y CxP:
            "assignedApproverId": assigned_approver_id,
            "assignedApproverName": assigned_approver_name,
            "assignedApproverEmail": assigned_approver_email,
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
            "dueDate": due_date,
            "bankAccountId": request.form.get('bankAccountId', '')
        }
        
        DatabaseService.save_expense(owner_uid, expense_id, expense_dict, sandbox=sandbox)

        # Actualizar saldo de la cuenta bancaria si se especificó bankAccountId
        bank_account_id = expense_dict.get("bankAccountId")
        if bank_account_id:
            try:
                bank_acc = DatabaseService.get_bank_account(owner_uid, bank_account_id, sandbox=sandbox)
                if bank_acc:
                    new_balance = bank_acc["currentBalance"] - amount
                    DatabaseService.save_bank_account(owner_uid, bank_account_id, {
                        **bank_acc,
                        "currentBalance": new_balance
                    }, sandbox=sandbox)
            except Exception as bank_err:
                print(f"⚠️ Error al actualizar saldo de cuenta bancaria en gasto: {bank_err}")

        # === EMISIÓN e-CF PARA E41 (Comprobante de Compras) / E43 (Gastos Menores) ===
        # Solo aplica cuando el usuario opera bajo e-CF y selecciona estos tipos.
        ecf_type_raw = expense_dict.get("ecfType", "")
        should_emit_ecf = ecf_type_raw in (
            "E41", "E43",
            "Comprobante de Compras (E41)",
            "Gastos Menores (E43)"
        )
        ecf_emission_msg = None
        if should_emit_ecf:
            try:
                ecf_short    = "E41" if "E41" in ecf_type_raw else "E43"
                ecf_full_type = "Comprobante de Compras (E41)" if ecf_short == "E41" else "Gastos Menores (E43)"
                user_email   = session['user']['email']

                # Verificar límite de documentos (solo en producción)
                exceeded, limit_msg = check_document_limit_exceeded(owner_uid, sandbox=sandbox)
                if exceeded:
                    ecf_emission_msg = ("warning", limit_msg)
                else:
                    if limit_msg:
                        flash(limit_msg, 'warning')

                    # Consumir la siguiente secuencia autorizada por la DGII
                    encf, log_id = DatabaseService.consume_next_sequence(
                        owner_uid, ecf_short, user_email, sandbox=sandbox
                    )
                    expense_dict["encf"]      = encf
                    expense_dict["ecfNumber"] = encf
                    expense_dict["ncf"]       = encf

                    # Obtener perfil de la empresa emisora
                    company = DatabaseService.get_company_profile(owner_uid)

                    # Construir payload y emitir ante la DGII vía proveedor activo
                    invoice_payload = _build_expense_ecf_payload(expense_dict, ecf_full_type)
                    res = EcfEmissionService.emit_electronic_comprobante(
                        company, invoice_payload, sandbox=sandbox
                    )

                    if res.get("success"):
                        expense_dict["encf"]             = res.get("encf", encf)
                        expense_dict["ecfNumber"]        = res.get("encf", encf)
                        expense_dict["xmlSignature"]     = res.get("xmlSignature", "")
                        expense_dict["qrCodeURL"]        = res.get("qrCodeURL", "")
                        pending_dgii = res.get("status") == "PENDING"
                        expense_dict["isSyncedWithDGII"] = (res.get("mode", "API") == "API" and not pending_dgii)
                        expense_dict["emisionMode"]      = res.get("mode", "API")
                        expense_dict["trackId"]          = res.get("trackId", "")
                        expense_dict["dgiiStatus"]        = res.get("dgiiStatus") or ("CONTINGENCY" if res.get("mode") == "FALLBACK" else ("PENDING" if pending_dgii else "ACCEPTED"))
                        # Generar y guardar el XML firmado
                        try:
                            from app.services.dgii_xml_builder import DgiiXmlBuilder
                            from app.services.dgii_signer import DgiiSigner
                            raw_xml = DgiiXmlBuilder.build_invoice_xml(company, invoice_payload)
                            signed_xml_bytes = DgiiSigner.sign_xml(raw_xml, company)
                            expense_dict["xmlContent"] = signed_xml_bytes.decode('utf-8')
                        except Exception as xml_err:
                            print(f"⚠️ Error al generar XML para gasto {expense_id}: {xml_err}")
                        # Persistir datos de la DGII en Firestore
                        DatabaseService.save_expense(owner_uid, expense_id, expense_dict, sandbox=sandbox)
                        # Registrar en el log de trazabilidad fiscal
                        _update_expense_sequence_log(owner_uid, log_id, res, expense_dict, sandbox)

                        if res.get("mode") == "FALLBACK":
                            ecf_emission_msg = ("warning",
                                f"⚠️ e-CF emitido en contingencia (sin conexión a la DGII). "
                                f"e-NCF: {expense_dict['encf']}. Sincronizar en máximo 72 horas.")
                        else:
                            ecf_emission_msg = ("success",
                                f"✅ Gasto registrado y {ecf_short} emitido ante la DGII. "
                                f"e-NCF: {expense_dict['encf']}")
                    else:
                        ecf_emission_msg = ("warning",
                            f"Gasto guardado, pero error al emitir el e-CF: "
                            f"{res.get('message', 'Error desconocido')}")

            except Exception as e:
                print(f"❌ Error al emitir e-CF para gasto {expense_id}: {e}")
                ecf_emission_msg = ("error",
                    f"Gasto guardado, pero fallo en la emisión del e-CF ({ecf_short}): {str(e)}")

        from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_GASTOS
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_CREATE,
            module=MODULE_GASTOS,
            entity_id=expense_id,
            entity_label=f"Gasto registrado: {expense_dict['concept']} (Monto: RD$ {amount:.2f})",
            user_session=session.get('user', {}),
            after=expense_dict,
            sandbox=sandbox
        )

        if ecf_emission_msg:
            flash(ecf_emission_msg[1], ecf_emission_msg[0])
        else:
            flash('Gasto operativo registrado exitosamente.', 'success')

        # Notificación al aprobador si el gasto queda pendiente de aprobación
        if request.form.get('approvalStatus', 'Aprobado') == 'Pendiente' and assigned_approver_id:
            try:
                from app.services.notifications import NotificationService
                notif_data = {
                    "title": "Gasto Asignado para Aprobación",
                    "message": f"Se te ha asignado el gasto '{expense_dict.get('concept', '')}' por RD$ {expense_dict.get('amount', 0.0):,.2f} para tu revisión.",
                    "type": "info",
                    "link": "/expenses"
                }
                DatabaseService.create_user_notification(assigned_approver_id, notif_data)
                if assigned_approver_email:
                    NotificationService.send_expense_assignment_notification(
                        recipient_email=assigned_approver_email,
                        recipient_name=assigned_approver_name,
                        expense=expense_dict,
                        owner_uid=owner_uid,
                        sandbox=sandbox
                    )
            except Exception as e:
                print("Error enviando notificacion de gasto: ", e)

        return redirect(url_for('web_invoices.list_expenses'))


        
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    team_members = DatabaseService.get_team_members(owner_uid)
    owner_profile = DatabaseService.get_user_profile(owner_uid)
    if owner_profile and not any(m.get('uid') == owner_uid for m in team_members):
        team_members.insert(0, {
            "uid": owner_profile.get("uid"),
            "name": f"{owner_profile.get('name', 'Usuario Principal')} (Tú)",
            "email": owner_profile.get("email", "")
        })
    # Secuencias disponibles para gastos (E41, E43)
    all_sequences = DatabaseService.get_sequences(owner_uid, sandbox=sandbox)
    expense_sequences = {
        s['tipoComprobante']: s
        for s in all_sequences
        if s.get('tipoComprobante', '').upper() in ('E41', 'E43')
        and s.get('estado', '').upper() == 'ACTIVA'
        and not s.get('bloqueadaManualmente', False)
    }
    bank_accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox)
    return render_template(
        'expenses/new.html',
        active_page='expenses',
        team_members=team_members,
        invoices=[],
        today_str=today_str,
        expense_sequences=expense_sequences,
        bank_accounts=bank_accounts
    )


# =========================================================================
# PAGOS / GASTOS — Listado y Creación
# =========================================================================

@web_invoices_bp.route('/expenses/payments')
def payments_list():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Pagos y Gastos", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    # Filter: exclude E43 (minor) and recurring
    filtered = [e for e in expenses if e.get('ecfType') != 'E43' and not e.get('isRecurring')]

    category_filter = request.args.get('category', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    search_query = request.args.get('search', '').strip().lower()

    for exp in filtered[:]:
        if category_filter and exp.get('category') != category_filter:
            filtered.remove(exp); continue
        if start_date and exp.get('date', '')[:10] < start_date:
            filtered.remove(exp); continue
        if end_date and exp.get('date', '')[:10] > end_date:
            filtered.remove(exp); continue
        if search_query:
            concept = exp.get('concept', '').lower()
            ncf = exp.get('ncf', '').lower()
            rnc = exp.get('rncEmisor', '').lower()
            provider = exp.get('providerName', '').lower()
            if search_query not in concept and search_query not in ncf and search_query not in rnc and search_query not in provider:
                filtered.remove(exp)
                continue

    total_items = len(filtered)
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    per_page_val = 20
    total_pages = max(1, (total_items + per_page_val - 1) // per_page_val)
    if page < 1: page = 1
    if page > total_pages: page = total_pages
    start_idx = (page - 1) * per_page_val
    paginated = filtered[start_idx:start_idx + per_page_val]
    start_count = ((page - 1) * per_page_val) + 1 if total_items > 0 else 0
    end_count = min(page * per_page_val, total_items)

    total_amount = sum(e.get('amount', 0) for e in filtered)
    paid_amount = sum(e.get('amount', 0) for e in filtered if e.get('cxpStatus') == 'Pagado')
    pending_amount = sum(e.get('amount', 0) for e in filtered if e.get('cxpStatus') == 'Pendiente')
    paid_count = sum(1 for e in filtered if e.get('cxpStatus') == 'Pagado')
    pending_count = sum(1 for e in filtered if e.get('cxpStatus') == 'Pendiente')

    return render_template(
        'expenses/payments_list.html',
        active_page='expenses_payments',
        expenses=paginated,
        page=page, total_pages=total_pages, total_items=total_items,
        has_prev=page > 1, has_next=page < total_pages,
        start_count=start_count, end_count=end_count,
        category_filter=category_filter, start_date=start_date, end_date=end_date,
        search_query=search_query,
        total_amount=total_amount, paid_amount=paid_amount, pending_amount=pending_amount,
        paid_count=paid_count, pending_count=pending_count
    )


@web_invoices_bp.route('/expenses/payments/new', methods=['GET', 'POST'])
def payments_new_route():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Nuevo Pago", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    if request.method == 'POST':
        expense_id = str(uuid.uuid4())
        currency = request.form.get('currency', 'DOP')
        exchange_rate = float(request.form.get('exchangeRate', 1.0)) if currency != 'DOP' else 1.0

        account_items = []
        idx = 0
        while True:
            concept = request.form.get(f'account_items[{idx}][concept]')
            if concept is None:
                break
            concept_id = request.form.get(f'account_items[{idx}][concept_id]', '')
            value = float(request.form.get(f'account_items[{idx}][value]', 0) or 0)
            tax = float(request.form.get(f'account_items[{idx}][tax]', 0) or 0)
            qty = int(request.form.get(f'account_items[{idx}][quantity]', 1) or 1)
            obs = request.form.get(f'account_items[{idx}][observations]', '')
            total = float(request.form.get(f'account_items[{idx}][total]', 0) or 0)
            account_items.append({
                'concept': concept, 'concept_id': concept_id, 'value': value, 'tax': tax,
                'quantity': qty, 'observations': obs, 'total': total
            })
            idx += 1

        total_amount = sum(item['total'] for item in account_items)
        amount = total_amount * exchange_rate

        concept_value = account_items[0]['concept'] if account_items else request.form.get('notes', '')
        if not concept_value or not concept_value.strip():
            flash('El concepto del gasto es obligatorio.', 'error')
            return redirect(url_for('web_invoices.payments_new_route'))

        payment_type = 'Contado'
        cxp_status = 'Pagado'

        expense_dict = {
            'supplierType': 'formal',
            'concept': account_items[0]['concept'] if account_items else request.form.get('notes', 'Pago'),
            'category': request.form.get('category', 'Otros Gastos'),
            'currency': currency,
            'exchangeRate': exchange_rate,
            'amountOriginal': total_amount,
            'amount': amount,
            'date': request.form['date'],
            'rncEmisor': request.form.get('rncEmisor', ''),
            'providerName': request.form.get('providerName', ''),
            'ncf': '',
            'isMinorExpense': False,
            'isSyncedWithDGII': False,
            'notes': request.form.get('notes', ''),
            'isRecurring': False,
            'itbisAmountOriginal': 0.0,
            'itbisAmount': 0.0,
            'isITBISDeductible': True,
            'isDeductible': True,
            'ecfType': request.form.get('ecfType', 'Gasto'),
            'cne': '',
            'tipoGastoDGII': '02',
            'paymentType': payment_type,
            'paymentMethod': request.form.get('paymentMethod', 'transferencia'),
            'cxpStatus': cxp_status,
            'cxpRemainingBalance': 0.0,
            'approvalStatus': 'Aprobado',
            'dueDate': request.form.get('date', ''),
            'bankAccountId': request.form.get('bankAccountId', ''),
            'retainedISR': float(request.form.get('retainedISRRate', 0) or 0),
            'retainedITBIS': float(request.form.get('retainedITBISRate', 0) or 0),
            'accountItems': account_items,
            'expense_type': 'payment',
            'comentario': request.form.get('comentario', ''),
        }

        try:
            DatabaseService.save_expense(owner_uid, expense_id, expense_dict, sandbox=sandbox)
        except ValueError as ve:
            flash(str(ve), 'error')
            return redirect(url_for('web_invoices.payments_new_route'))

        bank_account_id = expense_dict.get('bankAccountId')
        if bank_account_id:
            try:
                bank_acc = DatabaseService.get_bank_account(owner_uid, bank_account_id, sandbox=sandbox)
                if bank_acc:
                    new_balance = bank_acc['currentBalance'] - amount
                    DatabaseService.save_bank_account(owner_uid, bank_account_id, {
                        **bank_acc, 'currentBalance': new_balance
                    }, sandbox=sandbox)
            except Exception as e:
                print(f"Error al actualizar saldo de cuenta bancaria: {e}")

        try:
            from app.services.accounting_service import AccountingService
            AccountingService.auto_generate_expense_entry(owner_uid, expense_dict, sandbox=sandbox)
        except Exception as acc_err:
            print(f"Error al generar asiento contable del gasto: {acc_err}")

        flash('Pago registrado exitosamente.', 'success')
        return redirect(url_for('web_invoices.payments_list'))

    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    bank_accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox)
    accounting_accounts = DatabaseService.get_chart_of_accounts(owner_uid)
    tax_rules = DatabaseService.get_tax_rules(owner_uid)
    itbis_general = tax_rules.get('itbis', {}).get('general', 0.18)
    itbis_reduced = tax_rules.get('itbis', {}).get('reduced', 0.16)
    return render_template(
        'expenses/payments_new.html',
        active_page='expenses_payments',
        today_str=today_str,
        bank_accounts=bank_accounts,
        accounting_accounts=accounting_accounts,
        itbis_general=itbis_general,
        itbis_reduced=itbis_reduced
    )


# =========================================================================
# GASTOS MENORES (E43) — Listado y Creación
# =========================================================================

@web_invoices_bp.route('/expenses/minor')
def minor_list():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Gastos Menores", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    filtered = [e for e in expenses if e.get('ecfType') == 'E43']

    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    search_query = request.args.get('search', '').strip().lower()

    for exp in filtered[:]:
        if start_date and exp.get('date', '')[:10] < start_date:
            filtered.remove(exp); continue
        if end_date and exp.get('date', '')[:10] > end_date:
            filtered.remove(exp); continue
        if search_query:
            concept = exp.get('concept', '').lower()
            notes = exp.get('notes', '').lower()
            if search_query not in concept and search_query not in notes:
                filtered.remove(exp)
                continue

    total_items = len(filtered)
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    per_page_val = 20
    total_pages = max(1, (total_items + per_page_val - 1) // per_page_val)
    if page < 1: page = 1
    if page > total_pages: page = total_pages
    start_idx = (page - 1) * per_page_val
    paginated = filtered[start_idx:start_idx + per_page_val]
    start_count = ((page - 1) * per_page_val) + 1 if total_items > 0 else 0
    end_count = min(page * per_page_val, total_items)

    total_amount = sum(e.get('amount', 0) for e in filtered)
    this_month = datetime.now(timezone.utc).strftime('%Y-%m')
    this_month_expenses = [e for e in filtered if e.get('date', '')[:7] == this_month]
    this_month_amount = sum(e.get('amount', 0) for e in this_month_expenses)
    avg_amount = total_amount / total_items if total_items > 0 else 0

    return render_template(
        'expenses/minor_list.html',
        active_page='expenses_minor',
        expenses=paginated,
        page=page, total_pages=total_pages, total_items=total_items,
        has_prev=page > 1, has_next=page < total_pages,
        start_count=start_count, end_count=end_count,
        start_date=start_date, end_date=end_date, search_query=search_query,
        total_amount=total_amount,
        this_month_amount=this_month_amount, this_month_count=len(this_month_expenses),
        avg_amount=avg_amount
    )


@web_invoices_bp.route('/expenses/minor/new', methods=['GET', 'POST'])
def minor_new_route():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Nuevo Gasto Menor", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    if request.method == 'POST':
        expense_id = str(uuid.uuid4())
        currency = request.form.get('currency', 'DOP')
        exchange_rate = float(request.form.get('exchangeRate', 1.0)) if currency != 'DOP' else 1.0

        account_items = []
        idx = 0
        while True:
            concept = request.form.get(f'account_items[{idx}][concept]')
            if concept is None:
                break
            concept_id = request.form.get(f'account_items[{idx}][concept_id]', '')
            value = float(request.form.get(f'account_items[{idx}][value]', 0) or 0)
            tax = float(request.form.get(f'account_items[{idx}][tax]', 0) or 0)
            qty = int(request.form.get(f'account_items[{idx}][quantity]', 1) or 1)
            obs = request.form.get(f'account_items[{idx}][observations]', '')
            total = float(request.form.get(f'account_items[{idx}][total]', 0) or 0)
            account_items.append({
                'concept': concept, 'concept_id': concept_id, 'value': value, 'tax': tax,
                'quantity': qty, 'observations': obs, 'total': total
            })
            idx += 1

        total_amount = sum(item['total'] for item in account_items)
        amount = total_amount * exchange_rate

        concept_value = account_items[0]['concept'] if account_items else request.form.get('notes', '')
        if not concept_value or not concept_value.strip():
            flash('El concepto del gasto es obligatorio.', 'error')
            return redirect(url_for('web_invoices.minor_new_route'))

        expense_dict = {
            'supplierType': 'informal',
            'concept': account_items[0]['concept'] if account_items else request.form.get('notes', 'Gasto Menor'),
            'category': request.form.get('category', 'Comida y Restaurantes'),
            'currency': currency,
            'exchangeRate': exchange_rate,
            'amountOriginal': total_amount,
            'amount': amount,
            'date': request.form['date'],
            'rncEmisor': '',
            'providerName': '',
            'ncf': '',
            'isMinorExpense': True,
            'isSyncedWithDGII': False,
            'notes': request.form.get('notes', ''),
            'isRecurring': False,
            'itbisAmountOriginal': 0.0,
            'itbisAmount': 0.0,
            'isITBISDeductible': True,
            'isDeductible': True,
            'ecfType': 'E43',
            'cne': '',
            'tipoGastoDGII': '06',
            'paymentType': 'Contado',
            'cxpStatus': 'Pagado',
            'cxpRemainingBalance': 0.0,
            'approvalStatus': 'Aprobado',
            'dueDate': request.form.get('date', ''),
            'bankAccountId': request.form.get('bankAccountId', ''),
            'accountItems': account_items,
            'expense_type': 'minor',
            'comentario': request.form.get('comentario', ''),
        }

        try:
            DatabaseService.save_expense(owner_uid, expense_id, expense_dict, sandbox=sandbox)
        except ValueError as ve:
            flash(str(ve), 'error')
            return redirect(url_for('web_invoices.minor_new_route'))

        try:
            from app.services.accounting_service import AccountingService
            AccountingService.auto_generate_expense_entry(owner_uid, expense_dict, sandbox=sandbox)
        except Exception as acc_err:
            print(f"Error al generar asiento contable del gasto menor: {acc_err}")

        try:
            ecf_short = 'E43'
            user_email = session['user']['email']
            encf, log_id = DatabaseService.consume_next_sequence(
                owner_uid, ecf_short, user_email, sandbox=sandbox
            )
            expense_dict['encf'] = encf
            expense_dict['ecfNumber'] = encf
            expense_dict['ncf'] = encf

            company = DatabaseService.get_company_profile(owner_uid)
            ecf_full_type = 'Gastos Menores (E43)'
            invoice_payload = _build_expense_ecf_payload(expense_dict, ecf_full_type)
            res = EcfEmissionService.emit_electronic_comprobante(
                company, invoice_payload, sandbox=sandbox
            )
            if res.get('success'):
                expense_dict['encf'] = res.get('encf', encf)
                expense_dict['ecfNumber'] = res.get('encf', encf)
                expense_dict['xmlSignature'] = res.get('xmlSignature', '')
                expense_dict['qrCodeURL'] = res.get('qrCodeURL', '')
                expense_dict['isSyncedWithDGII'] = (res.get('mode', 'API') == 'API')
                expense_dict['emisionMode'] = res.get('mode', 'API')
                expense_dict['trackId'] = res.get('trackId', '')
                DatabaseService.save_expense(owner_uid, expense_id, expense_dict, sandbox=sandbox)
                _update_expense_sequence_log(owner_uid, log_id, res, expense_dict, sandbox)
                flash(f'E43 emitido ante DGII: {expense_dict["encf"]}', 'success')
            else:
                flash(f'Gasto guardado, pero error al emitir E43: {res.get("message", "Error")}', 'warning')
        except Exception as e:
            print(f"Error al emitir E43 para gasto menor {expense_id}: {e}")
            flash(f'Gasto menor guardado. Error E43: {str(e)}', 'warning')

        bank_account_id = expense_dict.get('bankAccountId')
        if bank_account_id:
            try:
                bank_acc = DatabaseService.get_bank_account(owner_uid, bank_account_id, sandbox=sandbox)
                if bank_acc:
                    new_balance = bank_acc['currentBalance'] - amount
                    DatabaseService.save_bank_account(owner_uid, bank_account_id, {
                        **bank_acc, 'currentBalance': new_balance
                    }, sandbox=sandbox)
            except Exception as e:
                print(f"Error al actualizar saldo: {e}")

        return redirect(url_for('web_invoices.minor_list'))

    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    bank_accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox)
    accounting_accounts = DatabaseService.get_chart_of_accounts(owner_uid)
    tax_rules = DatabaseService.get_tax_rules(owner_uid)
    itbis_general = tax_rules.get('itbis', {}).get('general', 0.18)
    itbis_reduced = tax_rules.get('itbis', {}).get('reduced', 0.16)
    return render_template(
        'expenses/minor_new.html',
        active_page='expenses_minor',
        today_str=today_str,
        bank_accounts=bank_accounts,
        accounting_accounts=accounting_accounts,
        itbis_general=itbis_general,
        itbis_reduced=itbis_reduced
    )


# =========================================================================
# PAGOS RECURRENTES — Listado y Creación
# =========================================================================

@web_invoices_bp.route('/expenses/recurring')
def recurring_list():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Pagos Recurrentes", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    filtered = [e for e in expenses if e.get('isRecurring')]

    search_query = request.args.get('search', '').strip().lower()
    frequency_filter = request.args.get('frequency', '').strip()

    for exp in filtered[:]:
        if search_query:
            concept = exp.get('concept', '').lower()
            if search_query not in concept:
                filtered.remove(exp)
                continue
        if frequency_filter and exp.get('recurrenceInterval') != frequency_filter:
            filtered.remove(exp)
            continue

    total_items = len(filtered)
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    per_page_val = 20
    total_pages = max(1, (total_items + per_page_val - 1) // per_page_val)
    if page < 1: page = 1
    if page > total_pages: page = total_pages
    start_idx = (page - 1) * per_page_val
    paginated = filtered[start_idx:start_idx + per_page_val]
    start_count = ((page - 1) * per_page_val) + 1 if total_items > 0 else 0
    end_count = min(page * per_page_val, total_items)

    total_monthly = sum(e.get('amount', 0) for e in filtered if e.get('recurrenceInterval') == 'mensual')
    now = datetime.now(timezone.utc)
    upcoming = [e for e in filtered if e.get('nextOccurrenceDate') and e['nextOccurrenceDate'][:10] >= now.strftime('%Y-%m-%d')]
    next_due = min((e['nextOccurrenceDate'][:10] for e in upcoming), default=None)
    freq_summary = f"{sum(1 for e in filtered if e.get('recurrenceInterval')=='mensual')}M / {sum(1 for e in filtered if e.get('recurrenceInterval')=='semanal')}S"

    return render_template(
        'expenses/recurring_list.html',
        active_page='expenses_recurring',
        expenses=paginated,
        page=page, total_pages=total_pages, total_items=total_items,
        has_prev=page > 1, has_next=page < total_pages,
        start_count=start_count, end_count=end_count,
        search_query=search_query, frequency_filter=frequency_filter,
        total_monthly=total_monthly, next_due=next_due,
        upcoming_count=len(upcoming), frequency_summary=freq_summary
    )


@web_invoices_bp.route('/expenses/recurring/new', methods=['GET', 'POST'])
def recurring_new_route():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Nuevo Pago Recurrente", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    if request.method == 'POST':
        expense_id = str(uuid.uuid4())
        currency = request.form.get('currency', 'DOP')
        exchange_rate = float(request.form.get('exchangeRate', 1.0)) if currency != 'DOP' else 1.0

        concept_items = []
        idx = 0
        while True:
            concept = request.form.get(f'concept_items[{idx}][concept]')
            if concept is None:
                break
            concept_id = request.form.get(f'concept_items[{idx}][concept_id]', '')
            price = float(request.form.get(f'concept_items[{idx}][price]', 0) or 0)
            tax_raw = (request.form.get(f'concept_items[{idx}][tax]', 0) or 0)
            if str(tax_raw) == 'exento':
                tax = 0.0
            else:
                tax = float(tax_raw)
            qty = int(request.form.get(f'concept_items[{idx}][quantity]', 1) or 1)
            obs = request.form.get(f'concept_items[{idx}][observations]', '')
            total = float(request.form.get(f'concept_items[{idx}][total]', 0) or 0)
            concept_items.append({
                'concept': concept, 'concept_id': concept_id, 'price': price, 'tax': tax,
                'quantity': qty, 'observations': obs, 'total': total
            })
            idx += 1

        total_amount = sum(item['total'] for item in concept_items)
        amount = total_amount * exchange_rate
        tax_amount = sum(float(item['price']) * float(item['tax']) * int(item['quantity']) for item in concept_items)

        concept_value = concept_items[0]['concept'] if concept_items else ''
        if not concept_value or not concept_value.strip():
            flash('El concepto del gasto es obligatorio.', 'error')
            return redirect(url_for('web_invoices.recurring_new_route'))

        is_recurring = True
        recurrence_interval = request.form.get('recurrenceInterval', 'mensual')
        next_occurrence = request.form.get('nextOccurrenceDate')
        recurrence_end_date = request.form.get('recurrenceEndDate')

        expense_dict = {
            'expense_type': 'recurring',
            'concept': concept_items[0]['concept'] if concept_items else 'Pago Recurrente',
            'category': 'Otros Gastos',
            'currency': currency,
            'exchangeRate': exchange_rate,
            'amountOriginal': total_amount,
            'amount': amount,
            'date': request.form.get('nextOccurrenceDate', datetime.now(timezone.utc).strftime('%Y-%m-%d')),
            'rncEmisor': '',
            'providerName': '',
            'ncf': '',
            'isMinorExpense': False,
            'isSyncedWithDGII': False,
            'notes': '',
            'isRecurring': True,
            'recurrenceInterval': recurrence_interval,
            'nextOccurrenceDate': next_occurrence,
            'recurrenceEndDate': recurrence_end_date if recurrence_end_date else None,
            'itbisAmountOriginal': tax_amount,
            'itbisAmount': tax_amount * exchange_rate,
            'isITBISDeductible': True,
            'isDeductible': True,
            'ecfType': 'E31',
            'cne': '',
            'tipoGastoDGII': '02',
            'paymentType': 'Contado',
            'cxpStatus': 'Pagado',
            'cxpRemainingBalance': 0.0,
            'approvalStatus': 'Aprobado',
            'dueDate': next_occurrence,
            'bankAccountId': request.form.get('bankAccountId', ''),
            'conceptItems': concept_items,
            'accountItems': [{
                'concept': ci['concept'],
                'concept_id': ci.get('concept_id', ''),
                'value': ci['price'],
                'tax': ci['tax'],
                'quantity': ci['quantity'],
                'observations': ci.get('observations', ''),
                'total': ci['total'],
            } for ci in concept_items],
        }

        try:
            DatabaseService.save_expense(owner_uid, expense_id, expense_dict, sandbox=sandbox)
        except ValueError as ve:
            flash(str(ve), 'error')
            return redirect(url_for('web_invoices.recurring_new_route'))

        try:
            from app.services.accounting_service import AccountingService
            AccountingService.auto_generate_expense_entry(owner_uid, expense_dict, sandbox=sandbox)
        except Exception as acc_err:
            print(f"Error al generar asiento contable del pago recurrente: {acc_err}")

        flash('Pago recurrente programado exitosamente.', 'success')
        return redirect(url_for('web_invoices.recurring_list'))

    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    bank_accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox)
    accounting_accounts = DatabaseService.get_chart_of_accounts(owner_uid)
    tax_rules = DatabaseService.get_tax_rules(owner_uid)
    itbis_general = tax_rules.get('itbis', {}).get('general', 0.18)
    itbis_reduced = tax_rules.get('itbis', {}).get('reduced', 0.16)
    return render_template(
        'expenses/recurring_new.html',
        active_page='expenses_recurring',
        today_str=today_str,
        bank_accounts=bank_accounts,
        accounting_accounts=accounting_accounts,
        itbis_general=itbis_general,
        itbis_reduced=itbis_reduced
    )


@web_invoices_bp.route('/expenses/<expense_id>/delete', methods=['POST'])
def delete_expense_route(expense_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Eliminar Gasto", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    # Obtener el gasto antes de eliminarlo
    before_expense = {}
    try:
        expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
        before_expense = next((e for e in expenses if e['id'] == expense_id), {})
    except Exception:
        pass

    DatabaseService.delete_expense(owner_uid, expense_id, sandbox=sandbox)
    
    from app.services.audit_service import AuditService, ACTION_DELETE, MODULE_GASTOS
    AuditService.log_from_request(
        owner_uid=owner_uid,
        action=ACTION_DELETE,
        module=MODULE_GASTOS,
        entity_id=expense_id,
        entity_label=f"Gasto eliminado: {before_expense.get('concept', 'N/A')} (Monto: RD$ {before_expense.get('amount', 0.0):.2f})",
        user_session=session.get('user', {}),
        before=before_expense,
        sandbox=sandbox
    )
    flash('Gasto eliminado.', 'success')
    return redirect(url_for('web_invoices.list_expenses'))

@web_invoices_bp.route('/expenses/delete-multiple', methods=['POST'])
def delete_multiple_expenses_route():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Eliminar Gasto", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    expense_ids = request.form.getlist('expense_ids')
    if not expense_ids:
        flash('No se seleccionó ningún gasto para eliminar.', 'warning')
        return redirect(url_for('web_invoices.list_expenses'))

    from app.services.audit_service import AuditService, ACTION_DELETE, MODULE_GASTOS
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    deleted_count = 0

    for expense_id in expense_ids:
        before_expense = next((e for e in expenses if e['id'] == expense_id), {})
        if before_expense:
            DatabaseService.delete_expense(owner_uid, expense_id, sandbox=sandbox)
            AuditService.log_from_request(
                owner_uid=owner_uid,
                action=ACTION_DELETE,
                module=MODULE_GASTOS,
                entity_id=expense_id,
                entity_label=f"Gasto eliminado (Lote): {before_expense.get('concept', 'N/A')} (Monto: RD$ {before_expense.get('amount', 0.0):.2f})",
                user_session=session.get('user', {}),
                before=before_expense,
                sandbox=sandbox
            )
            deleted_count += 1
            
    flash(f'{deleted_count} gasto(s) eliminado(s) correctamente.', 'success')
    return redirect(url_for('web_invoices.list_expenses'))
@web_invoices_bp.route('/expenses/<expense_id>/edit', methods=['GET', 'POST'])
def edit_expense_route(expense_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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
        return redirect(url_for('web_invoices.list_expenses'))
        
    if request.method == 'POST':
        # Procesar MÚLTIPLES archivos nuevos (se agregan a los existentes)
        existing_attachments = expense.get('attachments', [])
        existing_urls = expense.get('firebaseAttachmentURLs', [])
        
        # Si no hay nuevo formato 'attachments' pero sí URLs antiguas, migrar retrocompat.
        if not existing_attachments and existing_urls:
            existing_attachments = [{'url': u, 'type': 'factura', 'name': u.split('/')[-1].split('?')[0]} for u in existing_urls]
        
        attachment_files = request.files.getlist('attachments[]')
        attachment_types = request.form.getlist('attachmentTypes[]')
        
        new_attachments = list(existing_attachments)
        new_attachment_urls = list(existing_urls)
        
        for i, att_file in enumerate(attachment_files):
            if att_file and att_file.filename:
                file_data = att_file.read()
                mime_type = att_file.content_type or "image/jpeg"
                safe_name = att_file.filename.replace(' ', '_')
                dest_path = f"users/{owner_uid}/expenses/{expense_id}/{safe_name}"
                try:
                    public_url = DatabaseService.upload_file_to_storage(file_data, dest_path, mime_type)
                    att_type = attachment_types[i] if i < len(attachment_types) else 'otro'
                    new_attachment_urls.append(public_url)
                    new_attachments.append({'url': public_url, 'type': att_type, 'name': att_file.filename})
                except Exception as e:
                    print(f"⚠️ Error al subir adjunto {att_file.filename}: {e}")
        
        attachment_urls = new_attachment_urls
        attachments = new_attachments

        currency = request.form.get('currency', 'DOP')
        exchange_rate = float(request.form.get('exchangeRate', 1.0)) if currency != 'DOP' else 1.0
        amount_original = float(request.form['amount'])
        amount = amount_original * exchange_rate
        
        is_recurring = request.form.get('isRecurring') == 'true'
        is_deductible = request.form.get('isDeductible') == 'true'
        recurrence_interval = request.form.get('recurrenceInterval', 'mensual')
        next_occurrence = request.form.get('nextOccurrenceDate')
        recurrence_end_date = request.form.get('recurrenceEndDate')
        
        payment_type = request.form.get('paymentType', 'Contado')
        due_date = request.form.get('dueDate', '')
        
        raw_itbis = request.form.get('itbisAmount', '').strip()
        itbis_amount_original = float(raw_itbis) if raw_itbis else (amount_original * 0.18 / 1.18)
        
        cxp_status = expense.get('cxpStatus', 'Pagado')
        if payment_type == 'Crédito' and cxp_status == 'Pagado':
            cxp_status = 'Pendiente'
        elif payment_type == 'Contado':
            cxp_status = 'Pagado'
            
        current_rem = float(expense.get('cxpRemainingBalance', expense.get('amount', 0.0)))
        if payment_type == 'Contado':
            rem_bal = 0.0
        else:
            if amount != expense.get('amount', 0.0):
                rem_bal = amount
            else:
                rem_bal = current_rem

        assigned_approver_id = request.form.get('assignedApproverId', '')
        assigned_approver_name = expense.get('assignedApproverName', '')
        assigned_approver_email = expense.get('assignedApproverEmail', '')
        if assigned_approver_id:
            _team_members = DatabaseService.get_team_members(owner_uid)
            _owner_profile = DatabaseService.get_user_profile(owner_uid)
            if _owner_profile and not any(m.get('uid') == owner_uid for m in _team_members):
                _team_members.insert(0, {
                    "uid": _owner_profile.get("uid"),
                    "name": f"{_owner_profile.get('name', 'Usuario Principal')} (Tú)",
                    "email": _owner_profile.get("email", "")
                })
            for m in _team_members:
                if m.get('uid') == assigned_approver_id:
                    assigned_approver_name = m.get('name', '')
                    assigned_approver_email = m.get('email', '')
                    break

        concept = request.form.get('concept', '').strip()
        if not concept:
            flash('El concepto del gasto es obligatorio.', 'error')
            return redirect(url_for('web_invoices.edit_expense_route', expense_id=expense_id))

        expense_dict = {
            "supplierType": request.form.get('supplierType', expense.get('supplierType', 'formal')),
            "concept": concept,
            "category": request.form['category'],
            "currency": currency,
            "exchangeRate": exchange_rate,
            "amountOriginal": amount_original,
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
            "itbisAmountOriginal": itbis_amount_original,
            "itbisAmount": itbis_amount_original * exchange_rate,
            "isITBISDeductible": is_deductible,
            "isDeductible": is_deductible,
            "firebaseAttachmentURLs": attachment_urls,
            "attachments": attachments,
            "ecfType": request.form.get('ecfType', 'E31'),
            "ecfNumber": request.form.get('ncf', ''),
            "cne": request.form.get('cne', ''),
            "tipoGastoDGII": request.form.get('tipoGastoDGII', '02'),
            "paymentType": payment_type,
            "cxpStatus": cxp_status,
            "cxpRemainingBalance": rem_bal,
            "approvalStatus": request.form.get('approvalStatus', 'Aprobado'),
            "assignedApproverId": assigned_approver_id,
            "assignedApproverName": assigned_approver_name,
            "assignedApproverEmail": assigned_approver_email,
            "requestedBy": expense.get('requestedBy', session['user'].get('name', 'Usuario')),
            "approvedBy": session['user'].get('name', 'Usuario') if request.form.get('approvalStatus', 'Aprobado') == 'Aprobado' else '',
            "dueDate": due_date,
            "createdAt": expense.get('createdAt'),
            "bankAccountId": request.form.get('bankAccountId', expense.get('bankAccountId', ''))
        }
        
        try:
            DatabaseService.save_expense(owner_uid, expense_id, expense_dict, sandbox=sandbox)
        except ValueError as ve:
            flash(str(ve), 'error')
            return redirect(url_for('web_invoices.edit_expense_route', expense_id=expense_id))

        try:
            from app.services.accounting_service import AccountingService, _accounting_entry_exists
            all_entries = DatabaseService.get_accounting_entries(owner_uid, sandbox=sandbox)
            for e in all_entries:
                if e.get("status") != "voided" and e.get("referenceType") == "expense" and e.get("referenceId") == expense_id:
                    AccountingService.void_entry(owner_uid, e["id"], reason="Regenerado por edición", user_id=session['user']['email'], sandbox=sandbox)
                    break
            AccountingService.auto_generate_expense_entry(owner_uid, expense_dict, sandbox=sandbox)
        except Exception as acc_err:
            print(f"Error al regenerar asiento contable en edición: {acc_err}")

        # === EMISIÓN e-CF PARA E41/E43 AL EDITAR ===
        # Solo si el gasto aún NO tiene un e-NCF asignado (no re-emisión de documentos ya enviados a la DGII).
        ecf_type_raw_edit = expense_dict.get("ecfType", "")
        already_emitted   = bool(expense_dict.get("encf") and expense_dict.get("isSyncedWithDGII"))
        should_emit_ecf_edit = (
            not already_emitted
            and ecf_type_raw_edit in ("E41", "E43",
                                      "Comprobante de Compras (E41)",
                                      "Gastos Menores (E43)")
        )
        ecf_edit_msg = None
        if should_emit_ecf_edit:
            try:
                ecf_short_edit    = "E41" if "E41" in ecf_type_raw_edit else "E43"
                ecf_full_edit     = "Comprobante de Compras (E41)" if ecf_short_edit == "E41" else "Gastos Menores (E43)"
                user_email_edit   = session['user']['email']

                exceeded_edit, limit_msg_edit = check_document_limit_exceeded(owner_uid, sandbox=sandbox)
                if exceeded_edit:
                    ecf_edit_msg = ("warning", limit_msg_edit)
                else:
                    if limit_msg_edit:
                        flash(limit_msg_edit, 'warning')

                    encf_edit, log_id_edit = DatabaseService.consume_next_sequence(
                        owner_uid, ecf_short_edit, user_email_edit, sandbox=sandbox
                    )
                    expense_dict["encf"]      = encf_edit
                    expense_dict["ecfNumber"] = encf_edit
                    expense_dict["ncf"]       = encf_edit

                    company_edit   = DatabaseService.get_company_profile(owner_uid)
                    inv_payload_ed = _build_expense_ecf_payload(expense_dict, ecf_full_edit)
                    res_edit = EcfEmissionService.emit_electronic_comprobante(
                        company_edit, inv_payload_ed, sandbox=sandbox
                    )

                    if res_edit.get("success"):
                        expense_dict["encf"]             = res_edit.get("encf", encf_edit)
                        expense_dict["ecfNumber"]        = res_edit.get("encf", encf_edit)
                        expense_dict["xmlSignature"]     = res_edit.get("xmlSignature", "")
                        expense_dict["qrCodeURL"]        = res_edit.get("qrCodeURL", "")
                        pending_dgii = res_edit.get("status") == "PENDING"
                        expense_dict["isSyncedWithDGII"] = (res_edit.get("mode", "API") == "API" and not pending_dgii)
                        expense_dict["emisionMode"]      = res_edit.get("mode", "API")
                        expense_dict["trackId"]          = res_edit.get("trackId", "")
                        expense_dict["dgiiStatus"]        = res_edit.get("dgiiStatus") or ("CONTINGENCY" if res_edit.get("mode") == "FALLBACK" else ("PENDING" if pending_dgii else "ACCEPTED"))
                        try:
                            from app.services.dgii_xml_builder import DgiiXmlBuilder
                            from app.services.dgii_signer import DgiiSigner
                            raw_xml = DgiiXmlBuilder.build_invoice_xml(company_edit, inv_payload_ed)
                            signed_xml_bytes = DgiiSigner.sign_xml(raw_xml, company_edit)
                            expense_dict["xmlContent"] = signed_xml_bytes.decode('utf-8')
                        except Exception as xml_err:
                            print(f"⚠️ Error al generar XML para gasto {expense_id}: {xml_err}")
                        DatabaseService.save_expense(owner_uid, expense_id, expense_dict, sandbox=sandbox)
                        _update_expense_sequence_log(owner_uid, log_id_edit, res_edit, expense_dict, sandbox)

                        if res_edit.get("mode") == "FALLBACK":
                            ecf_edit_msg = ("warning",
                                f"⚠️ e-CF emitido en contingencia. e-NCF: {expense_dict['encf']}. Sincronizar en máximo 72h.")
                        else:
                            ecf_edit_msg = ("success",
                                f"✅ Gasto actualizado y {ecf_short_edit} emitido ante la DGII. e-NCF: {expense_dict['encf']}")
                    else:
                        ecf_edit_msg = ("warning",
                            f"Gasto actualizado, pero error al emitir e-CF: {res_edit.get('message', 'Error desconocido')}")

            except Exception as e:
                print(f"❌ Error al emitir e-CF en edición de gasto {expense_id}: {e}")
                ecf_edit_msg = ("error",
                    f"Gasto actualizado, pero fallo en la emisión del e-CF: {str(e)}")

        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_GASTOS
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_UPDATE,
            module=MODULE_GASTOS,
            entity_id=expense_id,
            entity_label=f"Gasto modificado: {expense_dict['concept']} (Monto: RD$ {amount:.2f})",
            user_session=session.get('user', {}),
            before=expense,
            after=expense_dict,
            sandbox=sandbox
        )

        if ecf_edit_msg:
            flash(ecf_edit_msg[1], ecf_edit_msg[0])
        else:
            flash('Gasto operativo actualizado exitosamente.', 'success')
        return redirect(url_for('web_invoices.list_expenses'))
         
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    bank_accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox)
    accounting_accounts = DatabaseService.get_chart_of_accounts(owner_uid)
    tax_rules = DatabaseService.get_tax_rules(owner_uid)
    itbis_general = tax_rules.get('itbis', {}).get('general', 0.18)
    itbis_reduced = tax_rules.get('itbis', {}).get('reduced', 0.16)

    common_vars = {
        'active_page': 'expenses',
        'mode': 'edit',
        'expense': expense,
        'bank_accounts': bank_accounts,
        'accounting_accounts': accounting_accounts,
        'itbis_general': itbis_general,
        'itbis_reduced': itbis_reduced,
        'today_str': today_str,
    }

    if expense.get('isMinorExpense'):
        return render_template('expenses/minor_new.html', **common_vars)
    elif expense.get('isRecurring'):
        return render_template('expenses/recurring_new.html', **common_vars)
    else:
        return render_template('expenses/payments_new.html', **common_vars)

@web_invoices_bp.route('/expenses/<expense_id>/sync', methods=['POST'])
def sync_expense_ecf_route(expense_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Sincronizar e-CF Gasto", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    expense = DatabaseService.get_expense(owner_uid, expense_id, sandbox=sandbox)
    if not expense:
        flash('Gasto no encontrado.', 'error')
        return redirect(url_for('web_invoices.list_expenses'))

    ecf_type_raw = expense.get("ecfType", "")
    if ecf_type_raw not in ("E41", "E43", "Comprobante de Compras (E41)", "Gastos Menores (E43)"):
        flash('Solo los gastos E41 y E43 pueden sincronizarse con la DGII.', 'warning')
        return redirect(url_for('web_invoices.expense_detail', expense_id=expense_id))

    ecf_short = "E41" if "E41" in ecf_type_raw else "E43"
    ecf_full_type = "Comprobante de Compras (E41)" if ecf_short == "E41" else "Gastos Menores (E43)"
    company = DatabaseService.get_company_profile(owner_uid)

    try:
        invoice_payload = _build_expense_ecf_payload(expense, ecf_full_type)
        res = EcfEmissionService.emit_electronic_comprobante(company, invoice_payload, sandbox=sandbox)

        if res.get("success") and res.get("mode", "API") == "API":
            pending_dgii = res.get("status") == "PENDING"
            expense["isSyncedWithDGII"] = not pending_dgii
            expense["emisionMode"] = "API"
            expense["dgiiStatus"] = res.get("dgiiStatus") or ("PENDING" if pending_dgii else "ACCEPTED")
            expense["xmlSignature"] = res.get("xmlSignature", expense.get("xmlSignature", ""))
            expense["qrCodeURL"] = res.get("qrCodeURL", expense.get("qrCodeURL", ""))
            expense["encf"] = res.get("encf", expense.get("encf", ""))
            try:
                from app.services.dgii_xml_builder import DgiiXmlBuilder
                from app.services.dgii_signer import DgiiSigner
                raw_xml = DgiiXmlBuilder.build_invoice_xml(company, invoice_payload)
                signed_xml_bytes = DgiiSigner.sign_xml(raw_xml, company)
                expense["xmlContent"] = signed_xml_bytes.decode('utf-8')
            except Exception as xml_err:
                print(f"⚠️ Error al generar XML en sync de gasto {expense_id}: {xml_err}")
            DatabaseService.save_expense(owner_uid, expense_id, expense, sandbox=sandbox)

            logs = DatabaseService.get_sequence_logs(owner_uid, sandbox=sandbox)
            log = next((l for l in logs if l.get("encf") == expense.get("encf")), None)
            if log:
                items = expense.get("items") or [{
                    "subtotal": expense.get("amount", 0.0),
                    "itbisAmount": expense.get("itbisAmount", 0.0)
                }]
                cuadratura = DGIIService.check_tolerancia_cuadratura(items, expense.get("amount", 0.0))
                estado_dgii = "ACCEPTED" if cuadratura["within_tolerance"] else "ACCEPTED_CONDITIONAL"
                if pending_dgii:
                    estado_dgii = "PENDING"
                DatabaseService.update_sequence_log(owner_uid, log["id"], {
                    "estado": estado_dgii,
                    "motivo": f"Regularizado por Sincronización Manual. Firma: {res['xmlSignature'][:12] if res.get('xmlSignature') else 'N/A'}",
                    "xmlEnviado": json.dumps(res.get("requestPayload"), indent=2) if res.get("requestPayload") else "",
                    "respuestaDGII": json.dumps(res.get("responseBody"), indent=2) if res.get("responseBody") else ""
                }, sandbox=sandbox)

            if pending_dgii:
                flash(f"Gasto {ecf_short} enviado a la DGII y pendiente de validación. e-NCF: {expense.get('encf')}", 'warning')
            else:
                flash(f"Gasto {ecf_short} sincronizado con la DGII exitosamente! e-NCF: {expense.get('encf')}", 'success')
        else:
            flash(f"No se pudo sincronizar: {res.get('message') or 'Sigue en modalidad de contingencia (sin conexión a DGII).'}", 'warning')
    except Exception as e:
        flash(f"Error durante la sincronización: {str(e)}", 'error')

    return redirect(url_for('web_invoices.expense_detail', expense_id=expense_id))

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


@web_invoices_bp.route('/expenses/<expense_id>/approve', methods=['POST'])
def approve_expense_route(expense_id):
    if 'user' not in session: return jsonify({'success': False, 'message': 'No autenticado'}), 401
    # Asume que si puede ver/gestionar gastos puede aprobar, ideal sería un permiso específico
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    expense = next((e for e in expenses if e['id'] == expense_id), None)
    
    if not expense:
        return jsonify({'success': False, 'message': 'Gasto no encontrado'})
        
    expense['approvalStatus'] = 'Aprobado'
    expense['approvedBy'] = session['user'].get('name', 'Usuario')
    
    DatabaseService.save_expense(owner_uid, expense_id, expense, sandbox=sandbox)
    if True:
        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_GASTOS
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_UPDATE,
            module=MODULE_GASTOS,
            description=f"Se aprobó rápidamente el gasto {expense.get('concept', '')}"
        )
        return jsonify({'success': True, 'message': 'Gasto aprobado correctamente'})
    return jsonify({'success': False, 'message': msg})

@web_invoices_bp.route('/expenses/cxp')
def list_cxp():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageCXP'):
        return render_template('auth/restricted.html', feature_name="Cuentas por Pagar (CxP)", required_permission="canManageCXP")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    
    cxp_list = []
    total_cxp_pending = 0.0
    total_cxp_vencido = 0.0
    
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    for exp in expenses:
        if exp.get('approvalStatus') == 'Pendiente':
            continue
            
        if exp.get('paymentType') == 'Crédito':
            due_date = exp.get('dueDate', '')
            status = exp.get('cxpStatus', 'Pendiente')
            rem_bal = float(exp.get('cxpRemainingBalance', exp.get('amount', 0.0)))
            exp['cxpRemainingBalance'] = rem_bal
            
            if status in ['Pendiente', 'Abonado'] and due_date and due_date < today_str:
                status = 'Vencido'
                exp['cxpStatus'] = 'Vencido'
                
            cxp_list.append(exp)
            
            if status in ['Pendiente', 'Abonado', 'Vencido']:
                total_cxp_pending += rem_bal
                if status == 'Vencido' or (due_date and due_date < today_str):
                    total_cxp_vencido += rem_bal

    # Aplicar Filtros
    status_filter = request.args.get('status', '').strip()
    search_query = request.args.get('search', '').strip().lower()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()

    filtered_cxp = []
    for exp in cxp_list:
        status = exp.get('cxpStatus', 'Pendiente')
        due_date = exp.get('dueDate', '')
        
        if status_filter and status != status_filter:
            continue
            
        if search_query:
            concept = exp.get('concept', '').lower()
            ncf = exp.get('ncf', '').lower()
            rnc = exp.get('rncEmisor', '').lower()
            provider = exp.get('providerName', '').lower()
            if search_query not in concept and search_query not in ncf and search_query not in rnc and search_query not in provider:
                continue
                
        if start_date and due_date < start_date:
            continue
        if end_date and due_date > end_date:
            continue
            
        filtered_cxp.append(exp)

    # Exportar a CSV si se solicita
    if request.args.get('export') == 'csv':
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["Proveedor", "RNC Proveedor", "NCF", "Concepto", "Fecha Emisión", "Fecha Vencimiento", "Estatus", "Monto Total (RD$)", "Balance Pendiente (RD$)"])
        for exp in filtered_cxp:
            writer.writerow([
                exp.get("providerName", "N/A"),
                exp.get("rncEmisor", ""),
                exp.get("ncf", ""),
                exp.get("concept", ""),
                exp.get("date", "")[:10],
                exp.get("dueDate", ""),
                exp.get("cxpStatus", "Pendiente"),
                f"{exp.get('amount', 0.0):.2f}",
                f"{exp.get('cxpRemainingBalance', exp.get('amount', 0.0)):.2f}"
            ])
            
        dest = io.BytesIO()
        dest.write(b'\xef\xbb\xbf')  # UTF-8 BOM
        dest.write(output.getvalue().encode('utf-8'))
        dest.seek(0)
        
        filename = f"cuentas_por_pagar_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(
            dest,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )
                    
    return render_template(
        'expenses/cxp.html',
        active_page='expenses_cxp',
        cxp_list=filtered_cxp,
        total_cxp_pending=total_cxp_pending,
        total_cxp_vencido=total_cxp_vencido,
        today_str=today_str,
        status_filter=status_filter,
        search_query=search_query,
        start_date=start_date,
        end_date=end_date
    )

@web_invoices_bp.route('/expenses/cxp/<expense_id>/pay', methods=['POST'])
def pay_cxp_route(expense_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canModifySettings'):
        return render_template('auth/restricted.html', feature_name="Secuencias Fiscales", required_permission="canModifySettings")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    sequences = DatabaseService.get_sequences(owner_uid, sandbox=sandbox)
    sequence_logs = DatabaseService.get_sequence_logs(owner_uid, sandbox=sandbox)
    cancellations = DatabaseService.get_cancellations(owner_uid, sandbox=sandbox)
    
    default_exp_date = (datetime.now(timezone.utc) + timedelta(days=730)).strftime("%Y-%m-%d") # 2 años
    
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
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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
        "fechaAutorizacion": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "fechaExpiracion": request.form['fechaExpiracion'],
        "numeroAutorizacionDgii": request.form['numeroAutorizacionDgii'],
        "estado": "ACTIVA",
        "ambiente": "SANDBOX" if sandbox else "PRODUCCION",
        "bloqueadaManualmente": False
    }
    
    DatabaseService.save_sequence(owner_uid, seq_id, seq_dict, sandbox=sandbox)
    flash('Secuencia fiscal autorizada por la DGII registrada con éxito.', 'success')
    return redirect(url_for('web_invoices.list_sequences'))

@web_invoices_bp.route('/cancellations/new', methods=['POST'])
def new_cancellation_route():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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
        
    return redirect(url_for('web_invoices.list_sequences'))

# =========================================================================
# CONFIGURACIÓN DE EMPRESA Y EQUIPO
# =========================================================================

@web_invoices_bp.route('/settings/taxes', methods=['GET', 'POST'])
def tax_settings():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canModifySettings'):
        return render_template('auth/restricted.html', feature_name="Configuración de Impuestos",
                               required_permission="canModifySettings")
    owner_uid = session['user']['ownerUID']
    rules = DatabaseService.get_tax_rules(owner_uid)
    config_updated = False

    if request.method == 'POST':
        action = request.form.get('action', 'save')
        if action == 'reset':
            from app.services.tax_engine import DEFAULT_TAX_RULES
            import copy
            rules = copy.deepcopy(DEFAULT_TAX_RULES)
            rules["updatedBy"] = session.get("user", {}).get("email", "")
            success, error_msg = DatabaseService.save_tax_rules(owner_uid, rules)
            if not success:
                flash(f"Error al restaurar: {error_msg}", "error")
            else:
                config_updated = True
        else:
            # ISC rates
            isc = {}
            for codigo, key in [("001", "codigo_001_propina_legal"), ("002", "codigo_002_cdt"),
                                 ("003", "codigo_003_isc_seguros"), ("004", "codigo_004_telecomunicaciones"),
                                 ("005", "codigo_005_primera_placa")]:
                val = request.form.get(f"isc_{codigo}", "")
                if val:
                    isc[key] = float(val) / 100.0

            # RST brackets
            rst_brackets = []
            for i in range(4):
                rate = request.form.get(f"rst_rate_{i}", "")
                fixed = request.form.get(f"rst_fixed_{i}", "")
                if i < 3:
                    limit = request.form.get(f"rst_limit_{i}", "")
                    if limit and rate:
                        rst_brackets.append([float(limit), float(rate) / 100.0, float(fixed or 0)])
                else:
                    if rate:
                        rst_brackets.append([999999999.0, float(rate) / 100.0, float(fixed or 0)])

            rules = {
                "country": request.form.get("country", "RD"),
                "itbis": {
                    "general": float(request.form.get("itbis_general", 0) or 0) / 100.0,
                    "reduced": float(request.form.get("itbis_reduced", 0) or 0) / 100.0,
                },
                "isc": isc,
                "isr_corporate": {
                    "general": float(request.form.get("isr_corporate", 0) or 0) / 100.0,
                    "large_taxpayer": float(request.form.get("isr_large_taxpayer", 0) or 0) / 100.0,
                },
                "withholding_isr": {
                    "goods_services": float(request.form.get("w_isr_goods", 0) or 0) / 100.0,
                    "professional_fees": float(request.form.get("w_isr_professional", 0) or 0) / 100.0,
                    "digital_services_abroad": float(request.form.get("w_isr_digital", 0) or 0) / 100.0,
                },
                "withholding_itbis": {
                    "corporate_goods": float(request.form.get("w_itbis_corp", 0) or 0) / 100.0,
                    "legal_services": float(request.form.get("w_itbis_legal", 0) or 0) / 100.0,
                    "independent_professionals": float(request.form.get("w_itbis_indep", 0) or 0) / 100.0,
                },
                "rst": {
                    "limit": float(request.form.get("rst_annual_limit", 0) or 0),
                    "brackets": rst_brackets,
                },
                "updatedBy": session.get("user", {}).get("email", ""),
            }
            success, error_msg = DatabaseService.save_tax_rules(owner_uid, rules)
            print(f"🔧 tax_settings SAVE: success={success}, error={error_msg}")
            print(f"   rst_annual={rules.get('rst', {}).get('limit')}, brackets_len={len(rules.get('rst', {}).get('brackets', []))}")
            print(f"   rst brackets={rules.get('rst', {}).get('brackets')}")
            if not success:
                flash(f"Error al guardar: {error_msg}", "error")
            else:
                config_updated = True

    rules = DatabaseService.get_tax_rules(owner_uid)
    print(f"🔧 tax_settings READ: withholding_isr={rules.get('withholding_isr')}")
    return render_template('settings/taxes.html', active_page='settings',
                           rules=rules, config_updated=config_updated)


@web_invoices_bp.route('/settings/company', methods=['GET', 'POST'])
def company_settings():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canModifySettings'):
        return render_template('auth/restricted.html', feature_name="Configuración de la Empresa", required_permission="canModifySettings")
    owner_uid = session['user']['ownerUID']
    
    if request.method == 'POST':
        # Preservar logoUrl y configuraciones de marca existentes
        existing_profile = DatabaseService.get_company_profile(owner_uid)

        # ── Validar cambios en RNC, Razón Social o Nombre Comercial si ya hay documentos emitidos ──
        new_rnc = request.form.get('companyRNC', '').strip()
        new_name = request.form.get('companyName', '').strip()
        new_trade = request.form.get('tradeName', '').strip()
        old_rnc = (existing_profile.get('companyRNC') or '').strip()
        old_name = (existing_profile.get('companyName') or '').strip()
        old_trade = (existing_profile.get('tradeName') or '').strip()
        if (new_rnc != old_rnc or new_name != old_name or new_trade != old_trade) and _company_has_issued_documents(owner_uid, sandbox=session.get('is_sandbox_mode', True)):
            flash(
                'No es posible modificar el RNC ni la Razón Social porque la empresa ya tiene documentos '
                'fiscales emitidos. Para realizar este cambio, contacta al administrador del portal '
                'para un proceso de migración controlada con auditoría.',
                'error'
            )
            return redirect(url_for('web_invoices.company_settings'))
        
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

        profile_dict = dict(existing_profile or {})
        profile_dict.update({
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
            "regimenFiscal": DGIIService.normalize_regimen(request.form.get('regimenFiscal', 'General')),
            "openaiApiKey": request.form.get('openaiApiKey', ''),

            "theme": request.form.get('theme', existing_profile.get('theme', 'moderno')),
            "azulMerchantId": request.form.get('azulMerchantId', '').strip(),
            "azulAuth1": request.form.get('azulAuth1', '').strip(),
            "azulAuth2": request.form.get('azulAuth2', '').strip(),
            "consolidationEnabled": request.form.get('consolidationEnabled') == 'true',
            "consolidationThreshold": float(request.form.get('consolidationThreshold') or 250000.0),
            "posToleranceDOP": float(request.form.get('posToleranceDOP') or 0.0),
            "posToleranceUSD": float(request.form.get('posToleranceUSD') or 0.0),
            "configured": True
        })
        saved = DatabaseService.save_company_profile(owner_uid, profile_dict)
        if saved:
            # Refrescar empresas asociadas en sesión para reflejar nombre actualizado en sidebar
            session['associated_companies'] = DatabaseService.get_associated_companies(session['user']['uid'])
            flash('Ajustes y perfil de empresa actualizados correctamente.', 'success')
        else:
            flash('Error al guardar el perfil. Verifica que los datos no excedan el tamaño permitido.', 'error')
            return redirect(url_for('web_invoices.company_settings'))

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
                
            return redirect(url_for('web_invoices.company_settings', onboarding_success='true'))

        return redirect(url_for('web_invoices.company_settings'))
        
    profile = DatabaseService.get_company_profile(owner_uid)

    # Obtener sucursales
    branches = DatabaseService.get_branches(owner_uid, sandbox=session.get('is_sandbox_mode', True))

    onboarding_success = request.args.get('onboarding_success') == 'true'
    show_wizard = False
    has_issued_documents = _company_has_issued_documents(owner_uid, sandbox=session.get('is_sandbox_mode', True))
    return render_template('company_settings.html', active_page='settings', profile=profile, branches=branches, show_wizard=show_wizard, onboarding_success=onboarding_success, has_issued_documents=has_issued_documents, e_cf_provider=Config.E_CF_PROVIDER.lower())

@web_invoices_bp.route('/onboarding', methods=['GET', 'POST'])
def onboarding_wizard():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    
    if request.method == 'POST':
        existing_profile = DatabaseService.get_company_profile(owner_uid) or {}
        
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

        profile_dict = dict(existing_profile)
        regimen_normalized = DGIIService.normalize_regimen(request.form.get('regimenFiscal', 'ordinary'))
        use_simulation = request.form.get('useSimulation') == 'true'

        # Defaults inteligentes según régimen fiscal
        if regimen_normalized in ('rst_income', 'rst_purchases'):
            defaults = {"defaultEcfType": "Factura de Consumo (E32)", "defaultItbisRate": 0.0}
        elif regimen_normalized == 'ordinary':
            defaults = {"defaultEcfType": "Factura de Crédito Fiscal (E31)", "defaultItbisRate": 0.18}
        elif regimen_normalized == 'exempt':
            defaults = {"defaultEcfType": "Factura de Consumo (E32)", "defaultItbisRate": 0.0}
        else:
            defaults = {"defaultEcfType": "Factura de Consumo (E32)", "defaultItbisRate": 0.18}

        profile_dict.update({
            "companyName": request.form['companyName'],
            "companyRNC": request.form['companyRNC'],
            "companyAddress": request.form.get('companyAddress', ''),
            "companyPhone": request.form.get('companyPhone', ''),
            "companyEmail": request.form.get('companyEmail', ''),
            "tradeName": request.form.get('tradeName', ''),
            "companyType": "associated",
            "province": request.form.get('province', ''),
            "municipality": request.form.get('municipality', ''),
            "certificateName": cert_name if not use_simulation else '',
            "certificateExtension": cert_ext if not use_simulation else '',
            "certificateContent": cert_content if not use_simulation else '',
            "certificatePassword": cert_password if not use_simulation else '',
            "regimenFiscal": regimen_normalized,
            "consolidationEnabled": request.form.get('consolidationEnabled') == 'true',
            "consolidationThreshold": float(request.form.get('consolidationThreshold') or 250000.0),
            "contribuyenteTipo": request.form.get('contribuyenteTipo', 'empresa'),
            "useSimulation": use_simulation,
            "configured": True,
            **defaults
        })
        
        saved = DatabaseService.save_company_profile(owner_uid, profile_dict)
        if not saved:
            flash('Error al guardar el perfil durante el onboarding. Intenta de nuevo.', 'error')
            return redirect(url_for('web_invoices.onboarding_wizard'))
        flash('¡Onboarding completado con éxito!', 'success')
        return redirect(url_for('web_dashboard.dashboard'))

    profile = DatabaseService.get_company_profile(owner_uid)
    return render_template('onboarding_wizard.html', profile=profile)

@web_invoices_bp.route('/settings/company/generate-api-key', methods=['POST'])
def generate_company_api_key():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canModifySettings'):
        return render_template('auth/restricted.html', feature_name="Configuración de la Empresa", required_permission="canModifySettings")
    
    owner_uid = session['user']['ownerUID']
    new_key = DatabaseService.generate_api_key(owner_uid)
    if new_key:
        flash('¡Nueva API Key generada con éxito!', 'success')
    else:
        flash('Ocurrió un error al generar la API Key.', 'error')
    return redirect(url_for('web_invoices.company_settings'))

@web_invoices_bp.route('/settings/company/brand', methods=['POST'])
def save_company_brand_settings():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
    if not check_permission('canModifySettings'): return jsonify({"error": "No autorizado"}), 403

    try:
        owner_uid = session['user']['ownerUID']
        existing_profile = DatabaseService.get_company_profile(owner_uid)
        if not existing_profile:
            return jsonify({"success": False, "error": "Perfil de empresa no encontrado."}), 404

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
            b64 = base64.b64encode(file_data).decode('utf-8')
            if len(b64) < 800000:
                existing_profile['logoBase64'] = b64
            else:
                existing_profile['logoBase64'] = ''
            
        if request.form.get('removeLogo') == 'true':
            existing_profile['logoUrl'] = ''
            existing_profile['logoBase64'] = ''
            
        saved = DatabaseService.save_company_profile(owner_uid, existing_profile)
        if not saved:
            return jsonify({"success": False, "error": "No se pudo guardar el perfil. Verifica el tamaño del archivo o intenta de nuevo."}), 500

        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_EMPRESA
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_UPDATE,
            module=MODULE_EMPRESA,
            entity_id=owner_uid,
            entity_label="Configuración de apariencia y marca de empresa actualizada",
            user_session=session.get('user', {}),
            after=existing_profile,
            sandbox=True
        )
        return jsonify({"success": True, "profile": existing_profile})
    except Exception as e:
        print(f"❌ Error en save_company_brand_settings: {e}")
        return jsonify({"success": False, "error": f"Error interno: {str(e)[:200]}"}), 500

@web_invoices_bp.route('/settings/team', methods=['GET'])
def team_settings():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if session['user'].get('role') != 'owner':
        flash('No tienes permisos de propietario.', 'error')
        return redirect(url_for('web_dashboard.dashboard'))
    owner_uid = session['user']['ownerUID']
    team = DatabaseService.get_team_members(owner_uid)
    return render_template('team_settings.html', active_page='team_settings', team=team)

@web_invoices_bp.route('/settings/team/new', methods=['POST'])
def add_team_member():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if session['user'].get('role') != 'owner':
        flash('No tienes permisos de propietario.', 'error')
        return redirect(url_for('web_invoices.team_settings'))
    
    owner_uid = session['user']['ownerUID']
    
    profile = DatabaseService.get_company_profile(owner_uid)
    user_limit = int(profile.get('userLimit', 2)) if profile else 2
    team = DatabaseService.get_team_members(owner_uid)
    if user_limit > 0 and (len(team) + 1) >= user_limit:
        flash(f'Límite de usuarios alcanzado ({user_limit} usuarios en tu plan). Por favor, actualiza tu plan para registrar nuevos colaboradores.', 'error')
        return redirect(url_for('web_invoices.team_settings'))
    
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
        "canViewBI": 'canViewBI' in request.form,
        "canViewAuditLog": 'canViewAuditLog' in request.form,
        "canAccounting": 'canAccounting' in request.form,
        "isPosSupervisor": 'isPosSupervisor' in request.form,
        "canViewSubscription": 'canViewSubscription' in request.form,
        "canToggleSandbox": 'canToggleSandbox' in request.form,
        "canManageNotes": 'canManageNotes' in request.form,
        "canManageSuppliers": 'canManageSuppliers' in request.form,
        "canManagePurchaseCXP": 'canManagePurchaseCXP' in request.form,
        "canUseChatbot": 'canUseChatbot' in request.form
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
        
        from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_USUARIOS
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_CREATE,
            module=MODULE_USUARIOS,
            entity_id=profile['uid'],
            entity_label=f"Nuevo colaborador registrado: {name} ({email})",
            user_session=session.get('user', {}),
            after={"uid": profile['uid'], "name": name, "email": email, "permissions": permissions},
            sandbox=True
        )
        flash(f'Colaborador {name} registrado y vinculado exitosamente.', 'success')
    except Exception as e:
        flash(f'Error al registrar colaborador: {str(e)}', 'error')
        
    return redirect(url_for('web_invoices.team_settings'))

@web_invoices_bp.route('/settings/branches/save', methods=['POST'])
def save_branch_route():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canModifySettings'):
        flash('No tienes permisos.', 'error')
        return redirect(url_for('web_invoices.company_settings'))
    
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
    return redirect(url_for('web_invoices.company_settings'))

@web_invoices_bp.route('/settings/branches/<branch_id>/delete', methods=['POST'])
def delete_branch_route(branch_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canModifySettings'):
        flash('No tienes permisos.', 'error')
        return redirect(url_for('web_invoices.company_settings'))
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    # Prevenir eliminar la sucursal predeterminada si es la unica, o si isDefault
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
    branch = next((b for b in branches if b['id'] == branch_id), None)
    if not branch:
        flash("Sucursal no encontrada.", 'error')
        return redirect(url_for('web_invoices.company_settings'))
        
    if branch.get('isDefault') and len(branches) > 1:
        flash("No puedes eliminar la sucursal principal. Marca otra como principal primero.", 'error')
        return redirect(url_for('web_invoices.company_settings'))
        
    if len(branches) <= 1:
        flash("No puedes eliminar la única sucursal.", 'error')
        return redirect(url_for('web_invoices.company_settings'))

    DatabaseService.delete_branch(owner_uid, branch_id, sandbox=sandbox)
    flash("Sucursal eliminada.", 'success')
    return redirect(url_for('web_invoices.company_settings'))

@web_invoices_bp.route('/settings/team/<employee_uid>/permissions', methods=['POST'])
def update_team_member_permissions(employee_uid):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if session['user'].get('role') != 'owner':
        flash('No tienes permisos de propietario.', 'error')
        return redirect(url_for('web_invoices.team_settings'))
    
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
        "canViewBI": 'canViewBI' in request.form,
        "canViewAuditLog": 'canViewAuditLog' in request.form,
        "canAccounting": 'canAccounting' in request.form,
        "isPosSupervisor": 'isPosSupervisor' in request.form,
        "canViewSubscription": 'canViewSubscription' in request.form,
        "canToggleSandbox": 'canToggleSandbox' in request.form,
        "canManageNotes": 'canManageNotes' in request.form,
        "canManageSuppliers": 'canManageSuppliers' in request.form,
        "canManagePurchaseCXP": 'canManagePurchaseCXP' in request.form,
        "canUseChatbot": 'canUseChatbot' in request.form
    }

    avatar_file = request.files.get('avatar')
    if avatar_file and avatar_file.filename:
        from werkzeug.utils import secure_filename
        import uuid
        
        filename = secure_filename(avatar_file.filename)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        owner_uid = session['user'].get('ownerUID', session['user']['uid'])
        destination_path = f"users/{owner_uid}/avatars/{unique_filename}"
        
        avatar_file.seek(0)
        file_bytes = avatar_file.read()
        content_type = avatar_file.content_type
        
        try:
            profile_image_url = DatabaseService.upload_file_to_storage(
                file_bytes, destination_path, content_type
            )
            # Actualizamos también la URL de la imagen de perfil en el documento
            from app.services.db_service import db_firestore
            db_firestore.collection("users").document(employee_uid).collection("config").document("user_profile").update({
                "profileImageUrl": profile_image_url
            })
        except Exception as e:
            flash(f"Error al subir avatar: {str(e)}", "error")
    
    if DatabaseService.update_employee_permissions(employee_uid, permissions):
        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_USUARIOS
        AuditService.log_from_request(
            owner_uid=session['user']['ownerUID'],
            action=ACTION_UPDATE,
            module=MODULE_USUARIOS,
            entity_id=employee_uid,
            entity_label=f"Permisos de colaborador actualizados (ID: {employee_uid})",
            user_session=session.get('user', {}),
            after=permissions,
            sandbox=True
        )
        flash('Permisos del colaborador actualizados con éxito.', 'success')
    else:
        flash('Error al actualizar permisos.', 'error')
        
    return redirect(url_for('web_invoices.team_settings'))

@web_invoices_bp.route('/settings/team/<employee_uid>/delete', methods=['POST'])
def delete_team_member_route(employee_uid):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if session['user'].get('role') != 'owner':
        flash('No tienes permisos de propietario.', 'error')
        return redirect(url_for('web_invoices.team_settings'))
    
    owner_uid = session['user']['ownerUID']
    
    if DatabaseService.delete_team_member(owner_uid, employee_uid):
        from app.services.audit_service import AuditService, ACTION_DELETE, MODULE_USUARIOS
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_DELETE,
            module=MODULE_USUARIOS,
            entity_id=employee_uid,
            entity_label=f"Colaborador desvinculado (ID: {employee_uid})",
            user_session=session.get('user', {}),
            sandbox=True
        )
        flash('Colaborador desvinculado de tu equipo.', 'success')
    else:
        flash('Error al desvincular colaborador.', 'error')
        
    return redirect(url_for('web_invoices.team_settings'))

@web_invoices_bp.route('/settings/company/export', methods=['POST'])
def export_company_data():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canModifySettings'):
        return render_template('auth/restricted.html', feature_name="Exportación de Datos", required_permission="canModifySettings")
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    selected_sections = request.form.getlist('sections')
    if not selected_sections:
        flash('Debes seleccionar al menos una sección para exportar.', 'error')
        return redirect(url_for('web_invoices.company_settings'))
    
    import io
    import csv
    import zipfile
    from datetime import datetime
    
    def build_clients_csv():
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
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
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
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
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
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
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
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
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
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
            
            timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
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
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
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
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Reportes", required_permission="canInvoice")

    report_categories = get_report_categories()

    return render_template('reports/reports_dashboard.html', active_page='reports',
                           report_categories=report_categories)


def get_report_categories():
    from app.utils.module_gate import module_enabled
    from flask import url_for
    return [
        {
            "key": "ventas",
            "icon": "fa-solid fa-chart-simple",
            "title": "Ventas",
            "count": 6,
            "description": "Monitorea la distribución de tus ventas y obtén información para gestionar tus operaciones comerciales.",
            "category_url": url_for('web_invoices.reports_category', category_key='ventas'),
            "reports": [
                {"title": "Ventas generales", "url": "web_reports_sales.ventas_generales",
                 "enabled": module_enabled('e_cf'),
                 "desc": "Revisa el desempeño de tus ventas para crear estrategias comerciales."},
                {"title": "Ventas por producto/servicio", "url": "web_reports_sales.ventas_por_producto",
                 "enabled": module_enabled('e_cf'),
                 "desc": "Consulta tus ventas detalladas por cada ítem o servicio."},
                {"title": "Ventas por cliente", "url": "web_reports_sales.ventas_por_cliente",
                 "enabled": module_enabled('e_cf'),
                 "desc": "Conoce las ventas asociadas a cada uno de tus clientes."},
                {"title": "Rentabilidad por producto", "url": "web_reports_sales.ventas_rentabilidad",
                 "enabled": module_enabled('e_cf'),
                 "desc": "Conoce la utilidad que generan tus ítems inventariables."},
                {"title": "Ventas por vendedor", "url": "web_reports_sales.ventas_por_vendedor",
                 "enabled": module_enabled('e_cf'),
                 "desc": "Revisa el resumen de las ventas asociadas a cada vendedor/a."},
                {"title": "Estado de cuenta por cliente", "url": "web_reports_sales.ventas_estado_cuenta",
                 "enabled": module_enabled('e_cf'),
                 "desc": "Revisa el detalle de las ventas asociadas a cada cliente."},
            ]
        },
        {
            "key": "administrativos",
            "icon": "fa-solid fa-clipboard-list",
            "title": "Administrativos",
            "count": 7,
            "description": "Haz seguimiento a tus transacciones y obtén información para controlar la salud financiera de tu empresa.",
            "category_url": url_for('web_invoices.reports_category', category_key='administrativos'),
            "reports": [
                {"title": "Cuentas por cobrar", "url": "web_reports_sales.cxc_report",
                 "enabled": module_enabled('cxc'),
                 "desc": "Conoce lo que te deben tus clientes y lleva un control del vencimiento de sus facturas."},
                {"title": "Cuentas por pagar", "url": "web_reports_sales.cxp_report",
                 "enabled": module_enabled('cxp_compras'),
                 "desc": "Conoce las deudas que tienes registradas y lleva un control de tus pagos pendientes."},
                {"title": "Ingresos y compras", "url": "web_reports_sales.admin_ingresos_compras",
                 "enabled": module_enabled('e_cf'),
                 "desc": "Conoce los valores asociados a tus cuentas de ingresos y egresos."},
                {"title": "Valor de inventario", "url": "web_reports_sales.inventory_value_report",
                 "enabled": module_enabled('inventario'),
                 "desc": "Consulta el valor actual, cantidad y costo promedio de tu inventario."},
                {"title": "Transacciones", "url": "web_reports_sales.transactions_report",
                 "enabled": module_enabled('e_cf'),
                 "desc": "Consulta los movimientos de dinero asociados a tus transacciones, sin incluir las transferencias entre bancos."},
                {"title": "Compras", "url": "web_reports_sales.purchases_report",
                 "enabled": module_enabled('cxp_compras'),
                 "desc": "Consulta el detalle de las facturas de compra que tienes registradas en tu contabilidad."},
                {"title": "Reporte anual", "url": "web_reports_sales.admin_reporte_anual",
                 "enabled": module_enabled('e_cf'),
                 "desc": "Conoce el rendimiento que ha tenido tu negocio en cada año."},
            ]
        },
        {
            "key": "financieros",
            "icon": "fa-solid fa-coins",
            "title": "Financieros",
            "count": 1,
            "description": "Analiza los resultados financieros de tu empresa, incluyendo entradas y salidas de efectivo.",
            "category_url": url_for('web_invoices.reports_category', category_key='financieros'),
            "reports": [
                {"title": "Flujo de caja", "url": "web_reports_sales.cash_flow_report",
                 "enabled": module_enabled('e_cf'),
                 "desc": "Revisa la evolución de tus movimientos de efectivo y conoce la liquidez de tu empresa."},
            ]
        },
        {
            "key": "contables",
            "icon": "fa-solid fa-book",
            "title": "Contables",
            "count": 9,
            "description": "Conoce el desempeño contable y el estado económico de tu empresa en todo momento.",
            "category_url": url_for('web_invoices.reports_category', category_key='contables'),
            "reports": [
                {"title": "Exportación contable", "url": "web_invoices.accounting_export_page",
                 "enabled": module_enabled('exportacion_contable'),
                 "desc": "Exporta tu información contable para tu sistema externo."},
                {"title": "Estado de resultados", "url": "web_accounting.income_statement",
                 "enabled": module_enabled('contabilidad'),
                 "desc": "Conoce la utilidad o pérdida de tu empresa en un período."},
                {"title": "Estado de situación financiera", "url": "web_accounting.balance_sheet",
                 "enabled": module_enabled('contabilidad'),
                 "desc": "Conoce la situación financiera de tu empresa en un momento dado."},
                {"title": "Balanza de comprobación", "url": "web_accounting.trial_balance",
                 "enabled": module_enabled('contabilidad'),
                 "desc": "Resume los débitos, créditos y saldos de cada cuenta contable."},
                {"title": "Libro Diario", "url": "web_accounting.general_journal",
                 "enabled": module_enabled('contabilidad'),
                 "desc": "Todas las transacciones contables ordenadas cronológicamente."},
                {"title": "Informe de cuentas", "url": "web_accounting.chart_of_accounts",
                 "enabled": module_enabled('contabilidad'),
                 "desc": "Explora el catálogo de cuentas y sus saldos actuales."},
{"title": "Mayor general", "url": "web_accounting.general_ledger",
                 "enabled": module_enabled('contabilidad'),
                 "desc": "Consulta los movimientos y saldos de cada cuenta contable."},
            ]
        },
        {
            "key": "fiscales",
            "icon": "fa-solid fa-file-shield",
            "title": "Fiscales",
            "count": 7,
            "description": "Revisa el detalle de tus impuestos y retenciones para cumplir con tus obligaciones tributarias.",
            "category_url": url_for('web_invoices.reports_category', category_key='fiscales'),
            "reports": [
                {"title": "Reporte 606", "url": "web_reports_606.reporte_606",
                 "enabled": module_enabled('reporte_606'),
                 "desc": "Compras y gastos del período para tu declaración DGII."},
                {"title": "Reporte 607", "url": "web_reports_607.reporte_607",
                 "enabled": module_enabled('reporte_606'),
                 "desc": "Ventas del período para tu declaración DGII."},
                {"title": "Reporte 608", "url": "web_reports_608.reporte_608",
                 "enabled": True,
                 "desc": "Reporte de compras de bienes y servicios para tu declaración DGII."},
                {"title": "Reporte 623", "url": "web_reports_623.reporte_623",
                 "enabled": True,
                 "desc": "Reporte de compras de servicios transfronterizos para tu declaración DGII."},
                {"title": "Reporte IT1", "url": "web_reports_sales.it1_reports_list",
                 "enabled": module_enabled('e_cf'),
                 "desc": "Crea un reporte con los datos de tu IT-1 y Anexo A para presentarlo en la oficina virtual de la DGII."},
                {"title": "Reporte detallado de impuestos", "url": "web_reports_sales.detailed_taxes_report",
                 "enabled": module_enabled('e_cf'),
                 "desc": "Consulta la base y el valor de tus impuestos generados por cada transacción."},
                {"title": "Impuestos mensuales", "url": "web_reports_sales.monthly_taxes_report",
                 "enabled": True,
                 "desc": "Resumen mensual de impuestos generados, soportados y retenciones para tu declaración DGII."},
                {"title": "Conciliación fiscal", "url": "web_reports_sales.tax_reconciliation_report",
                 "enabled": True,
                 "desc": "Comparativa mes a mes de impuestos y retenciones del año fiscal para detectar discrepancias."},
                {"title": "Impuestos y retenciones", "url": "web_reports_sales.taxes_retentions_report",
                 "enabled": True,
                 "desc": "Conoce el detalle de los impuestos y retenciones asociados a tus compras, ventas y devoluciones."},
            ]
        },
        {
            "key": "para_trabajar",
            "icon": "fa-solid fa-briefcase",
            "title": "Para trabajar",
            "count": 2,
            "description": "Exporta la información clave de tu negocio para realizar análisis adicionales.",
            "category_url": url_for('web_invoices.reports_category', category_key='para_trabajar'),
            "reports": [
                {"title": "Importar gastos", "url": "web_invoices.expense_import_page",
                 "enabled": True,
                 "desc": "Importa gastos desde archivos CSV."},
                {"title": "Exportar respaldo", "url": "web_invoices.backup_export",
                 "enabled": True,
                 "desc": "Descarga una copia de seguridad de todos los datos de tu empresa."},
            ]
        },
        {
            "key": "favoritos",
            "icon": "fa-solid fa-star",
            "title": "Favoritos",
            "count": 0,
            "description": "En este espacio vas a encontrar todos los reportes que has marcado como favoritos.",
            "reports": []
        },
    ]


@web_invoices_bp.route('/reports/categoria/<category_key>')
def reports_category(category_key):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Reportes",
                               required_permission="canInvoice")

    categories = get_report_categories()
    category = next((c for c in categories if c['key'] == category_key), None)
    if not category:
        flash('Categoría de reportes no encontrada.', 'error')
        return redirect(url_for('web_invoices.reports_dashboard'))

    return render_template('reports/categoria.html', active_page='reports',
                           category=category)


@web_invoices_bp.route('/reports/it1')
def it1_diagnostic():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Diagnóstico de IT-1", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    
    real_invoices = [inv for inv in invoices if not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador', 'Pagado pero no emitido']]
    
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
    
    current_period = datetime.now(timezone.utc).strftime("%Y-%m")
    return render_template('reports/it1.html', active_page='reports', it1=it1, current_period=current_period)


@web_invoices_bp.route('/reports/backup-export', methods=['GET', 'POST'])
def backup_export():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Exportar Respaldo", required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox_flag = session.get('is_sandbox_mode', True)

    if request.method == 'GET':
        invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox_flag)
        real_invoices = [inv for inv in invoices if not inv.get('isQuotation')]
        expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox_flag)
        clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox_flag)
        items = DatabaseService.get_items(owner_uid, sandbox=sandbox_flag)
        categories = DatabaseService.get_categories(owner_uid, sandbox=sandbox_flag)
        branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox_flag)
        warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox_flag)

        entries = []
        accounts = []
        price_lists = []
        cost_centers = []
        try:
            entries = DatabaseService.get_accounting_entries(owner_uid, sandbox=sandbox_flag)
        except Exception:
            pass
        try:
            accounts = DatabaseService.get_accounts(owner_uid, sandbox=sandbox_flag)
        except Exception:
            pass
        try:
            price_lists = DatabaseService.get_price_lists(owner_uid, sandbox=sandbox_flag)
        except Exception:
            pass
        try:
            cost_centers = DatabaseService.get_cost_centers(owner_uid, sandbox=sandbox_flag)
        except Exception:
            pass

        modules = [
            {"key": "invoices", "title": "Ventas (e-CF)", "icon": "fa-file-invoice-dollar", "color": "blue",
             "count": len(real_invoices), "default_selected": True},
            {"key": "expenses", "title": "Gastos", "icon": "fa-receipt", "color": "red",
             "count": len(expenses), "default_selected": True},
            {"key": "clients", "title": "Clientes", "icon": "fa-users", "color": "green",
             "count": len(clients), "default_selected": True},
            {"key": "items", "title": "Art\u00edculos", "icon": "fa-boxes-stacked", "color": "purple",
             "count": len(items), "default_selected": True},
            {"key": "accounting_entries", "title": "Asientos contables", "icon": "fa-book", "color": "amber",
             "count": len(entries), "default_selected": True},
            {"key": "accounts", "title": "Cat\u00e1logo de cuentas", "icon": "fa-list-ol", "color": "cyan",
             "count": len(accounts), "default_selected": False},
            {"key": "branches", "title": "Sucursales", "icon": "fa-building", "color": "blue",
             "count": len(branches), "default_selected": False},
            {"key": "warehouses", "title": "Almacenes", "icon": "fa-warehouse", "color": "purple",
             "count": len(warehouses), "default_selected": False},
            {"key": "categories", "title": "Categor\u00edas", "icon": "fa-tags", "color": "green",
             "count": len(categories), "default_selected": False},
            {"key": "price_lists", "title": "Listas de precios", "icon": "fa-tag", "color": "amber",
             "count": len(price_lists), "default_selected": False},
            {"key": "cost_centers", "title": "Centros de costo", "icon": "fa-chart-pie", "color": "red",
             "count": len(cost_centers), "default_selected": False},
        ]

        return render_template('reports/backup_export.html', active_page='reports',
                               modules=modules, sandbox=sandbox_flag)

    # --- POST: generar y descargar respaldo ---
    selected = request.form.getlist('modules')
    fmt = request.form.get('format', 'json')

    if not selected:
        flash('Selecciona al menos un m\u00f3dulo para exportar.', 'error')
        return redirect(url_for('web_invoices.backup_export'))

    # Recolectar datos
    backup = {
        "metadata": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "format": fmt,
            "modules": selected,
        },
        "data": {}
    }

    # Cargar m\u00f3dulos seleccionados
    if 'invoices' in selected:
        invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox_flag)
        backup["data"]["invoices"] = [inv for inv in invoices if not inv.get('isQuotation')]

    if 'expenses' in selected:
        backup["data"]["expenses"] = DatabaseService.get_expenses(owner_uid, sandbox=sandbox_flag)

    if 'clients' in selected:
        backup["data"]["clients"] = DatabaseService.get_clients(owner_uid, sandbox=sandbox_flag)

    if 'items' in selected:
        backup["data"]["items"] = DatabaseService.get_items(owner_uid, sandbox=sandbox_flag)

    if 'categories' in selected:
        backup["data"]["categories"] = DatabaseService.get_categories(owner_uid, sandbox=sandbox_flag)

    if 'branches' in selected:
        backup["data"]["branches"] = DatabaseService.get_branches(owner_uid, sandbox=sandbox_flag)

    if 'warehouses' in selected:
        backup["data"]["warehouses"] = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox_flag)

    if 'accounting_entries' in selected:
        try:
            backup["data"]["accounting_entries"] = DatabaseService.get_accounting_entries(owner_uid, sandbox=sandbox_flag)
        except Exception:
            backup["data"]["accounting_entries"] = []

    if 'accounts' in selected:
        try:
            backup["data"]["accounts"] = DatabaseService.get_accounts(owner_uid, sandbox=sandbox_flag)
        except Exception:
            backup["data"]["accounts"] = []

    if 'price_lists' in selected:
        try:
            backup["data"]["price_lists"] = DatabaseService.get_price_lists(owner_uid, sandbox=sandbox_flag)
        except Exception:
            backup["data"]["price_lists"] = []

    if 'cost_centers' in selected:
        try:
            backup["data"]["cost_centers"] = DatabaseService.get_cost_centers(owner_uid, sandbox=sandbox_flag)
        except Exception:
            backup["data"]["cost_centers"] = []

    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')

    if fmt == 'json':
        # Serializar a JSON con manejo de tipos no serializables
        class BackupEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                return str(obj)

        json_str = json.dumps(backup, ensure_ascii=False, indent=2, cls=BackupEncoder)
        dest = io.BytesIO()
        dest.write(b'\xef\xbb\xbf')
        dest.write(json_str.encode('utf-8'))
        dest.seek(0)
        filename = f"respaldo_{timestamp}.json"
        return send_file(dest, mimetype="application/json", as_attachment=True, download_name=filename)

    else:
        # CSV: crear ZIP con un CSV por m\u00f3dulo
        import zipfile
        dest = io.BytesIO()
        with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as zf:
            for mod_key, records in backup["data"].items():
                if not records:
                    continue
                csv_output = io.StringIO()
                writer = csv.writer(csv_output, quoting=csv.QUOTE_ALL)
                # Encabezados desde el primer registro
                if records:
                    headers = list(records[0].keys())
                    writer.writerow(headers)
                    for rec in records:
                        row = []
                        for h in headers:
                            val = rec.get(h, '')
                            if isinstance(val, (dict, list)):
                                val = json.dumps(val, ensure_ascii=False)
                            row.append(str(val) if val is not None else '')
                        writer.writerow(row)
                zf.writestr(f"{mod_key}.csv", csv_output.getvalue().encode('utf-8-sig'))
        dest.seek(0)
        filename = f"respaldo_{timestamp}.zip"
        return send_file(dest, mimetype="application/zip", as_attachment=True, download_name=filename)


def _parse_period_args():
    now = datetime.now(timezone.utc)
    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', now.month))
    except ValueError:
        month = now.month
    month = max(1, min(12, month))
    return year, month


def _filter_docs_by_period(docs, year, month, date_field='date'):
    prefix = f"{year:04d}-{month:02d}"
    filtered = []
    for d in docs:
        date_val = (d.get(date_field) or d.get('createdAt') or '')[:7]
        if date_val == prefix:
            filtered.append(d)
    return filtered


@web_invoices_bp.route('/reports/607/export')
def report_607_export():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Reporte 607", required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    year, month = _parse_period_args()
    fmt = request.args.get('format', 'dgii')

    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=False)
    real_invoices = [
        inv for inv in invoices
        if inv.get('status') not in ['Borrador', 'Anulada', 'Consolidada', 'Pagado pero no emitido']
        and inv.get('dgiiStatus') in ['ACCEPTED', 'ACCEPTED_CONDITIONAL']
    ]
    filtered = _filter_docs_by_period(real_invoices, year, month)

    company = DatabaseService.get_company_profile(owner_uid) or {}
    owner_rnc = (company.get('companyRNC') or '').replace('-', '')

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)

    if fmt == 'dgii':
        writer.writerow([
            "RNC Emisor",
            "Periodo",
            "RNC/Cédula Receptor",
            "Tipo Identificación",
            "NCF/e-CF",
            "NCF Modificado",
            "Tipo Ingreso",
            "Fecha Comprobante",
            "Monto Facturado",
            "ITBIS Facturado",
            "ITBIS Retenido",
            "ISR Retenido",
        ])
        period = f"{year:04d}{month:02d}"
        for inv in filtered:
            rnc_rec = (inv.get('clientRNC') or '').replace('-', '')
            tipo_id = "1" if len(rnc_rec) == 9 else ("2" if len(rnc_rec) == 11 else "3")
            income_type = (inv.get('incomeType', '01') or '01')
            income_code = income_type.split('-')[0].strip() if isinstance(income_type, str) else str(income_type)
            income_code = income_code.zfill(2)[:2]
            writer.writerow([
                owner_rnc,
                period,
                rnc_rec,
                tipo_id,
                inv.get('encf', ''),
                inv.get('ncfModified', ''),
                income_code,
                (inv.get('date') or '')[:10],
                f"{float(inv.get('total', 0.0)):.2f}",
                f"{float(inv.get('totalITBIS', 0.0)):.2f}",
                f"{float(inv.get('retainedITBIS', 0.0)):.2f}",
                f"{float(inv.get('retainedISR', 0.0)):.2f}",
            ])
    else:
        writer.writerow([
            "Fecha",
            "Cliente",
            "RNC",
            "NCF/e-CF",
            "Tipo e-CF",
            "Monto",
            "ITBIS",
            "Ret. ITBIS",
            "Ret. ISR",
            "Estatus",
        ])
        for inv in filtered:
            writer.writerow([
                (inv.get('date') or '')[:10],
                inv.get('clientName', ''),
                inv.get('clientRNC', ''),
                inv.get('encf', ''),
                inv.get('ecfType', ''),
                f"{float(inv.get('total', 0.0)):.2f}",
                f"{float(inv.get('totalITBIS', 0.0)):.2f}",
                f"{float(inv.get('retainedITBIS', 0.0)):.2f}",
                f"{float(inv.get('retainedISR', 0.0)):.2f}",
                inv.get('status', ''),
            ])

    dest = io.BytesIO()
    dest.write(b"\xef\xbb\xbf")
    dest.write(output.getvalue().encode('utf-8'))
    dest.seek(0)
    filename = f"reporte_607_{year:04d}{month:02d}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return send_file(dest, mimetype="text/csv", as_attachment=True, download_name=filename)


@web_invoices_bp.route('/reports/608/export')
def report_608_export():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Reporte 608", required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    year, month = _parse_period_args()

    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=False)
    anuladas = [inv for inv in invoices if inv.get('status') == 'Anulada']
    filtered = _filter_docs_by_period(anuladas, year, month)

    company = DatabaseService.get_company_profile(owner_uid) or {}
    owner_rnc = (company.get('companyRNC') or '').replace('-', '')

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow([
        "RNC Emisor",
        "Periodo",
        "NCF/e-CF",
        "Fecha Anulación",
        "Tipo Anulación",
        "Motivo"
    ])
    period = f"{year:04d}{month:02d}"
    for inv in filtered:
        writer.writerow([
            owner_rnc,
            period,
            inv.get('encf', ''),
            (inv.get('updatedAt') or inv.get('date') or '')[:10],
            "01",
            (inv.get('comentario') or inv.get('notes') or "")[:150]
        ])

    dest = io.BytesIO()
    dest.write(b"\xef\xbb\xbf")
    dest.write(output.getvalue().encode('utf-8'))
    dest.seek(0)
    filename = f"reporte_608_{year:04d}{month:02d}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return send_file(dest, mimetype="text/csv", as_attachment=True, download_name=filename)


@web_invoices_bp.route('/reports/609/export')
def report_609_export():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Reporte 609", required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    year, month = _parse_period_args()

    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=False)
    contingencia = [
        inv for inv in invoices
        if inv.get('emisionMode') == 'FALLBACK' and not inv.get('isSyncedWithDGII', False)
    ]
    filtered = _filter_docs_by_period(contingencia, year, month)

    company = DatabaseService.get_company_profile(owner_uid) or {}
    owner_rnc = (company.get('companyRNC') or '').replace('-', '')

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow([
        "RNC Emisor",
        "Periodo",
        "NCF/e-CF",
        "Fecha Emisión",
        "Monto",
        "ITBIS",
        "Estado"
    ])
    period = f"{year:04d}{month:02d}"
    for inv in filtered:
        writer.writerow([
            owner_rnc,
            period,
            inv.get('encf', ''),
            (inv.get('date') or '')[:10],
            f"{float(inv.get('total', 0.0)):.2f}",
            f"{float(inv.get('totalITBIS', 0.0)):.2f}",
            inv.get('status', 'Pendiente DGII')
        ])

    dest = io.BytesIO()
    dest.write(b"\xef\xbb\xbf")
    dest.write(output.getvalue().encode('utf-8'))
    dest.seek(0)
    filename = f"reporte_609_{year:04d}{month:02d}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return send_file(dest, mimetype="text/csv", as_attachment=True, download_name=filename)


@web_invoices_bp.route('/reports/dgii-tools', methods=['GET'])
def dgii_tools():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Herramientas DGII", required_permission="canInvoice")
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    company = DatabaseService.get_company_profile(owner_uid)
    
    dgii_status = DgiiDirectService.check_dgii_status(company, sandbox=sandbox)
    
    return render_template(
        'reports/dgii_tools.html',
        active_page='reports',
        dgii_status=dgii_status,
        dgii_provider='dgii_direct',
        dgii_sandbox_mode=Config.DGII_SANDBOX_MODE,
        is_sandbox=sandbox
    )

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
    res = DGIIService.validate_and_fetch_rnc(rnc)
    return jsonify({
        "success": not res.get("error", True),
        "data": {
            "razonSocial": res.get("razon_social", ""),
            "actividad": res.get("actividad", ""),
            "regimen": res.get("regimen", "")
        } if not res.get("error") else None,
        "message": res.get("message", "")
    })

@web_invoices_bp.route('/reports/check-dgii-status-ajax', methods=['POST'])
def check_dgii_status_ajax():
    if 'user' not in session: return jsonify({"success": False, "message": "No autenticado"}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.get_json(silent=True) or {}
    env = data.get("environment")
    maint = data.get("maintenance")
    
    company = DatabaseService.get_company_profile(owner_uid)
    res = DgiiDirectService.check_dgii_status(company, sandbox=sandbox)
    return jsonify(res)


@web_invoices_bp.route('/help')
def help_center():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    return render_template('help.html', active_page='help')

@web_invoices_bp.route('/api/chatbot', methods=['POST'])
@require_module('ia_bi')
@require_permission('canUseChatbot', 'Asistente IA')
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
        
    from app.services.chatbot import ChatbotService
    result = ChatbotService.ask_chatbot(owner_uid, message, history, sandbox=sandbox)
    return jsonify(result)

@web_invoices_bp.route('/suscripcion')
@require_permission('canViewSubscription', 'Suscripción y Consumo')
def client_subscription_page():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    
    profile = DatabaseService.get_company_profile(owner_uid)
    
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

    billing_day = profile.get('billingDay', 1)
    stats = DatabaseService.get_invoice_stats(owner_uid, billing_day)
    payments = DatabaseService.get_payments(owner_uid)
    user_profile = DatabaseService.get_user_profile(session['user']['uid'])
    created_at = user_profile.get('createdAt') if user_profile else None
    monthly_payment = float(profile.get('monthlyPayment', 0))
    additional_cost = float(profile.get('additionalDocumentCost', 0))
    document_limit = int(profile.get('documentLimit', 0)) if profile.get('documentLimit') else 0
    
    previous_monthly_payment = profile.get('previous_monthlyPayment')
    previous_additional_document_cost = profile.get('previous_additionalDocumentCost')
    previous_document_limit = profile.get('previous_documentLimit')
    plan_change_date = None
    pcd = profile.get('plan_change_date')
    if pcd:
        try:
            plan_change_date = datetime.strptime(str(pcd)[:10], '%Y-%m-%d')
        except (ValueError, TypeError):
            pass
    
    billing_history = DatabaseService.get_billing_history(
        owner_uid, billing_day=billing_day, monthly_payment=monthly_payment,
        additional_document_cost=additional_cost, document_limit=document_limit, created_at=created_at,
        previous_monthly_payment=previous_monthly_payment,
        previous_additional_document_cost=previous_additional_document_cost,
        previous_document_limit=previous_document_limit,
        plan_change_date=plan_change_date,
    )
    storage_used = DatabaseService.get_storage_usage_mb(owner_uid)
    storage_limit = profile.get('storageLimitMB', 512) or 512

    cancel_scheduled = profile.get('cancel_at_period_end', False)
    cancel_date = profile.get('cancel_scheduled_date', '')

    # Calcular prorrateo para el ciclo actual si aplica
    proration_current = None
    if plan_change_date and stats.get('current_cycle_start') and stats.get('current_cycle_end'):
        try:
            cs = datetime.strptime(stats['current_cycle_start'], '%Y-%m-%d')
            ce = datetime.strptime(stats['current_cycle_end'], '%Y-%m-%d')
            if cs <= plan_change_date <= ce:
                total_days = (ce - cs).days + 1
                days_before = max(0, (plan_change_date - cs).days)
                days_after = total_days - days_before
                old_rate = float(previous_monthly_payment or monthly_payment)
                new_rate = monthly_payment
                prorated = round((old_rate * days_before / total_days) + (new_rate * days_after / total_days), 2)
                proration_current = {
                    'old_rate': old_rate,
                    'new_rate': new_rate,
                    'days_before': days_before,
                    'days_after': days_after,
                    'total_days': total_days,
                    'prorated_fee': prorated,
                    'change_date': plan_change_date.strftime('%Y-%m-%d'),
                }
        except (ValueError, TypeError):
            pass

    return render_template('subscription.html', active_page='subscription',
        profile=profile, plan_name=plan_name, stats=stats, payments=payments,
        billing_history=billing_history, storage_used=storage_used, storage_limit=storage_limit,
        cancel_scheduled=cancel_scheduled, cancel_date=cancel_date,
        proration_current=proration_current)

def _update_profile_fields(owner_uid, updates):
    """Actualiza campos específicos del perfil de empresa en Firestore sin sobrescribir todo."""
    from app.services.db_service import db_firestore, _cached_company_profile
    from app.cache import cache
    try:
        db_firestore.collection('users').document(owner_uid)\
            .collection('config').document('profile').update(updates)
        cache.delete_memoized(_cached_company_profile, owner_uid)
    except Exception as e:
        print(f"⚠️ Error actualizando perfil: {e}")

@web_invoices_bp.route('/cambiar-plan', methods=['GET', 'POST'])
@require_permission('canViewSubscription', 'Suscripción y Consumo')
def change_plan_page():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    profile = DatabaseService.get_company_profile(owner_uid)
    billing_day = profile.get('billingDay', 1)
    
    if request.method == 'POST':
        new_plan_id = request.form.get('plan_id', '').strip()
        if not new_plan_id:
            flash('Selecciona un plan.', 'error')
            return redirect(url_for('web_invoices.change_plan_page'))
        
        plan_data = DatabaseService.get_plan(new_plan_id)
        if not plan_data:
            flash('El plan seleccionado no existe.', 'error')
            return redirect(url_for('web_invoices.change_plan_page'))
        
        if plan_data.get('is_custom', False) or not plan_data.get('visible_on_landing', True):
            flash('Plan no disponible para cambio.', 'error')
            return redirect(url_for('web_invoices.change_plan_page'))
        
        current_plan_id = profile.get('planId', '')
        if current_plan_id == new_plan_id:
            flash('Ya estás en este plan.', 'info')
            return redirect(url_for('web_invoices.change_plan_page'))
        
        # Verificar uso actual vs límites del plan destino (anti-abuso)
        from datetime import datetime, timezone as _tz
        stats = DatabaseService.get_invoice_stats(owner_uid, billing_day)
        current_docs = stats.get('prod_current_cycle', 0)
        
        blocked_reasons = []
        
        target_doc_limit = plan_data.get('documentLimit', 0)
        if target_doc_limit > 0 and current_docs > target_doc_limit:
            blocked_reasons.append(f'tienes {current_docs} documentos emitidos este ciclo (límite: {target_doc_limit})')
        
        target_storage = plan_data.get('storageLimitMB', 0)
        if target_storage > 0:
            storage_used = DatabaseService.get_storage_usage_mb(owner_uid)
            if storage_used > target_storage:
                blocked_reasons.append(f'tienes {storage_used:.1f} MB de almacenamiento (límite: {target_storage} MB)')
        
        target_user_limit = plan_data.get('userLimit', 0)
        if target_user_limit > 0:
            team = DatabaseService.get_team_members(owner_uid)
            current_team = len(team) + 1
            if current_team > target_user_limit:
                blocked_reasons.append(f'tienes {current_team} miembros del equipo (límite: {target_user_limit})')
        
        target_branch_limit = plan_data.get('branchLimit', 0)
        if target_branch_limit > 0:
            branches = DatabaseService.get_branches(owner_uid, sandbox=False)
            current_branches = len(branches)
            if current_branches > target_branch_limit:
                blocked_reasons.append(f'tienes {current_branches} sucursales (límite: {target_branch_limit})')
        
        target_box_limit = plan_data.get('boxLimit', 0)
        if target_box_limit > 0:
            boxes = DatabaseService.get_cash_registers(owner_uid, sandbox=False)
            current_boxes = len(boxes)
            if current_boxes > target_box_limit:
                blocked_reasons.append(f'tienes {current_boxes} cajas registradoras (límite: {target_box_limit})')
        
        if blocked_reasons:
            flash('No puedes cambiar a este plan porque ' + ', '.join(blocked_reasons) + '. Reduce tu consumo antes de cambiar.', 'error')
            return redirect(url_for('web_invoices.change_plan_page'))
        
        new_version = (profile.get('plan_version', 0) or 0) + 1
        updates = {'planId': new_plan_id, 'plan_version': new_version}
        for f in ['documentLimit','userLimit','storageLimitMB','monthlyPayment',
                  'additionalDocumentCost','additionalUserCost','branchLimit',
                  'boxLimit','additionalBoxCost','posEnabled']:
            if f in plan_data:
                updates[f] = plan_data[f]
        if profile.get('cancel_at_period_end'):
            updates['cancel_at_period_end'] = False
            updates['cancel_scheduled_date'] = ''
        
        # Guardar valores anteriores para prorrateo
        if profile.get('monthlyPayment') is not None:
            updates['previous_monthlyPayment'] = profile.get('monthlyPayment')
        if profile.get('additionalDocumentCost') is not None:
            updates['previous_additionalDocumentCost'] = profile.get('additionalDocumentCost')
        if profile.get('documentLimit') is not None:
            updates['previous_documentLimit'] = profile.get('documentLimit')
        updates['plan_change_date'] = datetime.now(_tz.utc).strftime('%Y-%m-%d')
        
        _update_profile_fields(owner_uid, updates)
        new_name = plan_data.get('name', 'Nuevo Plan')
        flash(f'¡Plan cambiado a {new_name} exitosamente! Los cambios se aplicarán de inmediato.', 'success')
        return redirect(url_for('web_invoices.client_subscription_page'))
    
    # GET: mostrar planes con uso actual para referencia visual
    plans = DatabaseService.get_visible_plans()
    current_plan_id = profile.get('planId', '')
    current_plan = next((p for p in plans if p['id'] == current_plan_id), None)
    
    stats = DatabaseService.get_invoice_stats(owner_uid, billing_day)
    current_usage = {
        'docs': stats.get('prod_current_cycle', 0),
        'storage': DatabaseService.get_storage_usage_mb(owner_uid),
        'team': len(DatabaseService.get_team_members(owner_uid)) + 1,
        'branches': len(DatabaseService.get_branches(owner_uid, sandbox=False)),
        'boxes': len(DatabaseService.get_cash_registers(owner_uid, sandbox=False)),
    }
    
    return render_template('change_plan.html', active_page='subscription',
        plans=plans, current_plan_id=current_plan_id, current_plan=current_plan,
        profile=profile, current_usage=current_usage)

@web_invoices_bp.route('/cancelar-suscripcion', methods=['POST'])
@require_permission('canViewSubscription', 'Suscripción y Consumo')
def cancel_subscription():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    profile = DatabaseService.get_company_profile(owner_uid)
    
    if profile.get('status') != 'Activo':
        flash('No puedes cancelar una cuenta que no está activa.', 'error')
        return redirect(url_for('web_invoices.client_subscription_page'))
    
    if profile.get('cancel_at_period_end'):
        flash('Ya tienes una cancelación programada.', 'info')
        return redirect(url_for('web_invoices.client_subscription_page'))
    
    from datetime import datetime, timezone
    import calendar
    billing_day = profile.get('billingDay', 1)
    now = datetime.now(timezone.utc)
    if billing_day <= now.day:
        next_month = now.month + 1
        year = now.year
        if next_month > 12:
            next_month = 1
            year += 1
    else:
        next_month = now.month
        year = now.year
    last_day = calendar.monthrange(year, next_month)[1]
    cancel_day = min(billing_day, last_day)
    cancel_date = datetime(year, next_month, cancel_day, 23, 59, 59, tzinfo=timezone.utc)
    cancel_date_str = cancel_date.strftime('%d/%m/%Y')
    
    _update_profile_fields(owner_uid, {
        'cancel_at_period_end': True,
        'cancel_scheduled_date': cancel_date_str,
    })
    flash(f'Cancelación programada para el {cancel_date_str}. Podrás seguir usando el servicio hasta esa fecha.', 'warning')
    return redirect(url_for('web_invoices.client_subscription_page'))

@web_invoices_bp.route('/reactivar-suscripcion', methods=['POST'])
@require_permission('canViewSubscription', 'Suscripción y Consumo')
def reactivate_subscription():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    profile = DatabaseService.get_company_profile(owner_uid)
    
    if not profile.get('cancel_at_period_end'):
        flash('No hay cancelación programada.', 'info')
        return redirect(url_for('web_invoices.client_subscription_page'))
    
    _update_profile_fields(owner_uid, {
        'cancel_at_period_end': False,
        'cancel_scheduled_date': '',
    })
    flash('Suscripción reactivada exitosamente.', 'success')
    return redirect(url_for('web_invoices.client_subscription_page'))


# -------------------------------------------------------------
# CxC (Cuentas por Cobrar) and Payment Promises Module
# -------------------------------------------------------------

@web_invoices_bp.route('/cxc')
def cxc_dashboard():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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
        elif status in ["Emitida", "Parcialmente Cobrada", "Vencida", "Revisión de Pago"]:
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
    
    # Exportar a CSV si se solicita
    if request.args.get('export') == 'csv':
        import io
        from datetime import datetime
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["Factura #", "Cliente", "Fecha Emisión", "Fecha Vencimiento", "Total Facturado (RD$)", "Balance Pendiente (RD$)", "Estatus"])
        for inv in cxc_invoices:
            writer.writerow([
                inv.get("invoiceNumber", ""),
                inv.get("clientName", ""),
                inv.get("date", "")[:10],
                inv.get("dueDate", "")[:10],
                f"{inv.get('total', 0.0):.2f}",
                f"{inv.get('remainingBalance', inv.get('netPayable', 0.0)):.2f}",
                inv.get("status", "")
            ])
        dest = io.BytesIO()
        dest.write(b'\xef\xbb\xbf')  # UTF-8 BOM
        dest.write(output.getvalue().encode('utf-8'))
        dest.seek(0)
        filename = f"cxc_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(
            dest,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )

    bank_accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox)

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
        company=company,
        bank_accounts=bank_accounts
    )


@web_invoices_bp.route('/cxc/pay/<invoice_id>', methods=['POST'])
def cxc_quick_pay(invoice_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageCXC'):
        flash('No tienes permiso para registrar cobros.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('Factura no encontrada.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

    before_invoice = invoice.copy()
    remaining_balance = float(invoice.get('remainingBalance', invoice.get('netPayable', 0.0)))

    try:
        amount = float(request.form.get('amount', remaining_balance))
    except ValueError:
        amount = 0.0

    if amount <= 0.0:
        flash('El monto a cobrar debe ser mayor a cero.', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))
    if amount > remaining_balance + 0.01:
        flash(f'El monto (RD$ {amount:,.2f}) no puede superar el balance pendiente (RD$ {remaining_balance:,.2f}).', 'error')
        return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))

    payment_method = request.form.get('paymentMethod', 'Cheque / Transferencia')
    if payment_method == 'Efectivo':
        bank = 'Caja Efectivo'
        reference_number = 'Pago en Efectivo'
    else:
        bank = request.form.get('bank', 'Banco Popular Dominicano')
        reference_number = request.form.get('referenceNumber', 'Abono Registrado')

    bank_account_id = request.form.get('bankAccountId', '')

    payment_dict = {
        "paymentMethod": payment_method,
        "bank": bank,
        "referenceNumber": reference_number,
        "paymentDate": datetime.now(timezone.utc).isoformat(),
        "registeredBy": session['user']['email'],
        "amount": amount,
        "moraAction": "perdonado",
        "moraForgiven": 0,
        "bankAccountId": bank_account_id
    }

    try:
        DatabaseService.register_invoice_payment(owner_uid, invoice_id, payment_dict, sandbox=sandbox)
        new_balance = max(0.0, remaining_balance - amount)
        if new_balance <= 0.01:
            flash('¡Factura liquidada y saldada al 100% con éxito!', 'success')
        else:
            flash(f'¡Abono de RD$ {amount:,.2f} registrado con éxito! Pendiente: RD$ {new_balance:,.2f}.', 'success')

        updated_invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
        from app.services.audit_service import AuditService, MODULE_FACTURAS
        AuditService.log_from_request(
            owner_uid=owner_uid, action="PAYMENT", module=MODULE_FACTURAS,
            entity_id=invoice_id,
            entity_label=f"Cobro rápido CxC: RD$ {amount:,.2f} - {payment_method}",
            user_session=session.get('user', {}),
            before=before_invoice, after=updated_invoice,
            sandbox=sandbox
        )
    except Exception as e:
        flash(f'Error al registrar el cobro: {str(e)}', 'error')

    return redirect(url_for('web_invoices.invoice_detail', invoice_id=invoice_id))


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
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageCXC'):
        flash("No tienes permiso para gestionar promesas de pago.", "error")
        return redirect(url_for('web_invoices.cxc_dashboard'))
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice_id = request.form.get('invoiceId')
    fecha_promesa = request.form.get('fechaPromesa')
    monto_prometido = request.form.get('montoPrometido', 0.0)
    notas = request.form.get('notas', '')
    
    if not invoice_id or not fecha_promesa:
        flash("Factura y fecha de promesa son campos obligatorios.", "error")
        return redirect(url_for('web_invoices.cxc_dashboard'))
        
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash("Factura no encontrada.", "error")
        return redirect(url_for('web_invoices.cxc_dashboard'))
        
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
            "date": datetime.now(timezone.utc).isoformat(),
            "nextContactDate": fecha_promesa,
            "completed": False,
            "registeredBy": session['user'].get('name', 'Usuario')
        }
        DatabaseService.save_client_interaction(owner_uid, invoice["clientId"], str(uuid.uuid4()), interaction_dict, sandbox=sandbox)
        
    flash("Promesa de pago registrada exitosamente.", "success")
    return redirect(url_for('web_invoices.cxc_dashboard'))

@web_invoices_bp.route('/cxc/promises/<promise_id>/update-status', methods=['POST'])
def update_payment_promise_status(promise_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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
            "date": datetime.now(timezone.utc).isoformat(),
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


@web_invoices_bp.route('/cxc/write-off/<invoice_id>', methods=['POST'])
def cxc_write_off(invoice_id):
    if 'user' not in session:
        return jsonify({"success": False, "message": "No autorizado"}), 401
    if not check_permission('canManageCXC'):
        return jsonify({"success": False, "message": "Permiso insuficiente"}), 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        return jsonify({"success": False, "message": "Factura no encontrada"}), 404
    if invoice.get('status') not in ('Vencida', 'Emitida'):
        return jsonify({"success": False, "message": "Solo se pueden castigar facturas vencidas o emitidas"}), 400
    reason = request.form.get('reason', '')
    amount = float(request.form.get('amount', invoice.get('remainingBalance', 0)))
    try:
        from app.services.accounting_service import AccountingService
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        bad_debt = next((a for a in accounts if 'incobrable' in a.get('name','').lower()), None)
        lines = [{"accountId": bad_debt['id'], "accountCode": bad_debt.get('code',''), "accountName": bad_debt.get('name',''), "debit": amount, "credit": 0, "description": f"Castigo {invoice.get('invoiceNumber','')}"}]
        cxc = next((a for a in accounts if a.get('usage') == 'cxc'), None)
        if cxc:
            lines.append({"accountId": cxc['id'], "accountCode": cxc.get('code',''), "accountName": cxc.get('name',''), "debit": 0, "credit": amount, "description": f"Castigo {invoice.get('invoiceNumber','')}"})
        AccountingService.generate_entry(owner_uid, {"entryType":"standard","date":datetime.now(timezone.utc).strftime("%Y-%m-%d"),"concept":f"Castigo factura {invoice.get('invoiceNumber','')}","lines":lines,"createdBy":session.get('user',{}).get('name','')}, sandbox=sandbox)
    except (ImportError, StopIteration):
        pass
    invoice['status'] = 'Castigada'
    invoice['remainingBalance'] = 0.0
    invoice['writeOffReason'] = reason
    invoice['writeOffDate'] = datetime.now(timezone.utc).isoformat()
    DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
    return jsonify({"success": True, "message": "Factura castigada"})


@web_invoices_bp.route('/expenses/cxp/batch-pay', methods=['POST'])
def cxp_batch_pay():
    if 'user' not in session:
        return jsonify({"success": False, "message": "No autorizado"}), 401
    if not check_permission('canManageCXP'):
        return jsonify({"success": False, "message": "Permiso insuficiente"}), 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    eids = request.form.getlist('expense_ids')
    if not eids:
        return jsonify({"success": False, "message": "Selecciona al menos un gasto"}), 400
    total, paid = 0.0, 0
    for eid in eids:
        try:
            exp = DatabaseService.get_expense(owner_uid, eid, sandbox=sandbox)
            if not exp:
                continue
            rem = float(exp.get('cxpRemainingBalance', exp.get('amount', 0)))
            total += rem
            DatabaseService.save_cxp_payment(owner_uid, eid, rem, registered_by=session.get('user',{}).get('name',''), sandbox=sandbox)
            paid += 1
        except Exception:
            pass
    return jsonify({"success": True, "paid": paid, "total": total})
# EXPORTACIÓN CONTABLE
# =========================================================================================
from app.services.accounting_export_service import AccountingExportService, EXPORT_FORMATS, DEFAULT_CHART_OF_ACCOUNTS


@web_invoices_bp.route('/reports/export/accounting')
def accounting_export_page():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', required_permission="canInvoice")
    return render_template('reports/accounting_export.html',
                           formats=EXPORT_FORMATS,
                           active_page='reports')


@web_invoices_bp.route('/reports/export/accounting/download', methods=['POST'])
def accounting_export_download():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    export_type = request.form.get('exportType', 'sales')
    fmt = request.form.get('format', 'csv_std')
    date_from = request.form.get('dateFrom', '')
    date_to = request.form.get('dateTo', '')

    real = [inv for inv in all_invoices if not inv.get('isQuotation') and inv.get('status') not in ('Anulada', 'Borrador', 'Pagado pero no emitido')]

    if date_from:
        real = [inv for inv in real if (inv.get('date') or '')[:10] >= date_from]
    if date_to:
        real = [inv for inv in real if (inv.get('date') or '')[:10] <= date_to]

    all_expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    real_exp = [exp for exp in all_expenses if exp.get('status') not in ('Anulada',)]
    if date_from:
        real_exp = [exp for exp in real_exp if (exp.get('date') or '')[:10] >= date_from]
    if date_to:
        real_exp = [exp for exp in real_exp if (exp.get('date') or '')[:10] <= date_to]

    from flask import send_file
    if export_type == 'sales':
        buf = AccountingExportService.export_sales(owner_uid, real, fmt=fmt)
        filename = f"contabilidad_ventas_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    elif export_type == 'expenses':
        buf = AccountingExportService.export_expenses(owner_uid, real_exp, fmt=fmt)
        filename = f"contabilidad_gastos_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    else:
        flash('❌ Tipo de exportación inválido.', 'error')
        return redirect(url_for('web_invoices.accounting_export_page'))

    return send_file(buf, mimetype="text/csv", as_attachment=True, download_name=filename)


@web_invoices_bp.route('/api/save-chart-of-accounts', methods=['POST'])
def save_chart_of_accounts():
    if 'user' not in session:
        return jsonify(success=False, error="No autorizado"), 401
    owner_uid = session['user']['ownerUID']
    coa = {}
    for key in DEFAULT_CHART_OF_ACCOUNTS:
        val = request.form.get(f'coa_{key}', '').strip()
        if val:
            coa[key] = val
    profile = DatabaseService.get_company_profile(owner_uid) or {}
    profile["chartOfAccounts"] = coa
    DatabaseService.save_company_profile(owner_uid, profile)
    flash('✅ Plan de cuentas actualizado.', 'success')
    return redirect(url_for('web_invoices.accounting_export_page'))


@web_invoices_bp.route('/reports/bi')
def bi_dashboard():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canViewBI'):
        return render_template('auth/restricted.html', feature_name="Inteligencia de Negocios (BI)", required_permission="canViewBI")
    return redirect(url_for('web_dashboard.dashboard'))


# =========================================================================
# IMPORTACIÓN DE XML DE GASTOS
# =========================================================================

@web_invoices_bp.route('/expenses/import')
def expense_import_page():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Importar XML", required_permission="canExpenses")
    return render_template('expenses/import.html', active_page='expenses',
                           categories=["Comida y Restaurantes", "Transporte y Combustible",
                                       "Servicios Básicos", "Software y Tecnología",
                                       "Materiales de Oficina", "Alquileres",
                                       "Impuestos y Tasas", "Otros Gastos"])


@web_invoices_bp.route('/expenses/import/preview', methods=['POST'])
def expense_import_preview():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return jsonify({"success": False, "error": "Sin permiso"}), 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    xml_file = request.files.get('xml_file')
    pdf_file = request.files.get('pdf_file')

    if not xml_file or not xml_file.filename:
        return jsonify({"success": False, "message": "Debes subir un archivo XML."}), 400

    try:
        xml_bytes = xml_file.read()
    except Exception as e:
        return jsonify({"success": False, "message": f"Error al leer XML: {e}"}), 400

    from app.services.xml_import_service import XMLImportService
    parsed = XMLImportService.parse_ecf_xml(xml_bytes)
    if not parsed.get("success"):
        return jsonify({"success": False, "message": parsed.get("message", "Error al parsear XML")}), 400

    errors = XMLImportService.validate_fiscal_structure(parsed)
    if errors:
        return jsonify({"success": False, "message": "Errores de validación: " + "; ".join(errors)}), 400

    from app.services.supplier_service import SupplierService
    supplier_id, _ = SupplierService.get_or_create_supplier(
        owner_uid, parsed["supplierRnc"], parsed["supplierName"],
        parsed.get("supplierAddress", ""), sandbox=sandbox
    )

    from app.services.ai_classifier_service import AIExpenseClassifier
    items_text = XMLImportService.items_to_text(parsed)
    ai_result = AIExpenseClassifier.classify_expense_from_import(
        owner_uid, parsed["supplierName"], parsed["supplierRnc"],
        items_text, parsed["total"], parsed.get("issueDate", ""), parsed["ecfType"]
    )

    duplicate = AIExpenseClassifier.detect_duplicate(
        owner_uid, parsed["supplierRnc"], parsed["total"],
        parsed.get("issueDate", ""), sandbox=sandbox
    )

    import json
    import uuid
    preview_id = str(uuid.uuid4())
    session_data = {
        "parsed": parsed,
        "ai_result": ai_result,
        "supplier_id": supplier_id,
        "items_text": items_text,
        "duplicate": duplicate,
    }
    if 'expense_import_previews' not in session:
        session['expense_import_previews'] = {}
    session['expense_import_previews'][preview_id] = session_data
    session.modified = True

    return jsonify({
        "success": True,
        "preview_id": preview_id,
        "parsed": {
            "encf": parsed.get("encf", ""),
            "ecfType": parsed.get("ecfType", ""),
            "supplierName": parsed.get("supplierName", ""),
            "supplierRnc": parsed.get("supplierRnc", ""),
            "supplierAddress": parsed.get("supplierAddress", ""),
            "issueDate": parsed.get("issueDate", ""),
            "subtotal": parsed.get("subtotal", 0),
            "totalITBIS": parsed.get("totalITBIS", 0),
            "total": parsed.get("total", 0),
            "items": parsed.get("items", []),
        },
        "ai": ai_result,
        "duplicate": duplicate,
        "supplier_id": supplier_id,
        "categories": AIExpenseClassifier.CATEGORIES,
    })


@web_invoices_bp.route('/expenses/import/confirm', methods=['POST'])
def expense_import_confirm():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return jsonify({"success": False, "error": "Sin permiso"}), 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    import uuid
    expense_id = str(uuid.uuid4())
    data = request.get_json(force=True) or {}

    preview_id = data.get("preview_id", "")
    encf = data.get("encf", "")
    ecf_type = data.get("ecfType", "E31")
    supplier_rnc = "".join(filter(str.isdigit, str(data.get("supplierRnc", ""))))
    supplier_name = data.get("supplierName", "")
    supplier_address = data.get("supplierAddress", "")
    date = data.get("issueDate", "")
    subtotal = float(data.get("subtotal", 0))
    itbis = float(data.get("totalITBIS", 0))
    total = float(data.get("total", 0))
    category = data.get("category", "Otros Gastos")
    tipo_gasto = data.get("tipoGastoDGII", "02")
    concept = data.get("concept", supplier_name)
    payment_type = data.get("paymentType", "Contado")
    is_recurring = data.get("isRecurring", False)
    recurrence_interval = data.get("recurrenceInterval", "mensual") if is_recurring else ""
    is_deductible = data.get("isDeductible", True)

    # Recuperar datos del preview para el reporte
    ai_result = {}
    duplicate = None
    preview_data = session.get('expense_import_previews', {}).get(preview_id)
    if preview_data:
        ai_result = preview_data.get("ai_result", {})
        duplicate = preview_data.get("duplicate")

    from app.services.supplier_service import SupplierService
    supplier_id, supplier_created = SupplierService.get_or_create_supplier(
        owner_uid, supplier_rnc, supplier_name, supplier_address, sandbox=sandbox
    )

    importMeta = {
        "encf": encf,
        "ecfType": ecf_type,
        "supplierName": supplier_name,
        "supplierRnc": supplier_rnc,
        "total": total,
        "itbis": itbis,
        "subtotal": subtotal,
        "date": date[:10] if date else "",
        "concept": concept,
        "category": category,
        "tipoGasto": tipo_gasto,
        "paymentType": payment_type,
        "isDeductible": is_deductible,
        "isRecurring": is_recurring,
        "recurrenceInterval": recurrence_interval,
        "aiConfidence": ai_result.get("confidence", 0),
        "aiCategory": ai_result.get("category", ""),
        "anomalies": ai_result.get("anomalies", []),
        "duplicate": duplicate,
        "supplierCreated": supplier_created,
        "supplierId": supplier_id or "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    expense_dict = {
        "supplierType": "formal",
        "concept": concept,
        "category": category,
        "currency": "DOP",
        "exchangeRate": 1.0,
        "amountOriginal": total,
        "amount": total,
        "date": date[:10] if date else "",
        "rncEmisor": supplier_rnc,
        "providerName": supplier_name,
        "ncf": encf,
        "isMinorExpense": False,
        "isSyncedWithDGII": False,
        "qrCodeURL": "",
        "xmlSignature": "",
        "notes": f"Importado de XML e-CF. Proveedor: {supplier_name}",
        "isRecurring": is_recurring,
        "recurrenceInterval": recurrence_interval,
        "nextOccurrenceDate": "",
        "recurrenceEndDate": "",
        "associatedInvoiceId": "",
        "itbisAmountOriginal": itbis,
        "itbisAmount": itbis,
        "isITBISDeductible": is_deductible,
        "isDeductible": is_deductible,
        "firebaseAttachmentURLs": [],
        "attachments": [],
        "ecfType": ecf_type,
        "ecfNumber": encf,
        "cne": "",
        "tipoGastoDGII": tipo_gasto,
        "paymentType": payment_type,
        "cxpStatus": "Pagado" if payment_type == "Contado" else "Pendiente",
        "cxpRemainingBalance": 0.0 if payment_type == "Contado" else total,
        "approvalStatus": "Aprobado",
        "requestedBy": session['user'].get('name', 'Usuario'),
        "approvedBy": session['user'].get('name', 'Usuario'),
        "dueDate": "",
        "encf": encf,
        "emisionMode": "",
        "trackId": "",
        "xmlContent": "",
        "supplierId": supplier_id or "",
        "_importMeta": importMeta,
    }

    try:
        DatabaseService.save_expense(owner_uid, expense_id, expense_dict, sandbox=sandbox)
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400

    from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_GASTOS
    AuditService.log_from_request(
        owner_uid=owner_uid, action=ACTION_CREATE, module=MODULE_GASTOS,
        entity_id=expense_id,
        entity_label=f"Gasto importado de XML: {concept} (RD$ {total:.2f})",
        user_session=session.get('user', {}), after=expense_dict, sandbox=sandbox
    )

    flash(f'Gasto importado exitosamente. {ecf_type} - {encf}', 'success')
    return jsonify({
        "success": True,
        "expense_id": expense_id,
        "redirect": url_for("web_invoices.expense_import_report", expense_id=expense_id),
    })


@web_invoices_bp.route('/expenses/import/report/<expense_id>')
def expense_import_report(expense_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Informe de Importación", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    from app.services.db_service import DatabaseService
    expense = DatabaseService.get_expense(owner_uid, expense_id, sandbox=sandbox)

    if not expense:
        flash('El gasto no fue encontrado.', 'error')
        return redirect(url_for('web_invoices.expense_import_page'))

    report_data = expense.get("_importMeta", {})

    total = report_data.get("total", 0)
    itbis = report_data.get("itbis", 0)

    alerts = []
    if report_data.get("duplicate") and report_data["duplicate"].get("duplicate"):
        d = report_data["duplicate"]
        alerts.append({
            "type": "warning",
            "icon": "fa-triangle-exclamation",
            "title": "Posible gasto duplicado",
            "message": f"Ya existe un gasto similar de {d.get('existingConcept', '')} por RD$ {float(d.get('existingAmount', 0)):,.2f} del {d.get('existingDate', '')}.",
        })
    for anomaly in report_data.get("anomalies", []):
        alerts.append({
            "type": "warning",
            "icon": "fa-triangle-exclamation",
            "title": "Anomalía detectada",
            "message": anomaly,
        })
    ai_conf = report_data.get("aiConfidence", 0)
    if ai_conf and ai_conf < 0.7:
        alerts.append({
            "type": "info",
            "icon": "fa-circle-info",
            "title": "Clasificación con poca confianza",
            "message": f"La IA clasificó este gasto con solo {round(ai_conf * 100)}% de confianza. Revise la categoría y el tipo de gasto asignados.",
        })
    if itbis == 0 and total > 100000:
        alerts.append({
            "type": "info",
            "icon": "fa-circle-info",
            "title": "Monto elevado sin ITBIS",
            "message": "El monto del documento es superior a RD$ 100,000 pero no incluye ITBIS. Verifique si el proveedor está exento.",
        })
    if report_data.get("supplierCreated"):
        alerts.append({
            "type": "info",
            "icon": "fa-building",
            "title": "Nuevo proveedor registrado",
            "message": f"El proveedor {report_data.get('supplierName', '')} fue creado automáticamente durante la importación.",
        })

    return render_template('expenses/import_report.html',
                           expense=expense, report=report_data, alerts=alerts,
                           active_page='expenses')


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
    filename = file.filename or ""
    if filename.lower().endswith(('.heic', '.heif')):
        mime_type = "image/heic"
        
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
    sender_name = session['user'].get('name', session['user'].get('email', 'Usuario'))
    from app.services.ai_service import AIService
    message = AIService.draft_collection_message(owner_uid, client_name, amount, due_date, status, tone, sender_name=sender_name)
    return jsonify({"success": True, "message": message})


@web_invoices_bp.route('/api/invoices/search', methods=['GET'])
def api_search_invoices():
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({"success": True, "results": []})
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    results = DatabaseService.search_invoices_by_number(owner_uid, q, sandbox=sandbox)
    return jsonify({"success": True, "results": results})

@web_invoices_bp.route('/api/dgii/rnc/<rnc>', methods=['GET'])
def web_lookup_rnc(rnc):
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    try:
        res = DGIIService.validate_and_fetch_rnc(rnc)
        return jsonify(res)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _get_taggable_users(owner_uid):
    taggable_users = []
    owner_prof = DatabaseService.get_user_profile(owner_uid)
    if owner_prof:
        taggable_users.append({
            "uid": owner_uid,
            "name": owner_prof.get("name", "Propietario"),
            "email": owner_prof.get("email", ""),
            "role": "owner"
        })
    team = DatabaseService.get_team_members(owner_uid) or []
    for member in team:
        taggable_users.append({
            "uid": member.get("uid"),
            "name": member.get("name", ""),
            "email": member.get("email", ""),
            "role": member.get("role", "collaborator")
        })
    return taggable_users


def process_resource_comment_mentions(owner_uid, content, resource_type, resource_id, resource_label, sandbox):
    taggable_users = _get_taggable_users(owner_uid)
    for u in taggable_users:
        name = u.get("name", "")
        email = u.get("email", "")
        uid = u.get("uid")
        if not uid or not email:
            continue
            
        if 'user' in session and session['user'].get('uid') == uid:
            continue
            
        import re
        import html
        escaped_name = re.escape(name)
        escaped_email = re.escape(email)
        pattern = rf"@({escaped_name}|{escaped_email})\b"
        if re.search(pattern, content, re.IGNORECASE):
            notif_id = str(uuid.uuid4())
            
            if resource_type == "expenses":
                link = f"/expenses/{resource_id}?sandbox={'true' if sandbox else 'false'}"
                msg = f"{session['user'].get('name', session['user']['email'])} te mencionó en un comentario del gasto: {resource_label}."
            elif resource_type == "contracts":
                link = f"/contracts/{resource_id}?sandbox={'true' if sandbox else 'false'}"
                msg = f"{session['user'].get('name', session['user']['email'])} te mencionó en un comentario del contrato: {resource_label}."
            elif resource_type == "shifts":
                link = f"/pos/admin/shift/{resource_id}?sandbox={'true' if sandbox else 'false'}"
                msg = f"{session['user'].get('name', session['user']['email'])} te mencionó en un comentario del turno de caja: {resource_label}."
            else:
                link = f"/invoices/{resource_id}?sandbox={'true' if sandbox else 'false'}"
                msg = f"{session['user'].get('name', session['user']['email'])} te mencionó en un comentario del documento {resource_label}."
                
            notif_dict = {
                "id": notif_id,
                "title": "Nueva mención en un comentario",
                "message": msg,
                "documentId": resource_id,
                "documentNumber": resource_label,
                "link": link,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "read": False,
                "type": "mention"
            }
            DatabaseService.create_user_notification(uid, notif_dict)
            
            from flask import request
            try:
                base_url = request.host_url.rstrip('/')
            except Exception:
                base_url = os.environ.get("PORTAL_BASE_URL", "http://localhost:5001").rstrip('/')
            doc_url = f"{base_url}{link}"
            
            from app.services.notifications import NotificationService
            
            # Obtener el nombre comercial de la empresa
            company = DatabaseService.get_company(owner_uid) or {}
            issuer_company_name = company.get("tradeName") or company.get("companyName") or get_product_name()
            
            NotificationService.send_mention_notification(
                recipient_email=email,
                recipient_name=name,
                commenter_name=session['user'].get('name', session['user']['email']),
                comment_snippet=content[:150] + ("..." if len(content) > 150 else ""),
                doc_number=resource_label,
                doc_url=doc_url,
                issuer_company_name=issuer_company_name,
                sandbox=sandbox
            )


@web_invoices_bp.route('/expenses/<expense_id>')
def expense_detail(expense_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Detalle de Gasto", required_permission="canExpenses")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    expense = DatabaseService.get_expense(owner_uid, expense_id, sandbox=sandbox)
    if not expense:
        flash('Gasto no encontrado.', 'error')
        return redirect(url_for('web_invoices.list_expenses'))
        
    comments = DatabaseService.get_resource_comments(owner_uid, "expenses", expense_id, sandbox=sandbox)
    taggable_users = _get_taggable_users(owner_uid)
    
    is_cxp = expense.get('paymentType') == 'Crédito'
    cxp_payments = []
    if is_cxp:
        cxp_payments = DatabaseService.get_cxp_payments(owner_uid, expense_id, sandbox=sandbox)

    linked_entry = None
    all_entries = DatabaseService.get_accounting_entries(owner_uid, sandbox=sandbox)
    for e in all_entries:
        if e.get("status") != "voided" and e.get("referenceType") == "expense" and e.get("referenceId") == expense_id:
            linked_entry = e
            break
        
    return render_template(
        'expenses/detail.html',
        active_page='expenses',
        expense=expense,
        comments=comments,
        taggable_users=taggable_users,
        is_cxp=is_cxp,
        cxp_payments=cxp_payments,
        format_mentions=format_mentions,
        linked_entry=linked_entry,
    )


@web_invoices_bp.route('/expenses/<expense_id>/attach', methods=['POST'])
def attach_expense_document(expense_id):
    """Agrega documentos a un gasto existente sin pasar por el flujo de edición completo."""
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    expense = DatabaseService.get_expense(owner_uid, expense_id, sandbox=sandbox)
    if not expense:
        return jsonify({"success": False, "error": "Gasto no encontrado."}), 404

    attachment_files = request.files.getlist('attachments[]')
    attachment_types = request.form.getlist('attachmentTypes[]')

    existing_attachments = expense.get('attachments', [])
    existing_urls = expense.get('firebaseAttachmentURLs', [])

    if not existing_attachments and existing_urls:
        existing_attachments = [{'url': u, 'type': 'otro', 'name': u.split('/')[-1].split('?')[0]} for u in existing_urls]

    new_attachments = list(existing_attachments)
    new_urls = list(existing_urls)
    uploaded_count = 0
    errors = []

    for i, att_file in enumerate(attachment_files):
        if att_file and att_file.filename:
            try:
                file_data = att_file.read()
                mime_type = att_file.content_type or "application/octet-stream"
                safe_name = att_file.filename.replace(' ', '_')
                dest_path = f"users/{owner_uid}/expenses/{expense_id}/{safe_name}"
                public_url = DatabaseService.upload_file_to_storage(file_data, dest_path, mime_type)
                att_type = attachment_types[i] if i < len(attachment_types) else 'otro'
                new_urls.append(public_url)
                new_attachments.append({'url': public_url, 'type': att_type, 'name': att_file.filename})
                uploaded_count += 1
            except Exception as e:
                errors.append(str(e))

    if uploaded_count > 0:
        from app.services.db_service import db_firestore, firebase_initialized
        if firebase_initialized:
            coll_name = "sandbox_expenses" if sandbox else "expenses"
            db_firestore.collection("users").document(owner_uid).collection(coll_name).document(expense_id).update({
                "attachments": new_attachments,
                "firebaseAttachmentURLs": new_urls
            })

    wants_json = request.headers.get('Accept', '').find('application/json') != -1 or request.args.get('format') == 'json'
    if wants_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            "success": uploaded_count > 0,
            "uploaded": uploaded_count,
            "errors": errors,
            "attachments": new_attachments,
        })

    if uploaded_count > 0:
        flash(f'{uploaded_count} documento(s) adjuntado(s) exitosamente.', 'success')
    else:
        flash('No se seleccionó ningún archivo válido.', 'warning')
    return redirect(url_for('web_invoices.expense_detail', expense_id=expense_id))


@web_invoices_bp.route('/expenses/<expense_id>/attach/<int:att_index>', methods=['POST'])
def detach_expense_document(expense_id, att_index):
    """Elimina un adjunto específico de un gasto por índice."""
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    expense = DatabaseService.get_expense(owner_uid, expense_id, sandbox=sandbox)
    if not expense:
        return jsonify({"success": False, "error": "Gasto no encontrado."}), 404

    existing_attachments = expense.get('attachments', [])
    existing_urls = expense.get('firebaseAttachmentURLs', [])

    if not existing_attachments and existing_urls:
        existing_attachments = [{'url': u, 'type': 'otro', 'name': u.split('/')[-1].split('?')[0]} for u in existing_urls]

    if att_index < 0 or att_index >= len(existing_attachments):
        return jsonify({"success": False, "error": "Índice de adjunto inválido."}), 400

    removed = existing_attachments.pop(att_index)
    new_urls = [a['url'] for a in existing_attachments]

    from app.services.db_service import db_firestore, firebase_initialized
    if firebase_initialized:
        coll_name = "sandbox_expenses" if sandbox else "expenses"
        db_firestore.collection("users").document(owner_uid).collection(coll_name).document(expense_id).update({
            "attachments": existing_attachments,
            "firebaseAttachmentURLs": new_urls
        })

    return jsonify({
        "success": True,
        "removed": removed.get('name', 'Documento'),
        "attachments": existing_attachments,
    })


@web_invoices_bp.route('/expenses/<expense_id>/comments/new', methods=['POST'])
def add_expense_comment(expense_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    content = request.form.get('content', '').strip()
    if not content:
        flash('El comentario no puede estar vacío.', 'error')
        return redirect(url_for('web_invoices.expense_detail', expense_id=expense_id))
        
    attachment_url = ""
    attachment_name = ""
    file = request.files.get('attachment')
    if file and file.filename:
        try:
            file_data = file.read()
            mime_type = file.mimetype or "application/octet-stream"
            filename = f"comment_expense_{expense_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
            destination_path = f"users/{owner_uid}/comments/{filename}"
            attachment_url = DatabaseService.upload_file_to_storage(file_data, destination_path, mime_type)
            attachment_name = file.filename
        except Exception as e:
            flash(f"Advertencia: No se pudo cargar el archivo adjunto: {html.escape(str(e))}", 'warning')
            
    comment_id = str(uuid.uuid4())
    comment_dict = {
        "content": content,
        "createdBy": session['user']['email'],
        "createdByName": session['user'].get('name', session['user']['email']),
        "createdByUid": session['user']['uid'],
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "attachmentUrl": attachment_url,
        "attachmentName": attachment_name,
        "edited": False
    }
    
    DatabaseService.save_resource_comment(owner_uid, "expenses", expense_id, comment_id, comment_dict, sandbox=sandbox)
    
    try:
        expense = DatabaseService.get_expense(owner_uid, expense_id, sandbox=sandbox) or {}
        concept = expense.get('concept', 'Gasto')
        process_resource_comment_mentions(owner_uid, content, "expenses", expense_id, concept, sandbox)
    except Exception as ex:
        print(f"⚠️ Error al procesar menciones en add_expense_comment: {ex}")
        
    flash('Comentario agregado exitosamente.', 'success')
    return redirect(url_for('web_invoices.expense_detail', expense_id=expense_id))


@web_invoices_bp.route('/expenses/<expense_id>/comments/<comment_id>/edit', methods=['POST'])
def edit_expense_comment(expense_id, comment_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    comments = DatabaseService.get_resource_comments(owner_uid, "expenses", expense_id, sandbox=sandbox)
    comment = next((c for c in comments if c['id'] == comment_id), None)
    if not comment:
        flash('Comentario no encontrado.', 'error')
        return redirect(url_for('web_invoices.expense_detail', expense_id=expense_id))
        
    is_owner = session['user'].get('role') == 'owner'
    is_author = session['user']['uid'] == comment.get('createdByUid')
    if not (is_owner or is_author):
        flash('No tienes permiso para editar este comentario.', 'error')
        return redirect(url_for('web_invoices.expense_detail', expense_id=expense_id))
        
    content = request.form.get('content', '').strip()
    if not content:
        flash('El comentario no puede estar vacío.', 'error')
        return redirect(url_for('web_invoices.expense_detail', expense_id=expense_id))
        
    comment['content'] = content
    comment['edited'] = True
    comment['editedAt'] = datetime.now(timezone.utc).isoformat()
    
    file = request.files.get('attachment')
    if file and file.filename:
        try:
            file_data = file.read()
            mime_type = file.mimetype or "application/octet-stream"
            filename = f"comment_expense_{expense_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
            destination_path = f"users/{owner_uid}/comments/{filename}"
            attachment_url = DatabaseService.upload_file_to_storage(file_data, destination_path, mime_type)
            comment['attachmentUrl'] = attachment_url
            comment['attachmentName'] = file.filename
        except Exception as e:
            flash(f"Advertencia: No se pudo cargar el archivo adjunto: {html.escape(str(e))}", 'warning')
            
    DatabaseService.save_resource_comment(owner_uid, "expenses", expense_id, comment_id, comment, sandbox=sandbox)
    
    try:
        expense = DatabaseService.get_expense(owner_uid, expense_id, sandbox=sandbox) or {}
        concept = expense.get('concept', 'Gasto')
        process_resource_comment_mentions(owner_uid, content, "expenses", expense_id, concept, sandbox)
    except Exception as ex:
        print(f"⚠️ Error al procesar menciones en edit_expense_comment: {ex}")
        
    flash('Comentario modificado.', 'success')
    return redirect(url_for('web_invoices.expense_detail', expense_id=expense_id))


@web_invoices_bp.route('/expenses/<expense_id>/comments/<comment_id>/delete', methods=['POST'])
def delete_expense_comment(expense_id, comment_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    comments = DatabaseService.get_resource_comments(owner_uid, "expenses", expense_id, sandbox=sandbox)
    comment = next((c for c in comments if c['id'] == comment_id), None)
    if not comment:
        flash('Comentario no encontrado.', 'error')
        return redirect(url_for('web_invoices.expense_detail', expense_id=expense_id))
        
    is_owner = session['user'].get('role') == 'owner'
    is_author = session['user']['uid'] == comment.get('createdByUid')
    if not (is_owner or is_author):
        flash('No tienes permiso para eliminar este comentario.', 'error')
        return redirect(url_for('web_invoices.expense_detail', expense_id=expense_id))
        
    DatabaseService.delete_resource_comment(owner_uid, "expenses", expense_id, comment_id, sandbox=sandbox)
    flash('Comentario eliminado.', 'success')
    return redirect(url_for('web_invoices.expense_detail', expense_id=expense_id))


@web_invoices_bp.route('/api/v1/comments/<resource_type>/<resource_id>/<comment_id>/react', methods=['POST'])
def api_toggle_comment_reaction(resource_type, resource_id, comment_id):
    if 'user' not in session: return jsonify({"success": False, "error": "No autorizado"}), 401
    
    owner_uid = session['user']['ownerUID']
    user_uid = session['user']['uid']
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.json or {}
    emoji = data.get('emoji', '👍')
    
    res = DatabaseService.toggle_comment_reaction(owner_uid, resource_type, resource_id, comment_id, user_uid, emoji, sandbox=sandbox)
    if res and res.get("success"):
        return jsonify(res)
    
    return jsonify({"success": False, "error": "Error al actualizar reacción"}), 500

@web_invoices_bp.route('/quotations/new/professional', methods=['GET', 'POST'])
def professional_quotation_route():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Cotización Personalizada", required_permission="canInvoice")
    
    if request.method == 'GET':
        owner_uid = session['user']['ownerUID']
        sandbox = session.get('is_sandbox_mode', True)
        catalog = [it for it in DatabaseService.get_items(owner_uid, sandbox=sandbox) if it.get('isActive', True)]
        
        initial_data_json = 'null'
        clone_id = request.args.get('clone')
        if clone_id:
            source = DatabaseService.get_invoice(owner_uid, clone_id, sandbox=sandbox)
            if source and source.get('isProfessional'):
                pd = source.get('professionalData', {})
                initial_data = {
                    "clientId": source.get('clientId', ''),
                    "clientName": source.get('clientName', ''),
                    "clientRNC": source.get('clientRNC', ''),
                    "clientContact": source.get('clientContact', ''),
                    "clientEmail": source.get('clientEmail', ''),
                    "clientPhone": source.get('clientPhone', ''),
                    "clientAddress": source.get('clientAddress', ''),
                    "subject": pd.get('subject', ''),
                    "items": [{
                        "code": i.get('code', ''), "name": i.get('name', ''),
                        "quantity": i.get('quantity', 1), "price": i.get('price', 0),
                        "itbisRate": i.get('itbisRate', 0.18), "discountRate": i.get('discountRate', 0),
                        "catalogId": i.get('catalogId', '')
                    } for i in source.get('items', [])],
                    "scopeIncluded": pd.get('scopeIncluded', []),
                    "scopeExcluded": pd.get('scopeExcluded', []),
                    "deliverables": pd.get('deliverables', []),
                    "timeline": pd.get('timeline', []),
                    "paymentSchedule": pd.get('paymentSchedule', []),
                    "validityDays": pd.get('validityDays', 15),
                    "termsAndConditions": pd.get('termsAndConditions', ''),
                    "intellectualProperty": pd.get('intellectualProperty', ''),
                    "confidentiality": pd.get('confidentiality', ''),
                    "supportTerms": pd.get('supportTerms', ''),
                    "warrantyTerms": pd.get('warrantyTerms', ''),
                    "observations": pd.get('observations', ''),
                    "deliveryTimeTotal": pd.get('deliveryTimeTotal', ''),
                    "currency": pd.get('currency', source.get('currency', 'RD$')),
                    "paymentType": pd.get('paymentType', source.get('paymentType', 'Transferencia Bancaria')),
                    "paymentMethod": pd.get('paymentMethod', source.get('paymentMethod', 'Transferencia')),
                    "notes": source.get('notes', ''),
                    "discountRate": source.get('discountRate', 0)
                }
                initial_data_json = json.dumps(initial_data)
        
        return render_template('quotations/professional_new.html', catalog_json=json.dumps(catalog), initial_data_json=initial_data_json)
    
    # POST - save
    if 'user' not in session:
        return jsonify({"success": False, "message": "No autorizado"}), 401
    if not check_permission('canInvoice'):
        return jsonify({"success": False, "message": "Sin permisos"}), 403

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    data = request.json or {}
    user_display = session['user'].get('displayName', session['user'].get('email', 'Usuario'))

    items = []
    for item in data.get('items', []):
        price = float(item.get('price', 0))
        qty = float(item.get('quantity', 1))
        itbis_rate = float(item.get('itbisRate', 0.18))
        discount_rate = float(item.get('discountRate', 0)) / 100.0
        subtotal = price * qty
        discount_amt = subtotal * discount_rate
        itbis_amt = (subtotal - discount_amt) * itbis_rate
        total = subtotal - discount_amt + itbis_amt
        items.append({
            "code": item.get('code', ''),
            "name": item.get('name', ''),
            "quantity": qty,
            "price": price,
            "itbisRate": itbis_rate,
            "discountRate": discount_rate,
            "catalogId": item.get('catalogId', ''),
            "subtotal": round(subtotal, 2),
            "discountAmount": round(discount_amt, 2),
            "itbis_amount": round(itbis_amt, 2),
            "total": round(total, 2)
        })

    subtotal = sum(item['subtotal'] for item in items)
    total_itbis = sum(item['itbis_amount'] for item in items)
    total_discount = sum(item['discountAmount'] for item in items)
    total = subtotal + total_itbis - total_discount

    import random
    inv_number = f"COT-{random.randint(1, 999999):06d}"
    now = datetime.now(timezone.utc).isoformat()

    professional_data = {
        "subject": data.get('subject', ''),
        "scopeIncluded": data.get('scopeIncluded', []),
        "scopeExcluded": data.get('scopeExcluded', []),
        "deliverables": data.get('deliverables', []),
        "timeline": data.get('timeline', []),
        "paymentSchedule": data.get('paymentSchedule', []),
        "validityDays": int(data.get('validityDays', 15)),
        "termsAndConditions": data.get('termsAndConditions', ''),
        "intellectualProperty": data.get('intellectualProperty', ''),
        "confidentiality": data.get('confidentiality', ''),
        "supportTerms": data.get('supportTerms', ''),
        "warrantyTerms": data.get('warrantyTerms', ''),
        "observations": data.get('observations', ''),
        "deliveryTimeTotal": data.get('deliveryTimeTotal', ''),
        "currency": data.get('currency', 'RD$'),
        "paymentType": data.get('paymentType', 'Transferencia Bancaria'),
        "paymentMethod": data.get('paymentMethod', 'Transferencia'),
    }

    invoice_dict = {
        "owner_uid": owner_uid,
        "invoiceNumber": inv_number,
        "date": now,
        "dueDate": now,
        "ecfType": "Cotización",
        "isQuotation": True,
        "isProfessional": True,
        "professionalData": professional_data,
        "clientId": data.get('clientId', ''),
        "clientName": data.get('clientName', 'Cliente'),
        "clientRNC": data.get('clientRNC', ''),
        "clientContact": data.get('clientContact', ''),
        "clientEmail": data.get('clientEmail', ''),
        "clientPhone": data.get('clientPhone', ''),
        "clientAddress": data.get('clientAddress', ''),
        "items": items,
        "subtotal": round(subtotal, 2),
        "totalITBIS": round(total_itbis, 2),
        "discountAmount": round(total_discount, 2),
        "total": round(total, 2),
        "netPayable": round(total, 2),
        "currency": data.get('currency', 'RD$'),
        "paymentType": data.get('paymentType', 'Transferencia Bancaria'),
        "paymentMethod": data.get('paymentMethod', 'Transferencia'),
        "notes": data.get('notes', ''),
        "status": "Borrador",
        "createdBy": user_display,
        "createdAt": now,
        "updatedAt": now,
        "isConvertedToInvoice": False,
    }

    try:
        new_invoice_id = str(uuid.uuid4())
        invoice_dict['id'] = new_invoice_id
        result = DatabaseService.save_invoice(owner_uid, new_invoice_id, invoice_dict, sandbox=sandbox)
        if result and result.get('id'):
            from app.services.audit_service import AuditService
            AuditService.log_from_request(
                owner_uid=owner_uid,
                action="CREATE",
                module="Cotizaciones",
                entity_id=new_invoice_id,
                entity_label=f"Cotización profesional {inv_number} creada",
                user_session=session.get('user', {}),
                sandbox=sandbox
            )
            return jsonify({"success": True, "id": new_invoice_id, "redirect": url_for('web_invoices.invoice_detail', invoice_id=new_invoice_id)})
        return jsonify({"success": False, "message": "Error al guardar la cotización"}), 500
    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

@web_invoices_bp.route('/api/quotations/ai-generate', methods=['POST'])
def ai_generate_quotation():
    if 'user' not in session:
        return jsonify({"success": False, "message": "No autorizado"}), 401
    owner_uid = session['user']['ownerUID']
    data = request.json or {}
    context = data.get('context', '')

    if not context.strip():
        return jsonify({"success": False, "message": "Debe proporcionar contexto del proyecto"}), 400

    from app.services.ai_quotation_service import AIQuotationService
    company = DatabaseService.get_company_profile(owner_uid) or {}
    result = AIQuotationService.generate_full_quotation(owner_uid, context, company)

    if result.get("success"):
        return jsonify({"success": True, "data": result["data"]})
    return jsonify({"success": False, "message": result.get("message", "Error al generar con IA")}), 500

@web_invoices_bp.route('/api/quotations/ai-suggest-section', methods=['POST'])
def ai_suggest_section():
    if 'user' not in session:
        return jsonify({"success": False, "message": "No autorizado"}), 401
    owner_uid = session['user']['ownerUID']
    data = request.json or {}
    section = data.get('section', '')
    context_data = data.get('contextData', {})

    if not section:
        return jsonify({"success": False, "message": "Sección requerida"}), 400

    from app.services.ai_quotation_service import AIQuotationService
    result = AIQuotationService.suggest_section(owner_uid, section, context_data)

    if result.get("success"):
        try:
            import json as json_module
            content = result["content"]
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            parsed = json_module.loads(content.strip())
            return jsonify({"success": True, "data": parsed})
        except Exception:
            return jsonify({"success": True, "data": {"raw": result["content"]}})
    return jsonify({"success": False, "message": result.get("message", "Error")}), 500

@web_invoices_bp.route('/api/quotations/preview', methods=['POST'])
def quotation_preview():
    """
    Renderiza el mismo template PDF con los datos del formulario para vista previa en vivo.
    Usa el mismo template de PDF que se usará para el documento final.
    """
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    data = request.json or {}

    company = DatabaseService.get_company_profile(owner_uid) or {}
    if not company:
        company = {"companyName": "Mi Empresa", "companyRNC": "", "companyAddress": "", "companyPhone": "", "companyEmail": "", "tradeName": ""}

    items = []
    for item in data.get('items', []):
        price = float(item.get('price', 0))
        qty = float(item.get('quantity', 1))
        itbis_rate = float(item.get('itbisRate', 0.18) or 0.18)
        discount_rate = float(item.get('discountRate', 0) or 0) / 100.0
        subtotal = price * qty
        discount_amt = subtotal * discount_rate
        itbis_amt = (subtotal - discount_amt) * itbis_rate
        total = subtotal - discount_amt + itbis_amt
        items.append({
            "code": item.get('code', ''),
            "name": item.get('name', ''),
            "quantity": qty,
            "price": price,
            "itbisRate": itbis_rate,
            "discountRate": discount_rate,
            "catalogId": item.get('catalogId', ''),
            "subtotal": round(subtotal, 2),
            "discountAmount": round(discount_amt, 2),
            "itbis_amount": round(itbis_amt, 2),
            "total": round(total, 2)
        })

    subtotal = sum(item['subtotal'] for item in items)
    total_itbis = sum(item['itbis_amount'] for item in items)
    total_discount = sum(item['discountAmount'] for item in items)
    total = subtotal + total_itbis - total_discount

    import random
    inv_number = f"COT-{random.randint(1, 999999):06d}"

    from datetime import datetime as dt_module
    now = dt_module.now()

    professional_data = {
        "subject": data.get('subject', ''),
        "scopeIncluded": data.get('scopeIncluded', []),
        "scopeExcluded": data.get('scopeExcluded', []),
        "deliverables": data.get('deliverables', []),
        "timeline": data.get('timeline', []),
        "paymentSchedule": data.get('paymentSchedule', []),
        "validityDays": int(data.get('validityDays', 15)),
        "termsAndConditions": data.get('termsAndConditions', ''),
        "intellectualProperty": data.get('intellectualProperty', ''),
        "confidentiality": data.get('confidentiality', ''),
        "supportTerms": data.get('supportTerms', ''),
        "warrantyTerms": data.get('warrantyTerms', ''),
        "observations": data.get('observations', ''),
        "deliveryTimeTotal": data.get('deliveryTimeTotal', ''),
        "currency": data.get('currency', 'RD$'),
        "paymentType": data.get('paymentType', 'Transferencia Bancaria'),
        "paymentMethod": data.get('paymentMethod', 'Transferencia'),
    }

    invoice = {
        "invoiceNumber": inv_number,
        "date": now.isoformat(),
        "dueDate": now.isoformat(),
        "isQuotation": True,
        "isProfessional": True,
        "professionalData": professional_data,
        "clientName": data.get('clientName', 'Cliente'),
        "clientRNC": data.get('clientRNC', ''),
        "clientContact": data.get('clientContact', ''),
        "clientEmail": data.get('clientEmail', ''),
        "clientPhone": data.get('clientPhone', ''),
        "clientAddress": data.get('clientAddress', ''),
        "items": items,
        "subtotal": round(subtotal, 2),
        "totalITBIS": round(total_itbis, 2),
        "discountAmount": round(total_discount, 2),
        "total": round(total, 2),
        "netPayable": round(total, 2),
        "currency": data.get('currency', 'RD$'),
        "paymentType": data.get('paymentType', 'Transferencia Bancaria'),
        "paymentMethod": data.get('paymentMethod', 'Transferencia'),
        "notes": data.get('notes', ''),
        "status": "Borrador",
        "encf": None,
        "xmlSignature": None,
        "comentario": data.get('comentario', ''),
        "footer": data.get('footer', ''),
    }

    try:
        rendered = render_template('invoices/pdf.html', invoice=invoice, company=company, qr_base64=None, sandbox=sandbox, auto_print=False, fecha_firma_str=None)
        return rendered, 200, {'Content-Type': 'text/html; charset=utf-8'}
    except Exception as e:
        return f"<div style='padding:20px;color:red;'>Error en preview: {str(e)}</div>", 200


if __name__ == '__main__':
    app.run(debug=True, port=5001)


@web_invoices_bp.route('/api/currency/rate/<currency>', methods=['GET'])
def get_currency_rate_api(currency):
    try:
        from app.utils.currency import CurrencyService
        rate = CurrencyService.get_rate(currency)
        return jsonify({"success": True, "currency": currency, "rate": rate})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
