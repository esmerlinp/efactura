# app/web/clients.py
import uuid
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.services.db_service import DatabaseService
from app.services.dgii import DGIIService
from app.utils.decorators import check_permission

web_clients_bp = Blueprint('web_clients', __name__)

@web_clients_bp.route('/clients')
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
        client_sales = [inv for inv in invoices if inv['clientId'] == c_id and not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador']]
        client['total_invoiced'] = sum(inv['total'] for inv in client_sales)
        client['total_cxc'] = sum(inv['netPayable'] for inv in client_sales if inv['status'] in ['Emitida', 'Vencida'])

    # Aplicar filtros
    q = request.args.get('q', '').strip()
    q_lower = q.lower()
    stage = request.args.get('stage', '').strip()
    
    if q_lower:
        clients = [c for c in clients if q_lower in c.get('razonSocial', '').lower() or q_lower in c.get('rnc', '').lower() or q_lower in c.get('telefono', '').lower()]
        
    if stage:
        clients = [c for c in clients if c.get('pipelineStage') == stage]

    # Paginación
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    total_items = len(clients)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    
    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages
        
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_clients = clients[start_idx:end_idx]

    return render_template(
        'clients/list.html', 
        active_page='clients', 
        clients=clients, 
        paginated_clients=paginated_clients,
        q=q, 
        stage=stage,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_items=total_items
    )

@web_clients_bp.route('/clients/new', methods=['GET', 'POST'])
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
            "nextContactDate": request.form.get('nextContactDate', ''),
            "disableAutoReminders": request.form.get('disableAutoReminders') == 'on' or request.form.get('disableAutoReminders') == 'true'
        }
        
        DatabaseService.save_client(owner_uid, client_id, client_dict, sandbox=sandbox)
        
        from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_CLIENTES
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_CREATE,
            module=MODULE_CLIENTES,
            entity_id=client_id,
            entity_label=f"Cliente registrado: {client_dict['razonSocial']} (RNC: {client_dict['rnc']})",
            user_session=session.get('user', {}),
            after=client_dict,
            sandbox=sandbox
        )
        flash('Cliente registrado exitosamente en el directorio CRM.', 'success')
        return redirect(url_for('list_clients'))
        
    return render_template('clients/form.html', active_page='clients', client=None)

@web_clients_bp.route('/clients/ajax_create', methods=['POST'])
def ajax_create_client():
    """Ruta AJAX para crear un cliente desde la pantalla de facturación sin recargar la página."""
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autenticado."}), 401
    if not (check_permission('canClients') or check_permission('canManagePOS')):
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
    
    from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_CLIENTES
    AuditService.log_from_request(
        owner_uid=owner_uid,
        action=ACTION_CREATE,
        module=MODULE_CLIENTES,
        entity_id=client_id,
        entity_label=f"Cliente registrado (Rápido): {client_dict['razonSocial']} (RNC: {client_dict['rnc']})",
        user_session=session.get('user', {}),
        after=client_dict,
        sandbox=sandbox
    )
    
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

@web_clients_bp.route('/clients/<client_id>/edit', methods=['GET', 'POST'])
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
        before_client = client.copy()
        client_dict = {
            "rnc": request.form['rnc'],
            "razonSocial": request.form['razonSocial'],
            "email": request.form.get('email', ''),
            "telefono": request.form.get('telefono', ''),
            "direccion": request.form.get('direccion', ''),
            "crmNotes": request.form.get('crmNotes', ''),
            "nextContactDate": request.form.get('nextContactDate', ''),
            "createdAt": client["createdAt"],
            "disableAutoReminders": request.form.get('disableAutoReminders') == 'on' or request.form.get('disableAutoReminders') == 'true'
        }
        DatabaseService.save_client(owner_uid, client_id, client_dict, sandbox=sandbox)
        
        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_CLIENTES
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_UPDATE,
            module=MODULE_CLIENTES,
            entity_id=client_id,
            entity_label=f"Cliente modificado: {client_dict['razonSocial']} (RNC: {client_dict['rnc']})",
            user_session=session.get('user', {}),
            before=before_client,
            after=client_dict,
            sandbox=sandbox
        )
        flash('Ficha CRM del cliente actualizada exitosamente.', 'success')
        return redirect(url_for('list_clients'))
        
    return render_template('clients/form.html', active_page='clients', client=client)

@web_clients_bp.route('/clients/<client_id>/delete', methods=['POST'])
def delete_client_route(client_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Eliminar Cliente", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    before_client = {}
    try:
        clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
        before_client = next((c for c in clients if c['id'] == client_id), {})
    except Exception:
        pass
        
    DatabaseService.delete_client(owner_uid, client_id, sandbox=sandbox)
    
    from app.services.audit_service import AuditService, ACTION_DELETE, MODULE_CLIENTES
    AuditService.log_from_request(
        owner_uid=owner_uid,
        action=ACTION_DELETE,
        module=MODULE_CLIENTES,
        entity_id=client_id,
        entity_label=f"Cliente eliminado: {before_client.get('razonSocial', 'N/A')} (RNC: {before_client.get('rnc', 'N/A')})",
        user_session=session.get('user', {}),
        before=before_client,
        sandbox=sandbox
    )
    flash('Cliente eliminado del directorio.', 'success')
    return redirect(url_for('list_clients'))

@web_clients_bp.route('/clients/<client_id>/update_pipeline', methods=['POST'])
def update_client_pipeline(client_id):
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    if not check_permission('canClients'):
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.json
    new_stage = data.get('pipelineStage')
    
    DatabaseService.update_client_pipeline(owner_uid, client_id, new_stage, sandbox=sandbox)
    return jsonify({'success': True})

@web_clients_bp.route('/clients/<client_id>/toggle_reminders', methods=['POST'])
def toggle_client_reminders(client_id):
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado."}), 401
    if not check_permission('canClients'):
        return jsonify({"success": False, "error": "Sin permisos."}), 403
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.json or {}
    disable_reminders = data.get('disableAutoReminders') is True
    
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
    client = next((c for c in clients if c['id'] == client_id), None)
    if not client:
        return jsonify({"success": False, "error": "Cliente no encontrado."}), 404
        
    client['disableAutoReminders'] = disable_reminders
    DatabaseService.save_client(owner_uid, client_id, client, sandbox=sandbox)
    return jsonify({"success": True, "disableAutoReminders": disable_reminders})

@web_clients_bp.route('/clients/<client_id>')
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
    
    # Calcular sumas financieras específicas (excluyendo cotizaciones, anuladas y borradores)
    client['total_invoiced'] = sum(inv['total'] for inv in client_invoices if inv.get('status') not in ['Anulada', 'Borrador'])
    client['total_cxc'] = sum(inv['netPayable'] for inv in client_invoices if inv['status'] in ['Emitida', 'Vencida'])
    
    # Obtener interacciones
    interactions = DatabaseService.get_client_interactions(owner_uid, client_id, sandbox=sandbox)
    documents = DatabaseService.get_client_documents(owner_uid, client_id, sandbox=sandbox)
    
    return render_template(
        'clients/detail.html',
        active_page='clients',
        client=client,
        invoices=client_invoices,
        quotations=client_quotations,
        interactions=interactions,
        documents=documents
    )

@web_clients_bp.route('/clients/<client_id>/interactions/new', methods=['POST'])
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
    
    from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_CRM
    AuditService.log_from_request(
        owner_uid=owner_uid,
        action=ACTION_CREATE,
        module=MODULE_CRM,
        entity_id=interaction_id,
        entity_label=f"Seguimiento CRM registrado para Cliente ID: {client_id} (Tipo: {interaction_type})",
        user_session=session.get('user', {}),
        after=interaction_dict,
        sandbox=sandbox
    )
    
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

@web_clients_bp.route('/clients/<client_id>/interactions/<interaction_id>/delete', methods=['POST'])
def delete_client_interaction_route(client_id, interaction_id):
    if 'user' not in session: return redirect(url_for('login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Eliminar Seguimiento", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    DatabaseService.delete_client_interaction(owner_uid, client_id, interaction_id, sandbox=sandbox)
    
    from app.services.audit_service import AuditService, ACTION_DELETE, MODULE_CRM
    AuditService.log_from_request(
        owner_uid=owner_uid,
        action=ACTION_DELETE,
        module=MODULE_CRM,
        entity_id=interaction_id,
        entity_label=f"Seguimiento CRM eliminado del Cliente ID: {client_id}",
        user_session=session.get('user', {}),
        sandbox=sandbox
    )
    flash('Interacción eliminada correctamente de la línea de tiempo.', 'success')
    return redirect(url_for('client_detail', client_id=client_id))

@web_clients_bp.route('/clients/<client_id>/interactions/<interaction_id>/complete', methods=['POST'])
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

@web_clients_bp.route('/clients/<client_id>/interactions/quick-note', methods=['POST'])
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
        return redirect(url_for('web_dashboard.dashboard'))
        
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
    
    if complete_task:
        clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
        client = next((c for c in clients if c['id'] == client_id), None)
        if client:
            client['nextContactDate'] = None
            client['crmNotes'] = content[:100]
            DatabaseService.save_client(owner_uid, client_id, client, sandbox=sandbox)
            
    flash('Nota rápida registrada en el historial del cliente.', 'success')
    return redirect(url_for('web_dashboard.dashboard'))

@web_clients_bp.route('/api/rnc-lookup')
def rnc_lookup():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    rnc = request.args.get('rnc', '')
    res = DGIIService.validate_and_fetch_rnc(rnc)
    return jsonify(res)
