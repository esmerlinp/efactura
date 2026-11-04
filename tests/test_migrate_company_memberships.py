from unittest.mock import MagicMock, patch

from scripts.migrate_company_memberships import migrate


def _company_doc(company_id, owner_uid):
    doc = MagicMock()
    doc.id = company_id
    doc.exists = True
    doc.to_dict.return_value = {"id": company_id, "owner_uid": owner_uid}
    return doc


def test_migration_dry_run_does_not_create_membership():
    with patch("scripts.migrate_company_memberships.firebase_initialized", True), \
         patch("scripts.migrate_company_memberships.db_firestore") as db, \
         patch("scripts.migrate_company_memberships.DatabaseService.get_membership", return_value=None), \
         patch("scripts.migrate_company_memberships.DatabaseService.create_membership") as create:
        db.collection.return_value.get.return_value = [_company_doc("company-a", "owner-a")]
        result = migrate(dry_run=True)

    assert result == {"scanned": 1, "created": 1, "skipped": 0, "invalid": 0}
    create.assert_not_called()


def test_migration_is_idempotent_for_active_membership():
    with patch("scripts.migrate_company_memberships.firebase_initialized", True), \
         patch("scripts.migrate_company_memberships.db_firestore") as db, \
         patch("scripts.migrate_company_memberships.DatabaseService.get_membership", return_value={"status": "active"}), \
         patch("scripts.migrate_company_memberships.DatabaseService.create_membership") as create:
        db.collection.return_value.get.return_value = [_company_doc("company-a", "owner-a")]
        result = migrate(dry_run=False)

    assert result == {"scanned": 1, "created": 0, "skipped": 1, "invalid": 0}
    create.assert_not_called()
