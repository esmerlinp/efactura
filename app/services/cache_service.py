from functools import wraps
from flask import current_app as app


class CacheService:
    _cache = None

    @classmethod
    def get_cache(cls):
        if cls._cache is None:
            from flask_caching import Cache
            cls._cache = Cache(config={
                'CACHE_TYPE': 'SimpleCache',
                'CACHE_DEFAULT_TIMEOUT': 300,
            })
            cls._cache.init_app(app)
        return cls._cache

    @staticmethod
    def memoize(timeout: int = 300):
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                cache = CacheService.get_cache()
                cache_key = f"{func.__module__}.{func.__qualname__}:{str(args)}:{str(sorted(kwargs.items()))}"
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
        cache = CacheService.get_cache()
        try:
            if hasattr(cache.cache, '_cache'):
                keys_to_delete = [k for k in cache.cache._cache if pattern in str(k)]
                for k in keys_to_delete:
                    cache.delete(k)
        except Exception:
            pass

    @staticmethod
    def invalidate_dashboard(owner_uid: str):
        CacheService.invalidate_pattern("web_dashboard.dashboard")
        CacheService.invalidate_pattern(f"ownerUID': '{owner_uid}'")

    @staticmethod
    def invalidate_accounting(owner_uid: str):
        CacheService.invalidate_pattern("web_accounting")
        CacheService.invalidate_pattern(f"ownerUID': '{owner_uid}'")

    @staticmethod
    def invalidate_reports(owner_uid: str):
        CacheService.invalidate_pattern("reports_sales")
        CacheService.invalidate_pattern(f"ownerUID': '{owner_uid}'")
