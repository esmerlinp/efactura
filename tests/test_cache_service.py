import pytest

from app.services.cache_service import CacheService


def test_make_key_is_stable_for_dict_order(app):
    with app.app_context():
        first = CacheService.make_key("report", {"b": 2, "a": 1})
        second = CacheService.make_key("report", {"a": 1, "b": 2})

    assert first == second


def test_make_key_separates_company_and_environment(app):
    with app.app_context():
        sandbox = CacheService.domain_key("hr", "company-a", True, "employees")
        production = CacheService.domain_key("hr", "company-a", False, "employees")
        other_company = CacheService.domain_key("hr", "company-b", True, "employees")

    assert sandbox != production
    assert sandbox != other_company


def test_request_cache_is_scoped_to_request(app):
    with app.test_request_context("/"):
        key = "test-key"
        assert CacheService.request_get(key) is None
        CacheService.request_set(key, {"value": 1})
        assert CacheService.request_get(key) == {"value": 1}

    with app.test_request_context("/"):
        assert CacheService.request_get(key) is None


def test_bump_version_changes_domain_key(app):
    with app.app_context():
        before = CacheService.domain_key("sales", "company-a", True, "month")
        CacheService.bump_version("company-a", True, "sales")
        after = CacheService.domain_key("sales", "company-a", True, "month")

    assert before != after
