"""Runtime navigation resolver."""

from dataclasses import asdict
import unicodedata

from .constants import SETTINGS_CATEGORIES, WORKSPACE_GLOBAL
from .registry import NAVIGATION_ITEMS


def resolve_navigation(
    workspace=WORKSPACE_GLOBAL,
    *,
    active_page=None,
    active_endpoint=None,
    items=NAVIGATION_ITEMS,
    check_permission_fn=None,
    module_enabled_fn=None,
    session_data=None,
    environment=None,
):
    """Resolve visible navigation into a nested, template-friendly tree.

    Permission and module functions are injected to keep this module
    independently testable and to avoid duplicating authorization rules.
    """
    check_permission_fn = check_permission_fn or _default_check_permission
    module_enabled_fn = module_enabled_fn or _default_module_enabled
    session_data = session_data or {}

    candidates = [
        item for item in items
        if item.workspace == workspace and _is_visible(
            item,
            check_permission_fn=check_permission_fn,
            module_enabled_fn=module_enabled_fn,
            session_data=session_data,
            environment=environment,
        )
    ]
    visible_ids = {item.id for item in candidates}

    # A group is rendered only when it contains a visible descendant.
    changed = True
    while changed:
        changed = False
        for item in tuple(candidates):
            if item.type == "group" and not any(child.parent == item.id for child in candidates):
                candidates.remove(item)
                visible_ids.discard(item.id)
                changed = True
            elif item.parent and item.parent not in visible_ids:
                candidates.remove(item)
                visible_ids.discard(item.id)
                changed = True

    by_parent = {}
    for item in candidates:
        by_parent.setdefault(item.parent, []).append(item)
    for children in by_parent.values():
        children.sort(key=lambda child: (child.order, child.label.lower()))

    def build(parent):
        result = []
        for item in by_parent.get(parent, []):
            data = asdict(item)
            data["active"] = _is_active(item, active_page, active_endpoint)
            data["children"] = build(item.id)
            data["has_children"] = bool(data["children"])
            data["active_parent"] = data["active"] or any(child["active_parent"] or child["active"] for child in data["children"])
            result.append(data)
        return result

    return build(None)


def resolve_settings_center(
    *,
    active_page=None,
    active_endpoint=None,
    items=NAVIGATION_ITEMS,
    check_permission_fn=None,
    module_enabled_fn=None,
    session_data=None,
    environment=None,
):
    """Resolve authorized global settings grouped for the administration center."""
    tree = resolve_navigation(
        workspace=WORKSPACE_GLOBAL,
        active_page=active_page,
        active_endpoint=active_endpoint,
        items=items,
        check_permission_fn=check_permission_fn,
        module_enabled_fn=module_enabled_fn,
        session_data=session_data,
        environment=environment,
    )
    settings_node = next((item for item in tree if item["id"] == "global.settings"), None)
    available = settings_node["children"] if settings_node else []
    category_labels = {category["id"]: category["label"] for category in SETTINGS_CATEGORIES}
    by_category = {}
    for item in available:
        category_id = item.get("settings_category")
        if not category_id:
            continue
        item["settings_category_label"] = category_labels[category_id]
        item["search_text"] = build_settings_search_text(item)
        by_category.setdefault(category_id, []).append(item)

    categories = []
    for category in SETTINGS_CATEGORIES:
        category_items = by_category.get(category["id"], [])
        if not category_items:
            continue
        data = dict(category)
        data["items"] = category_items
        categories.append(data)
    return categories


def build_settings_search_text(item):
    """Build normalized searchable text from registry metadata."""
    values = [
        item.get("label", ""),
        item.get("description", ""),
        item.get("settings_category_label", item.get("settings_category", "")),
        *item.get("search_terms", ()),
    ]
    text = " ".join(str(value) for value in values if value)
    return "".join(
        character for character in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(character)
    )


def _is_visible(item, *, check_permission_fn, module_enabled_fn, session_data, environment):
    if not item.visible:
        return False
    if item.environment and environment != item.environment:
        return False
    if item.company_flag and not session_data.get(item.company_flag, item.company_flag_default):
        return False

    if item.module_key and not module_enabled_fn(item.module_key):
        return False
    if item.module_any and not any(module_enabled_fn(key) for key in item.module_any):
        return False

    if item.permission and not check_permission_fn(item.permission):
        return False
    if item.permission_any and not any(check_permission_fn(key) for key in item.permission_any):
        return False
    return True


def _is_active(item, active_page, active_endpoint):
    if active_endpoint and item.route == active_endpoint:
        return True
    if active_page and active_page in item.active_pages:
        return True
    return bool(item.active_prefix and active_page and active_page.startswith(item.active_prefix))


def _default_check_permission(permission):
    from app.utils.decorators import check_permission
    return check_permission(permission)


def _default_module_enabled(module_key):
    from app.utils.module_gate import module_enabled
    return module_enabled(module_key)
