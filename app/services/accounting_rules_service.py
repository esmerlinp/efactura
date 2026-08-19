"""
Motor de configuración de cuentas contables por transacción.

Cada transacción del sistema (venta, nota de crédito, gasto, cobro, nómina,
activos, cierre) resuelve sus cuentas a través de este servicio:

    regla específica (condición) → regla por defecto → usage de la cuenta

Los generadores de asientos conocen la contabilidad de la operación
(concepto + contexto); este servicio determina la cuenta concreta.
"""

from app.services.db_service import DatabaseService

CONDITIONS = {
    "pago_efectivo": {
        "label": "Pago en efectivo",
        "type": "flag",
        "match": lambda ctx: ctx.get("payment_type", "Contado") == "Contado"
        and ctx.get("payment_method", "Efectivo")
        not in ("Tarjeta de Crédito", "Tarjeta de Débito", "Transferencia"),
    },
    "pago_tarjeta": {
        "label": "Pago con tarjeta (crédito/débito)",
        "type": "flag",
        "match": lambda ctx: ctx.get("payment_type", "Contado") == "Contado"
        and ctx.get("payment_method", "Efectivo")
        in ("Tarjeta de Crédito", "Tarjeta de Débito"),
    },
    "pago_transferencia": {
        "label": "Pago por transferencia",
        "type": "flag",
        "match": lambda ctx: ctx.get("payment_type", "Contado") == "Contado"
        and ctx.get("payment_method", "Efectivo") == "Transferencia",
    },
    "pago_contado": {
        "label": "Operación al contado",
        "type": "flag",
        "match": lambda ctx: ctx.get("payment_type", "Contado") == "Contado",
    },
    "pago_credito": {
        "label": "Operación a crédito",
        "type": "flag",
        "match": lambda ctx: ctx.get("payment_type", "Contado") != "Contado",
    },
    "centro_costo": {
        "label": "Centro de costo",
        "type": "value",
        "value": lambda ctx: (ctx.get("centro_costo") or "").strip(),
    },
}

TRANSACTIONS = {
    "venta": {
        "label": "Factura de venta (e-CF)",
        "concepts": {
            "venta_deudor": {
                "label": "Cuenta deudora (contraparte)",
                "side": "debit",
                "fallback_usages": ["cxc", "banco", "efectivo"],
                "conditions": [
                    {"key": "pago_efectivo", "fallback_usages": ["efectivo", "banco"]},
                    {"key": "pago_tarjeta", "fallback_usages": ["banco", "transferencias_bancarias"]},
                    {"key": "pago_transferencia", "fallback_usages": ["banco", "transferencias_bancarias"]},
                    {"key": "pago_credito", "fallback_usages": ["cxc", "banco", "efectivo"]},
                ],
            },
            "venta_ingresos": {
                "label": "Ingresos por ventas",
                "side": "credit",
                "fallback_usages": ["ventas"],
                "conditions": [],
            },
            "venta_itbis_por_pagar": {
                "label": "ITBIS por pagar",
                "side": "credit",
                "fallback_usages": ["itbis_pagar"],
                "conditions": [],
            },
            "venta_retencion_itbis_cliente": {
                "label": "ITBIS retenido por el cliente (a favor)",
                "side": "debit",
                "fallback_usages": ["retenciones_a_favor", "impuesto_a_favor"],
                "conditions": [],
            },
            "venta_retencion_isr_cliente": {
                "label": "ISR retenido por el cliente (a favor)",
                "side": "debit",
                "fallback_usages": ["retenciones_a_favor", "impuesto_a_favor"],
                "conditions": [],
            },
            "venta_costo_ventas": {
                "label": "Costo de ventas",
                "side": "debit",
                "fallback_usages": ["costo_ventas"],
                "conditions": [],
            },
            "venta_inventario": {
                "label": "Inventario (descargo)",
                "side": "credit",
                "fallback_usages": ["inventario"],
                "conditions": [],
            },
            "venta_otros_impuestos": {
                "label": "Otros impuestos por pagar (ISC, propinas)",
                "side": "credit",
                "fallback_usages": ["impuesto_por_pagar", "otro_impuesto_por_pagar"],
                "conditions": [],
            },
        },
    },
    "nota_credito": {
        "label": "Nota de crédito (E34)",
        "concepts": {
            "nc_deudor": {
                "label": "Cuentas por cobrar (haber)",
                "side": "credit",
                "fallback_usages": ["cxc"],
                "conditions": [],
            },
            "nc_devolucion_ingresos": {
                "label": "Devoluciones en ventas (debe)",
                "side": "debit",
                "fallback_usages": ["devoluciones_ventas", "devoluciones_clientes"],
                "conditions": [],
            },
            "nc_ingresos": {
                "label": "Ingresos por ventas (si no hay cuenta de devoluciones)",
                "side": "debit",
                "fallback_usages": ["ventas"],
                "conditions": [],
            },
            "nc_itbis": {
                "label": "ITBIS por pagar (reverso)",
                "side": "debit",
                "fallback_usages": ["itbis_pagar"],
                "conditions": [],
            },
        },
    },
    "gasto": {
        "label": "Compras y gastos (CxP)",
        "concepts": {
            "gasto_deudor": {
                "label": "Cuenta acreedora (contraparte del pago)",
                "side": "credit",
                "fallback_usages": ["cxp"],
                "conditions": [
                    {"key": "pago_contado", "fallback_usages": ["banco", "efectivo"]},
                    {"key": "pago_credito", "fallback_usages": ["cxp"]},
                ],
            },
            "gasto_cuenta_general": {
                "label": "Cuenta de gasto por defecto",
                "side": "debit",
                "fallback_usages": ["gastos", "compras"],
                "conditions": [],
            },
            "gasto_compras": {
                "label": "Compras (costos)",
                "side": "debit",
                "fallback_usages": ["compras", "gastos"],
                "conditions": [],
            },
            "gasto_itbis_credito": {
                "label": "ITBIS crédito fiscal",
                "side": "debit",
                "fallback_usages": ["itbis_credito"],
                "conditions": [],
            },
            "gasto_itbis_retenido": {
                "label": "ITBIS retenido a proveedores",
                "side": "credit",
                "fallback_usages": ["itbis_retenido"],
                "conditions": [],
            },
            "gasto_isr_retenido": {
                "label": "ISR retenido a proveedores",
                "side": "credit",
                "fallback_usages": ["isr_retenido"],
                "conditions": [],
            },
        },
    },
    "cobro": {
        "label": "Cobro de factura",
        "concepts": {
            "cobro_deudor": {
                "label": "Cuenta de ingreso del cobro (banco/efectivo)",
                "side": "debit",
                "fallback_usages": ["banco", "transferencias_bancarias", "efectivo"],
                "conditions": [],
            },
            "cobro_cxc": {
                "label": "Cuentas por cobrar (haber)",
                "side": "credit",
                "fallback_usages": ["cxc"],
                "conditions": [],
            },
        },
    },
    "anticipo_cliente": {
        "label": "Anticipo recibido de cliente",
        "concepts": {
            "anticipo_deudor": {
                "label": "Cuenta de ingreso (banco/efectivo)",
                "side": "debit",
                "fallback_usages": ["efectivo", "banco"],
                "conditions": [
                    {"key": "pago_tarjeta", "fallback_usages": ["banco", "transferencias_bancarias"]},
                    {"key": "pago_transferencia", "fallback_usages": ["banco", "transferencias_bancarias"]},
                    {"key": "pago_efectivo", "fallback_usages": ["efectivo", "banco"]},
                ],
            },
            "anticipo_recibido": {
                "label": "Anticipos recibidos de clientes",
                "side": "credit",
                "fallback_usages": ["anticipos_recibidos"],
                "conditions": [],
            },
        },
    },
    "anticipo_aplicacion": {
        "label": "Aplicación de anticipo a factura",
        "concepts": {
            "anticipo_aplicado": {
                "label": "Anticipos recibidos (debe)",
                "side": "debit",
                "fallback_usages": ["anticipos_recibidos"],
                "conditions": [],
            },
            "anticipo_aplicacion_deudor": {
                "label": "Cuenta deudora de la factura (haber)",
                "side": "credit",
                "fallback_usages": ["cxc", "banco", "efectivo"],
                "conditions": [
                    {"key": "pago_contado", "fallback_usages": ["efectivo", "banco"]},
                    {"key": "pago_credito", "fallback_usages": ["cxc", "banco", "efectivo"]},
                ],
            },
        },
    },
    "inventario": {
        "label": "Operaciones de inventario",
        "concepts": {
            "inventario_cuenta": {
                "label": "Inventario",
                "side": "debit",
                "fallback_usages": ["inventario"],
                "conditions": [],
            },
            "inventario_ajuste": {
                "label": "Ajuste de inventario",
                "side": "credit",
                "fallback_usages": ["ajuste_inventario", "costo_ventas"],
                "conditions": [],
            },
            "inventario_merma": {
                "label": "Merma / pérdida de inventario",
                "side": "debit",
                "fallback_usages": ["merma_perdida", "costo_ventas"],
                "conditions": [],
            },
        },
    },
    "nomina": {
        "label": "Nómina",
        "concepts": {
            "nomina_gasto": {
                "label": "Gasto de nómina (por centro de costo)",
                "side": "debit",
                "fallback_usages": [],
                "fallback_note": "Config de nómina (centros de costo) o código 6.2.1.01",
                "conditions": [{"key": "centro_costo", "fallback_usages": []}],
            },
            "nomina_salarios_por_pagar": {
                "label": "Salarios por pagar (neto)",
                "side": "credit",
                "fallback_usages": [],
                "fallback_note": "Config de nómina (2.1.2.1.02)",
                "conditions": [],
            },
            "nomina_afp_empleado": {
                "label": "Retención AFP empleado",
                "side": "credit",
                "fallback_usages": [],
                "fallback_note": "Config de nómina (2.1.2.1.05)",
                "conditions": [],
            },
            "nomina_sfs_empleado": {
                "label": "Retención SFS empleado",
                "side": "credit",
                "fallback_usages": [],
                "fallback_note": "Config de nómina (2.1.2.1.06)",
                "conditions": [],
            },
            "nomina_isr_empleado": {
                "label": "Retención ISR empleados",
                "side": "credit",
                "fallback_usages": [],
                "fallback_note": "Config de nómina (2.1.2.1.08)",
                "conditions": [],
            },
            "nomina_afp_empleador": {
                "label": "AFP empleador por pagar",
                "side": "credit",
                "fallback_usages": [],
                "fallback_note": "Config de nómina (2.1.2.1.10)",
                "conditions": [],
            },
            "nomina_sfs_empleador": {
                "label": "SFS empleador por pagar",
                "side": "credit",
                "fallback_usages": [],
                "fallback_note": "Config de nómina (2.1.2.1.09)",
                "conditions": [],
            },
            "nomina_srl_empleador": {
                "label": "SRL empleador por pagar",
                "side": "credit",
                "fallback_usages": [],
                "fallback_note": "Config de nómina (2.1.2.1.11)",
                "conditions": [],
            },
            "nomina_infotep": {
                "label": "INFOTEP por pagar",
                "side": "credit",
                "fallback_usages": [],
                "fallback_note": "Config de nómina (2.1.2.1.12)",
                "conditions": [],
            },
            "nomina_otras_deducciones": {
                "label": "Otras deducciones por pagar",
                "side": "credit",
                "fallback_usages": [],
                "fallback_note": "Config de nómina (2.1.2.1.13)",
                "conditions": [],
            },
        },
    },
    "activos": {
        "label": "Activos fijos",
        "concepts": {
            "activo_depreciacion_gasto": {
                "label": "Gasto de depreciación",
                "side": "debit",
                "fallback_usages": ["depreciacion"],
                "conditions": [],
            },
            "activo_depreciacion_acumulada": {
                "label": "Depreciación acumulada",
                "side": "credit",
                "fallback_usages": ["depreciacion_acumulada"],
                "conditions": [],
            },
            "activo_disposicion_deudor": {
                "label": "Cuenta de ingreso por venta del activo",
                "side": "debit",
                "fallback_usages": ["banco", "efectivo"],
                "conditions": [],
            },
            "activo_utilidad_disposicion": {
                "label": "Utilidad en disposición de activo",
                "side": "credit",
                "fallback_usages": [],
                "fallback_note": "Cuenta 4.2.2 o cuenta de ingresos",
                "conditions": [],
            },
            "activo_perdida_disposicion": {
                "label": "Pérdida en disposición de activo",
                "side": "debit",
                "fallback_usages": [],
                "fallback_note": "Cuenta 6.4.04 o cuenta de pérdida",
                "conditions": [],
            },
        },
    },
    "cierre": {
        "label": "Cierre fiscal",
        "concepts": {
            "cierre_resultados": {
                "label": "Resultados acumulados",
                "side": "credit",
                "fallback_usages": ["resultados_acumulados"],
                "fallback_note": "Cuenta con 'resultado' en el nombre",
                "conditions": [],
            },
        },
    },
}


def _first_by_usages(accounts, usages):
    for usage in usages or []:
        for acc in accounts or []:
            if acc.get("usage") == usage:
                return acc
    return None


def _account_by_id(accounts, account_id):
    if not account_id:
        return None
    for acc in accounts or []:
        if acc.get("id") == account_id:
            return acc
    return None


def _find_rule(rules, transaction, concept, condition_key, condition_value):
    condition_value = condition_value or ""
    for rule in rules or []:
        if rule.get("transaction") != transaction:
            continue
        if rule.get("concept") != concept:
            continue
        if (rule.get("conditionKey") or "") != (condition_key or ""):
            continue
        if (rule.get("conditionValue") or "") != condition_value:
            continue
        if rule.get("isActive") is False:
            continue
        return rule
    return None


class AccountingRulesService:

    @classmethod
    def get_rules(cls, company_id):
        if not company_id:
            return []
        try:
            rules = DatabaseService.get_accounting_rules(company_id, company_id=company_id)
        except Exception:
            return []
        if not isinstance(rules, list):
            return []
        return [r for r in rules if isinstance(r, dict)]

    @classmethod
    def resolve(cls, company_id, transaction, concept, ctx, accounts, rules=None, fallback_usages=None):
        txdef = TRANSACTIONS.get(transaction)
        if not txdef:
            return None
        cdef = (txdef.get("concepts") or {}).get(concept)
        if not cdef:
            return None
        if rules is None:
            rules = cls.get_rules(company_id)
        matched = []
        for cond in cdef.get("conditions") or []:
            cspec = CONDITIONS.get(cond.get("key"))
            if not cspec:
                continue
            if cspec.get("type") == "value":
                value = cspec["value"](ctx or {})
                if value:
                    matched.append((cond, value))
            elif cspec.get("match") and cspec["match"](ctx or {}):
                matched.append((cond, None))
        for cond, value in matched:
            rule = _find_rule(rules, transaction, concept, cond.get("key"), value)
            if rule:
                acc = _account_by_id(accounts, rule.get("accountId", ""))
                if acc:
                    return acc
        rule = _find_rule(rules, transaction, concept, "", None)
        if rule:
            acc = _account_by_id(accounts, rule.get("accountId", ""))
            if acc:
                return acc
        for cond, _value in matched:
            acc = _first_by_usages(accounts, cond.get("fallback_usages"))
            if acc:
                return acc
        usages = cdef.get("fallback_usages") if fallback_usages is None else fallback_usages
        return _first_by_usages(accounts, usages)

    @classmethod
    def save_rule(cls, company_id, rule):
        rule_id = rule.get("id") or "::".join([
            rule.get("transaction", ""),
            rule.get("concept", ""),
            rule.get("conditionKey") or "",
            rule.get("conditionValue") or "",
        ])
        rule["id"] = rule_id
        return DatabaseService.save_accounting_rule(company_id, rule_id, rule, company_id=company_id)

    @classmethod
    def reset_rule(cls, company_id, transaction, concept, condition_key="", condition_value=""):
        rule_id = "::".join([transaction, concept, condition_key or "", condition_value or ""])
        return DatabaseService.delete_accounting_rule(company_id, rule_id, company_id=company_id)

    @classmethod
    def rules_referencing_account(cls, company_id, account_id):
        return [r for r in cls.get_rules(company_id) if r.get("accountId") == account_id]

    @classmethod
    def ensure_initialized(cls, company_id):
        if cls.get_rules(company_id):
            return False
        try:
            accounts = DatabaseService.get_chart_of_accounts(company_id, company_id=company_id)
        except Exception:
            return False
        if not accounts:
            return False
        seeded = 0
        for tx, txdef in TRANSACTIONS.items():
            for concept, cdef in txdef.get("concepts", {}).items():
                entries = [{"key": "", "fallback_usages": cdef.get("fallback_usages") or []}]
                entries.extend(cdef.get("conditions") or [])
                for cond in entries:
                    acc = _first_by_usages(accounts, cond.get("fallback_usages") or [])
                    if not acc:
                        continue
                    cls.save_rule(company_id, {
                        "transaction": tx,
                        "concept": concept,
                        "conditionKey": cond.get("key", ""),
                        "conditionValue": "",
                        "accountId": acc.get("id", ""),
                        "isCustom": False,
                        "isActive": True,
                        "createdBy": "system",
                    })
                    seeded += 1
        return seeded > 0

    @classmethod
    def build_catalog_view(cls, company_id, accounts, rules=None):
        if rules is None:
            rules = cls.get_rules(company_id)
        view = []
        for tx, txdef in TRANSACTIONS.items():
            concepts_view = []
            for concept, cdef in txdef.get("concepts", {}).items():
                default_acc = _first_by_usages(accounts, cdef.get("fallback_usages") or [])
                default_rule = _find_rule(rules, tx, concept, "", None)
                cond_view = []
                for cond in cdef.get("conditions") or []:
                    cspec = CONDITIONS.get(cond.get("key")) or {}
                    cond_rule = _find_rule(rules, tx, concept, cond.get("key"), None)
                    cond_default = _first_by_usages(accounts, cond.get("fallback_usages") or [])
                    cond_view.append({
                        "key": cond.get("key"),
                        "label": cspec.get("label", cond.get("key")),
                        "type": cspec.get("type", "flag"),
                        "defaultAccountId": cond_default.get("id") if cond_default else None,
                        "defaultAccountName": (cond_default.get("code") + " — " + cond_default.get("name")) if cond_default else None,
                        "ruleAccountId": (cond_rule or {}).get("accountId"),
                        "isCustom": bool((cond_rule or {}).get("isCustom")),
                    })
                concepts_view.append({
                    "key": concept,
                    "label": cdef.get("label", concept),
                    "side": cdef.get("side", "debit"),
                    "fallbackNote": cdef.get("fallback_note", ""),
                    "defaultAccountId": default_acc.get("id") if default_acc else None,
                    "defaultAccountName": (default_acc.get("code") + " — " + default_acc.get("name")) if default_acc else None,
                    "ruleAccountId": (default_rule or {}).get("accountId"),
                    "isCustom": bool((default_rule or {}).get("isCustom")),
                    "conditions": cond_view,
                })
            view.append({"key": tx, "label": txdef.get("label", tx), "concepts": concepts_view})
        return view
