"""Tests del resolver de logo (app/utils/logo.py)."""

from app.utils.logo import resolve_logo_data_uri


class _CompanyContextLike:
    logo_url = ""
    logo_base64 = ""
    logo_storage_path = ""


def test_base64_raw():
    assert resolve_logo_data_uri({"logoBase64": "iVBORw0KGgo="}) == "data:image/png;base64,iVBORw0KGgo="


def test_base64_prefixed():
    src = "data:image/png;base64,iVBORw0KGgo="
    assert resolve_logo_data_uri({"logoBase64": src}) == src


def test_empty():
    assert resolve_logo_data_uri({}) == ""


def test_url_remote_fallback():
    # URL remota que falla al descargar → se devuelve la URL como último recurso
    assert resolve_logo_data_uri({"logoUrl": "https://x.invalid/y.png"}) == "https://x.invalid/y.png"


def test_object_snake_case_attrs():
    ctx = _CompanyContextLike()
    ctx.logo_base64 = "iVBORw0KGgo="
    assert resolve_logo_data_uri(ctx) == "data:image/png;base64,iVBORw0KGgo="
