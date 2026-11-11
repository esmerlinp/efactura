from unittest.mock import MagicMock, patch

import pytest

from app.services.db_service import DatabaseService


def _invoice(document_type="proforma", status="Pendiente de pago", paid=0.0):
    return {
        "id": "proforma-1",
        "documentType": document_type,
        "isQuotation": document_type in ("quotation", "proforma"),
        "status": status,
        "netPayable": 1000.0,
        "total": 1000.0,
        "totalPaid": paid,
        "remainingBalance": 1000.0 - paid,
        "items": [],
    }


@patch("app.services.db_service.firebase_initialized", True)
@patch("app.services.db_service.db_firestore")
def test_register_payment_allows_proforma(mock_firestore):
    invoice_ref = MagicMock()
    invoice_doc = MagicMock(exists=True)
    invoice_doc.to_dict.return_value = _invoice()
    invoice_ref.get.return_value = invoice_doc
    mock_firestore.collection.return_value.document.return_value.collection.return_value.document.return_value = invoice_ref

    payment = DatabaseService.register_invoice_payment(
        "owner-1", "proforma-1", {
            "amount": 250.0,
            "paymentMethod": "Transferencia",
            "bank": "Banco",
            "referenceNumber": "REF-1",
        }, company_id="company-1"
    )

    assert payment["amount"] == 250.0
    updates = invoice_ref.update.call_args[0][0]
    assert updates["status"] == "Aprobada"
    assert updates["paymentStatus"] == "Pago parcial"
    assert updates["totalPaid"] == 250.0
    assert updates["remainingBalance"] == 750.0


@patch("app.services.db_service.firebase_initialized", True)
@patch("app.services.db_service.db_firestore")
def test_register_payment_rejects_regular_quotation(mock_firestore):
    invoice_ref = MagicMock()
    invoice_doc = MagicMock(exists=True)
    invoice_doc.to_dict.return_value = _invoice(document_type="quotation")
    invoice_ref.get.return_value = invoice_doc
    mock_firestore.collection.return_value.document.return_value.collection.return_value.document.return_value = invoice_ref

    with pytest.raises(ValueError, match="proformas y facturas"):
        DatabaseService.register_invoice_payment(
            "owner-1", "quotation-1", {
                "amount": 100.0,
                "paymentMethod": "Transferencia",
                "bank": "Banco",
                "referenceNumber": "REF-1",
            }, company_id="company-1"
        )


@patch("app.services.db_service.firebase_initialized", True)
@patch("app.services.db_service.db_firestore")
def test_register_payment_rejects_overpayment(mock_firestore):
    invoice_ref = MagicMock()
    invoice_doc = MagicMock(exists=True)
    invoice_doc.to_dict.return_value = _invoice(paid=900.0)
    invoice_ref.get.return_value = invoice_doc
    mock_firestore.collection.return_value.document.return_value.collection.return_value.document.return_value = invoice_ref

    with pytest.raises(ValueError, match="excede el saldo"):
        DatabaseService.register_invoice_payment(
            "owner-1", "proforma-1", {
                "amount": 101.0,
                "paymentMethod": "Transferencia",
                "bank": "Banco",
                "referenceNumber": "REF-1",
            }, company_id="company-1"
        )
