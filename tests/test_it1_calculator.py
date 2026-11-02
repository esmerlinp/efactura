from app.services.it1_calculator import calculate_annex_a, calculate_it1, proportionality_admitted, proportionality_coefficient


def test_proportionality_uses_official_it1_formula():
    coefficient = proportionality_coefficient("1000", "100", "200", "500")
    assert coefficient == 80
    assert proportionality_admitted("100", coefficient) == 80


def test_annex_a_totals_and_four_itbis_columns():
    result = calculate_annex_a({"values": {"1": "100", "2": "20", "3": "10", "4": "5", "45": "2", "46": "3", "47": "4", "49": "5", "50": "6", "51": "7", "53": "10"}, "it1_casilla_1": "1000", "it1_casilla_2": "100", "it1_casilla_5": "200", "it1_casilla_10": "500"})
    assert result[11] == 125
    assert result[48] == 9
    assert result[52] == 18
    assert result[55] == 8
    assert result[56] == 26


def test_it1_settlement_and_withholding_sections():
    result = calculate_it1({"values": {"1": "1000", "11": "1000", "22": "50", "40": "100", "41": "100", "43": "100", "44": "10", "45": "5", "47": "10", "48": "5", "61": "20"}})
    assert result[10] == 1000
    assert result[16] == 180
    assert result[25] == 50
    assert result[26] == 130
    assert result[38] == 130
    assert result[60] > 0
