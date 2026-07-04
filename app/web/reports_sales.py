import csv
import io
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, jsonify, session, send_file, redirect, url_for
from app.services.db_service import DatabaseService
from app.utils.decorators import check_permission
from collections import defaultdict

web_reports_sales_bp = Blueprint('web_reports_sales', __name__)

MONTH_NAMES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]
MONTH_FILTER_OPTIONS = [(0, "Todo el año")] + [(idx + 1, name) for idx, name in enumerate(MONTH_NAMES)]


def get_sales_data(owner_uid, sandbox, year, month, warehouse_id=None, series=None):
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    real = [inv for inv in invoices
            if not inv.get('isQuotation')
            and inv.get('status') not in ('Anulada', 'Borrador', 'Consolidada')]
    if not real:
        return None

    filtered = []
    for inv in real:
        inv_date = (inv.get('date') or inv.get('createdAt') or '')[:7]
        if inv_date and inv_date >= f"{year:04d}-01" and inv_date <= f"{year:04d}-12":
            if f"{year:04d}-{month:02d}" == inv_date:
                filtered.append(inv)
            elif month == 0:
                filtered.append(inv)

    if not filtered:
        return None

    total_bruto = sum(inv.get('subtotal', 0) for inv in filtered)
    total_credit_notes = sum(inv.get('creditedAmount', 0) for inv in filtered)

    antes_impuestos = total_bruto - total_credit_notes
    total_impuestos = sum(inv.get('totalITBIS', 0) for inv in filtered)
    despues_impuestos = antes_impuestos + total_impuestos
    total_neto = sum(inv.get('total', 0) for inv in filtered)

    monthly_data = {}
    for inv in filtered:
        m = (inv.get('date') or inv.get('createdAt') or '')[:7]
        if m:
            monthly_data.setdefault(m, {"bruto": 0, "impuestos": 0, "neto": 0})
            monthly_data[m]["bruto"] += inv.get('subtotal', 0)
            monthly_data[m]["impuestos"] += inv.get('totalITBIS', 0)
            monthly_data[m]["neto"] += inv.get('total', 0)

    months_sorted = sorted(monthly_data.keys())
    labels = []
    bruto_data = []
    impuestos_data = []
    neto_data = []
    for m in months_sorted:
        labels.append(m)
        bruto_data.append(round(monthly_data[m]["bruto"], 2))
        impuestos_data.append(round(monthly_data[m]["impuestos"], 2))
        neto_data.append(round(monthly_data[m]["neto"], 2))

    return {
        "total_bruto": round(total_bruto, 2),
        "total_credit_notes": round(total_credit_notes, 2),
        "antes_impuestos": round(antes_impuestos, 2),
        "total_impuestos": round(total_impuestos, 2),
        "despues_impuestos": round(despues_impuestos, 2),
        "total_neto": round(total_neto, 2),
        "count_facturas": len(filtered),
        "chart_labels": labels,
        "chart_bruto": bruto_data,
        "chart_impuestos": impuestos_data,
        "chart_neto": neto_data,
    }


@web_reports_sales_bp.route('/reports/ventas')
def ventas_generales():
    if 'user' not in session:
        return render_template('auth/restricted.html', feature_name="Ventas generales")
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Ventas generales",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', 0))
    except ValueError:
        month = 0

    warehouse_id = request.args.get('warehouse', '')
    series = request.args.get('series', '')

    data = get_sales_data(owner_uid, sandbox, year, month, warehouse_id, series)

    years_range = list(range(now.year - 5, now.year + 1))
    months_list = [
        (0, "Todo el año"),
        (1, "Enero"), (2, "Febrero"), (3, "Marzo"),
        (4, "Abril"), (5, "Mayo"), (6, "Junio"),
        (7, "Julio"), (8, "Agosto"), (9, "Septiembre"),
        (10, "Octubre"), (11, "Noviembre"), (12, "Diciembre"),
    ]

    all_warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox)
    all_sequences = DatabaseService.get_sequences(owner_uid, sandbox=sandbox)
    invoice_types = ('e31', 'e32', 'e33', 'e34', 'factura de consumo', 'factura de crédito fiscal',
                     'factura gubernamental', 'factura régimen especial')
    invoice_sequences = [s for s in all_sequences
                         if s.get('tipoComprobante', '').lower().replace(' ', '') in
                         [t.lower().replace(' ', '') for t in invoice_types]]
    if not invoice_sequences:
        invoice_sequences = all_sequences

    return render_template('reports/ventas_generales.html',
                           active_page='ventas_generales',
                           data=data,
                           year=year, month=month,
                           years_range=years_range,
                           months_list=months_list,
                           warehouses=all_warehouses,
                           warehouse_id=warehouse_id,
                           series=series,
                           invoice_sequences=invoice_sequences)


@web_reports_sales_bp.route('/reports/ventas/export')
def ventas_generales_export():
    if 'user' not in session:
        return render_template('auth/restricted.html', feature_name="Ventas generales")
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Ventas generales",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', 0))
    except ValueError:
        month = 0

    data = get_sales_data(owner_uid, sandbox, year, month)
    if not data:
        return render_template('auth/restricted.html', feature_name="Ventas generales",
                               custom_message="No hay datos de ventas para exportar.")

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['Métrica', 'Valor'])
    writer.writerow(['Ventas brutas', data['total_bruto']])
    writer.writerow(['Notas crédito', data['total_credit_notes']])
    writer.writerow(['Antes de impuestos', data['antes_impuestos']])
    writer.writerow(['Impuestos', data['total_impuestos']])
    writer.writerow(['Después de impuestos', data['despues_impuestos']])
    writer.writerow(['Total ventas', data['total_neto']])
    writer.writerow([])
    writer.writerow(['Mes', 'Ventas brutas', 'Impuestos', 'Total'])
    for i, label in enumerate(data['chart_labels']):
        writer.writerow([label, data['chart_bruto'][i], data['chart_impuestos'][i], data['chart_neto'][i]])

    buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    return send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'ventas_generales_{year}_{month if month else "anual"}.csv'
    )


def get_product_sales_data(owner_uid, sandbox, year, month, item_type=None):
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    real = [inv for inv in invoices
            if not inv.get('isQuotation')
            and inv.get('status') not in ('Anulada', 'Borrador', 'Consolidada')]
    if not real:
        return [], 0, 0

    filtered = []
    for inv in real:
        inv_date = (inv.get('date') or inv.get('createdAt') or '')[:7]
        if inv_date and inv_date >= f"{year:04d}-01" and inv_date <= f"{year:04d}-12":
            if f"{year:04d}-{month:02d}" == inv_date:
                filtered.append(inv)
            elif month == 0:
                filtered.append(inv)

    if not filtered:
        return [], 0, 0

    products = defaultdict(lambda: {"code": "", "name": "", "type": "", "quantity": 0, "subtotal": 0.0, "itbis": 0.0, "total": 0.0})

    for inv in filtered:
        for item in inv.get('items', []):
            code = item.get('code', '') or item.get('id', '')
            name = item.get('name', 'Sin nombre')
            it_type = item.get('type', 'Bien')
            if item_type and it_type != item_type:
                continue
            key = code or name
            p = products[key]
            p["code"] = code
            p["name"] = name
            p["type"] = it_type
            p["quantity"] += int(item.get('quantity', 1))
            p["subtotal"] += float(item.get('subtotal', 0))
            p["itbis"] += float(item.get('itbisAmount', 0))
            p["total"] += float(item.get('total', 0))

    result = []
    for key, p in products.items():
        result.append({
            "code": p["code"],
            "name": p["name"],
            "type": p["type"],
            "quantity": p["quantity"],
            "subtotal": round(p["subtotal"], 2),
            "itbis": round(p["itbis"], 2),
            "total": round(p["total"], 2),
        })

    result.sort(key=lambda x: x["total"], reverse=True)
    total_antes = round(sum(r["subtotal"] for r in result), 2)
    total_despues = round(sum(r["total"] for r in result), 2)
    return result, total_antes, total_despues


@web_reports_sales_bp.route('/reports/ventas/producto')
def ventas_por_producto():
    if 'user' not in session:
        return render_template('auth/restricted.html', feature_name="Ventas por producto/servicio")
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Ventas por producto/servicio",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', 0))
    except ValueError:
        month = 0
    item_type = request.args.get('type', '')

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get('per_page', 10))
    except ValueError:
        per_page = 10
    if per_page < 1:
        per_page = 10

    all_products, total_antes, total_despues = get_product_sales_data(owner_uid, sandbox, year, month, item_type)

    total_items = len(all_products)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated = all_products[start_idx:end_idx]

    start_count = start_idx + 1 if total_items > 0 else 0
    end_count = min(page * per_page, total_items)

    years_range = list(range(now.year - 5, now.year + 1))
    months_list = [
        (0, "Todo el año"),
        (1, "Enero"), (2, "Febrero"), (3, "Marzo"),
        (4, "Abril"), (5, "Mayo"), (6, "Junio"),
        (7, "Julio"), (8, "Agosto"), (9, "Septiembre"),
        (10, "Octubre"), (11, "Noviembre"), (12, "Diciembre"),
    ]

    return render_template('reports/ventas_por_producto.html',
                           active_page='ventas_por_producto',
                           products=paginated,
                           total_antes=total_antes,
                           total_despues=total_despues,
                           total_items=total_items,
                           total_pages=total_pages,
                           page=page,
                           per_page=per_page,
                           start_count=start_count,
                           end_count=end_count,
                           year=year, month=month,
                           item_type=item_type,
                           years_range=years_range,
                           months_list=months_list)


@web_reports_sales_bp.route('/reports/ventas/producto/export')
def ventas_por_producto_export():
    if 'user' not in session:
        return render_template('auth/restricted.html', feature_name="Ventas por producto/servicio")
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Ventas por producto/servicio",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', 0))
    except ValueError:
        month = 0
    item_type = request.args.get('type', '')

    all_products, total_antes, total_despues = get_product_sales_data(owner_uid, sandbox, year, month, item_type)

    if not all_products:
        return render_template('auth/restricted.html', feature_name="Ventas por producto/servicio",
                               custom_message="No hay datos para exportar.")

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['Producto/Servicio', 'Referencia', 'Tipo', 'Cantidad', 'Antes de impuestos', 'ITBIS', 'Después de impuestos'])
    for p in all_products:
        writer.writerow([p['name'], p['code'], p['type'], p['quantity'], p['subtotal'], p['itbis'], p['total']])
    writer.writerow([])
    writer.writerow(['Totales', '', '', '', total_antes, '', total_despues])

    buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    return send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'ventas_por_producto_{year}_{month if month else "anual"}.csv'
    )


def get_client_sales_data(owner_uid, sandbox, year, month):
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    real = [inv for inv in invoices
            if not inv.get('isQuotation')
            and inv.get('status') not in ('Anulada', 'Borrador', 'Consolidada')]
    if not real:
        return [], 0, 0

    filtered = []
    for inv in real:
        inv_date = (inv.get('date') or inv.get('createdAt') or '')[:7]
        if inv_date and inv_date >= f"{year:04d}-01" and inv_date <= f"{year:04d}-12":
            if f"{year:04d}-{month:02d}" == inv_date:
                filtered.append(inv)
            elif month == 0:
                filtered.append(inv)

    if not filtered:
        return [], 0, 0

    clients = defaultdict(lambda: {"name": "", "rnc": "", "count": 0, "subtotal": 0.0, "itbis": 0.0, "total": 0.0})

    for inv in filtered:
        cid = inv.get('clientId', '') or inv.get('clientName', '') or 'sin-cliente'
        name = inv.get('clientName', '').strip() or 'Consumidor Final'
        rnc = inv.get('clientRNC', '').strip()
        if not name and not rnc:
            name = 'Consumidor Final'

        c = clients[cid]
        c["name"] = name
        c["rnc"] = rnc
        c["count"] += 1
        c["subtotal"] += float(inv.get('subtotal', 0))
        c["itbis"] += float(inv.get('totalITBIS', 0))
        c["total"] += float(inv.get('total', 0))

    result = []
    for cid, c in clients.items():
        result.append({
            "client_id": cid,
            "name": c["name"],
            "rnc": c["rnc"],
            "count": c["count"],
            "subtotal": round(c["subtotal"], 2),
            "itbis": round(c["itbis"], 2),
            "total": round(c["total"], 2),
        })

    result.sort(key=lambda x: x["total"], reverse=True)
    total_antes = round(sum(r["subtotal"] for r in result), 2)
    total_despues = round(sum(r["total"] for r in result), 2)
    return result, total_antes, total_despues


@web_reports_sales_bp.route('/reports/ventas/cliente')
def ventas_por_cliente():
    if 'user' not in session:
        return render_template('auth/restricted.html', feature_name="Ventas por cliente")
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Ventas por cliente",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', 0))
    except ValueError:
        month = 0

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get('per_page', 10))
    except ValueError:
        per_page = 10
    if per_page < 1:
        per_page = 10

    all_clients, total_antes, total_despues = get_client_sales_data(owner_uid, sandbox, year, month)

    total_items = len(all_clients)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated = all_clients[start_idx:end_idx]

    start_count = start_idx + 1 if total_items > 0 else 0
    end_count = min(page * per_page, total_items)

    years_range = list(range(now.year - 5, now.year + 1))
    months_list = [
        (0, "Todo el año"),
        (1, "Enero"), (2, "Febrero"), (3, "Marzo"),
        (4, "Abril"), (5, "Mayo"), (6, "Junio"),
        (7, "Julio"), (8, "Agosto"), (9, "Septiembre"),
        (10, "Octubre"), (11, "Noviembre"), (12, "Diciembre"),
    ]

    return render_template('reports/ventas_por_cliente.html',
                           active_page='ventas_por_cliente',
                           clients=paginated,
                           total_antes=total_antes,
                           total_despues=total_despues,
                           total_items=total_items,
                           total_pages=total_pages,
                           page=page,
                           per_page=per_page,
                           start_count=start_count,
                           end_count=end_count,
                           year=year, month=month,
                           years_range=years_range,
                           months_list=months_list)


@web_reports_sales_bp.route('/reports/ventas/cliente/export')
def ventas_por_cliente_export():
    if 'user' not in session:
        return render_template('auth/restricted.html', feature_name="Ventas por cliente")
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Ventas por cliente",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', 0))
    except ValueError:
        month = 0

    all_clients, total_antes, total_despues = get_client_sales_data(owner_uid, sandbox, year, month)

    if not all_clients:
        return render_template('auth/restricted.html', feature_name="Ventas por cliente",
                               custom_message="No hay datos para exportar.")

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['Cliente', 'RNC', 'Documentos', 'Antes de impuestos', 'ITBIS', 'Después de impuestos'])
    for c in all_clients:
        writer.writerow([c['name'], c['rnc'], c['count'], c['subtotal'], c['itbis'], c['total']])
    writer.writerow([])
    writer.writerow(['Totales', '', '', total_antes, '', total_despues])

    buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    return send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'ventas_por_cliente_{year}_{month if month else "anual"}.csv'
    )


def get_profitability_data(owner_uid, sandbox, year, month, item_type=None):
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    real = [inv for inv in invoices
            if not inv.get('isQuotation')
            and inv.get('status') not in ('Anulada', 'Borrador', 'Consolidada')]
    if not real:
        return [], 0, 0, 0

    filtered = []
    for inv in real:
        inv_date = (inv.get('date') or inv.get('createdAt') or '')[:7]
        if inv_date and inv_date >= f"{year:04d}-01" and inv_date <= f"{year:04d}-12":
            if f"{year:04d}-{month:02d}" == inv_date:
                filtered.append(inv)
            elif month == 0:
                filtered.append(inv)

    if not filtered:
        return [], 0, 0, 0

    catalog_items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
    cost_by_code = {}
    for item in catalog_items:
        code = item.get('code', '') or item.get('id', '')
        if code:
            cost_by_code[code] = float(item.get('costPrice', 0))
            if item.get('id'):
                cost_by_code[item['id']] = float(item.get('costPrice', 0))

    products = defaultdict(lambda: {"code": "", "name": "", "type": "", "quantity": 0, "total_sold": 0.0, "total_cost": 0.0})

    for inv in filtered:
        for item in inv.get('items', []):
            code = item.get('code', '') or item.get('id', '')
            name = item.get('name', 'Sin nombre')
            it_type = item.get('type', 'Bien')
            if item_type and it_type != item_type:
                continue
            key = code or name
            qty = int(item.get('quantity', 1))
            total = float(item.get('total', 0))
            cost_price = cost_by_code.get(code, 0)
            p = products[key]
            p["code"] = code
            p["name"] = name
            p["type"] = it_type
            p["quantity"] += qty
            p["total_sold"] += total
            p["total_cost"] += cost_price * qty

    result = []
    for key, p in products.items():
        profit = p["total_sold"] - p["total_cost"]
        margin = (profit / p["total_sold"] * 100) if p["total_sold"] else 0
        result.append({
            "code": p["code"],
            "name": p["name"],
            "type": p["type"],
            "quantity": p["quantity"],
            "total_sold": round(p["total_sold"], 2),
            "total_cost": round(p["total_cost"], 2),
            "profit": round(profit, 2),
            "margin": round(margin, 2),
        })

    result.sort(key=lambda x: x["total_sold"], reverse=True)
    total_sold = round(sum(r["total_sold"] for r in result), 2)
    total_cost = round(sum(r["total_cost"] for r in result), 2)
    total_profit = round(total_sold - total_cost, 2)
    return result, total_sold, total_cost, total_profit


@web_reports_sales_bp.route('/reports/ventas/rentabilidad')
def ventas_rentabilidad():
    if 'user' not in session:
        return render_template('auth/restricted.html', feature_name="Rentabilidad por producto/servicio")
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Rentabilidad por producto/servicio",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', 0))
    except ValueError:
        month = 0
    item_type = request.args.get('type', '')

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get('per_page', 10))
    except ValueError:
        per_page = 10
    if per_page < 1:
        per_page = 10

    all_products, total_sold, total_cost, total_profit = get_profitability_data(owner_uid, sandbox, year, month, item_type)

    total_items = len(all_products)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated = all_products[start_idx:end_idx]

    start_count = start_idx + 1 if total_items > 0 else 0
    end_count = min(page * per_page, total_items)

    years_range = list(range(now.year - 5, now.year + 1))
    months_list = [
        (0, "Todo el año"),
        (1, "Enero"), (2, "Febrero"), (3, "Marzo"),
        (4, "Abril"), (5, "Mayo"), (6, "Junio"),
        (7, "Julio"), (8, "Agosto"), (9, "Septiembre"),
        (10, "Octubre"), (11, "Noviembre"), (12, "Diciembre"),
    ]

    return render_template('reports/ventas_rentabilidad.html',
                           active_page='ventas_rentabilidad',
                           products=paginated,
                           total_sold=total_sold,
                           total_cost=total_cost,
                           total_profit=total_profit,
                           total_items=total_items,
                           total_pages=total_pages,
                           page=page,
                           per_page=per_page,
                           start_count=start_count,
                           end_count=end_count,
                           year=year, month=month,
                           item_type=item_type,
                           years_range=years_range,
                           months_list=months_list)


@web_reports_sales_bp.route('/reports/ventas/rentabilidad/export')
def ventas_rentabilidad_export():
    if 'user' not in session:
        return render_template('auth/restricted.html', feature_name="Rentabilidad por producto/servicio")
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Rentabilidad por producto/servicio",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', 0))
    except ValueError:
        month = 0
    item_type = request.args.get('type', '')

    all_products, total_sold, total_cost, total_profit = get_profitability_data(owner_uid, sandbox, year, month, item_type)

    if not all_products:
        return render_template('auth/restricted.html', feature_name="Rentabilidad por producto/servicio",
                               custom_message="No hay datos para exportar.")

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['Producto/Servicio', 'Tipo', 'Cantidad', 'Total vendido', 'Costo total', 'Rentabilidad', 'Margen %'])
    for p in all_products:
        writer.writerow([p['name'], p['type'], p['quantity'], p['total_sold'], p['total_cost'], p['profit'], f"{p['margin']}%"])
    writer.writerow([])
    writer.writerow(['Totales', '', '', total_sold, total_cost, total_profit, ''])

    buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    return send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'rentabilidad_{year}_{month if month else "anual"}.csv'
    )


def get_seller_sales_data(owner_uid, sandbox, year, month, seller_filter=None):
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    real = [inv for inv in invoices
            if not inv.get('isQuotation')
            and inv.get('status') not in ('Anulada', 'Borrador', 'Consolidada')]
    if not real:
        return [], 0, 0, 0, []

    filtered = []
    for inv in real:
        inv_date = (inv.get('date') or inv.get('createdAt') or '')[:7]
        if inv_date and inv_date >= f"{year:04d}-01" and inv_date <= f"{year:04d}-12":
            if f"{year:04d}-{month:02d}" == inv_date:
                filtered.append(inv)
            elif month == 0:
                filtered.append(inv)

    if not filtered:
        return [], 0, 0, 0, []

    team = DatabaseService.get_team_members(owner_uid) or []
    email_to_name = {}
    for m in team:
        email = m.get('email', '') or m.get('uid', '')
        name = m.get('name', '') or email
        if email:
            email_to_name[email] = name

    seller_options = []
    seen = set()
    for inv in filtered:
        reg_by = inv.get('registeredBy', '') or 'Sistema'
        if reg_by not in seen:
            seen.add(reg_by)
            seller_options.append({
                "email": reg_by,
                "name": email_to_name.get(reg_by, reg_by),
            })
    seller_options.sort(key=lambda x: x["name"].lower())

    sellers = defaultdict(lambda: {"email": "", "name": "", "count": 0, "total_paid": 0.0, "subtotal": 0.0, "itbis": 0.0, "total": 0.0})

    for inv in filtered:
        reg_by = inv.get('registeredBy', '') or 'Sistema'
        if seller_filter and reg_by != seller_filter:
            continue
        name = email_to_name.get(reg_by, reg_by)
        total_paid = float(inv.get('totalPaid', 0)) or float(inv.get('total', 0))
        s = sellers[reg_by]
        s["email"] = reg_by
        s["name"] = name
        s["count"] += 1
        s["total_paid"] += total_paid
        s["subtotal"] += float(inv.get('subtotal', 0))
        s["itbis"] += float(inv.get('totalITBIS', 0))
        s["total"] += float(inv.get('total', 0))

    result = []
    for key, s in sellers.items():
        result.append({
            "email": s["email"],
            "name": s["name"],
            "count": s["count"],
            "total_paid": round(s["total_paid"], 2),
            "subtotal": round(s["subtotal"], 2),
            "itbis": round(s["itbis"], 2),
            "total": round(s["total"], 2),
        })

    result.sort(key=lambda x: x["total"], reverse=True)
    total_paid = round(sum(r["total_paid"] for r in result), 2)
    total_antes = round(sum(r["subtotal"] for r in result), 2)
    total_despues = round(sum(r["total"] for r in result), 2)

    return result, total_paid, total_antes, total_despues, seller_options


@web_reports_sales_bp.route('/reports/ventas/vendedor')
def ventas_por_vendedor():
    if 'user' not in session:
        return render_template('auth/restricted.html', feature_name="Ventas por vendedor")
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Ventas por vendedor",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', 0))
    except ValueError:
        month = 0
    seller_filter = request.args.get('seller', '')

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get('per_page', 10))
    except ValueError:
        per_page = 10
    if per_page < 1:
        per_page = 10

    all_sellers, total_paid, total_antes, total_despues, seller_options = \
        get_seller_sales_data(owner_uid, sandbox, year, month, seller_filter)

    total_items = len(all_sellers)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated = all_sellers[start_idx:end_idx]

    start_count = start_idx + 1 if total_items > 0 else 0
    end_count = min(page * per_page, total_items)

    years_range = list(range(now.year - 5, now.year + 1))
    months_list = [
        (0, "Todo el año"),
        (1, "Enero"), (2, "Febrero"), (3, "Marzo"),
        (4, "Abril"), (5, "Mayo"), (6, "Junio"),
        (7, "Julio"), (8, "Agosto"), (9, "Septiembre"),
        (10, "Octubre"), (11, "Noviembre"), (12, "Diciembre"),
    ]

    return render_template('reports/ventas_por_vendedor.html',
                           active_page='ventas_por_vendedor',
                           sellers=paginated,
                           total_paid=total_paid,
                           total_antes=total_antes,
                           total_despues=total_despues,
                           total_items=total_items,
                           total_pages=total_pages,
                           page=page,
                           per_page=per_page,
                           start_count=start_count,
                           end_count=end_count,
                           year=year, month=month,
                           seller_filter=seller_filter,
                           seller_options=seller_options,
                           years_range=years_range,
                           months_list=months_list)


@web_reports_sales_bp.route('/reports/ventas/vendedor/export')
def ventas_por_vendedor_export():
    if 'user' not in session:
        return render_template('auth/restricted.html', feature_name="Ventas por vendedor")
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Ventas por vendedor",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', 0))
    except ValueError:
        month = 0
    seller_filter = request.args.get('seller', '')

    all_sellers, total_paid, total_antes, total_despues, _ = \
        get_seller_sales_data(owner_uid, sandbox, year, month, seller_filter)

    if not all_sellers:
        return render_template('auth/restricted.html', feature_name="Ventas por vendedor",
                               custom_message="No hay datos para exportar.")

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['Vendedor', 'Documentos', 'Pagado', 'Antes de impuestos', 'ITBIS', 'Después de impuestos'])
    for s in all_sellers:
        writer.writerow([s['name'], s['count'], s['total_paid'], s['subtotal'], s['itbis'], s['total']])
    writer.writerow([])
    writer.writerow(['Totales', '', total_paid, total_antes, '', total_despues])

    buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    return send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'ventas_por_vendedor_{year}_{month if month else "anual"}.csv'
    )


def get_client_account_data(owner_uid, sandbox, client_id, year, month, aging_filter=None, search=None):
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    real = [inv for inv in invoices
            if not inv.get('isQuotation')
            and inv.get('status') not in ('Anulada', 'Borrador', 'Consolidada')]
    if not real:
        return {}, [], 0, 0, 0, 0, {}, []

    filtered = []
    for inv in real:
        cid = inv.get('clientId', '')
        if cid != client_id:
            continue
        inv_date = (inv.get('date') or inv.get('createdAt') or '')[:7]
        if not (inv_date and inv_date >= f"{year:04d}-01" and inv_date <= f"{year:04d}-12"):
            continue
        if f"{year:04d}-{month:02d}" == inv_date or month == 0:
            filtered.append(inv)

    if not filtered:
        return {}, [], 0, 0, 0, 0, {}, []

    total_ventas = 0.0
    total_retenciones = 0.0
    total_cobrado = 0.0
    total_saldo = 0.0

    aging = {"sin_vencer": 0, "1_30": 0, "31_60": 0, "61_90": 0, "91_plus": 0}
    now = datetime.now(timezone.utc)

    filtered_with_aging = []
    for inv in filtered:
        total = float(inv.get('total', 0))
        retained_isr = float(inv.get('retainedISR', 0))
        retained_itbis = float(inv.get('retainedITBIS', 0))
        total_paid = float(inv.get('totalPaid', 0))
        remaining = float(inv.get('remainingBalance', total - total_paid))
        retenciones = retained_isr + retained_itbis

        total_ventas += total
        total_retenciones += retenciones
        total_cobrado += total_paid

        due_str = inv.get('dueDate', '') or inv.get('date', '')
        try:
            due_date = datetime.fromisoformat(due_str) if due_str else now
            if due_date.tzinfo is None:
                due_date = due_date.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            due_date = now

        days_overdue = (now - due_date).days if due_date < now else 0
        balance = remaining

        if balance > 0 and days_overdue <= 0:
            aging["sin_vencer"] += balance
        elif balance > 0 and days_overdue <= 30:
            aging["1_30"] += balance
        elif balance > 0 and days_overdue <= 60:
            aging["31_60"] += balance
        elif balance > 0 and days_overdue <= 90:
            aging["61_90"] += balance
        elif balance > 0:
            aging["91_plus"] += balance

        aging_bucket = "sin_vencer" if days_overdue <= 0 else (
            "1_30" if days_overdue <= 30 else
            "31_60" if days_overdue <= 60 else
            "61_90" if days_overdue <= 90 else "91_plus"
        )

        if aging_filter and aging_filter != aging_bucket:
            continue

        inv_copy = dict(inv)
        inv_copy["_retenciones"] = round(retenciones, 2)
        inv_copy["_total_paid"] = round(total_paid, 2)
        inv_copy["_remaining"] = round(balance, 2)
        inv_copy["_days_overdue"] = days_overdue
        inv_copy["_aging_bucket"] = aging_bucket
        filtered_with_aging.append(inv_copy)

    total_saldo = total_ventas - total_cobrado

    # Recent payments (last 90 days)
    recent_payments = []
    for inv in filtered:
        payment_date_str = inv.get('paymentDate', '')
        total_paid = float(inv.get('totalPaid', 0))
        if payment_date_str and total_paid > 0:
            try:
                pd = datetime.fromisoformat(payment_date_str)
                if (now - pd).days <= 90:
                    recent_payments.append({
                        "invoice_number": inv.get('invoiceNumber', ''),
                        "date": payment_date_str[:10],
                        "amount": total_paid,
                        "remaining": float(inv.get('remainingBalance', 0)),
                    })
            except (ValueError, TypeError):
                pass
    recent_payments.sort(key=lambda x: x["date"], reverse=True)

    result = {
        "total_ventas": round(total_ventas, 2),
        "total_retenciones": round(total_retenciones, 2),
        "total_cobrado": round(total_cobrado, 2),
        "total_saldo": round(total_saldo, 2),
    }

    for k in aging:
        aging[k] = round(aging[k], 2)

    return result, filtered_with_aging, total_ventas, total_retenciones, total_cobrado, total_saldo, aging, recent_payments


@web_reports_sales_bp.route('/reports/ventas/estado-cuenta')
def ventas_estado_cuenta():
    if 'user' not in session:
        return render_template('auth/restricted.html', feature_name="Estado de cuenta por cliente")
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Estado de cuenta por cliente",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', 0))
    except ValueError:
        month = 0

    client_id = request.args.get('client_id', '')
    aging_filter = request.args.get('aging', '')
    search = request.args.get('search', '')

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get('per_page', 10))
    except ValueError:
        per_page = 10
    if per_page < 1:
        per_page = 10

    all_clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox) or []
    clients_list = [{"id": c.get("id", ""), "name": c.get("razonSocial", ""), "rnc": c.get("rnc", "")}
                    for c in all_clients if c.get("razonSocial")]
    clients_list.sort(key=lambda x: x["name"].lower())

    selected_client_name = ''
    summary = {}
    invoices_data = []
    total_ventas = total_retenciones = total_cobrado = total_saldo = 0
    aging = {"sin_vencer": 0, "1_30": 0, "31_60": 0, "61_90": 0, "91_plus": 0}
    recent_payments = []

    if client_id:
        for c in all_clients:
            if c.get("id") == client_id:
                selected_client_name = c.get("razonSocial", '')
                break
        if not selected_client_name:
            for inv in DatabaseService.get_invoices(owner_uid, sandbox=sandbox):
                if inv.get('clientId') == client_id:
                    selected_client_name = inv.get('clientName', 'Cliente')
                    break

        summary, invoices_data, total_ventas, total_retenciones, total_cobrado, total_saldo, aging, recent_payments = \
            get_client_account_data(owner_uid, sandbox, client_id, year, month, aging_filter, search)

    if search and invoices_data:
        s = search.lower()
        invoices_data = [inv for inv in invoices_data
                         if s in (inv.get('invoiceNumber', '') or '').lower()
                         or s in (inv.get('ecfType', '') or '').lower()
                         or s in (inv.get('encf', '') or '').lower()
                         or s in str(inv.get('total', 0))]

    total_items = len(invoices_data)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated = invoices_data[start_idx:end_idx]

    start_count = start_idx + 1 if total_items > 0 else 0
    end_count = min(page * per_page, total_items)

    years_range = list(range(now.year - 5, now.year + 1))
    months_list = [
        (0, "Todo el año"),
        (1, "Enero"), (2, "Febrero"), (3, "Marzo"),
        (4, "Abril"), (5, "Mayo"), (6, "Junio"),
        (7, "Julio"), (8, "Agosto"), (9, "Septiembre"),
        (10, "Octubre"), (11, "Noviembre"), (12, "Diciembre"),
    ]

    return render_template('reports/ventas_estado_cuenta.html',
                           active_page='ventas_estado_cuenta',
                           clients=clients_list,
                           client_id=client_id,
                           selected_client_name=selected_client_name,
                           summary=summary,
                           invoices=paginated,
                           total_items=total_items,
                           total_pages=total_pages,
                           page=page,
                           per_page=per_page,
                           start_count=start_count,
                           end_count=end_count,
                           total_ventas=total_ventas,
                           total_retenciones=total_retenciones,
                           total_cobrado=total_cobrado,
                           total_saldo=total_saldo,
                           aging=aging,
                           recent_payments=recent_payments,
                           year=year, month=month,
                           aging_filter=aging_filter,
                           search=search,
                           years_range=years_range,
                           months_list=months_list)


@web_reports_sales_bp.route('/reports/ventas/estado-cuenta/export')
def ventas_estado_cuenta_export():
    if 'user' not in session:
        return render_template('auth/restricted.html', feature_name="Estado de cuenta por cliente")
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Estado de cuenta por cliente",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', 0))
    except ValueError:
        month = 0
    client_id = request.args.get('client_id', '')

    summary, invoices_data, total_ventas, total_retenciones, total_cobrado, total_saldo, aging, recent_payments = \
        get_client_account_data(owner_uid, sandbox, client_id, year, month)

    if not invoices_data:
        return render_template('auth/restricted.html', feature_name="Estado de cuenta por cliente",
                               custom_message="No hay datos para exportar.")

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['Estado de cuenta por cliente'])
    writer.writerow(['Período', f'{year}-{month if month else "anual"}'])
    writer.writerow(['Cliente', client_id])
    writer.writerow([])
    writer.writerow(['Resumen'])
    writer.writerow(['Total ventas', total_ventas])
    writer.writerow(['Retenciones', total_retenciones])
    writer.writerow(['Total cobrado', total_cobrado])
    writer.writerow(['Saldo por cobrar', total_saldo])
    writer.writerow([])
    writer.writerow(['Deuda por vencimiento'])
    writer.writerow(['Sin vencer', aging['sin_vencer']])
    writer.writerow(['1-30 días', aging['1_30']])
    writer.writerow(['31-60 días', aging['31_60']])
    writer.writerow(['61-90 días', aging['61_90']])
    writer.writerow(['+91 días', aging['91_plus']])
    writer.writerow([])
    writer.writerow(['Factura', 'Fecha', 'Vence', 'Total', 'Pagado', 'Saldo', 'Días vencido'])
    for inv in invoices_data:
        writer.writerow([
            inv.get('invoiceNumber', ''),
            (inv.get('date', '') or '')[:10],
            (inv.get('dueDate', '') or '')[:10],
            inv.get('total', 0),
            inv.get('_total_paid', 0),
            inv.get('_remaining', 0),
            inv.get('_days_overdue', 0),
        ])

    buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    return send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'estado_cuenta_{client_id}_{year}_{month if month else "anual"}.csv'
    )


def _safe_parse_iso_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        dt_value = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        try:
            dt_value = datetime.fromisoformat(text)
        except ValueError:
            try:
                dt_value = datetime.fromisoformat(text.split('.')[0])
            except ValueError:
                return None
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    return dt_value


class AccountNode:
    def __init__(self, name, parent=None, is_leaf=False):
        self.name = name
        self.parent = parent
        self.is_leaf = is_leaf
        self.children = {}
        self.value = 0.0

    def add_value(self, val):
        self.value += val
        if self.parent:
            self.parent.add_value(val)


def build_accounts_tree():
    root = AccountNode("Root")
    
    ingresos = AccountNode("Ingresos", parent=root)
    costos = AccountNode("Costos", parent=root)
    gastos = AccountNode("Gastos", parent=root)
    
    root.children["Ingresos"] = ingresos
    root.children["Costos"] = costos
    root.children["Gastos"] = gastos
    
    # Subtree: Ingresos
    ing_ord = AccountNode("Ingresos de actividades ordinarias", parent=ingresos)
    ing_ord.children["Ventas"] = AccountNode("Ventas", parent=ing_ord, is_leaf=True)
    ing_ord.children["Devoluciones en ventas"] = AccountNode("Devoluciones en ventas", parent=ing_ord, is_leaf=True)
    ingresos.children["Ingresos de actividades ordinarias"] = ing_ord
    
    oth_ing = AccountNode("Otros Ingresos", parent=ingresos)
    ing_fin = AccountNode("Ingresos financieros", parent=oth_ing)
    ing_fin.children["Ingresos por Intereses financieros"] = AccountNode("Ingresos por Intereses financieros", parent=ing_fin, is_leaf=True)
    oth_ing.children["Ingresos financieros"] = ing_fin
    
    oth_ing_div = AccountNode("Otros ingresos diversos", parent=oth_ing)
    oth_ing_div.children["Ganancia por diferencia en cambio"] = AccountNode("Ganancia por diferencia en cambio", parent=oth_ing_div, is_leaf=True)
    oth_ing_div.children["Ajustes por aproximaciones en cálculos"] = AccountNode("Ajustes por aproximaciones en cálculos", parent=oth_ing_div, is_leaf=True)
    oth_ing.children["Otros ingresos diversos"] = oth_ing_div
    ingresos.children["Otros Ingresos"] = oth_ing
    
    # Subtree: Costos
    cost_vent = AccountNode("Costos de ventas y operación", parent=costos)
    cost_merc = AccountNode("Costos de la mercancía vendida", parent=cost_vent)
    cost_merc.children["Costos del inventario"] = AccountNode("Costos del inventario", parent=cost_merc, is_leaf=True)
    cost_merc.children["Ajustes al inventario"] = AccountNode("Ajustes al inventario", parent=cost_merc, is_leaf=True)
    cost_merc.children["Descuentos financieros"] = AccountNode("Descuentos financieros", parent=cost_merc, is_leaf=True)
    cost_merc.children["Devoluciones en compras de inventario"] = AccountNode("Devoluciones en compras de inventario", parent=cost_merc, is_leaf=True)
    cost_merc.children["Costo de los servicios vendidos"] = AccountNode("Costo de los servicios vendidos", parent=cost_merc, is_leaf=True)
    cost_vent.children["Costos de la mercancía vendida"] = cost_merc
    costos.children["Costos de ventas y operación"] = cost_vent
    
    # Subtree: Gastos
    g_venta = AccountNode("Gastos de venta", parent=gastos)
    g_pers_vta = AccountNode("Gastos de personal de ventas", parent=g_venta)
    payroll_sales = [
        "Sueldos y salarios personal de ventas",
        "Salario de navidad personal de ventas",
        "Horas extras personal de ventas",
        "Comisiones personal de ventas",
        "Vacaciones personal de ventas",
        "Bonificaciones personal de ventas",
        "Dotación a trabajadores de ventas",
        "Aportes aseguradora fondo de pensiones personal de ventas",
        "Aportes seguro familiar de salud (SFS) personal de ventas",
        "Seguro de riesgo laboral (SRL) personal de ventas",
        "INFOTEP personal de ventas",
        "Otros gastos personal de ventas"
    ]
    for p in payroll_sales:
        g_pers_vta.children[p] = AccountNode(p, parent=g_pers_vta, is_leaf=True)
    g_venta.children["Gastos de personal de ventas"] = g_pers_vta
    gastos.children["Gastos de venta"] = g_venta
    
    g_admin = AccountNode("Gastos de administración", parent=gastos)
    
    g_pers = AccountNode("Gastos de personal", parent=g_admin)
    payroll_admin = [
        "Sueldos y salarios",
        "Salario de navidad",
        "Horas extras",
        "Comisiones",
        "Vacaciones",
        "Bonificaciones",
        "Dotación a trabajadores",
        "Aportes aseguradora fondo de pensiones",
        "Aportes seguro familiar de salud (SFS)",
        "Seguro de riesgo laboral (SRL)",
        "INFOTEP",
        "Gastos no admitidos para fines fiscales",
        "Otros gastos personal administrativo"
    ]
    for p in payroll_admin:
        g_pers.children[p] = AccountNode(p, parent=g_pers, is_leaf=True)
    g_admin.children["Gastos de personal"] = g_pers
    
    g_gen = AccountNode("Gastos generales", parent=g_admin)
    
    serv_prof = AccountNode("Servicios profesionales", parent=g_gen)
    serv_prof.children["Asesoría jurídica"] = AccountNode("Asesoría jurídica", parent=serv_prof, is_leaf=True)
    serv_prof.children["Asesoría contable"] = AccountNode("Asesoría contable", parent=serv_prof, is_leaf=True)
    g_gen.children["Servicios profesionales"] = serv_prof
    
    arrend = AccountNode("Arrendamientos", parent=g_gen)
    arrend.children["Arrendamiento de equipos"] = AccountNode("Arrendamiento de equipos", parent=arrend, is_leaf=True)
    arrend.children["Arrendamiento de oficinas"] = AccountNode("Arrendamiento de oficinas", parent=arrend, is_leaf=True)
    g_gen.children["Arrendamientos"] = arrend
    
    serv_pub = AccountNode("Servicios públicos", parent=g_gen)
    public_services = [
        "Gas", "Aseo", "Agua", "Energia eléctrica",
        "Teléfono / Internet", "Asistencia técnica", "Otros servicios"
    ]
    for s in public_services:
        serv_pub.children[s] = AccountNode(s, parent=serv_pub, is_leaf=True)
    g_gen.children["Servicios públicos"] = serv_pub
    
    g_gen.children["Vigilancia y seguridad"] = AccountNode("Vigilancia y seguridad", parent=g_gen, is_leaf=True)
    
    g_rep = AccountNode("Gastos de representación", parent=g_gen)
    g_rep.children["Comidas y entretenimiento"] = AccountNode("Comidas y entretenimiento", parent=g_rep, is_leaf=True)
    g_rep.children["Viáticos y gastos de viaje"] = AccountNode("Viáticos y gastos de viaje", parent=g_rep, is_leaf=True)
    g_gen.children["Gastos de representación"] = g_rep
    
    art_ofic = AccountNode("Artículos de oficina", parent=g_gen)
    art_ofic.children["Papelería"] = AccountNode("Papelería", parent=art_ofic, is_leaf=True)
    art_ofic.children["Combustibles y lubricantes"] = AccountNode("Combustibles y lubricantes", parent=art_ofic, is_leaf=True)
    g_gen.children["Artículos de oficina"] = art_ofic
    
    fletes = AccountNode("Fletes y gastos de envios", parent=g_gen)
    fletes.children["Envios y Mensajería"] = AccountNode("Envios y Mensajería", parent=fletes, is_leaf=True)
    fletes.children["Estacionamiento"] = AccountNode("Estacionamiento", parent=fletes, is_leaf=True)
    g_gen.children["Fletes y gastos de envios"] = fletes
    
    g_gen.children["Propaganda y publicidad"] = AccountNode("Propaganda y publicidad", parent=g_gen, is_leaf=True)
    g_gen.children["Capacitación al personal"] = AccountNode("Capacitación al personal", parent=g_gen, is_leaf=True)
    
    seguros = AccountNode("Seguros", parent=g_gen)
    seguros.children["Seguro de accidentes"] = AccountNode("Seguro de accidentes", parent=seguros, is_leaf=True)
    seguros.children["Seguro de vehículos"] = AccountNode("Seguro de vehículos", parent=seguros, is_leaf=True)
    seguros.children["Seguro contra Incendios"] = AccountNode("Seguro contra Incendios", parent=seguros, is_leaf=True)
    g_gen.children["Seguros"] = seguros
    
    g_gen.children["Patentes y marcas"] = AccountNode("Patentes y marcas", parent=g_gen, is_leaf=True)
    
    serv_online = AccountNode("Servicios Online", parent=g_gen)
    serv_online.children["Software contables"] = AccountNode("Software contables", parent=serv_online, is_leaf=True)
    serv_online.children["Gastos constitución"] = AccountNode("Gastos constitución", parent=serv_online, is_leaf=True)
    g_gen.children["Servicios Online"] = serv_online
    
    gast_leg = AccountNode("Gastos legales", parent=g_gen)
    gast_leg.children["Notariales"] = AccountNode("Notariales", parent=gast_leg, is_leaf=True)
    gast_leg.children["Registro mercantiles"] = AccountNode("Registro mercantiles", parent=gast_leg, is_leaf=True)
    gast_leg.children["Trámites legales"] = AccountNode("Trámites legales", parent=gast_leg, is_leaf=True)
    g_gen.children["Gastos legales"] = gast_leg
    
    manten = AccountNode("Mantenimiento y conservación", parent=g_gen)
    manten.children["Construcción y edificación"] = AccountNode("Construcción y edificación", parent=manten, is_leaf=True)
    manten.children["Equipo oficina"] = AccountNode("Equipo oficina", parent=manten, is_leaf=True)
    manten.children["Equipo computación"] = AccountNode("Equipo computación", parent=manten, is_leaf=True)
    manten.children["Adecuaciones e instalaciones"] = AccountNode("Adecuaciones e instalaciones", parent=manten, is_leaf=True)
    manten.children["Adecuaciones locativas"] = AccountNode("Adecuaciones locativas", parent=manten, is_leaf=True)
    g_gen.children["Mantenimiento y conservación"] = manten
    
    g_gen.children["Cuotas y suscripciones"] = AccountNode("Cuotas y suscripciones", parent=g_gen, is_leaf=True)
    g_gen.children["Otros gastos generales"] = AccountNode("Otros gastos generales", parent=g_gen, is_leaf=True)
    g_admin.children["Gastos generales"] = g_gen
    
    deprec = AccountNode("Depreciaciones, amortizaciones y desvalorizaciones", parent=g_admin)
    deprec.children["Deterioro de cuentas por cobrar"] = AccountNode("Deterioro de cuentas por cobrar", parent=deprec, is_leaf=True)
    
    dep_prop = AccountNode("Depreciación de propiedad, planta y equipo", parent=deprec)
    dep_prop.children["Depreciación construcciones y edificaciones"] = AccountNode("Depreciación construcciones y edificaciones", parent=dep_prop, is_leaf=True)
    dep_prop.children["Depreciación mobiliario y equipo de oficina"] = AccountNode("Depreciación mobiliario y equipo de oficina", parent=dep_prop, is_leaf=True)
    dep_prop.children["Depreciación equipo de computación"] = AccountNode("Depreciación equipo de computación", parent=dep_prop, is_leaf=True)
    dep_prop.children["Depreciación vehiculos y equipos de transporte"] = AccountNode("Depreciación vehiculos y equipos de transporte", parent=dep_prop, is_leaf=True)
    deprec.children["Depreciación de propiedad, planta y equipo"] = dep_prop
    g_admin.children["Depreciaciones, amortizaciones y desvalorizaciones"] = deprec
    
    g_finan = AccountNode("Gastos financieros", parent=g_admin)
    g_finan.children["Gastos por Intereses financieros"] = AccountNode("Gastos por Intereses financieros", parent=g_finan, is_leaf=True)
    g_finan.children["Gastos por Intereses de mora"] = AccountNode("Gastos por Intereses de mora", parent=g_finan, is_leaf=True)
    g_admin.children["Gastos financieros"] = g_finan
    
    oth_gast = AccountNode("Otros gastos", parent=g_admin)
    oth_gast.children["Comisiones bancarias"] = AccountNode("Comisiones bancarias", parent=oth_gast, is_leaf=True)
    oth_gast.children["Pérdida por diferencia en cambio"] = AccountNode("Pérdida por diferencia en cambio", parent=oth_gast, is_leaf=True)
    oth_gast.children["Ajustes por aproximaciones en cálculos"] = AccountNode("Ajustes por aproximaciones en cálculos", parent=oth_gast, is_leaf=True)
    oth_gast.children["Pérdida por disposición de activos"] = AccountNode("Pérdida por disposición de activos", parent=oth_gast, is_leaf=True)
    g_admin.children["Otros gastos"] = oth_gast
    
    g_imp = AccountNode("Gastos por impuestos", parent=g_admin)
    g_imp.children["Impuestos de renta"] = AccountNode("Impuestos de renta", parent=g_imp, is_leaf=True)
    g_imp.children["Gastos por impuestos no acreditables"] = AccountNode("Gastos por impuestos no acreditables", parent=g_imp, is_leaf=True)
    g_imp.children["Retenciones asumidas"] = AccountNode("Retenciones asumidas", parent=g_imp, is_leaf=True)
    g_admin.children["Gastos por impuestos"] = g_imp
    
    gastos.children["Gastos de administración"] = g_admin
    
    return root


def serialize_node(node, depth, list_out):
    list_out.append({
        "name": node.name,
        "depth": depth,
        "value": node.value,
        "is_leaf": node.is_leaf
    })
    for child_name, child_node in node.children.items():
        serialize_node(child_node, depth + 1, list_out)


def _compute_admin_ingresos_compras(owner_uid, sandbox, year, month):
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox) or []
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox) or []

    # Initialize accounting tree
    root_node = build_accounts_tree()

    # 1. Classify incomes
    for inv in invoices:
        if inv.get('isQuotation'):
            continue
        status = inv.get('status')
        if status in ('Anulada', 'Borrador', 'Consolidada'):
            continue

        dt_value = _safe_parse_iso_date(inv.get('date') or inv.get('createdAt'))
        if not dt_value or dt_value.year != year or (month and dt_value.month != month):
            continue

        subtotal = float(inv.get('subtotal') or 0.0)
        credited = float(inv.get('creditedAmount') or 0.0)

        # Sales
        root_node.children["Ingresos"].children["Ingresos de actividades ordinarias"].children["Ventas"].add_value(subtotal)

        # Refunds / Credit notes
        if credited > 0.01:
            root_node.children["Ingresos"].children["Ingresos de actividades ordinarias"].children["Devoluciones en ventas"].add_value(-credited)

    # 2. Classify costs and expenses
    for exp in expenses:
        if exp.get('approvalStatus') == 'Pendiente':
            continue

        dt_value = _safe_parse_iso_date(exp.get('date') or exp.get('createdAt'))
        if not dt_value or dt_value.year != year or (month and dt_value.month != month):
            continue

        total = float(exp.get('total') or exp.get('amount') or 0.0)
        itbis = float(exp.get('totalITBIS') or exp.get('itbis') or 0.0)
        subtotal = total - itbis

        concept = (exp.get('concept') or '').lower()
        category = exp.get('category') or ''

        is_cost = False

        if "compra de mercancia" in concept or "compra de mercancía" in concept or "inventario" in concept or "mercancia" in concept or "mercancía" in concept:
            root_node.children["Costos"].children["Costos de ventas y operación"].children["Costos de la mercancía vendida"].children["Costos del inventario"].add_value(subtotal)
            is_cost = True
        elif "costo de servicio" in concept or "servicio vendido" in concept:
            root_node.children["Costos"].children["Costos de ventas y operación"].children["Costos de la mercancía vendida"].children["Costo de los servicios vendidos"].add_value(subtotal)
            is_cost = True

        if not is_cost:
            # Map to Gastos
            is_sales_gasto = "ventas" in concept or "vendedor" in concept or "vendedores" in concept or "personal de ventas" in concept

            if is_sales_gasto:
                p_node = root_node.children["Gastos"].children["Gastos de venta"].children["Gastos de personal de ventas"]
                mapped = False
                if "sueldo" in concept or "salario" in concept or "nomina" in concept or "nómina" in concept or "sueldos" in concept:
                    p_node.children["Sueldos y salarios personal de ventas"].add_value(subtotal)
                    mapped = True
                elif "navidad" in concept or "regalia" in concept or "regalía" in concept:
                    p_node.children["Salario de navidad personal de ventas"].add_value(subtotal)
                    mapped = True
                elif "extra" in concept or "horas extras" in concept:
                    p_node.children["Horas extras personal de ventas"].add_value(subtotal)
                    mapped = True
                elif "comision" in concept or "comisión" in concept or "comisiones" in concept:
                    p_node.children["Comisiones personal de ventas"].add_value(subtotal)
                    mapped = True
                elif "vacacion" in concept or "vacación" in concept or "vacaciones" in concept:
                    p_node.children["Vacaciones personal de ventas"].add_value(subtotal)
                    mapped = True
                elif "bonificacion" in concept or "bonificación" in concept or "bonificaciones" in concept:
                    p_node.children["Bonificaciones personal de ventas"].add_value(subtotal)
                    mapped = True
                elif "dotacion" in concept or "dotación" in concept:
                    p_node.children["Dotación a trabajadores de ventas"].add_value(subtotal)
                    mapped = True
                elif "pension" in concept or "pensión" in concept or "afp" in concept:
                    p_node.children["Aportes aseguradora fondo de pensiones personal de ventas"].add_value(subtotal)
                    mapped = True
                elif "salud" in concept or "sfs" in concept or "ars" in concept:
                    p_node.children["Aportes seguro familiar de salud (SFS) personal de ventas"].add_value(subtotal)
                    mapped = True
                elif "riesgo" in concept or "srl" in concept:
                    p_node.children["Seguro de riesgo laboral (SRL) personal de ventas"].add_value(subtotal)
                    mapped = True
                elif "infotep" in concept:
                    p_node.children["INFOTEP personal de ventas"].add_value(subtotal)
                    mapped = True
                
                if not mapped:
                    p_node.children["Otros gastos personal de ventas"].add_value(subtotal)
            else:
                g_admin_node = root_node.children["Gastos"].children["Gastos de administración"]
                mapped = False

                if category == "Comida y Restaurantes":
                    g_admin_node.children["Gastos generales"].children["Gastos de representación"].children["Comidas y entretenimiento"].add_value(subtotal)
                    mapped = True
                elif category == "Transporte y Combustible":
                    g_admin_node.children["Gastos generales"].children["Artículos de oficina"].children["Combustibles y lubricantes"].add_value(subtotal)
                    mapped = True
                elif category == "Alquileres":
                    g_admin_node.children["Gastos generales"].children["Arrendamientos"].children["Arrendamiento de oficinas"].add_value(subtotal)
                    mapped = True
                elif category == "Impuestos y Tasas":
                    g_admin_node.children["Gastos por impuestos"].children["Gastos por impuestos no acreditables"].add_value(subtotal)
                    mapped = True
                elif category == "Software y Tecnología":
                    g_admin_node.children["Gastos generales"].children["Servicios Online"].children["Software contables"].add_value(subtotal)
                    mapped = True
                elif category == "Materiales de Oficina":
                    g_admin_node.children["Gastos generales"].children["Artículos de oficina"].children["Papelería"].add_value(subtotal)
                    mapped = True
                elif category == "Servicios Básicos":
                    serv_pub_node = g_admin_node.children["Gastos generales"].children["Servicios públicos"]
                    if "luz" in concept or "energia" in concept or "eléctrica" in concept:
                        serv_pub_node.children["Energia eléctrica"].add_value(subtotal)
                    elif "gas" in concept:
                        serv_pub_node.children["Gas"].add_value(subtotal)
                    elif "agua" in concept:
                        serv_pub_node.children["Agua"].add_value(subtotal)
                    elif "telefono" in concept or "internet" in concept or "claro" in concept or "altice" in concept or "wind" in concept:
                        serv_pub_node.children["Teléfono / Internet"].add_value(subtotal)
                    elif "basura" in concept or "aseo" in concept or "limpieza" in concept:
                        serv_pub_node.children["Aseo"].add_value(subtotal)
                    else:
                        serv_pub_node.children["Otros servicios"].add_value(subtotal)
                    mapped = True

                if not mapped:
                    if "sueldo" in concept or "salario" in concept or "nomina" in concept or "nómina" in concept or "sueldos" in concept:
                        g_admin_node.children["Gastos de personal"].children["Sueldos y salarios"].add_value(subtotal)
                    elif "navidad" in concept or "regalia" in concept or "regalía" in concept:
                        g_admin_node.children["Gastos de personal"].children["Salario de navidad"].add_value(subtotal)
                    elif "extra" in concept or "horas extras" in concept:
                        g_admin_node.children["Gastos de personal"].children["Horas extras"].add_value(subtotal)
                    elif "comision" in concept or "comisión" in concept or "comisiones" in concept:
                        g_admin_node.children["Gastos de personal"].children["Comisiones"].add_value(subtotal)
                    elif "vacacion" in concept or "vacación" in concept or "vacaciones" in concept:
                        g_admin_node.children["Gastos de personal"].children["Vacaciones"].add_value(subtotal)
                    elif "bonificacion" in concept or "bonificación" in concept or "bonificaciones" in concept:
                        g_admin_node.children["Gastos de personal"].children["Bonificaciones"].add_value(subtotal)
                    elif "dotacion" in concept or "dotación" in concept:
                        g_admin_node.children["Gastos de personal"].children["Dotación a trabajadores"].add_value(subtotal)
                    elif "pension" in concept or "pensión" in concept or "afp" in concept:
                        g_admin_node.children["Gastos de personal"].children["Aportes aseguradora fondo de pensiones"].add_value(subtotal)
                    elif "salud" in concept or "sfs" in concept or "ars" in concept:
                        g_admin_node.children["Gastos de personal"].children["Aportes seguro familiar de salud (SFS)"].add_value(subtotal)
                    elif "riesgo" in concept or "srl" in concept:
                        g_admin_node.children["Gastos de personal"].children["Seguro de riesgo laboral (SRL)"].add_value(subtotal)
                    elif "infotep" in concept:
                        g_admin_node.children["Gastos de personal"].children["INFOTEP"].add_value(subtotal)
                    elif "abogado" in concept or "legal" in concept or "notario" in concept:
                        g_admin_node.children["Gastos generales"].children["Servicios profesionales"].children["Asesoría jurídica"].add_value(subtotal)
                    elif "contador" in concept or "auditor" in concept or "contable" in concept:
                        g_admin_node.children["Gastos generales"].children["Servicios profesionales"].children["Asesoría contable"].add_value(subtotal)
                    elif "vigilancia" in concept or "seguridad" in concept or "guardian" in concept:
                        g_admin_node.children["Gastos generales"].children["Vigilancia y seguridad"].add_value(subtotal)
                    elif "seguro de accidentes" in concept:
                        g_admin_node.children["Gastos generales"].children["Seguros"].children["Seguro de accidentes"].add_value(subtotal)
                    elif "seguro de vehiculo" in concept or "seguro de vehículo" in concept:
                        g_admin_node.children["Gastos generales"].children["Seguros"].children["Seguro de vehículos"].add_value(subtotal)
                    elif "seguro contra incendios" in concept:
                        g_admin_node.children["Gastos generales"].children["Seguros"].children["Seguro contra Incendios"].add_value(subtotal)
                    elif "seguro" in concept:
                        g_admin_node.children["Gastos generales"].children["Seguros"].children["Seguro de vehículos"].add_value(subtotal)
                    elif "software" in concept:
                        g_admin_node.children["Gastos generales"].children["Servicios Online"].children["Software contables"].add_value(subtotal)
                    elif "banco" in concept or "comision bancaria" in concept or "comisión bancaria" in concept:
                        g_admin_node.children["Otros gastos"].children["Comisiones bancarias"].add_value(subtotal)
                    elif "interes" in concept or "interés" in concept:
                        g_admin_node.children["Gastos financieros"].children["Gastos por Intereses financieros"].add_value(subtotal)
                    else:
                        g_admin_node.children["Gastos generales"].children["Otros gastos generales"].add_value(subtotal)

    # Flatten the tree
    accounts_list = []
    for name, child in root_node.children.items():
        serialize_node(child, 0, accounts_list)

    total_ingresos = root_node.children["Ingresos"].value
    total_egresos = root_node.children["Costos"].value + root_node.children["Gastos"].value
    saldo = total_ingresos - total_egresos

    month_label = next((label for value, label in MONTH_FILTER_OPTIONS if value == month), "Todo el año")

    return {
        "accounts_list": accounts_list,
        "total_ingresos": round(total_ingresos, 2),
        "total_egresos": round(total_egresos, 2),
        "saldo": round(saldo, 2),
        "month_label": month_label,
    }


@web_reports_sales_bp.route('/reports/admin/ingresos-compras')
def admin_ingresos_compras():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Ingresos y compras",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', 0))
    except ValueError:
        month = 0

    show_zero = request.args.get('show_zero', '1') == '1'

    data = _compute_admin_ingresos_compras(owner_uid, sandbox, year, month)
    
    accounts_list = []
    for item in data.get('accounts_list', []):
        if not show_zero and abs(item['value']) < 0.01:
            continue
        accounts_list.append(item)
    data['accounts_list'] = accounts_list

    years_range = list(range(now.year - 5, now.year + 1))

    return render_template('reports/admin_ingresos_compras.html',
                           active_page='admin_ingresos_compras',
                           year=year,
                           month=month,
                           years_range=years_range,
                           months_list=MONTH_FILTER_OPTIONS,
                           show_zero=show_zero,
                           **data)


@web_reports_sales_bp.route('/reports/admin/ingresos-compras/export')
def admin_ingresos_compras_export():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Ingresos y compras",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', 0))
    except ValueError:
        month = 0

    show_zero = request.args.get('show_zero', '1') == '1'

    data = _compute_admin_ingresos_compras(owner_uid, sandbox, year, month)

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)

    writer.writerow(['Reporte de Ingresos y compras'])
    writer.writerow(['Año', year])
    writer.writerow(['Mes', data['month_label']])
    writer.writerow([])
    writer.writerow(['Resumen financiero'])
    writer.writerow(['Total ingresos', f"RD$ {data['total_ingresos']:,.2f}"])
    writer.writerow(['Total egresos', f"RD$ {data['total_egresos']:,.2f}"])
    writer.writerow(['Saldo', f"RD$ {data['saldo']:,.2f}"])
    writer.writerow([])
    writer.writerow(['Cuenta contable', 'Total'])

    for row in data.get('accounts_list', []):
        if not show_zero and abs(row['value']) < 0.01:
            continue
        indent = "  " * row['depth']
        writer.writerow([f"{indent}{row['name']}", f"{row['value']:.2f}"])

    buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    return send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'ingresos_compras_{year}_{month if month else "anual"}.csv'
    )

def _compute_admin_reporte_anual(owner_uid, sandbox, year):
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox) or []
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox) or []
    team_members = DatabaseService.get_team_members(owner_uid) or []
    
    # Map team member emails/uids to names
    user_map = {}
    for member in team_members:
        email = member.get('email', '')
        if email:
            user_map[email.lower()] = member.get('name') or email
            
    # Filter invoices
    year_invoices = []
    total_sales = 0.0
    
    ingresos_map = {idx: {"count": 0, "subtotal": 0.0, "itbis": 0.0, "total": 0.0}
                    for idx in range(1, 13)}
                    
    for inv in invoices:
        if inv.get('isQuotation'):
            continue
        status = inv.get('status')
        if status in ('Anulada', 'Borrador', 'Consolidada'):
            continue
            
        dt_value = _safe_parse_iso_date(inv.get('date') or inv.get('createdAt'))
        if not dt_value or dt_value.year != year:
            continue
            
        year_invoices.append(inv)
        
        subtotal = float(inv.get('subtotal') or 0.0)
        itbis = float(inv.get('totalITBIS') or 0.0)
        total = float(inv.get('total') or 0.0)
        
        month = dt_value.month
        data_month = ingresos_map[month]
        data_month["count"] += 1
        data_month["subtotal"] += subtotal
        data_month["itbis"] += itbis
        data_month["total"] += total
        
        total_sales += total
        
    # Filter expenses
    year_expenses = []
    total_expenses = 0.0
    
    gastos_map = {idx: {"count": 0, "total": 0.0} for idx in range(1, 13)}
    
    for exp in expenses:
        if exp.get('approvalStatus') == 'Rechazado':
            continue
        dt_value = _safe_parse_iso_date(exp.get('date') or exp.get('createdAt'))
        if not dt_value or dt_value.year != year:
            continue
            
        year_expenses.append(exp)
        
        total = float(exp.get('total') or 0.0)
        
        month = dt_value.month
        data_month = gastos_map[month]
        data_month["count"] += 1
        data_month["total"] += total
        
        total_expenses += total
        
    # Averages
    avg_monthly = total_sales / 12.0
    avg_weekly = total_sales / 52.0
    avg_daily = total_sales / 365.0
    
    # Months lists for charts
    months_data = []
    chart_ingresos = []
    chart_gastos = []
    
    for idx, label in enumerate(MONTH_NAMES, start=1):
        ing_info = ingresos_map[idx]
        gst_info = gastos_map[idx]
        
        chart_ingresos.append(round(ing_info["total"], 2))
        chart_gastos.append(round(gst_info["total"], 2))
        
        months_data.append({
            "month": idx,
            "label": label,
            "ingresos_count": ing_info["count"],
            "ingresos_subtotal": round(ing_info["subtotal"], 2),
            "ingresos_itbis": round(ing_info["itbis"], 2),
            "ingresos_total": round(ing_info["total"], 2),
            "gastos_count": gst_info["count"],
            "gastos_total": round(gst_info["total"], 2),
            "resultado": round(ing_info["total"] - gst_info["total"], 2),
        })
        
    # Rankings:
    # 1. Top Products
    product_sales = defaultdict(lambda: {"name": "", "reference": "N/A", "quantity": 0.0, "total": 0.0})
    for inv in year_invoices:
        for item in inv.get('items', []):
            name = item.get('name') or item.get('itemName') or item.get('description') or 'Producto'
            qty = float(item.get('quantity') or 0.0)
            price = float(item.get('price') or item.get('unitPrice') or 0.0)
            tot = float(item.get('total') or (qty * price))
            ref = item.get('reference') or 'N/A'
            
            p = product_sales[name]
            p["name"] = name
            p["reference"] = ref
            p["quantity"] += qty
            p["total"] += tot
            
    top_products = sorted(product_sales.values(), key=lambda x: x["quantity"], reverse=True)[:5]
    for p in top_products:
        p["quantity"] = round(p["quantity"], 2)
        p["total"] = round(p["total"], 2)
        
    # 2. Top Sellers
    seller_sales = defaultdict(lambda: {"name": "", "count": 0, "total": 0.0})
    for inv in year_invoices:
        reg_by = (inv.get('registeredBy') or inv.get('createdBy') or 'Desconocido').lower()
        seller_name = user_map.get(reg_by) or inv.get('sellerName') or inv.get('registeredBy') or inv.get('createdBy') or 'Desconocido'
        s = seller_sales[seller_name]
        s["name"] = seller_name
        s["count"] += 1
        s["total"] += float(inv.get('total') or 0.0)
        
    top_sellers = sorted(seller_sales.values(), key=lambda x: x["total"], reverse=True)[:5]
    for s in top_sellers:
        s["total"] = round(s["total"], 2)
        
    # 3. Top Clients
    client_sales = defaultdict(lambda: {"name": "", "rnc": "N/A", "count": 0, "total": 0.0})
    for inv in year_invoices:
        c_name = inv.get('clientName') or 'Cliente sin nombre'
        c_rnc = inv.get('clientRNC') or 'N/A'
        
        c = client_sales[c_name]
        c["name"] = c_name
        c["rnc"] = c_rnc
        c["count"] += 1
        c["total"] += float(inv.get('total') or 0.0)
        
    top_clients = sorted(client_sales.values(), key=lambda x: x["total"], reverse=True)[:5]
    for c in top_clients:
        c["total"] = round(c["total"], 2)
        
    # 4. Top Expenses (Principales gastos)
    expense_categories = defaultdict(lambda: {"name": "", "total": 0.0})
    for exp in year_expenses:
        cat = exp.get('category') or exp.get('concept') or 'Otros Gastos'
        expense_categories[cat]["name"] = cat
        expense_categories[cat]["total"] += float(exp.get('total') or 0.0)
        
    top_expenses = sorted(expense_categories.values(), key=lambda x: x["total"], reverse=True)[:5]
    for e in top_expenses:
        e["total"] = round(e["total"], 2)
        
    return {
        "year": year,
        "months_data": months_data,
        "total_ingresos": round(total_sales, 2),
        "total_gastos": round(total_expenses, 2),
        "resultado": round(total_sales - total_expenses, 2),
        "chart_ingresos": chart_ingresos,
        "chart_gastos": chart_gastos,
        "chart_labels": MONTH_NAMES,
        "avg_monthly": round(avg_monthly, 2),
        "avg_weekly": round(avg_weekly, 2),
        "avg_daily": round(avg_daily, 2),
        "top_products": top_products,
        "top_sellers": top_sellers,
        "top_clients": top_clients,
        "top_expenses": top_expenses,
        "has_sales": len(year_invoices) > 0,
        "has_expenses": len(year_expenses) > 0
    }


@web_reports_sales_bp.route('/reports/admin/reporte-anual')
def admin_reporte_anual():
    if 'user' not in session:
        return render_template('auth/restricted.html', feature_name="Reporte anual")
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Reporte anual",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year

    compare = request.args.get('compare') == '1'
    data = _compute_admin_reporte_anual(owner_uid, sandbox, year)
    
    prev_data = None
    if compare:
        prev_data = _compute_admin_reporte_anual(owner_uid, sandbox, year - 1)

    years_range = list(range(now.year - 5, now.year + 1))

    return render_template('reports/admin_reporte_anual.html',
                           active_page='admin_reporte_anual',
                           year=year,
                           compare=compare,
                           years_range=years_range,
                           months_data=data['months_data'],
                           total_ingresos=data['total_ingresos'],
                           total_gastos=data['total_gastos'],
                           resultado=data['resultado'],
                           chart_labels=data['chart_labels'],
                           chart_ingresos=data['chart_ingresos'],
                           chart_gastos=data['chart_gastos'],
                           avg_monthly=data['avg_monthly'],
                           avg_weekly=data['avg_weekly'],
                           avg_daily=data['avg_daily'],
                           top_products=data['top_products'],
                           top_sellers=data['top_sellers'],
                           top_clients=data['top_clients'],
                           top_expenses=data['top_expenses'],
                           has_sales=data['has_sales'],
                           has_expenses=data['has_expenses'],
                           prev_data=prev_data)


@web_reports_sales_bp.route('/reports/admin/reporte-anual/export')
def admin_reporte_anual_export():
    if 'user' not in session:
        return render_template('auth/restricted.html', feature_name="Reporte anual")
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Reporte anual",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year

    data = _compute_admin_reporte_anual(owner_uid, sandbox, year)

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)

    writer.writerow(['Reporte anual'])
    writer.writerow(['Año', year])
    writer.writerow([])
    writer.writerow(['Mes', 'Facturas emitidas', 'Subtotal', 'ITBIS', 'Total ingresos',
                    'Compras registradas', 'Total compras', 'Resultado'])
    for row in data['months_data']:
        writer.writerow([
            row['label'],
            row['ingresos_count'],
            row['ingresos_subtotal'],
            row['ingresos_itbis'],
            row['ingresos_total'],
            row['gastos_count'],
            row['gastos_total'],
            row['resultado'],
        ])

    writer.writerow([])
    writer.writerow(['Total ingresos', data['total_ingresos']])
    writer.writerow(['Total gastos', data['total_gastos']])
    writer.writerow(['Resultado neto', data['resultado']])

    buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    return send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'reporte_anual_{year}.csv'
    )


@web_reports_sales_bp.route('/reports/admin/cxc')
def cxc_report():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Cuentas por cobrar", required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)
    
    hasta_str = request.args.get('hasta', '')
    if not hasta_str:
        hasta_str = now.strftime('%Y-%m-%d')
    
    try:
        hasta_date = datetime.strptime(hasta_str, '%Y-%m-%d').date()
    except ValueError:
        hasta_str = now.strftime('%Y-%m-%d')
        hasta_date = now.date()

    query = request.args.get('q', '').strip().lower()

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get('per_page', 10))
    except ValueError:
        per_page = 10
    if per_page < 1:
        per_page = 10

    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=False)

    cxc_list = []
    vencidas_30_menos = 0.0
    vencidas_31_60 = 0.0
    vencidas_61_90 = 0.0
    vencidas_91_mas = 0.0
    no_vencidas = 0.0
    total_por_cobrar = 0.0

    for inv in invoices:
        if inv.get('isQuotation'):
            continue
        
        status = inv.get('status')
        if status in ['Borrador', 'Anulada', 'Consolidada']:
            continue
            
        client_name = inv.get('clientName', '')
        client_id = inv.get('clientId', '')
        if not client_id or 'consumidor final' in client_name.lower():
            continue
            
        inv_date_str = (inv.get('date') or inv.get('createdAt') or '')[:10]
        if not inv_date_str:
            continue
        try:
            inv_date = datetime.strptime(inv_date_str, '%Y-%m-%d').date()
        except ValueError:
            continue
            
        if inv_date > hasta_date:
            continue

        if status == 'Cobrada' or float(inv.get('remainingBalance', 0.0)) <= 0.01:
            continue

        rem_bal = float(inv.get('remainingBalance', inv.get('netPayable', 0.0)))
        total_paid = float(inv.get('totalPaid', 0.0))
        total_amt = float(inv.get('total', inv.get('netPayable', 0.0)))
        
        due_date_str = (inv.get('dueDate') or inv.get('date') or inv.get('createdAt') or '')[:10]
        try:
            due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        except ValueError:
            due_date = inv_date

        days_diff = (hasta_date - due_date).days
        
        if days_diff <= 0:
            no_vencidas += rem_bal
        else:
            if days_diff <= 30:
                vencidas_30_menos += rem_bal
            elif days_diff <= 60:
                vencidas_31_60 += rem_bal
            elif days_diff <= 90:
                vencidas_61_90 += rem_bal
            else:
                vencidas_91_mas += rem_bal
                
        total_por_cobrar += rem_bal

        ncf_num = (inv.get('encf') or inv.get('invoiceNumber') or '').lower()
        doc_type = inv.get('ecfType', '').lower()
        client_rnc = inv.get('clientRNC', '').lower()
        
        if query:
            if (query not in ncf_num and
                query not in doc_type and
                query not in client_name.lower() and
                query not in client_rnc):
                continue

        cxc_list.append({
            'id': inv.get('id'),
            'ncf_num': inv.get('encf') or inv.get('invoiceNumber') or 'N/A',
            'doc_type': inv.get('ecfType', 'Factura de Consumo (E32)'),
            'client_name': client_name,
            'client_rnc': client_rnc,
            'fecha_creacion': inv_date_str,
            'fecha_vencimiento': due_date_str,
            'total': total_amt,
            'cobrado': total_paid,
            'por_cobrar': rem_bal,
            'days_diff': days_diff
        })

    cxc_list.sort(key=lambda x: x['fecha_vencimiento'])

    total_items = len(cxc_list)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated = cxc_list[start_idx:end_idx]

    start_count = start_idx + 1 if total_items > 0 else 0
    end_count = min(page * per_page, total_items)

    return render_template(
        'reports/cxc_report.html',
        active_page='cxc_report',
        invoices=paginated,
        total_items=total_items,
        total_pages=total_pages,
        page=page,
        per_page=per_page,
        start_count=start_count,
        end_count=end_count,
        hasta=hasta_str,
        q=request.args.get('q', ''),
        vencidas_30_menos=vencidas_30_menos,
        vencidas_31_60=vencidas_31_60,
        vencidas_61_90=vencidas_61_90,
        vencidas_91_mas=vencidas_91_mas,
        no_vencidas=no_vencidas,
        total_por_cobrar=total_por_cobrar
    )


@web_reports_sales_bp.route('/reports/admin/cxc/export')
def cxc_report_export():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Cuentas por cobrar", required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)
    
    hasta_str = request.args.get('hasta', '')
    if not hasta_str:
        hasta_str = now.strftime('%Y-%m-%d')
    try:
        hasta_date = datetime.strptime(hasta_str, '%Y-%m-%d').date()
    except ValueError:
        hasta_date = now.date()

    query = request.args.get('q', '').strip().lower()

    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=False)

    cxc_list = []
    for inv in invoices:
        if inv.get('isQuotation'):
            continue
        status = inv.get('status')
        if status in ['Borrador', 'Anulada', 'Consolidada']:
            continue
        client_name = inv.get('clientName', '')
        client_id = inv.get('clientId', '')
        if not client_id or 'consumidor final' in client_name.lower():
            continue
        inv_date_str = (inv.get('date') or inv.get('createdAt') or '')[:10]
        if not inv_date_str:
            continue
        try:
            inv_date = datetime.strptime(inv_date_str, '%Y-%m-%d').date()
        except ValueError:
            continue
        if inv_date > hasta_date:
            continue
        if status == 'Cobrada' or float(inv.get('remainingBalance', 0.0)) <= 0.01:
            continue

        rem_bal = float(inv.get('remainingBalance', inv.get('netPayable', 0.0)))
        total_paid = float(inv.get('totalPaid', 0.0))
        total_amt = float(inv.get('total', inv.get('netPayable', 0.0)))
        
        due_date_str = (inv.get('dueDate') or inv.get('date') or inv.get('createdAt') or '')[:10]

        ncf_num = (inv.get('encf') or inv.get('invoiceNumber') or '').lower()
        doc_type = inv.get('ecfType', '').lower()
        client_rnc = inv.get('clientRNC', '').lower()
        
        if query:
            if (query not in ncf_num and
                query not in doc_type and
                query not in client_name.lower() and
                query not in client_rnc):
                continue

        cxc_list.append([
            inv.get('encf') or inv.get('invoiceNumber') or 'N/A',
            inv.get('ecfType', 'Factura de Consumo (E32)'),
            client_name,
            inv_date_str,
            due_date_str,
            f"{total_amt:.2f}",
            f"{total_paid:.2f}",
            f"{rem_bal:.2f}"
        ])

    cxc_list.sort(key=lambda x: x[4])

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['NCF/Numero', 'Tipo de documento', 'Cliente', 'Creacion', 'Vencimiento', 'Total', 'Cobrado', 'Por cobrar'])
    for row in cxc_list:
        writer.writerow(row)

    buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    return send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'reporte_cxc_{hasta_str}.csv'
    )


@web_reports_sales_bp.route('/reports/admin/cxp')
def cxp_report():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Cuentas por pagar", required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)
    
    hasta_str = request.args.get('hasta', '')
    if not hasta_str:
        hasta_str = now.strftime('%Y-%m-%d')
    try:
        hasta_date = datetime.strptime(hasta_str, '%Y-%m-%d').date()
    except ValueError:
        hasta_str = now.strftime('%Y-%m-%d')
        hasta_date = now.date()

    query = request.args.get('q', '').strip().lower()

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get('per_page', 10))
    except ValueError:
        per_page = 10
    if per_page < 1:
        per_page = 10

    from app.services.supplier_invoice_service import SupplierInvoiceService
    
    purchase_invoices = SupplierInvoiceService.get_all(owner_uid, sandbox=sandbox)
    all_expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)

    cxp_list = []
    vencidas_30_menos = 0.0
    vencidas_31_60 = 0.0
    vencidas_61_90 = 0.0
    vencidas_91_mas = 0.0
    no_vencidas = 0.0
    total_por_pagar = 0.0

    for inv in purchase_invoices:
        status = inv.get('cxpStatus', 'Pendiente')
        if status == 'Saldada' or float(inv.get('cxpRemainingBalance', 0.0)) <= 0.01:
            continue
            
        inv_date_str = (inv.get('date') or inv.get('createdAt') or '')[:10]
        if not inv_date_str:
            continue
        try:
            inv_date = datetime.strptime(inv_date_str, '%Y-%m-%d').date()
        except ValueError:
            continue
            
        if inv_date > hasta_date:
            continue

        rem_bal = float(inv.get('cxpRemainingBalance', inv.get('total', 0.0)))
        total_amt = float(inv.get('total', 0.0))
        total_paid = total_amt - rem_bal
        
        due_date_str = (inv.get('dueDate') or inv.get('date') or inv.get('createdAt') or '')[:10]
        try:
            due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        except ValueError:
            due_date = inv_date

        days_diff = (hasta_date - due_date).days
        
        if days_diff <= 0:
            no_vencidas += rem_bal
        else:
            if days_diff <= 30:
                vencidas_30_menos += rem_bal
            elif days_diff <= 60:
                vencidas_31_60 += rem_bal
            elif days_diff <= 90:
                vencidas_61_90 += rem_bal
            else:
                vencidas_91_mas += rem_bal
                
        total_por_pagar += rem_bal

        ncf_num = (inv.get('ncf') or inv.get('invoiceNumber') or '').lower()
        supplier_name = inv.get('supplierName', '')
        supplier_rnc = inv.get('supplierRnc', '')
        
        if query:
            if (query not in ncf_num and
                query not in supplier_name.lower() and
                query not in supplier_rnc.lower()):
                continue

        cxp_list.append({
            'id': inv.get('id'),
            'type': 'compra',
            'doc_type': 'Factura de Proveedor',
            'ncf_num': inv.get('ncf') or inv.get('invoiceNumber') or 'N/A',
            'supplier_name': supplier_name,
            'supplier_rnc': supplier_rnc,
            'fecha_creacion': inv_date_str,
            'fecha_vencimiento': due_date_str,
            'total': total_amt,
            'pagado': total_paid,
            'por_pagar': rem_bal,
            'days_diff': days_diff,
            'detail_url': url_for('web_purchase_orders.supplier_invoice_detail', invoice_id=inv.get('id'))
        })

    for exp in all_expenses:
        if exp.get('approvalStatus') == 'Pendiente':
            continue
        if exp.get('paymentType') != 'Crédito':
            continue
        status = exp.get('cxpStatus', 'Pendiente')
        if status == 'Saldada' or float(exp.get('cxpRemainingBalance', 0.0)) <= 0.01:
            continue

        inv_date_str = (exp.get('date') or exp.get('createdAt') or '')[:10]
        if not inv_date_str:
            continue
        try:
            inv_date = datetime.strptime(inv_date_str, '%Y-%m-%d').date()
        except ValueError:
            continue
            
        if inv_date > hasta_date:
            continue

        rem_bal = float(exp.get('cxpRemainingBalance', exp.get('amount', 0.0)))
        total_amt = float(exp.get('amount', 0.0))
        total_paid = total_amt - rem_bal
        
        due_date_str = (exp.get('dueDate') or exp.get('date') or exp.get('createdAt') or '')[:10]
        try:
            due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        except ValueError:
            due_date = inv_date

        days_diff = (hasta_date - due_date).days
        
        if days_diff <= 0:
            no_vencidas += rem_bal
        else:
            if days_diff <= 30:
                vencidas_30_menos += rem_bal
            elif days_diff <= 60:
                vencidas_31_60 += rem_bal
            elif days_diff <= 90:
                vencidas_61_90 += rem_bal
            else:
                vencidas_91_mas += rem_bal
                
        total_por_pagar += rem_bal

        ncf_num = (exp.get('ncf') or exp.get('documentNumber') or '').lower()
        supplier_name = exp.get('providerName', '')
        supplier_rnc = exp.get('rncEmisor', '')
        
        if query:
            if (query not in ncf_num and
                query not in supplier_name.lower() and
                query not in supplier_rnc.lower()):
                continue

        cxp_list.append({
            'id': exp.get('id'),
            'type': 'gasto',
            'doc_type': 'Gasto a Crédito',
            'ncf_num': exp.get('ncf') or exp.get('documentNumber') or 'N/A',
            'supplier_name': supplier_name,
            'supplier_rnc': supplier_rnc,
            'fecha_creacion': inv_date_str,
            'fecha_vencimiento': due_date_str,
            'total': total_amt,
            'pagado': total_paid,
            'por_pagar': rem_bal,
            'days_diff': days_diff,
            'detail_url': url_for('web_invoices.expense_detail', expense_id=exp.get('id'))
        })

    cxp_list.sort(key=lambda x: x['fecha_vencimiento'])

    total_items = len(cxp_list)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated = cxp_list[start_idx:end_idx]

    start_count = start_idx + 1 if total_items > 0 else 0
    end_count = min(page * per_page, total_items)

    return render_template(
        'reports/cxp_report.html',
        active_page='cxp_report',
        invoices=paginated,
        total_items=total_items,
        total_pages=total_pages,
        page=page,
        per_page=per_page,
        start_count=start_count,
        end_count=end_count,
        hasta=hasta_str,
        q=request.args.get('q', ''),
        vencidas_30_menos=vencidas_30_menos,
        vencidas_31_60=vencidas_31_60,
        vencidas_61_90=vencidas_61_90,
        vencidas_91_mas=vencidas_91_mas,
        no_vencidas=no_vencidas,
        total_por_pagar=total_por_pagar
    )


@web_reports_sales_bp.route('/reports/admin/cxp/export')
def cxp_report_export():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Cuentas por pagar", required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)
    
    hasta_str = request.args.get('hasta', '')
    if not hasta_str:
        hasta_str = now.strftime('%Y-%m-%d')
    try:
        hasta_date = datetime.strptime(hasta_str, '%Y-%m-%d').date()
    except ValueError:
        hasta_date = now.date()

    query = request.args.get('q', '').strip().lower()

    from app.services.supplier_invoice_service import SupplierInvoiceService
    
    purchase_invoices = SupplierInvoiceService.get_all(owner_uid, sandbox=sandbox)
    all_expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)

    cxp_list = []

    for inv in purchase_invoices:
        status = inv.get('cxpStatus', 'Pendiente')
        if status == 'Saldada' or float(inv.get('cxpRemainingBalance', 0.0)) <= 0.01:
            continue
            
        inv_date_str = (inv.get('date') or inv.get('createdAt') or '')[:10]
        if not inv_date_str:
            continue
        try:
            inv_date = datetime.strptime(inv_date_str, '%Y-%m-%d').date()
        except ValueError:
            continue
        if inv_date > hasta_date:
            continue

        rem_bal = float(inv.get('cxpRemainingBalance', inv.get('total', 0.0)))
        total_amt = float(inv.get('total', 0.0))
        total_paid = total_amt - rem_bal
        due_date_str = (inv.get('dueDate') or inv.get('date') or inv.get('createdAt') or '')[:10]

        ncf_num = (inv.get('ncf') or inv.get('invoiceNumber') or '').lower()
        supplier_name = inv.get('supplierName', '')
        supplier_rnc = inv.get('supplierRnc', '')
        
        if query:
            if (query not in ncf_num and
                query not in supplier_name.lower() and
                query not in supplier_rnc.lower()):
                continue

        cxp_list.append([
            'Factura de Proveedor',
            inv.get('ncf') or inv.get('invoiceNumber') or 'N/A',
            supplier_name,
            inv_date_str,
            due_date_str,
            f"{total_amt:.2f}",
            f"{total_paid:.2f}",
            f"{rem_bal:.2f}"
        ])

    for exp in all_expenses:
        if exp.get('approvalStatus') == 'Pendiente':
            continue
        if exp.get('paymentType') != 'Crédito':
            continue
        status = exp.get('cxpStatus', 'Pendiente')
        if status == 'Saldada' or float(exp.get('cxpRemainingBalance', 0.0)) <= 0.01:
            continue

        inv_date_str = (exp.get('date') or exp.get('createdAt') or '')[:10]
        if not inv_date_str:
            continue
        try:
            inv_date = datetime.strptime(inv_date_str, '%Y-%m-%d').date()
        except ValueError:
            continue
        if inv_date > hasta_date:
            continue

        rem_bal = float(exp.get('cxpRemainingBalance', exp.get('amount', 0.0)))
        total_amt = float(exp.get('amount', 0.0))
        total_paid = total_amt - rem_bal
        due_date_str = (exp.get('dueDate') or exp.get('date') or exp.get('createdAt') or '')[:10]

        ncf_num = (exp.get('ncf') or exp.get('documentNumber') or '').lower()
        supplier_name = exp.get('providerName', '')
        supplier_rnc = exp.get('rncEmisor', '')
        
        if query:
            if (query not in ncf_num and
                query not in supplier_name.lower() and
                query not in supplier_rnc.lower()):
                continue

        cxp_list.append([
            'Gasto a Crédito',
            exp.get('ncf') or exp.get('documentNumber') or 'N/A',
            supplier_name,
            inv_date_str,
            due_date_str,
            f"{total_amt:.2f}",
            f"{total_paid:.2f}",
            f"{rem_bal:.2f}"
        ])

    cxp_list.sort(key=lambda x: x[4])

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['Tipo de documento', 'NCF/Numero', 'Proveedor', 'Creacion', 'Vencimiento', 'Total', 'Pagado', 'Por pagar'])
    for row in cxp_list:
        writer.writerow(row)

    buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    return send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'reporte_cxp_{hasta_str}.csv'
    )


@web_reports_sales_bp.route('/reports/admin/inventory-value')
def inventory_value_report():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageInventory'):
        return render_template('auth/restricted.html', feature_name="Valor de inventario", required_permission="canManageInventory")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    warehouse_id = request.args.get('warehouse_id', '').strip()
    query = request.args.get('q', '').strip().lower()

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get('per_page', 10))
    except ValueError:
        per_page = 10
    if per_page < 1:
        per_page = 10

    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox) or []
    items = DatabaseService.get_items(owner_uid, sandbox=sandbox) or []
    stocks = DatabaseService.get_inventory_stock(owner_uid, sandbox=sandbox) or []

    wh_map = {wh['id']: wh['name'] for wh in warehouses}
    items_map = {}
    for it in items:
        if it.get('type', 'Bien') == 'Bien':
            items_map[it['id']] = {
                'name': it.get('name', 'Sin nombre'),
                'reference': it.get('reference', 'N/A'),
                'costPrice': float(it.get('costPrice', 0.0))
            }

    inventory_rows = []
    total_value = 0.0

    for st in stocks:
        item_id = st.get('itemId')
        wh_id = st.get('warehouseId')
        qty = float(st.get('quantity', 0.0))

        if item_id not in items_map:
            continue
        if warehouse_id and wh_id != warehouse_id:
            continue

        item_info = items_map[item_id]
        cost = item_info['costPrice']
        row_value = qty * cost

        total_value += row_value

        wh_name = wh_map.get(wh_id, 'Desconocido')
        item_name = item_info['name']
        ref = item_info['reference']

        if query:
            if (query not in item_name.lower() and
                query not in ref.lower() and
                query not in wh_name.lower()):
                continue

        inventory_rows.append({
            'reference': ref,
            'name': item_name,
            'warehouse_name': wh_name,
            'quantity': qty,
            'cost_price': cost,
            'total_value': row_value
        })

    inventory_rows.sort(key=lambda x: x['name'].lower())

    total_items = len(inventory_rows)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated = inventory_rows[start_idx:end_idx]

    start_count = start_idx + 1 if total_items > 0 else 0
    end_count = min(page * per_page, total_items)

    return render_template(
        'reports/inventory_value.html',
        active_page='inventory_value',
        rows=paginated,
        warehouses=warehouses,
        selected_warehouse_id=warehouse_id,
        q=request.args.get('q', ''),
        total_items=total_items,
        total_pages=total_pages,
        page=page,
        per_page=per_page,
        start_count=start_count,
        end_count=end_count,
        total_value=total_value
    )


@web_reports_sales_bp.route('/reports/admin/inventory-value/export')
def inventory_value_export():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageInventory'):
        return render_template('auth/restricted.html', feature_name="Valor de inventario", required_permission="canManageInventory")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    warehouse_id = request.args.get('warehouse_id', '').strip()
    query = request.args.get('q', '').strip().lower()

    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox) or []
    items = DatabaseService.get_items(owner_uid, sandbox=sandbox) or []
    stocks = DatabaseService.get_inventory_stock(owner_uid, sandbox=sandbox) or []

    wh_map = {wh['id']: wh['name'] for wh in warehouses}
    items_map = {}
    for it in items:
        if it.get('type', 'Bien') == 'Bien':
            items_map[it['id']] = {
                'name': it.get('name', 'Sin nombre'),
                'reference': it.get('reference', 'N/A'),
                'costPrice': float(it.get('costPrice', 0.0))
            }

    inventory_rows = []

    for st in stocks:
        item_id = st.get('itemId')
        wh_id = st.get('warehouseId')
        qty = float(st.get('quantity', 0.0))

        if item_id not in items_map:
            continue
        if warehouse_id and wh_id != warehouse_id:
            continue

        item_info = items_map[item_id]
        cost = item_info['costPrice']
        row_value = qty * cost

        wh_name = wh_map.get(wh_id, 'Desconocido')
        item_name = item_info['name']
        ref = item_info['reference']

        if query:
            if (query not in item_name.lower() and
                query not in ref.lower() and
                query not in wh_name.lower()):
                continue

        inventory_rows.append([
            ref,
            item_name,
            wh_name,
            f"{qty:.2f}",
            f"{cost:.2f}",
            f"{row_value:.2f}"
        ])

    inventory_rows.sort(key=lambda x: x[1].lower())

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['Referencia', 'Item / Producto', 'Almacen', 'Cantidad', 'Costo promedio', 'Valor total'])
    for row in inventory_rows:
        writer.writerow(row)

    buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    return send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'valor_inventario.csv'
    )


def _compute_transactions(owner_uid, sandbox, year, month, query=None):
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox) or []
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox) or []
    bank_accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox) or []
    
    acc_map = {acc['id']: acc['name'] for acc in bank_accounts}
    
    transactions = []
    
    # 1. ENTRADAS: Payments on invoices
    for inv in invoices:
        payments = DatabaseService.get_invoice_payments(owner_uid, inv['id'], sandbox=sandbox) or []
        for pmt in payments:
            pmt_date = pmt.get('paymentDate') or inv.get('date') or ''
            if not pmt_date:
                continue
            
            try:
                date_obj = datetime.fromisoformat(pmt_date.replace('Z', '+00:00'))
            except Exception:
                try:
                    date_obj = datetime.strptime(pmt_date[:10], '%Y-%m-%d')
                except Exception:
                    continue
            
            if date_obj.year != year:
                continue
            if month > 0 and date_obj.month != month:
                continue
                
            amount = float(pmt.get('amount', 0.0))
            method = pmt.get('paymentMethod') or 'Efectivo'
            bank_name = pmt.get('bank') or 'Caja General'
            
            if bank_name in acc_map:
                bank_name = acc_map[bank_name]
                
            desc = f"Pago Recibido: Factura {inv.get('invoiceNumber') or inv.get('id')} — {inv.get('clientName') or 'Cliente'}"
            
            if query:
                q_lower = query.lower()
                if (q_lower not in desc.lower() and
                    q_lower not in method.lower() and
                    q_lower not in bank_name.lower()):
                    continue
                    
            transactions.append({
                'date': pmt_date[:10] if len(pmt_date) >= 10 else pmt_date,
                'description': desc,
                'bank': bank_name,
                'method': method,
                'type': 'ENTRADA',
                'amount': amount
            })
            
    # 2. SALIDAS: Payments on expenses & Cash Expenses (Contado)
    for exp in expenses:
        if exp.get('approvalStatus') == 'Rechazado':
            continue
            
        is_contado = exp.get('paymentType', 'Contado') == 'Contado'
        if is_contado:
            exp_date = exp.get('date') or ''
            if not exp_date:
                continue
                
            try:
                date_obj = datetime.fromisoformat(exp_date.replace('Z', '+00:00'))
            except Exception:
                try:
                    date_obj = datetime.strptime(exp_date[:10], '%Y-%m-%d')
                except Exception:
                    continue
                    
            if date_obj.year != year:
                continue
            if month > 0 and date_obj.month != month:
                continue
                
            amount = float(exp.get('amount', 0.0))
            method = 'Efectivo'
            bank_name = 'Caja General'
            
            desc = f"Gasto Contado: {exp.get('concept') or 'Compra'} — {exp.get('rncEmisor') or 'Proveedor'}"
            
            if query:
                q_lower = query.lower()
                if (q_lower not in desc.lower() and
                    q_lower not in method.lower() and
                    q_lower not in bank_name.lower()):
                    continue
                    
            transactions.append({
                'date': exp_date[:10] if len(exp_date) >= 10 else exp_date,
                'description': desc,
                'bank': bank_name,
                'method': method,
                'type': 'SALIDA',
                'amount': amount
            })
        else:
            payments = DatabaseService.get_cxp_payments(owner_uid, exp['id'], sandbox=sandbox) or []
            for pmt in payments:
                pmt_date = pmt.get('paymentDate') or exp.get('date') or ''
                if not pmt_date:
                    continue
                    
                try:
                    date_obj = datetime.fromisoformat(pmt_date.replace('Z', '+00:00'))
                except Exception:
                    try:
                        date_obj = datetime.strptime(pmt_date[:10], '%Y-%m-%d')
                    except Exception:
                        continue
                        
                if date_obj.year != year:
                    continue
                if month > 0 and date_obj.month != month:
                    continue
                    
                amount = float(pmt.get('amount', 0.0))
                method = 'Efectivo'
                bank_name = 'Caja General'
                
                desc = f"Pago Gasto: {exp.get('concept') or 'Compra'} — {exp.get('rncEmisor') or 'Proveedor'}"
                
                if query:
                    q_lower = query.lower()
                    if (q_lower not in desc.lower() and
                        q_lower not in method.lower() and
                        q_lower not in bank_name.lower()):
                        continue
                        
                transactions.append({
                    'date': pmt_date[:10] if len(pmt_date) >= 10 else pmt_date,
                    'description': desc,
                    'bank': bank_name,
                    'method': method,
                    'type': 'SALIDA',
                    'amount': amount
                })
                
    transactions.sort(key=lambda x: x['date'], reverse=True)
    
    total_inflow = sum(tx['amount'] for tx in transactions if tx['type'] == 'ENTRADA')
    total_outflow = sum(tx['amount'] for tx in transactions if tx['type'] == 'SALIDA')
    
    return transactions, total_inflow, total_outflow


@web_reports_sales_bp.route('/reports/admin/transactions')
def transactions_report():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    now = datetime.now(timezone.utc)
    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', now.month))
    except ValueError:
        month = now.month
    
    query = request.args.get('q', '').strip()
    
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get('per_page', 10))
    except ValueError:
        per_page = 10
    if per_page < 1:
        per_page = 10
        
    transactions, total_inflow, total_outflow = _compute_transactions(owner_uid, sandbox, year, month, query)
    
    total_items = len(transactions)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
        
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated = transactions[start_idx:end_idx]
    
    start_count = start_idx + 1 if total_items > 0 else 0
    end_count = min(page * per_page, total_items)
    
    years_range = list(range(now.year - 5, now.year + 1))
    
    return render_template(
        'reports/transactions.html',
        active_page='transactions',
        rows=paginated,
        year=year,
        month=month,
        years_range=years_range,
        months_list=MONTH_FILTER_OPTIONS,
        q=query,
        total_items=total_items,
        total_pages=total_pages,
        page=page,
        per_page=per_page,
        start_count=start_count,
        end_count=end_count,
        total_inflow=total_inflow,
        total_outflow=total_outflow
    )


@web_reports_sales_bp.route('/reports/admin/transactions/export')
def transactions_export():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    now = datetime.now(timezone.utc)
    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', now.month))
    except ValueError:
        month = now.month
        
    query = request.args.get('q', '').strip()
    
    transactions, _, _ = _compute_transactions(owner_uid, sandbox, year, month, query)
    
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['Fecha', 'Detalle / Concepto', 'Método / Cuenta', 'Tipo', 'Monto'])
    for tx in transactions:
        writer.writerow([
            tx['date'],
            tx['description'],
            f"{tx['method']} ({tx['bank']})",
            tx['type'],
            f"{tx['amount']:.2f}"
        ])
        
    buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    return send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'transacciones_{year}_{month}.csv'
    )


@web_reports_sales_bp.route('/reports/admin/purchases')
def purchases_report():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    now = datetime.now(timezone.utc)
    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', now.month))
    except ValueError:
        month = now.month
        
    query = request.args.get('q', '').strip().lower()
    
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get('per_page', 10))
    except ValueError:
        per_page = 10
    if per_page < 1:
        per_page = 10
        
    from app.services.supplier_invoice_service import SupplierInvoiceService
    invoices = SupplierInvoiceService.get_all(owner_uid, sandbox=sandbox) or []
    
    filtered_invoices = []
    total_before_tax = 0.0
    total_after_tax = 0.0
    
    for inv in invoices:
        inv_date = inv.get('date', '')
        if not inv_date:
            continue
            
        try:
            date_obj = datetime.fromisoformat(inv_date.replace('Z', '+00:00'))
        except Exception:
            try:
                date_obj = datetime.strptime(inv_date[:10], '%Y-%m-%d')
            except Exception:
                continue
                
        if date_obj.year != year:
            continue
        if month > 0 and date_obj.month != month:
            continue
            
        supplier_name = inv.get('supplierName', '')
        supplier_rnc = inv.get('supplierRnc', '')
        inv_num = inv.get('invoiceNumber', '')
        supp_inv_num = inv.get('supplierInvoiceNumber', '')
        ncf = inv.get('ncf', '')
        
        if query:
            haystack = f"{supplier_name} {supplier_rnc} {inv_num} {supp_inv_num} {ncf}".lower()
            if query not in haystack:
                continue
                
        sub = float(inv.get('subtotal', 0.0))
        disc = float(inv.get('discount', 0.0))
        tax = float(inv.get('itbis', 0.0))
        tot = float(inv.get('total', 0.0))
        
        before_tax = sub - disc
        after_tax = tot
        
        total_before_tax += before_tax
        total_after_tax += after_tax
        
        filtered_invoices.append({
            'id': inv['id'],
            'invoice_number': inv_num,
            'supplier_invoice_number': supp_inv_num or 'N/A',
            'ncf': ncf or 'N/A',
            'supplier_name': supplier_name,
            'supplier_rnc': supplier_rnc,
            'date': inv_date[:10],
            'due_date': inv.get('dueDate', '')[:10],
            'before_tax': before_tax,
            'tax': tax,
            'after_tax': after_tax,
            'status': inv.get('cxpStatus', 'Pendiente')
        })
        
    filtered_invoices.sort(key=lambda x: x['date'], reverse=True)
    
    total_items = len(filtered_invoices)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
        
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated = filtered_invoices[start_idx:end_idx]
    
    start_count = start_idx + 1 if total_items > 0 else 0
    end_count = min(page * per_page, total_items)
    
    years_range = list(range(now.year - 5, now.year + 1))
    
    return render_template(
        'reports/purchases.html',
        active_page='purchases',
        rows=paginated,
        year=year,
        month=month,
        years_range=years_range,
        months_list=MONTH_FILTER_OPTIONS,
        q=request.args.get('q', ''),
        total_items=total_items,
        total_pages=total_pages,
        page=page,
        per_page=per_page,
        start_count=start_count,
        end_count=end_count,
        total_before_tax=total_before_tax,
        total_after_tax=total_after_tax
    )


@web_reports_sales_bp.route('/reports/admin/purchases/export')
def purchases_export():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    now = datetime.now(timezone.utc)
    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', now.month))
    except ValueError:
        month = now.month
        
    query = request.args.get('q', '').strip().lower()
    
    from app.services.supplier_invoice_service import SupplierInvoiceService
    invoices = SupplierInvoiceService.get_all(owner_uid, sandbox=sandbox) or []
    
    rows_list = []
    for inv in invoices:
        inv_date = inv.get('date', '')
        if not inv_date:
            continue
            
        try:
            date_obj = datetime.fromisoformat(inv_date.replace('Z', '+00:00'))
        except Exception:
            try:
                date_obj = datetime.strptime(inv_date[:10], '%Y-%m-%d')
            except Exception:
                continue
                
        if date_obj.year != year:
            continue
        if month > 0 and date_obj.month != month:
            continue
            
        supplier_name = inv.get('supplierName', '')
        supplier_rnc = inv.get('supplierRnc', '')
        inv_num = inv.get('invoiceNumber', '')
        supp_inv_num = inv.get('supplierInvoiceNumber', '')
        ncf = inv.get('ncf', '')
        
        if query:
            haystack = f"{supplier_name} {supplier_rnc} {inv_num} {supp_inv_num} {ncf}".lower()
            if query not in haystack:
                continue
                
        sub = float(inv.get('subtotal', 0.0))
        disc = float(inv.get('discount', 0.0))
        tax = float(inv.get('itbis', 0.0))
        tot = float(inv.get('total', 0.0))
        
        before_tax = sub - disc
        after_tax = tot
        
        rows_list.append([
            inv_num,
            supp_inv_num or 'N/A',
            supplier_name,
            supplier_rnc,
            ncf or 'N/A',
            inv_date[:10],
            inv.get('dueDate', '')[:10],
            f"{before_tax:.2f}",
            f"{tax:.2f}",
            f"{after_tax:.2f}",
            inv.get('cxpStatus', 'Pendiente')
        ])
        
    rows_list.sort(key=lambda x: x[5], reverse=True)
    
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['Factura #', 'Factura Proveedor', 'Proveedor', 'RNC', 'NCF', 'Fecha Emision', 'Vencimiento', 'Antes de impuestos', 'Impuestos', 'Despues de impuestos', 'Estado'])
    for row in rows_list:
        writer.writerow(row)
        
    buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    return send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'compras_{year}_{month}.csv'
    )


@web_reports_sales_bp.route('/reports/financial/cash-flow')
def cash_flow_report():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    now = datetime.now(timezone.utc)
    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', now.month))
    except ValueError:
        month = now.month
        
    # Get 3 months rolling range ending at (year, month)
    import calendar
    from datetime import date
    
    m3_yr, m3_mo = year, month
    if m3_mo == 1:
        m2_yr, m2_mo = year - 1, 12
    else:
        m2_yr, m2_mo = year, month - 1
        
    if m2_mo == 1:
        m1_yr, m1_mo = m2_yr - 1, 12
    else:
        m1_yr, m1_mo = m2_yr, m2_mo - 1
        
    rolling_periods = [
        (m1_yr, m1_mo),
        (m2_yr, m2_mo),
        (m3_yr, m3_mo)
    ]
    
    # 1. Accounts initial balance sum
    accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox) or []
    initial_balance_all_accounts = sum(float(a.get('initialBalance', 0.0)) for a in accounts)
    
    # 2. Get all inflows (sales payments)
    inflows = []
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox) or []
    for inv in invoices:
        if inv.get('isQuotation') or inv.get('status') in ('Anulada', 'Borrador', 'Consolidada'):
            continue
        pmts = DatabaseService.get_invoice_payments(owner_uid, inv['id'], sandbox=sandbox) or []
        for pmt in pmts:
            pmt_date = pmt.get('paymentDate') or inv.get('date') or ''
            if pmt_date:
                try:
                    dt = datetime.fromisoformat(pmt_date.replace('Z', '+00:00'))
                except Exception:
                    try:
                        dt = datetime.strptime(pmt_date[:10], '%Y-%m-%d')
                    except Exception:
                        continue
                inflows.append({
                    'date': dt.date(),
                    'amount': float(pmt.get('amount', 0.0))
                })
                
    # 3. Get all outflows (expenses/supplier bill payments)
    outflows = []
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox) or []
    for exp in expenses:
        if exp.get('approvalStatus') == 'Rechazado':
            continue
        is_contado = exp.get('paymentType', 'Contado') == 'Contado'
        if is_contado:
            exp_date = exp.get('date') or ''
            if exp_date:
                try:
                    dt = datetime.fromisoformat(exp_date.replace('Z', '+00:00'))
                except Exception:
                    try:
                        dt = datetime.strptime(exp_date[:10], '%Y-%m-%d')
                    except Exception:
                        continue
                outflows.append({
                    'date': dt.date(),
                    'amount': float(exp.get('total') or exp.get('amount', 0.0))
                })
        else:
            pmts = DatabaseService.get_cxp_payments(owner_uid, exp['id'], sandbox=sandbox) or []
            for pmt in pmts:
                pmt_date = pmt.get('paymentDate') or exp.get('date') or ''
                if pmt_date:
                    try:
                        dt = datetime.fromisoformat(pmt_date.replace('Z', '+00:00'))
                    except Exception:
                        try:
                            dt = datetime.strptime(pmt_date[:10], '%Y-%m-%d')
                        except Exception:
                            continue
                    outflows.append({
                        'date': dt.date(),
                        'amount': float(pmt.get('amount', 0.0))
                    })
                    
    # Helper to calculate balance at a specific date
    def get_balance_before(target_date):
        inf_sum = sum(item['amount'] for item in inflows if item['date'] < target_date)
        out_sum = sum(item['amount'] for item in outflows if item['date'] < target_date)
        return initial_balance_all_accounts + inf_sum - out_sum
        
    # Build data for the 3 rolling months
    months_columns = []
    
    # Check if there is any movement in the whole 3 months
    total_inflow_period = 0.0
    total_outflow_period = 0.0
    
    for yr, mo in rolling_periods:
        start_dt = date(yr, mo, 1)
        last_day = calendar.monthrange(yr, mo)[1]
        end_dt = date(yr, mo, last_day)
        
        # Calculate monthly totals
        inf_mo = sum(item['amount'] for item in inflows if start_dt <= item['date'] <= end_dt)
        out_mo = sum(item['amount'] for item in outflows if start_dt <= item['date'] <= end_dt)
        
        total_inflow_period += inf_mo
        total_outflow_period += out_mo
        
        # Initial balance for this month
        bal_init = get_balance_before(start_dt)
        net_mo = inf_mo - out_mo
        bal_final = bal_init + net_mo
        
        months_columns.append({
            'label': f"{MONTH_NAMES[mo-1]} {yr}",
            'chart_label': f"{MONTH_NAMES[mo-1][:3]} {yr}",
            'initial': round(bal_init, 2),
            'inflow': round(inf_mo, 2),
            'outflow': round(out_mo, 2),
            'net': round(net_mo, 2),
            'final': round(bal_final, 2)
        })
        
    years_range = list(range(now.year - 5, now.year + 1))
    
    has_movements = (total_inflow_period > 0 or total_outflow_period > 0)
    
    return render_template(
        'reports/cash_flow.html',
        active_page='cash_flow',
        year=year,
        month=month,
        years_range=years_range,
        months_list=MONTH_FILTER_OPTIONS[1:], # skip "Todo el año" option since Cash Flow is rolling month target
        columns=months_columns,
        has_movements=has_movements
    )


@web_reports_sales_bp.route('/reports/financial/cash-flow/export')
def cash_flow_export():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    now = datetime.now(timezone.utc)
    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', now.month))
    except ValueError:
        month = now.month
        
    import calendar
    from datetime import date
    
    m3_yr, m3_mo = year, month
    if m3_mo == 1:
        m2_yr, m2_mo = year - 1, 12
    else:
        m2_yr, m2_mo = year, month - 1
        
    if m2_mo == 1:
        m1_yr, m1_mo = m2_yr - 1, 12
    else:
        m1_yr, m1_mo = m2_yr, m2_mo - 1
        
    rolling_periods = [
        (m1_yr, m1_mo),
        (m2_yr, m2_mo),
        (m3_yr, m3_mo)
    ]
    
    accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox) or []
    initial_balance_all_accounts = sum(float(a.get('initialBalance', 0.0)) for a in accounts)
    
    inflows = []
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox) or []
    for inv in invoices:
        if inv.get('isQuotation') or inv.get('status') in ('Anulada', 'Borrador', 'Consolidada'):
            continue
        pmts = DatabaseService.get_invoice_payments(owner_uid, inv['id'], sandbox=sandbox) or []
        for pmt in pmts:
            pmt_date = pmt.get('paymentDate') or inv.get('date') or ''
            if pmt_date:
                try:
                    dt = datetime.fromisoformat(pmt_date.replace('Z', '+00:00'))
                except Exception:
                    try:
                        dt = datetime.strptime(pmt_date[:10], '%Y-%m-%d')
                    except Exception:
                        continue
                inflows.append({
                    'date': dt.date(),
                    'amount': float(pmt.get('amount', 0.0))
                })
                
    outflows = []
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox) or []
    for exp in expenses:
        if exp.get('approvalStatus') == 'Rechazado':
            continue
        is_contado = exp.get('paymentType', 'Contado') == 'Contado'
        if is_contado:
            exp_date = exp.get('date') or ''
            if exp_date:
                try:
                    dt = datetime.fromisoformat(exp_date.replace('Z', '+00:00'))
                except Exception:
                    try:
                        dt = datetime.strptime(exp_date[:10], '%Y-%m-%d')
                    except Exception:
                        continue
                outflows.append({
                    'date': dt.date(),
                    'amount': float(exp.get('total') or exp.get('amount', 0.0))
                })
        else:
            pmts = DatabaseService.get_cxp_payments(owner_uid, exp['id'], sandbox=sandbox) or []
            for pmt in pmts:
                pmt_date = pmt.get('paymentDate') or exp.get('date') or ''
                if pmt_date:
                    try:
                        dt = datetime.fromisoformat(pmt_date.replace('Z', '+00:00'))
                    except Exception:
                        try:
                            dt = datetime.strptime(pmt_date[:10], '%Y-%m-%d')
                        except Exception:
                            continue
                    outflows.append({
                        'date': dt.date(),
                        'amount': float(pmt.get('amount', 0.0))
                    })
                    
    def get_balance_before(target_date):
        inf_sum = sum(item['amount'] for item in inflows if item['date'] < target_date)
        out_sum = sum(item['amount'] for item in outflows if item['date'] < target_date)
        return initial_balance_all_accounts + inf_sum - out_sum
        
    months_columns = []
    for yr, mo in rolling_periods:
        start_dt = date(yr, mo, 1)
        last_day = calendar.monthrange(yr, mo)[1]
        end_dt = date(yr, mo, last_day)
        
        inf_mo = sum(item['amount'] for item in inflows if start_dt <= item['date'] <= end_dt)
        out_mo = sum(item['amount'] for item in outflows if start_dt <= item['date'] <= end_dt)
        
        bal_init = get_balance_before(start_dt)
        net_mo = inf_mo - out_mo
        bal_final = bal_init + net_mo
        
        months_columns.append({
            'label': f"{MONTH_NAMES[mo-1]} {yr}",
            'initial': f"{bal_init:.2f}",
            'inflow': f"{inf_mo:.2f}",
            'outflow': f"{out_mo:.2f}",
            'net': f"{net_mo:.2f}",
            'final': f"{bal_final:.2f}"
        })
        
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    
    # CSV Header Row: Concepto, Month 1, Month 2, Month 3
    headers = ['Concepto'] + [c['label'] for c in months_columns]
    writer.writerow(headers)
    
    writer.writerow(['Saldo inicial en caja y bancos'] + [c['initial'] for c in months_columns])
    writer.writerow(['Entradas'] + [c['inflow'] for c in months_columns])
    writer.writerow(['Salidas'] + [c['outflow'] for c in months_columns])
    writer.writerow(['Saldo del periodo'] + [c['net'] for c in months_columns])
    writer.writerow(['Saldo final en caja y bancos'] + [c['final'] for c in months_columns])
    
    buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    return send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'flujo_de_caja_{year}_{month}.csv'
    )


def _it1_coll(owner_uid, sandbox):
    from app.services.db_service import db_firestore
    coll_name = "sandbox_it1_reports" if sandbox else "it1_reports"
    return db_firestore.collection("users").document(owner_uid).collection(coll_name)


@web_reports_sales_bp.route('/reports/fiscal/it1')
def it1_reports_list():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Reporte IT1", required_permission="canInvoice")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    now = datetime.now(timezone.utc)
    year_filter = request.args.get('year', '').strip()
    month_filter = request.args.get('month', '').strip()
    
    from app.services.db_service import firebase_initialized, db_firestore
    reports = []
    if firebase_initialized and db_firestore is not None:
        try:
            coll = _it1_coll(owner_uid, sandbox)
            docs = coll.get()
            for d in docs:
                data = d.to_dict()
                reports.append(data)
        except Exception as e:
            print(f"⚠️ Error al obtener reportes IT-1: {e}")
            
    filtered = []
    for r in reports:
        if year_filter and str(r.get('year')) != year_filter:
            continue
        if month_filter and str(r.get('month')) != month_filter:
            continue
        filtered.append(r)
        
    # Sort chronological desc (year desc, month desc)
    filtered.sort(key=lambda x: (int(x.get('year', 0)), int(x.get('month', 0))), reverse=True)
    
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get('per_page', 10))
    except ValueError:
        per_page = 10
        
    total_items = len(filtered)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
        
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated = filtered[start_idx:end_idx]
    
    start_count = start_idx + 1 if total_items > 0 else 0
    end_count = min(page * per_page, total_items)
    
    years_range = list(range(now.year - 5, now.year + 1))
    
    return render_template(
        'reports/it1_list.html',
        active_page='reports',
        rows=paginated,
        year=year_filter,
        month=month_filter,
        years_range=years_range,
        months_list=MONTH_FILTER_OPTIONS[1:],
        total_items=total_items,
        total_pages=total_pages,
        page=page,
        per_page=per_page,
        start_count=start_count,
        end_count=end_count
    )


@web_reports_sales_bp.route('/reports/fiscal/it1/new', methods=['GET', 'POST'])
def it1_new_report():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Reporte IT1", required_permission="canInvoice")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)
    
    # Defaults
    year_val = now.year
    month_val = now.month
    
    if request.method == 'POST':
        try:
            year_val = int(request.form.get('year', now.year))
        except ValueError:
            year_val = now.year
        try:
            month_val = int(request.form.get('month', now.month))
        except ValueError:
            month_val = now.month
            
        from app.services.db_service import firebase_initialized, db_firestore
        if firebase_initialized and db_firestore is not None:
            coll = _it1_coll(owner_uid, sandbox)
            # Check duplicate
            existing_docs = coll.where('year', '==', year_val).where('month', '==', month_val).get()
            if len(existing_docs) > 0:
                flash(f"❌ Ya existe un reporte IT-1 registrado para el período {month_val:02d}/{year_val}.", "error")
                years_range = list(range(now.year - 5, now.year + 1))
                return render_template('reports/it1_new.html', active_page='reports', year=year_val, month=month_val, years_range=years_range, months_list=MONTH_FILTER_OPTIONS[1:], preview_data=None)
                
        # 1. Calculate values for that period
        invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox) or []
        expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox) or []
        
        real_invoices = []
        for inv in invoices:
            if inv.get('isQuotation') or inv.get('status') in ('Anulada', 'Borrador', 'Consolidada'):
                continue
            inv_date = (inv.get('date') or inv.get('createdAt') or '')[:7]
            if inv_date == f"{year_val:04d}-{month_val:02d}":
                real_invoices.append(inv)
                
        period_expenses = []
        for exp in expenses:
            if exp.get('approvalStatus') == 'Rechazado':
                continue
            exp_date = (exp.get('date') or exp.get('createdAt') or '')[:7]
            if exp_date == f"{year_val:04d}-{month_val:02d}":
                period_expenses.append(exp)
                
        sales_subtotal = sum(float(inv.get('subtotal', 0.0)) for inv in real_invoices)
        total_itbis_sales = sum(float(inv.get('totalITBIS', 0.0)) for inv in real_invoices)
        total_retained_itbis = sum(float(inv.get('retainedITBIS', 0.0)) for inv in real_invoices)
        total_retained_isr = sum(float(inv.get('retainedISR', 0.0)) for inv in real_invoices)
        
        expenses_subtotal = sum(float(exp.get('amount', 0.0)) - float(exp.get('itbisAmount', 0.0)) for exp in period_expenses)
        total_itbis_expenses = sum(float(exp.get('itbisAmount', 0.0)) for exp in period_expenses if exp.get('isITBISDeductible', True))
        
        import uuid
        report_id = str(uuid.uuid4())
        doc_data = {
            "id": report_id,
            "year": year_val,
            "month": month_val,
            "status": "Borrador",
            "sales_subtotal": round(sales_subtotal, 2),
            "total_itbis_sales": round(total_itbis_sales, 2),
            "total_retained_itbis": round(total_retained_itbis, 2),
            "total_retained_isr": round(total_retained_isr, 2),
            "expenses_subtotal": round(expenses_subtotal, 2),
            "total_itbis_expenses": round(total_itbis_expenses, 2),
            "createdAt": datetime.now(timezone.utc).isoformat()
        }
        
        if firebase_initialized and db_firestore is not None:
            try:
                coll.document(report_id).set(doc_data)
                flash(f"✅ Reporte IT-1 para el período {month_val:02d}/{year_val} generado exitosamente.", "success")
            except Exception as e:
                print(f"⚠️ Error al guardar reporte IT-1: {e}")
                
        return redirect(url_for('web_reports_sales.it1_report_detail', report_id=report_id))
        
    # GET: check if we should display a preview
    preview_data = None
    try:
        req_year = request.args.get('year')
        req_month = request.args.get('month')
        if req_year and req_month:
            year_val = int(req_year)
            month_val = int(req_month)
            
            invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox) or []
            expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox) or []
            
            real_invoices = []
            for inv in invoices:
                if inv.get('isQuotation') or inv.get('status') in ('Anulada', 'Borrador', 'Consolidada'):
                    continue
                inv_date = (inv.get('date') or inv.get('createdAt') or '')[:7]
                if inv_date == f"{year_val:04d}-{month_val:02d}":
                    real_invoices.append(inv)
                    
            period_expenses = []
            for exp in expenses:
                if exp.get('approvalStatus') == 'Rechazado':
                    continue
                exp_date = (exp.get('date') or exp.get('createdAt') or '')[:7]
                if exp_date == f"{year_val:04d}-{month_val:02d}":
                    period_expenses.append(exp)
                    
            sales_subtotal = sum(float(inv.get('subtotal', 0.0)) for inv in real_invoices)
            total_itbis_sales = sum(float(inv.get('totalITBIS', 0.0)) for inv in real_invoices)
            total_retained_itbis = sum(float(inv.get('retainedITBIS', 0.0)) for inv in real_invoices)
            total_retained_isr = sum(float(inv.get('retainedISR', 0.0)) for inv in real_invoices)
            
            expenses_subtotal = sum(float(exp.get('amount', 0.0)) - float(exp.get('itbisAmount', 0.0)) for exp in period_expenses)
            total_itbis_expenses = sum(float(exp.get('itbisAmount', 0.0)) for exp in period_expenses if exp.get('isITBISDeductible', True))
            
            preview_data = {
                "sales_subtotal": round(sales_subtotal, 2),
                "total_itbis_sales": round(total_itbis_sales, 2),
                "total_retained_itbis": round(total_retained_itbis, 2),
                "total_retained_isr": round(total_retained_isr, 2),
                "expenses_subtotal": round(expenses_subtotal, 2),
                "total_itbis_expenses": round(total_itbis_expenses, 2),
                "itbis_balance": round(total_itbis_sales - total_itbis_expenses, 2)
            }
    except Exception as e:
        print(f"⚠️ Error al generar vista previa IT-1: {e}")
        
    years_range = list(range(now.year - 5, now.year + 1))
    return render_template(
        'reports/it1_new.html',
        active_page='reports',
        year=year_val,
        month=month_val,
        years_range=years_range,
        months_list=MONTH_FILTER_OPTIONS[1:],
        preview_data=preview_data
    )


@web_reports_sales_bp.route('/reports/fiscal/it1/<report_id>', methods=['GET', 'POST'])
def it1_report_detail(report_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Reporte IT1", required_permission="canInvoice")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    from app.services.db_service import firebase_initialized, db_firestore
    report = None
    if firebase_initialized and db_firestore is not None:
        try:
            coll = _it1_coll(owner_uid, sandbox)
            doc = coll.document(report_id).get()
            if doc.exists:
                report = doc.to_dict()
        except Exception as e:
            print(f"⚠️ Error al obtener reporte IT-1 {report_id}: {e}")
            
    if not report:
        flash("❌ Reporte no encontrado.", "error")
        return redirect(url_for('web_reports_sales.it1_reports_list'))
        
    if request.method == 'POST':
        new_status = request.form.get('status')
        if new_status in ('Borrador', 'Presentado'):
            report['status'] = new_status
            if firebase_initialized and db_firestore is not None:
                try:
                    coll.document(report_id).update({"status": new_status})
                    flash(f"✅ Estado del reporte actualizado a '{new_status}'.", "success")
                except Exception as e:
                    print(f"⚠️ Error al actualizar estado del reporte: {e}")
                    
    current_period = f"{report.get('month'):02d}/{report.get('year')}"
    return render_template(
        'reports/it1.html',
        active_page='reports',
        it1=report,
        report=report,
        current_period=current_period
    )


@web_reports_sales_bp.route('/reports/fiscal/it1/<report_id>/delete', methods=['POST'])
def it1_report_delete(report_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Reporte IT1", required_permission="canInvoice")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    from app.services.db_service import firebase_initialized, db_firestore
    if firebase_initialized and db_firestore is not None:
        try:
            coll = _it1_coll(owner_uid, sandbox)
            coll.document(report_id).delete()
            flash("✅ Reporte IT-1 eliminado correctamente.", "success")
        except Exception as e:
            print(f"⚠️ Error al eliminar reporte IT-1 {report_id}: {e}")
            
    return redirect(url_for('web_reports_sales.it1_reports_list'))


# ─────────────────────────────────────────────────────────────────────────────
# REPORTE DETALLADO DE IMPUESTOS
# ─────────────────────────────────────────────────────────────────────────────

TAX_LABELS = [
    "ITBIS (18%)",
    "ITBIS (16%)",
    "ITBIS (0%)",
    "Exento (0%)",
    "Propina (10%)",
    "CDT (2%)",
]


def _classify_rate(rate_float):
    """Map a numeric rate to a canonical tax label."""
    if 0.17 <= rate_float <= 0.19:
        return "ITBIS (18%)"
    if 0.15 <= rate_float < 0.17:
        return "ITBIS (16%)"
    return "ITBIS (0%)"


def _empty_tax_breakdown():
    return {label: {"base": 0.0, "tax": 0.0} for label in TAX_LABELS}


def _invoice_tax_breakdown(inv):
    """Return per-label tax breakdown for a sales invoice."""
    breakdown = _empty_tax_breakdown()
    for item in inv.get("items", []):
        rate = float(item.get("itbisRate", 0) or 0)
        base = float(item.get("subtotal", 0) or 0)
        tax_amt = float(item.get("itbis_amount", 0) or item.get("itbisAmount", 0) or 0)
        if tax_amt == 0 and rate > 0:
            tax_amt = base * rate

        # Determine ITBIS bucket
        if rate >= 0.17:
            label = "ITBIS (18%)"
        elif rate >= 0.15:
            label = "ITBIS (16%)"
        elif rate == 0.0 and tax_amt == 0:
            label = "Exento (0%)"
        else:
            label = "ITBIS (0%)"

        breakdown[label]["base"] += base
        breakdown[label]["tax"] += tax_amt

        # Propina (código 001)
        cod_imp = str(item.get("codigoImpuesto") or "").strip().zfill(3)
        otros_imp = float(item.get("otros_impuestos_amount") or 0)
        if cod_imp == "001" and otros_imp:
            breakdown["Propina (10%)"]["base"] += base
            breakdown["Propina (10%)"]["tax"] += otros_imp
        elif cod_imp == "002" and otros_imp:
            breakdown["CDT (2%)"]["base"] += base
            breakdown["CDT (2%)"]["tax"] += otros_imp

    # Round
    for lbl in breakdown:
        breakdown[lbl]["base"] = round(breakdown[lbl]["base"], 2)
        breakdown[lbl]["tax"] = round(breakdown[lbl]["tax"], 2)
    return breakdown


def _expense_tax_breakdown(exp):
    """Return per-label tax breakdown for a purchase expense (no itemized lines)."""
    breakdown = _empty_tax_breakdown()
    amount = float(exp.get("amount", 0) or 0)
    itbis_amt = float(exp.get("itbisAmount", 0) or exp.get("itbis", 0) or 0)
    base = amount - itbis_amt

    if itbis_amt > 0 and base > 0:
        estimated_rate = itbis_amt / base
        label = _classify_rate(estimated_rate)
    elif itbis_amt == 0:
        label = "Exento (0%)"
    else:
        label = "ITBIS (18%)"

    breakdown[label]["base"] = round(base, 2)
    breakdown[label]["tax"] = round(itbis_amt, 2)
    return breakdown


def _merge_breakdown(target, source):
    for lbl in TAX_LABELS:
        target[lbl]["base"] = round(target[lbl]["base"] + source[lbl]["base"], 2)
        target[lbl]["tax"] = round(target[lbl]["tax"] + source[lbl]["tax"], 2)


def _period_matches(date_str, year, month):
    prefix = (date_str or "")[:7]
    if month == 0:
        return prefix.startswith(f"{year:04d}")
    return prefix == f"{year:04d}-{month:02d}"


@web_reports_sales_bp.route('/reports/fiscal/detailed-taxes')
def detailed_taxes_report():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html',
                               feature_name="Reporte detallado de impuestos",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    # ── Filters ──────────────────────────────────────────────────────────────
    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', now.month))
    except ValueError:
        month = now.month

    tax_filter = request.args.get('tax', '')          # e.g. "ITBIS (18%)"
    active_tab = request.args.get('tab', 'sales')     # sales | sales_returns | purchases | purchase_returns

    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get('per_page', 10))
        if per_page < 1:
            per_page = 10
    except ValueError:
        per_page = 10

    # ── Load data ─────────────────────────────────────────────────────────────
    all_invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox) or []
    all_expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox) or []

    from app.services.purchase_credit_note_service import PurchaseCreditNoteService
    all_purchase_cn = PurchaseCreditNoteService.get_all(owner_uid, sandbox=sandbox) or []

    # ── Classify invoices ─────────────────────────────────────────────────────
    CREDIT_TYPES = {"Nota de Crédito (E34)", "Nota de Crédito"}
    SKIP_STATUSES = {"Anulada", "Borrador", "Consolidada"}

    sales_invoices = []
    sales_credit_notes = []

    for inv in all_invoices:
        if inv.get('status') in SKIP_STATUSES or inv.get('isQuotation'):
            continue
        date_raw = inv.get('date') or inv.get('createdAt') or ''
        if not _period_matches(date_raw, year, month):
            continue
        ecf = inv.get('ecfType', '')
        if ecf in CREDIT_TYPES or 'Crédito' in ecf:
            sales_credit_notes.append(inv)
        else:
            sales_invoices.append(inv)

    # Filter expenses in period
    period_expenses = []
    for exp in all_expenses:
        d = exp.get('date') or exp.get('createdAt') or ''
        if _period_matches(d, year, month):
            period_expenses.append(exp)

    # Filter purchase credit notes in period
    period_purchase_cn = []
    for cn in all_purchase_cn:
        d = cn.get('date') or cn.get('createdAt') or ''
        if _period_matches(d, year, month):
            period_purchase_cn.append(cn)

    # ── Tax breakdown aggregates ───────────────────────────────────────────────
    sales_breakdown = _empty_tax_breakdown()
    for inv in sales_invoices:
        _merge_breakdown(sales_breakdown, _invoice_tax_breakdown(inv))

    sales_returns_breakdown = _empty_tax_breakdown()
    for inv in sales_credit_notes:
        _merge_breakdown(sales_returns_breakdown, _invoice_tax_breakdown(inv))

    purchases_breakdown = _empty_tax_breakdown()
    for exp in period_expenses:
        _merge_breakdown(purchases_breakdown, _expense_tax_breakdown(exp))

    purchase_returns_breakdown = _empty_tax_breakdown()
    for cn in period_purchase_cn:
        amt = float(cn.get('amount', 0) or 0)
        itbis = float(cn.get('itbisAmount', 0) or 0)
        base = amt - itbis
        if itbis > 0 and base > 0:
            lbl = _classify_rate(itbis / base)
        else:
            lbl = "Exento (0%)"
        purchase_returns_breakdown[lbl]["base"] = round(
            purchase_returns_breakdown[lbl]["base"] + base, 2)
        purchase_returns_breakdown[lbl]["tax"] = round(
            purchase_returns_breakdown[lbl]["tax"] + itbis, 2)

    # ── KPI totals ─────────────────────────────────────────────────────────────
    total_tax_sales = round(sum(v["tax"] for v in sales_breakdown.values()), 2)
    total_tax_purchases = round(sum(v["tax"] for v in purchases_breakdown.values()), 2)
    total_tax_sales_returns = round(sum(v["tax"] for v in sales_returns_breakdown.values()), 2)
    total_tax_purchase_returns = round(sum(v["tax"] for v in purchase_returns_breakdown.values()), 2)
    diferencia = round(total_tax_sales - total_tax_purchases - total_tax_sales_returns + total_tax_purchase_returns, 2)

    # ── Transaction detail list ────────────────────────────────────────────────
    def _make_sales_rows(inv_list):
        rows = []
        for inv in inv_list:
            bd = _invoice_tax_breakdown(inv)
            for lbl in TAX_LABELS:
                if bd[lbl]["tax"] == 0 and bd[lbl]["base"] == 0:
                    continue
                if tax_filter and lbl != tax_filter:
                    continue
                rows.append({
                    "ncf": inv.get('encf') or inv.get('ncf') or inv.get('invoiceNumber') or '—',
                    "doc_type": inv.get('ecfType') or 'Factura',
                    "entity": inv.get('clientName') or inv.get('client') or '—',
                    "date": (inv.get('date') or inv.get('createdAt') or '')[:10],
                    "tax_label": lbl,
                    "base": bd[lbl]["base"],
                    "tax": bd[lbl]["tax"],
                })
        return sorted(rows, key=lambda r: r["date"], reverse=True)

    def _make_expense_rows(exp_list):
        rows = []
        for exp in exp_list:
            bd = _expense_tax_breakdown(exp)
            for lbl in TAX_LABELS:
                if bd[lbl]["tax"] == 0 and bd[lbl]["base"] == 0:
                    continue
                if tax_filter and lbl != tax_filter:
                    continue
                rows.append({
                    "ncf": exp.get('ncf') or exp.get('supplierInvoiceNumber') or exp.get('invoiceNumber') or '—',
                    "doc_type": exp.get('ecfType') or 'Gasto',
                    "entity": exp.get('supplierName') or exp.get('supplier') or '—',
                    "date": (exp.get('date') or exp.get('createdAt') or '')[:10],
                    "tax_label": lbl,
                    "base": bd[lbl]["base"],
                    "tax": bd[lbl]["tax"],
                })
        return sorted(rows, key=lambda r: r["date"], reverse=True)

    def _make_purchase_cn_rows(cn_list):
        rows = []
        for cn in cn_list:
            amt = float(cn.get('amount', 0) or 0)
            itbis = float(cn.get('itbisAmount', 0) or 0)
            base = amt - itbis
            if itbis > 0 and base > 0:
                lbl = _classify_rate(itbis / base)
            else:
                lbl = "Exento (0%)"
            if tax_filter and lbl != tax_filter:
                continue
            rows.append({
                "ncf": cn.get('creditNoteNumber') or '—',
                "doc_type": 'Nota de Crédito Compra',
                "entity": cn.get('creditedSupplierName') or '—',
                "date": (cn.get('date') or cn.get('createdAt') or '')[:10],
                "tax_label": lbl,
                "base": round(base, 2),
                "tax": round(itbis, 2),
            })
        return sorted(rows, key=lambda r: r["date"], reverse=True)

    if active_tab == 'sales':
        detail_rows = _make_sales_rows(sales_invoices)
    elif active_tab == 'sales_returns':
        detail_rows = _make_sales_rows(sales_credit_notes)
    elif active_tab == 'purchases':
        detail_rows = _make_expense_rows(period_expenses)
    else:  # purchase_returns
        detail_rows = _make_purchase_cn_rows(period_purchase_cn)

    total_detail = len(detail_rows)
    total_pages = max(1, (total_detail + per_page - 1) // per_page)
    page = min(page, total_pages)
    paginated_rows = detail_rows[(page - 1) * per_page: page * per_page]

    years_range = list(range(now.year - 5, now.year + 1))

    return render_template(
        'reports/detailed_taxes.html',
        active_page='reports',
        year=year,
        month=month,
        years_range=years_range,
        months_list=MONTH_FILTER_OPTIONS,
        tax_filter=tax_filter,
        tax_labels=TAX_LABELS,
        active_tab=active_tab,
        # KPIs
        total_tax_sales=total_tax_sales,
        total_tax_purchases=total_tax_purchases,
        total_tax_sales_returns=total_tax_sales_returns,
        total_tax_purchase_returns=total_tax_purchase_returns,
        diferencia=diferencia,
        # Breakdowns
        sales_breakdown=sales_breakdown,
        sales_returns_breakdown=sales_returns_breakdown,
        purchases_breakdown=purchases_breakdown,
        purchase_returns_breakdown=purchase_returns_breakdown,
        # Detail table
        detail_rows=paginated_rows,
        total_detail=total_detail,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )

# ─────────────────────────────────────────────────────────────────────────────
# REPORTE IMPUESTOS Y RETENCIONES
# ─────────────────────────────────────────────────────────────────────────────

def _tr_sales_rows(invoices, tax_filter, year, month):
    """Build transaction rows for sales invoices tax view."""
    rows = []
    CREDIT_TYPES = {"Nota de Crédito (E34)", "Nota de Crédito"}
    SKIP_STATUSES = {"Anulada", "Borrador", "Consolidada"}
    for inv in invoices:
        if inv.get('status') in SKIP_STATUSES or inv.get('isQuotation'):
            continue
        ecf = inv.get('ecfType', '')
        if ecf in CREDIT_TYPES or 'Crédito' in ecf:
            continue
        date_raw = inv.get('date') or inv.get('createdAt') or ''
        if not _period_matches(date_raw, year, month):
            continue
        for item in inv.get('items', []):
            rate = float(item.get('itbisRate', 0) or 0)
            base = float(item.get('subtotal', 0) or 0)
            tax_amt = float(item.get('itbis_amount', 0) or item.get('itbisAmount', 0) or 0)
            if tax_amt == 0 and rate > 0:
                tax_amt = round(base * rate, 2)
            if rate >= 0.17:
                lbl = "ITBIS (18%)"
            elif rate >= 0.15:
                lbl = "ITBIS (16%)"
            elif rate == 0.0 and tax_amt == 0:
                lbl = "Exento (0%)"
            else:
                lbl = "ITBIS (0%)"
            if tax_filter and lbl != tax_filter:
                continue
            if tax_amt == 0 and base == 0:
                continue
            rows.append({
                'ncf': inv.get('encf') or inv.get('ncf') or inv.get('invoiceNumber') or '—',
                'doc_type': ecf or 'Factura',
                'entity': inv.get('clientName') or '—',
                'date': date_raw[:10],
                'tax_label': lbl,
                'base': round(base, 2),
                'tax': round(tax_amt, 2),
            })
    return sorted(rows, key=lambda r: r['date'], reverse=True)


def _tr_sales_credit_note_rows(invoices, tax_filter, year, month):
    """Build transaction rows for sales credit notes."""
    rows = []
    CREDIT_TYPES = {"Nota de Crédito (E34)", "Nota de Crédito"}
    SKIP_STATUSES = {"Anulada", "Borrador"}
    for inv in invoices:
        if inv.get('status') in SKIP_STATUSES or inv.get('isQuotation'):
            continue
        ecf = inv.get('ecfType', '')
        if ecf not in CREDIT_TYPES and 'Crédito' not in ecf:
            continue
        date_raw = inv.get('date') or inv.get('createdAt') or ''
        if not _period_matches(date_raw, year, month):
            continue
        for item in inv.get('items', []):
            rate = float(item.get('itbisRate', 0) or 0)
            base = float(item.get('subtotal', 0) or 0)
            tax_amt = float(item.get('itbis_amount', 0) or item.get('itbisAmount', 0) or 0)
            if tax_amt == 0 and rate > 0:
                tax_amt = round(base * rate, 2)
            if rate >= 0.17:
                lbl = "ITBIS (18%)"
            elif rate >= 0.15:
                lbl = "ITBIS (16%)"
            elif rate == 0.0 and tax_amt == 0:
                lbl = "Exento (0%)"
            else:
                lbl = "ITBIS (0%)"
            if tax_filter and lbl != tax_filter:
                continue
            if tax_amt == 0 and base == 0:
                continue
            rows.append({
                'ncf': inv.get('encf') or inv.get('ncf') or inv.get('invoiceNumber') or '—',
                'doc_type': ecf or 'Nota de Crédito',
                'entity': inv.get('clientName') or '—',
                'date': date_raw[:10],
                'tax_label': lbl,
                'base': round(base, 2),
                'tax': round(tax_amt, 2),
            })
    return sorted(rows, key=lambda r: r['date'], reverse=True)


def _tr_expenses_rows(expenses, tax_filter, year, month):
    """Build transaction rows for purchase expenses taxes."""
    rows = []
    for exp in expenses:
        date_raw = exp.get('date') or exp.get('createdAt') or ''
        if not _period_matches(date_raw, year, month):
            continue
        amount = float(exp.get('amount', 0) or 0)
        itbis_amt = float(exp.get('itbisAmount', 0) or exp.get('itbis', 0) or 0)
        base = amount - itbis_amt
        if itbis_amt > 0 and base > 0:
            lbl = _classify_rate(itbis_amt / base)
        else:
            lbl = "Exento (0%)"
        if tax_filter and lbl != tax_filter:
            continue
        if itbis_amt == 0 and base == 0:
            continue
        rows.append({
            'ncf': exp.get('ncf') or exp.get('supplierInvoiceNumber') or exp.get('invoiceNumber') or '—',
            'doc_type': exp.get('ecfType') or 'Gasto',
            'entity': exp.get('supplierName') or '—',
            'date': date_raw[:10],
            'tax_label': lbl,
            'base': round(base, 2),
            'tax': round(itbis_amt, 2),
        })
    return sorted(rows, key=lambda r: r['date'], reverse=True)


def _tr_purchase_cn_rows(purchase_cn_list, year, month):
    """Build transaction rows for purchase credit notes."""
    rows = []
    for cn in purchase_cn_list:
        date_raw = cn.get('date') or cn.get('createdAt') or ''
        if not _period_matches(date_raw, year, month):
            continue
        amt = float(cn.get('amount', 0) or 0)
        itbis = float(cn.get('itbisAmount', 0) or 0)
        base = amt - itbis
        if itbis > 0 and base > 0:
            lbl = _classify_rate(itbis / base)
        else:
            lbl = "Exento (0%)"
        if amt == 0:
            continue
        rows.append({
            'ncf': cn.get('creditNoteNumber') or '—',
            'doc_type': 'Nota de Crédito Compra',
            'entity': cn.get('creditedSupplierName') or '—',
            'date': date_raw[:10],
            'tax_label': lbl,
            'base': round(base, 2),
            'tax': round(itbis, 2),
        })
    return sorted(rows, key=lambda r: r['date'], reverse=True)


def _tr_sales_retention_rows(invoices, year, month):
    """Build rows for retentions applied on sales invoices (retainedITBIS + retainedISR)."""
    rows = []
    CREDIT_TYPES = {"Nota de Crédito (E34)", "Nota de Crédito"}
    SKIP_STATUSES = {"Anulada", "Borrador", "Consolidada"}
    for inv in invoices:
        if inv.get('status') in SKIP_STATUSES or inv.get('isQuotation'):
            continue
        ecf = inv.get('ecfType', '')
        if ecf in CREDIT_TYPES or 'Crédito' in ecf:
            continue
        date_raw = inv.get('date') or inv.get('createdAt') or ''
        if not _period_matches(date_raw, year, month):
            continue
        ret_itbis = float(inv.get('retainedITBIS', 0) or 0)
        ret_isr = float(inv.get('retainedISR', 0) or 0)
        if ret_itbis == 0 and ret_isr == 0:
            continue
        rows.append({
            'ncf': inv.get('encf') or inv.get('ncf') or inv.get('invoiceNumber') or '—',
            'doc_type': ecf or 'Factura',
            'entity': inv.get('clientName') or '—',
            'date': date_raw[:10],
            'retained_itbis': ret_itbis,
            'retained_isr': ret_isr,
            'total': round(ret_itbis + ret_isr, 2),
        })
    return sorted(rows, key=lambda r: r['date'], reverse=True)


def _tr_purchase_retention_rows(expenses, year, month):
    """Build rows for retentions on purchases (retainedITBIS + retainedISR on expenses)."""
    rows = []
    for exp in expenses:
        date_raw = exp.get('date') or exp.get('createdAt') or ''
        if not _period_matches(date_raw, year, month):
            continue
        ret_itbis = float(exp.get('retainedITBIS', 0) or 0)
        ret_isr = float(exp.get('retainedISR', 0) or 0)
        if ret_itbis == 0 and ret_isr == 0:
            continue
        rows.append({
            'ncf': exp.get('ncf') or exp.get('supplierInvoiceNumber') or '—',
            'doc_type': exp.get('ecfType') or 'Gasto',
            'entity': exp.get('supplierName') or '—',
            'date': date_raw[:10],
            'retained_itbis': ret_itbis,
            'retained_isr': ret_isr,
            'total': round(ret_itbis + ret_isr, 2),
        })
    return sorted(rows, key=lambda r: r['date'], reverse=True)


@web_reports_sales_bp.route('/reports/fiscal/taxes-retentions')
def taxes_retentions_report():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html',
                               feature_name="Impuestos y retenciones",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    # ── Filters ──────────────────────────────────────────────────────────────
    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', now.month))
    except ValueError:
        month = now.month

    tax_filter = request.args.get('tax', '')
    active_tab = request.args.get('tab', 'sales')

    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get('per_page', 10))
        if per_page < 1:
            per_page = 10
    except ValueError:
        per_page = 10

    # ── Load data ─────────────────────────────────────────────────────────────
    all_invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox) or []
    all_expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox) or []

    from app.services.purchase_credit_note_service import PurchaseCreditNoteService
    all_purchase_cn = PurchaseCreditNoteService.get_all(owner_uid, sandbox=sandbox) or []

    # ── Build rows for each tab ───────────────────────────────────────────────
    if active_tab == 'sales':
        detail_rows = _tr_sales_rows(all_invoices, tax_filter, year, month)
        is_retention_tab = False
    elif active_tab == 'sales_returns':
        detail_rows = _tr_sales_credit_note_rows(all_invoices, tax_filter, year, month)
        is_retention_tab = False
    elif active_tab == 'purchases':
        detail_rows = _tr_expenses_rows(all_expenses, tax_filter, year, month)
        is_retention_tab = False
    elif active_tab == 'purchase_returns':
        detail_rows = _tr_purchase_cn_rows(all_purchase_cn, year, month)
        is_retention_tab = False
    elif active_tab == 'purchase_retentions':
        detail_rows = _tr_purchase_retention_rows(all_expenses, year, month)
        is_retention_tab = True
    else:  # sales_retentions
        active_tab = 'sales_retentions'
        detail_rows = _tr_sales_retention_rows(all_invoices, year, month)
        is_retention_tab = True

    # ── Summary KPIs for header ───────────────────────────────────────────────
    sales_rows_all = _tr_sales_rows(all_invoices, '', year, month)
    purchases_rows_all = _tr_expenses_rows(all_expenses, '', year, month)
    sales_returns_all = _tr_sales_credit_note_rows(all_invoices, '', year, month)
    purchase_returns_all = _tr_purchase_cn_rows(all_purchase_cn, year, month)
    sales_ret_all = _tr_sales_retention_rows(all_invoices, year, month)
    purchase_ret_all = _tr_purchase_retention_rows(all_expenses, year, month)

    total_sales_tax = round(sum(r['tax'] for r in sales_rows_all), 2)
    total_purchases_tax = round(sum(r['tax'] for r in purchases_rows_all), 2)
    total_sales_returns_tax = round(sum(r['tax'] for r in sales_returns_all), 2)
    total_purchase_returns_tax = round(sum(r['tax'] for r in purchase_returns_all), 2)
    total_sales_retentions = round(sum(r['total'] for r in sales_ret_all), 2)
    total_purchase_retentions = round(sum(r['total'] for r in purchase_ret_all), 2)

    # ── Pagination ────────────────────────────────────────────────────────────
    total_detail = len(detail_rows)
    total_pages = max(1, (total_detail + per_page - 1) // per_page)
    page = min(page, total_pages)
    paginated_rows = detail_rows[(page - 1) * per_page: page * per_page]

    years_range = list(range(now.year - 5, now.year + 1))

    return render_template(
        'reports/taxes_retentions.html',
        active_page='reports',
        year=year,
        month=month,
        years_range=years_range,
        months_list=MONTH_FILTER_OPTIONS,
        tax_filter=tax_filter,
        tax_labels=TAX_LABELS,
        active_tab=active_tab,
        is_retention_tab=is_retention_tab,
        # KPI totals
        total_sales_tax=total_sales_tax,
        total_purchases_tax=total_purchases_tax,
        total_sales_returns_tax=total_sales_returns_tax,
        total_purchase_returns_tax=total_purchase_returns_tax,
        total_sales_retentions=total_sales_retentions,
        total_purchase_retentions=total_purchase_retentions,
        # Detail table
        detail_rows=paginated_rows,
        total_detail=total_detail,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@web_reports_sales_bp.route('/reports/fiscal/taxes-retentions/export')
def taxes_retentions_export():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html',
                               feature_name="Impuestos y retenciones",
                               required_permission="canInvoice")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    now = datetime.now(timezone.utc)

    try:
        year = int(request.args.get('year', now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get('month', now.month))
    except ValueError:
        month = now.month

    tax_filter = request.args.get('tax', '')
    active_tab = request.args.get('tab', 'sales')

    all_invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox) or []
    all_expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox) or []
    from app.services.purchase_credit_note_service import PurchaseCreditNoteService
    all_purchase_cn = PurchaseCreditNoteService.get_all(owner_uid, sandbox=sandbox) or []

    if active_tab == 'sales':
        rows = _tr_sales_rows(all_invoices, tax_filter, year, month)
        is_retention = False
    elif active_tab == 'sales_returns':
        rows = _tr_sales_credit_note_rows(all_invoices, tax_filter, year, month)
        is_retention = False
    elif active_tab == 'purchases':
        rows = _tr_expenses_rows(all_expenses, tax_filter, year, month)
        is_retention = False
    elif active_tab == 'purchase_returns':
        rows = _tr_purchase_cn_rows(all_purchase_cn, year, month)
        is_retention = False
    elif active_tab == 'purchase_retentions':
        rows = _tr_purchase_retention_rows(all_expenses, year, month)
        is_retention = True
    else:
        rows = _tr_sales_retention_rows(all_invoices, year, month)
        is_retention = True

    output = io.StringIO()
    writer = csv.writer(output)
    if is_retention:
        writer.writerow(['NCF/Número', 'Tipo de documento', 'Proveedor/Cliente', 'Fecha',
                         'Ret. ITBIS', 'Ret. ISR', 'Total retenciones'])
        for r in rows:
            writer.writerow([r['ncf'], r['doc_type'], r['entity'], r['date'],
                             r['retained_itbis'], r['retained_isr'], r['total']])
    else:
        writer.writerow(['NCF/Número', 'Tipo de documento', 'Proveedor/Cliente', 'Fecha',
                         'Impuesto', 'Base imponible', 'Valor impuesto'])
        for r in rows:
            writer.writerow([r['ncf'], r['doc_type'], r['entity'], r['date'],
                             r['tax_label'], r['base'], r['tax']])

    output.seek(0)
    tab_name = active_tab.replace('_', '-')
    filename = f"impuestos-retenciones-{tab_name}-{year}-{month:02d}.csv"
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename,
    )
