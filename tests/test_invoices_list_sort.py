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
