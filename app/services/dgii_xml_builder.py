import xml.etree.ElementTree as ET
from datetime import datetime

class DgiiXmlBuilder:
    
    @classmethod
    def map_unit_of_measure(cls, unit_str):
        """Mapea las unidades de texto de nuestro catálogo a los códigos numéricos oficiales de la DGII (Tabla IV)."""
        if not unit_str:
            return "43"  # Por defecto: Unidad (UND)
        unit_str = str(unit_str).lower().strip()
        
        mapping = {
            "unidad": "43",
            "ud": "43",
            "caja": "6",
            "cj": "6",
            "hora": "19",
            "hr": "19",
            "servicio": "43",
            "srv": "43",
            "mes": "43",
            "granel": "18",
            "bandeja": "57",
            "quintal": "51",
            "hectarea": "58",
            "hectárea": "58",
            "mililitro": "59",
            "miligramo": "60",
            "onzas": "61",
            "onzas troy": "62",
            "pasajero": "54",
            "pulgadas": "55",
            "otros": "43"
        }
        return mapping.get(unit_str, "43")

    @classmethod
    def map_currency(cls, currency_str):
        """Mapea códigos de moneda a los oficiales de la DGII (Tabla II)."""
        if not currency_str:
            return "DOP"
        currency_str = str(currency_str).upper().strip()
        
        mapping = {
            "DOP": "DOP",
            "USD": "USD",
            "EUR": "EUR",
            "BRL": "BRL",
            "CAD": "CAD",
            "CHF": "CHF",
            "CHY": "CHY",
            "XDR": "XDR",
            "DKK": "DKK",
            "GBP": "GBP",
            "JPY": "JPY",
            "NOK": "NOK",
            "SCP": "SCP",
            "SEK": "SEK",
            "VEF": "VEF",
            "HTG": "HTG",
            "MXN": "MXN",
            "COP": "COP",
            "ARS": "ARS"
        }
        return mapping.get(currency_str, "DOP")

    @classmethod
    def map_province_or_municipality(cls, name_str, is_province=True):
        """
        Mapea el nombre de la provincia o municipio a su código oficial de la DGII de 6 dígitos (Tabla III).
        Si ya es un código numérico válido de 6 dígitos, lo devuelve directamente.
        """
        if not name_str:
            return "010000" if is_province else "010100"
            
        clean_name = str(name_str).strip()
        
        # Si ya es un código de 6 dígitos numéricos, devolverlo directamente
        if len(clean_name) == 6 and clean_name.isdigit():
            return clean_name
            
        clean_name = clean_name.lower()
        
        # Mapeo de Provincias comunes (Tabla III)
        provincias = {
            "distrito nacional": "010000",
            "azua": "020000",
            "bahoruco": "030000",
            "barahona": "040000",
            "dajabón": "050000",
            "dajabon": "050000",
            "duarte": "060000",
            "elías piña": "070000",
            "elias pina": "070000",
            "el seibo": "080000",
            "espaillat": "090000",
            "independencia": "100000",
            "la altagracia": "110000",
            "la romana": "120000",
            "la vega": "130000",
            "maría trinidad sánchez": "140000",
            "maria trinidad sanchez": "140000",
            "monte cristi": "150000",
            "pedernales": "160000",
            "peravia": "170000",
            "puerto plata": "180000",
            "hermanas mirabal": "190000",
            "samaná": "200000",
            "samana": "200000",
            "san cristóbal": "210000",
            "san cristobal": "210000",
            "san juan": "220000",
            "san pedro de macorís": "230000",
            "san pedro de macoris": "230000",
            "sánchez ramírez": "240000",
            "sanchez ramirez": "240000",
            "santiago": "250000",
            "santiago rodríguez": "260000",
            "santiago rodriguez": "260000",
            "valverde": "270000",
            "monseñor nouel": "280000",
            "monsenor nouel": "280000",
            "monte plata": "290000",
            "hato mayor": "300000",
            "san josé de ocoa": "310000",
            "san jose de ocoa": "310000",
            "santo domingo": "320000"
        }
        
        # Mapeo de Municipios comunes (Tabla III)
        municipios = {
            "santo domingo de guzmán": "010100",
            "santo domingo de guzman": "010100",
            "azua": "020100",
            "las charcas": "020200",
            "las yayas de viajama": "020300",
            "padre las casas": "020400",
            "peralta": "020500",
            "sabana yegua": "020600",
            "pueblo viejo": "020700",
            "tábara arriba": "020800",
            "tabara arriba": "020800",
            "guayabal": "020900",
            "estebanía": "021000",
            "estebania": "021000",
            "neiba": "030100",
            "galván": "030200",
            "galvan": "030200",
            "tamayo": "030300",
            "villa jaragua": "030400",
            "los ríos": "030500",
            "los rios": "030500",
            "barahona": "040100",
            "cabral": "040200",
            "enriquillo": "040300",
            "paraíso": "040400",
            "paraiso": "040400",
            "vicente noble": "040500",
            "el peñón": "040600",
            "el penon": "040600",
            "la ciénaga": "040700",
            "la cienaga": "040700",
            "fundación": "040800",
            "fundacion": "040800",
            "las salinas": "040900",
            "polo": "041000",
            "jaquimeyes": "041100",
            "dajabón": "050100",
            "dajabon": "050100",
            "san francisco de macorís": "060100",
            "san francisco de macoris": "060100",
            "higüey": "110100",
            "higuey": "110100",
            "punta cana": "110104",
            "bávaro": "110104",
            "bavaro": "110104",
            "la romana": "120100",
            "la vega": "130100",
            "constanza": "130200",
            "jarabacoa": "130300",
            "santiago": "250100",
            "santo domingo este": "320100",
            "santo domingo oeste": "320200",
            "santo domingo norte": "320300",
            "boca chica": "320400",
            "san antonio de guerra": "320500",
            "guerra": "320500",
            "los alcarrizos": "320600",
            "pedro brand": "320700"
        }
        
        if is_province:
            return provincias.get(clean_name, "010000")  # Distrito Nacional por defecto
        else:
            return municipios.get(clean_name, "010100")  # Santo Domingo de Guzmán por defecto

    @classmethod
    def build_invoice_xml(cls, company_profile, invoice_data):
        """
        Construye el árbol XML de un e-CF según las especificaciones del estándar de la DGII.
        """
        # Determinar tipo de comprobante de acuerdo a la factura
        raw_type = invoice_data.get('ecfType', 'Factura de Consumo (E32)')
        tipo_ecf = "32" # Consumo por defecto
        if "31" in raw_type or "Crédito Fiscal" in raw_type:
            tipo_ecf = "31"
        elif "33" in raw_type or "Nota de Débito" in raw_type:
            tipo_ecf = "33"
        elif "34" in raw_type or "Nota de Crédito" in raw_type:
            tipo_ecf = "34"
        elif "41" in raw_type or "Comprobante de Compras" in raw_type:
            tipo_ecf = "41"
        elif "43" in raw_type or "Gastos Menores" in raw_type:
            tipo_ecf = "43"
            
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
        
        # Tipo de moneda (Mapeado a Tabla II)
        currency_code = cls.map_currency(invoice_data.get("currency", "DOP"))
        ET.SubElement(id_doc, "TipoMoneda").text = currency_code
        
        # Indicadores requeridos
        ET.SubElement(id_doc, "IndicadorMontoGravado").text = "0" if tipo_ecf in ["31", "32", "33", "34"] else "1"
        ET.SubElement(id_doc, "TipoIngresos").text = "01"
        
        # TipoPago y FormaPago
        pay_method = invoice_data.get("paymentMethod", "Efectivo")
        tipo_pago = "2" if pay_method.lower() == "crédito" or pay_method.lower() == "credito" else "1"
        ET.SubElement(id_doc, "TipoPago").text = tipo_pago
        
        # Tabla Formas de Pago
        tabla_formas = ET.SubElement(id_doc, "TablaFormasPago")
        forma_de_pago = ET.SubElement(tabla_formas, "FormaDePago")
        
        # Mapeo a FormaPago (1: Efectivo, 2: Cheque, 3: Tarjeta, etc.)
        forma_pago_val = "1" # Efectivo
        if "tarjeta" in pay_method.lower():
            forma_pago_val = "3"
        elif "cheque" in pay_method.lower():
            forma_pago_val = "2"
            
        ET.SubElement(forma_de_pago, "FormaPago").text = forma_pago_val
        ET.SubElement(forma_de_pago, "MontoPago").text = f"{float(invoice_data.get('total', 0.0)):.2f}"
        
        # Encabezado -> Emisor
        emisor = ET.SubElement(encabezado, "Emisor")
        ET.SubElement(emisor, "RNCEDOC").text = company_profile.get("companyRNC", "").replace("-", "")
        ET.SubElement(emisor, "RazonSocial").text = company_profile.get("companyName", "Mi Empresa SRL")
        ET.SubElement(emisor, "NombreComercial").text = company_profile.get("tradeName", "")
        ET.SubElement(emisor, "DomicilioFiscal").text = company_profile.get("companyAddress", "")
        
        # Provincia y Municipio oficiales de Emisor (Tabla III)
        mun_code = cls.map_province_or_municipality(company_profile.get("municipality", ""), is_province=False)
        prov_code = cls.map_province_or_municipality(company_profile.get("province", ""), is_province=True)
        ET.SubElement(emisor, "Municipio").text = mun_code
        ET.SubElement(emisor, "Provincia").text = prov_code
        
        ET.SubElement(emisor, "TelefonoEmisor").text = company_profile.get("companyPhone", "809-555-5555")
        
        correo_emisor = company_profile.get("companyEmail")
        if correo_emisor:
            ET.SubElement(emisor, "CorreoEmisor").text = correo_emisor
            
        internal_num = invoice_data.get("internalInvoiceNumber") or str(invoice_data.get("invoiceNumber", ""))
        if internal_num:
            ET.SubElement(emisor, "NumeroFacturaInterna").text = str(internal_num)[:60]
        
        total_amount = float(invoice_data.get("total", 0.0))
        
        # Encabezado -> Receptor (Condicional según actualización 19-11-2021)
        receptor = ET.SubElement(encabezado, "Receptor")
        is_expense_ecf = tipo_ecf in ["41", "43"]
        
        if is_expense_ecf:
            # Para E41/E43 el receptor es la misma empresa (comprador del gasto)
            company_rnc = company_profile.get("companyRNC", "").replace("-", "").strip()
            company_name = company_profile.get("companyName", "Mi Empresa SRL")
            ET.SubElement(receptor, "RNCReceptor").text = company_rnc or "999999999"
            ET.SubElement(receptor, "RazonSocialReceptor").text = company_name
            mun_comp = cls.map_province_or_municipality(company_profile.get("municipality", "Santo Domingo de Guzmán"), is_province=False)
            prov_comp = cls.map_province_or_municipality(company_profile.get("province", "Santo Domingo"), is_province=True)
            ET.SubElement(receptor, "MunicipioComprador").text = mun_comp
            ET.SubElement(receptor, "ProvinciaComprador").text = prov_comp
        else:
            client_rnc = invoice_data.get("clientRNC", "").replace("-", "").strip()
            razon_social_rec = invoice_data.get("razonSocial", invoice_data.get("clientName", "")).strip()
            
            total_amount = float(invoice_data.get("total", 0.0))
            is_consumo_or_related = tipo_ecf in ["32", "33", "34"]
            is_less_than_250k = total_amount < 250000.00
            
            # Si es Consumo, NC o ND menor de RD$ 250,000, los campos son condicionales
            if is_consumo_or_related and is_less_than_250k:
                if client_rnc:
                    ET.SubElement(receptor, "RNCReceptor").text = client_rnc
                if razon_social_rec:
                    ET.SubElement(receptor, "RazonSocialReceptor").text = razon_social_rec
                
                # Enviar provincia y municipio si están presentes
                if invoice_data.get("clientMunicipality"):
                    mun_comp = cls.map_province_or_municipality(invoice_data.get("clientMunicipality"), is_province=False)
                    ET.SubElement(receptor, "MunicipioComprador").text = mun_comp
                if invoice_data.get("clientProvince"):
                    prov_comp = cls.map_province_or_municipality(invoice_data.get("clientProvince"), is_province=True)
                    ET.SubElement(receptor, "ProvinciaComprador").text = prov_comp
            else:
                # En otros casos, forzar los datos obligatorios
                ET.SubElement(receptor, "RNCReceptor").text = client_rnc if client_rnc else "999999999"
                ET.SubElement(receptor, "RazonSocialReceptor").text = razon_social_rec if razon_social_rec else "Consumidor Final"
                
                mun_comp = cls.map_province_or_municipality(invoice_data.get("clientMunicipality", "Santo Domingo de Guzmán"), is_province=False)
                prov_comp = cls.map_province_or_municipality(invoice_data.get("clientProvince", "Santo Domingo"), is_province=True)
                ET.SubElement(receptor, "MunicipioComprador").text = mun_comp
                ET.SubElement(receptor, "ProvinciaComprador").text = prov_comp
        
        # Encabezado -> Totales (Actualización 28-07-2020: Retenciones obligatorias a cero)
        totales = ET.SubElement(encabezado, "Totales")
        ET.SubElement(totales, "MontoSubtotal").text = f"{float(invoice_data.get('subtotal', 0.0)):.2f}"
        ET.SubElement(totales, "MontoDescuentoLineas").text = f"{float(invoice_data.get('subtotal', 0.0)) * float(invoice_data.get('discountRate', 0.0)):.2f}"
        ET.SubElement(totales, "MontoITBIS").text = f"{float(invoice_data.get('totalITBIS', 0.0)):.2f}"
        
        # Retenciones obligatorias explícitas (soportando cero)
        retained_itbis = float(invoice_data.get("retainedITBIS", 0.0))
        retained_isr = float(invoice_data.get("retainedISR", 0.0))
        ET.SubElement(totales, "TotalITBISRetenido").text = f"{retained_itbis:.2f}"
        ET.SubElement(totales, "TotalISRRetencion").text = f"{retained_isr:.2f}"
        
        # Mapeo y codificación de impuestos adicionales en Totales (Tabla I)
        total_isc_especifico = float(invoice_data.get("total_isc_especifico", invoice_data.get("totalISCEspecifico", invoice_data.get("totalIscEspecifico", 0.0))))
        total_isc_advalorem = float(invoice_data.get("total_isc_advalorem", invoice_data.get("totalISCAdValorem", invoice_data.get("totalIscAdvalorem", 0.0))))
        otros_impuestos = float(invoice_data.get("totalOtrosImpuestos", 0.0))
        
        monto_impuesto_adicional = total_isc_especifico + total_isc_advalorem + otros_impuestos
        if monto_impuesto_adicional > 0:
            ET.SubElement(totales, "MontoImpuestoAdicional").text = f"{monto_impuesto_adicional:.2f}"
            
            impuestos_adicionales = ET.SubElement(totales, "ImpuestosAdicionales")
            
            # Recorrer los items para agrupar impuestos adicionales reales
            grouped_taxes = {}
            for item in invoice_data.get("items", []):
                cod_imp = str(item.get("codigoImpuesto", "")).strip().zfill(3)
                if cod_imp and cod_imp != "000" and cod_imp != "00":
                    tasa = float(item.get("tasaImpuestoAdicional", 0.0))
                    val_esp = float(item.get("isc_especifico_amount", item.get("montoImpuestoSelectivoEspecifico", 0.0)))
                    val_adv = float(item.get("isc_advalorem_amount", item.get("montoImpuestoSelectivoAdvalorem", 0.0)))
                    val_otr = float(item.get("otros_impuestos_amount", 0.0))
                    
                    # Dividir el doble selectivo de alcohol / tabaco en códigos DGII independientes
                    if '006' <= cod_imp <= '018': # Alcohol Específico
                        if cod_imp not in grouped_taxes:
                            grouped_taxes[cod_imp] = {"tasa": tasa, "especifico": 0.0, "advalorem": 0.0, "otros": 0.0}
                        grouped_taxes[cod_imp]["especifico"] += val_esp
                        
                        if val_adv > 0:
                            cod_adv = str(int(cod_imp) + 17).zfill(3) # e.g. 006 + 17 = 023
                            if cod_adv not in grouped_taxes:
                                grouped_taxes[cod_adv] = {"tasa": 10.0, "especifico": 0.0, "advalorem": 0.0, "otros": 0.0}
                            grouped_taxes[cod_adv]["advalorem"] += val_adv
                            
                    elif '023' <= cod_imp <= '035': # Alcohol AdValorem
                        if cod_imp not in grouped_taxes:
                            grouped_taxes[cod_imp] = {"tasa": tasa, "especifico": 0.0, "advalorem": 0.0, "otros": 0.0}
                        grouped_taxes[cod_imp]["advalorem"] += val_adv
                        
                        if val_esp > 0:
                            cod_esp = str(int(cod_imp) - 17).zfill(3) # e.g. 023 - 17 = 006
                            if cod_esp not in grouped_taxes:
                                grouped_taxes[cod_esp] = {"tasa": 632.58, "especifico": 0.0, "advalorem": 0.0, "otros": 0.0}
                            grouped_taxes[cod_esp]["especifico"] += val_esp
                            
                    elif '019' <= cod_imp <= '022': # Cigarrillo Específico
                        if cod_imp not in grouped_taxes:
                            grouped_taxes[cod_imp] = {"tasa": tasa, "especifico": 0.0, "advalorem": 0.0, "otros": 0.0}
                        grouped_taxes[cod_imp]["especifico"] += val_esp
                        
                        if val_adv > 0:
                            cod_adv = str(int(cod_imp) + 17).zfill(3) # e.g. 019 + 17 = 036
                            if cod_adv not in grouped_taxes:
                                grouped_taxes[cod_adv] = {"tasa": 20.0, "especifico": 0.0, "advalorem": 0.0, "otros": 0.0}
                            grouped_taxes[cod_adv]["advalorem"] += val_adv
                            
                    elif '036' <= cod_imp <= '039': # Cigarrillo AdValorem
                        if cod_imp not in grouped_taxes:
                            grouped_taxes[cod_imp] = {"tasa": tasa, "especifico": 0.0, "advalorem": 0.0, "otros": 0.0}
                        grouped_taxes[cod_imp]["advalorem"] += val_adv
                        
                        if val_esp > 0:
                            cod_esp = str(int(cod_imp) - 17).zfill(3) # e.g. 036 - 17 = 019
                            if cod_esp not in grouped_taxes:
                                grouped_taxes[cod_esp] = {"tasa": 2.5, "especifico": 0.0, "advalorem": 0.0, "otros": 0.0}
                            grouped_taxes[cod_esp]["especifico"] += val_esp
                            
                    else: # Otros Impuestos (Propina, CDT, Primera Placa, etc.)
                        if cod_imp not in grouped_taxes:
                            grouped_taxes[cod_imp] = {"tasa": tasa, "especifico": 0.0, "advalorem": 0.0, "otros": 0.0}
                        grouped_taxes[cod_imp]["otros"] += val_otr
            
            for code, data in grouped_taxes.items():
                impuesto = ET.SubElement(impuestos_adicionales, "ImpuestoAdicional")
                ET.SubElement(impuesto, "TipoImpuesto").text = code
                ET.SubElement(impuesto, "TasaImpuestoAdicional").text = f"{data['tasa']:.2f}"
                
                if '006' <= code <= '022':
                    ET.SubElement(impuesto, "MontoImpuestoSelectivoConsumoEspecífico").text = f"{data['especifico']:.2f}"
                elif '023' <= code <= '039':
                    ET.SubElement(impuesto, "MontoImpuestoSelectivoConsumoAdvalorem").text = f"{data['advalorem']:.2f}"
                else:
                    ET.SubElement(impuesto, "MontoOtrosImpuestosAdicionales").text = f"{data['otros']:.2f}"
        
        ET.SubElement(totales, "MontoTotal").text = f"{total_amount:.2f}"
        
        # Detalles de Items
        detalles_items = ET.SubElement(ecf, "DetallesItems")
        
        for index, item in enumerate(invoice_data.get("items", [])):
            detalle = ET.SubElement(detalles_items, "Detail" if "detail" in ET.__dict__ else "Detalle")
            ET.SubElement(detalle, "NumeroLinea").text = str(index + 1)
            
            # Indicador (1 = Bien, 2 = Servicio)
            is_service = "servicio" in item.get("unit", "").lower() or "service" in item.get("unit", "").lower() or item.get("type", "").lower() == "servicio"
            ET.SubElement(detalle, "IndicadorBienesOServicios").text = "2" if is_service else "1"
            
            ET.SubElement(detalle, "NombreItem").text = item.get("name", "Artículo")
            
            # Unidad de medida mapeada a código oficial
            unit_code = cls.map_unit_of_measure(item.get("unit", "Unidad"))
            ET.SubElement(detalle, "UnidadMedida").text = unit_code
            
            ET.SubElement(detalle, "CantidadItem").text = f"{float(item.get('quantity', 1.0)):.2f}"
            ET.SubElement(detalle, "PrecioUnitarioItem").text = f"{float(item.get('price', 0.0)):.2f}"
            ET.SubElement(detalle, "MontoItem").text = f"{float(item.get('subtotal', 0.0)):.2f}"
            ET.SubElement(detalle, "MontoITBISItem").text = f"{float(item.get('itbisAmount', item.get('itbis_amount', 0.0))):.2f}"
            
            # Impuesto Adicional a nivel de Detalle
            cod_imp = str(item.get("codigoImpuesto", "")).strip().zfill(3)
            if cod_imp and cod_imp != "000" and cod_imp != "00":
                impuesto_detalle = ET.SubElement(detalle, "ImpuestoAdicional")
                ET.SubElement(impuesto_detalle, "TipoImpuesto").text = cod_imp
                ET.SubElement(impuesto_detalle, "TasaImpuestoAdicional").text = f"{float(item.get('tasaImpuestoAdicional', 0.0)):.2f}"
                
                val_esp = float(item.get("isc_especifico_amount", item.get("montoImpuestoSelectivoEspecifico", 0.0)))
                val_adv = float(item.get("isc_advalorem_amount", item.get("montoImpuestoSelectivoAdvalorem", 0.0)))
                val_otr = float(item.get("otros_impuestos_amount", 0.0))
                
                if '006' <= cod_imp <= '022':
                    ET.SubElement(impuesto_detalle, "MontoImpuestoSelectivoConsumoEspecífico").text = f"{val_esp:.2f}"
                elif '023' <= cod_imp <= '039':
                    ET.SubElement(impuesto_detalle, "MontoImpuestoSelectivoConsumoAdvalorem").text = f"{val_adv:.2f}"
                else:
                    ET.SubElement(impuesto_detalle, "MontoOtrosImpuestosAdicionales").text = f"{val_otr:.2f}"
            
        # Convertir a cadena de texto XML formateada
        raw_xml = ET.tostring(root, encoding="utf-8")
        return raw_xml
