"""Navigation constants shared by the registry and templates."""

WORKSPACE_GLOBAL = "global"
WORKSPACE_RRHH = "rrhh"
WORKSPACE_ACCOUNTING = "accounting"

VALID_WORKSPACES = frozenset({
    WORKSPACE_GLOBAL,
    WORKSPACE_RRHH,
    WORKSPACE_ACCOUNTING,
})

NAVIGATION_TYPES = frozenset({
    "link",
    "group",
    "workspace",
    "dynamic",
})

SETTINGS_CATEGORIES = (
    {"id": "company_fiscal", "label": "Empresa y Fiscalidad", "icon": "fa-solid fa-building-shield", "order": 10},
    {"id": "users_security", "label": "Usuarios y Seguridad", "icon": "fa-solid fa-user-shield", "order": 20},
    {"id": "integrations_development", "label": "Integraciones y Desarrollo", "icon": "fa-solid fa-code", "order": 30},
    {"id": "system_monitoring", "label": "Sistema y Monitoreo", "icon": "fa-solid fa-server", "order": 40},
    {"id": "data_subscription", "label": "Datos y Suscripción", "icon": "fa-solid fa-database", "order": 50},
)

VALID_SETTINGS_CATEGORIES = frozenset(category["id"] for category in SETTINGS_CATEGORIES)
