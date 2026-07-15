# app/web/clients.py
import uuid
import html
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, g
from app.services.db_service import DatabaseService
from app.services.mailer import Mailer
from app.services.dgii import DGIIService
from app.services.ai_service import AIService
from app.utils.decorators import check_permission
from app.brand import get_product_name

web_clients_bp = Blueprint('web_clients', __name__)

@web_clients_bp.route('/clients')
def list_clients():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="CRM Clientes", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    
    # Integrar sumas por cliente
    for client in clients:
        c_id = client['id']
        client_sales = [inv for inv in invoices if inv['clientId'] == c_id and not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador']]
        client['total_invoiced'] = sum(inv['total'] for inv in client_sales)
        client['total_cxc'] = sum(inv['netPayable'] for inv in client_sales if inv['status'] in ['Emitida', 'Vencida', 'Revisión de Pago'])

    # Aplicar filtros
    q = request.args.get('q', '').strip()
    q_lower = q.lower()
    
    stage = request.args.get('stage')
    # Por defecto, mostrar 'Cliente Activo' si no se provee filtro
    if stage is None:
        stage = 'Cliente Activo'
    else:
        stage = stage.strip()
    
    if q_lower:
        clients = [c for c in clients if q_lower in c.get('razonSocial', '').lower() or q_lower in c.get('rnc', '').lower() or q_lower in c.get('telefono', '').lower()]
        
    if stage and stage != 'Todos':
        clients = [c for c in clients if c.get('pipelineStage') == stage]

    # Exportar a CSV si se solicita
    if request.args.get('export') == 'csv':
        import csv
        import io
        from flask import send_file
        from datetime import datetime, timezone
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["RNC / Cédula", "Razón Social", "Email", "Teléfono", "Dirección", "Etapa Pipeline", "Total Facturado (RD$)", "Pendiente CxC (RD$)"])
        for c in clients:
            writer.writerow([
                c.get("rnc", ""),
                c.get("razonSocial", ""),
                c.get("email", ""),
                c.get("telefono", ""),
                c.get("direccion", ""),
                c.get("pipelineStage", "Prospecto"),
                f"{c.get('total_invoiced', 0.0):.2f}",
                f"{c.get('total_cxc', 0.0):.2f}"
            ])
        dest = io.BytesIO()
        dest.write(b'\xef\xbb\xbf')  # UTF-8 BOM
        dest.write(output.getvalue().encode('utf-8'))
        dest.seek(0)
        filename = f"clientes_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(
            dest,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )

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
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Nuevo Cliente", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    if request.method == 'POST':
        client_id = str(uuid.uuid4())
        image_url = ""
        image_file = request.files.get('image')
        if image_file and image_file.filename:
            try:
                file_data = image_file.read()
                mime_type = image_file.mimetype or "image/png"
                filename = f"client_{client_id}_{str(uuid.uuid4())[:8]}_{image_file.filename}"
                destination_path = f"users/{owner_uid}/clients/{filename}"
                image_url = DatabaseService.upload_file_to_storage(
                    file_data=file_data,
                    destination_path=destination_path,
                    mime_type=mime_type
                )
            except Exception as e:
                flash(f"Advertencia: No se pudo subir la imagen del cliente: {html.escape(str(e))}", 'warning')

        import random
        access_pin = request.form.get('accessPin', '').strip()
        if not access_pin or len(access_pin) != 6 or not access_pin.isdigit():
            access_pin = "".join([str(random.randint(0, 9)) for _ in range(6)])

        client_dict = {
            "rnc": request.form['rnc'],
            "razonSocial": request.form['razonSocial'],
            "email": request.form.get('email', ''),
            "telefono": request.form.get('telefono', ''),
            "direccion": request.form.get('direccion', ''),
            "crmNotes": request.form.get('crmNotes', ''),
            "nextContactDate": request.form.get('nextContactDate', ''),
            "pipelineStage": request.form.get('pipelineStage', 'Cliente Activo'),
            "disableAutoReminders": request.form.get('disableAutoReminders') == 'on' or request.form.get('disableAutoReminders') == 'true',
            "responsibleId": request.form.get('responsibleId', ''),
            "imageUrl": image_url,
            "accessPin": access_pin,
            "priceListId": request.form.get('priceListId', ''),
            "projectId": request.form.get('projectId') or None,
            "customer_category": request.form.get('customer_category', 'NORMAL')
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
        return redirect(url_for('web_clients.list_clients'))
        
    collaborators = DatabaseService.get_team_members(owner_uid) or []
    price_lists = DatabaseService.get_price_lists(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    projects = DatabaseService.get_projects(owner_uid, branch_id=g.get('branch_id'), sandbox=sandbox) if g.get('branch_id') else DatabaseService.get_projects(owner_uid, sandbox=sandbox)
    return render_template('clients/form.html', active_page='clients', client=None, collaborators=collaborators, price_lists=price_lists, projects=projects)

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
    
    import random
    access_pin = "".join([str(random.randint(0, 9)) for _ in range(6)])
    
    client_id = str(uuid.uuid4())
    client_dict = {
        "rnc": rnc,
        "razonSocial": razon_social,
        "email": (data.get('email') or '').strip(),
        "telefono": (data.get('telefono') or '').strip(),
        "direccion": (data.get('direccion') or '').strip(),
        "crmNotes": "Registrado desde formulario de facturación",
        "nextContactDate": "",
        "pipelineStage": "Cliente Activo",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "accessPin": access_pin,
        "projectId": (data.get('projectId') or '').strip() or None,
        "customer_category": (data.get('customer_category') or 'NORMAL').strip()
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
            "projectId": client_dict.get("projectId") or "",
            "customer_category": client_dict.get("customer_category", "NORMAL")
        }
    })

@web_clients_bp.route('/clients/<client_id>/edit', methods=['GET', 'POST'])
def edit_client(client_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Editar Cliente", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    client = next((c for c in clients if c['id'] == client_id), None)
    
    if not client:
        flash('Cliente no encontrado.', 'error')
        return redirect(url_for('web_clients.list_clients'))
        
    if request.method == 'POST':
        before_client = client.copy()
        image_url = client.get('imageUrl', '')
        image_file = request.files.get('image')
        if image_file and image_file.filename:
            try:
                file_data = image_file.read()
                mime_type = image_file.mimetype or "image/png"
                filename = f"client_{client_id}_{str(uuid.uuid4())[:8]}_{image_file.filename}"
                destination_path = f"users/{owner_uid}/clients/{filename}"
                image_url = DatabaseService.upload_file_to_storage(
                    file_data=file_data,
                    destination_path=destination_path,
                    mime_type=mime_type
                )
            except Exception as e:
                flash(f"Advertencia: No se pudo subir la imagen del cliente: {html.escape(str(e))}", 'warning')

        import random
        access_pin = request.form.get('accessPin', '').strip()
        if not access_pin or len(access_pin) != 6 or not access_pin.isdigit():
            access_pin = client.get('accessPin', '')
            if not access_pin:
                access_pin = "".join([str(random.randint(0, 9)) for _ in range(6)])

        client_dict = {
            "rnc": request.form['rnc'],
            "razonSocial": request.form['razonSocial'],
            "email": request.form.get('email', ''),
            "telefono": request.form.get('telefono', ''),
            "direccion": request.form.get('direccion', ''),
            "crmNotes": request.form.get('crmNotes', ''),
            "nextContactDate": request.form.get('nextContactDate', ''),
            "createdAt": client["createdAt"],
            "pipelineStage": request.form.get('pipelineStage', client.get("pipelineStage", "Cliente Activo")),
            "disableAutoReminders": request.form.get('disableAutoReminders') == 'on' or request.form.get('disableAutoReminders') == 'true',
            "responsibleId": request.form.get('responsibleId', ''),
            "imageUrl": image_url,
            "accessPin": access_pin,
            "priceListId": request.form.get('priceListId', ''),
            "projectId": request.form.get('projectId') or None,
            "customer_category": request.form.get('customer_category', client.get('customer_category', 'NORMAL'))
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
        return redirect(url_for('web_clients.list_clients'))
        
    collaborators = DatabaseService.get_team_members(owner_uid) or []
    price_lists = DatabaseService.get_price_lists(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    projects = DatabaseService.get_projects(owner_uid, branch_id=g.get('branch_id'), sandbox=sandbox) if g.get('branch_id') else DatabaseService.get_projects(owner_uid, sandbox=sandbox)
    return render_template('clients/form.html', active_page='clients', client=client, collaborators=collaborators, price_lists=price_lists, projects=projects)

@web_clients_bp.route('/clients/<client_id>/delete', methods=['POST'])
def delete_client_route(client_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Eliminar Cliente", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    before_client = {}
    try:
        clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
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
    return redirect(url_for('web_clients.list_clients'))

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
    
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    client = next((c for c in clients if c['id'] == client_id), None)
    if not client:
        return jsonify({"success": False, "error": "Cliente no encontrado."}), 404
        
    client['disableAutoReminders'] = disable_reminders
    DatabaseService.save_client(owner_uid, client_id, client, sandbox=sandbox)
    return jsonify({"success": True, "disableAutoReminders": disable_reminders})

@web_clients_bp.route('/clients/<client_id>/send_portal_credentials', methods=['POST'])
def send_portal_credentials(client_id):
    """Envía las credenciales de acceso del portal al cliente por email."""
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado."}), 401
    if not check_permission('canClients'):
        return jsonify({"success": False, "error": "Sin permisos."}), 403

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    data = request.json or {}
    recipient_email = data.get('email', '').strip()

    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    client = next((c for c in clients if c['id'] == client_id), None)
    if not client:
        return jsonify({"success": False, "error": "Cliente no encontrado."}), 404

    if not recipient_email:
        recipient_email = client.get('email', '')
    if not recipient_email:
        return jsonify({"success": False, "error": "Este cliente no tiene un correo registrado."}), 400

    access_pin = client.get('accessPin', '')
    if not access_pin:
        return jsonify({"success": False, "error": "El cliente no tiene una clave de acceso asignada. Edite el cliente primero."}), 400

    # Construir URL del portal segura y encriptada
    from app.utils.security import generate_portal_token
    token = generate_portal_token(owner_uid, client_id, sandbox=sandbox)
    portal_url = url_for('portal.portal_entry', token=token, _external=True)

    company = DatabaseService.get_company_profile(owner_uid) or {}
    company_name = company.get('tradeName') or company.get('companyName') or get_product_name()
    brand_color = company.get('colorMarca', '#10b981')
    logo_url = company.get('logoUrl', '')
    logo_html = f'<img src="{logo_url}" alt="Logo" style="max-height: 60px; margin-bottom: 15px;"><br>' if logo_url else ''

    from flask import current_app

    client_name = client.get('razonSocial', 'Cliente')
    client_rnc = client.get('rnc', '')

    html_body = f"""
    <html>
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
        <div style="text-align: center; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 2px solid {brand_color};">
            {logo_html}
            <h2 style="color: {brand_color}; margin: 0;">Acceso al Portal de Autoservicio</h2>
            <p style="color: #666; margin: 4px 0 0 0;">{company_name}</p>
        </div>

        <p>Estimado/a <strong>{client_name}</strong>,</p>
        <p>Le compartimos sus credenciales de acceso al portal de autoservicio de <strong>{company_name}</strong>, donde podrá consultar sus facturas, cotizaciones y realizar pagos en línea.</p>

        <div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 20px; margin: 20px 0;">
            <h3 style="margin: 0 0 14px 0; color: {brand_color}; font-size: 1rem;">Sus Credenciales de Acceso</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 8px 0; color: #6b7280; font-size: 0.9rem;">Usuario (RNC / Cédula):</td>
                    <td style="padding: 8px 0; font-weight: bold; text-align: right; font-family: monospace; font-size: 1rem;">{client_rnc}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; border-top: 1px solid #e5e7eb; color: #6b7280; font-size: 0.9rem;">Clave de Acceso (PIN):</td>
                    <td style="padding: 8px 0; border-top: 1px solid #e5e7eb; font-weight: bold; text-align: right; font-family: monospace; font-size: 1.2rem; letter-spacing: 0.15em; color: {brand_color};">{access_pin}</td>
                </tr>
            </table>
        </div>

        <p style="text-align: center; margin: 28px 0 10px 0;">
            <a href="{portal_url}" style="background: {brand_color}; color: white; text-decoration: none; padding: 14px 36px; border-radius: 6px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(0,0,0,0.1); font-size: 1rem;">
                Ingresar al Portal
            </a>
        </p>
        <p style="font-size: 0.82rem; color: #6b7280; text-align: center; margin-top: 8px;">
            O copie y pegue este enlace en su navegador:<br>
            <span style="font-family: monospace; color: #475569; font-size: 0.8rem; word-break: break-all;">{portal_url}</span>
        </p>

        <p style="font-size: 0.82rem; color: #6b7280; text-align: center; margin-top: 20px;">
            Por seguridad, le recomendamos no compartir su clave de acceso con terceros.
        </p>

        <hr style="border: 0; border-top: 1px solid #e5e7eb; margin: 24px 0;">
        <div style="font-size: 0.8rem; color: #9ca3af; text-align: center;">
            Enviado automáticamente por la plataforma {get_product_name()} &middot; {company_name}
        </div>
    </body>
    </html>
    """

    if not current_app.config.get("SMTP_USER") or not current_app.config.get("SMTP_PASSWORD"):
        if sandbox:
            print(f"⚠️ SMTP no configurado. Simulando envío de credenciales a {recipient_email}...")
            import uuid as _uuid
            from datetime import datetime as _dt, timezone
            interaction_id = str(_uuid.uuid4())
            interaction_dict = {
                "type": "Email",
                "title": "Credenciales del Portal enviadas (Simulado)",
                "content": f"Simulación: Credenciales de acceso al portal enviadas a {recipient_email}.\nRNC: {client_rnc} | PIN: {access_pin} | URL: {portal_url}",
                "date": _dt.now(timezone.utc).isoformat(),
                "completed": True,
                "createdBy": session.get('user', {}).get('email', 'Sistema')
            }
            DatabaseService.save_client_interaction(owner_uid, client_id, interaction_id, interaction_dict, sandbox=sandbox)
            return jsonify({"success": True, "message": f"Credenciales simuladas enviadas a {recipient_email} (SMTP no configurado)."})
        return jsonify({"success": False, "error": "Servidor de correo SMTP no configurado."}), 500

    subject = f"🔑 Acceso al Portal de Autoservicio - {company_name}"

    success = Mailer.send(
        app=current_app._get_current_object(),
        to_email=recipient_email,
        subject=subject,
        html_body=html_body,
        from_name=company_name,
        category='credentials'
    )

    if not success:
        return jsonify({"success": False, "error": "Error al enviar correo."}), 500

    import uuid as _uuid
    from datetime import datetime as _dt, timezone
    interaction_id = str(_uuid.uuid4())
    interaction_dict = {
        "type": "Email",
        "title": "Credenciales del Portal enviadas",
        "content": f"Credenciales de acceso al portal enviadas a {recipient_email}.\nRNC: {client_rnc} | PIN: {access_pin}",
        "date": _dt.now(timezone.utc).isoformat(),
        "completed": True,
        "createdBy": session.get('user', {}).get('email', 'Sistema')
    }
    DatabaseService.save_client_interaction(owner_uid, client_id, interaction_id, interaction_dict, sandbox=sandbox)

    return jsonify({"success": True, "message": f"Credenciales enviadas exitosamente a {recipient_email}."})

@web_clients_bp.route('/clients/<client_id>')
def client_detail(client_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Ver Detalle de Cliente", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    client = next((c for c in clients if c['id'] == client_id), None)
    
    if not client:
        flash('Cliente no encontrado.', 'error')
        return redirect(url_for('web_clients.list_clients'))
        
    # Obtener facturas y cotizaciones del cliente
    all_invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    client_invoices = [inv for inv in all_invoices if inv['clientId'] == client_id and not inv.get('isQuotation')]
    client_quotations = [inv for inv in all_invoices if inv['clientId'] == client_id and inv.get('isQuotation')]
    
    # Calcular sumas financieras específicas (excluyendo cotizaciones, anuladas y borradores)
    client['total_invoiced'] = sum(inv['total'] for inv in client_invoices if inv.get('status') not in ['Anulada', 'Borrador'])
    client['total_cxc'] = sum(inv['netPayable'] for inv in client_invoices if inv['status'] in ['Emitida', 'Vencida', 'Revisión de Pago'])
    
    # Obtener interacciones
    interactions = DatabaseService.get_client_interactions(owner_uid, client_id, sandbox=sandbox)
    documents = DatabaseService.get_client_documents(owner_uid, client_id, sandbox=sandbox)
    
    # Obtener todos los abonos/pagos de las facturas del cliente
    client_payments = []
    for inv in client_invoices:
        inv_payments = DatabaseService.get_invoice_payments(owner_uid, inv['id'], sandbox=sandbox)
        for pay in inv_payments:
            pay['invoiceNumber'] = inv.get('invoiceNumber', '')
            pay['invoiceId'] = inv['id']
            client_payments.append(pay)
    client_payments.sort(key=lambda x: x.get('paymentDate') or '', reverse=True)
    
    # Obtener nombre del responsable
    responsible_name = None
    resp_id = client.get('responsibleId')
    if resp_id:
        try:
            colabs = DatabaseService.get_team_members(owner_uid) or []
            target_colab = next((col for col in colabs if col['uid'] == resp_id), None)
            if target_colab:
                responsible_name = target_colab.get('name') or target_colab.get('email', '').split('@')[0]
        except Exception:
            pass
            
    # Generar URL del portal encriptada y segura
    # Detectar alertas Smart Insights para este cliente
    client_insight = None
    now_dt = datetime.now(timezone.utc)
    current_month = now_dt.strftime("%Y-%m")
    monthly_data = {}
    for inv in client_invoices:
        if inv.get('status') in ('Anulada', 'Borrador'):
            continue
        month = (inv.get('date') or '')[:7]
        if month:
            monthly_data[month] = monthly_data.get(month, 0.0) + float(inv.get('total', 0.0))

    if len(monthly_data) >= 2:
        current_sales = monthly_data.get(current_month, 0.0)
        other = [v for k, v in monthly_data.items() if k != current_month]
        avg_hist = sum(other) / len(other)
        if avg_hist > 5000 and current_sales < (avg_hist * 0.60):
            drop = int((1 - (current_sales / avg_hist)) * 100)
            client_insight = {
                "type": "warning",
                "text": f"Atención: Este cliente ha reducido sus compras un {drop}% este mes comparado con su promedio histórico."
            }

    if not client_insight:
        overdue = sum(inv.get('remainingBalance', 0.0) for inv in client_invoices if inv.get('status') == 'Vencida')
        if overdue > 10000:
            client_insight = {
                "type": "danger",
                "text": f"Alerta: Este cliente acumula RD$ {overdue:,.2f} en facturas vencidas."
            }

    if not client_insight:
        client_insight = {"type": "success", "text": "Cliente sin anomalías detectadas. Perfil de compras estable."}

    from app.utils.security import generate_portal_token
    token = generate_portal_token(owner_uid, client_id, sandbox=sandbox)
    portal_url = url_for('portal.portal_entry', token=token, _external=True)

    # Detectar campos relevantes faltantes para operaciones
    operational_fields = [
        ("email",         "Correo Electrónico",   "fa-envelope"),
        ("telefono",      "Teléfono",             "fa-phone"),
        ("direccion",     "Dirección Física",     "fa-location-dot"),
        ("accessPin",     "PIN de Acceso (Portal)","fa-key"),
        ("pipelineStage", "Etapa de Seguimiento",  "fa-chart-simple"),
        ("responsibleId", "Responsable Asignado",  "fa-user-tie"),
    ]
    missing_fields = [
        {"field": f, "label": lbl, "icon": ic}
        for f, lbl, ic in operational_fields
        if not client.get(f)
    ]

    return render_template(
        'clients/detail.html',
        active_page='clients',
        client=client,
        invoices=client_invoices,
        quotations=client_quotations,
        interactions=interactions,
        documents=documents,
        payments=client_payments,
        responsible_name=responsible_name,
        portal_url=portal_url,
        client_insight=client_insight,
        missing_fields=missing_fields
    )

@web_clients_bp.route('/clients/<client_id>/insights')
def client_insights(client_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Smart Insights", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    client = next((c for c in clients if c['id'] == client_id), None)
    if not client:
        flash('Cliente no encontrado.', 'error')
        return redirect(url_for('web_clients.list_clients'))

    all_invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    client_invoices = [inv for inv in all_invoices if inv['clientId'] == client_id and not inv.get('isQuotation')]

    total_invoiced = sum(inv['total'] for inv in client_invoices if inv.get('status') not in ('Anulada', 'Borrador'))
    total_cxc = sum(inv['netPayable'] for inv in client_invoices if inv.get('status') in ('Emitida', 'Vencida', 'Revision de Pago'))

    from collections import Counter
    product_counter = Counter()
    for inv in client_invoices:
        for item in inv.get('items', []):
            name = item.get('name', 'Producto')
            qty = float(item.get('quantity', 1))
            product_counter[name] += qty
    top_product_names = [name for name, _ in product_counter.most_common(5)]

    strategy = AIService.generate_client_strategy(owner_uid, client, client_invoices)

    return render_template(
        'clients/insights.html',
        active_page='clients',
        client=client,
        invoices=client_invoices,
        strategy=strategy,
        total_invoiced=total_invoiced,
        total_cxc=total_cxc,
        invoice_count=len(client_invoices),
        top_products=top_product_names
    )

@web_clients_bp.route('/clients/<client_id>/interactions/new', methods=['POST'])
def add_client_interaction(client_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name="Registrar Seguimiento", required_permission="canClients")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    content = request.form.get('content', '').strip()
    interaction_type = request.form.get('type', 'Nota')
    next_contact_date = request.form.get('nextContactDate', '').strip()
    
    if not content:
        flash('El comentario no puede estar vacío.', 'error')
        return redirect(url_for('web_clients.client_detail', client_id=client_id))
        
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
            flash(f"Advertencia: No se pudo cargar el archivo adjunto: {html.escape(str(e))}", 'warning')

    interaction_id = str(uuid.uuid4())
    interaction_dict = {
        "type": interaction_type,
        "content": content,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
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
        clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
        client = next((c for c in clients if c['id'] == client_id), None)
        if client:
            client['nextContactDate'] = next_contact_date
            client['crmNotes'] = content[:100]
            DatabaseService.save_client(owner_uid, client_id, client, sandbox=sandbox)
            
    flash('Interacción registrada exitosamente.', 'success')
    return redirect(url_for('web_clients.client_detail', client_id=client_id))

@web_clients_bp.route('/clients/<client_id>/interactions/<interaction_id>/delete', methods=['POST'])
def delete_client_interaction_route(client_id, interaction_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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
    return redirect(url_for('web_clients.client_detail', client_id=client_id))

@web_clients_bp.route('/clients/<client_id>/interactions/<interaction_id>/complete', methods=['POST'])
def complete_client_interaction_task(client_id, interaction_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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
        clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
        client = next((c for c in clients if c['id'] == client_id), None)
        if client and client.get('nextContactDate') == interaction.get('nextContactDate'):
            client['nextContactDate'] = None
            DatabaseService.save_client(owner_uid, client_id, client, sandbox=sandbox)
            
        flash('Seguimiento marcado como COMPLETADO.', 'success')
        
    return redirect(url_for('web_clients.client_detail', client_id=client_id))

@web_clients_bp.route('/clients/<client_id>/interactions/quick-note', methods=['POST'])
def add_quick_note(client_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
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
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "nextContactDate": None,
        "completed": False,
        "createdBy": session['user']['email'],
        "attachmentUrl": "",
        "attachmentName": ""
    }
    
    DatabaseService.save_client_interaction(owner_uid, client_id, interaction_id, interaction_dict, sandbox=sandbox)
    
    if complete_task:
        clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
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

@web_clients_bp.route('/api/clients/lookup_by_rnc')
def api_clients_lookup_by_rnc():
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    rnc = request.args.get('rnc', '').strip()
    if not rnc:
        return jsonify({"success": False, "error": "RNC requerido"}), 400
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    from app.services.contact_service import ContactService
    contact = ContactService.get_contact_by_rnc(owner_uid, rnc, sandbox=sandbox)
    if not contact:
        client = DatabaseService.get_client_by_rnc(owner_uid, rnc, sandbox=sandbox)
        if client:
            return jsonify({
                "success": True,
                "found": True,
                "isClient": True,
                "client": {
                    "id": client.get("id", ""),
                    "rnc": client.get("rnc", ""),
                    "name": client.get("razonSocial", ""),
                    "email": client.get("email", ""),
                    "phone": client.get("telefono", ""),
                    "address": client.get("direccion", ""),
                }
            })
        return jsonify({"success": True, "found": False})
    types = contact.get("types", [])
    return jsonify({
        "success": True,
        "found": True,
        "isClient": "cliente" in types,
        "isSupplier": "proveedor" in types,
        "client": {
            "id": contact.get("id", ""),
            "rnc": contact.get("rnc", ""),
            "name": contact.get("razonSocial", ""),
            "email": contact.get("email", ""),
            "phone": contact.get("telefono", ""),
            "address": contact.get("direccion", ""),
        }
    })

@web_clients_bp.route('/api/clients/list')
def api_clients_list():
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    result = []
    for c in clients:
        name = c.get('name') or c.get('tradeName') or c.get('companyName') or c.get('razonSocial') or c.get('businessName') or ''
        rnc = c.get('rnc') or c.get('companyRNC') or ''
        result.append({
            "id": c['id'],
            "name": name,
            "rnc": rnc,
            "email": c.get('email', ''),
            "phone": c.get('phone') or c.get('telefono') or '',
            "address": c.get('address', ''),
            "contactPerson": c.get('contactPerson') or c.get('contactName', '')
        })
    return jsonify({"success": True, "clients": result})
