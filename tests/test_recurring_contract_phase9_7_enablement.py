from pathlib import Path


def test_enablement_document_does_not_authorize_or_store_secrets():
    text = (Path(__file__).parents[1] / "docs" / "recurring-contracts-phase-9-7-pilot-enablement.md").read_text(encoding="utf-8")
    assert "PENDIENTE" in text
    assert "contraseña" in text
    assert "nunca escrita" in text
    assert "No seleccionar" not in text or "No selecciona" in text
    assert "Producción queda fuera del alcance" in text
