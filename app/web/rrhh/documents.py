"""RRHH module — auto-extracted."""

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/documents/upload", methods=["POST"])
def employee_document_upload(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    category = request.form.get("category", "other")
    notes = request.form.get("notes", "").strip()
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debes seleccionar un archivo.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    import os, base64
    content = base64.b64encode(file.read()).decode("utf-8")
    max_size = 10 * 1024 * 1024
    if len(content) > max_size * 1.4:
        flash("El archivo excede el tamaño máximo de 10MB.", "error")
        return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))

    doc_id = str(uuid.uuid4())
    hr.save_employee_document(owner_uid, {
        "id": doc_id,
        "employeeId": employee_id,
        "name": file.filename,
        "category": category,
        "notes": notes,
        "size": len(content),
        "contentType": file.content_type or "application/octet-stream",
        "data": content,
        "uploadedBy": session.get("user", {}).get("email", ""),
        "uploadedAt": datetime.now(timezone.utc).isoformat(),
    }, sandbox=sandbox)

    flash("Documento subido exitosamente.", "success")
    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/documents/<doc_id>/download")
def employee_document_download(employee_id, doc_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr

    employee = hr.get_employee(owner_uid, employee_id, sandbox=sandbox)
    if not employee:
        return "", 404

    docs = hr.get_employee_documents(owner_uid, employee_id, sandbox=sandbox)
    doc = next((d for d in docs if d.get("id") == doc_id), None)
    if not doc or not doc.get("data"):
        return "", 404

    import base64, io as _io
    content = base64.b64decode(doc["data"])
    return send_file(_io.BytesIO(content), mimetype=doc.get("contentType", "application/octet-stream"),
                     as_attachment=True, download_name=doc.get("name", "documento"))


@web_rrhh_bp.route("/rrhh/employees/<employee_id>/documents/<doc_id>/delete", methods=["POST"])
def employee_document_delete(employee_id, doc_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox = _get_owner_uid_and_sandbox()
    from app.services import hr_data_service as hr
    hr.delete_employee_document(owner_uid, doc_id, sandbox=sandbox)
    flash("Documento eliminado.", "success")
    return redirect(url_for("web_rrhh.employee_view", employee_id=employee_id))


