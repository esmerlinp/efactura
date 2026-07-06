from flask import Blueprint, render_template, redirect, url_for, session, request

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
    runs = JobService.list_runs(limit=500 if not status else limit, status=status)  # get all for stats
    displayed_runs = runs[:limit] if not status else runs
    scheduled_jobs = JobService.scheduler_jobs()

    # stats
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

