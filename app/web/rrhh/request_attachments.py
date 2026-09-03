"""RRHH module — auto-extracted.

Adjuntos (documentos de aval) para solicitudes de vacaciones y permisos/licencias.
Se almacenan en Firebase Storage (metadata en Firestore).
"""

import base64
import io as _io
import uuid
from datetime import datetime, timezone

from flask import request, redirect, url_for, session, flash, send_file
from werkzeug.utils import secure_filename

from app.web.rrhh import web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required
from app.services import hr_data_service as hr
from app.services.db_service import DatabaseService, firebase_storage_bucket, _invalidate_storage_cache

MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10MB


def _delete_storage_blob(storage_path, owner_uid):
    if not storage_path or storage_path.startswith("/uploads/"):
        return
    try:
        if firebase_storage_bucket:
            firebase_storage_bucket.blob(storage_path).delete()
        if owner_uid:
            _invalidate_storage_cache(owner_uid)
    except Exception as e:
        print(f"⚠️ Error al eliminar adjunto de storage: {e}")


def save_uploaded_files(company_id, request_id, request_type, sandbox):
    """Sube a Firebase Storage los archivos del formulario y guarda su metadata."""
    owner_uid, _, _ = _get_owner_uid_and_sandbox()
    files = request.files.getlist("files")
    saved = 0
    for f in files:
        if not f or not f.filename:
            continue
        file_data = f.read()
        if len(file_data) > MAX_ATTACHMENT_SIZE:
            continue
        mime_type = f.content_type or "application/octet-stream"
        safe_name = secure_filename(f.filename) or "adjunto"
        destination_path = f"users/{owner_uid}/request_attachments/{request_id}/{uuid.uuid4().hex[:8]}_{safe_name}"
        url = DatabaseService.upload_file_to_storage(file_data, destination_path, mime_type)
        hr.save_request_attachment(company_id, {
            "id": str(uuid.uuid4()),
            "requestId": request_id,
            "requestType": request_type,
            "name": f.filename,
            "size": len(file_data),
            "contentType": mime_type,
            "url": url,
            "storagePath": destination_path,
            "uploadedBy": session.get("user", {}).get("email", ""),
            "uploadedAt": datetime.now(timezone.utc).isoformat(),
        }, sandbox=sandbox)
        saved += 1
    return saved


def _get_company_request(request_id, request_type):
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    if request_type == "vacation":
        req = hr.get_vacation_request(company_id, request_id, sandbox=sandbox)
    else:
        req = hr.get_leave_request(company_id, request_id, sandbox=sandbox)
    return company_id, sandbox, req


def _download(company_id, request_id, doc_id, sandbox):
    doc = next((d for d in hr.get_request_attachments(company_id, request_id, sandbox=sandbox)
                if d.get("id") == doc_id), None)
    if not doc:
        return None
    if doc.get("url"):
        return redirect(doc["url"])
    if doc.get("data"):
        content = base64.b64decode(doc["data"])
        return send_file(_io.BytesIO(content),
                         mimetype=doc.get("contentType", "application/octet-stream"),
                         as_attachment=True, download_name=doc.get("name", "adjunto"))
    return None


@web_rrhh_bp.route("/rrhh/vacations/<request_id>/attachments/upload", methods=["POST"])
def vacation_attachment_upload(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    company_id, sandbox, req = _get_company_request(request_id, "vacation")
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.vacation_list"))
    save_uploaded_files(company_id, request_id, "vacation", sandbox)
    flash("Adjuntos subidos.", "success")
    return redirect(url_for("web_rrhh.vacation_list"))


@web_rrhh_bp.route("/rrhh/vacations/<request_id>/attachments/<doc_id>/download")
def vacation_attachment_download(request_id, doc_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    company_id, sandbox, req = _get_company_request(request_id, "vacation")
    if not req:
        return "", 404
    return _download(company_id, request_id, doc_id, sandbox) or ("", 404)


@web_rrhh_bp.route("/rrhh/vacations/<request_id>/attachments/<doc_id>/delete", methods=["POST"])
def vacation_attachment_delete(request_id, doc_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    req = hr.get_vacation_request(company_id, request_id, sandbox=sandbox)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.vacation_list"))
    doc = next((d for d in hr.get_request_attachments(company_id, request_id, sandbox=sandbox)
                if d.get("id") == doc_id), None)
    if doc:
        _delete_storage_blob(doc.get("storagePath", ""), owner_uid)
    hr.delete_request_attachment(company_id, doc_id, sandbox=sandbox)
    flash("Adjunto eliminado.", "success")
    return redirect(url_for("web_rrhh.vacation_list"))


@web_rrhh_bp.route("/rrhh/leaves/<request_id>/attachments/upload", methods=["POST"])
def leave_attachment_upload(request_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    company_id, sandbox, req = _get_company_request(request_id, "leave")
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.leave_list"))
    save_uploaded_files(company_id, request_id, "leave", sandbox)
    flash("Adjuntos subidos.", "success")
    return redirect(url_for("web_rrhh.leave_list"))


@web_rrhh_bp.route("/rrhh/leaves/<request_id>/attachments/<doc_id>/download")
def leave_attachment_download(request_id, doc_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    company_id, sandbox, req = _get_company_request(request_id, "leave")
    if not req:
        return "", 404
    return _download(company_id, request_id, doc_id, sandbox) or ("", 404)


@web_rrhh_bp.route("/rrhh/leaves/<request_id>/attachments/<doc_id>/delete", methods=["POST"])
def leave_attachment_delete(request_id, doc_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    req = hr.get_leave_request(company_id, request_id, sandbox=sandbox)
    if not req:
        flash("Solicitud no encontrada.", "error")
        return redirect(url_for("web_rrhh.leave_list"))
    doc = next((d for d in hr.get_request_attachments(company_id, request_id, sandbox=sandbox)
                if d.get("id") == doc_id), None)
    if doc:
        _delete_storage_blob(doc.get("storagePath", ""), owner_uid)
    hr.delete_request_attachment(company_id, doc_id, sandbox=sandbox)
    flash("Adjunto eliminado.", "success")
    return redirect(url_for("web_rrhh.leave_list"))
