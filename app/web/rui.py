import uuid
from datetime import datetime, timezone, date as dt_date
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify

from app.services.db_service import DatabaseService
from app.services.rui_generation_service import RuiGenerationService
from app.utils.decorators import require_permission

web_rui_bp = Blueprint('web_rui', __name__, url_prefix='/rui')


@web_rui_bp.route('/list')
@require_permission('canManagePOS', 'RUI')
def rui_list():
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    company_id = session.get('selected_company_id')

    estado = request.args.get('estado', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    docs = DatabaseService.get_fiscal_summary_documents(
        owner_uid, sandbox=sandbox,
        document_type="RUI",
        estado=estado if estado else None,
        date_from=date_from if date_from else None,
        date_to=date_to if date_to else None,
        company_id=company_id,
    )

    return render_template(
        'rui/list.html',
        active_page='rui',
        docs=docs,
        estado=estado,
        date_from=date_from,
        date_to=date_to,
    )


@web_rui_bp.route('/<rui_id>')
@require_permission('canManagePOS', 'RUI')
def rui_detail(rui_id):
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    company_id = session.get('selected_company_id')

    doc = DatabaseService.get_fiscal_summary_document(owner_uid, rui_id, sandbox=sandbox, company_id=company_id)
    if not doc:
        flash('Documento RUI no encontrado.', 'error')
        return redirect(url_for('web_rui.rui_list'))

    invoices = []
    try:
        all_invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, company_id=company_id)
        invoices = [inv for inv in all_invoices if inv.get("ruiId") == rui_id]
    except Exception:
        pass

    return render_template(
        'rui/detail.html',
        active_page='rui',
        doc=doc,
        invoices=invoices,
    )


@web_rui_bp.route('/generate', methods=['POST'])
@require_permission('canManagePOS', 'RUI')
def rui_generate():
    owner_uid = session['user']['ownerUID']
    user_email = session['user'].get('email', '')
    sandbox = session.get('is_sandbox_mode', True)
    company_id = session.get('selected_company_id')

    business_date = request.form.get('businessDate', '').strip()
    notes = request.form.get('notes', '').strip()
    if not business_date:
        business_date = dt_date.today().isoformat()

    try:
        doc = RuiGenerationService.generate_rui(
            owner_uid, business_date, user_email,
            user_name=session['user'].get('name', ''),
            sandbox=sandbox, auto=False, notes=notes,
            company_id=company_id
        )
        flash(f'RUI generado exitosamente: {doc.get("ncf", "")}', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    except RuntimeError as e:
        flash(f'Error al generar RUI: {e}', 'error')
    except Exception as e:
        flash(f'Error inesperado: {e}', 'error')

    return redirect(url_for('web_rui.rui_list'))


@web_rui_bp.route('/<rui_id>/cancel', methods=['POST'])
@require_permission('canManagePOS', 'RUI')
def rui_cancel(rui_id):
    owner_uid = session['user']['ownerUID']
    user_uid = session['user'].get('uid', '')
    user_email = session['user'].get('email', '')
    sandbox = session.get('is_sandbox_mode', True)
    company_id = session.get('selected_company_id')

    cancel_reason = request.form.get('cancelReason', '').strip()
    if not cancel_reason:
        flash('El motivo de anulación es obligatorio.', 'error')
        return redirect(url_for('web_rui.rui_detail', rui_id=rui_id))

    try:
        result = RuiGenerationService.cancel_rui(
            owner_uid, rui_id, user_uid, user_email, cancel_reason, sandbox=sandbox,
            company_id=company_id
        )
        flash(f'RUI anulado exitosamente.', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    except Exception as e:
        flash(f'Error al anular RUI: {e}', 'error')

    return redirect(url_for('web_rui.rui_detail', rui_id=rui_id))


@web_rui_bp.route('/api/generate', methods=['POST'])
def api_rui_generate():
    from flask import request as req
    data = req.get_json(silent=True) or {}
    owner_uid = (data.get("ownerUID") or "").strip()
    business_date = (data.get("businessDate") or "").strip()
    user_email = (data.get("userEmail") or "").strip()
    sandbox = data.get("sandbox", True)
    company_id = data.get("companyId")

    if not owner_uid or not user_email:
        return jsonify({"success": False, "error": "ownerUID y userEmail son requeridos"}), 400
    if not business_date:
        business_date = dt_date.today().isoformat()

    try:
        doc = RuiGenerationService.generate_rui(
            owner_uid, business_date, user_email,
            sandbox=sandbox, auto=True,
            company_id=company_id
        )
        return jsonify({
            "success": True,
            "data": {
                "id": doc.get("id"),
                "ncf": doc.get("ncf"),
                "businessDate": doc.get("businessDate"),
                "totalVentas": doc.get("totalVentas"),
                "cantidadTransacciones": doc.get("cantidadTransacciones"),
            }
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@web_rui_bp.route('/<rui_id>/pdf')
@require_permission('canManagePOS', 'RUI')
def rui_pdf(rui_id):
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    company_id = session.get('selected_company_id')

    doc = DatabaseService.get_fiscal_summary_document(owner_uid, rui_id, sandbox=sandbox, company_id=company_id)
    if not doc:
        flash('Documento RUI no encontrado.', 'error')
        return redirect(url_for('web_rui.rui_list'))

    company = DatabaseService.get_company_profile(owner_uid, company_id=company_id)

    return render_template(
        'rui/pdf.html',
        doc=doc,
        company=company,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@web_rui_bp.route('/check')
@require_permission('canManagePOS', 'RUI')
def rui_check():
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    company_id = session.get('selected_company_id')

    today = dt_date.today().isoformat()
    eligible = DatabaseService.get_rui_eligible_invoices(owner_uid, today, sandbox=sandbox, company_id=company_id)
    eligible = [inv for inv in eligible if RuiGenerationService.is_invoice_eligible(inv, company_id=company_id)]

    existing_docs = DatabaseService.get_fiscal_summary_documents(
        owner_uid, sandbox=sandbox,
        document_type="RUI",
        business_date=today,
        company_id=company_id,
    )
    has_active_rui = any(d.get("estado") == "ACTIVO" for d in existing_docs)

    company = DatabaseService.get_company_profile(owner_uid, company_id=company_id)

    return jsonify({
        "ruiEnabled": company.get("ruiEnabled", False),
        "eligibleCount": len(eligible),
        "eligibleTotal": sum(float(inv.get("total", 0.0)) for inv in eligible),
        "hasActiveRui": has_active_rui,
        "existingRuis": [
            {"id": d["id"], "ncf": d.get("ncf", ""), "estado": d.get("estado", "")}
            for d in existing_docs
        ],
    })
