import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from app.fiscal_forms.ir17_rules import IR17_LINES


def test_catalog_matches_ir17_2026_template_rates_and_lines():
    path = Path(__file__).parents[1] / "docs" / "IR-17-2026.xlsx"
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        strings_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = ["".join(t.text or "" for t in si.findall(".//m:t", ns)) for si in strings_root.findall("m:si", ns)]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {r.attrib["Id"]: r.attrib["Target"] for r in rels}
        sheet = next(s for s in workbook.findall(".//m:sheet", ns) if s.attrib["name"] == "IR-17")
        target = "xl/" + rel_map[sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
        root = ET.fromstring(archive.read(target))
        values = {}
        for cell in root.findall(".//m:c", ns):
            ref = cell.attrib.get("r", "")
            value = cell.find("m:v", ns)
            if value is not None and value.text is not None:
                values[ref] = strings[int(value.text)] if cell.attrib.get("t") == "s" else value.text
    assert len(IR17_LINES) == 24
    for number, concept, rate, _ in IR17_LINES:
        row = 26 + number
        assert values[f"D{row}"].startswith(concept.split(" (")[0])
        assert values[f"AI{row}"] == str(float(rate))
