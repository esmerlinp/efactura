# app/web/dashboard.py
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, session, request
from app.services.db_service import DatabaseService
from app.services.recurrence import RecurrenceService

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
    date_str = request.args.get('date', datetime.utcnow().strftime("%Y-%m-%d"))
    kpi_period = request.args.get('kpi_period', 'month')
    
    try:
        selected_date = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        selected_date = datetime.utcnow()
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
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
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
    current_year_str = str(datetime.utcnow().year)
    rst_income_year = sum(inv['total'] for inv in real_invoices if inv['date'].startswith(current_year_str))
    rst_limit_2026 = 12068181.09

    # Contingencia: detectar facturas emitidas offline sin sincronizar con la DGII
    now_utc = datetime.utcnow()
    contingency_invoices = []
    for inv in real_invoices:
        if inv.get('emisionMode') == 'FALLBACK' and not inv.get('isSyncedWithDGII', True):
            emitted_at_str = inv.get('contingencyEmittedAt') or inv.get('date', now_utc.isoformat())
            try:
                emitted_at = datetime.fromisoformat(emitted_at_str.replace('Z', '+00:00')).replace(tzinfo=None)
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
        plan_pct=plan_pct,
        onboarding_state=onboarding_state
    )
