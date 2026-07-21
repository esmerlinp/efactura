"""API REST para Cálculo de Liquidaciones Laborales (RD)."""

from flask import Blueprint, request, jsonify, session
from app.api.auth import require_api_key

api_liquidacion_bp = Blueprint("api_liquidacion", __name__)


def _get_owner(uid_override=None):
    uid = session.get("selected_owner_uid", "") or session.get("user", {}).get("ownerUID", "")
    sandbox = session.get("is_sandbox_mode", True)
    return uid, sandbox


@api_liquidacion_bp.route("/labor/settlement", methods=["POST"])
@require_api_key
def calculate_settlement():
    """
    Calcular liquidación laboral
    ---
    tags:
      - Labor
    summary: Calcular liquidación laboral (RD)
    description: |
      Calcula una liquidación laboral conforme a la legislación dominicana.
      Si se envía `save: true`, se persiste en Firestore.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - employeeId
            - employeeName
            - hireDate
            - terminationDate
            - lastBaseSalary
          properties:
            employeeId:
              type: string
              description: ID del empleado
            employeeName:
              type: string
              description: Nombre del empleado
            cedula:
              type: string
              description: Cédula del empleado
            hireDate:
              type: string
              description: Fecha de contratación
            terminationDate:
              type: string
              description: Fecha de terminación
            terminationType:
              type: string
              default: "renuncia"
              enum: ["renuncia", "desahucio", "despido"]
            lastBaseSalary:
              type: number
              description: Último salario base mensual
            salaryFrequency:
              type: string
              default: "mensual"
            monthlySalariesLast12:
              type: array
              items:
                type: number
              description: Salarios de los últimos 12 meses
            monthlySalariesYearToDate:
              type: array
              items:
                type: number
              description: Salarios del año en curso
            preavisoTrabajado:
              type: boolean
              default: false
            vacationPendingDays:
              type: integer
            vacationDaysTakenThisPeriod:
              type: integer
            notes:
              type: string
            createdBy:
              type: string
              default: "api"
            save:
              type: boolean
              default: false
              description: Si es true, persiste la liquidación en Firestore
    responses:
      200:
        description: Liquidación calculada exitosamente
      400:
        description: Datos inválidos o faltantes
      500:
        description: Error interno del servidor
    """
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
    """
    Obtener liquidación guardada
    ---
    tags:
      - Labor
    summary: Consultar liquidación por ID
    description: Retorna una liquidación laboral previamente guardada.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: settlement_id
        in: path
        required: true
        type: string
        description: ID de la liquidación
    responses:
      200:
        description: Liquidación encontrada
      404:
        description: Liquidación no encontrada
      500:
        description: Error interno del servidor
    """
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
    """
    Eliminar liquidación
    ---
    tags:
      - Labor
    summary: Eliminar liquidación por ID
    description: Elimina una liquidación laboral guardada.
    security:
      - ApiKeyHeader: []
    parameters:
      - name: settlement_id
        in: path
        required: true
        type: string
        description: ID de la liquidación
    responses:
      200:
        description: Liquidación eliminada exitosamente
      500:
        description: Error interno del servidor
    """
    owner_uid, sandbox = _get_owner()
    try:
        from app.services import hr_data_service as hr
        hr.delete_liquidacion(owner_uid, settlement_id, sandbox=sandbox)
        return jsonify({"success": True, "message": "Liquidación eliminada."}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
