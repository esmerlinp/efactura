# app/services/initial_stock_service.py
"""
InitialStockService — Registro de existencias iniciales por importación.

Genera un movimiento formal de inventario (ENTRADA / SALDO_INICIAL) a través
del motor central `InventoryTransactionService.execute_transaction`. Nunca
modifica directamente `inventory_stock` ni `items.totalStock`.

Idempotencia:
    Clave canónica `{companyId}|PRODUCT_IMPORT|{batchId}:{rowKey}|ENTRADA`.
    Reintentar la misma fila devuelve la transacción existente sin duplicar
    existencias.
"""

from datetime import datetime, timezone

from app.services.inventory_transaction_service import InventoryTransactionService


class InitialStockService:
    """Constructor y ejecutor del movimiento de inventario inicial."""

    REFERENCE_TYPE = "PRODUCT_IMPORT"

    @staticmethod
    def build_idempotency_key(company_id: str, batch_id: str, row_key) -> str:
        reference_id = InitialStockService.build_reference_id(batch_id, row_key)
        return InventoryTransactionService.build_idempotency_key(
            company_id, InitialStockService.REFERENCE_TYPE, reference_id,
            InventoryTransactionService.TYPE_ENTRADA,
        )

    @staticmethod
    def build_reference_id(batch_id: str, row_key) -> str:
        return f"{batch_id}:{row_key}"

    @classmethod
    def build_tx(cls, company_id: str, item_id: str, warehouse_id: str,
                 quantity: float, unit_cost: float, batch_id: str, row_key,
                 performed_by: str = "", effective_date: str = "",
                 lot_number: str = "", expiration_date: str = "") -> dict:
        """Construye el `tx_dict` del movimiento inicial (sin ejecutarlo)."""
        reference_id = cls.build_reference_id(batch_id, row_key)
        tx_dict = {
            "itemId": item_id,
            "type": InventoryTransactionService.TYPE_ENTRADA,
            "quantity": float(quantity),
            "destinationWarehouseId": warehouse_id,
            "unitCost": float(unit_cost),
            "reason": InventoryTransactionService.REASON_SALDO_INICIAL,
            "referenceType": cls.REFERENCE_TYPE,
            "referenceId": reference_id,
            "idempotencyKey": cls.build_idempotency_key(company_id, batch_id, row_key),
            "performedBy": performed_by,
            "date": effective_date or datetime.now(timezone.utc).isoformat(),
            "notes": "Inventario inicial por importación",
        }
        if lot_number:
            tx_dict["lotNumber"] = lot_number
        if expiration_date:
            tx_dict["expirationDate"] = expiration_date
        return tx_dict

    @classmethod
    def register(cls, owner_uid: str, company_id: str, item_id: str,
                 warehouse_id: str, quantity: float, unit_cost: float,
                 batch_id: str, row_key, sandbox: bool = True,
                 performed_by: str = "", effective_date: str = "",
                 lot_number: str = "", expiration_date: str = ""):
        """Ejecuta el movimiento inicial vía el motor central."""
        tx_dict = cls.build_tx(
            company_id, item_id, warehouse_id, quantity, unit_cost,
            batch_id, row_key, performed_by=performed_by,
            effective_date=effective_date, lot_number=lot_number,
            expiration_date=expiration_date,
        )
        return InventoryTransactionService.execute_transaction(
            owner_uid, company_id, tx_dict, sandbox=sandbox,
        )

    @staticmethod
    def resolve_warehouse_id(value, warehouses):
        """Resuelve el ID de almacén desde su id o nombre. Retorna None si no existe."""
        if not value:
            return None
        value = str(value).strip()
        for w in warehouses or []:
            if w.get("id") == value or w.get("name") == value:
                return w.get("id")
        return None
