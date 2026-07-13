# app/services/session_service.py
import uuid
from datetime import datetime, timezone
from app.services.db_service import db_firestore, firebase_initialized


class SessionService:
    """
    Gestiona el control de sesiones activas para evitar que un mismo usuario
    inicie sesión desde dos máquinas diferentes al mismo tiempo.

    Firestore structure:
      users/{uid}/config/active_session
        { "session_token": str, "ip_address": str, "user_agent": str,
          "started_at": str, "last_activity": str }
    """

    SESSION_COLLECTION = "config"
    SESSION_DOC = "active_session"

    @classmethod
    def _session_ref(cls, uid):
        if not firebase_initialized:
            return None
        return db_firestore.collection("users").document(uid).collection(cls.SESSION_COLLECTION).document(cls.SESSION_DOC)

    @classmethod
    def register_session(cls, uid, session_token, ip_address="", user_agent=""):
        """
        Guarda o sobrescribe el registro de sesión activa del usuario.
        Devuelve True si se registró correctamente.
        """
        ref = cls._session_ref(uid)
        if not ref:
            return False
        try:
            now = datetime.now(timezone.utc).isoformat()
            ref.set({
                "session_token": session_token,
                "ip_address": ip_address,
                "user_agent": user_agent[:500] if user_agent else "",
                "started_at": now,
                "last_activity": now,
            })
            return True
        except Exception as e:
            print(f"⚠️ [SessionService] Error al registrar sesión para {uid}: {e}")
            return False

    @classmethod
    def get_active_session(cls, uid):
        """
        Retorna el dict de la sesión activa del usuario, o None si no existe.
        """
        ref = cls._session_ref(uid)
        if not ref:
            return None
        try:
            doc = ref.get()
            if doc.exists:
                return doc.to_dict()
        except Exception as e:
            print(f"⚠️ [SessionService] Error al obtener sesión activa para {uid}: {e}")
        return None

    @classmethod
    def invalidate_session(cls, uid):
        """
        Elimina el registro de sesión activa del usuario (logout).
        """
        ref = cls._session_ref(uid)
        if not ref:
            return
        try:
            ref.delete()
        except Exception as e:
            print(f"⚠️ [SessionService] Error al eliminar sesión para {uid}: {e}")

    @classmethod
    def update_activity(cls, uid):
        """
        Actualiza la marca de última actividad de la sesión.
        Se llama en cada request autenticado (before_request).
        """
        ref = cls._session_ref(uid)
        if not ref:
            return
        try:
            ref.update({
                "last_activity": datetime.now(timezone.utc).isoformat()
            })
        except Exception as e:
            # No imprimir error para no ensuciar logs en cada request
            pass
