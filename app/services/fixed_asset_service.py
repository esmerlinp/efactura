import uuid
from datetime import datetime, timezone, timedelta
from app.services.db_service import DatabaseService
from app.services.accounting_service import AccountingService


ASSET_CATEGORIES = {
    "terrenos": {"label": "Terrenos", "useful_life_months": None},
    "edificios": {"label": "Edificios", "useful_life_months": 240},
    "mobiliario": {"label": "Mobiliario y Equipo de Oficina", "useful_life_months": 120},
    "equipos_computo": {"label": "Equipos de Computación", "useful_life_months": 36},
    "maquinaria": {"label": "Maquinaria y Equipo", "useful_life_months": 120},
    "vehiculos": {"label": "Vehículos", "useful_life_months": 60},
    "intangibles": {"label": "Activos Intangibles", "useful_life_months": 60},
}


class FixedAssetService:

    @classmethod
    def register_asset(cls, owner_uid, asset_data, sandbox=True):
        asset_id = str(uuid.uuid4())
        category = asset_data.get("category", "equipos_computo")
        cat_info = ASSET_CATEGORIES.get(category, {})
        useful_life = asset_data.get("usefulLife") or cat_info.get("useful_life_months") or 36
        purchase_amount = float(asset_data.get("purchaseAmount", 0))
        residual_value = float(asset_data.get("residualValue", 0))
        life_months = int(useful_life)
        depreciable_amount = purchase_amount - residual_value
        rate = round(100.0 / life_months, 2) if life_months > 0 else 0

        asset = {
            "id": asset_id,
            "code": asset_data.get("code", f"AF-{asset_id[:8].upper()}"),
            "name": asset_data.get("name", ""),
            "assetType": asset_data.get("assetType", "tangible"),
            "category": category,
            "accountId": asset_data.get("accountId"),
            "depreciationAccountId": asset_data.get("depreciationAccountId"),
            "depreciationExpenseAccountId": asset_data.get("depreciationExpenseAccountId"),
            "description": asset_data.get("description", ""),
            "purchaseDate": asset_data.get("purchaseDate", ""),
            "purchaseAmount": purchase_amount,
            "supplierId": asset_data.get("supplierId"),
            "supplierName": asset_data.get("supplierName", ""),
            "location": asset_data.get("location", ""),
            "responsible": asset_data.get("responsible", ""),
            "usefulLife": life_months,
            "usefulLifeUnit": "meses",
            "depreciationMethod": "lineal",
            "depreciationRate": rate,
            "residualValue": residual_value,
            "currentValue": purchase_amount,
            "accumulatedDepreciation": 0.0,
            "depreciationPeriod": asset_data.get("depreciationPeriod", "mensual"),
            "lastDepreciationDate": None,
            "nextDepreciationDate": cls._calc_next_date(asset_data.get("purchaseDate"), asset_data.get("depreciationPeriod", "mensual")),
            "status": "active",
            "disposalDate": None,
            "disposalAmount": None,
            "disposalReason": None,
            "images": asset_data.get("images", []),
            "attachments": asset_data.get("attachments", []),
            "notes": asset_data.get("notes", ""),
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
        DatabaseService.save_fixed_asset(owner_uid, asset_id, asset, sandbox=sandbox)
        return asset

    @classmethod
    def _calc_next_date(cls, purchase_date, period="mensual"):
        if not purchase_date:
            return ""
        try:
            d = datetime.strptime(str(purchase_date)[:10], "%Y-%m-%d")
        except ValueError:
            return ""
        if period == "mensual":
            next_d = d + timedelta(days=30)
        else:
            next_d = d + timedelta(days=365)
        return next_d.strftime("%Y-%m-%d")

    @classmethod
    def register_depreciation(cls, owner_uid, asset_id, periods=None, sandbox=True):
        asset = DatabaseService.get_fixed_asset(owner_uid, asset_id, sandbox=sandbox)
        if not asset:
            return None
        if asset.get("status") != "active":
            raise ValueError(f"El activo {asset.get('name')} no está activo")
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        expense_account_id = asset.get("depreciationExpenseAccountId")
        accum_account_id = asset.get("depreciationAccountId")
        if not expense_account_id or not accum_account_id:
            raise ValueError("El activo no tiene cuentas contables de depreciación configuradas")
        period = asset.get("depreciationPeriod", "mensual")
        per_period_amount = cls._calc_period_depreciation(asset)
        if per_period_amount <= 0:
            raise ValueError("El activo ya está totalmente depreciado o no tiene valor depreciable")
        if not periods:
            periods = 1
        total_amount = per_period_amount * periods
        remaining = asset.get("currentValue", 0) - asset.get("residualValue", 0)
        if total_amount > remaining:
            total_amount = max(0, remaining)
        if total_amount <= 0:
            raise ValueError("El activo ya está totalmente depreciado")
        now = datetime.now(timezone.utc)
        entry = AccountingService.generate_entry(owner_uid, {
            "entryType": "depreciation",
            "date": now.strftime("%Y-%m-%d"),
            "concept": f"Depreciación {period} — {asset.get('name', '')}",
            "referenceType": "depreciation",
            "referenceId": asset_id,
            "referenceNumber": asset.get("code", ""),
            "lines": [
                {"accountId": expense_account_id, "accountCode": "", "accountName": "Gasto Depreciación", "debit": round(total_amount, 2), "credit": 0.00, "description": f"Dep. {asset.get('name')}"},
                {"accountId": accum_account_id, "accountCode": "", "accountName": "Depreciación Acumulada", "debit": 0.00, "credit": round(total_amount, 2), "description": f"Dep. {asset.get('name')}"},
            ],
            "createdBy": "system",
        }, sandbox=sandbox)
        new_accum = asset.get("accumulatedDepreciation", 0) + total_amount
        new_value = asset.get("purchaseAmount", 0) - new_accum
        asset["accumulatedDepreciation"] = round(new_accum, 2)
        asset["currentValue"] = round(max(new_value, 0), 2)
        asset["lastDepreciationDate"] = now.strftime("%Y-%m-%d")
        next_date = cls._calc_next_date(now.strftime("%Y-%m-%d"), period)
        asset["nextDepreciationDate"] = next_date
        if asset["currentValue"] <= asset.get("residualValue", 0):
            asset["status"] = "fully_depreciated"
        asset["updatedAt"] = now.isoformat()
        DatabaseService.save_fixed_asset(owner_uid, asset_id, asset, sandbox=sandbox)
        return {"entry": entry, "asset": asset, "amount": round(total_amount, 2)}

    @classmethod
    def _calc_period_depreciation(cls, asset):
        purchase_amount = float(asset.get("purchaseAmount", 0))
        residual = float(asset.get("residualValue", 0))
        useful_life = int(asset.get("usefulLife", 36))
        method = asset.get("depreciationMethod", "lineal")
        period = asset.get("depreciationPeriod", "mensual")
        current_value = float(asset.get("currentValue", purchase_amount))
        accum = float(asset.get("accumulatedDepreciation", 0))

        if useful_life <= 0:
            return 0
        depreciable = purchase_amount - residual
        if depreciable <= 0:
            return 0

        periods_per_year = 12 if period == "mensual" else 1
        total_periods = useful_life if period == "mensual" else max(1, useful_life / 12)

        if method == "lineal":
            return round(depreciable / total_periods, 2)
        elif method == "decreciente":
            rate = 2.0 / total_periods
            amount = round((current_value - residual) * rate, 2)
            return max(amount, 0.0)
        elif method == "syd":
            remaining_periods = total_periods - int(accum / max(depreciable / total_periods, 1))
            remaining_periods = max(remaining_periods, 1)
            syd_sum = total_periods * (total_periods + 1) / 2
            amount = round(depreciable * remaining_periods / syd_sum, 2)
            return max(amount, 0.0)
        else:
            return round(depreciable / total_periods, 2)

    @classmethod
    def dispose_asset(cls, owner_uid, asset_id, disposal_data, sandbox=True):
        asset = DatabaseService.get_fixed_asset(owner_uid, asset_id, sandbox=sandbox)
        if not asset:
            return None
        disposal_date = disposal_data.get("disposalDate", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        disposal_amount = float(disposal_data.get("disposalAmount", 0))
        disposal_reason = disposal_data.get("disposalReason", "Venta")
        book_value = asset.get("currentValue", 0)
        accum_dep = asset.get("accumulatedDepreciation", 0)
        purchase_amount = asset.get("purchaseAmount", 0)
        accounts = DatabaseService.get_chart_of_accounts(owner_uid)
        lines = []
        if accum_dep > 0:
            accum_account = asset.get("depreciationAccountId")
            if accum_account:
                lines.append({
                    "accountId": accum_account, "accountCode": "", "accountName": "Depreciación Acumulada",
                    "debit": round(accum_dep, 2), "credit": 0.00, "description": f"Baja de {asset.get('name')}"
                })
        asset_account = asset.get("accountId")
        if asset_account:
            lines.append({
                "accountId": asset_account, "accountCode": "", "accountName": asset.get("name", "Activo"),
                "debit": 0.00, "credit": round(purchase_amount, 2), "description": f"Baja de {asset.get('name')}"
            })
        diff = disposal_amount - book_value
        if abs(diff) > 0.01:
            if diff > 0:
                gain_account = next((a for a in accounts if a.get("code") == "4.2.2"), None) or \
                               next((a for a in accounts if "ingreso" in (a.get("name") or "").lower()), None)
                if gain_account:
                    lines.append({
                        "accountId": gain_account.get("id"), "accountCode": gain_account.get("code", ""),
                        "accountName": f"Ganancia por venta de {asset.get('name', 'Activo')}",
                        "debit": 0.00, "credit": round(diff, 2),
                        "description": f"Utilidad en disposición de {asset.get('name')}"
                    })
            else:
                loss_account = next((a for a in accounts if a.get("code") == "6.4.04"), None) or \
                               next((a for a in accounts if "pérdida" in (a.get("name") or "").lower()), None)
                if loss_account:
                    lines.append({
                        "accountId": loss_account.get("id"), "accountCode": loss_account.get("code", ""),
                        "accountName": f"Pérdida por venta de {asset.get('name', 'Activo')}",
                        "debit": round(abs(diff), 2), "credit": 0.00,
                        "description": f"Pérdida en disposición de {asset.get('name')}"
                    })
        if disposal_amount > 0:
            bank_account = _find_account_by_usage(accounts, "banco") or _find_account_by_usage(accounts, "efectivo")
            if bank_account:
                lines.append({
                    "accountId": bank_account.get("id"), "accountCode": bank_account.get("code", ""), "accountName": bank_account.get("name", "Banco"),
                    "debit": round(disposal_amount, 2), "credit": 0.00, "description": f"Venta de {asset.get('name')}"
                })
        entry = AccountingService.generate_entry(owner_uid, {
            "entryType": "disposal",
            "date": disposal_date,
            "concept": f"Baja de activo — {asset.get('name', '')} ({disposal_reason})",
            "referenceType": "disposal",
            "referenceId": asset_id,
            "referenceNumber": asset.get("code", ""),
            "lines": lines,
            "createdBy": "system",
        }, sandbox=sandbox)
        asset["status"] = "disposed"
        asset["disposalDate"] = disposal_date
        asset["disposalAmount"] = disposal_amount
        asset["disposalReason"] = disposal_reason
        asset["currentValue"] = 0
        asset["updatedAt"] = datetime.now(timezone.utc).isoformat()
        DatabaseService.save_fixed_asset(owner_uid, asset_id, asset, sandbox=sandbox)
        return {"entry": entry, "asset": asset}

    @classmethod
    def get_assets_summary(cls, owner_uid, sandbox=True):
        assets = DatabaseService.get_fixed_assets(owner_uid, sandbox=sandbox)
        total_cost = 0.0
        total_dep = 0.0
        total_current = 0.0
        active_count = 0
        disposed_count = 0
        fully_dep_count = 0
        for a in assets:
            total_cost += float(a.get("purchaseAmount", 0))
            total_dep += float(a.get("accumulatedDepreciation", 0))
            total_current += float(a.get("currentValue", 0))
            status = a.get("status", "active")
            if status == "active":
                active_count += 1
            elif status == "disposed":
                disposed_count += 1
            elif status == "fully_depreciated":
                fully_dep_count += 1
        return {
            "totalCost": round(total_cost, 2),
            "totalDepreciation": round(total_dep, 2),
            "totalCurrentValue": round(total_current, 2),
            "activeCount": active_count,
            "disposedCount": disposed_count,
            "fullyDepreciatedCount": fully_dep_count,
            "totalCount": len(assets),
        }

    @classmethod
    def run_auto_depreciation(cls, owner_uid, sandbox=True):
        assets = DatabaseService.get_fixed_assets(owner_uid, sandbox=sandbox)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        results = []
        for asset in assets:
            if asset.get("status") != "active":
                continue
            next_date = asset.get("nextDepreciationDate", "")
            if next_date and next_date <= today:
                try:
                    result = cls.register_depreciation(owner_uid, asset["id"], sandbox=sandbox)
                    results.append({"asset": asset.get("name"), "success": True, "amount": result["amount"]})
                except Exception as e:
                    results.append({"asset": asset.get("name"), "success": False, "error": str(e)})
        return results
