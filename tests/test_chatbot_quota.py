"""Regresión del límite diario de 20 consultas del chatbot (cuota del servidor).

Cubren:
- El bloqueo se evalúa ANTES del FAQ cache y de llamar a OpenAI.
- Las preguntas FAQ también consumen cuota.
- Solo aplica con la key global (no con key propia de la empresa).
- Reset diario (fecha de reset distinta a hoy cuenta como 0).
- El endpoint /api/chatbot/usage refleja el conteo real.
"""
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from config import Config
from app.services.chatbot import ChatbotService, DAILY_LIMIT

GLOBAL_PROFILE = {"companyName": "Test SRL", "openaiApiKey": ""}
OWN_KEY_PROFILE = {"companyName": "Test SRL", "openaiApiKey": "sk-mia"}


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _openai_resp(text="Respuesta IA"):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"role": "assistant", "content": text}}]}
    return resp


@pytest.fixture
def global_key():
    with patch.object(Config, "OPENAI_API_KEY", "sk-global-test"):
        yield


def _ask(message, quota, bump_return=None, profile=None):
    """Ejecuta ask_chatbot con DatabaseService y requests.post mockeados.

    quota: tupla (count, reset) que devuelve get_chatbot_quota.
    bump_return: valor que retorna bump_chatbot_quota (default count+1).
    """
    profile = profile if profile is not None else GLOBAL_PROFILE
    if bump_return is None:
        bump_return = (quota[0] + 1) if quota else 1
    with patch("app.services.chatbot.DatabaseService.get_company_profile",
               return_value=profile), \
         patch("app.services.chatbot.DatabaseService.get_chatbot_quota",
               return_value=quota) as mock_quota, \
         patch("app.services.chatbot.DatabaseService.bump_chatbot_quota",
               return_value=bump_return) as mock_bump, \
         patch("app.services.chatbot.requests.post",
               return_value=_openai_resp()) as mock_post:
        result = ChatbotService.ask_chatbot("owner1", "user1", message, [])
    return result, mock_quota, mock_bump, mock_post


# ─── Bloqueo al llegar al límite ───

def test_blocked_at_limit_does_not_call_openai(global_key):
    result, mock_quota, mock_bump, mock_post = _ask(
        "¿cuánto he facturado este mes?", (DAILY_LIMIT, _today())
    )
    assert result["success"] is False
    assert "Límite" in result["message"]
    assert result["usage_info"] == {"used": DAILY_LIMIT, "limit": DAILY_LIMIT}
    mock_post.assert_not_called()
    mock_bump.assert_not_called()


def test_blocked_at_limit_applies_to_faq_cache(global_key):
    result, mock_quota, mock_bump, mock_post = _ask(
        "¿qué hago en caso de contingencia?", (DAILY_LIMIT, _today())
    )
    assert result["success"] is False
    assert "Límite" in result["message"]
    assert "source" not in result
    mock_post.assert_not_called()
    mock_bump.assert_not_called()


# ─── Consumo de cuota ───

def test_faq_answer_consumes_quota(global_key):
    result, mock_quota, mock_bump, mock_post = _ask(
        "¿qué hago en caso de contingencia?", (DAILY_LIMIT - 1, _today()),
        bump_return=DAILY_LIMIT,
    )
    assert result["success"] is True
    assert result["source"] == "cache"
    assert result["usage_info"] == {"used": DAILY_LIMIT, "limit": DAILY_LIMIT}
    mock_bump.assert_called_once()
    mock_post.assert_not_called()


def test_openai_answer_consumes_quota(global_key):
    result, mock_quota, mock_bump, mock_post = _ask(
        "¿cuánto he facturado este mes?", (DAILY_LIMIT - 1, _today()),
        bump_return=DAILY_LIMIT,
    )
    assert result["success"] is True
    assert result["message"] == "Respuesta IA"
    assert result["usage_info"] == {"used": DAILY_LIMIT, "limit": DAILY_LIMIT}
    mock_bump.assert_called_once()
    mock_post.assert_called_once()


def test_bump_failure_still_returns_answer(global_key):
    with patch("app.services.chatbot.DatabaseService.get_company_profile",
               return_value=GLOBAL_PROFILE), \
         patch("app.services.chatbot.DatabaseService.get_chatbot_quota",
               return_value=(1, _today())), \
         patch("app.services.chatbot.DatabaseService.bump_chatbot_quota",
               side_effect=Exception("firestore caído")), \
         patch("app.services.chatbot.requests.post",
               return_value=_openai_resp()):
        result = ChatbotService.ask_chatbot("owner1", "user1", "¿cuánto he facturado este mes?", [])
    assert result["success"] is True
    assert result["usage_info"] is None


# ─── Reset diario ───

def test_stale_reset_counts_as_zero(global_key):
    result, mock_quota, mock_bump, mock_post = _ask(
        "¿cuánto he facturado este mes?", (DAILY_LIMIT, "2020-01-01"),
        bump_return=1,
    )
    assert result["success"] is True
    assert result["usage_info"] == {"used": 1, "limit": DAILY_LIMIT}
    mock_bump.assert_called_once()
    mock_post.assert_called_once()


# ─── Key propia: sin cuota ───

def test_own_key_skips_quota(global_key):
    result, mock_quota, mock_bump, mock_post = _ask(
        "¿cuánto he facturado este mes?", (DAILY_LIMIT, _today()),
        profile=OWN_KEY_PROFILE,
    )
    assert result["success"] is True
    assert result["usage_info"] is None
    mock_quota.assert_not_called()
    mock_bump.assert_not_called()
    mock_post.assert_called_once()


def test_own_key_faq_unlimited(global_key):
    result, mock_quota, mock_bump, mock_post = _ask(
        "¿qué es el RST?", (DAILY_LIMIT, _today()),
        profile=OWN_KEY_PROFILE,
    )
    assert result["success"] is True
    assert result["source"] == "cache"
    assert result["usage_info"] is None
    mock_quota.assert_not_called()
    mock_bump.assert_not_called()


# ─── Endpoint /api/chatbot/usage ───

def _call_usage_api(app, profile, quota):
    """Invoca la vista del endpoint en un request context (evita el before_request global)."""
    from flask import session
    from app.web.invoices import chatbot_usage_api

    with app.test_request_context("/api/chatbot/usage", headers={"Accept": "application/json"}):
        session["user"] = {
            "uid": "u1",
            "ownerUID": "o1",
            "role": "owner",
            "email": "admin@test.com",
            "name": "Admin",
            "status": "active",
            "default_company_id": "c1",
            "permissions": {"canUseChatbot": True},
        }
        session["selected_company_id"] = "c1"
        session["company_modules"] = {"ia_bi": {"enabled": True}}

        with patch("app.web.invoices.DatabaseService.get_company_profile",
                   return_value=profile), \
             patch("app.web.invoices.DatabaseService.get_chatbot_quota",
                   return_value=quota) as mock_quota:
            return chatbot_usage_api().get_json(), mock_quota


def test_usage_endpoint_reflects_count(app):
    data, _ = _call_usage_api(app, GLOBAL_PROFILE, (7, _today()))
    assert data["usage_info"]["used"] == 7
    assert data["usage_info"]["limit"] == DAILY_LIMIT


def test_usage_endpoint_zero_when_stale_reset(app):
    data, _ = _call_usage_api(app, GLOBAL_PROFILE, (20, "2020-01-01"))
    assert data["usage_info"]["used"] == 0


def test_usage_endpoint_hidden_with_own_key(app):
    data, mock_quota = _call_usage_api(app, OWN_KEY_PROFILE, (20, _today()))
    assert data["usage_info"] is None
    mock_quota.assert_not_called()
