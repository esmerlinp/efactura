"""Tests para la importación masiva de clientes (asistente de mapeo inteligente).

Cubre la definición de campos (requeridos + sinónimos), la detección de
delimitador y los helpers de saneamiento/parseo usados al procesar cada fila.
"""

import pytest

from app.web import clients_import as ci


# ═══════════════════════════════════════════════════════════════════════════
# Definición de campos
# ═══════════════════════════════════════════════════════════════════════════

def test_campos_requeridos_son_razon_social_y_rnc():
    required = ci.CLIENT_REQUIRED_FIELDS
    assert "razonSocial" in required
    assert "rnc" in required
    # Nada más es obligatorio para poder importar un cliente.
    assert required == ["razonSocial", "rnc"]


def test_target_fields_tienen_sinonimos_para_mapeo_inteligente():
    ids = {f["id"] for f in ci.CLIENT_TARGET_FIELDS}
    assert "razonSocial" in ids
    assert "rnc" in ids
    assert "email" in ids
    assert "pipelineStage" in ids

    for f in ci.CLIENT_TARGET_FIELDS:
        assert isinstance(f["suggestions"], list)
        assert f["suggestions"], f"El campo {f['id']} no tiene sinónimos"
        assert "required" in f


def test_headers_ejemplo_coinciden_en_longitud():
    assert len(ci.CLIENT_CSV_HEADERS) == len(ci.CLIENT_EXAMPLE_ROW)
    assert len(ci.CLIENT_CSV_HEADERS) == len(ci.CLIENT_CSV_FIELDS)


def test_rutas_registradas_en_blueprint(app):
    rules = {r.rule for r in app.url_map.iter_rules()}
    expected = [
        "/clients/import",
        "/clients/import/template",
        "/clients/import/upload",
        "/clients/import/ai-suggest",
        "/clients/import/process",
        "/clients/import/status/<job_id>",
    ]
    for rule in expected:
        assert rule in rules, f"Falta la ruta {rule}"


# ═══════════════════════════════════════════════════════════════════════════
# Detección de delimitador
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("line,expected", [
    ("razonSocial;rnc;email", ";"),
    ("razonSocial\trnc\temail", "\t"),
    ("razonSocial,rnc,email", ","),
    ("razonSocial|rnc|email", ","),  # sin delimitador conocido → coma por defecto
])
def test_get_delimiter(line, expected):
    assert ci._get_delimiter(line) == expected


# ═══════════════════════════════════════════════════════════════════════════
# Saneamiento numérico
# ═══════════════════════════════════════════════════════════════════════════

def test_sanitize_float_import_variantes():
    assert ci._sanitize_float_import("50000") == 50000.0
    assert ci._sanitize_float_import("1,234.56") == 1234.56
    assert ci._sanitize_float_import("1234,56") == 1234.56
    assert ci._sanitize_float_import("RD$ 5000") == 5000.0
    assert ci._sanitize_float_import("") == 0.0
    assert ci._sanitize_float_import("abc", 7.0) == 7.0


# ═══════════════════════════════════════════════════════════════════════════
# Normalización de fechas
# ═══════════════════════════════════════════════════════════════════════════

def test_normalize_date_formato_comun():
    assert ci._normalize_date("15/01/2026") == "2026-01-15"
    assert ci._normalize_date("2026-01-15") == "2026-01-15"
    assert ci._normalize_date("15-01-2026") == "2026-01-15"
    assert ci._normalize_date("") == ""


def test_normalize_date_con_hora_y_fecha_invalida():
    assert ci._normalize_date("2026-01-15 10:30:00") == "2026-01-15"
    assert ci._normalize_date("no-es-fecha") == "no-es-fecha"
