INVOICE_STATES = {
    "Borrador": {
        "label": "Borrador",
        "transitions": ["Emitida", "Anulada"],
        "color": "secondary",
    },
    "Emitida": {
        "label": "Emitida",
        "transitions": ["Parcialmente Cobrada", "Vencida", "Anulada", "Nota de Crédito"],
        "color": "primary",
    },
    "Parcialmente Cobrada": {
        "label": "Parcialmente Cobrada",
        "transitions": ["Cobrada", "Vencida"],
        "color": "info",
    },
    "Vencida": {
        "label": "Vencida",
        "transitions": ["Parcialmente Cobrada", "Cobrada", "Castigada", "Anulada"],
        "color": "warning",
    },
    "Cobrada": {
        "label": "Cobrada",
        "transitions": [],
        "color": "success",
    },
    "Anulada": {
        "label": "Anulada",
        "transitions": [],
        "color": "danger",
    },
    "Castigada": {
        "label": "Castigada",
        "transitions": [],
        "color": "dark",
    },
}

EXPENSE_STATES = {
    "Borrador": {
        "label": "Borrador",
        "transitions": ["Emitida", "Anulada"],
        "color": "secondary",
    },
    "Emitida": {
        "label": "Emitida",
        "transitions": ["Pagado", "Vencido"],
        "color": "primary",
    },
    "Pagado": {
        "label": "Pagado",
        "transitions": [],
        "color": "success",
    },
    "Vencido": {
        "label": "Vencido",
        "transitions": ["Pagado", "Anulada"],
        "color": "warning",
    },
    "Anulada": {
        "label": "Anulada",
        "transitions": [],
        "color": "danger",
    },
}

PURCHASE_ORDER_STATES = {
    "borrador": {
        "label": "Borrador",
        "transitions": ["aprobada", "cancelada"],
    },
    "aprobada": {
        "label": "Aprobada",
        "transitions": ["parcialmente_recibida", "totalmente_recibida", "cancelada"],
    },
    "parcialmente_recibida": {
        "label": "Parcialmente Recibida",
        "transitions": ["totalmente_recibida", "cancelada"],
    },
    "totalmente_recibida": {
        "label": "Totalmente Recibida",
        "transitions": ["facturada", "cancelada"],
    },
    "facturada": {
        "label": "Facturada",
        "transitions": [],
    },
    "cancelada": {
        "label": "Cancelada",
        "transitions": [],
    },
}

MASS_ACTION_STATES = {
    "draft": {
        "label": "Borrador",
        "transitions": ["processing", "failed"],
        "color": "secondary",
    },
    "processing": {
        "label": "Procesando",
        "transitions": ["completed", "partial", "failed"],
        "color": "info",
    },
    "completed": {
        "label": "Completada",
        "transitions": [],
        "color": "success",
    },
    "partial": {
        "label": "Parcial",
        "transitions": [],
        "color": "warning",
    },
    "failed": {
        "label": "Fallida",
        "transitions": ["draft"],
        "color": "danger",
    },
}

JOURNAL_ENTRY_STATES = {
    "active": {
        "label": "Activo",
        "transitions": ["voided"],
    },
    "voided": {
        "label": "Anulado",
        "transitions": [],
    },
}


class StateMachineValidator:
    def __init__(self, state_map: dict):
        self.state_map = state_map

    def can_transition(self, current_state: str, new_state: str) -> bool:
        state_config = self.state_map.get(current_state)
        if not state_config:
            return False
        return new_state in state_config["transitions"]

    def get_allowed_transitions(self, current_state: str) -> list:
        state_config = self.state_map.get(current_state)
        if not state_config:
            return []
        return state_config["transitions"]

    def validate_transition(self, current_state: str, new_state: str, entity_type: str = "documento"):
        if not self.can_transition(current_state, new_state):
            allowed = self.get_allowed_transitions(current_state)
            allowed_str = ", ".join(allowed) if allowed else "ninguna"
            raise ValueError(
                f"Transición inválida para {entity_type}: "
                f"'{current_state}' → '{new_state}'. "
                f"Transiciones permitidas: {allowed_str}."
            )
        return True

    @staticmethod
    def for_invoices():
        return StateMachineValidator(INVOICE_STATES)

    @staticmethod
    def for_expenses():
        return StateMachineValidator(EXPENSE_STATES)

    @staticmethod
    def for_purchase_orders():
        return StateMachineValidator(PURCHASE_ORDER_STATES)

    @staticmethod
    def for_journal_entries():
        return StateMachineValidator(JOURNAL_ENTRY_STATES)

    @staticmethod
    def for_mass_actions():
        return StateMachineValidator(MASS_ACTION_STATES)
