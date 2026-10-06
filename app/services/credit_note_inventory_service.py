# app/services/credit_note_inventory_service.py
"""
Servicio para la Gestión de Reingresos de Inventario en Notas de Crédito (E34).
Fase 5A de la Remediación del Módulo de Inventario de VykOne ERP.

Reglas de Negocio y Garantías:
1. `reingresoStock: true/false` por línea de la E34.
2. Almacén destino de la devolución (`warehouseId`).
3. `ENTRADA / DEVOLUCION_CLIENTE` ÚNICAMENTE cuando exista devolución física
   (`reingresoStock == True` y `type == "Bien"`).
4. Si es corrección de precio, descuento o servicio -> SIN movimiento de inventario.
5. Recuperar el costo original de la mercancía vendida (`originalCost`), evitando
   asumir el `costPrice` actual del producto.
6. Idempotencia independiente de la factura original:
   `{companyId}|CREDIT_NOTE|{creditNoteId}_{itemId}|ENTRADA`.
7. Trazabilidad completa por línea:
   - invoiceId original
   - lineId original
   - reingresoStock
   - warehouseId
   - quantityReturned
   - originalCost
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from app.services.db_service import (
    DatabaseService,
    db_firestore,
    firebase_initialized,
    _company_coll,
)
from app.services.inventory_transaction_service import (
    InventoryTransactionService,
    InventoryTransactionError,
)


class CreditNoteInventoryService:
    """Servicio para procesar movimientos de inventario asociados a Notas de Crédito E34."""

    @classmethod
    def is_credit_note_e34(cls, doc_dict: Dict[str, Any]) -> bool:
        """Determina si el comprobante corresponde a una Nota de Crédito (E34 / 34)."""
        if not doc_dict:
            return False
        ecf_type = str(doc_dict.get("ecfType", "")).upper()
        inv_number = str(doc_dict.get("invoiceNumber", "")).upper()
        encf = str(doc_dict.get("encf", "")).upper()
        return (
            "E34" in ecf_type
            or "NOTA DE CRÉDITO" in ecf_type
            or "NOTA DE CREDITO" in ecf_type
            or ecf_type == "34"
            or encf.startswith("E34")
            or inv_number.startswith("NC-")
            or inv_number.startswith("NC")
            or inv_number.startswith("E34")
        )

    @classmethod
    def resolve_original_cost(
        cls,
        owner_uid: str,
        company_id: str,
        ref_invoice: Optional[Dict[str, Any]],
        item: Dict[str, Any],
        sandbox: bool = True,
    ) -> float:
        """
        Recupera el costo unitario original de venta de una línea devuelta.
        
        Prioridades:
        1. `item.originalCost` / `item.unitCost` si viene explícito y > 0.
        2. Línea correspondiente en la factura original (`ref_invoice.items`).
        3. Transacción previa de salida por venta (`inventory_transactions` con referenceType INVOICE).
        4. Costo de catálogo del item en el momento actual (fallback).
        """
        # 1. Explícito en el item
        explicit_cost = float(item.get("originalCost") or item.get("unitCost") or 0.0)
        if explicit_cost > 0:
            return round(explicit_cost, 4)

        item_id = item.get("id") or item.get("itemId", "")
        item_code = (item.get("code") or "").strip().lower()
        item_name = (item.get("name") or "").strip().lower()
        orig_line_id = item.get("originalLineId", "")

        # 2. Factura original
        if ref_invoice and ref_invoice.get("items"):
            for orig_it in ref_invoice.get("items", []):
                match_id = orig_line_id and (orig_it.get("id") == orig_line_id)
                match_same_id = item_id and (orig_it.get("id") == item_id or orig_it.get("itemId") == item_id)
                match_code = item_code and ((orig_it.get("code") or "").strip().lower() == item_code)
                match_name = item_name and ((orig_it.get("name") or "").strip().lower() == item_name)

                if match_id or match_same_id or match_code or match_name:
                    orig_cost = float(
                        orig_it.get("originalCost")
                        or orig_it.get("unitCost")
                        or orig_it.get("costPrice")
                        or 0.0
                    )
                    if orig_cost > 0:
                        return round(orig_cost, 4)

        # 3. Transacción histórica en inventory_transactions
        if firebase_initialized and db_firestore and ref_invoice:
            try:
                from google.cloud import firestore
                coll_name = "sandbox_inventory_transactions" if sandbox else "inventory_transactions"
                ref_num = ref_invoice.get("invoiceNumber")
                ref_id = ref_invoice.get("id")
                
                query_ref = _company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=coll_name)\
                    .where(filter=firestore.FieldFilter("referenceType", "==", "INVOICE"))
                
                docs = query_ref.stream()
                for d in docs:
                    t_data = d.to_dict()
                    t_ref = t_data.get("referenceId")
                    if t_ref in (ref_num, ref_id) and t_data.get("itemId") == item_id:
                        t_cost = float(t_data.get("unitCost", 0.0))
                        if t_cost > 0:
                            return round(t_cost, 4)
            except Exception:
                pass

        # 4. Fallback: Catálogo de artículos
        try:
            items_catalog = DatabaseService.get_items(owner_uid, sandbox=sandbox, company_id=company_id) or []
            for cat_it in items_catalog:
                if (item_id and cat_it.get("id") == item_id) or (item_code and (cat_it.get("code") or "").strip().lower() == item_code):
                    cat_cost = float(cat_it.get("costPrice", 0.0) or 0.0)
                    if cat_cost > 0:
                        return round(cat_cost, 4)
        except Exception:
            pass

        return 0.0

    @classmethod
    def get_reference_invoice(
        cls,
        owner_uid: str,
        company_id: str,
        credit_note_dict: Dict[str, Any],
        sandbox: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Busca y retorna la factura original de referencia."""
        ref_id = credit_note_dict.get("referenceInvoiceId")
        if ref_id:
            inv = DatabaseService.get_invoice(owner_uid, ref_id, sandbox=sandbox, company_id=company_id)
            if inv:
                return inv

        # Intentar por NCF modificado
        info_ref = credit_note_dict.get("informationReference", {}) or {}
        ncf_modified = info_ref.get("ncfModified", "").strip()
        if ncf_modified:
            all_invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, company_id=company_id) or []
            for inv in all_invoices:
                if (
                    inv.get("encf") == ncf_modified
                    or inv.get("ncf") == ncf_modified
                    or inv.get("invoiceNumber") == ncf_modified
                    or inv.get("id") == ncf_modified
                ):
                    return inv

        return None

    @classmethod
    def process_credit_note_stock_reentry(
        cls,
        owner_uid: str,
        company_id: str,
        credit_note_dict: Dict[str, Any],
        sandbox: bool = True,
        default_warehouse_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Procesa el reingreso físico de inventario para una Nota de Crédito (E34).
        
        Asegura:
        - Solo procesa items con `reingresoStock == True` y `type == "Bien"`.
        - Si es corrección de precio/descuento/servicio -> NO genera movimientos.
        - Asigna almacén destino.
        - Recupera costo original de venta (`originalCost`).
        - Idempotencia por línea: `{companyId}|CREDIT_NOTE|{creditNoteId}_{itemId}|ENTRADA`.
        - Trazabilidad y metadatos completos.
        """
        if not cls.is_credit_note_e34(credit_note_dict):
            return []

        if credit_note_dict.get("stockReentered"):
            return []

        status = credit_note_dict.get("status", "Borrador")
        if status in ("Borrador", "Anulada"):
            return []

        credit_note_id = credit_note_dict.get("id", "")
        ref_invoice = cls.get_reference_invoice(owner_uid, company_id, credit_note_dict, sandbox=sandbox)
        ref_invoice_id = ref_invoice.get("id", "") if ref_invoice else credit_note_dict.get("referenceInvoiceId", "")

        # Determinar almacén por defecto
        wh_id = credit_note_dict.get("warehouseId")
        if not wh_id and ref_invoice:
            wh_id = ref_invoice.get("warehouseId")
        if not wh_id and default_warehouse_id:
            wh_id = default_warehouse_id
        if not wh_id:
            whs = DatabaseService.get_warehouses(owner_uid, sandbox=sandbox, company_id=company_id) or []
            wh_id = whs[0]["id"] if whs else "default-almacen-principal"
            credit_note_dict["warehouseId"] = wh_id

        # Catálogo para validar existencia de artículos
        items_catalog = DatabaseService.get_items(owner_uid, sandbox=sandbox, company_id=company_id) or []
        catalog_map = {cit["id"]: cit for cit in items_catalog}

        executed_transactions = []
        any_reentered = False

        for it in credit_note_dict.get("items", []):
            item_type = it.get("type", "Bien")
            is_bien = (item_type == "Bien")
            reingreso = bool(it.get("reingresoStock", False)) and is_bien
            item_id = it.get("id") or it.get("itemId", "")
            qty_returned = float(it.get("quantityReturned", it.get("quantity", 0.0)))

            if not reingreso or qty_returned <= 0 or not item_id or item_id not in catalog_map:
                # Línea sin reingreso físico (servicio, descuento, corrección o item no catalogado)
                it["reingresoStock"] = False
                it["quantityReturned"] = 0.0
                continue

            # Destino específico de la línea o del documento
            dest_wh = it.get("warehouseId") or wh_id

            # Recuperar costo original
            orig_cost = cls.resolve_original_cost(owner_uid, company_id, ref_invoice, it, sandbox=sandbox)
            if orig_cost <= 0:
                orig_cost = float(catalog_map[item_id].get("costPrice", 0.0) or 0.0)

            # Actualizar campos de trazabilidad en la línea
            it["reingresoStock"] = True
            it["originalInvoiceId"] = ref_invoice_id
            it["originalLineId"] = it.get("originalLineId", "")
            it["warehouseId"] = dest_wh
            it["quantityReturned"] = qty_returned
            it["originalCost"] = orig_cost
            it["unitCost"] = orig_cost

            # Clave de idempotencia única por comprobante y línea
            idempotency_key = InventoryTransactionService.build_idempotency_key(
                company_id=company_id,
                reference_type="CREDIT_NOTE",
                reference_id=f"{credit_note_id}_{item_id}",
                operation=InventoryTransactionService.TYPE_ENTRADA
            )

            tx_dict = {
                "itemId": item_id,
                "itemName": it.get("name") or catalog_map[item_id].get("name", "Artículo"),
                "itemCode": it.get("code") or catalog_map[item_id].get("code", ""),
                "type": InventoryTransactionService.TYPE_ENTRADA,
                "quantity": qty_returned,
                "unitCost": orig_cost,
                "reason": InventoryTransactionService.REASON_DEVOLUCION_CLIENTE,
                "referenceType": "CREDIT_NOTE",
                "referenceId": credit_note_dict.get("invoiceNumber") or credit_note_id,
                "idempotencyKey": idempotency_key,
                "originWarehouseId": "",
                "destinationWarehouseId": dest_wh,
                "notes": f"Reingreso por devolución física en Nota de Crédito {credit_note_dict.get('invoiceNumber', credit_note_id)}",
                "performedBy": credit_note_dict.get("createdBy") or "Sistema VykOne",
                "metadata": {
                    "originalInvoiceId": ref_invoice_id,
                    "originalLineId": it.get("originalLineId", ""),
                    "reingresoStock": True,
                    "warehouseId": dest_wh,
                    "quantityReturned": qty_returned,
                    "originalCost": orig_cost,
                }
            }

            res = InventoryTransactionService.execute_transaction(
                owner_uid=owner_uid,
                company_id=company_id,
                tx_dict=tx_dict,
                sandbox=sandbox
            )
            executed_transactions.append(res)
            any_reentered = True

        # ── Post-Commit Contable: Contabilizar Reingreso E34 ──
        from app.services.inventory_accounting_service import InventoryAccountingService
        for tx in executed_transactions:
            try:
                InventoryAccountingService.post_inventory_transaction(
                    company_id=company_id,
                    tx=tx,
                    sandbox=sandbox,
                    owner_uid=owner_uid
                )
            except Exception as acc_e:
                print(f"⚠️ Error al contabilizar reingreso de E34: {acc_e}")

        if any_reentered:
            credit_note_dict["stockReentered"] = True

        return executed_transactions

    @classmethod
    def revert_credit_note_stock_reentry(
        cls,
        owner_uid: str,
        company_id: str,
        credit_note_dict: Dict[str, Any],
        sandbox: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Revierte los reingresos físicos de stock si una Nota de Crédito es Anulada.
        """
        if not cls.is_credit_note_e34(credit_note_dict):
            return []

        if not credit_note_dict.get("stockReentered") or credit_note_dict.get("stockReverted"):
            return []

        credit_note_id = credit_note_dict.get("id", "")
        wh_id = credit_note_dict.get("warehouseId") or "default-almacen-principal"
        items_catalog = DatabaseService.get_items(owner_uid, sandbox=sandbox, company_id=company_id) or []
        catalog_map = {cit["id"]: cit for cit in items_catalog}

        reverted_txs = []
        for it in credit_note_dict.get("items", []):
            if not it.get("reingresoStock") or it.get("type", "Bien") != "Bien":
                continue

            item_id = it.get("id") or it.get("itemId", "")
            if not item_id or item_id not in catalog_map:
                continue

            qty = float(it.get("quantityReturned", it.get("quantity", 0.0)))
            if qty <= 0:
                continue

            dest_wh = it.get("warehouseId") or wh_id
            orig_cost = float(it.get("originalCost") or it.get("unitCost") or 0.0)

            idempotency_key = InventoryTransactionService.build_idempotency_key(
                company_id=company_id,
                reference_type="CREDIT_NOTE_CANCEL",
                reference_id=f"{credit_note_id}_{item_id}",
                operation=InventoryTransactionService.TYPE_SALIDA
            )

            tx_dict = {
                "itemId": item_id,
                "itemName": it.get("name") or catalog_map[item_id].get("name", "Artículo"),
                "itemCode": it.get("code") or catalog_map[item_id].get("code", ""),
                "type": InventoryTransactionService.TYPE_SALIDA,
                "quantity": qty,
                "unitCost": orig_cost,
                "reason": InventoryTransactionService.REASON_AJUSTE_MANUAL,
                "referenceType": "CREDIT_NOTE_CANCEL",
                "referenceId": credit_note_dict.get("invoiceNumber") or credit_note_id,
                "idempotencyKey": idempotency_key,
                "originWarehouseId": dest_wh,
                "destinationWarehouseId": "",
                "notes": f"Reversión de reingreso por Anulación de Nota de Crédito {credit_note_dict.get('invoiceNumber', credit_note_id)}",
                "performedBy": credit_note_dict.get("createdBy") or "Sistema VykOne (Automático)"
            }

            res = InventoryTransactionService.execute_transaction(
                owner_uid=owner_uid,
                company_id=company_id,
                tx_dict=tx_dict,
                sandbox=sandbox
            )
            reverted_txs.append(res)

        # ── Post-Commit Contable: Contabilizar Reversión de Reingreso E34 ──
        from app.services.inventory_accounting_service import InventoryAccountingService
        for rev_tx in reverted_txs:
            try:
                InventoryAccountingService.post_inventory_transaction(
                    company_id=company_id,
                    tx=rev_tx,
                    sandbox=sandbox,
                    owner_uid=owner_uid
                )
            except Exception as acc_e:
                print(f"⚠️ Error al contabilizar reversión de reingreso E34: {acc_e}")

        credit_note_dict["stockReverted"] = True
        return reverted_txs

