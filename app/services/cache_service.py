"""Shared cache helpers.

The application owns a single Flask-Caching instance in ``app.cache``.  This
module provides key and invalidation helpers without creating a second local
cache per process.
"""

import hashlib
import json
from functools import wraps

from flask import current_app, g, has_request_context

from app.cache import cache


class CacheService:
    _cache = cache
    _stats = {"hits": 0, "misses": 0, "sets": 0}

    @classmethod
    def get_cache(cls):
        return cache

    @classmethod
    def get_with_stats(cls, key):
        value = cls.get_cache().get(key)
        cls._stats["hits" if value is not None else "misses"] += 1
        return value

    @classmethod
    def set_with_stats(cls, key, value, timeout=None):
        if timeout is None:
            cls.get_cache().set(key, value)
        else:
            cls.get_cache().set(key, value, timeout=timeout)
        cls._stats["sets"] += 1

    @classmethod
    def stats(cls):
        return dict(cls._stats)

    @classmethod
    def reset_stats(cls):
        cls._stats = {"hits": 0, "misses": 0, "sets": 0}

    @staticmethod
    def _stable_value(value):
        """Return a deterministic, JSON-safe representation for cache keys."""
        if isinstance(value, dict):
            return {
                str(key): CacheService._stable_value(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(value, (list, tuple)):
            return [CacheService._stable_value(item) for item in value]
        if isinstance(value, set):
            return sorted(CacheService._stable_value(item) for item in value)
        return value

    @classmethod
    def make_key(cls, namespace, *args, **kwargs):
        payload = {
            "args": cls._stable_value(args),
            "kwargs": cls._stable_value(kwargs),
        }
        encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        prefix = current_app.config.get('CACHE_KEY_PREFIX', 'vykone:')
        return f"{prefix}{namespace}:{digest}"

    @staticmethod
    def memoize(timeout: int = 300):
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                cache = CacheService.get_cache()
                namespace = f"memoize:{func.__module__}.{func.__qualname__}"
                cache_key = CacheService.make_key(namespace, *args, **kwargs)
                cached = cache.get(cache_key)
                if cached is not None:
                    return cached
                result = func(*args, **kwargs)
                cache.set(cache_key, result, timeout=timeout)
                return result
            return wrapper
        return decorator

    @staticmethod
    def invalidate_pattern(pattern: str):
        """Best-effort compatibility helper for local SimpleCache only.

        New code should use ``bump_version``. Redis does not expose its key
        store safely, so pattern invalidation cannot be portable.
        """
        cache = CacheService.get_cache()
        try:
            backend = getattr(cache, "cache", None)
            if hasattr(backend, '_cache'):
                keys_to_delete = [k for k in backend._cache if pattern in str(k)]
                for k in keys_to_delete:
                    cache.delete(k)
        except Exception:
            pass

    @classmethod
    def version_key(cls, company_id, sandbox, domain):
        return cls.make_key("version", company_id, bool(sandbox), domain)

    @classmethod
    def get_version(cls, company_id, sandbox, domain):
        return int(cls.get_cache().get(cls.version_key(company_id, sandbox, domain)) or 0)

    @classmethod
    def bump_version(cls, company_id, sandbox, domain):
        key = cls.version_key(company_id, sandbox, domain)
        # SimpleCache and Redis both support get/set, keeping this helper
        # backend-agnostic. Concurrent bumps may coalesce, which is safe:
        # every existing value remains expired when the version changes.
        version = cls.get_version(company_id, sandbox, domain) + 1
        timeout = current_app.config.get('CACHE_VERSION_TIMEOUT', 86400)
        cls.get_cache().set(key, version, timeout=timeout)
        return version

    @classmethod
    def domain_key(cls, domain, company_id, sandbox, *args, **kwargs):
        version = cls.get_version(company_id, sandbox, domain)
        return cls.make_key(
            f"domain:{domain}", company_id, bool(sandbox), version, *args, **kwargs
        )

    @staticmethod
    def request_get(key):
        if not has_request_context():
            return None
        return getattr(g, "_vykone_request_cache", {}).get(key)

    @staticmethod
    def request_set(key, value):
        if has_request_context():
            store = getattr(g, "_vykone_request_cache", None)
            if store is None:
                store = {}
                g._vykone_request_cache = store
            store[key] = value
        return value

    @classmethod
    def get_or_set_request(cls, key, factory):
        marker = object()
        value = cls.request_get(key)
        if value is not None:
            return value
        result = factory()
        return cls.request_set(key, result)

    @classmethod
    def invalidate_hr(cls, company_id, sandbox=True, payroll=False):
        if company_id:
            cls.bump_version(company_id, sandbox, "hr")
            if payroll:
                cls.bump_version(company_id, sandbox, "payroll")

    @classmethod
    def invalidate_audit(cls, company_id, sandbox=True):
        if company_id:
            cls.bump_version(company_id, sandbox, "audit")

    @classmethod
    def invalidate_production_agreement(cls, company_id, user_id=None, sandbox=False):
        """Invalida el dominio de contrato de producción para una compañía.

        El dominio se versiona por ambiente (producción o sandbox), de modo que
        una aceptación en sandbox no invalide indebidamente la decisión de
        producción y viceversa.
        """
        if company_id:
            cls.bump_version(company_id, bool(sandbox), "production_agreement")

    @classmethod
    def invalidate_production_agreement_global(cls):
        """Invalida el puntero global de la versión activa del contrato."""
        cls.bump_version("__global__", False, "production_agreement_global")

    @staticmethod
    def invalidate_dashboard(owner_uid: str, company_id=None):
        CacheService.invalidate_pattern("web_dashboard.dashboard")
        if company_id:
            CacheService.bump_version(company_id, True, "sales")

    @staticmethod
    def invalidate_accounting(owner_uid: str, company_id=None):
        CacheService.invalidate_pattern("web_accounting")
        if company_id:
            CacheService.bump_version(company_id, True, "accounting")

    @staticmethod
    def invalidate_reports(owner_uid: str, company_id=None):
        CacheService.invalidate_pattern("reports_sales")
        if company_id:
            CacheService.bump_version(company_id, True, "sales")
