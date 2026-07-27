from app.services.db_service import DatabaseService, db_firestore


COLLECTION_RECEIVED_ECF = "received_ecf"
COLLECTION_RECEIVED_APPROVALS = "received_approvals"
COLLECTION_RECEPTOR_TOKENS = "receptor_tokens"


class ReceptorRepository:

    @staticmethod
    def _resolve_collection(owner_uid, collection_name, sandbox=True):
        prefix = "sandbox_" if sandbox else ""
        coll_name = f"{prefix}{collection_name}"
        return db_firestore.collection("companies").document(owner_uid).collection(coll_name)

    @staticmethod
    def save_received_ecf(owner_uid, ecf_data, sandbox=True):
        coll = ReceptorRepository._resolve_collection(owner_uid, COLLECTION_RECEIVED_ECF, sandbox)
        _, ref = coll.add(ecf_data)
        return ref.id

    @staticmethod
    def get_received_ecf(owner_uid, ecf_id, sandbox=True):
        coll = ReceptorRepository._resolve_collection(owner_uid, COLLECTION_RECEIVED_ECF, sandbox)
        doc = coll.document(ecf_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        data["id"] = doc.id
        return data

    @staticmethod
    def list_received_ecf(owner_uid, sandbox=True, limit=100, status=None):
        coll = ReceptorRepository._resolve_collection(owner_uid, COLLECTION_RECEIVED_ECF, sandbox)
        query = coll.order_by("received_at", direction="DESCENDING").limit(limit)
        if status:
            query = coll.where("status", "==", status).order_by("received_at", direction="DESCENDING").limit(limit)
        docs = query.stream()
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            results.append(data)
        return results

    @staticmethod
    def save_received_approval(owner_uid, approval_data, sandbox=True):
        coll = ReceptorRepository._resolve_collection(owner_uid, COLLECTION_RECEIVED_APPROVALS, sandbox)
        _, ref = coll.add(approval_data)
        return ref.id

    @staticmethod
    def get_received_approval(owner_uid, approval_id, sandbox=True):
        coll = ReceptorRepository._resolve_collection(owner_uid, COLLECTION_RECEIVED_APPROVALS, sandbox)
        doc = coll.document(approval_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        data["id"] = doc.id
        return data

    @staticmethod
    def list_received_approvals(owner_uid, sandbox=True, limit=100):
        coll = ReceptorRepository._resolve_collection(owner_uid, COLLECTION_RECEIVED_APPROVALS, sandbox)
        docs = coll.order_by("received_at", direction="DESCENDING").limit(limit).stream()
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            results.append(data)
        return results

    @staticmethod
    def save_token(owner_uid, token_data, sandbox=True):
        coll = ReceptorRepository._resolve_collection(owner_uid, COLLECTION_RECEPTOR_TOKENS, sandbox)
        _, ref = coll.add(token_data)
        return ref.id

    @staticmethod
    def get_token(owner_uid, token_value, sandbox=True):
        coll = ReceptorRepository._resolve_collection(owner_uid, COLLECTION_RECEPTOR_TOKENS, sandbox)
        docs = coll.where("token", "==", token_value).limit(1).stream()
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
        return None

    @staticmethod
    def delete_expired_tokens(owner_uid, sandbox=True):
        coll = ReceptorRepository._resolve_collection(owner_uid, COLLECTION_RECEPTOR_TOKENS, sandbox)
        now = datetime.now(timezone.utc).isoformat()
        docs = coll.where("expires_at", "<", now).stream()
        for doc in docs:
            doc.reference.delete()
