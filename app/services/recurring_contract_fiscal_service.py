"""Fiscal eligibility rules for commercial recurring contracts."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.fiscal_document_type import FiscalDocumentType, by_code


@dataclass(frozen=True)
class FiscalEligibility:
    code: str
    allowed: bool
    requires_review: bool
    reason: str = ""


class RecurringContractFiscalService:
    """Domain-level filtering; final DGII validation remains in the fiscal engine."""

    GENERAL_CODES = frozenset({"E31", "E32"})
    CONDITIONAL_CODES = frozenset({"E44", "E45", "E46", "E47", "E48", "E49"})
    EXCLUDED_CODES = frozenset({"E41", "E43", "E33", "E34", "E50"})

    @classmethod
    def eligible_types(cls) -> tuple[FiscalDocumentType, ...]:
        from app.models.fiscal_document_type import all_types

        return tuple(
            sorted(
                (item for item in all_types() if item.code in cls.GENERAL_CODES | cls.CONDITIONAL_CODES),
                key=lambda item: item.code,
            )
        )

    @classmethod
    def validate(cls, value: str | None, *, allow_conditional: bool = False) -> FiscalEligibility:
        if not value:
            return FiscalEligibility("", False, True, "El contrato no tiene tipo de e-CF configurado")
        try:
            document_type = by_code(value)
        except (KeyError, AttributeError, TypeError):
            return FiscalEligibility(str(value), False, True, "Tipo fiscal desconocido")
        if document_type.code in cls.GENERAL_CODES:
            return FiscalEligibility(document_type.code, True, False)
        if document_type.code in cls.CONDITIONAL_CODES:
            return FiscalEligibility(
                document_type.code,
                allow_conditional,
                not allow_conditional,
                "Requiere validación de operación, cliente y régimen fiscal" if not allow_conditional else "",
            )
        return FiscalEligibility(document_type.code, False, True, "No es un comprobante de venta recurrente elegible")

    @classmethod
    def normalize_for_contract(cls, value: str | None, *, allow_conditional: bool = False) -> str | None:
        result = cls.validate(value, allow_conditional=allow_conditional)
        if not result.allowed:
            raise ValueError(result.reason)
        return result.code
