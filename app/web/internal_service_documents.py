"""UI de documentos internos de servicios gratuitos y promociones."""

import io
from datetime import date

from flask import Blueprint, flash, g, redirect, render_template, request, send_file, session, url_for

from app.services.db_service import DatabaseService
from app.services.internal_service_document_pdf_service import generate_internal_service_document_pdf
from app.services.internal_service_document_service import InternalServiceDocumentError, InternalServiceDocumentService
from app.utils.decorators import check_permission


web_internal_service_documents_bp = Blueprint("web_internal_service_documents", __name__)


def _context():
    user = session.get("user", {})
    return user.get("ownerUID", ""), session.get("selected_company_id"), session.get("is_sandbox_mode", True)


def _require(permission):
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    if session.get("user", {}).get("role") != "owner" and not check_permission(permission):
        return render_template("auth/restricted.html", feature_name="Documentos internos", required_permission=permission), 403
    return None


def _lines_from_form():
    item_ids = request.form.getlist("lineItemId")
    quantities = request.form.getlist("lineQty")
    discounts = request.form.getlist("lineDiscount")
    return [
        {"itemId": item_id, "quantity": quantities[index] if index < len(quantities) else "1", "discountRate": discounts[index] if index < len(discounts) else "100"}
        for index, item_id in enumerate(item_ids) if item_id
    ]


@web_internal_service_documents_bp.route("/internal-documents")
def list_documents():
    denied = _require("canViewInternalServiceDocuments")
    if denied:
        return denied
    _, company_id, sandbox = _context()
    documents = InternalServiceDocumentService.list(company_id, sandbox)
    query = request.args.get("q", "").strip().lower()
    state = request.args.get("state", "")
    promotion_type = request.args.get("promotionType", "")
    if query:
        documents = [d for d in documents if query in d.get("clientSnapshot", {}).get("razonSocial", "").lower() or query in d.get("clientSnapshot", {}).get("rnc", "").lower()]
    if state:
        documents = [d for d in documents if d.get("calculatedState") == state]
    if promotion_type:
        documents = [d for d in documents if d.get("promotionType") == promotion_type]
    return render_template("internal_documents/list.html", documents=documents, active_page="internal_documents", q=query, state=state, promotion_type=promotion_type)


@web_internal_service_documents_bp.route("/internal-documents/new", methods=["GET", "POST"])
def new_document():
    denied = _require("canCreateInternalServiceDocument")
    if denied:
        return denied
    owner_uid, company_id, sandbox = _context()
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox, company_id=company_id, branch_id=g.get("branch_id"), project_id=g.get("project_id"))
    items = DatabaseService.get_items(owner_uid, sandbox=sandbox, company_id=company_id, branch_id=g.get("branch_id"), project_id=g.get("project_id"))
    if request.method == "POST":
        try:
            document = InternalServiceDocumentService.create(
                owner_uid=owner_uid, company_id=company_id, sandbox=sandbox,
                client_id=request.form.get("clientId", ""), issue_date=request.form.get("issueDate") or date.today().isoformat(),
                reason=request.form.get("reason", ""), promotion_type=request.form.get("promotionType", ""),
                promotion_start=request.form.get("promotionStartDate", ""), promotion_end=request.form.get("promotionEndDate", ""),
                billing_start=request.form.get("billingStartDate", ""), lines=_lines_from_form(), notes=request.form.get("notes", ""),
                idempotency_key=request.form.get("idempotencyKey", ""), actor=session.get("user", {}),
            )
            flash("Documento interno creado correctamente.", "success")
            return redirect(url_for("web_internal_service_documents.detail_document", document_id=document["id"]))
        except (InternalServiceDocumentError, ValueError) as error:
            flash(str(error), "error")
    return render_template("internal_documents/form.html", clients=clients, items=items, active_page="internal_documents", today=date.today().isoformat())


@web_internal_service_documents_bp.route("/internal-documents/<document_id>")
def detail_document(document_id):
    denied = _require("canViewInternalServiceDocuments")
    if denied:
        return denied
    _, company_id, sandbox = _context()
    document = InternalServiceDocumentService.get(company_id, document_id, sandbox)
    if not document:
        return "Documento no encontrado", 404
    return render_template("internal_documents/detail.html", document=document, active_page="internal_documents")


@web_internal_service_documents_bp.route("/internal-documents/<document_id>/pdf")
def document_pdf(document_id):
    denied = _require("canDownloadInternalServiceDocument")
    if denied:
        return denied
    owner_uid, company_id, sandbox = _context()
    document = InternalServiceDocumentService.get(company_id, document_id, sandbox)
    if not document:
        return "Documento no encontrado", 404
    company = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
    pdf = generate_internal_service_document_pdf(document, company, request.host_url)
    return send_file(io.BytesIO(pdf), mimetype="application/pdf", as_attachment=False, download_name=f"{document['documentNumber']}.pdf")


@web_internal_service_documents_bp.route("/internal-documents/<document_id>/download")
def document_download(document_id):
    denied = _require("canDownloadInternalServiceDocument")
    if denied:
        return denied
    owner_uid, company_id, sandbox = _context()
    document = InternalServiceDocumentService.get(company_id, document_id, sandbox)
    if not document:
        return "Documento no encontrado", 404
    company = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
    pdf = generate_internal_service_document_pdf(document, company, request.host_url)
    return send_file(io.BytesIO(pdf), mimetype="application/pdf", as_attachment=True, download_name=f"{document['documentNumber']}.pdf")


@web_internal_service_documents_bp.route("/internal-documents/<document_id>/void", methods=["POST"])
def void_document(document_id):
    denied = _require("canVoidInternalServiceDocument")
    if denied:
        return denied
    _, company_id, sandbox = _context()
    try:
        InternalServiceDocumentService.void(company_id, document_id, sandbox, request.form.get("reason", ""), session.get("user", {}))
        flash("Documento interno anulado correctamente.", "success")
    except InternalServiceDocumentError as error:
        flash(str(error), "error")
    return redirect(url_for("web_internal_service_documents.detail_document", document_id=document_id))
