"""Regresión del maestro de posiciones: ficha (detail) persiste descripción,
merge de horario y validación anti-ciclo; creación redirige a la ficha."""

from types import SimpleNamespace
from unittest.mock import patch

import app.web.rrhh.positions as pos


class _Form:
    """Mini form con get/getlist para simular request.form."""

    def __init__(self, data):
        self.data = data

    def get(self, key, default=""):
        return self.data.get(key, default)

    def getlist(self, key):
        v = self.data.get(key)
        if v is None:
            return []
        return v if isinstance(v, list) else [v]


def _run_detail_save(item_id, form_data, positions):
    saved = {}

    def fake_get_catalog(company_id, catalog_name, sandbox=True):
        return positions

    def fake_save(company_id, catalog_name, item, sandbox=True):
        saved["item"] = item

    with patch.object(pos, "_login_required", return_value=None), \
         patch.object(pos, "_get_owner_uid_and_sandbox", return_value=("u", True, "c")), \
         patch.object(pos.hr, "get_catalog", side_effect=fake_get_catalog), \
         patch.object(pos.hr, "save_catalog_item", side_effect=fake_save), \
         patch.object(pos, "flash", return_value=None), \
         patch.object(pos, "url_for", return_value="/x"), \
         patch.object(pos, "redirect", return_value="redirected"):
        pos.request = SimpleNamespace(form=_Form(form_data))
        pos.position_detail_save(item_id)
    return saved


def _run_create(form_data):
    saved = {}

    def fake_save(company_id, catalog_name, item, sandbox=True):
        saved["item"] = item

    with patch.object(pos, "_login_required", return_value=None), \
         patch.object(pos, "_get_owner_uid_and_sandbox", return_value=("u", True, "c")), \
         patch.object(pos.hr, "save_catalog_item", side_effect=fake_save), \
         patch.object(pos, "flash", return_value=None), \
         patch.object(pos, "url_for", return_value="/detail"), \
         patch.object(pos, "redirect", return_value="redirected"):
        pos.request = SimpleNamespace(form=_Form(form_data))
        pos.position_save()
    return saved


def test_detail_save_persiste_descripcion_y_merge_horario():
    positions = [{"id": "p1", "name": "Gerente", "active": True,
                  "workSchedule": [{"day": 0, "start": "08:00", "end": "17:00"}],
                  "reportsTo": ""}]
    saved = _run_detail_save("p1", {
        "name": "Gerente General",
        "reportsTo": "",
        "level": "estrategico",
        "departmentId": "d1",
        "purpose": "Dirigir la empresa.",
        "functions": ["Planificar", "Dirigir"],
        "responsibilities": ["Manejo de efectivo"],
        "competencies_knowledge": ["Finanzas"],
        "competencies_skills": ["Liderazgo"],
        "competencies_attitudes": ["Proactividad"],
        "performanceIndicators": ["Cumplimiento de metas"],
    }, positions)

    item = saved["item"]
    assert item["id"] == "p1"
    assert item["name"] == "Gerente General"
    assert item["level"] == "estrategico"
    assert item["departmentId"] == "d1"
    assert item["purpose"] == "Dirigir la empresa."
    assert item["functions"] == ["Planificar", "Dirigir"]
    assert item["responsibilities"] == ["Manejo de efectivo"]
    assert item["competencies"] == {
        "knowledge": ["Finanzas"], "skills": ["Liderazgo"], "attitudes": ["Proactividad"],
    }
    assert item["performanceIndicators"] == ["Cumplimiento de metas"]
    # merge: no se pisa el horario existente
    assert item["workSchedule"] == [{"day": 0, "start": "08:00", "end": "17:00"}]


def test_detail_save_rechaza_ciclo():
    positions = [
        {"id": "p1", "name": "Gerente", "active": True, "workSchedule": [], "reportsTo": "p2"},
        {"id": "p2", "name": "Supervisor", "active": True, "workSchedule": [], "reportsTo": "p1"},
    ]
    saved = _run_detail_save("p1", {"name": "Gerente", "reportsTo": "p2"}, positions)
    assert "item" not in saved


def test_detail_save_rechaza_autoreferencia():
    positions = [{"id": "p1", "name": "Gerente", "active": True, "workSchedule": [], "reportsTo": ""}]
    saved = _run_detail_save("p1", {"name": "Gerente", "reportsTo": "p1"}, positions)
    assert "item" not in saved


def test_create_persiste_nombre_y_reports_to():
    saved = _run_create({"name": "Analista", "reportsTo": ""})
    item = saved["item"]
    assert item["name"] == "Analista"
    assert item["reportsTo"] == ""
    assert item["workSchedule"] == []
    assert item["id"]


def test_create_sin_nombre_no_guarda():
    saved = _run_create({"name": "  "})
    assert "item" not in saved
