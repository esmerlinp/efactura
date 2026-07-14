import uuid
import json
import html
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, g, make_response
from app.services.db_service import DatabaseService, db_firestore, firebase_initialized
from app.services.purchase_order_service import PurchaseOrderService
from app.services.supplier_service import SupplierService
from app.services.goods_receipt_service import GoodsReceiptService
from app.services.supplier_invoice_service import SupplierInvoiceService, ALLOWED_MIME_TYPES, MAX_FILE_SIZE
from app.services.purchase_credit_note_service import PurchaseCreditNoteService
from app.utils.decorators import check_permission
from app.services.audit_service import AuditService, ACTION_CREATE, ACTION_UPDATE, ACTION_DELETE
from app.web.invoices import format_mentions, _get_taggable_users, process_resource_comment_mentions
from app.models.fiscal_document_type import by_code as _by_code

try:
    from weasyprint import HTML as WeasyprintHTML
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WeasyprintHTML = None
    WEASYPRINT_AVAILABLE = False

web_purchase_orders_bp = Blueprint('web_purchase_orders', __name__)

MODULE_PO = "Órdenes de Compra"
MODULE_SINV = "Facturas Proveedor"


@web_purchase_orders_bp.route('/purchase-orders')
def list_purchase_orders():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='purchase_orders')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    orders = PurchaseOrderService.get_purchase_orders(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))

    total_items = len(orders)
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
    paginated = orders[start_idx:end_idx]
    start_count = ((page - 1) * per_page_val) + 1 if total_items > 0 else 0
    end_count = min(page * per_page_val, total_items)

    return render_template('purchase_orders/list.html',
                           orders=paginated,
                           page=page,
                           total_pages=total_pages,
                           total_items=total_items,
                           pages_range=range(1, total_pages + 1),
                           has_prev=page > 1,
                           has_next=page < total_pages,
                           start_count=start_count,
                           end_count=end_count,
                           active_page='purchase_orders')


@web_purchase_orders_bp.route('/purchase-orders/new', methods=['GET', 'POST'])
def new_purchase_order():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='purchase_orders')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    if request.method == 'POST':
        po_id = str(uuid.uuid4())
        items_raw = request.form.getlist('items[][name]')
        items_qty = request.form.getlist('items[][quantity]')
        items_price = request.form.getlist('items[][unitPrice]')
        items_itbis = request.form.getlist('items[][itbisRate]')
        items_discount = request.form.getlist('items[][discount]')

        items = []
        subtotal = 0.0
        total_itbis = 0.0
        total_discount = 0.0
        for i in range(len(items_raw)):
            name = items_raw[i].strip()
            if not name:
                continue
            qty = float(items_qty[i]) if i < len(items_qty) and items_qty[i] else 0
            price = float(items_price[i]) if i < len(items_price) and items_price[i] else 0
            itbis_rate = float(items_itbis[i]) if i < len(items_itbis) and items_itbis[i] else 0.0
            discount_pct = float(items_discount[i]) if i < len(items_discount) and items_discount[i] else 0.0

            line_sub = qty * price
            line_discount = line_sub * (discount_pct / 100.0)
            line_itbis = (line_sub - line_discount) * itbis_rate
            line_total = line_sub - line_discount + line_itbis
            subtotal += line_sub
            total_discount += line_discount
            total_itbis += line_itbis

            items.append({
                "id": str(uuid.uuid4()),
                "name": name,
                "quantity": qty,
                "unit": "Unidad",
                "unitPrice": price,
                "itbisRate": itbis_rate,
                "discount": discount_pct,
                "subtotal": round(line_sub, 2),
                "itbisAmount": round(line_itbis, 2),
                "total": round(line_total, 2),
                "receivedQuantity": 0,
            })

        po_number = PurchaseOrderService.get_next_po_number(owner_uid, sandbox=sandbox)
        supplier_id = request.form.get('supplierId', '')

        po_dict = {
            "poNumber": po_number,
            "supplierId": supplier_id,
            "supplierName": request.form.get('supplierName', ''),
            "supplierRnc": request.form.get('supplierRnc', ''),
            "status": "borrador",
            "orderDate": request.form.get('orderDate', datetime.now(timezone.utc).strftime('%Y-%m-%d')),
            "expectedDate": request.form.get('expectedDate', ''),
            "deliveryAddress": request.form.get('deliveryAddress', ''),
            "paymentTerms": request.form.get('paymentTerms', 'contado'),
            "currency": request.form.get('currency', 'DOP'),
            "exchangeRate": float(request.form.get('exchangeRate', 1.0)),
            "subtotal": round(subtotal, 2),
            "itbis": round(total_itbis, 2),
            "discount": round(total_discount, 2),
            "total": round(subtotal - total_discount + total_itbis, 2),
            "notes": request.form.get('notes', ''),
            "internalNotes": request.form.get('internalNotes', ''),
            "items": items,
            "createdBy": session['user'].get('displayName', 'Usuario'),
            "branchId": g.get('branch_id', 'default-sucursal-principal'),
            "projectId": request.form.get('projectId') or g.get('project_id'),
        }

        PurchaseOrderService.save_purchase_order(owner_uid, po_id, po_dict, sandbox=sandbox)

        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_CREATE,
            module=MODULE_PO,
            entity_id=po_id,
            entity_label=po_number,
            after=po_dict,
        )

        flash(f'✅ Orden de compra {po_number} creada exitosamente.', 'success')
        if request.form.get('save_action') == 'save_and_new':
            flash('Orden de compra guardada. Puedes crear otra.', 'success')
            return redirect(url_for('web_purchase_orders.new_purchase_order'))
        return redirect(url_for('web_purchase_orders.list_purchase_orders'))

    po_number = PurchaseOrderService.get_next_po_number(owner_uid, sandbox=sandbox)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    suppliers = SupplierService.get_suppliers(owner_uid, sandbox=sandbox)
    selected_bid = g.get('branch_id') or session.get('selected_branch_id')
    projects = DatabaseService.get_projects(owner_uid, branch_id=selected_bid, sandbox=sandbox) if selected_bid else []
    active_project_id = session.get('selected_project_id') or ''
    return render_template('purchase_orders/new.html',
                           po_number=po_number,
                           today=today,
                           suppliers=suppliers,
                           projects=projects,
                           active_project_id=active_project_id,
                           active_page='purchase_orders')


@web_purchase_orders_bp.route('/purchase-orders/<po_id>')
def purchase_order_detail(po_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='purchase_orders')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    order = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not order:
        flash('❌ Orden de compra no encontrada.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_orders'))
    receipts = GoodsReceiptService.get_receipts_by_po(owner_uid, po_id, sandbox=sandbox)
    order['receipts'] = receipts
    supplier_invoices = SupplierInvoiceService.get_by_po(owner_uid, po_id, sandbox=sandbox)
    order['supplier_invoices'] = supplier_invoices
    comments = DatabaseService.get_resource_comments(owner_uid, "purchase_orders", po_id, sandbox=sandbox)
    taggable_users = _get_taggable_users(owner_uid)
    return render_template('purchase_orders/detail.html',
                           order=order,
                           comments=comments,
                           taggable_users=taggable_users,
                           format_mentions=format_mentions,
                           active_page='purchase_orders')


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/comments/new', methods=['POST'])
def add_po_comment(po_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    content = request.form.get('content', '').strip()
    if not content:
        flash('El comentario no puede estar vacío.', 'error')
        return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))

    attachment_url = ""
    attachment_name = ""
    file = request.files.get('attachment')
    if file and file.filename:
        try:
            file_data = file.read()
            mime_type = file.mimetype or "application/octet-stream"
            filename = f"comment_po_{po_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
            destination_path = f"users/{owner_uid}/comments/{filename}"
            attachment_url = DatabaseService.upload_file_to_storage(file_data, destination_path, mime_type)
            attachment_name = file.filename
        except Exception as e:
            flash(f"Advertencia: No se pudo cargar el archivo adjunto: {html.escape(str(e))}", 'warning')

    comment_id = str(uuid.uuid4())
    comment_dict = {
        "content": content,
        "createdBy": session['user']['email'],
        "createdByName": session['user'].get('name', session['user']['email']),
        "createdByUid": session['user']['uid'],
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "attachmentUrl": attachment_url,
        "attachmentName": attachment_name,
        "edited": False
    }

    DatabaseService.save_resource_comment(owner_uid, "purchase_orders", po_id, comment_id, comment_dict, sandbox=sandbox)

    try:
        order = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox) or {}
        label = order.get('poNumber', 'OC')
        process_resource_comment_mentions(owner_uid, content, "purchase_orders", po_id, label, sandbox)
    except Exception as ex:
        print(f"⚠️ Error al procesar menciones en add_po_comment: {ex}")

    flash('Comentario agregado exitosamente.', 'success')
    return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/comments/<comment_id>/edit', methods=['POST'])
def edit_po_comment(po_id, comment_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    comments = DatabaseService.get_resource_comments(owner_uid, "purchase_orders", po_id, sandbox=sandbox)
    comment = next((c for c in comments if c['id'] == comment_id), None)
    if not comment:
        flash('Comentario no encontrado.', 'error')
        return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))

    is_owner = session['user'].get('role') == 'owner'
    is_author = session['user']['uid'] == comment.get('createdByUid')
    if not (is_owner or is_author):
        flash('No tienes permiso para editar este comentario.', 'error')
        return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))

    content = request.form.get('content', '').strip()
    if not content:
        flash('El comentario no puede estar vacío.', 'error')
        return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))

    comment['content'] = content
    comment['edited'] = True
    comment['editedAt'] = datetime.now(timezone.utc).isoformat()

    file = request.files.get('attachment')
    if file and file.filename:
        try:
            file_data = file.read()
            mime_type = file.mimetype or "application/octet-stream"
            filename = f"comment_po_{po_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
            destination_path = f"users/{owner_uid}/comments/{filename}"
            attachment_url = DatabaseService.upload_file_to_storage(file_data, destination_path, mime_type)
            comment['attachmentUrl'] = attachment_url
            comment['attachmentName'] = file.filename
        except Exception as e:
            flash(f"Advertencia: No se pudo cargar el archivo adjunto: {html.escape(str(e))}", 'warning')

    DatabaseService.save_resource_comment(owner_uid, "purchase_orders", po_id, comment_id, comment, sandbox=sandbox)

    try:
        order = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox) or {}
        label = order.get('poNumber', 'OC')
        process_resource_comment_mentions(owner_uid, content, "purchase_orders", po_id, label, sandbox)
    except Exception as ex:
        print(f"⚠️ Error al procesar menciones en edit_po_comment: {ex}")

    flash('Comentario modificado.', 'success')
    return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/comments/<comment_id>/delete', methods=['POST'])
def delete_po_comment(po_id, comment_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    comments = DatabaseService.get_resource_comments(owner_uid, "purchase_orders", po_id, sandbox=sandbox)
    comment = next((c for c in comments if c['id'] == comment_id), None)
    if not comment:
        flash('Comentario no encontrado.', 'error')
        return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))

    is_owner = session['user'].get('role') == 'owner'
    is_author = session['user']['uid'] == comment.get('createdByUid')
    if not (is_owner or is_author):
        flash('No tienes permiso para eliminar este comentario.', 'error')
        return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))

    DatabaseService.delete_resource_comment(owner_uid, "purchase_orders", po_id, comment_id, sandbox=sandbox)
    flash('Comentario eliminado.', 'success')
    return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/attach', methods=['POST'])
def attach_po_document(po_id):
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    order = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not order:
        return jsonify({"success": False, "error": "Orden de compra no encontrada."}), 404

    attachment_files = request.files.getlist('attachments[]')
    attachment_types = request.form.getlist('attachmentTypes[]')

    existing_attachments = order.get('attachments', [])
    existing_urls = order.get('firebaseAttachmentURLs', [])

    if not existing_attachments and existing_urls:
        existing_attachments = [{'url': u, 'type': 'otro', 'name': u.split('/')[-1].split('?')[0]} for u in existing_urls]

    new_attachments = list(existing_attachments)
    new_urls = list(existing_urls)
    uploaded_count = 0
    errors = []

    for i, att_file in enumerate(attachment_files):
        if att_file and att_file.filename:
            try:
                file_data = att_file.read()
                mime_type = att_file.content_type or "application/octet-stream"
                safe_name = att_file.filename.replace(' ', '_')
                dest_path = f"users/{owner_uid}/purchase_orders/{po_id}/{safe_name}"
                public_url = DatabaseService.upload_file_to_storage(file_data, dest_path, mime_type)
                att_type = attachment_types[i] if i < len(attachment_types) else 'otro'
                new_urls.append(public_url)
                new_attachments.append({'url': public_url, 'type': att_type, 'name': att_file.filename})
                uploaded_count += 1
            except Exception as e:
                errors.append(str(e))

    if uploaded_count > 0:
        if firebase_initialized:
            coll_name = "sandbox_purchase_orders" if sandbox else "purchase_orders"
            db_firestore.collection("users").document(owner_uid).collection(coll_name).document(po_id).update({
                "attachments": new_attachments,
                "firebaseAttachmentURLs": new_urls
            })

    wants_json = request.headers.get('Accept', '').find('application/json') != -1 or request.args.get('format') == 'json'
    if wants_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            "success": uploaded_count > 0,
            "uploaded": uploaded_count,
            "errors": errors,
            "attachments": new_attachments,
        })

    if uploaded_count > 0:
        flash(f'{uploaded_count} documento(s) adjuntado(s) exitosamente.', 'success')
    else:
        flash('No se seleccionó ningún archivo válido.', 'warning')
    return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/attach/<int:att_index>', methods=['POST'])
def detach_po_document(po_id, att_index):
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autorizado"}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    order = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not order:
        return jsonify({"success": False, "error": "Orden de compra no encontrada."}), 404

    existing_attachments = order.get('attachments', [])
    existing_urls = order.get('firebaseAttachmentURLs', [])

    if not existing_attachments and existing_urls:
        existing_attachments = [{'url': u, 'type': 'otro', 'name': u.split('/')[-1].split('?')[0]} for u in existing_urls]

    if att_index < 0 or att_index >= len(existing_attachments):
        return jsonify({"success": False, "error": "Índice de adjunto inválido."}), 400

    removed = existing_attachments.pop(att_index)
    new_urls = [a['url'] for a in existing_attachments]

    if firebase_initialized:
        coll_name = "sandbox_purchase_orders" if sandbox else "purchase_orders"
        db_firestore.collection("users").document(owner_uid).collection(coll_name).document(po_id).update({
            "attachments": existing_attachments,
            "firebaseAttachmentURLs": new_urls
        })

    return jsonify({
        "success": True,
        "removed": removed.get('name', 'Documento'),
        "attachments": existing_attachments,
    })


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/edit', methods=['GET', 'POST'])
def edit_purchase_order(po_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='purchase_orders')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    order = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not order:
        flash('❌ Orden de compra no encontrada.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_orders'))

    if order.get('status') not in ('borrador', 'pendiente_aprobacion'):
        flash('❌ Solo se pueden editar órdenes en estado borrador o pendiente de aprobación.', 'error')
        return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))

    if request.method == 'POST':
        items_raw = request.form.getlist('items[][name]')
        items_qty = request.form.getlist('items[][quantity]')
        items_price = request.form.getlist('items[][unitPrice]')
        items_itbis = request.form.getlist('items[][itbisRate]')
        items_discount = request.form.getlist('items[][discount]')

        items = []
        subtotal = 0.0
        total_itbis = 0.0
        total_discount = 0.0
        for i in range(len(items_raw)):
            name = items_raw[i].strip()
            if not name:
                continue
            qty = float(items_qty[i]) if i < len(items_qty) and items_qty[i] else 0
            price = float(items_price[i]) if i < len(items_price) and items_price[i] else 0
            itbis_rate = float(items_itbis[i]) if i < len(items_itbis) and items_itbis[i] else 0.0
            discount_pct = float(items_discount[i]) if i < len(items_discount) and items_discount[i] else 0.0

            line_sub = qty * price
            line_discount = line_sub * (discount_pct / 100.0)
            line_itbis = (line_sub - line_discount) * itbis_rate
            line_total = line_sub - line_discount + line_itbis
            subtotal += line_sub
            total_discount += line_discount
            total_itbis += line_itbis

            items.append({
                "id": str(uuid.uuid4()),
                "name": name,
                "quantity": qty,
                "unit": "Unidad",
                "unitPrice": price,
                "itbisRate": itbis_rate,
                "discount": discount_pct,
                "subtotal": round(line_sub, 2),
                "itbisAmount": round(line_itbis, 2),
                "total": round(line_total, 2),
                "receivedQuantity": 0,
            })

        supplier_id = request.form.get('supplierId', '')

        before = dict(order)
        order.update({
            "supplierId": supplier_id,
            "supplierName": request.form.get('supplierName', ''),
            "supplierRnc": request.form.get('supplierRnc', ''),
            "orderDate": request.form.get('orderDate', order.get('orderDate', '')),
            "expectedDate": request.form.get('expectedDate', ''),
            "deliveryAddress": request.form.get('deliveryAddress', ''),
            "paymentTerms": request.form.get('paymentTerms', 'contado'),
            "currency": request.form.get('currency', 'DOP'),
            "exchangeRate": float(request.form.get('exchangeRate', 1.0)),
            "subtotal": round(subtotal, 2),
            "itbis": round(total_itbis, 2),
            "discount": round(total_discount, 2),
            "total": round(subtotal - total_discount + total_itbis, 2),
            "notes": request.form.get('notes', ''),
            "internalNotes": request.form.get('internalNotes', ''),
            "items": items,
        })

        PurchaseOrderService.save_purchase_order(owner_uid, po_id, order, sandbox=sandbox)

        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_UPDATE,
            module=MODULE_PO,
            entity_id=po_id,
            entity_label=order.get('poNumber', ''),
            before=before,
            after=order,
        )

        flash(f'✅ Orden de compra {order.get("poNumber")} actualizada.', 'success')
        return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    suppliers = SupplierService.get_suppliers(owner_uid, sandbox=sandbox)
    return render_template('purchase_orders/edit.html',
                           order=order,
                           today=today,
                           suppliers=suppliers,
                           active_page='purchase_orders')


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/delete', methods=['POST'])
def delete_purchase_order(po_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', active_page='purchase_orders')
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    order = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not order:
        flash('❌ Orden de compra no encontrada.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_orders'))

    po_number = order.get('poNumber', '')
    PurchaseOrderService.delete_purchase_order(owner_uid, po_id, sandbox=sandbox)

    AuditService.log_from_request(
        owner_uid=owner_uid,
        action=ACTION_DELETE,
        module=MODULE_PO,
        entity_id=po_id,
        entity_label=po_number,
        before=order,
    )

    flash(f'🗑️ Orden de compra {po_number} eliminada.', 'success')
    return redirect(url_for('web_purchase_orders.list_purchase_orders'))


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/approve', methods=['POST'])
def approve_purchase_order(po_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    user = session['user'].get('displayName', 'Usuario')

    po = PurchaseOrderService.update_status(owner_uid, po_id, 'aprobada', sandbox=sandbox, user=user)
    if not po:
        return jsonify(success=False, error="Orden no encontrada"), 404

    AuditService.log_from_request(
        owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_PO,
        entity_id=po_id, entity_label=po.get('poNumber', ''),
        after=po,
    )
    return jsonify(success=True)


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/receive', methods=['POST'])
def receive_purchase_order(po_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    po = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not po:
        return jsonify(success=False, error="Orden no encontrada"), 404

    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}

    received_qty_map = data.get('receivedQuantities', {})
    items = po.get('items', [])
    all_complete = True
    for item in items:
        item_id = item.get('id', '')
        qty = float(received_qty_map.get(item_id, item.get('quantity', 0)))
        item['receivedQuantity'] = qty
        if qty < item.get('quantity', 0):
            all_complete = False

    new_status = 'recibida_completa' if all_complete else 'recibida_parcial'
    user = session['user'].get('displayName', 'Usuario')
    po['status'] = new_status
    po['receivedBy'] = user
    po['receivedAt'] = datetime.now(timezone.utc).isoformat()
    po['items'] = items
    PurchaseOrderService.save_purchase_order(owner_uid, po_id, po, sandbox=sandbox)

    AuditService.log_from_request(
        owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_PO,
        entity_id=po_id, entity_label=po.get('poNumber', ''),
        after=po,
    )
    return jsonify(success=True, status=new_status)


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/cancel', methods=['POST'])
def cancel_purchase_order(po_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    user = session['user'].get('displayName', 'Usuario')

    po = PurchaseOrderService.update_status(owner_uid, po_id, 'cancelada', sandbox=sandbox, user=user)
    if not po:
        return jsonify(success=False, error="Orden no encontrada"), 404

    AuditService.log_from_request(
        owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_PO,
        entity_id=po_id, entity_label=po.get('poNumber', ''),
        after=po,
    )
    return jsonify(success=True)


@web_purchase_orders_bp.route('/api/purchase-orders/next-number')
def api_next_po_number():
    if 'user' not in session:
        return jsonify(success=False, error="No autorizado"), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    number = PurchaseOrderService.get_next_po_number(owner_uid, sandbox=sandbox)
    return jsonify(success=True, poNumber=number)


@web_purchase_orders_bp.route('/api/purchase-orders/supplier-items')
def api_supplier_items():
    if 'user' not in session:
        return jsonify(success=False, error="No autorizado"), 401
    owner_uid = session['user']['ownerUID']
    items = DatabaseService.get_items(owner_uid, sandbox=session.get('is_sandbox_mode', True), branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    active = [i for i in items if i.get('isActive', True)]
    return jsonify(success=True, items=active)


# ═════════════════════════════════════════════════════════════════════
# SUPPLIER INVOICES (Facturas de Proveedor + CxP Compras)
# ═════════════════════════════════════════════════════════════════════



@web_purchase_orders_bp.route('/purchase-orders/cxp/consolidado')
def consolidated_cxp():
    """Vista consolidada de Cuentas por Pagar (Compras + Gastos)."""
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. Purchase invoices
    purchase_invoices = SupplierInvoiceService.get_all(owner_uid, sandbox=sandbox)
    # 2. Expense CxP
    all_expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))

    unified = []
    total_pending = 0.0
    total_overdue = 0.0

    # Normalize purchase invoices
    for inv in purchase_invoices:
        due_date = inv.get('dueDate', '')
        rem_bal = float(inv.get('cxpRemainingBalance', inv.get('total', 0)))
        inv['cxpRemainingBalance'] = rem_bal
        status = inv.get('cxpStatus', 'Pendiente')
        if status in ('Pendiente', 'Abonado') and due_date and due_date < today_str:
            status = 'Vencido'
            inv['cxpStatus'] = 'Vencido'
        if status in ('Pendiente', 'Abonado', 'Vencido'):
            total_pending += rem_bal
            if status == 'Vencido' or (due_date and due_date < today_str):
                total_overdue += rem_bal
        unified.append({
            "id": inv["id"],
            "type": "compra",
            "documentNumber": inv.get("invoiceNumber", ""),
            "referenceNumber": inv.get("poNumber", ""),
            "supplierName": inv.get("supplierName", ""),
            "supplierRnc": inv.get("supplierRnc", ""),
            "ncf": inv.get("ncf", ""),
            "concept": f"Factura {inv.get('invoiceNumber', '')}" + (f" (OC {inv.get('poNumber', '')})" if inv.get('poNumber') else ""),
            "date": str(inv.get("date", ""))[:10],
            "dueDate": str(inv.get("dueDate", ""))[:10] if inv.get("dueDate") else "",
            "total": float(inv.get("total", 0)),
            "balance": rem_bal,
            "status": inv.get("cxpStatus", "Pendiente"),
            "detail_url": url_for('web_purchase_orders.supplier_invoice_detail', invoice_id=inv["id"]),
        })

    # Normalize expense CxP
    for exp in all_expenses:
        if exp.get('approvalStatus') == 'Pendiente':
            continue
        if exp.get('paymentType') != 'Crédito':
            continue
        due_date = exp.get('dueDate', '')
        rem_bal = float(exp.get('cxpRemainingBalance', exp.get('amount', 0.0)))
        status = exp.get('cxpStatus', 'Pendiente')
        if status in ('Pendiente', 'Abonado') and due_date and due_date < today_str:
            status = 'Vencido'
        if status in ('Pendiente', 'Abonado', 'Vencido'):
            total_pending += rem_bal
            if status == 'Vencido' or (due_date and due_date < today_str):
                total_overdue += rem_bal
        unified.append({
            "id": exp["id"],
            "type": "gasto",
            "documentNumber": exp.get("ncf", ""),
            "referenceNumber": "",
            "supplierName": exp.get("providerName", ""),
            "supplierRnc": exp.get("rncEmisor", ""),
            "ncf": exp.get("ncf", ""),
            "concept": exp.get("concept", ""),
            "date": str(exp.get("date", ""))[:10],
            "dueDate": str(exp.get("dueDate", ""))[:10] if exp.get("dueDate") else "",
            "total": float(exp.get("amount", 0)),
            "balance": rem_bal,
            "status": status,
            "detail_url": url_for('web_invoices.expense_detail', expense_id=exp["id"]),
        })

    # Sort by date descending
    unified.sort(key=lambda x: x["date"], reverse=True)

    # Filters
    status_filter = request.args.get('status', '').strip()
    search_query = request.args.get('search', '').strip().lower()
    type_filter = request.args.get('type', '').strip()

    filtered = []
    for item in unified:
        if status_filter and item["status"] != status_filter:
            continue
        if type_filter and item["type"] != type_filter:
            continue
        if search_query:
            haystack = f"{item['supplierName']} {item['supplierRnc']} {item['ncf']} {item['concept']} {item['documentNumber']}".lower()
            if search_query not in haystack:
                continue
        filtered.append(item)

    return render_template('purchase_orders/consolidated_cxp.html',
                           active_page='consolidated_cxp',
                           items=filtered,
                           total_pending=total_pending,
                           total_overdue=total_overdue,
                           today_str=today_str,
                           status_filter=status_filter,
                           search_query=search_query,
                           type_filter=type_filter)


@web_purchase_orders_bp.route('/purchase-orders/invoices')
def list_purchase_cxp():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        return render_template('auth/restricted.html', feature_name="CxP Compras", required_permission="canManagePurchaseCXP")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoices = SupplierInvoiceService.get_all(owner_uid, sandbox=sandbox)

    total_pending = 0.0
    total_overdue = 0.0
    total_month_purchases = 0.0
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    this_month = datetime.now(timezone.utc).strftime("%Y-%m")

    for inv in invoices:
        status = inv.get('cxpStatus', 'Pendiente')
        due_date = inv.get('dueDate', '')
        rem_bal = float(inv.get('cxpRemainingBalance', inv.get('total', 0)))
        inv['cxpRemainingBalance'] = rem_bal
        if status in ('Pendiente', 'Abonado') and due_date and due_date < today_str:
            status = 'Vencido'
            inv['cxpStatus'] = 'Vencido'
        if status in ('Pendiente', 'Abonado', 'Vencido'):
            total_pending += rem_bal
            if status == 'Vencido' or (due_date and due_date < today_str):
                total_overdue += rem_bal
        inv_date = str(inv.get('date', ''))[:7] if inv.get('date') else ''
        if inv_date == this_month:
            total_month_purchases += float(inv.get('total', 0))

    status_filter = request.args.get('status', '').strip()
    search_query = request.args.get('search', '').strip().lower()

    filtered = []
    for inv in invoices:
        st = inv.get('cxpStatus', 'Pendiente')
        if status_filter and st != status_filter:
            continue
        if search_query:
            haystack = f"{inv.get('supplierName', '')} {inv.get('supplierRnc', '')} {inv.get('invoiceNumber', '')} {inv.get('ncf', '')}".lower()
            if search_query not in haystack:
                continue
        filtered.append(inv)

    if request.args.get('export') == 'csv':
        import csv, io
        from flask import send_file
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["Factura#", "OC#", "Proveedor", "RNC", "NCF", "Fecha Emisión", "Vencimiento", "Total (RD$)", "Balance (RD$)", "Estado"])
        for inv in filtered:
            writer.writerow([
                inv.get("invoiceNumber", ""), inv.get("poNumber", ""),
                inv.get("supplierName", ""), inv.get("supplierRnc", ""),
                inv.get("ncf", ""), str(inv.get("date", ""))[:10],
                str(inv.get("dueDate", ""))[:10],
                f"{float(inv.get('total', 0)):.2f}",
                f"{float(inv.get('cxpRemainingBalance', inv.get('total', 0))):.2f}",
                inv.get("cxpStatus", "Pendiente"),
            ])
        dest = io.BytesIO()
        dest.write(b'\xef\xbb\xbf')
        dest.write(output.getvalue().encode('utf-8'))
        dest.seek(0)
        filename = f"cxp_compras_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(dest, mimetype="text/csv", as_attachment=True, download_name=filename)

    return render_template('purchase_orders/purchase_cxp_dashboard.html',
                           active_page='purchase_cxp',
                           invoices=filtered,
                           total_pending=total_pending,
                           total_overdue=total_overdue,
                           total_month_purchases=total_month_purchases,
                           today_str=today_str,
                           status_filter=status_filter,
                           search_query=search_query)


@web_purchase_orders_bp.route('/purchase-orders/invoices/new', methods=['GET', 'POST'])
def new_supplier_invoice_direct():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        return render_template('auth/restricted.html', feature_name="Nueva Factura Directa", required_permission="canManagePurchaseCXP")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    po_id = request.args.get('po_id', '') or request.form.get('po_id', '')
    po = None
    po_supplier_name = ''
    po_supplier_rnc = ''
    po_supplier_id = ''
    po_currency = 'DOP'
    po_exchange_rate = 1.0
    po_payment_terms = 'contado'
    if po_id:
        po = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
        if po:
            po_supplier_name = po.get('supplierName', '')
            po_supplier_rnc = po.get('supplierRnc', '')
            po_supplier_id = po.get('supplierId', '')
            po_currency = po.get('currency', 'DOP')
            po_exchange_rate = float(po.get('exchangeRate', 1.0))
            po_payment_terms = po.get('paymentTerms', 'contado')

    if request.method == 'POST':
        invoice_number = request.form.get('invoiceNumber', '').strip()
        if not invoice_number:
            flash('El número de factura del proveedor es obligatorio.', 'error')
            return redirect(url_for('web_purchase_orders.new_supplier_invoice_direct', po_id=po_id))

        if not SupplierInvoiceService._check_ncf_unique(owner_uid, invoice_number, sandbox=sandbox):
            flash('El número de factura del proveedor ya existe. Verifique los datos.', 'error')
            return redirect(url_for('web_purchase_orders.new_supplier_invoice_direct', po_id=po_id))

        ncf = request.form.get('ncf', '').strip()
        inv_date = request.form.get('date', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
        due_date = request.form.get('dueDate', '')
        ecf_type = request.form.get('ecfType', _by_code("E31").code)

        today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        if inv_date > today_str:
            flash('La fecha de emisión no puede ser futura.', 'error')
            return redirect(url_for('web_purchase_orders.new_supplier_invoice_direct', po_id=po_id))
        if due_date and due_date < inv_date:
            flash('La fecha de vencimiento no puede ser anterior a la fecha de emisión.', 'error')
            return redirect(url_for('web_purchase_orders.new_supplier_invoice_direct', po_id=po_id))

        if ncf and not SupplierInvoiceService._check_ncf_unique(owner_uid, ncf, sandbox=sandbox):
            flash('El NCF ya está registrado en otra factura.', 'error')
            return redirect(url_for('web_purchase_orders.new_supplier_invoice_direct', po_id=po_id))

        payment_type = request.form.get('paymentType', 'Contado')
        currency = request.form.get('currency', 'DOP')
        exchange_rate = float(request.form.get('exchangeRate', 1.0))

        bank_account_id = request.form.get('bankAccountId', '')
        if payment_type == 'Contado' and not bank_account_id:
            flash('Debe seleccionar una cuenta bancaria para pagos al contado.', 'error')
            return redirect(url_for('web_purchase_orders.new_supplier_invoice_direct', po_id=po_id))

        items = []
        subtotal = 0.0
        total_itbis = 0.0
        total_discount = 0.0
        MAX_ITEMS = 500
        idx = 0
        while idx < MAX_ITEMS:
            item_name = request.form.get(f'items[{idx}][name]', '').strip()
            if not item_name:
                break

            qty = float(request.form.get(f'items[{idx}][quantity]', 0) or 0)
            price = float(request.form.get(f'items[{idx}][unitPrice]', 0) or 0)
            itbis_rate = float(request.form.get(f'items[{idx}][itbisRate]', 0.0) or 0.0)
            discount_pct = float(request.form.get(f'items[{idx}][discount]', 0.0) or 0.0)
            accounting_account_id = request.form.get(f'items[{idx}][accountingAccountId]', '')

            line_sub = qty * price
            line_discount = line_sub * (discount_pct / 100.0)
            line_itbis = (line_sub - line_discount) * itbis_rate
            line_total = line_sub - line_discount + line_itbis
            subtotal += line_sub
            total_discount += line_discount
            total_itbis += line_itbis

            items.append({
                "id": str(uuid.uuid4()),
                "name": item_name,
                "quantity": qty,
                "unit": "Unidad",
                "unitPrice": price,
                "itbisRate": itbis_rate,
                "discount": discount_pct,
                "subtotal": round(line_sub, 2),
                "itbisAmount": round(line_itbis, 2),
                "total": round(line_total, 2),
                "receivedQuantity": 0,
                "accountingAccountId": accounting_account_id,
            })
            idx += 1

        if not items:
            flash('Debe agregar al menos una partida.', 'error')
            return redirect(url_for('web_purchase_orders.new_supplier_invoice_direct', po_id=po_id))

        total = subtotal - total_discount + total_itbis
        cxp_status = "Pagado" if payment_type == 'Contado' else "Pendiente"
        cxp_remaining = 0.0 if payment_type == 'Contado' else total

        sinv_number = SupplierInvoiceService.get_next_invoice_number(owner_uid, sandbox=sandbox)

        supplier_id = request.form.get('supplierId', '')
        supplier_name = request.form.get('supplierName', '')
        supplier_rnc = request.form.get('supplierRnc', '')

        if not supplier_id and supplier_rnc:
            from app.services.contact_service import ContactService
            contact = ContactService.get_contact_by_rnc(owner_uid, supplier_rnc, sandbox=sandbox)
            if contact:
                supplier_id = contact["id"]
                types = list(contact.get("types", []))
                if "proveedor" not in types:
                    types.append("proveedor")
                    contact_dict = dict(contact)
                    contact_dict["types"] = types
                    ContactService.save_contact(owner_uid, contact["id"], contact_dict, sandbox=sandbox)
            elif supplier_name:
                supplier_id = str(uuid.uuid4())
                ContactService.save_contact(owner_uid, supplier_id, {
                    "rnc": supplier_rnc,
                    "razonSocial": supplier_name,
                    "types": ["proveedor"],
                }, sandbox=sandbox)

        inv_data = {
            "invoiceNumber": sinv_number,
            "supplierInvoiceNumber": invoice_number,
            "ncf": ncf,
            "poId": po_id or '',
            "poNumber": (po.get("poNumber", "") if po else ""),
            "supplierId": supplier_id,
            "supplierName": supplier_name,
            "supplierRnc": supplier_rnc,
            "supplierType": request.form.get('supplierType', 'formal'),
            "ecfType": ecf_type,
            "cne": request.form.get('cne', ''),
            "date": inv_date,
            "dueDate": due_date,
            "paymentTerms": "contado" if payment_type == 'Contado' else "credito_30d",
            "currency": currency,
            "exchangeRate": exchange_rate,
            "subtotal": round(subtotal, 2),
            "itbis": round(total_itbis, 2),
            "discount": round(total_discount, 2),
            "total": round(total, 2),
            "items": items,
            "attachmentUrls": [],
            "notes": request.form.get('notes', ''),
            "comentario": request.form.get('comentario', ''),
            "tipoGastoDGII": request.form.get('tipoGastoDGII', '02'),
            "cxpStatus": cxp_status,
            "cxpRemainingBalance": round(cxp_remaining, 2),
            "paymentType": payment_type,
            "paymentMethod": request.form.get('paymentMethod', 'transferencia'),
            "bankAccountId": bank_account_id,
            "retainedISR": float(request.form.get('retainedISRRate', 0) or 0),
            "retainedITBIS": float(request.form.get('retainedITBISRate', 0) or 0),
            "createdBy": session['user'].get('displayName', 'Usuario'),
            "branchId": g.get('branch_id', 'default-sucursal-principal'),
            "projectId": request.form.get('projectId') or g.get('project_id'),
        }

        inv_data["id"] = SupplierInvoiceService.create(owner_uid, inv_data, sandbox=sandbox)["id"]

        # ── Generate accounting entry ──
        try:
            from app.services.accounting_service import AccountingService
            account_items = []
            for item in inv_data.get("items", []):
                line_value = (float(item.get("quantity", 0)) * float(item.get("unitPrice", 0)))
                line_disc = line_value * (float(item.get("discount", 0)) / 100.0)
                account_items.append({
                    "concept_id": item.get("accountingAccountId", ""),
                    "concept": item.get("name", ""),
                    "value": round(line_value - line_disc, 2),
                    "quantity": float(item.get("quantity", 0)),
                    "tax": float(item.get("itbisRate", 0)),
                    "total": float(item.get("total", 0)),
                })
            expense_dict = {
                "id": inv_data["id"],
                "providerName": inv_data.get("supplierName", ""),
                "supplierName": inv_data.get("supplierName", ""),
                "concept": f"Compra {inv_data.get('supplierInvoiceNumber', '')} - {inv_data.get('supplierName', '')}",
                "ncf": inv_data.get("ncf", ""),
                "amount": float(inv_data.get("total", 0)),
                "total": float(inv_data.get("total", 0)),
                "itbisAmount": float(inv_data.get("itbis", 0)),
                "itbis": float(inv_data.get("itbis", 0)),
                "date": inv_data.get("date", ""),
                "paymentType": inv_data.get("paymentType", "Contado"),
                "bankAccountId": inv_data.get("bankAccountId", ""),
                "retainedISR": float(inv_data.get("retainedISR", 0)),
                "retainedITBIS": float(inv_data.get("retainedITBIS", 0)),
                "accountItems": account_items,
                "isCost": False,
            }
            AccountingService.auto_generate_expense_entry(owner_uid, expense_dict, sandbox=sandbox)
        except Exception as acc_err:
            print(f"Error al generar asiento contable de factura proveedor: {acc_err}")

        # ── File upload after save (non-blocking with timeout) ──
        file_upload_error = None
        attachment_file = request.files.get('attachment')
        if attachment_file and attachment_file.filename:
            file_data = attachment_file.read()
            if len(file_data) > MAX_FILE_SIZE:
                file_upload_error = 'El archivo excede el límite de 10 MB.'
            else:
                mime_type = attachment_file.content_type or "application/octet-stream"
                if mime_type not in ALLOWED_MIME_TYPES:
                    file_upload_error = 'Tipo de archivo no permitido. Solo PDF, JPG y PNG.'
                else:
                    try:
                        public_url = SupplierInvoiceService.add_attachment(
                            owner_uid, inv_data["id"], file_data,
                            attachment_file.filename, mime_type, sandbox=sandbox
                        )
                        if not public_url:
                            file_upload_error = 'El archivo no pudo subirse.'
                    except Exception as e:
                        file_upload_error = str(e)
                        print(f"Error al subir archivo factura proveedor: {e}")

        ocr_attachment_url = request.form.get('ocr_attachment_url', '').strip()
        if ocr_attachment_url:
            inv = SupplierInvoiceService.get(owner_uid, inv_data["id"], sandbox=sandbox)
            if inv:
                urls = inv.get("attachmentUrls", [])
                urls.append(ocr_attachment_url)
                SupplierInvoiceService.update(owner_uid, inv_data["id"], {"attachmentUrls": urls}, sandbox=sandbox)

        if payment_type == 'Contado' and bank_account_id:
            try:
                bank_acc = DatabaseService.get_bank_account(owner_uid, bank_account_id, sandbox=sandbox)
                if bank_acc:
                    new_balance = bank_acc["currentBalance"] - round(total, 2)
                    DatabaseService.save_bank_account(owner_uid, bank_account_id, {
                        **bank_acc,
                        "currentBalance": new_balance
                    }, sandbox=sandbox)
            except Exception as bank_err:
                print(f"Error al actualizar saldo bancario en factura directa: {bank_err}")

        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_CREATE, module=MODULE_SINV,
            entity_id=inv_data["id"],
            entity_label=f"Factura Proveedor {sinv_number} - {inv_data.get('supplierName', '')}",
            after=inv_data, sandbox=sandbox
        )

        msg = f'Factura proveedor {sinv_number} registrada exitosamente.'
        if file_upload_error:
            msg += ' El archivo no pudo subirse. Puede adjuntarlo después desde el detalle.'
        flash(msg, 'success')
        if request.form.get('save_action') == 'save_and_new':
            flash('Factura de compra guardada. Puedes crear otra.', 'success')
            return redirect(url_for('web_purchase_orders.new_supplier_invoice_direct'))
        return redirect(url_for('web_purchase_orders.supplier_invoice_detail', invoice_id=inv_data['id']))

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    suppliers = SupplierService.get_suppliers(owner_uid, sandbox=sandbox)
    bank_accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox)
    accounting_accounts = DatabaseService.get_chart_of_accounts(owner_uid)
    tax_rules = DatabaseService.get_tax_rules(owner_uid)
    itbis_general = tax_rules.get('itbis', {}).get('general', 0.18)
    itbis_reduced = tax_rules.get('itbis', {}).get('reduced', 0.16)
    selected_bid = g.get('branch_id') or session.get('selected_branch_id')
    projects = DatabaseService.get_projects(owner_uid, branch_id=selected_bid, sandbox=sandbox) if selected_bid else []
    active_project_id = session.get('selected_project_id') or ''
    return render_template('purchase_orders/new_invoice.html',
                           today=today,
                           suppliers=suppliers,
                           bank_accounts=bank_accounts,
                           accounting_accounts=accounting_accounts,
                           itbis_general=itbis_general,
                           itbis_reduced=itbis_reduced,
                           projects=projects,
                           active_project_id=active_project_id,
                           po=po,
                           po_id=po_id,
                           po_supplier_name=po_supplier_name,
                           po_supplier_rnc=po_supplier_rnc,
                           po_supplier_id=po_supplier_id,
                           po_currency=po_currency,
                           po_exchange_rate=po_exchange_rate,
                           po_payment_terms=po_payment_terms,
                           active_page='purchase_cxp')


@web_purchase_orders_bp.route('/purchase-orders/<po_id>/register-invoice', methods=['GET', 'POST'])
def register_supplier_invoice(po_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        return render_template('auth/restricted.html', required_permission="canManagePurchaseCXP")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    po = PurchaseOrderService.get_purchase_order(owner_uid, po_id, sandbox=sandbox)
    if not po:
        flash('❌ Orden de compra no encontrada.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_orders'))

    po_status = po.get('status', '')
    if po_status not in ('recibida_parcial', 'recibida_completa'):
        flash('❌ Solo se pueden facturar órdenes con recepción parcial o completa.', 'error')
        return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))

    po_items = po.get('items', [])
    total_received = sum(float(item.get('receivedQuantity', 0)) for item in po_items)
    if total_received <= 0:
        flash('❌ La orden de compra no tiene cantidades recibidas. Debe recibir mercancía antes de facturar.', 'error')
        return redirect(url_for('web_purchase_orders.purchase_order_detail', po_id=po_id))

    if request.method == 'POST':
        invoice_number = request.form.get('invoiceNumber', '').strip()
        if not invoice_number:
            flash('❌ El número de factura del proveedor es obligatorio.', 'error')
            return render_template('purchase_orders/register_invoice.html', po=po, today=datetime.now(timezone.utc).strftime('%Y-%m-%d'), active_page='purchase_orders')

        if not SupplierInvoiceService._check_ncf_unique(owner_uid, invoice_number, sandbox=sandbox):
            flash('❌ El número de factura del proveedor o NCF ya existe. Verifique los datos.', 'error')
            return render_template('purchase_orders/register_invoice.html', po=po, today=datetime.now(timezone.utc).strftime('%Y-%m-%d'), active_page='purchase_orders')

        ncf = request.form.get('ncf', '').strip()
        inv_date = request.form.get('date', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
        due_date = request.form.get('dueDate', '')
        notes = request.form.get('notes', '').strip()

        today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        if inv_date > today_str:
            flash('❌ La fecha de emisión no puede ser futura.', 'error')
            return render_template('purchase_orders/register_invoice.html', po=po, today=today_str, active_page='purchase_orders')
        if due_date and due_date < inv_date:
            flash('❌ La fecha de vencimiento no puede ser anterior a la fecha de emisión.', 'error')
            return render_template('purchase_orders/register_invoice.html', po=po, today=today_str, active_page='purchase_orders')

        if ncf and not SupplierInvoiceService._check_ncf_unique(owner_uid, ncf, sandbox=sandbox):
            flash('❌ El NCF ya está registrado en otra factura.', 'error')
            return render_template('purchase_orders/register_invoice.html', po=po, today=today_str, active_page='purchase_orders')

        items = []
        subtotal = 0.0
        total_itbis = 0.0
        total_discount = 0.0
        for item in po_items:
            qty = float(item.get('receivedQuantity', item.get('quantity', 0)))
            price = float(item.get('unitPrice', 0))
            itbis_rate = float(item.get('itbisRate', 0))
            discount_pct = float(item.get('discount', 0))
            line_sub = qty * price
            line_discount = line_sub * (discount_pct / 100.0)
            line_itbis = (line_sub - line_discount) * itbis_rate
            line_total = line_sub - line_discount + line_itbis
            subtotal += line_sub
            total_discount += line_discount
            total_itbis += line_itbis
            items.append({
                "poItemId": item.get("id", ""),
                "itemName": item.get("name", ""),
                "quantity": qty,
                "unitPrice": price,
                "itbisRate": itbis_rate,
                "discount": discount_pct,
                "subtotal": round(line_sub, 2),
                "itbisAmount": round(line_itbis, 2),
                "total": round(line_total, 2),
            })

        total = subtotal - total_discount + total_itbis
        sinv_number = SupplierInvoiceService.get_next_invoice_number(owner_uid, sandbox=sandbox)

        inv_data = {
            "invoiceNumber": sinv_number,
            "supplierInvoiceNumber": invoice_number,
            "ncf": ncf,
            "poId": po_id,
            "poNumber": po.get("poNumber", ""),
            "supplierId": po.get("supplierId", ""),
            "supplierName": po.get("supplierName", ""),
            "supplierRnc": po.get("supplierRnc", ""),
            "date": inv_date,
            "dueDate": due_date,
            "paymentTerms": po.get("paymentTerms", "contado"),
            "currency": po.get("currency", "DOP"),
            "exchangeRate": float(po.get("exchangeRate", 1.0)),
            "subtotal": round(subtotal, 2),
            "itbis": round(total_itbis, 2),
            "discount": round(total_discount, 2),
            "total": round(total, 2),
            "items": items,
            "attachmentUrls": [],
            "notes": notes,
            "createdBy": session['user'].get('displayName', 'Usuario'),
        }

        inv_data["id"] = SupplierInvoiceService.create(owner_uid, inv_data, sandbox=sandbox)["id"]

        # ── Generate accounting entry ──
        try:
            from app.services.accounting_service import AccountingService
            account_items = []
            for item in inv_data.get("items", []):
                line_value = (float(item.get("quantity", 0)) * float(item.get("unitPrice", 0)))
                line_disc = line_value * (float(item.get("discount", 0)) / 100.0)
                account_items.append({
                    "concept_id": "",
                    "concept": item.get("itemName", ""),
                    "value": round(line_value - line_disc, 2),
                    "quantity": float(item.get("quantity", 0)),
                    "tax": float(item.get("itbisRate", 0)),
                    "total": float(item.get("total", 0)),
                })
            expense_dict = {
                "id": inv_data["id"],
                "providerName": inv_data.get("supplierName", ""),
                "supplierName": inv_data.get("supplierName", ""),
                "concept": f"Compra {inv_data.get('supplierInvoiceNumber', '')} - {inv_data.get('supplierName', '')}",
                "ncf": inv_data.get("ncf", ""),
                "amount": float(inv_data.get("total", 0)),
                "total": float(inv_data.get("total", 0)),
                "itbisAmount": float(inv_data.get("itbis", 0)),
                "itbis": float(inv_data.get("itbis", 0)),
                "date": inv_data.get("date", ""),
                "paymentType": "Crédito",
                "retainedISR": 0.0,
                "retainedITBIS": 0.0,
                "accountItems": account_items,
                "isCost": True,
            }
            AccountingService.auto_generate_expense_entry(owner_uid, expense_dict, sandbox=sandbox)
        except Exception as acc_err:
            print(f"Error al generar asiento contable de factura desde OC: {acc_err}")

        # ── File upload after save (non-blocking with timeout) ──
        file_upload_error = None
        attachment_file = request.files.get('attachment')
        if attachment_file and attachment_file.filename:
            file_data = attachment_file.read()
            if len(file_data) > MAX_FILE_SIZE:
                file_upload_error = 'El archivo excede el límite de 10 MB.'
            else:
                mime_type = attachment_file.content_type or "application/octet-stream"
                if mime_type not in ALLOWED_MIME_TYPES:
                    file_upload_error = 'Tipo de archivo no permitido. Solo PDF, JPG y PNG.'
                else:
                    try:
                        public_url = SupplierInvoiceService.add_attachment(
                            owner_uid, inv_data["id"], file_data,
                            attachment_file.filename, mime_type, sandbox=sandbox
                        )
                        if not public_url:
                            file_upload_error = 'El archivo no pudo subirse.'
                    except Exception as e:
                        file_upload_error = str(e)
                        print(f"⚠️ Error al subir PDF factura proveedor: {e}")

        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_CREATE, module=MODULE_SINV,
            entity_id=inv_data["id"],
            entity_label=f"Factura Proveedor {sinv_number} - {inv_data.get('supplierName', '')}",
            after=inv_data, sandbox=sandbox
        )

        msg = f'✅ Factura proveedor {sinv_number} registrada exitosamente.'
        if file_upload_error:
            msg += ' ⚠️ El PDF no pudo subirse. Puede adjuntarlo después desde el detalle.'
        flash(msg, 'success')
        return redirect(url_for('web_purchase_orders.supplier_invoice_detail', invoice_id=inv_data['id']))

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return render_template('purchase_orders/register_invoice.html',
                           po=po, today=today, active_page='purchase_orders')


@web_purchase_orders_bp.route('/purchase-orders/invoices/<invoice_id>')
def supplier_invoice_detail(invoice_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        return render_template('auth/restricted.html', required_permission="canManagePurchaseCXP")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoice = SupplierInvoiceService.get(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('❌ Factura proveedor no encontrada.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_cxp'))

    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    status = invoice.get('cxpStatus', 'Pendiente')
    due_date = invoice.get('dueDate', '')
    if status in ('Pendiente', 'Abonado') and due_date and due_date < today_str:
        invoice['cxpStatus'] = 'Vencido'

    payments = SupplierInvoiceService.get_payments(owner_uid, invoice_id, sandbox=sandbox)
    bank_accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox)

    comments = DatabaseService.get_resource_comments(owner_uid, "purchase_orders", invoice_id, sandbox=sandbox)
    taggable_users = _get_taggable_users(owner_uid)

    is_cxp = invoice.get('paymentType') == 'Crédito'

    linked_entry = None
    all_entries = DatabaseService.get_accounting_entries(owner_uid, sandbox=sandbox)
    for e in all_entries:
        if e.get("status") != "voided" and e.get("referenceId") == invoice_id and e.get("referenceType") in ("supplier_invoice", "expense"):
            linked_entry = e
            break

    return render_template('purchase_orders/supplier_invoice_detail.html',
                           invoice=invoice, payments=payments,
                           bank_accounts=bank_accounts,
                           comments=comments, taggable_users=taggable_users,
                           format_mentions=format_mentions,
                           is_cxp=is_cxp, cxp_payments=payments,
                           linked_entry=linked_entry,
                           active_page='purchase_cxp')


@web_purchase_orders_bp.route('/purchase-orders/invoices/<invoice_id>/pay', methods=['POST'])
def pay_supplier_invoice(invoice_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        flash('❌ No tienes permiso para registrar pagos.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_cxp'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    try:
        amount = float(request.form.get('amount', 0))
    except (ValueError, TypeError):
        amount = 0
    if amount <= 0:
        flash('❌ El monto debe ser mayor a 0.', 'error')
        return redirect(url_for('web_purchase_orders.supplier_invoice_detail', invoice_id=invoice_id))

    payment_method = request.form.get('paymentMethod', '').strip()
    payment_reference = request.form.get('paymentReference', '').strip()
    bank_account_id = request.form.get('bankAccountId', '').strip()
    registered_by = session['user'].get('displayName', 'Usuario')

    success, message = SupplierInvoiceService.save_payment(
        owner_uid, invoice_id, amount, registered_by=registered_by,
        sandbox=sandbox, payment_method=payment_method,
        payment_reference=payment_reference,
        bank_account_id=bank_account_id
    )

    if success:
        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_SINV,
            entity_id=invoice_id,
            entity_label=f"Pago registrado: RD$ {amount:,.2f}",
            sandbox=sandbox
        )
    flash(message, 'success' if success else 'error')
    return redirect(url_for('web_purchase_orders.supplier_invoice_detail', invoice_id=invoice_id))


@web_purchase_orders_bp.route('/purchase-orders/invoices/<invoice_id>/edit', methods=['GET', 'POST'])
def edit_supplier_invoice(invoice_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        return render_template('auth/restricted.html', required_permission="canManagePurchaseCXP")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoice = SupplierInvoiceService.get(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        flash('❌ Factura proveedor no encontrada.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_cxp'))

    if request.method == 'POST':
        updates = {}
        notes = request.form.get('notes', '').strip()
        if notes != invoice.get('notes', ''):
            updates['notes'] = notes
        due_date = request.form.get('dueDate', '')
        if due_date and due_date != invoice.get('dueDate', ''):
            updates['dueDate'] = due_date
        date = request.form.get('date', '')
        if date and date != invoice.get('date', ''):
            updates['date'] = date

        if updates:
            SupplierInvoiceService.update(owner_uid, invoice_id, updates, sandbox=sandbox)
            AuditService.log_from_request(
                owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_SINV,
                entity_id=invoice_id,
                entity_label=f"Factura Proveedor {invoice.get('invoiceNumber', '')} editada",
                sandbox=sandbox
            )
            flash('✅ Factura actualizada.', 'success')
        else:
            flash('ℹ️ No hay cambios para guardar.', 'info')
        return redirect(url_for('web_purchase_orders.supplier_invoice_detail', invoice_id=invoice_id))

    return render_template('purchase_orders/edit_supplier_invoice.html',
                           invoice=invoice, active_page='purchase_cxp')


@web_purchase_orders_bp.route('/purchase-orders/invoices/<invoice_id>/add-attachment', methods=['POST'])
def add_invoice_attachment(invoice_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoice = SupplierInvoiceService.get(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        return jsonify(success=False, error="Factura no encontrada"), 404

    attachment_file = request.files.get('attachment')
    if not attachment_file or not attachment_file.filename:
        return jsonify(success=False, error="No se seleccionó archivo"), 400

    file_data = attachment_file.read()
    if len(file_data) > MAX_FILE_SIZE:
        return jsonify(success=False, error="El archivo excede el límite de 10 MB"), 400

    mime_type = attachment_file.content_type or "application/octet-stream"
    if mime_type not in ALLOWED_MIME_TYPES:
        return jsonify(success=False, error="Tipo de archivo no permitido"), 400

    url = SupplierInvoiceService.add_attachment(owner_uid, invoice_id, file_data,
                                                 attachment_file.filename, mime_type, sandbox=sandbox)
    if url:
        return jsonify(success=True, url=url)
    return jsonify(success=False, error="Error al subir archivo"), 500


@web_purchase_orders_bp.route('/purchase-orders/invoices/<invoice_id>/void-payment/<payment_id>', methods=['POST'])
def void_payment(invoice_id, payment_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        flash('❌ No tienes permiso para revertir pagos.', 'error')
        return redirect(url_for('web_purchase_orders.list_purchase_cxp'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    success, message = SupplierInvoiceService.void_payment(owner_uid, invoice_id, payment_id, sandbox=sandbox)
    if success:
        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_SINV,
            entity_id=invoice_id,
            entity_label=f"Pago revertido en factura {invoice_id}",
            sandbox=sandbox
        )
    flash(message, 'success' if success else 'error')
    return redirect(url_for('web_purchase_orders.supplier_invoice_detail', invoice_id=invoice_id))


@web_purchase_orders_bp.route('/purchase-orders/invoices/<invoice_id>/delete', methods=['POST'])
def delete_supplier_invoice(invoice_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        flash('No tienes permiso para eliminar facturas de proveedor.', 'error')
        return redirect(url_for('web_purchase_orders.consolidated_cxp'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    inv = None
    try:
        invoices = SupplierInvoiceService.get_all(owner_uid, sandbox=sandbox)
        inv = next((i for i in invoices if i['id'] == invoice_id), None)
    except Exception:
        pass

    SupplierInvoiceService.delete(owner_uid, invoice_id, sandbox=sandbox)

    AuditService.log_from_request(
        owner_uid=owner_uid, action=ACTION_DELETE, module=MODULE_SINV,
        entity_id=invoice_id,
        entity_label=f"Factura proveedor eliminada: {inv.get('invoiceNumber', 'N/A')} (Proveedor: {inv.get('supplierName', 'N/A')})" if inv else f"Factura proveedor eliminada: {invoice_id}",
        user_session=session.get('user', {}),
        before=inv or {},
        sandbox=sandbox
    )
    flash('Factura de proveedor eliminada.', 'success')
    return redirect(url_for('web_purchase_orders.consolidated_cxp'))


@web_purchase_orders_bp.route('/purchase-orders/cxp/delete-expense/<expense_id>', methods=['POST'])
def delete_cxp_expense(expense_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageCXP'):
        flash('No tienes permiso para eliminar cuentas por pagar.', 'error')
        return redirect(url_for('web_purchase_orders.consolidated_cxp'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    before_expense = {}
    try:
        expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
        before_expense = next((e for e in expenses if e['id'] == expense_id), {})
    except Exception:
        pass

    DatabaseService.delete_expense(owner_uid, expense_id, sandbox=sandbox)

    from app.services.audit_service import ACTION_DELETE as AD, MODULE_GASTOS
    AuditService.log_from_request(
        owner_uid=owner_uid, action=AD, module=MODULE_GASTOS,
        entity_id=expense_id,
        entity_label=f"Gasto eliminado desde CxP: {before_expense.get('concept', 'N/A')}",
        user_session=session.get('user', {}),
        before=before_expense,
        sandbox=sandbox
    )
    flash('Gasto eliminado.', 'success')
    return redirect(url_for('web_purchase_orders.consolidated_cxp'))


@web_purchase_orders_bp.route('/api/purchase-orders/invoices/next-number')
def api_next_supplier_invoice_number():
    if 'user' not in session:
        return jsonify(success=False, error="No autorizado"), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    number = SupplierInvoiceService.get_next_invoice_number(owner_uid, sandbox=sandbox)
    return jsonify(success=True, invoiceNumber=number)


# ═════════════════════════════════════════════════════════════════════
# NOTAS DE CRÉDITO EN COMPRAS
# ═════════════════════════════════════════════════════════════════════

MODULE_CN = "Notas de Crédito en Compras"


@web_purchase_orders_bp.route('/purchase-orders/credit-notes')
def list_credit_notes():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        return render_template('auth/restricted.html', feature_name=MODULE_CN, required_permission="canManagePurchaseCXP")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    notes = PurchaseCreditNoteService.get_all(owner_uid, sandbox=sandbox)

    search_query = request.args.get('search', '').strip().lower()
    if search_query:
        filtered = []
        for n in notes:
            haystack = f"{n.get('creditNoteNumber', '')} {n.get('creditedSupplierName', '')} {n.get('creditedInvoiceNumber', '')} {n.get('concept', '')}".lower()
            if search_query in haystack:
                filtered.append(n)
        notes = filtered

    return render_template('purchase_orders/credit_notes_list.html',
                           notes=notes, search_query=search_query,
                           active_page='purchase_credit_notes')


@web_purchase_orders_bp.route('/purchase-orders/credit-notes/new', methods=['GET', 'POST'])
def new_credit_note():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        return render_template('auth/restricted.html', feature_name=MODULE_CN, required_permission="canManagePurchaseCXP")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    if request.method == 'POST':
        credited_invoice_id = request.form.get('creditedInvoiceId', '')
        if not credited_invoice_id:
            flash('❌ Debes seleccionar una factura de proveedor.', 'error')
            return redirect(url_for('web_purchase_orders.new_credit_note'))

        try:
            amount = float(request.form.get('amount', 0))
        except (ValueError, TypeError):
            amount = 0
        if amount <= 0:
            flash('❌ El monto debe ser mayor a 0.', 'error')
            return redirect(url_for('web_purchase_orders.new_credit_note'))

        inv = SupplierInvoiceService.get(owner_uid, credited_invoice_id, sandbox=sandbox)
        if not inv:
            flash('❌ Factura de proveedor no encontrada.', 'error')
            return redirect(url_for('web_purchase_orders.new_credit_note'))

        rem_bal = float(inv.get('cxpRemainingBalance', inv.get('total', 0)))
        if amount > rem_bal:
            flash(f'❌ El monto (RD$ {amount:,.2f}) excede el saldo pendiente (RD$ {rem_bal:,.2f}).', 'error')
            return redirect(url_for('web_purchase_orders.new_credit_note'))

        created_by = session['user'].get('displayName', 'Usuario')
        note_data = {
            "creditedInvoiceId": credited_invoice_id,
            "creditedInvoiceNumber": inv.get('invoiceNumber', ''),
            "creditedSupplierName": inv.get('supplierName', ''),
            "creditedSupplierRnc": inv.get('supplierRnc', ''),
            "amount": amount,
            "date": request.form.get('date', datetime.now(timezone.utc).strftime('%Y-%m-%d')),
            "concept": request.form.get('concept', '').strip(),
            "notes": request.form.get('notes', '').strip(),
            "createdBy": created_by,
        }

        success, message = PurchaseCreditNoteService.create(owner_uid, note_data, sandbox=sandbox)
        flash(message, 'success' if success else 'error')

        if success:
            AuditService.log_from_request(
                owner_uid=owner_uid, action=ACTION_CREATE, module=MODULE_CN,
                entity_id=note_data.get("id", ""),
                entity_label=f"NC Compra {note_data.get('creditNoteNumber', '')} - {note_data.get('creditedSupplierName', '')}",
                sandbox=sandbox
            )
        return redirect(url_for('web_purchase_orders.list_credit_notes'))

    invoices = SupplierInvoiceService.get_all(owner_uid, sandbox=sandbox)
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    return render_template('purchase_orders/credit_note_form.html',
                           invoices=invoices, today_str=today_str,
                           active_page='purchase_credit_notes')


@web_purchase_orders_bp.route('/purchase-orders/credit-notes/<note_id>')
def credit_note_detail(note_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        return render_template('auth/restricted.html', feature_name=MODULE_CN, required_permission="canManagePurchaseCXP")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    note = PurchaseCreditNoteService.get(owner_uid, note_id, sandbox=sandbox)
    if not note:
        flash('❌ Nota de crédito no encontrada.', 'error')
        return redirect(url_for('web_purchase_orders.list_credit_notes'))
    return render_template('purchase_orders/credit_note_detail.html',
                           note=note, active_page='purchase_credit_notes')


@web_purchase_orders_bp.route('/purchase-orders/credit-notes/<note_id>/void', methods=['POST'])
def void_credit_note(note_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManagePurchaseCXP'):
        flash('❌ No tienes permiso para anular notas de crédito.', 'error')
        return redirect(url_for('web_purchase_orders.list_credit_notes'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    note = PurchaseCreditNoteService.get(owner_uid, note_id, sandbox=sandbox)
    success, message = PurchaseCreditNoteService.void(owner_uid, note_id, sandbox=sandbox)
    if success:
        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_CN,
            entity_id=note_id,
            entity_label=f"NC Compra anulada: {note.get('creditNoteNumber', '')}" if note else f"NC {note_id}",
            sandbox=sandbox
        )
    flash(message, 'success' if success else 'error')
    return redirect(url_for('web_purchase_orders.list_credit_notes'))


@web_purchase_orders_bp.route('/purchase-orders/invoices/<invoice_id>/retention-letter')
def supplier_retention_letter(invoice_id):
    if 'user' not in session: return "No autorizado", 401
    if not check_permission('canManagePurchaseCXP'):
        return "Acceso denegado: requiere permiso de CxP", 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoice = SupplierInvoiceService.get(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        return "Factura no encontrada", 404

    company = DatabaseService.get_company_profile(owner_uid)

    retained_isr_rate = float(invoice.get('retainedISR', 0) or 0)
    retained_itbis_rate = float(invoice.get('retainedITBIS', 0) or 0)
    if retained_isr_rate <= 0 and retained_itbis_rate <= 0:
        return "Esta factura no tiene retenciones aplicadas", 400

    total = float(invoice.get('total', 0) or 0)
    total_itbis = float(invoice.get('itbis', 0) or 0)
    retained_isr = round(total * retained_isr_rate, 2)
    retained_itbis = round(total_itbis * retained_itbis_rate, 2)
    retention_percent = round((retained_itbis / total_itbis) * 100) if total_itbis > 0 else 0
    retained_total = retained_isr + retained_itbis
    net_amount = total - retained_total

    payment_type = invoice.get('paymentType', 'Contado')
    method_labels = {'Contado': 'Contado / Efectivo', 'Crédito': 'Crédito'}
    payment_method = method_labels.get(payment_type, payment_type)

    from datetime import datetime
    now = datetime.now()

    doc_num = invoice.get('ncf') or invoice.get('invoiceNumber', '') or invoice_id
    inv_num = doc_num.replace('/', '-').replace(' ', '_')

    representative_name = session['user'].get('name', '')
    representative_id = session['user'].get('cedula', '')

    invoice_wrapper = {
        'invoiceNumber': doc_num,
        'clientName': invoice.get('supplierName', 'Proveedor'),
        'clientRNC': invoice.get('supplierRnc', ''),
        'total': total,
        'totalITBIS': total_itbis,
        'concept': invoice.get('notes', 'Compra de bienes/servicios'),
        'date': invoice.get('date', ''),
        'paymentDate': invoice.get('date', ''),
    }

    action = request.args.get('action', 'download')

    if WEASYPRINT_AVAILABLE and action == 'download':
        rendered_html = render_template('invoices/retention_letter.html',
            invoice=invoice_wrapper, company=company, now=now,
            retained_isr=retained_isr, retained_itbis=retained_itbis,
            retained_total=retained_total, retention_percent=retention_percent,
            net_amount=net_amount, payment_method=payment_method,
            representative_name=representative_name, representative_id=representative_id,
            auto_print=False)
        pdf_bytes = WeasyprintHTML(string=rendered_html, base_url=request.host_url).write_pdf()
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename="Carta_Retencion_{inv_num}.pdf"'
        return response
    else:
        rendered_html = render_template('invoices/retention_letter.html',
            invoice=invoice_wrapper, company=company, now=now,
            retained_isr=retained_isr, retained_itbis=retained_itbis,
            retained_total=retained_total, retention_percent=retention_percent,
            net_amount=net_amount, payment_method=payment_method,
            representative_name=representative_name, representative_id=representative_id,
            auto_print=True)
        response = make_response(rendered_html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        return response


@web_purchase_orders_bp.route('/purchase-orders/invoices/<invoice_id>/retention-letter/email', methods=['POST'])
def supplier_retention_letter_email(invoice_id):
    if 'user' not in session: return jsonify(success=False, error="No autorizado"), 401
    if not check_permission('canManagePurchaseCXP'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoice = SupplierInvoiceService.get(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        return jsonify(success=False, error="Factura no encontrada"), 404

    company = DatabaseService.get_company_profile(owner_uid)

    retained_isr_rate = float(invoice.get('retainedISR', 0) or 0)
    retained_itbis_rate = float(invoice.get('retainedITBIS', 0) or 0)
    if retained_isr_rate <= 0 and retained_itbis_rate <= 0:
        return jsonify(success=False, error="Esta factura no tiene retenciones aplicadas"), 400

    total = float(invoice.get('total', 0) or 0)
    total_itbis = float(invoice.get('itbis', 0) or 0)
    retained_isr = round(total * retained_isr_rate, 2)
    retained_itbis = round(total_itbis * retained_itbis_rate, 2)
    retention_percent = round((retained_itbis / total_itbis) * 100) if total_itbis > 0 else 0
    retained_total = retained_isr + retained_itbis
    net_amount = total - retained_total

    payment_type = invoice.get('paymentType', 'Contado')
    method_labels = {'Contado': 'Contado / Efectivo', 'Crédito': 'Crédito'}
    payment_method = method_labels.get(payment_type, payment_type)

    from datetime import datetime
    now = datetime.now()
    representative_name = session['user'].get('name', '')
    representative_id = session['user'].get('cedula', '')

    doc_num = invoice.get('ncf') or invoice.get('invoiceNumber', '') or invoice_id
    inv_num = doc_num.replace('/', '-').replace(' ', '_')

    invoice_wrapper = {
        'invoiceNumber': doc_num,
        'clientName': invoice.get('supplierName', 'Proveedor'),
        'clientRNC': invoice.get('supplierRnc', ''),
        'total': total,
        'totalITBIS': total_itbis,
        'concept': invoice.get('notes', 'Compra de bienes/servicios'),
        'date': invoice.get('date', ''),
        'paymentDate': invoice.get('date', ''),
    }

    rendered_html = render_template('invoices/retention_letter.html',
        invoice=invoice_wrapper, company=company, now=now,
        retained_isr=retained_isr, retained_itbis=retained_itbis,
        retained_total=retained_total, retention_percent=retention_percent,
        net_amount=net_amount, payment_method=payment_method,
        representative_name=representative_name, representative_id=representative_id,
        auto_print=False)

    pdf_bytes = None
    if WEASYPRINT_AVAILABLE:
        pdf_bytes = WeasyprintHTML(string=rendered_html, base_url=request.host_url).write_pdf()
    else:
        import io
        try:
            pdf_bytes = WeasyprintHTML(string=rendered_html, base_url=request.host_url).write_pdf()
        except:
            pdf_bytes = rendered_html.encode('utf-8')

    recipient_email = request.form.get('email', '').strip()
    if not recipient_email:
        recipient_email = invoice.get('email', '')
    if not recipient_email:
        return jsonify(success=False, error="No se encontró correo del proveedor. Especifica un correo electrónico."), 400

    try:
        from flask import current_app as app

        if not app.config.get("SMTP_USER") or not app.config.get("SMTP_PASSWORD"):
            return jsonify(success=False, error="Servidor de correo no configurado (SMTP)."), 400

        company_name = company.get('companyName', 'Mi Empresa')

        email_html = f"""
        <html><body style="font-family:Arial,sans-serif;padding:20px;">
        <h2 style="color:{company.get('colorMarca', '#10b981')};">Carta de Retención — {company_name}</h2>
        <p>Estimado(a) <strong>{invoice.get('supplierName', 'Proveedor')}</strong>,</p>
        <p>Adjunto encontrará la Carta de Retención correspondiente al comprobante <strong>{doc_num}</strong> por un monto retenido de <strong>RD$ {retained_total:,.2f}</strong>.</p>
        <p>Puede descargar el documento adjunto para sus registros contables.</p>
        <hr>
        <p style="font-size:12px;color:#888;">Este mensaje fue generado automáticamente por {company_name}. Favor no responder a este correo.</p>
        </body></html>
        """

        from app.services.mailer import Mailer
        mailer = Mailer()
        attachments = [("Carta_Retencion_{}.pdf".format(inv_num), pdf_bytes, "application/pdf")] if pdf_bytes else []

        mailer.send(
            app=app._get_current_object(),
            to_email=recipient_email,
            subject=f"Carta de Retención — Comprobante {doc_num} — {company_name}",
            html_body=email_html,
            from_name=company_name,
            category="Retención",
            attachments=attachments
        )

        return jsonify(success=True, message="Carta de retención enviada correctamente.")
    except Exception as e:
        return jsonify(success=False, error=f"Error al enviar correo: {str(e)}"), 500
