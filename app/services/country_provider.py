import logging
from typing import Optional

from app.countries.base import BaseCountryProvider

logger = logging.getLogger(__name__)


class CountryProviderFactory:
    _registry = {}

    @classmethod
    def register(cls, country_code: str, provider_class):
        normalized = country_code.upper()
        cls._registry[normalized] = provider_class
        logger.info("Country provider registered", extra={"country": normalized, "provider": provider_class.__name__})

    @classmethod
    def create(cls, country_code: str) -> Optional[BaseCountryProvider]:
        country_code = country_code.upper()
        provider_class = cls._registry.get(country_code)
        if not provider_class:
            provider_class = cls._lazy_register(country_code)
        if provider_class:
            logger.info("Country provider loaded", extra={"country": country_code})
            return provider_class()
        logger.warning("Country provider not found", extra={"country": country_code})
        return None

    @classmethod
    def _lazy_register(cls, country_code: str):
        if country_code == "DO":
            from app.countries.do.provider import DOProvider
            cls._registry["DO"] = DOProvider
            logger.info("Country provider registered (lazy)", extra={"country": "DO", "provider": "DOProvider"})
            return DOProvider
        if country_code == "MX":
            from app.countries.mx.provider import MXProvider
            cls._registry["MX"] = MXProvider
            logger.info("Country provider registered (lazy)", extra={"country": "MX", "provider": "MXProvider"})
            return MXProvider
        return None

    @classmethod
    def get_supported_countries(cls) -> list:
        return [
            {"code": c, "name": cls._registry[c].country_name}
            for c in cls._registry
        ]

    @classmethod
    def get_current_provider(cls) -> Optional[BaseCountryProvider]:
        from app.utils.country_context import get_current_country
        return cls.create(get_current_country())
