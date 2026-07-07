"""API REST para Cálculo de Liquidaciones Laborales (RD)."""

from flask import Blueprint, request, jsonify, session
from app.api.auth import require_api_key

api_liquidacion_bp = Blueprint("api_liquidacion", __name__)


def _get_owner(uid_override=None):
    uid = session.get("user", {}).get("ownerUID", "")
    sandbox = session.get("is_sandbox_mode", True)
    return uid, sandbox


@api_liquidacion_bp.route("/labor/settlement", methods=["POST"])
@require_api_key
def calculate_settlement():
    data = request.json or {}
    if not data:
        return jsonify({"success": False, "error": "Se requiere un JSON con los datos de liquidación."}), 400

    try:
        from app.services.liquidacion_service import LiquidacionService

        employee_id = data.get("employeeId", "")
        employee_name = data.get("employeeName", "")
        cedula = data.get("cedula", "")
        hire_date = data.get("hireDate", "")
        termination_date = data.get("terminationDate", "")
        termination_type = data.get("terminationType", "renuncia")
        last_base_salary = float(data.get("lastBaseSalary", 0) or 0)
        salary_frequency = data.get("salaryFrequency", "mensual")
        monthly_salaries_last_12 = data.get("monthlySalariesLast12", [])
        monthly_salaries_ytd = data.get("monthlySalariesYearToDate", [])
        preaviso_trabajado = bool(data.get("preavisoTrabajado", False))
        vacation_pending_days = int(data.get("vacationPendingDays", 0) or 0)
        vacation_days_taken_this_period = int(data.get("vacationDaysTakenThisPeriod", 0) or 0)
        notes = data.get("notes", "")
        created_by = data.get("createdBy", "api")

        resultado = LiquidacionService.calcular_liquidacion(
            employee_id=employee_id,
            employee_name=employee_name,
            cedula=cedula,
            hire_date=hire_date,
            termination_date=termination_date,
            termination_type=termination_type,
            last_base_salary=last_base_salary,
            salary_frequency=salary_frequency,
            monthly_salaries_last_12=monthly_salaries_last_12,
            monthly_salaries_ytd=monthly_salaries_ytd,
            preaviso_trabajado=preaviso_trabajado,
            vacation_pending_days=vacation_pending_days,
            vacation_days_taken_this_period=vacation_days_taken_this_period,
            notes=notes,
            created_by=created_by,
        )

        # Persistir si se solicita
        if data.get("save", False):
            owner_uid, sandbox = _get_owner()
            from app.services import hr_data_service as hr
            hr.save_liquidacion(owner_uid, resultado["id"], resultado, sandbox=sandbox)

        return jsonify({"success": True, "data": resultado}), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_liquidacion_bp.route("/labor/settlement/<settlement_id>", methods=["GET"])
@require_api_key
def get_settlement(settlement_id):
    owner_uid, sandbox = _get_owner()
    try:
        from app.services import hr_data_service as hr
        liquidacion = hr.get_liquidacion(owner_uid, settlement_id, sandbox=sandbox)
        if not liquidacion:
            return jsonify({"success": False, "error": "Liquidación no encontrada."}), 404
        return jsonify({"success": True, "data": liquidacion}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@api_liquidacion_bp.route("/labor/settlement/<settlement_id>", methods=["DELETE"])
@require_api_key
def delete_settlement(settlement_id):
    owner_uid, sandbox = _get_owner()
    try:
        from app.services import hr_data_service as hr
        hr.delete_liquidacion(owner_uid, settlement_id, sandbox=sandbox)
        return jsonify({"success": True, "message": "Liquidación eliminada."}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
