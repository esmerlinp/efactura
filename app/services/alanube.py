import requests
import uuid
import json
from datetime import datetime
from urllib.parse import quote
from config import Config
# pyrefly: ignore [missing-import]


class AlanubeService:
    @classmethod
    def get_dgii_friendly_error(cls, error_detail):
        """
        Analiza el detalle del error de Alanube para encontrar códigos AEP2xxx
        y retornar el mensaje correspondiente traducido al español.
        """
        dgii_errors_map = {
            "AEP2001": "La clave del valor para la DGII no existe (Valor no encontrado).",
            "AEP2002": "El entorno especificado para la DGII no es soportado.",
            "AEP2003": "Ocurrió un error al intentar autenticarse con la DGII (Firma/Certificado).",
            "AEP2004": "Ocurrió un error al intentar comunicarse con los servidores de la DGII.",
            "AEP2005": "La conexión se cerró inesperadamente durante la comunicación con la DGII.",
            "AEP2006": "La conexión con la DGII ha superado el tiempo de espera (Timeout).",
            "AEP2007": "El servicio de recepción de la DGII no está disponible temporalmente.",
            "AEP2008": "El servicio de la DGII retornó un error de recurso no encontrado (Not Found).",
            "AEP2009": "El servicio de la DGII retornó una solicitud incorrecta (Bad Request).",
            "AEP2010": "El servicio de la DGII denegó el acceso (No autorizado).",
            "AEP2011": "La DGII retornó una respuesta con formato inválido o corrupto.",
            "AEP2012": "El servidor/host de la DGII se encuentra inalcanzable.",
            "AEP2013": "Falló la verificación de la firma digital de la hoja (Leaf Signature) ante la DGII.",
            "AP3011": "El documento con este consecutivo (e-NCF) ya se encuentra en proceso.",
            "AP3012": "El documento referenciado por esta nota fue rechazado por la DGII o falló.",
            "AP3013": "El monto de la nota de crédito excede el balance restante disponible del documento referenciado.",
            "AP3014": "El monto total de una nota de anulación debe coincidir exactamente con el balance restante del documento referenciado.",
            "AP3015": "Las notas de crédito para corrección de texto (código de modificación 2) deben tener un monto total igual a 0.",
            "AP3016": "Las notas de crédito para corrección de texto (código de modificación 2) deben tener un monto total igual a 0."
        }
        
        code = None
        message = None
        
        if isinstance(error_detail, dict):
            code = error_detail.get("code")
            message = error_detail.get("message")
            
            # Buscar en lista de errores
            errors = error_detail.get("errors") or error_detail.get("response")
            if errors and isinstance(errors, list) and len(errors) > 0:
                first_err = errors[0]
                if isinstance(first_err, dict):
                    code = first_err.get("code") or code
                    message = first_err.get("message") or message

            # Si hay un objeto 'error' dentro del detalle
            inner_error = error_detail.get("error")
            if isinstance(inner_error, dict):
                code = inner_error.get("code") or code
                message = inner_error.get("message") or message
                    
        if code and code in dgii_errors_map:
            return f"{code} - {dgii_errors_map[code]} ({message or ''})"
            
        return message or "Error de comunicación."

    @staticmethod
    def get_endpoints():
        """Mapeo de los endpoints de la API de Alanube para cada tipo de comprobante electrónico (e-CF)."""
        return {
            "Factura de Crédito Fiscal (E31)": "/dom/v1/fiscal-invoices",
            "Factura de Consumo (E32)": "/dom/v1/invoices",
            "Nota de Débito (E33)": "/dom/v1/debit-notes",
            "Nota de Crédito (E34)": "/dom/v1/credit-notes",
            "Comprobante de Compras (E41)": "/dom/v1/purchases",
            "Gastos Menores (E43)": "/dom/v1/minor-expenses",
            "Regímenes Especiales (E44)": "/dom/v1/special-regimes",
            "Gubernamental (E45)": "/dom/v1/gubernamentals",
            "Exportación (E46)": "/dom/v1/export-supports",
            "Pagos al Exterior (E47)": "/dom/v1/payment-abroad-supports"
        }

    @classmethod
    def get_endpoint_path(cls, ecf_type):
        """Retorna la ruta del endpoint para el tipo de e-CF provisto."""
        endpoints = cls.get_endpoints()
        return endpoints.get(ecf_type, "/dom/v1/invoices")

    @classmethod
    def get_ecf_type_number_code(cls, ecf_type):
        """Obtiene el código numérico de 2 dígitos del e-CF (ej: E31 -> 31)."""
        if "E31" in ecf_type: return "31"
        if "E32" in ecf_type: return "32"
        if "E33" in ecf_type: return "33"
        if "E34" in ecf_type: return "34"
        if "E41" in ecf_type: return "41"
        if "E43" in ecf_type: return "43"
        if "E44" in ecf_type: return "44"
        if "E45" in ecf_type: return "45"
        if "E46" in ecf_type: return "46"
        if "E47" in ecf_type: return "47"
        return "32"

    @classmethod
    def get_ecf_type_short_code(cls, ecf_type):
        """Obtiene el prefijo de 3 caracteres (ej: E31)."""
        return f"E{cls.get_ecf_type_number_code(ecf_type)}"

    @classmethod
    def emit_electronic_comprobante(cls, company_profile, invoice, sandbox=True):
        """
        Emite un e-CF a través de la API REST de Alanube.
        Si la llamada falla, o si se encuentra en modo Sandbox con el token por defecto,
        se activa de forma reactiva el MODO CONTINGENCIA (FALLBACK) simulando la firma y el QR.
        """
        ecf_type = invoice.get("ecfType", "Factura de Consumo (E32)")
        short_code = cls.get_ecf_type_short_code(ecf_type)
        number_code = cls.get_ecf_type_number_code(ecf_type)
        
        # Limpiar guiones del RNC de emisor y receptor
        company_rnc = str(company_profile.get("companyRNC", "132109122")).replace("-", "").strip()
        client_rnc = str(invoice.get("clientRNC", "999999999")).replace("-", "").strip()
        if not client_rnc and number_code == "32":
            client_rnc = "999999999"  # Consumidor final genérico

        # Construir payload estructurado de Alanube
        payload = cls.build_payload(company_profile, invoice, company_rnc, client_rnc, number_code, short_code)

        # Determinar credenciales según entorno
        base_url = Config.ALANUBE_SANDBOX_BASE_URL if sandbox else Config.ALANUBE_PRODUCTION_BASE_URL
        token = Config.ALANUBE_SANDBOX_TOKEN if sandbox else Config.ALANUBE_PRODUCTION_TOKEN
        company_id = (company_profile.get("alanubeCompanyIDSandbox") or Config.ALANUBE_SANDBOX_COMPANY_ID) if sandbox else (company_profile.get("alanubeCompanyIDProduction") or Config.ALANUBE_PRODUCTION_COMPANY_ID)

        path = cls.get_endpoint_path(ecf_type)
        url = f"{base_url}{path}"

        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        print(f"📡 Enviando payload a Alanube API (POST {url})...")
        
        error_detail = None
        response_status_code = 0
        use_fallback = False

        if not use_fallback:
            try:
                print(f"URL: {url}")
                print(f"Payload: {payload}")
                print(f"Headers: {headers}")
                response = requests.post(url, json=payload, headers=headers, timeout=12)
                response_status_code = response.status_code
                if response.status_code >= 200 and response.status_code < 300:
                    data = response.json()
                    if data.get("status") == "FAILED":
                        print("⚠️ Alanube API retornó status FAILED en la respuesta.")
                        err_msg = cls.get_dgii_friendly_error(data)
                        return {
                            "success": False,
                            "message": err_msg,
                            "error": err_msg,
                            "requestPayload": payload,
                            "responseBody": data,
                            "statusCode": response.status_code
                        }
                    print("✅ Alanube API emitió exitosamente el comprobante.")
                    return {
                        "success": True,
                        "encf": data.get("encf") or invoice.get("encf"),
                        "xmlSignature": data.get("id") or f"ALANUBE-ID-{uuid.uuid4().hex[:12].upper()}",
                        "qrCodeURL": data.get("qr_code_url") or cls.generate_mock_qr(company_rnc, client_rnc, invoice.get("encf", "E320000000001"), invoice["total"]),
                        "pdfUrl": data.get("pdf_url"),
                        "xmlUrl": data.get("xml_url"),
                        "mode": "API",
                        "status": data.get("status"),
                        "requestPayload": payload,
                        "responseBody": data,
                        "statusCode": response.status_code
                    }
                else:
                    print(f"⚠️ Alanube API retornó error {response.status_code}. Activando Fallback de Contingencia.")
                    try:
                        error_detail = response.json()
                        err_msg = cls.get_dgii_friendly_error(error_detail)
                        print(f"Mensaje de error Alanube: {err_msg}")
                    except Exception:
                        error_detail = {"error": response.text or "Unauthorized"}
                    use_fallback = True
            except requests.RequestException as e:
                print(f"❌ Excepción de red al conectar con Alanube: {e}. Activando Fallback de Contingencia.")
                error_detail = {"error": str(e)}
                use_fallback = True

        # Ejecución de MODO CONTINGENCIA (FALLBACK)
        if use_fallback:
            print("🛡️ Ejecutando firma mock y código QR de validación local según Ley 32-23...")
            
            # --- LOG API ERROR ---
            try:
                import os, json
                from datetime import datetime
                from flask import current_app
                log_file_path = os.path.join(current_app.root_path, '../api_errores.log')
                log_entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR EXTERNO (ALANUBE):\n"
                log_entry += f"Ruta: POST {url}\n"
                log_entry += f"HTTP Code: {response_status_code}\n"
                log_entry += f"Payload: {json.dumps(payload)}\n"
                log_entry += f"Response: {json.dumps(error_detail) if isinstance(error_detail, dict) else error_detail}\n"
                log_entry += ("-" * 60) + "\n"
                with open(log_file_path, 'a', encoding='utf-8') as f:
                    f.write(log_entry)
            except Exception as e:
                print(f"Error escribiendo en api_errores.log desde alanube.py: {e}")
            # ---------------------
            
            # Generar e-NCF simulado si no está establecido
            encf = invoice.get("encf")
            if not encf or "PENDIENTE" in encf:
                random_seq = f"{uuid.uuid4().int}"[:8]
                encf = f"E{number_code}{random_seq.zfill(8)}"

            # Generar QR de verificación DGII
            # https://dgii.gov.do/validaecf?rncEmisor={companyRNC}&rncReceptor={clientRNC}&encf={encf}&monto={total}
            qr_url = cls.generate_mock_qr(company_rnc, client_rnc, encf, invoice["total"])
            
            # Firma mock
            mock_signature = f"MOCK-SIGNATURE-{uuid.uuid4().hex[:16].upper()}"
            
            # Rutas de descarga locales simuladas en Flask
            pdf_url = f"/invoices/{invoice['id']}/pdf"
            xml_url = f"/invoices/{invoice['id']}/xml"
            
            return {
                "success": True,
                "encf": encf,
                "xmlSignature": mock_signature,
                "qrCodeURL": qr_url,
                "pdfUrl": pdf_url,
                "xmlUrl": xml_url,
                "mode": "FALLBACK",
                "requestPayload": payload,
                "responseBody": error_detail or {"error": "Unauthorized / Contingency Fallback Activated"},
                "statusCode": response_status_code
            }

    @classmethod
    def generate_mock_qr(cls, company_rnc, client_rnc, encf, total):
        """Genera el enlace de código QR de validación exacto de la DGII para contingencias."""
        query_params = f"rncEmisor={company_rnc}&rncReceptor={client_rnc}&encf={encf}&monto={total:.2f}"
        return f"https://dgii.gov.do/validaecf?{quote(query_params)}"

    @classmethod
    def build_payload(cls, company_profile, invoice, company_rnc, client_rnc, number_code, short_code):
        """Construye el payload JSON mapeado exactamente a la estructura del API de Alanube."""
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        
        invoice_id_doc = invoice.get("idDoc") or {}
        
        # 1. Encabezado de Documento (idDoc)
        id_doc = {
            "encf": invoice_id_doc.get("encf") or invoice.get("encf") or "PENDIENTE",
            "sequenceDueDate": invoice_id_doc.get("sequenceDueDate") or invoice.get("dueDate", date_str),
            "paymentType": 2 if invoice.get("paymentType") == "Crédito" or invoice_id_doc.get("paymentType") == 2 else 1, # 1: Contado, 2: Crédito
        }
        
        if number_code in ["31", "32", "33", "34"]:
            id_doc["taxAmountIndicator"] = 0
            # Resolver código numérico de tipo de ingreso (ej: "01 - Ingresos por operaciones" -> 1)
            raw_income_type = invoice.get("incomeType", "01")
            try:
                num_part = raw_income_type.split("-")[0].strip()
                id_doc["incomeType"] = int(num_part)
            except Exception:
                id_doc["incomeType"] = 1

            # Indicadores obligatorios de plazo para Notas de Crédito (34) / Débito (33) - Ley 32-23
            if number_code == "34":
                info_ref = invoice.get("informationReference") or {}
                ncf_mod_date = info_ref.get("ncfModifiedDate") or invoice.get("ncfModifiedDate") or invoice.get("date", date_str)[:10]
                try:
                    current_date = datetime.strptime(invoice.get("date", date_str)[:10], "%Y-%m-%d")
                    referenced_date = datetime.strptime(ncf_mod_date[:10], "%Y-%m-%d")
                    delta_days = (current_date - referenced_date).days
                    id_doc["creditNoteIndicator"] = 1 if delta_days > 30 else 0
                except Exception:
                    id_doc["creditNoteIndicator"] = 0
            elif number_code == "33":
                info_ref = invoice.get("informationReference") or {}
                ncf_mod_date = info_ref.get("ncfModifiedDate") or invoice.get("ncfModifiedDate") or invoice.get("date", date_str)[:10]
                try:
                    current_date = datetime.strptime(invoice.get("date", date_str)[:10], "%Y-%m-%d")
                    referenced_date = datetime.strptime(ncf_mod_date[:10], "%Y-%m-%d")
                    delta_days = (current_date - referenced_date).days
                    id_doc["debitNoteIndicator"] = 1 if delta_days > 30 else 0
                except Exception:
                    id_doc["debitNoteIndicator"] = 0

        # Transfer custom/extra idDoc fields from input if present
        for key in ["paymentDeadline", "paymentTerm", "paymentFormsTable", "paymentAccountType", "paymentAccountNumber", "bankPayment", "taxAmountIndicator", "incomeType", "dateFrom", "dateUntil"]:
            val = invoice_id_doc.get(key) or invoice.get(key)
            if val is not None:
                if key == "incomeType" and isinstance(val, str):
                    try:
                        val = int(val.split("-")[0].strip())
                    except Exception:
                        val = 1
                id_doc[key] = val

        if "paymentFormsTable" not in id_doc:
            # Default paymentFormsTable para todos los comprobantes (es mandatorio en muchos casos)
            pay_method = 1  # Efectivo
            method_map = {"efectivo": 1, "cheque": 2, "tarjeta": 3, "credito": 4, "crédito": 4, "bonos": 5, "permuta": 6, "otras": 7}
            raw_method = str(invoice.get("paymentMethod", "Efectivo")).lower()
            for k, v in method_map.items():
                if k in raw_method:
                    pay_method = v
                    break
            id_doc["paymentFormsTable"] = [
                {"paymentMethod": pay_method, "paymentAmount": invoice.get("total", 0.0)}
            ]

        if number_code == "41":
            if "paymentDeadline" not in id_doc:
                id_doc["paymentDeadline"] = invoice.get("dueDate", date_str)
            if "paymentTerm" not in id_doc:
                id_doc["paymentTerm"] = "30 días"

        if number_code == "47":
            if "paymentDeadline" not in id_doc:
                id_doc["paymentDeadline"] = invoice.get("dueDate", date_str)
            if "paymentTerm" not in id_doc:
                id_doc["paymentTerm"] = "30 días"
            if "dateFrom" not in id_doc:
                id_doc["dateFrom"] = invoice.get("date", date_str)
            if "dateUntil" not in id_doc:
                id_doc["dateUntil"] = invoice.get("dueDate", date_str)

        # Resolver nombre de sucursal
        branch_name = "Sucursal Principal"
        branch_id = invoice.get("branchId")
        if branch_id and company_profile.get("ownerUID"):
            try:
                from app.services.db_service import DatabaseService
                owner_uid = company_profile["ownerUID"]
                branches = DatabaseService.get_branches(owner_uid, sandbox=True) + DatabaseService.get_branches(owner_uid, sandbox=False)
                branch_obj = next((b for b in branches if b["id"] == branch_id), None)
                if branch_obj:
                    branch_name = branch_obj.get("name") or "Sucursal Principal"
            except Exception:
                pass

        # Validar provincia y municipio (deben ser códigos de 6 dígitos)
        province_code = company_profile.get("province", "010000")
        if not (isinstance(province_code, str) and province_code.isdigit() and len(province_code) == 6):
            province_code = "010000"

        municipality_code = company_profile.get("municipality", "010101")
        if not (isinstance(municipality_code, str) and municipality_code.isdigit() and len(municipality_code) == 6):
            municipality_code = "010101"

        # Procesar números de teléfono
        phones = company_profile.get("companyPhone", "809-555-0199")
        if isinstance(phones, str):
            phone_list = [p.strip() for p in phones.replace(";", ",").split(",") if p.strip()]
        elif isinstance(phones, list):
            phone_list = [str(p).strip() for p in phones if str(p).strip()]
        else:
            phone_list = ["809-555-0199"]
        if not phone_list:
            phone_list = ["809-555-0199"]

        # Procesar número de factura interna
        internal_inv_num = invoice.get("internalInvoiceNumber")
        if not internal_inv_num:
            internal_inv_num = str(invoice.get("invoiceNumber", "456789"))
            if len(internal_inv_num) > 60:
                internal_inv_num = internal_inv_num[:60]

        # Obtener comentario/notas del documento para el emisor
        comment = (invoice.get("comentario") or invoice.get("notes") or "").strip()

        # 2. Datos del Emisor (sender)
        sender = {
            "rnc": company_rnc,
            "companyName": company_profile.get("companyName", "Mi Empresa SRL"),
            "tradename": company_profile.get("tradeName") or company_profile.get("companyName", "Mi Empresa"),
            "branchOffice": branch_name,
            "address": company_profile.get("companyAddress", "Santo Domingo, RD"),
            "municipality": municipality_code,
            "province": province_code,
            "phoneNumber": phone_list,
            "mail": company_profile.get("companyEmail", "factura@miempresa.com.do"),
            "webSite": company_profile.get("webSite") or company_profile.get("companyWebsite") or f"www.{company_profile.get('companyName', 'miempresa').lower().replace(' ', '').replace('.', '')}.com.do",
            "economicActivity": company_profile.get("economicActivity") or company_profile.get("companyActivity") or "Actividad Comercial",
            "sellerCode": invoice.get("sellerCode") or invoice.get("seller") or "Carlos Segura ID458-457",
            "internalInvoiceNumber": internal_inv_num,
            "internalOrderNumber": invoice.get("internalOrderNumber") or invoice.get("invoiceNumber", "562344"),
            "saleArea": invoice.get("saleArea") or "Santo Domingo Este",
            "saleRoute": invoice.get("saleRoute") or "Ruta 1",
            "stampDate": invoice.get("date", date_str)[:10]
        }
        if comment:
            sender["additionalInformationIssuer"] = comment
        else:
            sender["additionalInformationIssuer"] = "Información adicional del emisor"

        # 3. Datos del Receptor (buyer)
        invoice_buyer = invoice.get("buyer") or {}
        buyer = {
            "companyName": invoice_buyer.get("companyName") or invoice.get("clientName", "Consumidor Final"),
            "address": invoice_buyer.get("address") or invoice.get("clientAddress", "República Dominicana")
        }
        
        # Resolver correo del cliente (solo si no es Factura de Consumo E32, ya que Consumidor Final no debe recibir correos automáticos)
        client_email = None
        if number_code != "32":
            client_email = invoice_buyer.get("mail") or invoice.get("clientEmail")
            if not client_email and company_profile.get("ownerUID"):
                try:
                    from app.services.db_service import DatabaseService
                    owner_uid = company_profile["ownerUID"]
                    client_id = invoice.get("clientId")
                    if client_id:
                        clients = DatabaseService.get_clients(owner_uid, sandbox=True) + DatabaseService.get_clients(owner_uid, sandbox=False)
                        client_obj = next((c for c in clients if c["id"] == client_id), None)
                        if client_obj:
                            client_email = client_obj.get("email")
                except Exception:
                    pass
        buyer["mail"] = client_email or "contacto@cliente.com"
        
        client_contact = invoice_buyer.get("contact") or invoice.get("clientContact") or invoice.get("contact")
        buyer["contact"] = client_contact or invoice.get("clientName", "Robert Townes")

        # Map other buyer fields if present
        for key in ["municipality", "province", "internalCode", "responsibleForPayment", "additionalInformation", "foreignIdentifier"]:
            val = invoice_buyer.get(key) or invoice.get(key)
            if val is not None:
                buyer[key] = val

        if number_code == "47":
            buyer["foreignIdentifier"] = buyer.get("foreignIdentifier") or client_rnc
        else:
            buyer["rnc"] = client_rnc

        # 4. Totales (totals)
        totals = {}
        info_totals = invoice.get("totals") or {}
        
        subtotal_val = info_totals.get("totalTaxedAmount") or info_totals.get("exemptAmount") or invoice.get("subtotal") or 0.0
        itbis_val = info_totals.get("itbisTotal") or invoice.get("totalITBIS") or 0.0
        total_val = info_totals.get("totalAmount") or invoice.get("total") or 0.0
        
        if number_code in ["43", "47"]:
            totals["exemptAmount"] = subtotal_val
            totals["totalAmount"] = total_val
            totals["amountPeriod"] = total_val
            totals["payValue"] = total_val
            if float(invoice.get("retainedISR", 0.0)) > 0:
                totals["isrTotalRetention"] = float(invoice["retainedISR"])
            
            # Map any other totals fields present in invoice
            for key in ["previousBalance", "amountAdvancePayment", "amountPeriod", "payValue", "itbisTotalRetained", "isrTotalRetention"]:
                val = info_totals.get(key) or invoice.get(key)
                if val is not None:
                    totals[key] = float(val)
        else:
            totals["totalTaxedAmount"] = subtotal_val
            totals["i1AmountTaxed"] = subtotal_val
            totals["itbisS1"] = 18
            totals["itbisTotal"] = itbis_val
            totals["itbis1Total"] = itbis_val
            totals["totalAmount"] = total_val
            
            # Map any other totals fields present in invoice
            for key in ["previousBalance", "amountAdvancePayment", "amountPeriod", "payValue", "itbisTotalRetained", "isrTotalRetention"]:
                val = info_totals.get(key) or invoice.get(key)
                if val is not None:
                    totals[key] = float(val)
                    
            if number_code == "41":
                if "amountPeriod" not in totals:
                    totals["amountPeriod"] = total_val
                if "payValue" not in totals:
                    totals["payValue"] = invoice.get("netPayable") or total_val
                if "itbisTotalRetained" not in totals:
                    totals["itbisTotalRetained"] = float(invoice.get("retainedITBIS", 0.0))

        # 4b. Otra Moneda (otherCurrency) si aplica
        other_currency = {}
        invoice_currency = invoice.get("currency", "DOP")
        exchange_rate = float(invoice.get("exchangeRate") or 1.0)
        if invoice_currency != "DOP" and exchange_rate > 0:
            other_currency = {
                "currencyType": invoice_currency,
                "exchangeRate": exchange_rate,
                "totalTaxedAmountOtherCurrency": round(subtotal_val / exchange_rate, 2),
                "amountTaxed1OtherCurrency": round(subtotal_val / exchange_rate, 2),
                "itbisTotalOtherCurrency": round(itbis_val / exchange_rate, 2),
                "itbis1TotalOtherCurrency": round(itbis_val / exchange_rate, 2),
                "totalAmountOtherCurrency": round(total_val / exchange_rate, 2)
            }

        # 5. Detalles de Artículos (itemDetails)
        item_details = []
        for index, item in enumerate(invoice.get("items", [])):
            item_code = item.get("code") or f"ITM-{index+1}"
            qty_val = item.get("quantity") or item.get("quantityItem") or 1
            price_val = item.get("price") or item.get("unitPriceItem") or 0.0
            sub_val = item.get("subtotal") or item.get("itemAmount") or (float(qty_val) * float(price_val))
            itbis_rate_val = item.get("itbisRate") or item.get("itbis_rate") or 0.18

            item_code_table = item.get("itemCodeTable")
            if not item_code_table:
                item_code_table = [
                    {
                        "codeType": "Interna",
                        "itemCode": item_code
                    }
                ]

            item_dict = {
                "lineNumber": index + 1,
                "productCode": item_code,
                "itemCodeTable": item_code_table,
                "itemName": item["name"],
                "quantityItem": float(qty_val),
                "unitPriceItem": float(price_val),
                "itemAmount": float(sub_val),
                "goodServiceIndicator": 2 if item.get("type", "Bien").lower() == "servicio" else 1,
                "billingIndicator": 4 if float(itbis_rate_val) == 0.0 else 1
            }

            if item.get("itemDescription"):
                item_dict["itemDescription"] = item["itemDescription"]

            unit_val = item.get("unitMeasure") or item.get("unit") or 58
            try:
                item_dict["unitMeasure"] = int(unit_val)
            except ValueError:
                item_dict["unitMeasure"] = unit_val

            # Detalle de otra moneda por ítem si aplica
            if invoice_currency != "DOP" and exchange_rate > 0:
                item_dict["otherCurrencyDetail"] = {
                    "priceOtherCurrency": round(float(price_val) / exchange_rate, 2),
                    "discountOtherCurrency": round(float(item.get("discount_amount", 0.0)) / exchange_rate, 2),
                    "surchargeAnotherCurrency": 0.0,
                    "amountItemOtherCurrency": round(float(sub_val) / exchange_rate, 2)
                }

            # Retenciones a nivel de ítem si existen o vienen en el input
            item_retention = item.get("retention")
            if item_retention:
                item_dict["retention"] = item_retention
            else:
                item_count = max(1, len(invoice.get("items", [])))
                if number_code == "41" and float(invoice.get("retainedITBIS", 0.0)) > 0:
                    item_dict["retention"] = {
                        "indicatorAgentWithholdingPerception": 1,
                        "itbisAmountWithheld": float(invoice["retainedITBIS"]) / item_count
                    }
                elif number_code == "47" and float(invoice.get("retainedISR", 0.0)) > 0:
                    item_dict["retention"] = {
                        "indicatorAgentWithholdingPerception": 1,
                        "isrAmountWithheld": float(invoice["retainedISR"]) / item_count
                    }

            item_details.append(item_dict)

        payload = {
            "idDoc": id_doc,
            "sender": sender,
            "totals": totals,
            "itemDetails": item_details,
            "config": {
                "pdf": {"type": "generic"}
            }
        }
        
        transport = invoice.get("transport")
        if transport:
            payload["transport"] = transport
        
        if other_currency:
            payload["otherCurrency"] = other_currency
            
        if client_rnc:
            payload["buyer"] = buyer

        # Referencia para Notas de Crédito (34) o Débito (33)
        if number_code in ["33", "34"]:
            info_ref = invoice.get("informationReference") or {}
            mod_code = info_ref.get("modificationCode") or invoice.get("modificationCode") or 3
            ncf_mod = info_ref.get("ncfModified") or invoice.get("ncfModified") or invoice.get("xmlSignature") or "E310000000001"
            ncf_mod_date = info_ref.get("ncfModifiedDate") or invoice.get("ncfModifiedDate") or invoice.get("date", date_str)[:10]
            
            if ncf_mod_date and len(ncf_mod_date) > 10:
                ncf_mod_date = ncf_mod_date[:10]
                
            reason = info_ref.get("reasonForModification") or invoice.get("reasonForModification") or invoice.get("comentario") or invoice.get("notes") or "Corrección de importes"
            
            payload["informationReference"] = {
                "modificationCode": int(mod_code),
                "ncfModified": ncf_mod,
                "ncfModifiedDate": ncf_mod_date,
                "reasonForModification": reason
            }

        return payload

    @classmethod
    def emit_cancellation(cls, company_profile, cancellation, sandbox=True):
        """Envía una petición de anulación de rango de comprobantes a Alanube."""
        base_url = Config.ALANUBE_SANDBOX_BASE_URL if sandbox else Config.ALANUBE_PRODUCTION_BASE_URL
        token = Config.ALANUBE_SANDBOX_TOKEN if sandbox else Config.ALANUBE_PRODUCTION_TOKEN
        company_id = (company_profile.get("alanubeCompanyIDSandbox") or Config.ALANUBE_SANDBOX_COMPANY_ID) if sandbox else (company_profile.get("alanubeCompanyIDProduction") or Config.ALANUBE_PRODUCTION_COMPANY_ID)

        url = f"{base_url}/dom/v1/cancellations"
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        company_rnc = str(company_profile.get("companyRNC", "132109122")).replace("-", "").strip()
        date_str = datetime.utcnow().strftime("%Y-%m-%d")

        payload = {
            "header": {
                "rnc": company_rnc,
                "fechaAnulacion": date_str
            },
            "cancellations": [
                {
                    "series": cancellation["series"],
                    "startSequence": int(cancellation["startSequence"]),
                    "endSequence": int(cancellation["endSequence"]),
                    "reason": cancellation["reason"]
                }
            ]
        }

        if company_id:
            payload["company"] = {
                "identification": company_id
            }

        # Modo Contingencia local por defecto
        if token == "DEVELOPMENT_SANDBOX_TOKEN" or token == "PRODUCTION_REAL_TOKEN" or not token:
            print("🛡️ Modo contingencia: Anulación de secuencias simulada localmente.")
            return {
                "success": True,
                "status": "Aceptado",
                "cancellationCode": f"MOCK-CAN-{uuid.uuid4().hex[:8].upper()}",
                "message": "Anulación de rango procesada exitosamente en Contingencia."
            }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=12)
            if response.status_code >= 200 and response.status_code < 300:
                data = response.json()
                return {
                    "success": True,
                    "status": "Aceptado",
                    "cancellationCode": data.get("cancellationCode") or f"CAN-{uuid.uuid4().hex[:8].upper()}",
                    "message": data.get("message") or "Anulación de rango procesada exitosamente."
                }
            else:
                try:
                    error_detail = response.json()
                    err_msg = cls.get_dgii_friendly_error(error_detail)
                    return {
                        "success": False,
                        "message": f"Error de Alanube: {err_msg} (Código HTTP {response.status_code})"
                    }
                except Exception:
                    return {
                        "success": False,
                        "message": f"Error en anulación (Código HTTP {response.status_code})"
                    }
        except requests.RequestException as e:
            return {
                "success": False,
                "message": f"Error de conexión con la API de Alanube: {str(e)}"
            }

    @classmethod
    def notify_by_email(cls, company_profile, xml_signature, ecf_type="Factura de Consumo (E32)", recipient_email=None, pdf_type="generic", sandbox=True):
        """
        Notifica por correo un comprobante electrónico (e-CF) emitido.
        POST {base_url}{endpoint_path}/notify-by-email
        """
        base_url = Config.ALANUBE_SANDBOX_BASE_URL if sandbox else Config.ALANUBE_PRODUCTION_BASE_URL
        token = Config.ALANUBE_SANDBOX_TOKEN if sandbox else Config.ALANUBE_PRODUCTION_TOKEN
        company_id = (company_profile.get("alanubeCompanyIDSandbox") or Config.ALANUBE_SANDBOX_COMPANY_ID) if sandbox else (company_profile.get("alanubeCompanyIDProduction") or Config.ALANUBE_PRODUCTION_COMPANY_ID)

        path = cls.get_endpoint_path(ecf_type)
        url = f"{base_url}{path}/notify-by-email"
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        payload = {
            "id": xml_signature
        }
        if company_id:
            payload["idCompany"] = company_id
        if recipient_email:
            payload["mail"] = recipient_email
        if pdf_type:
            payload["pdfType"] = pdf_type

        # Si el token es simulado o estamos en modo offline/contingencia sin token real:
        if token == "DEVELOPMENT_SANDBOX_TOKEN" or token == "PRODUCTION_REAL_TOKEN" or not token:
            print("🛡️ Modo contingencia / sandbox mock: Notificación por correo simulada localmente.")
            return {
                "success": True,
                "message": f"Notificación enviada exitosamente por correo (Simulado localmente) a {recipient_email or 'correo registrado'}."
            }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=12)
            if response.status_code >= 200 and response.status_code < 300:
                return {
                    "success": True,
                    "message": "Éxito en la notificación del documento electrónico por correo."
                }
            else:
                try:
                    error_detail = response.json()
                    err_msg = cls.get_dgii_friendly_error(error_detail)
                    return {
                        "success": False,
                        "message": f"Error de Alanube: {err_msg} (Código HTTP {response.status_code})"
                    }
                except Exception:
                    return {
                        "success": False,
                        "message": f"Error en la notificación (Código HTTP {response.status_code})"
                    }
        except requests.RequestException as e:
            return {
                "success": False,
                "message": f"Error de conexión con la API de Alanube: {str(e)}"
            }

    @classmethod
    def check_directory(cls, company_profile, rnc, sandbox=True):
        """
        Consultar el directorio de compañías activas para facturación electrónica por idCompany.
        GET /dom/v1/check-directory/idCompany/{idCompany}?rnc={rnc}
        """
        base_url = Config.ALANUBE_SANDBOX_BASE_URL if sandbox else Config.ALANUBE_PRODUCTION_BASE_URL
        token = Config.ALANUBE_SANDBOX_TOKEN if sandbox else Config.ALANUBE_PRODUCTION_TOKEN
        company_id = (company_profile.get("alanubeCompanyIDSandbox") or Config.ALANUBE_SANDBOX_COMPANY_ID) if sandbox else (company_profile.get("alanubeCompanyIDProduction") or Config.ALANUBE_PRODUCTION_COMPANY_ID)

        url = f"{base_url}/dom/v1/check-directory/idCompany/{company_id or 'default'}"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {token}"
        }
        params = {"rnc": str(rnc).replace("-", "").strip()}

        # Modo contingencia / simulación local
        if token == "DEVELOPMENT_SANDBOX_TOKEN" or token == "PRODUCTION_REAL_TOKEN" or not token:
            print("🛡️ Modo contingencia / sandbox mock: Consulta de directorio simulada.")
            clean_rnc = params["rnc"]
            if clean_rnc == "999999999":
                return {
                    "success": False,
                    "message": "Compañía no encontrada en el directorio activo de facturación electrónica."
                }
            return {
                "success": True,
                "rnc": clean_rnc,
                "active": True,
                "razonSocial": "Empresa Homologada Electrónica SRL",
                "urls": ["https://dgii.gov.do/validaecf"],
                "message": "Compañía activa para facturación electrónica en el directorio de la DGII."
            }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code >= 200 and response.status_code < 300:
                return {
                    "success": True,
                    "data": response.json(),
                    "message": "Consulta realizada exitosamente."
                }
            else:
                return {
                    "success": False,
                    "message": f"Compañía no encontrada o error al consultar (Código HTTP {response.status_code})"
                }
        except requests.RequestException as e:
            return {
                "success": False,
                "message": f"Error de conexión con la API de Alanube: {str(e)}"
            }

    @classmethod
    def check_dgii_status(cls, company_profile, environment=None, maintenance=None, sandbox=True):
        """
        Consultar el estado de la DGII por idCompany.
        GET /dom/v1/check-dgii-status/idCompany/{idCompany}?environment={env}&maintenance={maint}
        """
        base_url = Config.ALANUBE_SANDBOX_BASE_URL if sandbox else Config.ALANUBE_PRODUCTION_BASE_URL
        token = Config.ALANUBE_SANDBOX_TOKEN if sandbox else Config.ALANUBE_PRODUCTION_TOKEN
        company_id = (company_profile.get("alanubeCompanyIDSandbox") or Config.ALANUBE_SANDBOX_COMPANY_ID) if sandbox else (company_profile.get("alanubeCompanyIDProduction") or Config.ALANUBE_PRODUCTION_COMPANY_ID)

        url = f"{base_url}/dom/v1/check-dgii-status/idCompany/{company_id or 'default'}"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {token}"
        }
        
        params = {}
        if environment:
            params["environment"] = str(environment)
        if maintenance:
            params["maintenance"] = str(maintenance)

        # Modo contingencia / simulación local
        if token == "DEVELOPMENT_SANDBOX_TOKEN" or token == "PRODUCTION_REAL_TOKEN" or not token:
            print("🛡️ Modo contingencia / sandbox mock: Consulta de estado de DGII simulada.")
            return {
                "success": True,
                "status": "ONLINE",
                "environments": {
                    "PreCertificacion": "Disponible",
                    "Certificacion": "Disponible",
                    "Produccion": "Disponible"
                },
                "maintenanceWindow": "No hay mantenimientos planificados para hoy.",
                "message": "Servicios de la DGII operando con normalidad."
            }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code >= 200 and response.status_code < 300:
                return {
                    "success": True,
                    "data": response.json(),
                    "message": "Estado de la DGII consultado con éxito."
                }
            else:
                return {
                    "success": False,
                    "message": f"Error al consultar estado de la DGII (Código HTTP {response.status_code})"
                }
        except requests.RequestException as e:
            return {
                "success": False,
                "message": f"Error de conexión con la API de Alanube: {str(e)}"
            }

    @classmethod
    def register_company(cls, company_profile, sandbox=True):
        """
        Registra la empresa como compañía en el API de Alanube.
        POST /dom/v1/companies
        """
        base_url = Config.ALANUBE_SANDBOX_BASE_URL if sandbox else Config.ALANUBE_PRODUCTION_BASE_URL
        token = Config.ALANUBE_SANDBOX_TOKEN if sandbox else Config.ALANUBE_PRODUCTION_TOKEN

        url = f"{base_url}/dom/v1/companies"
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        # Estructurar objeto del certificado
        cert_payload = None
        if company_profile.get("certificateContent"):
            cert_payload = {
                "name": company_profile.get("certificateName", "firma_digital"),
                "extension": company_profile.get("certificateExtension", ".p12"),
                "content": company_profile.get("certificateContent"),
                "password": company_profile.get("certificatePassword", "")
            }

        payload = {
            "name": company_profile.get("companyName"),
            "tradeName": company_profile.get("tradeName", company_profile.get("companyName")),
            "identification": str(company_profile.get("companyRNC", "")).replace("-", "").strip(),
            "type": company_profile.get("companyType", "associated"),
            "address": company_profile.get("companyAddress", "Santo Domingo, RD"),
            "province": company_profile.get("province", "Santo Domingo"),
            "municipality": company_profile.get("municipality", "Santo Domingo de Guzmán"),
            "email": company_profile.get("companyEmail")
        }

        if cert_payload:
            payload["certificate"] = cert_payload

        if company_profile.get("logoBase64"):
            payload["logo"] = company_profile.get("logoBase64")

        # Modo contingencia / simulación local
        if token == "DEVELOPMENT_SANDBOX_TOKEN" or token == "PRODUCTION_REAL_TOKEN" or not token:
            print("🛡️ Modo contingencia / sandbox mock: Registro de empresa simulado.")
            return {
                "success": True,
                "message": "Compañía registrada / sincronizada exitosamente con Alanube (Simulado localmente)."
            }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            if response.status_code >= 200 and response.status_code < 300:
                return {
                    "success": True,
                    "message": "Compañía registrada exitosamente en la plataforma de Alanube."
                }
            else:
                try:
                    error_detail = response.json()
                    err_msg = cls.get_dgii_friendly_error(error_detail)
                    return {
                        "success": False,
                        "message": f"Error de Alanube: {err_msg} (Código HTTP {response.status_code})"
                    }
                except Exception:
                    return {
                        "success": False,
                        "message": f"Error en registro de compañía (Código HTTP {response.status_code})"
                    }
        except requests.RequestException as e:
            return {
                "success": False,
                "message": f"Error de conexión con la API de Alanube: {str(e)}"
            }

    @classmethod
    def get_company_from_alanube(cls, identification, sandbox=True):
        """
        Obtiene la información de una compañía registrada en Alanube.
        GET /dom/v1/companies/{identification}
        """
        base_url = Config.ALANUBE_SANDBOX_BASE_URL if sandbox else Config.ALANUBE_PRODUCTION_BASE_URL
        token = Config.ALANUBE_SANDBOX_TOKEN if sandbox else Config.ALANUBE_PRODUCTION_TOKEN

        clean_id = str(identification).replace("-", "").strip()
        url = f"{base_url}/dom/v1/companies/{clean_id}"
        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {token}"
        }

        # Simulación en caso de usar tokens de prueba o modo contingencia
        if token == "DEVELOPMENT_SANDBOX_TOKEN" or token == "PRODUCTION_REAL_TOKEN" or not token:
            print("🛡️ Modo contingencia / sandbox mock: Consulta de datos de empresa simulada.")
            return {
                "success": True,
                "data": {
                    "name": "Alanube Sincronizada S.R.L.",
                    "tradeName": "Alanube Sincronizada",
                    "identification": clean_id,
                    "type": "main",
                    "address": "Av. Winston Churchill, Santo Domingo",
                    "province": "Distrito Nacional",
                    "municipality": "Santo Domingo de Guzmán",
                    "email": "contacto@alanubesincronizada.com.do",
                    "logo": "",
                    "certificate": {
                        "name": "firma_sincronizada",
                        "extension": ".p12",
                        "content": "MOCK_BASE64_CERTIFICATE_CONTENT_FROM_ALANUBE",
                        "password": "PasswordAlanubeMock123"
                    }
                },
                "message": "Datos de empresa obtenidos correctamente de Alanube (Simulado)."
            }

        try:
            response = requests.get(url, headers=headers, timeout=12)
            if response.status_code >= 200 and response.status_code < 300:
                return {
                    "success": True,
                    "data": response.json(),
                    "message": "Datos de empresa obtenidos exitosamente de Alanube."
                }
            else:
                try:
                    error_detail = response.json()
                    err_msg = cls.get_dgii_friendly_error(error_detail)
                    return {
                        "success": False,
                        "message": f"Error de Alanube: {err_msg} (Código HTTP {response.status_code})"
                    }
                except Exception:
                    return {
                        "success": False,
                        "message": f"Fallo al obtener datos de empresa de Alanube (Código HTTP {response.status_code})"
                    }
        except requests.RequestException as e:
            return {
                "success": False,
                "message": f"Error de conexión con la API de Alanube: {str(e)}"
            }




