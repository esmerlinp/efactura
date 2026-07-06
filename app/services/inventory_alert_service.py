"""Servicio de alertas de inventario: vencimientos y puntos de reorden."""

from datetime import datetime, timezone, date, timedelta
from collections import defaultdict


class InventoryAlertService:
    """Alertas de vencimiento de lotes y sugerencias de puntos de reorden."""

    @staticmethod
    def get_expiration_alerts(owner_uid, sandbox=True):
        """
        Retorna items/lotes próximos a vencer en 30, 60 y 90 días.
        Agrupado por: {alert_30d: [...], alert_60d: [...], alert_90d: [...]}
        """
        from app.services.db_service import db_firestore, firebase_initialized

        alerts = {"alert_30d": [], "alert_60d": [], "alert_90d": []}
        if not firebase_initialized:
            return alerts

        today = date.today()
        coll_name = "sandbox_inventory_lots" if sandbox else "inventory_lots"
        try:
            docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
            for doc in docs:
                data = doc.to_dict()
                exp_str = data.get("expirationDate", "")
                qty = float(data.get("quantity", 0))
                if not exp_str or qty <= 0:
                    continue
                try:
                    exp_date = date.fromisoformat(exp_str)
                except (ValueError, TypeError):
                    continue

                days_left = (exp_date - today).days
                entry = {
                    "id": doc.id,
                    "itemId": data.get("itemId", ""),
                    "itemName": data.get("itemName", ""),
                    "lotNumber": data.get("lotNumber", ""),
                    "warehouseId": data.get("warehouseId", ""),
                    "quantity": qty,
                    "expirationDate": exp_str,
                    "daysLeft": days_left,
                }

                if 0 <= days_left <= 30:
                    alerts["alert_30d"].append(entry)
                elif 31 <= days_left <= 60:
                    alerts["alert_60d"].append(entry)
                elif 61 <= days_left <= 90:
                    alerts["alert_90d"].append(entry)
        except Exception as e:
            print(f"⚠️ Error al obtener alertas de vencimiento: {e}")

        return alerts

    @staticmethod
    def get_reorder_suggestions(owner_uid, sandbox=True):
        """
        Sugiere órdenes de compra basadas en consumo mensual promedio.
        Retorna lista de {itemId, itemName, currentStock, minStock, maxStock,
                          monthlyConsumption, suggestedOrder, monthsOfStock}
        """
        from app.services.db_service import DatabaseService

        items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
        stocks = DatabaseService.get_inventory_stock(owner_uid, sandbox=sandbox)
        txs = DatabaseService.get_inventory_transactions(owner_uid, sandbox=sandbox)

        # Calcular consumo mensual por item (últimos 3 meses)
        today = date.today()
        three_months_ago = today - timedelta(days=90)
        monthly_usage = defaultdict(float)

        for tx in txs:
            if tx["type"] != "SALIDA":
                continue
            tx_date_str = tx.get("date", "")
            if not tx_date_str:
                continue
            try:
                tx_date = date.fromisoformat(tx_date_str[:10])
            except (ValueError, TypeError):
                continue
            if tx_date >= three_months_ago:
                monthly_usage[tx["itemId"]] += float(tx["quantity"])

        # Calcular promedio mensual
        for item_id in monthly_usage:
            monthly_usage[item_id] = round(monthly_usage[item_id] / 3.0, 2)

        suggestions = []
        for item in items:
            if item.get("type", "Bien") != "Bien":
                continue
            item_id = item["id"]
            current_stock = float(item.get("totalStock", 0))
            min_stock = float(item.get("minStock", 0))
            max_stock = float(item.get("maxStock", 0))
            consumption = monthly_usage.get(item_id, 0.0)

            if consumption <= 0 and current_stock > min_stock:
                continue

            months_of_stock = round(current_stock / consumption, 1) if consumption > 0 else float("inf")

            # Sugerir orden si: stock < minStock, o si quedan menos de 2 meses
            suggested = 0.0
            if current_stock <= min_stock and max_stock > 0:
                suggested = round(max_stock - current_stock, 2)
            elif months_of_stock < 2 and consumption > 0:
                suggested = round((2 * consumption) - current_stock, 2)

            if suggested > 0 or current_stock <= min_stock:
                suggestions.append({
                    "itemId": item_id,
                    "itemName": item.get("name", ""),
                    "currentStock": current_stock,
                    "minStock": min_stock,
                    "maxStock": max_stock,
                    "monthlyConsumption": consumption,
                    "suggestedOrder": max(suggested, 0),
                    "monthsOfStock": months_of_stock,
                    "severity": "critico" if current_stock <= 0 else
                                "alto" if current_stock <= min_stock else
                                "medio" if months_of_stock < 1 else "bajo",
                })

        suggestions.sort(key=lambda s: (
            0 if s["severity"] == "critico" else
            1 if s["severity"] == "alto" else
            2 if s["severity"] == "medio" else 3
        ))
        return suggestions
