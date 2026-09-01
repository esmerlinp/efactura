from flask import Blueprint, render_template, session, request, make_response, redirect, url_for, flash, send_file
from app.repositories.receptor_repository import ReceptorRepository
from app.services.db_service import DatabaseService
from app.services.receptor_xml_service import ReceptorXmlService

web_recepcion_bp = Blueprint("web_recepcion", __name__)


def _check_auth():
    if "user" not in session:
        return False
    return True


def _get_context():
    owner_uid = session.get("selected_owner_uid") or session["user"].get("ownerUID")
    company_id = session.get("selected_company_id")
    return owner_uid, company_id


@web_recepcion_bp.route("/recepcion/ecf")
def list_received_ecf():
    if not _check_auth():
        return redirect(url_for("web_auth.login"))
    owner_uid, company_id = _get_context()

    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    per_page = request.args.get("per_page", "10").strip()
    sort = request.args.get("sort", "received_at").strip()
    order = request.args.get("order", "desc").strip()
    if order not in ("asc", "desc"):
        order = "desc"
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1

    documents = ReceptorRepository.list_received_ecf_merged(owner_uid, limit=None)

    # Filtros en memoria
    filtered = []
    for doc in documents:
        if q:
            q_lower = q.lower()
            haystack = " ".join([
                str(doc.get("encf") or ""),
                str(doc.get("sender_rnc") or ""),
                str(doc.get("sender_name") or ""),
                str(doc.get("receiver_rnc") or ""),
                str(doc.get("receiver_name") or ""),
                str(doc.get("ecf_type") or ""),
                str(doc.get("track_id") or ""),
            ]).lower()
            if q_lower not in haystack:
                continue
        if status and doc.get("status") != status:
            continue
        received_date = str(doc.get("received_at") or "")[:10]
        if start_date and received_date < start_date:
            continue
        if end_date and received_date > end_date:
            continue
        filtered.append(doc)

    # Ordenar por columna (click en encabezados del grid)
    SORT_KEYS = {
        "encf": lambda d: str(d.get("encf") or "").lower(),
        "sender_name": lambda d: str(d.get("sender_name") or "").lower(),
        "sender_rnc": lambda d: str(d.get("sender_rnc") or "").lower(),
        "ecf_type": lambda d: str(d.get("ecf_type") or "").lower(),
        "monto_total": lambda d: float(d.get("monto_total") or 0),
        "received_at": lambda d: str(d.get("received_at") or ""),
        "status": lambda d: str(d.get("status") or "").lower(),
    }
    key_fn = SORT_KEYS.get(sort) or SORT_KEYS["received_at"]
    try:
        filtered.sort(key=key_fn, reverse=(order == "desc"))
    except Exception:
        filtered.sort(key=lambda d: str(d.get("received_at") or ""), reverse=True)

    # Exportar a CSV si se solicita
    if request.args.get("export") == "csv":
        import csv
        import io
        from datetime import datetime, timezone
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow([
            "RNC Emisor", "Razón Social Emisor", "e-NCF", "Tipo",
            "Monto Total (RD$)", "Recibido", "Estado", "Track ID",
        ])
        for doc in filtered:
            writer.writerow([
                doc.get("sender_rnc", ""),
                doc.get("sender_name", ""),
                doc.get("encf", ""),
                doc.get("ecf_type", ""),
                f"{float(doc.get('monto_total') or 0):.2f}",
                str(doc.get("received_at") or "")[:10],
                doc.get("status", ""),
                doc.get("track_id", ""),
            ])
        dest = io.BytesIO()
        dest.write(b'\xef\xbb\xbf')  # UTF-8 BOM
        dest.write(output.getvalue().encode("utf-8"))
        dest.seek(0)
        filename = f"ecf_recibidos_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(
            dest,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename,
        )

    total_items = len(filtered)
    if per_page == "all":
        per_page_val = max(1, total_items)
    else:
        try:
            per_page_val = int(per_page)
            if per_page_val not in [5, 10, 15, 20]:
                per_page_val = 10
        except ValueError:
            per_page_val = 10

    total_pages = max(1, (total_items + per_page_val - 1) // per_page_val)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start_idx = (page - 1) * per_page_val
    end_idx = start_idx + per_page_val
    paginated_documents = filtered[start_idx:end_idx]

    start_count = ((page - 1) * per_page_val) + 1 if total_items > 0 else 0
    end_count = min(page * per_page_val, total_items)

    return render_template(
        "recepcion/list.html",
        documents=paginated_documents,
        active_page="recepcion_ecf",
        company_id=company_id,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
        has_prev=page > 1,
        has_next=page < total_pages,
        start_count=start_count,
        end_count=end_count,
        per_page=per_page,
        q=q,
        status=status,
        start_date=start_date,
        end_date=end_date,
        sort=sort,
        order=order,
    )


@web_recepcion_bp.route("/recepcion/ecf/<ecf_id>")
def detail_received_ecf(ecf_id):
    if not _check_auth():
        return redirect(url_for("web_auth.login"))
    owner_uid, company_id = _get_context()
    doc = ReceptorRepository.get_received_ecf_merged(owner_uid, ecf_id)
    if not doc:
        flash("Documento no encontrado.", "error")
        return redirect(url_for("web_recepcion.list_received_ecf"))
    detail = ReceptorXmlService.default_detail()
    xml_content = doc.get("xml_content", "")
    if xml_content:
        try:
            parsed, _ = ReceptorXmlService.parse_ecf_detail(xml_content.encode("utf-8"))
            if parsed:
                detail.update(parsed)
        except Exception:
            pass
    return render_template(
        "recepcion/detail.html",
        doc=doc,
        detail=detail,
        active_page="recepcion_ecf",
        company_id=company_id,
    )


@web_recepcion_bp.route("/recepcion/ecf/<ecf_id>/xml")
def download_received_xml(ecf_id):
    if not _check_auth():
        return redirect(url_for("web_auth.login"))
    owner_uid, company_id = _get_context()
    doc = ReceptorRepository.get_received_ecf_merged(owner_uid, ecf_id)
    if not doc:
        flash("Documento no encontrado.", "error")
        return redirect(url_for("web_recepcion.list_received_ecf"))
    xml_content = doc.get("xml_content", "")
    encf = doc.get("encf", ecf_id)
    rnc = doc.get("sender_rnc", "")
    filename = f"{rnc}{encf}.xml"
    response = make_response(xml_content)
    response.headers["Content-Type"] = "application/xml; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@web_recepcion_bp.route("/recepcion/ecf/<ecf_id>/arecf")
def download_arecf(ecf_id):
    if not _check_auth():
        return redirect(url_for("web_auth.login"))
    owner_uid, company_id = _get_context()
    doc = ReceptorRepository.get_received_ecf_merged(owner_uid, ecf_id)
    if not doc:
        flash("Documento no encontrado.", "error")
        return redirect(url_for("web_recepcion.list_received_ecf"))
    arecf_xml = doc.get("arecf_xml", "")
    if not arecf_xml:
        flash("No hay ARECF disponible para este documento.", "warning")
        return redirect(url_for("web_recepcion.detail_received_ecf", ecf_id=ecf_id))
    encf = doc.get("encf", ecf_id)
    filename = f"ARECF_{encf}.xml"
    response = make_response(arecf_xml)
    response.headers["Content-Type"] = "application/xml; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@web_recepcion_bp.route("/recepcion/aprobaciones")
def list_approvals():
    if not _check_auth():
        return redirect(url_for("web_auth.login"))
    owner_uid, company_id = _get_context()
    documents = ReceptorRepository.list_received_approvals_merged(owner_uid)
    return render_template(
        "recepcion/approvals_list.html",
        documents=documents,
        active_page="recepcion_aprobaciones",
        company_id=company_id,
    )
