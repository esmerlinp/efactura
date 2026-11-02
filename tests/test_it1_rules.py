from pathlib import Path

from app.fiscal_forms.it1_rules import ANNEX_A_FORMULAS, ANNEX_A_SECTIONS, IT1_FORMULAS, IT1_RULES_VERSION, IT1_SECTIONS, validate_catalog_numbers


def test_historical_catalog_has_56_annex_and_63_it1_numbers():
    result = validate_catalog_numbers()
    assert result["annex_a_count"] == 56
    assert result["annex_a_numbers"] == tuple(range(1, 57))
    assert result["it1_count"] == 63
    assert result["it1_numbers"] == tuple(range(1, 64))
    assert IT1_RULES_VERSION.version == "2020"


def test_official_template_is_preserved():
    source = Path(__file__).parents[1] / "docs" / "IT-1-2020.xls"
    assert source.exists()
    assert source.stat().st_size > 100_000


def test_required_formula_documentation_exists():
    assert 48 in ANNEX_A_FORMULAS and 52 in ANNEX_A_FORMULAS and 55 in ANNEX_A_FORMULAS and 56 in ANNEX_A_FORMULAS
    assert all(number in IT1_FORMULAS for number in range(28, 35))
    assert all(number in IT1_FORMULAS for number in range(39, 64))
