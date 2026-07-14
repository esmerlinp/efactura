"""
Base para baterías de casos de prueba fiscales (Bloque 1).
Cada tipo (E31–E47) define su propia batería en test_cases_e{N}.py.

Estructura de un caso:
  case = {
      "name": str,              # Descripción del caso
      "expected": "accept"|"reject",  # Si DGII debe aceptar o rechazar
      "invoice_overrides": {},   # Overrides para build_invoice()
      "assertions": [callable],  # Validaciones post-construcción
      "xfail_reason": str|None,  # Si se espera fallo conocido
  }
"""
import importlib.util
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

spec = importlib.util.spec_from_file_location(
    "dgii_xml_builder",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "app", "services", "dgii_xml_builder.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
DgiiXmlBuilder = mod.DgiiXmlBuilder
map_province = DgiiXmlBuilder.map_province_or_municipality
map_currency = DgiiXmlBuilder.map_currency
_sd = DgiiXmlBuilder._sd

from lxml import etree


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

BASE_COMPANY = {
    "companyRNC": "131111111",
    "companyName": "EMPRESA TEST SRL",
    "tradeName": "TEST",
    "companyAddress": "Av. Test 123, Santo Domingo",
    "municipality": "Santo Domingo de Guzmán",
    "province": "Santo Domingo",
    "companyPhone": "809-555-1234",
    "companyEmail": "test@example.com",
}


def base_invoice(tipo_ecf, **overrides):
    d = {
        "ecfType": f"E{tipo_ecf}",
        "encf": f"E{tipo_ecf}0000000001",
        "subtotal": 1000.00,
        "total": 1180.00,
        "totalITBIS": 180.00,
        "montoExento": 0.00,
        "paymentMethod": "Efectivo",
        "incomeType": "01",
        "clientRNC": "131222222",
        "razonSocial": "CLIENTE TEST SRL",
        "clientMunicipality": "Santo Domingo de Guzmán",
        "clientProvince": "Santo Domingo",
        "internalInvoiceNumber": "INV-001",
        "fechaVencimientoSecuencia": "15-12-2028",
        "ncfModificado": f"E{tipo_ecf}0000000000",
        "fechaNCFModificado": "14-06-2026",
        "codigoModificacion": "1",
        "items": [{"name": "Producto test", "unit": "Unidad", "quantity": 1,
                   "price": 1000.00, "subtotal": 1000.00, "type": "producto"}],
    }
    d.update(overrides)
    return d


def load_xsd(tipo_ecf):
    xsd_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "Schemas", f"e-CF {tipo_ecf} v1.0.xsd")
    if not os.path.exists(xsd_path):
        return None
    with open(xsd_path, "rb") as f:
        return etree.XMLSchema(etree.parse(f))


def build_and_validate(tipo_ecf, company, invoice):
    """Build XML + XSD validate. Returns (xml_bytes, xsd_errors, doc)."""
    xml_bytes = DgiiXmlBuilder.build_invoice_xml(company, invoice)
    xsd = load_xsd(tipo_ecf)
    doc = etree.fromstring(xml_bytes)
    errors = []
    if xsd is not None:
        if not xsd.validate(doc):
            errors = [str(e) for e in xsd.error_log
                      if "Missing child element(s)" not in str(e)]
    return xml_bytes, errors, doc


def run_case(tipo_ecf, company, case):
    """Execute a single test case. Returns dict with results."""
    invoice = base_invoice(tipo_ecf, **case.get("invoice_overrides", {}))
    xml_bytes, xsd_errors, doc = build_and_validate(tipo_ecf, company, invoice)

    result = {
        "name": case["name"],
        "expected": case.get("expected", "accept"),
        "xfail": case.get("xfail_reason"),
        "xml_bytes": xml_bytes,
        "xsd_errors": xsd_errors,
        "doc": doc,
        "invoice": invoice,
        "assertions_passed": [],
        "assertions_failed": [],
    }

    for idx, assertion_fn in enumerate(case.get("assertions", [])):
        try:
            ret = assertion_fn(result)
            if ret is False:
                raise AssertionError("assertion returned False")
            result["assertions_passed"].append(idx)
        except AssertionError as e:
            result["assertions_failed"].append((idx, str(e)))

    return result


def run_battery(tipo_ecf, cases):
    """Run all cases for a type and print results table."""
    company = BASE_COMPANY.copy()
    print(f"\n{'='*70}")
    print(f"  BATERÍA E{tipo_ecf}")
    print(f"{'='*70}")
    print(f"{'#':<4} {'Caso':<40} {'XSD':<8} {'Esperado':<10} {'Bussines':<10} {'Resultado':<12} {'Detalle'}")
    print(f"{'='*70}")

    passed = 0
    total = 0
    for idx, case in enumerate(cases, 1):
        total += 1
        result = run_case(tipo_ecf, company, case)
        xsd_ok = "OK" if len(result["xsd_errors"]) == 0 else f"FAIL({len(result['xsd_errors'])})"
        af = result["assertions_failed"]
        ap = result["assertions_passed"]
        expected = case.get("expected", "accept")

        # Para casos "accept": todas las assertions deben pasar
        # Para casos "reject": al menos una assertion debe fallar
        if expected == "accept":
            biz_ok = "OK" if len(af) == 0 else f"FAIL({len(af)})"
        else:
            biz_ok = "DETECTED" if len(af) > 0 else "MISSED"

        # Decisión final
        if expected == "accept" and xsd_ok == "OK" and biz_ok == "OK":
            status = "✅ PASS"
            passed += 1
        elif expected == "reject":
            if biz_ok == "DETECTED" or xsd_ok != "OK":
                status = "✅ PASS (rechazo detectado)"
                passed += 1
            else:
                status = "❌ FAIL (no detectado)"
        elif result.get("xfail"):
            status = "⏭️ XFAIL"
        else:
            status = "❌ FAIL"

        # Detalle
        detail = ""
        if af:
            detail = af[0][1][:50]
        elif result["xsd_errors"]:
            detail = result["xsd_errors"][0][:50]
        elif ap:
            detail = f"{len(ap)} assertions passed"

        print(f"{idx:<4} {case['name'][:38]:<40} {xsd_ok:<8} {expected:<10} {biz_ok:<10} {status:<20} {detail[:40]}")

    print(f"{'='*70}")
    print(f"  {passed}/{total} passed")
    return passed, total
