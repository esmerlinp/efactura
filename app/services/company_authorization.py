"""Autorizacion centralizada del ambito de compania."""

from dataclasses import dataclass

from app.services.db_service import DatabaseService


@dataclass(frozen=True)
class CompanyAccess:
    uid: str
    company_id: str
    owner_uid: str
    role: str
    permissions: dict
    membership: dict
    company: dict

    def has_permission(self, permission_name: str) -> bool:
        if self.role == "owner":
            return True
        return bool(self.permissions.get(permission_name, False))


class CompanyAuthorizationError(PermissionError):
    """Se lanza cuando no existe acceso activo a la compania solicitada."""


def _active_membership(uid: str, company_id: str) -> dict | None:
    membership = DatabaseService.get_membership(uid, company_id)
    if not membership or membership.get("status") != "active":
        return None
    return membership


def get_company_access(uid: str, company_id: str) -> CompanyAccess | None:
    if not uid or not company_id:
        return None

    membership = _active_membership(uid, company_id)
    if membership is None:
        return None

    company = DatabaseService.get_company(company_id)
    if not company or company.get("status", "active") not in ("active", "Activo", ""):
        return None

    role = membership.get("role", "employee")
    owner_uid = company.get("owner_uid", "")
    permissions = membership.get("permissions") or {}

    if owner_uid == uid:
        role = "owner"

    return CompanyAccess(
        uid=uid,
        company_id=company_id,
        owner_uid=owner_uid,
        role=role,
        permissions=dict(permissions),
        membership=dict(membership),
        company=dict(company),
    )


def require_company_access(uid: str, company_id: str) -> CompanyAccess:
    access = get_company_access(uid, company_id)
    if access is None:
        raise CompanyAuthorizationError(
            f"El usuario {uid!r} no tiene acceso activo a la compania {company_id!r}."
        )
    return access


def require_permission(uid: str, company_id: str, permission_name: str) -> CompanyAccess:
    access = require_company_access(uid, company_id)
    if not access.has_permission(permission_name):
        raise CompanyAuthorizationError(
            f"El usuario {uid!r} no tiene el permiso {permission_name!r} "
            f"en la compania {company_id!r}."
        )
    return access


def require_company_id(company_id: str, context: str = "unknown") -> str:
    """Reject service calls that omit the company scope."""
    if not company_id or not isinstance(company_id, str):
        raise CompanyAuthorizationError(
            f"{context} requiere un company_id valido; recibido {company_id!r}."
        )
    return company_id
