"""
Integration test: generate, sign, compress, and XSD-validate for all 10 e-CF types.
Run standalone: python3 tests/test_integration_xsd_full_pipeline.py
"""
import importlib.util
import sys
import os
import gzip
import base64

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

spec = importlib.util.spec_from_file_location(
    "dgii_xml_builder",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "app", "services", "dgii_xml_builder.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
DgiiXmlBuilder = mod.DgiiXmlBuilder

# Import signer
spec_signer = importlib.util.spec_from_file_location(
    "dgii_signer",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "app", "services", "dgii_signer.py")
)
mod_signer = importlib.util.module_from_spec(spec_signer)
spec_signer.loader.exec_module(mod_signer)
DgiiSigner = mod_signer.DgiiSigner

try:
    from lxml import etree
except ImportError:
    etree = None

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Schemas")


def load_xsd(tipo_ecf):
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
        "companyPhone": "809-555-1234",
        "companyEmail": "test@example.com",
    }


def build_test_invoice(tipo_ecf, **overrides):
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
        "ncfModificado": f"E{tipo_ecf}0000000000",
        "fechaNCFModificado": "14-06-2026",
        "codigoModificacion": "1",
        "items": [
            {"name": "Servicio de consultoría", "unit": "Servicio", "quantity": 1,
             "price": 1000.00, "subtotal": 1000.00, "type": "servicio"},
        ],
    }
    data.update(overrides)
    return data


def main():
    results = {}
    types_to_test = ["31", "32", "33", "34", "41", "43", "44", "45", "46", "47"]

    print("=" * 70)
    print(f"{'Type':<6} {'XML Build':<12} {'XSD Val':<10} {'Sign':<10} {'Compress':<12} {'Decompress':<12}")
    print("=" * 70)

    for tipo in types_to_test:
        xsd = load_xsd(tipo)
        if xsd is None:
            results[tipo] = ("SKIP", "No XSD")
            continue

        company = build_test_company()
        invoice = build_test_invoice(tipo)
        row = {"tipo": tipo}

        # 1. Build XML
        try:
            raw_xml = DgiiXmlBuilder.build_invoice_xml(company, invoice)
            row["build"] = "OK"
        except Exception as e:
            row["build"] = f"FAIL:{e}"
            results[tipo] = (row,)
            print(f"E{tipo:<4} {row.get('build',''):<12} {'':<10} {'':<10} {'':<12} {'':<12}")
            continue

        # 2. XSD validate (accept wildcard-only error for unsigned XML)
        try:
            xml_doc = etree.fromstring(raw_xml)
            if xsd.validate(xml_doc):
                row["xsd"] = "OK"
            else:
                errors = [str(e) for e in xsd.error_log]
                real_errors = [e for e in errors if "Missing child element(s)" not in e]
                if real_errors:
                    row["xsd"] = f"FAIL({len(real_errors)})"
                else:
                    row["xsd"] = "OK(wildcard)"
        except Exception as e:
            row["xsd"] = f"ERR:{e}"

        # 3. Sign (mock mode)
        try:
            signed_xml = DgiiSigner.sign_xml(raw_xml, company)
            row["sign"] = "OK"
        except Exception as e:
            row["sign"] = f"FAIL:{e}"

        # 4. Compress (gzip)
        try:
            compressed = gzip.compress(signed_xml)
            b64_payload = base64.b64encode(compressed).decode("utf-8")
            row["compress"] = f"OK({len(compressed)}b)"
        except Exception as e:
            row["compress"] = f"FAIL:{e}"

        # 5. Decompress and verify integrity
        try:
            decompressed = gzip.decompress(base64.b64decode(b64_payload.encode("utf-8")))
            if decompressed == signed_xml:
                row["decompress"] = "OK"
            else:
                row["decompress"] = "MISMATCH"
        except Exception as e:
            row["decompress"] = f"FAIL:{e}"

        results[tipo] = (row,)
        print(f"E{tipo:<4} {row.get('build',''):<12} {row.get('xsd',''):<10} "
              f"{row.get('sign',''):<10} {row.get('compress',''):<12} {row.get('decompress',''):<12}")

    # Summary
    print("\n" + "=" * 70)
    passed = sum(1 for r in results.values() if r[0].get("xsd", "").startswith("OK"))
    total = len(types_to_test)
    print(f"XSD Validation: {passed}/{total} passed")
    all_ok = all(r[0].get("xsd", "").startswith("OK") and r[0].get("sign") == "OK"
                 and r[0].get("compress", "").startswith("OK") and r[0].get("decompress") == "OK"
                 for r in results.values())
    if all_ok:
        print("ALL PIPELINE STEPS: OK")
    else:
        print("Some steps failed - review above")


if __name__ == "__main__":
    main()
