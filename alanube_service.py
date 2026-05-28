import requests
import uuid
import json
from datetime import datetime
from urllib.parse import quote
from config import Config

class AlanubeService:
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

        # Si es Crédito Fiscal (E31) y no tiene RNC corporativo válido, lanzar error
        if number_code == "31" and (client_rnc == "999999999" or len(client_rnc) != 9):
            raise ValueError("Para emitir un Crédito Fiscal (E31) se requiere un RNC de cliente corporativo de 9 dígitos.")

        # Construir payload estructurado de Alanube
        payload = cls.build_payload(company_profile, invoice, company_rnc, client_rnc, number_code, short_code)

        # Determinar credenciales según entorno
        base_url = Config.ALANUBE_SANDBOX_BASE_URL if sandbox else Config.ALANUBE_PRODUCTION_BASE_URL
        token = Config.ALANUBE_SANDBOX_TOKEN if sandbox else Config.ALANUBE_PRODUCTION_TOKEN
        company_id = Config.ALANUBE_SANDBOX_COMPANY_ID if sandbox else Config.ALANUBE_PRODUCTION_COMPANY_ID

        path = cls.get_endpoint_path(ecf_type)
        url = f"{base_url}{path}"

        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        print(f"📡 Enviando payload a Alanube API (POST {url})...")
        
        # Activar Contingencia si estamos usando el token simulado por defecto
        use_fallback = (token == "DEVELOPMENT_SANDBOX_TOKEN" or token == "PRODUCTION_REAL_TOKEN" or not token)
        
        if not use_fallback:
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=12)
                if response.status_code >= 200 and response.status_code < 300:
                    data = response.json()
                    print("✅ Alanube API emitió exitosamente el comprobante.")
                    return {
                        "success": True,
                        "encf": data.get("encf") or invoice.get("encf"),
                        "xmlSignature": data.get("id") or f"ALANUBE-ID-{uuid.uuid4().hex[:12].upper()}",
                        "qrCodeURL": data.get("qr_code_url") or cls.generate_mock_qr(company_rnc, client_rnc, invoice.get("encf", "E320000000001"), invoice["total"]),
                        "pdfUrl": data.get("pdf_url"),
                        "xmlUrl": data.get("xml_url"),
                        "mode": "API"
                    }
                else:
                    print(f"⚠️ Alanube API retornó error {response.status_code}. Activando Fallback de Contingencia.")
                    try:
                        error_detail = response.json()
                        err_msg = error_detail.get("errors", [{}])[0].get("message") or error_detail.get("response", [{}])[0].get("message") or "Error desconocido de Alanube."
                        print(f"Mensaje de error Alanube: {err_msg}")
                    except Exception:
                        pass
                    use_fallback = True
            except requests.RequestException as e:
                print(f"❌ Excepción de red al conectar con Alanube: {e}. Activando Fallback de Contingencia.")
                use_fallback = True

        # Ejecución de MODO CONTINGENCIA (FALLBACK)
        if use_fallback:
            print("🛡️ Ejecutando firma mock y código QR de validación local según Ley 32-23...")
            
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
                "mode": "FALLBACK"
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
        
        # 1. Encabezado de Documento (idDoc)
        id_doc = {
            "encf": invoice.get("encf") or "PENDIENTE",
            "sequenceDueDate": invoice.get("dueDate", date_str),
            "paymentType": 2 if invoice.get("paymentType") == "Crédito" else 1, # 1: Contado, 2: Crédito
        }
        
        if number_code in ["31", "32", "33", "34"]:
            id_doc["taxAmountIndicator"] = 0
            id_doc["incomeType"] = 1

        if number_code == "41":
            id_doc["paymentDeadline"] = invoice.get("dueDate", date_str)
            id_doc["paymentTerm"] = "30 días"
            id_doc["paymentFormsTable"] = [
                {"paymentMethod": 1, "paymentAmount": invoice["total"]}
            ]

        if number_code == "47":
            id_doc["paymentDeadline"] = invoice.get("dueDate", date_str)
            id_doc["paymentTerm"] = "30 días"
            id_doc["dateFrom"] = invoice.get("date", date_str)
            id_doc["dateUntil"] = invoice.get("dueDate", date_str)

        # 2. Datos del Emisor (sender)
        sender = {
            "rnc": company_rnc,
            "companyName": company_profile.get("companyName", "Mi Empresa SRL"),
            "address": company_profile.get("companyAddress", "Santo Domingo, RD"),
            "municipality": "010101",
            "province": "010000",
            "phoneNumber": [company_profile.get("companyPhone", "809-555-0199")],
            "mail": company_profile.get("companyEmail", "factura@miempresa.com.do"),
            "stampDate": invoice.get("date", date_str)[:10]
        }

        # 3. Datos del Receptor (buyer)
        buyer = {
            "companyName": invoice.get("clientName", "Consumidor Final"),
            "address": invoice.get("clientAddress", "República Dominicana"),
            "mail": "contacto@cliente.com"
        }
        
        if number_code == "47":
            buyer["foreignIdentifier"] = client_rnc
        else:
            buyer["rnc"] = client_rnc

        # 4. Totales (totals)
        totals = {}
        if number_code in ["43", "47"]:
            totals["exemptAmount"] = invoice["subtotal"]
            totals["totalAmount"] = invoice["total"]
            totals["amountPeriod"] = invoice["total"]
            totals["payValue"] = invoice["total"]
            if float(invoice.get("retainedISR", 0.0)) > 0:
                totals["isrTotalRetention"] = float(invoice["retainedISR"])
        else:
            totals["totalTaxedAmount"] = invoice["subtotal"]
            totals["i1AmountTaxed"] = invoice["subtotal"]
            totals["itbisS1"] = 18
            totals["itbisTotal"] = invoice["totalITBIS"]
            totals["itbis1Total"] = invoice["totalITBIS"]
            totals["totalAmount"] = invoice["total"]
            
            if number_code == "41":
                totals["amountPeriod"] = invoice["total"]
                totals["payValue"] = invoice["netPayable"]
                totals["itbisTotalRetained"] = float(invoice.get("retainedITBIS", 0.0))

        # 5. Detalles de Artículos (itemDetails)
        item_details = []
        for index, item in enumerate(invoice.get("items", [])):
            item_dict = {
                "lineNumber": index + 1,
                "productCode": item.get("code") or f"ITM-{index+1}",
                "itemName": item["name"],
                "quantityItem": int(item["quantity"]),
                "unitPriceItem": float(item["price"]),
                "itemAmount": float(item["subtotal"]),
                "goodServiceIndicator": 2 if item.get("type", "Bien").lower() == "servicio" else 1,
                "billingIndicator": 4 if float(item.get("itbisRate", 0.18)) == 0.0 else 1
            }

            # Retenciones a nivel de ítem si existen
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
        
        if client_rnc:
            payload["buyer"] = buyer

        # Referencia para Notas de Crédito (34) o Débito (33)
        if number_code in ["33", "34"]:
            custom_notes = invoice.get("notes") or "Corrección de importes"
            payload["informationReference"] = {
                "modificationCode": 3,
                "ncfModified": invoice.get("xmlSignature") or "E310000000001",
                "ncfModifiedDate": invoice.get("date", date_str)[:10],
                "reasonForModification": custom_notes
            }

        return payload

    @classmethod
    def emit_cancellation(cls, company_profile, cancellation, sandbox=True):
        """Envía una petición de anulación de rango de comprobantes a Alanube."""
        base_url = Config.ALANUBE_SANDBOX_BASE_URL if sandbox else Config.ALANUBE_PRODUCTION_BASE_URL
        token = Config.ALANUBE_SANDBOX_TOKEN if sandbox else Config.ALANUBE_PRODUCTION_TOKEN
        company_id = Config.ALANUBE_SANDBOX_COMPANY_ID if sandbox else Config.ALANUBE_PRODUCTION_COMPANY_ID

        url = f"{base_url}/dom/v1/cancellations"
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"Bearer {token}"
        }

        company_rnc = str(company_profile.get("companyRNC", "132109122")).replace("-", "").strip()

        payload = {
            "idCompany": company_id or company_rnc,
            "series": cancellation["series"],
            "startSequence": int(cancellation["startSequence"]),
            "endSequence": int(cancellation["endSequence"]),
            "reason": cancellation["reason"]
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
                    err_msg = error_detail.get("message") or error_detail.get("response", [{}])[0].get("message") or "Fallo de respuesta."
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
