from app.services.tax_dashboard_service import build_tax_estimate


def test_tax_estimate_filters_period_and_approved_documents():
    result = build_tax_estimate(
        [
            {"date": "2026-11-10", "status": "Emitida", "subtotal": 1000, "totalITBIS": 180},
            {"date": "2026-10-10", "status": "Emitida", "subtotal": 900, "totalITBIS": 162},
        ],
        [
            {"date": "2026-11-05", "approvalStatus": "Aprobado", "amount": 500, "itbisAmount": 90, "isITBISDeductible": True},
            {"date": "2026-11-06", "approvalStatus": "Pendiente", "amount": 200, "itbisAmount": 36, "isITBISDeductible": True},
        ],
        2026,
        11,
    )

    assert result["sales_net"] == 1000
    assert result["expenses_net"] == 410
    assert result["itbis_to_pay"] == 90
    assert result["isr_estimated"] == 159.3
