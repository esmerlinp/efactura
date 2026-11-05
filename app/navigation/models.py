"""Typed immutable models for navigation definitions."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple


class Workspace(str, Enum):
    GLOBAL = "global"
    RRHH = "rrhh"
    ACCOUNTING = "accounting"


class NavigationType(str, Enum):
    LINK = "link"
    GROUP = "group"
    WORKSPACE = "workspace"
    DYNAMIC = "dynamic"


@dataclass(frozen=True)
class NavigationItem:
    id: str
    label: str
    icon: str = ""
    route: Optional[str] = None
    workspace: str = Workspace.GLOBAL.value
    module_key: Optional[str] = None
    permission: Optional[str] = None
    parent: Optional[str] = None
    order: int = 0
    visible: bool = True
    type: str = NavigationType.LINK.value
    description: str = ""
    settings_category: Optional[str] = None
    search_terms: Tuple[str, ...] = field(default_factory=tuple)
    dom_id: Optional[str] = None
    children: Tuple[str, ...] = field(default_factory=tuple)
    route_params: Dict[str, str] = field(default_factory=dict)
    active_pages: Tuple[str, ...] = field(default_factory=tuple)
    active_prefix: Optional[str] = None
    permission_any: Tuple[str, ...] = field(default_factory=tuple)
    module_any: Tuple[str, ...] = field(default_factory=tuple)
    environment: Optional[str] = None
    company_flag: Optional[str] = None
    company_flag_default: bool = True

    def __post_init__(self):
        object.__setattr__(self, "children", tuple(self.children))
        object.__setattr__(self, "route_params", dict(self.route_params))
        object.__setattr__(self, "search_terms", tuple(self.search_terms))
        object.__setattr__(self, "active_pages", tuple(self.active_pages))
        object.__setattr__(self, "permission_any", tuple(self.permission_any))
        object.__setattr__(self, "module_any", tuple(self.module_any))
