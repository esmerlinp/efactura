from flask import Blueprint, render_template, redirect, url_for, session, request, jsonify

from app.services.job_service import JobService
from app.utils.decorators import check_permission


web_system_jobs_bp = Blueprint("web_system_jobs", __name__)


@web_system_jobs_bp.route("/admin/jobs")
def dashboard():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    if not (check_permission("canModifySettings") or check_permission("canViewAuditLog")):
        return render_template("auth/restricted.html", feature_name="Jobs y procesos", required_permission="canModifySettings")

    status = request.args.get("status", "")
    try:
        limit = int(request.args.get("limit", 50))
    except ValueError:
        limit = 50
    runs = JobService.list_runs(limit=500 if not status else limit, status=status)
    displayed_runs = runs[:limit] if not status else runs
    scheduled_jobs = JobService.scheduler_jobs()

    total = len(runs)
    running = sum(1 for r in runs if r.get("status") == "running")
    success = sum(1 for r in runs if r.get("status") == "success")
    errors = sum(1 for r in runs if r.get("status") == "error")

    return render_template(
        "system/jobs.html",
        active_page="system_jobs",
        runs=displayed_runs,
        scheduled_jobs=scheduled_jobs,
        status=status,
        limit=limit,
        stats={"total": total, "running": running, "success": success, "errors": errors},
    )


@web_system_jobs_bp.route("/admin/jobs/trigger", methods=["POST"])
def trigger_job():
    if "user" not in session:
        return jsonify(success=False, error="No autorizado"), 401
    if not check_permission("canModifySettings"):
        return jsonify(success=False, error="Permiso insuficiente"), 403

    job_id = request.form.get("job_id") or request.json.get("job_id", "")
    if not job_id:
        return jsonify(success=False, error="job_id es requerido"), 400

    job_map = {
        "contingency_sync": ("contingency_sync", "Sincronización de Contingencia DGII (Manual)"),
        "daily_contract_billing": ("daily_contract_billing", "Facturación Diaria de Contratos (Manual)"),
        "daily_depreciation": ("daily_depreciation", "Depreciación de Activos Fijos (Manual)"),
        "cleanup_idempotency_keys": ("cleanup_idempotency_keys", "Limpieza de Idempotency Keys (Manual)"),
        "tax_obligation_reminders": ("tax_obligation_reminders", "Recordatorios de Obligaciones Tributarias DGII (Manual)"),
    }

    job_info = job_map.get(job_id)
    if not job_info:
        return jsonify(success=False, error=f"Job desconocido: {job_id}"), 400

    internal_id, display_name = job_info

    try:
        from app.services.scheduler import (
            run_contingency_sync,
            run_daily_contract_billing,
            run_daily_depreciation,
            cleanup_expired_idempotency_keys,
            run_tax_obligation_reminders,
        )
        func_map = {
            "contingency_sync": run_contingency_sync,
            "daily_contract_billing": run_daily_contract_billing,
            "daily_depreciation": run_daily_depreciation,
            "cleanup_idempotency_keys": cleanup_expired_idempotency_keys,
            "tax_obligation_reminders": run_tax_obligation_reminders,
        }
        func = func_map.get(job_id)
        if not func:
            return jsonify(success=False, error=f"Función no encontrada para: {job_id}"), 500

        result = JobService.run_monitored(internal_id, display_name, func)
        return jsonify(success=True, message=f"Job '{display_name}' ejecutado correctamente.", result=result if isinstance(result, dict) else {})
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error ejecutando job {job_id}: {e}")
        return jsonify(success=False, error=str(e)), 500

