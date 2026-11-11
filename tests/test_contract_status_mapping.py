from app.models.recurring_contract import RecurringContractStatus


def test_legacy_form_statuses_map_to_v2_statuses():
    status_map = {
        "borrador": RecurringContractStatus.DRAFT,
        "pendiente_de_aprobación": RecurringContractStatus.PENDING_APPROVAL,
        "pendiente_de_aprobacion": RecurringContractStatus.PENDING_APPROVAL,
        "activo": RecurringContractStatus.ACTIVE,
        "suspendido": RecurringContractStatus.SUSPENDED,
        "cancelado": RecurringContractStatus.CANCELLED,
        "expirado": RecurringContractStatus.EXPIRED,
    }
    assert status_map["activo"] == RecurringContractStatus.ACTIVE
    assert status_map["borrador"] == RecurringContractStatus.DRAFT
    assert status_map["pendiente_de_aprobación"] == RecurringContractStatus.PENDING_APPROVAL
