import io
import csv
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from app.services.db_service import DatabaseService
from app.utils.decorators import check_permission

web_reports_606_bp = Blueprint('web_reports_606', __name__)

TIPO_GASTO_606 = {
    "01": "Gastos Personales",
    "02": "Trabajos/Suministros",
    "03": "Arrendamientos",
    "04": "Activos Fijos",
    "05": "Representación",
    "06": "Otras Deducciones",
    "07": "Gastos Financieros",
}

ECF_TYPE_LABELS = {
    "E31": "E-31 (Crédito Fiscal)",
    "E41": "E-41 (Compras)",
    "E43": "E-43 (Gastos Menores)",
    "E45": "E-45 (Gubernamental)",
    "E47": "E-47 (Exterior)",
}


def _parse_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _get_expenses_for_period(owner_uid, sandbox, year, month):
    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
    prefix = f"{year:04d}-{month:02d}"
    filtered = []
    for exp in expenses:
        d = (exp.get("date") or exp.get("createdAt") or "")[:7]
        if d == prefix:
            filtered.append(exp)
    return filtered


def _filter_expenses(expenses, supplier_id, tipo_gasto, ecf_type, search):
    result = expenses
    if supplier_id:
        result = [e for e in result if e.get("supplierId") == supplier_id]
    if tipo_gasto:
        result = [e for e in result if e.get("tipoGastoDGII") == tipo_gasto]
    if ecf_type:
        result = [e for e in result if e.get("ecfType") == ecf_type]
    if search:
        q = search.lower()
        result = [
            e
            for e in result
            if q in (e.get("providerName") or "").lower()
            or q in (e.get("rncEmisor") or "").lower()
            or q in (e.get("ncf") or "").lower()
            or q in (e.get("concept") or "").lower()
        ]
    return result


# ═════════════════════════════════════════════════════════════════════
# REPORTE 606 — Main View
# ═════════════════════════════════════════════════════════════════════


@web_reports_606_bp.route("/reports/606")
def reporte_606():
    if "user" not in session:
        return redirect(url_for("login"))
    if not check_permission("canExpenses"):
        return render_template("auth/restricted.html", active_page="reporte_606")
    owner_uid = session["user"]["ownerUID"]
    sandbox = session.get("is_sandbox_mode", True)

    now = datetime.utcnow()
    year = _parse_int(request.args.get("year"), now.year)
    month = _parse_int(request.args.get("month"), now.month)
    supplier_id = request.args.get("supplier_id", "").strip()
    tipo_gasto = request.args.get("tipo_gasto", "").strip()
    ecf_type = request.args.get("ecf_type", "").strip()
    search = request.args.get("search", "").strip()

    expenses = _get_expenses_for_period(owner_uid, sandbox, year, month)
    filtered = _filter_expenses(expenses, supplier_id, tipo_gasto, ecf_type, search)
    filtered.sort(key=lambda x: (x.get("date") or x.get("createdAt") or ""))

    total_monto = sum(float(e.get("amount", 0)) for e in filtered)
    total_itbis = sum(float(e.get("itbisAmount", 0)) for e in filtered)
    total_itbis_deducible = sum(
        float(e.get("itbisAmount", 0))
        for e in filtered
        if e.get("isITBISDeductible")
    )
    total_deducible = sum(
        float(e.get("amount", 0)) for e in filtered if e.get("isDeductible")
    )

    # Group by supplier for subtotals
    by_supplier = defaultdict(lambda: {"count": 0, "monto": 0.0, "itbis": 0.0})
    for e in filtered:
        key = e.get("supplierId") or e.get("rncEmisor") or "sin-id"
        by_supplier[key]["count"] += 1
        by_supplier[key]["monto"] += float(e.get("amount", 0))
        by_supplier[key]["itbis"] += float(e.get("itbisAmount", 0))
        if not by_supplier[key].get("name"):
            by_supplier[key]["name"] = e.get("providerName", "—")
        if not by_supplier[key].get("rnc"):
            by_supplier[key]["rnc"] = e.get("rncEmisor", "—")

    return render_template(
        "reports/reporte_606.html",
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
        total_itbis_deducible=total_itbis_deducible,
        total_deducible=total_deducible,
        tipo_gasto_map=TIPO_GASTO_606,
        ecf_labels=ECF_TYPE_LABELS,
        active_page="reporte_606",
        now=now,
    )


# ═════════════════════════════════════════════════════════════════════
# REPORTE 606 — CSV Export
# ═════════════════════════════════════════════════════════════════════


@web_reports_606_bp.route("/reports/606/export")
def reporte_606_export():
    if "user" not in session:
        return redirect(url_for("login"))
    if not check_permission("canExpenses"):
        return render_template("auth/restricted.html"), 403
    owner_uid = session["user"]["ownerUID"]
    sandbox = session.get("is_sandbox_mode", True)

    now = datetime.utcnow()
    year = _parse_int(request.args.get("year"), now.year)
    month = _parse_int(request.args.get("month"), now.month)
    supplier_id = request.args.get("supplier_id", "").strip()
    tipo_gasto = request.args.get("tipo_gasto", "").strip()
    ecf_type = request.args.get("ecf_type", "").strip()
    search = request.args.get("search", "").strip()
    fmt = request.args.get("format", "simple")

    expenses = _get_expenses_for_period(owner_uid, sandbox, year, month)
    filtered = _filter_expenses(expenses, supplier_id, tipo_gasto, ecf_type, search)
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
            "Tipo Gasto 606",
        ])
        period = f"{year:04d}{month:02d}"
        tipo_comp_map = {
            "E31": "01", "E41": "02", "E43": "03", "E45": "04", "E47": "05",
        }
        for e in filtered:
            writer.writerow([
                owner_rnc,
                period,
                e.get("rncEmisor", ""),
                "1",
                e.get("providerName", ""),
                tipo_comp_map.get(e.get("ecfType", ""), "02"),
                e.get("ncf") or e.get("encf") or "",
                f'{float(e.get("amount", 0)):.2f}',
                f'{float(e.get("itbisAmount", 0)):.2f}',
                (e.get("date") or "")[:10],
                e.get("tipoGastoDGII", "06"),
            ])
    else:
        writer.writerow([
            "Fecha",
            "RNC Proveedor",
            "Proveedor",
            "e-CF Type",
            "NCF/e-CF",
            "Concepto",
            "Monto Facturado",
            "ITBIS",
            "ITBIS Deducible",
            "Tipo Gasto 606",
            "Deducible",
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
                f'{float(e.get("itbisAmount", 0)):.2f}' if e.get("isITBISDeductible") else "0.00",
                TIPO_GASTO_606.get(e.get("tipoGastoDGII", ""), e.get("tipoGastoDGII", "")),
                "Sí" if e.get("isDeductible") else "No",
            ])
        writer.writerow([])
        writer.writerow([
            "TOTALES", "", "", "", "", "",
            f'{sum(float(e.get("amount", 0)) for e in filtered):.2f}',
            f'{sum(float(e.get("itbisAmount", 0)) for e in filtered):.2f}',
            "", "", "",
        ])

    dest = io.BytesIO()
    dest.write(b"\xef\xbb\xbf")
    dest.write(output.getvalue().encode("utf-8"))
    dest.seek(0)

    filename = f"reporte_606_{year:04d}{month:02d}_{now.strftime('%Y%m%d')}.csv"
    return send_file(
        dest,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


# ═════════════════════════════════════════════════════════════════════
# REPORTE 606 — KPIs Dashboard
# ═════════════════════════════════════════════════════════════════════


@web_reports_606_bp.route("/reports/606/dashboard")
def reporte_606_dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    if not check_permission("canExpenses"):
        return render_template("auth/restricted.html", active_page="dashboard_606")
    owner_uid = session["user"]["ownerUID"]
    sandbox = session.get("is_sandbox_mode", True)

    now = datetime.utcnow()
    month = _parse_int(request.args.get("month"), now.month)
    year = _parse_int(request.args.get("year"), now.year)

    expenses = _get_expenses_for_period(owner_uid, sandbox, year, month)

    total_monto = sum(float(e.get("amount", 0)) for e in expenses)
    total_itbis = sum(float(e.get("itbisAmount", 0)) for e in expenses)
    total_itbis_deducible = sum(
        float(e.get("itbisAmount", 0)) for e in expenses if e.get("isITBISDeductible")
    )
    total_deducible = sum(
        float(e.get("amount", 0)) for e in expenses if e.get("isDeductible")
    )
    count = len(expenses)

    unique_suppliers = set()
    for e in expenses:
        sid = e.get("supplierId") or e.get("rncEmisor")
        if sid:
            unique_suppliers.add(sid)

    # Top 10 suppliers
    by_supplier = defaultdict(lambda: {"monto": 0.0, "itbis": 0.0, "count": 0})
    for e in expenses:
        key = e.get("supplierId") or e.get("rncEmisor") or "sin-id"
        by_supplier[key]["monto"] += float(e.get("amount", 0))
        by_supplier[key]["itbis"] += float(e.get("itbisAmount", 0))
        by_supplier[key]["count"] += 1
        if not by_supplier[key].get("name"):
            by_supplier[key]["name"] = e.get("providerName", "Sin nombre")
    top_suppliers = sorted(by_supplier.items(), key=lambda x: x[1]["monto"], reverse=True)[:10]

    # Tipo gasto breakdown
    by_tipo = defaultdict(lambda: {"monto": 0.0, "count": 0})
    for e in expenses:
        tg = e.get("tipoGastoDGII", "06")
        by_tipo[tg]["monto"] += float(e.get("amount", 0))
        by_tipo[tg]["count"] += 1
    tipo_breakdown = [{"code": k, "label": TIPO_GASTO_606.get(k, k), "monto": v["monto"], "count": v["count"]} for k, v in by_tipo.items()]
    tipo_breakdown.sort(key=lambda x: x["monto"], reverse=True)

    # e-CF type distribution
    by_ecf = defaultdict(lambda: {"monto": 0.0, "count": 0})
    for e in expenses:
        et = e.get("ecfType", "Otro")
        by_ecf[et]["monto"] += float(e.get("amount", 0))
        by_ecf[et]["count"] += 1
    ecf_dist = [{"code": k, "label": ECF_TYPE_LABELS.get(k, k), "monto": v["monto"], "count": v["count"]} for k, v in by_ecf.items()]
    ecf_dist.sort(key=lambda x: x["monto"], reverse=True)

    return render_template(
        "reports/dashboard_606.html",
        year=year,
        month=month,
        total_monto=total_monto,
        total_itbis=total_itbis,
        total_itbis_deducible=total_itbis_deducible,
        total_deducible=total_deducible,
        count=count,
        supplier_count=len(unique_suppliers),
        top_suppliers=top_suppliers,
        tipo_breakdown=tipo_breakdown,
        ecf_dist=ecf_dist,
        now=now,
        active_page="dashboard_606",
    )
