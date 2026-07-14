"""
Contabilidad por tipo de comprobante (E31–E47).

Verifica que cada tipo de e-CF genera el asiento contable correcto:

  Ventas (invoice entry):
    E31 Crédito Fiscal    → CxC(debe) / Ventas(haber) + ITBIS(haber)
    E32 Consumo           → CxC o Caja(debe) / Ventas(haber) + ITBIS(haber)
    E33 Nota Débito       → CxC(debe) / Ventas(haber) + ITBIS(haber) [incremento]
    E34 Nota Crédito      → Devoluciones(debe) + ITBIS(debe) / CxC(haber) [reversa]
    E45 Gubernamental     → CxC(debe) / Ventas(haber) [sin ITBIS?]
    E46 Exportación       → CxC(debe) / Ventas Exportación(haber) [sin ITBIS]

  Compras (expense entry):
    E41 Compras           → Compras(debe) + ITBIS crédito(debe) / CxP(haber)
    E43 Gastos Menores    → Gastos(debe) + ITBIS crédito(debe) / CxP(haber)
    E47 Pago al Exterior  → Gastos(debe) / CxP Extranjero(haber) [sin ITBIS]
"""
import pytest
from unittest.mock import patch, MagicMock

TEST_OWNER = "test-owner-uid"
TEST_SANDBOX = True


def _chart():
    return [
        {"id": "acc-cxc",       "code": "1.1.01", "name": "CxC Clientes",
         "usage": "cxc",        "group": "activos",  "type": "movimiento", "nature": "deudora",    "isActive": True},
        {"id": "acc-caja",      "code": "1.1.02", "name": "Caja General",
         "usage": "efectivo",   "group": "activos",  "type": "movimiento", "nature": "deudora",    "isActive": True},
        {"id": "acc-banco",     "code": "1.1.03", "name": "Banco",
         "usage": "banco",      "group": "activos",  "type": "movimiento", "nature": "deudora",    "isActive": True},
        {"id": "acc-ventas",    "code": "4.1.01", "name": "Ingresos por Ventas",
         "usage": "ventas",     "group": "ingresos", "type": "movimiento", "nature": "acreedora",  "isActive": True},
        {"id": "acc-itbis",     "code": "2.1.01", "name": "ITBIS por Pagar",
         "usage": "itbis_pagar","group": "pasivos",  "type": "movimiento", "nature": "acreedora",  "isActive": True},
        {"id": "acc-cxp",       "code": "2.2.01", "name": "CxP Proveedores",
         "usage": "cxp",        "group": "pasivos",  "type": "movimiento", "nature": "acreedora",  "isActive": True},
        {"id": "acc-compras",   "code": "5.1.01", "name": "Compras",
         "usage": "compras",    "group": "costos",   "type": "movimiento", "nature": "deudora",    "isActive": True},
        {"id": "acc-gastos",    "code": "6.1.01", "name": "Gastos Operativos",
         "usage": "gastos",     "group": "gastos",   "type": "movimiento", "nature": "deudora",    "isActive": True},
        {"id": "acc-itbis-cred","code": "1.1.04", "name": "ITBIS Crédito Fiscal",
         "usage": "itbis_credito","group": "activos","type": "movimiento", "nature": "deudora",    "isActive": True},
        {"id": "acc-devol",     "code": "4.1.02", "name": "Devoluciones en Ventas",
         "usage": "devoluciones_ventas","group": "ingresos","type":"movimiento","nature":"deudora","isActive":True},
    ]


def _entry_types():
    return [
        {"id": "INV", "name": "Factura de Venta", "prefix": "A", "isSystem": True},
        {"id": "CXP", "name": "Compra/Gasto",     "prefix": "C", "isSystem": True},
        {"id": "NC",  "name": "Nota de Crédito",  "prefix": "NC","isSystem": True},
    ]


def _verify_balanced(lines):
    total_debit = sum(l["debit"] for l in lines)
    total_credit = sum(l["credit"] for l in lines)
    assert total_debit == pytest.approx(total_credit, abs=0.02), \
        f"Desbalanceado: débitos={total_debit} créditos={total_credit}"


# ======================================================================
# VENTAS (Invoice Entry)
# ======================================================================

class TestVentasAccountingByType:

    def _setup(self, mock_db_class, accounts=None):
        """Configura mock de DatabaseService y retorna saved_entries."""
        accounts = accounts or _chart()
        mock_db_class.get_chart_of_accounts.return_value = accounts
        mock_db_class.get_entry_types.return_value = _entry_types()
        mock_db_class.get_accounting_entries.return_value = []
        mock_db_class.get_next_entry_number.return_value = "A-00001"
        saved = []
        mock_db_class.save_accounting_entry = MagicMock(
            side_effect=lambda uid, eid, entry, sandbox: saved.append(entry)
        )
        return saved

    @patch("app.services.accounting_service.DatabaseService")
    def test_e31_credito_fiscal(self, mock_db):
        """E31: Débito CxC, crédito Ventas + ITBIS."""
        saved = self._setup(mock_db)
        from app.services.accounting_service import AccountingService

        entry = AccountingService.auto_generate_invoice_entry(TEST_OWNER, {
            "id": "inv-e31", "invoiceNumber": "E310000000001",
            "clientId": "c1", "clientName": "Cliente RNC",
            "date": "2026-07-01",
            "subtotal": 100000.0, "totalITBIS": 18000.0,
            "total": 118000.0, "netPayable": 118000.0,
            "paymentType": "Crédito",
        }, sandbox=TEST_SANDBOX)

        assert entry is not None
        lines = saved[0]["lines"]
        _verify_balanced(lines)

        cxc = next(l for l in lines if l["accountId"] == "acc-cxc")
        assert cxc["debit"] == pytest.approx(118000.0)

        ventas = next(l for l in lines if l["accountId"] == "acc-ventas")
        assert ventas["credit"] == pytest.approx(100000.0)

        itbis = next(l for l in lines if l["accountId"] == "acc-itbis")
        assert itbis["credit"] == pytest.approx(18000.0)

    @patch("app.services.accounting_service.DatabaseService")
    def test_e32_consumo_contado(self, mock_db):
        """E32 consumo al contado: Débito Caja, crédito Ventas + ITBIS."""
        saved = self._setup(mock_db)
        from app.services.accounting_service import AccountingService

        entry = AccountingService.auto_generate_invoice_entry(TEST_OWNER, {
            "id": "inv-e32", "invoiceNumber": "E320000000001",
            "clientId": "", "clientName": "Consumidor Final",
            "date": "2026-07-01",
            "subtotal": 5000.0, "totalITBIS": 900.0,
            "total": 5900.0, "netPayable": 5900.0,
            "paymentType": "Contado",
        }, sandbox=TEST_SANDBOX)

        assert entry is not None
        lines = saved[0]["lines"]
        _verify_balanced(lines)

        caja = next(l for l in lines if l["accountId"] == "acc-caja")
        assert caja is not None, "E32 contado debe usar Caja, no CxC"
        assert caja["debit"] == pytest.approx(5900.0)

    @patch("app.services.accounting_service.DatabaseService")
    def test_e33_nota_debito(self, mock_db):
        """E33 Nota de Débito: incremento de CxC + Ventas + ITBIS."""
        saved = self._setup(mock_db)
        from app.services.accounting_service import AccountingService

        entry = AccountingService.auto_generate_invoice_entry(TEST_OWNER, {
            "id": "inv-e33", "invoiceNumber": "E330000000001",
            "clientId": "c1", "clientName": "Cliente A",
            "date": "2026-07-01",
            "subtotal": 10000.0, "totalITBIS": 1800.0,
            "total": 11800.0, "netPayable": 11800.0,
            "paymentType": "Crédito",
        }, sandbox=TEST_SANDBOX)

        assert entry is not None
        lines = saved[0]["lines"]
        _verify_balanced(lines)
        cxc = next(l for l in lines if l["accountId"] == "acc-cxc")
        assert cxc["debit"] == pytest.approx(11800.0)

    @patch("app.services.accounting_service.DatabaseService")
    def test_e34_nota_credito(self, mock_db):
        """E34 Nota de Crédito: reversa (Devoluciones + ITBIS / CxC)."""
        saved = self._setup(mock_db)
        from app.services.accounting_service import AccountingService

        entry = AccountingService.auto_generate_credit_note_entry(TEST_OWNER, {
            "id": "nc-e34", "creditNoteNumber": "E340000000001",
            "clientId": "c1", "clientName": "Cliente A",
            "date": "2026-07-01",
            "subtotal": 10000.0, "totalITBIS": 1800.0,
            "total": 11800.0, "netPayable": 11800.0,
            "originalInvoiceId": "inv-original",
        }, sandbox=TEST_SANDBOX)

        assert entry is not None
        lines = saved[0]["lines"]
        _verify_balanced(lines)

        devol = next(l for l in lines if l["accountId"] == "acc-devol")
        assert devol["debit"] == pytest.approx(10000.0)

    @patch("app.services.accounting_service.DatabaseService")
    def test_e45_gubernamental(self, mock_db):
        """E45 Gubernamental: misma lógica que invoice (sin ITBIS)."""
        saved = self._setup(mock_db)
        from app.services.accounting_service import AccountingService

        entry = AccountingService.auto_generate_invoice_entry(TEST_OWNER, {
            "id": "inv-e45", "invoiceNumber": "E450000000001",
            "clientId": "gov-1", "clientName": "Gobierno",
            "date": "2026-07-01",
            "subtotal": 50000.0, "totalITBIS": 0.0,
            "total": 50000.0, "netPayable": 50000.0,
        }, sandbox=TEST_SANDBOX)

        assert entry is not None
        lines = saved[0]["lines"]
        _verify_balanced(lines)
        itbis = [l for l in lines if l["accountId"] == "acc-itbis"]
        assert len(itbis) == 0, "E45 no debe tener línea de ITBIS"

    @patch("app.services.accounting_service.DatabaseService")
    def test_e46_exportacion(self, mock_db):
        """E46 Exportación: sin ITBIS, usa cuenta de ventas genérica."""
        saved = self._setup(mock_db)
        from app.services.accounting_service import AccountingService

        entry = AccountingService.auto_generate_invoice_entry(TEST_OWNER, {
            "id": "inv-e46", "invoiceNumber": "E460000000001",
            "clientId": "ext-1", "clientName": "Foreign Buyer",
            "date": "2026-07-01",
            "subtotal": 20000.0, "totalITBIS": 0.0,
            "total": 20000.0, "netPayable": 20000.0,
        }, sandbox=TEST_SANDBOX)

        assert entry is not None
        lines = saved[0]["lines"]
        _verify_balanced(lines)
        itbis = [l for l in lines if l["accountId"] == "acc-itbis"]
        assert len(itbis) == 0, "E46 no debe tener ITBIS"
        ventas = next(l for l in lines if l["accountId"] == "acc-ventas")
        assert ventas["credit"] == pytest.approx(20000.0)


# ======================================================================
# COMPRAS (Expense Entry)
# ======================================================================

class TestComprasAccountingByType:

    def _setup(self, mock_db_class):
        mock_db_class.get_chart_of_accounts.return_value = _chart()
        mock_db_class.get_entry_types.return_value = _entry_types()
        mock_db_class.get_accounting_entries.return_value = []
        mock_db_class.get_next_entry_number.return_value = "C-00001"
        saved = []
        mock_db_class.save_accounting_entry = MagicMock(
            side_effect=lambda uid, eid, entry, sandbox: saved.append(entry)
        )
        return saved

    @patch("app.services.accounting_service.DatabaseService")
    def test_e41_compras(self, mock_db):
        """E41: Débito Compras + ITBIS crédito, crédito CxP."""
        saved = self._setup(mock_db)
        from app.services.accounting_service import AccountingService

        entry = AccountingService.auto_generate_expense_entry(TEST_OWNER, {
            "id": "exp-e41", "ncf": "E410000000001",
            "concept": "Compra de mercancía", "supplierName": "Proveedor SRL",
            "amount": 59000.0, "itbisAmount": 9000.0,
            "total": 59000.0, "isCost": True,
            "date": "2026-07-01",
            "paymentType": "Crédito",
        }, sandbox=TEST_SANDBOX)

        assert entry is not None
        lines = saved[0]["lines"]
        _verify_balanced(lines)

        compras = next(l for l in lines if l["accountId"] == "acc-compras")
        # amount - itbis = 59000 - 9000 = 50000
        assert compras["debit"] == pytest.approx(50000.0)

        itbis_cred = next(l for l in lines if l["accountId"] == "acc-itbis-cred")
        assert itbis_cred["debit"] == pytest.approx(9000.0)

        cxp = next(l for l in lines if l["accountId"] == "acc-cxp")
        assert cxp["credit"] == pytest.approx(59000.0)

    @patch("app.services.accounting_service.DatabaseService")
    def test_e43_gastos_menores(self, mock_db):
        """E43: Débito Gastos + ITBIS crédito, crédito CxP."""
        saved = self._setup(mock_db)
        from app.services.accounting_service import AccountingService

        entry = AccountingService.auto_generate_expense_entry(TEST_OWNER, {
            "id": "exp-e43", "ncf": "E430000000001",
            "concept": "Papelería", "supplierName": "Papelería X",
            "amount": 9440.0, "itbisAmount": 1440.0,
            "total": 9440.0, "isCost": False,
            "date": "2026-07-01",
            "paymentType": "Crédito",
        }, sandbox=TEST_SANDBOX)

        assert entry is not None
        lines = saved[0]["lines"]
        _verify_balanced(lines)

        gastos = next(l for l in lines if l["accountId"] == "acc-gastos")
        # amount - itbis = 9440 - 1440 = 8000
        assert gastos["debit"] == pytest.approx(8000.0)

    @patch("app.services.accounting_service.DatabaseService")
    def test_e47_pago_exterior(self, mock_db):
        """E47 Pago al Exterior: sin ITBIS, gasto directo."""
        saved = self._setup(mock_db)
        from app.services.accounting_service import AccountingService

        entry = AccountingService.auto_generate_expense_entry(TEST_OWNER, {
            "id": "exp-e47", "ncf": "E470000000001",
            "concept": "Servicio cloud", "supplierName": "AWS Inc.",
            "amount": 10000.0, "itbisAmount": 0.0,
            "total": 10000.0, "isCost": False,
            "date": "2026-07-01",
            "paymentType": "Crédito",
        }, sandbox=TEST_SANDBOX)

        assert entry is not None
        lines = saved[0]["lines"]
        _verify_balanced(lines)
        itbis = [l for l in lines if "itbis" in l["accountId"]]
        assert len(itbis) == 0, "E47 no debe tener ITBIS"
        gastos = next(l for l in lines if l["accountId"] == "acc-gastos")
        assert gastos["debit"] == pytest.approx(10000.0)
