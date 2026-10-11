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
    def _indicador_to_rate(indicador):
        """Mapea IndicadorFacturacion a tasa de ITBIS (0/1=18%, 2=16%, 3=0%, 4=exento)."""
        ind = str(indicador or "").strip()
        if ind in ("0", "1"):
            return 0.18
        if ind == "2":
            return 0.16
        return 0.0

    @staticmethod
    def normalize_date_iso(date_str):
        if not date_str:
            return ""
        clean = str(date_str).strip()[:10]
        parts = clean.split("-")
        if len(parts) == 3:
            if len(parts[0]) == 4:
                return clean  # YYYY-MM-DD
            if len(parts[2]) == 4:
                return f"{parts[2]}-{parts[1]}-{parts[0]}"  # DD-MM-YYYY -> YYYY-MM-DD
        parts_slash = clean.split("/")
        if len(parts_slash) == 3:
            if len(parts_slash[0]) == 4:
                return f"{parts_slash[0]}-{parts_slash[1]}-{parts_slash[2]}"
            if len(parts_slash[2]) == 4:
                return f"{parts_slash[2]}-{parts_slash[1]}-{parts_slash[0]}"
        return clean

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
            "fecha_emision_iso": "",
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
            "monto_impuesto_adicional": 0.0,
            "monto_servicios": 0.0,
            "monto_bienes": 0.0,
            "ncf_modificado": "",
            "tipo_pago": "2",
            "forma_pago_606": "02",
            "detalle_items": [],
        }

    @staticmethod
    def parse_ecf_detail(xml_bytes):
        """Parseo enriquecido del e-CF recibido para la vista de detalle y el 606.

        Extrae fechas, totales por banda de ITBIS, retenciones, desglose de
        bienes vs servicios, NCF modificado (si aplica) e items.
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
        detalles = ReceptorXmlService._find_elem(root, "DetallesItems")
        info_ref = ReceptorXmlService._find_elem(root, "InformacionReferencia")

        items = []
        monto_servicios_calc = 0.0
        monto_bienes_calc = 0.0
        if detalles is not None:
            for item_elem in ReceptorXmlService._find_all(detalles, "Item"):
                indicador_facturacion = ReceptorXmlService._find_text(
                    item_elem, "IndicadorFacturacion"
                )
                indicador_bien_servicio = ReceptorXmlService._find_text(
                    item_elem, "IndicadorBienoServicio"
                ) or "1"
                precio_unitario = ReceptorXmlService._to_float(
                    ReceptorXmlService._find_text(item_elem, "PrecioUnitarioItem", "PrecioUnitario")
                )
                cantidad = ReceptorXmlService._to_float(
                    ReceptorXmlService._find_text(item_elem, "CantidadItem")
                )
                descuento = ReceptorXmlService._to_float(
                    ReceptorXmlService._find_text(item_elem, "DescuentoMonto")
                )
                monto_item = ReceptorXmlService._to_float(
                    ReceptorXmlService._find_text(item_elem, "MontoItem")
                )
                monto_exento = ReceptorXmlService._to_float(
                    ReceptorXmlService._find_text(item_elem, "MontoExento")
                )
                itbis_rate = ReceptorXmlService._indicador_to_rate(indicador_facturacion)
                base = precio_unitario * cantidad
                discount_rate = round(descuento / base, 4) if base > 0 else 0.0
                itbis_amount = 0.0
                if monto_exento <= 0 and itbis_rate > 0:
                    itbis_amount = round(monto_item * itbis_rate, 2)

                if indicador_bien_servicio == "2":
                    monto_servicios_calc += monto_item
                else:
                    monto_bienes_calc += monto_item

                item = {
                    "numero_linea": ReceptorXmlService._find_text(item_elem, "NumeroLinea"),
                    "codigo": ReceptorXmlService._find_text(item_elem, "CodigoItem"),
                    "nombre": ReceptorXmlService._find_text(item_elem, "NombreItem"),
                    "indicador_facturacion": indicador_facturacion,
                    "indicador_bien_servicio": indicador_bien_servicio,
                    "cantidad": cantidad,
                    "precio_unitario": precio_unitario,
                    "descuento": descuento,
                    "discount_rate": discount_rate,
                    "itbis_rate": itbis_rate,
                    "itbis_amount": itbis_amount,
                    "monto_item": monto_item,
                    "monto_exento": monto_exento,
                }
                items.append(item)

        raw_fecha_emision = ReceptorXmlService._find_text(emisor, "FechaEmision") if emisor is not None else ""
        fecha_emision_iso = ReceptorXmlService.normalize_date_iso(raw_fecha_emision)

        raw_fecha_venc = ReceptorXmlService._find_text(id_doc, "FechaVencimientoSecuencia") if id_doc is not None else ""
        fecha_venc_iso = ReceptorXmlService.normalize_date_iso(raw_fecha_venc)

        monto_total_val = ReceptorXmlService._to_float(
            ReceptorXmlService._find_text(totales, "MontoTotal")
        ) if totales is not None else 0.0

        if monto_servicios_calc == 0.0 and monto_bienes_calc == 0.0:
            monto_bienes_calc = monto_total_val

        ncf_modificado = ReceptorXmlService._find_text(info_ref, "NCFModificado") if info_ref is not None else ""

        tipo_pago = ReceptorXmlService._find_text(id_doc, "TipoPago") if id_doc is not None else "2"
        forma_pago_map = {"1": "01", "2": "02", "3": "03", "4": "04", "5": "05", "6": "06", "7": "07"}
        forma_pago_606 = forma_pago_map.get(tipo_pago, "02")

        detail = {
            "tipo_ecf": ReceptorXmlService._find_text(id_doc, "TipoeCF", "TipoECF", "tipoeCF") if id_doc is not None else "",
            "encf": ReceptorXmlService._find_text(id_doc, "eNCF", "ENCF") if id_doc is not None else "",
            "fecha_vencimiento": raw_fecha_venc,
            "fecha_vencimiento_iso": fecha_venc_iso,
            "rnc_emisor": ReceptorXmlService._find_text(emisor, "RNCEmisor") if emisor is not None else "",
            "razon_social_emisor": ReceptorXmlService._find_text(
                emisor, "RazonSocialEmisor", "RazonSocial"
            ) if emisor is not None else "",
            "nombre_comercial": ReceptorXmlService._find_text(emisor, "NombreComercial") if emisor is not None else "",
            "direccion_emisor": ReceptorXmlService._find_text(emisor, "DireccionEmisor") if emisor is not None else "",
            "correo_emisor": ReceptorXmlService._find_text(emisor, "CorreoEmisor") if emisor is not None else "",
            "telefono_emisor": ReceptorXmlService._find_text(emisor, "TelefonoEmisor") if emisor is not None else "",
            "fecha_emision": raw_fecha_emision,
            "fecha_emision_iso": fecha_emision_iso,
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
            "monto_total": monto_total_val,
            "monto_impuesto_adicional": ReceptorXmlService._to_float(
                ReceptorXmlService._find_text(totales, "MontoImpuestoAdicional")
            ) if totales is not None else 0.0,
            "monto_servicios": round(monto_servicios_calc, 2),
            "monto_bienes": round(monto_bienes_calc, 2),
            "ncf_modificado": ncf_modificado,
            "tipo_pago": tipo_pago,
            "forma_pago_606": forma_pago_606,
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
