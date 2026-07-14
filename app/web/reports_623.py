import io
import csv
from datetime import datetime, timezone
from collections import defaultdict
from flask import Blueprint, render_template, request, redirect, url_for, session, send_file, g
from app.services.db_service import DatabaseService
from app.utils.decorators import check_permission

web_reports_623_bp = Blueprint('web_reports_623', __name__)


@web_reports_623_bp.before_request
def restrict_to_do():
    if session.get('company_country', 'DO') != 'DO':
        return render_template('auth/restricted.html',
            feature_name="Reporte 623 DGII (solo disponible para República Dominicana)",
            required_permission="")

TIPO_GASTO_623 = {
    "01": "Gastos Personales",
    "02": "Trabajos/Suministros",
    "03": "Arrendamientos",
    "04": "Activos Fijos",
    "05": "Representación",
    "06": "Otras Deducciones",
    "07": "Gastos Financieros",
}

from app.models.fiscal_document_type import report_labels as _report_labels_623
ECF_TYPE_LABELS_623 = _report_labels_623("623")


def _parse_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _get_minor_expenses_for_period(owner_uid, sandbox, year, month):
    """Filtra gastos menores: montos pequeños, proveedores informales o E43."""
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    prefix = f"{year:04d}-{month:02d}"
    filtered = []
    for exp in expenses:
        d = (exp.get("date") or exp.get("createdAt") or "")[:7]
        if d != prefix:
            continue
        ecf = (exp.get("ecfType") or "")
        amount = float(exp.get("amount", 0))
        # Incluir: E43 explícito, o proveedores informales, o montos pequeños (< 50,000)
        if "E43" in ecf or exp.get("supplierType") == "informal" or amount < 50000:
            filtered.append(exp)
    return filtered


def _filter_minor_expenses(expenses, supplier_id, tipo_gasto, ecf_type, search):
    result = expenses
    if supplier_id:
        result = [e for e in result if e.get("supplierId") == supplier_id]
    if tipo_gasto:
        result = [e for e in result if e.get("tipoGastoDGII") == tipo_gasto]
    if ecf_type:
        result = [e for e in result if (e.get("ecfType") or "").upper().startswith(ecf_type)]
    if search:
        q = search.lower()
        result = [
            e for e in result
            if q in (e.get("providerName") or "").lower()
            or q in (e.get("rncEmisor") or "").lower()
            or q in (e.get("ncf") or "").lower()
            or q in (e.get("concept") or "").lower()
        ]
    return result


@web_reports_623_bp.route("/reports/623")
def reporte_623():
    if "user" not in session:
        return redirect(url_for("login"))
    if not check_permission("canExpenses"):
        return render_template("auth/restricted.html", active_page="reporte_623")
    owner_uid = session["user"]["ownerUID"]
    sandbox = session.get("is_sandbox_mode", True)

    now = datetime.now(timezone.utc)
    year = _parse_int(request.args.get("year"), now.year)
    month = _parse_int(request.args.get("month"), now.month)
    supplier_id = request.args.get("supplier_id", "").strip()
    tipo_gasto = request.args.get("tipo_gasto", "").strip()
    ecf_type = request.args.get("ecf_type", "").strip()
    search = request.args.get("search", "").strip()

    expenses = _get_minor_expenses_for_period(owner_uid, sandbox, year, month)
    filtered = _filter_minor_expenses(expenses, supplier_id, tipo_gasto, ecf_type, search)
    filtered.sort(key=lambda x: (x.get("date") or x.get("createdAt") or ""))

    total_monto = sum(float(e.get("amount", 0)) for e in filtered)
    total_itbis = sum(float(e.get("itbisAmount", 0)) for e in filtered)
    count = len(filtered)

    # Group by supplier
    by_supplier = defaultdict(lambda: {"count": 0, "monto": 0.0, "name": "", "rnc": ""})
    for e in filtered:
        key = e.get("supplierId") or e.get("rncEmisor") or "sin-id"
        by_supplier[key]["count"] += 1
        by_supplier[key]["monto"] += float(e.get("amount", 0))
        if not by_supplier[key].get("name"):
            by_supplier[key]["name"] = e.get("providerName", "—")
        if not by_supplier[key].get("rnc"):
            by_supplier[key]["rnc"] = e.get("rncEmisor", "—")

    profile = DatabaseService.get_company_profile(owner_uid)
    owner_rnc = (profile or {}).get("companyRNC", "")

    return render_template(
        "reports/reporte_623.html",
        filtered=filtered,
        by_supplier=dict(by_supplier),
        year=year,
        month=month,
        supplier_id=supplier_id,
        tipo_gasto=tipo_gasto,
        ecf_type=ecf_type,
        search=search,
        total_monto=total_monto,
        total_itbis=total_itbis,
        count=count,
        tipo_gasto_map=TIPO_GASTO_623,
        ecf_labels=ECF_TYPE_LABELS_623,
        owner_rnc=owner_rnc,
        active_page="reporte_623",
        now=now,
    )


@web_reports_623_bp.route("/reports/623/export")
def reporte_623_export():
    if "user" not in session:
        return redirect(url_for("login"))
    if not check_permission("canExpenses"):
        return render_template("auth/restricted.html"), 403
    owner_uid = session["user"]["ownerUID"]
    sandbox = session.get("is_sandbox_mode", True)

    now = datetime.now(timezone.utc)
    year = _parse_int(request.args.get("year"), now.year)
    month = _parse_int(request.args.get("month"), now.month)
    supplier_id = request.args.get("supplier_id", "").strip()
    tipo_gasto = request.args.get("tipo_gasto", "").strip()
    ecf_type = request.args.get("ecf_type", "").strip()
    search = request.args.get("search", "").strip()
    fmt = request.args.get("format", "simple")

    expenses = _get_minor_expenses_for_period(owner_uid, sandbox, year, month)
    filtered = _filter_minor_expenses(expenses, supplier_id, tipo_gasto, ecf_type, search)
    filtered.sort(key=lambda x: (x.get("date") or x.get("createdAt") or ""))

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)

    profile = DatabaseService.get_company_profile(owner_uid)
    owner_rnc = (profile or {}).get("companyRNC", "")

    if fmt == "dgii":
        writer.writerow([
            "RNC Comprador",
            "Período",
            "RNC Proveedor",
            "Tipo Identificación",
            "Nombre Proveedor",
            "Tipo Comprobante",
            "NCF/e-CF",
            "Monto Facturado",
            "ITBIS Facturado",
            "Fecha Comprobante",
            "Tipo Gasto",
            "Concepto",
        ])
        period = f"{year:04d}{month:02d}"
        tipo_comp_map = {"E41": "02", "E43": "03", "E45": "04", "E47": "05"}
        for e in filtered:
            writer.writerow([
                owner_rnc,
                period,
                e.get("rncEmisor", ""),
                "1" if len(e.get("rncEmisor", "")) == 9 else "2",
                e.get("providerName", ""),
                tipo_comp_map.get(e.get("ecfType", ""), "03"),
                e.get("ncf") or e.get("encf") or "",
                f'{float(e.get("amount", 0)):.2f}',
                f'{float(e.get("itbisAmount", 0)):.2f}',
                (e.get("date") or "")[:10],
                e.get("tipoGastoDGII", "06"),
                e.get("concept", ""),
            ])
    else:
        writer.writerow([
            "Fecha", "RNC Proveedor", "Proveedor", "e-CF", "NCF/e-CF",
            "Concepto", "Monto", "ITBIS", "Tipo Gasto", "Proveedor Informal",
        ])
        for e in filtered:
            writer.writerow([
                (e.get("date") or "")[:10],
                e.get("rncEmisor", ""),
                e.get("providerName", ""),
                e.get("ecfType", ""),
                e.get("ncf") or e.get("encf") or "",
                e.get("concept", ""),
                f'{float(e.get("amount", 0)):.2f}',
                f'{float(e.get("itbisAmount", 0)):.2f}',
                TIPO_GASTO_623.get(e.get("tipoGastoDGII", ""), e.get("tipoGastoDGII", "")),
                "Sí" if e.get("supplierType") == "informal" else "No",
            ])
        writer.writerow([])
        writer.writerow([
            "TOTALES", "", "", "", "", "",
            f'{sum(float(e.get("amount", 0)) for e in filtered):.2f}',
            f'{sum(float(e.get("itbisAmount", 0)) for e in filtered):.2f}',
            "", "",
        ])

    dest = io.BytesIO()
    dest.write(b"\xef\xbb\xbf")
    dest.write(output.getvalue().encode("utf-8"))
    dest.seek(0)

    filename = f"reporte_623_{year:04d}{month:02d}_{now.strftime('%Y%m%d')}.csv"
    return send_file(
        dest,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )
