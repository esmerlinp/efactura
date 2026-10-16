"""Servicio Central de Lotes de Inventario para VykOne ERP.

Gestiona el ciclo de vida de los lotes (LotBatch):
- Consulta y filtrado por producto y almacén.
- Validación de integridad, fechas y pertenencia a producto/almacén.
- Resolución determinista y prevención de duplicados (companyId, itemId, warehouseId, lotNumber).
- Aislamiento estricto multi-tenant por empresa y entorno sandbox/producción.
"""

import uuid
import hashlib
from datetime import datetime, timezone, date
from typing import Optional, List, Dict, Any

from app.models.inventory import LotBatch
from app.services.db_service import (
    db_firestore,
    firebase_initialized,
    _company_coll,
    _resolve_owner_uid,
    serialize_field,
)


class LotValidationError(ValueError):
    """Excepción lanzada cuando los datos de un lote no son válidos."""
    pass


class LotService:
    """Servicio de gestión y gobernanza de lotes de inventario."""

    @classmethod
    def _get_coll_name(cls, sandbox: bool = True) -> str:
        return "sandbox_inventory_lots" if sandbox else "inventory_lots"

    @classmethod
    def _get_collection(cls, company_id: str, sandbox: bool = True, owner_uid: Optional[str] = None):
        if not firebase_initialized or db_firestore is None:
            return None
        owner_uid = _resolve_owner_uid(company_id) or owner_uid
        coll_name = cls._get_coll_name(sandbox)
        return _company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=coll_name)

    @classmethod
    def build_canonical_lot_id(cls, item_id: str, warehouse_id: str, lot_number: str) -> str:
        """Genera un identificador canónico seguro para una partida física única.

        Garantiza que la combinación (itemId, warehouseId, lotNumber) resuelva
        al mismo ID de documento en Firestore, evitando duplicaciones accidentales.
        """
        clean_item = (item_id or "").strip()
        clean_wh = (warehouse_id or "").strip()
        clean_num = (lot_number or "").strip().upper()
        h = hashlib.sha256(f"{clean_item}|{clean_wh}|{clean_num}".encode("utf-8")).hexdigest()[:16]
        return f"lot_{clean_item[:8]}_{clean_wh[:8]}_{h}"

    @classmethod
    def validate_lot_data(
        cls,
        item_id: str,
        warehouse_id: str,
        lot_number: str,
        production_date: str = "",
        expiration_date: str = "",
        quantity: float = 0.0,
    ) -> None:
        """Valida las reglas de negocio de un lote antes de persistirlo."""
        if not (item_id or "").strip():
            raise LotValidationError("El ID del producto es obligatorio para el lote.")
        if not (warehouse_id or "").strip():
            raise LotValidationError("El ID del almacén es obligatorio para el lote.")
        if not (lot_number or "").strip():
            raise LotValidationError("El código o número de lote es obligatorio.")

        # Validar consistencia de fechas si ambas están provistas
        p_date = (production_date or "").strip()
        e_date = (expiration_date or "").strip()

        p_obj = None
        e_obj = None

        if p_date:
            try:
                p_obj = date.fromisoformat(p_date[:10])
            except (ValueError, TypeError):
                raise LotValidationError(f"Fecha de fabricación inválida: '{p_date}'. Debe ser formato YYYY-MM-DD.")

        if e_date:
            try:
                e_obj = date.fromisoformat(e_date[:10])
            except (ValueError, TypeError):
                raise LotValidationError(f"Fecha de vencimiento inválida: '{e_date}'. Debe ser formato YYYY-MM-DD.")

        if p_obj and e_obj and e_obj < p_obj:
            raise LotValidationError(
                f"La fecha de vencimiento ({e_date}) no puede ser anterior a la fecha de fabricación ({p_date})."
            )

        if quantity < 0:
            raise LotValidationError("La cantidad del lote no puede ser negativa.")

        return {
            "itemId": (item_id or "").strip(),
            "warehouseId": (warehouse_id or "").strip(),
            "lotNumber": (lot_number or "").strip(),
            "productionDate": p_date,
            "expirationDate": e_date,
            "quantity": float(quantity or 0.0),
        }

    @classmethod
    def get_lots(
        cls,
        company_id: str,
        item_id: Optional[str] = None,
        warehouse_id: Optional[str] = None,
        sandbox: bool = True,
        owner_uid: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Recupera los lotes de la empresa, con filtros opcionales por producto y almacén."""
        coll = cls._get_collection(company_id, sandbox=sandbox, owner_uid=owner_uid)
        if coll is None:
            return []

        lots = []
        try:
            docs = coll.get()
            for doc in docs:
                data = doc.to_dict() or {}
                data["id"] = doc.id
                if item_id and data.get("itemId") != item_id:
                    continue
                if warehouse_id and data.get("warehouseId") != warehouse_id:
                    continue
                lots.append(data)

            # Ordenar por fecha de vencimiento ascendente (los que vencen antes primero)
            lots.sort(key=lambda l: str(l.get("expirationDate") or "9999-99-99"))
        except Exception as e:
            print(f"⚠️ Error al obtener lotes de empresa {company_id}: {e}")

        return lots

    @classmethod
    def get_lot(
        cls,
        company_id: str,
        lot_id: str,
        sandbox: bool = True,
        owner_uid: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Recupera un lote específico por su ID."""
        if not lot_id:
            return None
        coll = cls._get_collection(company_id, sandbox=sandbox, owner_uid=owner_uid)
        if coll is None:
            return None
        try:
            doc = coll.document(lot_id).get()
            if doc.exists:
                data = doc.to_dict() or {}
                data["id"] = doc.id
                return data
        except Exception as e:
            print(f"⚠️ Error al obtener lote {lot_id}: {e}")
        return None

    @classmethod
    def find_lot_by_number(
        cls,
        company_id: str,
        item_id: str,
        lot_number: str,
        warehouse_id: Optional[str] = None,
        sandbox: bool = True,
        owner_uid: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Busca si ya existe un lote con el mismo código para el producto y almacén."""
        target_num = (lot_number or "").strip().upper()
        if not target_num or not item_id:
            return None

        lots = cls.get_lots(
            company_id=company_id,
            item_id=item_id,
            warehouse_id=warehouse_id,
            sandbox=sandbox,
            owner_uid=owner_uid,
        )
        for l in lots:
            if (l.get("lotNumber") or "").strip().upper() == target_num:
                return l
        return None
