"""Motor de cálculo IT-1 histórico, separado de HTTP y Firestore."""

from app.fiscal_forms.common import money


def positive(value):
    return max(money(value), money(0))


def proportionality_coefficient(casilla_1, casilla_2, casilla_5, casilla_10):
    total = money(casilla_1)
    if total == 0:
        return money(0)
    return ((money(casilla_2) + money(casilla_5) + money(casilla_10)) / total * 100).quantize(money("0.01"))


def proportionality_admitted(casilla_53, coefficient):
    return (money(casilla_53) * money(coefficient) / 100).quantize(money("0.01"))


def calculate_annex_a(data):
    values = {int(k): money(v) for k, v in (data.get("values") or {}).items()}
    result = dict(values)
    result[11] = values.get(1, 0) + values.get(2, 0) + values.get(3, 0) - values.get(4, 0) + values.get(5, 0) + values.get(6, 0) + values.get(7, 0) + values.get(8, 0) + values.get(9, 0) - values.get(10, 0)
    result[19] = sum((values.get(i, 0) for i in range(12, 19)), money(0))
    result[26] = sum((values.get(i, 0) for i in range(20, 26)), money(0))
    result[33] = sum((values.get(i, 0) for i in range(27, 33)), money(0))
    result[48] = sum((values.get(i, 0) for i in (45, 46, 47)), money(0))
    result[52] = sum((values.get(i, 0) for i in (49, 50, 51)), money(0))
    coefficient = proportionality_coefficient(data.get("it1_casilla_1", 0), data.get("it1_casilla_2", 0), data.get("it1_casilla_5", 0), data.get("it1_casilla_10", 0))
    result[54] = coefficient
    result[55] = proportionality_admitted(values.get(53, 0), coefficient)
    result[56] = result[52] + result[55]
    return result


def calculate_it1(data):
    values = {int(k): money(v) for k, v in (data.get("values") or {}).items()}
    result = dict(values)
    result[9] = sum((values.get(i, 0) for i in range(2, 9)), money(0))
    result[10] = values.get(1, 0) - result[9]
    result[16] = values.get(11, 0) * money("0.18")
    result[17] = values.get(12, 0) * money("0.16")
    result[18] = values.get(13, 0) * money("0.09")
    result[19] = values.get(14, 0) * money("0.08")
    result[20] = values.get(15, 0) * money("0.18")
    result[21] = sum((result.get(i, 0) for i in range(16, 21)), money(0))
    result[25] = sum((values.get(i, 0) for i in range(22, 25)), money(0))
    result[26] = positive(result[21] - result[25])
    result[27] = positive(result[25] - result[21])
    result[33] = positive(result[26] - sum((values.get(i, 0) for i in range(28, 33)), money(0)))
    result[34] = positive(sum((values.get(i, 0) for i in range(28, 33)), money(0)) - result[26]) if result[26] else result[27] + sum((values.get(i, 0) for i in range(28, 33)), money(0))
    result[38] = result[33] + values.get(35, 0) + values.get(36, 0) + values.get(37, 0)
    result[42] = values.get(40, 0) + values.get(41, 0)
    result[46] = values.get(44, 0) + values.get(45, 0)
    result[49] = values.get(47, 0) + values.get(48, 0)
    result[50] = values.get(41, 0) * money("0.18")
    result[51] = values.get(42, 0) * money("0.18")
    result[52] = values.get(43, 0) * money("0.18") * money("0.30")
    result[55] = values.get(53, 0) + values.get(54, 0)
    result[58] = values.get(56, 0) + values.get(57, 0)
    result[60] = result[50] + result[51] + result[52] + result[55] + result[58] + values.get(59, 0)
    result[62] = positive(result[60] - values.get(61, 0))
    result[63] = positive(values.get(61, 0) - result[60])
    return result
