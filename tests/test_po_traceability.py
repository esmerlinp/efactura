"""Entregable 2.5 — Trazabilidad completa OC → recepción → factura → pago.

Verifica que el resumen de trazabilidad consulte los registros originales y
calcule correctamente solicitado, recibido, facturado, pagado y pendiente,
respetando company_id y excluyendo facturas anuladas y pagos no aprobados.
"""

from unittest.mock import patch

from app.services.purchase_order_service import PurchaseOrderService


def _po(total=100000.0, items=None):
    return {
        "id": "po-1", "poNumber": "OC-00125", "supplierName": "Proveedor A",
        "status": "recibida_completa", "total": total,
        "items": items or [{"id": "i1", "name": "Item", "quantity": 10.0,
                            "receivedQuantity": 10.0, "unitPrice": 10000.0,
                            "discount": 0.0, "isInventoriable": True}],
    }


def _invoice(iid, total):
    return {"id": iid, "invoiceNumber": f"FI-{iid}", "total": total, "cxpStatus": "Pendiente"}


class TestGetTraceability:
    def test_full_traceability(self):
        po = _po(total=100000.0)
        invoices = [_invoice("inv-a", 60000.0), _invoice("inv-b", 40000.0)]
        payments_by_inv = {
            "inv-a": [{"amount": 60000.0, "approvalStatus": "approved", "approvedBy": "A"}],
            "inv-b": [{"amount": 10000.0, "approvalStatus": "approved", "approvedBy": "B"}],
        }
        with patch.object(PurchaseOrderService, "get_purchase_order", return_value=po), \
             patch("app.services.goods_receipt_service.GoodsReceiptService.get_receipts_by_po", return_value=[{"id": "r1"}]), \
             patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_by_po", return_value=invoices), \
             patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_payments",
                   side_effect=lambda owner_uid=None, invoice_id=None, sandbox=True, company_id=None: payments_by_inv.get(invoice_id, [])):
            t = PurchaseOrderService.get_traceability(owner_uid="u", po_id="po-1", sandbox=True, company_id="c")
        assert t["requested"] == 100000.0
        assert t["receivedAmount"] == 100000.0
        assert t["invoiced"] == 100000.0
        assert t["paid"] == 70000.0
        assert t["pending"] == 30000.0
        assert len(t["invoices"]) == 2
        assert t["invoices"][0]["paidAmount"] == 60000.0

    def test_only_approved_payments_counted(self):
        po = _po(total=1000.0)
        invoices = [_invoice("inv-a", 1000.0)]
        payments = [
            {"amount": 300.0, "approvalStatus": "approved"},
            {"amount": 200.0, "approvalStatus": "pending"},
            {"amount": 100.0, "approvalStatus": "rejected"},
        ]
        with patch.object(PurchaseOrderService, "get_purchase_order", return_value=po), \
             patch("app.services.goods_receipt_service.GoodsReceiptService.get_receipts_by_po", return_value=[]), \
             patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_by_po", return_value=invoices), \
             patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_payments", return_value=payments):
            t = PurchaseOrderService.get_traceability(owner_uid="u", po_id="po-1", sandbox=True, company_id="c")
        assert t["paid"] == 300.0
        assert t["pending"] == 700.0

    def test_voided_invoices_excluded(self):
        po = _po(total=1000.0)
        invoices = [
            _invoice("inv-a", 1000.0),
            {"id": "inv-voided", "total": 500.0, "status": "anulada", "cxpStatus": "Anulada"},
        ]
        with patch.object(PurchaseOrderService, "get_purchase_order", return_value=po), \
             patch("app.services.goods_receipt_service.GoodsReceiptService.get_receipts_by_po", return_value=[]), \
             patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_by_po", return_value=invoices), \
             patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_payments", return_value=[]):
            t = PurchaseOrderService.get_traceability(owner_uid="u", po_id="po-1", sandbox=True, company_id="c")
        assert t["invoiced"] == 1000.0
        assert len(t["invoices"]) == 1

    def test_company_id_propagated(self):
        po = _po(total=1000.0)
        invoices = [_invoice("inv-a", 1000.0)]
        with patch.object(PurchaseOrderService, "get_purchase_order", return_value=po) as get_po, \
             patch("app.services.goods_receipt_service.GoodsReceiptService.get_receipts_by_po", return_value=[]) as get_rec, \
             patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_by_po", return_value=invoices) as get_inv, \
             patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_payments", return_value=[]) as get_pay:
            PurchaseOrderService.get_traceability(owner_uid="u", po_id="po-1", sandbox=True, company_id="company-a")
        get_po.assert_called_once()
        assert get_rec.call_args.kwargs["company_id"] == "company-a"
        assert get_inv.call_args.kwargs["company_id"] == "company-a"
        assert get_pay.call_args.kwargs["company_id"] == "company-a"


class TestReceivedAmountValuation:
    def _item(self, qty=10.0, received=10.0, price=100.0, discount=0.0, itbis=0.18):
        return {"id": "i1", "name": "Item", "quantity": qty, "receivedQuantity": received,
                "unitPrice": price, "discount": discount, "itbisRate": itbis,
                "isInventoriable": True}

    def _run(self, po):
        with patch.object(PurchaseOrderService, "get_purchase_order", return_value=po), \
             patch("app.services.goods_receipt_service.GoodsReceiptService.get_receipts_by_po", return_value=[]), \
             patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_by_po", return_value=[]), \
             patch("app.services.supplier_invoice_service.SupplierInvoiceService.get_payments", return_value=[]):
            return PurchaseOrderService.get_traceability(owner_uid="u", po_id="po-1", sandbox=True, company_id="c")

    def test_received_amount_is_gross_including_itbis(self):
        # 10 × 100 × 1.0 × 1.18 = 1180
        po = {"id": "po-1", "total": 1180.0, "items": [self._item(price=100.0, itbis=0.18)]}
        t = self._run(po)
        assert t["requested"] == 1180.0
        assert t["receivedAmount"] == 1180.0

    def test_received_amount_exempt_item(self):
        # exento: 10 × 100 × 1.0 × 1.0 = 1000
        po = {"id": "po-1", "total": 1000.0, "items": [self._item(price=100.0, itbis=0.0)]}
        t = self._run(po)
        assert t["receivedAmount"] == 1000.0

    def test_received_amount_with_discount(self):
        # 10 × 100 × 0.9 × 1.18 = 1062
        po = {"id": "po-1", "total": 1062.0, "items": [self._item(price=100.0, discount=10.0, itbis=0.18)]}
        t = self._run(po)
        assert t["receivedAmount"] == 1062.0

    def test_received_amount_partial_receipt(self):
        # recibido 5 de 10: 5 × 100 × 1.0 × 1.18 = 590
        po = {"id": "po-1", "total": 1180.0,
              "items": [self._item(qty=10.0, received=5.0, price=100.0, itbis=0.18)]}
        t = self._run(po)
        assert t["receivedAmount"] == 590.0
