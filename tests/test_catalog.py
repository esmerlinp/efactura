"""Regresión del path y persistencia del catálogo (posiciones/departamentos).

Verifica que `_catalog_coll_path` usa `company_id` directamente (no owner_uid) y
que `save_catalog_item` → `get_catalog` persiste el campo `reportsTo`.
"""

from unittest.mock import patch

from app.services import hr_data_service as hr


class _FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


class _FakeStore:
    """Firestore mínimo en memoria: collection().document().set() y .get()."""

    def __init__(self):
        self.data = {}

    def collection(self, path):
        self._path = path
        return self

    def document(self, doc_id):
        self._doc_id = doc_id
        return self

    def set(self, item):
        self.data[self._doc_id] = dict(item)

    def get(self):
        return [_FakeDoc(did, d) for did, d in self.data.items()]


def test_catalog_coll_path_sandbox():
    assert hr._catalog_coll_path("c1", "positions", sandbox=True) == \
        "companies/c1/sandbox_hr_catalog_positions"


def test_catalog_coll_path_prod():
    assert hr._catalog_coll_path("c1", "departments", sandbox=False) == \
        "companies/c1/hr_catalog_departments"


def test_catalog_coll_path_sin_company():
    assert hr._catalog_coll_path("", "positions", sandbox=True) is None
    assert hr._catalog_coll_path(None, "positions", sandbox=True) is None


def test_roundtrip_persiste_reports_to():
    store = _FakeStore()
    with patch.object(hr, "firebase_initialized", True), \
         patch.object(hr, "db_firestore", store):
        hr.save_catalog_item("c1", "positions",
                             {"id": "p1", "name": "Gerente General", "active": True,
                              "workSchedule": [], "reportsTo": ""}, sandbox=True)
        hr.save_catalog_item("c1", "positions",
                             {"id": "p2", "name": "Supervisor", "active": True,
                              "workSchedule": [], "reportsTo": "p1"}, sandbox=True)

        items = hr.get_catalog("c1", "positions", sandbox=True)

    by_id = {i["id"]: i for i in items}
    assert by_id["p2"]["reportsTo"] == "p1"
    assert by_id["p1"]["reportsTo"] == ""


def test_roundtrip_persiste_descripcion_puesto():
    store = _FakeStore()
    with patch.object(hr, "firebase_initialized", True), \
         patch.object(hr, "db_firestore", store):
        hr.save_catalog_item("c1", "positions", {
            "id": "p1", "name": "Gerente General", "active": True,
            "workSchedule": [], "reportsTo": "",
            "departmentId": "d1", "level": "estrategico",
            "purpose": "Dirigir la empresa.",
            "functions": ["Planificar"],
            "responsibilities": ["Supervisión"],
            "competencies": {"knowledge": ["Finanzas"], "skills": ["Liderazgo"], "attitudes": ["Proactividad"]},
            "performanceIndicators": ["Metas"],
        }, sandbox=True)

        items = hr.get_catalog("c1", "positions", sandbox=True)

    item = items[0]
    assert item["departmentId"] == "d1"
    assert item["level"] == "estrategico"
    assert item["purpose"] == "Dirigir la empresa."
    assert item["functions"] == ["Planificar"]
    assert item["competencies"]["knowledge"] == ["Finanzas"]
    assert item["performanceIndicators"] == ["Metas"]
