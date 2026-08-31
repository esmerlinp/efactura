"""Regresión — Ordenamiento por columnas en /invoices (grid de documentos)."""
import os
import re
import shutil
import subprocess
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


def _strip_js_noise(code):
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    code = re.sub(r"//[^\n]*", "", code)
    out = []
    i = 0
    n = len(code)
    while i < n:
        ch = code[i]
        if ch in ("'", '"'):
            quote = ch
            j = i + 1
            while j < n and code[j] != quote:
                if code[j] == "\\":
                    j += 1
                j += 1
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _js_balanced(code):
    cleaned = _strip_js_noise(code)
    stack = []
    pairs = {")": "(", "]": "[", "}": "{"}
    for ch in cleaned:
        if ch in "([{":
            stack.append(ch)
        elif ch in ")]}":
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack


def test_historical_import_modal_script_sintaxis_valida(app):
    """Regresión: si el bloque <script> del modal 'Importar Histórico' tiene
    llaves sin cerrar, openHistoricalImportModal no se define y el clic en el
    botón dispara el toast global 'Ha ocurrido un error' (static/js/main.js)."""
    with app.test_request_context("/invoices"):
        with app.app_context():
            html = _render(app)

    assert "openHistoricalImportModal" in html
    blocks = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
    assert blocks
    modal_blocks = [b for b in blocks if "openHistoricalImportModal" in b]
    assert len(modal_blocks) == 1
    script = modal_blocks[0]

    assert _js_balanced(script), "El bloque <script> del modal tiene llaves/paréntesis sin cerrar"

    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, "--check", "-"], input=script,
                              capture_output=True, text=True)
        assert proc.returncode == 0, f"node --check falló: {proc.stderr}"


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


def test_pdf_fecha_vencimiento_segun_tipo(app):
    """E33 (Nota de Débito) SÍ tiene vencimiento → el PDF lo muestra como E31.
    E32 (Consumo) y E34 (Nota de Crédito) no → se oculta."""
    from flask import render_template

    def _render_pdf(ecf_type):
        invoice = {
            "isQuotation": False, "invoiceNumber": "X", "clientName": "A", "clientRNC": "131880681",
            "currency": "DOP", "date": "2026-08-16", "dueDate": "", "ecfType": ecf_type,
            "encf": "E330000000001", "emisionMode": "", "paymentMethod": "Efectivo", "paymentType": "Contado",
            "subtotal": 1000.0, "total": 1180.0, "totalITBIS": 180.0, "totalISCEspecifico": 0.0,
            "totalISCAdValorem": 0.0, "totalOtrosSelectivos": 0.0, "totalCDT": 0.0, "totalPropina": 0.0,
            "discountAmount": 0.0, "retainedISR": 0.0, "retainedITBIS": 0.0, "netPayable": 1180.0,
            "notes": "", "comentario": "", "footer": "", "foreignTaxId": "", "status": "Emitida",
            "xmlSignature": "", "fechaVencimientoSecuencia": "2028-12-31",
            "items": [{"code": "S1", "name": "Servicio", "price": 1000.0, "quantity": 1,
                       "itbisRate": 0.18, "discountRate": 0.0, "subtotal": 1000.0, "total": 1180.0,
                       "itbis_amount": 180.0, "unit": "Servicio", "type": "Servicio"}],
        }
        with app.test_request_context("/invoices/x/pdf"):
            with app.app_context():
                return render_template("invoices/pdf.html", invoice=invoice,
                                       company={"companyName": "C", "companyRNC": "131880681",
                                                "applyColorMarcaReports": False, "colorMarca": "#10b981"},
                                       branch={}, auto_print=False, qr_base64=None,
                                       fecha_firma_str="", sandbox=True)

    for ecf_type in ("Factura de Crédito Fiscal (E31)", "Nota de Débito (E33)", "E33"):
        html = _render_pdf(ecf_type)
        assert "Fecha Vencimiento" in html, f"{ecf_type} debe mostrar Fecha Vencimiento"
        assert "31/12/2028" in html, f"{ecf_type} debe mostrar la fecha formateada"

    for ecf_type in ("Nota de Crédito (E34)", "Factura de Consumo (E32)"):
        html = _render_pdf(ecf_type)
        assert "Fecha Vencimiento" not in html, f"{ecf_type} no debe mostrar Fecha Vencimiento"
