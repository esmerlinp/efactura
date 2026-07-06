import uuid
import threading
from datetime import datetime, timezone
from app.services.db_service import db_firestore, firebase_initialized


def _jobs_collection(owner_uid: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"users/{owner_uid}/{prefix}hr_payroll_jobs"


def create_job(owner_uid: str, sandbox: bool = True) -> str:
    if not firebase_initialized or db_firestore is None:
        return ""
    job_id = str(uuid.uuid4())
    coll = _jobs_collection(owner_uid, sandbox)
    db_firestore.collection(coll).document(job_id).set({
        "id": job_id,
        "status": "pending",
        "progress": 0,
        "total": 0,
        "message": "Iniciando cálculo...",
        "result": None,
        "error": None,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    })
    return job_id


def update_job(owner_uid: str, job_id: str, data: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _jobs_collection(owner_uid, sandbox)
        db_firestore.collection(coll).document(job_id).set(data, merge=True)
    except Exception as e:
        print(f"⚠️ update_job: {e}")


def get_job(owner_uid: str, job_id: str, sandbox: bool = True) -> dict:
    if not firebase_initialized or db_firestore is None:
        return {}
    try:
        coll = _jobs_collection(owner_uid, sandbox)
        doc = db_firestore.collection(coll).document(job_id).get()
        return doc.to_dict() if doc.exists else {}
    except Exception as e:
        print(f"⚠️ get_job: {e}")
        return {}


def run_async(owner_uid: str, job_id: str, target_func, sandbox: bool = True):
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
            update_job(owner_uid, job_id, {"status": "running"}, sandbox=sandbox)
            result = target_func()
            update_job(owner_uid, job_id, {
                "status": "completed",
                "progress": 100,
                "message": "Cálculo completado",
                "result": result,
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
            }, sandbox=sandbox)
            if system_run_id:
                try:
                    JobService.finish(system_run_id, "error", error=str(e))
                except Exception:
                    pass
    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return job_id
