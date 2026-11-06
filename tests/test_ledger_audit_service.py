from unittest.mock import patch

from app.services.ledger_audit_service import LedgerAuditService


def test_log_entry_creation_does_not_require_flask_context():
    entry = {"id": "entry-1", "number": "A-1", "lines": []}

    with patch.object(LedgerAuditService, "_get_db", side_effect=RuntimeError("db unavailable")), \
         patch("app.services.ledger_audit_service.logger.warning") as warning:
        LedgerAuditService.log_entry_creation(entry, "owner-1", company_id="company-1")

    warning.assert_called_once()
