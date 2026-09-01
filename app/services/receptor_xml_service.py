import uuid
from datetime import datetime, timezone, timedelta
from lxml import etree


class ReceptorXmlService:

    # ─────────────────────────────────────────────────────────────────
    # Utilidades de parseo namespace-agnostic (local-name)
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _local_name(elem):
        try:
            return etree.QName(elem).localname
        except Exception:
            return elem.tag

    @staticmethod
    def _find_text(root, *names):
        for name in names:
            for elem in root.iter():
                if ReceptorXmlService._local_name(elem) == name and elem.text and elem.text.strip():
                    return elem.text.strip()
        return ""

    @staticmethod
    def _find_elem(root, *names):
        for name in names:
            for elem in root.iter():
                if ReceptorXmlService._local_name(elem) == name:
                    return elem
        return None

    # ─────────────────────────────────────────────────────────────────
    # Firma XMLDSig del e-CF recibido
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def verify_signature(xml_bytes):
        """Verifica la firma XMLDSig. Devuelve (ok, error):
        ok=True firma válida; ok=False firma inválida; ok=None XML sin firma."""
        try:
            root = etree.fromstring(xml_bytes)
        except Exception as e:
            return False, f"XML malformado: {str(e)}"
        has_dsig = any(
            etree.QName(elem).namespace == "http://www.w3.org/2000/09/xmldsig#"
            and ReceptorXmlService._local_name(elem) == "Signature"
            for elem in root.iter()
        )
        if not has_dsig:
            return None, "El XML no contiene firma digital."
        try:
            from signxml import XMLVerifier
            XMLVerifier().verify(xml_bytes)
            return True, None
        except Exception as e:
            return False, f"Firma digital inválida: {str(e)}"

    # ─────────────────────────────────────────────────────────────────
    # Parseo del e-CF recibido
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def parse_ecf(xml_bytes):
        try:
            root = etree.fromstring(xml_bytes)
        except Exception as e:
            return None, f"XML malformado: {str(e)}"

        enc = ReceptorXmlService._find_elem(root, "Encabezado")
        if enc is None:
            return None, "No se encontró el elemento Encabezado en el XML."

        id_doc = ReceptorXmlService._find_elem(enc, "IdDoc")
        emisor = ReceptorXmlService._find_elem(enc, "Emisor")
        comprador = ReceptorXmlService._find_elem(enc, "Comprador")

        if id_doc is None:
            return None, "No se encontró IdDoc en el XML."

        tipo_ecf_full = ReceptorXmlService._find_text(id_doc, "TipoeCF", "TipoECF", "tipoeCF")
        encf = ReceptorXmlService._find_text(id_doc, "eNCF", "ENCF")

        rnc_emisor = ReceptorXmlService._find_text(emisor, "RNCEmisor") if emisor is not None else ""
        razon_social_emisor = ReceptorXmlService._find_text(emisor, "RazonSocialEmisor", "RazonSocial") if emisor is not None else ""

        rnc_comprador = ReceptorXmlService._find_text(comprador, "RNCComprador") if comprador is not None else ""
        razon_social_comprador = ReceptorXmlService._find_text(comprador, "RazonSocialComprador", "RazonSocial") if comprador is not None else ""

        totales = ReceptorXmlService._find_elem(enc, "Totales")
        monto_total_str = ReceptorXmlService._find_text(totales, "MontoTotal") if totales is not None else ""
        if not monto_total_str:
            monto_total_str = ReceptorXmlService._find_text(enc, "MontoTotal") or "0"

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

    # ─────────────────────────────────────────────────────────────────
    # Parseo enriquecido para la vista de detalle (items, totales, fechas)
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _find_all(root, *names):
        results = []
        for name in names:
            for elem in root.iter():
                if ReceptorXmlService._local_name(elem) == name:
                    results.append(elem)
        return results

    @staticmethod
    def _to_float(text):
        try:
            return float(str(text or "").strip() or 0)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def default_detail():
        """Estructura con valores por defecto para renderizar el detalle
        cuando el XML no está disponible o no se pudo parsear."""
        return {
            "tipo_ecf": "",
            "encf": "",
            "fecha_vencimiento": "",
            "rnc_emisor": "",
            "razon_social_emisor": "",
            "nombre_comercial": "",
            "direccion_emisor": "",
            "correo_emisor": "",
            "telefono_emisor": "",
            "fecha_emision": "",
            "rnc_comprador": "",
            "razon_social_comprador": "",
            "monto_gravado_total": 0.0,
            "monto_gravado_i1": 0.0,
            "monto_gravado_i2": 0.0,
            "monto_gravado_i3": 0.0,
            "monto_exento": 0.0,
            "total_itbis": 0.0,
            "total_itbis_retenido": 0.0,
            "total_isr_retencion": 0.0,
            "monto_total": 0.0,
            "detalle_items": [],
        }

    @staticmethod
    def parse_ecf_detail(xml_bytes):
        """Parseo enriquecido del e-CF recibido para la vista de detalle.

        Extrae fechas, totales por banda de ITBIS, retenciones e items.
        Es tolerante a campos ausentes (devuelve "" o 0.0) para poder
        renderizar documentos de cualquier tipo de e-CF.
        """
        try:
            root = etree.fromstring(xml_bytes)
        except Exception as e:
            return None, f"XML malformado: {str(e)}"

        enc = ReceptorXmlService._find_elem(root, "Encabezado")
        if enc is None:
            return None, "No se encontró el elemento Encabezado en el XML."

        id_doc = ReceptorXmlService._find_elem(enc, "IdDoc")
        emisor = ReceptorXmlService._find_elem(enc, "Emisor")
        comprador = ReceptorXmlService._find_elem(enc, "Comprador")
        totales = ReceptorXmlService._find_elem(enc, "Totales")
        detalles = ReceptorXmlService._find_elem(enc, "DetallesItems")

        items = []
        if detalles is not None:
            for item_elem in ReceptorXmlService._find_all(detalles, "Item"):
                item = {
                    "numero_linea": ReceptorXmlService._find_text(item_elem, "NumeroLinea"),
                    "codigo": ReceptorXmlService._find_text(item_elem, "CodigoItem"),
                    "nombre": ReceptorXmlService._find_text(item_elem, "NombreItem"),
                    "indicador_facturacion": ReceptorXmlService._find_text(
                        item_elem, "IndicadorFacturacion"
                    ),
                    "cantidad": ReceptorXmlService._to_float(
                        ReceptorXmlService._find_text(item_elem, "CantidadItem")
                    ),
                    "precio_unitario": ReceptorXmlService._to_float(
                        ReceptorXmlService._find_text(item_elem, "PrecioUnitarioItem", "PrecioUnitario")
                    ),
                    "descuento": ReceptorXmlService._to_float(
                        ReceptorXmlService._find_text(item_elem, "DescuentoMonto")
                    ),
                    "monto_item": ReceptorXmlService._to_float(
                        ReceptorXmlService._find_text(item_elem, "MontoItem")
                    ),
                    "monto_exento": ReceptorXmlService._to_float(
                        ReceptorXmlService._find_text(item_elem, "MontoExento")
                    ),
                }
                items.append(item)

        detail = {
            "tipo_ecf": ReceptorXmlService._find_text(id_doc, "TipoeCF", "TipoECF", "tipoeCF") if id_doc is not None else "",
            "encf": ReceptorXmlService._find_text(id_doc, "eNCF", "ENCF") if id_doc is not None else "",
            "fecha_vencimiento": ReceptorXmlService._find_text(
                id_doc, "FechaVencimientoSecuencia"
            ) if id_doc is not None else "",
            "rnc_emisor": ReceptorXmlService._find_text(emisor, "RNCEmisor") if emisor is not None else "",
            "razon_social_emisor": ReceptorXmlService._find_text(
                emisor, "RazonSocialEmisor", "RazonSocial"
            ) if emisor is not None else "",
            "nombre_comercial": ReceptorXmlService._find_text(emisor, "NombreComercial") if emisor is not None else "",
            "direccion_emisor": ReceptorXmlService._find_text(emisor, "DireccionEmisor") if emisor is not None else "",
            "correo_emisor": ReceptorXmlService._find_text(emisor, "CorreoEmisor") if emisor is not None else "",
            "telefono_emisor": ReceptorXmlService._find_text(emisor, "TelefonoEmisor") if emisor is not None else "",
            "fecha_emision": ReceptorXmlService._find_text(emisor, "FechaEmision") if emisor is not None else "",
            "rnc_comprador": ReceptorXmlService._find_text(comprador, "RNCComprador") if comprador is not None else "",
            "razon_social_comprador": ReceptorXmlService._find_text(
                comprador, "RazonSocialComprador", "RazonSocial"
            ) if comprador is not None else "",
            "monto_gravado_total": ReceptorXmlService._to_float(
                ReceptorXmlService._find_text(totales, "MontoGravadoTotal")
            ) if totales is not None else 0.0,
            "monto_gravado_i1": ReceptorXmlService._to_float(
                ReceptorXmlService._find_text(totales, "MontoGravadoI1")
            ) if totales is not None else 0.0,
            "monto_gravado_i2": ReceptorXmlService._to_float(
                ReceptorXmlService._find_text(totales, "MontoGravadoI2")
            ) if totales is not None else 0.0,
            "monto_gravado_i3": ReceptorXmlService._to_float(
                ReceptorXmlService._find_text(totales, "MontoGravadoI3")
            ) if totales is not None else 0.0,
            "monto_exento": ReceptorXmlService._to_float(
                ReceptorXmlService._find_text(totales, "MontoExento")
            ) if totales is not None else 0.0,
            "total_itbis": ReceptorXmlService._to_float(
                ReceptorXmlService._find_text(totales, "TotalITBIS", "TotalITBIS1", "TotalItbis")
            ) if totales is not None else 0.0,
            "total_itbis_retenido": ReceptorXmlService._to_float(
                ReceptorXmlService._find_text(totales, "TotalITBISRetenido")
            ) if totales is not None else 0.0,
            "total_isr_retencion": ReceptorXmlService._to_float(
                ReceptorXmlService._find_text(totales, "TotalISRRetencion", "TotalRetencionesISR")
            ) if totales is not None else 0.0,
            "monto_total": ReceptorXmlService._to_float(
                ReceptorXmlService._find_text(totales, "MontoTotal")
            ) if totales is not None else 0.0,
            "detalle_items": items,
        }
        return detail, None

    # ─────────────────────────────────────────────────────────────────
    # ARECF (Acuse de Recibo) — formato oficial Schemas/ARECF v1.0.xsd
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def build_arecf(receiver_rnc, parsed_ecf, estado="0", codigo_motivo=None):
        root = etree.Element("ARECF")
        detalle = etree.SubElement(root, "DetalleAcusedeRecibo")
        etree.SubElement(detalle, "Version").text = "1.0"
        etree.SubElement(detalle, "RNCEmisor").text = parsed_ecf.get("rnc_emisor", "")
        etree.SubElement(detalle, "RNCComprador").text = receiver_rnc
        etree.SubElement(detalle, "eNCF").text = parsed_ecf.get("encf", "")
        etree.SubElement(detalle, "Estado").text = estado
        if estado == "1" and codigo_motivo is not None:
            etree.SubElement(detalle, "CodigoMotivoNoRecibido").text = str(codigo_motivo)
        now = datetime.now(timezone.utc) - timedelta(hours=4)
        etree.SubElement(detalle, "FechaHoraAcuseRecibo").text = now.strftime("%d-%m-%Y %H:%M:%S")
        track_id = uuid.uuid4().hex[:20].upper()
        return etree.tostring(root, encoding="utf-8", xml_declaration=True), track_id

    # ─────────────────────────────────────────────────────────────────
    # Aprobación Comercial (ACECF)
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def parse_approval(xml_bytes):
        try:
            root = etree.fromstring(xml_bytes)
        except Exception as e:
            return None, f"XML malformado: {str(e)}"

        encf = ReceptorXmlService._find_text(root, "eNCF", "ENCF", "encf")
        tipo = ReceptorXmlService._find_text(root, "TipoeCF", "TipoECF", "tipoeCF")
        rnc_emisor = ReceptorXmlService._find_text(root, "RNCEmisor", "rncEmisor")
        rnc_comprador = ReceptorXmlService._find_text(root, "RNCComprador", "rncComprador")
        razon_social = ReceptorXmlService._find_text(root, "RazonSocialEmisor", "RazonSocial")

        return {
            "encf": encf,
            "tipo_ecf": tipo,
            "rnc_emisor": rnc_emisor,
            "rnc_comprador": rnc_comprador,
            "razon_social_emisor": razon_social,
        }, None
