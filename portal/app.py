import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from functools import wraps
from config import Config
from database_service import DatabaseService
from azul_service import AzulService

app = Flask(__name__)
app.config.from_object(Config)

# --- Authentication Decorator ---
def portal_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# --- Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == app.config['PORTAL_ADMIN_USER'] and password == app.config['PORTAL_ADMIN_PASSWORD']:
            session['admin_logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            flash('Credenciales incorrectas.', 'error')
    return render_template('auth/login.html')

@app.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('login'))

@app.route('/')
@app.route('/dashboard')
@portal_required
def dashboard():
    companies = DatabaseService.get_all_companies()
    active_count = sum(1 for c in companies if c.get('status', 'Activo') == 'Activo')
    suspended_count = sum(1 for c in companies if c.get('status') == 'Suspendido')
    
    stats = {
        'total_companies': len(companies),
        'active_companies': active_count,
        'suspended_companies': suspended_count
    }
    return render_template('admin/dashboard.html', stats=stats, active_page='dashboard')

@app.route('/clientes')
@portal_required
def clientes():
    companies = DatabaseService.get_all_companies()
    return render_template('admin/clientes.html', companies=companies, active_page='clientes')

@app.route('/clientes/<company_id>', methods=['GET', 'POST'])
@portal_required
def client_detail(company_id):
    company = DatabaseService.get_company(company_id)
    if not company:
        flash('Empresa no encontrada.', 'error')
        return redirect(url_for('clientes'))
        
    plans = DatabaseService.get_all_plans()
        
    if request.method == 'POST':
        status = request.form.get('status')
        plan_id = request.form.get('planId')
        document_limit = request.form.get('documentLimit')
        storage_limit = request.form.get('storageLimitMB')
        monthly_payment = request.form.get('monthlyPayment')
        additional_doc_cost = request.form.get('additionalDocumentCost')
        billing_day = request.form.get('billingDay')
        
        update_data = {
            'status': status,
            'planId': plan_id,
            'documentLimit': int(document_limit) if document_limit else '',
            'storageLimitMB': int(storage_limit) if storage_limit else '',
            'monthlyPayment': float(monthly_payment) if monthly_payment else 0.0,
            'additionalDocumentCost': float(additional_doc_cost) if additional_doc_cost else 0.0,
            'billingDay': int(billing_day) if billing_day else 1
        }
        DatabaseService.update_company(company_id, update_data)
        flash('Datos de la empresa actualizados.', 'success')
        return redirect(url_for('client_detail', company_id=company_id))
        
    payments = DatabaseService.get_payments(company_id)
    return render_template('admin/client_detail.html', company=company, plans=plans, payments=payments, active_page='clientes')

@app.route('/clientes/<company_id>/pagos', methods=['POST'])
@portal_required
def record_payment(company_id):
    amount = float(request.form.get('amount', 0))
    method = request.form.get('method')
    reference = request.form.get('reference')
    
    if amount <= 0:
        flash('El monto del pago debe ser mayor que cero.', 'error')
    else:
        success = DatabaseService.record_payment(company_id, amount, method, reference)
        if success:
            flash('Pago registrado exitosamente. Cuenta activada.', 'success')
        else:
            flash('Error al registrar el pago.', 'error')
            
    return redirect(url_for('client_detail', company_id=company_id))

@app.route('/clientes/<company_id>/pagos/azul', methods=['POST'])
@portal_required
def client_azul_payment(company_id):
    company = DatabaseService.get_company(company_id)
    if not company:
        flash('Empresa no encontrada.', 'error')
        return redirect(url_for('clientes'))
        
    amount = float(request.form.get('amount', 0) or company.get('monthlyPayment', 0))
    if amount <= 0:
        flash('El monto debe ser mayor a cero.', 'error')
        return redirect(url_for('client_detail', company_id=company_id))
        
    return_url = url_for('azul_callback', _external=True)
    payment_data = AzulService.prepare_payment_request(company_id, amount, return_url)
    return render_template('admin/azul_redirect.html', payment=payment_data)

@app.route('/pagos/azul/callback', methods=['GET', 'POST'])
def azul_callback():
    data = {}
    data.update(request.args.to_dict())
    if request.form:
        data.update(request.form.to_dict())
        
    if not data:
        return redirect(url_for('login'))
        
    result = AzulService.verify_payment_response(data)
    company_id = result.get('company_id')
    
    if result.get('success') and company_id:
        DatabaseService.record_payment(
            company_id, 
            result.get('amount'), 
            'Azul', 
            f"Orden: {result.get('order')} - Ref: {result.get('reference')}"
        )
        company = DatabaseService.get_company(company_id)
        flash('Pago online procesado exitosamente vía Azul. Cuenta activada.', 'success')
        return render_template('admin/payment_success.html', result=result, company=company)
    else:
        error_msg = result.get('error') or "El pago no pudo ser procesado."
        flash(f"Error procesando pago vía Azul: {error_msg}", 'error')
        return render_template('admin/payment_failed.html', error=error_msg)

@app.route('/planes')
@portal_required
def planes():
    plans = DatabaseService.get_all_plans()
    return render_template('admin/planes.html', plans=plans, active_page='planes')

@app.route('/planes/new', methods=['GET', 'POST'])
@portal_required
def new_plan():
    if request.method == 'POST':
        plan_id = str(uuid.uuid4())
        plan_data = {
            'name': request.form.get('name'),
            'monthlyPrice': float(request.form.get('monthlyPrice', 0)),
            'documentLimit': int(request.form.get('documentLimit', 0)),
            'additionalDocumentCost': float(request.form.get('additionalDocumentCost', 0)),
            'storageLimitMB': int(request.form.get('storageLimitMB', 0))
        }
        DatabaseService.save_plan(plan_id, plan_data)
        flash('Plan creado exitosamente.', 'success')
        return redirect(url_for('planes'))
    return render_template('admin/plan_form.html', plan=None, active_page='planes')

@app.route('/planes/<plan_id>/edit', methods=['GET', 'POST'])
@portal_required
def edit_plan(plan_id):
    plans = DatabaseService.get_all_plans()
    plan = next((p for p in plans if p['id'] == plan_id), None)
    if not plan:
        flash('Plan no encontrado.', 'error')
        return redirect(url_for('planes'))
        
    if request.method == 'POST':
        plan_data = {
            'name': request.form.get('name'),
            'monthlyPrice': float(request.form.get('monthlyPrice', 0)),
            'documentLimit': int(request.form.get('documentLimit', 0)),
            'additionalDocumentCost': float(request.form.get('additionalDocumentCost', 0)),
            'storageLimitMB': int(request.form.get('storageLimitMB', 0))
        }
        DatabaseService.save_plan(plan_id, plan_data)
        flash('Plan actualizado exitosamente.', 'success')
        return redirect(url_for('planes'))
    return render_template('admin/plan_form.html', plan=plan, active_page='planes')

@app.route('/planes/<plan_id>/delete', methods=['POST'])
@portal_required
def delete_plan(plan_id):
    DatabaseService.delete_plan(plan_id)
    flash('Plan eliminado.', 'success')
    return redirect(url_for('planes'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True)
