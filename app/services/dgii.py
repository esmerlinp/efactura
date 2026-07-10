import requests
import re


class DGIIService:

    @classmethod
    def _resolve_client(cls, country="DO"):
        from app.services.country_provider import CountryProviderFactory
        provider = CountryProviderFactory.create(country)
        if not provider:
            raise ValueError(f"No country provider for {country}")
        return provider.get_regimen_rules()

    @classmethod
    def normalize_regimen(cls, regimen, country="DO"):
        client = cls._resolve_client(country)
        if not regimen:
            return client["default"]
        return client["legacy_map"].get(regimen, regimen)

    @classmethod
    def is_rst_regimen(cls, regimen, country="DO"):
        client = cls._resolve_client(country)
        normalized = cls.normalize_regimen(regimen, country=country)
        rst_income = client.get("rst_income")
        rst_purchases = client.get("rst_purchases")
        if rst_income and rst_purchases:
            return normalized in (rst_income, rst_purchases)
        return False

    @classmethod
    def get_regimen_rules(cls, regimen, country="DO"):
        client = cls._resolve_client(country)
        regimes = client["regimes"]
        default = client["default"]
        return regimes.get(regimen, regimes.get(default, {}))

    @staticmethod
    def is_ecf_type_allowed(regimen, ecf_type):
        rules = DGIIService.get_regimen_rules(regimen)
        ecf_code = ecf_type.split("(")[-1].replace(")", "").strip() if "(" in ecf_type else ecf_type
        return ecf_code in rules["allowed_ecf_types"]

    @staticmethod
    def get_default_ecf_type(regimen):
        return DGIIService.get_regimen_rules(regimen)["default_ecf_type"]

    @staticmethod
    def is_itbis_enabled(regimen):
        rules = DGIIService.get_regimen_rules(regimen)
        return rules.get("vat_enabled", rules.get("itbis_enabled", True))

    @staticmethod
    def clean_rnc(rnc):
        if not rnc:
            return ""
        return re.sub(r'[^0-9]', '', str(rnc))

    @staticmethod
    def _validate_rnc_local(clean_rnc):
        if len(clean_rnc) == 9:
            weights = [7, 9, 8, 6, 5, 4, 3, 2]
            digits = [int(d) for d in clean_rnc[:8]]
            check_digit = int(clean_rnc[8])
            total = sum(d * w for d, w in zip(digits, weights))
            remainder = total % 11
            if remainder <= 1:
                expected = 0 if remainder == 0 else 1
            else:
                expected = 11 - remainder
            if expected != check_digit:
                return {"error": True, "message": "RNC invalido: el digito verificador no coincide."}
            return {"error": False, "rnc": clean_rnc, "razon_social": "", "actividad": "", "regimen": "", "source": "local"}

        elif len(clean_rnc) == 11:
            weights = [1, 2, 1, 2, 1, 2, 1, 2, 1, 2]
            digits = [int(d) for d in clean_rnc[:10]]
            check_digit = int(clean_rnc[10])
            products = []
            for d, w in zip(digits, weights):
                prod = d * w
                if prod >= 10:
                    products.append(prod // 10 + prod % 10)
                else:
                    products.append(prod)
            total = sum(products)
            next_ten = ((total + 9) // 10) * 10
            expected = next_ten - total
            if expected != check_digit:
                return {"error": True, "message": "Cedula invalida: el digito verificador no coincide."}
            return {"error": False, "rnc": clean_rnc, "razon_social": "", "actividad": "", "regimen": "", "source": "local"}

        return {"error": True, "message": "Formato de RNC/Cedula invalido. Debe tener 9 u 11 digitos sin guiones."}

    @classmethod
    def validate_and_fetch_rnc(cls, rnc):
        clean_rnc = cls.clean_rnc(rnc)
        if len(clean_rnc) not in [9, 11]:
            return {
                "error": True,
                "message": "Formato de RNC/Cedula invalido. Debe tener 9 u 11 digitos sin guiones."
            }

        url = f"https://rnc.megaplus.com.do/api/consulta?rnc={clean_rnc}"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if not data.get("error"):
                    razon_social = data.get("nombre_razon_social") or data.get("nombre_comercial")
                    if razon_social:
                        return {
                            "error": False,
                            "rnc": clean_rnc,
                            "razon_social": razon_social,
                            "actividad": data.get("actividad_economica", ""),
                            "regimen": data.get("regimen_pagos", ""),
                            "source": "megaplus"
                        }
        except requests.RequestException:
            pass

        return cls._validate_rnc_local(clean_rnc)

    @staticmethod
    def dgii_round(value, decimals=2):
        if value is None:
            return 0.0
        from decimal import Decimal, ROUND_HALF_UP
        quantize_str = '0.00' if decimals == 2 else '0.' + '0'*decimals
        return float(Decimal(str(float(value))).quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP))

    @staticmethod
    def calculate_invoice_totals(items, discount_rate=0.0, retained_isr_rate=0.0, retained_itbis_rate=0.0):
        subtotal_raw = 0.0
        total_discount = 0.0
        total_itbis = 0.0
        total_isc_especifico = 0.0
        total_isc_advalorem = 0.0
        total_otros_impuestos = 0.0

        calculated_items = []
        for item in items:
            price = float(item.get('price', 0.0))
            quantity = float(item.get('quantity', 1.0))
            itbis_rate = float(item.get('itbisRate', 0.18))
            item_discount_rate = float(item.get('discountRate', 0.0))

            codigo_impuesto = str(item.get('codigoImpuesto', '')).strip().zfill(3)
            tasa_impuesto_adicional = float(item.get('tasaImpuestoAdicional', 0.0))
            grados_alcohol = float(item.get('gradosAlcohol', 0.0))
            cantidad_referencia = float(item.get('cantidadReferencia', 0.0))
            subcantidad = float(item.get('subcantidad', 0.0))
            unidad_medida = str(item.get('unidadMedida', ''))
            precio_referencia = float(item.get('precioReferencia', 0.0))
            tasa_impuesto_ad_valorem = float(item.get('tasaImpuestoAdValorem', 0.0))

            item_subtotal_raw = DGIIService.dgii_round(price * quantity, 2)

            item_discount = DGIIService.dgii_round(item_subtotal_raw * item_discount_rate, 2)
            item_subtotal = item_subtotal_raw - item_discount

            isc_especifico = 0.0
            isc_advalorem = 0.0

            is_alcohol = ('006' <= codigo_impuesto <= '018') or ('023' <= codigo_impuesto <= '035')
            is_tabaco = ('019' <= codigo_impuesto <= '022') or ('036' <= codigo_impuesto <= '039')

            if is_alcohol:
                tasa_esp = tasa_impuesto_adicional if ('006' <= codigo_impuesto <= '018') else 632.58
                val_esp = tasa_esp * (grados_alcohol / 100.0 if grados_alcohol > 1.0 else grados_alcohol) * cantidad_referencia * subcantidad * quantity
                isc_especifico = DGIIService.dgii_round(val_esp, 2)

                if precio_referencia > 0.0:
                    tasa_adv = tasa_impuesto_adicional if ('023' <= codigo_impuesto <= '035') else 0.10
                    if unidad_medida == '18':
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
                tasa_esp = tasa_impuesto_adicional if ('019' <= codigo_impuesto <= '022') else 2.50
                val_esp = quantity * cantidad_referencia * tasa_esp
                isc_especifico = DGIIService.dgii_round(val_esp, 2)

                if precio_referencia > 0.0:
                    tasa_adv = tasa_impuesto_adicional if ('036' <= codigo_impuesto <= '039') else 0.20
                    precio_sin_itbis = precio_referencia / (1.0 + itbis_rate)
                    precio_sin_isc_esp = precio_sin_itbis - tasa_esp
                    precio_sin_isc_ad = precio_sin_isc_esp / (1.0 + tasa_adv)
                    val_adv = precio_sin_isc_ad * tasa_adv * cantidad_referencia * quantity
                    isc_advalorem = DGIIService.dgii_round(val_adv, 2)

            otros_impuestos = 0.0
            if '001' <= codigo_impuesto <= '005':
                tasa = tasa_impuesto_adicional
                if codigo_impuesto == '001':
                    tasa = 0.10
                elif codigo_impuesto == '002':
                    tasa = 0.02
                elif codigo_impuesto == '003':
                    tasa = 0.16
                elif codigo_impuesto == '004':
                    tasa = 0.10
                elif codigo_impuesto == '005':
                    tasa = 0.17

                otros_impuestos = DGIIService.dgii_round(item_subtotal * tasa, 2)

            total_isc = isc_especifico + isc_advalorem + otros_impuestos

            base_itbis = item_subtotal + total_isc
            item_itbis = DGIIService.dgii_round(base_itbis * itbis_rate, 2)

            item_total = item_subtotal + total_isc + item_itbis

            subtotal_raw += item_subtotal_raw
            total_discount += item_discount
            total_itbis += item_itbis
            total_isc_especifico += isc_especifico
            total_isc_advalorem += isc_advalorem
            total_otros_impuestos += otros_impuestos

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

        global_discount = DGIIService.dgii_round((subtotal_raw - total_discount) * discount_rate, 2)
        total_discount += global_discount

        subtotal = subtotal_raw - total_discount

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
            'retained_itbis': DGIIService.dgii_round(retained_itbis, 2),
            'net_payable': DGIIService.dgii_round(net_payable, 2)
        }

    @classmethod
    def check_tolerancia_cuadratura(cls, items, total_emisor):
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
                warnings.append(f"Linea {idx+1}: Dif {diff:.2f} excede la tolerancia de +-1")

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
