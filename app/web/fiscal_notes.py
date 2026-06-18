import uuid
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.services.db_service import DatabaseService
from app.utils.decorators import require_permission, check_permission
from app.services.dgii import DGIIService

web_fiscal_notes_bp = Blueprint('web_fiscal_notes', __name__)


@web_fiscal_notes_bp.route('/fiscal-notes')
@require_permission('canInvoice', 'Notas Fiscales')
def list_fiscal_notes():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
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
    sandbox = session.get('is_sandbox_mode', True)

    note_type = request.args.get('type', 'E34')
    if note_type not in ('E34', 'E33'):
        flash('❌ Tipo de nota inválido. Use E34 (Crédito) o E33 (Débito).', 'error')
        return redirect(url_for('web_fiscal_notes.list_fiscal_notes'))

    ref_invoice_id = request.args.get('reference_invoice_id', '')
    ref_invoice = None
    if ref_invoice_id:
        ref_invoice = DatabaseService.get_invoice(owner_uid, ref_invoice_id, sandbox=sandbox)
        if not ref_invoice:
            flash('❌ Factura de referencia no encontrada.', 'error')
            return redirect(url_for('web_fiscal_notes.list_fiscal_notes'))

    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    real_invoices = [inv for inv in invoices if not inv.get('isQuotation') and inv.get('status') not in ('Anulada', 'Borrador')
                     and inv.get('ecfType') not in ('Nota de Crédito (E34)', 'Nota de Débito (E33)', 'Cotización')]

    return render_template('fiscal_notes/form.html',
                           note_type=note_type,
                           ref_invoice=ref_invoice,
                           invoices=real_invoices,
                           active_page='fiscal_notes')


@web_fiscal_notes_bp.route('/fiscal-notes/create', methods=['POST'])
def save_fiscal_note():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canInvoice'):
        return render_template('auth/restricted.html', required_permission="canInvoice")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    user = session['user']

    note_type = request.form.get('noteType', 'E34')
    ref_invoice_id = request.form.get('referenceInvoiceId', '').strip()
    modification_code = request.form.get('modificationCode', '1')
    reason = request.form.get('reason', '').strip()
    notes = request.form.get('notes', '').strip()
    date = request.form.get('date', datetime.utcnow().strftime('%Y-%m-%d'))

    if not ref_invoice_id:
        flash('❌ Debes seleccionar una factura de referencia.', 'error')
        return redirect(url_for('web_fiscal_notes.create_fiscal_note', type=note_type))

    ref_invoice = DatabaseService.get_invoice(owner_uid, ref_invoice_id, sandbox=sandbox)
    if not ref_invoice:
        flash('❌ Factura de referencia no encontrada.', 'error')
        return redirect(url_for('web_fiscal_notes.list_fiscal_notes'))

    ref_total = float(ref_invoice.get('netPayable', ref_invoice.get('total', 0)))
    if note_type == 'E34':
        credited_amount = float(request.form.get('creditedAmount', ref_total))
        if credited_amount > ref_total:
            flash(f'❌ El monto a acreditar (RD$ {credited_amount:,.2f}) no puede exceder el total de la factura original (RD$ {ref_total:,.2f}).', 'error')
            return redirect(url_for('web_fiscal_notes.create_fiscal_note', type=note_type, reference_invoice_id=ref_invoice_id))
    else:
        debited_amount = float(request.form.get('debitedAmount', 0))
        if debited_amount <= 0:
            flash('❌ El monto a debitar debe ser mayor a 0.', 'error')
            return redirect(url_for('web_fiscal_notes.create_fiscal_note', type=note_type, reference_invoice_id=ref_invoice_id))

    modification_codes = {
        '1': 'Devolución',
        '2': 'Corrección de texto',
        '3': 'Descuento',
        '4': 'Descuento por volumen',
        '5': 'Otros',
    }
    modification_label = modification_codes.get(modification_code, 'Otros')

    ecf_type_label = 'Nota de Crédito (E34)' if note_type == 'E34' else 'Nota de Débito (E33)'
    inv_id = str(uuid.uuid4())
    inv_number = f"NC-{ref_invoice.get('invoiceNumber', ref_invoice_id)[-6:]}" if note_type == 'E34' else f"ND-{ref_invoice.get('invoiceNumber', ref_invoice_id)[-6:]}"

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
        "items": ref_invoice.get("items", []),
        "subtotal": ref_total if note_type == 'E34' else debited_amount,
        "itbis": 0,
        "total": ref_total if note_type == 'E34' else debited_amount,
        "netPayable": ref_total if note_type == 'E34' else debited_amount,
        "informationReference": {
            "modificationCode": int(modification_code),
            "ncfModified": ref_invoice.get("encf", ref_invoice.get("ncf", "")),
            "ncfModifiedDate": (ref_invoice.get("date", "") or "")[:10],
            "reasonForModification": f"{modification_label}: {reason}" if reason else modification_label,
        },
        "isQuotation": False,
        "notes": notes,
        "createdBy": user.get('displayName', 'Usuario'),
        "createdAt": datetime.utcnow().isoformat(),
    }

    DatabaseService.save_invoice(owner_uid, inv_id, inv_data, sandbox=sandbox)

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
    sandbox = session.get('is_sandbox_mode', True)

    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        return jsonify(success=False, error="Factura no encontrada"), 404

    all_invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
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
