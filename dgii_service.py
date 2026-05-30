import requests
import re

class DGIIService:
    @staticmethod
    def clean_rnc(rnc):
        """Limpia el RNC o Cédula removiendo guiones, espacios u otros caracteres."""
        if not rnc:
            return ""
        return re.sub(r'[^0-9]', '', str(rnc))

    @classmethod
    def validate_and_fetch_rnc(cls, rnc):
        """
        Consulta en tiempo real un RNC o Cédula utilizando el API público de Megaplus.
        GET https://rnc.megaplus.com.do/api/consulta?rnc={cleanRNC}
        """
        clean_rnc = cls.clean_rnc(rnc)
        if len(clean_rnc) not in [9, 11]:
            return {
                "error": True,
                "message": "Formato de RNC/Cédula inválido. Debe tener 9 u 11 dígitos sin guiones."
            }

        url = f"https://rnc.megaplus.com.do/api/consulta?rnc={clean_rnc}"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("error"):
                    return {
                        "error": True,
                        "message": data.get("mensaje", "No encontrado en el padrón de la DGII.")
                    }
                
                # Autocompletado de Razón Social
                razon_social = data.get("nombre_razon_social") or data.get("nombre_comercial")
                if razon_social:
                    return {
                        "error": False,
                        "rnc": clean_rnc,
                        "razon_social": razon_social,
                        "actividad": data.get("actividad_economica", ""),
                        "regimen": data.get("regimen_pagos", "")
                    }
            return {
                "error": True,
                "message": f"Servidor de consulta retornó código HTTP {response.status_code}."
            }
        except requests.RequestException as e:
            return {
                "error": True,
                "message": f"Fallo al conectar con el padrón RNC: {str(e)}"
            }

    @staticmethod
    def dgii_round(value, decimals=2):
        """
        Redondeo basado en la regla de DGII:
        El tercer decimal debe redondear al segundo decimal, dejando así fijo las cifras con dos decimales.
        Cuando el valor numérico del tercer decimal sea menor que 5, se debe mantener el valor del segundo decimal,
        mientras que, si es igual o mayor a 5, se debe incrementar el segundo decimal en una unidad.
        """
        if value is None:
            return 0.0
        # Utilizar Decimal con ROUND_HALF_UP para cumplir con la regla de la DGII
        from decimal import Decimal, ROUND_HALF_UP
        quantize_str = '0.00' if decimals == 2 else '0.' + '0'*decimals
        # Convertimos a string primero para evitar problemas de precisión de punto flotante de Python
        return float(Decimal(str(float(value))).quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP))

    @staticmethod
    def calculate_invoice_totals(items, discount_rate=0.0, retained_isr_rate=0.0, retained_itbis_rate=0.0):
        """
        Realiza cálculos financieros robustos para los comprobantes:
        - Subtotal = Cantidad * Precio Unitario (descontando descuento individual y global)
        - ISC = Impuesto Selectivo al Consumo Específico y Ad-Valorem
        - ITBIS = Subtotal * Tasa de ITBIS del ítem
        - Retenciones de ISR y de ITBIS
        - Neto a Pagar
        """
        subtotal_raw = 0.0
        total_discount = 0.0
        total_itbis = 0.0
        total_isc_especifico = 0.0
        total_isc_advalorem = 0.0
        
        calculated_items = []
        for item in items:
            price = float(item.get('price', 0.0))
            quantity = float(item.get('quantity', 1.0))
            itbis_rate = float(item.get('itbisRate', 0.18))
            item_discount_rate = float(item.get('discountRate', 0.0))
            
            # Campos ISC
            codigo_impuesto = str(item.get('codigoImpuesto', '')).strip().zfill(3)
            tasa_impuesto_adicional = float(item.get('tasaImpuestoAdicional', 0.0))
            grados_alcohol = float(item.get('gradosAlcohol', 0.0))
            cantidad_referencia = float(item.get('cantidadReferencia', 0.0))
            subcantidad = float(item.get('subcantidad', 0.0))
            unidad_medida = str(item.get('unidadMedida', ''))
            precio_referencia = float(item.get('precioReferencia', 0.0)) # PVP
            tasa_impuesto_ad_valorem = float(item.get('tasaImpuestoAdValorem', 0.0)) # En algunos casos es diferente a adicional
            # Subtotal crudo de la partida
            item_subtotal_raw = DGIIService.dgii_round(price * quantity, 2)
            
            # Descuento de la partida
            item_discount = DGIIService.dgii_round(item_subtotal_raw * item_discount_rate, 2)
            item_subtotal = item_subtotal_raw - item_discount
            
            # Calcular ISC Específico e ISC AdValorem simultáneamente para Alcoholes y Tabacos
            isc_especifico = 0.0
            isc_advalorem = 0.0
            
            is_alcohol = ('006' <= codigo_impuesto <= '018') or ('023' <= codigo_impuesto <= '035')
            is_tabaco = ('019' <= codigo_impuesto <= '022') or ('036' <= codigo_impuesto <= '039')
            
            if is_alcohol:
                # 1. ISC Específico de Alcohol
                tasa_esp = tasa_impuesto_adicional if ('006' <= codigo_impuesto <= '018') else 632.58
                val_esp = tasa_esp * (grados_alcohol / 100.0 if grados_alcohol > 1.0 else grados_alcohol) * cantidad_referencia * subcantidad * quantity
                isc_especifico = DGIIService.dgii_round(val_esp, 2)
                
                # 2. ISC Ad-Valorem de Alcohol (si hay precio de referencia PVP)
                if precio_referencia > 0.0:
                    tasa_adv = tasa_impuesto_adicional if ('023' <= codigo_impuesto <= '035') else 0.10
                    if unidad_medida == '18': # Granel
                        val_adv = (price * 1.30 * tasa_adv) * quantity
                        isc_advalorem = DGIIService.dgii_round(val_adv, 2)
                    else:
                        if quantity > 0 and cantidad_referencia > 0:
                            precio_sin_itbis = precio_referencia / (1.0 + itbis_rate)
                            isc_esp_unitario = isc_especifico / (quantity * cantidad_referencia)
                            precio_sin_isc_esp = precio_sin_itbis - isc_esp_unitario
                            precio_sin_isc_ad = precio_sin_isc_esp / (1.0 + tasa_adv)
                            val_adv = precio_sin_isc_ad * tasa_adv * cantidad_referencia * quantity
                            isc_advalorem = DGIIService.dgii_round(val_adv, 2)
                            
            elif is_tabaco:
                # 1. ISC Específico de Tabaco
                tasa_esp = tasa_impuesto_adicional if ('019' <= codigo_impuesto <= '022') else 2.50
                val_esp = quantity * cantidad_referencia * tasa_esp
                isc_especifico = DGIIService.dgii_round(val_esp, 2)
                
                # 2. ISC Ad-Valorem de Tabaco
                if precio_referencia > 0.0:
                    tasa_adv = tasa_impuesto_adicional if ('036' <= codigo_impuesto <= '039') else 0.20
                    precio_sin_itbis = precio_referencia / (1.0 + itbis_rate)
                    precio_sin_isc_esp = precio_sin_itbis - tasa_esp
                    precio_sin_isc_ad = precio_sin_isc_esp / (1.0 + tasa_adv)
                    val_adv = precio_sin_isc_ad * tasa_adv * cantidad_referencia * quantity
                    isc_advalorem = DGIIService.dgii_round(val_adv, 2)

            # Otros Impuestos Adicionales (Propina Legal, CDT, Primera Placa, etc. - Códigos 001 a 005)
            otros_impuestos = 0.0
            if '001' <= codigo_impuesto <= '005':
                tasa = tasa_impuesto_adicional
                if codigo_impuesto == '001': # Propina Legal
                    tasa = 0.10
                elif codigo_impuesto == '002': # CDT
                    tasa = 0.02
                elif codigo_impuesto == '003': # ISC Seguros
                    tasa = 0.16
                elif codigo_impuesto == '004': # Telecomunicaciones
                    tasa = 0.10
                elif codigo_impuesto == '005': # Primera Placa
                    tasa = 0.17
                
                otros_impuestos = DGIIService.dgii_round(item_subtotal * tasa, 2)
            
            total_isc = isc_especifico + isc_advalorem + otros_impuestos
            
            # ITBIS de la partida (se calcula sobre subtotal + ISC según regla general, pero la DGII suele pedirlo sobre el monto gravado)
            # Para e-CF, el ISC forma parte de la base imponible del ITBIS en la mayoría de los casos.
            base_itbis = item_subtotal + total_isc
            item_itbis = DGIIService.dgii_round(base_itbis * itbis_rate, 2)
            
            item_total = item_subtotal + total_isc + item_itbis
            
            subtotal_raw += item_subtotal_raw
            total_discount += item_discount
            total_itbis += item_itbis
            total_isc_especifico += isc_especifico
            total_isc_advalorem += isc_advalorem
            total_isc_especifico += otros_impuestos # Sumamos en total_otros_impuestos local
            
            calculated_items.append({
                **item,
                'subtotal_raw': item_subtotal_raw,
                'discount_amount': item_discount,
                'subtotal': item_subtotal,
                'isc_especifico_amount': isc_especifico,
                'isc_advalorem_amount': isc_advalorem,
                'otros_impuestos_amount': otros_impuestos,
                'itbis_amount': item_itbis,
                'total': item_total
            })

        # Aplicar descuento global comercial adicional si existe
        global_discount = DGIIService.dgii_round((subtotal_raw - total_discount) * discount_rate, 2)
        total_discount += global_discount
        
        # Subtotal neto final
        subtotal = subtotal_raw - total_discount
        
        # Recalcular ITBIS si hay descuento global proporcional o usar la suma de ITBIS individuales
        total_otros_impuestos = 0.0
        if discount_rate > 0.0:
            total_itbis = 0.0
            for item in calculated_items:
                item['subtotal'] = DGIIService.dgii_round(item['subtotal'] * (1.0 - discount_rate), 2)
                item['otros_impuestos_amount'] = DGIIService.dgii_round(item['otros_impuestos_amount'] * (1.0 - discount_rate), 2)
                base_itbis = item['subtotal'] + item['isc_especifico_amount'] + item['isc_advalorem_amount'] + item['otros_impuestos_amount']
                item['itbis_amount'] = DGIIService.dgii_round(base_itbis * item['itbisRate'], 2)
                item['total'] = item['subtotal'] + item['isc_especifico_amount'] + item['isc_advalorem_amount'] + item['otros_impuestos_amount'] + item['itbis_amount']
                total_itbis += item['itbis_amount']
                total_otros_impuestos += item['otros_impuestos_amount']
        else:
            total_otros_impuestos = sum(item['otros_impuestos_amount'] for item in calculated_items)

        total = subtotal + total_isc_especifico + total_isc_advalorem + total_otros_impuestos + total_itbis
        
        # Retenciones de Impuestos en RD
        retained_isr = DGIIService.dgii_round(subtotal * retained_isr_rate, 2)
        retained_itbis = DGIIService.dgii_round(total_itbis * retained_itbis_rate, 2)
        
        net_payable = max(0.0, total - retained_isr - retained_itbis)
        
        return {
            'items': calculated_items,
            'subtotal_raw': DGIIService.dgii_round(subtotal_raw, 2),
            'global_discount': DGIIService.dgii_round(global_discount, 2),
            'total_discount': DGIIService.dgii_round(total_discount, 2),
            'subtotal': DGIIService.dgii_round(subtotal, 2),
            'total_isc_especifico': DGIIService.dgii_round(total_isc_especifico, 2),
            'total_isc_advalorem': DGIIService.dgii_round(total_isc_advalorem, 2),
            'total_otros_impuestos': DGIIService.dgii_round(total_otros_impuestos, 2),
            'total_itbis': DGIIService.dgii_round(total_itbis, 2),
            'total': DGIIService.dgii_round(total, 2),
            'retained_isr': DGIIService.dgii_round(retained_isr, 2),
            'net_payable': DGIIService.dgii_round(net_payable, 2)
        }

    @classmethod
    def check_tolerancia_cuadratura(cls, items, total_emisor):
        """
        Aplica la regla de tolerancia y cuadratura según la normativa de la DGII.
        Admite una diferencia de +- 1 unidad del valor de (precio * cantidad) por línea,
        y una diferencia global equivalente al total de líneas del detalle.
        Retorna un dict con el resultado de la verificación.
        """
        total_lines = len(items)
        line_diffs = []
        is_condicional = False
        warnings = []
        
        for idx, item in enumerate(items):
            qty = float(item.get('quantity', 1))
            price = float(item.get('price', 0.0))
            expected_line_subtotal = qty * price
            reported_line_subtotal = float(item.get('subtotal', item.get('total', 0.0)))
            
            diff = abs(reported_line_subtotal - expected_line_subtotal)
            line_diffs.append(diff)
            
            if diff > 1.0:
                is_condicional = True
                warnings.append(f"Línea {idx+1}: Dif {diff:.2f} excede la tolerancia de +-1")
            
        calculated_total = sum(float(item.get('total', 0.0)) for item in items)
        global_diff = abs(total_emisor - calculated_total)
        
        if global_diff > total_lines:
            is_condicional = True
            warnings.append(f"Global: Dif {global_diff:.2f} excede la tolerancia de {total_lines}")
            
        return {
            "within_tolerance": not is_condicional,
            "status": "ACCEPTED" if not is_condicional else "ACCEPTED_CONDITIONAL",
            "global_diff": global_diff,
            "global_tolerance": total_lines,
            "line_diffs": line_diffs,
            "warnings": warnings
        }
