import base64
import json

from app.services.audit_service import AuditService


def test_cursor_contains_timestamp_and_document_id():
    cursor = base64.urlsafe_b64encode(json.dumps({
        "timestamp": "2026-11-02T10:00:00",
        "id": "log-1",
    }).encode()).decode()
    decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    assert decoded == {"timestamp": "2026-11-02T10:00:00", "id": "log-1"}


def test_export_service_uses_bounded_page_size(monkeypatch):
    calls = []

    def fake_page(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {"logs": [{"id": "a", "timestamp": "2026-11-02T10:00:00"}], "next_cursor": "next", "has_more": True}
        return {"logs": [{"id": "b", "timestamp": "2026-11-02T09:00:00"}], "next_cursor": None, "has_more": False}

    monkeypatch.setattr(AuditService, "_query_logs_page", classmethod(lambda cls, *args, **kwargs: fake_page(*args, **kwargs)))
    rows = AuditService.export_to_csv_rows("owner", company_id="company", use_cache=False)
    assert [row["id"] for row in rows] == ["a", "b"]
    assert all(call["per_page"] == 500 for call in calls)
