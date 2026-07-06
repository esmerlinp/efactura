import uuid
from datetime import datetime, timezone
from collections import defaultdict
from app.services.db_service import DatabaseService

ACCOUNT_GROUPS = {
    "activos": {"label": "Activos", "order": 1, "nature": "deudora"},
    "pasivos": {"label": "Pasivos", "order": 2, "nature": "acreedora"},
    "patrimonio": {"label": "Patrimonio", "order": 3, "nature": "acreedora"},
    "ingresos": {"label": "Ingresos", "order": 4, "nature": "acreedora"},
    "costos": {"label": "Costos", "order": 5, "nature": "deudora"},
    "gastos": {"label": "Gastos", "order": 6, "nature": "deudora"},
    "cuentas_orden": {"label": "Cuentas de Orden", "order": 7, "nature": "deudora"},
}

NATURE_DEBIT_INCREASE = {"activos": True, "costos": True, "gastos": True, "cuentas_orden": True}
NATURE_CREDIT_INCREASE = {"pasivos": True, "patrimonio": True, "ingresos": True}


def _default_chart_of_accounts():
    return [
        # ═══════════════════════════════════════════════
        # 1 — ACTIVOS
        # ═══════════════════════════════════════════════
        {"code": "1", "name": "Activos", "group": "activos", "type": "control", "parentId": None, "level": 0, "orderIdx": 1, "nature": "deudora", "description": "Bajo esta categoría se encuentran los activos que tiene la empresa", "isSystem": True},

        # 1.1 — Activos Corrientes
        {"code": "1.1", "name": "Activos corrientes", "group": "activos", "type": "control", "parentId": None, "level": 1, "orderIdx": 1, "nature": "deudora", "description": "", "isSystem": True},

        # 1.1.1 — Efectivo y equivalentes de efectivo
        {"code": "1.1.1", "name": "Efectivo y equivalentes de efectivo", "group": "activos", "type": "control", "parentId": None, "level": 2, "orderIdx": 1, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "1.1.1.01", "name": "Caja", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 1, "nature": "deudora", "usage": "efectivo", "description": "", "isSystem": False},
        {"code": "1.1.1.02", "name": "Caja chica", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 2, "nature": "deudora", "usage": "efectivo", "description": "", "isSystem": False},
        {"code": "1.1.1.03", "name": "Caja general", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 3, "nature": "deudora", "usage": "efectivo", "description": "", "isSystem": False},

        # 1.1.2 — Bancos
        {"code": "1.1.2", "name": "Bancos", "group": "activos", "type": "control", "parentId": None, "level": 2, "orderIdx": 2, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "1.1.2.01", "name": "Banco 1", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 1, "nature": "deudora", "usage": "banco", "description": "", "isSystem": False},

        # 1.1.3 — Deudores comerciales y otras cuentas por cobrar
        {"code": "1.1.3", "name": "Deudores comerciales y otras cuentas por cobrar", "group": "activos", "type": "control", "parentId": None, "level": 2, "orderIdx": 3, "nature": "deudora", "description": "", "isSystem": True},

        # 1.1.3.1 — Cuentas por cobrar comerciales
        {"code": "1.1.3.1", "name": "Cuentas por cobrar comerciales", "group": "activos", "type": "control", "parentId": None, "level": 3, "orderIdx": 1, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "1.1.3.1.01", "name": "Cuentas por cobrar clientes", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "deudora", "usage": "cxc", "description": "", "isSystem": False},
        {"code": "1.1.3.1.02", "name": "Deterioro acumulado de cuentas por cobrar", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},

        # 1.1.3.2 — Cuentas por cobrar a socios y accionistas
        {"code": "1.1.3.2", "name": "Cuentas por cobrar a socios y accionistas", "group": "activos", "type": "control", "parentId": None, "level": 3, "orderIdx": 2, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "1.1.3.2.01", "name": "Cuentas por cobrar a socios", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "1.1.3.2.02", "name": "Cuentas por cobrar a accionistas", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},

        # 1.1.3.3 — Avances y anticipos entregados
        {"code": "1.1.3.3", "name": "Avances y anticipos entregados", "group": "activos", "type": "control", "parentId": None, "level": 3, "orderIdx": 3, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "1.1.3.3.01", "name": "Avances y anticipos a proveedores", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "deudora", "usage": "anticipos_entregados", "description": "", "isSystem": False},
        {"code": "1.1.3.3.02", "name": "Avances y anticipos a empleados", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "deudora", "usage": "anticipos_entregados", "description": "", "isSystem": False},

        # 1.1.3.4 — Otros deudores y cuentas por cobrar
        {"code": "1.1.3.4", "name": "Otros deudores y cuentas por cobrar", "group": "activos", "type": "control", "parentId": None, "level": 3, "orderIdx": 4, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "1.1.3.4.01", "name": "Cuentas por cobrar empleados", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "1.1.3.4.02", "name": "Préstamos a terceros", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "1.1.3.4.03", "name": "Otras cuentas por cobrar", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 3, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "1.1.3.4.04", "name": "Pagos por cuenta de terceros", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 4, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "1.1.3.4.05", "name": "Devoluciones a proveedores", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 5, "nature": "deudora", "usage": "devoluciones_proveedores", "description": "", "isSystem": False},
        {"code": "1.1.3.4.06", "name": "Intereses por cobrar", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 6, "nature": "deudora", "usage": None, "description": "", "isSystem": False},

        # 1.1.4 — Inversiones financieras a corto plazo
        {"code": "1.1.4", "name": "Inversiones financieras a corto plazo", "group": "activos", "type": "control", "parentId": None, "level": 2, "orderIdx": 4, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "1.1.4.01", "name": "Acciones de otras compañías", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "1.1.4.02", "name": "Depósitos a plazos fijos", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "1.1.4.03", "name": "Otras inversiones", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 3, "nature": "deudora", "usage": None, "description": "", "isSystem": False},

        # 1.1.5 — Activos por impuestos corrientes
        {"code": "1.1.5", "name": "Activos por impuestos corrientes", "group": "activos", "type": "control", "parentId": None, "level": 2, "orderIdx": 5, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "1.1.5.01", "name": "Impuestos a favor", "group": "activos", "type": "control", "parentId": None, "level": 3, "orderIdx": 1, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "1.1.5.01.01", "name": "ITBIS a favor", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "deudora", "usage": "impuesto_a_favor", "description": "", "isSystem": False},
        {"code": "1.1.5.01.02", "name": "ISC a favor", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "deudora", "usage": "impuesto_a_favor", "description": "", "isSystem": False},
        {"code": "1.1.5.01.03", "name": "Otro tipo de impuesto a favor", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 3, "nature": "deudora", "usage": "otro_impuesto_a_favor", "description": "", "isSystem": False},

        # 1.1.6 — Activos por retenciones a favor
        {"code": "1.1.6", "name": "Activos por retenciones a favor", "group": "activos", "type": "control", "parentId": None, "level": 2, "orderIdx": 6, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "1.1.6.01", "name": "Retenciones a favor", "group": "activos", "type": "control", "parentId": None, "level": 3, "orderIdx": 1, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "1.1.6.01.01", "name": "Retención de ITBIS a favor", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "deudora", "usage": "retenciones_a_favor", "description": "", "isSystem": False},
        {"code": "1.1.6.01.02", "name": "Retención de ISR a favor", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "deudora", "usage": "retenciones_a_favor", "description": "", "isSystem": False},
        {"code": "1.1.6.01.03", "name": "Otro tipo de retención a favor", "group": "activos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 3, "nature": "deudora", "usage": "otro_retencion_a_favor", "description": "", "isSystem": False},

        # 1.1.7 — Inventarios
        {"code": "1.1.7", "name": "Inventarios", "group": "activos", "type": "control", "parentId": None, "level": 2, "orderIdx": 7, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "1.1.7.01", "name": "Inventario de mercancías", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 1, "nature": "deudora", "usage": "inventario", "description": "", "isSystem": False},

        # 1.1.8 — Activos pagados por anticipado
        {"code": "1.1.8", "name": "Activos pagados por anticipado", "group": "activos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 8, "nature": "deudora", "usage": None, "description": "", "isSystem": False},

        # 1.1.9 — Otros activos corrientes
        {"code": "1.1.9", "name": "Otros activos corrientes", "group": "activos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 9, "nature": "deudora", "usage": None, "description": "", "isSystem": False},

        # 1.2 — Activos No Corrientes
        {"code": "1.2", "name": "Activos no corrientes", "group": "activos", "type": "control", "parentId": None, "level": 1, "orderIdx": 2, "nature": "deudora", "description": "", "isSystem": True},

        # 1.2.1 — Propiedad, planta y equipo (Activos fijos)
        {"code": "1.2.1", "name": "Propiedad, planta y equipo (Activos fijos)", "group": "activos", "type": "control", "parentId": None, "level": 2, "orderIdx": 1, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "1.2.1.01", "name": "Terrenos", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 1, "nature": "deudora", "usage": "ppye", "description": "", "isSystem": False},
        {"code": "1.2.1.02", "name": "Activos fijos - Categoría 1", "group": "activos", "type": "control", "parentId": None, "level": 3, "orderIdx": 2, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "1.2.1.03", "name": "Edificaciones", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 3, "nature": "deudora", "usage": "ppye", "description": "", "isSystem": False},
        {"code": "1.2.1.04", "name": "Depreciación acumulada edificaciones", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 4, "nature": "acreedora", "usage": "depreciacion_acumulada", "description": "", "isSystem": False},
        {"code": "1.2.1.05", "name": "Construcciones en proceso", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 5, "nature": "deudora", "usage": "ppye", "description": "", "isSystem": False},
        {"code": "1.2.1.06", "name": "Activos fijos - Categoría 2", "group": "activos", "type": "control", "parentId": None, "level": 3, "orderIdx": 6, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "1.2.1.07", "name": "Mobiliario y equipo de oficina", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 7, "nature": "deudora", "usage": "ppye", "description": "", "isSystem": False},
        {"code": "1.2.1.08", "name": "Depreciación acumulada mobiliario y equipo de oficina", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 8, "nature": "acreedora", "usage": "depreciacion_acumulada", "description": "", "isSystem": False},
        {"code": "1.2.1.09", "name": "Vehículos y equipos de transporte", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 9, "nature": "deudora", "usage": "ppye", "description": "", "isSystem": False},
        {"code": "1.2.1.10", "name": "Depreciación vehículos y equipos de transporte", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 10, "nature": "acreedora", "usage": "depreciacion_acumulada", "description": "", "isSystem": False},
        {"code": "1.2.1.11", "name": "Equipo de computación", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 11, "nature": "deudora", "usage": "ppye", "description": "", "isSystem": False},
        {"code": "1.2.1.12", "name": "Depreciación acumulada equipo de computación", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 12, "nature": "acreedora", "usage": "depreciacion_acumulada", "description": "", "isSystem": False},
        {"code": "1.2.1.13", "name": "Activos fijos - Categoría 3", "group": "activos", "type": "control", "parentId": None, "level": 3, "orderIdx": 13, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "1.2.1.14", "name": "Deterioro acumulado de valor", "group": "activos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 14, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},

        # ═══════════════════════════════════════════════
        # 2 — PASIVOS
        # ═══════════════════════════════════════════════
        {"code": "2", "name": "Pasivos", "group": "pasivos", "type": "control", "parentId": None, "level": 0, "orderIdx": 1, "nature": "acreedora", "description": "Bajo esta categoría se encuentran los pasivos de la empresa", "isSystem": True},

        # 2.1 — Pasivos Corrientes
        {"code": "2.1", "name": "Pasivos corrientes", "group": "pasivos", "type": "control", "parentId": None, "level": 1, "orderIdx": 1, "nature": "acreedora", "description": "", "isSystem": True},

        # 2.1.1 — Acreedores comerciales y otras cuentas por pagar
        {"code": "2.1.1", "name": "Acreedores comerciales y otras cuentas por pagar", "group": "pasivos", "type": "control", "parentId": None, "level": 2, "orderIdx": 1, "nature": "acreedora", "description": "", "isSystem": True},

        # 2.1.1.1 — Cuentas por pagar a proveedores
        {"code": "2.1.1.1", "name": "Cuentas por pagar a proveedores", "group": "pasivos", "type": "control", "parentId": None, "level": 3, "orderIdx": 1, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "2.1.1.1.01", "name": "Cuentas por pagar a proveedores nacionales", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "acreedora", "usage": "cxp", "description": "", "isSystem": False},
        {"code": "2.1.1.1.02", "name": "Cuentas por pagar a proveedores del exterior", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "acreedora", "usage": "cxp", "description": "", "isSystem": False},

        # 2.1.1.2 — Avances y anticipos recibidos
        {"code": "2.1.1.2", "name": "Avances y anticipos recibidos", "group": "pasivos", "type": "control", "parentId": None, "level": 3, "orderIdx": 2, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "2.1.1.2.01", "name": "Avances y anticipos recibidos de clientes", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "acreedora", "usage": "anticipos_recibidos", "description": "", "isSystem": False},

        # 2.1.1.3 — Otras cuentas por pagar
        {"code": "2.1.1.3", "name": "Otras cuentas por pagar", "group": "pasivos", "type": "control", "parentId": None, "level": 3, "orderIdx": 3, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "2.1.1.3.01", "name": "Devoluciones de clientes", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "acreedora", "usage": "devoluciones_clientes", "description": "", "isSystem": False},

        # 2.1.2 — Obligaciones laborales y de seguridad social
        {"code": "2.1.2", "name": "Obligaciones laborales y de seguridad social", "group": "pasivos", "type": "control", "parentId": None, "level": 2, "orderIdx": 2, "nature": "acreedora", "description": "", "isSystem": True},

        # 2.1.2.1 — Salarios y prestaciones sociales
        {"code": "2.1.2.1", "name": "Salarios y prestaciones sociales", "group": "pasivos", "type": "control", "parentId": None, "level": 3, "orderIdx": 1, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "2.1.2.1.01", "name": "Salarios a empleados por pagar", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "2.1.2.1.02", "name": "Salarios por pagar", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "2.1.2.1.03", "name": "Vacaciones", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 3, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "2.1.2.1.04", "name": "Tesorería de la seguridad social por pagar", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 4, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "2.1.2.1.05", "name": "Retenciones empleado AFP", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 5, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "2.1.2.1.06", "name": "Retenciones a empleado SFS", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 6, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "2.1.2.1.07", "name": "Retenciones empleados dependientes adicionales", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 7, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "2.1.2.1.08", "name": "Retención de impuesto sobre la renta retenido empleados", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 8, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "2.1.2.1.09", "name": "Acumulaciones SFS", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 9, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "2.1.2.1.10", "name": "Acumulaciones AFP", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 10, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "2.1.2.1.11", "name": "Acumulaciones SRL", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 11, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "2.1.2.1.12", "name": "Acumulaciones INFOTEP", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 12, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "2.1.2.2", "name": "Otras obligaciones laborales", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 2, "nature": "acreedora", "usage": "pasivos_nomina", "description": "", "isSystem": False},

        # 2.1.3 — Obligaciones financieras a corto plazo
        {"code": "2.1.3", "name": "Obligaciones financieras a corto plazo", "group": "pasivos", "type": "control", "parentId": None, "level": 2, "orderIdx": 3, "nature": "acreedora", "description": "", "isSystem": True},

        # 2.1.3.1 — Préstamos a corto plazo bancos nacionales
        {"code": "2.1.3.1", "name": "Préstamos a corto plazo bancos nacionales", "group": "pasivos", "type": "control", "parentId": None, "level": 3, "orderIdx": 1, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "2.1.3.1.01", "name": "Préstamos bancarios a corto plazo", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},

        # 2.1.3.2 — Tarjetas de crédito
        {"code": "2.1.3.2", "name": "Tarjetas de crédito", "group": "pasivos", "type": "control", "parentId": None, "level": 3, "orderIdx": 2, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "2.1.3.2.01", "name": "Tarjeta de crédito empresarial", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "acreedora", "usage": "tarjeta_credito", "description": "", "isSystem": False},

        # 2.1.4 — Pasivos por impuestos corrientes
        {"code": "2.1.4", "name": "Pasivos por impuestos corrientes", "group": "pasivos", "type": "control", "parentId": None, "level": 2, "orderIdx": 4, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "2.1.4.01", "name": "Impuestos por pagar", "group": "pasivos", "type": "control", "parentId": None, "level": 3, "orderIdx": 1, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "2.1.4.01.01", "name": "Impuesto a las ventas por pagar", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "acreedora", "usage": "impuesto_por_pagar", "description": "", "isSystem": False},
        {"code": "2.1.4.01.02", "name": "ITBIS por pagar", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "acreedora", "usage": "itbis_pagar", "description": "", "isSystem": False},
        {"code": "2.1.4.01.03", "name": "ISC por pagar", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 3, "nature": "acreedora", "usage": "impuesto_por_pagar", "description": "", "isSystem": False},
        {"code": "2.1.4.01.04", "name": "Propinas por pagar", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 4, "nature": "acreedora", "usage": "impuesto_por_pagar", "description": "", "isSystem": False},
        {"code": "2.1.4.01.05", "name": "Otro tipo de impuesto por pagar", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 5, "nature": "acreedora", "usage": "otro_impuesto_por_pagar", "description": "", "isSystem": False},

        # 2.1.5 — Pasivos por retenciones corrientes
        {"code": "2.1.5", "name": "Pasivos por retenciones corrientes", "group": "pasivos", "type": "control", "parentId": None, "level": 2, "orderIdx": 5, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "2.1.5.01", "name": "Retenciones por pagar", "group": "pasivos", "type": "control", "parentId": None, "level": 3, "orderIdx": 1, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "2.1.5.01.01", "name": "Retención ITBIS por pagar", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "acreedora", "usage": "retenciones_por_pagar", "description": "", "isSystem": False},
        {"code": "2.1.5.01.02", "name": "Retención ISR por pagar", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "acreedora", "usage": "retenciones_por_pagar", "description": "", "isSystem": False},
        {"code": "2.1.5.01.03", "name": "Otro tipo de retención por pagar", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 3, "nature": "acreedora", "usage": "otra_retencion_por_pagar", "description": "", "isSystem": False},

        # 2.1.6 — Otros pasivos corrientes
        {"code": "2.1.6", "name": "Otros pasivos corrientes", "group": "pasivos", "type": "control", "parentId": None, "level": 2, "orderIdx": 6, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "2.1.6.01", "name": "Ingresos recibidos para terceros", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 1, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},

        # 2.2 — Pasivos No Corrientes
        {"code": "2.2", "name": "Pasivos no corrientes", "group": "pasivos", "type": "control", "parentId": None, "level": 1, "orderIdx": 2, "nature": "acreedora", "description": "", "isSystem": True},

        # 2.2.1 — Obligaciones financieras a largo plazo
        {"code": "2.2.1", "name": "Obligaciones financieras a largo plazo", "group": "pasivos", "type": "control", "parentId": None, "level": 2, "orderIdx": 1, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "2.2.1.01", "name": "Préstamos a largo plazo bancos nacionales", "group": "pasivos", "type": "control", "parentId": None, "level": 3, "orderIdx": 1, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "2.2.1.01.01", "name": "Préstamos bancarios a largo plazo", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},

        # 2.2.2 — Otros pasivos no corrientes
        {"code": "2.2.2", "name": "Otros pasivos no corrientes", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 2, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},

        # ═══════════════════════════════════════════════
        # 3 — PATRIMONIO
        # ═══════════════════════════════════════════════
        {"code": "3", "name": "Patrimonio", "group": "patrimonio", "type": "control", "parentId": None, "level": 0, "orderIdx": 1, "nature": "acreedora", "description": "Bajo esta categoría se encuentra el patrimonio de la empresa", "isSystem": True},

        # 3.1 — Capital social
        {"code": "3.1", "name": "Capital social", "group": "patrimonio", "type": "control", "parentId": None, "level": 1, "orderIdx": 1, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "3.1.1", "name": "Capital social suscrito y pagado", "group": "patrimonio", "type": "control", "parentId": None, "level": 2, "orderIdx": 1, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "3.1.1.01", "name": "Capital social suscrito", "group": "patrimonio", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 1, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "3.1.1.02", "name": "Capital social autorizado", "group": "patrimonio", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 2, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "3.1.2", "name": "Capital por suscribir o Acciones", "group": "patrimonio", "type": "control", "parentId": None, "level": 2, "orderIdx": 2, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "3.1.2.01", "name": "Capital social suscrito por cobrar", "group": "patrimonio", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "3.1.2.02", "name": "Capital suscrito por cobrar o Accionistas comunes", "group": "patrimonio", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},

        # 3.2 — Reservas
        {"code": "3.2", "name": "Reservas", "group": "patrimonio", "type": "movimiento", "parentId": None, "level": 1, "orderIdx": 2, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},

        # 3.3 — Resultado del ejercicio
        {"code": "3.3", "name": "Resultado del ejercicio", "group": "patrimonio", "type": "control", "parentId": None, "level": 1, "orderIdx": 3, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "3.3.01", "name": "Utilidad del ejercicio", "group": "patrimonio", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 1, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "3.3.02", "name": "Pérdida del ejercicio", "group": "patrimonio", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "3.3.03", "name": "Ganancias acumuladas", "group": "patrimonio", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 3, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},

        # 3.4 — Superávit
        {"code": "3.4", "name": "Superávit", "group": "patrimonio", "type": "movimiento", "parentId": None, "level": 1, "orderIdx": 4, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},

        # 3.5 — Ajustes por saldos iniciales
        {"code": "3.5", "name": "Ajustes por saldos iniciales", "group": "patrimonio", "type": "control", "parentId": None, "level": 1, "orderIdx": 5, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "3.5.01", "name": "Ajustes iniciales en bancos", "group": "patrimonio", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 1, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "3.5.02", "name": "Ajustes iniciales en inventario", "group": "patrimonio", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 2, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},

        # ═══════════════════════════════════════════════
        # 4 — INGRESOS
        # ═══════════════════════════════════════════════
        {"code": "4", "name": "Ingresos", "group": "ingresos", "type": "control", "parentId": None, "level": 0, "orderIdx": 1, "nature": "acreedora", "description": "Bajo esta categoría se encuentran todos los tipos de ingresos", "isSystem": True},

        # 4.1 — Ingresos de actividades ordinarias
        {"code": "4.1", "name": "Ingresos de actividades ordinarias", "group": "ingresos", "type": "control", "parentId": None, "level": 1, "orderIdx": 1, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "4.1.01", "name": "Ventas", "group": "ingresos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 1, "nature": "acreedora", "usage": "ventas", "description": "", "isSystem": False},
        {"code": "4.1.02", "name": "Devoluciones en ventas", "group": "ingresos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},

        # 4.2 — Otros Ingresos
        {"code": "4.2", "name": "Otros Ingresos", "group": "ingresos", "type": "control", "parentId": None, "level": 1, "orderIdx": 2, "nature": "acreedora", "description": "", "isSystem": True},

        # 4.2.1 — Ingresos financieros
        {"code": "4.2.1", "name": "Ingresos financieros", "group": "ingresos", "type": "control", "parentId": None, "level": 2, "orderIdx": 1, "nature": "acreedora", "description": "", "isSystem": True},
        {"code": "4.2.1.01", "name": "Ingresos por Intereses financieros", "group": "ingresos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 1, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "4.2.2", "name": "Otros ingresos diversos", "group": "ingresos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 2, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "4.2.3", "name": "Ganancia por diferencia en cambio", "group": "ingresos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 3, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "4.2.4", "name": "Ajustes por aproximaciones en cálculos", "group": "ingresos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 4, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},

        # ═══════════════════════════════════════════════
        # 5 — COSTOS
        # ═══════════════════════════════════════════════
        {"code": "5", "name": "Costos", "group": "costos", "type": "control", "parentId": None, "level": 0, "orderIdx": 1, "nature": "deudora", "description": "Bajo esta categoría se encuentran todos los tipos de costos", "isSystem": True},

        # 5.1 — Costos de ventas y operación
        {"code": "5.1", "name": "Costos de ventas y operación", "group": "costos", "type": "control", "parentId": None, "level": 1, "orderIdx": 1, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "5.1.1", "name": "Costos de la mercancía vendida", "group": "costos", "type": "control", "parentId": None, "level": 2, "orderIdx": 1, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "5.1.1.01", "name": "Costos del inventario", "group": "costos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 1, "nature": "deudora", "usage": "costo_ventas", "description": "", "isSystem": False},
        {"code": "5.1.1.02", "name": "Ajustes al inventario", "group": "costos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "5.1.1.03", "name": "Descuentos financieros", "group": "costos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 3, "nature": "acreedora", "usage": "descuentos_financieros", "description": "", "isSystem": False},
        {"code": "5.1.1.04", "name": "Devoluciones en compras de inventario", "group": "costos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 4, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},
        {"code": "5.1.2", "name": "Costo de los servicios vendidos", "group": "costos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},

        # ═══════════════════════════════════════════════
        # 6 — GASTOS
        # ═══════════════════════════════════════════════
        {"code": "6", "name": "Gastos", "group": "gastos", "type": "control", "parentId": None, "level": 0, "orderIdx": 1, "nature": "deudora", "description": "Bajo esta categoría se encuentran todos los tipos de gastos", "isSystem": True},

        # 6.1 — Gastos de venta
        {"code": "6.1", "name": "Gastos de venta", "group": "gastos", "type": "control", "parentId": None, "level": 1, "orderIdx": 1, "nature": "deudora", "description": "", "isSystem": True},

        # 6.1.1 — Gastos de personal de ventas
        {"code": "6.1.1", "name": "Gastos de personal de ventas", "group": "gastos", "type": "control", "parentId": None, "level": 2, "orderIdx": 1, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.1.1.01", "name": "Sueldos y salarios personal de ventas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.1.1.02", "name": "Salario de navidad personal de ventas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.1.1.03", "name": "Horas extras personal de ventas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 3, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.1.1.04", "name": "Comisiones personal de ventas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 4, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.1.1.05", "name": "Vacaciones personal de ventas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 5, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.1.1.06", "name": "Bonificaciones personal de ventas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 6, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.1.1.07", "name": "Dotación a trabajadores de ventas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 7, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.1.1.08", "name": "Aportes aseguradora fondo de pensiones personal de ventas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 8, "nature": "deudora", "usage": "gastos_nomina", "description": "", "isSystem": False},
        {"code": "6.1.1.09", "name": "Aportes seguro familiar de salud (SFS) personal de ventas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 9, "nature": "deudora", "usage": "gastos_nomina", "description": "", "isSystem": False},
        {"code": "6.1.1.10", "name": "Seguro de riesgo laboral (SRL) personal de ventas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 10, "nature": "deudora", "usage": "gastos_nomina", "description": "", "isSystem": False},
        {"code": "6.1.1.11", "name": "INFOTEP personal de ventas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 11, "nature": "deudora", "usage": "gastos_nomina", "description": "", "isSystem": False},
        {"code": "6.1.1.12", "name": "Otros gastos personal de ventas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 12, "nature": "deudora", "usage": "gastos_nomina", "description": "", "isSystem": False},

        # 6.2 — Gastos de administración
        {"code": "6.2", "name": "Gastos de administración", "group": "gastos", "type": "control", "parentId": None, "level": 1, "orderIdx": 2, "nature": "deudora", "description": "", "isSystem": True},

        # 6.2.1 — Gastos de personal
        {"code": "6.2.1", "name": "Gastos de personal", "group": "gastos", "type": "control", "parentId": None, "level": 2, "orderIdx": 1, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.2.1.01", "name": "Sueldos y salarios", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.1.02", "name": "Salario de navidad", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.1.03", "name": "Horas extras", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 3, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.1.04", "name": "Comisiones", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 4, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.1.05", "name": "Vacaciones", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 5, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.1.06", "name": "Bonificaciones", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 6, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.1.07", "name": "Dotación a trabajadores", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 7, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.1.08", "name": "Aportes aseguradora fondo de pensiones", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 8, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.1.09", "name": "Aportes seguro familiar de salud (SFS)", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 9, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.1.10", "name": "Seguro de riesgo laboral (SRL)", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 10, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.1.11", "name": "INFOTEP", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 11, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.1.12", "name": "Gastos no admitidos para fines fiscales", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 12, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.1.13", "name": "Otros gastos personal administrativo", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 13, "nature": "deudora", "usage": "gastos_nomina", "description": "", "isSystem": False},

        # 6.2.2 — Gastos generales
        {"code": "6.2.2", "name": "Gastos generales", "group": "gastos", "type": "control", "parentId": None, "level": 2, "orderIdx": 2, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.2.2.01", "name": "Servicios profesionales", "group": "gastos", "type": "control", "parentId": None, "level": 3, "orderIdx": 1, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.2.2.01.01", "name": "Asesoría jurídica", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.01.02", "name": "Asesoría contable", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.02", "name": "Arrendamientos", "group": "gastos", "type": "control", "parentId": None, "level": 3, "orderIdx": 2, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.2.2.02.01", "name": "Arrendamiento de equipos", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.02.02", "name": "Arrendamiento de oficinas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.03", "name": "Servicios públicos", "group": "gastos", "type": "control", "parentId": None, "level": 3, "orderIdx": 3, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.2.2.03.01", "name": "Gas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.03.02", "name": "Aseo", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.03.03", "name": "Agua", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 3, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.03.04", "name": "Energía eléctrica", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 4, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.03.05", "name": "Teléfono / Internet", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 5, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.03.06", "name": "Asistencia técnica", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 6, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.03.07", "name": "Otros servicios", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 7, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.04", "name": "Vigilancia y seguridad", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 4, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.05", "name": "Gastos de representación", "group": "gastos", "type": "control", "parentId": None, "level": 3, "orderIdx": 5, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.2.2.05.01", "name": "Comidas y entretenimiento", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.05.02", "name": "Viáticos y gastos de viaje", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.06", "name": "Artículos de oficina", "group": "gastos", "type": "control", "parentId": None, "level": 3, "orderIdx": 6, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.2.2.06.01", "name": "Papelería", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.07", "name": "Combustibles y lubricantes", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 7, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.08", "name": "Fletes y gastos de envíos", "group": "gastos", "type": "control", "parentId": None, "level": 3, "orderIdx": 8, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.2.2.08.01", "name": "Envíos y Mensajería", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.09", "name": "Estacionamiento", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 9, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.10", "name": "Propaganda y publicidad", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 10, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.11", "name": "Capacitación al personal", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 11, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.12", "name": "Seguros", "group": "gastos", "type": "control", "parentId": None, "level": 3, "orderIdx": 12, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.2.2.12.01", "name": "Seguro de accidentes", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.12.02", "name": "Seguro de vehículos", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.12.03", "name": "Seguro contra Incendios", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 3, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.13", "name": "Patentes y marcas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 13, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.14", "name": "Servicios Online", "group": "gastos", "type": "control", "parentId": None, "level": 3, "orderIdx": 14, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.2.2.14.01", "name": "Software contables", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.15", "name": "Gastos constitución", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 15, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.16", "name": "Gastos legales", "group": "gastos", "type": "control", "parentId": None, "level": 3, "orderIdx": 16, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.2.2.16.01", "name": "Notariales", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.16.02", "name": "Registro mercantiles", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.16.03", "name": "Trámites legales", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 3, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.17", "name": "Mantenimiento y conservación", "group": "gastos", "type": "control", "parentId": None, "level": 3, "orderIdx": 17, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.2.2.17.01", "name": "Construcción y edificación", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.17.02", "name": "Equipo oficina", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.17.03", "name": "Equipo computación", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 3, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.17.04", "name": "Adecuaciones e instalaciones", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 4, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.17.05", "name": "Adecuaciones locativas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 4, "orderIdx": 5, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.18", "name": "Cuotas y suscripciones", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 18, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.2.2.19", "name": "Otros gastos generales", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 19, "nature": "deudora", "usage": None, "description": "", "isSystem": False},

        # 6.2.3 — Depreciaciones, amortizaciones y desvalorizaciones
        {"code": "6.2.3", "name": "Depreciaciones, amortizaciones y desvalorizaciones", "group": "gastos", "type": "control", "parentId": None, "level": 2, "orderIdx": 3, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.2.3.01", "name": "Deterioro de cuentas por cobrar", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 1, "nature": "deudora", "usage": "cuentas_incobrables", "description": "", "isSystem": False},
        {"code": "6.2.3.02", "name": "Depreciación de propiedad, planta y equipo", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 2, "nature": "deudora", "usage": "depreciacion", "description": "", "isSystem": False},
        {"code": "6.2.3.03", "name": "Depreciación construcciones y edificaciones", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 3, "nature": "deudora", "usage": "cuentas_incobrables", "description": "", "isSystem": False},
        {"code": "6.2.3.04", "name": "Depreciación mobiliario y equipo de oficina", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 4, "nature": "deudora", "usage": "cuentas_incobrables", "description": "", "isSystem": False},
        {"code": "6.2.3.05", "name": "Depreciación equipo de computación", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 5, "nature": "deudora", "usage": "cuentas_incobrables", "description": "", "isSystem": False},
        {"code": "6.2.3.06", "name": "Depreciación vehículos y equipos de transporte", "group": "gastos", "type": "movimiento", "parentId": None, "level": 3, "orderIdx": 6, "nature": "deudora", "usage": "cuentas_incobrables", "description": "", "isSystem": False},

        # 6.3 — Gastos financieros
        {"code": "6.3", "name": "Gastos financieros", "group": "gastos", "type": "control", "parentId": None, "level": 1, "orderIdx": 3, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.3.01", "name": "Gastos por Intereses financieros", "group": "gastos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.3.02", "name": "Gastos por Intereses de mora", "group": "gastos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},

        # 6.4 — Otros gastos
        {"code": "6.4", "name": "Otros gastos", "group": "gastos", "type": "control", "parentId": None, "level": 1, "orderIdx": 4, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.4.01", "name": "Comisiones bancarias", "group": "gastos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.4.02", "name": "Pérdida por diferencia en cambio", "group": "gastos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 2, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.4.03", "name": "Ajustes por aproximaciones en cálculos", "group": "gastos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 3, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.4.04", "name": "Pérdida por disposición de activos", "group": "gastos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 4, "nature": "deudora", "usage": None, "description": "", "isSystem": False},

        # 6.5 — Gastos por impuestos
        {"code": "6.5", "name": "Gastos por impuestos", "group": "gastos", "type": "control", "parentId": None, "level": 1, "orderIdx": 5, "nature": "deudora", "description": "", "isSystem": True},
        {"code": "6.5.01", "name": "Impuestos de renta", "group": "gastos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "6.5.02", "name": "Gastos por impuestos no acreditables", "group": "gastos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 2, "nature": "deudora", "usage": "impuestos_no_acreditables", "description": "", "isSystem": False},
        {"code": "6.5.03", "name": "Retenciones asumidas", "group": "gastos", "type": "movimiento", "parentId": None, "level": 2, "orderIdx": 3, "nature": "deudora", "usage": "retencion_asumida", "description": "", "isSystem": False},

        # ═══════════════════════════════════════════════
        # 7 — CUENTAS DE ORDEN
        # ═══════════════════════════════════════════════
        {"code": "7", "name": "Cuentas de orden", "group": "cuentas_orden", "type": "control", "parentId": None, "level": 0, "orderIdx": 1, "nature": "deudora", "description": "Bajo esta categoría se encuentran todos los tipos de cuentas de orden", "isSystem": True},
        {"code": "7.1", "name": "Cuentas de orden deudoras", "group": "cuentas_orden", "type": "movimiento", "parentId": None, "level": 1, "orderIdx": 1, "nature": "deudora", "usage": None, "description": "", "isSystem": False},
        {"code": "7.2", "name": "Cuentas de orden acreedoras", "group": "cuentas_orden", "type": "movimiento", "parentId": None, "level": 1, "orderIdx": 2, "nature": "acreedora", "usage": None, "description": "", "isSystem": False},

        # ═══════════════════════════════════════════════
        # TRANSFERENCIAS BANCARIAS (cuenta de sistema)
        # ═══════════════════════════════════════════════
        {"code": "8.1", "name": "Transferencias bancarias", "group": "pasivos", "type": "movimiento", "parentId": None, "level": 1, "orderIdx": 1, "nature": "acreedora", "usage": "transferencias_bancarias", "description": "Bajo esta categoría se ubican todas las transferencias que se hagan entre bancos de la empresa", "isSystem": True},
    ]


def _find_account_by_usage(accounts, usage):
    if not usage:
        return None
    for a in accounts:
        if a.get("usage") == usage:
            return a
    return None


def _find_accounts_by_usage(accounts, usage):
    if not usage:
        return []
    return [a for a in accounts if a.get("usage") == usage]


def _find_account_by_usages(accounts, usages):
    if not usages:
        return None
    for usage in usages:
        for a in accounts:
            if a.get("usage") == usage:
                return a
    return None


def _accounting_entry_exists(owner_uid, reference_type, reference_id):
    entries = DatabaseService.get_accounting_entries(owner_uid)
    for e in entries:
        if e.get("status") == "voided":
            continue
        if e.get("referenceType") == reference_type and e.get("referenceId") == reference_id:
            return True
    return False


class AccountingService:

    @classmethod
    def seed_default_accounts(cls, owner_uid):
        existing = DatabaseService.get_chart_of_accounts(owner_uid)
        existing_codes = {a.get("code") for a in existing}
        default_accounts = _default_chart_of_accounts()
        if existing:
            missing = [a for a in default_accounts if a["code"] not in existing_codes]
            if not missing:
                return
        else:
            missing = default_accounts
        all_existing = existing or []
        existing_by_code = {a.get("code"): a for a in all_existing}
        all_accounts = all_existing + [a for a in missing if a["code"] not in existing_by_code]
        parent_map = {}
        for a in all_accounts:
            if a.get("id"):
                parent_map[a["code"]] = a["id"]
        for acc in missing:
            acc_id = str(uuid.uuid4())
            parent_code = ".".join(acc["code"].split(".")[:-1])
            if parent_code:
                parent = parent_map.get(parent_code)
                if parent:
                    acc["parentId"] = parent
            now = datetime.now(timezone.utc).isoformat()
            acc["id"] = acc_id
            acc["createdAt"] = now
            acc["updatedAt"] = now
            acc["isActive"] = True
            acc["showByThirdParty"] = False
            DatabaseService.save_account(owner_uid, acc_id, acc)
            parent_map[acc["code"]] = acc_id

    @classmethod
    def seed_default_entry_types(cls, owner_uid):
        existing = DatabaseService.get_entry_types(owner_uid)
        if existing:
            return
        defaults = [
            {"id": "ED", "name": "Entrada de Diario", "prefix": "ED", "description": "Asiento contable de diario general", "nature": "auto", "isSystem": True},
            {"id": "SI", "name": "Saldo Inicial", "prefix": "SI", "description": "Asiento de apertura o saldos iniciales", "nature": "debito", "isSystem": True},
            {"id": "AJ", "name": "Ajuste", "prefix": "AJ", "description": "Asiento de ajuste contable", "nature": "debito", "isSystem": True},
            {"id": "DP", "name": "Depreciación", "prefix": "DP", "description": "Asiento de depreciación de activos fijos", "nature": "auto", "isSystem": True},
            {"id": "INV", "name": "Factura de Venta", "prefix": "A", "description": "Asiento generado automáticamente por factura de venta", "nature": "auto", "isSystem": True},
            {"id": "CXP", "name": "Compra/Gasto", "prefix": "C", "description": "Asiento generado automáticamente por compras y gastos", "nature": "auto", "isSystem": True},
        ]
        for et in defaults:
            DatabaseService.save_entry_type(owner_uid, et["id"], et)

    @classmethod
    def get_accounts_tree(cls, owner_uid):
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        if not accounts:
            cls.seed_default_accounts(owner_uid)
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        else:
            # Verificar si faltan cuentas del default sin hacer fetch extra
            existing_codes = {a.get("code") for a in accounts}
            missing = [a for a in _default_chart_of_accounts() if a["code"] not in existing_codes]
            if missing:
                cls.seed_default_accounts(owner_uid)
                accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        children_map = defaultdict(list)
        for acc in accounts:
            children_map[acc.get("parentId") or ""].append(acc)

        def build_node(acc):
            kids = children_map.get(acc["id"], [])
            kids.sort(key=lambda x: (x.get("level", 0), x.get("orderIdx", 0)))
            built = [build_node(k) for k in kids]
            return {
                **acc,
                "children": built,
                "has_children": len(built) > 0
            }

        roots = children_map.get("", [])
        roots.sort(key=lambda x: (x.get("level", 0), x.get("orderIdx", 0)))
        root_nodes = [build_node(r) for r in roots]

        tree = []
        grouped_root = defaultdict(list)
        for node in root_nodes:
            grouped_root[node.get("group", "otros")].append(node)
        for group_key, group_info in sorted(ACCOUNT_GROUPS.items(), key=lambda x: x[1]["order"]):
            tree.append({
                "group": group_key,
                "label": group_info["label"],
                "nature": group_info["nature"],
                "order": group_info["order"],
                "children": grouped_root.get(group_key, []),
                "count": len(grouped_root.get(group_key, []))
            })
        return tree, accounts

    @classmethod
    def get_account_balance(cls, owner_uid, account_id, date_from=None, date_to=None):
        entries = DatabaseService.get_accounting_entries(owner_uid)
        balance = 0.0
        for entry in entries:
            if entry.get("status") == "voided":
                continue
            entry_date = str(entry.get("date", ""))[:10]
            if date_from and entry_date < date_from:
                continue
            if date_to and entry_date > date_to:
                continue
            for line in entry.get("lines", []):
                if line.get("accountId") == account_id:
                    balance += float(line.get("debit", 0)) - float(line.get("credit", 0))
        return balance

    @classmethod
    def get_account_movements(cls, owner_uid, account_id, date_from=None, date_to=None):
        movements = []
        entries = DatabaseService.get_accounting_entries(owner_uid)
        for entry in entries:
            if entry.get("status") == "voided":
                continue
            entry_date = str(entry.get("date", ""))[:10]
            if date_from and entry_date < date_from:
                continue
            if date_to and entry_date > date_to:
                continue
            for line in entry.get("lines", []):
                if line.get("accountId") == account_id:
                    movements.append({
                        "date": entry.get("date", ""),
                        "entryNumber": entry.get("number", ""),
                        "concept": entry.get("concept", ""),
                        "referenceType": entry.get("referenceType", ""),
                        "referenceNumber": entry.get("referenceNumber", ""),
                        "contactName": line.get("contactName", ""),
                        "description": line.get("description", ""),
                        "debit": float(line.get("debit", 0)),
                        "credit": float(line.get("credit", 0)),
                    })
        movements.sort(key=lambda x: x["date"])
        running = 0.0
        for m in movements:
            running += m["debit"] - m["credit"]
            m["balance"] = round(running, 2)
        return movements

    @classmethod
    def generate_entry(cls, owner_uid, entry_data, sandbox=True):
        lines = entry_data.get("lines", [])
        total_debit = sum(float(l.get("debit", 0)) for l in lines)
        total_credit = sum(float(l.get("credit", 0)) for l in lines)
        if abs(total_debit - total_credit) > 0.01:
            raise ValueError(f"El asiento no está balanceado: Débito {total_debit} ≠ Crédito {total_credit}")

        from app.services.fiscal_period_service import FiscalPeriodService
        entry_date = entry_data.get("date", "")
        if entry_date and entry_data.get("entryType") not in ("closing",):
            FiscalPeriodService.validate_period_open(owner_uid, entry_date)

        entry_id = str(uuid.uuid4())
        prefix = entry_data.get("prefix", "A")
        number = DatabaseService.get_next_entry_number(owner_uid, prefix=prefix, sandbox=sandbox)
        entry = {
            "id": entry_id,
            "number": number,
            "entryType": entry_data.get("entryType", "standard"),
            "typeId": entry_data.get("typeId"),
            "date": entry_data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            "concept": entry_data.get("concept", ""),
            "referenceType": entry_data.get("referenceType"),
            "referenceId": entry_data.get("referenceId"),
            "referenceNumber": entry_data.get("referenceNumber"),
            "lines": lines,
            "totalDebit": round(total_debit, 2),
            "totalCredit": round(total_credit, 2),
            "isBalanced": True,
            "status": "active",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "createdBy": entry_data.get("createdBy", ""),
        }
        DatabaseService.save_accounting_entry(owner_uid, entry_id, entry, sandbox=sandbox)
        from app.services.ledger_audit_service import LedgerAuditService
        LedgerAuditService.log_entry_creation(entry, owner_uid, performed_by=entry_data.get("createdBy", ""))
        return entry

    @classmethod
    def get_balance_sheet(cls, owner_uid, date=None):
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        if not accounts:
            cls.seed_default_accounts(owner_uid)
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        active_accounts = [a for a in accounts if a.get("group") in ("activos", "pasivos", "patrimonio")]
        result = {"activos": {"total": 0.0, "children": []}, "pasivos": {"total": 0.0, "children": []}, "patrimonio": {"total": 0.0, "children": []}}
        for acc in active_accounts:
            if acc.get("type") != "movimiento":
                continue
            balance = cls.get_account_balance(owner_uid, acc["id"], date_to=date)
            group = acc.get("group")
            if group in result:
                result[group]["children"].append({
                    "code": acc.get("code", ""),
                    "name": acc.get("name", ""),
                    "balance": balance
                })
                if acc.get("nature") == "deudora":
                    result[group]["total"] += balance
                else:
                    result[group]["total"] -= balance
        for k in result:
            result[k]["total"] = round(result[k]["total"], 2)
        return result

    @classmethod
    def get_income_statement(cls, owner_uid, date_from=None, date_to=None):
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        if not accounts:
            cls.seed_default_accounts(owner_uid)
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        result = {"ingresos": {"total": 0.0, "children": []}, "costos": {"total": 0.0, "children": []}, "gastos": {"total": 0.0, "children": []}}
        for acc in accounts:
            if acc.get("type") != "movimiento":
                continue
            group = acc.get("group")
            if group not in ("ingresos", "costos", "gastos"):
                continue
            balance = cls.get_account_balance(owner_uid, acc["id"], date_from=date_from, date_to=date_to)
            result[group]["children"].append({
                "code": acc.get("code", ""),
                "name": acc.get("name", ""),
                "balance": balance
            })
            if acc.get("nature") == "deudora":
                result[group]["total"] += balance
            else:
                result[group]["total"] -= balance
        for k in result:
            result[k]["total"] = round(result[k]["total"], 2)
        net_income = result["ingresos"]["total"] - result["costos"]["total"] - result["gastos"]["total"]
        result["netIncome"] = round(net_income, 2)
        return result

    @classmethod
    def get_trial_balance(cls, owner_uid, date=None):
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        if not accounts:
            cls.seed_default_accounts(owner_uid)
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        rows = []
        total_debit = 0.0
        total_credit = 0.0
        for acc in accounts:
            if acc.get("type") != "movimiento":
                continue
            balance = cls.get_account_balance(owner_uid, acc["id"], date_to=date)
            debit = balance if balance > 0 else 0.0
            credit = -balance if balance < 0 else 0.0
            if abs(balance) > 0.001:
                total_debit += debit
                total_credit += credit
                rows.append({
                    "code": acc.get("code", ""),
                    "name": acc.get("name", ""),
                    "group": ACCOUNT_GROUPS.get(acc.get("group"), {}).get("label", ""),
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2),
                })
        return {"rows": rows, "totalDebit": round(total_debit, 2), "totalCredit": round(total_credit, 2)}

    @classmethod
    def void_entry(cls, owner_uid, entry_id, reason="", user_id="", sandbox=True):
        entry = DatabaseService.get_accounting_entry(owner_uid, entry_id, sandbox=sandbox)
        if not entry:
            return None
        entry["status"] = "voided"
        entry["voidedAt"] = datetime.now(timezone.utc).isoformat()
        entry["voidedBy"] = user_id
        entry["voidReason"] = reason
        DatabaseService.save_accounting_entry(owner_uid, entry_id, entry, sandbox=sandbox)
        from app.services.ledger_audit_service import LedgerAuditService
        LedgerAuditService.log_entry_void(entry, owner_uid, performed_by=user_id, reason=reason)
        return entry

    @classmethod
    def _resolve_debit_account(cls, invoice, accounts):
        payment_type = invoice.get("paymentType", "Contado")
        if payment_type == "Contado":
            payment_method = invoice.get("paymentMethod", "Efectivo")
            if payment_method in ("Tarjeta de Crédito", "Tarjeta de Débito", "Transferencia"):
                acc = _find_account_by_usages(accounts, ["banco", "transferencias_bancarias"])
                if acc:
                    return acc, f"Banco - {invoice.get('invoiceNumber', '')}"
            acc = _find_account_by_usages(accounts, ["efectivo", "banco"])
            if acc:
                return acc, f"Efectivo/Banco - Factura {invoice.get('invoiceNumber', '')}"
        return _find_account_by_usages(accounts, ["cxc", "banco", "efectivo"]), f"Factura {invoice.get('invoiceNumber', '')}"

    @classmethod
    def _build_cogs_lines(cls, invoice, accounts):
        items = invoice.get("items", [])
        lines = []
        inv_acc = _find_account_by_usage(accounts, "inventario")
        cogs_acc = _find_account_by_usage(accounts, "costo_ventas")
        if not inv_acc or not cogs_acc:
            return lines
        for it in items:
            if it.get("type", "Bien") == "Bien":
                cost_price = float(it.get("costPrice", 0))
                quantity = float(it.get("quantity", 1))
                if cost_price > 0:
                    total_cost = round(cost_price * quantity, 2)
                    lines.append({
                        "accountId": cogs_acc["id"],
                        "accountCode": cogs_acc.get("code", ""),
                        "accountName": cogs_acc.get("name", ""),
                        "debit": total_cost,
                        "credit": 0.00,
                        "description": f"Costo de venta: {it.get('name', 'Item')} x{int(quantity)}"
                    })
                    lines.append({
                        "accountId": inv_acc["id"],
                        "accountCode": inv_acc.get("code", ""),
                        "accountName": inv_acc.get("name", ""),
                        "debit": 0.00,
                        "credit": total_cost,
                        "description": f"Descargo inventario: {it.get('name', 'Item')} x{int(quantity)}"
                    })
        return lines

    @classmethod
    def _build_extra_tax_lines(cls, invoice, accounts):
        lines = []
        total_isc_esp = float(invoice.get("totalISCEspecifico", 0))
        total_isc_adv = float(invoice.get("totalISCAdValorem", 0))
        total_otros = float(invoice.get("totalOtrosImpuestos", 0))
        total_tax_lines = round(total_isc_esp + total_isc_adv + total_otros, 2)
        if total_tax_lines <= 0:
            return lines
        impuesto_acc = _find_account_by_usages(accounts, ["impuesto_por_pagar", "otro_impuesto_por_pagar"])
        if not impuesto_acc:
            return lines
        labels = []
        if total_isc_esp > 0:
            labels.append(f"ISC específico {total_isc_esp:,.2f}")
        if total_isc_adv > 0:
            labels.append(f"ISC ad valorem {total_isc_adv:,.2f}")
        if total_otros > 0:
            labels.append(f"Otros impuestos {total_otros:,.2f}")
        lines.append({
            "accountId": impuesto_acc["id"],
            "accountCode": impuesto_acc.get("code", ""),
            "accountName": impuesto_acc.get("name", ""),
            "debit": 0.00,
            "credit": total_tax_lines,
            "description": "; ".join(labels)
        })
        return lines

    @classmethod
    def auto_generate_invoice_entry(cls, owner_uid, invoice, sandbox=True):
        invoice_id = invoice.get("id", "")
        if _accounting_entry_exists(owner_uid, "invoice", invoice_id):
            return None
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        if not accounts:
            cls.seed_default_accounts(owner_uid)
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        debit_acc, debit_desc = cls._resolve_debit_account(invoice, accounts)
        sales_acc = _find_account_by_usage(accounts, "ventas")
        itbis_acc = _find_account_by_usage(accounts, "itbis_pagar")
        itbis_ret_acc = _find_account_by_usage(accounts, "itbis_retenido")
        isr_ret_acc = _find_account_by_usage(accounts, "isr_retenido")
        if not debit_acc or not sales_acc:
            return None
        total = float(invoice.get("netPayable", invoice.get("total", 0)))
        subtotal = float(invoice.get("subtotal", 0))
        itbis = float(invoice.get("totalITBIS", invoice.get("itbis", 0)))
        retained_isr = float(invoice.get("retainedISR", 0))
        retained_itbis = float(invoice.get("retainedITBIS", 0))
        branch_id = invoice.get("branchId", "")
        cost_center_id = invoice.get("costCenterId", "")
        currency = invoice.get("currency", "DOP")
        client_id = invoice.get("clientId", "")
        client_name = invoice.get("clientName", "")
        lines = []
        lines.append({
            "accountId": debit_acc["id"],
            "accountCode": debit_acc.get("code", ""),
            "accountName": debit_acc.get("name", ""),
            "debit": round(total, 2),
            "credit": 0.00,
            "description": debit_desc,
            "contactId": client_id,
            "contactName": client_name,
            "branchId": branch_id,
            "costCenterId": cost_center_id,
            "currency": currency
        })
        lines.append({
            "accountId": sales_acc["id"],
            "accountCode": sales_acc.get("code", ""),
            "accountName": sales_acc.get("name", ""),
            "debit": 0.00,
            "credit": round(subtotal, 2),
            "description": f"Ventas factura {invoice.get('invoiceNumber', '')}",
            "branchId": branch_id,
            "costCenterId": cost_center_id,
            "currency": currency
        })
        if itbis > 0 and itbis_acc:
            lines.append({
                "accountId": itbis_acc["id"],
                "accountCode": itbis_acc.get("code", ""),
                "accountName": itbis_acc.get("name", ""),
                "debit": 0.00,
                "credit": round(itbis, 2),
                "description": "ITBIS factura",
                "branchId": branch_id,
                "costCenterId": cost_center_id,
                "currency": currency
            })
        if retained_itbis > 0 and itbis_ret_acc:
            lines.append({
                "accountId": itbis_ret_acc["id"],
                "accountCode": itbis_ret_acc.get("code", ""),
                "accountName": itbis_ret_acc.get("name", ""),
                "debit": round(retained_itbis, 2),
                "credit": 0.00,
                "description": "ITBIS retenido",
                "branchId": branch_id,
                "costCenterId": cost_center_id,
                "currency": currency
            })
        if retained_isr > 0 and isr_ret_acc:
            lines.append({
                "accountId": isr_ret_acc["id"],
                "accountCode": isr_ret_acc.get("code", ""),
                "accountName": isr_ret_acc.get("name", ""),
                "debit": round(retained_isr, 2),
                "credit": 0.00,
                "description": "ISR retenido",
                "branchId": branch_id,
                "costCenterId": cost_center_id,
                "currency": currency
            })
        extra_tax_lines = cls._build_extra_tax_lines(invoice, accounts)
        lines.extend(extra_tax_lines)
        cogs_lines = cls._build_cogs_lines(invoice, accounts)
        lines.extend(cogs_lines)
        try:
            entry = cls.generate_entry(owner_uid, {
                "entryType": "invoice",
                "date": str(invoice.get("date", ""))[:10],
                "concept": f"Factura de venta {invoice.get('invoiceNumber', '')} - {invoice.get('clientName', '')}",
                "referenceType": "invoice",
                "referenceId": invoice.get("id", ""),
                "referenceNumber": invoice.get("invoiceNumber", ""),
                "lines": lines,
                "createdBy": "system",
                "prefix": "A",
            }, sandbox=sandbox)
            return entry
        except ValueError:
            return None

    @classmethod
    def auto_reverse_invoice_entry(cls, owner_uid, invoice, reason="", user_id="", sandbox=True):
        invoice_id = invoice.get("id", "")
        entries = DatabaseService.get_accounting_entries(owner_uid, sandbox=sandbox)
        existing_entries = [
            e for e in entries
            if e.get("referenceType") == "invoice"
            and e.get("referenceId") == invoice_id
            and e.get("status") == "active"
        ]
        if not existing_entries:
            return None
        reversed_entries = []
        for orig_entry in existing_entries:
            if _accounting_entry_exists(owner_uid, "invoice_reversal", f"{invoice_id}_{orig_entry.get('id', '')}"):
                continue
            reversed_lines = []
            for line in orig_entry.get("lines", []):
                reversed_lines.append({
                    "accountId": line.get("accountId", ""),
                    "accountCode": line.get("accountCode", ""),
                    "accountName": line.get("accountName", ""),
                    "debit": round(float(line.get("credit", 0)), 2),
                    "credit": round(float(line.get("debit", 0)), 2),
                    "description": f"[REVERSO] {line.get('description', '')}",
                    "contactId": line.get("contactId"),
                    "contactName": line.get("contactName"),
                    "branchId": line.get("branchId", ""),
                    "costCenterId": line.get("costCenterId", ""),
                    "currency": line.get("currency", "DOP")
                })
            try:
                rev_entry = cls.generate_entry(owner_uid, {
                    "entryType": "invoice_reversal",
                    "date": str(invoice.get("date", ""))[:10],
                    "concept": f"REVERSO - Factura anulada {invoice.get('invoiceNumber', '')} - {reason}",
                    "referenceType": "invoice_reversal",
                    "referenceId": f"{invoice_id}_{orig_entry.get('id', '')}",
                    "referenceNumber": invoice.get("invoiceNumber", ""),
                    "lines": reversed_lines,
                    "createdBy": user_id or "system",
                    "prefix": "A",
                }, sandbox=sandbox)
                reversed_entries.append(rev_entry)
            except ValueError:
                continue
        return reversed_entries[0] if reversed_entries else None

    @classmethod
    def auto_generate_credit_note_entry(cls, owner_uid, invoice, sandbox=True):
        invoice_id = invoice.get("id", "")
        if _accounting_entry_exists(owner_uid, "credit_note", invoice_id):
            return None
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        if not accounts:
            cls.seed_default_accounts(owner_uid)
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        cxc_acc = _find_account_by_usage(accounts, "cxc")
        sales_acc = _find_account_by_usage(accounts, "ventas")
        devolucion_acc = _find_account_by_usages(accounts, ["devoluciones_ventas", "devoluciones_clientes"])
        itbis_acc = _find_account_by_usage(accounts, "itbis_pagar")
        if not cxc_acc or not sales_acc:
            return None
        total = float(invoice.get("netPayable", invoice.get("total", 0)))
        subtotal = float(invoice.get("subtotal", 0))
        itbis = float(invoice.get("totalITBIS", invoice.get("itbis", 0)))
        branch_id = invoice.get("branchId", "")
        cost_center_id = invoice.get("costCenterId", "")
        currency = invoice.get("currency", "DOP")
        lines = []
        if devolucion_acc:
            lines.append({
                "accountId": devolucion_acc["id"],
                "accountCode": devolucion_acc.get("code", ""),
                "accountName": devolucion_acc.get("name", ""),
                "debit": round(subtotal, 2),
                "credit": 0.00,
                "description": f"Devolución factura {invoice.get('invoiceNumber', '')}",
                "branchId": branch_id,
                "costCenterId": cost_center_id,
                "currency": currency
            })
        else:
            lines.append({
                "accountId": sales_acc["id"],
                "accountCode": sales_acc.get("code", ""),
                "accountName": sales_acc.get("name", ""),
                "debit": round(subtotal, 2),
                "credit": 0.00,
                "description": f"Devolución factura {invoice.get('invoiceNumber', '')}",
                "branchId": branch_id,
                "costCenterId": cost_center_id,
                "currency": currency
            })
        if itbis > 0 and itbis_acc:
            lines.append({
                "accountId": itbis_acc["id"],
                "accountCode": itbis_acc.get("code", ""),
                "accountName": itbis_acc.get("name", ""),
                "debit": round(itbis, 2),
                "credit": 0.00,
                "description": "ITBIS devolución",
                "branchId": branch_id,
                "costCenterId": cost_center_id,
                "currency": currency
            })
        lines.append({
            "accountId": cxc_acc["id"],
            "accountCode": cxc_acc.get("code", ""),
            "accountName": cxc_acc.get("name", ""),
            "debit": 0.00,
            "credit": round(total, 2),
            "description": f"Nota de crédito {invoice.get('invoiceNumber', '')}",
            "branchId": branch_id,
            "costCenterId": cost_center_id,
            "currency": currency
        })
        cogs_lines = cls._build_cogs_lines(invoice, accounts)
        if cogs_lines:
            for cl in cogs_lines:
                cl["debit"], cl["credit"] = cl["credit"], cl["debit"]
                cl["description"] = f"[REVERSO COGS] {cl.get('description', '')}"
            lines.extend(cogs_lines)
        try:
            entry = cls.generate_entry(owner_uid, {
                "entryType": "credit_note",
                "date": str(invoice.get("date", ""))[:10],
                "concept": f"Nota de crédito {invoice.get('invoiceNumber', '')} - {invoice.get('clientName', '')}",
                "referenceType": "credit_note",
                "referenceId": invoice.get("id", ""),
                "referenceNumber": invoice.get("invoiceNumber", ""),
                "lines": lines,
                "createdBy": "system",
                "prefix": "A",
            }, sandbox=sandbox)
            return entry
        except ValueError:
            return None

    @classmethod
    def auto_generate_expense_entry(cls, owner_uid, expense, sandbox=True):
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        if not accounts:
            cls.seed_default_accounts(owner_uid)
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        cxp_acc = _find_account_by_usage(accounts, "cxp")
        compras_acc = _find_account_by_usage(accounts, "compras")
        gastos_acc = _find_account_by_usage(accounts, "gastos")
        itbis_credito_acc = _find_account_by_usage(accounts, "itbis_credito")
        total = float(expense.get("amount", expense.get("total", 0)))
        itbis = float(expense.get("itbisAmount", expense.get("itbis", 0)))
        net = max(0, total - itbis)
        lines = []
        if compras_acc and expense.get("isCost"):
            lines.append({"accountId": compras_acc["id"], "accountCode": compras_acc.get("code", ""), "accountName": compras_acc.get("name", ""), "debit": round(net, 2), "credit": 0.00, "description": expense.get("concept", "")})
        elif gastos_acc:
            lines.append({"accountId": gastos_acc["id"], "accountCode": gastos_acc.get("code", ""), "accountName": gastos_acc.get("name", ""), "debit": round(net, 2), "credit": 0.00, "description": expense.get("concept", "")})
        if itbis > 0 and itbis_credito_acc:
            lines.append({"accountId": itbis_credito_acc["id"], "accountCode": itbis_credito_acc.get("code", ""), "accountName": itbis_credito_acc.get("name", ""), "debit": round(itbis, 2), "credit": 0.00, "description": "ITBIS"})
        if cxp_acc:
            lines.append({"accountId": cxp_acc["id"], "accountCode": cxp_acc.get("code", ""), "accountName": cxp_acc.get("name", ""), "debit": 0.00, "credit": round(total, 2), "description": ""})
        try:
            entry = cls.generate_entry(owner_uid, {
                "entryType": "expense",
                "date": str(expense.get("date", ""))[:10],
                "concept": f"Compra/gasto {expense.get('ncf', '')} - {expense.get('supplierName', '')}",
                "referenceType": "expense",
                "referenceId": expense.get("id", ""),
                "referenceNumber": expense.get("ncf", ""),
                "lines": lines,
                "createdBy": "system",
                "prefix": "A",
            }, sandbox=sandbox)
            return entry
        except ValueError:
            return None

    @classmethod
    def clone_entry(cls, owner_uid, entry_id, sandbox=True):
        entry = DatabaseService.get_accounting_entry(owner_uid, entry_id, sandbox=sandbox)
        if not entry:
            return None
        new_id = str(uuid.uuid4())
        prefix = entry.get("number", "A-00000").split("-")[0] if "-" in entry.get("number", "") else "A"
        number = DatabaseService.get_next_entry_number(owner_uid, prefix=prefix, sandbox=sandbox)
        new_entry = {k: v for k, v in entry.items() if k not in ("id", "number", "createdAt", "createdBy", "status", "voidedAt", "voidedBy", "voidReason")}
        new_entry["id"] = new_id
        new_entry["number"] = number
        new_entry["status"] = "active"
        new_entry["createdAt"] = datetime.now(timezone.utc).isoformat()
        DatabaseService.save_accounting_entry(owner_uid, new_id, new_entry, sandbox=sandbox)
        return new_entry
