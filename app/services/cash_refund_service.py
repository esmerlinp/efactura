"""Servicio de devoluciones y reembolsos desde el POS (Fase 3).

Flujo distribuido (Firestore + DGII + inventario) con estados y recuperación:
  1. Reservar la devolución y actualizar `returnedQty` por línea de forma atómica.
  2. Emitir la Nota de Crédito (E34) referenciando el e-CF original (reingresa inventario).
  3. Registrar el movimiento REFUND en caja por canal (efectivo/tarjeta/transferencia).

Estados de la emisión de la NC (``ncStatus``):
  - NC_ACCEPTED       DGII aceptó la NC (se tiene e-NCF).
  - NC_PENDING_DGII   Emisión enviada sin confirmación (fallback/contingencia, con trackId).
  - NC_REJECTED       DGII rechazó la NC explícitamente.
  - NC_RECONCILING    Resultado ambiguo (timeout). No se reemite automáticamente.

Política de reembolso: solo se registra el `REFUND` si la NC está `NC_ACCEPTED`
(o `NC_PENDING_DGII` solo con contingencia explícitamente autorizada).
"""
import hashlib
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from app.services.db_service import (
    DatabaseService,
    firebase_initialized,
    CASH_TYPE_REFUND,
    CashShiftLockError,
    CashAuthorizationError,
    _money,
    _money_round,
)
from app.services import db_service as _db


# Precisión de unidades para cantidades de inventario (3 decimales, independiente
# de la precisión monetaria de 2 decimales de `_money`).
QUANTITY_QUANTUM = Decimal("0.001")


def _qty(value, default="0"):
    """Convierte a Decimal de forma segura (para cantidades, no importes)."""
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return Decimal(str(default))


def _qty_round(value):
    return _qty(value).quantize(QUANTITY_QUANTUM, rounding=ROUND_HALF_UP)


REFUND_STATUS_RESERVED = "RESERVED"
REFUND_STATUS_COMPLETED = "COMPLETED"
REFUND_STATUS_FAILED = "FAILED"

NC_ACCEPTED = "NC_ACCEPTED"
NC_PENDING_DGII = "NC_PENDING_DGII"
NC_REJECTED = "NC_REJECTED"
NC_RECONCILING = "NC_RECONCILING"


class CashRefundError(Exception):
    """Error de negocio en una devolución (cantidad excedida, factura no encontrada, etc.)."""


class CashRefundService:
    """Orquestación de devolución + Nota de Crédito + reembolso."""

    @staticmethod
    def _coll_name(sandbox):
        return "sandbox_cash_refunds" if sandbox else "cash_refunds"

    @staticmethod
    def _derive_refund_id(company_id, sandbox, idempotency_key):
        return "rf-" + hashlib.sha256(f"{company_id}:{1 if sandbox else 0}:{idempotency_key}".encode()).hexdigest()[:24]

    @staticmethod
    def _content_signature(company_id, sandbox, invoice_id, refund_method, currency, refund_amount, items):
        items_str = ",".join(sorted(f"{str(i.get('itemId'))}:{_money(i.get('quantity', 0)):.2f}" for i in items))
        raw = "|".join([
            str(company_id), str(1 if sandbox else 0), str(invoice_id), str(refund_method),
            (currency or "DOP").upper(), f"{_money(refund_amount or 0):.2f}", items_str,
        ])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _classify_emission(res):
        """Clasifica el resultado de emisión de la NC → (ncStatus, error).

        R1/R5: la mera existencia de e-NCF NO implica aceptación, y un error técnico
        genérico (timeout/red) NO es un rechazo fiscal. Solo evidencia explícita de
        DGII con `success=True` clasifica ACEPTADO; una consulta fallida/incompleta
        NUNCA puede producir NC_ACCEPTED.
        """
        if not res:
            return NC_RECONCILING, "Sin respuesta de DGII"
        dgii = str(res.get("dgiiStatus") or res.get("status") or "").upper()
        msg = str(res.get("message") or res.get("error") or "").upper()
        success = bool(res.get("success"))
        rejected = any(t in dgii for t in ("RECHAZ", "REJECT", "DENIED")) or \
            any(t in msg for t in ("RECHAZAD", "REJECTED", "DENIED"))
        if rejected:
            return NC_REJECTED, res.get("message", "Rechazado por DGII")
        # La aceptación exige consulta exitosa + estado explícito.
        if success and any(t in dgii for t in ("ACEPT", "APROB", "APPROVED", "ACCEPTED")):
            return NC_ACCEPTED, None
        if success and ("PEND" in dgii or res.get("mode") in ("FALLBACK", "CONTINGENCY")):
            return NC_PENDING_DGII, None
        # Fallo de consulta o resultado no concluyente → ambiguo (nunca aceptación).
        return NC_RECONCILING, res.get("message") or "Resultado de emisión no concluyente"

    @classmethod
    def _refund_allowed(cls, nc_status, allow_pending=False):
        if nc_status == NC_ACCEPTED:
            return True
        if nc_status == NC_PENDING_DGII and allow_pending:
            return True
        return False

    @classmethod
    def _find_line(cls, invoice_items, item_id):
        for it in invoice_items:
            if str(item_id) in (str(it.get("id")), str(it.get("itemId")), str(it.get("catalogId"))):
                return it
        return None

    @classmethod
    def _compute_return_lines(cls, invoice, requested_items):
        invoice_items = list(invoice.get("items") or [])
        updated_items = [dict(it) for it in invoice_items]
        return_lines = []
        total_subtotal = _money(0)
        total_itbis = _money(0)
        for req in requested_items:
            item_id = req.get("itemId") or req.get("id")
            qty = _qty(req.get("quantity", 0))
            if not item_id or qty <= 0:
                raise CashRefundError("Cantidad de devolución inválida.")
            line = cls._find_line(updated_items, item_id)
            if line is None:
                raise CashRefundError(f"La línea '{item_id}' no pertenece a la factura original.")
            sold_qty = _qty(line.get("quantity", 0))
            returned_qty = _qty(line.get("returnedQty", 0))
            available = sold_qty - returned_qty
            if qty > available:
                raise CashRefundError(
                    f"Cantidad a devolver ({qty}) supera lo disponible ({available}) para la línea '{item_id}'."
                )
            line["returnedQty"] = float(_qty_round(returned_qty + qty))
            line_subtotal = _money(line.get("subtotal", 0))
            line_itbis = _money(line.get("itbisAmount", line.get("itbis_amount", 0)))
            prop_subtotal = _money_round(line_subtotal / sold_qty * qty) if sold_qty else 0.0
            prop_itbis = _money_round(line_itbis / sold_qty * qty) if sold_qty else 0.0
            total_subtotal += _money(prop_subtotal)
            total_itbis += _money(prop_itbis)
            return_lines.append({
                "id": line.get("id") or line.get("itemId") or item_id,
                "itemId": line.get("itemId") or item_id,
                "name": line.get("name", ""),
                "type": line.get("type", "Bien"),
                "price": float(line.get("price", 0) or 0),
                "quantity": float(_qty_round(qty)),
                "itbisRate": float(line.get("itbisRate", 0.0) if line.get("itbisRate") is not None else 0.0),
                "subtotal": prop_subtotal,
                "itbisAmount": prop_itbis,
                "total": _money_round(_money(prop_subtotal) + _money(prop_itbis)),
                "reingresoStock": bool(str(line.get("type", "Bien")).strip().lower() in ("bien", "bienes")),
                "originalCost": float(line.get("originalCost") or line.get("unitCost") or line.get("costPrice") or 0.0),
                "originalInvoiceId": invoice.get("id", ""),
                "originalLineId": line.get("id") or line.get("itemId") or item_id,
            })
        return updated_items, return_lines, _money_round(total_subtotal), _money_round(total_itbis)

    @classmethod
    def reserve_refund(cls, owner_uid, company_id, sandbox, invoice_id, refund_method, items,
                       performed_by, performed_by_uid, authorized_by, authorized_by_uid,
                       authorized_at, refund_amount, currency, idempotency_key):
        """Reserva la devolución y actualiza returnedQty de forma atómica."""
        if not firebase_initialized:
            raise CashRefundError("Firebase no está inicializado.")
        currency = (currency or "DOP").upper()
        if currency not in ("DOP", "USD"):
            raise CashRefundError("Moneda inválida.")

        refund_id = cls._derive_refund_id(company_id, sandbox, idempotency_key)
        content_sig = cls._content_signature(company_id, sandbox, invoice_id, refund_method, currency, refund_amount, items)

        refunds_coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._coll_name(sandbox))
        invoices_coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid,
                                          coll_name="sandbox_invoices" if sandbox else "invoices")
        if refunds_coll is None or invoices_coll is None:
            raise CashRefundError("No se pudo resolver las colecciones de devolución.")

        refund_ref = refunds_coll.document(refund_id)
        invoice_ref = invoices_coll.document(invoice_id)

        def _run(txn):
            refund_snap = txn.get(refund_ref)
            if refund_snap.exists:
                existing = refund_snap.to_dict() or {}
                if existing.get("contentSignature") == content_sig:
                    return {"already": True, "refund": existing}
                raise CashRefundError("La clave de idempotencia ya fue usada con parámetros distintos.")

            invoice_snap = txn.get(invoice_ref)
            if not invoice_snap.exists:
                raise CashRefundError("Factura original no encontrada.")
            invoice = invoice_snap.to_dict() or {}

            updated_items, return_lines, subtotal, itbis = cls._compute_return_lines(invoice, items)
            total = _money_round(_money(subtotal) + _money(itbis))
            if total <= 0:
                raise CashRefundError("El importe de la devolución debe ser mayor a cero.")
            if refund_amount is not None:
                amt = _money(refund_amount)
                if amt <= 0:
                    raise CashRefundError("El importe del reembolso debe ser mayor a cero.")
                # No se soportan reembolsos monetarios parciales sobre una misma NC:
                # igualdad exacta (redondeada a 2 decimales) con el total de la devolución.
                if _money_round(amt) != _money_round(total):
                    raise CashRefundError(
                        "El importe del reembolso no coincide con el total respaldado por la devolución."
                    )

            now = datetime.now(timezone.utc).isoformat()
            refund = {
                "id": refund_id,
                "idempotencyKey": idempotency_key,
                "contentSignature": content_sig,
                "ownerUID": owner_uid,
                "companyId": company_id,
                "invoiceId": invoice_id,
                "invoiceNumber": invoice.get("invoiceNumber", ""),
                "originalEncNcf": invoice.get("encf", ""),
                "refundMethod": refund_method,
                "refundAmount": _money_round(refund_amount if refund_amount else total),
                "currency": currency,
                "subtotal": subtotal,
                "totalITBIS": itbis,
                "total": total,
                "items": return_lines,
                "status": REFUND_STATUS_RESERVED,
                "performedBy": performed_by,
                "performedByUid": performed_by_uid,
                "authorizedBy": authorized_by,
                "authorizedByUid": authorized_by_uid,
                "authorizedAt": authorized_at,
                "createdAt": now,
                "updatedAt": now,
                "syncAttempts": 0,
            }
            txn.update(invoice_ref, {"items": updated_items})
            txn.set(refund_ref, refund)
            return {"already": False, "refund": refund}

        try:
            return DatabaseService._run_in_transaction(_run)
        except CashRefundError:
            raise
        except Exception as e:
            raise CashRefundError(f"Error al reservar la devolución: {e}")

    @classmethod
    def build_credit_note_dict(cls, company, refund):
        now = datetime.now(timezone.utc).isoformat()
        items = []
        for line in refund.get("items", []):
            items.append({
                "id": line.get("id"), "itemId": line.get("itemId"), "name": line.get("name", ""),
                "type": line.get("type", "Bien"), "price": line.get("price", 0.0),
                "quantity": line.get("quantity", 0.0), "itbisRate": line.get("itbisRate", 0.0),
                "subtotal": line.get("subtotal", 0.0), "itbisAmount": line.get("itbisAmount", 0.0),
                "total": line.get("total", 0.0), "reingresoStock": line.get("reingresoStock", False),
                "originalCost": line.get("originalCost", 0.0),
                "originalInvoiceId": line.get("originalInvoiceId", ""), "originalLineId": line.get("originalLineId", ""),
            })
        return {
            "invoiceNumber": f"NC-{refund.get('id', '')[:12]}", "date": now, "dueDate": now,
            "clientId": company.get("id") or "default",
            "clientName": company.get("tradeName") or company.get("companyName", "Cliente"),
            "clientRNC": company.get("companyRNC", "") or "000000000",
            "status": "Borrador", "ecfType": "Nota de Crédito (E34)",
            "currency": refund.get("currency", "DOP"), "paymentType": "01 - Contado",
            "paymentMethod": refund.get("refundMethod", "Efectivo"), "incomeType": "01 - Ingresos por operaciones",
            "subtotal": refund.get("subtotal", 0.0), "totalITBIS": refund.get("totalITBIS", 0.0),
            "total": refund.get("total", 0.0), "netPayable": refund.get("total", 0.0),
            "isQuotation": False, "isConvertedToInvoice": False, "items": items, "stockReduced": False,
            "referenceInvoiceId": refund.get("invoiceId", ""),
            "informationReference": {"ncfModified": refund.get("originalEncNcf", ""), "ncfModifiedDate": ""},
            "indicadorNotaCredito": "0", "refundId": refund.get("id", ""), "isSyncedWithDGII": False,
        }

    @classmethod
    def emit_credit_note(cls, owner_uid, company_id, sandbox, refund):
        """Emite la NC E34 y clasifica su resultado DGII (R1). Recupera NC existente (R4)."""
        from app.services.ecf_emission import EcfEmissionService

        refund_id = refund.get("id", "")
        nc_id = f"nc-{refund_id}"
        company = DatabaseService.get_company_profile(owner_uid, company_id=company_id)

        # R4: si la NC ya existe (determinista), reconciliar en lugar de reemitir.
        # Leer el documento crudo (no get_invoice) para conservar `emissionAttempted`.
        existing_nc = None
        invoices_coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid,
                                          coll_name="sandbox_invoices" if sandbox else "invoices")
        if invoices_coll is not None:
            snap = invoices_coll.document(nc_id).get()
            existing_nc = snap.to_dict() if snap and snap.exists else None

        if existing_nc and existing_nc.get("emissionAttempted"):
            # R4: la NC ya fue intentada. No inferir aceptación por e-NCF: consultar
            # por referencia inequívoca (e-NCF / trackId) y, si no hay, mantener bloqueo.
            refund["creditNoteId"] = nc_id
            refund["creditNoteEncNcf"] = existing_nc.get("encf", "")
            refund["trackId"] = existing_nc.get("trackId", "")
            if existing_nc.get("encf") or existing_nc.get("trackId"):
                refund = cls.reconcile_credit_note(owner_uid, company_id, sandbox, refund)
            else:
                refund["ncStatus"] = NC_RECONCILING
                refund["reconciliationStatus"] = NC_RECONCILING
            refund["updatedAt"] = datetime.now(timezone.utc).isoformat()
            cls._save_refund(owner_uid, company_id, sandbox, refund)
            return refund

        nc_dict = cls.build_credit_note_dict(company, refund)
        nc_dict["emissionAttempted"] = True  # marcador ANTES de emitir (evita reemisión)
        # Se guarda como Borrador: NO reingresa inventario hasta confirmar la E34.
        DatabaseService.save_invoice(owner_uid, nc_id, nc_dict, company_id=company_id, sandbox=sandbox)

        nc_status = None
        err = ""
        try:
            res = EcfEmissionService.emit_electronic_comprobante(company, nc_dict, sandbox=sandbox)
            nc_status, err = cls._classify_emission(res)
            nc_dict["encf"] = res.get("encf", "") if res else ""
            nc_dict["trackId"] = res.get("trackId", "") if res else ""
            nc_dict["xmlSignature"] = res.get("xmlSignature", "") if res else ""
            nc_dict["qrCodeURL"] = res.get("qrCodeURL", "") if res else ""
            nc_dict["emisionMode"] = res.get("mode", "API") if res else ""
            nc_dict["dgiiStatus"] = res.get("dgiiStatus", "") if res else ""
            # R1: solo marcar sincronizada ante aceptación concluyente (no por encf).
            nc_dict["isSyncedWithDGII"] = (nc_status == NC_ACCEPTED)
            # Si hay e-NCF/trackId pero no aceptación concluyente, se guarda como
            # ambigua (el encf se conserva para reconciliación posterior, no para aceptar).
            if nc_status in (NC_PENDING_DGII, NC_RECONCILING) and nc_dict.get("encf"):
                nc_dict["ncStatus"] = nc_status
        except Exception as e:
            nc_status = NC_RECONCILING
            nc_dict["emisionMode"] = "FALLBACK"
            nc_dict["isSyncedWithDGII"] = False
            nc_dict["dgiiError"] = str(e)[:200]
            err = str(e)[:200]

        nc_dict["emissionCompleted"] = True  # la llamada a DGII retornó (o lanzó)
        nc_dict["ncStatus"] = nc_status

        # Estado final: reingresa inventario SOLO cuando la E34 queda aceptada.
        if nc_status == NC_ACCEPTED:
            nc_dict["status"] = "Emitida"
        elif nc_status == NC_REJECTED:
            nc_dict["status"] = "Rechazado DGII"
            nc_dict["dgiiError"] = err or nc_dict.get("dgiiError", "")
        else:
            nc_dict["status"] = "Pendiente DGII"

        DatabaseService.save_invoice(owner_uid, nc_id, nc_dict, company_id=company_id, sandbox=sandbox)

        refund["creditNoteId"] = nc_id
        refund["creditNoteEncNcf"] = nc_dict.get("encf", "")
        refund["trackId"] = nc_dict.get("trackId", "")
        refund["creditNoteNumber"] = nc_dict.get("invoiceNumber", "")
        refund["ncStatus"] = nc_status
        refund["reconciliationStatus"] = nc_status
        refund["updatedAt"] = datetime.now(timezone.utc).isoformat()
        cls._save_refund(owner_uid, company_id, sandbox, refund)
        return refund

    @classmethod
    def reconcile_credit_note(cls, owner_uid, company_id, sandbox, refund):
        """Reconciliación de una emisión ambigua (R3): consulta estado DGII sin reemitir."""
        from app.services.dgii_direct import DgiiDirectService

        company = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
        track_id = refund.get("trackId") or refund.get("creditNoteTrackId")
        encf = refund.get("creditNoteEncNcf")

        sync_attempts = int(refund.get("syncAttempts", 0)) + 1
        now = datetime.now(timezone.utc).isoformat()
        refund["syncAttempts"] = sync_attempts
        refund["lastSyncAt"] = now

        # Referencia inequívoca: e-NCF o trackId.
        if not track_id and not encf:
            refund["reconciliationStatus"] = NC_RECONCILING
            refund["lastReconciliationError"] = "Sin referencia inequívoca (trackId/eNCF)."
            cls._save_refund(owner_uid, company_id, sandbox, refund)
            return refund

        try:
            if encf:
                res = DgiiDirectService.consultar_estado_ecf(
                    company, company.get("companyRNC", ""), encf, sandbox=sandbox
                )
                # consultar_estado_ecf retorna `responseBody` crudo; extraer estado
                # normalizado (ACCEPTED/PENDING/REJECTED) con la utilidad existente.
                body = (res or {}).get("responseBody")
                data = body if isinstance(body, dict) else None
                text = "" if isinstance(body, dict) else str(body or "")
                status = DgiiDirectService._extract_status(data, text) or "PENDING"
                res = {"success": bool(res and res.get("success")), "dgiiStatus": status}
            else:
                res = DgiiDirectService.check_status(company, track_id, sandbox=sandbox)
        except Exception as e:
            refund["reconciliationStatus"] = NC_RECONCILING
            refund["lastReconciliationError"] = str(e)[:200]
            cls._save_refund(owner_uid, company_id, sandbox, refund)
            return refund

        nc_status, err = cls._classify_emission(res)
        encf_found = (res or {}).get("encf") or (res or {}).get("eNCF")
        if nc_status == NC_ACCEPTED and encf_found:
            refund["creditNoteEncNcf"] = encf_found
        refund["reconciliationStatus"] = nc_status
        refund["ncStatus"] = nc_status
        refund["lastReconciliationError"] = err or ""
        cls._save_refund(owner_uid, company_id, sandbox, refund)

        # Si la reconciliación confirma aceptación, reingresar inventario (disponible).
        if nc_status == NC_ACCEPTED and refund.get("creditNoteId"):
            cls._finalize_credit_note_inventory(owner_uid, company_id, sandbox, refund, encf_found)
        return refund

    @classmethod
    def _finalize_credit_note_inventory(cls, owner_uid, company_id, sandbox, refund, encf):
        """Re-guarda la NC como Emitida (dispara reingreso de inventario) al confirmarse."""
        nc_id = refund.get("creditNoteId")
        if not nc_id:
            return
        invoices_coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid,
                                          coll_name="sandbox_invoices" if sandbox else "invoices")
        if invoices_coll is None:
            return
        snap = invoices_coll.document(nc_id).get()
        if not (snap and snap.exists):
            return
        nc = snap.to_dict() or {}
        if nc.get("stockReentered"):
            return
        nc["encf"] = encf or nc.get("encf", "")
        nc["ncStatus"] = NC_ACCEPTED
        nc["status"] = "Emitida"
        nc["isSyncedWithDGII"] = True
        DatabaseService.save_invoice(owner_uid, nc_id, nc, company_id=company_id, sandbox=sandbox)

    @classmethod
    def record_refund_movement(cls, owner_uid, company_id, sandbox, refund, open_shift,
                               auth_request_id, performer_uid, allow_pending=False):
        """Registra el movimiento REFUND solo si la NC está aceptada (o contingencia autorizada)."""
        nc_status = refund.get("ncStatus") or refund.get("reconciliationStatus")
        if not cls._refund_allowed(nc_status, allow_pending=allow_pending):
            raise CashRefundError(f"Reembolso bloqueado: la NC está en estado {nc_status}.")

        refund_id = refund.get("id", "")
        tx_dict = {
            "shiftId": open_shift["id"],
            "registerId": open_shift.get("registerId"),
            "type": CASH_TYPE_REFUND,
            "amount": float(refund.get("refundAmount", 0.0)),
            "currency": refund.get("currency", "DOP"),
            "paymentMethod": refund.get("refundMethod", "Efectivo"),
            "reason": f"Devolución factura {refund.get('invoiceNumber', '')}",
            "referenceId": refund.get("creditNoteId") or refund.get("invoiceId", ""),
            "transferId": refund.get("creditNoteEncNcf", ""),
            "performedBy": refund.get("performedBy", ""),
            "performedByUid": refund.get("performedByUid", ""),
            "authorizedBy": refund.get("authorizedBy", ""),
            "authorizedByUid": refund.get("authorizedByUid", ""),
            "authorizedAt": refund.get("authorizedAt", ""),
        }
        try:
            res = DatabaseService.register_cash_transaction(
                owner_uid, tx_dict, company_id=company_id, sandbox=sandbox,
                idempotency_key=f"refund-{refund_id}",
                register_id=open_shift.get("registerId"),
                shift_id=open_shift["id"],
                auth_request_id=auth_request_id,
                performer_uid=performer_uid,
            )
        except (CashShiftLockError, CashAuthorizationError):
            raise
        if not res:
            raise CashRefundError("No se pudo registrar el movimiento de reembolso.")

        refund["status"] = REFUND_STATUS_COMPLETED
        refund["updatedAt"] = datetime.now(timezone.utc).isoformat()
        cls._save_refund(owner_uid, company_id, sandbox, refund)
        return refund

    @classmethod
    def _save_refund(cls, owner_uid, company_id, sandbox, refund):
        coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._coll_name(sandbox))
        if coll is not None:
            coll.document(refund.get("id", "")).set(refund)

    @classmethod
    def resolve_reconciling(cls, owner_uid, company_id, sandbox, refund_id, resolution, reason,
                            resolved_by, resolution_key=None):
        """Resolución manual (supervisor) de una devolución en NC_RECONCILING.

        Transaccional, con historial y contador de intentos (R4):
          - Idempotencia por `resolution_key` (evita reejecutar la misma resolución).
          - R2: "reemit" se rechaza si hay evidencia de emisión (creditNoteId/encf/trackId).
          - R3: "abandon" exige factura original, líneas válidas y `returnedQty`
            suficiente (Decimal, sin `max`); cualquier inconsistencia aborta TODO.
        """
        if resolution not in ("reemit", "abandon"):
            raise CashRefundError("Resolución inválida.")
        if not (reason or "").strip():
            raise CashRefundError("La resolución requiere un motivo/evidencia registrado.")
        refunds_coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid, coll_name=cls._coll_name(sandbox))
        invoices_coll = _db._company_coll(company_id=company_id, owner_uid=owner_uid,
                                          coll_name="sandbox_invoices" if sandbox else "invoices")
        if refunds_coll is None or invoices_coll is None:
            raise CashRefundError("No se pudo resolver las colecciones de devolución.")
        refund_ref = refunds_coll.document(refund_id)
        nc_ref = invoices_coll.document(f"nc-{refund_id}")
        now = datetime.now(timezone.utc).isoformat()

        def _run(txn):
            snap = txn.get(refund_ref)
            if not snap.exists:
                raise CashRefundError("Devolución no encontrada.")
            refund = snap.to_dict() or {}

            # R4: idempotencia por clave de resolución.
            if resolution_key:
                used = set(refund.get("resolutionKeys") or [])
                if resolution_key in used:
                    return refund

            status = refund.get("status")
            nc_status = refund.get("ncStatus") or refund.get("reconciliationStatus")
            if status == REFUND_STATUS_COMPLETED:
                raise CashRefundError("La devolución ya fue completada.")
            # R4: una resolución ya aplicada bloquea otra, salvo que la devolución
            # haya vuelto a quedar ambigua (nuevo ciclo NC_RECONCILING).
            if refund.get("resolution") and nc_status not in (NC_RECONCILING,):
                raise CashRefundError("La devolución ya fue resuelta.")
            has_evidence = bool(
                refund.get("creditNoteId") or refund.get("creditNoteEncNcf") or refund.get("trackId")
                or refund.get("emissionAttempted") or refund.get("emissionCompleted")
            ) or nc_status in (NC_ACCEPTED, NC_PENDING_DGII)

            # Evidencia en el documento NC determinista (aunque no esté en el refund).
            nc_snap = txn.get(nc_ref)
            nc = nc_snap.to_dict() if nc_snap.exists else None
            nc_evidence = bool(nc and (
                nc.get("emissionAttempted") or nc.get("emissionCompleted")
                or nc.get("encf") or nc.get("trackId")
            ))

            history = list(refund.get("resolutionHistory") or [])
            attempts = int(refund.get("resolutionAttempts", 0)) + 1

            if resolution == "abandon":
                if has_evidence or nc_evidence:
                    raise CashRefundError("No se puede abandonar: existe evidencia de una E34 emitida o pendiente.")
                # R3: factura original obligatoria y liberación exacta por línea.
                invoice_ref = invoices_coll.document(refund.get("invoiceId", ""))
                inv_snap = txn.get(invoice_ref)
                if not inv_snap.exists:
                    raise CashRefundError("Factura original no encontrada.")
                inv = inv_snap.to_dict() or {}
                inv_items = list(inv.get("items") or [])
                for rline in refund.get("items", []):
                    item_id = str(rline.get("itemId") or rline.get("id"))
                    qty = _qty(rline.get("quantity", 0))
                    if qty <= 0:
                        raise CashRefundError("Cantidad de devolución inválida.")
                    matched = None
                    for it in inv_items:
                        if str(item_id) in (str(it.get("id")), str(it.get("itemId")), str(it.get("catalogId"))):
                            matched = it
                            break
                    if matched is None:
                        raise CashRefundError(f"La línea '{item_id}' no existe en la factura original.")
                    current_returned = _qty(matched.get("returnedQty", 0))
                    if current_returned < qty:
                        raise CashRefundError(
                            f"Cantidad devuelta insuficiente para liberar la línea '{item_id}'."
                        )
                    matched["returnedQty"] = float(_qty_round(current_returned - qty))
                txn.update(invoice_ref, {"items": inv_items})
                refund["status"] = REFUND_STATUS_FAILED
                refund["ncStatus"] = NC_REJECTED
                refund["reconciliationStatus"] = NC_REJECTED
                refund["resolution"] = "abandon"
            else:  # reemit
                # R2: no reemitir si hay evidencia (en el refund o en la NC) de que la
                # solicitud pudo ser recibida por DGII. La ausencia de trackId/e-NCF
                # NO demuestra no-procesamiento.
                if has_evidence or nc_evidence:
                    raise CashRefundError(
                        "No se puede reemitir: existe evidencia de que la solicitud pudo ser recibida por DGII."
                    )
                refund["creditNoteId"] = ""
                refund["creditNoteEncNcf"] = ""
                refund["trackId"] = ""
                refund["ncStatus"] = ""
                refund["reconciliationStatus"] = ""
                refund["status"] = REFUND_STATUS_RESERVED
                refund["resolution"] = "reemit"

            history.append({
                "action": resolution,
                "reason": reason,
                "resolvedBy": resolved_by,
                "resolvedAt": now,
            })
            used = set(refund.get("resolutionKeys") or [])
            if resolution_key:
                used.add(resolution_key)
            refund["resolutionHistory"] = history
            refund["resolutionKeys"] = sorted(used)
            refund["resolutionAttempts"] = attempts
            refund["resolvedBy"] = resolved_by
            refund["resolutionReason"] = reason
            refund["resolvedAt"] = now
            refund["updatedAt"] = now
            txn.set(refund_ref, refund)
            return refund

        try:
            return DatabaseService._run_in_transaction(_run)
        except CashRefundError:
            raise
        except Exception as e:
            raise CashRefundError(f"Error al resolver la devolución: {e}")

    @classmethod
    def preview_refund(cls, owner_uid, company_id, sandbox, invoice_id, items):
        invoice = DatabaseService.get_invoice(owner_uid, invoice_id, company_id=company_id, sandbox=sandbox)
        if not invoice:
            raise CashRefundError("Factura original no encontrada.")
        _updated, _lines, subtotal, itbis = cls._compute_return_lines(invoice, items)
        return {
            "subtotal": subtotal,
            "totalITBIS": itbis,
            "total": _money_round(_money(subtotal) + _money(itbis)),
        }

    @classmethod
    def process_refund(cls, owner_uid, company_id, sandbox, invoice_id, items, refund_method,
                       open_shift, performed_by, performed_by_uid, authorized_by, authorized_by_uid,
                       authorized_at, currency="DOP", refund_amount=None, idempotency_key=None,
                       auth_request_id=None, performer_uid=None, allow_pending_refund=False):
        """Orquesta la devolución completa (reserva → NC → reembolso) con recuperación."""
        if not idempotency_key:
            raise CashRefundError("Falta la clave de idempotencia.")

        result = cls.reserve_refund(
            owner_uid, company_id, sandbox, invoice_id, refund_method, items,
            performed_by, performed_by_uid, authorized_by, authorized_by_uid,
            authorized_at, refund_amount, currency, idempotency_key,
        )
        refund = result["refund"]
        refund["id"] = refund.get("id", cls._derive_refund_id(company_id, sandbox, idempotency_key))

        status = refund.get("status")
        if status == REFUND_STATUS_COMPLETED:
            return refund
        if status == REFUND_STATUS_FAILED and refund.get("failureStep") != "refund":
            status = REFUND_STATUS_RESERVED

        # 2. Emitir NC (o reconciliar si ya existe / está en estado ambiguo).
        if status == REFUND_STATUS_RESERVED and not refund.get("creditNoteId"):
            refund = cls.emit_credit_note(owner_uid, company_id, sandbox, refund)

        nc_status = refund.get("ncStatus") or refund.get("reconciliationStatus")
        if nc_status in (NC_REJECTED, NC_RECONCILING):
            # No reembolsar: NC rechazada o ambigua.
            raise CashRefundError(f"Reembolso bloqueado: la NC está en estado {nc_status}.")

        # 3. Registrar reembolso (solo NC_ACCEPTED o contingencia autorizada).
        if refund.get("status") != REFUND_STATUS_COMPLETED:
            try:
                refund = cls.record_refund_movement(
                    owner_uid, company_id, sandbox, refund, open_shift,
                    auth_request_id, performer_uid, allow_pending=allow_pending_refund,
                )
            except (CashShiftLockError, CashAuthorizationError, CashRefundError):
                raise
            except Exception as e:
                refund["status"] = REFUND_STATUS_FAILED
                refund["failureStep"] = "refund"
                refund["error"] = str(e)[:200]
                refund["updatedAt"] = datetime.now(timezone.utc).isoformat()
                cls._save_refund(owner_uid, company_id, sandbox, refund)
                raise CashRefundError(f"Error al registrar el reembolso: {e}")

        return refund
