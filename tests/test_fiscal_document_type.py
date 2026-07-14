"""
Tests integrales para FiscalDocumentType.

Cubre: integridad semántica (cada tipo documenta sus flags correctamente),
consistencia entre configs (TIPO_CONFIG bridge vs modelo), y lookup API.
"""
import pytest
from app.models.fiscal_document_type import (
    by_code, by_numeric, by_ncf_prefix, emitables, all_types,
    has_code, get_tipo_config, has_itbis_breakdown, has_retencion_item,
    select_options, report_labels,
    FiscalDocumentType, Family, Category,
)


class TestRegistry:
    def test_all_ecf_types_registered(self):
        codes = {t.code for t in all_types() if t.family == Family.ECF}
        expected = {"E31", "E32", "E33", "E34", "E41", "E43", "E44",
                    "E45", "E46", "E47", "E48", "E49", "E50"}
        assert codes >= expected, f"ECF faltantes: {expected - codes}"

    def test_all_traditional_types_registered(self):
        codes = {t.code for t in all_types() if t.family == Family.TRADITIONAL}
        expected = {"B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08",
                    "B09", "B10", "B11", "B13", "B14", "B15", "B16", "B17", "B18"}
        assert codes >= expected, f"NCF faltantes: {expected - codes}"

    def test_rui_registered(self):
        assert by_code("B12").family == Family.RUI

    def test_no_duplicate_numeric_codes(self):
        seen = {}
        for t in all_types():
            assert t.numeric_code not in seen, f"Código numérico duplicado: {t.numeric_code}"
            seen[t.numeric_code] = t.code

    def test_by_code_roundtrip(self):
        for t in all_types():
            assert by_code(t.code) is t

    def test_by_numeric_roundtrip(self):
        for t in all_types():
            assert by_numeric(t.numeric_code) is t

    def test_by_ncf_prefix(self):
        assert by_ncf_prefix("E310000000001").code == "E31"
        assert by_ncf_prefix("B010000000001").code == "B01"
        assert by_ncf_prefix("B120000000001").code == "B12"

    def test_has_code(self):
        assert has_code("E31")
        assert has_code("B01")
        assert has_code("B12")
        assert not has_code("XX99")
        assert not has_code("")

    def test_emitables_only_ecf(self):
        for t in emitables():
            assert t.family == Family.ECF

    def test_unknown_code_raises(self):
        with pytest.raises(KeyError):
            by_code("XX99")

    def test_unknown_numeric_raises(self):
        with pytest.raises(KeyError):
            by_numeric("99")

    def test_by_ncf_prefix_unknown_raises(self):
        with pytest.raises(KeyError):
            by_ncf_prefix("XX99000001")


class TestTypeMetadata:
    """Verifica que cada tipo tenga metadata sensible."""

    @pytest.mark.parametrize("code,expected", [
        ("E31", True), ("E32", True), ("E33", True), ("E34", True),
        ("E41", True), ("E43", False), ("E44", False), ("E45", True),
        ("E46", True), ("E47", False), ("E48", False), ("E49", False),
        ("E50", False), ("B12", False),
    ])
    def test_has_itbis_breakdown(self, code, expected):
        assert has_itbis_breakdown(code) == expected

    @pytest.mark.parametrize("code,expected", [
        ("E31", True), ("E33", True), ("E34", True), ("E41", True),
        ("E47", True), ("E50", True),
        ("E32", False), ("E43", False), ("E44", False), ("E45", False),
        ("E46", False), ("B12", False),
    ])
    def test_has_retention(self, code, expected):
        from app.models.fiscal_document_type import by_code
        assert by_code(code).has_retention == expected

    @pytest.mark.parametrize("code,expected", [
        ("E31", True), ("E32", True), ("E33", True), ("E34", False),
        ("E45", True), ("E46", True),
        ("E41", False), ("E43", False), ("E47", True),
    ])
    def test_has_payment_schedule(self, code, expected):
        assert by_code(code).has_payment_schedule == expected

    @pytest.mark.parametrize("code,expected", [
        ("E31", True), ("E33", True), ("E41", True), ("E43", True),
        ("E44", True), ("E45", True), ("E46", True), ("E47", True),
        ("E32", False), ("E34", False),
    ])
    def test_has_vencimiento(self, code, expected):
        assert by_code(code).has_vencimiento == expected

    def test_all_itbis_breakdown_types_have_itbis(self):
        """ITBIS breakdown implica ITBIS (excepto E45 gubernamental y E46
        exportación que usan breakdown por requisito DGII aunque exentos)."""
        for t in all_types():
            if t.has_itbis_breakdown and t.code not in ("E45", "E46"):
                assert t.has_itbis, f"{t.code} has_itbis_breakdown=True but has_itbis=False"

    def test_consumo_250_types(self):
        """E32/E33/E34 permiten omitir RNC cuando total < 250k."""
        for code in ("E32", "E33", "E34"):
            assert by_code(code).category in (Category.CONSUMER, Category.CREDIT_NOTE, Category.DEBIT_NOTE)

    def test_report_606_types(self):
        """606 solo aplica a compras/gastos/gobierno/exterior."""
        codes = {t.code for t in all_types() if t.in_reporte_606}
        assert codes == {"E41", "E43", "E45", "E47", "E49"}

    def test_report_607_types(self):
        """607 aplica a ventas/export/gobierno."""
        codes = {t.code for t in all_types() if t.in_reporte_607}
        expected = {"E31", "E32", "E33", "E34", "E45", "E46", "E48", "E49"}
        assert codes >= expected, f"607 espera {expected}, obtuvo {codes}"

    def test_e43_max_amount(self):
        assert by_code("E43").max_amount == 250000

    def test_e47_is_foreign_payment(self):
        assert by_code("E47").category == Category.FOREIGN_PAYMENT

    def test_e46_is_export(self):
        assert by_code("E46").category == Category.EXPORT

    def test_e45_no_itbis(self):
        t = by_code("E45")
        assert not t.has_itbis
        assert t.has_itbis_breakdown  # DGII requiere breakdown aunque exento

    def test_e43_no_comprador(self):
        assert not by_code("E43").has_comprador

    def test_xsd_files(self):
        for t in all_types():
            if t.family == Family.ECF:
                # E48/E49/E50 no tienen XSD publicado
                if t.code in ("E48", "E49", "E50"):
                    assert t.xsd_file is None, f"{t.code} debería tener xsd=None"
                else:
                    assert t.xsd_file is not None, f"{t.code} sin xsd asignado"

    def test_accounting_entry_types(self):
        """Verifica entry_type contable para cada tipo."""
        expected_expense = {"E41", "E43", "E47", "B05", "B06", "B07", "B10", "B13", "B16"}
        expected_credit_note = {"E34", "B04", "B18"}
        expected_invoice = {"E31", "E32", "E33", "E45", "E46", "E48", "E49",
                            "B01", "B02", "B03", "B08", "B09", "B12", "B14", "B15", "B17"}
        for t in all_types():
            if t.code in expected_expense:
                assert t.accounting_entry_type == "expense", f"{t.code} debe ser expense"
            elif t.code in expected_credit_note:
                assert t.accounting_entry_type == "credit_note", f"{t.code} debe ser credit_note"
            elif t.code in expected_invoice:
                assert t.accounting_entry_type == "invoice", f"{t.code} debe ser invoice"


class TestTipoConfigBridge:
    """Verifica que el puente a TIPO_CONFIG legacy devuelva datos correctos."""

    def test_bridge_preserves_original_semantics(self):
        for num in ("31", "32", "33", "34", "41", "43", "44", "45", "46", "47"):
            cfg = get_tipo_config(num)
            assert "label" in cfg
            assert "monto_gravado" in cfg
            assert "has_comprador" in cfg
            assert "ingresos" in cfg

    def test_bridge_e31(self):
        cfg = get_tipo_config("E31")
        assert cfg["label"] == "Factura de Crédito Fiscal"
        assert cfg["monto_gravado"] is True
        assert cfg["has_comprador"] is True
        assert cfg["ingresos"] is True
        assert cfg["expense"] is False
        assert cfg["retenciones"] is True
        assert cfg["tabla_pagos"] is True

    def test_bridge_e43(self):
        cfg = get_tipo_config("43")
        assert cfg["label"] == "Gastos Menores"
        assert cfg["monto_gravado"] is False
        assert cfg["has_comprador"] is False
        assert cfg["ingresos"] is False
        assert cfg["expense"] is True
        assert cfg["retenciones"] is False
        assert cfg["tabla_pagos"] is False
        assert cfg["descuentos"] is False

    def test_bridge_e47(self):
        cfg = get_tipo_config("E47")
        assert cfg["foreign_payment"] is True
        assert cfg["monto_gravado"] is False
        assert cfg["retenciones"] is True

    def test_bridge_e46(self):
        cfg = get_tipo_config("E46")
        assert cfg["export"] is True
        assert cfg["monto_gravado"] is False
        assert cfg["ingresos"] is True

    def test_bridge_unknown_returns_empty(self):
        assert get_tipo_config("XX99") == {}


class TestHasItbisBreakdownBridge:

    @pytest.mark.parametrize("num,expected", [
        ("31", True), ("32", True), ("33", True), ("34", True),
        ("41", True), ("45", True), ("46", True),
        ("43", False), ("44", False), ("47", False),
    ])
    def test_numeric(self, num, expected):
        assert has_itbis_breakdown(num) == expected

    @pytest.mark.parametrize("code,expected", [
        ("E31", True), ("E32", True), ("E33", True), ("E34", True),
        ("E41", True), ("E45", True), ("E46", True),
        ("E43", False), ("E44", False), ("E47", False), ("E48", False),
    ])
    def test_ecf_code(self, code, expected):
        assert has_itbis_breakdown(code) == expected


class TestHasRetencionItemBridge:

    @pytest.mark.parametrize("num,expected", [
        ("41", True), ("47", True),
        ("31", False), ("32", False), ("33", False), ("34", False),
        ("43", False), ("44", False), ("45", False), ("46", False),
    ])
    def test_numeric(self, num, expected):
        assert has_retencion_item(num) == expected

    @pytest.mark.parametrize("code,expected", [
        ("E41", True), ("E47", True),
        ("E31", False), ("E32", False), ("E33", False), ("E34", False),
        ("E43", False),
    ])
    def test_ecf_code(self, code, expected):
        assert has_retencion_item(code) == expected


class TestSemanticConsistency:
    """Razonamiento semántico: ninguna flag debe contradecir otra."""

    def test_export_types_have_no_itbis(self):
        for t in all_types():
            if t.category == Category.EXPORT:
                assert not t.has_itbis, f"{t.code} no debe tener ITBIS"
                # Nota: E46 tiene has_itbis_breakdown=True porque el XSD
                # requiere los campos MontoGravadoTotal/ITBIS3 para tasa 0%

    def test_foreign_payment_no_itbis(self):
        for t in all_types():
            if t.category == Category.FOREIGN_PAYMENT:
                assert not t.has_itbis
                assert not t.has_itbis_breakdown

    def test_government_no_itbis(self):
        for t in all_types():
            if t.category == Category.GOVERNMENT:
                assert not t.has_itbis

    def test_credit_note_no_vencimiento_no_payment_schedule(self):
        for t in all_types():
            if t.category == Category.CREDIT_NOTE:
                assert not t.has_vencimiento, f"{t.code} no debe tener vencimiento"
                assert not t.has_payment_schedule, f"{t.code} no debe tener tabla de pagos"

    def test_types_without_comprador_are_purchases_or_minor(self):
        for t in all_types():
            if not t.has_comprador:
                assert t.category in (Category.MINOR_EXPENSE, Category.PURCHASES,
                                      Category.SALES, Category.COMMON), f"{t.code} sin comprador pero categoría inusual"

    def test_debit_note_has_vencimiento(self):
        for t in all_types():
            if t.category == Category.DEBIT_NOTE:
                assert t.has_vencimiento, f"{t.code} debe tener vencimiento"


# =========================================================================
# Tests para helpers de templates y reportes
# =========================================================================

class TestSelectOptions:

    def test_select_options_ecf_family(self):
        opts = select_options(family="e-cf")
        codes = {c for c, _ in opts}
        assert "E31" in codes
        assert "E41" in codes
        assert "B01" not in codes

    def test_select_options_ncf_family(self):
        opts = select_options(family="ncf")
        codes = {c for c, _ in opts}
        assert "B01" in codes
        assert "E31" not in codes

    def test_select_options_family_enum(self):
        opts = select_options(family=Family.ECF)
        assert len(opts) == 13
        assert all(c.startswith("E") for c, _ in opts)

    def test_select_options_category(self):
        opts = select_options(category="ventas")
        codes = {c for c, _ in opts}
        assert "E31" in codes
        assert "B01" in codes
        assert "E41" not in codes

    def test_select_options_category_enum(self):
        opts = select_options(category=Category.SALES)
        assert len(opts) == len([c for c, _ in select_options(category="ventas")])

    def test_select_options_no_filter(self):
        opts = select_options()
        assert len(opts) >= 30

    def test_select_options_returns_tuples(self):
        opts = select_options(family="e-cf")
        for c, l in opts:
            assert isinstance(c, str)
            assert isinstance(l, str)
            assert " (" in l

    def test_select_options_sorted(self):
        opts = select_options(family="e-cf")
        codes = [c for c, _ in opts]
        assert codes == sorted(codes)


class TestReportLabels:

    def test_report_606_keys(self):
        labels = report_labels("606")
        assert "E41" in labels
        assert "E43" in labels
        assert "E31" not in labels  # E31 es ventas, no 606

    def test_report_607_keys(self):
        labels = report_labels("607")
        assert "E31" in labels
        assert "E32" in labels
        assert "E41" not in labels  # E41 es compras, no 607

    def test_report_623_keys(self):
        labels = report_labels("623")
        assert "E43" in labels
        assert "E47" in labels
        assert "E41" not in labels

    def test_report_labels_format(self):
        labels = report_labels("607")
        for code, label in labels.items():
            assert label.startswith(f"{code[0]}-{code[1:]} ("), f"{code}: {label!r}"
            assert label.endswith(")")

    def test_report_unknown_returns_empty(self):
        assert report_labels("999") == {}

    def test_report_608_has_all(self):
        labels = report_labels("608")
        assert len(labels) >= 30  # todos los tipos tienen in_reporte_608=True


class TestLabelProperties:

    def test_short_label(self):
        assert by_code("E31").short_label == "Factura de Crédito Fiscal"
        assert by_code("B04").short_label == "Nota de Crédito"

    def test_label_with_code(self):
        assert by_code("E31").label_with_code == "Factura de Crédito Fiscal (E31)"
        assert by_code("B04").label_with_code == "Nota de Crédito (B04)"

    def test_report_label(self):
        assert by_code("E31").report_label == "E-31 (Factura de Crédito Fiscal)"
        assert by_code("B04").report_label == "B-04 (Nota de Crédito)"

    def test_str(self):
        s = str(by_code("E31"))
        assert "E31" in s
        assert "Factura de Crédito Fiscal" in s
        assert "B01" not in s  # short_label no repite el código
