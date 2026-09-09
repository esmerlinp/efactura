"""Ficha de empleado en PDF estilo CV: resumen IA, helpers, template y ruta.

Nota: no usa el fixture `app` global porque `create_app()` no carga en este
entorno (extensiones nativas lxml/PIL rotas en el venv — preexistente). En su
lugar se levanta una app Flask mínima solo con el blueprint de RRHH.
"""

import os
import sys
import types
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from flask import Flask, render_template

from app.services.ai_service import AIService
from app.web.rrhh import employee_profile_pdf as profile_mod, web_rrhh_bp


@pytest.fixture(scope="module")
def mini_app():
    """App Flask mínima con solo el blueprint RRHH (evita create_app completo)."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(__name__, template_folder=os.path.join(base, "templates"))
    app.secret_key = "test-secret"
    app.register_blueprint(web_rrhh_bp)
    # Stub del login (la ruta real redirige a web_auth.login si no hay sesión)
    from flask import Blueprint
    auth_stub = Blueprint("web_auth", __name__)

    @auth_stub.route("/login")
    def login():
        return "login", 200

    app.register_blueprint(auth_stub)
    return app


@pytest.fixture()
def mini_client(mini_app):
    return mini_app.test_client()


# ── Fixtures ──────────────────────────────────────────────────────────────

def _employee():
    return {
        "id": "emp-1",
        "code": 7,
        "fullName": "María Fernández Pérez",
        "firstName": "María",
        "firstLastName": "Fernández",
        "position": "Contadora Senior",
        "department": "Contabilidad",
        "area": "Finanzas",
        "contractType": "Indefinido",
        "hireDate": "2020-03-15",
        "status": "activo",
        "idType": "Cédula",
        "idNumber": "001-1234567-8",
        "birthDate": "1990-06-20",
        "gender": "femenino",
        "maritalStatus": "C",
        "email": "maria@test.com",
        "phone": "809-555-0101",
        "address": "Calle 1ra #10",
        "municipality": "Santo Domingo Este",
        "emergencyContact": "Juan Pérez",
        "emergencyPhone": "809-555-0102",
        "educationLevel": 4,
        "sirlaEducationCode": "",
        "nationality": 1,
        "disability": "",
        "occupationCode": "2411",
        "branchId": "b1",
        "workday": "Completa",
        "workShift": 1,
        "weeklyHours": 44,
        "isVigilante": False,
        "tssKey": "TSS-1",
        "probationEndDate": "2020-06-15",
        "costCenter": "CC-01",
        "payrollGroupIds": ["g1"],
        "baseSalary": 85000.0,
        "paymentMethod": "Transferencia",
        "bank": "Banco Popular",
        "accountNumber": "123456789",
        "accountType": "Ahorros",
        "afpProvider": "AFP Popular",
        "photoUrl": "",
        "photoBase64": "",
        "notes": "Empleada destacada.",
    }


def _ctx():
    return {
        "employee": _employee(),
        "vacation_days": 12,
        "severance": {"preaviso": 85000.0, "cesantia": 340000.0,
                      "vacaciones_pendientes": 12000.0, "total": 437000.0},
        "evaluations": [
            {"date": "2024-12-01", "evalType": "Anual", "score": 4.5,
             "evaluatorName": "J. Soto", "strengths": "Responsable y puntual"},
            {"date": "2023-12-01", "evalType": "Anual", "score": 4.0,
             "evaluatorName": "J. Soto", "strengths": "Buen manejo contable"},
        ],
        "trainings": [
            {"date": "2024-05-10", "trainingName": "NIIF 2024", "institution": "INFOTEP",
             "hours": 20, "hasCertificate": True},
        ],
        "documents": [
            {"name": "Contrato.pdf", "category": "contract", "uploadedAt": "2020-03-15T10:00:00",
             "size": 204800, "notes": "", "_isRehireDoc": False, "_periodNumber": ""},
        ],
        "payment_history": [
            {"period": {"periodRange": "1 - 15 Ene 2025", "periodKey": "2025-01-1",
                        "periodType": "quincenal", "processedDate": "2025-01-15T12:00:00"},
             "line": {"grossSalary": 42500.0, "totalIncome": 45000.0,
                      "totalDeductions": 5000.0, "netSalary": 40000.0}},
        ],
        "timeline": [
            {"kind": "mass", "action": "promotion", "category": "accion_masiva",
             "label": "Promoción", "detail": "Puesto Contadora Junior → Contadora Senior",
             "actor": "rrhh@test.com", "_date": "2024-06-01", "_time": "09:00"},
            {"kind": "audit", "action": "create", "category": "empleado",
             "label": "Empleado creado", "detail": "Registro inicial",
             "actor": "admin@test.com", "_date": "2020-03-15", "_time": "08:00"},
        ],
        "active_requests": {},
        "average_salary": 85000.0,
        "payroll_groups": [{"id": "g1", "name": "Grupo Mensual"}],
        "branches": [{"id": "b1", "name": "Sede Central"}],
        "dependents": [
            {"firstName": "Luis", "middleName": "", "firstLastName": "Fernández",
             "secondLastName": "Pérez", "active": True, "isStudent": True,
             "isFinancialDependent": True, "relationshipName": "Hijo",
             "relationshipCode": "HIJO", "_age": 10, "gender": "masculino",
             "idNumber": "", "birthDate": "2015-01-01", "notes": ""},
        ],
        "dep_minor": 1, "dep_adult": 0, "dep_financial": 1, "dep_student": 1,
        "relationship_catalog": [],
        "herramientas_asignadas": [
            {"herramientaName": "Laptop Dell", "herramientaCode": "LT-001",
             "assignedDate": "2023-02-01T09:00:00", "status": "activa"},
        ],
        "recurring_movements": [
            {"description": "Préstamo personal", "conceptCode": "PREST",
             "movementType": "deduction", "status": "active", "isLoan": True,
             "isGarnishment": False, "installmentAmount": 5000.0, "amount": 5000.0,
             "totalAmount": 60000.0, "remainingBalance": 30000.0,
             "paidInstallments": 6, "totalInstallments": 12,
             "startDate": "2024-07-01", "endDate": "2025-06-30", "indefinite": False,
             "_applications": [
                 {"periodKey": "2025-01-1", "appliedAt": "2025-01-15T12:00:00",
                  "appliedAmount": 5000.0, "remainingAfter": 30000.0, "action": "applied"},
             ]},
        ],
        "offboarding_requests": [],
        "employment_contracts": [
            {"id": "c1", "periodNumber": 1, "startDate": "2020-03-15", "endDate": "",
             "position": "Contadora Senior", "salary": 85000.0, "status": "active"},
        ],
        "active_contract": {"id": "c1"},
        "states": {},
        "sirla_education_label": "Grado",
        "sirla_nationality_name": "Dominicana",
        "sirla_disability_names": "",
        "employee_work_days": [0, 1, 2, 3, 4],
    }


def _company():
    return {"companyName": "TecnoDom SRL", "tradeName": "TecnoDom",
            "companyRNC": "132109122", "logoUrl": "", "logoBase64": ""}


# ── Helpers de la ruta ────────────────────────────────────────────────────

def test_tenure_text():
    assert profile_mod._tenure_text("") == ""
    assert profile_mod._tenure_text("no-fecha") == ""
    three_years_ago = (date.today() - timedelta(days=3 * 365 + 40)).strftime("%Y-%m-%d")
    assert profile_mod._tenure_text(three_years_ago).startswith("3 años")
    recent = (date.today() - timedelta(days=40)).strftime("%Y-%m-%d")
    assert "mes" in profile_mod._tenure_text(recent)
    future = (date.today() + timedelta(days=10)).strftime("%Y-%m-%d")
    assert profile_mod._tenure_text(future) == ""


def test_fmt_rd():
    assert profile_mod._fmt_rd(85000) == "RD$ 85,000.00"
    assert profile_mod._fmt_rd("***") == "***"  # sanitizado por rol se conserva
    assert profile_mod._fmt_rd("no-num") == "—"


def test_avg_evaluation():
    assert profile_mod._avg_evaluation([]) is None
    assert profile_mod._avg_evaluation([{"score": 4.5}, {"score": "4.0"}]) == 4.2
    assert profile_mod._avg_evaluation([{"score": 0}]) is None


def test_milestones_limit_and_format():
    timeline = [
        {"kind": "mass", "action": "promotion", "category": "accion_masiva",
         "label": "Promoción", "detail": "A → B", "actor": "", "_date": "2024-06-01", "_time": ""},
        {"kind": "audit", "action": "payroll_paid", "category": "pago",
         "label": "Pago de nómina", "detail": "Neto RD$ 40,000.00",
         "actor": "", "_date": "2025-01-15", "_time": ""},
    ]
    miles = profile_mod._milestones(timeline)
    assert len(miles) == 1  # el pago de nómina no es hito
    assert miles[0] == "Promoción: A → B (2024-06-01)"


def test_build_bio_input_minimiza_pii():
    bio = profile_mod._build_bio_input(_ctx(), _company())
    assert bio["fullName"] == "María Fernández Pérez"
    assert bio["tenure"]  # calculada
    assert bio["avgEvaluation"] == 4.2
    assert bio["trainings"] == ["NIIF 2024"]
    assert any("Promoción" in m for m in bio["milestones"])
    for forbidden in ("idNumber", "cedula", "baseSalary", "salary", "bank",
                      "accountNumber", "address", "phone"):
        assert forbidden not in bio, forbidden


# ── Servicio IA ───────────────────────────────────────────────────────────

def test_bio_template_siempre_genera_texto():
    text = AIService.build_employee_bio_template(profile_mod._build_bio_input(_ctx(), _company()))
    assert "María Fernández Pérez" in text
    assert "Contadora Senior" in text
    assert "NIIF 2024" in text
    # Sin datos también genera algo razonable
    assert len(AIService.build_employee_bio_template({})) > 20


def test_generate_bio_sin_api_key():
    with patch.object(AIService, "_get_api_key", return_value=""):
        result = AIService.generate_employee_bio("uid", {"fullName": "X"})
    assert result["success"] is False


def test_generate_bio_llamada_ok():
    fake_resp = {"choices": [{"message": {"content": "Perfil generado por IA."}}]}

    class _Resp:
        status_code = 200

        def json(self):
            return fake_resp

    with patch.object(AIService, "_get_api_key", return_value="k"), \
         patch("app.services.ai_service.requests.post", return_value=_Resp()):
        result = AIService.generate_employee_bio("uid", {"fullName": "X"})
    assert result == {"success": True, "text": "Perfil generado por IA."}


def test_generate_bio_error_api():
    class _Resp:
        status_code = 500
        text = "boom"

    with patch.object(AIService, "_get_api_key", return_value="k"), \
         patch("app.services.ai_service.requests.post", return_value=_Resp()):
        result = AIService.generate_employee_bio("uid", {"fullName": "X"})
    assert result["success"] is False


# ── Template ──────────────────────────────────────────────────────────────

def test_template_renderiza_todas_las_secciones(mini_app):
    ctx = _ctx()
    company = _company()
    company["logoBase64"] = "iVBORw0KGgoAAAANSUhEUg=="  # base64 crudo, como lo guarda el perfil
    with mini_app.test_request_context():
        html = render_template(
            "rrhh/employee_profile_pdf.html",
            bio="Perfil de prueba en dos párrafos.\n\nSegundo párrafo.",
            company=company, now="01/01/2025",
            tenure="4 años y 9 meses", education_label="Grado",
            marital_label="Casado/a", shift_label="Diurno",
            status_label="Activo", avg_evaluation=4.2,
            fmt_rd=profile_mod._fmt_rd, **ctx)
    for expected in ["Perfil profesional", "Perfil de prueba", "Datos personales",
                     "Datos laborales", "Compensación", "Vacaciones y prestaciones",
                     "Historial laboral", "Trayectoria profesional",
                     "Evaluaciones de desempeño", "Capacitaciones",
                     "Historial de pagos", "Movimientos recurrentes",
                     "Herramientas asignadas", "Dependientes", "Documentos", "Notas",
                     "María Fernández Pérez", "Contadora Senior", "RD$ 85,000.00",
                     "2024", "Préstamo personal", "Laptop Dell", "NIIF 2024",
                     "Contrato.pdf", "Empleada destacada."]:
        assert expected in html, expected
    assert "{{" not in html and "{%" not in html  # sin tags sin renderizar
    # El logoBase64 del perfil es base64 crudo: el src debe llevar prefijo data:
    assert 'src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="' in html


def test_template_con_empleado_minimo(mini_app):
    emp = {"id": "e2", "fullName": "Sin Datos"}
    with mini_app.test_request_context():
        html = render_template(
            "rrhh/employee_profile_pdf.html",
            bio="Resumen mínimo.", company={}, now="01/01/2025",
            tenure="", education_label="", marital_label="", shift_label="",
            status_label="", avg_evaluation=None,
            fmt_rd=profile_mod._fmt_rd, show_payments=True,
            employee=emp, vacation_days=0, severance=None, evaluations=[],
            trainings=[], documents=[], payment_history=[], timeline=[],
            active_requests={}, average_salary=0, payroll_groups=[], branches=[],
            dependents=[], dep_minor=0, dep_adult=0, dep_financial=0, dep_student=0,
            relationship_catalog=[], herramientas_asignadas=[], recurring_movements=[],
            offboarding_requests=[], employment_contracts=[], active_contract=None,
        states={}, sirla_education_label="", sirla_nationality_name="",
        sirla_disability_names="", employee_work_days=[])
    assert "Sin Datos" in html
    assert "Sin acciones registradas" in html


def test_template_sin_historial_pagos(mini_app):
    ctx = _ctx()
    with mini_app.test_request_context():
        html = render_template(
            "rrhh/employee_profile_pdf.html",
            bio="Bio.", company=_company(), now="01/01/2025",
            tenure="", education_label="", marital_label="", shift_label="",
            status_label="Activo", avg_evaluation=None,
            fmt_rd=profile_mod._fmt_rd, show_payments=False, **ctx)
    assert "Historial de pagos" not in html
    # El resto de la ficha sigue intacto
    assert "Trayectoria profesional" in html
    assert "María Fernández Pérez" in html


# ── Ruta ──────────────────────────────────────────────────────────────────

def _fake_weasyprint_module():
    rendered = {}

    class _FakeHTML:
        def __init__(self, string=None, base_url=None):
            rendered["string"] = string
            rendered["base_url"] = base_url

        def write_pdf(self, **kwargs):
            rendered["kwargs"] = kwargs
            return b"%PDF-1.4 fake"

    module = types.ModuleType("weasyprint")
    module.HTML = _FakeHTML
    return module, rendered


def _login(client):
    with client.session_transaction() as sess:
        sess["user"] = {"uid": "test-uid", "ownerUID": "test-owner",
                        "role": "owner", "email": "admin@test.com",
                        "name": "Admin", "permissions": {"canHR": True}}
        sess["is_sandbox_mode"] = True
        sess["selected_company_id"] = "c1"


def test_profile_pdf_route_ok(mini_client):
    _login(mini_client)
    fake_mod, rendered = _fake_weasyprint_module()
    with patch.dict(sys.modules, {"weasyprint": fake_mod}), \
         patch.object(profile_mod, "_load_employee_context", return_value=_ctx()), \
         patch.object(profile_mod, "_get_company_data", return_value=_company()), \
         patch.object(AIService, "generate_employee_bio",
                      return_value={"success": True, "text": "Bio IA de prueba."}), \
         patch("app.services.payroll_audit_service.log_employee_action"):
        resp = mini_client.get("/rrhh/employees/emp-1/profile.pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data == b"%PDF-1.4 fake"
    assert "Bio IA de prueba." in rendered["string"]
    assert "María Fernández Pérez" in rendered["string"]
    assert "Historial de pagos" in rendered["string"]  # default: incluye pagos


def test_profile_pdf_route_con_pagos_explicito(mini_client):
    _login(mini_client)
    fake_mod, rendered = _fake_weasyprint_module()
    with patch.dict(sys.modules, {"weasyprint": fake_mod}), \
         patch.object(profile_mod, "_load_employee_context", return_value=_ctx()), \
         patch.object(profile_mod, "_get_company_data", return_value=_company()), \
         patch.object(AIService, "generate_employee_bio",
                      return_value={"success": True, "text": "Bio."}), \
         patch("app.services.payroll_audit_service.log_employee_action"):
        resp = mini_client.get("/rrhh/employees/emp-1/profile.pdf?include_payments=1")
    assert resp.status_code == 200
    assert "Historial de pagos" in rendered["string"]


def test_profile_pdf_route_sin_pagos(mini_client):
    _login(mini_client)
    fake_mod, rendered = _fake_weasyprint_module()
    with patch.dict(sys.modules, {"weasyprint": fake_mod}), \
         patch.object(profile_mod, "_load_employee_context", return_value=_ctx()), \
         patch.object(profile_mod, "_get_company_data", return_value=_company()), \
         patch.object(AIService, "generate_employee_bio",
                      return_value={"success": True, "text": "Bio."}), \
         patch("app.services.payroll_audit_service.log_employee_action") as mock_log:
        resp = mini_client.get("/rrhh/employees/emp-1/profile.pdf?include_payments=0")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert "Historial de pagos" not in rendered["string"]
    # El resto de la ficha sigue intacto
    assert "María Fernández Pérez" in rendered["string"]
    assert "Trayectoria profesional" in rendered["string"]
    # La elección queda registrada en auditoría
    assert mock_log.call_args.kwargs["changes"] == {"includePayments": False}


def test_profile_pdf_route_fallback_sin_ia(mini_client):
    _login(mini_client)
    fake_mod, rendered = _fake_weasyprint_module()
    with patch.dict(sys.modules, {"weasyprint": fake_mod}), \
         patch.object(profile_mod, "_load_employee_context", return_value=_ctx()), \
         patch.object(profile_mod, "_get_company_data", return_value=_company()), \
         patch.object(AIService, "generate_employee_bio",
                      return_value={"success": False, "message": "sin key"}), \
         patch("app.services.payroll_audit_service.log_employee_action"):
        resp = mini_client.get("/rrhh/employees/emp-1/profile.pdf")
    assert resp.status_code == 200
    # El respaldo determinístico menciona nombre y cargo
    assert "María Fernández Pérez" in rendered["string"]
    assert "Contadora Senior" in rendered["string"]


def test_profile_pdf_route_empleado_inexistente(mini_client):
    _login(mini_client)
    with patch.object(profile_mod, "_load_employee_context", return_value=None):
        resp = mini_client.get("/rrhh/employees/nope/profile.pdf")
    assert resp.status_code == 302  # redirect al listado


def test_profile_pdf_route_requiere_login(mini_client):
    resp = mini_client.get("/rrhh/employees/emp-1/profile.pdf")
    assert resp.status_code == 302
