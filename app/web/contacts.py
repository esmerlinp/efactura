import uuid
import html
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, g
from app.services.db_service import DatabaseService
from app.services.contact_service import ContactService
from app.services.mailer import Mailer
from app.services.dgii import DGIIService
from app.utils.decorators import check_permission
from app.brand import get_product_name
from app.models.fiscal_document_type import all_types as _all_fiscal_types, Family as _Family, by_code as _by_code

web_contacts_bp = Blueprint('web_contacts', __name__)


# =========================================================================
# UTILITY: check authed + permission
# =========================================================================

def _check(perm='canClients', feature='Contactos'):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission(perm):
        return render_template('auth/restricted.html', feature_name=feature, required_permission=perm)
    return None


# =========================================================================
# LIST
# =========================================================================

@web_contacts_bp.route('/contacts')
def list_contacts():
    r = _check()
    if r: return r
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    all_contacts = ContactService.get_contacts(owner_uid, sandbox=sandbox)

    total_contacts_count = len(all_contacts)
    count_clientes = sum(1 for c in all_contacts if 'cliente' in c.get('types', []))
    count_proveedores = sum(1 for c in all_contacts if 'proveedor' in c.get('types', []))

    tab = request.args.get('tab', 'todos')
    if tab == 'clientes':
        contacts = [c for c in all_contacts if 'cliente' in c.get('types', [])]
    elif tab == 'proveedores':
        contacts = [c for c in all_contacts if 'proveedor' in c.get('types', [])]
    else:
        contacts = all_contacts

    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))

    for c in contacts:
        cid = c['id']
        c_sales = [inv for inv in invoices if inv['clientId'] == cid and not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador']]
        c['total_invoiced'] = sum(inv['total'] for inv in c_sales)
        c['total_cxc'] = sum(inv['netPayable'] for inv in c_sales if inv['status'] in ['Emitida', 'Vencida', 'Revisión de Pago'])
        c_expenses = [e for e in expenses if e.get('supplierId') == cid]
        c['total_purchases'] = sum(float(e.get('amount', 0)) for e in c_expenses)
        c['cxp_balance'] = sum(float(e.get('cxpRemainingBalance', 0)) for e in c_expenses)

    q = request.args.get('q', '').strip().lower()
    if q:
        contacts = [c for c in contacts if
                     q in c.get('razonSocial', '').lower() or
                     q in c.get('rnc', '') or
                     q in c.get('email', '').lower() or
                     q in c.get('telefono', '')]

    stage = request.args.get('stage', '').strip()
    if stage and stage != 'Todos':
        contacts = [c for c in contacts if c.get('pipelineStage') == stage]

    if request.args.get('export') == 'csv':
        import csv, io
        from flask import send_file
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["RNC / Cédula", "Razón Social", "Email", "Teléfono", "Dirección", "Tipo", "Etapa Pipeline", "Total Facturado (RD$)", "Pendiente CxC (RD$)", "Compras (RD$)", "Saldo CxP (RD$)"])
        for c in contacts:
            writer.writerow([
                c.get("rnc", ""), c.get("razonSocial", ""), c.get("email", ""),
                c.get("telefono", ""), c.get("direccion", ""),
                " / ".join(c.get("types", [])),
                c.get("pipelineStage", "Prospecto"),
                f"{c.get('total_invoiced', 0.0):.2f}", f"{c.get('total_cxc', 0.0):.2f}",
                f"{c.get('total_purchases', 0.0):.2f}", f"{c.get('cxp_balance', 0.0):.2f}"
            ])
        dest = io.BytesIO()
        dest.write(b'\xef\xbb\xbf')
        dest.write(output.getvalue().encode('utf-8'))
        dest.seek(0)
        filename = f"contactos_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(dest, mimetype="text/csv", as_attachment=True, download_name=filename)

    total_items = len(contacts)
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
    paginated = contacts[start_idx:end_idx]
    start_count = ((page - 1) * per_page_val) + 1 if total_items > 0 else 0
    end_count = min(page * per_page_val, total_items)

    return render_template(
        'contacts/list.html',
        active_page='contacts',
        contacts=paginated,
        all_contacts=all_contacts,
        total_contacts_count=total_contacts_count,
        count_clientes=count_clientes,
        count_proveedores=count_proveedores,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
        pages_range=range(1, total_pages + 1),
        has_prev=page > 1,
        has_next=page < total_pages,
        start_count=start_count,
        end_count=end_count,
        tab=tab,
        q=request.args.get('q', ''),
        stage=request.args.get('stage', ''),
    )


# =========================================================================
# CREATE
# =========================================================================

@web_contacts_bp.route('/contacts/new', methods=['GET', 'POST'])
def new_contact():
    r = _check()
    if r: return r
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    if request.method == 'POST':
        rnc_raw = request.form.get('rnc', '')
        rnc = "".join(filter(str.isdigit, rnc_raw))
        razon_social = request.form.get('razonSocial', '').strip()
        if not razon_social:
            flash('La Razón Social es obligatoria.', 'error')
            return redirect(url_for('web_contacts.new_contact'))

        existing = ContactService.get_contact_by_rnc(owner_uid, rnc, sandbox=sandbox)
        if existing:
            flash('Ya existe un contacto con ese RNC.', 'error')
            return redirect(url_for('web_contacts.new_contact'))

        contact_id = str(uuid.uuid4())

        types_raw = request.form.getlist('types')
        types = [t for t in types_raw if t in ('cliente', 'proveedor')]
        if not types:
            types = ['cliente']

        image_url = ""
        image_file = request.files.get('image')
        if image_file and image_file.filename:
            try:
                file_data = image_file.read()
                mime_type = image_file.mimetype or "image/png"
                filename = f"contact_{contact_id}_{str(uuid.uuid4())[:8]}_{image_file.filename}"
                destination_path = f"users/{owner_uid}/contacts/{filename}"
                image_url = DatabaseService.upload_file_to_storage(
                    file_data=file_data, destination_path=destination_path, mime_type=mime_type
                )
            except Exception as e:
                flash(f"Advertencia: No se pudo subir la imagen: {html.escape(str(e))}", 'warning')

        import random
        access_pin = request.form.get('accessPin', '').strip()
        if not access_pin or len(access_pin) != 6 or not access_pin.isdigit():
            access_pin = "".join([str(random.randint(0, 9)) for _ in range(6)])

        contact_dict = {
            "types": types,
            "rnc": rnc,
            "razonSocial": razon_social,
            "email": request.form.get('email', ''),
            "telefono": request.form.get('telefono', ''),
            "telefono2": request.form.get('telefono2', ''),
            "celular": request.form.get('celular', ''),
            "direccion": request.form.get('direccion', ''),
            "municipio": request.form.get('municipio', ''),
            "provincia": request.form.get('provincia', ''),
            "pais": request.form.get('pais', 'República Dominicana'),
            "imageUrl": image_url,
            "pipelineStage": request.form.get('pipelineStage', 'Prospecto'),
            "priceListId": request.form.get('priceListId', ''),
            "nextContactDate": request.form.get('nextContactDate', ''),
            "responsibleId": request.form.get('responsibleId', ''),
            "accessPin": access_pin,
            "disableAutoReminders": request.form.get('disableAutoReminders') == 'on',
            "tipoPersona": request.form.get('tipoPersona', 'fisica'),
            "supplierType": request.form.get('supplierType', 'formal'),
            "creditDays": int(request.form.get('creditDays', 0) or 0),
            "creditLimit": float(request.form.get('creditLimit', 0) or 0),
            "paymentMethod": request.form.get('paymentMethod', 'Efectivo'),
            "currency": request.form.get('currency', 'DOP'),
            "itbisWithholding": request.form.get('itbisWithholding') == 'on',
            "isrWithholding": request.form.get('isrWithholding') == 'on',
            "tipoGastoDGII": request.form.get('tipoGastoDGII', '02'),
            "ecfTypeEmits": request.form.get('ecfTypeEmits', _by_code("E31").code),
            "estado": request.form.get('estado', 'Activo'),
            "notes": request.form.get('notes', ''),
            "associatedPeople": [],
        }

        # People
        people_names = request.form.getlist('people_name[]')
        people_emails = request.form.getlist('people_email[]')
        people_phones = request.form.getlist('people_phone[]')
        people_notify = request.form.getlist('people_notify[]')
        for i, name in enumerate(people_names):
            if name.strip():
                contact_dict["associatedPeople"].append({
                    "name": name.strip(),
                    "email": people_emails[i].strip() if i < len(people_emails) else '',
                    "phone": people_phones[i].strip() if i < len(people_phones) else '',
                    "notifyOnExpiry": (people_notify[i] if i < len(people_notify) else '') == 'on',
                })

        ContactService.save_contact(owner_uid, contact_id, contact_dict, sandbox=sandbox)

        from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_CLIENTES
        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_CREATE, module=MODULE_CLIENTES,
            entity_id=contact_id,
            entity_label=f"Contacto registrado: {contact_dict['razonSocial']} (RNC: {contact_dict['rnc']})",
            user_session=session.get('user', {}), after=contact_dict, sandbox=sandbox
        )
        flash('Contacto registrado exitosamente.', 'success')
        return redirect(url_for('web_contacts.list_contacts'))

    collaborators = DatabaseService.get_team_members(owner_uid) or []
    price_lists = DatabaseService.get_price_lists(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    _ecf_types = [t for t in _all_fiscal_types() if t.family == _Family.ECF]
    return render_template('contacts/form.html',
                           active_page='contacts',
                           contact=None,
                           collaborators=collaborators,
                           price_lists=price_lists,
                           ecf_types=_ecf_types)


# =========================================================================
# AJAX CREATE (quick-create from invoice / expense)
# =========================================================================

@web_contacts_bp.route('/contacts/ajax_create', methods=['POST'])
def ajax_create_contact():
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autenticado."}), 401
    if not (check_permission('canClients') or check_permission('canManagePOS')):
        return jsonify({"success": False, "error": "Sin permiso."}), 403

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    data = request.json or request.form
    rnc = (data.get('rnc') or '').strip()
    razon_social = (data.get('razonSocial') or '').strip()
    if not razon_social:
        return jsonify({"success": False, "error": "La Razón Social es obligatoria."}), 400

    contact_id = str(uuid.uuid4())
    import random
    access_pin = "".join([str(random.randint(0, 9)) for _ in range(6)])

    contact_dict = {
        "types": ["cliente"],
        "rnc": rnc,
        "razonSocial": razon_social,
        "email": (data.get('email') or '').strip(),
        "telefono": (data.get('telefono') or '').strip(),
        "direccion": (data.get('direccion') or '').strip(),
        "notes": "Registrado desde formulario de facturación",
        "pipelineStage": "Cliente Activo",
        "accessPin": access_pin,
    }
    ContactService.save_contact(owner_uid, contact_id, contact_dict, sandbox=sandbox)

    from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_CLIENTES
    AuditService.log_from_request(
        owner_uid=owner_uid, action=ACTION_CREATE, module=MODULE_CLIENTES,
        entity_id=contact_id,
        entity_label=f"Contacto registrado (Rápido): {razon_social} (RNC: {rnc})",
        user_session=session.get('user', {}), after=contact_dict, sandbox=sandbox
    )

    return jsonify({
        "success": True,
        "message": "Contacto registrado exitosamente.",
        "client": {
            "id": contact_id,
            "rnc": rnc,
            "razonSocial": razon_social,
            "email": contact_dict["email"],
            "telefono": contact_dict["telefono"],
            "direccion": contact_dict["direccion"],
        }
    })


# =========================================================================
# DETAIL
# =========================================================================

@web_contacts_bp.route('/contacts/<contact_id>')
def contact_detail(contact_id):
    r = _check()
    if r: return r
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    contact = ContactService.get_contact(owner_uid, contact_id, sandbox=sandbox)
    if not contact:
        flash('Contacto no encontrado.', 'error')
        return redirect(url_for('web_contacts.list_contacts'))

    is_client = 'cliente' in contact.get('types', [])
    is_supplier = 'proveedor' in contact.get('types', [])

    all_invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    client_invoices = [inv for inv in all_invoices if inv['clientId'] == contact_id and not inv.get('isQuotation')] if is_client else []
    client_quotations = [inv for inv in all_invoices if inv['clientId'] == contact_id and inv.get('isQuotation')] if is_client else []
    contact['total_invoiced'] = sum(inv['total'] for inv in client_invoices if inv.get('status') not in ['Anulada', 'Borrador'])
    contact['total_cxc'] = sum(inv['netPayable'] for inv in client_invoices if inv['status'] in ['Emitida', 'Vencida', 'Revisión de Pago'])

    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    linked_expenses = [e for e in expenses if e.get('supplierId') == contact_id] if is_supplier else []
    contact['total_purchases'] = sum(float(e.get('amount', 0)) for e in linked_expenses)
    contact['cxp_balance'] = sum(float(e.get('cxpRemainingBalance', 0)) for e in linked_expenses)

    # Interactions stored in contact doc (subcollection)
    interactions = DatabaseService.get_client_interactions(owner_uid, contact_id, sandbox=sandbox)
    documents = DatabaseService.get_client_documents(owner_uid, contact_id, sandbox=sandbox)

    # Payments
    client_payments = []
    for inv in client_invoices:
        inv_payments = DatabaseService.get_invoice_payments(owner_uid, inv['id'], sandbox=sandbox)
        for pay in inv_payments:
            pay['invoiceNumber'] = inv.get('invoiceNumber', '')
            pay['invoiceId'] = inv['id']
            client_payments.append(pay)
    client_payments.sort(key=lambda x: x.get('paymentDate') or '', reverse=True)

    responsible_name = None
    resp_id = contact.get('responsibleId')
    if resp_id:
        try:
            colabs = DatabaseService.get_team_members(owner_uid) or []
            target = next((col for col in colabs if col['uid'] == resp_id), None)
            if target:
                responsible_name = target.get('name') or target.get('email', '').split('@')[0]
        except Exception:
            pass

    # Insight
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
            client_insight = {"type": "warning", "text": f"Atención: Este contacto ha reducido sus compras un {drop}% este mes."}
    if not client_insight:
        overdue = sum(inv.get('remainingBalance', 0.0) for inv in client_invoices if inv.get('status') == 'Vencida')
        if overdue > 10000:
            client_insight = {"type": "danger", "text": f"Alerta: Este contacto acumula RD$ {overdue:,.2f} en facturas vencidas."}
    if not client_insight:
        client_insight = {"type": "success", "text": "Contacto sin anomalías detectadas. Perfil estable."}

    from app.utils.security import generate_portal_token
    token = generate_portal_token(owner_uid, contact_id, sandbox=sandbox)
    portal_url = url_for('portal.portal_entry', token=token, _external=True)

    missing_fields = []
    if is_client:
        for f, lbl, ic in [
            ("email", "Correo Electrónico", "fa-envelope"),
            ("telefono", "Teléfono", "fa-phone"),
            ("direccion", "Dirección Física", "fa-location-dot"),
            ("accessPin", "PIN de Acceso (Portal)", "fa-key"),
            ("pipelineStage", "Etapa de Seguimiento", "fa-chart-simple"),
            ("responsibleId", "Responsable Asignado", "fa-user-tie"),
        ]:
            if not contact.get(f):
                missing_fields.append({"field": f, "label": lbl, "icon": ic})

    return render_template(
        'contacts/detail.html',
        active_page='contacts',
        contact=contact,
        is_client=is_client,
        is_supplier=is_supplier,
        invoices=client_invoices,
        quotations=client_quotations,
        expenses=linked_expenses,
        interactions=interactions,
        documents=documents,
        payments=client_payments,
        responsible_name=responsible_name,
        portal_url=portal_url,
        client_insight=client_insight,
        missing_fields=missing_fields,
    )


# =========================================================================
# EDIT
# =========================================================================

@web_contacts_bp.route('/contacts/<contact_id>/edit', methods=['GET', 'POST'])
def edit_contact(contact_id):
    r = _check()
    if r: return r
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    contact = ContactService.get_contact(owner_uid, contact_id, sandbox=sandbox)
    if not contact:
        flash('Contacto no encontrado.', 'error')
        return redirect(url_for('web_contacts.list_contacts'))

    if request.method == 'POST':
        before = contact.copy()
        rnc = "".join(filter(str.isdigit, request.form.get('rnc', '')))
        types_raw = request.form.getlist('types')
        types = [t for t in types_raw if t in ('cliente', 'proveedor')]
        if not types:
            types = contact.get('types', ['cliente'])

        image_url = contact.get('imageUrl', '')
        image_file = request.files.get('image')
        if image_file and image_file.filename:
            try:
                file_data = image_file.read()
                mime_type = image_file.mimetype or "image/png"
                filename = f"contact_{contact_id}_{str(uuid.uuid4())[:8]}_{image_file.filename}"
                destination_path = f"users/{owner_uid}/contacts/{filename}"
                image_url = DatabaseService.upload_file_to_storage(
                    file_data=file_data, destination_path=destination_path, mime_type=mime_type
                )
            except Exception as e:
                flash(f"Advertencia: No se pudo subir la imagen: {html.escape(str(e))}", 'warning')

        import random
        access_pin = request.form.get('accessPin', '').strip()
        if not access_pin or len(access_pin) != 6 or not access_pin.isdigit():
            access_pin = contact.get('accessPin', '')
            if not access_pin:
                access_pin = "".join([str(random.randint(0, 9)) for _ in range(6)])

        contact_dict = {
            "types": types,
            "rnc": rnc,
            "razonSocial": request.form.get('razonSocial', '').strip(),
            "email": request.form.get('email', ''),
            "telefono": request.form.get('telefono', ''),
            "telefono2": request.form.get('telefono2', ''),
            "celular": request.form.get('celular', ''),
            "direccion": request.form.get('direccion', ''),
            "municipio": request.form.get('municipio', ''),
            "provincia": request.form.get('provincia', ''),
            "pais": request.form.get('pais', 'República Dominicana'),
            "imageUrl": image_url,
            "pipelineStage": request.form.get('pipelineStage', contact.get("pipelineStage", "Prospecto")),
            "priceListId": request.form.get('priceListId', ''),
            "nextContactDate": request.form.get('nextContactDate', ''),
            "responsibleId": request.form.get('responsibleId', ''),
            "accessPin": access_pin,
            "disableAutoReminders": request.form.get('disableAutoReminders') == 'on',
            "tipoPersona": request.form.get('tipoPersona', 'fisica'),
            "supplierType": request.form.get('supplierType', 'formal'),
            "creditDays": int(request.form.get('creditDays', 0) or 0),
            "creditLimit": float(request.form.get('creditLimit', 0) or 0),
            "paymentMethod": request.form.get('paymentMethod', 'Efectivo'),
            "currency": request.form.get('currency', 'DOP'),
            "itbisWithholding": request.form.get('itbisWithholding') == 'on',
            "isrWithholding": request.form.get('isrWithholding') == 'on',
            "tipoGastoDGII": request.form.get('tipoGastoDGII', '02'),
            "ecfTypeEmits": request.form.get('ecfTypeEmits', _by_code("E31").code),
            "estado": request.form.get('estado', 'Activo'),
            "notes": request.form.get('notes', ''),
            "associatedPeople": [],
            "createdAt": contact.get('createdAt', datetime.now(timezone.utc).isoformat()),
        }

        people_names = request.form.getlist('people_name[]')
        people_emails = request.form.getlist('people_email[]')
        people_phones = request.form.getlist('people_phone[]')
        people_notify = request.form.getlist('people_notify[]')
        for i, name in enumerate(people_names):
            if name.strip():
                contact_dict["associatedPeople"].append({
                    "name": name.strip(),
                    "email": people_emails[i].strip() if i < len(people_emails) else '',
                    "phone": people_phones[i].strip() if i < len(people_phones) else '',
                    "notifyOnExpiry": (people_notify[i] if i < len(people_notify) else '') == 'on',
                })

        ContactService.save_contact(owner_uid, contact_id, contact_dict, sandbox=sandbox)

        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_CLIENTES
        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_CLIENTES,
            entity_id=contact_id,
            entity_label=f"Contacto modificado: {contact_dict['razonSocial']} (RNC: {contact_dict['rnc']})",
            user_session=session.get('user', {}), before=before, after=contact_dict, sandbox=sandbox
        )
        flash('Contacto actualizado exitosamente.', 'success')
        return redirect(url_for('web_contacts.list_contacts'))

    collaborators = DatabaseService.get_team_members(owner_uid) or []
    price_lists = DatabaseService.get_price_lists(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    _ecf_types = [t for t in _all_fiscal_types() if t.family == _Family.ECF]
    return render_template('contacts/form.html',
                           active_page='contacts',
                           contact=contact,
                           collaborators=collaborators,
                           price_lists=price_lists,
                           ecf_types=_ecf_types)


# =========================================================================
# DELETE
# =========================================================================

@web_contacts_bp.route('/contacts/<contact_id>/delete', methods=['POST'])
def delete_contact_route(contact_id):
    r = _check()
    if r: return r
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    contact = ContactService.get_contact(owner_uid, contact_id, sandbox=sandbox)
    if not contact:
        flash('Contacto no encontrado.', 'error')
        return redirect(url_for('web_contacts.list_contacts'))

    ContactService.delete_contact(owner_uid, contact_id, sandbox=sandbox)

    from app.services.audit_service import AuditService, ACTION_DELETE, MODULE_CLIENTES
    AuditService.log_from_request(
        owner_uid=owner_uid, action=ACTION_DELETE, module=MODULE_CLIENTES,
        entity_id=contact_id,
        entity_label=f"Contacto eliminado: {contact.get('razonSocial', 'N/A')} (RNC: {contact.get('rnc', 'N/A')})",
        user_session=session.get('user', {}), before=contact, sandbox=sandbox
    )
    flash('Contacto eliminado.', 'success')
    return redirect(url_for('web_contacts.list_contacts'))


# =========================================================================
# PIPELINE
# =========================================================================

@web_contacts_bp.route('/contacts/<contact_id>/update_pipeline', methods=['POST'])
def update_contact_pipeline(contact_id):
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    if not check_permission('canClients'):
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    data = request.json
    new_stage = data.get('pipelineStage')

    ContactService.update_pipeline(owner_uid, contact_id, new_stage, sandbox=sandbox)
    return jsonify({'success': True})


# =========================================================================
# REMINDERS TOGGLE
# =========================================================================

@web_contacts_bp.route('/contacts/<contact_id>/toggle_reminders', methods=['POST'])
def toggle_contact_reminders(contact_id):
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado."}), 401
    if not check_permission('canClients'):
        return jsonify({"success": False, "error": "Sin permisos."}), 403

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    data = request.json or {}
    disable_reminders = data.get('disableAutoReminders') is True

    contact = ContactService.get_contact(owner_uid, contact_id, sandbox=sandbox)
    if not contact:
        return jsonify({"success": False, "error": "Contacto no encontrado."}), 404

    contact['disableAutoReminders'] = disable_reminders
    ContactService.save_contact(owner_uid, contact_id, contact, sandbox=sandbox)
    return jsonify({"success": True, "disableAutoReminders": disable_reminders})


# =========================================================================
# SEND PORTAL CREDENTIALS
# =========================================================================

@web_contacts_bp.route('/contacts/<contact_id>/send_portal_credentials', methods=['POST'])
def send_contact_portal_credentials(contact_id):
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado."}), 401
    if not check_permission('canClients'):
        return jsonify({"success": False, "error": "Sin permisos."}), 403

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    data = request.json or {}
    recipient_email = data.get('email', '').strip()

    contact = ContactService.get_contact(owner_uid, contact_id, sandbox=sandbox)
    if not contact:
        return jsonify({"success": False, "error": "Contacto no encontrado."}), 404

    if not recipient_email:
        recipient_email = contact.get('email', '')
    if not recipient_email:
        return jsonify({"success": False, "error": "Este contacto no tiene un correo registrado."}), 400

    access_pin = contact.get('accessPin', '')
    if not access_pin:
        return jsonify({"success": False, "error": "El contacto no tiene una clave de acceso asignada."}), 400

    from app.utils.security import generate_portal_token
    token = generate_portal_token(owner_uid, contact_id, sandbox=sandbox)
    portal_url = url_for('portal.portal_entry', token=token, _external=True)

    company = DatabaseService.get_company_profile(owner_uid) or {}
    company_name = company.get('tradeName') or company.get('companyName') or get_product_name()
    brand_color = company.get('colorMarca', '#10b981')
    logo_url = company.get('logoUrl', '')
    logo_html = f'<img src="{logo_url}" alt="Logo" style="max-height: 60px; margin-bottom: 15px;"><br>' if logo_url else ''

    from flask import current_app
    contact_name = contact.get('razonSocial', 'Contacto')
    contact_rnc = contact.get('rnc', '')

    html_body = f"""
    <html>
    <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
        <div style="text-align: center; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 2px solid {brand_color};">
            {logo_html}
            <h2 style="color: {brand_color}; margin: 0;">Acceso al Portal de Autoservicio</h2>
            <p style="color: #666; margin: 4px 0 0 0;">{company_name}</p>
        </div>
        <p>Estimado/a <strong>{contact_name}</strong>,</p>
        <p>Le compartimos sus credenciales de acceso al portal de autoservicio de <strong>{company_name}</strong>.</p>
        <div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 20px; margin: 20px 0;">
            <h3 style="margin: 0 0 14px 0; color: {brand_color}; font-size: 1rem;">Sus Credenciales</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <tr><td style="padding: 8px 0; color: #6b7280;">Usuario (RNC):</td><td style="padding: 8px 0; font-weight: bold; text-align: right; font-family: monospace;">{contact_rnc}</td></tr>
                <tr><td style="padding: 8px 0; border-top: 1px solid #e5e7eb; color: #6b7280;">Clave (PIN):</td><td style="padding: 8px 0; border-top: 1px solid #e5e7eb; font-weight: bold; text-align: right; font-family: monospace; letter-spacing: 0.15em; color: {brand_color};">{access_pin}</td></tr>
            </table>
        </div>
        <p style="text-align: center; margin: 28px 0 10px 0;">
            <a href="{portal_url}" style="background: {brand_color}; color: white; text-decoration: none; padding: 14px 36px; border-radius: 6px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(0,0,0,0.1);">Ingresar al Portal</a>
        </p>
        <p style="font-size: 0.82rem; color: #6b7280; text-align: center;">O copie este enlace: <span style="font-family: monospace; word-break: break-all;">{portal_url}</span></p>
        <hr style="border: 0; border-top: 1px solid #e5e7eb; margin: 24px 0;">
        <div style="font-size: 0.8rem; color: #9ca3af; text-align: center;">Enviado por {get_product_name()} &middot; {company_name}</div>
    </body>
    </html>
    """

    if not current_app.config.get("SMTP_USER") or not current_app.config.get("SMTP_PASSWORD"):
        if sandbox:
            import uuid as _uuid
            interaction_id = str(_uuid.uuid4())
            interaction_dict = {
                "type": "Email", "title": "Credenciales del Portal enviadas (Simulado)",
                "content": f"Simulación: Credenciales enviadas a {recipient_email}. RNC: {contact_rnc} | PIN: {access_pin}",
                "date": datetime.now(timezone.utc).isoformat(), "completed": True,
                "createdBy": session.get('user', {}).get('email', 'Sistema')
            }
            DatabaseService.save_client_interaction(owner_uid, contact_id, interaction_id, interaction_dict, sandbox=sandbox)
            return jsonify({"success": True, "message": f"Credenciales simuladas enviadas a {recipient_email}."})
        return jsonify({"success": False, "error": "Servidor SMTP no configurado."}), 500

    success = Mailer.send(
        app=current_app._get_current_object(),
        to_email=recipient_email,
        subject=f"Acceso al Portal de Autoservicio - {company_name}",
        html_body=html_body,
        from_name=company_name,
        category='credentials'
    )
    if not success:
        return jsonify({"success": False, "error": "Error al enviar correo."}), 500

    import uuid as _uuid
    interaction_id = str(_uuid.uuid4())
    interaction_dict = {
        "type": "Email", "title": "Credenciales del Portal enviadas",
        "content": f"Credenciales enviadas a {recipient_email}. RNC: {contact_rnc} | PIN: {access_pin}",
        "date": datetime.now(timezone.utc).isoformat(), "completed": True,
        "createdBy": session.get('user', {}).get('email', 'Sistema')
    }
    DatabaseService.save_client_interaction(owner_uid, contact_id, interaction_id, interaction_dict, sandbox=sandbox)

    return jsonify({"success": True, "message": f"Credenciales enviadas a {recipient_email}."})


# =========================================================================
# INTERACTIONS
# =========================================================================

@web_contacts_bp.route('/contacts/<contact_id>/interactions/new', methods=['POST'])
def add_contact_interaction(contact_id):
    r = _check()
    if r: return r
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    content = request.form.get('content', '').strip()
    interaction_type = request.form.get('type', 'Nota')
    next_contact_date = request.form.get('nextContactDate', '').strip()
    if not content:
        flash('El comentario no puede estar vacío.', 'error')
        return redirect(url_for('web_contacts.contact_detail', contact_id=contact_id))

    attachment_url = ""
    attachment_name = ""
    file = request.files.get('attachment')
    if file and file.filename:
        try:
            file_data = file.read()
            mime_type = file.mimetype or "application/octet-stream"
            filename = f"crm_{contact_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
            destination_path = f"users/{owner_uid}/crm/{filename}"
            attachment_url = DatabaseService.upload_file_to_storage(file_data, destination_path, mime_type)
            attachment_name = file.filename
        except Exception as e:
            flash(f"Advertencia: No se pudo cargar el archivo: {html.escape(str(e))}", 'warning')

    interaction_id = str(uuid.uuid4())
    interaction_dict = {
        "type": interaction_type, "content": content,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "nextContactDate": next_contact_date or None,
        "completed": False, "createdBy": session['user']['email'],
        "attachmentUrl": attachment_url, "attachmentName": attachment_name,
    }
    DatabaseService.save_client_interaction(owner_uid, contact_id, interaction_id, interaction_dict, sandbox=sandbox)

    from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_CRM
    AuditService.log_from_request(
        owner_uid=owner_uid, action=ACTION_CREATE, module=MODULE_CRM,
        entity_id=interaction_id,
        entity_label=f"Seguimiento CRM registrado para Contacto ID: {contact_id}",
        user_session=session.get('user', {}), after=interaction_dict, sandbox=sandbox
    )

    if next_contact_date:
        contact = ContactService.get_contact(owner_uid, contact_id, sandbox=sandbox)
        if contact:
            contact['nextContactDate'] = next_contact_date
            ContactService.save_contact(owner_uid, contact_id, contact, sandbox=sandbox)

    flash('Interacción registrada exitosamente.', 'success')
    return redirect(url_for('web_contacts.contact_detail', contact_id=contact_id))


@web_contacts_bp.route('/contacts/<contact_id>/interactions/<interaction_id>/delete', methods=['POST'])
def delete_contact_interaction(contact_id, interaction_id):
    r = _check()
    if r: return r
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    DatabaseService.delete_client_interaction(owner_uid, contact_id, interaction_id, sandbox=sandbox)

    from app.services.audit_service import AuditService, ACTION_DELETE, MODULE_CRM
    AuditService.log_from_request(
        owner_uid=owner_uid, action=ACTION_DELETE, module=MODULE_CRM,
        entity_id=interaction_id,
        entity_label=f"Seguimiento CRM eliminado del Contacto ID: {contact_id}",
        user_session=session.get('user', {}), sandbox=sandbox
    )
    flash('Interacción eliminada.', 'success')
    return redirect(url_for('web_contacts.contact_detail', contact_id=contact_id))


@web_contacts_bp.route('/contacts/<contact_id>/interactions/<interaction_id>/complete', methods=['POST'])
def complete_contact_interaction(contact_id, interaction_id):
    r = _check()
    if r: return r
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    interactions = DatabaseService.get_client_interactions(owner_uid, contact_id, sandbox=sandbox)
    interaction = next((it for it in interactions if it['id'] == interaction_id), None)
    if interaction:
        interaction['completed'] = True
        DatabaseService.save_client_interaction(owner_uid, contact_id, interaction_id, interaction, sandbox=sandbox)

        contact = ContactService.get_contact(owner_uid, contact_id, sandbox=sandbox)
        if contact and contact.get('nextContactDate') == interaction.get('nextContactDate'):
            contact['nextContactDate'] = None
            ContactService.save_contact(owner_uid, contact_id, contact, sandbox=sandbox)

        flash('Seguimiento marcado como completado.', 'success')

    return redirect(url_for('web_contacts.contact_detail', contact_id=contact_id))


# =========================================================================
# RNC LOOKUP (DGII)
# =========================================================================

@web_contacts_bp.route('/api/rnc-lookup')
def rnc_lookup():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    rnc = request.args.get('rnc', '')
    res = DGIIService.validate_and_fetch_rnc(rnc)
    return jsonify(res)


# =========================================================================
# API — contacts autocomplete list
# =========================================================================

@web_contacts_bp.route('/api/contacts/list')
def api_contacts_list():
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    contacts = ContactService.get_contacts(owner_uid, sandbox=sandbox)

    filter_type = request.args.get('type', '')
    if filter_type == 'cliente':
        contacts = [c for c in contacts if 'cliente' in c.get('types', [])]
    elif filter_type == 'proveedor':
        contacts = [c for c in contacts if 'proveedor' in c.get('types', [])]

    q = request.args.get('q', '').strip().lower()
    if q:
        contacts = [c for c in contacts if
                     q in c.get('razonSocial', '').lower() or
                     q in c.get('rnc', '') or
                     q in c.get('email', '').lower()]

    result = []
    for c in contacts:
        result.append({
            "id": c['id'],
            "rnc": c.get('rnc', ''),
            "name": c.get('razonSocial', ''),
            "email": c.get('email', ''),
            "phone": c.get('telefono', '') or c.get('celular', ''),
            "address": c.get('direccion', ''),
            "types": c.get('types', []),
            "creditDays": c.get('creditDays', 0),
            "ecfTypeEmits": c.get('ecfTypeEmits', _by_code("E31").code),
            "currency": c.get('currency', 'DOP'),
        })

    return jsonify({"success": True, "contacts": result[:20]})
