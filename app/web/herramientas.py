"""Blueprint de Gestión de Activos/Herramientas."""
import uuid
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.services.herramientas_service import (
    get_herramientas, get_herramienta, save_herramienta, delete_herramienta,
    get_next_code, get_next_asset_tag,
    get_asignaciones, get_asignacion, save_asignacion,
    get_asignaciones_por_empleado, get_asignaciones_por_herramienta,
    get_mantenimientos, get_mantenimiento, save_mantenimiento, delete_mantenimiento,
    get_mantenimientos_por_herramienta,
    get_movimientos_por_herramienta, save_movimiento,
    get_categorias_herramienta, save_categoria_herramienta,
)
from app.services.db_service import DatabaseService
from app.utils.security import encrypt_field, decrypt_field

web_herramientas_bp = Blueprint("web_herramientas", __name__)


CATEGORIES = [
    {"value": "computadora", "label": "Computadora"},
    {"value": "telefono", "label": "Teléfono"},
    {"value": "software", "label": "Software / Licencia"},
    {"value": "vehiculo", "label": "Vehículo"},
    {"value": "herramienta", "label": "Herramienta / Equipo"},
    {"value": "mobiliario", "label": "Mobiliario"},
    {"value": "otro", "label": "Otro"},
]

TYPES = [
    {"value": "fisico", "label": "Físico"},
    {"value": "digital", "label": "Digital"},
]

OPERATIONAL_STATUSES = [
    {"value": "activo", "label": "Activo"},
    {"value": "mantenimiento", "label": "En Mantenimiento"},
    {"value": "baja", "label": "De Baja"},
]


def _login_required():
    return "user" not in session


def _get_owner_uid_and_sandbox():
    uid = session.get("selected_owner_uid", "") or session.get("user", {}).get("ownerUID", "")
    sandbox = session.get("is_sandbox_mode", True)
    company_id = session.get("selected_company_id")
    return uid, sandbox, company_id


def _check_tools_permission():
    user = session.get("user", {})
    role = user.get("role", "")
    perms = user.get("permissions", {})
    return role == "owner" or perms.get("canManageTools", True)


def _get_all_categories(owner_uid, sandbox=True, company_id=None):
    custom = get_categorias_herramienta(owner_uid, sandbox=sandbox, company_id=company_id)
    combined = list(CATEGORIES)
    seen = {c["value"] for c in combined}
    for c in custom:
        if c.get("value") not in seen:
            combined.append({"value": c["value"], "label": c["label"]})
            seen.add(c["value"])
    return combined


def _log_movimiento(owner_uid, herramienta_id, herramienta_code, event_type, previous="", new="", notes="", sandbox=True, company_id=None):
    user = session.get("user", {})
    save_movimiento(owner_uid, {
        "ownerUID": owner_uid,
        "herramientaId": herramienta_id,
        "herramientaCode": herramienta_code,
        "eventType": event_type,
        "previousValue": previous,
        "newValue": new,
        "performedBy": user.get("uid", ""),
        "notes": notes,
    }, sandbox=sandbox, company_id=company_id)


# ─── LISTADO ────────────────────────────────────────────────────────────────

@web_herramientas_bp.route("/herramientas")
def list_herramientas():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    if not _check_tools_permission():
        return render_template("auth/restricted.html", feature_name="Gestión de Activos", required_permission="canManageTools")
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    herramientas = get_herramientas(owner_uid, sandbox=sandbox, company_id=company_id)
    q = request.args.get("q", "").strip().lower()
    cat = request.args.get("category", "")
    op_status = request.args.get("operationalStatus", "")
    as_status = request.args.get("assignmentStatus", "")
    loc = request.args.get("location", "")

    if q:
        herramientas = [h for h in herramientas if q in h.get("name", "").lower() or q in h.get("code", "").lower() or q in h.get("serialNumber", "").lower() or q in h.get("assetTag", "").lower()]
    if cat:
        herramientas = [h for h in herramientas if h.get("category") == cat]
    if op_status:
        herramientas = [h for h in herramientas if h.get("operationalStatus") == op_status]
    if as_status:
        herramientas = [h for h in herramientas if h.get("assignmentStatus") == as_status]
    if loc:
        herramientas = [h for h in herramientas if h.get("location") == loc]

    locations = sorted(set(h.get("location", "") for h in get_herramientas(owner_uid, sandbox=sandbox, company_id=company_id) if h.get("location")))

    return render_template("herramientas/list.html", active_page="herramientas",
                           herramientas=herramientas, categories=CATEGORIES,
                           operational_statuses=OPERATIONAL_STATUSES,
                           locations=locations, request=request)


# ─── CREAR ──────────────────────────────────────────────────────────────────

@web_herramientas_bp.route("/herramientas/new", methods=["GET", "POST"])
def new_herramienta():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    if not _check_tools_permission():
        return render_template("auth/restricted.html", feature_name="Gestión de Activos", required_permission="canManageTools")
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    if request.method == "POST":
        herramienta_id = str(uuid.uuid4())
        category = request.form.get("category", "")
        code = request.form.get("code", "").strip()
        if not code:
            code = get_next_code(owner_uid, category, sandbox=sandbox, company_id=company_id)

        raw_license = request.form.get("licenseKey", "")
        encrypted = encrypt_field(raw_license) if raw_license else ""

        data = {
            "code": code,
            "assetTag": request.form.get("assetTag", "").strip() or get_next_asset_tag(owner_uid, sandbox=sandbox, company_id=company_id),
            "name": request.form.get("name", "").strip(),
            "description": request.form.get("description", "").strip(),
            "category": category,
            "type": request.form.get("type", "fisico"),
            "brand": request.form.get("brand", "").strip(),
            "model": request.form.get("model", "").strip(),
            "serialNumber": request.form.get("serialNumber", "").strip(),
            "purchasePrice": float(request.form.get("purchasePrice", 0) or 0),
            "purchasePriceCurrency": request.form.get("purchasePriceCurrency", "DOP"),
            "purchaseDate": request.form.get("purchaseDate", "").strip(),
            "supplier": request.form.get("supplier", "").strip(),
            "usefulLife": int(request.form.get("usefulLife", 0) or 0),
            "location": request.form.get("location", "").strip(),
            "costCenterId": request.form.get("costCenterId", "").strip(),
            "operationalStatus": "activo",
            "assignmentStatus": "disponible",
            "notes": request.form.get("notes", "").strip(),
            "encryptedLicenseKey": encrypted,
            "licenseCount": int(request.form.get("licenseCount", 1) or 1),
            "expirationDate": request.form.get("expirationDate", "").strip(),
            "nextMaintenanceDate": request.form.get("nextMaintenanceDate", "").strip(),
            "usageReading": float(request.form.get("usageReading", 0) or 0),
        }
        save_herramienta(owner_uid, herramienta_id, data, sandbox=sandbox, company_id=company_id)
        _log_movimiento(owner_uid, herramienta_id, code, "CREADA", notes=f"Herramienta creada: {data['name']}", sandbox=sandbox, company_id=company_id)
        flash(f"Herramienta {code} creada exitosamente.", "success")
        return redirect(url_for("web_herramientas.list_herramientas"))

    next_code = get_next_code(owner_uid, "", sandbox=sandbox, company_id=company_id)
    cost_centers = DatabaseService.get_cost_centers(owner_uid, sandbox=sandbox, company_id=company_id)
    all_categories = _get_all_categories(owner_uid, sandbox=sandbox, company_id=company_id)
    return render_template("herramientas/form.html", active_page="herramientas",
                           herramienta=None, categories=all_categories, types=TYPES,
                           operational_statuses=OPERATIONAL_STATUSES,
                           next_code=next_code, cost_centers=cost_centers,
                           employees=[], is_new=True)


# ─── EDITAR ─────────────────────────────────────────────────────────────────

@web_herramientas_bp.route("/herramientas/<herramienta_id>/edit", methods=["GET", "POST"])
def edit_herramienta(herramienta_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    if not _check_tools_permission():
        return render_template("auth/restricted.html", feature_name="Gestión de Activos", required_permission="canManageTools")
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    herramienta = get_herramienta(owner_uid, herramienta_id, sandbox=sandbox, company_id=company_id)
    if not herramienta:
        flash("Herramienta no encontrada.", "error")
        return redirect(url_for("web_herramientas.list_herramientas"))

    if request.method == "POST":
        old_status = herramienta.get("operationalStatus", "")
        raw_license = request.form.get("licenseKey", "")
        encrypted = encrypt_field(raw_license) if raw_license else herramienta.get("encryptedLicenseKey", "")

        data = dict(herramienta)
        data.update({
            "code": request.form.get("code", data.get("code", "")).strip(),
            "assetTag": request.form.get("assetTag", "").strip() or data.get("assetTag", ""),
            "name": request.form.get("name", "").strip(),
            "description": request.form.get("description", "").strip(),
            "category": request.form.get("category", data.get("category", "")),
            "type": request.form.get("type", data.get("type", "fisico")),
            "brand": request.form.get("brand", "").strip(),
            "model": request.form.get("model", "").strip(),
            "serialNumber": request.form.get("serialNumber", "").strip(),
            "purchasePrice": float(request.form.get("purchasePrice", 0) or 0),
            "purchasePriceCurrency": request.form.get("purchasePriceCurrency", "DOP"),
            "purchaseDate": request.form.get("purchaseDate", "").strip(),
            "supplier": request.form.get("supplier", "").strip(),
            "usefulLife": int(request.form.get("usefulLife", 0) or 0),
            "location": request.form.get("location", "").strip(),
            "costCenterId": request.form.get("costCenterId", "").strip(),
            "operationalStatus": request.form.get("operationalStatus", data.get("operationalStatus", "activo")),
            "notes": request.form.get("notes", "").strip(),
            "encryptedLicenseKey": encrypted,
            "licenseCount": int(request.form.get("licenseCount", 1) or 1),
            "expirationDate": request.form.get("expirationDate", "").strip(),
            "nextMaintenanceDate": request.form.get("nextMaintenanceDate", "").strip(),
            "usageReading": float(request.form.get("usageReading", 0) or 0),
        })
        save_herramienta(owner_uid, herramienta_id, data, sandbox=sandbox, company_id=company_id)
        new_status = data.get("operationalStatus", "")
        if old_status != new_status:
            _log_movimiento(owner_uid, herramienta_id, data.get("code", ""), f"STATUS_{new_status.upper()}",
                            previous=old_status, new=new_status, sandbox=sandbox, company_id=company_id)
        _log_movimiento(owner_uid, herramienta_id, data.get("code", ""), "EDITADA", sandbox=sandbox, company_id=company_id)
        flash("Herramienta actualizada exitosamente.", "success")
        return redirect(url_for("web_herramientas.detail_herramienta", herramienta_id=herramienta_id))

    herramienta["licenseKey"] = decrypt_field(herramienta.get("encryptedLicenseKey", ""))
    cost_centers = DatabaseService.get_cost_centers(owner_uid, sandbox=sandbox, company_id=company_id)
    all_categories = _get_all_categories(owner_uid, sandbox=sandbox, company_id=company_id)
    return render_template("herramientas/form.html", active_page="herramientas",
                           herramienta=herramienta, categories=all_categories, types=TYPES,
                           operational_statuses=OPERATIONAL_STATUSES,
                           next_code=herramienta.get("code", ""), cost_centers=cost_centers,
                           employees=[], is_new=False)


# ─── DETALLE ────────────────────────────────────────────────────────────────

@web_herramientas_bp.route("/herramientas/<herramienta_id>")
def detail_herramienta(herramienta_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    if not _check_tools_permission():
        return render_template("auth/restricted.html", feature_name="Gestión de Activos", required_permission="canManageTools")
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    herramienta = get_herramienta(owner_uid, herramienta_id, sandbox=sandbox, company_id=company_id)
    if not herramienta:
        flash("Herramienta no encontrada.", "error")
        return redirect(url_for("web_herramientas.list_herramientas"))

    herramienta["licenseKey"] = decrypt_field(herramienta.get("encryptedLicenseKey", ""))

    asignaciones = get_asignaciones_por_herramienta(owner_uid, herramienta_id, sandbox=sandbox, company_id=company_id)
    mantenimientos = get_mantenimientos_por_herramienta(owner_uid, herramienta_id, sandbox=sandbox, company_id=company_id)
    movimientos = get_movimientos_por_herramienta(owner_uid, herramienta_id, sandbox=sandbox, company_id=company_id)

    return render_template("herramientas/detail.html", active_page="herramientas",
                           herramienta=herramienta, asignaciones=asignaciones,
                           mantenimientos=mantenimientos, movimientos=movimientos,
                           categories=CATEGORIES, operational_statuses=OPERATIONAL_STATUSES)


# ─── ELIMINAR ───────────────────────────────────────────────────────────────

@web_herramientas_bp.route("/herramientas/<herramienta_id>/delete", methods=["POST"])
def delete_herramienta_route(herramienta_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    if not _check_tools_permission():
        flash("No tienes permiso para eliminar herramientas.", "error")
        return redirect(url_for("web_herramientas.list_herramientas"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    herramienta = get_herramienta(owner_uid, herramienta_id, sandbox=sandbox, company_id=company_id)
    if not herramienta:
        flash("Herramienta no encontrada.", "error")
        return redirect(url_for("web_herramientas.list_herramientas"))
    if herramienta.get("assignmentStatus") == "asignado":
        flash("No se puede eliminar una herramienta asignada. Debe devolverse primero.", "error")
        return redirect(url_for("web_herramientas.detail_herramienta", herramienta_id=herramienta_id))

    delete_herramienta(owner_uid, herramienta_id, sandbox=sandbox, company_id=company_id)
    flash(f"Herramienta {herramienta.get('code', '')} eliminada.", "success")
    return redirect(url_for("web_herramientas.list_herramientas"))


# ─── CAMBIAR ESTADO OPERATIVO ───────────────────────────────────────────────

@web_herramientas_bp.route("/herramientas/<herramienta_id>/status", methods=["POST"])
def change_status(herramienta_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    herramienta = get_herramienta(owner_uid, herramienta_id, sandbox=sandbox, company_id=company_id)
    if not herramienta:
        flash("Herramienta no encontrada.", "error")
        return redirect(url_for("web_herramientas.list_herramientas"))

    new_status = request.form.get("operationalStatus", "")
    if new_status not in ("activo", "mantenimiento", "baja"):
        flash("Estado operativo inválido.", "error")
        return redirect(url_for("web_herramientas.detail_herramienta", herramienta_id=herramienta_id))

    old_status = herramienta.get("operationalStatus", "")
    herramienta["operationalStatus"] = new_status
    save_herramienta(owner_uid, herramienta_id, herramienta, sandbox=sandbox, company_id=company_id)
    _log_movimiento(owner_uid, herramienta_id, herramienta.get("code", ""), f"STATUS_{new_status.upper()}",
                    previous=old_status, new=new_status, sandbox=sandbox, company_id=company_id)
    flash(f"Estado operativo cambiado a '{new_status}'.", "success")
    return redirect(url_for("web_herramientas.detail_herramienta", herramienta_id=herramienta_id))


# ─── ASIGNAR ────────────────────────────────────────────────────────────────

@web_herramientas_bp.route("/herramientas/<herramienta_id>/asignar", methods=["GET", "POST"])
def asignar_herramienta(herramienta_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    if not _check_tools_permission():
        return render_template("auth/restricted.html", feature_name="Gestión de Activos", required_permission="canManageTools")
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    herramienta = get_herramienta(owner_uid, herramienta_id, sandbox=sandbox, company_id=company_id)
    if not herramienta:
        flash("Herramienta no encontrada.", "error")
        return redirect(url_for("web_herramientas.list_herramientas"))
    if herramienta.get("assignmentStatus") == "asignado":
        flash("Esta herramienta ya está asignada.", "error")
        return redirect(url_for("web_herramientas.detail_herramienta", herramienta_id=herramienta_id))
    if herramienta.get("operationalStatus") in ("mantenimiento", "baja"):
        flash(f"No se puede asignar una herramienta en estado '{herramienta.get('operationalStatus')}'.", "error")
        return redirect(url_for("web_herramientas.detail_herramienta", herramienta_id=herramienta_id))

    from app.services.herramientas_service import get_herramientas
    from app.services.hr_data_service import get_employees

    employees = get_employees(owner_uid, sandbox=sandbox)
    active_employees = [e for e in employees if e.get("status") == "activo"]

    if request.method == "POST":
        empleado_id = request.form.get("empleadoId", "").strip()
        if not empleado_id:
            flash("Debes seleccionar un empleado.", "error")
            return render_template("herramientas/asignar_form.html", active_page="herramientas",
                                   herramienta=herramienta, employees=active_employees)

        empleado = next((e for e in employees if e["id"] == empleado_id), None)
        empleado_name = (empleado.get("fullName") or f"{empleado.get('firstName', '')} {empleado.get('firstLastName', '')}".strip() or "") if empleado else ""

        asignacion_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        user = session.get("user", {})

        data = {
            "herramientaId": herramienta_id,
            "herramientaCode": herramienta.get("code", ""),
            "herramientaName": herramienta.get("name", ""),
            "empleadoId": empleado_id,
            "empleadoName": empleado_name,
            "assignedDate": now,
            "returnedDate": "",
            "status": "activa",
            "conditionOnAssignment": request.form.get("conditionOnAssignment", "").strip(),
            "conditionOnReturn": "",
            "deliveryNotes": request.form.get("deliveryNotes", "").strip(),
            "signedDocumentId": "",
            "requiresApproval": bool(request.form.get("requiresApproval")),
            "approvedBy": request.form.get("approvedBy", "").strip(),
            "approvedAt": now if request.form.get("approvedBy") else "",
            "assignedBy": user.get("uid", ""),
        }
        save_asignacion(owner_uid, asignacion_id, data, sandbox=sandbox, company_id=company_id)

        herramienta["assignmentStatus"] = "asignado"
        save_herramienta(owner_uid, herramienta_id, herramienta, sandbox=sandbox, company_id=company_id)

        _log_movimiento(owner_uid, herramienta_id, herramienta.get("code", ""), "ASIGNADA",
                        new=f"Empleado: {empleado_name}", sandbox=sandbox, company_id=company_id)
        flash(f"Herramienta asignada a {empleado_name}.", "success")
        return redirect(url_for("web_herramientas.detail_herramienta", herramienta_id=herramienta_id))

    return render_template("herramientas/asignar_form.html", active_page="herramientas",
                           herramienta=herramienta, employees=active_employees)


# ─── DEVOLVER ───────────────────────────────────────────────────────────────

@web_herramientas_bp.route("/herramientas/asignaciones/<asignacion_id>/devolver", methods=["POST"])
def devolver_asignacion(asignacion_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    if not _check_tools_permission():
        flash("No tienes permiso para gestionar asignaciones.", "error")
        return redirect(url_for("web_herramientas.list_herramientas"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    asignacion = get_asignacion(owner_uid, asignacion_id, sandbox=sandbox, company_id=company_id)
    if not asignacion:
        flash("Asignación no encontrada.", "error")
        return redirect(url_for("web_herramientas.list_herramientas"))
    if asignacion.get("status") != "activa":
        flash("Esta asignación ya fue devuelta.", "error")
        return redirect(url_for("web_herramientas.list_herramientas"))

    ahora = datetime.now(timezone.utc).isoformat()
    asignacion["returnedDate"] = ahora
    asignacion["status"] = "devuelta"
    asignacion["conditionOnReturn"] = request.form.get("conditionOnReturn", "").strip()
    save_asignacion(owner_uid, asignacion_id, asignacion, sandbox=sandbox, company_id=company_id)

    herramienta_id = asignacion.get("herramientaId", "")
    herramienta = get_herramienta(owner_uid, herramienta_id, sandbox=sandbox, company_id=company_id)
    if herramienta:
        herramienta["assignmentStatus"] = "disponible"
        save_herramienta(owner_uid, herramienta_id, herramienta, sandbox=sandbox, company_id=company_id)
        _log_movimiento(owner_uid, herramienta_id, herramienta.get("code", ""), "DEVUELTA",
                        previous=f"Asignada a: {asignacion.get('empleadoName', '')}",
                        new="Disponible", sandbox=sandbox, company_id=company_id)

    flash("Herramienta devuelta exitosamente.", "success")
    return redirect(url_for("web_herramientas.list_herramientas"))


# ─── LISTA DE ASIGNACIONES ──────────────────────────────────────────────────

@web_herramientas_bp.route("/herramientas/asignaciones")
def list_asignaciones():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    if not _check_tools_permission():
        return render_template("auth/restricted.html", feature_name="Gestión de Activos", required_permission="canManageTools")
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    asignaciones = get_asignaciones(owner_uid, sandbox=sandbox, company_id=company_id)
    status_filter = request.args.get("status", "")
    if status_filter:
        asignaciones = [a for a in asignaciones if a.get("status") == status_filter]

    asignaciones.sort(key=lambda a: a.get("assignedDate", ""), reverse=True)
    return render_template("herramientas/asignaciones_list.html", active_page="herramientas",
                           asignaciones=asignaciones)


# ─── NUEVO MANTENIMIENTO ────────────────────────────────────────────────────

@web_herramientas_bp.route("/herramientas/<herramienta_id>/mantenimiento/nuevo", methods=["GET", "POST"])
def nuevo_mantenimiento(herramienta_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    if not _check_tools_permission():
        return render_template("auth/restricted.html", feature_name="Gestión de Activos", required_permission="canManageTools")
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    herramienta = get_herramienta(owner_uid, herramienta_id, sandbox=sandbox, company_id=company_id)
    if not herramienta:
        flash("Herramienta no encontrada.", "error")
        return redirect(url_for("web_herramientas.list_herramientas"))

    if request.method == "POST":
        mantenimiento_id = str(uuid.uuid4())
        data = {
            "herramientaId": herramienta_id,
            "type": request.form.get("type", "preventivo"),
            "date": request.form.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            "cost": float(request.form.get("cost", 0) or 0),
            "description": request.form.get("description", "").strip(),
            "provider": request.form.get("provider", "").strip(),
            "usageReading": float(request.form.get("usageReading", 0) or 0),
            "nextMaintenanceDate": request.form.get("nextMaintenanceDate", "").strip(),
            "notes": request.form.get("notes", "").strip(),
        }
        save_mantenimiento(owner_uid, mantenimiento_id, data, sandbox=sandbox, company_id=company_id)

        if request.form.get("nextMaintenanceDate", "").strip():
            herramienta["nextMaintenanceDate"] = request.form.get("nextMaintenanceDate", "").strip()
        if request.form.get("usageReading", 0):
            herramienta["usageReading"] = float(request.form.get("usageReading", 0))
        save_herramienta(owner_uid, herramienta_id, herramienta, sandbox=sandbox, company_id=company_id)

        _log_movimiento(owner_uid, herramienta_id, herramienta.get("code", ""), "MANTENIMIENTO",
                        new=f"{data['type']}: {data['description'][:100]}", sandbox=sandbox, company_id=company_id)
        flash("Mantenimiento registrado exitosamente.", "success")
        return redirect(url_for("web_herramientas.detail_herramienta", herramienta_id=herramienta_id))

    return render_template("herramientas/mantenimiento_form.html", active_page="herramientas",
                           herramienta=herramienta)


# ─── LISTA DE MANTENIMIENTOS ────────────────────────────────────────────────

@web_herramientas_bp.route("/herramientas/mantenimientos")
def list_mantenimientos():
    if _login_required():
        return redirect(url_for("web_auth.login"))
    if not _check_tools_permission():
        return render_template("auth/restricted.html", feature_name="Gestión de Activos", required_permission="canManageTools")
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    mantenimientos = get_mantenimientos(owner_uid, sandbox=sandbox, company_id=company_id)
    herramientas_list = get_herramientas(owner_uid, sandbox=sandbox, company_id=company_id)
    h_map = {h["id"]: h for h in herramientas_list}
    for m in mantenimientos:
        h = h_map.get(m.get("herramientaId", ""))
        if h:
            m["_herramientaName"] = h.get("name", "")
            m["_herramientaCode"] = h.get("code", "")
        else:
            m["_herramientaName"] = ""
            m["_herramientaCode"] = ""
    mantenimientos.sort(key=lambda m: m.get("date", ""), reverse=True)
    return render_template("herramientas/mantenimientos_list.html", active_page="herramientas",
                           mantenimientos=mantenimientos)


# ─── ELIMINAR MANTENIMIENTO ─────────────────────────────────────────────────

@web_herramientas_bp.route("/herramientas/mantenimientos/<mantenimiento_id>/delete", methods=["POST"])
def delete_mantenimiento_route(mantenimiento_id):
    if _login_required():
        return redirect(url_for("web_auth.login"))
    if not _check_tools_permission():
        flash("No tienes permiso para eliminar mantenimientos.", "error")
        return redirect(url_for("web_herramientas.list_herramientas"))
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()

    mantenimiento = get_mantenimiento(owner_uid, mantenimiento_id, sandbox=sandbox, company_id=company_id)
    if not mantenimiento:
        flash("Mantenimiento no encontrado.", "error")
        return redirect(url_for("web_herramientas.list_herramientas"))

    delete_mantenimiento(owner_uid, mantenimiento_id, sandbox=sandbox, company_id=company_id)
    flash("Mantenimiento eliminado.", "success")
    return redirect(url_for("web_herramientas.detail_herramienta", herramienta_id=mantenimiento.get("herramientaId", "")))


# ─── AJAX: Generar código ───────────────────────────────────────────────────

@web_herramientas_bp.route("/herramientas/ajax/generate-code", methods=["POST"])
def ajax_generate_code():
    if _login_required():
        return jsonify({"success": False, "error": "No autorizado"}), 401
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    try:
        data = request.json or {}
        category = data.get("category", "")
        code = get_next_code(owner_uid, category, sandbox=sandbox, company_id=company_id)
        return jsonify({"success": True, "code": code})
    except Exception as e:
        print(f"⚠️ ajax_generate_code error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ─── AJAX: Empleados activos ────────────────────────────────────────────────

@web_herramientas_bp.route("/herramientas/ajax/empleados", methods=["GET"])
def ajax_empleados():
    if _login_required():
        return jsonify({"success": False, "error": "No autorizado"}), 401
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    from app.services.hr_data_service import get_employees
    employees = get_employees(owner_uid, sandbox=sandbox)
    active = [{"id": e["id"], "name": e.get("display_name") or e.get("fullName", ""),
               "cedula": e.get("cedula", ""), "position": e.get("position", "")}
              for e in employees if e.get("status") == "activo"]
    return jsonify({"success": True, "employees": active})


# ─── AJAX: Crear categoría ──────────────────────────────────────────────────

@web_herramientas_bp.route("/herramientas/ajax/categoria/nueva", methods=["POST"])
def ajax_nueva_categoria():
    if _login_required():
        return jsonify({"success": False, "error": "No autorizado"}), 401
    owner_uid, sandbox, company_id = _get_owner_uid_and_sandbox()
    try:
        data = request.json or {}
        value = data.get("value", "").strip().lower().replace(" ", "_").replace("-", "_")
        label = data.get("label", "").strip()
        if not value or not label:
            return jsonify({"success": False, "error": "Valor y etiqueta son requeridos"}), 400
        cat_id = f"cat_{value}"
        save_categoria_herramienta(owner_uid, cat_id, {"value": value, "label": label}, sandbox=sandbox, company_id=company_id)
        return jsonify({"success": True, "category": {"value": value, "label": label}})
    except Exception as e:
        print(f"⚠️ ajax_nueva_categoria error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
