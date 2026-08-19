"""
Tests del motor de reglas de contabilización (AccountingRulesService).

Criterio de aceptación #1: con las reglas por defecto (o sin reglas), los
asientos generados son idénticos a los que se generaban antes del motor.
"""
import pytest
from unittest.mock import MagicMock, patch

from app.services.accounting_rules_service import AccountingRulesService, TRANSACTIONS, CONDITIONS

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
        {"id": "acc-ventas-2",  "code": "4.1.07", "name": "Ventas Nacionales",
         "usage": None,         "group": "ingresos", "type": "movimiento", "nature": "acreedora",  "isActive": True},
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
         "usage": "devoluciones_ventas", "group": "ingresos", "type": "movimiento", "nature": "deudora", "isActive": True},
        {"id": "acc-inv",       "code": "1.1.05", "name": "Inventario",
         "usage": "inventario", "group": "activos",  "type": "movimiento", "nature": "deudora",    "isActive": True},
        {"id": "acc-cogs",      "code": "5.1.02", "name": "Costo de Ventas",
         "usage": "costo_ventas","group": "costos",  "type": "movimiento", "nature": "deudora",    "isActive": True},
        {"id": "acc-anticipo",  "code": "2.1.05", "name": "Anticipos de Clientes",
         "usage": "anticipos_recibidos", "group": "pasivos", "type": "movimiento", "nature": "acreedora", "isActive": True},
        {"id": "acc-ret-afavor","code": "1.1.06", "name": "Retenciones a favor",
         "usage": "retenciones_a_favor", "group": "activos", "type": "movimiento", "nature": "deudora", "isActive": True},
    ]


# ======================================================================
# INTEGRIDAD DEL CATÁLOGO
# ======================================================================

class TestCatalogIntegrity:

    def test_transacciones_con_conceptos(self):
        assert "venta" in TRANSACTIONS
        assert "nota_credito" in TRANSACTIONS
        assert "gasto" in TRANSACTIONS
        assert "nomina" in TRANSACTIONS
        assert "venta" != "nota_credito"
        for tx, txdef in TRANSACTIONS.items():
            assert txdef.get("label")
            assert txdef.get("concepts")
            for concept, cdef in txdef["concepts"].items():
                assert cdef.get("side") in ("debit", "credit")
                assert cdef.get("label")

    def test_condiciones_referenciadas_existen(self):
        for tx, txdef in TRANSACTIONS.items():
            for concept, cdef in txdef["concepts"].items():
                for cond in cdef.get("conditions", []):
                    assert cond["key"] in CONDITIONS, f"{tx}.{concept}: condición {cond['key']} desconocida"


# ======================================================================
# RESOLUCIÓN CON REGLAS VACÍAS (COMPORTAMIENTO ACTUAL)
# ======================================================================

class TestResolveFallback:

    def test_venta_deudor_efectivo(self):
        acc = AccountingRulesService.resolve(TEST_OWNER, "venta", "venta_deudor",
                                             {"payment_type": "Contado", "payment_method": "Efectivo"},
                                             _chart(), rules=[])
        assert acc and acc["id"] == "acc-caja"

    def test_venta_deudor_tarjeta(self):
        acc = AccountingRulesService.resolve(TEST_OWNER, "venta", "venta_deudor",
                                             {"payment_type": "Contado", "payment_method": "Tarjeta de Crédito"},
                                             _chart(), rules=[])
        assert acc and acc["id"] == "acc-banco"

    def test_venta_deudor_transferencia(self):
        acc = AccountingRulesService.resolve(TEST_OWNER, "venta", "venta_deudor",
                                             {"payment_type": "Contado", "payment_method": "Transferencia"},
                                             _chart(), rules=[])
        assert acc and acc["id"] == "acc-banco"

    def test_venta_deudor_credito(self):
        acc = AccountingRulesService.resolve(TEST_OWNER, "venta", "venta_deudor",
                                             {"payment_type": "Crédito", "payment_method": "Efectivo"},
                                             _chart(), rules=[])
        assert acc and acc["id"] == "acc-cxc"

    def test_gasto_deudor_contado(self):
        acc = AccountingRulesService.resolve(TEST_OWNER, "gasto", "gasto_deudor",
                                             {"payment_type": "Contado"}, _chart(), rules=[])
        assert acc and acc["id"] == "acc-banco"

    def test_gasto_deudor_credito(self):
        acc = AccountingRulesService.resolve(TEST_OWNER, "gasto", "gasto_deudor",
                                             {"payment_type": "Crédito"}, _chart(), rules=[])
        assert acc and acc["id"] == "acc-cxp"

    def test_anticipo_deudor_tarjeta(self):
        acc = AccountingRulesService.resolve(TEST_OWNER, "anticipo_cliente", "anticipo_deudor",
                                             {"payment_method": "Tarjeta de Débito"}, _chart(), rules=[])
        assert acc and acc["id"] == "acc-banco"

    def test_anticipo_deudor_efectivo(self):
        acc = AccountingRulesService.resolve(TEST_OWNER, "anticipo_cliente", "anticipo_deudor",
                                             {"payment_method": "Efectivo"}, _chart(), rules=[])
        assert acc and acc["id"] == "acc-caja"


# ======================================================================
# SEED + REGLAS PERSONALIZADAS
# ======================================================================

class TestSeedAndCustomRules:

    def _seed(self, accounts):
        saved = []
        with patch("app.services.accounting_rules_service.DatabaseService") as mock_db:
            mock_db.get_accounting_rules.return_value = []
            mock_db.get_chart_of_accounts.return_value = accounts
            mock_db.save_accounting_rule.side_effect = lambda uid, rid, rule, company_id: saved.append(rule)
            result = AccountingRulesService.ensure_initialized(TEST_OWNER)
        return result, saved

    def test_ensure_initialized_siembra_reglas(self):
        result, saved = self._seed(_chart())
        assert result is True
        assert len(saved) > 0
        concepts = {(r["transaction"], r["concept"]) for r in saved}
        assert ("venta", "venta_deudor") in concepts
        assert ("venta", "venta_ingresos") in concepts
        deudor_default = next(r for r in saved if r["transaction"] == "venta" and r["concept"] == "venta_deudor" and not r["conditionKey"])
        assert deudor_default["accountId"] == "acc-cxc"

    def test_ensure_initialized_idempotente(self):
        with patch("app.services.accounting_rules_service.DatabaseService") as mock_db:
            mock_db.get_accounting_rules.return_value = [{"id": "x"}]
            result = AccountingRulesService.ensure_initialized(TEST_OWNER)
        assert result is False

    def test_regla_personalizada_tiene_precedencia(self):
        rules = [{
            "id": "venta::venta_ingresos:::", "transaction": "venta", "concept": "venta_ingresos",
            "conditionKey": "", "conditionValue": "", "accountId": "acc-ventas-2",
            "isCustom": True, "isActive": True,
        }]
        acc = AccountingRulesService.resolve(TEST_OWNER, "venta", "venta_ingresos", {}, _chart(), rules=rules)
        assert acc and acc["id"] == "acc-ventas-2"

    def test_regla_condicion_especifica_gana_sobre_default(self):
        rules = [
            {"id": "r1", "transaction": "venta", "concept": "venta_deudor",
             "conditionKey": "", "conditionValue": "", "accountId": "acc-cxc", "isCustom": False, "isActive": True},
            {"id": "r2", "transaction": "venta", "concept": "venta_deudor",
             "conditionKey": "pago_efectivo", "conditionValue": "", "accountId": "acc-caja", "isCustom": False, "isActive": True},
        ]
        acc = AccountingRulesService.resolve(TEST_OWNER, "venta", "venta_deudor",
                                             {"payment_type": "Contado", "payment_method": "Efectivo"},
                                             _chart(), rules=rules)
        assert acc and acc["id"] == "acc-caja"

    def test_rules_referencing_account(self):
        rules = [{"id": "r1", "accountId": "acc-ventas-2", "isActive": True}]
        with patch("app.services.accounting_rules_service.DatabaseService") as mock_db:
            mock_db.get_accounting_rules.return_value = rules
            used = AccountingRulesService.rules_referencing_account(TEST_OWNER, "acc-ventas-2")
        assert len(used) == 1

    def test_get_rules_tolera_mock_no_lista(self):
        with patch("app.services.accounting_rules_service.DatabaseService") as mock_db:
            mock_db.get_accounting_rules.return_value = MagicMock()
            assert AccountingRulesService.get_rules(TEST_OWNER) == []


# ======================================================================
# CRITERIO DE ACEPTACIÓN #1: IGUALDAD DE ASIENTOS (antes/después del motor)
# ======================================================================

class TestEntryEquality:

    def _setup_mock(self, mock_db_class, mock_rules_db, rules):
        mock_db_class.get_chart_of_accounts.return_value = _chart()
        mock_db_class.get_accounting_entries.return_value = []
        mock_db_class.get_next_entry_number.return_value = "A-00001"
        mock_rules_db.get_accounting_rules.return_value = rules
        saved = []
        mock_db_class.save_accounting_entry = MagicMock(
            side_effect=lambda uid, eid, entry, sandbox=True, company_id=None, **kw: saved.append(entry)
        )
        return saved

    def _seeded_rules(self):
        saved = []
        with patch("app.services.accounting_rules_service.DatabaseService") as mock_db:
            mock_db.get_accounting_rules.return_value = []
            mock_db.get_chart_of_accounts.return_value = _chart()
            mock_db.save_accounting_rule.side_effect = lambda uid, rid, rule, company_id: saved.append(rule)
            AccountingRulesService.ensure_initialized(TEST_OWNER)
        return saved

    def _line_signature(self, entry):
        return [(l["accountId"], round(float(l["debit"]), 2), round(float(l["credit"]), 2)) for l in entry["lines"]]

    def _invoice(self, invoice_id):
        return {
            "id": invoice_id, "invoiceNumber": "E310000000001",
            "clientId": "c1", "clientName": "Cliente RNC",
            "date": "2026-07-01",
            "subtotal": 100000.0, "totalITBIS": 18000.0,
            "total": 118000.0, "netPayable": 118000.0,
            "paymentType": "Crédito",
            "items": [
                {"name": "Mercancía", "type": "Bien", "quantity": 10, "costPrice": 5000.0, "subtotal": 100000.0},
            ],
        }

    @patch("app.services.accounting_service.DatabaseService")
    @patch("app.services.accounting_rules_service.DatabaseService")
    def test_factura_sin_reglas_igual_a_con_reglas_sembradas(self, mock_rules_db, mock_db):
        from app.services.accounting_service import AccountingService

        saved_a = self._setup_mock(mock_db, mock_rules_db, rules=[])
        entry_a = AccountingService.auto_generate_invoice_entry(TEST_OWNER, self._invoice("inv-a"), sandbox=TEST_SANDBOX)
        assert entry_a is not None

        seeded = self._seeded_rules()
        saved_b = self._setup_mock(mock_db, mock_rules_db, rules=seeded)
        entry_b = AccountingService.auto_generate_invoice_entry(TEST_OWNER, self._invoice("inv-b"), sandbox=TEST_SANDBOX)
        assert entry_b is not None

        assert self._line_signature(entry_a) == self._line_signature(entry_b)

    @patch("app.services.accounting_service.DatabaseService")
    @patch("app.services.accounting_rules_service.DatabaseService")
    def test_factura_contado_tarjeta_sin_reglas_igual_a_con_reglas(self, mock_rules_db, mock_db):
        from app.services.accounting_service import AccountingService

        def invoice(invoice_id):
            inv = self._invoice(invoice_id)
            inv["paymentType"] = "Contado"
            inv["paymentMethod"] = "Tarjeta de Crédito"
            return inv

        saved_a = self._setup_mock(mock_db, mock_rules_db, rules=[])
        entry_a = AccountingService.auto_generate_invoice_entry(TEST_OWNER, invoice("inv-a"), sandbox=TEST_SANDBOX)
        assert entry_a is not None

        seeded = self._seeded_rules()
        saved_b = self._setup_mock(mock_db, mock_rules_db, rules=seeded)
        entry_b = AccountingService.auto_generate_invoice_entry(TEST_OWNER, invoice("inv-b"), sandbox=TEST_SANDBOX)
        assert entry_b is not None

        assert self._line_signature(entry_a) == self._line_signature(entry_b)
        debit_ids = [l["accountId"] for l in entry_a["lines"] if l["debit"] > 0]
        assert "acc-banco" in debit_ids

    @patch("app.services.accounting_service.DatabaseService")
    @patch("app.services.accounting_rules_service.DatabaseService")
    def test_nota_credito_sin_reglas_igual_a_con_reglas(self, mock_rules_db, mock_db):
        from app.services.accounting_service import AccountingService

        def nc(invoice_id):
            return {
                "id": invoice_id, "invoiceNumber": "E340000000001",
                "clientId": "c1", "clientName": "Cliente A",
                "date": "2026-07-01",
                "subtotal": 10000.0, "totalITBIS": 1800.0,
                "total": 11800.0, "netPayable": 11800.0,
            }

        saved_a = self._setup_mock(mock_db, mock_rules_db, rules=[])
        entry_a = AccountingService.auto_generate_credit_note_entry(TEST_OWNER, nc("nc-a"), sandbox=TEST_SANDBOX)
        assert entry_a is not None

        seeded = self._seeded_rules()
        saved_b = self._setup_mock(mock_db, mock_rules_db, rules=seeded)
        entry_b = AccountingService.auto_generate_credit_note_entry(TEST_OWNER, nc("nc-b"), sandbox=TEST_SANDBOX)
        assert entry_b is not None

        assert self._line_signature(entry_a) == self._line_signature(entry_b)

    @patch("app.services.accounting_service.DatabaseService")
    @patch("app.services.accounting_rules_service.DatabaseService")
    def test_gasto_sin_reglas_igual_a_con_reglas(self, mock_rules_db, mock_db):
        from app.services.accounting_service import AccountingService

        def expense(expense_id):
            return {
                "id": expense_id, "ncf": "E410000000001",
                "concept": "Compra de mercancía", "supplierName": "Proveedor SRL",
                "amount": 59000.0, "itbisAmount": 9000.0,
                "total": 59000.0, "isCost": True,
                "date": "2026-07-01", "paymentType": "Crédito",
            }

        saved_a = self._setup_mock(mock_db, mock_rules_db, rules=[])
        entry_a = AccountingService.auto_generate_expense_entry(TEST_OWNER, expense("exp-a"), sandbox=TEST_SANDBOX)
        assert entry_a is not None

        seeded = self._seeded_rules()
        saved_b = self._setup_mock(mock_db, mock_rules_db, rules=seeded)
        entry_b = AccountingService.auto_generate_expense_entry(TEST_OWNER, expense("exp-b"), sandbox=TEST_SANDBOX)
        assert entry_b is not None

        assert self._line_signature(entry_a) == self._line_signature(entry_b)

    @patch("app.services.accounting_service.DatabaseService")
    @patch("app.services.accounting_rules_service.DatabaseService")
    def test_regla_personalizada_cambia_solo_asientos_futuros(self, mock_rules_db, mock_db):
        from app.services.accounting_service import AccountingService

        saved_a = self._setup_mock(mock_db, mock_rules_db, rules=[])
        entry_a = AccountingService.auto_generate_invoice_entry(TEST_OWNER, self._invoice("inv-a"), sandbox=TEST_SANDBOX)
        assert entry_a is not None

        custom = [{
            "id": "venta::venta_ingresos:::", "transaction": "venta", "concept": "venta_ingresos",
            "conditionKey": "", "conditionValue": "", "accountId": "acc-ventas-2",
            "isCustom": True, "isActive": True,
        }]
        saved_b = self._setup_mock(mock_db, mock_rules_db, rules=custom)
        entry_b = AccountingService.auto_generate_invoice_entry(TEST_OWNER, self._invoice("inv-b"), sandbox=TEST_SANDBOX)
        assert entry_b is not None

        ventas_a = next(l for l in entry_a["lines"] if l["credit"] > 0 and l["accountId"] == "acc-ventas")
        ventas_b = next(l for l in entry_b["lines"] if l["credit"] > 0)
        assert ventas_b["accountId"] == "acc-ventas-2"
        assert ventas_a["credit"] == ventas_b["credit"]
        assert entry_a["lines"][0]["accountId"] == entry_b["lines"][0]["accountId"]


# ======================================================================
# NÓMINA: regla personalizada resuelve accountId
# ======================================================================

class TestNominaRules:

    def test_regla_personalizada_nomina(self):
        from app.services.payroll_service import PayrollService
        import app.services.hr_data_service as hr_data_service

        chart = _chart() + [
            {"id": "acc-salarios-2", "code": "2.1.09", "name": "Salarios por pagar (nueva)",
             "usage": None, "group": "pasivos", "type": "movimiento", "nature": "acreedora", "isActive": True},
        ]
        rules = [{
            "id": "nomina::nomina_salarios_por_pagar:::", "transaction": "nomina",
            "concept": "nomina_salarios_por_pagar", "conditionKey": "", "conditionValue": "",
            "accountId": "acc-salarios-2", "isCustom": True, "isActive": True,
        }]
        rates = {
            "account_salaries_payable": "2.1.1.01",
            "account_afp_employee": "2.1.1.02",
            "account_sfs_employee": "2.1.1.03",
            "account_isr_employee": "2.1.1.04",
            "account_afp_employer": "2.1.2.01",
            "account_sfs_employer": "2.1.2.02",
            "account_srl_employer": "2.1.2.03",
            "account_infotep_employer": "2.1.2.04",
            "account_infotep_employee": "2.1.2.05",
            "account_other_deductions": "2.1.1.99",
            "accountSalariesPayable": "2.1.1.01",
            "accountAfpEmployee": "2.1.1.02",
            "accountSfsEmployee": "2.1.1.03",
            "accountIsrEmployee": "2.1.1.04",
            "accountAfpEmployer": "2.1.2.01",
            "accountSfsEmployer": "2.1.2.02",
            "accountSrlEmployer": "2.1.2.03",
            "accountInfotepEmployer": "2.1.2.04",
            "accountInfotepEmployee": "2.1.2.05",
            "accountOtherDeductions": "2.1.1.99",
            "accountSalariesPayable": "2.1.1.01",
            "accountAfpEmployee": "2.1.1.02",
            "accountSfsEmployee": "2.1.1.03",
            "accountIsrEmployee": "2.1.1.04",
            "accountAfpEmployer": "2.1.2.01",
            "accountSfsEmployer": "2.1.2.02",
            "accountSrlEmployer": "2.1.2.03",
            "accountInfotepEmployer": "2.1.2.04",
            "accountInfotepEmployee": "2.1.2.05",
            "accountOtherDeductions": "2.1.1.99",
            "cost_center_accounts": {"General": "6.2.1.01"},

            "afpEmployeeRate": 0.0287,
 "afpEmployerRate": 0.0710,
            "sfsEmployeeRate": 0.0304, "sfsEmployerRate": 0.0709,
            "srlEmployerRate": 0.0120, "infotepRate": 0.01,
            "afpSalaryCap": 464460.0, "sfsSalaryCap": 232230.0,
            "minSalary": 23223.0, "educationDeduction": 50000.0,
            "isrAnnualTable": [
                [0.0, 416220.0, 0.0, 0.0],
                [416220.01, 624329.0, 0.15, 0.0],
                [624329.01, 867123.0, 0.20, 31216.00],
                [867123.01, float("inf"), 0.25, 79775.00],
            ],
            "overtimeRate": 1.35, "workingDaysPerMonth": 23.83, "workingHoursPerDay": 8.0,
            "infotepThresholdMultiplier": 5.0,
        }
        line = {
            "employeeId": "emp-001", "employeeName": "Juan Pérez",
            "totalIncome": 50000.00, "netSalary": 43699.33,
            "afpEmployee": 1435.00, "sfsEmployee": 1520.00, "infotepEmployee": 0.0,
            "isrRetention": 2345.67, "afpEmployer": 3550.00, "sfsEmployer": 3545.00,
            "srlEmployer": 600.00, "infotepEmployer": 500.00,
            "totalEmployerContrib": 8195.00, "otherDeductions": 1000.00,
        }
        payroll_period = {"periodKey": "2026-07", "status": "aprobada", "payrollLines": [line]}
        snapshot = dict(rates)
        with patch.object(PayrollService, 'get_period_lines', return_value=[line]):
            with patch.object(hr_data_service, 'get_tax_rates_snapshot', return_value=snapshot):
                with patch("app.services.db_service.DatabaseService") as mock_db:
                    mock_db.get_chart_of_accounts.return_value = chart
                    with patch("app.services.accounting_rules_service.DatabaseService") as mock_rules_db:
                        mock_rules_db.get_accounting_rules.return_value = rules
                        result = PayrollService.build_payroll_accounting_lines(
                            payroll_period, employees={"emp-001": {"costCenter": "General"}},
                            tax_rates=rates, company_id="company-1", sandbox=True
                        )
        salarios = [r for r in result if "Salarios por pagar" in r["accountName"]]
        assert salarios
        assert salarios[0]["accountId"] == "acc-salarios-2"
        afp = [r for r in result if "AFP" in r["accountName"] and r["credit"] > 0]
        assert afp and afp[0]["accountCode"] == "2.1.1.02"
        assert afp[0]["accountId"] == ""

    def test_sin_company_id_usa_codigos_fallback(self):
        from app.services.payroll_service import PayrollService
        import app.services.hr_data_service as hr_data_service

        rates = {
            "account_salaries_payable": "2.1.1.01",
            "account_afp_employee": "2.1.1.02",
            "account_sfs_employee": "2.1.1.03",
            "account_isr_employee": "2.1.1.04",
            "account_afp_employer": "2.1.2.01",
            "account_sfs_employer": "2.1.2.02",
            "account_srl_employer": "2.1.2.03",
            "account_infotep_employer": "2.1.2.04",
            "account_infotep_employee": "2.1.2.05",
            "account_other_deductions": "2.1.1.99",
            "accountSalariesPayable": "2.1.1.01",
            "accountAfpEmployee": "2.1.1.02",
            "accountSfsEmployee": "2.1.1.03",
            "accountIsrEmployee": "2.1.1.04",
            "accountAfpEmployer": "2.1.2.01",
            "accountSfsEmployer": "2.1.2.02",
            "accountSrlEmployer": "2.1.2.03",
            "accountInfotepEmployer": "2.1.2.04",
            "accountInfotepEmployee": "2.1.2.05",
            "accountOtherDeductions": "2.1.1.99",
            "cost_center_accounts": {"General": "6.2.1.01"},
            "afpEmployeeRate": 0.0287,
 "afpEmployerRate": 0.0710,
            "sfsEmployeeRate": 0.0304, "sfsEmployerRate": 0.0709,
            "srlEmployerRate": 0.0120, "infotepRate": 0.01,
            "afpSalaryCap": 464460.0, "sfsSalaryCap": 232230.0,
            "minSalary": 23223.0, "educationDeduction": 50000.0,
            "isrAnnualTable": [
                [0.0, 416220.0, 0.0, 0.0],
                [416220.01, 624329.0, 0.15, 0.0],
                [624329.01, 867123.0, 0.20, 31216.00],
                [867123.01, float("inf"), 0.25, 79775.00],
            ],
            "overtimeRate": 1.35, "workingDaysPerMonth": 23.83, "workingHoursPerDay": 8.0,
            "infotepThresholdMultiplier": 5.0,
        }
        line = {
            "employeeId": "emp-001", "employeeName": "Juan Pérez",
            "totalIncome": 50000.00, "netSalary": 43699.33,
            "afpEmployee": 1435.00, "sfsEmployee": 1520.00, "infotepEmployee": 0.0,
            "isrRetention": 2345.67, "afpEmployer": 3550.00, "sfsEmployer": 3545.00,
            "srlEmployer": 600.00, "infotepEmployer": 500.00,
            "totalEmployerContrib": 8195.00, "otherDeductions": 1000.00,
        }
        payroll_period = {"periodKey": "2026-07", "status": "aprobada", "payrollLines": [line]}
        snapshot = dict(rates)
        with patch.object(PayrollService, 'get_period_lines', return_value=[line]):
            with patch.object(hr_data_service, 'get_tax_rates_snapshot', return_value=snapshot):
                result = PayrollService.build_payroll_accounting_lines(
                    payroll_period, employees={"emp-001": {}}
                )
        account_codes = [r["accountCode"] for r in result]
        assert "2.1.1.01" in account_codes
        assert all(not r.get("accountId") for r in result)
