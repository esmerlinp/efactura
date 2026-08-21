"""Regresión — Ordenamiento por columnas en /invoices (grid de documentos)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("FIELD_ENCRYPTION_KEY", "wiS1GMquP_CvSrlBn7iOy-CalDQsPt7n1Pg_snPGluk=")


def _render(app, **extra):
    from flask import render_template
    ctx = dict(
        active_page="invoices",
        invoices=[],
        page=1,
        total_pages=1,
        total_items=0,
        pages_range=range(1, 2),
        has_prev=False,
        has_next=False,
        start_count=0,
        end_count=0,
        per_page="5",
        q="",
        status="",
        start_date="",
        end_date="",
        sort="date",
        order="desc",
    )
    ctx.update(extra)
    return render_template("invoices/list.html", **ctx)


def test_list_invoices_sort_links(app):
    with app.test_request_context("/invoices?sort=total&order=asc"):
        with app.app_context():
            html = _render(app, sort="total", order="asc", total_pages=3, total_items=25,
                           pages_range=range(1, 4), has_next=True)

    assert "?sort=total&order=desc" in html       # click en columna activa alterna
    assert "fa-sort-up" in html                    # flecha asc en Total
    assert "?sort=invoiceNumber&order=asc" in html
    assert "?sort=date&order=desc" in html
    # La paginación conserva el sort actual
    assert "&sort=total&order=asc" in html


def test_list_invoices_sort_defaults_for_quotations(app):
    """El template compartido con /quotations no se rompe sin sort/order."""
    with app.test_request_context("/quotations"):
        with app.app_context():
            html = _render(app, active_page="quotations", sort=None, order=None)
    assert "?sort=invoiceNumber&order=asc" in html


def test_enrich_invoice_totals_extrae_vencimiento_secuencia(app):
    """RI DGII: el PDF muestra la Fecha Vencimiento de la secuencia e-NCF
    extraída del xmlContent (31/12/2028), no la dueDate comercial."""
    from app.web.invoices import _enrich_invoice_totals

    inv = {"xmlContent": "<ECF><FechaVencimientoSecuencia>31-12-2028</FechaVencimientoSecuencia></ECF>",
           "items": []}
    out = _enrich_invoice_totals(inv)
    assert out.get("fechaVencimientoSecuencia") == "2028-12-31"

    inv2 = {"items": []}
    assert _enrich_invoice_totals(inv2).get("fechaVencimientoSecuencia") is None


def test_pdf_html_columnas_items_sin_unidad_medida(app):
    """RI: columna 'Precio' (no 'Precio Unit.') y sin 'Unid. Medida' en el detalle de ítems."""
    from flask import render_template

    invoice = {
        "isQuotation": False, "invoiceNumber": "X", "clientName": "A", "clientRNC": "",
        "currency": "DOP", "date": "2026-08-16", "dueDate": "", "ecfType": "Factura de Crédito Fiscal (E31)",
        "encf": "E310000000001", "emisionMode": "", "paymentMethod": "Efectivo", "paymentType": "Contado",
        "subtotal": 1000.0, "total": 1180.0, "totalITBIS": 180.0, "totalISCEspecifico": 0.0,
        "totalISCAdValorem": 0.0, "totalOtrosSelectivos": 0.0, "totalCDT": 0.0, "totalPropina": 0.0,
        "discountAmount": 0.0, "retainedISR": 0.0, "retainedITBIS": 0.0, "netPayable": 1180.0,
        "notes": "", "comentario": "", "footer": "", "foreignTaxId": "", "status": "Emitida", "xmlSignature": "",
        "items": [{"code": "S1", "name": "Servicio certificación", "price": 1000.0, "quantity": 1,
                   "itbisRate": 0.18, "discountRate": 0.0, "subtotal": 1000.0, "total": 1180.0,
                   "itbis_amount": 180.0, "unit": "Servicio", "type": "Servicio"}],
    }
    with app.test_request_context("/invoices/x/pdf"):
        with app.app_context():
            html = render_template("invoices/pdf.html", invoice=invoice,
                                   company={"companyName": "C", "companyRNC": "131880681",
                                            "applyColorMarcaReports": False, "colorMarca": "#10b981"},
                                   branch={}, auto_print=False, qr_base64=None,
                                   fecha_firma_str="", sandbox=True)
    assert "text-align: right; white-space: nowrap;\">Precio</th>" in html or "text-align: right;\">Precio</div>" in html
    assert "Precio Unit." not in html
    assert "Unid. Medida" not in html
    assert "text-align: right; white-space: nowrap;\">RD$" in html
    # Alineación determinista: filas flex con anchos fijos idénticos en cabecera y filas
    assert "display: flex; align-items: center" in html
    assert 'width: 92px; text-align: right;">Precio</div>' in html
    assert 'width: 92px; text-align: right; white-space: nowrap;' in html
    # Descuento por ítem muestra el MONTO (RD$), no el porcentaje
    assert "Desc. %" not in html
    assert 'text-align: right;">Desc.</div>' in html
    assert "RD$ 0.00" in html
