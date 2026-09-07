"""Tests de regresión para el parseo del formulario de movimientos recurrentes.

Cubre el bug de montos 0 en deducciones: el formulario envía ambas secciones
(ingresos + deducción) y los inputs de la sección oculta (display:none) también
se envían. _parse_recurring_form debe leer la sección visible según tipo/subtipo
(campos ded* para deducción regular) en lugar de la primera ocurrencia del DOM.
"""

from werkzeug.datastructures import MultiDict

from app.web.rrhh.recurring import _parse_recurring_form


EXISTING = {"employeeId": "EMP1", "employeeName": "Juan Pérez"}


def _base_form(**overrides):
    """Formulario base con las DOS secciones del DOM: la oculta de ingresos
    (ceros, primera en el DOM) y la visible de deducción."""
    pairs = [
        # Sección oculta de ingresos (display:none cuando es deducción)
        ("amountType", "fixed"),
        ("amount", "0"),
        ("percentage", "0"),
        ("formula", ""),
        # Campos comunes
        ("employeeId", "EMP1"),
        ("contractId", ""),
        ("conceptCode", "DESC001"),
        ("movementType", "deduction"),
        ("deductionSubType", "regular"),
        ("description", "Descuento cooperativa"),
        ("startDate", "2026-01-01"),
        ("indefinite", "on"),
        ("applyFrequency", "every_period"),
        ("priority", "50"),
        ("status", "active"),
        ("notes", ""),
    ]
    for key, value in overrides.items():
        pairs = [(k, v) for k, v in pairs if k != key]
        pairs.append((key, value))
    return MultiDict(pairs)


def test_deduccion_regular_fija_lee_monto_visible():
    form = _base_form(dedAmountType="fixed", dedAmount="5000", dedPercentage="0", dedFormula="")
    data = _parse_recurring_form(form, existing=dict(EXISTING))
    assert data["movementType"] == "deduction"
    assert data["amountType"] == "fixed"
    assert data["amount"] == 5000.0
    assert data["employeeName"] == "Juan Pérez"


def test_deduccion_regular_porcentaje_lee_tipo_y_valor_visible():
    form = _base_form(
        dedAmountType="percentage", dedAmount="0",
        dedPercentage="0.05", dedFormula="",
    )
    data = _parse_recurring_form(form, existing=dict(EXISTING))
    assert data["amountType"] == "percentage"
    assert data["percentage"] == 0.05


def test_prestamo_refleja_cuota_en_amount():
    form = _base_form(
        deductionSubType="loan",
        totalAmount="60000", installmentAmount="2500",
        totalInstallments="24", paidInstallments="0",
        remainingBalance="60000",
    )
    data = _parse_recurring_form(form, existing=dict(EXISTING))
    assert data["isLoan"] is True
    assert data["amountType"] == "fixed"
    assert data["amount"] == 2500.0
    assert data["installmentAmount"] == 2500.0
    assert data["totalAmount"] == 60000.0


def test_embargo_guarda_tipo_y_porcentaje():
    form = _base_form(
        deductionSubType="garnishment",
        garnishmentType="Pensión alimenticia",
        deductionType="percentage",
        deductionPercent="25",
        maxLegalRate="30",
    )
    data = _parse_recurring_form(form, existing=dict(EXISTING))
    assert data["isGarnishment"] is True
    assert data["deductionType"] == "percentage"
    assert data["deductionPercent"] == 25.0


def test_ingreso_sigue_leyendo_seccion_de_ingresos():
    form = MultiDict([
        ("employeeId", "EMP1"),
        ("contractId", ""),
        ("conceptCode", "BONO001"),
        ("movementType", "earning"),
        ("description", "Bono"),
        ("amountType", "fixed"),
        ("amount", "10000"),
        ("percentage", "0"),
        ("formula", ""),
        ("startDate", "2026-01-01"),
        ("indefinite", "on"),
        ("applyFrequency", "every_period"),
        ("priority", "50"),
        ("status", "active"),
        ("notes", ""),
    ])
    data = _parse_recurring_form(form, existing=dict(EXISTING))
    assert data["movementType"] == "earning"
    assert data["amount"] == 10000.0
