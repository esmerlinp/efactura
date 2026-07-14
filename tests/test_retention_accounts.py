"""Tests for tax retention account mapping — invoice flow vs expense flow.

Verifies that:
1. DOProvider.get_account_mapping() includes client-side retention keys
2. DOProvider.get_tax_labels() includes client-side descriptions
3. _find_account_by_usages correctly resolves retention accounts for invoice flow
"""

from unittest.mock import MagicMock, patch
import sys
import pytest

# ── Mock modules that trigger heavy/heavy import chains (cryptography) ───────
_patch_crypto = patch.dict("sys.modules", {"cryptography": MagicMock(), "cryptography.fernet": MagicMock()})
_patch_crypto.start()


# ── DOProvider account mapping tests ───────────────────────────────────────

class TestDOProviderAccountMapping:
    """Verify the DO provider exposes separate account mappings for
    supplier-side (expense flow) and client-side (invoice flow) retentions."""

    @pytest.fixture(autouse=True)
    def setup_provider(self):
        from app.countries.do.provider import DOProvider
        self.provider = DOProvider()

    def test_supplier_side_retention_keys_unchanged(self):
        """Expense flow: vat_withholding → itbis_retenido (pasivo), unchanged."""
        mapping = self.provider.get_account_mapping()
        assert mapping["vat_withholding"] == "itbis_retenido"
        assert mapping["income_tax_withholding"] == "isr_retenido"

    def test_client_side_retention_keys_map_to_asset_accounts(self):
        """Invoice flow: vat_withholding_client → retenciones_a_favor (activo)."""
        mapping = self.provider.get_account_mapping()
        assert "vat_withholding_client" in mapping, (
            "Missing vat_withholding_client key — required for invoice retention accounting"
        )
        assert mapping["vat_withholding_client"] == "retenciones_a_favor", (
            "vat_withholding_client must map to retenciones_a_favor (activo, not pasivo)"
        )

    def test_client_side_isr_retention_maps_to_asset(self):
        """ISR retention from clients should also use asset accounts."""
        mapping = self.provider.get_account_mapping()
        assert "income_tax_withholding_client" in mapping
        assert mapping["income_tax_withholding_client"] == "retenciones_a_favor"

    def test_vat_payable_and_credit_keys_present(self):
        """Sanity check that existing keys are not broken."""
        mapping = self.provider.get_account_mapping()
        assert mapping["vat_payable"] == "itbis_pagar"
        assert mapping["vat_credit"] == "itbis_credito"


class TestDOProviderTaxLabels:
    """Verify tax labels distinguish client-side vs supplier-side retentions."""

    @pytest.fixture(autouse=True)
    def setup_provider(self):
        from app.countries.do.provider import DOProvider
        self.provider = DOProvider()

    def test_client_side_itbis_label_present(self):
        labels = self.provider.get_tax_labels()
        assert "vat_withholding_client" in labels, (
            "Missing vat_withholding_client label — needed for readable accounting descriptions"
        )
        assert "retenido por cliente" in labels["vat_withholding_client"]

    def test_client_side_isr_label_present(self):
        labels = self.provider.get_tax_labels()
        assert "income_tax_withholding_client" in labels
        assert "retenido por cliente" in labels["income_tax_withholding_client"]

    def test_supplier_side_labels_unchanged(self):
        labels = self.provider.get_tax_labels()
        assert labels["vat_withholding"] == "ITBIS retenido"
        assert labels["income_tax_withholding"] == "ISR retenido"

    def test_vat_invoice_label_unchanged(self):
        labels = self.provider.get_tax_labels()
        assert labels["vat_invoice"] == "ITBIS factura"
        assert labels["vat_credit"] == "ITBIS crédito fiscal"


# ── Account resolution by usage tests ──────────────────────────────────────

class TestAccountResolutionForRetention:
    """Verify _find_account_by_usages resolves the correct account
    for the invoice retention flow using asset-oriented usage tags."""

    @pytest.fixture(autouse=True)
    def setup_functions(self):
        from app.services.accounting_service import _find_account_by_usage, _find_account_by_usages
        self._find_account_by_usage = _find_account_by_usage
        self._find_account_by_usages = _find_account_by_usages

    def _account(self, acc_id, usage):
        return {"id": acc_id, "code": "X", "name": usage, "usage": usage}

    def test_finds_retenciones_a_favor_when_present(self):
        """When retenciones_a_favor exists, it should be found first."""
        accounts = [
            self._account("a1", "itbis_retenido"),
            self._account("a2", "retenciones_a_favor"),
            self._account("a3", "impuesto_a_favor"),
        ]
        result = self._find_account_by_usages(accounts, [
            "retenciones_a_favor",
            "impuesto_a_favor",
        ])
        assert result is not None
        assert result["id"] == "a2"
        assert result["usage"] == "retenciones_a_favor"

    def test_falls_back_to_impuesto_a_favor(self):
        """When retenciones_a_favor is absent, fall back to impuesto_a_favor."""
        accounts = [
            self._account("a1", "itbis_retenido"),
            self._account("a3", "impuesto_a_favor"),
        ]
        result = self._find_account_by_usages(accounts, [
            "retenciones_a_favor",
            "impuesto_a_favor",
        ])
        assert result is not None
        assert result["id"] == "a3"
        assert result["usage"] == "impuesto_a_favor"

    def test_returns_none_when_no_match(self):
        """When none of the target usages exist, return None."""
        accounts = [
            self._account("a1", "itbis_retenido"),
            self._account("a2", "isr_retenido"),
        ]
        result = self._find_account_by_usages(accounts, [
            "retenciones_a_favor",
            "impuesto_a_favor",
        ])
        assert result is None

    def test_prefers_first_match_in_order(self):
        """The first matching usage in the list takes priority."""
        accounts = [
            self._account("a1", "impuesto_a_favor"),
            self._account("a2", "retenciones_a_favor"),
        ]
        # Search order: retenciones_a_favor first → should return a2
        result = self._find_account_by_usages(accounts, [
            "retenciones_a_favor",
            "impuesto_a_favor",
        ])
        assert result["id"] == "a2"

    def test_empty_usages_returns_none(self):
        """Empty usages list should return None gracefully."""
        accounts = [self._account("a1", "retenciones_a_favor")]
        result = self._find_account_by_usages(accounts, [])
        assert result is None

    def test_empty_accounts_returns_none(self):
        """Empty accounts list should return None gracefully."""
        result = self._find_account_by_usages([], ["retenciones_a_favor"])
        assert result is None


# ── Integration: account mapping → usage resolution ────────────────────────

class TestInvoiceRetentionAccountIntegration:
    """Verify the full chain: provider mapping → _find_account_by_usages → correct account."""

    def test_resolves_client_side_itbis_to_asset_account(self):
        """Using the DO provider mapping, the invoice flow should resolve
        retenciones_a_favor (activo) over itbis_retenido (pasivo)."""
        from app.countries.do.provider import DOProvider
        from app.services.accounting_service import _find_account_by_usages

        provider = DOProvider()
        mapping = provider.get_account_mapping()

        # Simulate chart of accounts with both pasivo and activo retention accounts
        accounts = [
            {"id": "pasivo-itbis", "code": "2.1.5.01.04", "name": "ITBIS retenido a proveedores",
             "group": "pasivos", "type": "movimiento", "nature": "acreedora",
             "usage": "itbis_retenido"},
            {"id": "activo-itbis", "code": "1.1.6.01.01", "name": "Retención de ITBIS a favor",
             "group": "activos", "type": "movimiento", "nature": "deudora",
             "usage": "retenciones_a_favor"},
        ]

        usages = [
            mapping.get("vat_withholding_client", "retenciones_a_favor"),
            "retenciones_a_favor",
            "impuesto_a_favor",
        ]

        result = _find_account_by_usages(accounts, usages)

        assert result is not None, "Should resolve a retention account"
        assert result["id"] == "activo-itbis", (
            "Expected activo account (retenciones_a_favor), got pasivo"
        )
        assert result["group"] == "activos"
        assert result["nature"] == "deudora"

    def test_resolves_client_side_isr_to_asset_account(self):
        """ISR retention in invoice flow should also resolve to activo."""
        from app.countries.do.provider import DOProvider
        from app.services.accounting_service import _find_account_by_usages

        provider = DOProvider()
        mapping = provider.get_account_mapping()

        accounts = [
            {"id": "pasivo-isr", "code": "2.1.5.01.05", "name": "ISR retenido a proveedores",
             "group": "pasivos", "type": "movimiento", "nature": "acreedora",
             "usage": "isr_retenido"},
            {"id": "activo-isr", "code": "1.1.6.01.02", "name": "Retención de ISR a favor",
             "group": "activos", "type": "movimiento", "nature": "deudora",
             "usage": "retenciones_a_favor"},
        ]

        usages = [
            mapping.get("income_tax_withholding_client", "retenciones_a_favor"),
            "retenciones_a_favor",
            "impuesto_a_favor",
        ]

        result = _find_account_by_usages(accounts, usages)

        assert result is not None
        assert result["id"] == "activo-isr"

    def test_falls_back_to_impuesto_a_favor_when_no_retenciones(self):
        """When only impuesto_a_favor exists (older chart), it should be used."""
        from app.countries.do.provider import DOProvider
        from app.services.accounting_service import _find_account_by_usages

        provider = DOProvider()
        mapping = provider.get_account_mapping()

        accounts = [
            {"id": "pasivo-itbis", "code": "2.1.5.01.04", "name": "ITBIS retenido",
             "group": "pasivos", "type": "movimiento", "nature": "acreedora",
             "usage": "itbis_retenido"},
            {"id": "impuesto-favor", "code": "1.1.5.01.01", "name": "ITBIS a favor",
             "group": "activos", "type": "movimiento", "nature": "deudora",
             "usage": "impuesto_a_favor"},
        ]

        usages = [
            mapping.get("vat_withholding_client", "retenciones_a_favor"),
            "retenciones_a_favor",
            "impuesto_a_favor",
        ]

        result = _find_account_by_usages(accounts, usages)

        assert result is not None
        assert result["id"] == "impuesto-favor", (
            "Should fall back to impuesto_a_favor when retenciones_a_favor is absent"
        )
