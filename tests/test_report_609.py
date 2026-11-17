"""Entregable 3.3.3 — Generador del Formato 609.

Verifica catálogos, validación, estructura TXT, pagos parciales y límite de
registros.
"""

import pytest

from app.services.dgii_609_service import (
    TIPO_SERVICIO_609,
    TIPO_IDENTIFICACION_609,
    PARTE_RELACIONADA_609,
    DETAIL_CODES_609,
    COUNTRIES_609,
    build_record,
    validate_record,
    detect_retention_dates,
    representable_retention_date,
    split_by_max_records,
    generate_609_txt,
    MAX_RECORDS_609,
    _normalize_country,
)


def _source(**kw):
    s = {
        "nombre": "Proveedor Exterior SRL",
        "tipoIdentificacion": "2",
        "identificacion": "123456789",
        "pais": "USA",
        "tipoServicio": "2",
        "detalleServicio": "21",
        "parteRelacionada": "0",
        "numeroDocumento": "E470000000001",
        "fechaDocumento": "2026-03-15",
        "montoFacturado": 1000.0,
        "fechaRetencionISR": "2026-03-20",
        "rentaPresunta": 1000.0,
        "isrRetenido": 150.0,
    }
    s.update(kw)
    return s


class TestCatalogs:
    def test_tipo_servicio_has_8_categories(self):
        assert len(TIPO_SERVICIO_609) == 8
        assert TIPO_SERVICIO_609["1"] == "Gastos de personal"
        assert TIPO_SERVICIO_609["8"] == "Gastos por regalías y otros intangibles"

    def test_tipo_identificacion(self):
        assert TIPO_IDENTIFICACION_609 == {"1": "Persona física", "2": "Persona jurídica"}

    def test_parte_relacionada(self):
        assert PARTE_RELACIONADA_609 == {"0": "No relacionado", "1": "Relacionado"}


class TestValidateRecord:
    def test_valid_record(self):
        assert validate_record(build_record(_source())) == []

    def test_invalid_tipo_identificacion(self):
        errs = validate_record(build_record(_source(tipoIdentificacion="3")))
        assert any("Tipo de identificación" in e for e in errs)

    def test_invalid_pais(self):
        errs = validate_record(build_record(_source(pais="999")))
        assert any("País de destino inválido" in e for e in errs)

    def test_invalid_tipo_servicio(self):
        errs = validate_record(build_record(_source(tipoServicio="9")))
        assert any("Tipo de servicio" in e for e in errs)

    def test_invalid_detalle(self):
        errs = validate_record(build_record(_source(detalleServicio="99")))
        assert any("fuera del catálogo" in e for e in errs)

    def test_detalle_does_not_match_tipo(self):
        errs = validate_record(build_record(_source(tipoServicio="1", detalleServicio="21")))
        assert any("no corresponde al tipo" in e for e in errs)

    def test_each_tipo_accepts_matching_detalle(self):
        for tipo in range(1, 9):
            detalle = tipo * 10 + 1
            errs = validate_record(build_record(_source(tipoServicio=str(tipo), detalleServicio=str(detalle))))
            assert errs == [], f"tipo {tipo} detalle {detalle}: {errs}"

    def test_parte_relacionada(self):
        assert validate_record(build_record(_source(parteRelacionada="1"))) == []
        assert any("Parte relacionada" in e for e in validate_record(build_record(_source(parteRelacionada="9"))))


class TestRetentionDates:
    def test_single_payment(self):
        d = representable_retention_date([{"paymentDate": "2026-03-20"}])
        assert d == "20260320"

    def test_no_payments(self):
        assert representable_retention_date([]) is None

    def test_multiple_dates_block(self):
        pays = [{"paymentDate": "2026-03-20"}, {"paymentDate": "2026-04-05"}]
        assert representable_retention_date(pays) is None

    def test_multiple_payments_same_date_ok(self):
        pays = [{"paymentDate": "2026-03-20"}, {"paymentDate": "2026-03-20"}]
        assert representable_retention_date(pays) == "20260320"


class TestGenerateTxt:
    def test_header_and_detail(self):
        rec = build_record(_source())
        txt = generate_609_txt([rec], "132123456", "202603")
        lines = txt.split("\n")
        assert lines[0] == "609|132123456|202603|1"
        assert len(lines[1].split("|")) == 13

    def test_period_normalized(self):
        txt = generate_609_txt([], "132123456", "2026-03")
        assert txt == "609|132123456|202603|0"

    def test_over_max_records_raises(self):
        records = [build_record(_source()) for _ in range(MAX_RECORDS_609 + 1)]
        with pytest.raises(ValueError):
            generate_609_txt(records, "132123456", "202603")

    def test_split_by_max(self):
        records = list(range(MAX_RECORDS_609 + 10))
        batches = split_by_max_records(records)
        assert len(batches) == 2
        assert len(batches[0]) == MAX_RECORDS_609
        assert len(batches[1]) == 10


from app.services.dgii_609_service import (
    is_foreign_payment_invoice,
    build_609_record_from_invoice,
)


class TestForeignPaymentClassification:
    def test_e47(self):
        assert is_foreign_payment_invoice({"ecfType": "E47"}) is True

    def test_b17(self):
        assert is_foreign_payment_invoice({"ecfType": "B17"}) is True

    def test_foreign_retention_rules(self):
        for rule in ("payments_abroad", "digital_services_abroad", "royalties"):
            assert is_foreign_payment_invoice({"retentionIsrRule": rule}) is True

    def test_normal_invoice(self):
        assert is_foreign_payment_invoice({"ecfType": "E31", "retentionIsrRule": "goods_services"}) is False


class TestBuild609RecordFromInvoice:
    def _supplier(self, **kw):
        s = {
            "supplierName": "Proveedor Exterior SRL",
            "tipoIdentificacion609": "2",
            "supplierRnc": "123456789",
            "paisDestino609": "USA",
            "parteRelacionada": "0",
        }
        s.update(kw)
        return s

    def _invoice(self, **kw):
        inv = {
            "id": "inv-1", "supplierName": "Proveedor Exterior SRL",
            "ncf": "E470000000001", "date": "2026-03-15", "total": 1000.0,
            "tipoServicio609": "2", "detalleServicio609": "21",
            "retentionIsrBase": 1000.0, "retentionIsrAmount": 150.0,
            "retentionIsrApplied": 150.0,
        }
        inv.update(kw)
        return inv

    def _pay(self, date, status="approved"):
        return {"paymentDate": date, "approvalStatus": status, "amount": 1000.0}

    def test_full_payment(self):
        rec, blocked = build_609_record_from_invoice(
            self._invoice(), self._supplier(), [self._pay("2026-03-20")],
        )
        assert blocked is None
        assert rec["nombre"] == "Proveedor Exterior SRL"
        assert rec["tipoIdentificacion"] == "2"
        assert rec["pais"] == "840"
        assert rec["tipoServicio"] == "2"
        assert rec["detalleServicio"] == "21"
        assert rec["montoFacturado"] == "1000.00"
        assert rec["fechaRetencionISR"] == "20260320"
        assert rec["isrRetenido"] == "150.00"

    def test_no_payment_blocked(self):
        rec, blocked = build_609_record_from_invoice(self._invoice(), self._supplier(), [])
        assert rec is None
        assert "Sin pago aprobado" in blocked

    def test_multiple_dates_blocked(self):
        rec, blocked = build_609_record_from_invoice(
            self._invoice(), self._supplier(),
            [self._pay("2026-03-20"), self._pay("2026-04-05")],
        )
        assert rec is None
        assert "distintas fechas" in blocked

    def test_pending_payment_excluded(self):
        rec, blocked = build_609_record_from_invoice(
            self._invoice(), self._supplier(), [self._pay("2026-03-20", status="pending")],
        )
        assert rec is None
        assert "Sin pago aprobado" in blocked

    def test_no_retention_invoice(self):
        inv = self._invoice(retentionIsrBase=0.0, retentionIsrAmount=0.0, retentionIsrApplied=0.0)
        rec, blocked = build_609_record_from_invoice(inv, self._supplier(), [self._pay("2026-03-20")])
        assert blocked is None
        assert rec["isrRetenido"] == "0.00"
        assert rec["rentaPresunta"] == "0.00"


class TestDetailCatalog:
    def test_exactly_25_official_codes(self):
        assert len(DETAIL_CODES_609) == 25

    def test_all_codes_valid_with_matching_tipo(self):
        for code in DETAIL_CODES_609:
            tipo = str(int(code) // 10)
            errs = validate_record(
                build_record(_source(tipoServicio=tipo, detalleServicio=code))
            )
            assert errs == [], f"{code}: {errs}"

    def test_nonexistent_codes_rejected(self):
        for bad in ("13", "19", "25", "34", "39", "45", "49", "55", "66", "72", "79", "85", "99"):
            errs = validate_record(build_record(_source(detalleServicio=bad)))
            assert any("fuera del catálogo" in e for e in errs), bad

    def test_invalid_tipo_detalle_combo(self):
        errs = validate_record(build_record(_source(tipoServicio="1", detalleServicio="21")))
        assert any("no corresponde al tipo" in e for e in errs)


class TestLengths:
    def test_nombre_max_50(self):
        assert validate_record(build_record(_source(nombre="A" * 50))) == []
        assert any("excede los 50" in e for e in validate_record(build_record(_source(nombre="A" * 51))))

    def test_identificacion_max_50(self):
        assert validate_record(build_record(_source(identificacion="1" * 50))) == []
        assert any("Identificación tributaria excede" in e for e in validate_record(build_record(_source(identificacion="1" * 51))))

    def test_numero_documento_max_30(self):
        assert validate_record(build_record(_source(numeroDocumento="X" * 30))) == []
        assert any("excede los 30" in e for e in validate_record(build_record(_source(numeroDocumento="X" * 31))))

    def test_monto_max_12(self):
        assert validate_record(build_record(_source(montoFacturado=999999999.99))) == []
        assert any("excede los 12" in e for e in validate_record(build_record(_source(montoFacturado=1000000000.00))))


class TestDates:
    def test_valid_leap_date(self):
        assert validate_record(build_record(_source(fechaDocumento="2026-02-28"))) == []

    def test_invalid_calendar_date(self):
        errs = validate_record(build_record(_source(fechaDocumento="2026-02-30")))
        assert any("Fecha del documento" in e for e in errs)

    def test_invalid_date_format(self):
        errs = validate_record(build_record(_source(fechaDocumento="202602")))
        assert any("Fecha del documento" in e for e in errs)

    def test_retention_date_period_match(self):
        assert validate_record(build_record(_source()), period="202603") == []

    def test_retention_date_period_mismatch(self):
        errs = validate_record(build_record(_source()), period="202604")
        assert any("no corresponde al período" in e for e in errs)

    def test_retention_date_required_when_renta_positive(self):
        errs = validate_record(build_record(_source(rentaPresunta=100.0, fechaRetencionISR="")))
        assert any("Fecha de retención ISR es obligatoria" in e for e in errs)


class TestCountries:
    def test_catalog_size(self):
        assert len(COUNTRIES_609) >= 200

    def test_numeric_code_valid(self):
        assert validate_record(build_record(_source(pais="840"))) == []

    def test_country_name_normalizes(self):
        assert build_record(_source(pais="Estados Unidos"))["pais"] == "840"

    def test_alpha_alias_normalizes(self):
        assert _normalize_country("US") == "840"
        assert _normalize_country("USA") == "840"
        assert _normalize_country("ES") == "724"

    def test_leading_zero_preserved(self):
        assert _normalize_country("004") == "004"
        assert _normalize_country(4) == "004"
        assert _normalize_country("4") == "004"
        rec = build_record(_source(pais="004"))
        assert rec["pais"] == "004"

    def test_unknown_country_rejected(self):
        errs = validate_record(build_record(_source(pais="ZZZ")))
        assert any("País de destino inválido" in e for e in errs)


class TestIsrRetenido:
    def test_zero_valid(self):
        assert validate_record(build_record(_source(isrRetenido=0.0, rentaPresunta=0.0))) == []

    def test_positive_valid(self):
        assert validate_record(build_record(_source(isrRetenido=150.0))) == []

    def test_negative_invalid(self):
        errs = validate_record(build_record(_source(isrRetenido=-1.0)))
        assert any("no puede ser negativo" in e for e in errs)

    def test_empty_becomes_zero(self):
        rec = build_record(_source(isrRetenido=""))
        assert rec["isrRetenido"] == "0.00"
        assert validate_record(rec) == []


class TestTxtExport:
    def test_thirteen_fields_in_order(self):
        rec = build_record(_source())
        txt = generate_609_txt([rec], "132123456", "202603")
        fields = txt.split("\n")[1].split("|")
        assert len(fields) == 13
        assert fields[0] == "Proveedor Exterior SRL"
        assert fields[1] == "2"
        assert fields[2] == "123456789"
        assert fields[3] == "840"
        assert fields[4] == "2"
        assert fields[5] == "21"
        assert fields[6] == "0"
        assert fields[7] == "E470000000001"
        assert fields[8] == "20260315"
        assert fields[9] == "1000.00"
        assert fields[10] == "20260320"
        assert fields[11] == "1000.00"
        assert fields[12] == "150.00"
