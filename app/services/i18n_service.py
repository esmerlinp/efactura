SUPPORTED_LOCALES = {
    "es": "Español",
    "en": "English",
}


TRANSLATIONS = {
    "es": {
        "nav.dashboard": "Inicio",
        "nav.reports": "Reportes",
        "nav.sales": "Ingresos",
        "nav.purchases": "Compras",
        "nav.inventory": "Inventario",
        "nav.banks": "Bancos",
        "nav.crm": "CRM",
        "nav.accounting": "Contabilidad",
        "nav.hr": "RRHH y Nómina",
        "nav.workflow": "Aprobaciones",
        "nav.budgets": "Presupuestos",
        "nav.jobs": "Jobs y Procesos",
        "nav.language": "Idioma",
        "action.save": "Guardar",
        "action.cancel": "Cancelar",
        "action.edit": "Editar",
        "action.delete": "Eliminar",
        "status.pending": "Pendiente",
        "status.approved": "Aprobado",
        "status.rejected": "Rechazado",
    },
    "en": {
        "nav.dashboard": "Home",
        "nav.reports": "Reports",
        "nav.sales": "Sales",
        "nav.purchases": "Purchases",
        "nav.inventory": "Inventory",
        "nav.banks": "Banks",
        "nav.crm": "CRM",
        "nav.accounting": "Accounting",
        "nav.hr": "HR & Payroll",
        "nav.workflow": "Approvals",
        "nav.budgets": "Budgets",
        "nav.jobs": "Jobs & Processes",
        "nav.language": "Language",
        "action.save": "Save",
        "action.cancel": "Cancel",
        "action.edit": "Edit",
        "action.delete": "Delete",
        "status.pending": "Pending",
        "status.approved": "Approved",
        "status.rejected": "Rejected",
    },
}


class I18nService:
    @staticmethod
    def normalise_locale(locale: str) -> str:
        locale = (locale or "es").split("_")[0].split("-")[0].lower()
        return locale if locale in SUPPORTED_LOCALES else "es"

    @classmethod
    def current_locale(cls) -> str:
        try:
            from flask import session
            user = session.get("user", {})
            return cls.normalise_locale(session.get("locale") or user.get("locale") or user.get("language") or "es")
        except Exception:
            return "es"

    @classmethod
    def translate(cls, key: str, default: str = None, locale: str = None, **kwargs) -> str:
        loc = cls.normalise_locale(locale or cls.current_locale())
        text = TRANSLATIONS.get(loc, {}).get(key)
        if text is None:
            text = TRANSLATIONS["es"].get(key, default or key)
        try:
            return text.format(**kwargs)
        except Exception:
            return text

    @classmethod
    def set_user_locale(cls, user_uid: str, locale: str) -> bool:
        locale = cls.normalise_locale(locale)
        try:
            from flask import session
            session["locale"] = locale
            if "user" in session:
                session["user"]["locale"] = locale
        except Exception:
            pass

        try:
            from app.services.db_service import db_firestore, firebase_initialized, cache, _cached_user_profile
            if firebase_initialized:
                db_firestore.collection("users").document(user_uid).collection("config").document("user_profile").update({
                    "locale": locale,
                    "language": locale,
                })
                try:
                    cache.delete_memoized(_cached_user_profile, user_uid)
                except Exception:
                    pass
                return True
        except Exception:
            pass
        return False
