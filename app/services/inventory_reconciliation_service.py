# app/services/inventory_reconciliation_service.py
"""
Servicio de Reconciliación de Inventario para VykOne ERP.

Gobernanza de Fuente de Verdad:
1. `inventory_stock` por almacén es la fuente de verdad física del inventario.
2. `inventory_transactions` es el registro inmutable histórico de movimientos.
3. `items.totalStock` es una vista materializada que debe reflejar exactamente:
   SUM(inventory_stock.quantity WHERE itemId == item.id)

Este servicio audita y reconcilia cualquier discrepancia entre la fuente física y la
vista materializada, permitiendo detección previa (dry-run) y corrección atómica.
"""

from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from app.services.db_service import DatabaseService, db_firestore, firebase_initialized, _company_coll, _resolve_owner_uid, _invalidate_items


class InventoryReconciliationService:
    """
    Servicio para auditar y reconciliar el stock físico por almacén (`inventory_stock`)
    con la vista materializada `totalStock` en el catálogo de productos (`items`).
    """

    @classmethod
    def audit_company_stock(
        cls,
        company_id: str,
        sandbox: bool = True,
        owner_uid: str = ""
    ) -> Dict[str, Any]:
        """
        Audita el stock de una empresa comparando SUM(inventory_stock) contra items.totalStock.
        NO realiza escrituras ni modificaciones en la base de datos.
        """
        owner_uid = _resolve_owner_uid(company_id) or owner_uid
        items = DatabaseService.get_items(owner_uid, company_id=company_id, sandbox=sandbox)
        stocks = DatabaseService.get_inventory_stock(owner_uid, company_id=company_id, sandbox=sandbox)
        warehouses = DatabaseService.get_warehouses(owner_uid, company_id=company_id, sandbox=sandbox)
        
        wh_name_map = {w.get("id"): w.get("name", "Almacén Principal") for w in warehouses}

        # Agrupar stock físico por itemId
        physical_stock_by_item: Dict[str, float] = {}
        warehouse_breakdown_by_item: Dict[str, List[Dict[str, Any]]] = {}

        for stock in stocks:
            item_id = stock.get("itemId")
            if not item_id:
                continue
            wh_id = stock.get("warehouseId", "")
            qty = float(stock.get("quantity", 0.0))
            
            physical_stock_by_item[item_id] = physical_stock_by_item.get(item_id, 0.0) + qty
            
            if item_id not in warehouse_breakdown_by_item:
                warehouse_breakdown_by_item[item_id] = []
            
            warehouse_breakdown_by_item[item_id].append({
                "warehouseId": wh_id,
                "warehouseName": wh_name_map.get(wh_id, wh_id or "Sin Asignar"),
                "quantity": qty
            })

        discrepancies = []
        clean_items_count = 0

        for item in items:
            # Solo artículos tipo 'Bien' o que manejen inventario
            item_type = item.get("type", "Bien")
            if item_type != "Bien":
                continue

            item_id = item.get("id")
            materialized_total = round(float(item.get("totalStock", 0.0)), 4)
            physical_sum = round(physical_stock_by_item.get(item_id, 0.0), 4)

            # Si hay diferencia numérica mayor a epsilon
            if abs(materialized_total - physical_sum) > 0.0001:
                discrepancies.append({
                    "itemId": item_id,
                    "code": item.get("code", ""),
                    "name": item.get("name", ""),
                    "materializedTotalStock": materialized_total,
                    "physicalSumStock": physical_sum,
                    "discrepancy": round(materialized_total - physical_sum, 4),
                    "warehouses": warehouse_breakdown_by_item.get(item_id, [])
                })
            else:
                clean_items_count += 1

        return {
            "companyId": company_id,
            "sandbox": sandbox,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "CLEAN" if len(discrepancies) == 0 else "DISCREPANCIES_FOUND",
            "totalItemsAudited": len(items),
            "goodsItemsAudited": len(discrepancies) + clean_items_count,
            "cleanItemsCount": clean_items_count,
            "discrepanciesCount": len(discrepancies),
            "discrepancies": discrepancies
        }

    @classmethod
    def reconcile_company_stock(
        cls,
        company_id: str,
        sandbox: bool = True,
        owner_uid: str = "",
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Reconcilia la vista materializada `totalStock` en `items` asignándole exactamente
        el valor de SUM(inventory_stock).
        
        Si dry_run=True, no escribe nada y solo retorna el plan de ajuste.
        """
        audit_result = cls.audit_company_stock(
            company_id=company_id,
            sandbox=sandbox,
            owner_uid=owner_uid
        )

        discrepancies = audit_result["discrepancies"]
        if not discrepancies:
            return {
                **audit_result,
                "applied": False,
                "reconciledCount": 0,
                "message": "Inventario 100% consistente. No se requirieron correcciones."
            }

        if dry_run:
            return {
                **audit_result,
                "applied": False,
                "reconciledCount": 0,
                "message": f"Modo DRY-RUN: Se detectaron {len(discrepancies)} inconsistencias que serían corregidas."
            }

        if not firebase_initialized:
            return {
                **audit_result,
                "applied": False,
                "reconciledCount": 0,
                "error": "Firebase no está inicializado."
            }

        owner_uid = _resolve_owner_uid(company_id) or owner_uid
        coll_items = "sandbox_items" if sandbox else "items"
        items_coll = _company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=coll_items)

        reconciled_items = []
        for disc in discrepancies:
            item_id = disc["itemId"]
            target_stock = disc["physicalSumStock"]
            try:
                items_coll.document(item_id).update({
                    "totalStock": target_stock,
                    "lastReconciliationDate": datetime.now(timezone.utc).isoformat(),
                    "lastReconciliationDiscrepancy": disc["discrepancy"]
                })
                reconciled_items.append({
                    "itemId": item_id,
                    "name": disc["name"],
                    "oldStock": disc["materializedTotalStock"],
                    "newStock": target_stock,
                    "adjustment": round(target_stock - disc["materializedTotalStock"], 4)
                })
            except Exception as e:
                print(f"⚠️ Error al reconciliar item {item_id}: {e}")

        _invalidate_items(owner_uid, company_id=company_id)

        # Registro en auditoría si es posible
        try:
            from app.services.audit_service import AuditService
            AuditService.log_action(
                owner_uid=owner_uid,
                company_id=company_id,
                action="INVENTORY_RECONCILIATION",
                entity="inventory_stock",
                entity_id=company_id,
                details={
                    "reconciledCount": len(reconciled_items),
                    "items": reconciled_items
                },
                sandbox=sandbox
            )
        except Exception:
            pass

        return {
            "companyId": company_id,
            "sandbox": sandbox,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "RECONCILED",
            "applied": True,
            "reconciledCount": len(reconciled_items),
            "reconciledItems": reconciled_items,
            "message": f"Se reconciliaron exitosamente {len(reconciled_items)} artículos."
        }

    @classmethod
    def reconcile_all_companies(
        cls,
        sandbox: bool = True,
        dry_run: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Ejecuta la auditoría/reconciliación en todas las empresas registradas.
        """
        companies = DatabaseService.get_all_companies()
        results = []
        for comp in companies:
            comp_id = comp.get("id")
            if not comp_id:
                continue
            res = cls.reconcile_company_stock(
                company_id=comp_id,
                sandbox=sandbox,
                dry_run=dry_run
            )
            results.append(res)
        return results
