from pathlib import Path


def test_pilot_runbook_keeps_activation_manual_and_safe():
    path = Path(__file__).parents[1] / "docs" / "recurring-contracts-phase-9-5-pilot-runbook.md"
    text = path.read_text(encoding="utf-8")
    assert "PENDIENTE DE SELECCIÓN" in text
    assert "No se ha seleccionado una compañía piloto" in text
    assert "No iniciar nuevos workers" in text
    assert "No se ejecuta durante esta fase" in text
    assert "no consiste simplemente en cambiar el flag a `false`" in text
