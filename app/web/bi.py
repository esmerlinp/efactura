from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, session

from app.services.bi_drilldown_service import BIDrilldownService, DRILLDOWN_METRICS
from app.utils.decorators import check_permission


web_bi_bp = Blueprint("web_bi", __name__)


@web_bi_bp.route("/bi/drilldown/<metric>")
def drilldown(metric):
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    if not check_permission("canViewBI"):
        return render_template("auth/restricted.html", feature_name="BI Drill-down", required_permission="canViewBI")

    now = datetime.now(timezone.utc)
    try:
        year = int(request.args.get("year", now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get("month", 0))
    except ValueError:
        month = 0

    data = BIDrilldownService.get_drilldown(
        owner_uid=session["user"]["ownerUID"],
        metric=metric,
        year=year,
        month=month,
        sandbox=session.get("is_sandbox_mode", True),
    )
    for row in data["rows"]:
        link = row.get("link")
        if link:
            endpoint, params = link
            try:
                row["href"] = url_for(endpoint, **params)
            except Exception:
                row["href"] = ""
    return render_template(
        "bi/drilldown.html",
        active_page="bi_drilldown",
        data=data,
        metrics=DRILLDOWN_METRICS,
        year=year,
        month=month,
        years=list(range(now.year - 5, now.year + 1)),
    )
