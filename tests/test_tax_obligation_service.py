"""
test_tax_obligation_service.py — Pruebas del motor de obligaciones tributarias DGII/TSS.

Cubre: catálogo, detección de régimen y sus modalidades RST (RS-1/RS-2/RS-3/RS-4),
presets por régimen, vencimientos dinámicos (días laborables + feriados RD), auto-gate
por empleados (IR-3/TSS/DGT-3 vs IR-17), dedup de notificaciones, DGT-4 y toggle.
"""
import pytest
from datetime import date
from unittest.mock import patch, MagicMock

from app.services.tax_obligation_service import (
    TaxObligationService,
    DGII_OBLIGATIONS,
    REGIME_PRESETS,
    OBLIGATIONS_DICT,
    LEGACY_KEY_ALIASES,
    normalize_email,
    is_valid_email,
    _coerce_bool,
    _next_monthly_day,
    _next_annual_120days,
    _next_annual_90days,
    _next_annual_rst_feb,
    _next_last_business_day,
    _next_third_business_day,
    _third_business_day,
    _last_business_day,
    _is_weekend_or_holiday,
    _next_business_day,
    _next_due_date,
    _get_period_key,
)


class TestTaxObligationCatalog:
    def test_catalog_contains_essential_obligations(self):
        keys = {ob["key"] for ob in DGII_OBLIGATIONS}
        essential = {
            "form_606", "form_607", "form_608", "form_609", "form_623",
            "it1", "ir17", "ir3", "tss", "dgt3", "anticipos_isr",
            "ir1", "ir2", "act",
            "rs1", "rs2", "rs3", "rs4",
            "rst_cuota_mar", "rst_cuota_jun", "rst_cuota_sep", "rst_cuota_dic",
        }
        assert essential.issubset(keys)

    def test_legacy_key_aliases(self):
        assert LEGACY_KEY_ALIASES["ir3_ret"] == "anticipos_isr"

    def test_rst_obligations_not_in_ordinary_forms(self):
        """606/607/608/609/623, it1, ir2, act, anticipos_isr NO aplican a RST."""
        rs2 = set(REGIME_PRESETS["rst_income_juridica"]["enabled_keys"])
        excluded = {"form_606", "form_607", "form_608", "form_609", "form_623",
                    "it1", "ir2", "act", "anticipos_isr", "ir1"}
        assert rs2.isdisjoint(excluded)

    def test_tss_and_dgt3_are_separate(self):
        assert "tss" in OBLIGATIONS_DICT
        assert "dgt3" in OBLIGATIONS_DICT
        assert OBLIGATIONS_DICT["tss"]["recurrence"] == "third_business_day_next_month"
        assert OBLIGATIONS_DICT["tss"]["condition"] == "registered_workers"
        assert OBLIGATIONS_DICT["dgt3"]["condition"] == "employer"


class TestRegimeProfileDetection:
    @patch("app.services.db_service.DatabaseService.get_company_profile")
    def test_detect_ordinary_juridica(self, mock_profile):
        mock_profile.return_value = {"companyRNC": "131880681", "regimenFiscal": "ordinary"}
        detected = TaxObligationService.detect_tax_profile("test_owner")
        assert detected["regime_key"] == "ordinary_juridica"
        assert detected["is_physical_person"] is False
        assert "ir2" in detected["recommended_keys"]
        assert "act" in detected["recommended_keys"]
        assert "ir1" not in detected["recommended_keys"]

    @patch("app.services.db_service.DatabaseService.get_company_profile")
    def test_detect_ordinary_persona_fisica(self, mock_profile):
        mock_profile.return_value = {"companyRNC": "40223456789", "regimenFiscal": "ordinary"}
        detected = TaxObligationService.detect_tax_profile("test_owner")
        assert detected["regime_key"] == "ordinary_fisica"
        assert "ir1" in detected["recommended_keys"]
        assert "ir2" not in detected["recommended_keys"]
        assert "act" not in detected["recommended_keys"]

    @patch("app.services.db_service.DatabaseService.get_company_profile")
    def test_detect_rst_income_fisica(self, mock_profile):
        mock_profile.return_value = {"companyRNC": "40223456789", "regimenFiscal": "rst_income"}
        detected = TaxObligationService.detect_tax_profile("test_owner")
        assert detected["regime_key"] == "rst_income_fisica"
        assert "rs1" in detected["recommended_keys"]
        assert "rs2" not in detected["recommended_keys"]

    @patch("app.services.db_service.DatabaseService.get_company_profile")
    def test_detect_rst_income_juridica(self, mock_profile):
        mock_profile.return_value = {"companyRNC": "131880681", "regimenFiscal": "rst_income"}
        detected = TaxObligationService.detect_tax_profile("test_owner")
        assert detected["regime_key"] == "rst_income_juridica"
        assert "rs2" in detected["recommended_keys"]
        assert "rs1" not in detected["recommended_keys"]

    @patch("app.services.db_service.DatabaseService.get_company_profile")
    def test_rst_income_has_no_ordinary_isr_advance(self, mock_profile):
        mock_profile.return_value = {"companyRNC": "131880681", "regimenFiscal": "rst_income"}
        detected = TaxObligationService.detect_tax_profile("test_owner")
        assert detected["regime_key"] == "rst_income_juridica"
        assert "anticipos_isr" not in detected["recommended_keys"]

    @patch("app.services.db_service.DatabaseService.get_company_profile")
    def test_detect_rst_purchases(self, mock_profile):
        mock_profile.return_value = {"companyRNC": "131880681", "regimenFiscal": "rst_purchases"}
        detected = TaxObligationService.detect_tax_profile("test_owner")
        assert detected["regime_key"] == "rst_purchases"
        assert "rs3" in detected["recommended_keys"]

    @patch("app.services.db_service.DatabaseService.get_company_profile")
    def test_detect_rst_agropecuario(self, mock_profile):
        mock_profile.return_value = {"companyRNC": "131880681", "regimenFiscal": "rst_agropecuario"}
        detected = TaxObligationService.detect_tax_profile("test_owner")
        assert detected["regime_key"] == "rst_agropecuario"
        assert "rs4" in detected["recommended_keys"]
        assert "rs2" not in detected["recommended_keys"]

    @patch("app.services.db_service.DatabaseService.get_company_profile")
    def test_explicit_rst_modality_takes_priority(self, mock_profile):
        """rstModality explícita debe ganar sobre el regimenFiscal genérico (evita agropecuario→RS2)."""
        mock_profile.return_value = {
            "companyRNC": "131880681",
            "regimenFiscal": "rst_income",
            "rstModality": "rs4",
        }
        detected = TaxObligationService.detect_tax_profile("test_owner")
        assert detected["regime_key"] == "rst_agropecuario"

    @patch("app.services.db_service.DatabaseService.get_company_profile")
    def test_agropecuario_never_maps_to_rs2(self, mock_profile):
        mock_profile.return_value = {"companyRNC": "131880681", "regimenFiscal": "rst_agropecuario"}
        detected = TaxObligationService.detect_tax_profile("test_owner")
        assert detected["regime_key"] != "rst_income_juridica"

    @patch("app.services.db_service.DatabaseService.get_company_profile")
    def test_detect_exempt(self, mock_profile):
        mock_profile.return_value = {"companyRNC": "131880681", "regimenFiscal": "exempt"}
        detected = TaxObligationService.detect_tax_profile("test_owner")
        assert detected["regime_key"] == "exempt"
        assert "ir2" in detected["recommended_keys"]
        assert "it1" not in detected["recommended_keys"]


class TestApplyRegimePreset:
    @patch("app.services.tax_obligation_service.TaxObligationService.save")
    @patch("app.services.tax_obligation_service.TaxObligationService.detect_tax_profile")
    def test_apply_preset_rs2(self, mock_detect, mock_save):
        mock_detect.return_value = {
            "regime_key": "rst_income_juridica",
            "recommended_keys": REGIME_PRESETS["rst_income_juridica"]["enabled_keys"],
        }
        res = TaxObligationService.apply_regime_preset("test_owner", preset_key="rst_income_juridica")
        assert res["preset_key"] == "rst_income_juridica"
        enabled = set(res["enabled_keys"])
        assert "rs2" in enabled
        assert {"rst_cuota_mar", "rst_cuota_jun", "rst_cuota_sep", "rst_cuota_dic"} <= enabled
        assert "ir17" in enabled and "ir3" in enabled and "tss" in enabled and "dgt3" in enabled
        assert "it1" not in enabled
        assert "ir2" not in enabled
        assert "anticipos_isr" not in enabled
        assert "act" not in enabled
        assert "form_606" not in enabled

    @patch("app.services.tax_obligation_service.TaxObligationService.save")
    @patch("app.services.tax_obligation_service.TaxObligationService.detect_tax_profile")
    def test_apply_preset_physical_person(self, mock_detect, mock_save):
        mock_detect.return_value = {
            "regime_key": "ordinary_fisica",
            "recommended_keys": ["form_606", "form_607", "it1", "ir17", "ir3", "tss", "dgt3", "anticipos_isr", "ir1"],
        }
        res = TaxObligationService.apply_regime_preset("test_owner", preset_key="ordinary_fisica")
        assert res["preset_key"] == "ordinary_fisica"
        assert "ir1" in res["enabled_keys"]
        assert "ir2" not in res["enabled_keys"]


class TestRecurrenceCalculations:
    def test_next_monthly_day_current_month(self):
        assert _next_monthly_day(None, 15, date(2026, 10, 7)) == date(2026, 10, 15)

    def test_next_monthly_day_next_month(self):
        assert _next_monthly_day(None, 15, date(2026, 10, 16)) == date(2026, 11, 15)

    def test_next_monthly_day_year_rollover(self):
        assert _next_monthly_day(None, 20, date(2026, 12, 21)) == date(2027, 1, 20)

    def test_next_annual_120days_december_closing(self):
        assert _next_annual_120days(date(2026, 2, 1), fiscal_end_month=12) == date(2026, 4, 30)
        assert _next_annual_120days(date(2026, 5, 15), fiscal_end_month=12) == date(2027, 4, 30)

    def test_next_annual_90days_personas_fisicas(self):
        assert _next_annual_90days(date(2026, 1, 10), fiscal_end_month=12) == date(2026, 3, 31)

    def test_next_annual_rst_february_is_last_business_day(self):
        # Feb 28 2026 es sábado → último día laborable = viernes 27.
        assert _next_annual_rst_feb(date(2026, 1, 15)) == date(2026, 2, 27)

    def test_last_business_day_february_weekend(self):
        assert _last_business_day(2026, 2) == date(2026, 2, 27)

    def test_last_business_day_march(self):
        # 31 de marzo 2026 es martes → sin desplazamiento.
        assert _last_business_day(2026, 3) == date(2026, 3, 31)

    def test_next_last_business_day_next_year(self):
        today = date(2026, 3, 1)
        assert _next_last_business_day(today, 2) == date(2027, 2, 26)  # 28 feb 2027 = domingo → 26

    def test_third_business_day_january_with_holidays(self):
        # 1 ene 2027 = viernes (Año Nuevo, trasladado a lun 4), 2-3 fin de semana, 4 feriado.
        # Días laborables: 1 (vie), 5 (mar), 6 (mié) → 3er día laborable = 6.
        assert _third_business_day(2027, 1) == date(2027, 1, 6)

    def test_next_third_business_day(self):
        # 3er día laborable de noviembre 2026 = miércoles 4.
        assert _next_third_business_day(date(2026, 10, 10)) == date(2026, 11, 4)


class TestWeekendAndHolidayShifts:
    def test_weekend_shift_to_monday(self):
        sunday = date(2026, 11, 15)
        assert _is_weekend_or_holiday(sunday) is True
        assert _next_business_day(sunday) == date(2026, 11, 16)

    def test_saturday_shift_to_monday(self):
        saturday = date(2026, 8, 15)
        assert _is_weekend_or_holiday(saturday) is True
        assert _next_business_day(saturday) >= date(2026, 8, 17)


class TestTaxObligationStatusCalculation:
    def test_status_categories(self):
        today = date(2026, 10, 7)
        with patch.object(TaxObligationService, "get_all") as mock_get_all, \
             patch("app.services.tax_obligation_service._get_fiscal_end_month", return_value=12):
            mock_get_all.return_value = [
                {"obligation_key": "form_606", "label": "Formato 606", "recurrence": "monthly_15",
                 "enabled": True, "first_due_date": ""},
                {"obligation_key": "ir17", "label": "IR-17", "recurrence": "monthly_10",
                 "enabled": True, "first_due_date": ""},
            ]
            statuses = TaxObligationService.get_status("user_123", reference_date=today)
            status_map = {s["key"]: s for s in statuses}
            assert status_map["form_606"]["status"] == "ok"
            assert status_map["form_606"]["days_remaining"] == 8
            assert status_map["ir17"]["status"] in ("upcoming", "due_soon")

    def test_disabled_obligations_filtered_out(self):
        today = date(2026, 10, 7)
        with patch.object(TaxObligationService, "get_all") as mock_get_all, \
             patch("app.services.tax_obligation_service._get_fiscal_end_month", return_value=12):
            mock_get_all.return_value = [
                {"obligation_key": "ir1", "label": "IR-1", "recurrence": "annual_90days", "enabled": False}
            ]
            statuses = TaxObligationService.get_status("user_123", reference_date=today)
            assert len(statuses) == 0

    def test_employee_conditional_gate(self):
        """Sin empleados activos: IR-3/TSS/DGT-3 se suprimen; IR-17 NO se suprime."""
        today = date(2026, 10, 7)
        obs = [
            {"obligation_key": "ir3", "label": "IR-3", "recurrence": "monthly_10", "enabled": True,
             "first_due_date": "", "conditional": True, "condition": "employees_with_salary_retention"},
            {"obligation_key": "tss", "label": "TSS", "recurrence": "third_business_day_next_month",
             "enabled": True, "first_due_date": "", "conditional": True, "condition": "registered_workers"},
            {"obligation_key": "dgt3", "label": "DGT-3", "recurrence": "third_business_day_next_month",
             "enabled": True, "first_due_date": "", "conditional": True, "condition": "employer"},
            {"obligation_key": "ir17", "label": "IR-17", "recurrence": "monthly_10", "enabled": True,
             "first_due_date": "", "conditional": True, "condition": "withholding_operations"},
        ]
        with patch.object(TaxObligationService, "get_all", return_value=obs), \
             patch.object(TaxObligationService, "_has_active_employees", return_value=False), \
             patch("app.services.tax_obligation_service._get_fiscal_end_month", return_value=12):
            statuses = TaxObligationService.get_status("user_123", reference_date=today)
            keys = {s["key"] for s in statuses}
            assert "ir3" not in keys
            assert "tss" not in keys
            assert "dgt3" not in keys
            assert "ir17" in keys

    def test_employee_conditional_kept_when_employees(self):
        today = date(2026, 10, 7)
        obs = [
            {"obligation_key": "tss", "label": "TSS", "recurrence": "third_business_day_next_month",
             "enabled": True, "first_due_date": "", "conditional": True, "condition": "registered_workers"},
        ]
        with patch.object(TaxObligationService, "get_all", return_value=obs), \
             patch.object(TaxObligationService, "_has_active_employees", return_value=True), \
             patch("app.services.tax_obligation_service._get_fiscal_end_month", return_value=12):
            statuses = TaxObligationService.get_status("user_123", reference_date=today)
            assert "tss" in {s["key"] for s in statuses}

    @patch("app.services.tax_obligation_service.TaxObligationService.detect_tax_profile")
    def test_legacy_isr_advance_is_hidden_for_rst_income(self, mock_profile):
        today = date(2026, 10, 7)
        mock_profile.return_value = {"regime_key": "rst_income_juridica"}
        legacy_advance = {
            "obligation_key": "anticipos_isr",
            "label": "Anticipos ISR",
            "recurrence": "monthly_15",
            "enabled": True,
            "first_due_date": "",
        }
        with patch.object(TaxObligationService, "get_all", return_value=[legacy_advance]), \
             patch("app.services.tax_obligation_service._get_fiscal_end_month", return_value=12):
            statuses = TaxObligationService.get_status("user_123", reference_date=today)

        assert statuses == []


class TestRS2Scenario:
    """Una jurídica acogida al RST por ingresos (RS2) recibe RS2 + 4 cuotas + condicionales;
    no recibe obligaciones de régimen ordinario ni exentas como pendientes."""

    def _mock_rs2_obligations(self):
        enabled = REGIME_PRESETS["rst_income_juridica"]["enabled_keys"]
        return [
            dict(OBLIGATIONS_DICT[k], enabled=True, first_due_date="", conditional=OBLIGATIONS_DICT[k].get("conditional", False))
            for k in enabled
        ]

    @patch("app.services.tax_obligation_service.TaxObligationService._has_active_employees", return_value=True)
    def test_rs2_status_only_expected_keys(self, _):
        today = date(2026, 10, 7)
        with patch.object(TaxObligationService, "get_all", return_value=self._mock_rs2_obligations()), \
             patch("app.services.tax_obligation_service._get_fiscal_end_month", return_value=12):
            statuses = TaxObligationService.get_status("user_123", reference_date=today)
            keys = {s["key"] for s in statuses}
            expected = {"rs2", "rst_cuota_mar", "rst_cuota_jun", "rst_cuota_sep", "rst_cuota_dic",
                        "ir17", "ir3", "tss", "dgt3"}
            assert keys == expected

    @patch("app.services.tax_obligation_service.TaxObligationService._has_active_employees", return_value=False)
    def test_rs2_status_without_employees_suppresses_employee_obligations(self, _):
        today = date(2026, 10, 7)
        with patch.object(TaxObligationService, "get_all", return_value=self._mock_rs2_obligations()), \
             patch("app.services.tax_obligation_service._get_fiscal_end_month", return_value=12):
            statuses = TaxObligationService.get_status("user_123", reference_date=today)
            keys = {s["key"] for s in statuses}
            assert {"rs2", "rst_cuota_mar", "rst_cuota_jun", "rst_cuota_sep", "rst_cuota_dic", "ir17"} <= keys
            assert "ir3" not in keys
            assert "tss" not in keys
            assert "dgt3" not in keys

    def test_rs2_cuotas_are_quarterly_months(self):
        today = date(2026, 2, 1)
        d1 = _next_due_date("", "last_business_day_march", reference_date=today)
        d2 = _next_due_date("", "last_business_day_june", reference_date=today)
        d3 = _next_due_date("", "last_business_day_september", reference_date=today)
        d4 = _next_due_date("", "last_business_day_december", reference_date=today)
        assert (d1.month, d2.month, d3.month, d4.month) == (3, 6, 9, 12)
        assert d1.year == d2.year == d3.year == d4.year == 2026


class TestCustomAlertsAndRecurrences:
    def test_custom_monthly_day_recurrence(self):
        assert _next_due_date("", "monthly_day_5", reference_date=date(2026, 10, 1)) == date(2026, 10, 5)
        assert _next_due_date("", "monthly_day_5", reference_date=date(2026, 10, 6)) == date(2026, 11, 5)

    def test_annual_date_recurrence(self):
        assert _next_due_date("2026-07-15", "annual_date", reference_date=date(2026, 5, 10)) == date(2026, 7, 15)
        assert _next_due_date("2026-07-15", "annual_date", reference_date=date(2026, 8, 1)) == date(2027, 7, 15)

    def test_fixed_date_recurrence(self):
        assert _next_due_date("2026-10-25", "fixed_date", reference_date=date(2026, 10, 1)) == date(2026, 10, 26)

    def test_delete_native_obligation_rejected(self):
        success, err = TaxObligationService.delete("user_123", "form_606")
        assert success is False
        assert "no pueden eliminarse" in err

    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    def test_delete_custom_obligation_allowed(self, mock_ref):
        mock_doc = MagicMock()
        mock_doc.get().exists = True
        mock_coll = MagicMock()
        mock_coll.document.return_value = mock_doc
        mock_ref.return_value = mock_coll
        success, err = TaxObligationService.delete("user_123", "custom_abc123")
        assert success is True
        assert err is None
        mock_doc.delete.assert_called_once()


class TestEnsureDGT4Alert:
    @patch("app.services.dgt_service.DGTService.get_dgt4_data")
    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    def test_ensure_dgt4_alert_creates_when_not_exists(self, mock_ref, mock_dgt4):
        mock_dgt4.return_value = {"totalCambios": 1}
        mock_doc = MagicMock()
        mock_doc.get().exists = False
        mock_coll = MagicMock()
        mock_coll.document.return_value = mock_doc
        mock_ref.return_value = mock_coll
        res = TaxObligationService.ensure_dgt4_alert(company_id="comp_1", transaction_date="2026-10-15", owner_uid="user_1")
        assert res["created"] is True
        assert res["key"] == "dgt4_2026_10"
        assert res["due_date"] == "2026-11-05"
        mock_coll.document.assert_any_call("dgt4_2026_10")

    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    @patch("app.services.dgt_service.DGTService.get_dgt4_data")
    def test_ensure_dgt4_alert_idempotent_no_duplicate(self, mock_dgt4, mock_ref):
        mock_dgt4.return_value = {"totalCambios": 1}
        mock_doc = MagicMock()
        mock_doc.get().exists = True
        mock_coll = MagicMock()
        mock_coll.document.return_value = mock_doc
        mock_ref.return_value = mock_coll
        res = TaxObligationService.ensure_dgt4_alert(company_id="comp_1", transaction_date="2026-10-28", owner_uid="user_1")
        assert res["created"] is False
        assert res["reason"] == "already_exists"
        mock_doc.set.assert_not_called()

    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    @patch("app.services.dgt_service.DGTService.get_dgt4_data")
    def test_ensure_dgt4_alert_weekend_shift(self, mock_dgt4, mock_ref):
        mock_dgt4.return_value = {"totalCambios": 1}
        mock_doc = MagicMock()
        mock_doc.get().exists = False
        mock_coll = MagicMock()
        mock_coll.document.return_value = mock_doc
        mock_ref.return_value = mock_coll
        res = TaxObligationService.ensure_dgt4_alert(company_id="comp_1", transaction_date="2026-08-10")
        assert res["created"] is True
        assert res["due_date"] == "2026-09-07"

    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    @patch("app.services.dgt_service.DGTService.get_dgt4_data")
    def test_ensure_dgt4_alert_skips_period_without_changes(self, mock_dgt4, mock_ref):
        mock_dgt4.return_value = {"totalCambios": 0, "lines": []}

        res = TaxObligationService.ensure_dgt4_alert(
            company_id="comp_1",
            transaction_date="2026-10-15",
            owner_uid="user_1",
        )

        assert res["created"] is False
        assert res["reason"] == "no_real_changes"
        mock_ref.assert_not_called()

    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    @patch("app.services.dgt_service.DGTService.get_dgt4_data")
    def test_ensure_dgt4_alert_disables_existing_stale_alert(self, mock_dgt4, mock_ref):
        mock_dgt4.return_value = {"totalCambios": 0, "lines": []}
        existing_ref = MagicMock()
        existing_ref.get.return_value.exists = True
        existing_ref.get.return_value.to_dict.return_value = {
            "origin": "rrhh_auto", "enabled": True,
        }
        collection = MagicMock()
        collection.document.return_value = existing_ref
        mock_ref.return_value = collection

        res = TaxObligationService.ensure_dgt4_alert(
            company_id="comp_1", transaction_date="2026-10-15", owner_uid="user_1"
        )

        assert res["reason"] == "no_real_changes"
        existing_ref.set.assert_called_once_with({"enabled": False}, merge=True)

    def test_ensure_dgt4_alert_missing_company_and_owner(self):
        res = TaxObligationService.ensure_dgt4_alert(company_id=None, owner_uid=None)
        assert res["created"] is False
        assert res["reason"] == "missing_company_or_owner"


class TestPeriodKeyCalculation:
    def test_monthly_period_key(self):
        assert _get_period_key(date(2026, 10, 15), "monthly_15") == "2026-10"
        assert _get_period_key(date(2026, 10, 5), "monthly_day_5") == "2026-10"

    def test_quarterly_period_key(self):
        assert _get_period_key(date(2026, 3, 31), "last_business_day_march") == "2026-03"

    def test_annual_period_key(self):
        assert _get_period_key(date(2026, 4, 30), "annual_120days") == "2026"
        assert _get_period_key(date(2026, 2, 27), "last_business_day_february") == "2026"

    def test_fixed_period_key(self):
        assert _get_period_key(date(2026, 10, 5), "fixed_date") == "2026-10-05"


class TestToggleCompleteObligation:
    @patch("app.services.tax_obligation_service.TaxObligationService.save")
    @patch("app.services.tax_obligation_service.TaxObligationService.get_all")
    def test_toggle_complete_marks_and_unmarks(self, mock_get_all, mock_save):
        mock_save.return_value = True
        mock_get_all.return_value = [{
            "obligation_key": "form_606", "label": "Formato 606", "recurrence": "monthly_15",
            "enabled": True, "first_due_date": "", "completed_periods": {}, "last_completed_period": "",
        }]
        res = TaxObligationService.toggle_complete("user_123", key="form_606", period="2026-10", completed=True, completed_by="a@b.c")
        assert res["success"] is True
        saved_payload = mock_save.call_args[0][1]
        assert saved_payload["last_completed_period"] == "2026-10"

        mock_get_all.return_value = [{
            "obligation_key": "form_606", "label": "Formato 606", "recurrence": "monthly_15",
            "enabled": True, "first_due_date": "",
            "completed_periods": {"2026-10": {"completed_at": "x"}}, "last_completed_period": "2026-10",
        }]
        res_unmark = TaxObligationService.toggle_complete("user_123", key="form_606", period="2026-10", completed=False)
        assert res_unmark["success"] is True
        saved_unmark_payload = mock_save.call_args[0][1]
        assert saved_unmark_payload["last_completed_period"] == ""

    def test_status_excludes_completed_keeps_other(self):
        today = date(2026, 10, 14)
        with patch.object(TaxObligationService, "get_all") as mock_get_all, \
             patch("app.services.tax_obligation_service._get_fiscal_end_month", return_value=12):
            mock_get_all.return_value = [
                {"obligation_key": "form_606", "label": "Formato 606", "recurrence": "monthly_15",
                 "enabled": True, "first_due_date": "",
                 "completed_periods": {"2026-10": {"completed_at": "x"}}, "last_completed_period": "2026-10"},
                {"obligation_key": "form_607", "label": "Formato 607", "recurrence": "monthly_15",
                 "enabled": True, "first_due_date": "", "completed_periods": {}, "last_completed_period": ""},
            ]
            statuses = TaxObligationService.get_status("user_123", reference_date=today)
            status_map = {s["key"]: s for s in statuses}
            assert status_map["form_606"]["status"] == "completed"
            assert status_map["form_607"]["status"] == "due_soon"
            pending = TaxObligationService.get_pending_alerts("user_123", reference_date=today)
            assert "form_606" not in [p["key"] for p in pending]
            assert "form_607" in [p["key"] for p in pending]


class TestNotificationDedup:
    def test_annual_uses_year_period_key(self):
        """period_key anual es solo el año (no YYYY-MM), evitando dedup incorrecto."""
        assert _get_period_key(date(2026, 4, 30), "annual_120days") == "2026"

    @patch("app.services.db_service.DatabaseService.get_company_profile")
    @patch.object(TaxObligationService, "get_all")
    @patch.object(TaxObligationService, "get_status")
    def test_process_notifications_dedups_by_period_key(self, mock_status, mock_get_all, mock_profile):
        mock_profile.return_value = {"companyEmail": "x@y.com", "companyName": "Empresa"}
        mock_get_all.return_value = [
            {"obligation_key": "ir2", "label": "IR-2", "recurrence": "annual_120days",
             "enabled": True, "first_due_date": "", "last_notified_period": "2026"},
        ]
        mock_status.return_value = [
            {"key": "ir2", "label": "IR-2", "status": "due_soon", "next_due_date": "2026-04-30",
             "period_key": "2026", "days_remaining": 2, "description": ""},
        ]
        from app.services.tax_obligation_service import TaxObligationService as T
        with patch.object(T, "save") as mock_save:
            sent, errors = T.process_notifications("user_123")
            # Ya notificado en período 2026 → no debe reenviar
            assert sent == 0
            assert mock_save.call_count == 0


class TestCoerceBool:
    def test_bool_passthrough(self):
        assert _coerce_bool(True) is True
        assert _coerce_bool(False) is False

    def test_string_false_values(self):
        for v in ("false", "False", "FALSE", "0", "off", "no", "  false  "):
            assert _coerce_bool(v) is False, f"'{v}' debe ser False"

    def test_string_true_values(self):
        for v in ("true", "True", "1", "yes", "on"):
            assert _coerce_bool(v) is True, f"'{v}' debe ser True"

    def test_numeric(self):
        assert _coerce_bool(1) is True
        assert _coerce_bool(0) is False


class TestEmailHelpers:
    def test_normalize_strips_and_lowercases(self):
        assert normalize_email("  Factura@MiEmpresa.COM  ") == "factura@miempresa.com"
        assert normalize_email(None) == ""
        assert normalize_email("") == ""

    def test_valid_emails(self):
        assert is_valid_email("factura@miempresa.com.do") is True
        assert is_valid_email("a.b+c@sub.domain.org") is True

    def test_invalid_emails(self):
        assert is_valid_email("") is False
        assert is_valid_email("no-arroba") is False
        assert is_valid_email("a@b") is False
        assert is_valid_email("a b@c.com") is False


class TestEmailPreferencePersistence:
    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    def test_save_persists_email_preferences(self, mock_ref):
        mock_doc = MagicMock()
        mock_coll = MagicMock()
        mock_coll.document.return_value = mock_doc
        mock_ref.return_value = mock_coll

        ok = TaxObligationService.save(
            "user_1",
            {"obligation_key": "custom_x", "notify_email": "false", "notify_email_to": "  Alerta@X.com  "},
            company_id="comp_1",
        )
        assert ok is True
        payload = mock_doc.set.call_args[0][0]
        assert payload["notify_email"] is False
        assert payload["notify_email_to"] == "alerta@x.com"

    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    def test_save_rejects_invalid_email(self, mock_ref):
        mock_doc = MagicMock()
        mock_coll = MagicMock()
        mock_coll.document.return_value = mock_doc
        mock_ref.return_value = mock_coll

        ok = TaxObligationService.save(
            "user_1",
            {"obligation_key": "custom_x", "notify_email_to": "correo-invalido"},
            company_id="comp_1",
        )
        assert ok is False
        mock_doc.set.assert_not_called()

    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    def test_save_allows_empty_email(self, mock_ref):
        mock_doc = MagicMock()
        mock_coll = MagicMock()
        mock_coll.document.return_value = mock_doc
        mock_ref.return_value = mock_coll

        ok = TaxObligationService.save(
            "user_1",
            {"obligation_key": "custom_x", "notify_email_to": "   "},
            company_id="comp_1",
        )
        assert ok is True
        assert mock_doc.set.call_args[0][0]["notify_email_to"] == ""

    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    def test_save_uses_scoped_collection_for_company(self, mock_ref):
        """El guardado debe ir contra la colección de la empresa activa."""
        mock_doc = MagicMock()
        mock_coll = MagicMock()
        mock_coll.document.return_value = mock_doc
        mock_ref.return_value = mock_coll

        TaxObligationService.save("user_1", {"obligation_key": "custom_x", "notify_email": True}, company_id="comp_9")
        mock_ref.assert_called_once_with("user_1", company_id="comp_9")
        mock_coll.document.assert_called_once_with("custom_x")


class TestSeedDefaultsBackfill:
    def _mock_profile_ref_with_docs(self, docs_by_key):
        mock_coll = MagicMock()
        doc_map = {}
        for k, data in docs_by_key.items():
            d = MagicMock()
            snap = MagicMock()
            snap.exists = data is not None
            snap.to_dict.return_value = data or {}
            d.get.return_value = snap
            doc_map[k] = d
        mock_coll.document.side_effect = lambda key: doc_map.setdefault(key, MagicMock())
        return mock_coll

    @patch("app.services.tax_obligation_service.TaxObligationService.detect_tax_profile")
    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    def test_backfills_missing_email_prefs_without_overwrite(self, mock_ref, mock_detect):
        mock_detect.return_value = {"recommended_keys": []}
        docs = {
            "form_606": {"obligation_key": "form_606", "enabled": True, "is_custom": False},
        }
        coll = self._mock_profile_ref_with_docs(docs)
        mock_ref.return_value = coll

        TaxObligationService.seed_defaults("user_1", company_id="comp_1")

        # El doc de form_606 sí debe haberse marcado dirty para backfill.
        form_doc = coll.document("form_606")
        assert form_doc.set.called
        data = form_doc.set.call_args[0][0]
        assert data["notify_email"] is True
        assert data["notify_email_to"] == ""

    @patch("app.services.tax_obligation_service.TaxObligationService.detect_tax_profile")
    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    def test_does_not_overwrite_existing_email_prefs(self, mock_ref, mock_detect):
        mock_detect.return_value = {"recommended_keys": []}
        docs = {
            "form_606": {
                "obligation_key": "form_606", "enabled": True, "is_custom": False,
                "notify_email": False, "notify_email_to": "otro@x.com",
            },
        }
        coll = self._mock_profile_ref_with_docs(docs)
        mock_ref.return_value = coll

        TaxObligationService.seed_defaults("user_1", company_id="comp_1")

        form_doc = coll.document("form_606")
        # Los campos ya existen → no debe reescribirse el documento.
        assert not form_doc.set.called


class TestProcessNotificationsEmailTargeting:
    def _status(self, key, status="due_soon"):
        return [{"key": key, "label": key, "status": status, "next_due_date": "2026-11-15",
                 "period_key": "2026-11", "days_remaining": 2, "description": ""}]

    @staticmethod
    def _run(company_email="empresa@x.com"):
        from flask import Flask
        app = Flask(__name__)
        with app.app_context():
            return TaxObligationService.process_notifications("user_1")

    @patch("app.services.mailer.Mailer.send", return_value=True)
    @patch("app.services.db_service.DatabaseService.get_company_profile")
    @patch.object(TaxObligationService, "get_all")
    @patch.object(TaxObligationService, "get_status")
    def test_skips_when_notify_email_false(self, mock_status, mock_get_all, mock_profile, mock_send):
        mock_profile.return_value = {"companyEmail": "empresa@x.com", "companyName": "Empresa"}
        mock_get_all.return_value = [
            {"obligation_key": "custom_a", "enabled": True, "notify_email": False},
        ]
        mock_status.return_value = self._status("custom_a")
        with patch.object(TaxObligationService, "save") as mock_save:
            sent, errors = self._run()
        assert sent == 0
        mock_send.assert_not_called()
        mock_save.assert_not_called()

    @patch("app.services.mailer.Mailer.send", return_value=True)
    @patch("app.services.db_service.DatabaseService.get_company_profile")
    @patch.object(TaxObligationService, "get_all")
    @patch.object(TaxObligationService, "get_status")
    def test_uses_custom_recipient_override(self, mock_status, mock_get_all, mock_profile, mock_send):
        mock_profile.return_value = {"companyEmail": "empresa@x.com", "companyName": "Empresa"}
        mock_get_all.return_value = [
            {"obligation_key": "custom_a", "enabled": True, "notify_email": True, "notify_email_to": "alerta@x.com"},
        ]
        mock_status.return_value = self._status("custom_a")
        with patch.object(TaxObligationService, "save"):
            sent, errors = self._run()
        assert sent == 1
        assert mock_send.call_args[1]["to_email"] == "alerta@x.com"

    @patch("app.services.mailer.Mailer.send", return_value=True)
    @patch("app.services.db_service.DatabaseService.get_company_profile")
    @patch.object(TaxObligationService, "get_all")
    @patch.object(TaxObligationService, "get_status")
    def test_falls_back_to_company_email(self, mock_status, mock_get_all, mock_profile, mock_send):
        mock_profile.return_value = {"companyEmail": "empresa@x.com", "companyName": "Empresa"}
        mock_get_all.return_value = [
            {"obligation_key": "custom_a", "enabled": True, "notify_email": True, "notify_email_to": ""},
        ]
        mock_status.return_value = self._status("custom_a")
        with patch.object(TaxObligationService, "save"):
            sent, errors = self._run()
        assert sent == 1
        assert mock_send.call_args[1]["to_email"] == "empresa@x.com"

    @patch("app.services.mailer.Mailer.send", return_value=True)
    @patch("app.services.db_service.DatabaseService.get_company_profile")
    @patch.object(TaxObligationService, "get_all")
    @patch.object(TaxObligationService, "get_status")
    def test_custom_alert_resolved_by_obligation_key(self, mock_status, mock_get_all, mock_profile, mock_send):
        """Una alerta personalizada (sin 'key') debe resolverse por obligation_key."""
        mock_profile.return_value = {"companyEmail": "empresa@x.com", "companyName": "Empresa"}
        # get_all devuelve alerta custom solo con obligation_key (sin 'key' ni 'id').
        mock_get_all.return_value = [
            {"obligation_key": "custom_abc", "enabled": True, "notify_email": True, "notify_email_to": "custom@x.com"},
        ]
        mock_status.return_value = self._status("custom_abc")
        with patch.object(TaxObligationService, "save"):
            sent, errors = self._run()
        assert sent == 1
        assert mock_send.call_args[1]["to_email"] == "custom@x.com"
