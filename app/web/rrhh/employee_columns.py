"""Columnas configurables del grid de empleados + persistencia por usuario.

Define el registro de columnas disponibles (derivado del catálogo de export),
los valores visibles por defecto, las columnas fijas y las helpers de resolución
y formateo. Además, la persistencia por usuario (users/{uid}/config/ui_preferences).
"""

from app.data.nationality_catalog import get_nationality_name
from app.data.disability_catalog import get_disability_name, normalize_disability


# ── Registro de columnas ────────────────────────────────────────────────────
# (key, label, kind). kind controla el formateo en el grid.
EMPLOYEE_GRID_COLUMNS = [
    {"key": "code", "label": "Código", "kind": "text"},
    {"key": "fullName", "label": "Empleado", "kind": "text"},
    {"key": "firstName", "label": "Primer Nombre", "kind": "text"},
    {"key": "middleName", "label": "Segundo Nombre", "kind": "text"},
    {"key": "firstLastName", "label": "Primer Apellido", "kind": "text"},
    {"key": "secondLastName", "label": "Segundo Apellido", "kind": "text"},
    {"key": "idType", "label": "Tipo Documento", "kind": "idType"},
    {"key": "cedula", "label": "Cédula", "kind": "text"},
    {"key": "idNumber", "label": "ID Número", "kind": "text"},
    {"key": "position", "label": "Cargo", "kind": "text"},
    {"key": "department", "label": "Departamento", "kind": "text"},
    {"key": "area", "label": "Área", "kind": "text"},
    {"key": "costCenter", "label": "Centro de Costo", "kind": "text"},
    {"key": "branchName", "label": "Sucursal", "kind": "text"},
    {"key": "hireDate", "label": "Fecha Ingreso", "kind": "date"},
    {"key": "baseSalary", "label": "Salario Base", "kind": "money"},
    {"key": "salaryType", "label": "Tipo Salario", "kind": "text"},
    {"key": "hourlyRate", "label": "Tarifa por Hora", "kind": "money"},
    {"key": "status", "label": "Estado", "kind": "status"},
    {"key": "employeeType", "label": "Tipo Empleado", "kind": "text"},
    {"key": "contractType", "label": "Tipo Contrato", "kind": "contractType"},
    {"key": "workday", "label": "Jornada", "kind": "workday"},
    {"key": "isVigilante", "label": "Vigilante", "kind": "bool"},
    {"key": "tssKey", "label": "Clave TSS", "kind": "text"},
    {"key": "email", "label": "Email", "kind": "text"},
    {"key": "phone", "label": "Teléfono", "kind": "text"},
    {"key": "address", "label": "Dirección", "kind": "text"},
    {"key": "municipality", "label": "Municipio", "kind": "text"},
    {"key": "emergencyContact", "label": "Contacto Emergencia", "kind": "text"},
    {"key": "emergencyPhone", "label": "Teléfono Emergencia", "kind": "text"},
    {"key": "gender", "label": "Género", "kind": "gender"},
    {"key": "birthDate", "label": "Fecha Nacimiento", "kind": "date"},
    {"key": "probationEndDate", "label": "Fin Período de Prueba", "kind": "date"},
    {"key": "paymentMethod", "label": "Método de Pago", "kind": "text"},
    {"key": "accountNumber", "label": "Número de Cuenta", "kind": "text"},
    {"key": "bank", "label": "Banco", "kind": "text"},
    {"key": "accountType", "label": "Tipo de Cuenta", "kind": "text"},
    {"key": "afpProvider", "label": "AFP", "kind": "text"},
    {"key": "afpSalaryCap", "label": "Tope AFP", "kind": "money"},
    {"key": "sfsSalaryCap", "label": "Tope SFS", "kind": "money"},
    {"key": "tssRegistrationNumber", "label": "No. Registro TSS", "kind": "text"},
    {"key": "supervisorName", "label": "Supervisor", "kind": "text"},
    {"key": "nationalityName", "label": "Nacionalidad", "kind": "text"},
    {"key": "nationality", "label": "ID Nacionalidad SIRLA", "kind": "text"},
    {"key": "maritalStatus", "label": "Estado Civil", "kind": "maritalStatus"},
    {"key": "numberOfChildren", "label": "No. Hijos", "kind": "text"},
    {"key": "occupationCode", "label": "Código Ocupación", "kind": "text"},
    {"key": "weeklyHours", "label": "Horas Semanales", "kind": "text"},
    {"key": "workShift", "label": "Turno", "kind": "workShift"},
    {"key": "educationLevel", "label": "Nivel Educación", "kind": "educationLevel"},
    {"key": "sirlaEducationCode", "label": "Código Educación SIRLA", "kind": "text"},
    {"key": "vacationGranted", "label": "Concesión Vacaciones", "kind": "vacationGranted"},
    {"key": "sdssNumber", "label": "No. SDSS", "kind": "text"},
    {"key": "vacationStartDate", "label": "Inicio Vacaciones (DGT)", "kind": "date"},
    {"key": "vacationEndDate", "label": "Fin Vacaciones (DGT)", "kind": "date"},
    {"key": "disabilityName", "label": "Discapacidad", "kind": "text"},
    {"key": "daysWorked", "label": "Días Trabajados", "kind": "text"},
    {"key": "dailySalary", "label": "Sueldo Diario", "kind": "money"},
    {"key": "terminationDate", "label": "Fecha Salida", "kind": "date"},
    {"key": "terminationReason", "label": "Motivo Salida", "kind": "text"},
    {"key": "terminationType", "label": "Tipo Salida", "kind": "terminationType"},
    {"key": "payrollGroupIds", "label": "Grupos de Nómina", "kind": "list"},
    {"key": "vacationDays", "label": "Vacaciones Disponibles", "kind": "vacation"},
    {"key": "notes", "label": "Notas", "kind": "text"},
]

COLUMNS_BY_KEY = {c["key"]: c for c in EMPLOYEE_GRID_COLUMNS}

DEFAULT_VISIBLE_COLUMNS = [
    "code", "fullName", "position", "department", "vacationDays", "status",
]

FIXED_COLUMNS = {"code", "fullName", "status"}


# ── Resolución y formateo ───────────────────────────────────────────────────

def enrich_employees(employees: list, branches: list) -> list:
    """Añade campos computados (sucursal, supervisor, nacionalidad, discapacidad)."""
    branch_names = {b.get("id"): b.get("name", "") for b in branches}
    emp_by_id = {e.get("id"): e for e in employees}
    for emp in employees:
        emp["branchName"] = branch_names.get(emp.get("branchId", ""), emp.get("branchId", "") or "")
        sup = emp_by_id.get(emp.get("reportsTo", ""))
        emp["supervisorName"] = sup.get("fullName", "") if sup else ""
        emp["nationalityName"] = get_nationality_name(emp.get("nationality", 1))
        emp["disabilityName"] = ", ".join(
            get_disability_name(c)
            for c in normalize_disability(emp.get("disability")).split(",")
            if get_disability_name(c)
        )
    return employees


def format_cell(value, kind: str) -> str:
    """Formatea el valor de una celda según su kind."""
    if value is None or value == "":
        return "—"
    if kind == "money":
        try:
            return f"{float(value):,.2f}"
        except (ValueError, TypeError):
            return str(value)
    if kind == "vacation":
        return f"{value} d"
    if kind == "bool":
        return "Sí" if value else "No"
    if kind == "list":
        return "; ".join(str(v) for v in value) if isinstance(value, list) else str(value)
    if kind == "date":
        s = str(value)
        parts = s.split("-")
        if len(parts) == 3:
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
        return s
    _maps = {
        "idType": {"cedula": "Cédula", "pasaporte": "Pasaporte", "rnc": "RNC"},
        "status": {
            "activo": "Activo", "vacaciones": "Vacaciones", "licencia": "Licencia",
            "suspendido": "Suspendido", "inactivo": "Inactivo",
        },
        "contractType": {
            "tiempo_indefinido": "Indefinido", "tiempo_definido": "Definido",
            "temporal": "Temporal", "obra_servicio": "Obra/Servicio",
        },
        "workday": {"completa": "Completa", "media_jornada": "Media jornada"},
        "gender": {"masculino": "Masculino", "femenino": "Femenino", "otro": "Otro"},
        "maritalStatus": {
            "S": "Soltero/a", "C": "Casado/a", "U": "Unión Libre",
            "D": "Divorciado/a", "V": "Viudo/a",
        },
        "workShift": {1: "Diurno", 2: "Nocturno", 3: "Mixto"},
        "educationLevel": {1: "Primaria", 2: "Secundaria", 3: "Técnico", 4: "Grado", 5: "Postgrado", 6: "Ninguno"},
        "vacationGranted": {1: "Tomará en el año", 2: "Ya las tomó"},
        "terminationType": {
            "renuncia": "Renuncia", "despido": "Despido", "mutuo_acuerdo": "Mutuo acuerdo",
            "fin_contrato": "Fin contrato",
        },
    }
    if kind in _maps:
        return _maps[kind].get(value, str(value))
    return str(value)


def status_class(status: str) -> str:
    return {
        "activo": "status-activo",
        "vacaciones": "status-vacaciones",
        "licencia": "status-licencia",
        "suspendido": "status-suspendido",
        "inactivo": "status-inactivo",
    }.get(status, "status-inactivo")


# ── Persistencia por usuario ────────────────────────────────────────────────

_PREFS_COLLECTION = "config"  # subcolección de users/{uid}
_PREFS_DOC_ID = "ui_preferences"
_PREFS_FIELD = "employeeListColumns"


def _config_path(uid: str) -> str:
    return f"users/{uid}/config"


def get_employee_list_columns(uid: str) -> dict:
    """Retorna el dict {key: bool} visible para el usuario, o defaults."""
    if not uid:
        return {k: (k in DEFAULT_VISIBLE_COLUMNS) for k in COLUMNS_BY_KEY}
    try:
        from app.services.db_service import db_firestore, firebase_initialized
        if firebase_initialized and db_firestore is not None:
            doc = db_firestore.collection(_config_path(uid)).document(_PREFS_DOC_ID).get()
            if doc.exists:
                stored = doc.to_dict().get(_PREFS_FIELD)
                if isinstance(stored, dict):
                    # Solo claves conocidas; las fijas siempre True.
                    visible = {k: (k in FIXED_COLUMNS or bool(stored.get(k))) for k in COLUMNS_BY_KEY}
                    return visible
    except Exception as e:
        print(f"⚠️ get_employee_list_columns({uid}): {e}")
    return {k: (k in DEFAULT_VISIBLE_COLUMNS) for k in COLUMNS_BY_KEY}


def save_employee_list_columns(uid: str, columns: dict) -> bool:
    """Guarda {key: bool} de visibilidad para el usuario."""
    if not uid:
        return False
    try:
        from app.services.db_service import db_firestore, firebase_initialized
        if firebase_initialized and db_firestore is not None:
            clean = {k: bool(v) for k, v in columns.items() if k in COLUMNS_BY_KEY}
            for k in FIXED_COLUMNS:
                clean[k] = True
            db_firestore.collection(_config_path(uid)).document(_PREFS_DOC_ID).set(
                {_PREFS_FIELD: clean}, merge=True
            )
            return True
    except Exception as e:
        print(f"⚠️ save_employee_list_columns({uid}): {e}")
    return False
