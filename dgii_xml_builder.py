import xml.etree.ElementTree as ET
from datetime import datetime

class DgiiXmlBuilder:
    
    @classmethod
    def build_invoice_xml(cls, company_profile, invoice_data):
        """
        Construye el árbol XML de un e-CF según las especificaciones del estándar de la DGII.
        Soporta Crédito Fiscal (Tipo 31) y Consumo (Tipo 32).
        """
        # Determinar tipo de comprobante de acuerdo a la factura
        raw_type = invoice_data.get('ecfType', 'Factura de Consumo (E32)')
        tipo_ecf = "32" # Consumo por defecto
        if "31" in raw_type or "Crédito Fiscal" in raw_type:
            tipo_ecf = "31"
            
        # Crear Elemento Raíz
        root = ET.Element("ECF")
        root.set("xmlns", "http://dgii.gov.do/CF")
        root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
        root.set("xsi:schemaLocation", "http://dgii.gov.do/CF nuevo_ecf.xsd")
        
        # Estructura interna eCF
        ecf = ET.SubElement(root, "eCF")
        
        # Encabezado
        encabezado = ET.SubElement(ecf, "Encabezado")
        
        # Encabezado -> IdDoc
        id_doc = ET.SubElement(encabezado, "IdDoc")
        ET.SubElement(id_doc, "TipoeCF").text = tipo_ecf
        ET.SubElement(id_doc, "eNCF").text = invoice_data.get("encf", "E" + tipo_ecf + "0000000001")
        ET.SubElement(id_doc, "FechaEmision").text = datetime.utcnow().strftime("%Y-%m-%d")
        
        # Forma de pago (1 = Efectivo, 2 = Crédito, etc.)
        pay_method = invoice_data.get("paymentMethod", "Efectivo")
        forma_pago = "1" if pay_method == "Efectivo" else "2"
        ET.SubElement(id_doc, "FormaPago").text = forma_pago
        
        # Encabezado -> Emisor
        emisor = ET.SubElement(encabezado, "Emisor")
        ET.SubElement(emisor, "RNCEDOC").text = company_profile.get("companyRNC", "").replace("-", "")
        ET.SubElement(emisor, "RazonSocial").text = company_profile.get("companyName", "Mi Empresa SRL")
        ET.SubElement(emisor, "NombreComercial").text = company_profile.get("tradeName", "")
        ET.SubElement(emisor, "DomicilioFiscal").text = company_profile.get("companyAddress", "")
        ET.SubElement(emisor, "TelefonoEmisor").text = company_profile.get("companyPhone", "")
        
        # Encabezado -> Receptor
        receptor = ET.SubElement(encabezado, "Receptor")
        ET.SubElement(receptor, "RNCReceptor").text = invoice_data.get("clientRNC", "").replace("-", "")
        ET.SubElement(receptor, "RazonSocialReceptor").text = invoice_data.get("razonSocial", "Consumidor Final")
        
        # Encabezado -> Totales
        totales = ET.SubElement(encabezado, "Totales")
        ET.SubElement(totales, "MontoSubtotal").text = f"{float(invoice_data.get('subtotal', 0.0)):.2f}"
        ET.SubElement(totales, "MontoDescuentoLineas").text = f"{float(invoice_data.get('subtotal', 0.0)) * float(invoice_data.get('discountRate', 0.0)):.2f}"
        ET.SubElement(totales, "MontoITBIS").text = f"{float(invoice_data.get('totalITBIS', 0.0)):.2f}"
        ET.SubElement(totales, "MontoTotal").text = f"{float(invoice_data.get('total', 0.0)):.2f}"
        
        # Detalles de Items
        detalles_items = ET.SubElement(ecf, "DetallesItems")
        
        for index, item in enumerate(invoice_data.get("items", [])):
            detalle = ET.SubElement(detalles_items, "Detalle")
            ET.SubElement(detalle, "NumeroLinea").text = str(index + 1)
            
            # Indicador (1 = Bien, 2 = Servicio)
            is_service = "servicio" in item.get("unit", "").lower() or "service" in item.get("unit", "").lower() or item.get("type", "").lower() == "servicio"
            ET.SubElement(detalle, "IndicadorBienesOServicios").text = "2" if is_service else "1"
            
            ET.SubElement(detalle, "NombreItem").text = item.get("name", "Artículo")
            ET.SubElement(detalle, "CantidadItem").text = f"{float(item.get('quantity', 1.0)):.2f}"
            ET.SubElement(detalle, "PrecioUnitarioItem").text = f"{float(item.get('price', 0.0)):.2f}"
            ET.SubElement(detalle, "MontoItem").text = f"{float(item.get('subtotal', 0.0)):.2f}"
            ET.SubElement(detalle, "MontoITBISItem").text = f"{float(item.get('itbisAmount', item.get('itbis_amount', 0.0))):.2f}"
            
        # Convertir a cadena de texto XML formateada
        raw_xml = ET.tostring(root, encoding="utf-8")
        return raw_xml
