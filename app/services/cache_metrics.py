"""Small in-process cache metrics endpoint helpers."""

from app.services.cache_service import CacheService


def get_cache_metrics():
    stats = CacheService.stats()
    lookups = stats["hits"] + stats["misses"]
    stats["hit_rate"] = round(stats["hits"] / lookups, 4) if lookups else 0.0
    return stats
