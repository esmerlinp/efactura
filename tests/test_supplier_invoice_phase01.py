"""Fase 0.1 — Corrección de hallazgos críticos de Cuentas por Pagar.

Cubre: anulación fiscal de e-CF, CxP/606, atomicidad contable, fail-closed,
período por fecha contable, contrato delete de certificación, permisos/SoD y
aislamiento multiempresa.
"""

from contextlib import ExitStack
from unittest.mock import patch, MagicMock

import pytest

import app.services.supplier_invoice_service as mod
from app.services.supplier_invoice_service import (
    SupplierInvoiceService,
    SupplierInvoiceGuardError,
)


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


class TestFiscalVoidGuards:
    def test_received_invoice_can_be_voided_locally(self):
        data = {
            "id": "inv-rec", "status": "registrada", "ncf": "B0100000001",
            "supplierName": "Proveedor local", "date": "2026-01-10",
            "cxpStatus": "Pendiente", "cxpRemainingBalance": 100.0,
        }
        doc = _doc_ref(data)
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref, \
                 patch.object(SupplierInvoiceService, "has_payments", return_value=False), \
                 patch.object(SupplierInvoiceService, "validate_period"), \
                 patch.object(mod.DatabaseService, "get_accounting_entries", return_value=[]):
                coll_ref.return_value.document.return_value = doc
                ok, msg = SupplierInvoiceService.void(
                    owner_uid="u", invoice_id="inv-rec", reason="Duplicada",
                    voided_by="Contador", sandbox=True, company_id="c",
                )
        assert ok is True
        final = doc.update.call_args_list[-1][0][0]
        assert final["status"] == "anulada"
        assert final["cxpStatus"] == "Anulada"
        assert final["cxpRemainingBalance"] == 0.0
        assert final["voidReason"] == "Duplicada"

    def test_company_issued_accepted_ecf_void_is_blocked(self):
        data = {
            "id": "inv-ecf", "status": "emitida", "isAutoEmitted": True,
            "encf": "E410000000001", "isSyncedWithDGII": True,
            "dgiiStatus": "ACCEPTED", "date": "2026-01-10",
        }
        doc = _doc_ref(data)
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref:
                coll_ref.return_value.document.return_value = doc
                ok, msg = SupplierInvoiceService.void(
                    owner_uid="u", invoice_id="inv-ecf", reason="Error",
                    sandbox=True, company_id="c",
                )
        assert ok is False
        assert "DGII" in msg or "ANECF" in msg
        doc.update.assert_not_called()

    def test_company_issued_contingency_void_is_blocked(self):
        data = {
            "id": "inv-cont", "status": "emitida", "isAutoEmitted": True,
            "encf": "E410000000002", "emisionMode": "FALLBACK",
            "contingencyEmittedAt": "2026-01-10T10:00:00Z",
        }
        doc = _doc_ref(data)
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref:
                coll_ref.return_value.document.return_value = doc
                ok, msg = SupplierInvoiceService.void(
                    owner_uid="u", invoice_id="inv-cont", reason="Error",
                    sandbox=True, company_id="c",
                )
        assert ok is False
        assert "contingencia" in msg.lower()
        doc.update.assert_not_called()

    def test_rejected_company_issued_ecf_can_be_voided(self):
        data = {
            "id": "inv-rej", "status": "rechazado_dgii", "isAutoEmitted": True,
            "encf": "E410000000003", "dgiiError": "Rechazado",
            "date": "2026-01-10", "cxpRemainingBalance": 50.0,
        }
        doc = _doc_ref(data)
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref, \
                 patch.object(SupplierInvoiceService, "has_payments", return_value=False), \
                 patch.object(SupplierInvoiceService, "validate_period"), \
                 patch.object(mod.DatabaseService, "get_accounting_entries", return_value=[]):
                coll_ref.return_value.document.return_value = doc
                ok, _ = SupplierInvoiceService.void(
                    owner_uid="u", invoice_id="inv-rej", reason="Rechazo DGII",
                    sandbox=True, company_id="c",
                )
        assert ok is True
        assert doc.update.call_args_list[-1][0][0]["status"] == "anulada"

    def test_void_requires_reason(self):
        data = {"id": "inv-1", "status": "registrada"}
        doc = _doc_ref(data)
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref:
                coll_ref.return_value.document.return_value = doc
                ok, msg = SupplierInvoiceService.void(
                    owner_uid="u", invoice_id="inv-1", reason="   ",
                    sandbox=True, company_id="c",
                )
        assert ok is False
        assert "motivo" in msg.lower()
        doc.update.assert_not_called()


class TestBlockedOperations:
    def test_payment_on_voided_invoice_is_blocked(self):
        data = {"id": "inv-1", "status": "anulada", "cxpStatus": "Anulada", "total": 100}
        doc = _doc_ref(data)
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref:
                coll_ref.return_value.document.return_value = doc
                ok, msg = SupplierInvoiceService.save_payment(
                    owner_uid="u", invoice_id="inv-1", payment_amount=10,
                    sandbox=True, company_id="c",
                )
        assert ok is False
        assert "anulada" in msg.lower()

    def test_reissue_and_edit_of_voided_invoice_are_blocked(self):
        data = {"id": "inv-1", "status": "anulada", "cxpStatus": "Anulada"}
        doc = _doc_ref(data)
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref:
                coll_ref.return_value.document.return_value = doc
                ok = SupplierInvoiceService.update(
                    owner_uid="u", invoice_id="inv-1",
                    data={"supplierName": "Nuevo nombre"}, sandbox=True, company_id="c",
                )
                ok_corr, _ = SupplierInvoiceService.prepare_correction(
                    owner_uid="u", invoice_id="inv-1", reason="Corregir",
                    sandbox=True, company_id="c",
                )
        assert ok is False
        assert ok_corr is False
        doc.update.assert_not_called()


class TestAccountingConsistency:
    def test_void_persistence_failure_does_not_mark_invoice_voided(self):
        data = {"id": "inv-1", "status": "registrada", "date": "2026-01-10"}
        doc = _doc_ref(data)
        entry = {"id": "e-1", "status": "active", "referenceId": "inv-1", "referenceType": "expense"}
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref, \
                 patch.object(SupplierInvoiceService, "has_payments", return_value=False), \
                 patch.object(SupplierInvoiceService, "validate_period"), \
                 patch.object(mod.DatabaseService, "get_accounting_entries", return_value=[entry]), \
                 patch("app.services.accounting_service.AccountingService.void_entry", return_value=None):
                coll_ref.return_value.document.return_value = doc
                ok, msg = SupplierInvoiceService.void(
                    owner_uid="u", invoice_id="inv-1", reason="Error",
                    sandbox=True, company_id="c",
                )
        assert ok is False
        all_updates = [c[0][0] for c in doc.update.call_args_list]
        assert all(u.get("status") != "anulada" for u in all_updates)
        assert any(u.get("voidStatus") == "pending" for u in all_updates)
        assert "NO fue anulada" in msg

    def test_document_update_failure_after_entry_void_keeps_retryable_state(self):
        data = {"id": "inv-1", "status": "registrada", "date": "2026-01-10"}
        doc = _doc_ref(data)
        doc.update.side_effect = [None, Exception("firestore down")]
        entry = {"id": "e-1", "status": "active", "referenceId": "inv-1", "referenceType": "expense"}
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref, \
                 patch.object(SupplierInvoiceService, "has_payments", return_value=False), \
                 patch.object(SupplierInvoiceService, "validate_period"), \
                 patch.object(mod.DatabaseService, "get_accounting_entries", return_value=[entry]), \
                 patch("app.services.accounting_service.AccountingService.void_entry",
                       return_value={"id": "e-1", "status": "voided"}):
                coll_ref.return_value.document.return_value = doc
                ok, msg = SupplierInvoiceService.void(
                    owner_uid="u", invoice_id="inv-1", reason="Error",
                    sandbox=True, company_id="c",
                )
        assert ok is False
        assert "no se pudo marcar" in msg.lower()
        assert doc.update.call_count == 2
        assert doc.update.call_args_list[1][0][0]["status"] == "anulada"

    def test_has_payments_firestore_error_is_fail_closed(self):
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref:
                coll_ref.return_value.document.return_value.collection.return_value.limit.return_value.get.side_effect = RuntimeError("db down")
                with pytest.raises(SupplierInvoiceGuardError):
                    SupplierInvoiceService.has_payments(
                        owner_uid="u", invoice_id="inv-1", sandbox=True, company_id="c"
                    )

    def test_has_accounting_entry_firestore_error_is_fail_closed(self):
        with _patch_firebase():
            with patch.object(mod.DatabaseService, "get_accounting_entries", side_effect=RuntimeError("db down")):
                with pytest.raises(SupplierInvoiceGuardError):
                    SupplierInvoiceService.has_accounting_entry(
                        owner_uid="u", invoice_id="inv-1", sandbox=True, company_id="c"
                    )

    def test_void_validates_effective_accounting_date_not_today(self):
        data = {"id": "inv-1", "status": "registrada", "date": "2026-11-17"}
        doc = _doc_ref(data)
        entry = {"id": "e-1", "status": "active", "date": "2025-03-15",
                 "referenceId": "inv-1", "referenceType": "expense"}
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref, \
                 patch.object(SupplierInvoiceService, "has_payments", return_value=False), \
                 patch.object(SupplierInvoiceService, "validate_period") as validate_period, \
                 patch.object(mod.DatabaseService, "get_accounting_entries", return_value=[entry]), \
                 patch("app.services.accounting_service.AccountingService.void_entry",
                       return_value={"id": "e-1", "status": "voided"}):
                coll_ref.return_value.document.return_value = doc
                ok, _ = SupplierInvoiceService.void(
                    owner_uid="u", invoice_id="inv-1", reason="Error",
                    sandbox=True, company_id="c",
                )
        assert ok is True
        validate_period.assert_called_once_with("c", "2025-03-15")


class TestCertificationDeleteContract:
    def test_delete_false_is_not_counted_as_deleted(self):
        from app.services.dgii_cert_service import DgiiCertService
        run_data = {"test_set": {"blocks": [{"cases": [
            {"doc_id": "keep", "kind": "supplier_invoice"},
            {"doc_id": "remove", "kind": "supplier_invoice"},
        ]}]}}
        with patch.object(SupplierInvoiceService, "delete", side_effect=[
            (False, "No se puede eliminar una factura emitida a la DGII."),
            (True, "Factura de proveedor eliminada."),
        ]):
            deleted, skipped = DgiiCertService._delete_previous_step4_docs(
                run_data, "u", sandbox=True, company_id="c"
            )
        assert deleted == 1
        assert len(skipped) == 1
        assert "keep" in skipped[0]


class TestPermissionsAndIsolation:
    def test_can_void_supplier_invoice_permission_is_defined(self):
        from app.web.invoices import ALL_PERMISSION_KEYS, PERMISSION_GROUPS
        assert "canVoidSupplierInvoice" in ALL_PERMISSION_KEYS
        grouped = {p for group in PERMISSION_GROUPS for p in group["perms"]}
        assert "canVoidSupplierInvoice" in grouped

    def test_sod_blocks_same_user_who_managed_cxp(self):
        from app.utils.decorators import check_sod
        with patch("app.services.db_service.DatabaseService.get_sod_actions",
                   return_value=[{"permission": "canManagePurchaseCXP"}]):
            ok, msg = check_sod(
                "owner", "user-1", "canVoidSupplierInvoice",
                "inv-1", "supplier_invoice", company_id="c",
            )
        assert ok is False
        assert "segregación" in msg.lower()

    def test_company_id_is_propagated_to_collection_scope(self):
        doc = _doc_ref({"id": "inv-1"})
        with _patch_firebase():
            with patch.object(SupplierInvoiceService, "_coll_ref") as coll_ref:
                coll_ref.return_value.document.return_value.get.return_value = doc.get.return_value
                SupplierInvoiceService.get(owner_uid="u", invoice_id="inv-1", sandbox=True, company_id="company-a")
        coll_ref.assert_called_once_with(owner_uid="u", sandbox=True, company_id="company-a")


class TestReportExclusion:
    def test_voided_supplier_invoice_is_excluded_from_606(self, app):
        from app.web import reports_606 as r606
        voided = {
            "id": "voided", "status": "anulada", "cxpStatus": "Anulada",
            "ncf": "E310000000099", "supplierRnc": "131111999",
            "supplierName": "PROVEEDOR ANULADO", "date": "2026-06-01",
            "total": 999.0, "subtotal": 999.0,
        }
        valid = {
            "id": "valid", "status": "registrada",
            "ncf": "E310000000001", "supplierRnc": "131111111",
            "supplierName": "PROVEEDOR VIGENTE", "date": "2026-06-01",
            "total": 100.0, "subtotal": 100.0,
        }
        with app.test_request_context("/reports/606"):
            from flask import session, g
            session["selected_company_id"] = "c1"
            g.branch_id = None
            g.project_id = None
            with patch("app.services.received_ecf_bridge_service.ReceivedEcfBridgeService.sync_unprocessed_received_ecfs"), \
                 patch("app.services.db_service.DatabaseService.get_expenses", return_value=[]), \
                 patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_all",
                       return_value=[voided, valid]):
                items = r606._get_expenses_for_period("u", True, 2026, 6)
        ids = {item["id"] for item in items}
        assert "valid" in ids
        assert "voided" not in ids


class TestReissueGuard:
    def test_emission_block_reason_for_voided_invoice(self):
        assert "anulada" in SupplierInvoiceService.emission_block_reason(
            {"status": "anulada"}
        ).lower()
        assert "anulación en proceso" in SupplierInvoiceService.emission_block_reason(
            {"status": "registrada", "voidStatus": "pending"}
        ).lower()
        assert SupplierInvoiceService.emission_block_reason(
            {"status": "registrada", "voidStatus": ""}
        ) is None
