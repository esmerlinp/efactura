"""
test_tax_obligation_service.py — Pruebas unitarias para TaxObligationService.
Valida el catálogo de obligaciones DGII/TSS, adaptación por Régimen Fiscal (Ordinario Jurídico, Ordinario Persona Física,
RST, Exento), cálculo de vencimientos, traslados por feriados RD (Ley 139-97) y fines de semana, y estados de alerta.
"""
import pytest
from datetime import date
from unittest.mock import patch, MagicMock

from app.services.tax_obligation_service import (
    TaxObligationService,
    DGII_OBLIGATIONS,
    REGIME_PRESETS,
    _next_monthly_day,
    _next_annual_120days,
    _next_annual_90days,
    _next_annual_rst_feb,
    _is_weekend_or_holiday,
    _next_business_day,
    _next_due_date,
)


class TestTaxObligationCatalog:
    def test_catalog_contains_essential_obligations(self):
        keys = {ob["key"] for ob in DGII_OBLIGATIONS}
        essential = {"form_606", "form_607", "it1", "ir17", "tss", "ir3_ret", "ir2", "act", "ir1", "rst"}
        assert essential.issubset(keys)

    def test_default_enabled_status(self):
        enabled_map = {ob["key"]: ob.get("default_enabled") for ob in DGII_OBLIGATIONS}
        assert enabled_map["form_606"] is True
        assert enabled_map["form_607"] is True
        assert enabled_map["it1"] is True
        assert enabled_map["ir17"] is True
        assert enabled_map["tss"] is True
        assert enabled_map["ir2"] is True


class TestRegimeProfileDetection:
    @patch("app.services.db_service.DatabaseService.get_company_profile")
    def test_detect_ordinary_juridica(self, mock_profile):
        mock_profile.return_value = {
            "companyRNC": "131880681", # 9 dígitos -> Sociedad
            "regimenFiscal": "ordinary",
        }
        detected = TaxObligationService.detect_tax_profile("test_owner")
        assert detected["regime_key"] == "ordinary_juridica"
        assert detected["is_physical_person"] is False
        assert "ir2" in detected["recommended_keys"]
        assert "act" in detected["recommended_keys"]
        assert "ir1" not in detected["recommended_keys"]
        assert "rst" not in detected["recommended_keys"]

    @patch("app.services.db_service.DatabaseService.get_company_profile")
    def test_detect_ordinary_persona_fisica(self, mock_profile):
        mock_profile.return_value = {
            "companyRNC": "40223456789", # 11 dígitos (cédula) -> Persona Física
            "regimenFiscal": "ordinary",
        }
        detected = TaxObligationService.detect_tax_profile("test_owner")
        assert detected["regime_key"] == "ordinary_fisica"
        assert detected["is_physical_person"] is True
        assert "ir1" in detected["recommended_keys"]
        assert "ir2" not in detected["recommended_keys"]
        assert "act" not in detected["recommended_keys"]

    @patch("app.services.db_service.DatabaseService.get_company_profile")
    def test_detect_rst(self, mock_profile):
        mock_profile.return_value = {
            "companyRNC": "131880681",
            "regimenFiscal": "rst_income",
        }
        detected = TaxObligationService.detect_tax_profile("test_owner")
        assert detected["regime_key"] == "rst"
        assert "rst" in detected["recommended_keys"]
        assert "form_606" not in detected["recommended_keys"]
        assert "it1" not in detected["recommended_keys"]
        assert "ir2" not in detected["recommended_keys"]

    @patch("app.services.db_service.DatabaseService.get_company_profile")
    def test_detect_exempt(self, mock_profile):
        mock_profile.return_value = {
            "companyRNC": "131880681",
            "regimenFiscal": "exempt",
        }
        detected = TaxObligationService.detect_tax_profile("test_owner")
        assert detected["regime_key"] == "exempt"
        assert "ir2" in detected["recommended_keys"]
        assert "it1" not in detected["recommended_keys"]
        assert "act" not in detected["recommended_keys"]


class TestApplyRegimePreset:
    @patch("app.services.tax_obligation_service.TaxObligationService.save")
    @patch("app.services.tax_obligation_service.TaxObligationService.detect_tax_profile")
    def test_apply_preset_physical_person(self, mock_detect, mock_save):
        mock_detect.return_value = {
            "regime_key": "ordinary_fisica",
            "recommended_keys": ["form_606", "form_607", "it1", "ir17", "tss", "ir3_ret", "ir1"],
        }
        res = TaxObligationService.apply_regime_preset("test_owner", preset_key="ordinary_fisica")
        assert res["preset_key"] == "ordinary_fisica"
        assert "ir1" in res["enabled_keys"]
        assert "ir2" not in res["enabled_keys"]
        assert mock_save.called


class TestRecurrenceCalculations:
    def test_next_monthly_day_current_month(self):
        today = date(2026, 10, 7)
        due = _next_monthly_day(None, 15, today)
        assert due == date(2026, 10, 15)

    def test_next_monthly_day_next_month(self):
        today = date(2026, 10, 16)
        due = _next_monthly_day(None, 15, today)
        assert due == date(2026, 11, 15)

    def test_next_monthly_day_year_rollover(self):
        today = date(2026, 12, 21)
        due = _next_monthly_day(None, 20, today)
        assert due == date(2027, 1, 20)

    def test_next_annual_120days_december_closing(self):
        today = date(2026, 2, 1)
        due = _next_annual_120days(today, fiscal_end_month=12)
        assert due == date(2026, 4, 30)

        today_after = date(2026, 5, 15)
        due_next = _next_annual_120days(today_after, fiscal_end_month=12)
        assert due_next == date(2027, 4, 30)

    def test_next_annual_120days_march_closing(self):
        today = date(2026, 4, 1)
        due = _next_annual_120days(today, fiscal_end_month=3)
        assert due == date(2026, 7, 29)

    def test_next_annual_90days_personas_fisicas(self):
        today = date(2026, 1, 10)
        due = _next_annual_90days(today, fiscal_end_month=12)
        assert due == date(2026, 3, 31)

    def test_next_annual_rst_february(self):
        today = date(2026, 1, 15)
        due = _next_annual_rst_feb(today)
        assert due == date(2026, 2, 28)


class TestWeekendAndHolidayShifts:
    def test_weekend_shift_to_monday(self):
        sunday = date(2026, 11, 15)
        assert sunday.weekday() == 6
        assert _is_weekend_or_holiday(sunday) is True
        business_day = _next_business_day(sunday)
        assert business_day == date(2026, 11, 16)
        assert business_day.weekday() == 0

    def test_saturday_shift_to_monday(self):
        saturday = date(2026, 8, 15)
        assert saturday.weekday() == 5
        assert _is_weekend_or_holiday(saturday) is True
        business_day = _next_business_day(saturday)
        assert business_day >= date(2026, 8, 17)


class TestTaxObligationStatusCalculation:
    def test_status_categories(self):
        today = date(2026, 10, 7)
        with patch.object(TaxObligationService, "get_all") as mock_get_all, \
             patch("app.services.tax_obligation_service._get_fiscal_end_month", return_value=12):
            
            mock_get_all.return_value = [
                {
                    "obligation_key": "form_606",
                    "label": "Formato 606",
                    "recurrence": "monthly_15",
                    "enabled": True,
                    "first_due_date": "",
                },
                {
                    "obligation_key": "ir17",
                    "label": "IR-17",
                    "recurrence": "monthly_10",
                    "enabled": True,
                    "first_due_date": "",
                },
            ]

            statuses = TaxObligationService.get_status("user_123", reference_date=today)
            status_map = {s["key"]: s for s in statuses}

            assert status_map["form_606"]["status"] == "ok"
            assert status_map["form_606"]["days_remaining"] == 8
            assert status_map["ir17"]["status"] in ("upcoming", "due_soon")
            assert status_map["ir17"]["days_remaining"] <= 7

    def test_disabled_obligations_filtered_out(self):
        today = date(2026, 10, 7)
        with patch.object(TaxObligationService, "get_all") as mock_get_all, \
             patch("app.services.tax_obligation_service._get_fiscal_end_month", return_value=12):
            
            mock_get_all.return_value = [
                {
                    "obligation_key": "ir1",
                    "label": "IR-1",
                    "recurrence": "annual_90days",
                    "enabled": False,
                }
            ]

            statuses = TaxObligationService.get_status("user_123", reference_date=today)
            assert len(statuses) == 0
