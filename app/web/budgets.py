from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from app.services.budget_service import BudgetService
from app.utils.decorators import check_permission
from flask import g


web_budgets_bp = Blueprint("web_budgets", __name__)


@web_budgets_bp.route("/budgets")
def dashboard():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    if not (check_permission("canExpenses") or check_permission("canViewBI")):
        return render_template("auth/restricted.html", feature_name="Presupuestos")

    now = datetime.now(timezone.utc)
    try:
        year = int(request.args.get("year", now.year))
    except ValueError:
        year = now.year
    try:
        month = int(request.args.get("month", now.month))
    except ValueError:
        month = now.month
    month = min(12, max(1, month))

    owner_uid = session["user"]["ownerUID"]
    sandbox = session.get("is_sandbox_mode", True)
    budget = BudgetService.get_budget(owner_uid, year)
    year_variance = BudgetService.get_year_variance(owner_uid, year, sandbox=sandbox)
    month_variance = BudgetService.get_variance(owner_uid, year, month, sandbox=sandbox)
    years = list(range(now.year - 3, now.year + 2))

    return render_template(
        "budgets/dashboard.html",
        active_page="budgets",
        budget=budget,
        categories=BudgetService.get_categories(),
        year=year,
        month=month,
        years=years,
        year_variance=year_variance,
        month_variance=month_variance,
    )


@web_budgets_bp.route("/budgets/save", methods=["POST"])
def save_budget():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    if not check_permission("canExpenses"):
        return render_template("auth/restricted.html", feature_name="Presupuestos", required_permission="canExpenses")

    try:
        year = int(request.form.get("year", datetime.now(timezone.utc).year))
    except ValueError:
        year = datetime.now(timezone.utc).year

    months = {}
    for month in range(1, 13):
        key = str(month)
        months[key] = {}
        for cat in BudgetService.get_categories():
            code = cat["code"]
            months[key][code] = request.form.get(f"m_{month}_{code}", 0)

    BudgetService.save_budget(
        session["user"]["ownerUID"],
        year,
        {"months": months, "updatedBy": session["user"].get("email", ""), "branchId": g.get("branch_id", "default-sucursal-principal"), "projectId": g.get("project_id")},
    )
    flash("Presupuesto guardado correctamente.", "success")
    return redirect(url_for("web_budgets.dashboard", year=year, month=request.form.get("focus_month", 1)))

