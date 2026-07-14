# app/web/suppliers.py
import uuid
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, g
from app.services.db_service import DatabaseService
from app.services.supplier_service import SupplierService
from app.utils.decorators import check_permission
from app.models.fiscal_document_type import all_types as _all_fiscal_types, Family as _Family, by_code as _by_code

web_suppliers_bp = Blueprint('web_suppliers', __name__)

@web_suppliers_bp.route('/suppliers')
def list_suppliers():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageSuppliers'):
        return render_template('auth/restricted.html', feature_name="Proveedores", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    suppliers = SupplierService.get_suppliers(owner_uid, sandbox=sandbox)
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))

    for s in suppliers:
        sid = s['id']
        s_expenses = [e for e in expenses if e.get('supplierId') == sid]
        s['total_purchases'] = sum(float(e.get('amount', 0)) for e in s_expenses)
        s['cxp_balance'] = sum(float(e.get('cxpRemainingBalance', 0)) for e in s_expenses)
        s['expense_count'] = len(s_expenses)

    q = request.args.get('q', '').strip().lower()
    estado = request.args.get('estado', '').strip()
    tipo = request.args.get('tipo', '').strip()

    if q:
        suppliers = [s for s in suppliers if
                     q in s.get('name', '').lower() or
                     q in s.get('rnc', '') or
                     q in s.get('email', '').lower() or
                     q in s.get('contactPerson', '').lower()]
    if estado:
        suppliers = [s for s in suppliers if s.get('estado', 'Activo') == estado]
    if tipo:
        suppliers = [s for s in suppliers if s.get('supplierType', 'formal') == tipo]

    if request.args.get('export') == 'csv':
        import csv, io
        from flask import send_file
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["RNC", "Nombre", "Teléfono", "Email", "Tipo", "Estado", "Compras (RD$)", "Saldo CxP (RD$)"])
        for s in suppliers:
            writer.writerow([
                s.get("rnc", ""), s.get("name", ""), s.get("phone", ""),
                s.get("email", ""), s.get("supplierType", ""), s.get("estado", "Activo"),
                f"{s.get('total_purchases', 0.0):.2f}", f"{s.get('cxp_balance', 0.0):.2f}"
            ])
        dest = io.BytesIO()
        dest.write(b'\xef\xbb\xbf')
        dest.write(output.getvalue().encode('utf-8'))
        dest.seek(0)
        filename = f"proveedores_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(dest, mimetype="text/csv", as_attachment=True, download_name=filename)

    total_items = len(suppliers)
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
    paginated = suppliers[start_idx:end_idx]
    start_count = ((page - 1) * per_page_val) + 1 if total_items > 0 else 0
    end_count = min(page * per_page_val, total_items)

    return render_template(
        'suppliers/list.html',
        active_page='suppliers',
        suppliers=paginated,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
        pages_range=range(1, total_pages + 1),
        has_prev=page > 1,
        has_next=page < total_pages,
        start_count=start_count,
        end_count=end_count,
        q=request.args.get('q', ''),
        estado=request.args.get('estado', ''),
        tipo=request.args.get('tipo', ''),
    )


@web_suppliers_bp.route('/suppliers/new', methods=['GET', 'POST'])
def new_supplier():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageSuppliers'):
        return render_template('auth/restricted.html', feature_name="Nuevo Proveedor", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    if request.method == 'POST':
        rnc = "".join(filter(str.isdigit, request.form.get('rnc', '')))
        if rnc and SupplierService.get_supplier_by_rnc(owner_uid, rnc, sandbox=sandbox):
            flash('Ya existe un proveedor con ese RNC.', 'error')
            return render_template('suppliers/new.html', active_page='suppliers')

        supplier_id = str(uuid.uuid4())
        supplier_dict = {
            "rnc": rnc,
            "name": request.form.get('name', '').strip(),
            "tipoPersona": request.form.get('tipoPersona', 'fisica'),
            "code": request.form.get('code', '').strip(),
            "estado": request.form.get('estado', 'Activo'),
            "phone": request.form.get('phone', '').strip(),
            "email": request.form.get('email', '').strip(),
            "address": request.form.get('address', '').strip(),
            "city": request.form.get('city', '').strip(),
            "country": request.form.get('country', 'República Dominicana').strip(),
            "contactPerson": request.form.get('contactPerson', '').strip(),
            "supplierType": request.form.get('supplierType', 'formal'),
            "currency": request.form.get('currency', 'DOP'),
            "creditDays": int(request.form.get('creditDays', 0)),
            "creditLimit": float(request.form.get('creditLimit', 0)),
            "paymentMethod": request.form.get('paymentMethod', 'Efectivo'),
            "ecfTypeEmits": request.form.get('ecfTypeEmits', _by_code("E31").code),
            "itbisWithholding": request.form.get('itbisWithholding') == 'on',
            "isrWithholding": request.form.get('isrWithholding') == 'on',
            "tipoGastoDGII": request.form.get('tipoGastoDGII', '02'),
            "notes": request.form.get('notes', '').strip(),
        }

        attachment_files = request.files.getlist('attachments[]')
        attachment_types = request.form.getlist('attachmentTypes[]')
        attachment_urls = []
        attachments = []

        for i, att_file in enumerate(attachment_files):
            if att_file and att_file.filename:
                try:
                    file_data = att_file.read()
                    mime_type = att_file.content_type or "application/octet-stream"
                    safe_name = att_file.filename.replace(' ', '_')
                    dest_path = f"users/{owner_uid}/suppliers/{supplier_id}/{safe_name}"
                    public_url = DatabaseService.upload_file_to_storage(file_data, dest_path, mime_type)
                    att_type = attachment_types[i] if i < len(attachment_types) else 'otro'
                    attachment_urls.append(public_url)
                    attachments.append({'url': public_url, 'type': att_type, 'name': att_file.filename})
                except Exception as e:
                    print(f"⚠️ Error al subir adjunto: {e}")

        supplier_dict["attachments"] = attachments
        supplier_dict["firebaseAttachmentURLs"] = attachment_urls

        SupplierService.save_supplier(owner_uid, supplier_id, supplier_dict, sandbox=sandbox)

        from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_CXP
        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_CREATE, module=MODULE_CXP,
            entity_id=supplier_id,
            entity_label=f"Proveedor registrado: {supplier_dict['name']} (RNC: {supplier_dict['rnc']})",
            user_session=session.get('user', {}), after=supplier_dict, sandbox=sandbox
        )
        flash('Proveedor registrado exitosamente.', 'success')
        return redirect(url_for('web_suppliers.list_suppliers'))

    _ecf_types = [t for t in _all_fiscal_types() if t.family == _Family.ECF]
    return render_template('suppliers/new.html', active_page='suppliers', ecf_types=_ecf_types)


@web_suppliers_bp.route('/suppliers/ajax_create', methods=['POST'])
def ajax_create_supplier():
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autenticado."}), 401
    if not check_permission('canExpenses'):
        return jsonify({"success": False, "error": "Sin permiso para registrar proveedores."}), 403

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    data = request.json or request.form
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({"success": False, "error": "El Nombre / Razón Social es obligatorio."}), 400

    rnc = "".join(filter(str.isdigit, (data.get('rnc') or '')))

    from app.services.contact_service import ContactService
    existing = ContactService.get_contact_by_rnc(owner_uid, rnc, sandbox=sandbox) if rnc else None

    if existing:
        supplier_id = existing["id"]
        types = list(existing.get("types", []))
        if "proveedor" not in types:
            types.append("proveedor")
        contact_dict = dict(existing)
        contact_dict["types"] = types
        contact_dict["rnc"] = rnc
        contact_dict["razonSocial"] = name or existing.get("razonSocial", "")
        contact_dict["email"] = (data.get('email') or '').strip() or existing.get("email", "")
        contact_dict["telefono"] = (data.get('phone') or '').strip() or existing.get("telefono", "")
        contact_dict["direccion"] = (data.get('address') or '').strip() or existing.get("direccion", "")
        ContactService.save_contact(owner_uid, supplier_id, contact_dict, sandbox=sandbox)
        was_client = "cliente" in existing.get("types", [])
    else:
        supplier_id = str(uuid.uuid4())
        contact_dict = {
            "rnc": rnc,
            "razonSocial": name,
            "email": (data.get('email') or '').strip(),
            "telefono": (data.get('phone') or '').strip(),
            "direccion": (data.get('address') or '').strip(),
            "types": ["proveedor"],
        }
        ContactService.save_contact(owner_uid, supplier_id, contact_dict, sandbox=sandbox)
        was_client = False

    from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_CXP
    AuditService.log_from_request(
        owner_uid=owner_uid,
        action=ACTION_CREATE,
        module=MODULE_CXP,
        entity_id=supplier_id,
        entity_label=f"Proveedor registrado (Rápido): {name} (RNC: {rnc}){' — vinculado a cliente existente' if was_client else ''}",
        user_session=session.get('user', {}),
        after={"name": name, "rnc": rnc, "wasClient": was_client},
        sandbox=sandbox
    )

    return jsonify({
        "success": True,
        "message": "Proveedor registrado exitosamente." if not was_client else "Cliente vinculado como proveedor exitosamente.",
        "supplier": {
            "id": supplier_id,
            "rnc": rnc,
            "name": name,
            "email": (data.get('email') or '').strip(),
            "phone": (data.get('phone') or '').strip(),
            "address": (data.get('address') or '').strip(),
        }
    })


@web_suppliers_bp.route('/suppliers/<supplier_id>')
def supplier_detail(supplier_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageSuppliers'):
        return render_template('auth/restricted.html', feature_name="Detalle Proveedor", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    supplier = SupplierService.get_supplier(owner_uid, supplier_id, sandbox=sandbox)
    if not supplier:
        flash('Proveedor no encontrado.', 'error')
        return redirect(url_for('web_suppliers.list_suppliers'))

    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    linked_expenses = [e for e in expenses if e.get('supplierId') == supplier_id]
    linked_expenses.sort(key=lambda x: x.get('date', ''), reverse=True)

    total_purchases = sum(float(e.get('amount', 0)) for e in linked_expenses)
    cxp_balance = sum(float(e.get('cxpRemainingBalance', 0)) for e in linked_expenses)

    return render_template(
        'suppliers/detail.html',
        active_page='suppliers',
        supplier=supplier,
        expenses=linked_expenses,
        total_purchases=total_purchases,
        cxp_balance=cxp_balance,
    )


@web_suppliers_bp.route('/suppliers/<supplier_id>/edit', methods=['GET', 'POST'])
def edit_supplier(supplier_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageSuppliers'):
        return render_template('auth/restricted.html', feature_name="Editar Proveedor", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    supplier = SupplierService.get_supplier(owner_uid, supplier_id, sandbox=sandbox)
    if not supplier:
        flash('Proveedor no encontrado.', 'error')
        return redirect(url_for('web_suppliers.list_suppliers'))

    if request.method == 'POST':
        before = supplier.copy()
        supplier_dict = {
            "rnc": "".join(filter(str.isdigit, request.form.get('rnc', ''))),
            "name": request.form.get('name', '').strip(),
            "tipoPersona": request.form.get('tipoPersona', 'fisica'),
            "code": request.form.get('code', '').strip(),
            "estado": request.form.get('estado', 'Activo'),
            "phone": request.form.get('phone', '').strip(),
            "email": request.form.get('email', '').strip(),
            "address": request.form.get('address', '').strip(),
            "city": request.form.get('city', '').strip(),
            "country": request.form.get('country', 'República Dominicana').strip(),
            "contactPerson": request.form.get('contactPerson', '').strip(),
            "supplierType": request.form.get('supplierType', 'formal'),
            "currency": request.form.get('currency', 'DOP'),
            "creditDays": int(request.form.get('creditDays', 0)),
            "creditLimit": float(request.form.get('creditLimit', 0)),
            "paymentMethod": request.form.get('paymentMethod', 'Efectivo'),
            "ecfTypeEmits": request.form.get('ecfTypeEmits', _by_code("E31").code),
            "itbisWithholding": request.form.get('itbisWithholding') == 'on',
            "isrWithholding": request.form.get('isrWithholding') == 'on',
            "tipoGastoDGII": request.form.get('tipoGastoDGII', '02'),
            "notes": request.form.get('notes', '').strip(),
            "attachments": supplier.get("attachments", []),
            "firebaseAttachmentURLs": supplier.get("firebaseAttachmentURLs", []),
        }

        attachment_files = request.files.getlist('attachments[]')
        attachment_types = request.form.getlist('attachmentTypes[]')
        if attachment_files and any(f.filename for f in attachment_files):
            for i, att_file in enumerate(attachment_files):
                if att_file and att_file.filename:
                    try:
                        file_data = att_file.read()
                        mime_type = att_file.content_type or "application/octet-stream"
                        safe_name = att_file.filename.replace(' ', '_')
                        dest_path = f"users/{owner_uid}/suppliers/{supplier_id}/{safe_name}"
                        public_url = DatabaseService.upload_file_to_storage(file_data, dest_path, mime_type)
                        att_type = attachment_types[i] if i < len(attachment_types) else 'otro'
                        supplier_dict["firebaseAttachmentURLs"].append(public_url)
                        supplier_dict["attachments"].append({'url': public_url, 'type': att_type, 'name': att_file.filename})
                    except Exception as e:
                        print(f"⚠️ Error al subir adjunto: {e}")

        SupplierService.save_supplier(owner_uid, supplier_id, supplier_dict, sandbox=sandbox)

        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_CXP
        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_CXP,
            entity_id=supplier_id,
            entity_label=f"Proveedor modificado: {supplier_dict['name']} (RNC: {supplier_dict['rnc']})",
            user_session=session.get('user', {}), before=before, after=supplier_dict, sandbox=sandbox
        )
        flash('Proveedor actualizado exitosamente.', 'success')
        return redirect(url_for('web_suppliers.list_suppliers'))

    _ecf_types = [t for t in _all_fiscal_types() if t.family == _Family.ECF]
    return render_template('suppliers/edit.html', active_page='suppliers', supplier=supplier, ecf_types=_ecf_types)


@web_suppliers_bp.route('/suppliers/<supplier_id>/delete', methods=['POST'])
def delete_supplier(supplier_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageSuppliers'):
        return render_template('auth/restricted.html', feature_name="Eliminar Proveedor", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    supplier = SupplierService.get_supplier(owner_uid, supplier_id, sandbox=sandbox)
    if not supplier:
        flash('Proveedor no encontrado.', 'error')
        return redirect(url_for('web_suppliers.list_suppliers'))

    SupplierService.delete_supplier(owner_uid, supplier_id, sandbox=sandbox)

    from app.services.audit_service import AuditService, ACTION_DELETE, MODULE_CXP
    AuditService.log_from_request(
        owner_uid=owner_uid, action=ACTION_DELETE, module=MODULE_CXP,
        entity_id=supplier_id,
        entity_label=f"Proveedor eliminado: {supplier.get('name', 'N/A')} (RNC: {supplier.get('rnc', 'N/A')})",
        user_session=session.get('user', {}), before=supplier, sandbox=sandbox
    )
    flash('Proveedor eliminado.', 'success')
    return redirect(url_for('web_suppliers.list_suppliers'))


@web_suppliers_bp.route('/api/suppliers/search')
def api_suppliers_search():
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    q = request.args.get('q', '').strip().lower()
    suppliers = SupplierService.get_suppliers(owner_uid, sandbox=sandbox)

    if q:
        suppliers = [s for s in suppliers if
                     q in s.get('name', '').lower() or
                     q in s.get('rnc', '') or
                     q in s.get('email', '').lower()]

    results = []
    for s in suppliers:
        results.append({
            "id": s["id"],
            "rnc": s.get("rnc", ""),
            "name": s.get("name", ""),
            "phone": s.get("phone", ""),
            "email": s.get("email", ""),
            "supplierType": s.get("supplierType", "formal"),
            "creditDays": s.get("creditDays", 0),
            "ecfTypeEmits": s.get("ecfTypeEmits", _by_code("E31").code),
            "currency": s.get("currency", "DOP"),
        })

    return jsonify({"success": True, "suppliers": results[:20]})
