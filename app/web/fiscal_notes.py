import io
import csv
import uuid
import json
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, send_file, g
from app.services.db_service import DatabaseService
from app.utils.decorators import require_permission, check_permission
from app.services.dgii import DGIIService
from app.models.fiscal_document_type import by_code as _by_code

from app.utils.module_gate import gate_blueprint_module

web_fiscal_notes_bp = Blueprint('web_fiscal_notes', __name__)
gate_blueprint_module(web_fiscal_notes_bp, 'e_cf', feature_name="Notas Fiscales e-CF")


def _ecf_code(ecf_type: str) -> str | None:
    try:
        return _by_code(ecf_type).code
    except KeyError:
        return None


@web_fiscal_notes_bp.before_request
def restrict_to_do():
    if session.get('company_country', 'DO') != 'DO':
        return render_template('auth/restricted.html',
            feature_name="Notas Fiscales e-CF (solo disponibles para República Dominicana)",
            required_permission=""), 403


@web_fiscal_notes_bp.route('/fiscal-notes')
@require_permission('canManageFiscalNotes', 'Notas Fiscales')
def list_fiscal_notes():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    q = request.args.get('q', '').strip()
    status = request.args.get('status', '').strip()
    dgii_status = request.args.get('dgii_status', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    per_page = request.args.get('per_page', '10').strip()
    sort = request.args.get('sort', 'date').strip()
    order = request.args.get('order', 'desc').strip()
    if order not in ('asc', 'desc'):
        order = 'desc'
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1

    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, company_id=company_id)
    credit_debit = [inv for inv in invoices if _ecf_code(inv.get('ecfType', '')) in ('E34', 'E33')]
    credit_debit.sort(key=lambda x: x.get('createdAt', ''), reverse=True)

    def _ncf_modified(inv):
        return str((inv.get('informationReference') or {}).get('ncfModified', '') or '')

    def _dgii_status(inv):
        return str(inv.get('dgiiStatus') or ('ACCEPTED' if inv.get('isSyncedWithDGII') else ('CONTINGENCY' if inv.get('emisionMode') == 'FALLBACK' else ''))).lower()

    # Filtrar
    filtered = []
    for inv in credit_debit:
        if q:
            q_lower = q.lower()
            if (q_lower not in str(inv.get('invoiceNumber', '')).lower() and
                q_lower not in str(inv.get('clientName', '')).lower() and
                q_lower not in str(inv.get('razonSocial', '')).lower() and
                q_lower not in str(inv.get('clientRNC', '')).lower() and
                q_lower not in str(inv.get('encf', '')).lower() and
                q_lower not in _ncf_modified(inv).lower()):
                continue
        if status and inv.get('status') != status:
            continue
        if dgii_status:
            if dgii_status == "Pendiente":
                if not (
                    (inv.get('emisionMode') == 'FALLBACK' and not inv.get('isSyncedWithDGII') and inv.get('status') != 'Anulada')
                    or inv.get('status') == 'Pendiente DGII'
                    or inv.get('dgiiStatus') in ['PENDING', 'CONTINGENCY']
                ):
                    continue
            elif dgii_status == "Aceptado":
                if not (inv.get('isSyncedWithDGII') or inv.get('dgiiStatus') in ['ACCEPTED', 'ACEPTADO', 'ACCEPTED_PREVIOUSLY']):
                    continue
            elif dgii_status == "Rechazado":
                if not (inv.get('dgiiStatus') in ['REJECTED', 'RECHAZADO']):
                    continue
            elif dgii_status == "Condicional":
                if not (inv.get('dgiiStatus') in ['CONDITIONAL', 'CONDICIONAL', 'ACEPTADO_CONDICIONAL']):
                    continue
            elif dgii_status == "No sincronizado":
                if not (bool(inv.get('encf')) and _dgii_status(inv) == ''):
                    continue
            elif dgii_status == "N/A":
                if inv.get('encf'):
                    continue
        inv_date = (inv.get('date', '') or '')[:10]
        if start_date and inv_date < start_date:
            continue
        if end_date and inv_date > end_date:
            continue
        filtered.append(inv)

    # Ordenar por columna (click en encabezados del grid)
    SORT_KEYS = {
        "invoiceNumber": lambda d: str(d.get("invoiceNumber") or "").lower(),
        "clientName": lambda d: str(d.get("clientName") or d.get("razonSocial") or "").lower(),
        "ncfModified": lambda d: _ncf_modified(d).lower(),
        "date": lambda d: str(d.get("date") or ""),
        "total": lambda d: float(d.get("netPayable", d.get("total", 0)) or 0),
        "status": lambda d: str(d.get("status") or "").lower(),
        "encf": lambda d: str(d.get("encf") or "").lower(),
        "dgiiStatus": _dgii_status,
    }
    key_fn = SORT_KEYS.get(sort) or SORT_KEYS["date"]
    try:
        filtered.sort(key=key_fn, reverse=(order == "desc"))
    except Exception:
        filtered.sort(key=lambda d: str(d.get("date") or ""), reverse=True)

    def _dgii_status_label(inv):
        if inv.get("isSyncedWithDGII") or inv.get("dgiiStatus") in ("ACCEPTED", "ACEPTADO", "ACCEPTED_PREVIOUSLY"):
            return "Aceptado"
        if inv.get("dgiiStatus") in ("REJECTED", "RECHAZADO"):
            return "Rechazado"
        if inv.get("dgiiStatus") == "CONTINGENCY" or (inv.get("emisionMode") == "FALLBACK" and not inv.get("isSyncedWithDGII")):
            return "Contingencia"
        if inv.get("dgiiStatus") in ("PENDING", "PENDIENTE") or inv.get("status") == "Pendiente DGII" or (inv.get("emisionMode") == "API" and not inv.get("isSyncedWithDGII") and inv.get("encf") and inv.get("status") != "Anulada"):
            return "Pendiente"
        if inv.get("dgiiStatus") in ("CONDITIONAL", "CONDICIONAL", "ACEPTADO_CONDICIONAL"):
            return "Condicional"
        if inv.get("encf"):
            return inv.get("dgiiStatus") or "No sincronizado"
        return "N/A"

    # Exportar a CSV si se solicita
    if request.args.get('export') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["# Interno", "NCF/Número", "Cliente", "RNC", "NCF Ref.", "Creación", "Total (RD$)", "Estado", "Estado DGII"])
        for inv in filtered:
            writer.writerow([
                inv.get("invoiceNumber", ""),
                inv.get("encf", ""),
                inv.get("clientName", inv.get("razonSocial", "")),
                inv.get("clientRNC", ""),
                _ncf_modified(inv),
                (inv.get("date", "") or "")[:10],
                f"{float(inv.get('netPayable', inv.get('total', 0)) or 0):.2f}",
                inv.get("status", ""),
                _dgii_status_label(inv),
            ])
        dest = io.BytesIO()
        dest.write(b'\xef\xbb\xbf')  # UTF-8 BOM
        dest.write(output.getvalue().encode('utf-8'))
        dest.seek(0)
        filename = f"notas_fiscales_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(dest, mimetype="text/csv", as_attachment=True, download_name=filename)

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
    paginated_notes = filtered[start_idx:end_idx]

    start_count = ((page - 1) * per_page_val) + 1 if total_items > 0 else 0
    end_count = min(page * per_page_val, total_items)

    return render_template(
        'fiscal_notes/list.html',
        notes=paginated_notes,
        active_page='fiscal_notes',
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
        dgii_status=dgii_status,
        start_date=start_date,
        end_date=end_date,
        sort=sort,
        order=order
    )


@web_fiscal_notes_bp.route('/fiscal-notes/create', methods=['GET'])
def create_fiscal_note():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageFiscalNotes'):
        return render_template('auth/restricted.html', required_permission="canManageFiscalNotes"), 403
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
                     and _ecf_code(inv.get('ecfType', '')) not in ('E34', 'E33', None)]

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
    if not check_permission('canManageFiscalNotes'):
        return render_template('auth/restricted.html', required_permission="canManageFiscalNotes"), 403
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

    ecf_type_label = note_type

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
    catalog_by_code = {it['code'].strip().lower(): it for it in catalog if it.get('code')}
    catalog_by_name = {it['name'].strip().lower(): it for it in catalog}

    from app.services.credit_note_inventory_service import CreditNoteInventoryService

    for idx in sorted(item_indices):
        name = request.form.get(f'items[{idx}][name]', '').strip()
        price = float(request.form.get(f'items[{idx}][price]', 0.0))
        qty = int(float(request.form.get(f'items[{idx}][quantity]', 1)))
        itbis_rate = float(request.form.get(f'items[{idx}][itbisRate]', 0.18))
        item_disc = float(request.form.get(f'items[{idx}][discountRate]', 0.0))
        code = request.form.get(f'items[{idx}][code]', '').strip()
        item_warehouse_id = request.form.get(f'items[{idx}][warehouseId]', '').strip() or warehouse_id
        reingreso_raw = request.form.get(f'items[{idx}][reingresoStock]')

        if name and price > 0:
            cat_it = catalog_by_code.get(code.lower()) or catalog_by_name.get(name.lower())
            item_id = cat_it["id"] if cat_it else str(uuid.uuid4())
            item_type = catalog_types.get(name.lower().strip()) or (cat_it.get("type") if cat_it else None)
            if not item_type:
                item_type = 'Servicio' if any(x in name.lower() for x in ['servicio', 'honorarios', 'consultoria', 'asesoria', 'soporte', 'mantenimiento']) else 'Bien'

            is_bien = (item_type == 'Bien')
            if note_type == 'E34':
                if reingreso_raw is not None:
                    is_reingreso = (reingreso_raw.lower() in ('1', 'true', 'on', 'yes')) and is_bien
                else:
                    is_reingreso = (modification_code == '1') and is_bien
            else:
                is_reingreso = False

            ref_it = None
            if ref_invoice and ref_invoice.get("items"):
                for ri in ref_invoice.get("items", []):
                    if (code and (ri.get("code", "")).strip().lower() == code.lower()) or (ri.get("name", "").strip().lower() == name.lower()) or (cat_it and ri.get("id") == cat_it["id"]):
                        ref_it = ri
                        break

            orig_line_id = ref_it.get("id", "") if ref_it else ""
            item_temp = {
                "id": item_id,
                "code": code,
                "name": name,
                "originalLineId": orig_line_id,
                "unitCost": float(request.form.get(f'items[{idx}][originalCost]', 0.0))
            }
            orig_cost = CreditNoteInventoryService.resolve_original_cost(
                owner_uid=owner_uid,
                company_id=company_id,
                ref_invoice=ref_invoice,
                item=item_temp,
                sandbox=sandbox
            )
            if orig_cost <= 0 and cat_it:
                orig_cost = float(cat_it.get("costPrice", 0.0) or 0.0)

            parsed_items.append({
                "id": item_id,
                "code": code or (cat_it.get("code") if cat_it else f"ITEM-{idx + 1}"),
                "type": item_type,
                "name": name,
                "price": price,
                "quantity": qty,
                "itbisRate": itbis_rate,
                "discountRate": item_disc / 100.0,  # Convert % to decimal
                "reingresoStock": is_reingreso,
                "originalInvoiceId": ref_invoice_id,
                "originalLineId": orig_line_id,
                "warehouseId": item_warehouse_id or warehouse_id,
                "quantityReturned": qty if is_reingreso else 0,
                "originalCost": orig_cost,
                "unitCost": orig_cost,
                "costPrice": orig_cost,
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
        "referenceInvoiceId": ref_invoice_id,
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
        if _ecf_code(inv.get('ecfType', '')) == 'E34'
        and inv.get('informationReference', {}).get('ncfModified') == invoice.get('encf', invoice.get('ncf', ''))
        and inv.get('status') not in ('Anulada', 'Borrador')
    )
    original_total = float(invoice.get('netPayable', invoice.get('total', 0)))
    available = max(0, original_total - total_credited)

    return jsonify(success=True, originalTotal=original_total, totalCredited=total_credited, available=available)
