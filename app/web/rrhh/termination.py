"""RRHH module — auto-extracted."""

from flask import render_template, request, redirect, url_for, session, flash, jsonify, send_file
from app.web.rrhh import (
    web_rrhh_bp, _get_owner_uid_and_sandbox, _login_required,
    _is_hr_role, _sanitize_for_role, MONTHS_ES,
    _filter_employees_by_period, _generate_periods,
)
from app.services import hr_data_service as hr



@web_rrhh_bp.route("/rrhh/employees/<employee_id>/terminate", methods=["POST"])
def employee_terminate(employee_id):
    flash("Esta ruta directa ha sido descontinuada. Use el módulo Offboarding.", "warning")
    return redirect(url_for("web_rrhh.offboarding_new", employee_id=employee_id))

