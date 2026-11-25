# app/services/product_import_batch_service.py
"""
ProductImportBatchService — Lote de importación masiva de productos.

Persiste el lote que agrupa una importación de catálogo y (posteriormente)
sus movimientos de inventario inicial. Proporciona:
    - Identificador único de lote (`importBatchId`) para trazabilidad.
    - Máquina de estados controlada: DRAFT → VALIDATED → CONFIRMED (+ FAILED).
    - Resumen de resultados (creados, actualizados, movimientos, unidades, valor).
    - Partición por empresa y entorno (sandbox / producción).

Colecciones:
    companies/{companyId}/sandbox_product_import_batches   (sandbox)
    companies/{companyId}/product_import_batches           (producción)

Reglas:
    - CONFIRMED es estado terminal (un lote confirmado no se reprocesa).
    - Las transiciones inválidas lanzan `ImportBatchStateError`.
    - Un lote confirmado no puede reutilizarse para evitar movimientos duplicados.
"""

import uuid
from datetime import datetime, timezone

from app.services.db_service import (
    db_firestore,
    firebase_initialized,
    _company_coll,
)


class ImportBatchStateError(Exception):
    """Excepción lanzada cuando una transición de estado del lote es inválida."""
    pass


class ProductImportBatchService:
    """Gestión del ciclo de vida de un lote de importación de productos."""

    STATUS_DRAFT = "DRAFT"
    STATUS_VALIDATED = "VALIDATED"
    STATUS_CONFIRMED = "CONFIRMED"
    STATUS_FAILED = "FAILED"

    # Transiciones permitidas. CONFIRMED y FAILED son terminales.
    _TRANSITIONS = {
        STATUS_DRAFT: {STATUS_VALIDATED, STATUS_FAILED},
        STATUS_VALIDATED: {STATUS_CONFIRMED, STATUS_FAILED},
        STATUS_CONFIRMED: set(),
        STATUS_FAILED: set(),
    }

    @classmethod
    def _coll_name(cls, sandbox: bool) -> str:
        return "sandbox_product_import_batches" if sandbox else "product_import_batches"

    @classmethod
    def _coll(cls, company_id: str, sandbox: bool = True):
        return _company_coll(company_id=company_id, coll_name=cls._coll_name(sandbox))

    @classmethod
    def _now(cls) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── Creación ───────────────────────────────────────────────────────────

    @classmethod
    def create_batch(cls, company_id: str, data: dict | None = None,
                     sandbox: bool = True) -> dict:
        """Crea un lote en estado DRAFT. Devuelve el documento persistido."""
        data = data or {}
        batch_id = data.get("id") or str(uuid.uuid4())
        doc = {
            "id": batch_id,
            "companyId": company_id,
            "environment": "sandbox" if sandbox else "production",
            "status": cls.STATUS_DRAFT,
            "filename": data.get("filename", ""),
            "fileHash": data.get("fileHash", ""),
            "createdBy": data.get("createdBy", ""),
            "createdAt": cls._now(),
            "confirmedBy": "",
            "confirmedAt": "",
            "totalRows": 0,
            "validRows": 0,
            "errorRows": 0,
            "warningRows": 0,
            "newProducts": 0,
            "updatedProducts": 0,
            "inventoryMovements": 0,
            "totalUnits": 0.0,
            "totalInventoryValue": 0.0,
        }
        cls._set(company_id, batch_id, doc, sandbox=sandbox)
        return doc

    # ── Lectura ────────────────────────────────────────────────────────────

    @classmethod
    def get_batch(cls, company_id: str, batch_id: str, sandbox: bool = True) -> dict | None:
        coll = cls._coll(company_id, sandbox=sandbox)
        if coll is None or not firebase_initialized or db_firestore is None:
            return None
        try:
            snap = coll.document(batch_id).get()
            if snap.exists:
                return {"id": batch_id, **snap.to_dict()}
        except Exception as e:
            print(f"⚠️ [import-batch] Error al leer lote {batch_id}: {e}")
        return None

    @classmethod
    def list_batches(cls, company_id: str, sandbox: bool = True) -> list[dict]:
        coll = cls._coll(company_id, sandbox=sandbox)
        if coll is None or not firebase_initialized or db_firestore is None:
            return []
        batches = []
        try:
            for doc in coll.stream():
                batches.append({"id": doc.id, **doc.to_dict()})
        except Exception as e:
            print(f"⚠️ [import-batch] Error al listar lotes: {e}")
        batches.sort(key=lambda b: str(b.get("createdAt", "")), reverse=True)
        return batches

    # ── Escritura / transiciones ───────────────────────────────────────────

    @classmethod
    def _set(cls, company_id: str, batch_id: str, doc: dict, sandbox: bool = True) -> bool:
        coll = cls._coll(company_id, sandbox=sandbox)
        if coll is None or not firebase_initialized or db_firestore is None:
            return False
        try:
            coll.document(batch_id).set(doc)
            return True
        except Exception as e:
            print(f"⚠️ [import-batch] Error al guardar lote {batch_id}: {e}")
            return False

    @classmethod
    def _update(cls, company_id: str, batch_id: str, updates: dict, sandbox: bool = True) -> bool:
        coll = cls._coll(company_id, sandbox=sandbox)
        if coll is None or not firebase_initialized or db_firestore is None:
            return False
        try:
            coll.document(batch_id).set(updates, merge=True)
            return True
        except Exception as e:
            print(f"⚠️ [import-batch] Error al actualizar lote {batch_id}: {e}")
            return False

    @classmethod
    def transition(cls, company_id: str, batch_id: str, to_status: str,
                   sandbox: bool = True, **fields) -> dict | None:
        """Aplica una transición de estado validando la máquina de estados.

        Devuelve el lote actualizado o None si no existe.
        Lanza `ImportBatchStateError` si la transición no está permitida.
        """
        to_status = (to_status or "").strip().upper()
        current = cls.get_batch(company_id, batch_id, sandbox=sandbox)
        if current is None:
            return None

        from_status = (current.get("status") or cls.STATUS_DRAFT).upper()
        allowed = cls._TRANSITIONS.get(from_status, set())
        if to_status not in allowed:
            raise ImportBatchStateError(
                f"Transición no permitida: {from_status} -> {to_status}."
            )

        updates = {"status": to_status}
        updates.update(fields)
        if to_status == cls.STATUS_CONFIRMED:
            updates["confirmedAt"] = cls._now()
            updates.setdefault("confirmedBy", current.get("confirmedBy", ""))
        cls._update(company_id, batch_id, updates, sandbox=sandbox)

        updated = dict(current)
        updated.update(updates)
        return updated

    @classmethod
    def record_summary(cls, company_id: str, batch_id: str, summary: dict,
                       sandbox: bool = True) -> dict | None:
        """Actualiza el resumen de resultados del lote (conteos y valores)."""
        current = cls.get_batch(company_id, batch_id, sandbox=sandbox)
        if current is None:
            return None

        def _int(key, default=0):
            try:
                return int(summary.get(key, current.get(key, default)) or 0)
            except (TypeError, ValueError):
                return int(current.get(key, default) or 0)

        def _float(key, default=0.0):
            try:
                return float(summary.get(key, current.get(key, default)) or 0)
            except (TypeError, ValueError):
                return float(current.get(key, default) or 0)

        updates = {
            "totalRows": _int("totalRows"),
            "validRows": _int("validRows"),
            "errorRows": _int("errorRows"),
            "warningRows": _int("warningRows"),
            "newProducts": _int("newProducts"),
            "updatedProducts": _int("updatedProducts"),
            "inventoryMovements": _int("inventoryMovements"),
            "totalUnits": _float("totalUnits"),
            "totalInventoryValue": _float("totalInventoryValue"),
        }
        cls._update(company_id, batch_id, updates, sandbox=sandbox)

        updated = dict(current)
        updated.update(updates)
        return updated

    # ── Conveniencia ───────────────────────────────────────────────────────

    @classmethod
    def mark_validated(cls, company_id: str, batch_id: str, summary: dict | None = None,
                       sandbox: bool = True) -> dict | None:
        cls.transition(company_id, batch_id, cls.STATUS_VALIDATED, sandbox=sandbox)
        if summary:
            return cls.record_summary(company_id, batch_id, summary, sandbox=sandbox)
        return cls.get_batch(company_id, batch_id, sandbox=sandbox)

    @classmethod
    def mark_confirmed(cls, company_id: str, batch_id: str, confirmed_by: str = "",
                       sandbox: bool = True) -> dict | None:
        fields = {"confirmedBy": confirmed_by} if confirmed_by else {}
        return cls.transition(company_id, batch_id, cls.STATUS_CONFIRMED,
                              sandbox=sandbox, **fields)

    @classmethod
    def mark_failed(cls, company_id: str, batch_id: str, reason: str = "",
                    sandbox: bool = True) -> dict | None:
        fields = {"failureReason": reason} if reason else {}
        return cls.transition(company_id, batch_id, cls.STATUS_FAILED,
                              sandbox=sandbox, **fields)
