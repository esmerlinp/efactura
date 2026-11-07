from pathlib import Path


def test_pos_payload_preserves_selected_client_email():
    source = Path("static/js/pos.js").read_text(encoding="utf-8")
    assert 'clientEmail: state.client.email || ""' in source
    assert 'clientEmail: ephemeralClient ? state.client.email : ""' not in source
