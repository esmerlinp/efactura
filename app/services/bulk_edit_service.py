"""BulkEditService — Edición masiva de campos de empleados con progreso en tiempo real."""

import uuid
import threading
from datetime import datetime, timezone
from typing import Any

from app.services import hr_data_service as hr
from app.services.payroll_audit_service import log_action

AFP_PROVIDERS = [
    "AFP Siembra",
    "AFP Popular",
    "AFP Reservas",
    "AFP Romana",
    "AFP Crecer",
    "AFP JMMB BDI",
]

BANKS = [
    "Banco Popular Dominicano",
    "Banco de Reservas",
    "Banco BHD",
    "Banco Caribe",
    "Banco BDI",
    "Banco Scotiabank",
    "Banco General",
    "Banco Vimenca",
    "Banco López de Haro",
    "Banco Atlántico",
    "Banco de Ahorro y Crédito ADEMI",
    "Banco de Ahorro y Crédito La Nacional",
    "Banco de Ahorro y Crédito Union",
    "Banco de Ahorro y Crédito JMMB",
    "Banco de Ahorro y Crédito Fihogar",
    "Banco de Ahorro y Crédito Caribería",
    "Banco de Ahorro y Crédito Associados",
    "Banco Múltiple Santa Cruz",
    "Banco Múltiple Activo Dominicana",
    "Banco Múltiple Bell Bank",
]

NATIONALITIES = [
    {"value": 1, "label": "Dominicana"},
    {"value": 2, "label": "Haitiana"},
    {"value": 3, "label": "Estadounidense"},
    {"value": 4, "label": "Venezolana"},
    {"value": 5, "label": "Colombiana"},
    {"value": 6, "label": "Española"},
    {"value": 7, "label": "Cubana"},
    {"value": 8, "label": "Puertorriqueña"},
    {"value": 9, "label": "Italiana"},
    {"value": 10, "label": "Otra"},
]

BULK_EDITABLE_FIELDS = {
    "tss": {
        "label": "TSS / Seguridad Social",
        "icon": "fa-solid fa-shield-halved",
        "fields": [
            {"name": "afpProvider", "label": "AFP", "type": "select", "options": AFP_PROVIDERS},
            {"name": "afpSalaryCap", "label": "Tope Salarial AFP (RD$)", "type": "number", "step": "0.01", "min": "0", "placeholder": "Ej: 464460.00"},
            {"name": "sfsSalaryCap", "label": "Tope SFS (RD$)", "type": "number", "step": "0.01", "min": "0", "placeholder": "Ej: 232230.00"},
            {"name": "tssKey", "label": "Clave Nómina TSS", "type": "text", "placeholder": "3 dígitos"},
            {"name": "tssRegistrationNumber", "label": "Núm. Registro TSS", "type": "text", "placeholder": "Número de registro"},
        ],
    },
    "contract": {
        "label": "Datos Contractuales",
        "icon": "fa-solid fa-file-contract",
        "fields": [
            {"name": "contractType", "label": "Tipo de Contrato", "type": "select", "options": [
                "tiempo_indefinido", "tiempo_definido", "obra_o_servicio", "temporal", "practicante",
            ]},
            {"name": "workday", "label": "Jornada Laboral", "type": "select", "options": [
                "completa", "media_jornada", "reducida", "por_turnos",
            ]},
            {"name": "probationEndDate", "label": "Fin Período de Prueba", "type": "date"},
            {"name": "status", "label": "Estado", "type": "select", "options": [
                "activo", "inactivo", "suspendido",
            ]},
        ],
    },
    "payment": {
        "label": "Forma de Pago",
        "icon": "fa-solid fa-credit-card",
        "fields": [
            {"name": "paymentMethod", "label": "Método de Pago", "type": "select", "options": [
                "transferencia", "cheque", "efectivo", "deposito",
            ]},
            {"name": "bank", "label": "Banco", "type": "select_search", "options": BANKS},
            {"name": "accountType", "label": "Tipo de Cuenta", "type": "select", "options": ["ahorro", "corriente"]},
            {"name": "accountNumber", "label": "Número de Cuenta", "type": "text", "placeholder": "Número de cuenta bancaria"},
            {"name": "salaryType", "label": "Tipo de Salario", "type": "select", "options": ["fijo", "por_hora"]},
            {"name": "hourlyRate", "label": "Tarifa por Hora (RD$)", "type": "number", "step": "0.01", "min": "0", "placeholder": "Ej: 150.00"},
        ],
    },
    "dgt_sirla": {
        "label": "DGT / SIRLA",
        "icon": "fa-solid fa-building-columns",
        "fields": [
            {"name": "nationality", "label": "Nacionalidad", "type": "select_options", "options": NATIONALITIES},
            {"name": "occupationCode", "label": "Código Ocupación CNO-2019", "type": "text", "placeholder": "4 dígitos (ej: 2411)"},
            {"name": "weeklyHours", "label": "Horas Semanales", "type": "number", "min": "1", "max": "44", "placeholder": "44"},
            {"name": "workShift", "label": "Turno de Trabajo", "type": "select_options", "options": [
                {"value": 1, "label": "Diurno"},
                {"value": 2, "label": "Nocturno"},
                {"value": 3, "label": "Mixto"},
            ]},
            {"name": "vacationGranted", "label": "Concesión Vacaciones", "type": "select_options", "options": [
                {"value": 1, "label": "Tomará en el año"},
                {"value": 2, "label": "Ya las tomó"},
            ]},
        ],
    },
    "personal": {
        "label": "Datos Personales",
        "icon": "fa-solid fa-user",
        "fields": [
            {"name": "gender", "label": "Género", "type": "select", "options": ["masculino", "femenino"]},
            {"name": "maritalStatus", "label": "Estado Civil", "type": "select_options", "options": [
                {"value": "S", "label": "Soltero/a"},
                {"value": "C", "label": "Casado/a"},
                {"value": "U", "label": "Unión Libre"},
                {"value": "D", "label": "Divorciado/a"},
                {"value": "V", "label": "Viudo/a"},
            ]},
            {"name": "educationLevel", "label": "Nivel de Educación", "type": "select_options", "options": [
                {"value": 0, "label": "—"},
                {"value": 6, "label": "Ninguno"},
                {"value": 1, "label": "Primaria"},
                {"value": 2, "label": "Secundaria"},
                {"value": 3, "label": "Técnico"},
                {"value": 4, "label": "Grado Universitario"},
                {"value": 5, "label": "Postgrado/Maestría"},
            ]},
            {"name": "email", "label": "Correo Electrónico", "type": "text", "placeholder": "correo@ejemplo.com"},
            {"name": "phone", "label": "Teléfono", "type": "text", "placeholder": "8095551234"},
            {"name": "emergencyContact", "label": "Contacto de Emergencia", "type": "text", "placeholder": "Nombre del contacto"},
            {"name": "emergencyPhone", "label": "Teléfono de Emergencia", "type": "text", "placeholder": "8095555678"},
            {"name": "municipality", "label": "Municipio", "type": "text", "placeholder": "Nombre del municipio"},
            {"name": "address", "label": "Dirección", "type": "text", "placeholder": "Dirección completa"},
        ],
    },
    "other": {
        "label": "Otros",
        "icon": "fa-solid fa-note-sticky",
        "fields": [
            {"name": "notes", "label": "Notas", "type": "textarea", "placeholder": "Observaciones generales..."},
            {"name": "isVigilante", "label": "¿Trabaja como Vigilante?", "type": "checkbox"},
        ],
    },
}

BULK_EDIT_JOBS: dict[str, dict] = {}


def get_bulk_editable_fields() -> dict:
    return BULK_EDITABLE_FIELDS


def create_bulk_edit_job(company_id: str, employee_ids: list[str], changes: dict,
                          user_email: str, sandbox: bool = True) -> str:
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    job = {
        "id": job_id,
        "status": "pending",
        "total": len(employee_ids),
        "progress": 0,
        "success": 0,
        "errors": [],
        "currentEmployee": "",
        "employee_ids": list(employee_ids),
        "changes": dict(changes),
        "createdAt": now,
        "userEmail": user_email,
    }
    BULK_EDIT_JOBS[job_id] = job

    thread = threading.Thread(
        target=_execute_bulk_edit,
        args=(company_id, job_id, user_email, sandbox),
        daemon=True,
    )
    thread.start()
    return job_id


def get_job_progress(job_id: str) -> dict | None:
    job = BULK_EDIT_JOBS.get(job_id)
    if not job:
        return None
    return {
        "jobId": job["id"],
        "status": job["status"],
        "total": job["total"],
        "progress": job["progress"],
        "success": job["success"],
        "errors": len(job["errors"]),
        "currentEmployee": job.get("currentEmployee", ""),
    }


def get_job_result(job_id: str) -> dict | None:
    job = BULK_EDIT_JOBS.get(job_id)
    if not job:
        return None
    return {
        "jobId": job["id"],
        "status": job["status"],
        "total": job["total"],
        "progress": job["progress"],
        "success": job["success"],
        "errors": job["errors"],
        "changes": job.get("changes", {}),
    }


def _execute_bulk_edit(company_id: str, job_id: str, user_email: str, sandbox: bool):
    job = BULK_EDIT_JOBS.get(job_id)
    if not job:
        return

    job["status"] = "processing"
    employee_ids = job["employee_ids"]
    changes = job["changes"]

    for eid in employee_ids:
        try:
            emp = hr.get_employee(company_id, eid, sandbox=sandbox)
            if not emp:
                job["errors"].append({
                    "employeeId": eid,
                    "employeeName": eid,
                    "message": "Empleado no encontrado",
                })
                job["progress"] += 1
                continue

            job["currentEmployee"] = emp.get("fullName", eid)
            before = {field: emp.get(field) for field in changes}

            for field, value in changes.items():
                emp[field] = value

            hr.save_employee(company_id, eid, emp, sandbox=sandbox)

            log_action(
                company_id=company_id,
                action="bulk_edit",
                entity="employee",
                entity_id=eid,
                user_email=user_email,
                changes=changes,
                comment=f"Edición masiva: {len(changes)} campo(s) modificado(s)",
                sandbox=sandbox,
                before=before,
                after={field: emp.get(field) for field in changes},
            )

            job["success"] += 1

        except Exception as e:
            job["errors"].append({
                "employeeId": eid,
                "employeeName": job.get("currentEmployee", eid),
                "message": str(e),
            })

        job["progress"] += 1

    job["status"] = "completed" if not job["errors"] else "partial"
    job["currentEmployee"] = ""
