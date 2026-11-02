"""Conciliaciones explicables del IT-1 contra 606, 607 y fuentes auxiliares."""

from app.fiscal_forms.common import ReconciliationDifference, money


def _difference(source, field, declared, source_value, document_ids=()):
    declared_amount = money(declared)
    source_amount = money(source_value)
    return ReconciliationDifference(source, field, str(declared_amount), str(source_amount), str(declared_amount - source_amount), tuple(document_ids))


def reconcile_it1(data, report_606=None, report_607=None, dga=None, previous=None):
    differences = []
    annex = data.get("annex_a", {}).get("values", {})
    form = data.get("it1", {}).get("values", {})
    report_606 = report_606 or {}
    report_607 = report_607 or {}
    differences.append(_difference("607", "total_operations", form.get("1", 0), report_607.get("total_subtotal", 0), report_607.get("document_ids", [])))
    differences.append(_difference("606", "itbis_deducible", annex.get("56", 0), report_606.get("itbis_deducible", 0), report_606.get("document_ids", [])))
    differences.append(_difference("606", "itbis_retained", form.get("60", 0), report_606.get("itbis_retained", 0), report_606.get("document_ids", [])))
    if dga is not None:
        differences.append(_difference("DGA", "itbis_importations", annex.get("56", 0), dga.get("itbis_importations", 0), dga.get("document_ids", [])))
    if previous is not None:
        differences.append(_difference("previous_it1", "prior_balance", form.get("29", 0), previous.get("new_balance", 0), previous.get("document_ids", [])))
    return [difference.__dict__ for difference in differences if money(difference.difference) != 0]
