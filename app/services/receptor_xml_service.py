import uuid
from datetime import datetime, timezone
from lxml import etree


class ReceptorXmlService:

    @staticmethod
    def parse_ecf(xml_bytes):
        try:
            root = etree.fromstring(xml_bytes)
        except Exception as e:
            return None, f"XML malformado: {str(e)}"

        ns = {"ns": "http://www.dgii.gov.do/ecf"}

        def find_text(parent, *path):
            for tag in path:
                elem = parent.find(f".//{tag}")
                if elem is not None and elem.text:
                    return elem.text.strip()
                elem = parent.find(f".//ns:{tag}", ns)
                if elem is not None and elem.text:
                    return elem.text.strip()
            return ""

        enc = root.find("Encabezado") or root.find(".//Encabezado")
        if enc is None:
            return None, "No se encontró el elemento Encabezado en el XML."

        id_doc = enc.find("IdDoc")
        emisor = enc.find("Emisor")
        comprador = enc.find("Comprador")

        if id_doc is None:
            return None, "No se encontró IdDoc en el XML."

        tipo_ecf_full = find_text(id_doc, "TipoeCF", "TipoECF", "tipoeCF")
        encf = find_text(id_doc, "eNCF", "ENCF")

        rnc_emisor = find_text(emisor, "RNCEmisor") if emisor is not None else ""
        razon_social_emisor = find_text(emisor, "RazonSocialEmisor", "RazonSocial") if emisor is not None else ""

        rnc_comprador = find_text(comprador, "RNCComprador") if comprador is not None else ""
        razon_social_comprador = find_text(comprador, "RazonSocialComprador", "RazonSocial") if comprador is not None else ""

        monto_total_str = find_text(enc, "MontoTotal") or find_text(enc, "Totales/MontoTotal") or "0"

        try:
            monto_total = float(monto_total_str)
        except ValueError:
            monto_total = 0.0

        return {
            "tipo_ecf": tipo_ecf_full,
            "encf": encf,
            "rnc_emisor": rnc_emisor,
            "razon_social_emisor": razon_social_emisor,
            "rnc_comprador": rnc_comprador,
            "razon_social_comprador": razon_social_comprador,
            "monto_total": monto_total,
        }, None

    @staticmethod
    def build_arecf(receiver_rnc, parsed_ecf, estado="0"):
        root = etree.Element("arecf", nsmap={
            "xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsd": "http://www.w3.org/2001/XMLSchema"
        })
        detalle = etree.SubElement(root, "detalleacusederecibo")
        etree.SubElement(detalle, "version").text = "1.0"
        etree.SubElement(detalle, "rncemisor").text = parsed_ecf.get("rnc_emisor", "")
        etree.SubElement(detalle, "rnccomprador").text = receiver_rnc
        etree.SubElement(detalle, "encf").text = parsed_ecf.get("encf", "")
        etree.SubElement(detalle, "estado").text = estado
        now_str = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S")
        etree.SubElement(detalle, "fechahoraacuserecibo").text = now_str
        track_id = uuid.uuid4().hex[:20].upper()
        etree.SubElement(detalle, "trackid").text = track_id
        return etree.tostring(root, encoding="utf-8", xml_declaration=True), track_id

    @staticmethod
    def parse_approval(xml_bytes):
        try:
            root = etree.fromstring(xml_bytes)
        except Exception as e:
            return None, f"XML malformado: {str(e)}"

        def find_text(parent, *path):
            for tag in path:
                elem = parent.find(f".//{tag}")
                if elem is not None and elem.text:
                    return elem.text.strip()
            return ""

        encf = find_text(root, "eNCF", "ENCF", "encf")
        tipo = find_text(root, "TipoeCF", "TipoECF", "tipoeCF")
        rnc_emisor = find_text(root, "RNCEmisor", "rncEmisor")
        rnc_comprador = find_text(root, "RNCComprador", "rncComprador")
        razon_social = find_text(root, "RazonSocialEmisor", "RazonSocial")

        return {
            "encf": encf,
            "tipo_ecf": tipo,
            "rnc_emisor": rnc_emisor,
            "rnc_comprador": rnc_comprador,
            "razon_social_emisor": razon_social,
        }, None
