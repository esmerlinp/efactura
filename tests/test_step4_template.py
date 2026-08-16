"""Render smoke test — plantilla paso 4 con set de pruebas embebido."""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("FIELD_ENCRYPTION_KEY", "wiS1GMquP_CvSrlBn7iOy-CalDQsPt7n1Pg_snPGluk=")


def test_step4_template_renders_with_set(app):
    from app.services.dgii_cert_service import DgiiCertService

    with app.test_request_context("/certificacion/paso/4"):
        with app.app_context():
            from flask import render_template, g, session, request
            from jinja2.exceptions import TemplateError

            blocks = []
            for b in DgiiCertService.STEP4_SET_TEMPLATE:
                cases = []
                for i in range(b["count"]):
                    cases.append({
                        "encf": f"E{b['tipo'][1:]}00000000{i+1}",
                        "doc_id": f"doc-{b['tipo']}-{i}",
                        "kind": b["kind"],
                        "tipo": b["tipo"],
                        "rfce": bool(b.get("rfce")),
                        "status": "pending",
                        "invoiceNumber": f"CERT-{b['tipo']}-{i+1:02d}",
                        "total": 1234.56,
                        "validation": "ok",
                    })
                blocks.append({**b, "status": "pending", "cases": cases})

            test_set = {
                "created_at": "2026-08-16T00:00:00",
                "total": 25,
                "blocks": blocks,
                "set_errors": [],
            }
            step_status = {
                "status": "in_progress",
                "current_run": 3,
                "runs": [{
                    "run_number": 3,
                    "status": "in_progress",
                    "test_set_summary": {"total": 25, "blocks": []},
                }],
            }
            try:
                html = render_template(
                    "certificacion/step_04_simulacion.html",
                    step=4,
                    step_label="Paso 4",
                    step_status=step_status,
                    current_step=4,
                    steps={"4": step_status},
                    step_labels={4: "Paso 4"},
                    profile={},
                    cert_status={},
                    is_locked=False,
                )
            except TemplateError as e:
                pytest.fail(f"Template error: {e}")
            assert "Generar Set de Pruebas Automático" in html
            assert "4× E32 RFCE" in html
            assert "Enviar bloque" in html
            assert "Marcar enviado (manual)" in html
            assert "se emiten <strong>manualmente</strong>" in html
            assert "Generar Nota de Débito" in html
            assert "step4-set-container" in html
            assert "step4-advance-form" in html
            assert "/certificacion/step-4/set" in html
            assert "/certificacion/step-4/mark-block-sent" in html
            # El flujo manual fue eliminado del paso 4
            assert "Seleccionar Facturas" not in html
            assert "Cargar facturas del sistema" not in html
            assert "Seleccionar todas" not in html


def test_step4_case_pdf_generation(app, tmp_path):
    """El helper de PDF usa la plantilla real invoices/pdf.html + WeasyPrint."""
    from app.services.dgii_cert_service import DgiiCertService

    payload = {
        "id": "inv-1",
        "ecfType": "Factura de Consumo (E32)",
        "encf": "E320000000001",
        "date": "2026-08-16",
        "clientName": "CERTIFICACION DGII SRL",
        "clientRNC": "131880681",
        "total": 14750.0,
        "subtotal": 12500.0,
        "totalITBIS": 2250.0,
        "netPayable": 14750.0,
        "paymentMethod": "Efectivo",
        "paymentType": "Contado",
        "status": "Borrador",
        "invoiceNumber": "CERT-E32-01",
        "items": [{
            "name": "Servicio de certificación DGII E32 #1",
            "price": 12500.0,
            "quantity": 1,
            "itbisRate": 0.18,
            "discountRate": 0.0,
            "subtotal": 12500.0,
            "subtotal_raw": 12500.0,
            "discount_amount": 0.0,
            "itbis_amount": 2250.0,
            "total": 14750.0,
            "type": "Servicio",
        }],
    }
    profile = {
        "companyRNC": "131880681",
        "companyName": "EMPRESA CERTIFICACION SRL",
        "tradeName": "CERT SRL",
        "companyAddress": "Av. Certificacion 123",
        "companyPhone": "809-555-0000",
        "companyEmail": "cert@test.do",
        "logoUrl": "",
        "colorMarca": "#10b981",
        "applyColorMarcaReports": False,
    }
    with app.test_request_context("/api/v1/certificacion/step-4/generate-set", method="POST"):
        with app.app_context():
            pdf_path = DgiiCertService._step4_case_pdf(payload, profile, str(tmp_path), "E320000000001")
    assert pdf_path
    assert os.path.exists(pdf_path)
    assert os.path.basename(pdf_path) == "131880681E320000000001.pdf"
    with open(pdf_path, "rb") as f:
        assert f.read(5) == b"%PDF-"


def test_step4_case_pdf_expense_without_discount_rate(app, tmp_path):
    """Regresión: los ítems de gastos/proveedor no traen discountRate y
    invoices/pdf.html hace aritmética con item.discountRate (UndefinedError)."""
    from app.services.dgii_cert_service import DgiiCertService

    payload = DgiiCertService._step4_build_payload({
        "id": "e1", "ecfType": "E41", "encf": "E410000000001",
        "amount": 17700.0, "itbisAmount": 2700.0, "date": "2026-08-16",
        "providerName": "PROVEEDOR FORMAL CERT SRL", "rncEmisor": "131880681",
        "concept": "Compra certificación",
    }, "expense")
    assert "discountRate" not in payload["items"][0]

    profile = {
        "companyRNC": "131880681",
        "companyName": "EMPRESA CERTIFICACION SRL",
        "tradeName": "CERT SRL",
        "companyAddress": "Av. Certificacion 123",
        "companyPhone": "809-555-0000",
        "companyEmail": "cert@test.do",
        "logoUrl": "",
        "colorMarca": "#10b981",
        "applyColorMarcaReports": False,
    }
    with app.test_request_context("/api/v1/certificacion/step-4/generate-set", method="POST"):
        with app.app_context():
            pdf_path = DgiiCertService._step4_case_pdf(payload, profile, str(tmp_path), "E410000000001")
    assert pdf_path
    assert os.path.exists(pdf_path)
    assert os.path.basename(pdf_path) == "131880681E410000000001.pdf"
    with open(pdf_path, "rb") as f:
        assert f.read(5) == b"%PDF-"


def test_step4_case_pdf_status_not_borrador(app, tmp_path):
    """Regresión: el PDF de evidencia nunca debe mostrar 'Borrador'."""
    from unittest.mock import patch
    from app.services.dgii_cert_service import DgiiCertService

    payload = {
        "id": "inv-1",
        "ecfType": "Factura de Consumo (E32)",
        "encf": "E320000000001",
        "date": "2026-08-16",
        "clientName": "CERTIFICACION DGII SRL",
        "clientRNC": "131880681",
        "total": 14750.0,
        "subtotal": 12500.0,
        "totalITBIS": 2250.0,
        "netPayable": 14750.0,
        "paymentMethod": "Efectivo",
        "paymentType": "Contado",
        "status": "Borrador",
        "invoiceNumber": "CERT-E32-01",
        "items": [{
            "name": "Servicio de certificación DGII E32 #1",
            "price": 12500.0,
            "quantity": 1,
            "itbisRate": 0.18,
            "discountRate": 0.0,
            "subtotal": 12500.0,
            "total": 14750.0,
            "type": "Servicio",
        }],
    }
    profile = {
        "companyRNC": "131880681",
        "companyName": "EMPRESA CERTIFICACION SRL",
        "tradeName": "CERT SRL",
        "companyAddress": "Av. Certificacion 123",
        "companyPhone": "809-555-0000",
        "companyEmail": "cert@test.do",
        "logoUrl": "",
        "colorMarca": "#10b981",
        "applyColorMarcaReports": False,
    }
    captured = {}

    def fake_render(template_name, **kwargs):
        captured["invoice"] = kwargs.get("invoice", {})
        captured["template"] = template_name
        return "<html><body></body></html>"

    with app.test_request_context("/api/v1/certificacion/step-4/generate-set", method="POST"):
        with app.app_context():
            with patch("flask.render_template", side_effect=fake_render):
                pdf_path = DgiiCertService._step4_case_pdf(payload, profile, str(tmp_path), "E320000000001")

    assert captured.get("template") == "invoices/pdf.html"
    assert captured["invoice"]["status"] == "Emitida"
    assert pdf_path
    assert os.path.exists(pdf_path)
