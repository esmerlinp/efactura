from unittest.mock import patch


def _emission_res(status="PENDING", mode="API", track_id="track-1"):
    return {
        "success": True,
        "mode": mode,
        "status": status,
        "dgiiStatus": status,
        "trackId": track_id,
        "encf": "E310000000001",
    }


def test_pending_api_emission_resolves_accepted():
    from app.web.invoices import _resolve_pending_dgii_inline

    res = _emission_res()
    accepted = {"success": True, "dgiiStatus": "ACCEPTED", "trackId": "track-1"}

    with patch("app.web.invoices.DgiiDirectService.poll_status_until_terminal",
               return_value=accepted) as poll:
        out = _resolve_pending_dgii_inline({"companyRNC": "101000001"}, res, True, "inv-1")

    poll.assert_called_once()
    assert out["status"] == "ACCEPTED"
    assert out["dgiiStatus"] == "ACCEPTED"
    assert out["success"] is True


def test_pending_api_emission_resolves_rejected():
    from app.web.invoices import _resolve_pending_dgii_inline

    res = _emission_res()
    rejected = {
        "success": True,
        "dgiiStatus": "REJECTED",
        "trackId": "track-1",
        "mensajes": [{"valor": "cuadratura incorrecta"}],
    }

    with patch("app.web.invoices.DgiiDirectService.poll_status_until_terminal",
               return_value=rejected) as poll:
        out = _resolve_pending_dgii_inline({"companyRNC": "101000001"}, res, True, "inv-1")

    poll.assert_called_once()
    assert out["success"] is False
    assert out["dgiiStatus"] == "REJECTED"
    assert "cuadratura incorrecta" in out["message"]


def test_timeout_keeps_pending_untouched():
    from app.web.invoices import _resolve_pending_dgii_inline

    res = _emission_res()
    timeout = {"success": False, "dgiiStatus": "TIMEOUT", "trackId": "track-1"}

    with patch("app.web.invoices.DgiiDirectService.poll_status_until_terminal",
               return_value=timeout) as poll:
        out = _resolve_pending_dgii_inline({"companyRNC": "101000001"}, res, True, "inv-1")

    poll.assert_called_once()
    assert out["success"] is True
    assert out["status"] == "PENDING"


def test_fallback_or_missing_track_id_skips_poll():
    from app.web.invoices import _resolve_pending_dgii_inline

    with patch("app.web.invoices.DgiiDirectService.poll_status_until_terminal") as poll:
        _resolve_pending_dgii_inline({"companyRNC": "101000001"},
                                     _emission_res(mode="FALLBACK"), True, "inv-1")
        _resolve_pending_dgii_inline({"companyRNC": "101000001"},
                                     _emission_res(track_id=""), True, "inv-1")

    poll.assert_not_called()
