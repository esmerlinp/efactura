from flask import Blueprint, render_template, session, request, make_response, redirect, url_for, flash
from app.repositories.receptor_repository import ReceptorRepository
from app.services.db_service import DatabaseService

web_recepcion_bp = Blueprint("web_recepcion", __name__)


def _check_auth():
    if "user" not in session:
        return False
    return True


def _get_context():
    owner_uid = session["user"]["ownerUID"]
    company_id = session.get("selected_company_id")
    sandbox = session.get("is_sandbox_mode", True)
    return owner_uid, company_id, sandbox


@web_recepcion_bp.route("/recepcion/ecf")
def list_received_ecf():
    if not _check_auth():
        return redirect(url_for("web_auth.login"))
    owner_uid, company_id, sandbox = _get_context()
    status_filter = request.args.get("status", "")
    documents = ReceptorRepository.list_received_ecf(
        owner_uid, sandbox=sandbox,
        status=status_filter if status_filter else None
    )
    return render_template(
        "recepcion/list.html",
        documents=documents,
        active_page="recepcion_ecf",
        status_filter=status_filter,
        company_id=company_id,
    )


@web_recepcion_bp.route("/recepcion/ecf/<ecf_id>")
def detail_received_ecf(ecf_id):
    if not _check_auth():
        return redirect(url_for("web_auth.login"))
    owner_uid, company_id, sandbox = _get_context()
    doc = ReceptorRepository.get_received_ecf(owner_uid, ecf_id, sandbox=sandbox)
    if not doc:
        flash("Documento no encontrado.", "error")
        return redirect(url_for("web_recepcion.list_received_ecf"))
    return render_template(
        "recepcion/detail.html",
        doc=doc,
        active_page="recepcion_ecf",
        company_id=company_id,
    )


@web_recepcion_bp.route("/recepcion/ecf/<ecf_id>/xml")
def download_received_xml(ecf_id):
    if not _check_auth():
        return redirect(url_for("web_auth.login"))
    owner_uid, company_id, sandbox = _get_context()
    doc = ReceptorRepository.get_received_ecf(owner_uid, ecf_id, sandbox=sandbox)
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
    owner_uid, company_id, sandbox = _get_context()
    doc = ReceptorRepository.get_received_ecf(owner_uid, ecf_id, sandbox=sandbox)
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
    owner_uid, company_id, sandbox = _get_context()
    documents = ReceptorRepository.list_received_approvals(owner_uid, sandbox=sandbox)
    return render_template(
        "recepcion/approvals_list.html",
        documents=documents,
        active_page="recepcion_aprobaciones",
        company_id=company_id,
    )
