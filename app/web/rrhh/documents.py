"""RRHH module — auto-extracted."""

import uuid
from datetime import datetime, timezone

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from werkzeug.utils import secure_filename

from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr
from app.services.db_service import DatabaseService, firebase_storage_bucket, _invalidate_storage_cache

MAX_SIZE = 10 * 1024 * 1024


def _delete_storage_blob(storage_path: str, owner_uid: str):
    if not storage_path or storage_path.startswith("/uploads/"):
        return
    try:
        if firebase_storage_bucket:
            firebase_storage_bucket.blob(storage_path).delete()
        if owner_uid:
            _invalidate_storage_cache(owner_uid)
    except Exception as e:
        print(f"⚠️ Error al eliminar archivo de storage: {e}")


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/documents/upload", methods=["POST"])
def employee_document_upload(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    category = request.form.get("category", "other")
    notes = request.form.get("notes", "").strip()
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debes seleccionar un archivo.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    file_data = file.read()
    if len(file_data) > MAX_SIZE:
        flash("El archivo excede el tamaño máximo de 10MB.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    mime_type = file.content_type or "application/octet-stream"
    safe_name = secure_filename(file.filename) or "documento"
    destination_path = f"users/{owner_uid}/employee_documents/{employee_id}/{uuid.uuid4().hex[:8]}_{safe_name}"
    url = DatabaseService.upload_file_to_storage(file_data, destination_path, mime_type)

    doc_id = str(uuid.uuid4())
    hr.save_employee_document(company_id, {
        "id": doc_id,
        "employeeId": employee_id,
        "name": file.filename,
        "category": category,
        "notes": notes,
        "size": len(file_data),
        "contentType": mime_type,
        "url": url,
        "storagePath": destination_path,
        "uploadedBy": session.get("user", {}).get("email", ""),
        "uploadedAt": datetime.now(timezone.utc).isoformat(),
    }, sandbox=sandbox)

    flash("Documento subido exitosamente.", "success")
    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/documents/<doc_id>/download")
def employee_document_download(employee_id, doc_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)
    if not employee:
        return "", 404

    docs = hr.get_employee_documents(company_id, employee_id, sandbox=sandbox)
    doc = next((d for d in docs if d.get("id") == doc_id), None)
    if not doc:
        return "", 404

    if doc.get("url"):
        return redirect(doc["url"])

    if doc.get("data"):
        import base64, io as _io
        content = base64.b64decode(doc["data"])
        return send_file(_io.BytesIO(content), mimetype=doc.get("contentType", "application/octet-stream"),
                         as_attachment=True, download_name=doc.get("name", "documento"))

    return "", 404


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/documents/<doc_id>/delete", methods=["POST"])
def employee_document_delete(employee_id, doc_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    docs = hr.get_employee_documents(company_id, employee_id, sandbox=sandbox)
    doc = next((d for d in docs if d.get("id") == doc_id), None)
    if doc:
        _delete_storage_blob(doc.get("storagePath", ""), owner_uid)

    hr.delete_employee_document(company_id, doc_id, sandbox=sandbox)
    flash("Documento eliminado.", "success")
    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))
