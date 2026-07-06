"""
scheduler.py — APScheduler para facturación automática diaria de contratos recurrentes.
Se inicializa una sola vez dentro del proceso Flask con BackgroundScheduler.
"""
import logging
import atexit
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
_scheduler = None
_flask_app = None   # Referencia a la instancia Flask para contexto en el job


def run_daily_contract_billing():
    """
    Job diario (6:00 AM hora RD): recorre todos los contratos Activos
    cuya nextBillingDate <= hoy y genera las facturas correspondientes.
    Respeta el flag sandbox de cada contrato.
    """
    from app.services.db_service import db_firestore
    from app.services.recurrence import RecurrenceService

    logger.info("⏰ APScheduler — Iniciando facturación diaria de contratos recurrentes...")

    collections = [
        ("contracts",         False),
        ("sandbox_contracts", True),
    ]

    for collection_name, is_sandbox in collections:
        try:
            # Obtener todos los owner UIDs únicos con contratos Activos
            docs = db_firestore.collection(collection_name) \
                .where("status", "==", "Activo").stream()

            owner_uids_seen = set()
            for doc in docs:
                data = doc.to_dict()
                uid = data.get("ownerUID") or data.get("owner_uid", "")
                if uid:
                    owner_uids_seen.add(uid)

            for owner_uid in owner_uids_seen:
                try:
                    count = RecurrenceService.process_pending_contracts(
                        owner_uid,
                        sandbox=is_sandbox,
                        app_instance=_flask_app,
                    )
                    if count > 0:
                        logger.info(
                            f"✅ {count} contrato(s) facturado(s) para owner "
                            f"{owner_uid} (sandbox={is_sandbox})"
                        )
                except Exception as exc:
                    logger.error(
                        f"❌ Error procesando contratos de {owner_uid} "
                        f"(sandbox={is_sandbox}): {exc}"
                    )

        except Exception as exc:
            logger.error(
                f"❌ Error accediendo a colección '{collection_name}': {exc}"
            )

    logger.info("✅ APScheduler — Facturación diaria finalizada.")



def run_daily_depreciation():
    """Job diario (2:00 AM RD): recorre todos los dueños con activos fijos
    y ejecuta depreciación automática para los activos cuya nextDepreciationDate <= hoy."""
    from app.services.db_service import db_firestore
    from app.services.fixed_asset_service import FixedAssetService

    logger.info("⏰ APScheduler — Iniciando depreciación automática de activos fijos...")

    collections = [
        ("sandbox_fixed_assets", True),
        ("fixed_assets",         False),
    ]

    for coll_name, is_sandbox in collections:
        try:
            docs = db_firestore.collection_group(coll_name).stream()
            owner_uids_seen = set()
            for doc in docs:
                parent_path = doc.reference.parent.parent.parent.path
                uid = parent_path.split("/")[1] if "/" in parent_path else ""
                if uid:
                    owner_uids_seen.add(uid)

            for owner_uid in owner_uids_seen:
                try:
                    results = FixedAssetService.run_auto_depreciation(owner_uid, sandbox=is_sandbox)
                    success_count = sum(1 for r in results if r["success"])
                    if success_count > 0:
                        logger.info(
                            f"✅ {success_count} activo(s) depreciado(s) para owner "
                            f"{owner_uid} (sandbox={is_sandbox})"
                        )
                except Exception as exc:
                    logger.error(
                        f"❌ Error depreciando activos de {owner_uid} "
                        f"(sandbox={is_sandbox}): {exc}"
                    )
        except Exception as exc:
            logger.error(
                f"❌ Error accediendo a colección '{coll_name}': {exc}"
            )

    logger.info("✅ APScheduler — Depreciación automática finalizada.")


def cleanup_expired_idempotency_keys():
    """Job diario: elimina idempotency keys con expireAt anterior a hoy."""
    from app.services.db_service import DatabaseService
    logger.info("🧹 APScheduler — Iniciando limpieza de idempotency keys expiradas...")
    DatabaseService.cleanup_expired_idempotency_keys()
    logger.info("✅ APScheduler — Limpieza de idempotency keys finalizada.")


def run_contingency_sync():
    """Job cada 30 min: sincroniza facturas en modo FALLBACK con DGII Direct."""
    from app.services.contingency_sync_service import ContingencySyncService
    logger.info("🔄 APScheduler — Iniciando sincronización de contingencia...")
    synced, failed = ContingencySyncService.sync_all_companies()
    logger.info(f"✅ APScheduler — Sincronización de contingencia: {synced} OK, {failed} fallidas")

def _run_monitored(job_id, name, func):
    from app.services.job_service import JobService
    return JobService.run_monitored(job_id, name, func)


def monitored_daily_contract_billing():
    return _run_monitored(
        "daily_contract_billing",
        "Facturación Diaria de Contratos Recurrentes",
        run_daily_contract_billing,
    )


def monitored_cleanup_expired_idempotency_keys():
    return _run_monitored(
        "cleanup_idempotency_keys",
        "Limpieza de Idempotency Keys Expiradas",
        cleanup_expired_idempotency_keys,
    )


def monitored_contingency_sync():
    return _run_monitored(
        "contingency_sync",
        "Sincronización Automática de Contingencia DGII",
        run_contingency_sync,
    )


def monitored_daily_depreciation():
    return _run_monitored(
        "daily_depreciation",
        "Depreciación Automática de Activos Fijos",
        run_daily_depreciation,
    )


def get_scheduler_jobs():
    if _scheduler is None:
        return []
    jobs = []
    try:
        for job in _scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else "",
                "trigger": str(job.trigger),
            })
    except Exception as exc:
        logger.warning(f"No se pudo leer la lista de jobs del scheduler: {exc}")
    return jobs


def init_scheduler(app):
    """
    Inicializa el BackgroundScheduler dentro del contexto de la app Flask.
    Llama a esta función UNA SOLA VEZ al final de create_app().
    La guarda `_scheduler is not None` evita doble-init en modo debug con reloader.
    """
    global _scheduler, _flask_app

    if _scheduler is not None:
        logger.debug("APScheduler ya estaba inicializado — omitiendo re-init.")
        return

    _flask_app = app  # Guardar referencia para uso en el job (email background)

    _scheduler = BackgroundScheduler(
        timezone="America/Santo_Domingo",
        job_defaults={"coalesce": True, "max_instances": 1},
    )

    _scheduler.add_job(
        func=monitored_daily_contract_billing,
        trigger=CronTrigger(hour=6, minute=0),   # 6:00 AM RD cada día
        id="daily_contract_billing",
        name="Facturación Diaria de Contratos Recurrentes",
        replace_existing=True,
    )

    _scheduler.add_job(
        func=monitored_cleanup_expired_idempotency_keys,
        trigger=CronTrigger(hour=3, minute=0),   # 3:00 AM RD cada día
        id="cleanup_idempotency_keys",
        name="Limpieza de Idempotency Keys Expiradas",
        replace_existing=True,
    )

    _scheduler.add_job(
        func=monitored_contingency_sync,
        trigger=CronTrigger(minute="*/30"),      # Cada 30 minutos
        id="contingency_sync",
        name="Sincronización Automática de Contingencia DGII",
        replace_existing=True,
    )

    _scheduler.add_job(
        func=monitored_daily_depreciation,
        trigger=CronTrigger(hour=2, minute=0),   # 2:00 AM RD cada día
        id="daily_depreciation",
        name="Depreciación Automática de Activos Fijos",
        replace_existing=True,
    )

    _scheduler.start()
    atexit.register(lambda: _scheduler.shutdown(wait=False))

    logger.info(
        "✅ APScheduler iniciado — Facturación automática de contratos activa "
        "(todos los días a las 6:00 AM hora RD)"
    )
    logger.info(
        "✅ APScheduler — Limpieza de idempotency keys expiradas programada "
        "(todos los días a las 3:00 AM hora RD)"
    )
