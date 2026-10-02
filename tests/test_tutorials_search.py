import os
import tempfile

import pytest

from app.services import tutorials


@pytest.fixture
def sample_dir():
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "facturacion"), exist_ok=True)
        os.makedirs(os.path.join(tmp, "rrhh"), exist_ok=True)

        with open(os.path.join(tmp, "facturacion", "01-e32.md"), "w", encoding="utf-8") as fh:
            fh.write(
                "# Tutorial: Factura de consumidor final (E32)\n\n"
                "La factura de Consumo (E32) se usa para ventas al público.\n\n"
                "## Crear la factura\n\n"
                "1. Abre **Ingresos** y haz clic en **Facturas de Venta**.\n"
                "2. Elige **E32 — Factura de Consumo**.\n\n"
                "## Emitir la factura\n\n"
                "1. Revisa los totales.\n"
                "2. Haz clic en **Emitir Documento**.\n"
            )

        with open(os.path.join(tmp, "rrhh", "03-nomina.md"), "w", encoding="utf-8") as fh:
            fh.write(
                "# Tutorial: Procesar nómina\n\n"
                "Procesar la nómina calcula ingresos, deducciones e ISR.\n\n"
                "## Crear un período de nómina\n\n"
                "1. Abre **Nómina** y haz clic en **Procesar nómina**.\n"
            )

        yield tmp


def test_parse_and_chunk(sample_dir, monkeypatch):
    monkeypatch.setattr(tutorials, "TUTORIALS_DIR", sample_dir)
    monkeypatch.setattr(tutorials, "INDEX_PATH", os.path.join(sample_dir, ".index.json"))

    path = os.path.join(sample_dir, "facturacion", "01-e32.md")
    doc = tutorials.parse_tutorial(path)
    assert doc["title"] == "Tutorial: Factura de consumidor final (E32)"
    assert doc["module"] == "facturacion"

    chunks = tutorials.chunk_tutorial(doc)
    headings = [c["heading"] for c in chunks]
    assert "Crear la factura" in headings
    assert "Emitir la factura" in headings
    assert all(c["title"] == doc["title"] for c in chunks)


def test_keyword_search_no_embeddings(sample_dir, monkeypatch):
    monkeypatch.setattr(tutorials, "TUTORIALS_DIR", sample_dir)
    monkeypatch.setattr(tutorials, "INDEX_PATH", os.path.join(sample_dir, ".index.json"))
    monkeypatch.setattr(tutorials, "_instance", None)

    result = tutorials.search_tutorials("procesar nomina", top_k=3)
    assert result["results"], result
    top = result["results"][0]
    assert "Procesar nómina" in top["titulo"]
    assert top["modulo"] == "rrhh"


def test_search_filtered_by_module(sample_dir, monkeypatch):
    monkeypatch.setattr(tutorials, "TUTORIALS_DIR", sample_dir)
    monkeypatch.setattr(tutorials, "INDEX_PATH", os.path.join(sample_dir, ".index.json"))
    monkeypatch.setattr(tutorials, "_instance", None)

    result = tutorials.search_tutorials("emitir factura", module="facturacion", top_k=3)
    assert result["results"]
    assert all(r["modulo"] == "facturacion" for r in result["results"])


def test_search_returns_relevancia_field(sample_dir, monkeypatch):
    monkeypatch.setattr(tutorials, "TUTORIALS_DIR", sample_dir)
    monkeypatch.setattr(tutorials, "INDEX_PATH", os.path.join(sample_dir, ".index.json"))
    monkeypatch.setattr(tutorials, "_instance", None)

    result = tutorials.search_tutorials("factura de consumo", top_k=3)
    for r in result["results"]:
        assert "relevancia" in r
        assert r["relevancia"] > 0


def test_cosine():
    assert tutorials._cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert tutorials._cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert tutorials._cosine([], [1.0]) == 0.0
    assert tutorials._cosine([0.0, 0.0], [0.0, 0.0]) == 0.0
