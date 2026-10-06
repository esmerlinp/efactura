import json
import logging
from datetime import datetime, timedelta, timezone

from app.services.db_service import DatabaseService, db_firestore, firebase_initialized
from app.services.ecf_emission import EcfEmissionService
from app.services.dgii import DGIIService
from app.services.dgii_direct import DgiiDirectService

logger = logging.getLogger(__name__)

BACKOFF_INTERVALS = [1, 5, 15, 60, 360, 1440]
MAX_RETRY_ATTEMPTS = 20
CONTINGENCY_WINDOW_HOURS = 72
WARNING_THRESHOLD_HOURS = 48


class ContingencySyncService:

    @classmethod
    def sync_all_companies(cls, app_instance=None, company_id=None):
        logger.info("Iniciando sync de contingencia para todas las empresas...")
        owner_uids = cls._discover_all_owner_uids(company_id=company_id)
        total_synced = 0
        total_failed = 0

        for owner_uid in owner_uids:
            for sandbox in (False, True):
                try:
                    synced, failed = cls.sync_company_pending(owner_uid, sandbox=sandbox, company_id=company_id)
                    total_synced += synced
                    total_failed += failed
                except Exception as e:
                    logger.error(f"Error sync empresa {owner_uid} (sandbox={sandbox}): {e}")

        logger.info(f"Sync completado: {total_synced} sincronizadas, {total_failed} fallidas")
        return total_synced, total_failed

    @classmethod
    def _discover_all_owner_uids(cls, company_id=None):
        uids = set()
        if not firebase_initialized or not db_firestore:
            return uids

        if company_id:
            uids.add(company_id)
            return uids

        try:
            docs = db_firestore.collection("users").limit(500).stream()
            for doc in docs:
                profile_ref = doc.reference.collection("config").document("profile")
                profile_doc = profile_ref.get()
                if profile_doc.exists:
                    profile = profile_doc.to_dict()
                    if profile.get("companyRNC") and profile.get("regimenFiscal"):
                        uids.add(doc.id)
        except Exception as e:
            logger.error(f"Error descubriendo Owner UIDs: {e}")
        return uids

    @classmethod
    def sync_company_pending(cls, owner_uid, sandbox=True, company_id=None):
        invoices = DatabaseService.get_contingency_invoices(owner_uid, sandbox=sandbox, company_id=company_id)
        pending = [
            inv for inv in invoices
            if inv.get('status') in ['Emitida', 'Cobrada', 'Pendiente DGII']
        ]

        if not pending:
            return 0, 0

        company = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
        if not company:
            logger.warning(f"Perfil de empresa no encontrado para {owner_uid}")
            return 0, 0

        synced_count = 0
        failed_count = 0

        for inv in pending:
            sync_attempts = int(inv.get('syncAttempts', 0))
            last_attempt_str = inv.get('lastSyncAttempt', '')

            if not cls._should_retry(sync_attempts, last_attempt_str):
                if sync_attempts >= MAX_RETRY_ATTEMPTS:
                    inv["dgiiStatus"] = "SYNC_FAILED"
                    inv["syncError"] = f"Reintentos agotados ({sync_attempts}). Contacte a soporte."
                    DatabaseService.save_invoice(owner_uid, inv.get("id"), inv, sandbox=sandbox, company_id=company_id)
                    logger.warning(f"Documento {inv.get('encf', 'N/A')} marcado como SYNC_FAILED tras {sync_attempts} intentos.")
                continue

            encf = inv.get('encf', 'N/A')
            inv_id = inv['id']
            try:
                full_inv = DatabaseService.get_invoice(owner_uid, inv_id, sandbox=sandbox, company_id=company_id)
                target_invoice = full_inv or inv
                target_invoice['syncAttempts'] = sync_attempts + 1
                target_invoice['lastSyncAttempt'] = datetime.now(timezone.utc).isoformat()

                res = EcfEmissionService.emit_electronic_comprobante(
                    company, target_invoice, sandbox=sandbox
                )

                if res.get("success") and res.get("mode", "API") == "API":
                    cls._mark_synced(owner_uid, inv_id, target_invoice, res, sandbox, company_id=company_id)
                    synced_count += 1
                    logger.info(f"e-NCF {encf} sincronizada exitosamente")
                else:
                    DatabaseService.save_invoice(owner_uid, inv_id, target_invoice, sandbox=sandbox, company_id=company_id)
                    failed_count += 1

                    hours_in_contingency = cls._hours_since_contingency(target_invoice)
                    if hours_in_contingency and hours_in_contingency >= WARNING_THRESHOLD_HOURS:
                        cls._notify_admins(owner_uid, encf, hours_in_contingency, sandbox, company_id=company_id)

            except Exception as e:
                logger.error(f"Error sync e-NCF {encf}: {e}")
                failed_count += 1

        return synced_count, failed_count

    @classmethod
    def _should_retry(cls, attempts, last_attempt_str):
        # Límite absoluto de reintentos para evitar bucles infinitos
        if attempts >= MAX_RETRY_ATTEMPTS:
            logger.warning(f"Documento agotó reintentos ({attempts}/{MAX_RETRY_ATTEMPTS}). Se marca como falla permanente.")
            return False

        if attempts >= len(BACKOFF_INTERVALS):
            logger.info(f"Documento fuera de ventana de backoff ({attempts} intentos). Último reintento con backoff extendido.")
            # Usar backoff extendido: 24h después del último intento
            wait_minutes = 1440
        else:
            wait_minutes = BACKOFF_INTERVALS[attempts]

        if not last_attempt_str:
            return True

        try:
            last_attempt = datetime.fromisoformat(last_attempt_str)
            now = datetime.now(timezone.utc)
            if last_attempt.tzinfo is None:
                last_attempt = last_attempt.replace(tzinfo=timezone.utc)
            elapsed_minutes = (now - last_attempt).total_seconds() / 60
            return elapsed_minutes >= wait_minutes
        except (ValueError, TypeError):
            return True

    @classmethod
    def _mark_synced(cls, owner_uid, inv_id, invoice, res, sandbox, company_id=None):
        invoice["isSyncedWithDGII"] = True
        invoice["emisionMode"] = "API"
        invoice["dgiiStatus"] = res.get("dgiiStatus") or "ACCEPTED"
        invoice["xmlSignature"] = res.get("xmlSignature", invoice.get("xmlSignature", ""))
        invoice["qrCodeURL"] = res.get("qrCodeURL", invoice.get("qrCodeURL", ""))
        invoice["contingencyEmittedAt"] = None
        invoice.pop("syncAttempts", None)
        invoice.pop("lastSyncAttempt", None)

        total_paid = float(invoice.get("totalPaid", 0.0))
        net_payable = float(invoice.get("netPayable", invoice.get("total", 0.0)))
        if total_paid >= net_payable and total_paid > 0:
            invoice["status"] = "Cobrada"
        elif invoice.get("status") == "Pendiente DGII":
            invoice["status"] = "Emitida"

        DatabaseService.save_invoice(owner_uid, inv_id, invoice, sandbox=sandbox, company_id=company_id)
        cls._sync_consolidated_children(owner_uid, invoice, sandbox, company_id=company_id)
        cls._update_sequence_log(owner_uid, invoice, res, sandbox, company_id=company_id)

    @classmethod
    def _sync_consolidated_children(cls, owner_uid, invoice, sandbox, company_id=None):
        if not invoice.get("isConsolidado") or not invoice.get("consolidatedInvoiceIds"):
            return
        try:
            from app.services.db_service import DatabaseService
            pending_children = []
            for child_id in invoice.get("consolidatedInvoiceIds", []):
                child_inv = DatabaseService.get_invoice(owner_uid, child_id, sandbox=sandbox, company_id=company_id)
                if child_inv:
                    pending_children.append(child_inv)
            if pending_children:
                DatabaseService.mark_invoices_consolidated(
                    owner_uid,
                    invoice.get("consolidatedInvoiceIds", []),
                    invoice.get("encf", ""),
                    invoice.get("invoiceNumber", ""),
                    pending_invoices=pending_children,
                    is_synced=True,
                    dgii_status=invoice.get("dgiiStatus") or "ACCEPTED",
                    emision_mode=invoice.get("emisionMode") or "API",
                    sandbox=sandbox,
                    company_id=company_id
                )
        except Exception as e:
            logger.warning(f"Error sync children consolidados: {e}")

    @classmethod
    def _update_sequence_log(cls, owner_uid, invoice, res, sandbox, company_id=None):
        try:
            logs = DatabaseService.get_sequence_logs(owner_uid, sandbox=sandbox, company_id=company_id)
            log = next((l for l in logs if l.get("encf") == invoice.get("encf")), None)
            if log:
                cuadratura = DGIIService.check_tolerancia_cuadratura(
                    invoice.get("items", []), invoice.get("total", 0)
                )
                estado = "ACCEPTED" if cuadratura["within_tolerance"] else "ACCEPTED_CONDITIONAL"
                DatabaseService.update_sequence_log(owner_uid, log["id"], {
                    "estado": estado,
                    "motivo": f"Regularizado por Sincronización Automática. TrackID: {res.get('trackId', 'N/A')[:12]}",
                    "xmlEnviado": json.dumps(res.get("requestPayload"), indent=2) if res.get("requestPayload") else "",
                    "respuestaDGII": json.dumps(res.get("responseBody"), indent=2) if res.get("responseBody") else ""
                }, sandbox=sandbox, company_id=company_id)
        except Exception as e:
            logger.warning(f"Error actualizando log de secuencia: {e}")

    @classmethod
    def _record_sequence_status(cls, owner_uid, invoice, estado, motivo, resp=None, sandbox=True, company_id=None):
        try:
            logs = DatabaseService.get_sequence_logs(owner_uid, sandbox=sandbox, company_id=company_id)
            log = next((l for l in logs if l.get("encf") == invoice.get("encf")), None)
            if log:
                DatabaseService.update_sequence_log(owner_uid, log["id"], {
                    "estado": estado,
                    "motivo": motivo,
                    "respuestaDGII": json.dumps(resp, indent=2) if resp else ""
                }, sandbox=sandbox, company_id=company_id)
        except Exception as e:
            logger.warning(f"Error actualizando log de secuencia: {e}")

    @classmethod
    def _apply_status_resolution(cls, owner_uid, inv_id, invoice, res, sandbox=True, company_id=None):
        """Aplica el resultado de una consulta de estado DGII (check_status) a una
        factura PENDING. Retorna 'accepted', 'rejected' o 'pending'."""
        if not res or not res.get("success"):
            return "pending"

        dgii_status = str(res.get("dgiiStatus") or "").strip().upper()
        response_body = res.get("responseBody")

        if dgii_status == "ACCEPTED":
            invoice["dgiiStatus"] = "ACCEPTED"
            invoice["isSyncedWithDGII"] = True
            invoice.pop("pendingSyncAttempts", None)
            invoice.pop("lastPendingCheckAt", None)
            total_paid = float(invoice.get("totalPaid", 0.0))
            net_payable = float(invoice.get("netPayable", invoice.get("total", 0.0)))
            if total_paid >= net_payable and total_paid > 0:
                invoice["status"] = "Cobrada"
            elif invoice.get("status") == "Pendiente DGII":
                invoice["status"] = "Emitida"
            DatabaseService.save_invoice(owner_uid, inv_id, invoice, sandbox=sandbox, company_id=company_id)
            cls._record_sequence_status(
                owner_uid, invoice, "ACCEPTED",
                f"Regularizado por consulta de estado. TrackID: {res.get('trackId', 'N/A')[:12]}",
                resp=response_body, sandbox=sandbox, company_id=company_id,
            )
            return "accepted"

        if dgii_status == "REJECTED":
            mensajes = res.get("mensajes", []) or []
            msgs = "; ".join(m.get("valor", "") for m in mensajes if isinstance(m, dict) and m.get("valor"))
            invoice["dgiiStatus"] = "REJECTED"
            invoice["status"] = "Rechazado DGII"
            invoice["dgiiError"] = (msgs or "DGII rechazó el comprobante")[:200]
            invoice.pop("pendingSyncAttempts", None)
            invoice.pop("lastPendingCheckAt", None)
            DatabaseService.save_invoice(owner_uid, inv_id, invoice, sandbox=sandbox, company_id=company_id)
            cls._record_sequence_status(
                owner_uid, invoice, "FAILED",
                f"DGII rechazó: {msgs or 'Rechazado'}",
                resp=response_body, sandbox=sandbox, company_id=company_id,
            )
            return "rejected"

        return "pending"

    @classmethod
    def reconcile_pending_api(cls, owner_uid, sandbox=True, company_id=None):
        invoices = DatabaseService.get_pending_api_invoices(owner_uid, sandbox=sandbox, company_id=company_id)
        if not invoices:
            return 0, 0, 0

        company = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
        if not company:
            logger.warning(f"Perfil de empresa no encontrado para {owner_uid}")
            return 0, 0, 0

        synced_count = 0
        rejected_count = 0
        still_pending = 0

        for inv in invoices:
            attempts = int(inv.get("pendingSyncAttempts", 0))
            last_check = inv.get("lastPendingCheckAt", "")
            if not cls._should_retry(attempts, last_check):
                continue

            encf = inv.get("encf", "N/A")
            inv_id = inv["id"]
            try:
                full_inv = DatabaseService.get_invoice(owner_uid, inv_id, sandbox=sandbox, company_id=company_id)
                target_invoice = full_inv or inv
                target_invoice["pendingSyncAttempts"] = attempts + 1
                target_invoice["lastPendingCheckAt"] = datetime.now(timezone.utc).isoformat()

                track_id = target_invoice.get("trackId") or inv.get("trackId") or ""
                if not track_id:
                    DatabaseService.save_invoice(owner_uid, inv_id, target_invoice, sandbox=sandbox, company_id=company_id)
                    still_pending += 1
                    logger.warning(f"e-NCF {encf} sin trackId para reconciliar; marcado para revisión manual.")
                    continue

                res = DgiiDirectService.check_status(company, track_id, sandbox=sandbox)
                outcome = cls._apply_status_resolution(
                    owner_uid, inv_id, target_invoice, res, sandbox=sandbox, company_id=company_id
                )
                if outcome == "accepted":
                    synced_count += 1
                    logger.info(f"e-NCF {encf} reconciliada: ACCEPTED")
                elif outcome == "rejected":
                    rejected_count += 1
                    logger.warning(f"e-NCF {encf} reconciliada: REJECTED")
                else:
                    DatabaseService.save_invoice(owner_uid, inv_id, target_invoice, sandbox=sandbox, company_id=company_id)
                    still_pending += 1
            except Exception as e:
                logger.error(f"Error reconciliando e-NCF {encf}: {e}")
                still_pending += 1

        return synced_count, rejected_count, still_pending

    @classmethod
    def reconcile_all_companies(cls, company_id=None):
        logger.info("Iniciando reconciliación de facturas PENDING (API) para todas las empresas...")
        owner_uids = cls._discover_all_owner_uids(company_id=company_id)
        total_synced = total_rejected = total_pending = 0
        for owner_uid in owner_uids:
            for sandbox in (False, True):
                try:
                    synced, rejected, pending = cls.reconcile_pending_api(
                        owner_uid, sandbox=sandbox, company_id=company_id
                    )
                    total_synced += synced
                    total_rejected += rejected
                    total_pending += pending
                except Exception as e:
                    logger.error(f"Error reconciliación empresa {owner_uid} (sandbox={sandbox}): {e}")
        logger.info(f"Reconciliación PENDING completada: {total_synced} aceptadas, {total_rejected} rechazadas, {total_pending} pendientes")
        return total_synced, total_rejected, total_pending

    @classmethod
    def _hours_since_contingency(cls, invoice):
        emitted_at = invoice.get("contingencyEmittedAt") or invoice.get("date")
        if not emitted_at:
            return None
        try:
            emitted = datetime.fromisoformat(emitted_at)
            now = datetime.now(timezone.utc)
            if emitted.tzinfo is None:
                emitted = emitted.replace(tzinfo=timezone.utc)
            return (now - emitted).total_seconds() / 3600
        except (ValueError, TypeError):
            return None

    @classmethod
    def _notify_admins(cls, owner_uid, encf, hours, sandbox, company_id=None):
        if not firebase_initialized or not db_firestore:
            return
        try:
            team = DatabaseService.get_team_members(owner_uid, company_id=company_id)
            user_ids = [owner_uid]
            for member in team:
                uid = member.get("uid")
                if uid:
                    user_ids.append(uid)

            sandbox_param = 'true' if sandbox else 'false'
            notification = {
                "title": "e-CF en Contingencia Prolongada",
                "message": (
                    f"El comprobante {encf} lleva {hours:.0f} horas en modo contingencia "
                    f"y aún no se ha sincronizado con la DGII. "
                    f"{'Quedan menos de 24h antes del límite de 72h.' if hours >= WARNING_THRESHOLD_HOURS else ''}"
                ),
                "type": "contingency_warning",
                "encf": encf,
                "link": f"/invoices/{encf}?sandbox={sandbox_param}",
                "sandbox": sandbox,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "read": False,
            }

            for uid in user_ids:
                DatabaseService.create_user_notification(uid, dict(notification))
        except Exception as e:
            logger.error(f"Error notificando admins: {e}")

    @classmethod
    def check_expired_contingency(cls, owner_uid, sandbox=True, company_id=None):
        invoices = DatabaseService.get_contingency_invoices(owner_uid, sandbox=sandbox, company_id=company_id)
        expired = []
        for inv in invoices:
            hours = cls._hours_since_contingency(inv)
            if hours and hours >= CONTINGENCY_WINDOW_HOURS:
                expired.append({
                    "encf": inv.get("encf", "N/A"),
                    "invoiceNumber": inv.get("invoiceNumber", "N/A"),
                    "total": inv.get("total", 0),
                    "contingencyEmittedAt": inv.get("contingencyEmittedAt"),
                    "hoursInContingency": round(hours, 1),
                })
        return expired
