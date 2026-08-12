import json
import sys
from flask import Flask
from app import create_app
from app.services.dgii_test_data_loader import DgiiTestDataLoader
import xml.etree.ElementTree as ET

with open('/Users/esmerlinpaniagua/Develop/e-Factura/e-FacturaWeb/uploads/certificacion/fa3abfc7-5e4c-410b-bde5-b101e1a8ea10/step2/run34/parsed_data.json', 'r') as f:
    parsed_data = json.load(f)

base_caso = parsed_data["_grupos_raw"]["4"][0]
row_dict = base_caso["row_dict"]
headers = base_caso["headers"]

# FORCE ECF
raw_xml = DgiiTestDataLoader.build_xml_from_row(row_dict, headers)
xml_str = ET.tostring(raw_xml, encoding='utf-8', xml_declaration=False).decode('utf-8')
print(xml_str)
