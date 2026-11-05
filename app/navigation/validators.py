"""Validation helpers for the declarative navigation registry."""

from .constants import NAVIGATION_TYPES, VALID_SETTINGS_CATEGORIES, VALID_WORKSPACES


class NavigationValidationError(ValueError):
    """Raised when the navigation registry is structurally invalid."""


def validate_registry(items, app=None, strict_routes=False, module_keys=None):
    """Validate registry structure and optionally Flask endpoints.

    Endpoint validation is opt-in because importing the application requires a
    configured Flask runtime. The registry itself remains importable without it.
    """
    errors = []
    by_id = {}

    module_keys = set(module_keys) if module_keys is not None else None

    for item in items:
        if item.id in by_id:
            errors.append(f"ID duplicado: {item.id}")
        by_id[item.id] = item
        if item.workspace not in VALID_WORKSPACES:
            errors.append(f"Workspace inválido para {item.id}: {item.workspace}")
        if item.type not in NAVIGATION_TYPES:
            errors.append(f"Tipo inválido para {item.id}: {item.type}")
        if item.type == "link" and not item.route:
            errors.append(f"Enlace sin ruta: {item.id}")
        if item.type in ("group", "dynamic") and item.route:
            errors.append(f"Grupo/dinámico con ruta: {item.id}")
        if item.settings_category and item.settings_category not in VALID_SETTINGS_CATEGORIES:
            errors.append(f"Categoría de configuración inválida para {item.id}: {item.settings_category}")

    children_by_parent = {}
    for item in items:
        if item.parent:
            children_by_parent.setdefault(item.parent, []).append(item)

    for item in items:
        if item.type == "group" and not children_by_parent.get(item.id):
            errors.append(f"Grupo sin hijos: {item.id}")
        if item.type != "group" and item.children:
            errors.append(f"Solo los grupos pueden declarar hijos: {item.id}")
        if item.parent and item.parent not in by_id:
            errors.append(f"Padre inexistente para {item.id}: {item.parent}")
        if item.parent and item.parent in by_id:
            parent = by_id[item.parent]
            if parent.workspace != item.workspace:
                errors.append(f"Workspace incompatible entre {item.id} y {item.parent}")
            if parent.type not in ("group", "workspace"):
                errors.append(f"Padre no agrupador para {item.id}: {item.parent}")

        if item.module_key and not _module_key_known(item.module_key, module_keys):
            errors.append(f"Módulo comercial desconocido para {item.id}: {item.module_key}")
        for module_key in item.module_any:
            if not _module_key_known(module_key, module_keys):
                errors.append(f"Módulo comercial desconocido para {item.id}: {module_key}")

    errors.extend(_cycle_errors(items, by_id))

    if strict_routes:
        if app is None:
            errors.append("strict_routes requiere una aplicación Flask")
        else:
            rules = {rule.endpoint: rule for rule in app.url_map.iter_rules()}
            for item in items:
                if not item.route:
                    continue
                rule = rules.get(item.route)
                if rule is None:
                    errors.append(f"Endpoint inexistente para {item.id}: {item.route}")
                    continue
                required = rule.arguments - set((rule.defaults or {}).keys())
                missing = required - set(item.route_params)
                if missing:
                    errors.append(
                        f"Faltan parámetros de ruta para {item.id} ({item.route}): "
                        f"{', '.join(sorted(missing))}"
                    )

    if errors:
        raise NavigationValidationError("\n".join(errors))
    return True


def _module_key_known(module_key, module_keys=None):
    if module_keys is not None:
        return module_key in module_keys
    from app.utils.module_gate import MODULE_MAP
    return module_key in MODULE_MAP


def _cycle_errors(items, by_id):
    errors = []
    for item in items:
        seen = set()
        current = item
        while current.parent:
            if current.id in seen:
                errors.append(f"Ciclo de jerarquía detectado desde {item.id}")
                break
            seen.add(current.id)
            current = by_id.get(current.parent)
            if current is None:
                break
    return errors


def validate_permissions(items, known_permissions):
    """Validate permission names when the application provides an allowlist."""
    unknown = sorted({
        permission
        for item in items
        for permission in ((item.permission,) if item.permission else ()) + tuple(item.permission_any)
        if permission not in known_permissions
    })
    if unknown:
        raise NavigationValidationError(f"Permisos no identificados: {', '.join(unknown)}")
    return True
