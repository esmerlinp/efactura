"""Persistent, bounded audit exports.

Exports are processed in pages so a large audit collection does not need to be
loaded entirely into the Flask worker memory.
"""

import csv
import io
import uuid
import threading
from datetime import datetime, timezone

from app.services.audit_service import AuditService
from app.services.db_service import db_firestore, firebase_initialized, firebase_storage_bucket


def _jobs_path(company_id, sandbox):
    prefix = "sandbox_" if sandbox else ""
    return f"companies/{company_id}/{prefix}audit_export_jobs"


class AuditExportService:
    @staticmethod
    def create_job(company_id, owner_uid, filters, sandbox=True):
        job_id = str(uuid.uuid4())
        job = {
            "id": job_id,
            "companyId": company_id,
            "ownerUID": owner_uid,
            "status": "pending",
            "filters": filters or {},
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "error": "",
            "downloadUrl": "",
        }
        if firebase_initialized and db_firestore:
            db_firestore.collection(_jobs_path(company_id, sandbox)).document(job_id).set(job)
        return job_id

    @staticmethod
    def get_job(company_id, job_id, sandbox=True):
        if not firebase_initialized or not db_firestore:
            return {}
        doc = db_firestore.collection(_jobs_path(company_id, sandbox)).document(job_id).get()
        return {"id": doc.id, **doc.to_dict()} if doc.exists else {}

    @staticmethod
    def get_download_url(company_id, owner_uid, job_id, sandbox=True):
        job = AuditExportService.get_job(company_id, job_id, sandbox=sandbox)
        if not job or job.get("ownerUID") != owner_uid:
            return None
        return job.get("downloadUrl") or None

    @staticmethod
    def run_job(company_id, owner_uid, job_id, filters, sandbox=True):
        if not firebase_initialized or not db_firestore:
            return False
        ref = db_firestore.collection(_jobs_path(company_id, sandbox)).document(job_id)
        ref.set({"status": "running", "updatedAt": datetime.now(timezone.utc).isoformat()}, merge=True)
        try:
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=[
                "Fecha/Hora", "Módulo", "Acción", "Descripción", "Entidad ID",
                "Realizado por", "Email", "IP", "Entorno",
            ], quoting=csv.QUOTE_ALL)
            writer.writeheader()
            rows = AuditService.export_to_csv_rows(
                owner_uid=owner_uid,
                company_id=company_id,
                use_cache=False,
                **(filters or {}),
            )
            for log in rows:
                writer.writerow({
                    "Fecha/Hora": log.get("timestamp", "")[:19].replace("T", " "),
                    "Módulo": log.get("module", ""),
                    "Acción": log.get("action", ""),
                    "Descripción": log.get("entityLabel", ""),
                    "Entidad ID": log.get("entityId", ""),
                    "Realizado por": log.get("performedBy", ""),
                    "Email": log.get("performedByEmail", ""),
                    "IP": log.get("ipAddress", ""),
                    "Entorno": "Sandbox" if log.get("isSandbox") else "Producción",
                })
            filename = f"audit_exports/{company_id}/{job_id}.csv"
            download_url = ""
            if firebase_storage_bucket:
                blob = firebase_storage_bucket.blob(filename)
                blob.upload_from_string(output.getvalue().encode("utf-8-sig"), content_type="text/csv")
                download_url = blob.generate_signed_url(version="v4", expiration=900, method="GET")
            ref.set({
                "status": "completed",
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "rowCount": len(rows),
                "downloadUrl": download_url,
            }, merge=True)
            return True
        except Exception as exc:
            ref.set({
                "status": "failed",
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            }, merge=True)
            return False

    @staticmethod
    def start_worker(company_id, owner_uid, job_id, filters, sandbox=True):
        """Start the compatibility worker and return immediately.

        The job state is persisted before the thread starts, so a future
        external worker can safely claim the same job without changing the
        HTTP contract.
        """
        thread = threading.Thread(
            target=AuditExportService.run_job,
            args=(company_id, owner_uid, job_id, filters, sandbox),
            daemon=True,
            name="audit-export-worker",
        )
        thread.start()
        return thread
