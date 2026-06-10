from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.services.db_service import DatabaseService
from app.services.recurrence import RecurrenceService
from app.utils.decorators import check_permission
from datetime import datetime, timedelta
import uuid
import random

web_operations_bp = Blueprint('web_operations', __name__)

# =========================================================================
# GESTIÓN DE CONTRATOS Y FACTURACIÓN RECURRENTE
# =========================================================================

@web_operations_bp.route('/operations/contracts', methods=['GET', 'POST'])
def list_contracts():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageContracts'):
        return render_template('auth/restricted.html', feature_name="Contratos y Facturación Recurrente", required_permission="canManageContracts")
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    if request.method == 'POST':
        # Guardar o editar contrato
        contract_id = request.form.get('id') or str(uuid.uuid4())
        client_id = request.form.get('clientId')
        clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
        client = next((c for c in clients if c['id'] == client_id), None)
        
        if not client:
            flash("Cliente no válido.", "error")
            return redirect(url_for('web_operations.list_contracts'))
            
        contract_dict = {
            "contractNumber": request.form.get('contractNumber') or f"CON-{random.randint(1000, 9999)}",
            "clientId": client_id,
            "clientName": client.get("razonSocial", ""),
            "clientRNC": client.get("rnc", ""),
            "amount": float(request.form.get('amount', 0.0)),
            "recurrenceInterval": request.form.get('recurrenceInterval', 'mensual'),
            "status": request.form.get('status', 'Activo'),
            "startDate": request.form.get('startDate', datetime.utcnow().strftime("%Y-%m-%d")),
            "endDate": request.form.get('endDate', ""),
            "nextBillingDate": request.form.get('nextBillingDate', datetime.utcnow().strftime("%Y-%m-%d")),
            "notes": request.form.get('notes', "")
        }
        
        DatabaseService.save_contract(owner_uid, contract_id, contract_dict, sandbox=sandbox)
        flash("Contrato guardado exitosamente.", "success")
        return redirect(url_for('web_operations.list_contracts'))

    contracts = DatabaseService.get_contracts(owner_uid, sandbox=sandbox)
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
    
    # Calcular estadísticas del panel de contratos
    total_active = sum(1 for c in contracts if c.get('status') == 'Activo')
    monthly_estimate = sum(c.get('amount', 0.0) for c in contracts if c.get('status') == 'Activo')
    total_contracts = len(contracts)
    
    return render_template(
        'operations/contracts.html',
        active_page='contracts',
        contracts=contracts,
        clients=clients,
        total_active=total_active,
        monthly_estimate=monthly_estimate,
        total_contracts=total_contracts
    )

@web_operations_bp.route('/operations/contracts/<contract_id>/toggle', methods=['POST'])
def toggle_contract(contract_id):
    if 'user' not in session: return jsonify({"success": False, "error": "No autorizado"}), 401
    if not check_permission('canManageContracts'): return jsonify({"success": False, "error": "Sin permisos"}), 403
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    contracts = DatabaseService.get_contracts(owner_uid, sandbox=sandbox)
    contract = next((c for c in contracts if c['id'] == contract_id), None)
    
    if contract:
        new_status = 'Inactivo' if contract.get('status') == 'Activo' else 'Activo'
        contract['status'] = new_status
        DatabaseService.save_contract(owner_uid, contract_id, contract, sandbox=sandbox)
        return jsonify({"success": True, "new_status": new_status})
        
    return jsonify({"success": False, "error": "Contrato no encontrado"}), 404

@web_operations_bp.route('/operations/contracts/<contract_id>/delete', methods=['POST'])
def delete_contract_route(contract_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageContracts'): return jsonify({"success": False, "error": "Sin permisos"}), 403
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    DatabaseService.delete_contract(owner_uid, contract_id, sandbox=sandbox)
    flash("Contrato eliminado correctamente.", "success")
    return redirect(url_for('web_operations.list_contracts'))

@web_operations_bp.route('/operations/contracts/<contract_id>/trigger', methods=['POST'])
def trigger_contract_billing(contract_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageContracts'):
        return render_template('auth/restricted.html', feature_name="Contratos y Facturación Recurrente", required_permission="canManageContracts")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    contracts = DatabaseService.get_contracts(owner_uid, sandbox=sandbox)
    contract = next((c for c in contracts if c['id'] == contract_id), None)
    
    if not contract:
        flash("Contrato no encontrado.", "error")
        return redirect(url_for('web_operations.list_contracts'))
        
    # Crear factura e-CF
    random_num = f"{random.randint(1, 999999):06d}"
    invoice_number = f"FAC-{random_num}"
    invoice_id = str(uuid.uuid4())
    
    # Calcular ITBIS (asumiendo 18% incluido o más)
    subtotal = contract['amount'] / 1.18
    itbis_amount = contract['amount'] - subtotal
    
    item_id = str(uuid.uuid4())
    items = [{
        "id": item_id,
        "code": "SERV-REC",
        "type": "Servicio",
        "name": f"Servicio Contratado ({contract.get('contractNumber')})",
        "price": subtotal,
        "quantity": 1,
        "itbisRate": 0.18,
        "discountRate": 0.0,
        "subtotal": subtotal,
        "itbis_amount": itbis_amount,
        "total": contract['amount']
    }]
    
    invoice_dict = {
        "id": invoice_id,
        "invoiceNumber": invoice_number,
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "dueDate": (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d"),
        "clientId": contract['clientId'],
        "clientName": contract['clientName'],
        "clientRNC": contract['clientRNC'],
        "status": "Emitida",
        "ecfType": "Factura de Consumo (E32)",
        "encf": "E32PENDIENTE",
        "xmlSignature": "",
        "qrCodeURL": "",
        "isSyncedWithDGII": False,
        "creditedAmount": 0.0,
        "retainedISR": 0.0,
        "retainedITBIS": 0.0,
        "netPayable": contract['amount'],
        "subtotal": subtotal,
        "totalITBIS": itbis_amount,
        "total": contract['amount'],
        "isQuotation": False,
        "isConvertedToInvoice": False,
        "notes": f"Generado automáticamente desde Contrato {contract.get('contractNumber')}",
        "comentario": contract.get('notes', ''),
        "isRecurring": False,
        "firebasePDFURL": "",
        "firebaseXMLURL": "",
        "currency": "DOP",
        "paymentType": "Contado",
        "paymentMethod": "Efectivo",
        "incomeType": "01 - Ingresos por operaciones",
        "exchangeRate": 1.0,
        "registeredBy": session['user']['email'],
        "items": items
    }
    
    # Guardar factura
    DatabaseService.save_invoice(owner_uid, invoice_id, invoice_dict, sandbox=sandbox)
    
    # Actualizar fecha de próxima ocurrencia en el contrato
    next_date = RecurrenceService.calculate_next_date(contract.get("nextBillingDate"), contract.get("recurrenceInterval"))
    contract["nextBillingDate"] = next_date
    DatabaseService.save_contract(owner_uid, contract_id, contract, sandbox=sandbox)
    
    flash(f"¡Factura {invoice_number} por RD$ {contract['amount']:,.2f} generada y programada con éxito!", "success")
    return redirect(url_for('web_operations.list_contracts'))

# =========================================================================
# CONTROL DE COMISIONES Y RENDIMIENTO (GAMIFICACIÓN)
# =========================================================================

@web_operations_bp.route('/operations/commissions', methods=['GET', 'POST'])
def list_commissions():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageCommissions'):
        return render_template('auth/restricted.html', feature_name="Comisiones y Metas", required_permission="canManageCommissions")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    if request.method == 'POST':
        if 'percentage' in request.form:
            # Configuración de comisiones
            settings_dict = {
                "percentage": float(request.form.get('percentage', 5.0)),
                "payOn": request.form.get('payOn', 'cobrada')
            }
            DatabaseService.save_commission_settings(owner_uid, settings_dict)
            flash("Configuración de comisiones actualizada.", "success")
        elif 'monthlyGoal' in request.form:
            # Metas mensuales de ventas
            goals_dict = {
                "monthlyGoal": float(request.form.get('monthlyGoal', 500000.0))
            }
            DatabaseService.save_sales_goals(owner_uid, goals_dict)
            flash("Metas de venta de la empresa actualizadas.", "success")
        return redirect(url_for('web_operations.list_commissions'))
        
    # Cargar datos
    settings = DatabaseService.get_commission_settings(owner_uid)
    goals = DatabaseService.get_sales_goals(owner_uid)
    team = DatabaseService.get_team_members(owner_uid)
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    
    # Filtrar facturas reales
    real_invoices = [inv for inv in invoices if not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador']]
    
    # Calcular ventas totales y comisiones por vendedor
    sellers_data = {}
    
    # Inicializar con los miembros del equipo
    for member in team:
        sellers_data[member['email']] = {
            "name": member['name'],
            "email": member['email'],
            "total_invoiced": 0.0,
            "total_collected": 0.0,
            "commission_earned": 0.0,
            "invoice_count": 0
        }
    # Añadir al propietario también por si emite facturas
    owner_email = session['user']['email']
    if owner_email not in sellers_data:
        sellers_data[owner_email] = {
            "name": session['user'].get('name', 'Propietario'),
            "email": owner_email,
            "total_invoiced": 0.0,
            "total_collected": 0.0,
            "commission_earned": 0.0,
            "invoice_count": 0
        }
        
    for inv in real_invoices:
        reg_by = inv.get('registeredBy') or owner_email
        if reg_by not in sellers_data:
            sellers_data[reg_by] = {
                "name": reg_by.split('@')[0],
                "email": reg_by,
                "total_invoiced": 0.0,
                "total_collected": 0.0,
                "commission_earned": 0.0,
                "invoice_count": 0
            }
            
        inv_total = inv.get('total', 0.0)
        sellers_data[reg_by]["total_invoiced"] += inv_total
        sellers_data[reg_by]["invoice_count"] += 1
        
        # Calcular recaudado (cobrado)
        if inv.get('status') == 'Saldada':
            sellers_data[reg_by]["total_collected"] += inv_total
        else:
            # Obtener abonos
            try:
                abonos = DatabaseService.get_invoice_abonos(owner_uid, inv['id'], sandbox=sandbox)
                collected = sum(ab.get('amount', 0.0) for ab in abonos)
                sellers_data[reg_by]["total_collected"] += collected
            except Exception:
                pass

    # Calcular comisión final
    pct = settings.get('percentage', 5.0) / 100.0
    pay_on = settings.get('payOn', 'cobrada')
    
    total_sales_month = 0.0
    
    for email, data in sellers_data.items():
        if pay_on == 'cobrada':
            data["commission_earned"] = data["total_collected"] * pct
        else:
            data["commission_earned"] = data["total_invoiced"] * pct
        total_sales_month += data["total_invoiced"]
            
    # Ordenar ranking para Gamificación
    ranking = sorted(sellers_data.values(), key=lambda x: x["total_invoiced"], reverse=True)
    
    # Progreso de meta mensual
    goal_amount = goals.get('monthlyGoal', 500000.0)
    goal_pct = min(100.0, (total_sales_month / goal_amount) * 100.0) if goal_amount > 0 else 0.0
    
    return render_template(
        'operations/commissions.html',
        active_page='commissions',
        settings=settings,
        goals=goals,
        ranking=ranking,
        total_sales_month=total_sales_month,
        goal_pct=goal_pct,
        goal_amount=goal_amount
    )

# =========================================================================
# GESTIÓN DOCUMENTAL DE CLIENTES (RUTAS AJAX)
# =========================================================================

@web_operations_bp.route('/clients/<client_id>/documents/upload', methods=['POST'])
def upload_client_document_route(client_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canClients'): return jsonify({"success": False, "error": "Sin permisos"}), 403
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    file = request.files.get('file')
    doc_type = request.form.get('documentType', 'Contrato Legal')
    notes = request.form.get('notes', '')
    
    if not file or not file.filename:
        flash("Por favor, selecciona un archivo válido.", "error")
        return redirect(url_for('web_clients.client_detail', client_id=client_id))
        
    try:
        file_data = file.read()
        mime_type = file.mimetype or "application/octet-stream"
        filename = f"doc_{client_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
        destination_path = f"users/{owner_uid}/crm_documents/{filename}"
        
        # Guardar en Firebase Storage
        url = DatabaseService.upload_file_to_storage(
            file_data=file_data,
            destination_path=destination_path,
            mime_type=mime_type
        )
        
        # Registrar en la base de datos
        doc_id = str(uuid.uuid4())
        doc_dict = {
            "documentType": doc_type,
            "name": file.filename,
            "url": url,
            "uploadedBy": session['user']['email'],
            "createdAt": datetime.utcnow().isoformat(),
            "notes": notes
        }
        
        DatabaseService.save_client_document(owner_uid, client_id, doc_id, doc_dict, sandbox=sandbox)
        flash("Documento cargado de forma segura y adjuntado al historial del cliente.", "success")
        
    except Exception as e:
        flash(f"Error al subir el archivo: {str(e)}", "error")
        
    return redirect(url_for('web_clients.client_detail', client_id=client_id))

@web_operations_bp.route('/clients/<client_id>/documents/<doc_id>/delete', methods=['POST'])
def delete_client_document_route(client_id, doc_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canClients'): return jsonify({"success": False, "error": "Sin permisos"}), 403
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    DatabaseService.delete_client_document(owner_uid, client_id, doc_id, sandbox=sandbox)
    flash("Documento eliminado del archivo centralizado del cliente.", "success")
    return redirect(url_for('web_clients.client_detail', client_id=client_id))
