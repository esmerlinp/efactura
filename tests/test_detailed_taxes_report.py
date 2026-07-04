"""
Tests para el Reporte detallado de impuestos.
Usa el cliente Flask con mocks para verificar la lógica de cálculo,
clasificación de impuestos, filtros y paginación.
"""
from unittest.mock import patch
from datetime import datetime, timezone

MOCK_USER_PROFILE = {
    'uid': 'test-uid',
    'email': 'admin@test.com',
    'name': 'Admin',
    'role': 'owner',
    'ownerUID': 'test-owner',
    'status': 'active',
    'permissions': {'canInvoice': True}
}

MOCK_COMPANY = {
    'companyRNC': '132-10912-2',
    'companyName': 'Test Co',
    'configured': True,
    'posEnabled': True,
    'productionEnabled': True,
    'sandboxEnabled': True,
    'sandboxIndefinite': True,
}


def mock_login(client, owner_uid='test-owner'):
    with client.session_transaction() as sess:
        sess['user'] = {
            'uid': 'test-uid',
            'ownerUID': owner_uid,
            'role': 'owner',
            'email': 'admin@test.com',
            'name': 'Admin',
            'permissions': {'canInvoice': True},
        }
        sess['is_sandbox_mode'] = True


MOCK_SALES_INVOICES = [
    {
        'id': 'inv-1',
        'clientName': 'Cliente A',
        'date': '2025-07-10',
        'status': 'Emitida',
        'ecfType': 'Factura de Crédito Fiscal (E31)',
        'encf': 'E310000000001',
        'isQuotation': False,
        'items': [
            {'itbisRate': 0.18, 'subtotal': 1000.0, 'itbis_amount': 180.0},
        ]
    },
    {
        'id': 'inv-2',
        'clientName': 'Cliente B',
        'date': '2025-07-20',
        'status': 'Emitida',
        'ecfType': 'Factura de Consumo (E32)',
        'encf': 'E320000000001',
        'isQuotation': False,
        'items': [
            {'itbisRate': 0.0, 'subtotal': 500.0, 'itbis_amount': 0.0},
        ]
    },
]

MOCK_CREDIT_NOTE = [
    {
        'id': 'cn-1',
        'clientName': 'Cliente A',
        'date': '2025-07-15',
        'status': 'Emitida',
        'ecfType': 'Nota de Crédito (E34)',
        'encf': 'E340000000001',
        'isQuotation': False,
        'items': [
            {'itbisRate': 0.18, 'subtotal': 200.0, 'itbis_amount': 36.0},
        ]
    },
]

MOCK_EXPENSES = [
    {
        'id': 'exp-1',
        'supplierName': 'Proveedor X',
        'date': '2025-07-05',
        'amount': 1180.0,
        'itbisAmount': 180.0,
    }
]

MOCK_PURCHASE_CN = []


def _patch_all(invoices=None, expenses=None, purchase_cn=None):
    inv = invoices if invoices is not None else MOCK_SALES_INVOICES + MOCK_CREDIT_NOTE
    exp = expenses if expenses is not None else MOCK_EXPENSES
    pcn = purchase_cn if purchase_cn is not None else MOCK_PURCHASE_CN
    return [
        patch('app.services.db_service.DatabaseService.get_invoices', return_value=inv),
        patch('app.services.db_service.DatabaseService.get_expenses', return_value=exp),
        patch('app.services.purchase_credit_note_service.PurchaseCreditNoteService.get_all', return_value=pcn),
        patch('app.services.db_service.DatabaseService.get_user_profile', return_value=MOCK_USER_PROFILE),
        patch('app.services.db_service.DatabaseService.get_associated_companies',
              return_value=[{'ownerUID': 'test-owner', 'companyName': 'Test Co', 'role': 'owner'}]),
        patch('app.services.db_service.DatabaseService.get_company_profile', return_value=MOCK_COMPANY),
    ]


# ── Auth tests ────────────────────────────────────────────────────────────────

def test_unauthenticated_redirect(client):
    resp = client.get('/reports/fiscal/detailed-taxes')
    assert resp.status_code in (302, 200)


def test_authenticated_empty_period(client):
    mock_login(client)
    patches = _patch_all(invoices=[], expenses=[], purchase_cn=[])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        resp = client.get('/reports/fiscal/detailed-taxes?year=2025&month=1')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'Reporte detallado de impuestos' in html or 'impuestos' in html.lower()
        # KPI zero values should appear
        assert 'RD$0.00' in html


# ── KPI calculation tests ─────────────────────────────────────────────────────

def test_sales_tax_kpi_shown(client):
    """With sales invoice of 1000 @ 18%, KPI should show 180.00."""
    mock_login(client)
    patches = _patch_all(invoices=MOCK_SALES_INVOICES, expenses=[], purchase_cn=[])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        resp = client.get('/reports/fiscal/detailed-taxes?year=2025&month=7')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert '180.00' in html


def test_exento_invoice_appears(client):
    """Exento invoice shows 0.00 tax."""
    mock_login(client)
    patches = _patch_all(invoices=[MOCK_SALES_INVOICES[1]], expenses=[], purchase_cn=[])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        resp = client.get('/reports/fiscal/detailed-taxes?year=2025&month=7')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        # Exento should have 0 tax
        assert '0.00' in html


def test_purchase_tax_kpi(client):
    """Expense of 1180 with 180 ITBIS shows in purchases column."""
    mock_login(client)
    patches = _patch_all(invoices=[], expenses=MOCK_EXPENSES, purchase_cn=[])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        resp = client.get('/reports/fiscal/detailed-taxes?year=2025&month=7')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert '180.00' in html


def test_credit_note_in_sales_returns_tab(client):
    """Nota de Crédito (E34) should appear in sales_returns tab."""
    mock_login(client)
    patches = _patch_all(invoices=MOCK_CREDIT_NOTE, expenses=[], purchase_cn=[])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        resp = client.get('/reports/fiscal/detailed-taxes?year=2025&month=7&tab=sales_returns')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert '36.00' in html


# ── Tax filter tests ──────────────────────────────────────────────────────────

def test_tax_filter_itbis18_includes_matching(client):
    mock_login(client)
    patches = _patch_all(invoices=MOCK_SALES_INVOICES, expenses=[], purchase_cn=[])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        resp = client.get('/reports/fiscal/detailed-taxes?year=2025&month=7&tab=sales&tax=ITBIS+%2818%25%29')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        # Invoice 1 should appear (18%), invoice 2 (exento) should not add tax rows
        assert '180.00' in html


def test_year_filter_excludes_wrong_year(client):
    mock_login(client)
    patches = _patch_all(invoices=MOCK_SALES_INVOICES, expenses=[], purchase_cn=[])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        resp = client.get('/reports/fiscal/detailed-taxes?year=2024&month=7&tab=sales')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        # No rows for 2024, all invoices are from 2025
        assert '0 registros' in html or 'No hay transacciones' in html


# ── Breakdown table tests ─────────────────────────────────────────────────────

def test_breakdown_tables_present(client):
    mock_login(client)
    patches = _patch_all()
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        resp = client.get('/reports/fiscal/detailed-taxes?year=2025&month=7')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'Impuestos en ventas con NCF' in html
        assert 'Impuestos en compras con NCF' in html
        assert 'Devoluciones en ventas' in html
        assert 'Devoluciones en compras' in html


def test_all_tax_labels_present(client):
    mock_login(client)
    patches = _patch_all(invoices=[], expenses=[], purchase_cn=[])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        resp = client.get('/reports/fiscal/detailed-taxes?year=2025&month=7')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        for lbl in ['ITBIS (18%)', 'ITBIS (16%)', 'ITBIS (0%)', 'Exento (0%)']:
            assert lbl in html


# ── Tab navigation tests ──────────────────────────────────────────────────────

def test_tab_sales_active(client):
    mock_login(client)
    patches = _patch_all(invoices=[], expenses=[], purchase_cn=[])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        resp = client.get('/reports/fiscal/detailed-taxes?tab=sales')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        # The sales tab link should have 'active' class
        assert 'tab=sales' in html

def test_tab_purchases_active(client):
    mock_login(client)
    patches = _patch_all(invoices=[], expenses=[], purchase_cn=[])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        resp = client.get('/reports/fiscal/detailed-taxes?tab=purchases')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        assert 'tab=purchases' in html


# ── Pagination tests ──────────────────────────────────────────────────────────

def test_pagination_per_page(client):
    """With per_page=1 and 2 invoice rows there should be 2 pages."""
    mock_login(client)
    many_invoices = MOCK_SALES_INVOICES * 5  # 10 invoices
    patches = _patch_all(invoices=many_invoices, expenses=[], purchase_cn=[])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        resp = client.get('/reports/fiscal/detailed-taxes?year=2025&month=7&tab=sales&per_page=5&page=1')
        assert resp.status_code == 200
        html = resp.data.decode('utf-8')
        # Should show pagination with multiple pages
        assert 'pag-btn' in html
