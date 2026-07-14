import os
import logging
from lxml import etree

logger = logging.getLogger(__name__)

XSD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "Schemas")

XSD_MAP = {
    "31": "e-CF 31 v1.0.xsd",
    "32": "e-CF 32 v1.0.xsd",
    "33": "e-CF 33 v1.0.xsd",
    "34": "e-CF 34 v1.0.xsd",
    "41": "e-CF 41 v1.0.xsd",
    "43": "e-CF 43 v1.0.xsd",
    "44": "e-CF 44 v1.0.xsd",
    "45": "e-CF 45 v1.0.xsd",
    "46": "e-CF 46 v1.0.xsd",
    "47": "e-CF 47 v1.0.xsd",
}

_cached_schemas = {}

def get_schema(tipo_ecf: str) -> etree.XMLSchema | None:
    if tipo_ecf in _cached_schemas:
        return _cached_schemas[tipo_ecf]
    xsd_file = XSD_MAP.get(tipo_ecf)
    if not xsd_file:
        logger.warning(f"No XSD found for tipo_ecf={tipo_ecf}")
        _cached_schemas[tipo_ecf] = None
        return None
    xsd_path = os.path.join(XSD_DIR, xsd_file)
    if not os.path.exists(xsd_path):
        logger.warning(f"XSD file not found: {xsd_path}")
        _cached_schemas[tipo_ecf] = None
        return None
    try:
        with open(xsd_path, "rb") as f:
            schema_doc = etree.parse(f)
        schema = etree.XMLSchema(schema_doc)
        _cached_schemas[tipo_ecf] = schema
        return schema
    except Exception as e:
        logger.error(f"Error loading XSD {xsd_file}: {e}")
        _cached_schemas[tipo_ecf] = None
        return None

def validate_xml(xml_bytes: bytes, tipo_ecf: str) -> dict:
    schema = get_schema(tipo_ecf)
    if schema is None:
        return {"valid": False, "errors": [f"No schema available for tipo_ecf={tipo_ecf}"]}
    try:
        doc = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as e:
        return {"valid": False, "errors": [f"XML syntax error: {e}"]}
    valid = schema.validate(doc)
    errors = []
    if not valid:
        for error in schema.error_log:
            errors.append(f"Line {error.line}, col {error.column}: {error.message}")
    return {
        "valid": valid,
        "errors": errors,
        "error_count": len(errors),
    }
