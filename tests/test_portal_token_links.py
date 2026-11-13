"""Compatibilidad del token de portal entre el ERP y el portal global de clientes."""

from itsdangerous import URLSafeTimedSerializer

from app.utils.security import generate_portal_token, decode_portal_token, build_clients_portal_url


def _portal_serializer(app):
    secret = app.config.get("PORTAL_TOKEN_SECRET") or app.config["SECRET_KEY"]
    return URLSafeTimedSerializer(secret, salt="portal-access")


def test_erp_token_is_decodable_by_global_portal(app):
    with app.app_context():
        token = generate_portal_token("u1", "c1", sandbox=True, company_id="comp-1", doc_id="doc-1")
        data = _portal_serializer(app).loads(token, max_age=None)
    assert data["owner_uid"] == "u1"
    assert data["client_id"] == "c1"
    assert data["sandbox"] is True
    assert data["company_id"] == "comp-1"
    assert data["doc_id"] == "doc-1"


def test_erp_roundtrip_still_works(app):
    with app.app_context():
        token = generate_portal_token("u1", "c1", sandbox=False, company_id="comp-1")
        decoded = decode_portal_token(token)
    assert decoded["owner_uid"] == "u1"
    assert decoded["client_id"] == "c1"
    assert decoded["company_id"] == "comp-1"


def test_build_clients_portal_url_points_to_global_domain(app):
    with app.app_context():
        token = generate_portal_token("u1", "c1", sandbox=True, company_id="comp-1")
        url = build_clients_portal_url(token)
        base = (app.config.get("CLIENTS_PORTAL_BASE_URL") or "https://clientes.vykcore.com").rstrip("/")
    assert url.startswith(f"{base}/portal/p/")
    assert url.endswith(token)
