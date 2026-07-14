"""
Standalone XSD validation test. Run with: python3 tests/test_xsd_validation_v2.py
Imports builder via importlib to avoid Flask app initialization issues.

NOTA: El XML unsigned NO satisface el <xs:any> wildcard (minOccurs=1).
Ese error es esperado — solo el XML firmado (con <ds:Signature>) lo satisface.
Este test verifica que NO HAY otros errores de esquema.
"""
import importlib.util
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

spec = importlib.util.spec_from_file_location(
    "dgii_xml_builder",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "app", "services", "dgii_xml_builder.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
DgiiXmlBuilder = mod.DgiiXmlBuilder

try:
    from lxml import etree
except ImportError:
    etree = None

if etree is None:
    print("lxml not available for validation; cannot validate.")
    sys.exit(1)


SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Schemas")


def load_xsd(tipo_ecf: str):
    xsd_file = os.path.join(SCHEMA_DIR, f"e-CF {tipo_ecf} v1.0.xsd")
    if not os.path.exists(xsd_file):
        return None
    with open(xsd_file, "rb") as f:
        return etree.XMLSchema(etree.parse(f))


def build_test_company():
    return {
        "companyRNC": "131111111",
        "companyName": "EMPRESA TEST SRL",
        "tradeName": "TEST",
        "companyAddress": "Av. Test 123",
        "municipality": "Santo Domingo de Guzmán",
        "province": "Santo Domingo",
        "companyPhone": "8095551234",
        "companyEmail": "test@example.com",
    }


def build_test_invoice(tipo_ecf: str, **overrides):
    data = {
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
        "items": [
            {"name": "Servicio de consultoría", "unit": "Servicio", "quantity": 1, "price": 1000.00, "subtotal": 1000.00, "type": "servicio"},
        ],
    }
    data.update(overrides)
    return data


def main():
    results = {}
    types_to_test = ["31", "32", "33", "34", "41", "43", "44", "45", "46", "47"]

    for tipo in types_to_test:
        xsd = load_xsd(tipo)
        if xsd is None:
            results[tipo] = ("SKIP", "No XSD found")
            continue

        invoice = build_test_invoice(tipo)

        try:
            xml_bytes = DgiiXmlBuilder.build_invoice_xml(build_test_company(), invoice)
        except Exception as e:
            results[tipo] = ("ERROR", f"Build failed: {e}")
            continue

        try:
            xml_doc = etree.fromstring(xml_bytes)
            if xsd.validate(xml_doc):
                results[tipo] = ("PASS", "")
            else:
                errors = [str(e) for e in xsd.error_log]
                # Filter out expected wildcard error (unsigned XML won't satisfy <xs:any>)
                real_errors = [e for e in errors if "Missing child element(s)" not in e]
                if real_errors:
                    results[tipo] = ("FAIL", real_errors)
                else:
                    results[tipo] = ("PASS", "(wildcard-only, expected)")
        except etree.XMLSyntaxError as e:
            results[tipo] = ("ERROR", f"XML syntax: {e}")

        # Print the XML for inspection on failure
        if results[tipo][0] == "FAIL":
            print(f"\n{'='*60}")
            print(f"E{tipo} FAILED: {len(results[tipo][1])} errors")
            print(f"{'='*60}")
            for err in results[tipo][1][:15]:
                print(f"  {err}")
            print(f"\nXML output:\n{xml_bytes.decode()}")

    # Summary
    print(f"\n{'='*60}")
    print(f"{'Type':<6} {'Result':<8} {'Detail'}")
    print(f"{'='*60}")
    for tipo in types_to_test:
        status, detail = results.get(tipo, ("SKIP", ""))
        if status == "PASS":
            detail_str = "OK"
        elif status == "SKIP":
            detail_str = str(detail)
        elif status == "ERROR":
            detail_str = str(detail)
        else:
            n_err = len(detail) if isinstance(detail, list) else 0
            detail_str = f"{n_err} errors"
        print(f"E{tipo:<4} {status:<8} {detail_str}")


if __name__ == "__main__":
    main()
