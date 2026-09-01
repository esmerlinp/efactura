from datetime import datetime, timezone
from app.services.db_service import DatabaseService, db_firestore


COLLECTION_RECEIVED_ECF = "received_ecf"
COLLECTION_RECEIVED_APPROVALS = "received_approvals"
COLLECTION_RECEPTOR_TOKENS = "receptor_tokens"
COLLECTION_RECEPTOR_SEEDS = "receptor_seeds"
COLLECTION_RECEPTOR_DIAGNOSTICS = "receptor_diagnostics"


class ReceptorRepository:

    @staticmethod
    def _resolve_collection(owner_uid, collection_name, sandbox=True):
        prefix = "sandbox_" if sandbox else ""
        coll_name = f"{prefix}{collection_name}"
        return db_firestore.collection("companies").document(owner_uid).collection(coll_name)

    # ── Semillas de autenticación (emitidas por GET /fe/autenticacion/api/semilla) ──

    @staticmethod
    def save_seed(seed, issued_at):
        try:
            db_firestore.collection(COLLECTION_RECEPTOR_SEEDS).document(seed).set({
                "seed": seed,
                "issued_at": issued_at,
            })
        except Exception:
            pass

    @staticmethod
    def validate_seed(seed, ttl_seconds=None):
        from config import Config
        ttl = ttl_seconds or getattr(Config, "RECEPTOR_SEED_TTL_SECONDS", 300)
        try:
            doc = db_firestore.collection(COLLECTION_RECEPTOR_SEEDS).document(seed).get()
            if not doc.exists:
                return False
            data = doc.to_dict() or {}
            issued_at = data.get("issued_at", "")
            try:
                issued = datetime.fromisoformat(issued_at)
            except (ValueError, TypeError):
                ReceptorRepository.consume_seed(seed)
                return False
            from datetime import timedelta
            if datetime.now(timezone.utc) - issued > timedelta(seconds=ttl):
                ReceptorRepository.consume_seed(seed)
                return False
            return True
        except Exception:
            return False

    @staticmethod
    def consume_seed(seed):
        try:
            db_firestore.collection(COLLECTION_RECEPTOR_SEEDS).document(seed).delete()
        except Exception:
            pass

    # ── Diagnóstico de peticiones rechazadas ──

    @staticmethod
    def save_diagnostic(data):
        try:
            if db_firestore is None:
                return None
            _, ref = db_firestore.collection(COLLECTION_RECEPTOR_DIAGNOSTICS).add(dict(data))
            return ref.id
        except Exception:
            return None

    # ── Tokens de recepción (emitidos por POST ValidacionCertificado) ──

    @staticmethod
    def save_token(owner_uid, token_data, sandbox=True):
        payload = dict(token_data)
        payload["owner_uid"] = owner_uid or ""
        payload["sandbox"] = bool(sandbox)
        try:
            db_firestore.collection(COLLECTION_RECEPTOR_TOKENS).document(token_data["token"]).set(payload)
        except Exception:
            pass
        return token_data["token"]

    @staticmethod
    def get_token_global(token_value):
        if not token_value:
            return None
        try:
            doc = db_firestore.collection(COLLECTION_RECEPTOR_TOKENS).document(token_value).get()
            if not doc.exists:
                return None
            data = doc.to_dict() or {}
            data["id"] = doc.id
            return data
        except Exception:
            return None

    @staticmethod
    def get_token(owner_uid, token_value, sandbox=True):
        stored = ReceptorRepository.get_token_global(token_value)
        if not stored:
            return None
        if owner_uid and stored.get("owner_uid") and stored.get("owner_uid") != owner_uid:
            return None
        return stored

    @staticmethod
    def delete_expired_tokens(owner_uid=None, sandbox=None):
        now = datetime.now(timezone.utc).isoformat()
        try:
            query = db_firestore.collection(COLLECTION_RECEPTOR_TOKENS).where("expires_at", "<", now)
            if owner_uid:
                query = query.where("owner_uid", "==", owner_uid)
            docs = query.stream()
            for doc in docs:
                doc.reference.delete()
        except Exception:
            pass

    # ── e-CF recibidos ──

    @staticmethod
    def save_received_ecf(owner_uid, ecf_data, sandbox=True):
        coll = ReceptorRepository._resolve_collection(owner_uid, COLLECTION_RECEIVED_ECF, sandbox)
        _, ref = coll.add(ecf_data)
        return ref.id

    @staticmethod
    def find_received_by_encf(owner_uid, encf, sender_rnc="", sandbox=True):
        if not encf:
            return None
        try:
            coll = ReceptorRepository._resolve_collection(owner_uid, COLLECTION_RECEIVED_ECF, sandbox)
            query = coll.where("encf", "==", encf)
            if sender_rnc:
                query = query.where("sender_rnc", "==", sender_rnc)
            docs = query.limit(1).stream()
            for doc in docs:
                data = doc.to_dict() or {}
                data["id"] = doc.id
                return data
        except Exception:
            pass
        return None

    # ── Lecturas combinadas sandbox + producción (para la UI de recepción) ──

    @staticmethod
    def _receptor_collections(owner_uid, collection_name):
        if db_firestore is None or not owner_uid:
            return []
        base = db_firestore.collection("companies").document(owner_uid)
        return [
            base.collection(f"sandbox_{collection_name}"),
            base.collection(collection_name),
        ]

    @staticmethod
    def list_received_ecf_merged(owner_uid, limit=100, status=None):
        """Lista e-CF recibidos combinando sandbox y producción.

        El filtro por estado se aplica en memoria para no requerir un
        índice compuesto Firestore (status + received_at).
        `limit=None` devuelve todos los documentos (para filtros UI).
        """
        docs = []
        for coll in ReceptorRepository._receptor_collections(owner_uid, COLLECTION_RECEIVED_ECF):
            try:
                query = coll.order_by("received_at", direction="DESCENDING")
                if limit:
                    query = query.limit(limit)
                for doc in query.stream():
                    data = doc.to_dict() or {}
                    data["id"] = doc.id
                    docs.append(data)
            except Exception:
                continue
        docs.sort(key=lambda d: str(d.get("received_at") or ""), reverse=True)
        if status:
            docs = [d for d in docs if d.get("status") == status]
        return docs[:limit] if limit else docs

    @staticmethod
    def get_received_ecf_merged(owner_uid, ecf_id):
        for coll in ReceptorRepository._receptor_collections(owner_uid, COLLECTION_RECEIVED_ECF):
            try:
                doc = coll.document(ecf_id).get()
                if doc.exists:
                    data = doc.to_dict() or {}
                    data["id"] = doc.id
                    return data
            except Exception:
                continue
        return None

    @staticmethod
    def list_received_approvals_merged(owner_uid, limit=100):
        docs = []
        for coll in ReceptorRepository._receptor_collections(owner_uid, COLLECTION_RECEIVED_APPROVALS):
            try:
                for doc in coll.order_by("received_at", direction="DESCENDING").limit(limit).stream():
                    data = doc.to_dict() or {}
                    data["id"] = doc.id
                    docs.append(data)
            except Exception:
                continue
        docs.sort(key=lambda d: str(d.get("received_at") or ""), reverse=True)
        return docs[:limit]

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
