"""PayrollAsyncService — Procesamiento asíncrono de nómina con tracking de progreso."""

import uuid
import threading
from datetime import datetime, timezone
from typing import Callable, Optional
from app.services.db_service import db_firestore, firebase_initialized

JOB_STATUSES = ("pending", "running", "completed", "failed", "cancelled")
JOB_TTL_DAYS = 7


def _jobs_collection(owner_uid: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"users/{owner_uid}/{prefix}hr_payroll_jobs"


def create_job(owner_uid: str, job_type: str = "payroll_calculation",
               total_items: int = 0, metadata: dict = None,
               sandbox: bool = True) -> str:
    """Crea un nuevo job asíncrono y retorna su ID."""
    if not firebase_initialized or db_firestore is None:
        return ""
    job_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    coll = _jobs_collection(owner_uid, sandbox)
    db_firestore.collection(coll).document(job_id).set({
        "id": job_id,
        "type": job_type,
        "status": "pending",
        "progress": 0,
        "totalItems": total_items,
        "processedItems": 0,
        "errorItems": 0,
        "message": "Iniciando...",
        "result": None,
        "error": None,
        "metadata": metadata or {},
        "createdAt": now_iso,
        "startedAt": None,
        "completedAt": None,
        "expiresAt": (datetime.now(timezone.utc) + __import__("datetime").timedelta(days=JOB_TTL_DAYS)).isoformat(),
    })
    return job_id


def update_job(owner_uid: str, job_id: str, data: dict, sandbox: bool = True):
    """Actualiza campos de un job (merge)."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _jobs_collection(owner_uid, sandbox)
        db_firestore.collection(coll).document(job_id).set(data, merge=True)
    except Exception as e:
        print(f"⚠️ update_job: {e}")


def get_job(owner_uid: str, job_id: str, sandbox: bool = True) -> dict:
    """Obtiene datos de un job."""
    if not firebase_initialized or db_firestore is None:
        return {}
    try:
        coll = _jobs_collection(owner_uid, sandbox)
        doc = db_firestore.collection(coll).document(job_id).get()
        return doc.to_dict() if doc.exists else {}
    except Exception as e:
        print(f"⚠️ get_job: {e}")
        return {}


def get_active_jobs(owner_uid: str, sandbox: bool = True) -> list:
    """Obtiene jobs activos (pending + running)."""
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll = _jobs_collection(owner_uid, sandbox)
        docs = db_firestore.collection(coll) \
            .where("status", "in", ["pending", "running"]) \
            .order_by("createdAt", direction="DESCENDING") \
            .get()
        return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception as e:
        print(f"⚠️ get_active_jobs: {e}")
        return []


def cancel_job(owner_uid: str, job_id: str, sandbox: bool = True) -> bool:
    """Cancela un job pendiente o en ejecución."""
    job = get_job(owner_uid, job_id, sandbox=sandbox)
    if not job or job.get("status") not in ("pending", "running"):
        return False
    update_job(owner_uid, job_id, {
        "status": "cancelled",
        "message": "Cancelado por el usuario",
        "completedAt": datetime.now(timezone.utc).isoformat(),
    }, sandbox=sandbox)
    return True


def delete_old_jobs(owner_uid: str, older_than_days: int = 30, sandbox: bool = True) -> int:
    """Elimina jobs antiguos (completados/fallados/cancelados). Retorna cuántos eliminó."""
    if not firebase_initialized or db_firestore is None:
        return 0
    try:
        cutoff = (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=older_than_days)).isoformat()
        coll = _jobs_collection(owner_uid, sandbox)
        docs = db_firestore.collection(coll) \
            .where("status", "in", ["completed", "failed", "cancelled"]) \
            .where("completedAt", "<=", cutoff) \
            .get()
        deleted = 0
        for d in docs:
            d.reference.delete()
            deleted += 1
        return deleted
    except Exception as e:
        print(f"⚠️ delete_old_jobs: {e}")
        return 0


def run_async_batch(
    owner_uid: str,
    job_id: str,
    items: list,
    process_item: Callable[[dict, int], dict],
    on_complete: Callable[[list], Optional[dict]] = None,
    batch_size: int = 50,
    sandbox: bool = True,
):
    """Ejecuta procesamiento por lotes en background con progreso incremental.

    Args:
        owner_uid: UID del tenant.
        job_id: ID del job creado previamente.
        items: Lista de items a procesar (dicts, uno por empleado).
        process_item: Función(item, index) -> dict con el resultado.
        on_complete: Función(results) -> dict opcional, llamada al finalizar.
        batch_size: Tamaño del lote para actualizar progreso en Firestore.
    """
    def _worker():
        system_run_id = None
        try:
            from app.services.job_service import JobService
            system_run_id = JobService.start(
                job_id="payroll_calc",
                name=f"payroll_calculation_{owner_uid}",
                metadata={"payroll_job_id": job_id, "sandbox": sandbox},
            )
        except Exception:
            pass

        try:
            total = len(items)
            now_iso = datetime.now(timezone.utc).isoformat()
            update_job(owner_uid, job_id, {
                "status": "running",
                "totalItems": total,
                "startedAt": now_iso,
                "message": f"Procesando {total} empleados...",
            }, sandbox=sandbox)

            results = []
            error_count = 0
            last_progress_update = 0

            for i, item in enumerate(items):
                try:
                    job = get_job(owner_uid, job_id, sandbox=sandbox)
                    if job.get("status") == "cancelled":
                        return
                    result = process_item(item, i)
                    results.append({"employeeId": item.get("employeeId", item.get("id", "")), "success": True, **result})
                except Exception as e:
                    error_count += 1
                    results.append({"employeeId": item.get("employeeId", item.get("id", "")), "success": False, "error": str(e)})

                current = i + 1
                if current - last_progress_update >= batch_size:
                    progress_pct = int((current / total) * 90) if total > 0 else 90
                    update_job(owner_uid, job_id, {
                        "progress": progress_pct,
                        "processedItems": current,
                        "errorItems": error_count,
                        "message": f"Procesados {current} de {total} empleados...",
                    }, sandbox=sandbox)
                    last_progress_update = current

            update_job(owner_uid, job_id, {
                "progress": 90,
                "processedItems": total,
                "errorItems": error_count,
                "message": "Finalizando...",
            }, sandbox=sandbox)

            final_result = None
            if on_complete:
                final_result = on_complete(results)

            now_iso = datetime.now(timezone.utc).isoformat()
            update_job(owner_uid, job_id, {
                "status": "completed",
                "progress": 100,
                "processedItems": total,
                "errorItems": error_count,
                "message": f"Cálculo completado: {total} empleados procesados, {error_count} errores",
                "result": final_result,
                "completedAt": now_iso,
            }, sandbox=sandbox)

            if system_run_id:
                try:
                    JobService.finish(system_run_id, "success", result=final_result)
                except Exception:
                    pass
        except Exception as e:
            now_iso = datetime.now(timezone.utc).isoformat()
            update_job(owner_uid, job_id, {
                "status": "failed",
                "error": str(e),
                "message": f"Error: {e}",
                "completedAt": now_iso,
            }, sandbox=sandbox)
            if system_run_id:
                try:
                    JobService.finish(system_run_id, "error", error=str(e))
                except Exception:
                    pass

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return job_id


def run_async(owner_uid: str, job_id: str, target_func: Callable, sandbox: bool = True):
    """Ejecuta una función simple en background (legacy wrapper)."""
    def _worker():
        system_run_id = None
        try:
            from app.services.job_service import JobService
            system_run_id = JobService.start(
                job_id="payroll_calc",
                name=f"payroll_calculation_{owner_uid}",
                metadata={"payroll_job_id": job_id, "sandbox": sandbox},
            )
        except Exception:
            pass

        try:
            update_job(owner_uid, job_id, {
                "status": "running",
                "startedAt": datetime.now(timezone.utc).isoformat(),
            }, sandbox=sandbox)
            result = target_func()
            update_job(owner_uid, job_id, {
                "status": "completed",
                "progress": 100,
                "message": "Cálculo completado",
                "result": result,
                "completedAt": datetime.now(timezone.utc).isoformat(),
            }, sandbox=sandbox)
            if system_run_id:
                try:
                    JobService.finish(system_run_id, "success", result=result)
                except Exception:
                    pass
        except Exception as e:
            update_job(owner_uid, job_id, {
                "status": "failed",
                "error": str(e),
                "message": f"Error: {e}",
                "completedAt": datetime.now(timezone.utc).isoformat(),
            }, sandbox=sandbox)
            if system_run_id:
                try:
                    JobService.finish(system_run_id, "error", error=str(e))
                except Exception:
                    pass

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return job_id
