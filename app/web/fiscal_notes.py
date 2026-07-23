import uuid
import json
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, g
from app.services.db_service import DatabaseService
from app.utils.decorators import require_permission, check_permission
from app.services.dgii import DGIIService
from app.models.fiscal_document_type import by_code as _by_code

web_fiscal_notes_bp = Blueprint('web_fiscal_notes', __name__)


@web_fiscal_notes_bp.before_request
def restrict_to_do():
    if session.get('company_country', 'DO') != 'DO':
        return render_template('auth/restricted.html',
            feature_name="Notas Fiscales e-CF (solo disponibles para República Dominicana)",
            required_permission="")


@web_fiscal_notes_bp.route('/fiscal-notes')
@require_permission('canInvoice', 'Notas Fiscales')
def list_fiscal_notes():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, company_id=company_id)
    credit_debit = [inv for inv in invoices if inv.get('ecfType') in ('Nota de Crédito (E34)', 'Nota de Débito (E33)')]
    credit_debit.sort(key=lambda x: x.get('createdAt', ''), reverse=True)

    return render_template('fiscal_notes/list.html', notes=credit_debit, active_page='fiscal_notes')


@web_fiscal_notes_bp.route('/fiscal-notes/create', methods=['GET'])
def create_fiscal_note():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    note_type = request.args.get('type', _by_code("E34").code)
    if note_type not in ('E34', 'E33'):
        flash('❌ Tipo de nota inválido. Use E34 (Crédito) o E33 (Débito).', 'error')
        return redirect(url_for('web_fiscal_notes.list_fiscal_notes'))

    ref_invoice_id = request.args.get('reference_invoice_id', '')
    ref_invoice = None
    if ref_invoice_id:
        ref_invoice = DatabaseService.get_invoice(owner_uid, ref_invoice_id, sandbox=sandbox, company_id=company_id)
        if not ref_invoice:
            flash('❌ Factura de referencia no encontrada.', 'error')
            return redirect(url_for('web_fiscal_notes.list_fiscal_notes'))

    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, company_id=company_id)
    real_invoices = [inv for inv in invoices if not inv.get('isQuotation') and inv.get('status') not in ('Anulada', 'Borrador')
                     and inv.get('ecfType') not in ('Nota de Crédito (E34)', 'Nota de Débito (E33)', 'Cotización')]

    catalog = DatabaseService.get_items(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'), company_id=company_id) or []
    catalog_json = json.dumps(catalog, default=str)

    # Data for "Más ajustes" sidebar
    all_sequences = DatabaseService.get_sequences(owner_uid, sandbox=sandbox, company_id=company_id) or []
    note_sequences = [s for s in all_sequences if s.get('tipoComprobante') == note_type
                      and s.get('estado', '').upper() == 'ACTIVA'
                      and not s.get('bloqueadaManualmente', False)]
    warehouses = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox, company_id=company_id) or []
    price_lists = DatabaseService.get_price_lists(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'), company_id=company_id) or []
    active_price_lists = [pl for pl in price_lists if pl.get('isActive', True)]
    default_price_list = next((pl for pl in active_price_lists if pl.get('isDefault')), None)
    default_price_list_id = default_price_list['id'] if default_price_list else ''
    sellers = DatabaseService.get_team_members(owner_uid, company_id=company_id) or []

    return render_template('fiscal_notes/form.html',
                           note_type=note_type,
                           ref_invoice=ref_invoice,
                           invoices=real_invoices,
                           catalog_json=catalog_json,
                           sequences=note_sequences,
                           warehouses=warehouses,
                           price_lists=active_price_lists,
                           default_price_list_id=default_price_list_id,
                           sellers=sellers,
                           active_page='fiscal_notes')


@web_fiscal_notes_bp.route('/fiscal-notes/create', methods=['POST'])
def save_fiscal_note():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    user = session['user']

    note_type = request.form.get('noteType', _by_code("E34").code)
    ref_invoice_id = request.form.get('referenceInvoiceId', '').strip()
    modification_code = request.form.get('modificationCode', '1')
    reason = request.form.get('reason', '').strip()
    date = request.form.get('date', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
    comentario = request.form.get('comentario', '').strip()
    warehouse_id = request.form.get('warehouseId', '').strip()
    price_list_id = request.form.get('priceListId', '').strip()
    seller_id = request.form.get('sellerId', '').strip()
    sequence_id = request.form.get('sequenceId', '').strip()

    if not ref_invoice_id:
        flash('❌ Debes seleccionar una factura de referencia.', 'error')
        return redirect(url_for('web_fiscal_notes.create_fiscal_note', type=note_type))

    ref_invoice = DatabaseService.get_invoice(owner_uid, ref_invoice_id, sandbox=sandbox, company_id=company_id)
    if not ref_invoice:
        flash('❌ Factura de referencia no encontrada.', 'error')
        return redirect(url_for('web_fiscal_notes.list_fiscal_notes'))

    ref_total = float(ref_invoice.get('netPayable', ref_invoice.get('total', 0)))

    ecf_type_label = 'Nota de Crédito (E34)' if note_type == 'E34' else 'Nota de Débito (E33)'

    if ref_invoice.get('status') in ('Borrador', 'Anulada'):
        flash('❌ No puedes crear una nota basada en un documento no emitido o anulado.', 'error')
        return redirect(url_for('web_fiscal_notes.list_fiscal_notes'))

    if ref_invoice.get('emisionMode') == 'FALLBACK' and not ref_invoice.get('isSyncedWithDGII', False):
        flash('❌ La factura de referencia está en contingencia y no ha sido aceptada por la DGII.', 'error')
        return redirect(url_for('web_fiscal_notes.list_fiscal_notes'))

    # Parse items from dynamic form
    parsed_items = []
    form_keys = request.form.keys()
    item_indices = set()
    for k in form_keys:
        if k.startswith('items['):
            parts = k.split(']')
            idx = parts[0].replace('items[', '')
            if idx.isdigit():
                item_indices.add(int(idx))

    catalog = DatabaseService.get_items(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'), company_id=company_id) or []
    catalog_types = {it['name'].lower().strip(): it.get('type', 'Bien') for it in catalog}

    for idx in sorted(item_indices):
        name = request.form.get(f'items[{idx}][name]', '').strip()
        price = float(request.form.get(f'items[{idx}][price]', 0.0))
        qty = int(float(request.form.get(f'items[{idx}][quantity]', 1)))
        itbis_rate = float(request.form.get(f'items[{idx}][itbisRate]', 0.18))
        item_disc = float(request.form.get(f'items[{idx}][discountRate]', 0.0))
        code = request.form.get(f'items[{idx}][code]', '').strip()

        if name and price > 0:
            item_type = catalog_types.get(name.lower().strip())
            if not item_type:
                item_type = 'Servicio' if any(x in name.lower() for x in ['servicio', 'honorarios', 'consultoria', 'asesoria', 'soporte', 'mantenimiento']) else 'Bien'
            parsed_items.append({
                "id": str(uuid.uuid4()),
                "code": code or f"ITEM-{idx + 1}",
                "type": item_type,
                "name": name,
                "price": price,
                "quantity": qty,
                "itbisRate": itbis_rate,
                "discountRate": item_disc / 100.0,  # Convert % to decimal
            })

    if not parsed_items:
        flash('❌ Debes añadir al menos una línea con producto/servicio, precio y descripción.', 'error')
        return redirect(url_for('web_fiscal_notes.create_fiscal_note', type=note_type, reference_invoice_id=ref_invoice_id))

    # Validate E34 total does not exceed reference total
    if note_type == 'E34':
        temp_calcs = DGIIService.calculate_invoice_totals(parsed_items, discount_rate=0.0, retained_isr_rate=0.0, retained_itbis_rate=0.0)
        if temp_calcs["net_payable"] > ref_total:
            flash(f'❌ El total de la nota (RD$ {temp_calcs["net_payable"]:,.2f}) excede el total de la factura original (RD$ {ref_total:,.2f}).', 'error')
            return redirect(url_for('web_fiscal_notes.create_fiscal_note', type=note_type, reference_invoice_id=ref_invoice_id))

    # Parse refunds (cash returns)
    cash_refunds = []
    refund_indices = set()
    for k in form_keys:
        if k.startswith('refunds['):
            parts = k.split(']')
            idx = parts[0].replace('refunds[', '')
            if idx.isdigit():
                refund_indices.add(int(idx))
    for idx in sorted(refund_indices):
        bank = request.form.get(f'refunds[{idx}][bank]', '').strip()
        amt = float(request.form.get(f'refunds[{idx}][amount]', 0.0))
        if bank and amt > 0:
            cash_refunds.append({
                "bank": bank,
                "accountNumber": request.form.get(f'refunds[{idx}][accountNumber]', '').strip(),
                "date": request.form.get(f'refunds[{idx}][date]', date),
                "amount": amt,
                "observations": request.form.get(f'refunds[{idx}][observations]', '').strip(),
            })

    modification_codes = {
        '1': 'Devolución',
        '2': 'Corrección de texto',
        '3': 'Descuento',
        '4': 'Descuento por volumen',
        '5': 'Otros',
    }
    modification_label = modification_codes.get(modification_code, 'Otros')

    inv_id = str(uuid.uuid4())
    inv_number = f"NC-{ref_invoice.get('invoiceNumber', ref_invoice_id)[-6:]}" if note_type == 'E34' else f"ND-{ref_invoice.get('invoiceNumber', ref_invoice_id)[-6:]}"

    calcs = DGIIService.calculate_invoice_totals(parsed_items, discount_rate=0.0, retained_isr_rate=0.0, retained_itbis_rate=0.0)

    inv_data = {
        "id": inv_id,
        "invoiceNumber": inv_number,
        "ecfType": ecf_type_label,
        "status": "Borrador",
        "date": date,
        "dueDate": date,
        "clientId": ref_invoice.get("clientId", ""),
        "clientRNC": ref_invoice.get("clientRNC", ""),
        "clientName": ref_invoice.get("clientName", ref_invoice.get("razonSocial", "")),
        "razonSocial": ref_invoice.get("razonSocial", ref_invoice.get("clientName", "")),
        "currency": ref_invoice.get("currency", "DOP"),
        "exchangeRate": ref_invoice.get("exchangeRate", 1.0),
        "items": calcs["items"],
        "subtotal": calcs["subtotal"],
        "totalITBIS": calcs["total_itbis"],
        "total": calcs["total"],
        "netPayable": calcs["net_payable"],
        "informationReference": {
            "modificationCode": int(modification_code),
            "ncfModified": ref_invoice.get("encf", ref_invoice.get("ncf", "")),
            "ncfModifiedDate": (ref_invoice.get("date", "") or "")[:10],
            "reasonForModification": f"{modification_label}: {reason}" if reason else modification_label,
        },
        "isQuotation": False,
        "notes": "",
        "comentario": comentario,
        "cashRefunds": cash_refunds,
        "warehouseId": warehouse_id,
        "priceListId": price_list_id,
        "sellerId": seller_id,
        "sequenceId": sequence_id,
        "branchId": ref_invoice.get("branchId") or session.get('selected_branch_id') or 'default-sucursal-principal',
        "projectId": ref_invoice.get("projectId") or session.get('selected_project_id') or None,
        "createdBy": user.get('displayName', 'Usuario'),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "creditedAmount": calcs["net_payable"] if note_type == 'E34' else 0.0,
        "debitedAmount": calcs["net_payable"] if note_type == 'E33' else 0.0,
    }

    DatabaseService.save_invoice(owner_uid, inv_id, inv_data, sandbox=sandbox, company_id=company_id)

    from app.services.audit_service import AuditService, ACTION_CREATE
    AuditService.log_from_request(
        owner_uid=owner_uid, action=ACTION_CREATE, module="Notas Fiscales",
        entity_id=inv_id, entity_label=f"{ecf_type_label} - {inv_number}",
        after=inv_data, sandbox=sandbox
    )

    flash(f'✅ {ecf_type_label} {inv_number} creada. Revisa los datos y emítela desde el módulo de facturación.', 'success')
    return redirect(url_for('web_invoices.invoice_detail', invoice_id=inv_id))


@web_fiscal_notes_bp.route('/api/invoices/<invoice_id>/credit-available')
def api_credit_available(invoice_id):
    if 'user' not in session:
        return jsonify(success=False, error="No autorizado"), 401
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox, company_id=company_id)
    if not invoice:
        return jsonify(success=False, error="Factura no encontrada"), 404

    all_invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, company_id=company_id)
    total_credited = sum(
        float(inv.get('netPayable', inv.get('total', 0)))
        for inv in all_invoices
        if inv.get('ecfType') == 'Nota de Crédito (E34)'
        and inv.get('informationReference', {}).get('ncfModified') == invoice.get('encf', invoice.get('ncf', ''))
        and inv.get('status') not in ('Anulada', 'Borrador')
    )
    original_total = float(invoice.get('netPayable', invoice.get('total', 0)))
    available = max(0, original_total - total_credited)

    return jsonify(success=True, originalTotal=original_total, totalCredited=total_credited, available=available)
