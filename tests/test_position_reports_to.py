"""Regresión: el formulario 'Reporta a' de posiciones debe persistir la jerarquía."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import app.web.rrhh.positions as pos
from app.services import hr_data_service as hr


def _post(form_data):
    """Invoca position_save() con los globals de Flask simulados."""
    saved = {}

    def fake_get_catalog(company_id, catalog_name, sandbox=True):
        return [
            {"id": "p1", "name": "Gerente General", "active": True, "workSchedule": [], "reportsTo": ""},
            {"id": "p2", "name": "Supervisor", "active": True, "workSchedule": [], "reportsTo": "p1"},
        ]

    def fake_save(company_id, catalog_name, item, sandbox=True):
        saved["item"] = item

    with patch.object(pos, "_login_required", return_value=None), \
         patch.object(pos, "_get_owner_uid_and_sandbox", return_value=("u", True, "c")), \
         patch.object(pos.hr, "get_catalog", side_effect=fake_get_catalog), \
         patch.object(pos.hr, "save_catalog_item", side_effect=fake_save), \
         patch.object(pos, "flash", return_value=None), \
         patch.object(pos, "url_for", return_value="/rrhh/positions"), \
         patch.object(pos, "redirect", return_value="redirected"):
        pos.request = SimpleNamespace(form=form_data)
        pos.position_save()
    return saved


def test_reports_to_persiste():
    saved = _post({"id": "p2", "name": "Supervisor", "reportsTo": "p1"})
    assert saved["item"]["id"] == "p2"
    assert saved["item"]["reportsTo"] == "p1"


def test_reports_to_raiz_limpia():
    saved = _post({"id": "p2", "name": "Supervisor", "reportsTo": ""})
    assert saved["item"]["reportsTo"] == ""


def test_editar_nombre_no_pisa_jerarquia():
    saved = _post({"id": "p2", "name": "Supervisor II"})
    assert saved["item"]["reportsTo"] == "p1"


def test_get_catalog_inyecta_id_desde_documento():
    """Catálogos legacy/migrados sin campo 'id' deben seguir trayendo id (doc.id)."""
    mock_db = MagicMock()
    doc = MagicMock()
    doc.id = "pos-legacy-1"
    doc.to_dict.return_value = {"name": "Gerente", "active": True}
    mock_db.collection.return_value.get.return_value = [doc]

    with patch.object(hr, "firebase_initialized", True), \
         patch.object(hr, "db_firestore", mock_db), \
         patch.object(hr, "_catalog_coll_path", return_value="companies/c/hr_catalog_positions"):
        items = hr.get_catalog("c", "positions", sandbox=True)

    assert items == [{"id": "pos-legacy-1", "name": "Gerente", "active": True}]

