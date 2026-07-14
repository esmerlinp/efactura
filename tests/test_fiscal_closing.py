"""Tests for FiscalClosingService — year filtering and double-close prevention.

These tests mock DatabaseService to isolate the fiscal year filtering logic
and verify that generate_closing_preview correctly restricts entries to the target year.
"""

from unittest.mock import MagicMock, patch
import sys
import pytest

# ── Mock modules to avoid architecture-dependent import chains ──────────────
_patch_crypto = patch.dict("sys.modules", {"cryptography": MagicMock(), "cryptography.fernet": MagicMock()})
_patch_crypto.start()


# ── Mock helpers ────────────────────────────────────────────────────────────

def _make_entry(entry_id, date, entry_type="standard", lines=None, status="active", concept="", **kwargs):
    result = {
        "id": entry_id,
        "date": date,
        "entryType": entry_type,
        "status": status,
        "concept": concept,
        "lines": lines or [],
    }
    result.update(kwargs)
    return result


def _make_line(account_id, debit=0.0, credit=0.0):
    return {"accountId": account_id, "debit": debit, "credit": credit}


def _make_account(acc_id, code, name, group, acc_type="movimiento", nature="deudora", usage=None):
    return {"id": acc_id, "code": code, "name": name, "group": group, "type": acc_type, "nature": nature, "usage": usage}


# ── Common test accounts ────────────────────────────────────────────────────

INCOME_ACC = _make_account("acc-ventas", "4.1.01", "Ventas", "ingresos", nature="acreedora", usage="ventas")
COST_ACC   = _make_account("acc-costos", "5.1.1.01", "Costo de ventas", "costos", nature="deudora", usage="costo_ventas")
EXPENSE_ACC = _make_account("acc-gastos", "6.2.2.20", "Gastos generales", "gastos", nature="deudora", usage="gastos")
RETAINED_ACC = _make_account("acc-res", "3.3.03", "Ganancias acumuladas", "patrimonio", nature="acreedora")

TEST_ACCOUNTS = [INCOME_ACC, COST_ACC, EXPENSE_ACC, RETAINED_ACC]


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db():
    """Return a mock DatabaseService class with configurable chart-of-accounts and entries.
    DatabaseService is imported both lazily (in fiscal_closing_service) and at module
    level (in accounting_service for _accounting_entry_exists), so we patch both."""
    with patch("app.services.db_service.DatabaseService") as mock1, \
         patch("app.services.accounting_service.DatabaseService") as mock2:
        # Share state: both mocks should return the same results
        mock1.get_chart_of_accounts = mock2.get_chart_of_accounts = MagicMock()
        mock1.get_accounting_entries = mock2.get_accounting_entries = MagicMock()
        mock1.save_account = mock2.save_account = MagicMock()
        mock1.save_entry_type = mock2.save_entry_type = MagicMock()
        mock1.get_entry_types = mock2.get_entry_types = MagicMock(return_value=[])
        mock2.get_entry_types = mock2.get_entry_types
        yield mock1


@pytest.fixture
def fiscal_closing():
    """Import FiscalClosingService with Firebase + AccountingService + FiscalPeriodService mocked.
    These patches persist for the test duration via yield."""
    with patch("app.services.db_service.db_firestore", MagicMock()), \
         patch("app.services.accounting_service.AccountingService", MagicMock()), \
         patch("app.services.fiscal_period_service.FiscalPeriodService", MagicMock()):
        from app.services.fiscal_closing_service import FiscalClosingService
        yield FiscalClosingService


# ── Year filtering tests ────────────────────────────────────────────────────

class TestYearFiltering:
    """Verify generate_closing_preview only includes entries from the target year."""

    def test_filters_out_previous_year_entries(self, mock_db, fiscal_closing):
        """Entries from 2024 should NOT appear in 2025 closing preview."""
        mock_db.get_chart_of_accounts.return_value = TEST_ACCOUNTS
        mock_db.get_accounting_entries.return_value = [
            # 2024 entry: credit income account by 100,000
            _make_entry("e-2024", "2024-06-15", lines=[
                _make_line("acc-ventas", credit=100000),
            ]),
            # 2025 entry: credit income account by 50,000
            _make_entry("e-2025", "2025-03-10", lines=[
                _make_line("acc-ventas", credit=50000),
            ]),
        ]

        preview = fiscal_closing.generate_closing_preview("uid", 2025)

        # Only 2025 entries should be reflected
        # Income accounts with naturaleza acreedora: balance = debit - credit = -50000
        # net_income = -balance (since acreedora balance is negated in net_income calc)
        # Actually let's trace: balance = 0 - 50000 = -50000
        # nature = acreedora -> net_income += balance = -50000
        # Then retained_line: if net_income < 0 -> debit abs(net_income), credit 0
        assert preview["net_income"] == -50000.0
        assert preview["total_income_accounts"] == 1
        assert preview["total_expense_accounts"] == 2  # COST_ACC (5.x) + EXPENSE_ACC (6.x) counted even with zero activity
        assert len(preview["income_lines"]) == 1
        # acreedora income account: closing entry debits the balance
        assert preview["income_lines"][0]["debit"] == 50000.0
        assert preview["income_lines"][0]["credit"] == 0.0

    def test_filters_out_future_year_entries(self, mock_db, fiscal_closing):
        """Entries from 2026 should NOT appear in 2025 closing preview."""
        mock_db.get_chart_of_accounts.return_value = TEST_ACCOUNTS
        mock_db.get_accounting_entries.return_value = [
            _make_entry("e-2025", "2025-08-20", lines=[
                _make_line("acc-ventas", credit=30000),
            ]),
            _make_entry("e-2026", "2026-01-10", lines=[
                _make_line("acc-ventas", credit=70000),
            ]),
        ]

        preview = fiscal_closing.generate_closing_preview("uid", 2025)

        assert preview["net_income"] == -30000.0
        assert len(preview["income_lines"]) == 1

    def test_includes_closing_entries_for_target_year(self, mock_db, fiscal_closing):
        """Closing entries with dates outside the year range should still be included."""
        mock_db.get_chart_of_accounts.return_value = TEST_ACCOUNTS
        mock_db.get_accounting_entries.return_value = [
            _make_entry("e-2025", "2025-05-01", lines=[
                _make_line("acc-ventas", credit=40000),
            ]),
            _make_entry("ce-2025", "2025-12-31", entry_type="closing",
                        concept="Asiento de cierre del ejercicio fiscal 2025",
                        lines=[_make_line("acc-ventas", debit=40000)]),
        ]

        preview = fiscal_closing.generate_closing_preview("uid", 2025)

        # The closing entry zeros out the income account balance
        # income balance: credit 40000 - debit 40000 = 0
        assert preview["net_income"] == 0.0

    def test_closing_entry_from_wrong_year_excluded(self, mock_db, fiscal_closing):
        """A closing entry for 2024 should not be included in 2025 preview."""
        mock_db.get_chart_of_accounts.return_value = TEST_ACCOUNTS
        mock_db.get_accounting_entries.return_value = [
            _make_entry("e-2025", "2025-07-01", lines=[
                _make_line("acc-ventas", credit=25000),
            ]),
            _make_entry("ce-2024", "2024-12-31", entry_type="closing",
                        concept="Asiento de cierre del ejercicio fiscal 2024",
                        lines=[_make_line("acc-ventas", debit=80000)]),
        ]

        preview = fiscal_closing.generate_closing_preview("uid", 2025)

        # Only the 2025 entry: income balance = -25000
        assert preview["net_income"] == -25000.0

    def test_includes_both_income_and_expense(self, mock_db, fiscal_closing):
        """Verify expense accounts are also computed correctly within the year."""
        mock_db.get_chart_of_accounts.return_value = TEST_ACCOUNTS
        mock_db.get_accounting_entries.return_value = [
            _make_entry("e-1", "2025-03-01", lines=[
                _make_line("acc-ventas", credit=100000),
                _make_line("acc-costos", debit=40000),
                _make_line("acc-gastos", debit=10000),
            ]),
        ]

        preview = fiscal_closing.generate_closing_preview("uid", 2025)

        # Income (acreedora): balance = -100000, net_income += -100000
        # Costos (deudora): balance = 40000, net_income -= 40000
        # Gastos (deudora): balance = 10000, net_income -= 10000
        # Total: -100000 - 40000 - 10000 = -150000
        assert preview["net_income"] == -150000.0
        assert preview["total_income_accounts"] == 1
        assert preview["total_expense_accounts"] == 2

    def test_skips_voided_entries(self, mock_db, fiscal_closing):
        """Voided entries in the year range should be ignored."""
        mock_db.get_chart_of_accounts.return_value = TEST_ACCOUNTS
        mock_db.get_accounting_entries.return_value = [
            _make_entry("e-void", "2025-04-01", status="voided", lines=[
                _make_line("acc-ventas", credit=99999),
            ]),
            _make_entry("e-valid", "2025-04-01", lines=[
                _make_line("acc-ventas", credit=30000),
            ]),
        ]

        preview = fiscal_closing.generate_closing_preview("uid", 2025)

        assert preview["net_income"] == -30000.0

    def test_no_entries_for_year(self, mock_db, fiscal_closing):
        """When no entries exist for the target year, all balances are zero."""
        mock_db.get_chart_of_accounts.return_value = TEST_ACCOUNTS
        mock_db.get_accounting_entries.return_value = [
            _make_entry("e-2024", "2024-11-01", lines=[
                _make_line("acc-ventas", credit=50000),
            ]),
        ]

        preview = fiscal_closing.generate_closing_preview("uid", 2025)

        assert preview["net_income"] == 0.0
        assert len(preview["income_lines"]) == 0
        assert len(preview["expense_lines"]) == 0

    def test_boundary_includes_jan_1(self, mock_db, fiscal_closing):
        """Entry on January 1 should be included."""
        mock_db.get_chart_of_accounts.return_value = TEST_ACCOUNTS
        mock_db.get_accounting_entries.return_value = [
            _make_entry("e-jan", "2025-01-01", lines=[
                _make_line("acc-ventas", credit=10000),
            ]),
        ]

        preview = fiscal_closing.generate_closing_preview("uid", 2025)
        assert preview["net_income"] == -10000.0

    def test_boundary_includes_dec_31(self, mock_db, fiscal_closing):
        """Entry on December 31 should be included."""
        mock_db.get_chart_of_accounts.return_value = TEST_ACCOUNTS
        mock_db.get_accounting_entries.return_value = [
            _make_entry("e-dec", "2025-12-31", lines=[
                _make_line("acc-ventas", credit=10000),
            ]),
        ]

        preview = fiscal_closing.generate_closing_preview("uid", 2025)
        assert preview["net_income"] == -10000.0


# ── Double-close prevention tests ───────────────────────────────────────────

class TestDoubleClosePrevention:
    """Verify execute_year_close prevents closing an already-closed year."""

    def test_returns_already_closed_when_entry_exists(self, mock_db, fiscal_closing):
        """If a closing entry already exists for the year, return already_closed status."""
        mock_db.get_chart_of_accounts.return_value = TEST_ACCOUNTS
        # Simulate that an existing closing entry is found
        mock_db.get_accounting_entries.return_value = [
            _make_entry("e-2025", "2025-06-01", lines=[
                _make_line("acc-ventas", credit=20000),
            ]),
            # This entry acts as the "already exists" check
            _make_entry("ce-existing", "2025-12-31", entry_type="closing",
                        referenceType="closing", referenceId="year_2025",
                        concept="Asiento de cierre del ejercicio fiscal 2025"),
        ]

        result = fiscal_closing.execute_year_close("uid", 2025)
        assert result["status"] == "already_closed"
        assert "ya tiene un asiento de cierre" in result["message"]

    def test_returns_no_entries_when_empty_year(self, mock_db, fiscal_closing):
        """If no income/expense entries exist for the year, return no_entries."""
        mock_db.get_chart_of_accounts.return_value = TEST_ACCOUNTS
        mock_db.get_accounting_entries.return_value = []

        result = fiscal_closing.execute_year_close("uid", 2025)
        assert result["status"] == "no_entries"

    def test_duplicate_closing_prevented_via_reference_id(self, mock_db, fiscal_closing):
        """When a closing entry with referenceId="year_2025" already exists,
        execute_year_close must return already_closed."""
        mock_db.get_chart_of_accounts.return_value = TEST_ACCOUNTS
        # Simulate: year already has a closing entry in the ledger
        mock_db.get_accounting_entries.return_value = [
            _make_entry("e-2025", "2025-07-01", lines=[
                _make_line("acc-ventas", credit=15000),
            ]),
            # Existing closing entry — should trigger already_closed
            _make_entry("ce-2025", "2025-12-31",
                        entry_type="closing",
                        referenceType="closing",
                        referenceId="year_2025",
                        concept="Asiento de cierre del ejercicio fiscal 2025"),
        ]

        result = fiscal_closing.execute_year_close("uid", 2025)
        assert result["status"] == "already_closed"


# ── Retained earnings detection tests ───────────────────────────────────────

class TestRetainedEarnings:
    """Verify the retained earnings account is correctly identified."""

    def test_finds_account_by_usage(self, mock_db, fiscal_closing):
        account_with_usage = _make_account("acc-res-usage", "3.3.04", "Resultados acumulados",
                                            "patrimonio", nature="acreedora",
                                            usage="resultados_acumulados")
        mock_db.get_chart_of_accounts.return_value = [account_with_usage]
        mock_db.get_accounting_entries.return_value = []

        preview = fiscal_closing.generate_closing_preview("uid", 2025)
        assert preview["retained_earnings_account"] == "Resultados acumulados"

    def test_finds_account_by_name_substring(self, mock_db, fiscal_closing):
        account_by_name = _make_account("acc-res-name", "3.3.03", "Resultados acumulados",
                                         "patrimonio", nature="acreedora")
        mock_db.get_chart_of_accounts.return_value = [account_by_name]
        mock_db.get_accounting_entries.return_value = []

        preview = fiscal_closing.generate_closing_preview("uid", 2025)
        assert preview["retained_earnings_account"] == "Resultados acumulados"
