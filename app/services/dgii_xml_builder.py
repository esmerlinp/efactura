import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from app.models.fiscal_document_type import get_tipo_config, has_itbis_breakdown, has_retencion_item


class DgiiXmlBuilder:

    @classmethod
    def map_unit_of_measure(cls, unit_str):
        if not unit_str:
            return "43"
        unit_str = str(unit_str).lower().strip()
        mapping = {
            "unidad": "43", "ud": "43", "caja": "6", "cj": "6",
            "hora": "19", "hr": "19", "servicio": "43", "srv": "43",
            "mes": "43", "granel": "18", "bandeja": "57", "quintal": "51",
            "hectarea": "58", "hectárea": "58", "mililitro": "59",
            "miligramo": "60", "onzas": "61", "onzas troy": "62",
            "pasajero": "54", "pulgadas": "55", "otros": "43",
        }
        return mapping.get(unit_str, "43")

    @classmethod
    def map_currency(cls, currency_str):
        if not currency_str:
            return "DOP"
        currency_str = str(currency_str).upper().strip()
        mapping = {
            "DOP": "DOP", "USD": "USD", "EUR": "EUR", "BRL": "BRL",
            "CAD": "CAD", "CHF": "CHF", "CHY": "CHY", "XDR": "XDR",
            "DKK": "DKK", "GBP": "GBP", "JPY": "JPY", "NOK": "NOK",
            "SCP": "SCP", "SEK": "SEK", "VEF": "VEF", "HTG": "HTG",
            "MXN": "MXN", "COP": "COP", "ARS": "ARS",
        }
        return mapping.get(currency_str, "DOP")

    @classmethod
    def map_province_or_municipality(cls, name_str, is_province=True):
        if not name_str:
            return "010000" if is_province else "010100"
        clean_name = str(name_str).strip()
        if len(clean_name) == 6 and clean_name.isdigit():
            return clean_name
        clean_name = clean_name.lower()
        provincias = {
            "distrito nacional": "010000", "azua": "020000",
            "bahoruco": "030000", "barahona": "040000",
            "dajabón": "050000", "dajabon": "050000",
            "duarte": "060000", "elías piña": "070000",
            "elias pina": "070000", "el seibo": "080000",
            "espaillat": "090000", "independencia": "100000",
            "la altagracia": "110000", "la romana": "120000",
            "la vega": "130000", "maría trinidad sánchez": "140000",
            "maria trinidad sanchez": "140000", "monte cristi": "150000",
            "pedernales": "160000", "peravia": "170000",
            "puerto plata": "180000", "hermanas mirabal": "190000",
            "samaná": "200000", "samana": "200000",
            "san cristóbal": "210000", "san cristobal": "210000",
            "san juan": "220000", "san pedro de macorís": "230000",
            "san pedro de macoris": "230000",
            "sánchez ramírez": "240000", "sanchez ramirez": "240000",
            "santiago": "250000", "santiago rodríguez": "260000",
            "santiago rodriguez": "260000", "valverde": "270000",
            "monseñor nouel": "280000", "monsenor nouel": "280000",
            "monte plata": "290000", "hato mayor": "300000",
            "san josé de ocoa": "310000", "san jose de ocoa": "310000",
            "santo domingo": "320000",
        }
        municipios = {
            "santo domingo de guzmán": "010100",
            "santo domingo de guzman": "010100",
            "azua": "020100", "las charcas": "020200",
            "las yayas de viajama": "020300", "padre las casas": "020400",
            "peralta": "020500", "sabana yegua": "020600",
            "pueblo viejo": "020700", "tábara arriba": "020800",
            "tabara arriba": "020800", "guayabal": "020900",
            "estebanía": "021000", "estebania": "021000",
            "neiba": "030100", "galván": "030200", "galvan": "030200",
            "tamayo": "030300", "villa jaragua": "030400",
            "los ríos": "030500", "los rios": "030500",
            "barahona": "040100", "cabral": "040200",
            "enriquillo": "040300", "paraíso": "040400",
            "paraiso": "040400", "vicente noble": "040500",
            "el peñón": "040600", "el penon": "040600",
            "la ciénaga": "040700", "la cienaga": "040700",
            "fundación": "040800", "fundacion": "040800",
            "las salinas": "040900", "polo": "041000",
            "jaquimeyes": "041100", "dajabón": "050100",
            "dajabon": "050100", "san francisco de macorís": "060100",
            "san francisco de macoris": "060100", "higüey": "110100",
            "higuey": "110100", "punta cana": "110104",
            "bávaro": "110104", "bavaro": "110104",
            "la romana": "120100", "la vega": "130100",
            "constanza": "130200", "jarabacoa": "130300",
            "santiago": "250100", "santo domingo este": "320100",
            "santo domingo oeste": "320200", "santo domingo norte": "320300",
            "boca chica": "320400", "san antonio de guerra": "320500",
            "guerra": "320500", "los alcarrizos": "320600",
            "pedro brand": "320700",
        }
        if is_province:
            return provincias.get(clean_name, "010000")
        else:
            return municipios.get(clean_name, "010100")

    @classmethod
    def _detect_tipo_ecf(cls, raw_type):
        tipo_ecf = "32"
        for key, pattern in [
            ("31", ["31", "crédito fiscal", "credito fiscal"]),
            ("33", ["33", "nota de débito", "nota de debito"]),
            ("34", ["34", "nota de crédito", "nota de credito"]),
            ("41", ["41", "comprobante de compras"]),
            ("43", ["43", "gastos menores"]),
            ("44", ["44", "regímenes especiales", "regimenes especiales"]),
            ("45", ["45", "gubernamental"]),
            ("46", ["46", "exportación", "exportacion"]),
            ("48", ["48", "clientes del exterior", "cliente del exterior"]),
            ("47", ["47", "pagos al exterior"]),
            ("49", ["49", "zona franca", "zonas francas"]),
        ]:
            rl = raw_type.lower()
            if any(p in rl for p in pattern):
                tipo_ecf = key
                break
        return tipo_ecf

    @classmethod
    def _sd(cls, val, default="0.00"):
        try:
            return f"{float(val):.2f}"
        except (ValueError, TypeError):
            return default

    @classmethod
    def _fmt_date(cls, date_str):
        if not date_str:
            return None
        date_str = str(date_str).strip()[:10]
        parts = date_str.split("-")
        if len(parts) == 3 and len(parts[0]) == 4:
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
        return date_str

    @classmethod
    def _fmt_phone(cls, phone):
        if not phone:
            return None
        digits = "".join(c for c in phone if c.isdigit())
        if len(digits) == 10:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        return digits[:20]

    @classmethod
    def _country_name(cls, code):
        if not code or len(code) != 2:
            return code or "República Dominicana"
        countries = {
            "DO": "República Dominicana", "US": "Estados Unidos de América",
            "ES": "España", "FR": "Francia", "DE": "Alemania",
            "IT": "Italia", "GB": "Reino Unido", "CA": "Canadá",
            "MX": "México", "BR": "Brasil", "AR": "Argentina",
            "CO": "Colombia", "CL": "Chile", "PE": "Perú",
            "CN": "China", "JP": "Japón", "KR": "Corea del Sur",
            "IN": "India", "RU": "Rusia", "AU": "Australia",
            "PA": "Panamá", "PR": "Puerto Rico", "VE": "Venezuela",
            "HT": "Haití", "CU": "Cuba", "EC": "Ecuador",
            "UY": "Uruguay", "PY": "Paraguay", "BO": "Bolivia",
            "CR": "Costa Rica", "SV": "El Salvador", "GT": "Guatemala",
            "HN": "Honduras", "NI": "Nicaragua",
        }
        return countries.get(code.upper(), code)

    @classmethod
    def _income_code(cls, invoice_data):
        income_raw = invoice_data.get("incomeType", "01")
        if isinstance(income_raw, str):
            code = income_raw.split("-")[0].strip()
        else:
            code = str(income_raw)
        if not code.isdigit():
            code = "01"
        return code.zfill(2)[:2]

    @classmethod
    def _add_with_value(cls, parent, tag, value, default=None):
        if value is not None and (default is None or str(value) != str(default)):
            ET.SubElement(parent, tag).text = str(value)

    @classmethod
    def build_invoice_xml(cls, company_profile, invoice_data):
        raw_type = invoice_data.get("ecfType", "Factura de Consumo (E32)")
        tipo_ecf = cls._detect_tipo_ecf(raw_type)
        cfg = get_tipo_config(tipo_ecf)
        now = datetime.now(timezone.utc)
        today_ddmm = now.strftime("%d-%m-%Y")
        now_dt = now.strftime("%d-%m-%Y %H:%M:%S")

        root = ET.Element("ECF")
        enc = ET.SubElement(root, "Encabezado")
        ET.SubElement(enc, "Version").text = "1.0"

        # ======================== IdDoc ========================
        id_doc = ET.SubElement(enc, "IdDoc")
        ET.SubElement(id_doc, "TipoeCF").text = tipo_ecf
        ET.SubElement(id_doc, "eNCF").text = invoice_data.get("encf", f"E{tipo_ecf}0000000001")

        if tipo_ecf == "34":
            ET.SubElement(id_doc, "IndicadorNotaCredito").text = invoice_data.get("indicadorNotaCredito", "1")

        if cfg["vencimiento"] and tipo_ecf != "34":
            fv = invoice_data.get("fechaVencimientoSecuencia", invoice_data.get("fechaExpiracion", ""))
            if not fv:
                fv = now.replace(year=now.year + 2).strftime("%d-%m-%Y")
            else:
                fv = cls._fmt_date(fv)
            ET.SubElement(id_doc, "FechaVencimientoSecuencia").text = fv

        envio_dif = invoice_data.get("indicadorEnvioDiferido", invoice_data.get("envioDiferido", ""))
        if envio_dif == "1":
            ET.SubElement(id_doc, "IndicadorEnvioDiferido").text = "1"

        if cfg["monto_gravado"]:
            ET.SubElement(id_doc, "IndicadorMontoGravado").text = "0" if tipo_ecf in ("31", "32", "33", "34") else "1"

        if cfg["ingresos"]:
            ET.SubElement(id_doc, "TipoIngresos").text = cls._income_code(invoice_data)

        if tipo_ecf in ("31", "32", "33", "34", "44", "45", "46"):
            pay_method = invoice_data.get("paymentMethod", "Efectivo")
            tipo_pago = "2" if "crédito" in pay_method.lower() or "credito" in pay_method.lower() else "1"
            ET.SubElement(id_doc, "TipoPago").text = tipo_pago

            if cfg["tabla_pagos"] and tipo_ecf != "34":
                tabla_fp = ET.SubElement(id_doc, "TablaFormasPago")
                fdp = ET.SubElement(tabla_fp, "FormaDePago")
                pm = pay_method.lower()
                fpv = "1"
                if "tarjeta" in pm:
                    fpv = "3"
                elif "cheque" in pm:
                    fpv = "2"
                elif any(x in pm for x in ("transferencia", "depósito", "deposito")):
                    fpv = "4"
                ET.SubElement(fdp, "FormaPago").text = fpv
                ET.SubElement(fdp, "MontoPago").text = cls._sd(invoice_data.get("total", 0.0))
        elif tipo_ecf == "43":
            pay_method = invoice_data.get("paymentMethod", "")
            if "crédito" in pay_method.lower() or "credito" in pay_method.lower():
                ET.SubElement(id_doc, "TipoPago").text = "2"

        # ======================== Emisor ========================
        emisor = ET.SubElement(enc, "Emisor")
        ET.SubElement(emisor, "RNCEmisor").text = company_profile.get("companyRNC", "").replace("-", "")
        ET.SubElement(emisor, "RazonSocialEmisor").text = company_profile.get("companyName", "")
        nc = company_profile.get("tradeName", "")
        if nc:
            ET.SubElement(emisor, "NombreComercial").text = nc
        ET.SubElement(emisor, "DireccionEmisor").text = company_profile.get("companyAddress", "")
        mu = cls.map_province_or_municipality(company_profile.get("municipality", ""), is_province=False)
        pr = cls.map_province_or_municipality(company_profile.get("province", ""), is_province=True)
        ET.SubElement(emisor, "Municipio").text = mu
        ET.SubElement(emisor, "Provincia").text = pr
        tel = company_profile.get("companyPhone", "")
        tel_formatted = cls._fmt_phone(tel)
        if tel_formatted:
            ttel = ET.SubElement(emisor, "TablaTelefonoEmisor")
            ET.SubElement(ttel, "TelefonoEmisor").text = tel_formatted
        email = company_profile.get("companyEmail", "")
        if email:
            ET.SubElement(emisor, "CorreoEmisor").text = email
        internal_num = invoice_data.get("internalInvoiceNumber") or str(invoice_data.get("invoiceNumber", ""))
        if internal_num:
            ET.SubElement(emisor, "NumeroFacturaInterna").text = str(internal_num)[:20]
        ET.SubElement(emisor, "FechaEmision").text = today_ddmm

        # ======================== Comprador ========================
        if cfg["has_comprador"]:
            comp = ET.SubElement(enc, "Comprador")
            if cfg["foreign_payment"]:
                ext = invoice_data.get("clientRNC", invoice_data.get("clientPassport", invoice_data.get("clientId", ""))).replace("-", "").strip()
                ET.SubElement(comp, "IdentificadorExtranjero").text = ext or "000000000"
                rz = invoice_data.get("razonSocial", invoice_data.get("clientName", "Proveedor Extranjero"))
                ET.SubElement(comp, "RazonSocialComprador").text = rz
            elif cfg["expense"]:
                crnc = company_profile.get("companyRNC", "").replace("-", "").strip()
                ET.SubElement(comp, "RNCComprador").text = crnc or "000000000"
                ET.SubElement(comp, "RazonSocialComprador").text = company_profile.get("companyName", "")
                ET.SubElement(comp, "MunicipioComprador").text = mu
                ET.SubElement(comp, "ProvinciaComprador").text = pr
            else:
                crnc = invoice_data.get("clientRNC", "").replace("-", "").strip()
                rzs = invoice_data.get("razonSocial", invoice_data.get("clientName", "")).strip()
                total_amt = float(invoice_data.get("total", 0.0))
                consumo_250 = tipo_ecf in ("32", "33", "34") and total_amt < 250000.00

                if consumo_250:
                    if crnc:
                        ET.SubElement(comp, "RNCComprador").text = crnc
                    if rzs:
                        ET.SubElement(comp, "RazonSocialComprador").text = rzs
                    if invoice_data.get("clientMunicipality"):
                        cm = cls.map_province_or_municipality(invoice_data.get("clientMunicipality"), is_province=False)
                        ET.SubElement(comp, "MunicipioComprador").text = cm
                    if invoice_data.get("clientProvince"):
                        cp = cls.map_province_or_municipality(invoice_data.get("clientProvince"), is_province=True)
                        ET.SubElement(comp, "ProvinciaComprador").text = cp
                else:
                    ET.SubElement(comp, "RNCComprador").text = crnc if crnc else "000000000"
                    ET.SubElement(comp, "RazonSocialComprador").text = rzs if rzs else "Consumidor Final"
                    cm = cls.map_province_or_municipality(invoice_data.get("clientMunicipality", "Santo Domingo de Guzmán"), is_province=False)
                    cp = cls.map_province_or_municipality(invoice_data.get("clientProvince", "Santo Domingo"), is_province=True)
                    ET.SubElement(comp, "MunicipioComprador").text = cm
                    ET.SubElement(comp, "ProvinciaComprador").text = cp

                if cfg["export"]:
                    ET.SubElement(comp, "PaisComprador").text = cls._country_name(invoice_data.get("clientCountry", "DO"))

        # ======================== InformacionesAdicionales (export) ========================
        if cfg["export"]:
            info = ET.SubElement(enc, "InformacionesAdicionales")
            puerto = invoice_data.get("puertoEmbarque", invoice_data.get("puerto", ""))
            ET.SubElement(info, "NombrePuertoEmbarque").text = puerto or "Puerto de Haina"
            ET.SubElement(info, "CondicionesEntrega").text = invoice_data.get("condicionesEntrega", invoice_data.get("incoterm", "FOB"))

        # ======================== Transporte (export/E47) ========================
        if cfg["export"]:
            tr = ET.SubElement(enc, "Transporte")
            via = str(invoice_data.get("viaTransporte", invoice_data.get("transportMode", "01")))
            if via in ("1", "2", "3"):
                via = f"0{via}"
            ET.SubElement(tr, "ViaTransporte").text = via
            ET.SubElement(tr, "PaisOrigen").text = cls._country_name(invoice_data.get("paisOrigen", invoice_data.get("countryOfOrigin", "DO")))
            destino = invoice_data.get("direccionDestino", invoice_data.get("destinationAddress", ""))
            ET.SubElement(tr, "DireccionDestino").text = destino or "Miami, FL, USA"
            ET.SubElement(tr, "PaisDestino").text = cls._country_name(invoice_data.get("paisDestino", invoice_data.get("countryOfDestination", "US")))
        elif tipo_ecf == "47":
            tr = ET.SubElement(enc, "Transporte")
            ET.SubElement(tr, "PaisDestino").text = cls._country_name(invoice_data.get("paisDestino", invoice_data.get("countryOfDestination", "US")))

        # ======================== Totales ========================
        totales = ET.SubElement(enc, "Totales")
        subtotal = float(invoice_data.get("subtotal", 0.0))
        total_global = float(invoice_data.get("total", 0.0))
        total_itbis = float(invoice_data.get("totalITBIS", 0.0))
        monto_exento = float(invoice_data.get("montoExento", 0.0))
        gravado = subtotal - monto_exento
        if has_itbis_breakdown(tipo_ecf):
            ET.SubElement(totales, "MontoGravadoTotal").text = cls._sd(gravado)

            if tipo_ecf == "46":
                if gravado > 0:
                    ET.SubElement(totales, "MontoGravadoI3").text = cls._sd(gravado)
                if total_itbis > 0:
                    ET.SubElement(totales, "ITBIS3").text = "18"
                    ET.SubElement(totales, "TotalITBIS").text = cls._sd(total_itbis)
                    ET.SubElement(totales, "TotalITBIS3").text = cls._sd(total_itbis)
            else:
                if gravado > 0:
                    ET.SubElement(totales, "MontoGravadoI1").text = cls._sd(gravado)
                if monto_exento > 0:
                    ET.SubElement(totales, "MontoExento").text = cls._sd(monto_exento)
                if total_itbis > 0:
                    ET.SubElement(totales, "ITBIS1").text = "18"
                    ET.SubElement(totales, "TotalITBIS").text = cls._sd(total_itbis)
                    ET.SubElement(totales, "TotalITBIS1").text = cls._sd(total_itbis)

        elif tipo_ecf == "44":
            ET.SubElement(totales, "MontoExento").text = cls._sd(total_global)
        elif tipo_ecf in ("43", "47"):
            ET.SubElement(totales, "MontoExento").text = cls._sd(total_global)

        total_isc_esp = float(invoice_data.get("total_isc_especifico", invoice_data.get("totalISCEspecifico", invoice_data.get("totalIscEspecifico", 0.0))))
        total_isc_adv = float(invoice_data.get("total_isc_advalorem", invoice_data.get("totalISCAdValorem", invoice_data.get("totalIscAdvalorem", 0.0))))
        otros_imp = float(invoice_data.get("totalOtrosImpuestos", 0.0))
        monto_imp_adicional = total_isc_esp + total_isc_adv + otros_imp
        if monto_imp_adicional > 0:
            ET.SubElement(totales, "MontoImpuestoAdicional").text = cls._sd(monto_imp_adicional)

        ET.SubElement(totales, "MontoTotal").text = cls._sd(total_global)

        if cfg["retenciones"]:
            ritbis = float(invoice_data.get("retainedITBIS", 0.0))
            risr = float(invoice_data.get("retainedISR", 0.0))
            if ritbis > 0:
                ET.SubElement(totales, "TotalITBISRetenido").text = cls._sd(ritbis)
            if risr > 0:
                ET.SubElement(totales, "TotalISRRetencion").text = cls._sd(risr)

        # OtraMoneda (foreign currency)
        currency = invoice_data.get("currency", "DOP")
        if currency and currency.upper() != "DOP":
            om = ET.SubElement(enc, "OtraMoneda")
            ET.SubElement(om, "TipoMoneda").text = cls.map_currency(currency)
            er = invoice_data.get("exchangeRate", invoice_data.get("tipoCambio", "1.0"))
            ET.SubElement(om, "TipoCambio").text = cls._sd(er, "1.00")
            foreign_total = invoice_data.get("totalForeign", total_global)
            if tipo_ecf == "47":
                ET.SubElement(om, "MontoExentoOtraMoneda").text = cls._sd(foreign_total)
            else:
                ET.SubElement(om, "MontoGravadoTotalOtraMoneda").text = cls._sd(foreign_total)
            ET.SubElement(om, "MontoTotalOtraMoneda").text = cls._sd(foreign_total)

        # ======================== DetallesItems ========================
        detalles_items = ET.SubElement(root, "DetallesItems")
        for idx, item in enumerate(invoice_data.get("items", [])):
            item_elem = ET.SubElement(detalles_items, "Item")
            ET.SubElement(item_elem, "NumeroLinea").text = str(idx + 1)
            ET.SubElement(item_elem, "IndicadorFacturacion").text = "1"
            if has_retencion_item(tipo_ecf):
                ret_elem = ET.SubElement(item_elem, "Retencion")
                ET.SubElement(ret_elem, "IndicadorAgenteRetencionoPercepcion").text = "1"
                if tipo_ecf == "47":
                    item_isr = float(item.get("retainedISR", item.get("isrRetenido", 0.0)))
                    ET.SubElement(ret_elem, "MontoISRRetenido").text = cls._sd(item_isr)
            ET.SubElement(item_elem, "NombreItem").text = item.get("name", "Artículo")
            is_service = "servicio" in item.get("unit", "").lower() or "service" in item.get("unit", "").lower() or item.get("type", "").lower() == "servicio"
            ET.SubElement(item_elem, "IndicadorBienoServicio").text = "2" if is_service else "1"
            ET.SubElement(item_elem, "CantidadItem").text = f"{float(item.get('quantity', 1.0)):.2f}"
            unit_code = cls.map_unit_of_measure(item.get("unit", "Unidad"))
            ET.SubElement(item_elem, "UnidadMedida").text = unit_code
            ET.SubElement(item_elem, "PrecioUnitarioItem").text = f"{float(item.get('price', 0.0)):.2f}"
            ET.SubElement(item_elem, "MontoItem").text = f"{float(item.get('subtotal', 0.0)):.2f}"

        # ======================== Subtotales + Paginacion ========================
        pag = ET.SubElement(root, "Paginacion")
        pagina = ET.SubElement(pag, "Pagina")
        ET.SubElement(pagina, "PaginaNo").text = "1"
        num_items = len(invoice_data.get("items", []))
        ET.SubElement(pagina, "NoLineaDesde").text = "1"
        ET.SubElement(pagina, "NoLineaHasta").text = str(num_items) if num_items > 0 else "1"
        ET.SubElement(pagina, "MontoSubtotalPagina").text = cls._sd(subtotal)

        # ======================== InformacionReferencia (NC/ND) ========================
        if tipo_ecf in ("33", "34"):
            info_ref = ET.SubElement(root, "InformacionReferencia")
            ncf_mod = invoice_data.get("ncfModificado", invoice_data.get("referenceNCF", ""))
            ET.SubElement(info_ref, "NCFModificado").text = ncf_mod if ncf_mod else f"E{tipo_ecf}0000000000"
            fecha_mod = invoice_data.get("fechaNCFModificado", invoice_data.get("referenceDate", ""))
            ET.SubElement(info_ref, "FechaNCFModificado").text = cls._fmt_date(fecha_mod) if fecha_mod else today_ddmm
            cod_mod = invoice_data.get("codigoModificacion", invoice_data.get("modificationCode", "1"))
            ET.SubElement(info_ref, "CodigoModificacion").text = str(cod_mod).zfill(2)

        # ======================== FechaHoraFirma ========================
        ET.SubElement(root, "FechaHoraFirma").text = now_dt

        return ET.tostring(root, encoding="utf-8")
