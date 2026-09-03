"""Tests para las columnas configurables del grid de empleados."""

from unittest.mock import MagicMock, patch

from app.web.rrhh.employee_columns import (
    EMPLOYEE_GRID_COLUMNS,
    COLUMNS_BY_KEY,
    DEFAULT_VISIBLE_COLUMNS,
    FIXED_COLUMNS,
    format_cell,
    enrich_employees,
    get_employee_list_columns,
    save_employee_list_columns,
)


class TestColumnRegistry:
    def test_columnas_unicas(self):
        keys = [c["key"] for c in EMPLOYEE_GRID_COLUMNS]
        assert len(keys) == len(set(keys))

    def test_fijas_incluidas(self):
        assert FIXED_COLUMNS == {"code", "fullName", "status"}

    def test_defaults_subconjunto(self):
        assert set(DEFAULT_VISIBLE_COLUMNS) <= set(COLUMNS_BY_KEY)

    def test_campos_clave_presentes(self):
        for k in ("code", "fullName", "position", "department", "vacationDays",
                  "status", "baseSalary", "nationalityName", "disabilityName"):
            assert k in COLUMNS_BY_KEY


class TestFormatCell:
    def test_vacio(self):
        assert format_cell(None, "text") == "—"
        assert format_cell("", "text") == "—"

    def test_money(self):
        assert format_cell(50000, "money") == "50,000.00"

    def test_vacation(self):
        assert format_cell(15, "vacation") == "15 d"

    def test_bool(self):
        assert format_cell(True, "bool") == "Sí"
        assert format_cell(False, "bool") == "No"

    def test_status(self):
        assert format_cell("vacaciones", "status") == "Vacaciones"

    def test_termination_type(self):
        assert format_cell("renuncia", "terminationType") == "Renuncia"

    def test_date(self):
        assert format_cell("2024-01-15", "date") == "15/01/2024"

    def test_list(self):
        assert format_cell(["a", "b"], "list") == "a; b"


class TestEnrichEmployees:
    def test_resuelve_campos_computados(self):
        branches = [{"id": "b1", "name": "Sucursal Norte"}]
        employees = [
            {"id": "e1", "branchId": "b1", "reportsTo": "e2",
             "nationality": 18, "disability": "285,289"},
            {"id": "e2", "fullName": "Ana Jefa", "branchId": "", "reportsTo": "",
             "nationality": 1, "disability": "4714"},
        ]
        enrich_employees(employees, branches)
        e1, e2 = employees
        assert e1["branchName"] == "Sucursal Norte"
        assert e1["supervisorName"] == "Ana Jefa"
        assert e1["nationalityName"] == "VENEZOLANA"
        assert e1["disabilityName"] == "Discapacidad Auditiva, Discapacidad Visual"
        assert e2["disabilityName"] == "Ninguna"


class TestPersistence:
    def _mock_firestore(self, stored=None):
        db = MagicMock()
        doc = MagicMock()
        doc.exists = stored is not None
        doc.to_dict.return_value = stored or {}
        db.collection.return_value.document.return_value.get.return_value = doc
        db.collection.return_value.document.return_value.set.return_value = None
        return db

    def test_sin_uid_devuelve_defaults(self):
        visible = get_employee_list_columns("")
        assert visible["fullName"] is True
        assert visible["code"] is True
        assert visible["status"] is True
        assert visible["email"] is False

    def test_get_sin_documento_devuelve_defaults(self):
        db = self._mock_firestore(stored=None)
        with patch("app.services.db_service.db_firestore", db), \
             patch("app.services.db_service.firebase_initialized", True):
            visible = get_employee_list_columns("u1")
        assert visible["email"] is False
        assert visible["fullName"] is True

    def test_get_con_documento(self):
        db = self._mock_firestore(stored={"employeeListColumns": {"email": True, "fullName": True}})
        with patch("app.services.db_service.db_firestore", db), \
             patch("app.services.db_service.firebase_initialized", True):
            visible = get_employee_list_columns("u1")
        assert visible["email"] is True
        # Fijas siempre True aunque no estén en el doc
        assert visible["code"] is True
        assert visible["status"] is True
        assert visible["position"] is False

    def test_save_fuerza_fijas(self):
        db = self._mock_firestore(stored=None)
        with patch("app.services.db_service.db_firestore", db), \
             patch("app.services.db_service.firebase_initialized", True):
            ok = save_employee_list_columns("u1", {"email": True, "code": False, "fullName": False})
        assert ok is True
        set_args = db.collection.return_value.document.return_value.set.call_args
        payload = set_args[0][0]
        assert payload["employeeListColumns"]["code"] is True
        assert payload["employeeListColumns"]["fullName"] is True
        assert payload["employeeListColumns"]["email"] is True
