"""Fase 2 — Integración compras → recepciones → facturas → CxP.

Valida que la factura de proveedor no exceda lo solicitado/recibido, impide
facturas duplicadas por la misma orden de compra, y acumula las cantidades
facturadas en las partidas de la OC.
"""

from unittest.mock import MagicMock, patch
from contextlib import ExitStack

import pytest

import app.services.supplier_invoice_service as mod
from app.services.supplier_invoice_service import SupplierInvoiceService


def _po_item(pid="pi-1", qty=10.0, received=10.0, invoiced=0.0, is_inv=True):
    return {
        "id": pid, "name": "Item", "quantity": qty, "receivedQuantity": received,
        "invoicedQuantity": invoiced, "isInventoriable": is_inv,
    }


class TestValidateInvoiceAgainstPo:
    def test_ok_within_received(self):
        po = {"items": [_po_item(received=10.0, invoiced=0.0)]}
        ok, errors = SupplierInvoiceService.validate_invoice_against_po(po, [{"poItemId": "pi-1", "quantity": 5.0}])
        assert ok is True and errors == []

    def test_block_over_invoicing(self):
        po = {"items": [_po_item(received=10.0, invoiced=8.0)]}
        ok, errors = SupplierInvoiceService.validate_invoice_against_po(po, [{"poItemId": "pi-1", "quantity": 5.0}])
        assert ok is False
        assert any("excede" in e for e in errors)

    def test_block_duplicate_full_invoice(self):
        po = {"items": [_po_item(received=10.0, invoiced=10.0)]}
        ok, _ = SupplierInvoiceService.validate_invoice_against_po(po, [{"poItemId": "pi-1", "quantity": 10.0}])
        assert ok is False

    def test_block_item_not_in_po(self):
        po = {"items": [_po_item(pid="pi-1")]}
        ok, errors = SupplierInvoiceService.validate_invoice_against_po(po, [{"poItemId": "pi-999", "quantity": 1.0}])
        assert ok is False
        assert any("no pertenece" in e for e in errors)

    def test_service_uses_ordered_not_received(self):
        po = {"items": [_po_item(qty=10.0, received=0.0, invoiced=3.0, is_inv=False)]}
        ok, _ = SupplierInvoiceService.validate_invoice_against_po(po, [{"poItemId": "pi-1", "quantity": 8.0}])
        assert ok is False

    def test_ignores_items_without_po_item_id(self):
        po = {"items": [_po_item(received=10.0, invoiced=10.0)]}
        ok, _ = SupplierInvoiceService.validate_invoice_against_po(po, [{"quantity": 999.0}])
        assert ok is True


class TestRecordInvoiceQuantities:
    def test_accumulates_invoiced_quantity(self):
        po = {"items": [_po_item(received=10.0, invoiced=2.0)]}
        with patch("app.services.purchase_order_service.PurchaseOrderService.get_purchase_order", return_value=po), \
             patch("app.services.purchase_order_service.PurchaseOrderService.save_purchase_order") as save:
            SupplierInvoiceService.record_invoice_quantities(
                owner_uid="u", po_id="po-1",
                invoice_items=[{"poItemId": "pi-1", "quantity": 5.0}],
                sandbox=True, company_id="c",
            )
        save.assert_called_once()
        saved_po = save.call_args.kwargs["po_dict"]
        assert saved_po["items"][0]["invoicedQuantity"] == 7.0


class TestCreateWiring:
    def _delegating_tx(self):
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

    @staticmethod
    def _snap(data):
        s = MagicMock()
        s.exists = True
        s.to_dict.return_value = data
        return s

    def _po_ref(self, po):
        ref = MagicMock()
        ref.get.return_value = self._snap(po)
        return ref

    def _create_patches(self, po_ref, inv_ref):
        po_coll = MagicMock()
        po_coll.document.return_value = po_ref
        inv_coll = MagicMock()
        inv_coll.document.return_value = inv_ref
        return (
            patch.object(mod, "firebase_initialized", True),
            patch.object(mod, "db_firestore", MagicMock()),
            patch.object(SupplierInvoiceService, "validate_period"),
            patch.object(mod, "_company_coll", return_value=po_coll),
            patch.object(SupplierInvoiceService, "_coll_ref", return_value=inv_coll),
            self._delegating_tx(),
        )

    def test_create_raises_on_over_invoice(self):
        data = {"date": "2026-06-15", "total": 100.0, "poId": "po-1",
                "items": [{"poItemId": "pi-1", "quantity": 10.0, "unitPrice": 10.0, "itbisRate": 0.18}]}
        po = {"items": [_po_item(received=10.0, invoiced=10.0)]}
        po_ref = self._po_ref(po)
        inv_ref = MagicMock()
        with ExitStack() as stack:
            for p in self._create_patches(po_ref, inv_ref):
                stack.enter_context(p)
            with pytest.raises(ValueError):
                SupplierInvoiceService.create(owner_uid="u", data=data, sandbox=True, company_id="c")
        inv_ref.set.assert_not_called()
        po_ref.set.assert_not_called()

    def test_create_writes_invoice_and_updates_po_atomically(self):
        data = {"date": "2026-06-15", "total": 100.0, "poId": "po-1",
                "items": [{"poItemId": "pi-1", "quantity": 5.0, "unitPrice": 10.0, "itbisRate": 0.18}]}
        po = {"items": [{"id": "pi-1", "name": "Item", "quantity": 10.0, "receivedQuantity": 10.0,
                         "invoicedQuantity": 0.0, "isInventoriable": True,
                         "unitPrice": 10.0, "itbisRate": 0.18}]}
        po_ref = self._po_ref(po)
        inv_ref = MagicMock()
        with ExitStack() as stack:
            for p in self._create_patches(po_ref, inv_ref):
                stack.enter_context(p)
            result = SupplierInvoiceService.create(owner_uid="u", data=data, sandbox=True, company_id="c")
        assert result["id"]
        inv_ref.set.assert_called_once()
        po_ref.set.assert_called_once()
        saved_po = po_ref.set.call_args[0][0]
        assert saved_po["items"][0]["invoicedQuantity"] == 5.0


class TestValidateInvoicePrices:
    @staticmethod
    def _po_item_full(unit_price=100.0, itbis=0.18, **kw):
        d = _po_item(**kw)
        d["unitPrice"] = unit_price
        d["itbisRate"] = itbis
        return d

    def test_no_differences(self):
        po = {"items": [self._po_item_full()]}
        items = [{"poItemId": "pi-1", "unitPrice": 100.0, "itbisRate": 0.18, "quantity": 1.0}]
        ok, diffs = SupplierInvoiceService.validate_invoice_prices(po, items)
        assert ok is True and diffs == []

    def test_price_within_tolerance_is_warning(self):
        po = {"items": [self._po_item_full(unit_price=100.0)]}
        items = [{"poItemId": "pi-1", "unitPrice": 101.0, "itbisRate": 0.18, "quantity": 1.0}]
        ok, diffs = SupplierInvoiceService.validate_invoice_prices(po, items)
        assert ok is True
        assert any(d["severity"] == "warning" and d["field"] == "unitPrice" for d in diffs)

    def test_price_beyond_tolerance_is_error(self):
        po = {"items": [self._po_item_full(unit_price=100.0)]}
        items = [{"poItemId": "pi-1", "unitPrice": 110.0, "itbisRate": 0.18, "quantity": 1.0}]
        ok, diffs = SupplierInvoiceService.validate_invoice_prices(po, items)
        assert ok is False
        assert any(d["severity"] == "error" and d["field"] == "unitPrice" for d in diffs)

    def test_itbis_beyond_tolerance_is_error(self):
        po = {"items": [self._po_item_full(unit_price=100.0, itbis=0.18)]}
        items = [{"poItemId": "pi-1", "unitPrice": 100.0, "itbisRate": 0.16, "quantity": 1.0}]
        ok, diffs = SupplierInvoiceService.validate_invoice_prices(po, items)
        assert ok is False
        assert any(d["severity"] == "error" and d["field"] == "itbisRate" for d in diffs)

    def test_custom_tolerances(self):
        po = {"items": [self._po_item_full(unit_price=100.0)]}
        items = [{"poItemId": "pi-1", "unitPrice": 110.0, "itbisRate": 0.18, "quantity": 1.0}]
        ok, _ = SupplierInvoiceService.validate_invoice_prices(po, items, tolerances={"price_relative": 0.15})
        assert ok is True



class TestMultiplePartialInvoices:
    def test_multiple_partial_invoices_do_not_exceed_available(self):
        po = {"items": [_po_item(received=10.0, invoiced=0.0)]}
        with patch("app.services.purchase_order_service.PurchaseOrderService.get_purchase_order", return_value=po), \
             patch("app.services.purchase_order_service.PurchaseOrderService.save_purchase_order"):
            ok1, _ = SupplierInvoiceService.validate_invoice_against_po(po, [{"poItemId": "pi-1", "quantity": 5.0}])
            assert ok1 is True
            SupplierInvoiceService.record_invoice_quantities(
                owner_uid="u", po_id="po-1",
                invoice_items=[{"poItemId": "pi-1", "quantity": 5.0}],
                sandbox=True, company_id="c",
            )
            ok2, _ = SupplierInvoiceService.validate_invoice_against_po(po, [{"poItemId": "pi-1", "quantity": 5.0}])
            assert ok2 is True
            SupplierInvoiceService.record_invoice_quantities(
                owner_uid="u", po_id="po-1",
                invoice_items=[{"poItemId": "pi-1", "quantity": 5.0}],
                sandbox=True, company_id="c",
            )
            ok3, _ = SupplierInvoiceService.validate_invoice_against_po(po, [{"poItemId": "pi-1", "quantity": 5.0}])
            assert ok3 is False
