import xml.etree.ElementTree as ET

class XMLImportService:

    NS = {"ecf": "http://dgii.gov.do/CF"}

    @classmethod
    def parse_ecf_xml(cls, xml_bytes):
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as e:
            return {"success": False, "message": f"Error al parsear XML: {e}"}

        ecf = root.find(".//ecf:eCF", cls.NS) or root.find(".//eCF")
        if ecf is None:
            ecf = root

        encabezado = ecf.find("Encabezado")
        if encabezado is None:
            return {"success": False, "message": "Estructura XML inválida: no se encontró Encabezado"}

        id_doc = encabezado.find("IdDoc")
        emisor = encabezado.find("Emisor")
        receptor = encabezado.find("Receptor")
        totales = encabezado.find("Totales")
        detalles_items = ecf.find("DetallesItems")

        raw_type = cls._get_text(id_doc, "TipoeCF")

        items = []
        if detalles_items is not None:
            for detalle in detalles_items.findall("Detalle"):
                items.append({
                    "lineNumber": cls._get_text(detalle, "NumeroLinea"),
                    "name": cls._get_text(detalle, "NombreItem"),
                    "unit": cls._get_text(detalle, "UnidadMedida"),
                    "quantity": cls._parse_float(detalle, "CantidadItem"),
                    "unitPrice": cls._parse_float(detalle, "PrecioUnitarioItem"),
                    "subtotal": cls._parse_float(detalle, "MontoItem"),
                    "itbisAmount": cls._parse_float(detalle, "MontoITBISItem"),
                })

        data = {
            "success": True,
            "ecfType": cls._map_ecf_type(raw_type),
            "rawEcfType": raw_type,
            "encf": cls._get_text(id_doc, "eNCF"),
            "issueDate": cls._get_text(id_doc, "FechaEmision"),
            "currency": cls._get_text(id_doc, "TipoMoneda", "DOP"),
            "paymentMethod": cls._get_text(id_doc, "TipoPago"),
            "supplierRnc": cls._get_text(emisor, "RNCEDOC"),
            "supplierName": cls._get_text(emisor, "RazonSocial"),
            "supplierTradeName": cls._get_text(emisor, "NombreComercial"),
            "supplierAddress": cls._get_text(emisor, "DomicilioFiscal"),
            "supplierMunicipality": cls._get_text(emisor, "Municipio"),
            "supplierProvince": cls._get_text(emisor, "Provincia"),
            "supplierPhone": cls._get_text(emisor, "TelefonoEmisor"),
            "supplierEmail": cls._get_text(emisor, "CorreoEmisor"),
            "buyerRnc": cls._get_text(receptor, "RNCReceptor") if receptor is not None else "",
            "buyerName": cls._get_text(receptor, "RazonSocialReceptor") if receptor is not None else "",
            "subtotal": cls._parse_float(totales, "MontoSubtotal"),
            "totalDiscount": cls._parse_float(totales, "MontoDescuentoLineas"),
            "totalITBIS": cls._parse_float(totales, "MontoITBIS"),
            "retainedITBIS": cls._parse_float(totales, "TotalITBISRetenido"),
            "retainedISR": cls._parse_float(totales, "TotalISRRetencion"),
            "total": cls._parse_float(totales, "MontoTotal"),
            "items": items,
        }
        return data

    @classmethod
    def validate_fiscal_structure(cls, parsed):
        errors = []
        if not parsed.get("encf"):
            errors.append("Falta el e-NCF")
        if not parsed.get("ecfType"):
            errors.append("Falta el tipo de e-CF")
        if not parsed.get("supplierRnc"):
            errors.append("Falta el RNC del emisor")
        if not parsed.get("supplierName"):
            errors.append("Falta la razón social del emisor")
        if parsed.get("total") is None or parsed["total"] <= 0:
            errors.append("El monto total debe ser mayor a 0")
        if parsed.get("subtotal") is None or parsed["subtotal"] < 0:
            errors.append("El subtotal no puede ser negativo")
        return errors

    @classmethod
    def items_to_text(cls, parsed):
        items = parsed.get("items", [])
        if not items:
            return parsed.get("supplierName", "")
        descriptions = []
        for item in items:
            name = item.get("name", "")
            qty = item.get("quantity")
            qty_str = f" x{qty}" if qty else ""
            descriptions.append(f"{name}{qty_str}")
        return "; ".join(descriptions)

    @classmethod
    def _get_text(cls, parent, tag, default=""):
        if parent is None:
            return default
        el = parent.find(tag)
        if el is not None and el.text:
            return el.text.strip()
        ns_tag = f"{{{cls.NS['ecf']}}}{tag}"
        el = parent.find(ns_tag)
        if el is not None and el.text:
            return el.text.strip()
        return default

    @classmethod
    def _parse_float(cls, parent, tag):
        text = cls._get_text(parent, tag)
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return 0.0

    @classmethod
    def _map_ecf_type(cls, raw):
        if not raw:
            return ""
        raw = raw.strip()
        mapping = {
            "31": "E31", "32": "E32", "33": "E33", "34": "E34",
            "41": "E41", "43": "E43", "44": "E44", "45": "E45",
            "46": "E46", "47": "E47",
        }
        if raw in mapping:
            return mapping[raw]
        if raw.startswith("E"):
            raw_clean = raw.upper()[:3]
            return raw_clean if raw_clean in mapping.values() else raw
        return f"E{raw}" if raw.isdigit() else raw
