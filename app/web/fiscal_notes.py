import io
import csv
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, session, send_file
from app.services.db_service import DatabaseService
from app.utils.decorators import require_permission
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
