"""Centralized navigation definitions and resolution."""

from .models import NavigationItem, NavigationType, Workspace
from .registry import NAVIGATION_ITEMS
from .resolver import resolve_navigation, resolve_settings_center

__all__ = [
    "NAVIGATION_ITEMS",
    "NavigationItem",
    "NavigationType",
    "Workspace",
    "resolve_navigation",
    "resolve_settings_center",
]
