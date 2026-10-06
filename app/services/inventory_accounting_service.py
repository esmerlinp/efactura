"""
InventoryAccountingService — Motor de Contabilidad Automática de Inventario.

Responsabilidades:
1. Desacoplar el movimiento físico (InventoryTransactionService) de la contabilidad.
2. Contabilizar hechos económicos de inventario usando exclusivamente el valor real
   (inventory_transactions.totalValue y costLayers), nunca recalcular ni usar item.costPrice.
3. Garantizar idempotencia contable bidireccional mediante InventoryPosting.
4. Gestionar ciclo de vida de postings: PENDING -> POSTING -> POSTED / FAILED / REVERSED.
5. Soportar reversiones no destructivas (nuevo asiento de reversión simétrica).
6. Validar períodos fiscales con la fecha económica real del movimiento (entryDate).
"""

import uuid
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

_tx_locks: Dict[str, threading.Lock] = {}
_tx_locks_guard = threading.Lock()


def _get_tx_lock(key: str) -> threading.Lock:
    with _tx_locks_guard:
        if key not in _tx_locks:
            _tx_locks[key] = threading.Lock()
        return _tx_locks[key]


try:
    from app.services.db_service import db_firestore, firebase_initialized, DatabaseService, _company_coll
except ImportError:
    db_firestore = None
    firebase_initialized = False
    DatabaseService = None
    _company_coll = None

from app.services.accounting_rules_service import AccountingRulesService
from app.services.accounting_service import AccountingService
from app.services.fiscal_period_service import FiscalPeriodService


class InventoryAccountingService:
    """Servicio para la generación, auditoría y reversión de asientos contables de inventario."""

    STATUS_PENDING = "PENDING"
    STATUS_POSTING = "POSTING"
    STATUS_POSTED = "POSTED"
    STATUS_FAILED = "FAILED"
    STATUS_REVERSED = "REVERSED"
    STATUS_SKIPPED_NEUTRAL = "SKIPPED_NEUTRAL"

    @classmethod
    def _postings_coll(cls, company_id: str, sandbox: bool = True):
        """Retorna la referencia a la colección de inventory_postings."""
        coll_name = "sandbox_inventory_postings" if sandbox else "inventory_postings"
        if _company_coll is not None:
            return _company_coll(company_id=company_id, coll_name=coll_name)
        if firebase_initialized and db_firestore is not None:
            return db_firestore.collection("companies").document(company_id).collection(coll_name)
        return None

    @classmethod
    def build_idempotency_key(cls, company_id: str, tx_id: str) -> str:
        """Construye la clave de idempotencia contable."""
        return f"{company_id}|INVENTORY|{tx_id}"

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. RESOLUCIÓN DE CUENTAS CONTABLES
    # ═══════════════════════════════════════════════════════════════════════════

    @classmethod
    def resolve_accounts(
        cls,
        company_id: str,
        tx_type: str,
        reason: str,
        origin_wh_id: Optional[str] = None,
        dest_wh_id: Optional[str] = None,
        sandbox: bool = True,
        country: str = "DO"
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], bool, str]:
        """
        Resuelve las cuentas Débito y Crédito para una transacción de inventario.
        
        Retorna:
            (debit_account, credit_account, is_neutral, error_message)
        """
        accounts = DatabaseService.get_chart_of_accounts(company_id, company_id=company_id) if DatabaseService else []
        if not accounts and DatabaseService:
            AccountingService.seed_default_accounts(company_id, country=country)
            accounts = DatabaseService.get_chart_of_accounts(company_id, company_id=company_id)

        rules = AccountingRulesService.get_rules(company_id) if company_id else []

        tx_type_upper = (tx_type or "").upper()
        reason_upper = (reason or "").upper()

        # ── 1.1 VENTA / FACTURACIÓN ──
        if tx_type_upper == "SALIDA" and reason_upper in ("VENTA", "FACTURA", "POS", "EMISION_ECF"):
            cogs_acc = AccountingRulesService.resolve(
                company_id, "venta", "venta_costo_ventas", {}, accounts, rules=rules,
                fallback_usages=["costo_ventas"]
            )
            inv_acc = AccountingRulesService.resolve(
                company_id, "venta", "venta_inventario", {}, accounts, rules=rules,
                fallback_usages=["inventario"]
            )
            if not cogs_acc or not inv_acc:
                return None, None, False, "No se encontraron las cuentas de Costo de Ventas o Inventario."
            return cogs_acc, inv_acc, False, ""

        # ── 1.2 DEVOLUCIÓN FÍSICA CLIENTE (E34 / NOTA DE CRÉDITO) ──
        if tx_type_upper == "ENTRADA" and reason_upper in ("DEVOLUCION_CLIENTE", "CREDIT_NOTE", "E34", "DEVOLUCION"):
            inv_acc = AccountingRulesService.resolve(
                company_id, "inventario", "inventario_cuenta", {}, accounts, rules=rules,
                fallback_usages=["inventario"]
            )
            cogs_acc = AccountingRulesService.resolve(
                company_id, "venta", "venta_costo_ventas", {}, accounts, rules=rules,
                fallback_usages=["costo_ventas"]
            )
            if not inv_acc or not cogs_acc:
                return None, None, False, "No se encontraron las cuentas de Inventario o Costo de Ventas para la devolución."
            return inv_acc, cogs_acc, False, ""

        # ── 1.3 RECEPCIÓN DE COMPRA (GOODS RECEIPT) ──
        if tx_type_upper == "ENTRADA" and reason_upper in ("COMPRA", "RECEPCION", "GOODS_RECEIPT", "ORDEN_COMPRA"):
            inv_acc = AccountingRulesService.resolve(
                company_id, "inventario", "inventario_cuenta", {}, accounts, rules=rules,
                fallback_usages=["inventario"]
            )
            transit_acc = AccountingRulesService.resolve(
                company_id, "gasto", "gasto_mercancia_transito", {}, accounts, rules=rules,
                fallback_usages=["mercancia_transito", "mercancia_recibida_no_facturada", "cxp", "pasivos"]
            )
            if not inv_acc or not transit_acc:
                return None, None, False, "No se encontraron las cuentas de Inventario o Mercancía en Tránsito / Provisión."
            return inv_acc, transit_acc, False, ""

        # ── 1.4 AJUSTE FÍSICO POSITIVO (SOBRANTE / ENTRADA) ──
        if tx_type_upper in ("ENTRADA", "AJUSTE") and reason_upper in ("RECUENTO_FISICO", "AJUSTE_POSITIVO", "AJUSTE", "SOBRANTE"):
            inv_acc = AccountingRulesService.resolve(
                company_id, "inventario", "inventario_cuenta", {}, accounts, rules=rules,
                fallback_usages=["inventario"]
            )
            gain_acc = AccountingRulesService.resolve(
                company_id, "inventario", "inventario_ajuste", {}, accounts, rules=rules,
                fallback_usages=["ajuste_inventario", "ingresos", "costo_ventas"]
            )
            if not inv_acc or not gain_acc:
                return None, None, False, "No se encontraron las cuentas de Inventario o Ajuste de Inventario (Ganancia)."
            return inv_acc, gain_acc, False, ""

        # ── 1.5 AJUSTE FÍSICO NEGATIVO / MERMA (SALIDA) ──
        if (tx_type_upper in ("SALIDA", "AJUSTE") and reason_upper in ("RECUENTO_FISICO", "AJUSTE_NEGATIVO", "AJUSTE", "FALTANTE")) or reason_upper == "MERMA":
            merma_acc = AccountingRulesService.resolve(
                company_id, "inventario", "inventario_merma", {}, accounts, rules=rules,
                fallback_usages=["merma_perdida", "costo_ventas", "gastos"]
            )
            inv_acc = AccountingRulesService.resolve(
                company_id, "inventario", "inventario_cuenta", {}, accounts, rules=rules,
                fallback_usages=["inventario"]
            )
            if not merma_acc or not inv_acc:
                return None, None, False, "No se encontraron las cuentas de Merma/Pérdida o Inventario."
            return merma_acc, inv_acc, False, ""

        # ── 1.6 TRANSFERENCIA ENTRE ALMACENES ──
        if tx_type_upper == "TRANSFERENCIA" or reason_upper == "TRANSFERENCIA":
            # Si ambos almacenes usan la misma cuenta contable (o no hay cuentas por almacén), es neutral
            # Preparado para admitir cuentas distintas por almacén si existen en el modelo de almacenes
            orig_acc = None
            dest_acc = None
            if origin_wh_id and dest_wh_id and DatabaseService:
                try:
                    warehouses = DatabaseService.get_warehouses(company_id, company_id=company_id, sandbox=sandbox)
                    wh_orig = next((w for w in warehouses if w.get("id") == origin_wh_id), None)
                    wh_dest = next((w for w in warehouses if w.get("id") == dest_wh_id), None)
                    if wh_orig and wh_orig.get("accountingAccountId"):
                        orig_acc = next((a for a in accounts if a.get("id") == wh_orig["accountingAccountId"]), None)
                    if wh_dest and wh_dest.get("accountingAccountId"):
                        dest_acc = next((a for a in accounts if a.get("id") == wh_dest["accountingAccountId"]), None)
                except Exception:
                    pass

            if orig_acc and dest_acc and orig_acc.get("id") != dest_acc.get("id"):
                return dest_acc, orig_acc, False, ""
            
            # Mismo almacén / misma cuenta contable general -> Neutral (sin asiento financiero)
            return None, None, True, ""

        return None, None, False, f"Tipo de movimiento de inventario no soportado para contabilización: {tx_type}/{reason}"

    # ═══════════════════════════════════════════════════════════════════════════
    # 2. CONTABILIZACIÓN DE TRANSACCIÓN DE INVENTARIO (POST-COMMIT)
    # ═══════════════════════════════════════════════════════════════════════════

    @classmethod
    def post_inventory_transaction(
        cls,
        company_id: str,
        tx: Dict[str, Any],
        sandbox: bool = True,
        owner_uid: str = ""
    ) -> Dict[str, Any]:
        """
        Genera el asiento contable para una transacción de inventario ejecutada y persistida.
        
        Garantías:
        1. Idempotencia absoluta por txId.
        2. No recalcula costos: usa tx['totalValue'].
        3. Falla controlada sin afectar el inventario físico.
        4. No modifica asientos existentes; crea un InventoryPosting de trazabilidad.
        """
        if not company_id or not tx:
            return {"success": False, "status": cls.STATUS_FAILED, "error": "company_id y tx requeridos"}

        tx_id = tx.get("id") or tx.get("transactionId") or ""
        if not tx_id:
            return {"success": False, "status": cls.STATUS_FAILED, "error": "tx.id es obligatorio"}

        idempotency_key = cls.build_idempotency_key(company_id, tx_id)
        postings_ref = cls._postings_coll(company_id, sandbox=sandbox)

        with _get_tx_lock(idempotency_key):
            # ── 2.1 Verificar si ya existe un posting previo (Anti-Duplicidad) ──
            existing_posting = cls.get_inventory_posting_by_tx(company_id, tx_id, sandbox=sandbox)
            if existing_posting:
                status = existing_posting.get("status")
                if status == cls.STATUS_POSTED:
                    return {
                        "success": True,
                        "status": cls.STATUS_POSTED,
                        "posting": existing_posting,
                        "journalEntryId": existing_posting.get("journalEntryId"),
                        "journalEntryNumber": existing_posting.get("journalEntryNumber"),
                        "idempotent": True
                    }
                elif status == cls.STATUS_SKIPPED_NEUTRAL:
                    return {
                        "success": True,
                        "status": cls.STATUS_SKIPPED_NEUTRAL,
                        "posting": existing_posting,
                        "idempotent": True
                    }

            # ── 2.2 Extraer datos de la transacción ──
            tx_type = tx.get("type", "")
            reason = tx.get("reason", "")
            total_value = round(float(tx.get("totalValue", 0.0)), 2)
            cost_layers = tx.get("costLayers", [])
            reference_type = tx.get("referenceType", "inventory")
            reference_id = tx.get("referenceId", tx_id)
            reference_number = tx.get("documentNumber") or tx.get("referenceNumber") or reference_id
            
            tx_date_raw = tx.get("date") or tx.get("createdAt") or datetime.now(timezone.utc).isoformat()
            entry_date = str(tx_date_raw)[:10]  # YYYY-MM-DD
            
            origin_wh_id = tx.get("originWarehouseId")
            dest_wh_id = tx.get("destinationWarehouseId")
            item_name = tx.get("itemName", "Artículo")
            quantity = float(tx.get("quantity", 0))
            performed_by = tx.get("performedBy", "system")

            posting_id = (existing_posting.get("id") if existing_posting else None) or str(uuid.uuid4())
            now_iso = datetime.now(timezone.utc).isoformat()

            posting_doc = {
                "id": posting_id,
                "idempotencyKey": idempotency_key,
                "companyId": company_id,
                "inventoryTransactionId": tx_id,
                "inventoryTransactionType": tx_type,
                "reason": reason,
                "entryDate": entry_date,
                "inventoryTransactionDate": tx_date_raw,
                "referenceType": reference_type,
                "referenceId": reference_id,
                "referenceNumber": reference_number,
                "amount": total_value,
                "costLayers": cost_layers,
                "status": cls.STATUS_POSTING,
                "retryCount": (existing_posting.get("retryCount", 0) + 1 if existing_posting else 0),
                "createdAt": existing_posting.get("createdAt") if existing_posting else now_iso,
                "updatedAt": now_iso,
                "postedBy": performed_by,
            }

            # ── 2.3 Resolver cuentas contables ──
            debit_acc, credit_acc, is_neutral, error_msg = cls.resolve_accounts(
                company_id=company_id,
                tx_type=tx_type,
                reason=reason,
                origin_wh_id=origin_wh_id,
                dest_wh_id=dest_wh_id,
                sandbox=sandbox
            )

            # ── 2.4 Movimiento Neutral o Sin Importe Financiero ──
            if is_neutral or total_value <= 0.0:
                posting_doc["status"] = cls.STATUS_SKIPPED_NEUTRAL
                posting_doc["notes"] = "Movimiento neutro sin impacto contable en resultados." if is_neutral else "Movimiento con valor RD$ 0.00."
                cls._save_posting(company_id, posting_id, posting_doc, sandbox=sandbox)
                return {"success": True, "status": cls.STATUS_SKIPPED_NEUTRAL, "posting": posting_doc}

            if error_msg or not debit_acc or not credit_acc:
                posting_doc["status"] = cls.STATUS_FAILED
                posting_doc["errorDetails"] = error_msg or "Cuentas contables no disponibles."
                cls._save_posting(company_id, posting_id, posting_doc, sandbox=sandbox)
                return {"success": False, "status": cls.STATUS_FAILED, "error": posting_doc["errorDetails"], "posting": posting_doc}

            # ── 2.5 Validar Período Fiscal con entryDate (Fecha Económica) ──
            try:
                FiscalPeriodService.validate_period_open(owner_uid or company_id, entry_date, company_id=company_id)
            except Exception as p_err:
                posting_doc["status"] = cls.STATUS_FAILED
                posting_doc["errorDetails"] = str(p_err)
                cls._save_posting(company_id, posting_id, posting_doc, sandbox=sandbox)
                return {"success": False, "status": cls.STATUS_FAILED, "error": str(p_err), "posting": posting_doc}

            # ── 2.6 Formular Líneas del Asiento Contable ──
            concept_desc = cls._build_concept_description(tx_type, reason, reference_number, item_name, quantity)

            lines = [
                {
                    "accountId": debit_acc["id"],
                    "accountCode": debit_acc.get("code", ""),
                    "accountName": debit_acc.get("name", ""),
                    "debit": total_value,
                    "credit": 0.00,
                    "description": f"{concept_desc} (Débito)",
                    "currency": "DOP",
                    "branchId": tx.get("branchId", ""),
                    "costCenterId": tx.get("costCenterId", ""),
                },
                {
                    "accountId": credit_acc["id"],
                    "accountCode": credit_acc.get("code", ""),
                    "accountName": credit_acc.get("name", ""),
                    "debit": 0.00,
                    "credit": total_value,
                    "description": f"{concept_desc} (Crédito)",
                    "currency": "DOP",
                    "branchId": tx.get("branchId", ""),
                    "costCenterId": tx.get("costCenterId", ""),
                }
            ]

            entry_payload = {
                "entryType": "inventory",
                "date": entry_date,
                "concept": concept_desc,
                "referenceType": "inventory",
                "referenceId": tx_id,
                "referenceNumber": reference_number,
                "lines": lines,
                "createdBy": performed_by,
                "prefix": "A",
            }

            # ── 2.7 Generar Asiento Contable ──
            try:
                journal_entry = AccountingService.generate_entry(company_id, entry_payload, sandbox=sandbox)
                posting_doc["journalEntryId"] = journal_entry.get("id")
                posting_doc["journalEntryNumber"] = journal_entry.get("number")
                posting_doc["status"] = cls.STATUS_POSTED
                posting_doc["postedAt"] = datetime.now(timezone.utc).isoformat()
                posting_doc["errorDetails"] = None
                cls._save_posting(company_id, posting_id, posting_doc, sandbox=sandbox)

                return {
                    "success": True,
                    "status": cls.STATUS_POSTED,
                    "posting": posting_doc,
                    "journalEntry": journal_entry,
                    "journalEntryId": journal_entry.get("id"),
                    "journalEntryNumber": journal_entry.get("number"),
                }
            except Exception as e:
                posting_doc["status"] = cls.STATUS_FAILED
                posting_doc["errorDetails"] = f"Error al generar asiento contable: {str(e)}"
                cls._save_posting(company_id, posting_id, posting_doc, sandbox=sandbox)
                return {
                    "success": False,
                    "status": cls.STATUS_FAILED,
                    "error": posting_doc["errorDetails"],
                    "posting": posting_doc
                }

    # ═══════════════════════════════════════════════════════════════════════════
    # 3. REVERSIÓN NO DESTRUCTIVA (NUEVO ASIENTO INVERSO)
    # ═══════════════════════════════════════════════════════════════════════════

    @classmethod
    def reverse_posting(
        cls,
        company_id: str,
        posting_id_or_tx_id: str,
        reversal_tx: Optional[Dict[str, Any]] = None,
        reason: str = "Anulación de movimiento",
        user_id: str = "system",
        sandbox: bool = True,
        owner_uid: str = ""
    ) -> Dict[str, Any]:
        """
        Revierte una contabilización de inventario creando un NUEVO asiento simétrico inverso.
        Nunca modifica ni elimina el asiento original POSTED.
        """
        # Buscar el posting
        posting = cls.get_inventory_posting_by_tx(company_id, posting_id_or_tx_id, sandbox=sandbox)
        if not posting:
            # Intentar por posting_id directo
            postings_coll = cls._postings_coll(company_id, sandbox=sandbox)
            if postings_coll is not None:
                doc = postings_coll.document(posting_id_or_tx_id).get()
                if doc.exists:
                    posting = doc.to_dict()


        if not posting:
            return {"success": False, "error": f"Posting {posting_id_or_tx_id} no encontrado"}

        if posting.get("status") == cls.STATUS_REVERSED:
            return {
                "success": True,
                "status": cls.STATUS_REVERSED,
                "posting": posting,
                "reversalEntryId": posting.get("reversalEntryId"),
                "alreadyReversed": True
            }

        if posting.get("status") != cls.STATUS_POSTED:
            return {
                "success": False,
                "error": f"No se puede revertir un posting en estado {posting.get('status')}"
            }

        journal_entry_id = posting.get("journalEntryId")
        if not journal_entry_id:
            return {"success": False, "error": "El posting no tiene un journalEntryId asociado"}

        # Cargar asiento original
        entries = DatabaseService.get_accounting_entries(company_id, sandbox=sandbox, company_id=company_id) if DatabaseService else []
        orig_entry = next((e for e in entries if e.get("id") == journal_entry_id), None)
        if not orig_entry:
            return {"success": False, "error": f"Asiento original {journal_entry_id} no encontrado"}

        reversal_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if reversal_tx and reversal_tx.get("date"):
            reversal_date = str(reversal_tx["date"])[:10]

        # Validar período abierto para la fecha de reversión
        try:
            FiscalPeriodService.validate_period_open(owner_uid or company_id, reversal_date, company_id=company_id)
        except Exception as p_err:
            return {"success": False, "error": f"No se puede registrar reversión: {p_err}"}

        # Formular líneas inversas (intercambiar débito y crédito)
        reversed_lines = []
        for line in orig_entry.get("lines", []):
            orig_debit = float(line.get("debit", 0.0))
            orig_credit = float(line.get("credit", 0.0))
            reversed_lines.append({
                "accountId": line.get("accountId"),
                "accountCode": line.get("accountCode"),
                "accountName": line.get("accountName"),
                "debit": orig_credit,
                "credit": orig_debit,
                "description": f"[REVERSO] {line.get('description', '')}",
                "currency": line.get("currency", "DOP"),
                "branchId": line.get("branchId"),
                "costCenterId": line.get("costCenterId"),
            })

        reversal_ref_id = (reversal_tx.get("id") or reversal_tx.get("transactionId") or str(uuid.uuid4())) if reversal_tx else str(uuid.uuid4())
        reversal_payload = {
            "entryType": "inventory_reversal",
            "date": reversal_date,
            "concept": f"Reverso contable inventario: {reason} (Ref: {orig_entry.get('number', '')})",
            "referenceType": "inventory_reversal",
            "referenceId": reversal_ref_id,
            "referenceNumber": f"REV-{orig_entry.get('number', '')}",
            "reversalOfEntryId": orig_entry.get("id"),
            "lines": reversed_lines,
            "createdBy": user_id or "system",
            "prefix": "A",
        }

        try:
            reversal_entry = AccountingService.generate_entry(company_id, reversal_payload, sandbox=sandbox)
            
            # Actualizar el posting original manteniendo el asiento intacto
            now_iso = datetime.now(timezone.utc).isoformat()
            posting["status"] = cls.STATUS_REVERSED
            posting["reversalEntryId"] = reversal_entry.get("id")
            posting["reversalEntryNumber"] = reversal_entry.get("number")
            posting["reversedAt"] = now_iso
            posting["reversedBy"] = user_id
            posting["reversalReason"] = reason
            posting["updatedAt"] = now_iso

            cls._save_posting(company_id, posting["id"], posting, sandbox=sandbox)

            return {
                "success": True,
                "status": cls.STATUS_REVERSED,
                "originalPosting": posting,
                "reversalEntry": reversal_entry,
                "reversalEntryId": reversal_entry.get("id"),
                "reversalEntryNumber": reversal_entry.get("number")
            }
        except Exception as e:
            return {"success": False, "error": f"Error al generar asiento de reversión: {e}"}

    # ═══════════════════════════════════════════════════════════════════════════
    # 4. REINTENTOS Y RECUPERACIÓN DE ERRORES (RETRY)
    # ═══════════════════════════════════════════════════════════════════════════

    @classmethod
    def retry_failed_posting(
        cls,
        company_id: str,
        posting_id: str,
        tx: Optional[Dict[str, Any]] = None,
        sandbox: bool = True,
        owner_uid: str = ""
    ) -> Dict[str, Any]:
        """Reintenta contabilizar un posting en estado FAILED o PENDING."""
        postings_coll = cls._postings_coll(company_id, sandbox=sandbox)
        if not postings_coll:
            return {"success": False, "error": "No se pudo conectar a Firestore"}

        doc = postings_coll.document(posting_id).get()
        if not doc.exists:
            return {"success": False, "error": f"Posting {posting_id} no encontrado"}

        posting_data = doc.to_dict()
        if posting_data.get("status") == cls.STATUS_POSTED:
            return {"success": True, "status": cls.STATUS_POSTED, "posting": posting_data, "alreadyPosted": True}

        if not tx:
            # Buscar la transacción de inventario en Firestore
            tx_id = posting_data.get("inventoryTransactionId")
            tx = cls._fetch_inventory_transaction(company_id, tx_id, sandbox=sandbox)

        if not tx:
            return {"success": False, "error": f"Transacción física no encontrada para reintento"}

        return cls.post_inventory_transaction(company_id, tx, sandbox=sandbox, owner_uid=owner_uid)

    # ═══════════════════════════════════════════════════════════════════════════
    # 5. CONSULTA Y AUDITORÍA DE POSTINGS
    # ═══════════════════════════════════════════════════════════════════════════

    @classmethod
    def get_inventory_postings(
        cls,
        company_id: str,
        sandbox: bool = True,
        status: Optional[str] = None,
        limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Lista los registros de contabilización de inventario para reportes y auditoría."""
        postings = []
        coll = cls._postings_coll(company_id, sandbox=sandbox)
        if not coll:
            return postings

        try:
            query = coll
            if status:
                query = query.where("status", "==", status)
            docs = query.stream()
            for doc in docs:
                d = doc.to_dict()
                d["id"] = doc.id
                postings.append(d)
            postings.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
            if limit:
                postings = postings[:limit]
        except Exception as e:
            print(f"⚠️ Error al obtener inventory_postings: {e}")
        return postings

    @classmethod
    def get_inventory_posting_by_tx(
        cls,
        company_id: str,
        tx_id: str,
        sandbox: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Obtiene el posting correspondiente a un txId específico."""
        idempotency_key = cls.build_idempotency_key(company_id, tx_id)
        coll = cls._postings_coll(company_id, sandbox=sandbox)
        if not coll:
            return None

        try:
            docs = coll.where("idempotencyKey", "==", idempotency_key).limit(1).get()
            for doc in docs:
                d = doc.to_dict()
                d["id"] = doc.id
                return d
            
            # Búsqueda secundaria por inventoryTransactionId directo (aislado por company_id)
            docs = coll.where("inventoryTransactionId", "==", tx_id).get()
            for doc in docs:
                d = doc.to_dict()
                if not d.get("companyId") or d.get("companyId") == company_id:
                    d["id"] = doc.id
                    return d
        except Exception as e:
            print(f"⚠️ Error al buscar inventory_posting por tx {tx_id}: {e}")
        return None

    @classmethod
    def _fetch_all_inventory_transactions(cls, company_id: str, sandbox: bool = True) -> List[Dict[str, Any]]:
        coll_name = "sandbox_inventory_transactions" if sandbox else "inventory_transactions"
        txs = []
        if _company_coll is not None:
            try:
                docs = _company_coll(company_id=company_id, coll_name=coll_name).get()
                for doc in docs:
                    d = doc.to_dict()
                    d["id"] = doc.id
                    txs.append(d)
                txs.sort(key=lambda x: x.get("date") or x.get("createdAt", ""), reverse=False)
            except Exception as e:
                print(f"⚠️ Error al obtener transacciones de inventario: {e}")
        return txs

    @classmethod
    def audit_unposted_inventory_transactions(
        cls,
        company_id: str,
        sandbox: bool = True,
        transactions: Optional[List[Dict[str, Any]]] = None,
        owner_uid: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Compara las transacciones de inventario con los postings contables
        y detecta transacciones sin asiento, en fallo o con diferencias de valor.
        """
        txs = transactions if transactions is not None else cls._fetch_all_inventory_transactions(company_id, sandbox=sandbox)
        postings = cls.get_inventory_postings(company_id, sandbox=sandbox, limit=5000)

        postings_by_tx = {p.get("inventoryTransactionId"): p for p in postings}

        unposted = []
        failed = []
        posted = []
        neutral = []

        for tx in txs:
            tx_id = tx.get("id") or tx.get("transactionId")
            total_val = round(float(tx.get("totalValue", 0.0)), 2)
            posting = postings_by_tx.get(tx_id)

            if not posting:
                if total_val > 0.0 and tx.get("type") != "TRANSFERENCIA":
                    unposted.append({
                        "txId": tx_id,
                        "date": tx.get("date"),
                        "type": tx.get("type"),
                        "reason": tx.get("reason"),
                        "itemName": tx.get("itemName"),
                        "quantity": tx.get("quantity"),
                        "totalValue": total_val,
                        "referenceNumber": tx.get("referenceId")
                    })
            elif posting.get("status") == cls.STATUS_FAILED:
                failed.append(posting)
            elif posting.get("status") == cls.STATUS_POSTED:
                posted.append(posting)
            elif posting.get("status") == cls.STATUS_SKIPPED_NEUTRAL:
                neutral.append(posting)

        return {
            "companyId": company_id,
            "totalTransactions": len(txs),
            "postedCount": len(posted),
            "neutralCount": len(neutral),
            "unpostedCount": len(unposted),
            "failedCount": len(failed),
            "unpostedTransactions": unposted,
            "failedPostings": failed,
            "status": "OK" if len(unposted) == 0 and len(failed) == 0 else "DISCREPANCY"
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # 6. HELPERS PRIVADOS
    # ═══════════════════════════════════════════════════════════════════════════

    @classmethod
    def _save_posting(cls, company_id: str, posting_id: str, data: Dict[str, Any], sandbox: bool = True):
        coll = cls._postings_coll(company_id, sandbox=sandbox)
        if coll is not None:
            try:
                coll.document(posting_id).set(data)
            except Exception as e:
                print(f"⚠️ Error al guardar inventory_posting en Firestore: {e}")


    @classmethod
    def _fetch_inventory_transaction(cls, company_id: str, tx_id: str, sandbox: bool = True) -> Optional[Dict[str, Any]]:
        coll_name = "sandbox_inventory_transactions" if sandbox else "inventory_transactions"
        if _company_coll is not None:
            doc = _company_coll(company_id=company_id, coll_name=coll_name).document(tx_id).get()
            if doc.exists:
                d = doc.to_dict()
                d["id"] = doc.id
                return d
        return None

    @classmethod
    def _build_concept_description(cls, tx_type: str, reason: str, ref_num: str, item_name: str, qty: float) -> str:
        reason_upper = (reason or "").upper()
        qty_str = f"x{int(qty)}" if qty == int(qty) else f"x{qty:.2f}"
        if reason_upper in ("VENTA", "FACTURA", "POS", "EMISION_ECF"):
            return f"Costo de ventas: {item_name} {qty_str} - Factura {ref_num}"
        elif reason_upper in ("DEVOLUCION_CLIENTE", "CREDIT_NOTE", "E34"):
            return f"Reingreso costo devuelto: {item_name} {qty_str} - Nota Crédito {ref_num}"
        elif reason_upper in ("COMPRA", "RECEPCION", "GOODS_RECEIPT"):
            return f"Recepción compra: {item_name} {qty_str} - Doc {ref_num}"
        elif reason_upper in ("RECUENTO_FISICO", "AJUSTE", "AJUSTE_POSITIVO", "SOBRANTE"):
            return f"Ajuste inventario (+): {item_name} {qty_str} - Ref {ref_num}"
        elif reason_upper in ("AJUSTE_NEGATIVO", "FALTANTE", "MERMA"):
            return f"Descargo ajuste/merma: {item_name} {qty_str} - Ref {ref_num}"
        elif tx_type == "TRANSFERENCIA":
            return f"Transferencia inventario: {item_name} {qty_str} - Ref {ref_num}"
        return f"Contabilización inventario: {item_name} {qty_str} - {ref_num}"
