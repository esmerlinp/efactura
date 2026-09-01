"""Tests para el código incremental de empleado en HRDataService.

Cubre: asignación secuencial del contador (transacción Firestore), auto-asignación
al crear, preservación al actualizar, respeto de códigos explícitos (importación)
y bump del contador con códigos importados.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services import hr_data_service as hr

COMPANY = "company-test"


# ═══════════════════════════════════════════════════════════════════════════
# Contador transaccional get_next_employee_code
# ═══════════════════════════════════════════════════════════════════════════

class TestGetNextEmployeeCode:
    @patch("firebase_admin.firestore")
    def test_primer_codigo_es_1(self, mock_fstore):
        mock_fstore.transactional = lambda f: f
        mock_db = MagicMock()
        transaction = MagicMock()
        mock_db.transaction.return_value = transaction
        counter_doc = MagicMock()
        counter_doc.exists = False
        mock_db.collection.return_value.document.return_value.get.return_value = counter_doc

        with patch.object(hr, "db_firestore", mock_db), \
             patch.object(hr, "firebase_initialized", True):
            code = hr.get_next_employee_code(COMPANY, sandbox=True)

        assert code == 1
        coll = mock_db.collection.call_args.args[0]
        assert coll == f"companies/{COMPANY}/sandbox_hr_config"
        transaction.set.assert_called_once()

    @patch("firebase_admin.firestore")
    def test_secuencia_incremental(self, mock_fstore):
        mock_fstore.transactional = lambda f: f
        mock_db = MagicMock()
        transaction = MagicMock()
        mock_db.transaction.return_value = transaction
        counter_doc = MagicMock()
        counter_doc.exists = True
        counter_doc.to_dict.return_value = {"next": 7}
        mock_db.collection.return_value.document.return_value.get.return_value = counter_doc

        with patch.object(hr, "db_firestore", mock_db), \
             patch.object(hr, "firebase_initialized", True):
            code = hr.get_next_employee_code(COMPANY, sandbox=True)

        assert code == 8

    @patch("firebase_admin.firestore")
    def test_sandbox_y_prod_usan_contadores_separados(self, mock_fstore):
        mock_fstore.transactional = lambda f: f
        mock_db = MagicMock()
        transaction = MagicMock()
        mock_db.transaction.return_value = transaction
        counter_doc = MagicMock()
        counter_doc.exists = False
        mock_db.collection.return_value.document.return_value.get.return_value = counter_doc

        with patch.object(hr, "db_firestore", mock_db), \
             patch.object(hr, "firebase_initialized", True):
            hr.get_next_employee_code(COMPANY, sandbox=True)
            hr.get_next_employee_code(COMPANY, sandbox=False)

        colls = [c.args[0] for c in mock_db.collection.call_args_list]
        assert f"companies/{COMPANY}/sandbox_hr_config" in colls
        assert f"companies/{COMPANY}/hr_config" in colls

    def test_sin_firebase_retorna_0(self):
        with patch.object(hr, "firebase_initialized", False):
            assert hr.get_next_employee_code(COMPANY, sandbox=True) == 0

    @patch("firebase_admin.firestore")
    def test_fallback_scan_max_si_falla_transaccion(self, mock_fstore):
        mock_fstore.transactional = lambda f: f
        mock_db = MagicMock()
        mock_db.transaction.return_value = MagicMock()

        def boom(transaction):
            raise RuntimeError("fail")
        counter_doc = MagicMock()
        counter_doc.exists = True
        mock_db.collection.return_value.document.return_value.get.return_value = counter_doc
        counter_doc.to_dict.side_effect = boom

        with patch.object(hr, "db_firestore", mock_db), \
             patch.object(hr, "firebase_initialized", True), \
             patch.object(hr, "get_employees", return_value=[{"code": 5}, {"code": 12}]) as mock_emps:
            code = hr.get_next_employee_code(COMPANY, sandbox=True)

        assert code == 13
        mock_emps.assert_called_once_with(COMPANY, sandbox=True)


# ═══════════════════════════════════════════════════════════════════════════
# save_employee — auto-asignación y preservación
# ═══════════════════════════════════════════════════════════════════════════

class TestSaveEmployeeCode:
    @patch.object(hr, "_save")
    def test_crea_asigna_codigo(self, mock_save):
        with patch.object(hr, "get_employee", return_value=None), \
             patch.object(hr, "get_next_employee_code", return_value=3):
            hr.save_employee(COMPANY, "emp-a", {"id": "emp-a", "fullName": "Ana Pérez"}, sandbox=True)

        saved = mock_save.call_args.args[3]
        assert saved["code"] == 3

    @patch.object(hr, "_save")
    def test_update_preserva_codigo_del_dict(self, mock_save):
        with patch.object(hr, "get_employee") as mock_get, \
             patch.object(hr, "get_next_employee_code") as mock_next:
            hr.save_employee(COMPANY, "emp-a", {"id": "emp-a", "code": 7}, sandbox=True)

        mock_get.assert_not_called()
        mock_next.assert_not_called()
        saved = mock_save.call_args.args[3]
        assert saved["code"] == 7

    @patch.object(hr, "_save")
    def test_update_sin_codigo_recupera_existente(self, mock_save):
        with patch.object(hr, "get_employee", return_value={"id": "emp-a", "code": 9}), \
             patch.object(hr, "get_next_employee_code") as mock_next:
            hr.save_employee(COMPANY, "emp-a", {"id": "emp-a", "fullName": "Ana Pérez"}, sandbox=True)

        mock_next.assert_not_called()
        saved = mock_save.call_args.args[3]
        assert saved["code"] == 9

    @patch.object(hr, "_save")
    def test_import_csv_codigo_explicito_se_respeta(self, mock_save):
        with patch.object(hr, "get_next_employee_code") as mock_next:
            hr.save_employee(COMPANY, "emp-b", {"id": "emp-b", "code": 42}, sandbox=True)

        mock_next.assert_not_called()
        saved = mock_save.call_args.args[3]
        assert saved["code"] == 42

    @patch.object(hr, "_save")
    def test_legacy_sin_codigo_edicion_asigna(self, mock_save):
        with patch.object(hr, "get_employee", return_value={"id": "emp-c", "fullName": "Legacy"}), \
             patch.object(hr, "get_next_employee_code", return_value=1):
            hr.save_employee(COMPANY, "emp-c", {"id": "emp-c", "fullName": "Legacy"}, sandbox=True)

        saved = mock_save.call_args.args[3]
        assert saved["code"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# bump_employee_counter
# ═══════════════════════════════════════════════════════════════════════════

class TestBumpEmployeeCounter:
    @patch("firebase_admin.firestore")
    def test_bump_cuando_codigo_mayor(self, mock_fstore):
        mock_fstore.transactional = lambda f: f
        mock_db = MagicMock()
        transaction = MagicMock()
        mock_db.transaction.return_value = transaction
        counter_doc = MagicMock()
        counter_doc.exists = True
        counter_doc.to_dict.return_value = {"next": 10}
        mock_db.collection.return_value.document.return_value.get.return_value = counter_doc

        with patch.object(hr, "db_firestore", mock_db), \
             patch.object(hr, "firebase_initialized", True):
            hr.bump_employee_counter(COMPANY, 25, sandbox=True)

        transaction.set.assert_called_once()

    @patch("firebase_admin.firestore")
    def test_no_bump_cuando_codigo_menor(self, mock_fstore):
        mock_fstore.transactional = lambda f: f
        mock_db = MagicMock()
        transaction = MagicMock()
        mock_db.transaction.return_value = transaction
        counter_doc = MagicMock()
        counter_doc.exists = True
        counter_doc.to_dict.return_value = {"next": 30}
        mock_db.collection.return_value.document.return_value.get.return_value = counter_doc

        with patch.object(hr, "db_firestore", mock_db), \
             patch.object(hr, "firebase_initialized", True):
            hr.bump_employee_counter(COMPANY, 25, sandbox=True)

        transaction.set.assert_not_called()

    def test_sin_codigo_no_hace_nada(self):
        with patch.object(hr, "firebase_initialized", True), \
             patch.object(hr, "db_firestore", MagicMock()) as mock_db:
            hr.bump_employee_counter(COMPANY, 0, sandbox=True)
        mock_db.transaction.assert_not_called()
