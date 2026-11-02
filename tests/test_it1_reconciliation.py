from app.services.it1_reconciliation_service import reconcile_it1


def test_reconciliation_returns_explainable_document_differences():
    result = reconcile_it1({"annex_a": {"values": {"56": "100"}}, "it1": {"values": {"1": "1000", "60": "20"}}}, report_606={"itbis_deducible": 90, "itbis_retained": 25, "document_ids": ["exp-1"]}, report_607={"total_subtotal": 950, "document_ids": ["inv-1"]})
    assert {item["source"] for item in result} == {"607", "606"}
    assert all(item["document_ids"] for item in result)
