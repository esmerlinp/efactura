# app/web/dashboard.py
from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, redirect, url_for, session, request
from app.services.db_service import DatabaseService
from app.services.recurrence import RecurrenceService
from app.services.cache_service import CacheService
from app.services.dgii import DGIIService

web_dashboard_bp = Blueprint('web_dashboard', __name__)

@web_dashboard_bp.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
        
    from app.utils.decorators import check_permission
    if not check_permission('canViewDashboard'):
        if check_permission('canManagePOS'):
            return redirect(url_for('web_pos.pos_dashboard'))
        elif check_permission('canInvoice'):
            return redirect(url_for('web_invoices.list_invoices'))
        elif check_permission('canClients'):
            return redirect(url_for('web_clients.list_clients'))
        elif check_permission('canManageInventory'):
            return redirect(url_for('web_invoices.inventory_dashboard'))
        elif check_permission('canExpenses'):
            return redirect(url_for('web_invoices.list_expenses'))
        else:
            return render_template('auth/restricted.html', feature_name="Dashboard General", required_permission="canViewDashboard")
            
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    # Procesar automáticamente recurrencias programadas al abrir dashboard
    RecurrenceService.process_pending_recurrences(owner_uid, sandbox=sandbox)
    
    # Procesar automáticamente recordatorios de cobro de CxC programados al abrir dashboard
    try:
        from app.services.notifications import NotificationService
        NotificationService.process_automatic_reminders(owner_uid, sandbox=sandbox)
    except Exception as e:
        print(f"⚠️ Error al procesar recordatorios automáticos en el Dashboard: {e}")
    
    # Obtener filtros de escala, fecha y KPI
    scale = request.args.get('scale', 'month')
    date_str = request.args.get('date', datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    kpi_period = request.args.get('kpi_period', 'month')
    
    try:
        selected_date = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        selected_date = datetime.now(timezone.utc)
        date_str = selected_date.strftime("%Y-%m-%d")
        
    selected_month = selected_date.month
    selected_year = selected_date.year
    
    # Calcular mes anterior
    if selected_month == 1:
        prev_month = 12
        prev_month_year = selected_year - 1
    else:
        prev_month = selected_month - 1
        prev_month_year = selected_year
        
    # Obtener facturas y gastos
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    sequences = DatabaseService.get_sequences(owner_uid, sandbox=sandbox)
    profile = DatabaseService.get_company_profile(owner_uid)
    
    # Filtrar cotizaciones y borradores
    real_invoices = [inv for inv in invoices if not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador']]
    
    # Helper para parsear fechas
    def parse_doc_date(doc_date_str):
        try:
            if 'T' in doc_date_str:
                return datetime.strptime(doc_date_str[:19], "%Y-%m-%dT%H:%M:%S")
            return datetime.strptime(doc_date_str[:10], "%Y-%m-%d")
        except Exception:
            return None
            
    # Filtrar facturas y gastos para los KPIs según kpi_period
    kpi_invoices = []
    kpi_expenses = []
    
    for inv in real_invoices:
        dt = parse_doc_date(inv.get('date'))
        if not dt:
            continue
        if kpi_period == 'month':
            if dt.month == selected_month and dt.year == selected_year:
                kpi_invoices.append(inv)
        elif kpi_period == 'prev_month':
            if dt.month == prev_month and dt.year == prev_month_year:
                kpi_invoices.append(inv)
        elif kpi_period == 'year':
            if dt.year == selected_year:
                kpi_invoices.append(inv)
        else: # 'all'
            kpi_invoices.append(inv)
            
    for exp in expenses:
        dt = parse_doc_date(exp.get('date'))
        if not dt:
            continue
        if kpi_period == 'month':
            if dt.month == selected_month and dt.year == selected_year:
                kpi_expenses.append(exp)
        elif kpi_period == 'prev_month':
            if dt.month == prev_month and dt.year == prev_month_year:
                kpi_expenses.append(exp)
        elif kpi_period == 'year':
            if dt.year == selected_year:
                kpi_expenses.append(exp)
        else: # 'all'
            kpi_expenses.append(exp)
            
    # Calcular KPIs basados en datos filtrados
    total_invoiced = sum(inv['total'] for inv in kpi_invoices)
    total_expenses = sum(exp['amount'] for exp in kpi_expenses)
    total_itbis = sum(inv.get('totalITBIS', 0.0) for inv in kpi_invoices)
    
    # Cuentas por Cobrar (CxC): Siempre acumulado de toda la vida para evitar deslices en cobranzas
    total_cxc = sum(inv['netPayable'] for inv in real_invoices if inv['status'] in ['Emitida', 'Vencida'])
    
    # CxC breakdown
    cxc_vigentes = sum(inv['netPayable'] for inv in real_invoices if inv['status'] == 'Emitida')
    cxc_vencidas = sum(inv['netPayable'] for inv in real_invoices if inv['status'] == 'Vencida')
    cxc_docs_vigentes = sum(1 for inv in real_invoices if inv['status'] == 'Emitida')
    cxc_docs_vencidas = sum(1 for inv in real_invoices if inv['status'] == 'Vencida')
    
    # Pagos Recibidos (total de netPayable que ya han sido pagados)
    pagos_recibidos = sum(inv.get('netPayable', 0.0) - inv.get('remainingBalance', 0.0) 
                         for inv in real_invoices if inv['status'] == 'Pagado')
    pagos_parciales = sum(inv.get('netPayable', 0.0) - inv.get('remainingBalance', 0.0)
                         for inv in real_invoices if inv['status'] == 'Parcialmente Cobrada')
    
    # Cuentas por Pagar (CxP): Gastos de crédito no pagados
    cxp_expenses = [exp for exp in expenses if exp.get('paymentType') == 'Crédito' and exp.get('cxpStatus') != 'Pagado']
    total_cxp = sum(exp.get('cxpRemainingBalance', 0.0) for exp in cxp_expenses)
    cxp_vigentes = sum(exp.get('cxpRemainingBalance', 0.0) for exp in cxp_expenses if exp.get('cxpStatus') != 'Vencido')
    cxp_vencidas = sum(exp.get('cxpRemainingBalance', 0.0) for exp in cxp_expenses if exp.get('cxpStatus') == 'Vencido')
    cxp_docs_vigentes = sum(1 for exp in cxp_expenses if exp.get('cxpStatus') != 'Vencido')
    cxp_docs_vencidas = sum(1 for exp in cxp_expenses if exp.get('cxpStatus') == 'Vencido')
    
    # Productos vendidos (items distintos en facturas)
    productos_vendidos_set = set()
    for inv in real_invoices:
        for it in inv.get('items', []):
            nombre = it.get('name', '')
            if nombre:
                productos_vendidos_set.add(nombre.lower().strip())
    productos_vendidos_count = len(productos_vendidos_set)
    
    # Clientes con ventas
    clientes_con_ventas = len(set(inv.get('clientId', '') for inv in real_invoices if inv.get('clientId')))
    
    # Impuestos en venta (ITBIS de todas las facturas reales)
    impuestos_venta = total_itbis
    
    # Ingresos netos y egresos netos para estado de resultados simplificado
    ingresos_netos = sum(inv.get('subtotal', 0.0) for inv in real_invoices)
    egresos_netos = sum(exp.get('amount', 0.0) - exp.get('itbisAmount', 0.0) for exp in expenses)
    
    margin_net = 0.0
    if total_invoiced > 0:
        margin_net = ((total_invoiced - total_expenses) / total_invoiced) * 100
        
    stats = {
        "total_invoiced": total_invoiced,
        "total_expenses": total_expenses,
        "total_cxc": total_cxc,
        "total_itbis": total_itbis,
        "margin_net": margin_net
    }
    
    # 1. Gráfico de Flujo de Caja (Ventas vs Egresos) con Filtro Temporal Completo (Igual a iOS)
    labels = []
    buckets = {}
    current_year = selected_date.year
    
    if scale == 'hour':
        for h in range(0, 24, 2):
            label = f"{h:02d}:00"
            buckets[label] = {"invoiced": 0.0, "expenses": 0.0, "order": h}
            labels.append(label)
    elif scale == 'day':
        days = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        for idx, day in enumerate(days):
            buckets[day] = {"invoiced": 0.0, "expenses": 0.0, "order": idx}
            labels.append(day)
    elif scale == 'week':
        for w in range(1, 6):
            label = f"Sem. {w}"
            buckets[label] = {"invoiced": 0.0, "expenses": 0.0, "order": w}
            labels.append(label)
    elif scale == 'month':
        months = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        for idx, month in enumerate(months):
            buckets[month] = {"invoiced": 0.0, "expenses": 0.0, "order": idx}
            labels.append(month)
    elif scale == 'quarter':
        for q in range(1, 5):
            label = f"Trim. {q}"
            buckets[label] = {"invoiced": 0.0, "expenses": 0.0, "order": q}
            labels.append(label)
    elif scale == 'year':
        for y in range(current_year - 4, current_year + 1):
            label = str(y)
            buckets[label] = {"invoiced": 0.0, "expenses": 0.0, "order": y}
            labels.append(label)
            
    def is_in_period(doc_date):
        if not doc_date:
            return False
        if scale == 'hour':
            return doc_date.date() == selected_date.date()
        elif scale == 'day':
            return doc_date.isocalendar()[1] == selected_date.isocalendar()[1] and doc_date.year == selected_date.year
        elif scale == 'week':
            return doc_date.month == selected_date.month and doc_date.year == selected_date.year
        elif scale == 'month' or scale == 'quarter':
            return doc_date.year == selected_date.year
        elif scale == 'year':
            return (current_year - 4) <= doc_date.year <= current_year
        return False
        
    def get_bucket_label(doc_date):
        if scale == 'hour':
            h = (doc_date.hour // 2) * 2
            return f"{h:02d}:00"
        elif scale == 'day':
            days = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
            return days[doc_date.weekday()]
        elif scale == 'week':
            w = min(5, (doc_date.day - 1) // 7 + 1)
            return f"Sem. {w}"
        elif scale == 'month':
            months = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
            return months[doc_date.month - 1]
        elif scale == 'quarter':
            q = (doc_date.month - 1) // 3 + 1
            return f"Trim. {q}"
        elif scale == 'year':
            return str(doc_date.year)
        return None

    for inv in real_invoices:
        try:
            inv_date_str = inv['date']
            if 'T' in inv_date_str:
                inv_date = datetime.strptime(inv_date_str[:19], "%Y-%m-%dT%H:%M:%S")
            else:
                inv_date = datetime.strptime(inv_date_str[:10], "%Y-%m-%d")
            
            if is_in_period(inv_date):
                lbl = get_bucket_label(inv_date)
                if lbl in buckets:
                    buckets[lbl]["invoiced"] += inv['total']
        except Exception:
            pass

    for exp in expenses:
        try:
            exp_date_str = exp['date']
            if 'T' in exp_date_str:
                exp_date = datetime.strptime(exp_date_str[:19], "%Y-%m-%dT%H:%M:%S")
            else:
                exp_date = datetime.strptime(exp_date_str[:10], "%Y-%m-%d")
                
            if is_in_period(exp_date):
                lbl = get_bucket_label(exp_date)
                if lbl in buckets:
                    buckets[lbl]["expenses"] += exp['amount']
        except Exception:
            pass
            
    sorted_labels = sorted(labels, key=lambda l: buckets[l]["order"])
    invoiced_data = [buckets[lbl]["invoiced"] for lbl in sorted_labels]
    expenses_data = [buckets[lbl]["expenses"] for lbl in sorted_labels]
    
    chart_data = {
        "labels": sorted_labels,
        "invoiced": invoiced_data,
        "expenses": expenses_data
    }

    months_full = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    if scale == 'hour':
        chart_title = f"Desempeño por Hora ({selected_date.day} de {months_full[selected_date.month - 1]})"
    elif scale == 'day':
        chart_title = f"Desempeño Diario ({months_full[selected_date.month - 1]}, {selected_date.year})"
    elif scale == 'week':
        chart_title = f"Desempeño Semanal ({months_full[selected_date.month - 1]}, {selected_date.year})"
    elif scale == 'month':
        chart_title = f"Desempeño Mensual ({selected_date.year})"
    elif scale == 'quarter':
        chart_title = f"Desempeño por Trimestre ({selected_date.year})"
    elif scale == 'year':
        chart_title = "Desempeño Anual Histórico"
    else:
        chart_title = "Flujo de Caja"
    
    # 2. Distribución de Ventas por Tipo de e-CF
    type_counts = {"Crédito Fiscal (E31)": 0, "Consumo (E32)": 0, "Otros": 0}
    for inv in real_invoices:
        t = inv.get('ecfType', 'Factura de Consumo (E32)')
        if "E31" in t:
            type_counts["Crédito Fiscal (E31)"] += inv['total']
        elif "E32" in t:
            type_counts["Consumo (E32)"] += inv['total']
        else:
            type_counts["Otros"] += inv['total']
            
    type_chart_data = {
        "labels": list(type_counts.keys()),
        "values": list(type_counts.values())
    }
    
    # Agenda CRM del día
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
    
    for c in clients:
        c_id = c['id']
        c_sales = [inv for inv in real_invoices if inv['clientId'] == c_id]
        c['total_cxc'] = sum(inv['netPayable'] for inv in c_sales if inv['status'] in ['Emitida', 'Vencida'])

    crm_contacts = [
        c for c in clients 
        if (c.get('nextContactDate') and c['nextContactDate'][:10] == today_str) or c.get('total_cxc', 0.0) > 0.0
    ]

    # Calcular ingresos acumulados RST 2026
    current_year_str = str(datetime.now(timezone.utc).year)
    rst_income_year = sum(inv['total'] for inv in real_invoices if inv['date'].startswith(current_year_str))
    rst_limit_2026 = 12068181.09

    # Contingencia: detectar facturas emitidas offline sin sincronizar con la DGII
    now_utc = datetime.now(timezone.utc)
    contingency_invoices = []
    for inv in real_invoices:
        if inv.get('emisionMode') == 'FALLBACK' and not inv.get('isSyncedWithDGII', True):
            emitted_at_str = inv.get('contingencyEmittedAt') or inv.get('date', now_utc.isoformat())
            try:
                emitted_at = datetime.fromisoformat(emitted_at_str.replace('Z', '+00:00'))
                if emitted_at.tzinfo is None:
                    emitted_at = emitted_at.replace(tzinfo=timezone.utc)
            except Exception:
                emitted_at = now_utc
            hours_elapsed = (now_utc - emitted_at).total_seconds() / 3600
            hours_remaining = max(0.0, 72.0 - hours_elapsed)
            contingency_invoices.append({
                'id': inv['id'],
                'invoiceNumber': inv.get('invoiceNumber', ''),
                'encf': inv.get('encf', ''),
                'total': inv.get('total', 0.0),
                'hours_elapsed': round(hours_elapsed, 1),
                'hours_remaining': round(hours_remaining, 1),
                'is_critical': hours_remaining < 12
            })

    # 3. Consumo del Plan
    billing_day = profile.get('billingDay', 1)
    plan_stats = DatabaseService.get_invoice_stats(owner_uid, billing_day)
    
    docs_used = plan_stats['sandbox_current_cycle'] if sandbox else plan_stats['prod_current_cycle']
    docs_limit = int(profile.get('documentLimit', 100)) if profile.get('documentLimit') else 100
    plan_pct = min(100.0, (docs_used / docs_limit) * 100.0) if docs_limit > 0 else 0.0
    
    plan_name = "Plan Personalizado"
    from app.services.db_service import db_firestore
    try:
        plan_id = profile.get('planId')
        if plan_id:
            plan_doc = db_firestore.collection('plans').document(plan_id).get()
            if plan_doc.exists:
                plan_name = plan_doc.to_dict().get('name', 'Plan Activo')
    except Exception:
        pass

    months_full = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    current_month_name = months_full[selected_month - 1]

    # 4. Onboarding y Configuración Inicial
    items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
    has_company_configured = bool(profile.get('companyRNC')) and profile.get('companyRNC') != "132109122" # Default dummy RNC
    has_products = len(items) > 0
    has_clients = len(clients) > 0
    has_invoices = len(real_invoices) > 0
    
    onboarding_state = {
        "has_company_configured": has_company_configured,
        "has_products": has_products,
        "has_clients": has_clients,
        "has_invoices": has_invoices,
        "is_complete": has_company_configured and has_products and has_clients and has_invoices,
        "progress_pct": sum([has_company_configured, has_products, has_clients, has_invoices]) * 25
    }

    # 5. BI: Margen por Producto
    catalog_cost = {}
    for it in items:
        cost = float(it.get('costPrice', 0.0))
        name_key = it.get('name', '').lower().strip()
        code_key = it.get('code', '').lower().strip()
        if name_key:
            catalog_cost[name_key] = cost
        if code_key:
            catalog_cost[code_key] = cost

    product_stats = {}
    for inv in real_invoices:
        for it in inv.get('items', []):
            name = it.get('name', '')
            code = it.get('code', '')
            price = float(it.get('price', 0.0))
            qty = int(it.get('quantity', 1))
            subtotal = float(it.get('subtotal', price * qty))
            cost = catalog_cost.get(code.lower().strip()) or catalog_cost.get(name.lower().strip()) or 0.0
            total_cost = cost * qty
            key = name or code or "Producto Desconocido"
            if key not in product_stats:
                product_stats[key] = {"name": key, "qty": 0, "revenue": 0.0, "cost": 0.0}
            product_stats[key]["qty"] += qty
            product_stats[key]["revenue"] += subtotal
            product_stats[key]["cost"] += total_cost

    for key, ps in product_stats.items():
        rev = ps["revenue"]
        cst = ps["cost"]
        ps["profit"] = rev - cst
        ps["margin"] = ((rev - cst) / rev * 100) if rev > 0 else 0.0

    products_by_profit = sorted(product_stats.values(), key=lambda x: x["profit"], reverse=True)

    # 6. BI: Clientes más rentables
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
            cost = catalog_cost.get(code.lower().strip()) or catalog_cost.get(name.lower().strip()) or 0.0
            inv_cost += cost * qty
        if client_id not in client_stats:
            client_stats[client_id] = {"name": client_name, "revenue": 0.0, "cost": 0.0, "invoice_count": 0}
        client_stats[client_id]["revenue"] += subtotal
        client_stats[client_id]["cost"] += inv_cost
        client_stats[client_id]["invoice_count"] += 1

    for c_id, cs in client_stats.items():
        rev = cs["revenue"]
        cst = cs["cost"]
        cs["profit"] = rev - cst
        cs["margin"] = (rev - cst) / rev * 100 if rev > 0 else 0.0

    clients_by_profit = sorted(client_stats.values(), key=lambda x: x["profit"], reverse=True)

    # 7. BI: Flujo de Caja Proyectado (4 meses)
    now = datetime.now(timezone.utc)
    months_projection = []
    for i in range(4):
        future_date = now.replace(day=1) + timedelta(days=30 * i)
        m_label = future_date.strftime("%Y-%m")
        months_projection.append({
            "key": m_label,
            "label": future_date.strftime("%B %Y").capitalize(),
            "inflow": 0.0, "outflow": 0.0, "net": 0.0
        })

    for inv in real_invoices:
        if inv.get('status') in ['Emitida', 'Vencida', 'Parcialmente Cobrada']:
            due_str = inv.get('dueDate', '')[:7]
            for m in months_projection:
                if m["key"] == due_str:
                    m["inflow"] += float(inv.get('remainingBalance', 0.0))

    for exp in expenses:
        if exp.get('paymentType') == 'Crédito' and exp.get('cxpStatus') != 'Pagado':
            due_str = exp.get('dueDate', '')[:7]
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

    # 8. BI: Indicadores Tributarios
    total_itbis_sales = sum(float(inv.get('totalITBIS', 0.0)) for inv in real_invoices)
    total_itbis_expenses = sum(float(exp.get('itbisAmount', 0.0)) for exp in expenses if exp.get('isITBISDeductible', True))
    itbis_to_pay = total_itbis_sales - total_itbis_expenses

    total_sales_net = sum(inv.get('subtotal', 0.0) for inv in real_invoices)
    total_expenses_net = sum(exp.get('amount', 0.0) - exp.get('itbisAmount', 0.0) for exp in expenses)
    isr_base = max(0.0, total_sales_net - total_expenses_net)
    isr_estimated = isr_base * 0.27
    anticipos_estimated = isr_estimated / 12.0

    rst_taxable_base = total_sales_net * 0.60
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

    # 9. Smart Insights IA (Predictivo)
    insights = []

    client_monthly_sales = {}
    for inv in real_invoices:
        client_name = inv.get('clientName') or 'Consumidor Final'
        if client_name == 'Consumidor Final':
            continue
        cid = inv.get('clientId', '')
        if not cid:
            continue
        date_str = inv.get('date', '')[:7]
        if cid not in client_monthly_sales:
            client_monthly_sales[cid] = {"name": client_name, "months": {}}
        if date_str not in client_monthly_sales[cid]["months"]:
            client_monthly_sales[cid]["months"][date_str] = 0.0
        client_monthly_sales[cid]["months"][date_str] += float(inv.get('subtotal', 0.0))

    current_month_str = now.strftime("%Y-%m")
    for cid, cdata in client_monthly_sales.items():
        monthly_data = cdata["months"]
        c_name = cdata["name"]
        if len(monthly_data) >= 2:
            current_sales = monthly_data.get(current_month_str, 0.0)
            other_months = [v for k, v in monthly_data.items() if k != current_month_str]
            avg_historical = sum(other_months) / len(other_months)
            if avg_historical > 10000 and current_sales < (avg_historical * 0.60):
                drop_pct = int((1 - (current_sales / avg_historical)) * 100)
                insights.append({
                    "type": "warning",
                    "text": f"Atención: El cliente {c_name} ha reducido sus compras un {drop_pct}% este mes comparado con su promedio histórico.",
                    "client_id": cid,
                    "client_name": c_name
                })

    overdue_b2b_total = 0.0
    for inv in real_invoices:
        if inv.get('status') == 'Vencida' and len(inv.get('clientRNC', '').replace('-', '').strip()) >= 9:
            overdue_b2b_total += float(inv.get('remainingBalance', 0.0))

    if overdue_b2b_total > 50000:
        insights.append({
            "type": "danger",
            "text": f"Alerta: Tienes RD$ {overdue_b2b_total:,.2f} en facturas vencidas acumuladas de clientes B2B (con RNC)."
        })

    if liquidity_warning_month:
        insights.append({
            "type": "danger",
            "text": f"Alerta de liquidez: Proyección de flujo de caja neto acumulado negativo detectado para el mes de {liquidity_warning_month}."
        })

    low_margin_count = sum(1 for ps in product_stats.values() if ps["cost"] > 0 and ps["margin"] < 15.0)
    if low_margin_count > 0:
        insights.append({
            "type": "info",
            "text": f"Optimización: Detectamos {low_margin_count} productos/servicios con margen de beneficio inferior al 15%."
        })

    if not insights:
        insights.append({
            "type": "success",
            "text": "Salud financiera estable. No se detectan anomalías en las compras de clientes ni riesgos de liquidez inmediatos."
        })

    return render_template(
        'dashboard.html',
        active_page='dashboard',
        stats=stats,
        chart_data=chart_data,
        type_chart_data=type_chart_data,
        crm_contacts=crm_contacts,
        sequences=sequences[:4],
        scale=scale,
        date_str=date_str,
        chart_title=chart_title,
        profile=profile,
        rst_income_year=rst_income_year,
        rst_limit_2026=rst_limit_2026,
        contingency_invoices=contingency_invoices,
        kpi_period=kpi_period,
        current_month_name=current_month_name,
        selected_year=selected_year,
        plan_name=plan_name,
        docs_used=docs_used,
        docs_limit=docs_limit,
        onboarding_state=onboarding_state,
        plan_pct=plan_pct,
        insights=insights,
        products_by_profit=products_by_profit[:5],
        clients_by_profit=clients_by_profit[:5],
        months_projection=months_projection,
        total_sales_net=total_sales_net,
        total_expenses_net=total_expenses_net,
        total_itbis_sales=total_itbis_sales,
        total_itbis_expenses=total_itbis_expenses,
        itbis_to_pay=itbis_to_pay,
        isr_estimated=isr_estimated,
        anticipos_estimated=anticipos_estimated,
        rst_isr_estimated=rst_isr_estimated,
        cxc_vigentes=cxc_vigentes,
        cxc_vencidas=cxc_vencidas,
        cxc_docs_vigentes=cxc_docs_vigentes,
        cxc_docs_vencidas=cxc_docs_vencidas,
        pagos_recibidos=pagos_recibidos,
        pagos_parciales=pagos_parciales,
        total_cxp=total_cxp,
        cxp_vigentes=cxp_vigentes,
        cxp_vencidas=cxp_vencidas,
        cxp_docs_vigentes=cxp_docs_vigentes,
        cxp_docs_vencidas=cxp_docs_vencidas,
        productos_vendidos_count=productos_vendidos_count,
        clientes_con_ventas=clientes_con_ventas,
        impuestos_venta=impuestos_venta,
        ingresos_netos=ingresos_netos,
        egresos_netos=egresos_netos,
        _cache_key=f"dashboard_{owner_uid}_{kpi_period}_{scale}_{date_str}",
    )
