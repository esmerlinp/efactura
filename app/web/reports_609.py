"""Reporte 609 — Pagos por Servicios al Exterior (generación TXT)."""

import io
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_file

from app.services.db_service import DatabaseService
from app.utils.decorators import check_permission
from app.utils.module_gate import gate_blueprint_module
from app.services.dgii_609_service import (
    is_foreign_payment_invoice,
    build_609_record_from_invoice,
    validate_record,
    generate_609_txt,
)

web_reports_609_bp = Blueprint('web_reports_609', __name__)
gate_blueprint_module(web_reports_609_bp, 'e_cf', feature_name="Reporte 609 DGII")


@web_reports_609_bp.before_request
def restrict_to_do():
    if session.get('company_country', 'DO') != 'DO':
        return render_template('auth/restricted.html',
            feature_name="Reporte 609 (solo disponible para República Dominicana)",
            required_permission=""), 403


@web_reports_609_bp.route('/reports/609/export')
def reporte_609_export():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission("canReportsFiscal"):
        return render_template("auth/restricted.html", feature_name="Reporte 609", required_permission="canReportsFiscal"), 403

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    now = datetime.now(timezone.utc)
    year = request.args.get('year', now.strftime('%Y'))
    month = request.args.get('month', now.strftime('%m'))
    period = f"{year}{month}"

    try:
        from app.services.supplier_invoice_service import SupplierInvoiceService
        from app.services.supplier_service import SupplierService

        invoices = SupplierInvoiceService.get_all(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id)
        included = []
        excluded = []
        incomplete = []
        for inv in invoices:
            if SupplierInvoiceService.is_voided(inv):
                continue
            if not is_foreign_payment_invoice(inv):
                continue
            if (str(inv.get('date') or '')[:7]).replace('-', '') != period:
                continue

            supplier = {}
            if inv.get('supplierId'):
                supplier = SupplierService.get_supplier(
                    owner_uid=owner_uid, supplier_id=inv['supplierId'],
                    sandbox=sandbox, company_id=company_id,
                ) or {}
            payments = SupplierInvoiceService.get_payments(
                owner_uid=owner_uid, invoice_id=inv.get('id', ''),
                sandbox=sandbox, company_id=company_id,
            )
            record, blocked = build_609_record_from_invoice(inv, supplier, payments)
            if blocked:
                excluded.append((inv.get('id', ''), blocked))
                continue
            errors = validate_record(record, period=period)
            if errors:
                incomplete.append((inv.get('id', ''), "; ".join(errors)))
                continue
            included.append(record)

        if incomplete:
            detail = "; ".join(f"{iid}: {e}" for iid, e in incomplete[:5])
            flash(f'No se generó el 609: existen registros incompletos ({len(incomplete)}). {detail}', 'error')
            return redirect(url_for('web_reports_609.reporte_609_status', year=year, month=month))
        if not included:
            flash('No hay documentos de pago al exterior en el período seleccionado.', 'warning')
            return redirect(url_for('web_reports_609.reporte_609_status', year=year, month=month))

        profile = DatabaseService.get_company_profile(owner_uid, company_id=company_id) or {}
        owner_rnc = "".join(filter(str.isdigit, str(profile.get('companyRnc') or profile.get('rnc') or '')))

        try:
            txt = generate_609_txt(included, owner_rnc, period)
        except ValueError as ve:
            flash(f'No se generó el 609: {ve}', 'error')
            return redirect(url_for('web_reports_609.reporte_609_status', year=year, month=month))

        dest = io.BytesIO()
        dest.write(txt.encode('utf-8'))
        dest.seek(0)
        filename = f"609_{period}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.txt"
        return send_file(dest, mimetype='text/plain', as_attachment=True, download_name=filename)
    except Exception as e:
        flash(f'Error al generar el reporte 609: {e}', 'error')
        return redirect(url_for('web_reports_609.reporte_609_status', year=year, month=month))


@web_reports_609_bp.route('/reports/609')
def reporte_609_status():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission("canReportsFiscal"):
        return render_template("auth/restricted.html", feature_name="Reporte 609", required_permission="canReportsFiscal"), 403
    return render_template('reports/609.html', active_page='reporte_609')
