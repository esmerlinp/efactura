"""
ContactRepository — clientes, proveedores, interacciones CRM, documentos.
"""
from typing import Optional

from app.repositories.base import BaseRepository


class ContactRepository(BaseRepository):
    """Repositorio para gestión de contactos (clientes y proveedores)."""

    # ── Clients ─────────────────────────────────────────────────────────
    def get_clients(self, sandbox: bool = True) -> list:
        self.collection_prefix = "clients"
        return self._get_all(sandbox=sandbox)

    def get_client(self, client_id: str, sandbox: bool = True) -> Optional[dict]:
        self.collection_prefix = "clients"
        return self._get_one(client_id, sandbox=sandbox)

    def get_client_by_rnc(self, rnc: str, sandbox: bool = True) -> Optional[dict]:
        from app.services.db_service import db_firestore, firebase_initialized
        if not firebase_initialized:
            return None
        coll_name = "sandbox_clients" if sandbox else "clients"
        clean_rnc = str(rnc).replace("-", "").strip()
        docs = db_firestore.collection("users").document(self.owner_uid).collection(coll_name).where("rnc", "==", clean_rnc).get()
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
        docs = db_firestore.collection("users").document(self.owner_uid).collection(coll_name).where("rnc", "==", rnc).get()
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
        return None

    def save_client(self, client_id: str, data: dict, sandbox: bool = True) -> str:
        self.collection_prefix = "clients"
        return self._save(client_id, data, sandbox=sandbox)

    def delete_client(self, client_id: str, sandbox: bool = True) -> bool:
        self.collection_prefix = "clients"
        return self._delete(client_id, sandbox=sandbox)

    def update_client_pipeline(self, client_id: str, pipeline_stage: str, sandbox: bool = True) -> None:
        from app.services.db_service import db_firestore, firebase_initialized
        from firebase_admin import firestore
        if firebase_initialized:
            coll_name = "sandbox_clients" if sandbox else "clients"
            db_firestore.collection("users").document(self.owner_uid).collection(coll_name).document(client_id).update({
                "pipelineStage": pipeline_stage,
                "updatedAt": firestore.SERVER_TIMESTAMP
            })

    # ── Client Interactions ─────────────────────────────────────────────
    def get_client_interactions(self, client_id: str, sandbox: bool = True) -> list:
        from app.services.db_service import db_firestore, firebase_initialized
        interactions = []
        if not firebase_initialized:
            return interactions
        coll_name = "sandbox_clients" if sandbox else "clients"
        docs = db_firestore.collection("users").document(self.owner_uid).collection(coll_name).document(client_id).collection("interactions").get()
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            interactions.append(data)
        interactions.sort(key=lambda x: x.get("createdAt", x.get("date", "")), reverse=True)
        return interactions

    def save_client_interaction(self, client_id: str, interaction_id: str, data: dict, sandbox: bool = True) -> str:
        self.collection_prefix = "clients"
        from app.services.db_service import db_firestore, firebase_initialized
        data["id"] = interaction_id
        if not data.get("createdAt"):
            from datetime import datetime, timezone
            data["createdAt"] = datetime.now(timezone.utc).isoformat()
        if firebase_initialized:
            coll_name = "sandbox_clients" if sandbox else "clients"
            db_firestore.collection("users").document(self.owner_uid).collection(coll_name).document(client_id).collection("interactions").document(interaction_id).set(data)
            if data.get("nextContactDate") and not data.get("completed"):
                db_firestore.collection("users").document(self.owner_uid).collection(coll_name).document(client_id).update({
                    "nextContactDate": data["nextContactDate"],
                    "crmNotes": data.get("content", "")[:100]
                })
        return interaction_id

    # ── Client Documents ────────────────────────────────────────────────
    def get_client_documents(self, client_id: str, sandbox: bool = True) -> list:
        from app.services.db_service import db_firestore, firebase_initialized
        docs_list = []
        if firebase_initialized:
            coll_name = "sandbox_clients" if sandbox else "clients"
            docs = db_firestore.collection("users").document(self.owner_uid).collection(coll_name).document(client_id).collection("documents").get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                docs_list.append(data)
            docs_list.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        return docs_list

    # ── Suppliers ───────────────────────────────────────────────────────
    def get_suppliers(self, sandbox: bool = True) -> list:
        self.collection_prefix = "suppliers"
        return self._get_all(sandbox=sandbox)

    def get_supplier(self, supplier_id: str, sandbox: bool = True) -> Optional[dict]:
        self.collection_prefix = "suppliers"
        return self._get_one(supplier_id, sandbox=sandbox)

    def save_supplier(self, supplier_id: str, data: dict, sandbox: bool = True) -> str:
        self.collection_prefix = "suppliers"
        return self._save(supplier_id, data, sandbox=sandbox)

    def delete_supplier(self, supplier_id: str, sandbox: bool = True) -> bool:
        self.collection_prefix = "suppliers"
        return self._delete(supplier_id, sandbox=sandbox)
