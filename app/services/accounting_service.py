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


def _default_chart_of_accounts(country="DO"):
    from app.services.country_provider import CountryProviderFactory
    provider = CountryProviderFactory.create(country)
    if provider:
        return provider.get_default_chart()
    return []


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


def _resolve_bank_account_account(owner_uid, bank_account_id, accounts, sandbox=True):
    """Resuelve la cuenta contable asociada a una cuenta bancaria.
    Si la cuenta bancaria tiene un accountingAccountId asignado, retorna esa cuenta.
    Si no, retorna None para que el sistema use el comportamiento por defecto (por usage).
    """
    if not bank_account_id:
        return None
    try:
        bank = DatabaseService.get_bank_account(owner_uid, bank_account_id, sandbox=sandbox)
        if bank and bank.get("accountingAccountId"):
            acc_id = bank["accountingAccountId"]
            for a in accounts:
                if a.get("id") == acc_id:
                    return a
    except Exception:
        pass
    return None


class AccountingService:

    @classmethod
    def seed_default_accounts(cls, owner_uid, country="DO"):
        existing = DatabaseService.get_chart_of_accounts(owner_uid)
        existing_codes = {a.get("code") for a in existing}
        default_accounts = _default_chart_of_accounts(country)
        if existing:
            missing = [a for a in default_accounts if a["code"] not in existing_codes]
            if not missing:
                return
        else:
            missing = default_accounts

        # Re-leer para prevenir escritura duplicada en concurrencia
        refreshed = DatabaseService.get_chart_of_accounts(owner_uid)
        refreshed_codes = {a.get("code") for a in refreshed}
        missing = [a for a in missing if a["code"] not in refreshed_codes]
        if not missing:
            return

        # Construir parent_map solo con cuentas existentes confirmadas
        parent_map = {}
        for a in refreshed:
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
    def get_accounts_tree(cls, owner_uid, country="DO"):
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        if not accounts:
            cls.seed_default_accounts(owner_uid, country=country)
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        else:
            # Verificar si faltan cuentas del default sin hacer fetch extra
            existing_codes = {a.get("code") for a in accounts}
            missing = [a for a in _default_chart_of_accounts(country) if a["code"] not in existing_codes]
            if missing:
                cls.seed_default_accounts(owner_uid, country=country)
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
    def _compute_balances_map(cls, entries, date_from=None, date_to=None):
        """Calcula un mapa account_id → balance en una sola pasada sobre las entradas."""
        balances = defaultdict(float)
        for entry in entries:
            if entry.get("status") == "voided":
                continue
            entry_date = str(entry.get("date", ""))[:10]
            if date_from and entry_date < date_from:
                continue
            if date_to and entry_date > date_to:
                continue
            for line in entry.get("lines", []):
                aid = line.get("accountId")
                if aid:
                    balances[aid] += float(line.get("debit", 0)) - float(line.get("credit", 0))
        return dict(balances)

    @classmethod
    def get_account_balance(cls, owner_uid, account_id, date_from=None, date_to=None, entries=None):
        if entries is not None:
            # Usar entradas pre-cargadas: cálculo rápido sin consulta a BD
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
        # Fallback: sin entradas pre-cargadas, consultar BD
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
    def get_account_movements(cls, owner_uid, account_id, date_from=None, date_to=None, entries=None):
        movements = []
        if entries is None:
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
                        "entryId": entry.get("id", ""),
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
    def get_balance_sheet(cls, owner_uid, date=None, accounts=None, entries=None, country="DO"):
        if accounts is None:
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
            if not accounts:
                cls.seed_default_accounts(owner_uid, country=country)
                accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        balances = cls._compute_balances_map(entries or [], date_to=date)
        active_accounts = [a for a in accounts if a.get("group") in ("activos", "pasivos", "patrimonio")]
        result = {"activos": {"total": 0.0, "children": []}, "pasivos": {"total": 0.0, "children": []}, "patrimonio": {"total": 0.0, "children": []}}
        for acc in active_accounts:
            if acc.get("type") != "movimiento":
                continue
            balance = balances.get(acc["id"], 0.0)
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
    def get_income_statement(cls, owner_uid, date_from=None, date_to=None, accounts=None, entries=None, country="DO"):
        if accounts is None:
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
            if not accounts:
                cls.seed_default_accounts(owner_uid, country=country)
                accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        balances = cls._compute_balances_map(entries or [], date_from=date_from, date_to=date_to)
        result = {"ingresos": {"total": 0.0, "children": []}, "costos": {"total": 0.0, "children": []}, "gastos": {"total": 0.0, "children": []}}
        for acc in accounts:
            if acc.get("type") != "movimiento":
                continue
            group = acc.get("group")
            if group not in ("ingresos", "costos", "gastos"):
                continue
            balance = balances.get(acc["id"], 0.0)
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
    def get_trial_balance(cls, owner_uid, date=None, accounts=None, entries=None, country="DO"):
        if accounts is None:
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
            if not accounts:
                cls.seed_default_accounts(owner_uid, country=country)
                accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        balances = cls._compute_balances_map(entries or [], date_to=date)
        rows = []
        total_debit = 0.0
        total_credit = 0.0
        for acc in accounts:
            if acc.get("type") != "movimiento":
                continue
            balance = balances.get(acc["id"], 0.0)
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
    def _resolve_debit_account(cls, invoice, accounts, owner_uid=None, sandbox=True):
        # Intentar usar la cuenta contable vinculada a la cuenta bancaria seleccionada
        bank_account_id = invoice.get("bankAccountId", "")
        if bank_account_id and owner_uid:
            linked = _resolve_bank_account_account(owner_uid, bank_account_id, accounts, sandbox=sandbox)
            if linked:
                return linked, f"{linked.get('name', 'Banco')} - {invoice.get('invoiceNumber', '')}"
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
    def auto_generate_invoice_entry(cls, owner_uid, invoice, sandbox=True, country="DO"):
        invoice_id = invoice.get("id", "")
        if _accounting_entry_exists(owner_uid, "invoice", invoice_id):
            return None
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        if not accounts:
            cls.seed_default_accounts(owner_uid, country=country)
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        from app.services.country_provider import CountryProviderFactory
        provider = CountryProviderFactory.create(country)
        mapping = provider.get_account_mapping() if provider else {}
        labels = provider.get_tax_labels() if provider else {}
        debit_acc, debit_desc = cls._resolve_debit_account(invoice, accounts, owner_uid=owner_uid, sandbox=sandbox)
        sales_acc = _find_account_by_usage(accounts, "ventas")
        itbis_acc = _find_account_by_usage(accounts, mapping.get("vat_payable"))
        # Cuentas de retención del lado del cliente (cuando te retienen a ti → ACTIVO)
        itbis_ret_acc = _find_account_by_usages(accounts, [
            mapping.get("vat_withholding_client", "retenciones_a_favor"),
            "retenciones_a_favor",
            "impuesto_a_favor",
        ])
        isr_ret_acc = _find_account_by_usages(accounts, [
            mapping.get("income_tax_withholding_client", "retenciones_a_favor"),
            "retenciones_a_favor",
            "impuesto_a_favor",
        ])
        if not debit_acc or not sales_acc:
            return None
        total = float(invoice.get("netPayable", invoice.get("total", 0)))
        subtotal = float(invoice.get("subtotal", 0))
        itbis = float(invoice.get("totalITBIS", invoice.get("itbis", 0)))
        retained_isr = float(invoice.get("retainedISR", 0))
        retained_itbis = float(invoice.get("retainedITBIS", 0))
        branch_id = invoice.get("branchId", "")
        cost_center_id = invoice.get("costCenterId", "")
        currency = invoice.get("currency", provider.currency if provider else "DOP")
        client_id = invoice.get("clientId", "")
        client_name = invoice.get("clientName", "")

        items = invoice.get("items", [])
        missing_cost = [it for it in items if it.get("type", "Bien") == "Bien" and not (float(it.get("costPrice", 0) or 0) > 0)]
        if missing_cost:
            catalog_items = {}
            try:
                from app.services.db_service import db_firestore, firebase_initialized
                if firebase_initialized and db_firestore:
                    coll_name = "sandbox_items" if sandbox else "items"
                    docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).stream()
                    for doc in docs:
                        data = doc.to_dict()
                        data["id"] = doc.id
                        catalog_items[data["id"]] = data
            except Exception:
                pass
            catalog_by_name = {ci.get("name", "").strip().lower(): ci for ci in catalog_items.values()}
            catalog_by_code = {ci.get("code", "").strip().lower(): ci for ci in catalog_items.values() if ci.get("code")}
            for it in missing_cost:
                cat = (catalog_items.get(it.get("itemId", "")) or
                       catalog_by_code.get((it.get("code", "") or "").strip().lower()) or
                       catalog_by_name.get((it.get("name", "") or "").strip().lower()))
                if cat and float(cat.get("costPrice", 0) or 0) > 0:
                    it["costPrice"] = float(cat["costPrice"])

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
                "description": labels.get("vat_invoice", "ITBIS factura"),
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
                "description": labels.get("vat_withholding_client", "ITBIS retenido por cliente"),
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
                "description": labels.get("income_tax_withholding_client", "ISR retenido por cliente"),
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
                "concept": f"Factura de venta {invoice.get('invoiceNumber', '')} - {client_name}",
                "referenceType": "invoice",
                "referenceId": invoice_id,
                "referenceNumber": invoice.get("invoiceNumber", ""),
                "lines": lines,
                "createdBy": "system",
                "prefix": "A",
            }, sandbox=sandbox)
            return entry
        except ValueError as e:
            from flask import current_app
            current_app.logger.warning(f"auto_generate_invoice_entry desbalanceada ({invoice_id}): {e}")
            return None

    @classmethod
    def auto_generate_client_advance_entry(cls, owner_uid, advance, sandbox=True, country="DO"):
        advance_id = advance.get("id", "")
        if _accounting_entry_exists(owner_uid, "client_advance", advance_id):
            return None
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        if not accounts:
            cls.seed_default_accounts(owner_uid, country=country)
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        anticipo_acc = _find_account_by_usage(accounts, "anticipos_recibidos")
        if not anticipo_acc:
            return None
        # Intentar usar la cuenta contable vinculada a la cuenta bancaria
        bank_id = advance.get("bankAccountId", "")
        debit_acc = _resolve_bank_account_account(owner_uid, bank_id, accounts, sandbox=sandbox)
        if not debit_acc:
            payment_method = advance.get("paymentMethod", "Efectivo")
            if payment_method in ("Transferencia", "Tarjeta de Crédito", "Tarjeta de Débito"):
                debit_acc = _find_account_by_usages(accounts, ["banco", "transferencias_bancarias"])
            else:
                debit_acc = _find_account_by_usages(accounts, ["efectivo", "banco"])
        if not debit_acc:
            return None
        amount = float(advance.get("amount", 0))
        client_name = advance.get("clientName", "")
        branch_id = advance.get("branchId", "")
        project_id = advance.get("projectId")
        lines = [{
            "accountId": debit_acc["id"],
            "accountCode": debit_acc.get("code", ""),
            "accountName": debit_acc.get("name", ""),
            "debit": round(amount, 2),
            "credit": 0.00,
            "description": f"Anticipo recibido de {client_name}",
            "contactId": advance.get("clientId", ""),
            "contactName": client_name,
            "branchId": branch_id,
            "costCenterId": "",
            "currency": "DOP",
            "projectId": project_id
        }, {
            "accountId": anticipo_acc["id"],
            "accountCode": anticipo_acc.get("code", ""),
            "accountName": anticipo_acc.get("name", ""),
            "debit": 0.00,
            "credit": round(amount, 2),
            "description": f"Anticipo de {client_name}",
            "contactId": advance.get("clientId", ""),
            "contactName": client_name,
            "branchId": branch_id,
            "costCenterId": "",
            "currency": "DOP",
            "projectId": project_id
        }]
        try:
            entry = cls.generate_entry(owner_uid, {
                "entryType": "client_advance",
                "date": str(advance.get("paymentDate", ""))[:10],
                "concept": f"Anticipo de cliente {client_name} - RD$ {amount:,.2f}",
                "referenceType": "client_advance",
                "referenceId": advance_id,
                "referenceNumber": advance.get("referenceNumber", ""),
                "lines": lines,
                "createdBy": advance.get("registeredBy", "system"),
                "prefix": "A",
            }, sandbox=sandbox)
            return entry
        except ValueError as e:
            from flask import current_app
            current_app.logger.warning(f"auto_generate_client_advance_entry desbalanceado ({advance_id}): {e}")
            return None

    @classmethod
    def auto_generate_advance_application_entry(cls, owner_uid, invoice, advances, sandbox=True, country="DO"):
        invoice_id = invoice.get("id", "")
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        if not accounts:
            cls.seed_default_accounts(owner_uid, country=country)
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        anticipo_acc = _find_account_by_usage(accounts, "anticipos_recibidos")
        if not anticipo_acc:
            return None
        payment_type = invoice.get("paymentType", "Contado")
        if payment_type == "Contado":
            # Intentar usar la cuenta contable vinculada a la cuenta bancaria
            bank_id = invoice.get("bankAccountId", "")
            debit_acc = _resolve_bank_account_account(owner_uid, bank_id, accounts, sandbox=sandbox)
            if not debit_acc:
                debit_acc = _find_account_by_usages(accounts, ["efectivo", "banco"])
        else:
            debit_acc = _find_account_by_usages(accounts, ["cxc", "banco", "efectivo"])
        if not debit_acc:
            return None
        total_applied = sum(float(a.get("amount", 0)) for a in advances)
        if total_applied <= 0:
            return None
        lines = [{
            "accountId": anticipo_acc["id"],
            "accountCode": anticipo_acc.get("code", ""),
            "accountName": anticipo_acc.get("name", ""),
            "debit": round(total_applied, 2),
            "credit": 0.00,
            "description": f"Aplicación de anticipos a factura {invoice.get('invoiceNumber', '')}",
            "branchId": invoice.get("branchId", ""),
            "costCenterId": invoice.get("costCenterId", ""),
            "currency": invoice.get("currency", "DOP"),
            "projectId": invoice.get("projectId")
        }, {
            "accountId": debit_acc["id"],
            "accountCode": debit_acc.get("code", ""),
            "accountName": debit_acc.get("name", ""),
            "debit": 0.00,
            "credit": round(total_applied, 2),
            "description": f"Anticipos aplicados - Factura {invoice.get('invoiceNumber', '')}",
            "branchId": invoice.get("branchId", ""),
            "costCenterId": invoice.get("costCenterId", ""),
            "currency": invoice.get("currency", "DOP"),
            "projectId": invoice.get("projectId")
        }]
        try:
            entry = cls.generate_entry(owner_uid, {
                "entryType": "advance_application",
                "date": str(invoice.get("date", ""))[:10],
                "concept": f"Aplicación de anticipos a factura {invoice.get('invoiceNumber', '')} - RD$ {total_applied:,.2f}",
                "referenceType": "advance_application",
                "referenceId": invoice_id,
                "referenceNumber": invoice.get("invoiceNumber", ""),
                "lines": lines,
                "createdBy": "system",
                "prefix": "A",
            }, sandbox=sandbox)
            return entry
        except ValueError as e:
            from flask import current_app
            current_app.logger.warning(f"auto_generate_advance_application_entry desbalanceado ({invoice_id}): {e}")
            return None

    @classmethod
    def _build_inventory_adjustment_lines(cls, operation_type, items, accounts, reference_id=""):
        """
        Genera líneas contables para operaciones de inventario:
        - ajuste (+/-): ajusta inventario contra cuenta de ajustes
        - transferencia: mueve entre almacenes (sin efecto en resultados)
        - merma: descarga inventario contra cuenta de mermas/pérdidas
        """
        inv_acc = _find_account_by_usage(accounts, "inventario")
        if not inv_acc:
            return []
        lines = []
        if operation_type == "ajuste":
            ajuste_acc = _find_account_by_usage(accounts, "ajuste_inventario")
            if not ajuste_acc:
                ajuste_acc = _find_account_by_usage(accounts, "costo_ventas")
            if not ajuste_acc:
                return []
            for it in items:
                qty_diff = float(it.get("qtyDiff", it.get("quantity", 0)))
                cost_price = float(it.get("costPrice", 0))
                if abs(qty_diff) < 0.001 or cost_price <= 0:
                    continue
                total = round(abs(qty_diff) * cost_price, 2)
                name = it.get("name", "Item")
                if qty_diff > 0:
                    # Entrada: débito inventario, crédito ajustes
                    lines.append({
                        "accountId": inv_acc["id"], "accountCode": inv_acc.get("code", ""),
                        "accountName": inv_acc.get("name", ""), "debit": total, "credit": 0.00,
                        "description": f"Ajuste (+): {name}"
                    })
                    lines.append({
                        "accountId": ajuste_acc["id"], "accountCode": ajuste_acc.get("code", ""),
                        "accountName": ajuste_acc.get("name", ""), "debit": 0.00, "credit": total,
                        "description": f"Ajuste inventario (+): {name}"
                    })
                else:
                    # Salida: débito ajustes, crédito inventario
                    lines.append({
                        "accountId": ajuste_acc["id"], "accountCode": ajuste_acc.get("code", ""),
                        "accountName": ajuste_acc.get("name", ""), "debit": total, "credit": 0.00,
                        "description": f"Ajuste (-): {name}"
                    })
                    lines.append({
                        "accountId": inv_acc["id"], "accountCode": inv_acc.get("code", ""),
                        "accountName": inv_acc.get("name", ""), "debit": 0.00, "credit": total,
                        "description": f"Ajuste inventario (-): {name}"
                    })
        elif operation_type == "merma":
            merma_acc = _find_account_by_usage(accounts, "merma_perdida")
            if not merma_acc:
                merma_acc = _find_account_by_usage(accounts, "costo_ventas")
            if not merma_acc:
                return []
            for it in items:
                qty = abs(float(it.get("quantity", 0)))
                cost_price = float(it.get("costPrice", 0))
                if qty < 0.001 or cost_price <= 0:
                    continue
                total = round(qty * cost_price, 2)
                name = it.get("name", "Item")
                lines.append({
                    "accountId": merma_acc["id"], "accountCode": merma_acc.get("code", ""),
                    "accountName": merma_acc.get("name", ""), "debit": total, "credit": 0.00,
                    "description": f"Merma: {name}"
                })
                lines.append({
                    "accountId": inv_acc["id"], "accountCode": inv_acc.get("code", ""),
                    "accountName": inv_acc.get("name", ""), "debit": 0.00, "credit": total,
                    "description": f"Descargo por merma: {name}"
                    })
        elif operation_type == "transferencia":
            for it in items:
                qty = abs(float(it.get("quantity", 0)))
                cost_price = float(it.get("costPrice", 0))
                if qty < 0.001:
                    continue
                total = round(qty * cost_price, 2) if cost_price > 0 else 0
                name = it.get("name", "Item")
                origin = it.get("originWarehouseName", "Origen")
                dest = it.get("destinationWarehouseName", "Destino")
                lines.append({
                    "accountId": inv_acc["id"], "accountCode": inv_acc.get("code", ""),
                    "accountName": inv_acc.get("name", ""), "debit": total, "credit": 0.00,
                    "description": f"Transferencia recibida: {name} ({dest})"
                })
                lines.append({
                    "accountId": inv_acc["id"], "accountCode": inv_acc.get("code", ""),
                    "accountName": inv_acc.get("name", ""), "debit": 0.00, "credit": total,
                    "description": f"Transferencia enviada: {name} ({origin})"
                })
        return lines

    @classmethod
    def auto_generate_inventory_entry(cls, owner_uid, operation_type, items, reference_id="", performed_by="", sandbox=True, country="DO"):
        """
        Genera asiento contable para operaciones de inventario (ajustes, mermas, transferencias).
        operation_type: 'ajuste', 'merma', 'transferencia'
        """
        if _accounting_entry_exists(owner_uid, "inventory", reference_id):
            return None
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        if not accounts:
            cls.seed_default_accounts(owner_uid, country=country)
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        lines = cls._build_inventory_adjustment_lines(operation_type, items, accounts, reference_id)
        if not lines:
            return None
        concept = f"{'Ajuste' if operation_type == 'ajuste' else 'Merma' if operation_type == 'merma' else 'Transferencia'} de inventario"
        try:
            entry = cls.generate_entry(owner_uid, {
                "entryType": "inventory",
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "concept": concept,
                "referenceType": "inventory",
                "referenceId": reference_id,
                "lines": lines,
                "createdBy": performed_by or "system",
                "prefix": "A",
            }, sandbox=sandbox)
            return entry
        except ValueError as e:
            from flask import current_app
            current_app.logger.warning(f"auto_generate_inventory_entry desbalanceado ({reference_id}): {e}")
            return None

    @classmethod
    def auto_reverse_invoice_entry(cls, owner_uid, invoice, reason="", user_id="", sandbox=True, country="DO"):
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
            from app.services.country_provider import CountryProviderFactory
            provider = CountryProviderFactory.create(country)
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
                    "currency": line.get("currency", provider.currency if provider else "DOP")
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
            except ValueError as e:
                from flask import current_app
                current_app.logger.warning(f"auto_reverse_invoice_entry desbalanceado ({invoice_id}): {e}")
                continue
        return reversed_entries[0] if reversed_entries else None

    @classmethod
    def auto_generate_credit_note_entry(cls, owner_uid, invoice, sandbox=True, country="DO"):
        invoice_id = invoice.get("id", "")
        if _accounting_entry_exists(owner_uid, "credit_note", invoice_id):
            return None
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        if not accounts:
            cls.seed_default_accounts(owner_uid, country=country)
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        from app.services.country_provider import CountryProviderFactory
        provider = CountryProviderFactory.create(country)
        mapping = provider.get_account_mapping() if provider else {}
        labels = provider.get_tax_labels() if provider else {}
        cxc_acc = _find_account_by_usage(accounts, "cxc")
        sales_acc = _find_account_by_usage(accounts, "ventas")
        devolucion_acc = _find_account_by_usages(accounts, ["devoluciones_ventas", "devoluciones_clientes"])
        itbis_acc = _find_account_by_usage(accounts, mapping.get("vat_payable"))
        if not cxc_acc or not sales_acc:
            return None
        total = float(invoice.get("netPayable", invoice.get("total", 0)))
        subtotal = float(invoice.get("subtotal", 0))
        itbis = float(invoice.get("totalITBIS", invoice.get("itbis", 0)))
        branch_id = invoice.get("branchId", "")
        cost_center_id = invoice.get("costCenterId", "")
        currency = invoice.get("currency", provider.currency if provider else "DOP")
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
                "description": labels.get("vat_credit_note", "ITBIS devolución"),
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
        except ValueError as e:
            from flask import current_app
            current_app.logger.warning(f"auto_generate_credit_note_entry desbalanceada ({invoice.get('id', '')}): {e}")
            return None

    @classmethod
    def auto_generate_expense_entry(cls, owner_uid, expense, sandbox=True, country="DO"):
        expense_id = expense.get("id", "")
        if _accounting_entry_exists(owner_uid, "expense", expense_id):
            return None
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        if not accounts:
            cls.seed_default_accounts(owner_uid, country=country)
            accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        from app.services.country_provider import CountryProviderFactory
        provider = CountryProviderFactory.create(country)
        mapping = provider.get_account_mapping() if provider else {}
        labels = provider.get_tax_labels() if provider else {}
        cxp_acc = _find_account_by_usage(accounts, "cxp")
        compras_acc = _find_account_by_usage(accounts, "compras")
        gastos_acc = _find_account_by_usage(accounts, "gastos")
        banco_acc = _find_account_by_usages(accounts, ["banco", "efectivo"])
        itbis_credito_acc = _find_account_by_usage(accounts, mapping.get("vat_credit"))
        itbis_retenido_acc = _find_account_by_usage(accounts, mapping.get("vat_withholding"))
        isr_retenido_acc = _find_account_by_usage(accounts, mapping.get("income_tax_withholding"))
        total = float(expense.get("amount", expense.get("total", 0)))
        account_items = expense.get("accountItems", [])
        payment_type = expense.get("paymentType", expense.get("payment_type", "Contado"))
        lines = []

        if account_items:
            # Usar cuentas específicas seleccionadas por el usuario
            total_debit_computed = 0.0
            for item in account_items:
                concept_id = item.get("concept_id", "")
                item_value = float(item.get("value", 0))
                item_total = float(item.get("total", 0))
                tax_amount = round(item_total - item_value, 2)

                if concept_id:
                    acc = next((a for a in accounts if a.get("id") == concept_id), None)
                else:
                    acc = None

                if acc:
                    lines.append({
                        "accountId": acc["id"],
                        "accountCode": acc.get("code", ""),
                        "accountName": acc.get("name", ""),
                        "debit": round(item_value, 2),
                        "credit": 0.00,
                        "description": item.get("concept", "") or expense.get("concept", ""),
                    })
                    total_debit_computed += item_value
                else:
                    fallback = gastos_acc or compras_acc
                    lines.append({
                        "accountId": fallback["id"] if fallback else "",
                        "accountCode": fallback.get("code", "-") if fallback else "-",
                        "accountName": fallback.get("name", item.get("concept", "Gasto")) if fallback else item.get("concept", "Gasto"),
                        "debit": round(item_total, 2),
                        "credit": 0.00,
                        "description": item.get("concept", "") or expense.get("concept", ""),
                    })
                    total_debit_computed += item_total

                if tax_amount > 0 and itbis_credito_acc:
                    lines.append({
                        "accountId": itbis_credito_acc["id"],
                        "accountCode": itbis_credito_acc.get("code", ""),
                        "accountName": itbis_credito_acc.get("name", ""),
                        "debit": round(tax_amount, 2),
                        "credit": 0.00,
                        "description": labels.get("vat_credit", "ITBIS crédito fiscal"),
                    })
                    total_debit_computed += tax_amount

            # Retenciones
            retained_isr_amount = 0.0
            retained_isr_rate = float(expense.get("retainedISR", 0))
            retained_itbis_amount = 0.0
            retained_itbis_rate = float(expense.get("retainedITBIS", 0))
            if retained_isr_rate > 0:
                retained_isr_amount = round(total * retained_isr_rate, 2)
            if retained_itbis_rate > 0:
                tax_total = sum(max(0, round(float(it.get("total", 0)) - float(it.get("value", 0)), 2)) for it in account_items)
                retained_itbis_amount = round(tax_total * retained_itbis_rate, 2)

            if retained_isr_amount > 0 and isr_retenido_acc:
                lines.append({
                    "accountId": isr_retenido_acc["id"],
                    "accountCode": isr_retenido_acc.get("code", ""),
                    "accountName": isr_retenido_acc.get("name", ""),
                    "debit": 0.00,
                    "credit": round(retained_isr_amount, 2),
                    "description": labels.get("income_tax_withholding", "ISR retenido"),
                })
            if retained_itbis_amount > 0 and itbis_retenido_acc:
                lines.append({
                    "accountId": itbis_retenido_acc["id"],
                    "accountCode": itbis_retenido_acc.get("code", ""),
                    "accountName": itbis_retenido_acc.get("name", ""),
                    "debit": 0.00,
                    "credit": round(retained_itbis_amount, 2),
                    "description": labels.get("vat_withholding", "ITBIS retenido"),
                })

            # Crédito: CXP o Banco/Efectivo
            credit_amount = round(total - retained_isr_amount - retained_itbis_amount, 2)
            if payment_type == "Contado":
                # Intentar usar la cuenta contable vinculada a la cuenta bancaria
                bank_id = expense.get("bankAccountId", "")
                credit_acc = _resolve_bank_account_account(owner_uid, bank_id, accounts, sandbox=sandbox)
                if not credit_acc:
                    credit_acc = banco_acc
            elif cxp_acc:
                credit_acc = cxp_acc
            else:
                credit_acc = None
            if credit_acc and credit_amount > 0:
                lines.append({
                    "accountId": credit_acc["id"],
                    "accountCode": credit_acc.get("code", ""),
                    "accountName": credit_acc.get("name", ""),
                    "debit": 0.00,
                    "credit": round(credit_amount, 2),
                    "description": expense.get("concept", "") or "Pago",
                })
        else:
            # Fallback genérico cuando no hay account_items específicos
            itbis = float(expense.get("itbisAmount", expense.get("itbis", 0)))
            net = max(0, total - itbis)
            if compras_acc and expense.get("isCost"):
                lines.append({"accountId": compras_acc["id"], "accountCode": compras_acc.get("code", ""), "accountName": compras_acc.get("name", ""), "debit": round(net, 2), "credit": 0.00, "description": expense.get("concept", "")})
            elif gastos_acc:
                lines.append({"accountId": gastos_acc["id"], "accountCode": gastos_acc.get("code", ""), "accountName": gastos_acc.get("name", ""), "debit": round(net, 2), "credit": 0.00, "description": expense.get("concept", "")})
            if itbis > 0 and itbis_credito_acc:
                lines.append({"accountId": itbis_credito_acc["id"], "accountCode": itbis_credito_acc.get("code", ""), "accountName": itbis_credito_acc.get("name", ""), "debit": round(itbis, 2), "credit": 0.00, "description": labels.get("vat", "ITBIS")})
            # Retenciones en el fallback
            retained_isr_amount = 0.0
            retained_itbis_amount = 0.0
            retained_isr_rate = float(expense.get("retainedISR", 0))
            retained_itbis_rate = float(expense.get("retainedITBIS", 0))
            if retained_isr_rate > 0:
                retained_isr_amount = round(total * retained_isr_rate, 2)
            if retained_itbis_rate > 0:
                retained_itbis_amount = round(itbis * retained_itbis_rate, 2)
            if retained_isr_amount > 0 and isr_retenido_acc:
                lines.append({"accountId": isr_retenido_acc["id"], "accountCode": isr_retenido_acc.get("code", ""), "accountName": isr_retenido_acc.get("name", ""), "debit": 0.00, "credit": round(retained_isr_amount, 2), "description": labels.get("income_tax_withholding", "ISR retenido")})
            if retained_itbis_amount > 0 and itbis_retenido_acc:
                lines.append({"accountId": itbis_retenido_acc["id"], "accountCode": itbis_retenido_acc.get("code", ""), "accountName": itbis_retenido_acc.get("name", ""), "debit": 0.00, "credit": round(retained_itbis_amount, 2), "description": labels.get("vat_withholding", "ITBIS retenido")})
            credit_amount = round(total - retained_isr_amount - retained_itbis_amount, 2)
            credit_acc = None
            if payment_type == "Contado":
                # Intentar usar la cuenta contable vinculada a la cuenta bancaria
                bank_id = expense.get("bankAccountId", "")
                credit_acc = _resolve_bank_account_account(owner_uid, bank_id, accounts, sandbox=sandbox)
                if not credit_acc:
                    credit_acc = banco_acc
            elif cxp_acc:
                credit_acc = cxp_acc
            if credit_acc and credit_amount > 0:
                lines.append({"accountId": credit_acc["id"], "accountCode": credit_acc.get("code", ""), "accountName": credit_acc.get("name", ""), "debit": 0.00, "credit": round(credit_amount, 2), "description": expense.get("concept", "")})

        try:
            supplier_name = expense.get("providerName", expense.get("supplierName", ""))
            concept = expense.get("concept", "")
            ncf = expense.get("ncf", "")
            entry = cls.generate_entry(owner_uid, {
                "entryType": "expense",
                "date": str(expense.get("date", ""))[:10],
                "concept": f"Gasto {ncf} - {supplier_name} - {concept}"[:200],
                "referenceType": "expense",
                "referenceId": expense.get("id", ""),
                "referenceNumber": ncf,
                "lines": lines,
                "createdBy": "system",
                "prefix": "A",
            }, sandbox=sandbox)
            return entry
        except ValueError as e:
            from flask import current_app
            current_app.logger.warning(f"auto_generate_expense_entry desbalanceado ({expense.get('id', '')}): {e}")
            return None

    @classmethod
    def auto_generate_depreciation_entry(cls, owner_uid, dep_data, sandbox=True):
        """Genera asiento contable para depreciación de activos fijos.

        Args:
            owner_uid: ID de la empresa.
            dep_data: Diccionario con datos de depreciación. Debe contener:
                - asset_id: ID del activo
                - asset_name: Nombre del activo
                - amount: Monto depreciado
                - expense_account_id: ID de cuenta de gasto
                - accum_account_id: ID de cuenta de depreciación acumulada
                - period: Período ('mensual' o 'anual')
                - code: Código del activo (opcional)
            sandbox: Si es entorno sandbox.

        Returns:
            El entry generado, o None si ya existe.
        """
        asset_id = dep_data.get("asset_id", dep_data.get("assetId", ""))
        if _accounting_entry_exists(owner_uid, "depreciation", asset_id):
            return None

        amount = float(dep_data.get("amount", 0))
        asset_name = dep_data.get("asset_name", dep_data.get("assetName", "Activo"))
        expense_account_id = dep_data.get("expense_account_id", dep_data.get("expenseAccountId", ""))
        accum_account_id = dep_data.get("accum_account_id", dep_data.get("accumAccountId", ""))
        period = dep_data.get("period", "mensual")
        code = dep_data.get("code", "")

        if not expense_account_id or not accum_account_id:
            return None

        lines = [
            {
                "accountId": expense_account_id,
                "accountCode": "",
                "accountName": "Gasto Depreciación",
                "debit": round(amount, 2),
                "credit": 0.00,
                "description": f"Dep. {asset_name}",
            },
            {
                "accountId": accum_account_id,
                "accountCode": "",
                "accountName": "Depreciación Acumulada",
                "debit": 0.00,
                "credit": round(amount, 2),
                "description": f"Dep. {asset_name}",
            },
        ]

        try:
            entry = cls.generate_entry(owner_uid, {
                "entryType": "depreciation",
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "concept": f"Depreciación {period} — {asset_name}",
                "referenceType": "depreciation",
                "referenceId": asset_id,
                "referenceNumber": code,
                "lines": lines,
                "createdBy": "system",
                "prefix": "DP",
            }, sandbox=sandbox)
            return entry
        except ValueError as e:
            from flask import current_app
            current_app.logger.warning(f"auto_generate_depreciation_entry desbalanceado ({asset_id}): {e}")
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
