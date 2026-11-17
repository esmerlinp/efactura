"""Fase 0 — Integridad de facturas de proveedor.

Valida las protecciones introducidas:
  - borrado destructivo bloqueado ante pagos/asiento/emitida,
  - anulación (void) preservando trazabilidad,
  - validación de período contable,
  - protección de campos CxP/estado en la capa de API (sanitización),
  - cálculo de ITBIS sin duplicación (ver test_critical_fixes.py).
"""

from unittest.mock import patch, MagicMock
from contextlib import ExitStack

import pytest

import app.services.supplier_invoice_service as mod
from app.services.supplier_invoice_service import SupplierInvoiceService


def _patch_firebase():
    stack = ExitStack()
    stack.enter_context(patch.object(mod, "firebase_initialized", True))
    stack.enter_context(patch.object(mod, "db_firestore", MagicMock()))
    return stack


def _doc_ref(data):
    doc = MagicMock()
    doc.get.return_value.exists = True
    doc.get.return_value.to_dict.return_value = data
    doc.collection.return_value.get.return_value = []
    return doc


class TestDeleteGuards:
    def test_delete_blocked_when_has_payments(self):
        doc = _doc_ref({"id": "inv-1", "status": "registrada", "attachmentUrls": []})
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref, \
                 patch.object(SupplierInvoiceService, "has_payments", return_value=True), \
                 patch.object(SupplierInvoiceService, "has_accounting_entry", return_value=False):
                coll_ref.return_value.document.return_value = doc
                ok, msg = SupplierInvoiceService.delete(owner_uid="u", invoice_id="inv-1", sandbox=True, company_id="c")
                assert ok is False
                assert "pagos" in msg

    def test_delete_blocked_when_accounting_entry(self):
        doc = _doc_ref({"id": "inv-1", "status": "registrada", "attachmentUrls": []})
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref, \
                 patch.object(SupplierInvoiceService, "has_payments", return_value=False), \
                 patch.object(SupplierInvoiceService, "has_accounting_entry", return_value=True):
                coll_ref.return_value.document.return_value = doc
                ok, msg = SupplierInvoiceService.delete(owner_uid="u", invoice_id="inv-1", sandbox=True, company_id="c")
                assert ok is False
                assert "contabilizada" in msg

    def test_delete_blocked_when_emitted(self):
        doc = _doc_ref({"id": "inv-1", "status": "emitida", "attachmentUrls": []})
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref, \
                 patch.object(SupplierInvoiceService, "has_payments", return_value=False), \
                 patch.object(SupplierInvoiceService, "has_accounting_entry", return_value=False):
                coll_ref.return_value.document.return_value = doc
                ok, msg = SupplierInvoiceService.delete(owner_uid="u", invoice_id="inv-1", sandbox=True, company_id="c")
                assert ok is False
                assert "emitida" in msg

    def test_delete_allowed_for_clean_invoice(self):
        doc = _doc_ref({"id": "inv-1", "status": "registrada", "attachmentUrls": []})
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref, \
                 patch.object(SupplierInvoiceService, "has_payments", return_value=False), \
                 patch.object(SupplierInvoiceService, "has_accounting_entry", return_value=False):
                coll_ref.return_value.document.return_value = doc
                ok, msg = SupplierInvoiceService.delete(owner_uid="u", invoice_id="inv-1", sandbox=True, company_id="c")
                assert ok is True
                doc.delete.assert_called_once()


class TestVoid:
    def test_void_blocked_when_has_payments(self):
        doc = _doc_ref({"id": "inv-1", "status": "registrada", "attachmentUrls": []})
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref, \
                 patch.object(SupplierInvoiceService, "has_payments", return_value=True):
                coll_ref.return_value.document.return_value = doc
                ok, msg = SupplierInvoiceService.void(
                    owner_uid="u", invoice_id="inv-1", reason="Duplicada",
                    sandbox=True, company_id="c",
                )
                assert ok is False
                assert "pagos" in msg

    def test_void_marks_anulada_and_voids_entry(self):
        doc = _doc_ref({"id": "inv-1", "status": "registrada", "attachmentUrls": []})
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref, \
                 patch.object(SupplierInvoiceService, "has_payments", return_value=False), \
                 patch.object(SupplierInvoiceService, "validate_period", return_value=None), \
                 patch.object(mod.DatabaseService, "get_accounting_entries", return_value=[
                     {"id": "e-1", "status": "active", "referenceId": "inv-1", "referenceType": "expense"}
                 ]), \
                 patch("app.services.accounting_service.AccountingService.void_entry",
                       return_value={"id": "e-1", "status": "voided"}) as void_entry:
                coll_ref.return_value.document.return_value = doc
                ok, msg = SupplierInvoiceService.void(
                    owner_uid="u", invoice_id="inv-1", reason="Error", voided_by="Admin",
                    sandbox=True, company_id="c",
                )
                assert ok is True
                void_entry.assert_called_once()
                assert doc.update.call_count >= 2
                updated = doc.update.call_args_list[-1][0][0]
                assert updated["status"] == "anulada"
                assert updated["cxpStatus"] == "Anulada"
                assert updated["cxpRemainingBalance"] == 0.0
                assert updated["voidReason"] == "Error"
                assert updated["voidStatus"] == "completed"


class TestValidatePeriod:
    def test_validate_period_propagates_closed_period(self):
        with patch("app.services.fiscal_period_service.FiscalPeriodService.validate_period_open",
                   side_effect=ValueError("El período fiscal 2026-01 está cerrado.")):
            with pytest.raises(ValueError):
                SupplierInvoiceService.validate_period("cid", "2026-01-15")

    def test_validate_period_noop_when_no_date(self):
        SupplierInvoiceService.validate_period("cid", "")

    def test_create_validates_period(self):
        with patch.object(SupplierInvoiceService, "validate_period",
                          side_effect=ValueError("período cerrado")):
            with pytest.raises(ValueError):
                SupplierInvoiceService.create(
                    owner_uid="u", data={"total": 100.0, "date": "2026-01-15"},
                    sandbox=True, company_id="c",
                )


class TestIsEmitted:
    def test_is_emitted_true_for_status_emitida(self):
        assert SupplierInvoiceService.is_emitted({"status": "emitida"}) is True

    def test_is_emitted_true_for_synced_with_encf(self):
        assert SupplierInvoiceService.is_emitted(
            {"status": "registrada", "isSyncedWithDGII": True, "encf": "E310000000001"}
        ) is True

    def test_is_emitted_false_for_draft(self):
        assert SupplierInvoiceService.is_emitted({"status": "registrada"}) is False


class TestApiSanitizePayload:
    def test_strips_protected_and_unknown_fields(self):
        from app.api.v1.supplier_invoices import _sanitize_payload, _CREATE_ALLOWED_FIELDS
        cleaned, forbidden = _sanitize_payload(
            {
                "supplierName": "Proveedor",
                "cxpStatus": "Pagado",
                "cxpRemainingBalance": 0,
                "status": "emitida",
                "unknownField": "x",
            },
            _CREATE_ALLOWED_FIELDS,
        )
        assert "supplierName" in cleaned
        assert "cxpStatus" not in cleaned
        assert "cxpRemainingBalance" not in cleaned
        assert "status" not in cleaned
        assert "unknownField" not in cleaned
        assert set(forbidden) == {"cxpRemainingBalance", "cxpStatus", "status"}

    def test_maps_aliases(self):
        from app.api.v1.supplier_invoices import _sanitize_payload, _CREATE_ALLOWED_FIELDS
        cleaned, _ = _sanitize_payload({"invoiceDate": "2026-01-15", "comment": "nota"}, _CREATE_ALLOWED_FIELDS)
        assert cleaned["date"] == "2026-01-15"
        assert cleaned["comentario"] == "nota"
