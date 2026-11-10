"""Contrato de Producción — guard de acceso web.

Integra la decisión contractual en el ``before_request`` global de
``app/__init__.py`` sin duplicar autenticación ni resolución de compañía.

Aplica tanto a producción como a sandbox. La evidencia de aceptación es
independiente por ambiente: aceptar en sandbox no satisface producción y
viceversa. Las excepciones son endpoints exactos (nunca blueprints completos).
"""

from dataclasses import dataclass

from app.services.production_agreement_access_service import (
    ProductionAgreementAccessService,
)


@dataclass(frozen=True)
class GuardResult:
    blocked: bool = False
    reason: str = "ok"


class ProductionAgreementGuard:
    """Decide si una petición web debe ser bloqueada por contrato."""

    # Endpoints permitidos sin aceptación contractual.
    EXEMPT_ENDPOINTS = frozenset({
        # Visualización y aceptación del contrato
        "web_production_agreement.view",
        "web_production_agreement.current",
        "web_production_agreement.download",
        "web_production_agreement.accept_company",
        "web_production_agreement.acknowledge",
        "web_production_agreement.reject",
        # Autenticación y cierre de sesión
        "web_auth.logout",
        "web_auth.select_company",
        "web_auth.select_branch",
        "web_auth.select_project",
        "web_auth.toggle_sandbox",
        # Rutas mínimas de soporte / perfil
        "web_auth.user_profile_page",
        "web_auth.update_user_profile",
        "web_auth.change_user_password",
        # Recursos estáticos
        "static",
    })

    @classmethod
    def is_exempt(cls, endpoint) -> bool:
        return endpoint is None or endpoint in cls.EXEMPT_ENDPOINTS

    @classmethod
    def evaluate(cls, endpoint, company_id, user_id, is_sandbox) -> GuardResult:
        """Retorna GuardResult(blocked=False) si la petición puede continuar."""
        if cls.is_exempt(endpoint):
            return GuardResult(blocked=False, reason="endpoint_exempt")

        if not company_id or not user_id:
            return GuardResult(blocked=False, reason="missing_context")

        decision = ProductionAgreementAccessService.evaluate_web_access(
            company_id, user_id, sandbox=is_sandbox
        )
        if decision.allowed:
            return GuardResult(blocked=False, reason="ok")

        return GuardResult(blocked=True, reason=decision.reason)
