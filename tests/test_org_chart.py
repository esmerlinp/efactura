"""Tests para el organigrama por posición y su jerarquía.

Cubre: construcción del árbol `build_position_nodes` (mapeo empleado→puesto por
id y por nombre, empleados sin puesto, padres huérfanos y rotura de ciclos) y la
validación `_reports_to_is_valid` del catálogo de posiciones (auto-referencia y
ciclos).
"""

from app.web.rrhh.org_chart import build_position_nodes
from app.web.rrhh.positions import _reports_to_is_valid


def _emp(eid, name, position=None, position_id=None):
    return {"id": eid, "fullName": name, "position": position or "", "positionId": position_id or ""}


# ═══════════════════════════════════════════════════════════════════════════
# build_position_nodes
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildPositionNodes:
    def test_jerarquia_y_mapeo_por_id(self):
        positions = [
            {"id": "p1", "name": "Gerente General", "reportsTo": ""},
            {"id": "p2", "name": "Supervisor", "reportsTo": "p1"},
        ]
        employees = [
            _emp("e1", "Ana", position_id="p1"),
            _emp("e2", "Luis", position_id="p2"),
        ]
        roots = build_position_nodes(positions, employees)

        assert len(roots) == 1
        assert roots[0]["id"] == "p1"
        assert [e["id"] for e in roots[0]["employees"]] == ["e1"]
        assert len(roots[0]["children"]) == 1
        assert roots[0]["children"][0]["id"] == "p2"
        assert [e["id"] for e in roots[0]["children"][0]["employees"]] == ["e2"]

    def test_mapeo_por_nombre_legacy(self):
        positions = [{"id": "p1", "name": "Analista", "reportsTo": ""}]
        employees = [_emp("e1", "Ana", position="analista")]
        roots = build_position_nodes(positions, employees)
        assert [e["id"] for e in roots[0]["employees"]] == ["e1"]

    def test_empleados_sin_posicion(self):
        positions = [{"id": "p1", "name": "Analista", "reportsTo": ""}]
        employees = [
            _emp("e1", "Ana", position_id="p1"),
            _emp("e2", "Sin puesto"),
        ]
        roots = build_position_nodes(positions, employees)
        ids = {r["id"] for r in roots}
        assert ids == {"p1", "unassigned_positions_group"}
        unassigned = next(r for r in roots if r["id"] == "unassigned_positions_group")
        assert [e["id"] for e in unassigned["employees"]] == ["e2"]

    def test_padre_huerfano_es_raiz(self):
        positions = [
            {"id": "p1", "name": "Supervisor", "reportsTo": "inexistente"},
        ]
        employees = [_emp("e1", "Ana", position_id="p1")]
        roots = build_position_nodes(positions, employees)
        assert len(roots) == 1
        assert roots[0]["id"] == "p1"

    def test_rompe_ciclo(self):
        positions = [
            {"id": "p1", "name": "A", "reportsTo": "p2"},
            {"id": "p2", "name": "B", "reportsTo": "p1"},
        ]
        employees = []
        roots = build_position_nodes(positions, employees)

        # Sin caer en recursión: el ciclo se rompe y ambos nodos quedan en el árbol.
        seen = set()

        def walk(nodes):
            for n in nodes:
                seen.add(n["id"])
                walk(n["children"])

        walk(roots)
        assert seen == {"p1", "p2"}


# ═══════════════════════════════════════════════════════════════════════════
# _reports_to_is_valid
# ═══════════════════════════════════════════════════════════════════════════

class TestReportsToIsValid:
    def test_vacio_es_valido(self):
        assert _reports_to_is_valid([], "p1", "") is True

    def test_auto_referencia_invalida(self):
        positions = [{"id": "p1", "reportsTo": ""}]
        assert _reports_to_is_valid(positions, "p1", "p1") is False

    def test_padre_normal_valido(self):
        positions = [
            {"id": "p1", "reportsTo": ""},
            {"id": "p2", "reportsTo": ""},
        ]
        assert _reports_to_is_valid(positions, "p2", "p1") is True

    def test_ciclo_invalido(self):
        positions = [
            {"id": "p1", "reportsTo": "p2"},
            {"id": "p2", "reportsTo": "p3"},
            {"id": "p3", "reportsTo": ""},
        ]
        # p3 → p1 → p2 → p3: p3 no puede reportar a p1 porque p1 ya desciende de p3.
        assert _reports_to_is_valid(positions, "p3", "p1") is False
