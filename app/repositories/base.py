"""
Base Repository — abstrae Firestore con interfaz tipada.
Cada repositorio de dominio hereda de esta clase.
Opera exclusivamente sobre companies/{company_id}/{collection}.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.services.db_service import db_firestore, firebase_initialized


def _serialize(value):
    """Convierte datetime a ISO string si es necesario."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class BaseRepository:
    """Repositorio base con operaciones CRUD genéricas sobre Firestore."""

    collection_prefix: str = ""
    company_id: str = ""

    def __init__(self, company_id: str):
        self.company_id = company_id

    def _collection(self, sandbox: bool = True) -> str:
        """Retorna el nombre de la colección con prefijo sandbox si aplica."""
        prefix = "sandbox_" if sandbox else ""
        return f"{prefix}{self.collection_prefix}"

    def _doc_ref(self, doc_id: str, sandbox: bool = True):
        """Retorna la referencia al documento en Firestore bajo companies/{company_id}/."""
        return (
            db_firestore.collection("companies")
            .document(self.company_id)
            .collection(self._collection(sandbox))
            .document(doc_id)
        )

    def _docs_ref(self, sandbox: bool = True):
        """Retorna la referencia a la colección en Firestore bajo companies/{company_id}/."""
        return (
            db_firestore.collection("companies")
            .document(self.company_id)
            .collection(self._collection(sandbox))
        )

    def _get_all(self, sandbox: bool = True) -> list:
        """Obtiene todos los documentos de la colección."""
        if not firebase_initialized:
            return []
        docs = self._docs_ref(sandbox).get()
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            results.append(data)
        return results

    def _get_one(self, doc_id: str, sandbox: bool = True) -> Optional[dict]:
        """Obtiene un documento por ID."""
        if not firebase_initialized:
            return None
        doc = self._doc_ref(doc_id, sandbox).get()
        if doc.exists:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
        return None

    def _save(self, doc_id: str, data: dict, sandbox: bool = True) -> str:
        """Guarda o actualiza un documento."""
        data["id"] = doc_id
        if "createdAt" not in data or not data.get("createdAt"):
            data["createdAt"] = datetime.now(timezone.utc).isoformat()
        data["updatedAt"] = datetime.now(timezone.utc).isoformat()
        if firebase_initialized:
            self._doc_ref(doc_id, sandbox).set(data)
        return doc_id

    def _delete(self, doc_id: str, sandbox: bool = True) -> bool:
        """Elimina un documento."""
        if firebase_initialized:
            self._doc_ref(doc_id, sandbox).delete()
            return True
        return False

    @staticmethod
    def _new_id() -> str:
        """Genera un nuevo UUID."""
        return str(uuid.uuid4())
