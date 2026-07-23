"""Servicio de transferencias entre almacenes con flujo de aprobación."""

import uuid
from datetime import datetime, timezone


class WarehouseTransferService:
    """Gestiona transferencias de stock entre almacenes."""

    @classmethod
    def _get_coll(cls, company_id, sandbox=True):
        from app.services.db_service import _company_coll, firebase_initialized
        if not firebase_initialized:
            return None
        coll_name = "sandbox_warehouse_transfers" if sandbox else "warehouse_transfers"
        return _company_coll(company_id=company_id, coll_name=coll_name)

    @classmethod
    def get_transfers(cls, company_id, sandbox=True):
        """Lista todas las transferencias."""
        transfers = []
        coll = cls._get_coll(company_id, sandbox)
        if not coll:
            return transfers
        try:
            docs = coll.get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                transfers.append(data)
            transfers.sort(key=lambda t: t.get("requestedDate", ""), reverse=True)
        except Exception as e:
            print(f"⚠️ Error al obtener transferencias: {e}")
        return transfers

    @classmethod
    def get_transfer(cls, company_id, transfer_id, sandbox=True):
        coll = cls._get_coll(company_id, sandbox)
        if not coll:
            return None
        try:
            doc = coll.document(transfer_id).get()
            if doc.exists:
                data = doc.to_dict()
                data["id"] = doc.id
                return data
        except Exception as e:
            print(f"⚠️ Error al obtener transferencia: {e}")
        return None

    @classmethod
    def request_transfer(cls, company_id, transfer_dict, sandbox=True):
        """Crea una solicitud de transferencia pendiente."""
        coll = cls._get_coll(company_id, sandbox)
        if not coll:
            return None
        transfer_id = transfer_dict.get("id") or str(uuid.uuid4())
        transfer_dict["id"] = transfer_id
        transfer_dict["status"] = "pendiente"
        transfer_dict["requestedDate"] = datetime.now(timezone.utc).isoformat()
        try:
            coll.document(transfer_id).set(transfer_dict)
            return transfer_id
        except Exception as e:
            print(f"⚠️ Error al crear transferencia: {e}")
            return None

    @classmethod
    def approve_transfer(cls, company_id, transfer_id, approved_by, sandbox=True):
        """Aprueba y ejecuta la transferencia, moviendo stock."""
        from app.services.db_service import DatabaseService

        transfer = cls.get_transfer(company_id, transfer_id, sandbox)
        if not transfer or transfer["status"] != "pendiente":
            return False, "Transferencia no encontrada o no está pendiente."

        transfer["status"] = "en_transito"
        transfer["approvedBy"] = approved_by
        transfer["approvedDate"] = datetime.now(timezone.utc).isoformat()

        for line in transfer.get("lines", []):
            item_id = line["itemId"]
            qty = float(line["quantity"])
            item_name = line.get("itemName", "")

            DatabaseService.register_inventory_transaction(company_id, {
                "type": "SALIDA",
                "itemId": item_id,
                "itemName": item_name,
                "quantity": qty,
                "originWarehouseId": transfer["originWarehouseId"],
                "reason": "TRANSFERENCIA_SALIDA",
                "referenceId": transfer_id,
                "notes": f"Transferencia #{transfer_id[:8]} → {transfer.get('destinationWarehouseName', '')}",
                "performedBy": approved_by,
            }, sandbox=sandbox)

            cost = line.get("unitCost", 0.0)
            DatabaseService.register_inventory_transaction(company_id, {
                "type": "ENTRADA",
                "itemId": item_id,
                "itemName": item_name,
                "quantity": qty,
                "destinationWarehouseId": transfer["destinationWarehouseId"],
                "reason": "TRANSFERENCIA_ENTRADA",
                "referenceId": transfer_id,
                "notes": f"Transferencia #{transfer_id[:8]} ← {transfer.get('originWarehouseName', '')}",
                "performedBy": approved_by,
            }, sandbox=sandbox)

            if cost > 0:
                from app.services.inventory_costing_service import InventoryCostingService
                InventoryCostingService.record_fifo_entry(
                    company_id, item_id, transfer["destinationWarehouseId"],
                    qty, cost, transfer_id, "transfer", sandbox
                )

        transfer["status"] = "completada"
        transfer["completedDate"] = datetime.now(timezone.utc).isoformat()
        cls._update_transfer(company_id, transfer_id, transfer, sandbox)
        return True, "Transferencia completada."

    @classmethod
    def reject_transfer(cls, company_id, transfer_id, reason, sandbox=True):
        """Rechaza una solicitud de transferencia."""
        transfer = cls.get_transfer(company_id, transfer_id, sandbox)
        if not transfer or transfer["status"] != "pendiente":
            return False, "Transferencia no encontrada o no está pendiente."
        transfer["status"] = "rechazada"
        transfer["rejectionReason"] = reason
        cls._update_transfer(company_id, transfer_id, transfer, sandbox)
        return True, "Transferencia rechazada."

    @classmethod
    def _update_transfer(cls, company_id, transfer_id, data, sandbox=True):
        coll = cls._get_coll(company_id, sandbox)
        if coll:
            coll.document(transfer_id).set(data)
