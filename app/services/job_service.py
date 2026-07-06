from datetime import datetime, timezone
from uuid import uuid4


_MEMORY_RUNS = []


class JobService:
    @staticmethod
    def _get_db():
        try:
            from app.services.db_service import db_firestore, firebase_initialized
            if firebase_initialized:
                return db_firestore
        except Exception:
            pass
        return None

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _collection_path() -> str:
        return "system_job_runs"

    @classmethod
    def start(cls, job_id: str, name: str, metadata: dict = None) -> str:
        run_id = str(uuid4())
        payload = {
            "id": run_id,
            "jobId": job_id,
            "name": name,
            "status": "running",
            "startedAt": cls._now(),
            "finishedAt": "",
            "durationSeconds": 0,
            "metadata": metadata or {},
            "error": "",
            "result": {},
        }
        db = cls._get_db()
        if db:
            try:
                db.collection(cls._collection_path()).document(run_id).set(payload)
            except Exception:
                _MEMORY_RUNS.append(payload)
        else:
            _MEMORY_RUNS.append(payload)
        return run_id

    @classmethod
    def finish(cls, run_id: str, status: str = "success", result: dict = None, error: str = ""):
        finished_at = cls._now()
        update = {
            "status": status,
            "finishedAt": finished_at,
            "result": result or {},
            "error": error or "",
        }
        db = cls._get_db()
        if db:
            try:
                doc = db.collection(cls._collection_path()).document(run_id).get()
                started = ""
                if doc.exists:
                    started = doc.to_dict().get("startedAt", "")
                update["durationSeconds"] = cls._duration_seconds(started, finished_at)
                db.collection(cls._collection_path()).document(run_id).update(update)
                return
            except Exception:
                pass

        for run in _MEMORY_RUNS:
            if run.get("id") == run_id:
                run.update(update)
                run["durationSeconds"] = cls._duration_seconds(run.get("startedAt", ""), finished_at)
                return

    @classmethod
    def run_monitored(cls, job_id: str, name: str, func, metadata: dict = None):
        run_id = cls.start(job_id, name, metadata=metadata)
        try:
            result = func()
            cls.finish(run_id, status="success", result=result if isinstance(result, dict) else {})
            return result
        except Exception as exc:
            cls.finish(run_id, status="error", error=str(exc))
            raise

    @staticmethod
    def _duration_seconds(started: str, finished: str) -> int:
        try:
            start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(finished.replace("Z", "+00:00"))
            return max(0, int((end_dt - start_dt).total_seconds()))
        except Exception:
            return 0

    @classmethod
    def list_runs(cls, limit: int = 50, status: str = "") -> list:
        db = cls._get_db()
        runs = []
        if db:
            try:
                query = db.collection(cls._collection_path())
                if status:
                    query = query.where("status", "==", status)
                docs = query.order_by("startedAt", direction="DESCENDING").limit(limit).stream()
                for doc in docs:
                    data = doc.to_dict()
                    data["id"] = data.get("id") or doc.id
                    runs.append(data)
                return runs
            except Exception:
                pass
        runs = list(_MEMORY_RUNS)
        if status:
            runs = [r for r in runs if r.get("status") == status]
        return sorted(runs, key=lambda r: r.get("startedAt", ""), reverse=True)[:limit]

    @classmethod
    def scheduler_jobs(cls) -> list:
        try:
            from app.services.scheduler import get_scheduler_jobs
            return get_scheduler_jobs()
        except Exception:
            return []

