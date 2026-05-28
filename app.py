import os
import io
import csv
import json
import uuid
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file, make_response
import qrcode
try:
    from weasyprint import HTML as WeasyprintHTML
    WEASYPRINT_AVAILABLE = True
except Exception:
    WEASYPRINT_AVAILABLE = False
import random
from config import Config
from firebase_service import DatabaseService
from dgii_service import DGIIService
from currency_service import CurrencyService
from alanube_service import AlanubeService
from recurrence_service import RecurrenceService

# Inicializar Flask
app = Flask(__name__)
app.config.from_object(Config)

# Registrar funciones matemáticas útiles en Jinja2
app.jinja_env.globals.update(min=min, max=max)

# Inicializar Base de Datos SQLite local y tablas
DatabaseService.init_local_db()

# =========================================================================
# FILTROS JINJA2 PERSONALIZADOS
# =========================================================================
@app.template_filter('formatted')
def formatted_filter(value):
    try:
        return f"{float(value):,.2f}"
    except (ValueError, TypeError):
        return value

# =========================================================================
# LIFECYCLE HOOKS & SEGURIDAD DE PERMISOS
# =========================================================================
@app.before_request
def load_fresh_user_profile():
    # Saltar carga para llamadas de archivos estáticos
    if request.endpoint == 'static':
        return
    if 'user' in session:
        # Cargar perfil fresco en tiempo real de Firestore para sincronización reactiva
        fresh_profile = DatabaseService.get_user_profile(session['user']['uid'])
        if fresh_profile:
            session['user'] = fresh_profile

@app.context_processor
def inject_company_brand():
    """Inyecta el logo y color de marca de la empresa en todos los templates."""
    logo_url = ''
    gradient_enabled = True
    color_marca = ''
    apply_ui = True
    apply_reports = True
    if 'user' in session:
        owner_uid = session['user'].get('ownerUID')
        if owner_uid:
            company = DatabaseService.get_company_profile(owner_uid)
            logo_url = company.get('logoUrl', '')
            color_marca = company.get('colorMarca', '')
            gradient_enabled = company.get('gradientEnabled', True)
            apply_ui = company.get('applyColorMarcaUI', True)
            apply_reports = company.get('applyColorMarcaReports', True)
            print(f"DEBUG: owner_uid={owner_uid}, gradient_enabled={gradient_enabled}, type={type(gradient_enabled)}", flush=True)
    return dict(company_logo_url=logo_url, company_color_marca=color_marca, company_gradient_enabled=gradient_enabled, company_apply_color_marca_ui=apply_ui, company_apply_color_marca_reports=apply_reports)

def check_permission(permission_name):
    """Retorna True si el usuario tiene el rol de propietario o cuenta con el permiso granular solicitado."""
    if 'user' not in session:
        return False
    user = session['user']
    if user.get('role') == 'owner':
        return True
    return user.get('permissions', {}).get(permission_name, True)

# =========================================================================
# CONTROLADORES DE RUTA - AUTENTICACIÓN
# =========================================================================
@app.route('/')
def home():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user_profile = DatabaseService.authenticate_user(email, password)
        if user_profile:
            session['user'] = user_profile
            session['is_sandbox_mode'] = True  # Sandbox por defecto al iniciar
            flash('¡Sesión iniciada exitosamente!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Credenciales incorrectas. Inténtalo de nuevo.', 'error')
            
    return render_template('auth/login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user' in session:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']
        role = request.form['role']
        owner_uid = request.form.get('owner_uid')
        
        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'error')
            return render_template('auth/register.html')
            
        if role == 'employee' and not owner_uid:
            flash('Como colaborador de equipo, debes proveer el código UID de tu administrador.', 'error')
            return render_template('auth/register.html')
            
        try:
            user_profile = DatabaseService.register_user(
                email=email,
                password=password,
                name=name,
                role=role,
                owner_uid=owner_uid
            )
            session['user'] = user_profile
            session['is_sandbox_mode'] = True
            flash('Cuenta creada e iniciada exitosamente.', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f'Error al registrar cuenta: {str(e)}', 'error')
            
    return render_template('auth/register.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('is_sandbox_mode', None)
    flash('Sesión cerrada correctamente.', 'success')
    return redirect(url_for('login'))

@app.route('/toggle-sandbox', methods=['POST'])
def toggle_sandbox():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    
    current_mode = session.get('is_sandbox_mode', True)
    session['is_sandbox_mode'] = not current_mode
    return jsonify({"success": True, "sandbox": session['is_sandbox_mode']})

# =========================================================================
# DASHBOARD PRINCIPAL Y ANALÍTICAS
# =========================================================================
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    # Procesar automáticamente recurrencias programadas al abrir dashboard
    RecurrenceService.process_pending_recurrences(owner_uid, sandbox=sandbox)
    
    # Obtener facturas y gastos
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    sequences = DatabaseService.get_sequences(owner_uid, sandbox=sandbox)
    profile = DatabaseService.get_company_profile(owner_uid)
    
    # Filtrar cotizaciones
    real_invoices = [inv for inv in invoices if not inv.get('isQuotation') and inv.get('status') != 'Anulada']
    
    # Calcular KPIs
    total_invoiced = sum(inv['total'] for inv in real_invoices)
    total_expenses = sum(exp['amount'] for exp in expenses)
    total_itbis = sum(inv.get('totalITBIS', 0.0) for inv in real_invoices)
    
    # Cuentas por Cobrar (CxC): Facturas emitidas o vencidas pendientes de pago
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
    scale = request.args.get('scale', 'month')
    date_str = request.args.get('date', datetime.utcnow().strftime("%Y-%m-%d"))
    
    try:
        selected_date = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        selected_date = datetime.utcnow()
        date_str = selected_date.strftime("%Y-%m-%d")
        
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

    # Título dinámico descriptivo para el gráfico (Igual a iOS)
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
    crm_contacts = [c for c in clients if c.get('nextContactDate') and c['nextContactDate'][:10] == today_str]

    # Calcular ingresos acumulados RST 2026 (Ingresos de facturas reales en el año en curso)
    current_year_str = str(datetime.utcnow().year)
    rst_income_year = sum(inv['total'] for inv in real_invoices if inv['date'].startswith(current_year_str))
    rst_limit_2026 = 12068181.09

    # Contingencia: detectar facturas emitidas offline sin sincronizar con la DGII
    from datetime import timezone
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
        contingency_invoices=contingency_invoices
    )

# =========================================================================
# CLIENTES & CRM
# =========================================================================
@app.route('/clients')
def list_clients():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="CRM Clientes", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    
    # Integrar sumas por cliente
    for client in clients:
        c_id = client['id']
        client_sales = [inv for inv in invoices if inv['clientId'] == c_id and not inv.get('isQuotation') and inv.get('status') != 'Anulada']
        client['total_invoiced'] = sum(inv['total'] for inv in client_sales)
        client['total_cxc'] = sum(inv['netPayable'] for inv in client_sales if inv['status'] in ['Emitida', 'Vencida'])

    return render_template('clients/list.html', active_page='clients', clients=clients)

@app.route('/clients/new', methods=['GET', 'POST'])
def new_client():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Nuevo Cliente", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    if request.method == 'POST':
        client_id = str(uuid.uuid4())
        client_dict = {
            "rnc": request.form['rnc'],
            "razonSocial": request.form['razonSocial'],
            "email": request.form.get('email', ''),
            "telefono": request.form.get('telefono', ''),
            "direccion": request.form.get('direccion', ''),
            "crmNotes": request.form.get('crmNotes', ''),
            "nextContactDate": request.form.get('nextContactDate', '')
        }
        
        DatabaseService.save_client(owner_uid, client_id, client_dict, sandbox=sandbox)
        flash('Cliente registrado exitosamente en el directorio CRM.', 'success')
        return redirect(url_for('list_clients'))
        
    return render_template('clients/form.html', active_page='clients', client=None)

@app.route('/clients/<client_id>/edit', methods=['GET', 'POST'])
def edit_client(client_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Editar Cliente", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
    client = next((c for c in clients if c['id'] == client_id), None)
    
    if not client:
        flash('Cliente no encontrado.', 'error')
        return redirect(url_for('list_clients'))
        
    if request.method == 'POST':
        client_dict = {
            "rnc": request.form['rnc'],
            "razonSocial": request.form['razonSocial'],
            "email": request.form.get('email', ''),
            "telefono": request.form.get('telefono', ''),
            "direccion": request.form.get('direccion', ''),
            "crmNotes": request.form.get('crmNotes', ''),
            "nextContactDate": request.form.get('nextContactDate', ''),
            "createdAt": client["createdAt"]
        }
        DatabaseService.save_client(owner_uid, client_id, client_dict, sandbox=sandbox)
        flash('Ficha CRM del cliente actualizada exitosamente.', 'success')
        return redirect(url_for('list_clients'))
        
    return render_template('clients/form.html', active_page='clients', client=client)

@app.route('/clients/<client_id>/delete', methods=['POST'])
def delete_client_route(client_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Eliminar Cliente", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    DatabaseService.delete_client(owner_uid, client_id, sandbox=sandbox)
    flash('Cliente eliminado del directorio.', 'success')
    return redirect(url_for('list_clients'))

@app.route('/clients/<client_id>')
def client_detail(client_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Ver Detalle de Cliente", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
    client = next((c for c in clients if c['id'] == client_id), None)
    
    if not client:
        flash('Cliente no encontrado.', 'error')
        return redirect(url_for('list_clients'))
        
    # Obtener facturas y cotizaciones del cliente
    all_invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    client_invoices = [inv for inv in all_invoices if inv['clientId'] == client_id and not inv.get('isQuotation')]
    client_quotations = [inv for inv in all_invoices if inv['clientId'] == client_id and inv.get('isQuotation')]
    
    # Calcular sumas financieras específicas
    client['total_invoiced'] = sum(inv['total'] for inv in client_invoices if inv.get('status') != 'Anulada')
    client['total_cxc'] = sum(inv['netPayable'] for inv in client_invoices if inv['status'] in ['Emitida', 'Vencida'])
    
    # Obtener interacciones
    interactions = DatabaseService.get_client_interactions(owner_uid, client_id, sandbox=sandbox)
    
    return render_template(
        'clients/detail.html',
        active_page='clients',
        client=client,
        invoices=client_invoices,
        quotations=client_quotations,
        interactions=interactions
    )

@app.route('/clients/<client_id>/interactions/new', methods=['POST'])
def add_client_interaction(client_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Registrar Seguimiento", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    content = request.form.get('content', '').strip()
    interaction_type = request.form.get('type', 'Nota')
    next_contact_date = request.form.get('nextContactDate', '').strip()
    
    if not content:
        flash('El comentario no puede estar vacío.', 'error')
        return redirect(url_for('client_detail', client_id=client_id))
        
    attachment_url = ""
    attachment_name = ""
    
    # Manejar subida de archivo
    file = request.files.get('attachment')
    if file and file.filename:
        try:
            file_data = file.read()
            mime_type = file.mimetype or "application/octet-stream"
            filename = f"crm_{client_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
            destination_path = f"users/{owner_uid}/crm/{filename}"
            
            attachment_url = DatabaseService.upload_file_to_storage(
                file_data=file_data,
                destination_path=destination_path,
                mime_type=mime_type
            )
            attachment_name = file.filename
        except Exception as e:
            flash(f"Advertencia: No se pudo cargar el archivo adjunto: {str(e)}", 'warning')

    interaction_id = str(uuid.uuid4())
    interaction_dict = {
        "type": interaction_type,
        "content": content,
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "nextContactDate": next_contact_date if next_contact_date else None,
        "completed": False,
        "createdBy": session['user']['email'],
        "attachmentUrl": attachment_url,
        "attachmentName": attachment_name
    }
    
    DatabaseService.save_client_interaction(owner_uid, client_id, interaction_id, interaction_dict, sandbox=sandbox)
    
    # Si agregamos un seguimiento y tiene fecha de contacto próxima, actualizar también al cliente
    if next_contact_date:
        clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
        client = next((c for c in clients if c['id'] == client_id), None)
        if client:
            client['nextContactDate'] = next_contact_date
            client['crmNotes'] = content[:100]
            DatabaseService.save_client(owner_uid, client_id, client, sandbox=sandbox)
            
    flash('Interacción registrada exitosamente.', 'success')
    return redirect(url_for('client_detail', client_id=client_id))

@app.route('/clients/<client_id>/interactions/<interaction_id>/delete', methods=['POST'])
def delete_client_interaction_route(client_id, interaction_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Eliminar Seguimiento", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    DatabaseService.delete_client_interaction(owner_uid, client_id, interaction_id, sandbox=sandbox)
    flash('Interacción eliminada correctamente de la línea de tiempo.', 'success')
    return redirect(url_for('client_detail', client_id=client_id))

@app.route('/clients/<client_id>/interactions/<interaction_id>/complete', methods=['POST'])
def complete_client_interaction_task(client_id, interaction_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Completar Seguimiento", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    interactions = DatabaseService.get_client_interactions(owner_uid, client_id, sandbox=sandbox)
    interaction = next((it for it in interactions if it['id'] == interaction_id), None)
    
    if interaction:
        interaction['completed'] = True
        DatabaseService.save_client_interaction(owner_uid, client_id, interaction_id, interaction, sandbox=sandbox)
        
        # Limpiar también la fecha de próximo contacto de la ficha principal del cliente
        clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
        client = next((c for c in clients if c['id'] == client_id), None)
        if client and client.get('nextContactDate') == interaction.get('nextContactDate'):
            client['nextContactDate'] = None
            DatabaseService.save_client(owner_uid, client_id, client, sandbox=sandbox)
            
        flash('Seguimiento marcado como COMPLETADO.', 'success')
        
    return redirect(url_for('client_detail', client_id=client_id))

@app.route('/clients/<client_id>/interactions/quick-note', methods=['POST'])
def add_quick_note(client_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Registrar Nota CRM", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    content = request.form.get('content', '').strip()
    interaction_type = request.form.get('type', 'Nota')
    complete_task = request.form.get('completeTask') == 'true'
    
    if not content:
        flash('La nota no puede estar vacía.', 'error')
        return redirect(url_for('dashboard'))
        
    interaction_id = str(uuid.uuid4())
    interaction_dict = {
        "type": interaction_type,
        "content": content,
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "nextContactDate": None,
        "completed": False,
        "createdBy": session['user']['email'],
        "attachmentUrl": "",
        "attachmentName": ""
    }
    
    DatabaseService.save_client_interaction(owner_uid, client_id, interaction_id, interaction_dict, sandbox=sandbox)
    
    # Si se marcó completar compromiso
    if complete_task:
        clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
        client = next((c for c in clients if c['id'] == client_id), None)
        if client:
            client['nextContactDate'] = None
            client['crmNotes'] = content[:100]
            DatabaseService.save_client(owner_uid, client_id, client, sandbox=sandbox)
            
    flash('Nota rápida registrada en el historial del cliente.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/api/rnc-lookup')
def rnc_lookup():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    rnc = request.args.get('rnc', '')
    res = DGIIService.validate_and_fetch_rnc(rnc)
    return jsonify(res)

# =========================================================================
# CATÁLOGO DE ARTÍCULOS
# =========================================================================
@app.route('/items')
def list_items():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Catálogo de Productos", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
    return render_template('items/list.html', active_page='items', items=items)

@app.route('/items/new', methods=['GET', 'POST'])
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
            "type": request.form.get('type', 'Bien'),
            "name": request.form['name'],
            "price": float(request.form['price']),
            "unit": request.form.get('unit', 'Unidad'),
            "itbisRate": float(request.form.get('itbisRate', 0.18)),
            "minStock": float(request.form.get('minStock') or 0.0),
            "rackLocation": request.form.get('rackLocation', ''),
            "totalStock": 0.0
        }
        
        DatabaseService.save_item(owner_uid, item_id, item_dict, sandbox=sandbox)
        flash('Artículo añadido al catálogo de ventas.', 'success')
        return redirect(url_for('list_items'))
        
    return render_template('items/form.html', active_page='items', item=None)

@app.route('/items/<item_id>/edit', methods=['GET', 'POST'])
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
            "type": request.form.get('type', 'Bien'),
            "name": request.form['name'],
            "price": float(request.form['price']),
            "unit": request.form.get('unit', 'Unidad'),
            "itbisRate": float(request.form.get('itbisRate', 0.18)),
            "minStock": float(request.form.get('minStock') or 0.0),
            "rackLocation": request.form.get('rackLocation', ''),
            "totalStock": float(item.get("totalStock", 0.0)),
            "createdAt": item["createdAt"]
        }
        DatabaseService.save_item(owner_uid, item_id, item_dict, sandbox=sandbox)
        flash('Artículo del catálogo actualizado.', 'success')
        return redirect(url_for('list_items'))
        
    return render_template('items/form.html', active_page='items', item=item)

@app.route('/items/<item_id>/delete', methods=['POST'])
def delete_item_route(item_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Eliminar Artículo", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    DatabaseService.delete_item(owner_uid, item_id, sandbox=sandbox)
    flash('Artículo eliminado del catálogo.', 'success')
    return redirect(url_for('list_items'))

@app.route('/items/import-csv', methods=['POST'])
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

@app.route('/items/download-template')
def download_csv_template():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Descargar Plantilla CSV", required_permission="canClients")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["codigo", "tipo_bien_o_servicio", "nombre", "precio", "unidad_medida", "tasa_itbis"])
    writer.writerow(["PROD-001", "Bien", "Laptop Dell Latitude", "45000.00", "Unidad", "0.18"])
    writer.writerow(["SERV-002", "Servicio", "Asesoría Legal por Hora", "3500.00", "Hora", "0.0"])
    
    dest = io.BytesIO(output.getvalue().encode('utf-8'))
    return send_file(
        dest,
        mimetype="text/csv",
        as_attachment=True,
        download_name="plantilla_items_efactura.csv"
    )

# =========================================================================
# GESTIÓN DE INVENTARIO Y ALMACENES
# =========================================================================
@app.route('/inventory')
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

@app.route('/inventory/warehouses')
def inventory_warehouses():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canManageInventory'):
        return render_template('auth/restricted.html', feature_name="Almacenes", required_permission="canManageInventory")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox)
    return render_template('inventario/almacenes.html', active_page='inventory', warehouses=warehouses)

@app.route('/inventory/warehouses/new', methods=['GET', 'POST'])
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

@app.route('/inventory/warehouses/<warehouse_id>/edit', methods=['GET', 'POST'])
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

@app.route('/inventory/warehouses/<warehouse_id>/delete', methods=['POST'])
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

@app.route('/inventory/transactions')
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

@app.route('/inventory/transactions/new', methods=['GET', 'POST'])
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
@app.route('/invoices')
def list_invoices():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Documentos y Facturación", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=False)
    return render_template('invoices/list.html', active_page='invoices', invoices=invoices)

@app.route('/quotations')
def list_quotations():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Cotizaciones", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    quotations = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=True)
    return render_template('invoices/list.html', active_page='quotations', invoices=quotations)

@app.route('/invoices/new', methods=['GET', 'POST'])
@app.route('/quotations/new', methods=['GET', 'POST'])
@app.route('/invoices/<invoice_id>/edit', methods=['GET', 'POST'])
@app.route('/quotations/<invoice_id>/edit', methods=['GET', 'POST'])
def new_invoice_route(invoice_id=None):
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
            return redirect(url_for('list_invoices'))
        if existing_invoice.get('status') not in ['Borrador', 'Rechazada']:
            flash('Solo se pueden editar documentos en estado Borrador.', 'error')
            return redirect(url_for('invoice_detail', invoice_id=invoice_id))

    if existing_invoice:
        is_quotation_route = existing_invoice.get('isQuotation', False)
    else:
        is_quotation_route = "quotation" in request.path or "cotizacion" in request.path
        
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
        
        # Parámetros de recurrencia
        is_recurring = request.form.get('isRecurring') == 'true'
        recurrence_interval = request.form.get('recurrenceInterval', 'mensual')
        next_occurrence = request.form.get('nextOccurrenceDate')

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
                    
        for idx in sorted(item_indices):
            name = request.form.get(f'items[{idx}][name]')
            price = float(request.form.get(f'items[{idx}][price]', 0.0))
            qty = int(request.form.get(f'items[{idx}][quantity]', 1))
            itbis_rate = float(request.form.get(f'items[{idx}][itbisRate]', 0.18))
            item_disc = float(request.form.get(f'items[{idx}][discountRate]', 0.0))
            
            if name:
                parsed_items.append({
                    "name": name,
                    "price": price,
                    "quantity": qty,
                    "itbisRate": itbis_rate,
                    "discountRate": item_disc
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
            invoice_dict["isQuotation"] = is_quotation
            invoice_dict["notes"] = request.form.get('notes', '')
            invoice_dict["isRecurring"] = is_recurring
            invoice_dict["recurrenceInterval"] = recurrence_interval
            invoice_dict["nextOccurrenceDate"] = next_occurrence if is_recurring else None
            invoice_dict["currency"] = currency
            invoice_dict["paymentType"] = "Crédito" if due_date > datetime.utcnow().strftime("%Y-%m-%d") else "Contado"
            invoice_dict["paymentMethod"] = payment_method
            invoice_dict["warehouseId"] = request.form.get('warehouseId', '')
            invoice_dict["branchId"] = request.form.get('branchId', 'default-sucursal-principal')
            invoice_dict["items"] = calcs["items"]
        else:
            random_num = f"{random.randint(1, 999999):06d}"
            inv_number = f"COT-{random_num}" if is_quotation else f"FAC-{random_num}"
            target_invoice_id = str(uuid.uuid4())
            invoice_dict = {
                "invoiceNumber": inv_number,
                "date": datetime.utcnow().strftime("%Y-%m-%d"),
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
                "isQuotation": is_quotation,
                "isConvertedToInvoice": False,
                "notes": request.form.get('notes', ''),
                "isRecurring": is_recurring,
                "recurrenceInterval": recurrence_interval,
                "nextOccurrenceDate": next_occurrence if is_recurring else None,
                "firebasePDFURL": "",
                "firebaseXMLURL": "",
                "currency": currency,
                "paymentType": "Crédito" if due_date > datetime.utcnow().strftime("%Y-%m-%d") else "Contado",
                "paymentMethod": payment_method,
                "incomeType": "01 - Ingresos por operaciones",
                "customFields": [],
                "exchangeRate": CurrencyService.get_rate(currency),
                "warehouseId": request.form.get('warehouseId', ''),
                "branchId": request.form.get('branchId', 'default-sucursal-principal'),
                "items": calcs["items"]
            }
        
        DatabaseService.save_invoice(owner_uid, target_invoice_id, invoice_dict, sandbox=sandbox)
        
        action = request.form.get('action')
        
        if is_quotation:
            flash('Cotización creada exitosamente como borrador.', 'success')
            return redirect(url_for('list_quotations'))
        elif action == 'emitir_cobrar':
            company = DatabaseService.get_company_profile(owner_uid)
            try:
                if not invoice_dict.get("encf"):
                    ecf_short = AlanubeService.get_ecf_type_short_code(invoice_dict["ecfType"])
                    user_email = session['user']['email']
                    encf, log_id = DatabaseService.consume_next_sequence(owner_uid, ecf_short, user_email, sandbox=sandbox)
                    invoice_dict["encf"] = encf
                    
                res = AlanubeService.emit_electronic_comprobante(company, invoice_dict, sandbox=sandbox)
                
                if res.get("success"):
                    invoice_dict["status"] = "Cobrada"
                    invoice_dict["encf"] = res["encf"]
                    invoice_dict["xmlSignature"] = res["xmlSignature"]
                    invoice_dict["qrCodeURL"] = res["qrCodeURL"]
                    invoice_dict["firebasePDFURL"] = res["pdfUrl"]
                    invoice_dict["firebaseXMLURL"] = res["xmlUrl"]
                    # FALLBACK = emitido offline, aún pendiente de sincronizar con la DGII
                    invoice_dict["isSyncedWithDGII"] = (res.get("mode", "API") == "API")
                    invoice_dict["paymentDate"] = datetime.utcnow().isoformat()
                    invoice_dict["emisionMode"] = res.get("mode", "API")
                    invoice_dict["contingencyEmittedAt"] = datetime.utcnow().isoformat() if res.get("mode") == "FALLBACK" else None
                    
                    DatabaseService.save_invoice(owner_uid, target_invoice_id, invoice_dict, sandbox=sandbox)
                    
                    logs = DatabaseService.get_sequence_logs(owner_uid, sandbox=sandbox)
                    log = next((l for l in logs if l["encf"] == res["encf"]), None)
                    if log:
                        # Verificar cuadratura y regla de tolerancia
                        cuadratura = DGIIService.check_tolerancia_cuadratura(invoice_dict["items"], invoice_dict["total"])
                        estado_dgii = "ACCEPTED" if cuadratura["within_tolerance"] else "ACCEPTED_CONDITIONAL"
                        motivo = f"Aprobado por la DGII. Firma: {res['xmlSignature'][:12]}"
                        if estado_dgii == "ACCEPTED_CONDITIONAL":
                            motivo = f"Aceptado Condicional por tolerancia: {', '.join(cuadratura['warnings'])}"
                        
                        DatabaseService.update_sequence_log(owner_uid, log["id"], {
                            "estado": estado_dgii,
                            "motivo": motivo
                        }, sandbox=sandbox)
                        
                    flash(f"¡Comprobante emitido y cobrado con éxito! e-NCF: {res['encf']}", "success")
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
    catalog = DatabaseService.get_items(owner_uid, sandbox=sandbox)
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

@app.route('/invoices/<invoice_id>')
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
        
    company = DatabaseService.get_company_profile(owner_uid)
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
    branch = next((b for b in branches if b['id'] == invoice.get("branchId")), None)
    if not branch and branches:
        branch = branches[0]
        
    return render_template('invoices/detail.html', active_page='invoices', invoice=invoice, company=company, branch=branch)

@app.route('/invoices/<invoice_id>/pay', methods=['POST'])
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
        
    bank = request.form.get('bank', 'Caja Efectivo')
    reference_number = request.form.get('referenceNumber', 'Pago en Efectivo')
    
    invoice["status"] = "Cobrada"
    invoice["bank"] = bank
    invoice["referenceNumber"] = reference_number
    invoice["paymentDate"] = datetime.utcnow().isoformat()
    
    DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
    if invoice.get("paymentMethod") == 'Efectivo':
        flash('¡Cobro en efectivo registrado con éxito!', 'success')
    else:
        flash(f'¡Cobro por transferencia registrado con éxito en {bank}!', 'success')
    
    return redirect(url_for('invoice_detail', invoice_id=invoice_id))

@app.route('/invoices/<invoice_id>/sign', methods=['POST'])
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
        res = AlanubeService.emit_electronic_comprobante(company, invoice, sandbox=sandbox)
        
        if res.get("success"):
            invoice["status"] = "Emitida"
            invoice["encf"] = res["encf"]
            invoice["xmlSignature"] = res["xmlSignature"]
            invoice["qrCodeURL"] = res["qrCodeURL"]
            invoice["firebasePDFURL"] = res["pdfUrl"]
            invoice["firebaseXMLURL"] = res["xmlUrl"]
            # FALLBACK = emitido offline, aún pendiente de sincronizar con la DGII
            invoice["isSyncedWithDGII"] = (res.get("mode", "API") == "API")
            invoice["emisionMode"] = res.get("mode", "API")
            invoice["contingencyEmittedAt"] = datetime.utcnow().isoformat() if res.get("mode") == "FALLBACK" else None
            
            DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
            
            # Sincronizar en log de auditoría
            logs = DatabaseService.get_sequence_logs(owner_uid, sandbox=sandbox)
            log = next((l for l in logs if l["encf"] == res["encf"]), None)
            if log:
                # Verificar cuadratura y regla de tolerancia
                cuadratura = DGIIService.check_tolerancia_cuadratura(invoice["items"], invoice["total"])
                estado_dgii = "ACCEPTED" if cuadratura["within_tolerance"] else "ACCEPTED_CONDITIONAL"
                motivo = f"Aprobado por la DGII. Firma: {res['xmlSignature'][:12]}"
                if estado_dgii == "ACCEPTED_CONDITIONAL":
                    motivo = f"Aceptado Condicional por tolerancia: {', '.join(cuadratura['warnings'])}"
                
                # Guardar actualización
                DatabaseService.update_sequence_log(owner_uid, log["id"], {
                    "estado": estado_dgii,
                    "motivo": motivo
                }, sandbox=sandbox)
                
            flash(f"¡Comprobante firmado digitalmente con éxito! e-NCF: {res['encf']} (Modo: {res['mode']})", "success")
        else:
            flash(f"Error al certificar comprobante: {res.get('message')}", "error")
            
    except Exception as e:
        flash(f"Fallo en la emisión de comprobante: {str(e)}", "error")
        
    return redirect(url_for('invoice_detail', invoice_id=invoice_id))

@app.route('/invoices/<invoice_id>/convert', methods=['POST'])
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


@app.route('/invoices/<invoice_id>/qr-image')
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

@app.route('/invoices/<invoice_id>/pdf')
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
        rendered_html = render_template('invoices/pdf.html', invoice=invoice, company=company, branch=branch, auto_print=False, qr_base64=qr_base64, fecha_firma_str=fecha_firma_str)
        pdf_bytes = WeasyprintHTML(string=rendered_html, base_url=request.host_url).write_pdf()
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="{inv_num}.pdf"'
        return response
    else:
        # Fallback sin dependencias externas o si action es 'print':
        # devolver HTML optimizado para impresión y auto-disparar el diálogo Imprimir del navegador
        rendered_html = render_template('invoices/pdf.html', invoice=invoice, company=company, branch=branch, auto_print=True, qr_base64=qr_base64, fecha_firma_str=fecha_firma_str)
        response = make_response(rendered_html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        return response

@app.route('/invoices/<invoice_id>/xml')
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

    xml_content = invoice.get('xmlContent') or invoice.get('xmlSignature') or ''
    if not xml_content:
        return "No hay XML disponible para este comprobante", 404

    inv_num = invoice.get('invoiceNumber', invoice_id).replace('/', '-').replace(' ', '_')
    response = make_response(xml_content)
    response.headers['Content-Type'] = 'application/xml; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{inv_num}.xml"'
    return response

@app.route('/invoices/<invoice_id>/void', methods=['POST'])
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
        res = AlanubeService.emit_cancellation(company, canc_dict, sandbox=sandbox)
        if res.get("success"):
            invoice["status"] = "Anulada"
            DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
            
            # Registrar anulación local
            DatabaseService.save_cancellation(owner_uid, str(uuid.uuid4()), {
                "series": canc_dict["series"],
                "startSequence": canc_dict["startSequence"],
                "endSequence": canc_dict["endSequence"],
                "reason": canc_dict["reason"],
                "status": "Aceptado",
                "cancellationCode": res["cancellationCode"],
                "responseMessage": res["message"]
            }, sandbox=sandbox)
            
            flash(f"Comprobante anulado y reportado a la DGII. Código: {res['cancellationCode']}", "success")
        else:
            flash(f"Fallo al anular comprobante en la API: {res.get('message')}", "error")
    else:
        invoice["status"] = "Anulada"
        DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
        flash('Borrador de factura anulado correctamente.', 'success')
        
    return redirect(url_for('list_invoices'))

@app.route('/api/invoices/sync-contingency', methods=['POST'])
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
            res = AlanubeService.emit_electronic_comprobante(company, inv, sandbox=sandbox)
            if res.get("success") and res.get("mode") == "API":
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
                        "motivo": f"Regularizado por Sincronización Post-Contingencia. Firma: {res['xmlSignature'][:12] if res.get('xmlSignature') else 'N/A'}"
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

@app.route('/invoices/<invoice_id>/sync', methods=['POST'])
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
        res = AlanubeService.emit_electronic_comprobante(company, invoice, sandbox=sandbox)
        if res.get("success") and res.get("mode") == "API":
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
                    "motivo": f"Regularizado por Sincronización Manual. Firma: {res['xmlSignature'][:12] if res.get('xmlSignature') else 'N/A'}"
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
@app.route('/expenses')
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

@app.route('/expenses/new', methods=['GET', 'POST'])
def new_expense_route():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Registrar Gasto", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    if request.method == 'POST':
        expense_id = str(uuid.uuid4())
        
        # Procesar archivo subido (recibo/ticket) a Storage
        attachment_file = request.files.get('attachment')
        attachment_urls = []
        if attachment_file and attachment_file.filename:
            file_data = attachment_file.read()
            mime_type = attachment_file.content_type or "image/jpeg"
            dest_path = f"users/{owner_uid}/expenses/{expense_id}/{attachment_file.filename}"
            
            # Subir a Firebase Storage (o local fallback si no está configurado)
            public_url = DatabaseService.upload_file_to_storage(file_data, dest_path, mime_type)
            attachment_urls.append(public_url)
            
        amount = float(request.form['amount'])
        is_recurring = request.form.get('isRecurring') == 'true'
        is_deductible = request.form.get('isDeductible') == 'true'
        recurrence_interval = request.form.get('recurrenceInterval', 'mensual')
        next_occurrence = request.form.get('nextOccurrenceDate')

        expense_dict = {
            "concept": request.form['concept'],
            "category": request.form['category'],
            "amount": amount,
            "date": request.form['date'],
            "rncEmisor": request.form.get('rncEmisor', ''),
            "ncf": request.form.get('ncf', ''),
            "isMinorExpense": "E43" in request.form.get('ncf', ''),
            "isSyncedWithDGII": False,
            "qrCodeURL": "",
            "xmlSignature": "",
            "notes": request.form.get('notes', ''),
            "isRecurring": is_recurring,
            "recurrenceInterval": recurrence_interval,
            "nextOccurrenceDate": next_occurrence if is_recurring else None,
            "associatedInvoiceId": request.form.get('associatedInvoiceId', ''),
            "itbisAmount": amount * 0.18 / 1.18,  # Cálculo de ITBIS estándar incluido
            "isITBISDeductible": is_deductible,
            "isDeductible": is_deductible,
            "firebaseAttachmentURLs": attachment_urls
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

@app.route('/expenses/<expense_id>/delete', methods=['POST'])
def delete_expense_route(expense_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Eliminar Gasto", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    DatabaseService.delete_expense(owner_uid, expense_id, sandbox=sandbox)
    flash('Gasto eliminado.', 'success')
    return redirect(url_for('list_expenses'))

# =========================================================================
# SECUENCIAS FISCALES
# =========================================================================
@app.route('/sequences')
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

@app.route('/sequences/new', methods=['POST'])
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

@app.route('/cancellations/new', methods=['POST'])
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
    
    res = AlanubeService.emit_cancellation(company, canc_dict, sandbox=sandbox)
    
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
@app.route('/settings/company', methods=['GET', 'POST'])
def company_settings():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canModifySettings'):
        return render_template('auth/restricted.html', feature_name="Configuración de la Empresa", required_permission="canModifySettings")
    owner_uid = session['user']['ownerUID']
    
    if request.method == 'POST':
        # Preservar logoUrl y configuraciones de marca existentes
        existing_profile = DatabaseService.get_company_profile(owner_uid)
        
        profile_dict = {
            "companyName": request.form['companyName'],
            "companyRNC": request.form['companyRNC'],
            "companyAddress": request.form.get('companyAddress', ''),
            "companyPhone": request.form.get('companyPhone', ''),
            "companyEmail": request.form.get('companyEmail', ''),
            "colorMarca": existing_profile.get('colorMarca', '#10b981'),
            "gradientEnabled": existing_profile.get('gradientEnabled', True),
            "applyColorMarcaUI": existing_profile.get('applyColorMarcaUI', True),
            "applyColorMarcaReports": existing_profile.get('applyColorMarcaReports', True),
            "logoUrl": existing_profile.get('logoUrl', ''),
            "regimenFiscal": request.form.get('regimenFiscal', 'General'),
            "openaiApiKey": request.form.get('openaiApiKey', '')
        }
        DatabaseService.save_company_profile(owner_uid, profile_dict)

        flash('Ajustes y perfil de empresa actualizados correctamente.', 'success')
        return redirect(url_for('company_settings'))
        
    profile = DatabaseService.get_company_profile(owner_uid)
    
    # Obtener equipo
    team = DatabaseService.get_team_members(owner_uid)

    # Obtener sucursales
    branches = DatabaseService.get_branches(owner_uid, sandbox=session.get('is_sandbox_mode', True))

    return render_template('company_settings.html', active_page='settings', profile=profile, team=team, branches=branches)

@app.route('/settings/company/brand', methods=['POST'])
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
        
    logo_file = request.files.get('logoFile')
    if logo_file and logo_file.filename:
        file_data = logo_file.read()
        mime_type = logo_file.content_type or "image/png"
        ext = logo_file.filename.rsplit('.', 1)[-1].lower() if '.' in logo_file.filename else 'png'
        dest_path = f"users/{owner_uid}/company/logo_{uuid.uuid4().hex[:8]}.{ext}"
        existing_profile['logoUrl'] = DatabaseService.upload_file_to_storage(file_data, dest_path, mime_type)
        
    if request.form.get('removeLogo') == 'true':
        existing_profile['logoUrl'] = ''
        
    DatabaseService.save_company_profile(owner_uid, existing_profile)
    return jsonify({"success": True, "profile": existing_profile})

@app.route('/settings/team/new', methods=['POST'])
def add_team_member():
    if 'user' not in session: return redirect(url_for('login'))
    if session['user'].get('role') != 'owner':
        flash('No tienes permisos de propietario.', 'error')
        return redirect(url_for('company_settings'))
    
    owner_uid = session['user']['ownerUID']
    
    name = request.form['name']
    email = request.form['email']
    password = request.form['password']
    
    permissions = {
        "canInvoice": 'canInvoice' in request.form,
        "canExpenses": 'canExpenses' in request.form,
        "canClients": 'canClients' in request.form,
        "canModifySettings": 'canModifySettings' in request.form,
        "canManageInventory": 'canManageInventory' in request.form
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
        
    return redirect(url_for('company_settings'))

@app.route('/settings/branches/save', methods=['POST'])
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

@app.route('/settings/branches/<branch_id>/delete', methods=['POST'])
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

@app.route('/settings/team/<employee_uid>/permissions', methods=['POST'])
def update_team_member_permissions(employee_uid):
    if 'user' not in session: return redirect(url_for('login'))
    if session['user'].get('role') != 'owner':
        flash('No tienes permisos de propietario.', 'error')
        return redirect(url_for('company_settings'))
    
    permissions = {
        "canInvoice": 'canInvoice' in request.form,
        "canExpenses": 'canExpenses' in request.form,
        "canClients": 'canClients' in request.form,
        "canModifySettings": 'canModifySettings' in request.form,
        "canManageInventory": 'canManageInventory' in request.form
    }
    
    if DatabaseService.update_employee_permissions(employee_uid, permissions):
        flash('Permisos del colaborador actualizados con éxito.', 'success')
    else:
        flash('Error al actualizar permisos.', 'error')
        
    return redirect(url_for('company_settings'))

@app.route('/settings/team/<employee_uid>/delete', methods=['POST'])
def delete_team_member_route(employee_uid):
    if 'user' not in session: return redirect(url_for('login'))
    if session['user'].get('role') != 'owner':
        flash('No tienes permisos de propietario.', 'error')
        return redirect(url_for('company_settings'))
    
    owner_uid = session['user']['ownerUID']
    
    if DatabaseService.delete_team_member(owner_uid, employee_uid):
        flash('Colaborador desvinculado de tu equipo.', 'success')
    else:
        flash('Error al desvincular colaborador.', 'error')
        
    return redirect(url_for('company_settings'))

@app.route('/settings/company/export', methods=['POST'])
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
        writer.writerow(["ID", "Codigo", "Tipo", "Nombre", "Precio", "Unidad", "Tasa ITBIS", "Stock Minimo", "Ubicacion Estanteria", "Stock Total", "Creado En"])
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
                p.get("createdAt", "")
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
@app.route('/reports')
def reports_dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Reportería DGII", required_permission="canInvoice")
    return render_template('reports/reports_dashboard.html', active_page='reports')

@app.route('/reports/it1')
def it1_diagnostic():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Diagnóstico de IT-1", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    
    # Filtrar reales
    real_invoices = [inv for inv in invoices if not inv.get('isQuotation') and inv.get('status') != 'Anulada']
    
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

@app.route('/reports/simulators')
def simulators_dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', feature_name="Simuladores de Reportes", required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    tab = request.args.get('tab', '606')
    
    if tab == '606':
        expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
        reports_data = [exp for exp in expenses if exp.get('isDeductible', True)]
    else:
        invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
        reports_data = [inv for inv in invoices if not inv.get('isQuotation') and inv.get('status') != 'Anulada']
        
    return render_template(
        'reports/simulators.html',
        active_page='reports',
        active_tab=tab,
        reports_data=reports_data
    )

@app.route('/reports/export/<report_type>')
def export_report_csv(report_type):
    if 'user' not in session: return "No autorizado", 401
    if not check_permission('canInvoice'):
        return "Acceso denegado: requiere permiso de facturación", 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    dest = io.BytesIO()
    # Escribir en UTF-8 con wrapper de texto
    wrapper = io.TextIOWrapper(dest, 'utf-8', write_through=True)
    writer = csv.writer(wrapper)
    
    if report_type == '606':
        # Cabecera oficial simplificada DGII 606
        writer.writerow(["RNC o Cedula", "Tipo Bien o Servicio", "NCF", "NCF Modificado", "Fecha Comprobante", "Fecha Pago", "Monto Facturado", "ITBIS Facturado", "ITBIS Retenido", "ISR Retenido", "Medio Pago"])
        expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
        deductible_expenses = [exp for exp in expenses if exp.get('isDeductible', True)]
        for exp in deductible_expenses:
            writer.writerow([
                exp.get("rncEmisor", "101012345"),
                "02 - Gastos de Tecnología",
                exp.get("ncf", "B0100000001"),
                "",
                exp["date"][:10].replace("-", ""),
                exp["date"][:10].replace("-", ""),
                f"{exp['amount'] - exp['itbisAmount']:.2f}",
                f"{exp['itbisAmount']:.2f}",
                "0.00",
                "0.00",
                "01 - Efectivo"
            ])
    else:
        # Cabecera oficial simplificada DGII 607
        writer.writerow(["RNC o Cedula", "Tipo Identificacion", "NCF", "NCF Modificado", "Fecha Comprobante", "Monto Facturado", "ITBIS Facturado", "ITBIS Retenido", "Retencion ISR", "Efectivo", "Tarjeta", "Cheque/Transf", "Credito"])
        invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
        real_invoices = [inv for inv in invoices if not inv.get('isQuotation') and inv.get('status') != 'Anulada']
        for inv in real_invoices:
            rnc = inv.get("clientRNC") or "999999999"
            t_id = "1" if len(rnc) == 9 else ("2" if len(rnc) == 11 else "3")
            writer.writerow([
                rnc,
                t_id,
                inv.get("encf", ""),
                "",
                inv["date"][:10].replace("-", ""),
                f"{inv['subtotal']:.2f}",
                f"{inv['totalITBIS']:.2f}",
                f"{inv.get('retainedITBIS', 0.0):.2f}",
                f"{inv.get('retainedISR', 0.0):.2f}",
                f"{inv['netPayable'] if inv['paymentMethod'] == 'Efectivo' else 0.0:.2f}",
                f"{inv['netPayable'] if inv['paymentMethod'] == 'Tarjeta de Crédito / Débito' else 0.0:.2f}",
                f"{inv['netPayable'] if inv['paymentMethod'] == 'Cheque / Transferencia' else 0.0:.2f}",
                f"{inv['netPayable'] if inv['paymentMethod'] == 'Crédito' else 0.0:.2f}"
            ])
            
    dest.seek(0)
    filename = f"reporte_{report_type}_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return send_file(
        dest,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )

@app.route('/help')
def help_center():
    if 'user' not in session: return redirect(url_for('login'))
    return render_template('help.html', active_page='help')

@app.route('/api/chatbot', methods=['POST'])
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

if __name__ == '__main__':
    app.run(debug=True, port=5001)
