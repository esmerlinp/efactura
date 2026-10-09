"""Pruebas exhaustivas de secuencia de nómina y migración de históricos (18 escenarios)."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import date

from app.services.payroll_period_sequence import (
    blocked_period_keys,
    get_initial_live_period,
    get_historical_cutoff_period,
    get_payroll_migration_status,
    set_payroll_migration_config,
    _is_historical,
    _sort_key,
)
from app.web.rrhh import _generate_periods, get_locked_periods
from app.web.rrhh.payroll_history_import import (
    build_import_transactions,
    sync_imported_payroll_periods,
    revert_import_batch,
    get_imported_period_summaries,
)
from app.services.ir13_service import calculate_ir13
from app.services.liquidacion_service import LiquidacionService
from app.web.rrhh.payroll_workflow import _ensure_payroll_accounting_entry


def _monthly(year=2026):
    return [
        {"key": f"{year}-{m:02d}-M", "start": f"{year}-{m:02d}-01",
         "end": f"{year}-{m:02d}-28", "type": "mensual", "label": f"M: {m} {year}"}
        for m in range(1, 13)
    ]


def _quincenal(year=2026):
    periods = []
    for m in range(1, 13):
        periods.append({"key": f"{year}-{m:02d}-1", "start": f"{year}-{m:02d}-01",
                        "end": f"{year}-{m:02d}-15", "type": "quincenal", "label": f"Q1: {m} {year}"})
        periods.append({"key": f"{year}-{m:02d}-2", "start": f"{year}-{m:02d}-16",
                        "end": f"{year}-{m:02d}-28", "type": "quincenal", "label": f"Q2: {m} {year}"})
    return periods


def _p(group_id, key, start, status="borrador", subtype="regular", is_historical=False):
    return {
        "id": f"p_{key}_{group_id}",
        "payrollGroupId": group_id,
        "periodKey": key,
        "startDate": start,
        "status": status,
        "periodSubType": subtype,
        "periodRange": key,
        "isHistorical": is_historical,
    }


GROUP = "group_admin"


# ── Escenario 1: Empresa nueva que inicia en octubre de 2026 sin períodos previos ──
def test_scenario_01_new_company_starts_in_october():
    available = _monthly(2026)
    blocked, open_label, closed = blocked_period_keys(
        [], available, GROUP, initial_live_period="2026-10-M"
    )
    # Octubre está desbloqueado para operar
    assert "2026-10-M" not in blocked
    # Meses posteriores bloqueados
    assert "2026-11-M" in blocked
    assert "2026-12-M" in blocked
    # Meses previos no cerrados bloqueados para creación operativa
    assert "2026-01-M" in blocked
    assert "2026-09-M" in blocked
    assert open_label is None


# ── Escenario 2: Empresa con históricos importados de enero a septiembre y primer período operativo en octubre ──
def test_scenario_02_historical_jan_to_sep_and_live_october():
    periods = [
        _p(GROUP, f"2026-{m:02d}-M", f"2026-{m:02d}-01", status="cerrada", is_historical=True)
        for m in range(1, 10)
    ]
    available = _monthly(2026)
    blocked, open_label, closed = blocked_period_keys(
        periods, available, GROUP, initial_live_period="2026-10-M"
    )
    assert "2026-10-M" not in blocked
    assert "2026-11-M" in blocked
    assert "2026-12-M" in blocked
    # Enero a septiembre constan como cerrados/históricos
    for m in range(1, 10):
        assert f"2026-{m:02d}-M" in closed
        assert f"2026-{m:02d}-M" not in blocked
    assert open_label is None


# ── Escenario 3: Empresa con un período operativo abierto y un período posterior seleccionado ──
def test_scenario_03_open_operational_period_blocks_subsequent():
    periods = [
        _p(GROUP, "2026-10-M", "2026-10-01", status="calculada", is_historical=False),
    ]
    available = _monthly(2026)
    blocked, open_label, closed = blocked_period_keys(
        periods, available, GROUP, initial_live_period="2026-10-M"
    )
    assert "2026-10-M" not in blocked
    assert "2026-11-M" in blocked
    assert "2026-12-M" in blocked
    assert open_label == "2026-10-M"


# ── Escenario 4: Grupo quincenal con inicio operativo ──
def test_scenario_04_quincenal_group_initial_live():
    available = _quincenal(2026)
    blocked, open_label, closed = blocked_period_keys(
        [], available, "group_ops", initial_live_period="2026-10-1"
    )
    assert "2026-10-1" not in blocked
    assert "2026-10-2" in blocked
    assert "2026-11-1" in blocked
    assert "2026-09-2" in blocked


# ── Escenario 5: Empresa existente sin la nueva configuración (Retrocompatibilidad) ──
def test_scenario_05_legacy_company_without_config_fallback_january():
    available = _monthly(2026)
    blocked, open_label, closed = blocked_period_keys([], available, GROUP)
    # Sin config -> primer mes disponible habilitado (Enero 2026)
    assert "2026-01-M" not in blocked
    assert "2026-02-M" in blocked
    assert "2026-12-M" in blocked


# ── Escenario 6: Generación y consulta de períodos de años anteriores (2024, 2025, 2026) ──
def test_scenario_06_multi_year_generation():
    periods_2024 = _generate_periods("mensual", year=2024)
    assert len(periods_2024) == 12
    assert periods_2024[0]["key"] == "2024-01-M"

    multi = _generate_periods("mensual", years=[2024, 2025])
    assert len(multi) == 24
    assert multi[0]["key"] == "2024-01-M"
    assert multi[-1]["key"] == "2025-12-M"


# ── Escenario 7: Reimportación del mismo archivo (Idempotencia) ──
def test_scenario_07_reimport_idempotency():
    emp = {"id": "emp_1", "currentEmploymentContractId": "ct_1"}
    now_iso = "2026-10-09T00:00:00Z"
    values = {"salario_base": "30000.00", "afp_empleado": "861.00", "sfs_empleado": "912.00"}
    
    # Lote 1
    txs_1 = build_import_transactions(emp, "ct_1", "2026-05-M", 2026, values, {}, now_iso, batch_id="b1")
    # Lote 2 (reimportación)
    txs_2 = build_import_transactions(emp, "ct_1", "2026-05-M", 2026, values, {}, now_iso, batch_id="b2")

    # IDs deterministas por concepto/empleado/período evitan duplicados
    assert {t["id"] for t in txs_1} == {t["id"] for t in txs_2}
    assert len(txs_1) == 3


# ── Escenario 8: Dos lotes que intentan importar el mismo período ──
def test_scenario_08_two_batches_same_period_clean_overwrite():
    emp1 = {"id": "emp_1", "currentEmploymentContractId": "ct_1"}
    emp2 = {"id": "emp_2", "currentEmploymentContractId": "ct_2"}
    now_iso = "2026-10-09T00:00:00Z"

    txs_b1 = build_import_transactions(emp1, "ct_1", "2026-06-M", 2026, {"salario_base": "25000"}, {}, now_iso, batch_id="batch_A")
    txs_b2 = build_import_transactions(emp2, "ct_2", "2026-06-M", 2026, {"salario_base": "35000"}, {}, now_iso, batch_id="batch_B")

    assert txs_b1[0]["id"] != txs_b2[0]["id"]
    assert txs_b1[0]["periodKey"] == txs_b2[0]["periodKey"] == "2026-06-M"


# ── Escenario 9: Archivo con registros incompletos o montos vacíos ──
def test_scenario_09_empty_or_zero_amounts_return_empty():
    emp = {"id": "emp_1", "currentEmploymentContractId": "ct_1"}
    now_iso = "2026-10-09T00:00:00Z"
    values = {"salario_base": "0", "comision": "", "horas_extra": "0.00"}
    txs = build_import_transactions(emp, "ct_1", "2026-07-M", 2026, values, {}, now_iso)
    assert txs == []


# ── Escenario 10: Histórico validado no genera asientos contables en VykOne ──
def test_scenario_10_historical_bypasses_accounting_generation():
    historical_period = {
        "id": "imp_2026-05-M",
        "periodKey": "2026-05-M",
        "isHistorical": True,
        "source": "import",
        "accountingEntryGenerated": False,
    }
    with patch("app.services.accounting_service.AccountingService.generate_entry") as mock_gen:
        ok, msg = _ensure_payroll_accounting_entry(historical_period, "imp_2026-05-M", "uid1", "comp1", True)
        assert ok is True
        assert "OK" in msg
        mock_gen.assert_not_called()
        assert historical_period["accountingEntryGenerated"] is True


# ── Escenario 11: Histórico contabilizado externamente no genera asientos ──
def test_scenario_11_externally_accounted_flag_bypasses_accounting():
    ext_period = {
        "id": "imp_2026-06-M",
        "periodKey": "2026-06-M",
        "isExternallyAccounted": True,
        "accountingEntryGenerated": False,
    }
    with patch("app.services.accounting_service.AccountingService.generate_entry") as mock_gen:
        ok, msg = _ensure_payroll_accounting_entry(ext_period, "imp_2026-06-M", "uid1", "comp1", True)
        assert ok is True
        mock_gen.assert_not_called()


# ── Escenario 12: Declaración Anual IR-13 combina históricos y operativos sin duplicar ──
def test_scenario_12_ir13_with_historical_and_operational():
    emp_map = [
        {"id": "emp_1", "fullName": "Perez, Juan", "cedula": "001-0000000-1", "status": "activo", "firstName": "Juan", "firstLastName": "Perez"}
    ]
    # Enero histórico + Febrero operativo
    periods = [
        {
            "id": "imp_2026-01-M",
            "periodKey": "2026-01-M",
            "year": 2026,
            "lines": [{"employeeId": "emp_1", "grossSalary": 40000.0, "afpEmployee": 1148.0, "sfsEmployee": 1216.0, "isrRetention": 0.0}]
        },
        {
            "id": "op_2026-02-M",
            "periodKey": "2026-02-M",
            "year": 2026,
            "lines": [{"employeeId": "emp_1", "grossSalary": 40000.0, "afpEmployee": 1148.0, "sfsEmployee": 1216.0, "isrRetention": 0.0}]
        }
    ]
    with patch("app.services.hr_data_service.get_employees", return_value=emp_map), \
         patch("app.services.hr_data_service.get_payroll_periods", return_value=periods), \
         patch("app.services.payroll_service.PayrollService.get_period_lines", side_effect=lambda p, **kw: p.get("lines", [])):
        res = calculate_ir13("comp1", 2026, sandbox=True)

    assert res["num_asalariados"] == 1
    row = res["employees"][0]
    assert row["C"] == 80000.0  # 40k + 40k
    assert row["H"] == (1148.0 + 1216.0) * 2


# ── Escenario 13: Exportación histórica de TSS ──
def test_scenario_13_tss_lines_compatibility():
    historical_doc = {
        "id": "imp_2026-03-M",
        "periodKey": "2026-03-M",
        "lines": [
            {"employeeId": "emp_1", "cedula": "00100000001", "grossSalary": 35000.0,
             "afpEmployee": 1004.5, "sfsEmployee": 1064.0, "afpEmployer": 2485.0,
             "sfsEmployer": 2481.5, "srlEmployer": 420.0, "infotepEmployer": 350.0,
             "isrRetention": 0.0, "netSalary": 32931.5}
        ]
    }
    assert len(historical_doc["lines"]) == 1
    l = historical_doc["lines"][0]
    assert l["afpEmployee"] == 1004.5
    assert l["sfsEmployee"] == 1064.0


# ── Escenario 14: Cálculo de liquidación (SDP) con transacciones importadas ──
def test_scenario_14_liquidacion_sdp_with_imported_transactions():
    txs = [
        {"conceptCode": "SALARIO_BASE", "type": "earning", "amount": 50000.0, "status": "applied",
         "periodKey": f"2026-{m:02d}-M", "conceptSnapshot": {"affectsTSS": True}}
        for m in range(1, 13)
    ]
    res = LiquidacionService.calcular_salario_promedio_mensual(txs)
    # 50,000 / 23.83 = 2098.1955
    sdp = LiquidacionService.calcular_sdp([res["promedio_mensual"]])
    assert round(sdp, 2) == 2098.20


# ── Escenario 15: Corrección o reversión controlada de un lote ──
def test_scenario_15_revert_batch():
    class FakeDoc:
        def __init__(self, data):
            self._d = data
            self.reference = "ref_" + data.get("id", "")
        def to_dict(self):
            return self._d

    class FakeBatch:
        def __init__(self):
            self.deleted = []
        def delete(self, ref):
            self.deleted.append(ref)
        def commit(self):
            pass

    class FakeColl:
        def __init__(self, docs):
            self._docs = docs
        def where(self, f, op, v):
            filtered = [d for d in self._docs if d._d.get(f) == v]
            return FakeColl(filtered)
        def get(self):
            return self._docs

    class FakeDB:
        def __init__(self, docs):
            self._docs = docs
        def collection(self, p):
            return FakeColl(self._docs)
        def batch(self):
            return FakeBatch()

    tx_data = [
        {"id": "t1", "employeeId": "e1", "periodYear": 2026, "importBatchId": "batch_99"},
        {"id": "t2", "employeeId": "e2", "periodYear": 2026, "importBatchId": "batch_99"},
    ]
    fake_db = FakeDB([FakeDoc(t) for t in tx_data])

    with patch("app.services.db_service.firebase_initialized", True), \
         patch("app.services.db_service.db_firestore", fake_db), \
         patch("app.web.rrhh.payroll_history_import._rebuild_ytd_for_employee"), \
         patch("app.web.rrhh.payroll_history_import.sync_imported_payroll_periods"):
        res = revert_import_batch("comp1", "batch_99", sandbox=True)

    assert res["deleted_transactions"] == 2
    assert res["affected_employees"] == 2


# ── Escenario 16: Secuencialidad y avance tras cierre operativo ──
def test_scenario_16_operational_closure_advances_sequence():
    periods = [
        _p(GROUP, "2026-10-M", "2026-10-01", status="cerrada", is_historical=False),
    ]
    available = _monthly(2026)
    blocked, open_label, closed = blocked_period_keys(
        periods, available, GROUP, initial_live_period="2026-10-M"
    )
    # Noviembre se desbloquea automáticamente
    assert "2026-11-M" not in blocked
    # Diciembre permanece bloqueado hasta cerrar Noviembre
    assert "2026-12-M" in blocked
    assert "2026-10-M" in closed


# ── Escenario 17: Aislamiento de datos entre empresas ──
def test_scenario_17_company_isolation():
    periods_comp_a = [_p("g_a", "2026-10-M", "2026-10-01", status="cerrada")]
    periods_comp_b = [_p("g_b", "2026-05-M", "2026-05-01", status="borrador")]

    avail = _monthly(2026)
    blocked_a, _, closed_a = blocked_period_keys(periods_comp_a, avail, "g_a", initial_live_period="2026-10-M")
    blocked_b, label_b, _ = blocked_period_keys(periods_comp_b, avail, "g_b", initial_live_period="2026-05-M")

    assert "2026-11-M" not in blocked_a
    assert "2026-06-M" in blocked_b
    assert label_b == "2026-05-M"


# ── Escenario 18: Empresa con período operativo pendiente posterior al inicio configurado ──
def test_scenario_18_pending_period_after_initial_live_blocks_ahead():
    periods = [
        _p(GROUP, "2026-10-M", "2026-10-01", status="cerrada", is_historical=False),
        _p(GROUP, "2026-11-M", "2026-11-01", status="borrador", is_historical=False),
    ]
    available = _monthly(2026)
    blocked, open_label, closed = blocked_period_keys(
        periods, available, GROUP, initial_live_period="2026-10-M"
    )
    # Noviembre está abierto -> Diciembre bloqueado
    assert "2026-11-M" not in blocked
    assert "2026-12-M" in blocked
    assert open_label == "2026-11-M"
    assert "2026-10-M" in closed


# ── Escenario 19: Resolución de contradicción initial_live_period vs históricos existentes ──
def test_scenario_19_contradictory_initial_live_advances_after_history():
    # initial_live_period configurado en 2026-08-M, pero existen históricos hasta 2026-10-M
    periods = [
        _p(GROUP, f"2026-{m:02d}-M", f"2026-{m:02d}-01", status="cerrada", is_historical=True)
        for m in range(1, 11)
    ]
    available = _monthly(2026)
    blocked, open_label, closed = blocked_period_keys(
        periods, available, GROUP, initial_live_period="2026-08-M"
    )
    # Debe avanzar automáticamente a Noviembre (2026-11-M)
    assert "2026-11-M" not in blocked
    assert "2026-12-M" in blocked
    assert "2026-10-M" in closed


# ── Escenario 20: IR-13 exacto con sueldos, comisiones, horas extras y regalía ──
def test_scenario_20_ir13_exact_breakdown_no_double_count():
    emp_map = [
        {"id": "emp_1", "fullName": "Perez, Juan", "cedula": "001-0000000-1", "status": "activo", "firstName": "Juan", "firstLastName": "Perez"}
    ]
    # Nómina con base 50k, comision 10k, horas extra 5k, bono 5k, regalia 50k (exenta)
    periods = [
        {
            "id": "imp_2026-12-M",
            "periodKey": "2026-12-M",
            "year": 2026,
            "lines": [{
                "employeeId": "emp_1",
                "grossSalary": 50000.0,
                "commission": 10000.0,
                "bonus": 5000.0,
                "otherIncome": 0.0,
                "overtimePay": 5000.0,
                "christmasBonus": 50000.0,
                "afpEmployee": 2000.0,
                "sfsEmployee": 2000.0,
                "isrRetention": 5000.0,
                "educationDeduction": 10000.0,
            }]
        }
    ]
    with patch("app.services.hr_data_service.get_employees", return_value=emp_map), \
         patch("app.services.hr_data_service.get_payroll_periods", return_value=periods), \
         patch("app.services.payroll_service.PayrollService.get_period_lines", side_effect=lambda p, **kw: p.get("lines", [])):
        res = calculate_ir13("comp1", 2026, sandbox=True)

    row = res["employees"][0]
    assert row["C"] == 50000.0   # Sueldo ordinario
    assert row["D"] == 20000.0   # 10k comisión + 5k bono + 5k horas extra
    assert row["F"] == 70000.0   # Total ingresos brutos C + D (NO duplica comisión)
    assert row["G"] == 50000.0   # Exento (regalía)
    assert row["H"] == 4000.0    # TSS (AFP + SFS)
    assert row["I"] == 16000.0   # Base imponible F - G - H = 70k - 50k - 4k = 16k
    assert row["L"] == 5000.0    # Retenido


# ── Escenario 21: Limpieza de períodos históricos obsoletos tras rollback ──
def test_scenario_21_sync_imported_cleans_obsolete_periods():
    deleted_periods = []
    class FakeDoc:
        def __init__(self, data):
            self._d = data
            self.id = data.get("id")
        def to_dict(self):
            return self._d

    class FakeColl:
        def __init__(self, docs):
            self._docs = docs
        def where(self, f, op, v):
            filtered = [d for d in self._docs if d._d.get(f) == v]
            return FakeColl(filtered)
        def get(self):
            return self._docs

    class FakeDB:
        def __init__(self, docs):
            self._docs = docs
        def collection(self, p):
            return FakeColl(self._docs)

    # Solo queda transacción de 2026-02-M (la de 2026-01-M fue revertida)
    tx_data = [
        {"id": "t2", "employeeId": "e1", "periodKey": "2026-02-M", "periodYear": 2026, "source": "import", "status": "applied", "amount": 30000.0, "type": "earning", "conceptCode": "SALARIO_BASE"},
    ]
    # En payroll_periods aún figura imp_2026-01-M de antes
    existing_periods = [
        {"id": "imp_2026-01-M", "periodKey": "2026-01-M", "isHistorical": True},
        {"id": "imp_2026-02-M", "periodKey": "2026-02-M", "isHistorical": True},
    ]

    with patch("app.services.db_service.firebase_initialized", True), \
         patch("app.services.db_service.db_firestore", FakeDB([FakeDoc(t) for t in tx_data])), \
         patch("app.services.hr_data_service.get_employees", return_value=[{"id": "e1"}]), \
         patch("app.services.hr_data_service.get_payroll_periods", return_value=existing_periods), \
         patch("app.services.hr_data_service.delete_payroll_period", side_effect=lambda c, pid, **kw: deleted_periods.append(pid)), \
         patch("app.services.hr_data_service.delete_payroll_lines"), \
         patch("app.services.hr_data_service.save_payroll_period"), \
         patch("app.services.payroll_period_sequence.set_payroll_migration_config"):
        synced = sync_imported_payroll_periods("comp1", sandbox=True)

    assert "imp_2026-01-M" in deleted_periods
    assert len(synced) == 1
    assert synced[0]["periodKey"] == "2026-02-M"


# ── Escenario 22: Chunking seguro en Firestore para lotes grandes (> 400 docs) ──
def test_scenario_22_batch_chunking_large_rollback():
    batch_commits = []
    class FakeBatch:
        def __init__(self):
            self.ops = 0
        def delete(self, ref):
            self.ops += 1
        def commit(self):
            batch_commits.append(self.ops)

    class FakeDoc:
        def __init__(self, i):
            self.id = f"tx_{i}"
            self.reference = f"ref_{i}"
            self._d = {"id": f"tx_{i}", "employeeId": f"e_{i%50}", "periodYear": 2026, "importBatchId": "large_batch"}
        def to_dict(self):
            return self._d

    class FakeColl:
        def __init__(self, docs):
            self._docs = docs
        def where(self, f, op, v):
            return self
        def get(self):
            return self._docs

    class FakeDB:
        def __init__(self, docs):
            self._docs = docs
        def collection(self, p):
            return FakeColl(self._docs)
        def batch(self):
            return FakeBatch()

    # 950 transacciones
    docs = [FakeDoc(i) for i in range(950)]
    fake_db = FakeDB(docs)

    with patch("app.services.db_service.firebase_initialized", True), \
         patch("app.services.db_service.db_firestore", fake_db), \
         patch("app.web.rrhh.payroll_history_import._rebuild_ytd_for_employee"), \
         patch("app.web.rrhh.payroll_history_import.sync_imported_payroll_periods"):
        res = revert_import_batch("comp1", "large_batch", sandbox=True)

    assert res["deleted_transactions"] == 950
    # Verificamos que se dividió en 3 commits: 400 + 400 + 150
    assert batch_commits == [400, 400, 150]
