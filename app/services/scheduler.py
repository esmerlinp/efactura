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


def _get_all_owner_uids():
    """Obtiene todos los owner UIDs con perfil configurado (RNC + regimenFiscal).
    Cache compartido por los jobs del scheduler para evitar lecturas repetitivas de users."""
    from app.services.db_service import db_firestore, firebase_initialized
    uids = set()
    if not firebase_initialized or not db_firestore:
        return uids
    try:
        docs = db_firestore.collection("users").limit(1000).stream()
        for doc in docs:
            profile_ref = doc.reference.collection("config").document("profile")
            profile_doc = profile_ref.get()
            if profile_doc.exists:
                profile = profile_doc.to_dict()
                if profile.get("companyRNC"):
                    uids.add(doc.id)
    except Exception as e:
        logger.error(f"Error obteniendo owner UIDs: {e}")
    return uids


def run_daily_contract_billing():
    """
    Job diario (6:00 AM hora RD): recorre todos los usuarios con contratos Activos
    cuya nextBillingDate <= hoy y genera las facturas correspondientes.
    Respeta el flag sandbox de cada contrato.
    Optimización GCP: lee la colección users primero (más pequeña) y luego
    busca contratos por ownerUID en vez de escanear toda la colección contracts.
    """
    from app.services.db_service import db_firestore
    from app.services.recurrence import RecurrenceService

    logger.info("⏰ APScheduler — Iniciando facturación diaria de contratos recurrentes...")

    owner_uids = _get_all_owner_uids()
    if not owner_uids:
        logger.info("ℹ️ No se encontraron usuarios para facturación de contratos.")
        return

    collections = [
        ("contracts",         False),
        ("sandbox_contracts", True),
    ]

    for collection_name, is_sandbox in collections:
        for owner_uid in owner_uids:
            try:
                contracts = db_firestore.collection(collection_name) \
                    .where("ownerUID", "==", owner_uid) \
                    .where("status", "==", "Activo").stream()
                has_active = any(True for _ in contracts)
                if not has_active:
                    continue

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

    logger.info("✅ APScheduler — Facturación diaria finalizada.")



def run_daily_depreciation():
    """Job diario (2:00 AM RD): recorre todos los dueños con activos fijos
    y ejecuta depreciación automática para los activos cuya nextDepreciationDate <= hoy.
    Optimización GCP: evita collection_group (costoso), itera por usuario."""
    from app.services.db_service import db_firestore
    from app.services.fixed_asset_service import FixedAssetService

    logger.info("⏰ APScheduler — Iniciando depreciación automática de activos fijos...")

    owner_uids = _get_all_owner_uids()
    if not owner_uids:
        logger.info("ℹ️ No se encontraron usuarios para depreciación de activos.")
        return

    collections = [
        ("sandbox_fixed_assets", True),
        ("fixed_assets",         False),
    ]

    for coll_name, is_sandbox in collections:
        for owner_uid in owner_uids:
            try:
                assets_coll = db_firestore.collection("users").document(owner_uid).collection(coll_name)
                docs = assets_coll.where("status", "==", "active").stream()
                has_active = any(True for _ in docs)
                if not has_active:
                    continue

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


def run_daily_rui_generation():
    """Job diario (00:30 AM RD): genera RUI automático para el día anterior
    en todas las empresas con ruiEnabled=True y ruiAutoGenerate=True."""
    from app.services.db_service import db_firestore
    from app.services.rui_generation_service import RuiGenerationService
    from datetime import date, timedelta

    logger.info("⏰ APScheduler — Iniciando generación automática de RUI...")

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    owner_uids = _get_all_owner_uids()
    if not owner_uids:
        logger.info("ℹ️ No se encontraron usuarios para generación de RUI.")
        return

    generated = 0
    skipped = 0
    errors = 0

    for owner_uid in owner_uids:
        for coll_prefix, is_sandbox in [("sandbox_", True), ("", False)]:
            try:
                profile_ref = db_firestore.collection("users").document(owner_uid) \
                    .collection("config").document("profile")
                profile_doc = profile_ref.get()
                if not profile_doc.exists:
                    continue
                profile = profile_doc.to_dict()
                if not profile.get("ruiEnabled") or not profile.get("ruiAutoGenerate"):
                    skipped += 1
                    continue

                RuiGenerationService.generate_rui(
                    owner_uid, yesterday, "sistema@rui-automatico",
                    sandbox=is_sandbox, auto=True
                )
                logger.info(f"✅ RUI generado para {owner_uid} (fecha={yesterday}, sandbox={is_sandbox})")
                generated += 1
            except ValueError as e:
                if "ya existe" in str(e).lower() or "no hay facturas" in str(e).lower():
                    skipped += 1
                else:
                    logger.warning(f"⏭️ RUI {owner_uid}: {e}")
                    skipped += 1
            except Exception as exc:
                logger.error(f"❌ Error generando RUI para {owner_uid}: {exc}")
                errors += 1

    logger.info(
        f"✅ APScheduler — RUI finalizado: {generated} generados, "
        f"{skipped} omitidos, {errors} errores."
    )

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


def monitored_daily_rui_generation():
    return _run_monitored(
        "daily_rui_generation",
        "Generación Automática de RUI",
        run_daily_rui_generation,
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

    # NOTA: La sincronización de contingencia se ejecuta manualmente
    # desde /admin/jobs (panel de administración) o desde el Dashboard.
    # El job automático cada 30 min fue deshabilitado para reducir
    # costos de Firestore — ver plan de optimización GCP Jul 2026.

    _scheduler.add_job(
        func=monitored_daily_depreciation,
        trigger=CronTrigger(hour=2, minute=0),   # 2:00 AM RD cada día
        id="daily_depreciation",
        name="Depreciación Automática de Activos Fijos",
        replace_existing=True,
    )

    _scheduler.add_job(
        func=monitored_daily_rui_generation,
        trigger=CronTrigger(hour=0, minute=30),  # 12:30 AM RD cada día
        id="daily_rui_generation",
        name="Generación Automática de RUI (día anterior)",
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
