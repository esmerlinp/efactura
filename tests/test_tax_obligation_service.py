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


class TestCustomAlertsAndRecurrences:
    def test_custom_monthly_day_recurrence(self):
        # 5 de cada mes
        today = date(2026, 10, 1)
        next_due = _next_due_date("", "monthly_day_5", reference_date=today)
        assert next_due == date(2026, 10, 5)

        # Si hoy es 6 de octubre, debe calcular para noviembre
        today_after = date(2026, 10, 6)
        next_due_after = _next_due_date("", "monthly_day_5", reference_date=today_after)
        # 5 de nov 2026 es jueves (laborable)
        assert next_due_after == date(2026, 11, 5)

    def test_annual_date_recurrence(self):
        today = date(2026, 5, 10)
        # Vence cada 15 de julio
        next_due = _next_due_date("2026-07-15", "annual_date", reference_date=today)
        assert next_due == date(2026, 7, 15)

        # Si ya pasó en el año actual, debe ser en el año siguiente
        today_past = date(2026, 8, 1)
        next_due_next_year = _next_due_date("2026-07-15", "annual_date", reference_date=today_past)
        assert next_due_next_year == date(2027, 7, 15)

    def test_fixed_date_recurrence(self):
        today = date(2026, 10, 1)
        next_due = _next_due_date("2026-10-25", "fixed_date", reference_date=today)
        # 25 de octubre 2026 es domingo -> se traslada a lunes 26
        assert next_due == date(2026, 10, 26)

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
    """Pruebas del enlace automático de RRHH con Alertas para el reporte DGT-4."""

    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    def test_ensure_dgt4_alert_creates_when_not_exists(self, mock_ref):
        mock_doc = MagicMock()
        mock_doc.get().exists = False
        mock_coll = MagicMock()
        mock_coll.document.return_value = mock_doc
        mock_ref.return_value = mock_coll

        res = TaxObligationService.ensure_dgt4_alert(
            company_id="comp_1",
            transaction_date="2026-10-15",
            owner_uid="user_1",
        )

        assert res["created"] is True
        assert res["key"] == "dgt4_2026_10"
        assert res["year"] == 2026
        assert res["month"] == 10
        # 5 de noviembre 2026 es jueves (día hábil)
        assert res["due_date"] == "2026-11-05"

        mock_coll.document.assert_any_call("dgt4_2026_10")
        saved_call = mock_doc.set.call_args
        assert saved_call is not None
        payload = saved_call[0][0]
        assert payload["obligation_key"] == "dgt4_2026_10"
        assert "Octubre 2026" in payload["label"]
        assert payload["recurrence"] == "fixed_date"
        assert payload["first_due_date"] == "2026-11-05"
        assert payload["action_url"] == "/rrhh/dgt/dgt4?year=2026&month=10"
        assert payload["is_custom"] is True
        assert payload["origin"] == "rrhh_auto"

    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    def test_ensure_dgt4_alert_idempotent_no_duplicate(self, mock_ref):
        mock_doc = MagicMock()
        mock_doc.get().exists = True  # Ya existe la alerta para ese mes
        mock_coll = MagicMock()
        mock_coll.document.return_value = mock_doc
        mock_ref.return_value = mock_coll

        # Segundo movimiento de empleado en el mismo mes (ej. otra alta o baja)
        res = TaxObligationService.ensure_dgt4_alert(
            company_id="comp_1",
            transaction_date="2026-10-28",
            owner_uid="user_1",
        )

        assert res["created"] is False
        assert res["key"] == "dgt4_2026_10"
        assert res["reason"] == "already_exists"
        # No debe haber llamado a set() porque ya existía
        mock_doc.set.assert_not_called()

    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    def test_ensure_dgt4_alert_weekend_shift(self, mock_ref):
        mock_doc = MagicMock()
        mock_doc.get().exists = False
        mock_coll = MagicMock()
        mock_coll.document.return_value = mock_doc
        mock_ref.return_value = mock_coll

        # Transacción en agosto 2026. Mes siguiente = septiembre 2026.
        # 5 de septiembre 2026 es sábado -> se traslada a lunes 7 de septiembre 2026.
        res = TaxObligationService.ensure_dgt4_alert(
            company_id="comp_1",
            transaction_date="2026-08-10",
        )

        assert res["created"] is True
        assert res["key"] == "dgt4_2026_08"
        assert res["due_date"] == "2026-09-07"

    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    def test_ensure_dgt4_alert_december_rollover(self, mock_ref):
        mock_doc = MagicMock()
        mock_doc.get().exists = False
        mock_coll = MagicMock()
        mock_coll.document.return_value = mock_doc
        mock_ref.return_value = mock_coll

        # Transacción en diciembre 2026. Mes siguiente = enero 2027.
        # 5 de enero 2027 es martes (día hábil).
        res = TaxObligationService.ensure_dgt4_alert(
            company_id="comp_1",
            transaction_date="2026-12-20",
        )

        assert res["created"] is True
        assert res["key"] == "dgt4_2026_12"
        assert res["due_date"] == "2027-01-05"

    def test_ensure_dgt4_alert_missing_company_and_owner(self):
        res = TaxObligationService.ensure_dgt4_alert(company_id=None, owner_uid=None)
        assert res["created"] is False
        assert res["reason"] == "missing_company_or_owner"

    @patch("app.services.tax_obligation_service.TaxObligationService._profile_ref")
    def test_ensure_dgt4_alert_all_change_events_deduplicated_in_month(self, mock_ref):
        """
        Verifica que cuando ocurren múltiples novedades de cambio en el mismo mes
        (1. Cambio de turno, 2. Cambio de cargo, 3. Aumento salarial, 4. Vacaciones, 5. Traslado)
        solo la primera crea la alerta y las siguientes 4 son detectadas como ya existentes (idempotencia).
        """
        existing_docs = {}

        def mock_document(doc_key):
            m_doc = MagicMock()
            m_doc.exists = doc_key in existing_docs
            m_doc.get.return_value.exists = doc_key in existing_docs

            def _set(data, **kwargs):
                existing_docs[doc_key] = data
            m_doc.set.side_effect = _set
            return m_doc

        mock_coll = MagicMock()
        mock_coll.document.side_effect = mock_document
        mock_ref.return_value = mock_coll

        # Evento 1: Cambio de turno (02 de octubre)
        res1 = TaxObligationService.ensure_dgt4_alert(
            company_id="comp_1",
            transaction_date="2026-10-02",
            owner_uid="user_1",
        )
        assert res1["created"] is True
        assert res1["key"] == "dgt4_2026_10"
        assert "dgt4_2026_10" in existing_docs

        # Evento 2: Cambio de ocupación/cargo (05 de octubre)
        res2 = TaxObligationService.ensure_dgt4_alert(
            company_id="comp_1",
            transaction_date="2026-10-05",
            owner_uid="user_1",
        )
        assert res2["created"] is False
        assert res2["reason"] == "already_exists"
        assert res2["key"] == "dgt4_2026_10"

        # Evento 3: Aumento de salario mensual (12 de octubre)
        res3 = TaxObligationService.ensure_dgt4_alert(
            company_id="comp_1",
            transaction_date="2026-10-12",
            owner_uid="user_1",
        )
        assert res3["created"] is False
        assert res3["reason"] == "already_exists"

        # Evento 4: Inicio y finalización de vacaciones (18 de octubre)
        res4 = TaxObligationService.ensure_dgt4_alert(
            company_id="comp_1",
            transaction_date="2026-10-18",
            owner_uid="user_1",
        )
        assert res4["created"] is False
        assert res4["reason"] == "already_exists"

        # Evento 5: Traslado de establecimiento (25 de octubre)
        res5 = TaxObligationService.ensure_dgt4_alert(
            company_id="comp_1",
            transaction_date="2026-10-25",
            owner_uid="user_1",
        )
        assert res5["created"] is False
        assert res5["reason"] == "already_exists"


