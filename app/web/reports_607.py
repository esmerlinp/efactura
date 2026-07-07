import io
import csv
from datetime import datetime, timezone
from collections import defaultdict
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_file
from app.services.db_service import DatabaseService
from app.utils.decorators import check_permission

web_reports_607_bp = Blueprint('web_reports_607', __name__)

ECF_TYPE_LABELS_607 = {
    "E31": "E-31 (Crédito Fiscal)",
    "E32": "E-32 (Consumo)",
    "E33": "E-33 (Nota de Débito)",
    "E34": "E-34 (Nota de Crédito)",
}

INCOME_TYPE_LABELS = {
    "01": "Ingresos por operaciones",
    "02": "Ingresos financieros",
    "03": "Ingresos extraordinarios",
    "04": "Ingresos por alquileres",
    "05": "Ingresos por exportaciones",
    "06": "Otros ingresos",
}


def _parse_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _get_invoices_for_period(owner_uid, sandbox, year, month):
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    real = [inv for inv in invoices
            if not inv.get('isQuotation')
            and inv.get('status') not in ('Anulada', 'Borrador', 'Consolidada')]
    prefix = f"{year:04d}-{month:02d}"
    filtered = []
    for inv in real:
        d = (inv.get("date") or inv.get("createdAt") or "")[:7]
        if d == prefix:
            filtered.append(inv)
    return filtered


def _filter_invoices(invoices, client_id, ecf_type, income_type, search):
    result = invoices
    if client_id:
        result = [e for e in result if e.get("clientId") == client_id]
    if ecf_type:
        ecf_short = ecf_type.split("(")[-1].replace(")", "").strip() if "(" in ecf_type else ecf_type
        result = [e for e in result if (e.get("ecfType") or "").upper().startswith(ecf_short)]
    if income_type:
        result = [e for e in result if (e.get("incomeType") or "").startswith(income_type)]
    if search:
        q = search.lower()
        result = [
            e for e in result
            if q in (e.get("clientName") or "").lower()
            or q in (e.get("clientRNC") or "").lower()
            or q in (e.get("encf") or e.get("invoiceNumber") or "").lower()
        ]
    return result


# ═════════════════════════════════════════════════════════════════════
# REPORTE 607 — Main View
# ═════════════════════════════════════════════════════════════════════


@web_reports_607_bp.route("/reports/607")
def reporte_607():
    if "user" not in session:
        return redirect(url_for("login"))
    if not check_permission("canInvoice"):
        return render_template("auth/restricted.html", active_page="reporte_607")
    owner_uid = session["user"]["ownerUID"]
    sandbox = session.get("is_sandbox_mode", True)

    now = datetime.now(timezone.utc)
    year = _parse_int(request.args.get("year"), now.year)
    month = _parse_int(request.args.get("month"), now.month)
    client_id = request.args.get("client_id", "").strip()
    ecf_type = request.args.get("ecf_type", "").strip()
    income_type = request.args.get("income_type", "").strip()
    search = request.args.get("search", "").strip()

    invoices = _get_invoices_for_period(owner_uid, sandbox, year, month)
    filtered = _filter_invoices(invoices, client_id, ecf_type, income_type, search)
    filtered.sort(key=lambda x: (x.get("date") or x.get("createdAt") or ""))

    total_monto = sum(float(e.get("subtotal", 0)) for e in filtered)
    total_itbis = sum(float(e.get("totalITBIS", 0)) for e in filtered)
    total_neto = sum(float(e.get("total", 0)) for e in filtered)
    total_retenciones = sum(float(e.get("retainedISR", 0)) + float(e.get("retainedITBIS", 0)) for e in filtered)

    # Group by client
    by_client = defaultdict(lambda: {"count": 0, "monto": 0.0, "itbis": 0.0, "name": "", "rnc": ""})
    for e in filtered:
        key = e.get("clientId") or e.get("clientRNC") or "sin-id"
        by_client[key]["count"] += 1
        by_client[key]["monto"] += float(e.get("subtotal", 0))
        by_client[key]["itbis"] += float(e.get("totalITBIS", 0))
        if not by_client[key].get("name"):
            by_client[key]["name"] = e.get("clientName", "Consumidor Final")
        if not by_client[key].get("rnc"):
            by_client[key]["rnc"] = e.get("clientRNC", "—")

    clients_list = DatabaseService.get_clients(owner_uid, sandbox=sandbox) or []

    return render_template(
        "reports/reporte_607.html",
        filtered=filtered,
        by_client=dict(by_client),
        year=year,
        month=month,
        client_id=client_id,
        ecf_type=ecf_type,
        income_type=income_type,
        search=search,
        total_monto=total_monto,
        total_itbis=total_itbis,
        total_neto=total_neto,
        total_retenciones=total_retenciones,
        ecf_labels=ECF_TYPE_LABELS_607,
        income_labels=INCOME_TYPE_LABELS,
        clients_list=clients_list,
        active_page="reporte_607",
        now=now,
    )


# ═════════════════════════════════════════════════════════════════════
# REPORTE 607 — CSV Export
# ═════════════════════════════════════════════════════════════════════


@web_reports_607_bp.route("/reports/607/export")
def reporte_607_export():
    if "user" not in session:
        return redirect(url_for("login"))
    if not check_permission("canInvoice"):
        return render_template("auth/restricted.html"), 403
    owner_uid = session["user"]["ownerUID"]
    sandbox = session.get("is_sandbox_mode", True)

    now = datetime.now(timezone.utc)
    year = _parse_int(request.args.get("year"), now.year)
    month = _parse_int(request.args.get("month"), now.month)
    client_id = request.args.get("client_id", "").strip()
    ecf_type = request.args.get("ecf_type", "").strip()
    income_type = request.args.get("income_type", "").strip()
    search = request.args.get("search", "").strip()
    fmt = request.args.get("format", "simple")

    invoices = _get_invoices_for_period(owner_uid, sandbox, year, month)
    filtered = _filter_invoices(invoices, client_id, ecf_type, income_type, search)
    filtered.sort(key=lambda x: (x.get("date") or x.get("createdAt") or ""))

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)

    profile = DatabaseService.get_company_profile(owner_uid)
    owner_rnc = (profile or {}).get("companyRNC", "")

    if fmt == "dgii":
        writer.writerow([
            "RNC Emisor",
            "Período",
            "RNC Cliente",
            "Tipo Identificación",
            "Nombre Cliente",
            "Tipo Comprobante",
            "NCF/e-CF",
            "Monto Facturado",
            "ITBIS Facturado",
            "Retenciones",
            "Fecha Comprobante",
            "Tipo Ingreso",
        ])
        period = f"{year:04d}{month:02d}"
        tipo_comp_map = {
            "E31": "01", "E32": "02", "E33": "03", "E34": "04",
        }
        for e in filtered:
            ecf = (e.get("ecfType") or "")
            ecf_code = ecf.split("(")[-1].replace(")", "").strip() if "(" in ecf else ecf
            retenciones = float(e.get("retainedISR", 0)) + float(e.get("retainedITBIS", 0))
            writer.writerow([
                owner_rnc,
                period,
                e.get("clientRNC", ""),
                "1" if len(e.get("clientRNC", "")) == 9 else "2",
                e.get("clientName", ""),
                tipo_comp_map.get(ecf_code, "02"),
                e.get("encf") or e.get("invoiceNumber") or "",
                f'{float(e.get("subtotal", 0)):.2f}',
                f'{float(e.get("totalITBIS", 0)):.2f}',
                f'{retenciones:.2f}',
                (e.get("date") or "")[:10],
                (e.get("incomeType") or "01")[:2],
            ])
    else:
        writer.writerow([
            "Fecha", "RNC Cliente", "Cliente", "e-CF", "NCF/e-CF",
            "Monto", "ITBIS", "ISR Ret.", "ITBIS Ret.", "Neto", "Tipo Ingreso",
        ])
        for e in filtered:
            writer.writerow([
                (e.get("date") or "")[:10],
                e.get("clientRNC", ""),
                e.get("clientName", ""),
                e.get("ecfType", ""),
                e.get("encf") or e.get("invoiceNumber") or "",
                f'{float(e.get("subtotal", 0)):.2f}',
                f'{float(e.get("totalITBIS", 0)):.2f}',
                f'{float(e.get("retainedISR", 0)):.2f}',
                f'{float(e.get("retainedITBIS", 0)):.2f}',
                f'{float(e.get("total", 0)):.2f}',
                e.get("incomeType", "01"),
            ])
        writer.writerow([])
        writer.writerow([
            "TOTALES", "", "", "", "",
            f'{sum(float(e.get("subtotal", 0)) for e in filtered):.2f}',
            f'{sum(float(e.get("totalITBIS", 0)) for e in filtered):.2f}',
            f'{sum(float(e.get("retainedISR", 0)) for e in filtered):.2f}',
            f'{sum(float(e.get("retainedITBIS", 0)) for e in filtered):.2f}',
            f'{sum(float(e.get("total", 0)) for e in filtered):.2f}',
            "",
        ])

    dest = io.BytesIO()
    dest.write(b"\xef\xbb\xbf")
    dest.write(output.getvalue().encode("utf-8"))
    dest.seek(0)

    filename = f"reporte_607_{year:04d}{month:02d}_{now.strftime('%Y%m%d')}.csv"
    return send_file(
        dest,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )
