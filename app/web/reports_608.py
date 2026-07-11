import io
import csv
from datetime import datetime, timezone
from collections import defaultdict
from flask import Blueprint, render_template, request, redirect, url_for, session, send_file, g
from app.services.db_service import DatabaseService
from app.utils.decorators import check_permission

web_reports_608_bp = Blueprint('web_reports_608', __name__)


@web_reports_608_bp.before_request
def restrict_to_do():
    if session.get('company_country', 'DO') != 'DO':
        return render_template('auth/restricted.html',
            feature_name="Reporte 608 DGII (solo disponible para República Dominicana)",
            required_permission="")

RETENTION_TYPE_LABELS = {
    "ITBIS": "Retención ITBIS",
    "ISR": "Retención ISR",
}

ECF_TYPE_LABELS_608 = {
    "E31": "E-31 (Crédito Fiscal)",
    "E32": "E-32 (Consumo)",
    "E33": "E-33 (Nota de Débito)",
    "E34": "E-34 (Nota de Crédito)",
    "E41": "E-41 (Comprobante de Compras)",
    "E43": "E-43 (Gastos Menores)",
    "Gasto": "Gasto",
}


def _parse_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _get_invoices_with_retentions(owner_uid, sandbox, year, month):
    prefix = f"{year:04d}-{month:02d}"
    filtered = []

    # Retenciones de facturas de venta (nos retuvieron a nosotros)
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    real = [inv for inv in invoices
            if not inv.get('isQuotation')
            and inv.get('status') not in ('Anulada', 'Borrador', 'Consolidada')]
    for inv in real:
        d = (inv.get("date") or inv.get("createdAt") or "")[:7]
        if d != prefix:
            continue
        ret_isr = float(inv.get("retainedISR", 0))
        ret_itbis = float(inv.get("retainedITBIS", 0))
        if ret_isr > 0:
            inv_copy = dict(inv)
            inv_copy["_retencion_tipo"] = "ISR"
            inv_copy["_retencion_monto"] = ret_isr
            filtered.append(inv_copy)
        if ret_itbis > 0:
            inv_copy = dict(inv)
            inv_copy["_retencion_tipo"] = "ITBIS"
            inv_copy["_retencion_monto"] = ret_itbis
            filtered.append(inv_copy)

    # Retenciones de gastos (nosotros retuvimos al proveedor)
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    for exp in expenses:
        if exp.get('status') in ('Anulada', 'Borrador'):
            continue
        d = (exp.get("date") or exp.get("createdAt") or "")[:7]
        if d != prefix:
            continue
        isr_withheld = float(exp.get("isrWithheld", 0))
        itbis_withheld = float(exp.get("itbisWithheld", 0))
        if isr_withheld > 0:
            exp_copy = dict(exp)
            exp_copy["_retencion_tipo"] = "ISR"
            exp_copy["_retencion_monto"] = isr_withheld
            exp_copy["clientRNC"] = exp.get("rncEmisor", "")
            exp_copy["clientName"] = exp.get("providerName", "")
            exp_copy["subtotal"] = exp.get("amount", 0)
            exp_copy["invoiceNumber"] = exp.get("ncf", "")
            filtered.append(exp_copy)
        if itbis_withheld > 0:
            exp_copy = dict(exp)
            exp_copy["_retencion_tipo"] = "ITBIS"
            exp_copy["_retencion_monto"] = itbis_withheld
            exp_copy["clientRNC"] = exp.get("rncEmisor", "")
            exp_copy["clientName"] = exp.get("providerName", "")
            exp_copy["subtotal"] = exp.get("amount", 0)
            exp_copy["invoiceNumber"] = exp.get("ncf", "")
            filtered.append(exp_copy)

    return filtered


def _filter_retentions(invoices, retention_type, ecf_type, search):
    result = invoices
    if retention_type:
        result = [e for e in result if e.get("_retencion_tipo") == retention_type]
    if ecf_type:
        ecf_short = ecf_type.split("(")[-1].replace(")", "").strip() if "(" in ecf_type else ecf_type
        result = [e for e in result if (e.get("ecfType") or "").upper().startswith(ecf_short)]
    if search:
        q = search.lower()
        result = [
            e for e in result
            if q in (e.get("clientName") or "").lower()
            or q in (e.get("clientRNC") or "").lower()
            or q in (e.get("encf") or e.get("invoiceNumber") or "").lower()
        ]
    return result


@web_reports_608_bp.route("/reports/608")
def reporte_608():
    if "user" not in session:
        return redirect(url_for("login"))
    if not check_permission("canReports"):
        return render_template("auth/restricted.html", active_page="reporte_608")
    owner_uid = session["user"]["ownerUID"]
    sandbox = session.get("is_sandbox_mode", True)

    now = datetime.now(timezone.utc)
    year = _parse_int(request.args.get("year"), now.year)
    month = _parse_int(request.args.get("month"), now.month)
    retention_type = request.args.get("retention_type", "").strip()
    ecf_type = request.args.get("ecf_type", "").strip()
    search = request.args.get("search", "").strip()

    invoices = _get_invoices_with_retentions(owner_uid, sandbox, year, month)
    filtered = _filter_retentions(invoices, retention_type, ecf_type, search)
    filtered.sort(key=lambda x: (x.get("date") or x.get("createdAt") or ""))

    total_isr = sum(float(e.get("retainedISR", 0)) for e in filtered if e.get("_retencion_tipo") == "ISR")
    total_itbis = sum(float(e.get("retainedITBIS", 0)) for e in filtered if e.get("_retencion_tipo") == "ITBIS")

    # Group by client
    by_client = defaultdict(lambda: {"isr": 0.0, "itbis": 0.0, "name": "", "rnc": ""})
    for e in filtered:
        key = e.get("clientId") or e.get("clientRNC") or "sin-id"
        if e.get("_retencion_tipo") == "ISR":
            by_client[key]["isr"] += float(e.get("retainedISR", 0))
        else:
            by_client[key]["itbis"] += float(e.get("retainedITBIS", 0))
        if not by_client[key].get("name"):
            by_client[key]["name"] = e.get("clientName", "—")
        if not by_client[key].get("rnc"):
            by_client[key]["rnc"] = e.get("clientRNC", "—")

    profile = DatabaseService.get_company_profile(owner_uid)
    owner_rnc = (profile or {}).get("companyRNC", "")

    return render_template(
        "reports/reporte_608.html",
        filtered=filtered,
        by_client=dict(by_client),
        year=year,
        month=month,
        retention_type=retention_type,
        ecf_type=ecf_type,
        search=search,
        total_isr=total_isr,
        total_itbis=total_itbis,
        ecf_labels=ECF_TYPE_LABELS_608,
        retention_labels=RETENTION_TYPE_LABELS,
        owner_rnc=owner_rnc,
        active_page="reporte_608",
        now=now,
    )


@web_reports_608_bp.route("/reports/608/export")
def reporte_608_export():
    if "user" not in session:
        return redirect(url_for("login"))
    if not check_permission("canReports"):
        return render_template("auth/restricted.html"), 403
    owner_uid = session["user"]["ownerUID"]
    sandbox = session.get("is_sandbox_mode", True)

    now = datetime.now(timezone.utc)
    year = _parse_int(request.args.get("year"), now.year)
    month = _parse_int(request.args.get("month"), now.month)
    retention_type = request.args.get("retention_type", "").strip()
    ecf_type = request.args.get("ecf_type", "").strip()
    search = request.args.get("search", "").strip()
    fmt = request.args.get("format", "simple")

    invoices = _get_invoices_with_retentions(owner_uid, sandbox, year, month)
    filtered = _filter_retentions(invoices, retention_type, ecf_type, search)
    filtered.sort(key=lambda x: (x.get("date") or x.get("createdAt") or ""))

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)

    profile = DatabaseService.get_company_profile(owner_uid)
    owner_rnc = (profile or {}).get("companyRNC", "")

    if fmt == "dgii":
        writer.writerow([
            "RNC Agente Retenedor",
            "Período",
            "RNC Retenido",
            "Tipo Identificación",
            "Nombre Retenido",
            "Tipo Retención",
            "Tipo Comprobante",
            "NCF/e-CF",
            "Monto Base",
            "Monto Retenido",
            "Fecha Comprobante",
        ])
        period = f"{year:04d}{month:02d}"
        for e in filtered:
            writer.writerow([
                owner_rnc,
                period,
                e.get("clientRNC", ""),
                "1" if len(e.get("clientRNC", "")) == 9 else "2",
                e.get("clientName", ""),
                e.get("_retencion_tipo", ""),
                e.get("ecfType", ""),
                e.get("encf") or e.get("invoiceNumber") or "",
                f'{float(e.get("subtotal", 0)):.2f}',
                f'{float(e.get("_retencion_monto", 0)):.2f}',
                (e.get("date") or "")[:10],
            ])
    else:
        writer.writerow([
            "Fecha", "RNC Retenido", "Nombre Retenido", "e-CF", "NCF/e-CF",
            "Tipo Retención", "Base", "Monto Retenido",
        ])
        for e in filtered:
            writer.writerow([
                (e.get("date") or "")[:10],
                e.get("clientRNC", ""),
                e.get("clientName", ""),
                e.get("ecfType", ""),
                e.get("encf") or e.get("invoiceNumber") or "",
                e.get("_retencion_tipo", ""),
                f'{float(e.get("subtotal", 0)):.2f}',
                f'{float(e.get("_retencion_monto", 0)):.2f}',
            ])
        writer.writerow([])
        total = sum(float(e.get("_retencion_monto", 0)) for e in filtered)
        writer.writerow(["TOTALES", "", "", "", "", "", "", f"{total:.2f}"])

    dest = io.BytesIO()
    dest.write(b"\xef\xbb\xbf")
    dest.write(output.getvalue().encode("utf-8"))
    dest.seek(0)

    filename = f"reporte_608_{year:04d}{month:02d}_{now.strftime('%Y%m%d')}.csv"
    return send_file(
        dest,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )
