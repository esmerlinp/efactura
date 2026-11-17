"""Entregable 2.3 — Confirmación de servicios.

Verifica que los servicios (partidas no inventariables) requieran confirmación
antes de facturarse, y que un usuario pueda confirmar/rechazar la realización
del servicio con trazabilidad.
"""

from unittest.mock import MagicMock, patch
from contextlib import ExitStack

import pytest

import app.services.purchase_order_service as pomod
from app.services.purchase_order_service import PurchaseOrderService
from app.services.supplier_invoice_service import SupplierInvoiceService


def _delegating_tx():
    class _Tx:
        def get(self, ref):
            return ref.get()

        def set(self, ref, data, **kw):
            ref.set(data)

        def update(self, ref, data):
            ref.update(data)

        def delete(self, ref):
            ref.delete()

    def _run(func, *args, **kwargs):
        return func(_Tx(), *args, **kwargs)

    return patch("app.services.db_service.run_firestore_transaction", side_effect=_run)


def _stateful_po_ref(po):
    state = {"po": dict(po)}
    ref = MagicMock()

    def _get():
        s = MagicMock()
        s.exists = True
        s.to_dict.return_value = dict(state["po"])
        return s

    ref.get.side_effect = _get

    def _set(data):
        state["po"] = dict(data)

    ref.set.side_effect = _set
    return ref, state


class TestConfirmService:
    def _service_po(self, items):
        return {"id": "po-1", "items": items}

    def _service_item(self, iid="si-1", is_inv=False):
        return {"id": iid, "name": "Mantenimiento", "quantity": 1.0,
                "isInventoriable": is_inv, "unitPrice": 50000.0, "itbisRate": 0.18}

    def _patches(self, po_ref):
        po_coll = MagicMock()
        po_coll.document.return_value = po_ref
        return (
            patch.object(pomod, "firebase_initialized", True),
            patch.object(pomod, "db_firestore", MagicMock()),
            patch.object(pomod, "_company_coll", return_value=po_coll),
            _delegating_tx(),
        )

    def test_confirm_service(self):
        po = self._service_po([self._service_item()])
        po_ref, state = _stateful_po_ref(po)
        with ExitStack() as stack:
            for p in self._patches(po_ref):
                stack.enter_context(p)
            ok, msg = PurchaseOrderService.confirm_service(
                owner_uid="u", po_id="po-1", po_item_id="si-1", status="confirmado",
                user="Admin", user_uid="u1", notes="OK", sandbox=True, company_id="c",
            )
        assert ok is True
        item = state["po"]["items"][0]
        assert item["serviceStatus"] == "confirmado"
        assert item["serviceConfirmedByUid"] == "u1"
        assert item["serviceConfirmationNotes"] == "OK"

    def test_concurrent_confirmations_preserve_both(self):
        po = self._service_po([self._service_item("si-1"), self._service_item("si-2")])
        po_ref, state = _stateful_po_ref(po)
        with ExitStack() as stack:
            for p in self._patches(po_ref):
                stack.enter_context(p)
            ok1, _ = PurchaseOrderService.confirm_service(
                owner_uid="u", po_id="po-1", po_item_id="si-1", status="confirmado",
                user="A", user_uid="a", sandbox=True, company_id="c",
            )
            ok2, _ = PurchaseOrderService.confirm_service(
                owner_uid="u", po_id="po-1", po_item_id="si-2", status="confirmado",
                user="B", user_uid="b", sandbox=True, company_id="c",
            )
        assert ok1 is True and ok2 is True
        items = state["po"]["items"]
        assert items[0]["serviceStatus"] == "confirmado"
        assert items[1]["serviceStatus"] == "confirmado"
        assert items[0]["serviceConfirmedByUid"] == "a"
        assert items[1]["serviceConfirmedByUid"] == "b"

    def test_reject_service(self):
        po = self._service_po([self._service_item()])
        po_ref, state = _stateful_po_ref(po)
        with ExitStack() as stack:
            for p in self._patches(po_ref):
                stack.enter_context(p)
            ok, _ = PurchaseOrderService.confirm_service(
                owner_uid="u", po_id="po-1", po_item_id="si-1", status="rechazado",
                sandbox=True, company_id="c",
            )
        assert ok is True
        assert state["po"]["items"][0]["serviceStatus"] == "rechazado"

    def test_block_confirming_product(self):
        po = self._service_po([self._service_item(is_inv=True)])
        po_ref, _ = _stateful_po_ref(po)
        with ExitStack() as stack:
            for p in self._patches(po_ref):
                stack.enter_context(p)
            ok, msg = PurchaseOrderService.confirm_service(
                owner_uid="u", po_id="po-1", po_item_id="si-1", status="confirmado",
                sandbox=True, company_id="c",
            )
        assert ok is False
        assert "servicios" in msg.lower()

    def test_block_invalid_status(self):
        po = self._service_po([self._service_item()])
        po_ref, _ = _stateful_po_ref(po)
        with ExitStack() as stack:
            for p in self._patches(po_ref):
                stack.enter_context(p)
            ok, _ = PurchaseOrderService.confirm_service(
                owner_uid="u", po_id="po-1", po_item_id="si-1", status="xyz",
                sandbox=True, company_id="c",
            )
        assert ok is False

    def test_block_missing_item(self):
        po = self._service_po([self._service_item()])
        po_ref, _ = _stateful_po_ref(po)
        with ExitStack() as stack:
            for p in self._patches(po_ref):
                stack.enter_context(p)
            ok, _ = PurchaseOrderService.confirm_service(
                owner_uid="u", po_id="po-1", po_item_id="nope", status="confirmado",
                sandbox=True, company_id="c",
            )
        assert ok is False


class TestServiceConfirmationInInvoiceValidation:
    def _service_item(self, service_status="pendiente"):
        return {
            "id": "si-1", "name": "Mantenimiento", "quantity": 1.0, "isInventoriable": False,
            "unitPrice": 50000.0, "itbisRate": 0.18, "serviceStatus": service_status,
            "invoicedQuantity": 0.0,
        }

    def test_block_unconfirmed_service(self):
        po = {"items": [self._service_item("pendiente")]}
        ok, errors = SupplierInvoiceService.validate_invoice_against_po(
            po, [{"poItemId": "si-1", "quantity": 1.0}],
        )
        assert ok is False
        assert any("confirmación" in e for e in errors)

    def test_block_rejected_service(self):
        po = {"items": [self._service_item("rechazado")]}
        ok, errors = SupplierInvoiceService.validate_invoice_against_po(
            po, [{"poItemId": "si-1", "quantity": 1.0}],
        )
        assert ok is False
        assert any("rechazado" in e for e in errors)

    def test_allow_confirmed_service(self):
        po = {"items": [self._service_item("confirmado")]}
        ok, errors = SupplierInvoiceService.validate_invoice_against_po(
            po, [{"poItemId": "si-1", "quantity": 1.0}],
        )
        assert ok is True and errors == []

    def test_product_not_affected(self):
        po = {"items": [{"id": "pi-1", "name": "Producto", "quantity": 10.0,
                         "receivedQuantity": 10.0, "isInventoriable": True, "invoicedQuantity": 0.0}]}
        ok, errors = SupplierInvoiceService.validate_invoice_against_po(
            po, [{"poItemId": "pi-1", "quantity": 5.0}],
        )
        assert ok is True and errors == []
