from pathlib import Path


def test_sandbox_pilot_is_not_selected_or_activated():
    text = (Path(__file__).parents[1] / "docs" / "recurring-contracts-phase-9-6-sandbox-certification.md").read_text(encoding="utf-8")
    assert "PENDIENTE" in text
    assert "No se inventaron autorizaciones" in text
    assert "Feature flags productivos: sin cambios" in text
    assert "Comprobantes reales: ninguno emitido" in text
    assert "No existe certificado sandbox" in text
    assert "No se encontró secuencia sandbox autorizada" in text
