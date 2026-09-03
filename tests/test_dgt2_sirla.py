"""Tests para el archivo SIRLA DGT-2 (carga de trabajadores).

Valida que el archivo fixed-width generado coincida exactamente con el layout
oficial DGT-2: encabezado (20), detalle (400) y sumario (7), posiciones de
campo, formato decimal de valor hora, bloque diario de horas extras y causa.
"""

from unittest.mock import patch

import pytest

from app.services.dgt_export_service import (
    DGTExportService,
    _build_days_block,
    _decimal,
    _sanitize_cause,
)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers de formato
# ═══════════════════════════════════════════════════════════════════════════

class TestHelpers:
    def test_decimal_valor_hora_100(self):
        assert _decimal(100.0, 8, 2) == "00100.00"

    def test_decimal_valor_hora_50_5(self):
        assert _decimal(50.5, 8, 2) == "00050.50"

    def test_decimal_horas_cero(self):
        assert _decimal(0.0, 5, 2) == "00.00"

    def test_decimal_horas_dos_y_medio(self):
        assert _decimal(2.5, 5, 2) == "02.50"

    def test_decimal_porcentaje_35(self):
        assert _decimal(35.0, 6, 2) == "035.00"

    def test_decimal_porcentaje_100(self):
        assert _decimal(100.0, 6, 2) == "100.00"

    def test_decimal_porcentaje_cero(self):
        assert _decimal(0.0, 6, 2) == "000.00"

    def test_sanitize_cause_valida(self):
        assert _sanitize_cause("b") == "b"

    def test_sanitize_cause_mayuscula(self):
        assert _sanitize_cause("C") == "c"

    def test_sanitize_cause_invalida_vacia(self):
        assert _sanitize_cause("z") == ""
        assert _sanitize_cause("") == ""

    def test_days_block_longitud_341(self):
        assert len(_build_days_block({})) == 341

    def test_days_block_todo_ceros(self):
        block = _build_days_block({})
        # Cada día: "00.00" (5) + "000.00" (6) = 11 chars
        assert block[:11] == "00.00" + "000.00"
        assert block[-11:] == "00.00" + "000.00"

    def test_days_block_dia_3_con_horas(self):
        block = _build_days_block({3: {"hours": 2.5, "percentage": 35.0}})
        # días 1 y 2 en cero → offset 22
        assert block[22:33] == "02.50" + "035.00"


# ═══════════════════════════════════════════════════════════════════════════
# Generación completa del archivo
# ═══════════════════════════════════════════════════════════════════════════

def _sample_lines():
    return [
        {
            "docTypeSirla": "C",
            "documento": "00112345678",
            "hourlyRate": 100.0,
            "overtimeDays": {3: {"hours": 2.5, "percentage": 35.0}},
            "overtimeCause": "a",
        },
        {
            "docTypeSirla": "P",
            "documento": "AB123456",
            "hourlyRate": 50.5,
            "overtimeDays": {},
            "overtimeCause": "",
        },
    ]


class TestToSirlaTxtDgt2:
    def _render(self, lines=None, **kw):
        lines = lines if lines is not None else _sample_lines()
        kw.setdefault("company_info", {"companyRNC": "131-88068-1"})
        kw.setdefault("establishment_id", "001234")
        kw.setdefault("year", 2026)
        kw.setdefault("month", 9)
        return DGTExportService.to_sirla_txt_dgt2(lines, **kw)

    def test_encabezado(self):
        txt = self._render()
        header = txt.split("\n")[0]
        assert len(header) == 20
        assert header == "ET2" + "00131880681" + "092026"

    def test_detalle_longitud_400(self):
        txt = self._render()
        lines = txt.split("\n")
        assert len(lines[1]) == 400

    def test_sumario(self):
        txt = self._render()
        lines = [l for l in txt.split("\n") if l]
        # E + 2 D + S = 4 registros
        assert lines[-1] == "S000004"

    def test_posiciones_detalle(self):
        txt = self._render()
        detail = txt.split("\n")[1]
        assert detail[0] == "D"
        assert detail[1:4] == "NC "          # novedad, 3 chars
        assert detail[4] == "C"               # tipo documento
        assert detail[5:30] == "00112345678".ljust(25)  # número documento
        assert detail[30:36] == "001234"      # establecimiento
        assert detail[36:44] == "00100.00"    # valor hora
        assert len(detail[44:385]) == 341     # bloque días
        assert detail[385:400] == "a".ljust(15)  # causa

    def test_valor_hora_formato_decimal(self):
        txt = self._render()
        detail = txt.split("\n")[1]
        assert detail[36:44] == "00100.00"

    def test_causa_invalida_se_limpia(self):
        lines = [
            {
                "docTypeSirla": "C",
                "documento": "001",
                "hourlyRate": 10.0,
                "overtimeDays": {},
                "overtimeCause": "z",
            }
        ]
        txt = self._render(lines=lines)
        detail = txt.split("\n")[1]
        assert detail[385:400] == "".ljust(15)

    def test_establecimiento_padding(self):
        txt = self._render(establishment_id="")
        detail = txt.split("\n")[1]
        assert detail[30:36] == "000000"

    def test_periodo_es_mmyyyy(self):
        txt = self._render(year=2026, month=9)
        header = txt.split("\n")[0]
        assert header[3:14] == "00131880681"
        assert header[14:20] == "092026"


# ═══════════════════════════════════════════════════════════════════════════
# get_dgt2_data — datos por mes y por día
# ═══════════════════════════════════════════════════════════════════════════

class TestGetDgt2Data:
    def _emp(self, emp_id, status="activo", salary=50000.0, cedula="001-1234567-8",
             id_type="cedula", weekly_hours=44):
        return {
            "id": emp_id,
            "status": status,
            "cedula": cedula,
            "idType": id_type,
            "baseSalary": salary,
            "weeklyHours": weekly_hours,
            "firstName": "Juan",
            "middleName": "",
            "firstLastName": "Perez",
            "secondLastName": "Gomez",
            "sdssNumber": "SDSS-1",
        }

    def _run(self, employees, overtime_records, year=2026, month=9):
        with patch("app.services.dgt_service.get_employees", return_value=employees), \
             patch("app.services.dgt_service.get_vacation_requests", return_value=[]), \
             patch("app.services.dgt_service.get_overtime_records", return_value=overtime_records), \
             patch("app.services.db_service.DatabaseService.get_company",
                   return_value={"rnc": "131880681", "rnl_number": "1234",
                                 "company_name": "Test SRL"}):
            from app.services.dgt_service import DGTService
            return DGTService.get_dgt2_data("C1", year, month, sandbox=True)

    def test_filtra_empleados_activo_equivalente(self):
        employees = [
            self._emp("E1", status="activo"),
            self._emp("E2", status="vacaciones"),
            self._emp("E3", status="inactivo"),
            self._emp("E4", status="suspendido"),
        ]
        data = self._run(employees, [])
        docs = [l["documento"] for l in data["sirlaLines"]]
        assert docs == ["00112345678", "00112345678"]

    def test_agrega_horas_extras_por_dia(self):
        employees = [self._emp("E1")]
        records = [
            {"employeeId": "E1", "date": "2026-09-05", "totalMinutes": 150,
             "factorAtApproval": 1.35, "status": "processed"},
            {"employeeId": "E1", "date": "2026-09-05", "totalMinutes": 60,
             "factorAtApproval": 2.00, "status": "approved"},
        ]
        data = self._run(employees, records)
        line = data["sirlaLines"][0]
        assert line["overtimeDays"][5]["hours"] == 3.5  # 150 + 60 min = 210 min = 3.5 h

    def test_ignora_fuera_de_mes_y_draft(self):
        employees = [self._emp("E1")]
        records = [
            {"employeeId": "E1", "date": "2026-08-05", "totalMinutes": 120,
             "factorAtApproval": 1.35, "status": "processed"},
            {"employeeId": "E1", "date": "2026-09-05", "totalMinutes": 120,
             "factorAtApproval": 1.35, "status": "draft"},
        ]
        data = self._run(employees, records)
        assert data["sirlaLines"][0]["overtimeDays"] == {}

    def test_porcentaje_desde_factor(self):
        employees = [self._emp("E1")]
        records = [
            {"employeeId": "E1", "date": "2026-09-10", "totalMinutes": 120,
             "factorAtApproval": 2.00, "status": "processed"},
        ]
        data = self._run(employees, records)
        assert data["sirlaLines"][0]["overtimeDays"][10]["percentage"] == 100.0
