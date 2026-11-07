from pathlib import Path


def test_pos_uses_final_dgii_status_after_polling():
    source = Path("app/web/pos.py").read_text(encoding="utf-8")
    assert 'dgii_status = str(res.get("dgiiStatus") or "").upper()' in source
    assert 'dgii_status in ("ACCEPTED", "ACCEPTED_PREVIOUSLY")' in source
    assert 'res.get("status") == "PENDING" or res.get("mode") == "FALLBACK"' not in source
