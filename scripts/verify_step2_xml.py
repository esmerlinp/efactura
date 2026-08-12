#!/usr/bin/env python3
"""
Verificación pre-subida de los XML del Paso 2 (Pruebas de Datos e-CF).

La DGII compara cada comprobante contra su conjunto de datos (el Excel
oficial). Los valores del XML deben coincidir EXACTAMENTE con la fila del
Excel, caso por caso — incluido RNCComprador=131880681 en los E32 (cualquier
monto) y en los RFCE. Los casos E43/E47 no llevan RNCComprador.

Modos:
  1) --excel <xlsx> : genera los XML desde el Excel oficial de DGII y verifica
                      que el bloque Comprador coincida campo a campo con la fila.
  2) --run-dir <dir>: verifica los archivos generados en el directorio xml/ de
                      una corrida (ej. uploads/certificacion/<cid>/step2/runN/xml).
                      Requiere --excel para la comparación campo a campo.

Ejemplos:
  python scripts/verify_step2_xml.py --excel uploads/certificacion/<cid>_step2_test_data.xlsx
  python scripts/verify_step2_xml.py --excel <xlsx> --run-dir uploads/certificacion/<cid>/step2/run34/xml
"""
import argparse
import importlib.util
import os
import re
import sys
from xml.etree import ElementTree as ET

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DS_NS = "{http://www.w3.org/2000/09/xmldsig#}"
COMPRADOR_TAGS = [
    "RNCComprador", "IdentificadorExtranjero", "RazonSocialComprador",
    "ContactoComprador", "CorreoComprador", "DireccionComprador",
    "MunicipioComprador", "ProvinciaComprador", "PaisComprador",
    "FechaEntrega", "ContactoEntrega", "DireccionEntrega",
    "TelefonoAdicional", "FechaOrdenCompra", "NumeroOrdenCompra",
    "CodigoInternoComprador", "ResponsablePago",
    "InformacionAdicionalComprador",
]


def load_loader():
    spec = importlib.util.spec_from_file_location(
        "dgii_test_data_loader",
        os.path.join(REPO_ROOT, "app", "services", "dgii_test_data_loader.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.DgiiTestDataLoader


def sanitized_schema(path):
    try:
        from lxml import etree
    except ImportError:
        return None
    with open(path, encoding="utf-8") as f:
        x = f.read()
    x = x.replace("[$0-9]", "[0-9]").replace("(?:", "(")
    try:
        return etree.XMLSchema(etree.fromstring(x.encode()))
    except Exception:
        return None


def xsd_check(xml_bytes, schema):
    if schema is None:
        return None
    from lxml import etree
    doc = etree.fromstring(xml_bytes)
    etree.SubElement(doc, f"{DS_NS}Signature")
    valid = schema.validate(doc)
    errs = [str(e).split("\n")[0] for e in schema.error_log[:3]] if not valid else []
    return valid, errs


def comprador_map(root):
    comp = root.find("Encabezado/Comprador")
    if comp is None:
        return {}
    return {c.tag: (c.text or "") for c in comp}


def row_comprador_expectation(row_dict, headers, L):
    expected = {}
    for tag in COMPRADOR_TAGS:
        v = L._v(row_dict, headers, tag)
        if v:
            expected[tag] = str(v).strip()
    return expected


def check_excel(excel_path, run_dir=None):
    L = load_loader()
    sheet1, sheet2 = L.load_workbook(excel_path)

    XSD_FILES = {
        "31": "e-CF 31 v1.0.xsd", "32": "e-CF 32 v1.0.xsd",
        "33": "e-CF 33 v1.0.xsd", "34": "e-CF 34 v1.0.xsd",
        "41": "e-CF 41 v1.0.xsd", "43": "e-CF 43 v1.0.xsd",
        "44": "e-CF 44 v1.0.xsd", "45": "e-CF 45 v1.0.xsd",
        "46": "e-CF 46 v1.0.xsd", "47": "e-CF 47 v1.0.xsd",
    }
    schemas = {
        t: sanitized_schema(os.path.join(REPO_ROOT, "Schemas", fname))
        for t, fname in XSD_FILES.items()
    }
    rfce_xsd = sanitized_schema(os.path.join(REPO_ROOT, "Schemas", "RFCE 32 v.1.0.xsd"))

    problems = []
    checks = 0
    disk = {}
    if run_dir:
        for name in os.listdir(run_dir):
            if name.endswith(".xml"):
                disk[name] = os.path.join(run_dir, name)

    for row_dict, headers in sheet1:
        encf = str(row_dict.get("D", "")).strip()
        tipo = str(row_dict.get("C", L._v(row_dict, headers, "TipoeCF") or "")).strip().replace("E", "")
        expected = row_comprador_expectation(row_dict, headers, L)
        raw = L.build_xml_from_row(row_dict, headers)
        actual = comprador_map(ET.fromstring(raw))
        xsd = xsd_check(raw, schemas.get(tipo))
        checks += 1
        if actual != expected:
            problems.append(
                f"{encf} (tipo {tipo}): Comprador difiere del Excel. "
                f"esperado={expected} generado={actual}"
            )
        elif xsd and not xsd[0]:
            problems.append(f"{encf} (tipo {tipo}): XSD inválido — {xsd[1]}")
        else:
            print(f"  OK  {encf} (tipo {tipo}) Comprador coincide con Excel {expected or '(vacío)'} | XSD: {_fmt(xsd)}")

        if run_dir and f"{encf}_manual_signed.xml" in disk:
            with open(disk[f"{encf}_manual_signed.xml"], "rb") as f:
                content = f.read()
            actual = comprador_map(ET.fromstring(content))
            checks += 1
            if actual != expected:
                problems.append(f"{encf}_manual_signed.xml: Comprador difiere del Excel. esperado={expected} archivo={actual}")
            else:
                print(f"  OK  {encf}_manual_signed.xml coincide con Excel")

    rfce_expected = {}
    for row_dict, headers in sheet2:
        encf = str(L._v(row_dict, headers, "ENCF") or row_dict.get("D", "")).strip()
        if encf:
            rfce_expected[encf] = row_comprador_expectation(row_dict, headers, L)

    for encf, expected in sorted(rfce_expected.items()):
        for row_dict, headers in sheet2:
            e = str(L._v(row_dict, headers, "ENCF") or row_dict.get("D", "")).strip()
            if e != encf:
                continue
            raw = L.build_rfce_xml_from_row(row_dict, headers, codigo_seguridad="VERIFY1")
            actual = comprador_map(ET.fromstring(raw))
            checks += 1
            if actual != expected:
                problems.append(f"{encf} (RFCE): Comprador difiere del Excel. esperado={expected} generado={actual}")
            else:
                xsd = xsd_check(raw, rfce_xsd)
                print(f"  OK  {encf} (RFCE) Comprador coincide con Excel {expected} | XSD: {_fmt(xsd)}")
            if run_dir and f"{encf}_rfce_signed.xml" in disk:
                with open(disk[f"{encf}_rfce_signed.xml"], "rb") as f:
                    content = f.read()
                actual = comprador_map(ET.fromstring(content))
                checks += 1
                if actual != expected:
                    problems.append(f"{encf}_rfce_signed.xml: Comprador difiere del Excel. esperado={expected} archivo={actual}")
                else:
                    print(f"  OK  {encf}_rfce_signed.xml coincide con Excel")

    return problems, checks


def _fmt(result):
    if result is None:
        return "n/a"
    valid, errs = result
    return "VALID" if valid else f"INVALID {errs}"


def check_run_dir_only(xml_dir):
    """Sin Excel: verificaciones estructurales básicas."""
    problems = []
    checks = 0
    for name in sorted(os.listdir(xml_dir)):
        if not name.endswith(".xml"):
            continue
        path = os.path.join(xml_dir, name)
        with open(path, "rb") as f:
            content = f.read()
        root = ET.fromstring(content)
        actual = comprador_map(root)
        if name.endswith("_manual_signed.xml") or name.endswith("_e32_firmado.xml"):
            checks += 1
            if "RNCComprador" not in actual:
                problems.append(f"{name}: sin RNCComprador (el data set lo espera)")
            else:
                print(f"  OK  {name} RNCComprador={actual.get('RNCComprador')}")
        elif "_rfce_signed" in name:
            checks += 1
            if "RNCComprador" not in actual:
                problems.append(f"{name}: sin RNCComprador (el data set lo espera)")
            else:
                print(f"  OK  {name} RNCComprador={actual.get('RNCComprador')}")
    return problems, checks


def check_signature_link(xml_dir):
    """
    La DGII exige que el CodigoSeguridadeCF del RFCE sea igual a los 6 primeros
    caracteres del SignatureValue del E32 completo subido al portal.
    Verifica que cada *_manual_signed.xml coincida con su *_rfce_signed.xml.
    """
    problems = []
    checks = 0
    files = sorted(os.listdir(xml_dir))
    for name in files:
        if not name.endswith("_manual_signed.xml"):
            continue
        encf = name[: -len("_manual_signed.xml")]
        rfce_name = f"{encf}_rfce_signed.xml"
        if rfce_name not in files:
            continue
        with open(os.path.join(xml_dir, name), "rb") as f:
            manual = f.read()
        with open(os.path.join(xml_dir, rfce_name), "rb") as f:
            rfce = f.read()
        checks += 1
        sv = re.search(rb"<ds:SignatureValue>([^<]+)</ds:SignatureValue>", manual) or \
            re.search(rb"<SignatureValue>([^<]+)</SignatureValue>", manual)
        cod = re.search(rb"<CodigoSeguridadeCF>([^<]+)</CodigoSeguridadeCF>", rfce)
        if not sv or not cod:
            problems.append(f"{encf}: no se pudo extraer firma/código (manual={'sí' if sv else 'no'}, rfce={'sí' if cod else 'no'})")
            continue
        sv6 = sv.group(1).decode("utf-8", "ignore")[:6]
        cod6 = cod.group(1).decode("utf-8", "ignore")[:6]
        if sv6 != cod6:
            problems.append(
                f"{encf}: DESAJUSTE de firma — RFCE CodigoSeguridadeCF={cod6} vs "
                f"E32 SignatureValue[:6]={sv6}. Reenviar grupo 3 (RFCE) y regenerar "
                f"grupo 4 en la misma sesión, luego volver a verificar."
            )
        else:
            print(f"  OK  {encf} vínculo de firma: CodigoSeguridadeCF={cod6} == SignatureValue[:6]={sv6}")
    return problems, checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--excel", help="Excel oficial de pruebas DGII (.xlsx)")
    parser.add_argument("--run-dir", help="Directorio xml/ de una corrida del paso 2")
    args = parser.parse_args()

    if not args.excel and not args.run_dir:
        parser.error("Debe indicar --excel o --run-dir")

    problems = []
    checks = 0

    if args.excel:
        print(f"=== Verificando Excel: {args.excel}")
        p, c = check_excel(args.excel, run_dir=args.run_dir)
        problems += p
        checks += c
    elif args.run_dir:
        print(f"=== Verificando directorio (sin Excel): {args.run_dir}")
        p, c = check_run_dir_only(args.run_dir)
        problems += p
        checks += c

    if args.run_dir:
        print(f"=== Vínculo de firma RFCE <-> E32 completo ({args.run_dir})")
        p, c = check_signature_link(args.run_dir)
        problems += p
        checks += c

    print()
    print(f"{'=' * 60}")
    print(f"Checks: {checks} | Problemas: {len(problems)}")
    if problems:
        print("PROBLEMAS:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("TODO OK — los XML coinciden con el conjunto de datos (Excel).")
    sys.exit(0)


if __name__ == "__main__":
    main()
