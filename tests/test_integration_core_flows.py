"""
Tests de integración para flujos críticos del ERP.

Cubre los 4 flujos definidos en el Plan de Evolución (Fase 1.3):
1. Factura de venta → Asiento contable
2. Gasto → Asiento CxP
3. Depreciación de activo → Asientos
4. Orden de compra → Recepción → Factura proveedor → Pago

Parte del Plan de Evolución ERP - Fase 1.3: Cobertura de tests.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

# ── Helpers ──────────────────────────────────────────────────────────

TEST_OWNER = "test-owner-uid"
TEST_SANDBOX = True


def _mock_chart_of_accounts():
    """Retorna un catálogo de cuentas mínimo con usos definidos."""
    return [
        {"id": "acc-cxc", "code": "1.1.01", "name": "Cuentas por Cobrar",
         "usage": "cxc", "group": "activos", "type": "movimiento", "level": 1,
         "nature": "deudora", "isActive": True},
        {"id": "acc-ventas", "code": "4.1.01", "name": "Ingresos por Ventas",
         "usage": "ventas", "group": "ingresos", "type": "movimiento", "level": 1,
         "nature": "acreedora", "isActive": True},
        {"id": "acc-itbis", "code": "2.1.01", "name": "ITBIS por Pagar",
         "usage": "itbis_pagar", "group": "pasivos", "type": "movimiento", "level": 1,
         "nature": "acreedora", "isActive": True},
        {"id": "acc-cxp", "code": "2.2.01", "name": "Cuentas por Pagar",
         "usage": "cxp", "group": "pasivos", "type": "movimiento", "level": 1,
         "nature": "acreedora", "isActive": True},
        {"id": "acc-compras", "code": "5.1.01", "name": "Compras",
         "usage": "compras", "group": "costos", "type": "movimiento", "level": 1,
         "nature": "deudora", "isActive": True},
        {"id": "acc-gastos", "code": "6.1.01", "name": "Gastos Operativos",
         "usage": "gastos", "group": "gastos", "type": "movimiento", "level": 1,
         "nature": "deudora", "isActive": True},
        {"id": "acc-itbis-cred", "code": "2.1.02", "name": "ITBIS Crédito Fiscal",
         "usage": "itbis_credito", "group": "pasivos", "type": "movimiento", "level": 1,
         "nature": "deudora", "isActive": True},
        {"id": "acc-devol", "code": "4.1.02", "name": "Devoluciones en Ventas",
         "usage": "devoluciones_ventas", "group": "ingresos", "type": "movimiento", "level": 1,
         "nature": "deudora", "isActive": True},
        {"id": "acc-banco", "code": "1.2.01", "name": "Banco",
         "usage": "banco", "group": "activos", "type": "movimiento", "level": 1,
         "nature": "deudora", "isActive": True},
        {"id": "acc-inventario", "code": "1.3.01", "name": "Inventario",
         "usage": "inventario", "group": "activos", "type": "movimiento", "level": 1,
         "nature": "deudora", "isActive": True},
    ]


def _mock_entry_types():
    return [
        {"id": "INV", "name": "Factura de Venta", "prefix": "A", "isSystem": True},
        {"id": "CXP", "name": "Compra/Gasto", "prefix": "C", "isSystem": True},
        {"id": "DP", "name": "Depreciación", "prefix": "DP", "isSystem": True},
        {"id": "ED", "name": "Entrada de Diario", "prefix": "ED", "isSystem": True},
    ]


# ── Flow 1: Factura → Asiento Contable ──────────────────────────────


class TestInvoiceToAccountingEntry:
    """Flujo: emitir factura de venta → generar asiento contable automático."""

    @patch("app.services.accounting_service.DatabaseService")
    def test_invoice_generates_accounting_entry(self, mock_db):
        """Una factura con ITBIS genera débito a CxC, crédito a Ventas e ITBIS."""
        mock_db.get_chart_of_accounts.return_value = _mock_chart_of_accounts()
        mock_db.get_entry_types.return_value = _mock_entry_types()
        mock_db.get_accounting_entries.return_value = []
        mock_db.get_next_entry_number.return_value = "A-00001"

        saved_entries = []
        mock_db.save_accounting_entry = MagicMock(
            side_effect=lambda uid, eid, entry, sandbox: saved_entries.append(entry)
        )

        from app.services.accounting_service import AccountingService

        invoice = {
            "id": "inv-001",
            "invoiceNumber": "F001-00001",
            "clientId": "client-a",
            "clientName": "Cliente A",
            "date": "2026-07-01",
            "subtotal": 100000.00,
            "totalITBIS": 18000.00,
            "total": 118000.00,
            "netPayable": 118000.00,
            "currency": "DOP",
            "ecfType": "Factura de Crédito Fiscal (E31)",
            "paymentMethod": "Transferencia",
        }

        entry = AccountingService.auto_generate_invoice_entry(
            TEST_OWNER, invoice, sandbox=TEST_SANDBOX
        )

        assert entry is not None
        assert len(saved_entries) == 1
        saved = saved_entries[0]
        assert saved["referenceType"] == "invoice"
        assert saved["referenceId"] == "inv-001"
        assert saved["status"] == "active"

        lines = saved["lines"]
        assert len(lines) >= 2  # CxC + Ventas, mínimo

        # Verificar línea de CxC (débito)
        cxc_line = next((l for l in lines if l["accountId"] == "acc-cxc"), None)
        assert cxc_line is not None
        assert cxc_line["debit"] == pytest.approx(118000.00, abs=0.01)
        assert cxc_line["credit"] == 0.0

        # Verificar línea de Ventas (crédito)
        sales_line = next((l for l in lines if l["accountId"] == "acc-ventas"), None)
        assert sales_line is not None
        assert sales_line["credit"] == pytest.approx(100000.00, abs=0.01)

        # Verificar línea de ITBIS (crédito)
        itbis_line = next((l for l in lines if l["accountId"] == "acc-itbis"), None)
        assert itbis_line is not None
        assert itbis_line["credit"] == pytest.approx(18000.00, abs=0.01)

    @patch("app.services.accounting_service.DatabaseService")
    def test_invoice_no_duplicate_entry(self, mock_db):
        """No genera asiento duplicado si ya existe uno para la misma factura."""
        mock_db.get_chart_of_accounts.return_value = _mock_chart_of_accounts()
        mock_db.get_accounting_entries.return_value = [
            {
                "id": "entry-existing",
                "referenceType": "invoice",
                "referenceId": "inv-001",
                "status": "active",
                "number": "A-00001",
                "date": "2026-07-01",
                "lines": [],
            }
        ]

        from app.services.accounting_service import AccountingService

        invoice = {
            "id": "inv-001",
            "invoiceNumber": "F001-00001",
            "subtotal": 10000, "totalITBIS": 1800, "total": 11800, "netPayable": 11800,
            "date": "2026-07-01",
        }

        result = AccountingService.auto_generate_invoice_entry(
            TEST_OWNER, invoice, sandbox=TEST_SANDBOX
        )

        assert result is None

    @patch("app.services.accounting_service.DatabaseService")
    def test_invoice_with_retentions(self, mock_db):
        """Factura con ISR e ITBIS retenidos genera líneas adicionales."""
        mock_db.get_chart_of_accounts.return_value = _mock_chart_of_accounts() + [
            {"id": "acc-itbis-ret", "code": "2.1.03", "name": "ITBIS Retenido",
             "usage": "itbis_retenido", "group": "pasivos", "type": "movimiento", "level": 1,
             "nature": "deudora", "isActive": True},
            {"id": "acc-isr-ret", "code": "2.3.01", "name": "ISR Retenido",
             "usage": "isr_retenido", "group": "pasivos", "type": "movimiento", "level": 1,
             "nature": "deudora", "isActive": True},
        ]
        mock_db.get_entry_types.return_value = _mock_entry_types()
        mock_db.get_accounting_entries.return_value = []
        mock_db.get_next_entry_number.return_value = "A-00002"

        saved_entries = []
        mock_db.save_accounting_entry = MagicMock(
            side_effect=lambda uid, eid, entry, sandbox: saved_entries.append(entry)
        )

        from app.services.accounting_service import AccountingService

        invoice = {
            "id": "inv-002",
            "invoiceNumber": "F001-00002",
            "subtotal": 50000.00,
            "totalITBIS": 9000.00,
            "retainedISR": 5000.00,
            "retainedITBIS": 9000.00,
            "total": 59000.00,
            "netPayable": 45000.00,  # 50000 + 9000 - 5000 - 9000
            "date": "2026-07-02",
            "currency": "DOP",
        }

        entry = AccountingService.auto_generate_invoice_entry(
            TEST_OWNER, invoice, sandbox=TEST_SANDBOX
        )

        assert entry is not None
        lines = saved_entries[0]["lines"]

        # CxC debe ser 45000 (netPayable, no el total)
        cxc_line = next((l for l in lines if l["accountId"] == "acc-cxc"), None)
        assert cxc_line["debit"] == pytest.approx(45000.00, abs=0.01)

        # ITBIS retenido (débito)
        itbis_ret = next((l for l in lines if l["accountId"] == "acc-itbis-ret"), None)
        assert itbis_ret is not None
        assert itbis_ret["debit"] == pytest.approx(9000.00, abs=0.01)

        # ISR retenido (débito)
        isr_ret = next((l for l in lines if l["accountId"] == "acc-isr-ret"), None)
        assert isr_ret is not None
        assert isr_ret["debit"] == pytest.approx(5000.00, abs=0.01)

        # Cuadratura: suma débitos = suma créditos
        total_debit = sum(l["debit"] for l in lines)
        total_credit = sum(l["credit"] for l in lines)
        assert total_debit == pytest.approx(total_credit, abs=0.02)


# ── Flow 2: Gasto → Asiento CxP ─────────────────────────────────────

class TestExpenseToCxPEntry:
    """Flujo: registrar gasto → generar asiento de CxP."""

    @patch("app.services.accounting_service.DatabaseService")
    def test_expense_generates_cxp_entry(self, mock_db):
        """Un gasto operativo genera débito a Gastos y crédito a CxP."""
        mock_db.get_chart_of_accounts.return_value = _mock_chart_of_accounts()
        mock_db.get_entry_types.return_value = _mock_entry_types()
        mock_db.get_accounting_entries.return_value = []
        mock_db.get_next_entry_number.return_value = "C-00001"

        saved_entries = []
        mock_db.save_accounting_entry = MagicMock(
            side_effect=lambda uid, eid, entry, sandbox: saved_entries.append(entry)
        )

        from app.services.accounting_service import AccountingService

        expense = {
            "id": "exp-001",
            "ncf": "E310000000001",
            "concept": "Servicio de consultoría",
            "supplierName": "Proveedor SRL",
            "amount": 50000.00,
            "itbisAmount": 9000.00,
            "total": 59000.00,
            "isCost": False,  # Es gasto, no costo
            "date": "2026-07-03",
        }

        entry = AccountingService.auto_generate_expense_entry(
            TEST_OWNER, expense, sandbox=TEST_SANDBOX
        )

        assert entry is not None
        assert len(saved_entries) == 1
        saved = saved_entries[0]
        assert saved["referenceType"] == "expense"

        lines = saved["lines"]
        assert len(lines) >= 2

        # Verificar línea de Gasto (débito al neto sin ITBIS)
        gasto_line = next((l for l in lines if l["accountId"] == "acc-gastos"), None)
        assert gasto_line is not None
        assert gasto_line["debit"] == pytest.approx(50000.00, abs=0.01)

        # Verificar línea de CxP (crédito)
        cxp_line = next((l for l in lines if l["accountId"] == "acc-cxp"), None)
        assert cxp_line is not None
        assert cxp_line["credit"] == pytest.approx(59000.00, abs=0.01)


    @patch("app.services.accounting_service.DatabaseService")
    def test_cost_purchase_uses_compras_account(self, mock_db):
        """Un gasto marcado como costo usa cuenta de Compras en lugar de Gastos."""
        mock_db.get_chart_of_accounts.return_value = _mock_chart_of_accounts()
        mock_db.get_entry_types.return_value = _mock_entry_types()
        mock_db.get_accounting_entries.return_value = []
        mock_db.get_next_entry_number.return_value = "C-00002"

        saved_entries = []
        mock_db.save_accounting_entry = MagicMock(
            side_effect=lambda uid, eid, entry, sandbox: saved_entries.append(entry)
        )

        from app.services.accounting_service import AccountingService

        expense = {
            "id": "exp-002",
            "ncf": "E310000000002",
            "concept": "Compra de mercancía",
            "supplierName": "Distribuidora XYZ",
            "amount": 100000.00,
            "itbisAmount": 0.00,
            "total": 100000.00,
            "isCost": True,
            "date": "2026-07-04",
        }

        entry = AccountingService.auto_generate_expense_entry(
            TEST_OWNER, expense, sandbox=TEST_SANDBOX
        )

        assert entry is not None
        lines = saved_entries[0]["lines"]

        # Debe usar Compras, no Gastos
        compras_line = next((l for l in lines if l["accountId"] == "acc-compras"), None)
        assert compras_line is not None
        assert compras_line["debit"] == pytest.approx(100000.00, abs=0.01)


# ── Flow 3: Depreciación → Asientos ─────────────────────────────────

class TestDepreciationToEntries:
    """Flujo: depreciar activo fijo → generar asientos de depreciación."""

    @patch("app.services.accounting_service.DatabaseService")
    def test_depreciation_generates_correct_entry(self, mock_db):
        """La depreciación genera débito a Gasto Depreciación y crédito a Dep. Acumulada."""
        mock_db.get_chart_of_accounts.return_value = _mock_chart_of_accounts()
        mock_db.get_entry_types.return_value = _mock_entry_types()
        mock_db.get_accounting_entries.return_value = []
        mock_db.get_next_entry_number.return_value = "DP-00001"

        saved_entries = []
        mock_db.save_accounting_entry = MagicMock(
            side_effect=lambda uid, eid, entry, sandbox: saved_entries.append(entry)
        )

        from app.services.accounting_service import AccountingService

        dep_data = {
            "asset_id": "asset-001",
            "asset_name": "Vehículo Toyota",
            "amount": 15000.00,
            "expense_account_id": "acc-gastos",
            "accum_account_id": "acc-cxp",  # Usamos CxP como proxy de Dep.Acum.
            "period": "mensual",
            "code": "AF-001",
        }

        entry = AccountingService.auto_generate_depreciation_entry(
            TEST_OWNER, dep_data, sandbox=TEST_SANDBOX
        )

        assert entry is not None
        assert len(saved_entries) == 1
        saved = saved_entries[0]
        assert saved["referenceType"] == "depreciation"
        assert saved["referenceId"] == "asset-001"

        lines = saved["lines"]
        assert len(lines) == 2

        # Débito a Gasto Depreciación
        debit_line = next((l for l in lines if l["debit"] > 0), None)
        assert debit_line is not None
        assert debit_line["accountId"] == "acc-gastos"
        assert debit_line["debit"] == pytest.approx(15000.00, abs=0.01)

        # Crédito a Depreciación Acumulada
        credit_line = next((l for l in lines if l["credit"] > 0), None)
        assert credit_line is not None
        assert credit_line["accountId"] == "acc-cxp"
        assert credit_line["credit"] == pytest.approx(15000.00, abs=0.01)

    @patch("app.services.accounting_service.DatabaseService")
    def test_depreciation_no_duplicate(self, mock_db):
        """No genera asiento duplicado para el mismo activo."""
        mock_db.get_accounting_entries.return_value = [
            {
                "id": "dp-exist",
                "referenceType": "depreciation",
                "referenceId": "asset-001",
                "status": "active",
                "number": "DP-00001",
                "date": "2026-07-01",
                "lines": [],
            }
        ]

        from app.services.accounting_service import AccountingService

        dep_data = {
            "asset_id": "asset-001",
            "asset_name": "Vehículo Toyota",
            "amount": 15000.00,
            "expense_account_id": "acc-gastos",
            "accum_account_id": "acc-cxp",
            "period": "mensual",
        }

        result = AccountingService.auto_generate_depreciation_entry(
            TEST_OWNER, dep_data, sandbox=TEST_SANDBOX
        )

        assert result is None

    @patch("app.services.accounting_service.DatabaseService")
    def test_depreciation_with_fixed_asset_service(self, mock_db):
        """Flujo completo: FixedAssetService.register_depreciation genera entrada correcta."""
        mock_db.get_chart_of_accounts.return_value = _mock_chart_of_accounts()
        mock_db.get_entry_types.return_value = _mock_entry_types()
        mock_db.get_accounting_entries.return_value = []
        mock_db.get_next_entry_number.return_value = "DP-00002"

        saved_entries = []
        mock_db.save_accounting_entry = MagicMock(
            side_effect=lambda uid, eid, entry, sandbox: saved_entries.append(entry)
        )

        # Mock del activo en Firestore
        mock_asset = {
            "id": "asset-002",
            "name": "Laptop Dell",
            "code": "AF-002",
            "purchaseAmount": 60000.00,
            "residualValue": 6000.00,
            "currentValue": 60000.00,
            "accumulatedDepreciation": 0.0,
            "usefulLife": 36,
            "depreciationMethod": "lineal",
            "depreciationPeriod": "mensual",
            "depreciationExpenseAccountId": "acc-gastos",
            "depreciationAccountId": "acc-cxp",
            "accountId": "acc-inventario",
            "status": "active",
            "lastDepreciationDate": None,
            "nextDepreciationDate": "2026-07-15",
        }
        mock_db.get_fixed_asset.return_value = mock_asset
        mock_db.save_fixed_asset = MagicMock()

        from app.services.fixed_asset_service import FixedAssetService

        result = FixedAssetService.register_depreciation(
            TEST_OWNER, "asset-002", sandbox=TEST_SANDBOX
        )

        assert result is not None
        assert result["amount"] > 0

        # Depreciación lineal mensual: (60000 - 6000) / 36 = 1500.00
        expected_amount = round((60000.00 - 6000.00) / 36, 2)
        assert result["amount"] == pytest.approx(expected_amount, abs=0.01)

        # Verificar entrada contable
        assert len(saved_entries) == 1
        saved = saved_entries[0]
        assert saved["referenceType"] == "depreciation"

        lines = saved["lines"]
        assert lines[0]["debit"] == pytest.approx(expected_amount, abs=0.01)
        assert lines[1]["credit"] == pytest.approx(expected_amount, abs=0.01)

        # Verificar que el activo se actualizó
        assert mock_db.save_fixed_asset.called
        call_args = mock_db.save_fixed_asset.call_args
        updated_asset = call_args[0][3]  # 4to argumento posicional
        assert updated_asset["accumulatedDepreciation"] == pytest.approx(expected_amount, abs=0.01)
        assert updated_asset["currentValue"] == pytest.approx(60000.00 - expected_amount, abs=0.01)


# ── Flow 4: Orden de Compra → Recepción → Factura ───────────────────

class TestPurchaseFlow:
    """Flujo: orden de compra → recepción → factura proveedor → pago."""

    @patch("app.services.accounting_service.DatabaseService")
    def test_purchase_order_to_invoice_accounting(self, mock_db):
        """Simula el flujo contable de una orden de compra convertida a gasto."""
        mock_db.get_chart_of_accounts.return_value = _mock_chart_of_accounts()
        mock_db.get_entry_types.return_value = _mock_entry_types()
        mock_db.get_accounting_entries.return_value = []
        mock_db.get_next_entry_number.return_value = "C-00010"

        saved_entries = []
        mock_db.save_accounting_entry = MagicMock(
            side_effect=lambda uid, eid, entry, sandbox: saved_entries.append(entry)
        )

        from app.services.accounting_service import AccountingService

        # Paso 1: Registrar gasto de mercancía (simula recepción + factura proveedor)
        purchase_expense = {
            "id": "po-001",
            "ncf": "E310000000100",
            "concept": "Compra de materiales — OC-2026-001",
            "supplierName": "Materiales Industriales SRL",
            "amount": 85000.00,
            "itbisAmount": 15300.00,
            "total": 100300.00,
            "isCost": True,  # Es costo (inventario/compra)
            "date": "2026-07-05",
        }

        entry = AccountingService.auto_generate_expense_entry(
            TEST_OWNER, purchase_expense, sandbox=TEST_SANDBOX
        )

        assert entry is not None
        assert len(saved_entries) == 1
        saved = saved_entries[0]

        # Débito a Compras por el neto
        compras_line = next((l for l in saved["lines"] if l["accountId"] == "acc-compras"), None)
        assert compras_line is not None
        assert compras_line["debit"] == pytest.approx(85000.00, abs=0.01)

        # ITBIS crédito fiscal
        itbis_line = next((l for l in saved["lines"] if l["accountId"] == "acc-itbis-cred"), None)
        assert itbis_line is not None
        assert itbis_line["debit"] == pytest.approx(15300.00, abs=0.01)

        # Crédito a CxP por el total
        cxp_line = next((l for l in saved["lines"] if l["accountId"] == "acc-cxp"), None)
        assert cxp_line is not None
        assert cxp_line["credit"] == pytest.approx(100300.00, abs=0.01)

        # Cuadratura
        total_debit = sum(l["debit"] for l in saved["lines"])
        total_credit = sum(l["credit"] for l in saved["lines"])
        assert total_debit == pytest.approx(total_credit, abs=0.02)

    @patch("app.services.accounting_service.DatabaseService")
    def test_credit_note_generates_reversal(self, mock_db):
        """Una nota de crédito genera asiento de reverso de ventas."""
        mock_db.get_chart_of_accounts.return_value = _mock_chart_of_accounts()
        mock_db.get_entry_types.return_value = _mock_entry_types()
        mock_db.get_accounting_entries.return_value = []
        mock_db.get_next_entry_number.return_value = "A-00010"

        saved_entries = []
        mock_db.save_accounting_entry = MagicMock(
            side_effect=lambda uid, eid, entry, sandbox: saved_entries.append(entry)
        )

        from app.services.accounting_service import AccountingService

        credit_note = {
            "id": "nc-001",
            "invoiceNumber": "NC-00001",
            "clientName": "Cliente A",
            "subtotal": 20000.00,
            "totalITBIS": 3600.00,
            "total": 23600.00,
            "netPayable": 23600.00,
            "date": "2026-07-06",
            "currency": "DOP",
        }

        entry = AccountingService.auto_generate_credit_note_entry(
            TEST_OWNER, credit_note, sandbox=TEST_SANDBOX
        )

        assert entry is not None
        saved = saved_entries[0]
        assert saved["referenceType"] == "credit_note"

        lines = saved["lines"]
        # Débito a Devoluciones en Ventas
        devol_line = next((l for l in lines if l["accountId"] == "acc-devol"), None)
        assert devol_line is not None
        assert devol_line["debit"] == pytest.approx(20000.00, abs=0.01)

        # Crédito a CxC por el total
        cxc_line = next((l for l in lines if l["accountId"] == "acc-cxc"), None)
        assert cxc_line is not None
        assert cxc_line["credit"] == pytest.approx(23600.00, abs=0.01)


# ── Event Bus Integration ────────────────────────────────────────────

class TestEventBusIntegration:
    """Verifica que el Event Bus se inicializa y los handlers funcionan."""

    def test_event_bus_initialization(self):
        """El EventBus se inicializa en modo in-process por defecto."""
        from app.events import get_event_bus, init_event_bus

        bus = init_event_bus()  # Sin Redis
        assert bus is not None

        # Re-obtener la misma instancia
        bus2 = get_event_bus()
        assert bus2 is bus

    def test_event_bus_publish_and_subscribe(self):
        """Publicar un evento ejecuta el handler suscrito en un thread."""
        from app.events import (
            get_event_bus, init_event_bus,
            InvoiceEmitted, PaymentRegistered,
        )
        import time

        bus = init_event_bus()
        received = []

        def _handler(event):
            received.append(event.event_type)

        bus.subscribe("InvoiceEmitted", _handler)

        event = InvoiceEmitted(
            owner_uid=TEST_OWNER,
            invoice_id="inv-test",
            invoice_number="F001-TEST",
            invoice_data={"total": 1000},
            sandbox=True,
            country="DO",
        )
        bus.publish(event)

        # Esperar un poco para que el thread se ejecute
        time.sleep(0.2)

        assert len(received) >= 1
        assert "InvoiceEmitted" in received

    def test_payment_registered_event_logs(self):
        """PaymentRegistered no crashea aunque no tenga lógica completa aún."""
        from app.events import get_event_bus, init_event_bus, PaymentRegistered

        bus = init_event_bus()

        event = PaymentRegistered(
            owner_uid=TEST_OWNER,
            payment_id="pay-001",
            invoice_id="inv-001",
            invoice_number="F001-00001",
            payment_data={"amount": 5000},
            sandbox=True,
            country="DO",
        )

        # No debe lanzar excepción
        bus.publish(event)
