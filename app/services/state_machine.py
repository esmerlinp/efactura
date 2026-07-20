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


OFFBOARDING_STATES = {
    "draft": {
        "label": "Borrador",
        "transitions": ["pending_supervisor_approval", "cancelled"],
        "color": "secondary",
        "description": "Inicia el proceso de offboarding. Complete los datos preliminares antes de enviar a revisión.",
    },
    "pending_supervisor_approval": {
        "label": "Pendiente aprobación supervisor",
        "transitions": ["pending_hr_approval", "rejected", "cancelled"],
        "color": "info",
        "description": "Enviar al supervisor inmediato para que revise y apruebe la solicitud de desvinculación.",
    },
    "pending_hr_approval": {
        "label": "Pendiente aprobación RRHH",
        "transitions": ["pending_settlement", "rejected", "cancelled"],
        "color": "warning",
        "description": "El supervisor aprobó. Ahora RRHH debe revisar y validar la solicitud.",
    },
    "approved": {
        "label": "Aprobada",
        "transitions": ["pending_settlement", "cancelled"],
        "color": "primary",
        "description": "Solicitud aprobada por RRHH. Estado histórico — la transición a Pendiente liquidación es automática.",
    },
    "pending_settlement": {
        "label": "Pendiente liquidación",
        "transitions": ["pending_assets", "pending_payment", "cancelled"],
        "color": "info",
        "description": "Calcular liquidación: cesantía, preaviso, vacaciones proporcionales y salarios adeudados.",
    },
    "pending_assets": {
        "label": "Pendiente activos",
        "transitions": ["pending_payment", "cancelled"],
        "color": "warning",
        "description": "Gestionar devolución de activos asignados: laptop, teléfono, uniformes, accesos, etc.",
    },
    "pending_payment": {
        "label": "Pendiente pago",
        "transitions": ["pending_documents", "cancelled"],
        "color": "warning",
        "description": "Procesar el pago de la liquidación y cualquier monto pendiente con el empleado.",
    },
    "pending_documents": {
        "label": "Pendiente documentos",
        "transitions": ["pending_tss", "cancelled"],
        "color": "info",
        "description": "Preparar y gestionar la firma de documentos legales de desvinculación (finiquito, carta de renuncia, etc.).",
    },
    "pending_tss": {
        "label": "Pendiente baja TSS",
        "transitions": ["completed", "cancelled"],
        "color": "info",
        "description": "Realizar la baja del empleado en TSS (AFP, SFS, ARL) y notificar a las entidades correspondientes.",
    },
    "completed": {
        "label": "Completada",
        "transitions": [],
        "color": "success",
        "description": "Proceso de offboarding finalizado. El empleado queda marcado como inactivo en el sistema.",
    },
    "cancelled": {
        "label": "Cancelada",
        "transitions": [],
        "color": "danger",
        "description": "Cancela la solicitud. El empleado permanece activo y el proceso se descarta.",
    },
    "rejected": {
        "label": "Rechazada",
        "transitions": [],
        "color": "danger",
        "description": "Solicitud rechazada. El empleado continúa activo y no se realiza ninguna acción adicional.",
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

    @staticmethod
    def for_offboarding():
        return StateMachineValidator(OFFBOARDING_STATES)
