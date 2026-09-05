"""Tests para el historial de acciones del empleado.

Cubre: log_employee_action (escribe en hr_audit_log con entity/entityId),
_action_category y build_employee_timeline (fusión cronológica de audit log,
transiciones de estado y acciones masivas).
"""

from unittest.mock import MagicMock, patch

from app.web.rrhh.employees import (
    ACTION_LABELS,
    _action_category,
    build_employee_timeline,
)

COMPANY = "company-test"


# ═══════════════════════════════════════════════════════════════════════════
# _action_category
# ═══════════════════════════════════════════════════════════════════════════

def test_action_category_mapping():
    assert _action_category("work_certificate_generated", {}) == "carta"
    assert _action_category("overtime_created", {}) == "hora_extra"
    assert _action_category("overtime_approved", {}) == "hora_extra"
    assert _action_category("recurring_movement_created", {"movementType": "earning"}) == "recurrente_ingreso"
    assert _action_category("recurring_movement_created", {"movementType": "deduction"}) == "recurrente_deduccion"
    assert _action_category("payroll_paid", {}) == "pago"
    assert _action_category("evaluation_created", {}) == "evaluacion"
    assert _action_category("training_created", {}) == "capacitacion"
    assert _action_category("vacation_approved", {}) == "vacaciones"
    assert _action_category("leave_approved", {}) == "licencia"
    assert _action_category("tool_assigned", {}) == "herramienta"
    assert _action_category("tool_returned", {}) == "herramienta"
    assert _action_category("tool_maintenance", {}) == "herramienta"
    assert _action_category("employee_marked_inactive", {}) == "baja"
    assert _action_category("rehire", {}) == "alta"
    assert _action_category("update", {}) == "empleado"


# ═══════════════════════════════════════════════════════════════════════════
# build_employee_timeline
# ═══════════════════════════════════════════════════════════════════════════

def test_timeline_merges_and_sorts_descending():
    audit = [
        {"timestamp": "2026-01-03T10:00:00+00:00", "action": "payroll_paid",
         "changes": {"netSalary": 5000}, "userId": "u@x.com", "comment": "Pago"},
        {"timestamp": "2026-01-01T10:00:00+00:00", "action": "overtime_created",
         "changes": {"hours": 2}, "userId": "u@x.com", "comment": "HE"},
    ]
    status_events = [
        {"timestamp": "2026-01-02T10:00:00+00:00", "trigger": "vacation_start",
         "fromStatus": "activo", "toStatus": "vacaciones", "actor": "sistema", "reason": ""},
    ]
    mass_actions = [
        {"createdAt": "2026-01-04T10:00:00+00:00", "id": "ma1", "actionType": "salary_change",
         "actionTypeLabel": "Cambio Salarial", "createdBy": "u@x.com",
         "result": {"changes": {"before": {"baseSalary": 100}, "after": {"baseSalary": 200}}}},
    ]

    timeline = build_employee_timeline(audit, status_events, mass_actions)

    # 4 ítems (se filtran los employee_status_* del audit, aquí no hay)
    assert len(timeline) == 4
    # Ordenado desc por ts
    assert [i["ts"] for i in timeline] == [
        "2026-01-04T10:00:00+00:00",
        "2026-01-03T10:00:00+00:00",
        "2026-01-02T10:00:00+00:00",
        "2026-01-01T10:00:00+00:00",
    ]
    kinds = {i["kind"] for i in timeline}
    assert kinds == {"audit", "status", "mass"}


def test_timeline_filters_employee_status_events_from_audit():
    audit = [
        {"timestamp": "2026-01-01T10:00:00+00:00", "action": "employee_status_vacaciones",
         "changes": {}, "userId": "sistema", "comment": ""},
        {"timestamp": "2026-01-02T10:00:00+00:00", "action": "evaluation_created",
         "changes": {}, "userId": "u@x.com", "comment": ""},
    ]
    timeline = build_employee_timeline(audit, [], [])
    assert len(timeline) == 1
    assert timeline[0]["action"] == "evaluation_created"


def test_timeline_status_item_labels():
    status_events = [
        {"timestamp": "2026-01-01T10:00:00+00:00", "trigger": "leave_start",
         "fromStatus": "activo", "toStatus": "licencia", "actor": "sistema", "reason": "r"},
    ]
    timeline = build_employee_timeline([], status_events, [])
    assert timeline[0]["category"] == "licencia"
    assert timeline[0]["label"] == "Licencia"
    assert "activo" in timeline[0]["comment"]


def test_timeline_empty():
    assert build_employee_timeline([], [], []) == []


# ═══════════════════════════════════════════════════════════════════════════
# _detail_text / _format_ts
# ═══════════════════════════════════════════════════════════════════════════

def test_detail_text_audit_single_line():
    from app.web.rrhh.employees import _detail_text
    item = {"kind": "audit", "action": "payroll_paid",
            "comment": "Nómina pagada — 2026-01", "changes": {"netSalary": 5000}}
    assert _detail_text(item) == "Nómina pagada — 2026-01 · Neto RD$ 5,000.00"


def test_detail_text_mass_salary():
    from app.web.rrhh.employees import _detail_text
    item = {"kind": "mass", "action": "salary_change",
            "changes": {"before": {"baseSalary": 100}, "after": {"baseSalary": 200}}}
    assert "Salario RD$ 100 → RD$ 200" in _detail_text(item)


def test_format_ts():
    from app.web.rrhh.employees import _format_ts
    d, t = _format_ts("2026-01-03T10:30:00+00:00")
    assert d == "2026-01-03"
    assert len(t) == 5 and t[2] == ":"


def test_timeline_items_have_date_time_detail():
    audit = [{"timestamp": "2026-01-03T10:30:00+00:00", "action": "payroll_paid",
              "changes": {"netSalary": 5000}, "userId": "u@x.com", "comment": "Pago"}]
    timeline = build_employee_timeline(audit, [], [])
    assert timeline[0]["_date"] == "2026-01-03"
    assert len(timeline[0]["_time"]) == 5
    assert "Neto" in timeline[0]["detail"]


# ═══════════════════════════════════════════════════════════════════════════
# _filter_timeline
# ═══════════════════════════════════════════════════════════════════════════

def _tl_item(category, actor, date):
    return {"category": category, "actor": actor, "_date": date}


def test_filter_timeline_by_category():
    from app.web.rrhh.employees import _filter_timeline
    items = [_tl_item("pago", "a@x.com", "2026-01-01"),
             _tl_item("vacaciones", "b@x.com", "2026-01-02")]
    out = _filter_timeline(items, category="pago")
    assert len(out) == 1 and out[0]["category"] == "pago"


def test_filter_timeline_by_actor_and_date():
    from app.web.rrhh.employees import _filter_timeline
    items = [_tl_item("pago", "a@x.com", "2026-01-01"),
             _tl_item("pago", "b@x.com", "2026-01-05"),
             _tl_item("pago", "a@x.com", "2026-02-10")]
    out = _filter_timeline(items, actor="a@x.com", date_from="2026-01-01", date_to="2026-01-31")
    assert len(out) == 1 and out[0]["_date"] == "2026-01-01"


def test_filter_timeline_no_filters():
    from app.web.rrhh.employees import _filter_timeline
    items = [_tl_item("pago", "a@x.com", "2026-01-01")]
    assert _filter_timeline(items) == items


def test_action_labels_present_for_all_events():
    for key in ("work_certificate_generated", "overtime_created", "payroll_paid",
                "evaluation_created", "training_created", "vacation_approved",
                "leave_approved", "tool_assigned", "tool_returned",
                "tool_maintenance"):
        assert key in ACTION_LABELS


# ═══════════════════════════════════════════════════════════════════════════
# log_employee_action
# ═══════════════════════════════════════════════════════════════════════════

def test_log_employee_action_writes_audit_entry():
    import app.services.payroll_audit_service as svc

    fake_doc = MagicMock()
    fake_coll = MagicMock()
    fake_coll.document.return_value = fake_doc
    fake_db = MagicMock()
    fake_db.collection.return_value = fake_coll

    with patch.object(svc, "firebase_initialized", True), \
         patch.object(svc, "db_firestore", fake_db), \
         patch.object(svc, "_get_request_context", return_value=("", "", {})), \
         patch("app.services.audit_service.AuditService.log_from_request", return_value=None):
        svc.log_employee_action(
            COMPANY, "emp-1", "evaluation_created",
            comment="Evaluación", changes={"score": 5},
            user_email="u@x.com", sandbox=True,
        )

    # Colección sandbox hr_audit_log
    assert fake_db.collection.called
    coll_path = fake_db.collection.call_args[0][0]
    assert coll_path == f"companies/{COMPANY}/sandbox_hr_audit_log"

    entry = fake_doc.set.call_args[0][0]
    assert entry["entity"] == "employee"
    assert entry["entityId"] == "emp-1"
    assert entry["action"] == "evaluation_created"
    assert entry["comment"] == "Evaluación"


# ═══════════════════════════════════════════════════════════════════════════
# get_audit_log — sin índice compuesto en Firestore
# ═══════════════════════════════════════════════════════════════════════════

class _FakeQuery:
    def __init__(self, docs):
        self._docs = docs
        self.ordered = False
        self.where_calls = 0

    def where(self, *a, **k):
        self.where_calls += 1
        return self

    def order_by(self, *a, **k):
        self.ordered = True
        return self

    def limit(self, *a, **k):
        return self

    def get(self):
        return self._docs


def test_get_audit_log_skips_order_by_when_entity_and_entity_id():
    """Dos filtros de igualdad no deben usar order_by (requeriría índice compuesto)."""
    import app.services.payroll_audit_service as svc

    q = _FakeQuery([])
    fake_coll = MagicMock()
    fake_coll.where.return_value = q
    fake_db = MagicMock()
    fake_db.collection.return_value = fake_coll

    with patch.object(svc, "firebase_initialized", True), \
         patch.object(svc, "db_firestore", fake_db):
        result = svc.get_audit_log(COMPANY, entity="employee", entity_id="emp-1", limit=10)

    assert q.ordered is False
    assert fake_coll.where.call_count == 1
    assert q.where_calls == 1
    assert result == []


def test_get_audit_log_orders_when_entity_only():
    """El caso general (ej. vista de auditoría) mantiene order_by."""
    import app.services.payroll_audit_service as svc

    q = _FakeQuery([])
    fake_coll = MagicMock()
    fake_coll.where.return_value = q
    fake_db = MagicMock()
    fake_db.collection.return_value = fake_coll

    with patch.object(svc, "firebase_initialized", True), \
         patch.object(svc, "db_firestore", fake_db):
        svc.get_audit_log(COMPANY, entity="employee", limit=10)

    assert q.ordered is True


# ═══════════════════════════════════════════════════════════════════════════
# _timeline_detail_url
# ═══════════════════════════════════════════════════════════════════════════

def test_timeline_detail_url_mapping():
    from app.web.rrhh import employees as emp_mod

    cases = [
        ({"kind": "audit", "action": "payroll_paid", "changes": {"periodId": "p1"}},
         "web_rrhh.payroll_view", {"period_id": "p1"}),
        ({"kind": "audit", "action": "overtime_created", "changes": {"overtimeId": "o1"}},
         "web_rrhh.overtime_view", {"record_id": "o1"}),
        ({"kind": "audit", "action": "recurring_movement_created", "changes": {"movementId": "m1"}},
         "web_rrhh.recurring_edit", {"movement_id": "m1"}),
        ({"kind": "audit", "action": "tool_assigned", "changes": {"herramientaId": "h1"}},
         "web_herramientas.detail_herramienta", {"herramienta_id": "h1"}),
        ({"kind": "audit", "action": "work_certificate_generated", "changes": {}},
         "web_rrhh.employee_certificate", {"employee_id": "emp1"}),
        ({"kind": "audit", "action": "evaluation_created", "changes": {}},
         "web_rrhh.evaluation_list", {}),
        ({"kind": "audit", "action": "training_created", "changes": {}},
         "web_rrhh.training_list", {}),
        ({"kind": "mass", "action": "salary_change", "mass_action_id": "ma1", "changes": {}},
         "web_rrhh.mass_action_detail", {"action_id": "ma1"}),
        ({"kind": "status", "action": "vacation_start", "changes": {}},
         "web_rrhh.vacation_list", {}),
        ({"kind": "status", "action": "leave_start", "changes": {}},
         "web_rrhh.leave_list", {}),
        ({"kind": "audit", "action": "update", "changes": {}},
         "web_rrhh.employee_view", {"employee_id": "emp1"}),
        ({"kind": "audit", "action": "liquidacion_calculada", "changes": {}},
         "web_rrhh.employee_liquidaciones_list", {"employee_id": "emp1"}),
        ({"kind": "audit", "action": "unknown_action", "changes": {}}, None, None),
        ({"kind": "audit", "action": "overtime_created", "changes": {}}, None, None),
    ]

    with patch.object(emp_mod, "url_for", return_value="/x") as mock_uf:
        for item, ep, kw in cases:
            mock_uf.reset_mock()
            result = emp_mod._timeline_detail_url(item, "emp1")
            if ep is None:
                assert result is None
                mock_uf.assert_not_called()
            else:
                assert result == "/x"
                mock_uf.assert_called_once()
                assert mock_uf.call_args[0][0] == ep
                for k, v in kw.items():
                    assert mock_uf.call_args[1].get(k) == v
