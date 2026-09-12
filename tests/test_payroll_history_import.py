"""Tests para la importación de histórico de nómina (por cédula)."""

from datetime import datetime, timezone
from unittest.mock import patch

from app.web.rrhh.payroll_history_import import (
    build_import_transactions,
    _build_line_from_transactions,
    _normalize_period,
    _normalize_cedula,
    _sanitize_float_import,
    get_imported_period_summaries,
    _split_period_key,
    _period_range_label,
    HISTORY_CSV_HEADERS,
    HISTORY_EXAMPLE_ROWS,
    HISTORY_CONCEPT_MAP,
)
from app.services.liquidacion_service import LiquidacionService


# ── Normalización de período y cédula ───────────────────────────────────────

def test_normalize_period_mensual():
    key, year = _normalize_period("2026-07")
    assert key == "2026-07-M"
    assert year == 2026


def test_normalize_period_con_slash():
    key, year = _normalize_period("2026/07")
    assert key == "2026-07-M"
    assert year == 2026


def test_normalize_period_fecha_completa():
    key, year = _normalize_period("2026-07-15")
    assert key == "2026-07-15"
    assert year == 2026


def test_normalize_period_quincenal_q1():
    key, year = _normalize_period("2026-07-1")
    assert key == "2026-07-1"
    assert year == 2026


def test_normalize_period_quincenal_q2():
    key, year = _normalize_period("2026-07-2")
    assert key == "2026-07-2"
    assert year == 2026


def test_normalize_period_mensual_explicito():
    assert _normalize_period("2026-07-M") == ("2026-07-M", 2026)
    assert _normalize_period("2026-07-m") == ("2026-07-M", 2026)


def test_normalize_period_invalido():
    assert _normalize_period("") is None
    assert _normalize_period("abc") is None
    assert _normalize_period("2026-13") is None
    assert _normalize_period("2026-00") is None
    assert _normalize_period("2026-07-3") is None
    assert _normalize_period("2026-13-1") is None


def test_normalize_cedula_sin_guiones():
    assert _normalize_cedula("402-1234567-8") == "40212345678"
    assert _normalize_cedula(" 40212345678 ") == "40212345678"


def test_sanitize_float_variantes():
    assert _sanitize_float_import("5,000.00") == 5000.0
    assert _sanitize_float_import("1500,50") == 1500.5
    assert _sanitize_float_import("RD$ 3,000.00") == 3000.0
    assert _sanitize_float_import("") == 0.0
    assert _sanitize_float_import(None) == 0.0
    assert _sanitize_float_import("abc") == 0.0


# ── Construcción de transacciones ───────────────────────────────────────────

def _emp(emp_id="E1", contract_id=""):
    e = {"id": emp_id}
    if contract_id:
        e["currentEmploymentContractId"] = contract_id
    return e


def test_build_transactions_mapea_conceptos():
    values = {
        "cedula": "40212345678",
        "periodo": "2026-07",
        "salario_base": "35000",
        "afp_empleado": "1004.50",
        "isr": "0",
        "comision": "0",
    }
    txs = build_import_transactions(
        _emp(), "", "2026-07-M", 2026, values, {}, "now")
    codes = {t["conceptCode"] for t in txs}
    assert codes == {"SALARIO_BASE", "AFP_EMPLEADO"}
    sal = next(t for t in txs if t["conceptCode"] == "SALARIO_BASE")
    assert sal["amount"] == 35000.0
    assert sal["type"] == "earning"
    assert sal["source"] == "import"
    assert sal["status"] == "applied"
    assert sal["periodKey"] == "2026-07-M"
    assert sal["periodYear"] == 2026
    assert sal["conceptSnapshot"]["affectsTSS"] is True
    assert sal["conceptSnapshot"]["affectsISR"] is True
    afp = next(t for t in txs if t["conceptCode"] == "AFP_EMPLEADO")
    assert afp["type"] == "deduction"


def test_build_transactions_regalia_no_cotiza_tss():
    values = {"regalia_pascual": "25000"}
    txs = build_import_transactions(_emp(), "", "2026-12-M", 2026, values, {}, "now")
    assert len(txs) == 1
    assert txs[0]["conceptCode"] == "REGALIA_PASCUAL"
    assert txs[0]["conceptSnapshot"]["affectsTSS"] is False
    assert txs[0]["conceptSnapshot"]["affectsISR"] is False


def test_build_transactions_sin_montos_devuelve_vacio():
    txs = build_import_transactions(_emp(), "", "2026-07-M", 2026, {}, {}, "now")
    assert txs == []


def test_build_transactions_usa_contrato_del_empleado():
    values = {"salario_base": "35000"}
    txs = build_import_transactions(_emp(contract_id="C9"), "C9", "2026-07-M", 2026, values, {}, "now")
    assert all(t["contractId"] == "C9" for t in txs)


def test_build_transactions_usa_concepto_real_si_existe():
    concept = {
        "code": "SALARIO_BASE", "name": "Salario base", "type": "earning",
        "category": "fixed", "affects_sfs": True, "affects_isr": True,
        "affects_afp": True, "isLegalMandatory": False,
        "account_debit": "6.2.1.01", "account_credit": "2.1.2.1.02",
    }
    concepts_by_code = {"SALARIO_BASE": concept}
    values = {"salario_base": "35000"}
    txs = build_import_transactions(_emp(), "", "2026-07-M", 2026, values, concepts_by_code, "now")
    snap = txs[0]["conceptSnapshot"]
    assert snap["code"] == "SALARIO_BASE"
    assert snap["affectsTSS"] is True


# ── El histórico importado alimenta la liquidación (SDP) ────────────────────

def test_liquidacion_usa_transacciones_importadas():
    now = datetime.now(timezone.utc).isoformat()
    txs = []
    for month in range(1, 7):
        values = {"salario_base": "45000"}
        txs += build_import_transactions(
            _emp(), "", f"2025-{month:02d}-M", 2025, values, {}, now)
    prom = LiquidacionService.calcular_salario_promedio_mensual(txs)
    assert prom["promedio_mensual"] == 45000.0
    assert prom["months"] == 6


# ── Construcción de línea sintética para YTD ────────────────────────────────

def test_build_line_from_transactions_suma_por_tipo():
    txs = [
        {"conceptCode": "SALARIO_BASE", "type": "earning", "amount": 35000.0},
        {"conceptCode": "AFP_EMPLEADO", "type": "deduction", "amount": 1004.50},
        {"conceptCode": "SFS_EMPLEADO", "type": "deduction", "amount": 1064.0},
        {"conceptCode": "ISR_RETENCION", "type": "deduction", "amount": 100.0},
        {"conceptCode": "AFP_EMPLEADOR", "type": "employer_contrib", "amount": 2485.0},
    ]
    line = _build_line_from_transactions(txs)
    assert line["totalIncome"] == 35000.0
    assert line["afpEmployee"] == 1004.5
    assert line["sfsEmployee"] == 1064.0
    assert line["isrRetention"] == 100.0
    assert line["netSalary"] == 35000.0 - (1004.5 + 1064.0 + 100.0)
    assert line["afpEmployer"] == 2485.0
    assert line["totalEmployerContrib"] == 2485.0
    assert len(line["transactionSummary"]) == 5


# ── Plantilla ───────────────────────────────────────────────────────────────

def test_headers_de_plantilla_incluyen_cedula_y_periodo():
    assert "*cedula" in HISTORY_CSV_HEADERS
    assert "*periodo" in HISTORY_CSV_HEADERS
    assert "salario_base" in HISTORY_CSV_HEADERS
    assert set(HISTORY_CONCEPT_MAP.keys()) <= set(h.strip("*") for h in HISTORY_CSV_HEADERS)


def test_filas_de_ejemplo_alineadas_con_headers():
    n = len(HISTORY_CSV_HEADERS)
    assert all(len(r) == n for r in HISTORY_EXAMPLE_ROWS)
    periodos = [r[1] for r in HISTORY_EXAMPLE_ROWS]
    assert "2026-07" in periodos
    assert "2026-07-1" in periodos
    assert "2026-07-2" in periodos


# ── Resúmenes de período importados (para Historial/Dashboard) ──────────────

def test_split_period_key():
    assert _split_period_key("2026-07-M") == (2026, 7, "M")
    assert _split_period_key("2026-07-1") == (2026, 7, "1")
    assert _split_period_key("2026-07-2") == (2026, 7, "2")
    assert _split_period_key("basura") == (0, 0, "")


def test_period_range_label():
    assert _period_range_label("2026-07-M", 2026, 7, "M") == "Jul 2026"
    assert _period_range_label("2026-07-1", 2026, 7, "1") == "Q1: 1 Jul - 15 Jul 2026"
    assert _period_range_label("2026-07-2", 2026, 7, "2") == "Q2: 16 Jul - 31 Jul 2026"


class _FakeDoc:
    def __init__(self, data):
        self._data = data
        self.id = data.get("id", "doc")

    def to_dict(self):
        return self._data


class _FakeQuery:
    def __init__(self, docs):
        self._docs = docs

    def where(self, *a, **k):
        return self

    def get(self):
        return self._docs


class _FakeColl:
    def __init__(self, docs):
        self._docs = docs

    def where(self, *a, **k):
        return _FakeQuery(self._docs)


class _FakeDB:
    def __init__(self, docs):
        self._docs = docs

    def collection(self, path):
        return _FakeColl(self._docs)


def _tx(concept, ttype, amount, period_key, emp="E1", status="applied"):
    return {
        "employeeId": emp, "conceptCode": concept, "type": ttype,
        "amount": amount, "periodKey": period_key, "periodYear": int(period_key[:4]),
        "status": status, "source": "import",
    }


def test_get_imported_period_summaries_agrupa_y_suma():
    txs = [
        _tx("SALARIO_BASE", "earning", 35000.0, "2026-07-M"),
        _tx("AFP_EMPLEADO", "deduction", 1004.5, "2026-07-M"),
        _tx("SFS_EMPLEADO", "deduction", 1064.0, "2026-07-M"),
        _tx("ISR_RETENCION", "deduction", 100.0, "2026-07-M"),
        _tx("AFP_EMPLEADOR", "employer_contrib", 2485.0, "2026-07-M"),
        _tx("SALARIO_BASE", "earning", 17500.0, "2026-07-1"),
        _tx("SALARIO_BASE", "earning", 17500.0, "2026-07-2"),
    ]
    fake_db = _FakeDB([_FakeDoc(t) for t in txs])
    with patch("app.services.db_service.firebase_initialized", True), \
         patch("app.services.db_service.db_firestore", fake_db):
        summaries = get_imported_period_summaries("C1", sandbox=True)

    by_key = {s["periodKey"]: s for s in summaries}
    assert set(by_key) == {"2026-07-M", "2026-07-1", "2026-07-2"}

    mensual = by_key["2026-07-M"]
    assert mensual["totalGross"] == 35000.0
    assert mensual["totalIsr"] == 100.0
    assert mensual["totalTssEmployee"] == 1004.5 + 1064.0
    assert mensual["totalEmployerContrib"] == 2485.0
    assert mensual["totalTssEmployer"] == 2485.0
    assert mensual["totalNet"] == 35000.0 - (1004.5 + 1064.0 + 100.0)
    assert mensual["lineCount"] == 1
    assert mensual["status"] == "importado"
    assert mensual["source"] == "import"
    assert mensual["periodType"] == "mensual"

    assert by_key["2026-07-1"]["periodType"] == "quincenal"
    assert by_key["2026-07-1"]["totalGross"] == 17500.0


def test_get_imported_period_summaries_sin_firestore_devuelve_vacio():
    with patch("app.services.db_service.firebase_initialized", False):
        assert get_imported_period_summaries("C1", sandbox=True) == []


def test_get_imported_period_summaries_line_count_empleados_distintos():
    txs = [
        _tx("SALARIO_BASE", "earning", 20000.0, "2026-06-M", emp="E1"),
        _tx("SALARIO_BASE", "earning", 30000.0, "2026-06-M", emp="E2"),
    ]
    fake_db = _FakeDB([_FakeDoc(t) for t in txs])
    with patch("app.services.db_service.firebase_initialized", True), \
         patch("app.services.db_service.db_firestore", fake_db):
        summaries = get_imported_period_summaries("C1", sandbox=True)
    assert summaries[0]["lineCount"] == 2
    assert summaries[0]["totalGross"] == 50000.0
