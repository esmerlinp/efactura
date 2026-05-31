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
from ecf_emission_service import EcfEmissionService
from alanube_service import AlanubeService
from recurrence_service import RecurrenceService


# Inicializar Flask
app = Flask(__name__)
app.config.from_object(Config)

# Registrar Blueprint de la API REST v1
from api import api_bp
app.register_blueprint(api_bp, url_prefix='/api/v1')


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
        if 'is_sandbox_mode' not in session:
            session['is_sandbox_mode'] = False
        # Cargar perfil fresco en tiempo real de Firestore para sincronización reactiva
        fresh_profile = DatabaseService.get_user_profile(session['user']['uid'])
        if fresh_profile:
            session['user'] = fresh_profile
        
        # En modo producción, obligar al propietario a configurar el perfil si no lo ha hecho
        if not session.get('is_sandbox_mode', True):
            owner_uid = session['user'].get('ownerUID')
            if owner_uid:
                company_profile = DatabaseService.get_company_profile(owner_uid)
                if not company_profile.get('configured', False):
                    # Evitar bucle de redirección en páginas esenciales
                    if request.endpoint not in ['company_settings', 'logout', 'toggle_sandbox', 'static', 'user_profile_page', 'update_user_profile', 'change_user_password', None]:
                        flash("Para poder operar en Modo de Producción, debes primero configurar y guardar los datos reales de tu empresa.", "warning")
                        return redirect(url_for('company_settings'))

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
    is_logged_in = 'user' in session
    return render_template('landing.html', is_logged_in=is_logged_in)

@app.route('/api/solicitar-demo', methods=['POST'])
def api_solicitar_demo():
    try:
        data = request.json or {}
        name = data.get('name')
        email = data.get('email')
        phone = data.get('phone')
        rnc = data.get('rnc', '')
        volumen = data.get('volumen_facturas', '100')
        
        # Registrar solicitud de demo y cotización en consola
        print(f"INFO [Landing Lead]: Nueva solicitud de demo/cotización recibida. Nombre: {name}, Email: {email}, Teléfono: {phone}, RNC: {rnc}, Volumen: {volumen} e-CF/mes", flush=True)
        
        return jsonify({"success": True, "message": "¡Solicitud registrada con éxito!"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
            session['is_sandbox_mode'] = False  # Producción por defecto al iniciar
            flash('¡Sesión iniciada exitosamente!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Credenciales incorrectas. Inténtalo de nuevo.', 'error')
            
    return render_template('auth/login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    flash('El registro público de cuentas está deshabilitado. Comuníquese con ventas para crear su cuenta.', 'error')
    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('is_sandbox_mode', None)
    flash('Sesión cerrada correctamente.', 'success')
    return redirect(url_for('login'))


@app.route('/forgot-password', methods=['POST'])
def forgot_password():
    """Envía un correo de recuperación de contraseña usando Firebase Auth REST API."""
    from config import Config
    import requests as http_requests

    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()

    if not email:
        return jsonify({"success": False, "error": "El correo electrónico es requerido."}), 400

    if not Config.FIREBASE_API_KEY:
        return jsonify({"success": False, "error": "La función de recuperación de contraseña no está disponible en este momento."}), 503

    try:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={Config.FIREBASE_API_KEY}"
        res = http_requests.post(url, json={
            "requestType": "PASSWORD_RESET",
            "email": email
        }, timeout=10)

        if res.status_code == 200:
            # Éxito: Firebase envió el correo
            print(f"INFO [ForgotPassword]: Correo de recuperación enviado a {email}", flush=True)
            return jsonify({"success": True})
        else:
            error_data = res.json().get("error", {})
            error_code = error_data.get("message", "")
            print(f"⚠️ [ForgotPassword] Firebase error para {email}: {error_code}", flush=True)

            # Seguridad: para emails no registrados devolvemos éxito igualmente
            # para evitar enumeración de cuentas (email enumeration attack)
            if error_code in ("EMAIL_NOT_FOUND", "INVALID_EMAIL"):
                return jsonify({"success": True})

            return jsonify({"success": False, "error": "Error al enviar el correo. Verifica la dirección e inténtalo de nuevo."})

    except Exception as e:
        print(f"❌ [ForgotPassword] Excepción: {e}", flush=True)
        return jsonify({"success": False, "error": "Error de conexión. Por favor intenta más tarde."}), 500


@app.route('/toggle-sandbox', methods=['POST'])
def toggle_sandbox():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    
    data = request.get_json(silent=True) or {}
    if 'sandbox' in data:
        session['is_sandbox_mode'] = bool(data['sandbox'])
    else:
        current_mode = session.get('is_sandbox_mode', False)
        session['is_sandbox_mode'] = not current_mode
    return jsonify({"success": True, "sandbox": session['is_sandbox_mode']})

# =========================================================================
# PERFIL DE USUARIO
# =========================================================================
@app.route('/profile', methods=['GET'])
def user_profile_page():
    """Muestra la pantalla de perfil del usuario autenticado."""
    if 'user' not in session:
        return redirect(url_for('login'))
    
    # Parámetros de feedback inline (pasados como query params tras redirect)
    info_success = request.args.get('info_success')
    info_error = request.args.get('info_error')
    pwd_success = request.args.get('pwd_success')
    pwd_error = request.args.get('pwd_error')

    return render_template(
        'user_profile.html',
        active_page='profile',
        user=session['user'],
        info_success=info_success,
        info_error=info_error,
        pwd_success=pwd_success,
        pwd_error=pwd_error,
    )


@app.route('/profile/update', methods=['POST'])
def update_user_profile():
    """Procesa la actualización de información personal del usuario (nombre, teléfono, dirección)."""
    if 'user' not in session:
        return redirect(url_for('login'))

    uid = session['user']['uid']
    name = request.form.get('name', '').strip()
    phone = request.form.get('phone', '').strip()
    address = request.form.get('address', '').strip()

    if not name:
        return redirect(url_for('user_profile_page', info_error='El nombre no puede estar vacío.'))

    try:
        updated_profile = {
            "name": name,
            "phone": phone,
            "address": address,
            "permissions": session['user'].get('permissions', {})
        }
        DatabaseService.save_user_profile(uid, updated_profile)

        # Actualizar la sesión activa para reflejar los cambios de inmediato
        session['user']['name'] = name
        session['user']['phone'] = phone
        session['user']['address'] = address
        session.modified = True

        return redirect(url_for('user_profile_page', info_success='¡Información personal actualizada con éxito!'))
    except Exception as e:
        return redirect(url_for('user_profile_page', info_error=f'Error al guardar: {str(e)}'))


@app.route('/profile/change-password', methods=['POST'])
def change_user_password():
    """Cambia la contraseña del usuario verificando primero la contraseña actual con Firebase Auth REST API."""
    if 'user' not in session:
        return redirect(url_for('login'))

    email = session['user'].get('email', '')
    current_password = request.form.get('current_password', '').strip()
    new_password = request.form.get('new_password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()

    # Validaciones básicas
    if not current_password or not new_password or not confirm_password:
        return redirect(url_for('user_profile_page', pwd_error='Todos los campos de contraseña son obligatorios.'))

    if new_password != confirm_password:
        return redirect(url_for('user_profile_page', pwd_error='Las contraseñas nuevas no coinciden.'))

    if len(new_password) < 6:
        return redirect(url_for('user_profile_page', pwd_error='La nueva contraseña debe tener al menos 6 caracteres.'))

    if new_password == current_password:
        return redirect(url_for('user_profile_page', pwd_error='La nueva contraseña debe ser diferente a la contraseña actual.'))

    # 1. Verificar la contraseña actual autenticando contra Firebase Auth REST
    from config import Config
    if not Config.FIREBASE_API_KEY:
        return redirect(url_for('user_profile_page', pwd_error='La función de cambio de contraseña no está disponible (FIREBASE_API_KEY no configurada).'))

    import requests as http_requests
    try:
        # Verificar credenciales actuales
        verify_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={Config.FIREBASE_API_KEY}"
        verify_res = http_requests.post(verify_url, json={
            "email": email,
            "password": current_password,
            "returnSecureToken": True
        }, timeout=10)

        if verify_res.status_code != 200:
            error_msg = verify_res.json().get('error', {}).get('message', 'Contraseña actual incorrecta.')
            if 'INVALID_LOGIN_CREDENTIALS' in error_msg or 'WRONG_PASSWORD' in error_msg or 'INVALID_PASSWORD' in error_msg:
                error_msg = 'La contraseña actual es incorrecta. Por favor verifica e inténtalo de nuevo.'
            return redirect(url_for('user_profile_page', pwd_error=error_msg))

        # Obtener el idToken para cambiar la contraseña
        id_token = verify_res.json().get('idToken')
        if not id_token:
            return redirect(url_for('user_profile_page', pwd_error='No se pudo verificar la sesión con Firebase. Intenta de nuevo.'))

        # 2. Cambiar la contraseña usando el idToken válido
        update_url = f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={Config.FIREBASE_API_KEY}"
        update_res = http_requests.post(update_url, json={
            "idToken": id_token,
            "password": new_password,
            "returnSecureToken": True
        }, timeout=10)

        if update_res.status_code == 200:
            return redirect(url_for('user_profile_page', pwd_success='¡Contraseña actualizada exitosamente! Tu nueva contraseña está activa.'))
        else:
            error_detail = update_res.json().get('error', {}).get('message', 'Error desconocido.')
            return redirect(url_for('user_profile_page', pwd_error=f'No se pudo actualizar la contraseña: {error_detail}'))

    except Exception as e:
        return redirect(url_for('user_profile_page', pwd_error=f'Error de conexión con Firebase: {str(e)}'))


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
    
    # Calcular CxC para cada cliente y filtrar clientes con deudas pendientes
    for c in clients:
        c_id = c['id']
        c_sales = [inv for inv in real_invoices if inv['clientId'] == c_id]
        c['total_cxc'] = sum(inv['netPayable'] for inv in c_sales if inv['status'] in ['Emitida', 'Vencida'])

    crm_contacts = [
        c for c in clients 
        if (c.get('nextContactDate') and c['nextContactDate'][:10] == today_str) or c.get('total_cxc', 0.0) > 0.0
    ]

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

@app.route('/clients/ajax_create', methods=['POST'])
def ajax_create_client():
    """Ruta AJAX para crear un cliente desde la pantalla de facturación sin recargar la página."""
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autenticado."}), 401
    if not check_permission('canClients'):
        return jsonify({"success": False, "error": "Sin permiso para registrar clientes."}), 403
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.json or request.form
    rnc = (data.get('rnc') or '').strip()
    razon_social = (data.get('razonSocial') or '').strip()
    
    if not razon_social:
        return jsonify({"success": False, "error": "La Razón Social es obligatoria."}), 400
    
    client_id = str(uuid.uuid4())
    client_dict = {
        "rnc": rnc,
        "razonSocial": razon_social,
        "email": (data.get('email') or '').strip(),
        "telefono": (data.get('telefono') or '').strip(),
        "direccion": (data.get('direccion') or '').strip(),
        "crmNotes": "Registrado desde formulario de facturación",
        "nextContactDate": "",
        "createdAt": datetime.utcnow().isoformat()
    }
    
    DatabaseService.save_client(owner_uid, client_id, client_dict, sandbox=sandbox)
    
    return jsonify({
        "success": True,
        "message": "Cliente registrado exitosamente.",
        "client": {
            "id": client_id,
            "rnc": rnc,
            "razonSocial": razon_social,
            "email": client_dict["email"],
            "telefono": client_dict["telefono"],
            "direccion": client_dict["direccion"],
        }
    })

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
            "totalStock": 0.0,
            "codigoImpuesto": request.form.get('codigoImpuesto', '').strip(),
            "tasaImpuestoAdicional": float(request.form.get('tasaImpuestoAdicional') or 0.0),
            "gradosAlcohol": float(request.form.get('gradosAlcohol') or 0.0),
            "cantidadReferencia": float(request.form.get('cantidadReferencia') or 0.0),
            "subcantidad": float(request.form.get('subcantidad') or 0.0),
            "precioReferencia": float(request.form.get('precioReferencia') or 0.0)
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
            "createdAt": item["createdAt"],
            "codigoImpuesto": request.form.get('codigoImpuesto', '').strip(),
            "tasaImpuestoAdicional": float(request.form.get('tasaImpuestoAdicional') or 0.0),
            "gradosAlcohol": float(request.form.get('gradosAlcohol') or 0.0),
            "cantidadReferencia": float(request.form.get('cantidadReferencia') or 0.0),
            "subcantidad": float(request.form.get('subcantidad') or 0.0),
            "precioReferencia": float(request.form.get('precioReferencia') or 0.0)
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
    
    q = request.args.get('q', '').strip()
    status = request.args.get('status', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    per_page = request.args.get('per_page', '10').strip()
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
                per_page_val = 10
        except ValueError:
            per_page_val = 10
            
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

@app.route('/quotations')
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
        income_type = request.form.get('incomeType', '01 - Ingresos por operaciones')
        
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
            invoice_dict["isQuotation"] = is_quotation
            invoice_dict["notes"] = request.form.get('notes', '')
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
                        invoice_dict["status"] = "Emitida"
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
                            "motivo": motivo
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

@app.route('/invoices/<invoice_id>/send-receipt', methods=['POST'])
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

    company_name    = company.get("companyName", "e-Factura")
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
    .info-item .value {{ font-size: 0.92rem; font-weight: 600; color: #0f172a; }}
    .amount-box {{ background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); border: 2px solid #16a34a; border-radius: 10px; padding: 20px 24px; text-align: center; margin: 24px 0; }}
    .amount-box .label {{ font-size: 0.78rem; color: #166534; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }}
    .amount-box .amount {{ font-size: 2.1rem; font-weight: 800; color: #15803d; }}
    .footer-note {{ font-size: 0.78rem; color: #94a3b8; text-align: center; border-top: 1px solid #e2e8f0; padding-top: 20px; margin-top: 24px; line-height: 1.6; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
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

@app.route('/invoices/<invoice_id>/notify-email', methods=['POST'])
def notify_invoice_email(invoice_id):
    """Notifica la factura electrónica por email usando la API de Alanube."""
    if 'user' not in session:
        return jsonify({"success": False, "message": "No autenticado."}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    data = request.get_json(silent=True) or {}
    recipient_email = (data.get("email") or "").strip()
    pdf_type = data.get("pdfType", "generic")

    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        return jsonify({"success": False, "message": "Factura no encontrada."}), 404

    xml_signature = invoice.get("xmlSignature")
    if not xml_signature:
        return jsonify({"success": False, "message": "Este comprobante no ha sido firmado digitalmente aún. Fírmelo antes de notificar por correo."}), 400

    company = DatabaseService.get_company_profile(owner_uid)

    res = AlanubeService.notify_by_email(
        company_profile=company,
        xml_signature=xml_signature,
        ecf_type=invoice.get("ecfType", "Factura de Consumo (E32)"),
        recipient_email=recipient_email if recipient_email else None,
        pdf_type=pdf_type,
        sandbox=sandbox
    )

    if res.get("success"):
        return jsonify({"success": True, "message": res.get("message")})
    else:
        return jsonify({"success": False, "message": res.get("message")}), 500

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
        res = EcfEmissionService.emit_electronic_comprobante(company, invoice, sandbox=sandbox)
        
        if res.get("success"):
            invoice["status"] = "Emitida"
            invoice["encf"] = res.get("encf", invoice.get("encf", ""))
            invoice["xmlSignature"] = res.get("xmlSignature", "")
            invoice["qrCodeURL"] = res.get("qrCodeURL", "")
            invoice["firebasePDFURL"] = res.get("pdfUrl", "")
            invoice["firebaseXMLURL"] = res.get("xmlUrl", "")
            # FALLBACK = emitido offline, aún pendiente de sincronizar con la DGII
            invoice["isSyncedWithDGII"] = (res.get("mode", "API") == "API")
            invoice["emisionMode"] = res.get("mode", "API")
            invoice["contingencyEmittedAt"] = datetime.utcnow().isoformat() if res.get("mode") == "FALLBACK" else None
            
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
                    "motivo": motivo
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

    xml_content = invoice.get('xmlContent') or ''
    
    # Si no tiene el contenido del XML guardado, lo construimos y firmamos dinámicamente 
    # utilizando el perfil de la compañía para que siempre se descargue un XML válido
    if not xml_content or not (xml_content.strip().startswith('<?xml') or xml_content.strip().startswith('<ECF') or xml_content.strip().startswith('<eCF')):
        try:
            from dgii_xml_builder import DgiiXmlBuilder
            from dgii_signer import DgiiSigner
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
        res = EcfEmissionService.emit_cancellation(company, canc_dict, sandbox=sandbox)
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
@app.route('/settings/company', methods=['GET', 'POST'])
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
            "certificatePassword": request.form.get('certificatePassword', ''),
            "colorMarca": existing_profile.get('colorMarca', '#10b981'),
            "gradientEnabled": existing_profile.get('gradientEnabled', True),
            "applyColorMarcaUI": existing_profile.get('applyColorMarcaUI', True),
            "applyColorMarcaReports": existing_profile.get('applyColorMarcaReports', True),
            "logoUrl": existing_profile.get('logoUrl', ''),
            "regimenFiscal": request.form.get('regimenFiscal', 'General'),
            "openaiApiKey": request.form.get('openaiApiKey', ''),
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
    
    # Obtener equipo
    team = DatabaseService.get_team_members(owner_uid)

    # Obtener sucursales
    branches = DatabaseService.get_branches(owner_uid, sandbox=session.get('is_sandbox_mode', True))

    onboarding_success = request.args.get('onboarding_success') == 'true'
    show_wizard = not profile.get('configured', False)
    return render_template('company_settings.html', active_page='settings', profile=profile, team=team, branches=branches, show_wizard=show_wizard, onboarding_success=onboarding_success)

@app.route('/settings/company/generate-api-key', methods=['POST'])
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


@app.route('/reports/dgii-tools', methods=['GET'])
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

@app.route('/reports/check-directory-ajax', methods=['POST'])
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

@app.route('/reports/check-dgii-status-ajax', methods=['POST'])
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
