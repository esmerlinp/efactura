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
        func=run_daily_contract_billing,
        trigger=CronTrigger(hour=6, minute=0),   # 6:00 AM RD cada día
        id="daily_contract_billing",
        name="Facturación Diaria de Contratos Recurrentes",
        replace_existing=True,
    )

    _scheduler.start()
    atexit.register(lambda: _scheduler.shutdown(wait=False))

    logger.info(
        "✅ APScheduler iniciado — Facturación automática de contratos activa "
        "(todos los días a las 6:00 AM hora RD)"
    )
