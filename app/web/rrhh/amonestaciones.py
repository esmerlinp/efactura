"""RRHH — Carta de Amonestación (formulario de acción persistente).

Flujo:
- ``GET/POST /rrhh/employees/<id>/amonestacion/new``: formulario → Guardar
  (persiste el registro, estado "Pendiente de firma").
- ``GET /rrhh/amonestaciones/<id>/pdf``: descarga la plantilla pre-llenada
  (generada on-demand desde los datos guardados).
- ``POST /rrhh/amonestaciones/<id>/firmada/upload``: sube la carta firmada y
  marca el registro como "Firmada".
- ``GET /rrhh/amonestaciones``: listado global.
- ``GET /rrhh/amonestaciones/<id>``: detalle.
- ``GET/POST /rrhh/amonestaciones/<id>/edit``: edición.
- ``POST /rrhh/amonestaciones/<id>/delete``: eliminación.
"""

import io
import uuid
from datetime import datetime, timezone, date

from flask import request, redirect, url_for, session, flash, send_file, render_template
from werkzeug.utils import secure_filename

from app.web.rrhh import web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required
from app.services import hr_data_service as hr
from app.services.db_service import DatabaseService, firebase_storage_bucket, _invalidate_storage_cache
from app.services.amonestacion_service import (
    AMONESTACION_TIPOS, build_amonestacion_data, generate_amonestacion_pdf,
)

MAX_SIZE = 10 * 1024 * 1024


def _company_data(owner_uid, sandbox, company_id=None):
    from app.services.offboarding_document_service import _company_data as _off_company_data
    return _off_company_data(owner_uid, sandbox=sandbox, company_id=company_id)


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


def _fecha_iso(fecha: str) -> str:
    fecha = (fecha or "").strip()
    return fecha if fecha else date.today().isoformat()


def _existing_document(company_id, employee_id, doc_id, sandbox):
    if not doc_id:
        return None
    docs = hr.get_employee_documents(company_id, employee_id, sandbox=sandbox)
    return next((d for d in docs if d.get("id") == doc_id), None)


def _record_payload(employee, tipo, tipo_label, hecho, fecha_iso, fecha_legible,
                    signer_name, signer_position, existing=None):
    email = session.get("user", {}).get("email", "")
    now = datetime.now(timezone.utc).isoformat()
    existing = existing or {}
    payload = {
        "id": existing.get("id") or str(uuid.uuid4()),
        "employeeId": employee.get("id", ""),
        "employeeName": employee.get("fullName", ""),
        "cedula": employee.get("cedula", "") or employee.get("idNumber", ""),
        "tipo": tipo,
        "tipoLabel": tipo_label,
        "hecho": hecho,
        "fecha": fecha_iso,
        "fechaLegible": fecha_legible,
        "signerName": signer_name,
        "signerPosition": signer_position,
        "firmada": bool(existing.get("firmada", False)),
        "documentoFirmadoId": existing.get("documentoFirmadoId", ""),
        "documentoFirmadoName": existing.get("documentoFirmadoName", ""),
        "firmadaAt": existing.get("firmadaAt", ""),
        "firmadaBy": existing.get("firmadaBy", ""),
        "createdBy": existing.get("createdBy", email),
        "createdAt": existing.get("createdAt", now),
        "updatedBy": email,
        "updatedAt": now,
    }
    return payload


def _form_data(form, amonestacion=None):
    """Extrae y valida los campos comunes de crear/editar. Retorna (data, error)."""
    amonestacion = amonestacion or {}
    tipo = form.get("tipo", "").strip()
    hecho = form.get("hecho", "").strip()
    fecha = form.get("fecha", "").strip() or amonestacion.get("fecha", "")
    signer_name = form.get("signerName", "").strip()
    signer_position = form.get("signerPosition", "").strip()

    if tipo not in AMONESTACION_TIPOS:
        return None, "Debes seleccionar un tipo de amonestación válido."
    if not hecho:
        return None, "Debes describir el hecho que motiva la amonestación."

    return {
        "tipo": tipo,
        "hecho": hecho,
        "fecha": fecha,
        "signer_name": signer_name,
        "signer_position": signer_position,
    }, None


# ── Crear (formulario de acción) ─────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/employees/<employee_id>/amonestacion/new", methods=["GET", "POST"])
def amonestacion_new(employee_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    employee = hr.get_employee(company_id, employee_id, sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.employee_list"))

    company = _company_data(owner_uid, sandbox, company_id=company_id)

    if request.method == "GET":
        amonestacion = {
            "fecha": date.today().isoformat(),
            "signerName": company.get("representativeName", ""),
            "signerPosition": company.get("representativePosition", "") or "Representante Legal",
        }
        return render_template("rrhh/amonestacion_form.html",
                               active_page="rrhh_employees",
                               amonestacion=amonestacion, employee=employee,
                               AMONESTACION_TIPOS=AMONESTACION_TIPOS, is_new=True)

    parsed, error = _form_data(request.form)
    if error:
        flash(error, "error")
        return redirect(url_for("web_rrhh.amonestacion_new", employee_id=employee_id))

    signer_name = parsed["signer_name"] or company.get("representativeName", "")
    signer_position = parsed["signer_position"] or company.get("representativePosition", "") or "Representante Legal"

    data = build_amonestacion_data(
        tipo=parsed["tipo"], hecho=parsed["hecho"], fecha=parsed["fecha"],
        signer_name=signer_name, signer_position=signer_position,
    )
    record = _record_payload(
        employee, parsed["tipo"], data["tipo_label"], parsed["hecho"],
        _fecha_iso(parsed["fecha"]), data["fecha"], signer_name, signer_position,
    )
    hr.save_amonestacion(company_id, record["id"], record, sandbox=sandbox)

    try:
        from app.services.payroll_audit_service import log_employee_action
        log_employee_action(
            company_id, employee_id, "amonestacion_generated",
            comment=f"Amonestación {data['tipo_label']}",
            changes={"tipo": parsed["tipo"], "amonestacionId": record["id"]},
            user_email=session.get("user", {}).get("email", ""),
            sandbox=sandbox,
        )
    except Exception as e:
        print(f"⚠️ amonestacion.log_employee_action: {e}")

    flash("Amonestación guardada. Descarga la plantilla o sube la carta firmada.", "success")
    return redirect(url_for("web_rrhh.amonestacion_detail", amonestacion_id=record["id"]))


# ── Descargar plantilla (on-demand) ─────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/amonestaciones/<amonestacion_id>/pdf")
def amonestacion_pdf(amonestacion_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    amonestacion = hr.get_amonestacion(company_id, amonestacion_id, sandbox=sandbox)
    if not amonestacion:
        flash("Amonestación no encontrada.", "error")
        return redirect(url_for("web_rrhh.amonestacion_list"))

    employee = hr.get_employee(company_id, amonestacion.get("employeeId", ""), sandbox=sandbox)
    if not employee:
        return "", 404

    company = _company_data(owner_uid, sandbox, company_id=company_id)
    data = build_amonestacion_data(
        tipo=amonestacion.get("tipo", ""),
        hecho=amonestacion.get("hecho", ""),
        fecha=amonestacion.get("fecha", ""),
        signer_name=amonestacion.get("signerName", ""),
        signer_position=amonestacion.get("signerPosition", ""),
    )
    try:
        pdf_bytes = generate_amonestacion_pdf(employee, company, request.host_url, data)
    except Exception as e:
        print(f"Error generando carta de amonestación: {e}")
        flash("Error al generar la carta de amonestación.", "error")
        return redirect(url_for("web_rrhh.amonestacion_detail", amonestacion_id=amonestacion_id))

    filename = f"amonestacion_{amonestacion.get('tipo', '')}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.pdf"
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name=filename)


# ── Subir carta firmada ─────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/amonestaciones/<amonestacion_id>/firmada/upload", methods=["POST"])
def amonestacion_firmar_upload(amonestacion_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    amonestacion = hr.get_amonestacion(company_id, amonestacion_id, sandbox=sandbox)
    if not amonestacion:
        flash("Amonestación no encontrada.", "error")
        return redirect(url_for("web_rrhh.amonestacion_list"))

    file = request.files.get("file")
    if not file or not file.filename:
        flash("Debes seleccionar un archivo.", "error")
        return redirect(url_for("web_rrhh.amonestacion_detail", amonestacion_id=amonestacion_id))

    file_data = file.read()
    if len(file_data) > MAX_SIZE:
        flash("El archivo excede el tamaño máximo de 10MB.", "error")
        return redirect(url_for("web_rrhh.amonestacion_detail", amonestacion_id=amonestacion_id))

    employee_id = amonestacion.get("employeeId", "")
    mime_type = file.content_type or "application/pdf"
    safe_name = secure_filename(file.filename) or "amonestacion_firmada.pdf"
    destination_path = f"users/{owner_uid}/employee_documents/{employee_id}/{uuid.uuid4().hex[:8]}_{safe_name}"
    url = DatabaseService.upload_file_to_storage(file_data, destination_path, mime_type)

    doc_id = str(uuid.uuid4())
    hr.save_employee_document(company_id, {
        "id": doc_id,
        "employeeId": employee_id,
        "name": file.filename,
        "category": "carta_amonestacion",
        "signed": True,
        "notes": f"Carta de amonestación firmada — {amonestacion.get('tipoLabel', '')}",
        "size": len(file_data),
        "contentType": mime_type,
        "url": url,
        "storagePath": destination_path,
        "uploadedBy": session.get("user", {}).get("email", ""),
        "uploadedAt": datetime.now(timezone.utc).isoformat(),
    }, sandbox=sandbox)

    amonestacion["firmada"] = True
    amonestacion["documentoFirmadoId"] = doc_id
    amonestacion["documentoFirmadoName"] = file.filename
    amonestacion["firmadaAt"] = datetime.now(timezone.utc).isoformat()
    amonestacion["firmadaBy"] = session.get("user", {}).get("email", "")
    hr.save_amonestacion(company_id, amonestacion_id, amonestacion, sandbox=sandbox)

    try:
        from app.services.payroll_audit_service import log_employee_action
        log_employee_action(
            company_id, employee_id, "amonestacion_firmada",
            comment=f"Amonestación {amonestacion.get('tipoLabel', '')} firmada",
            changes={"tipo": amonestacion.get("tipo", ""), "amonestacionId": amonestacion_id},
            user_email=session.get("user", {}).get("email", ""),
            sandbox=sandbox,
        )
    except Exception as e:
        print(f"⚠️ amonestacion.log_employee_action (firmada): {e}")

    flash("Carta firmada subida. La amonestación quedó marcada como Firmada.", "success")
    return redirect(url_for("web_rrhh.amonestacion_detail", amonestacion_id=amonestacion_id))


@web_rrhh_bp.route("/rrhh/amonestaciones/<amonestacion_id>/firmada/delete", methods=["POST"])
def amonestacion_firmar_delete(amonestacion_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    amonestacion = hr.get_amonestacion(company_id, amonestacion_id, sandbox=sandbox)
    if not amonestacion:
        flash("Amonestación no encontrada.", "error")
        return redirect(url_for("web_rrhh.amonestacion_list"))

    doc = _existing_document(company_id, amonestacion.get("employeeId", ""),
                             amonestacion.get("documentoFirmadoId", ""), sandbox)
    if doc:
        _delete_storage_blob(doc.get("storagePath", ""), owner_uid)
        hr.delete_employee_document(company_id, doc.get("id", ""), sandbox=sandbox)

    amonestacion["firmada"] = False
    amonestacion["documentoFirmadoId"] = ""
    amonestacion["documentoFirmadoName"] = ""
    amonestacion["firmadaAt"] = ""
    amonestacion["firmadaBy"] = ""
    hr.save_amonestacion(company_id, amonestacion_id, amonestacion, sandbox=sandbox)

    flash("Carta firmada eliminada. La amonestación volvió a 'Pendiente de firma'.", "info")
    return redirect(url_for("web_rrhh.amonestacion_detail", amonestacion_id=amonestacion_id))


# ── Listado global ──────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/amonestaciones")
def amonestacion_list():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    amonestaciones = hr.get_amonestaciones(company_id, sandbox=sandbox)
    amonestaciones.sort(key=lambda a: a.get("fecha", "") or a.get("createdAt", ""), reverse=True)
    employees = {e["id"]: e for e in hr.get_employees(company_id, sandbox=sandbox)}

    return render_template("rrhh/amonestacion_list.html",
                           active_page="rrhh_employees",
                           amonestaciones=amonestaciones,
                           employees=employees)


# ── Detalle ─────────────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/amonestaciones/<amonestacion_id>")
def amonestacion_detail(amonestacion_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    amonestacion = hr.get_amonestacion(company_id, amonestacion_id, sandbox=sandbox)
    if not amonestacion:
        flash("Amonestación no encontrada.", "error")
        return redirect(url_for("web_rrhh.amonestacion_list"))

    employee = hr.get_employee(company_id, amonestacion.get("employeeId", ""), sandbox=sandbox)
    return render_template("rrhh/amonestacion_detail.html",
                           active_page="rrhh_employees",
                           amonestacion=amonestacion, employee=employee,
                           AMONESTACION_TIPOS=AMONESTACION_TIPOS)


# ── Edición ─────────────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/amonestaciones/<amonestacion_id>/edit", methods=["GET", "POST"])
def amonestacion_edit(amonestacion_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    amonestacion = hr.get_amonestacion(company_id, amonestacion_id, sandbox=sandbox)
    if not amonestacion:
        flash("Amonestación no encontrada.", "error")
        return redirect(url_for("web_rrhh.amonestacion_list"))

    employee = hr.get_employee(company_id, amonestacion.get("employeeId", ""), sandbox=sandbox)
    if not employee:
        flash("Empleado no encontrado.", "error")
        return redirect(url_for("web_rrhh.amonestacion_list"))

    if request.method == "GET":
        return render_template("rrhh/amonestacion_form.html",
                               active_page="rrhh_employees",
                               amonestacion=amonestacion, employee=employee,
                               AMONESTACION_TIPOS=AMONESTACION_TIPOS, is_new=False)

    parsed, error = _form_data(request.form, amonestacion=amonestacion)
    if error:
        flash(error, "error")
        return redirect(url_for("web_rrhh.amonestacion_edit", amonestacion_id=amonestacion_id))

    company = _company_data(owner_uid, sandbox, company_id=company_id)
    signer_name = parsed["signer_name"] or company.get("representativeName", "")
    signer_position = parsed["signer_position"] or company.get("representativePosition", "") or "Representante Legal"

    data = build_amonestacion_data(
        tipo=parsed["tipo"], hecho=parsed["hecho"], fecha=parsed["fecha"],
        signer_name=signer_name, signer_position=signer_position,
    )
    record = _record_payload(
        employee, parsed["tipo"], data["tipo_label"], parsed["hecho"],
        _fecha_iso(parsed["fecha"]), data["fecha"], signer_name, signer_position,
        existing=amonestacion,
    )
    hr.save_amonestacion(company_id, record["id"], record, sandbox=sandbox)

    try:
        from app.services.payroll_audit_service import log_employee_action
        log_employee_action(
            company_id, employee.get("id", ""), "amonestacion_updated",
            comment=f"Amonestación {data['tipo_label']} actualizada",
            changes={"tipo": parsed["tipo"], "amonestacionId": record["id"]},
            user_email=session.get("user", {}).get("email", ""),
            sandbox=sandbox,
        )
    except Exception as e:
        print(f"⚠️ amonestacion.log_employee_action (update): {e}")

    flash("Amonestación actualizada.", "success")
    return redirect(url_for("web_rrhh.amonestacion_detail", amonestacion_id=record["id"]))


# ── Eliminación ─────────────────────────────────────────────────────────────

@web_rrhh_bp.route("/rrhh/amonestaciones/<amonestacion_id>/delete", methods=["POST"])
def amonestacion_delete(amonestacion_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    amonestacion = hr.get_amonestacion(company_id, amonestacion_id, sandbox=sandbox)
    if not amonestacion:
        flash("Amonestación no encontrada.", "error")
        return redirect(url_for("web_rrhh.amonestacion_list"))

    employee_id = amonestacion.get("employeeId", "")
    doc = _existing_document(company_id, employee_id, amonestacion.get("documentoFirmadoId", ""), sandbox)
    if doc:
        _delete_storage_blob(doc.get("storagePath", ""), owner_uid)
        hr.delete_employee_document(company_id, doc.get("id", ""), sandbox=sandbox)

    hr.delete_amonestacion(company_id, amonestacion_id, sandbox=sandbox)

    try:
        from app.services.payroll_audit_service import log_employee_action
        log_employee_action(
            company_id, employee_id, "amonestacion_deleted",
            comment=f"Amonestación {amonestacion.get('tipoLabel', '')} eliminada",
            changes={"tipo": amonestacion.get("tipo", ""), "amonestacionId": amonestacion_id},
            user_email=session.get("user", {}).get("email", ""),
            sandbox=sandbox,
        )
    except Exception as e:
        print(f"⚠️ amonestacion.log_employee_action (delete): {e}")

    flash("Amonestación eliminada.", "success")
    return redirect(url_for("web_rrhh.amonestacion_list"))
