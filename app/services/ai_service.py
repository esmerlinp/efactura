import requests
import json
import base64
from config import Config
from app.services.db_service import DatabaseService
from app.brand import get_product_name

class AIService:
    @staticmethod
    def _get_api_key(owner_uid=None):
        # Priorizar la API Key configurada en el archivo .env del sistema
        api_key = Config.OPENAI_API_KEY.strip()
        if api_key and api_key != "YOUR_OPENAI_API_KEY_HERE" and api_key != "":
            return api_key
            
        # Fallback a la API Key del perfil de la empresa si no está definida a nivel de sistema
        if owner_uid:
            profile = DatabaseService.get_company_profile(owner_uid)
            return profile.get("openaiApiKey", "").strip()
        return ""

    @classmethod
    def analyze_receipt_ocr(cls, owner_uid, file_bytes, mime_type):
        """
        Envía una imagen (base64) o texto a GPT-4o-mini para extraer datos fiscales dominicanos.
        """
        api_key = cls._get_api_key(owner_uid)
        if not api_key or api_key == "YOUR_OPENAI_API_KEY_HERE":
            return {"success": False, "message": "API Key de OpenAI no configurada."}

        # Convert HEIC/HEIF to JPEG
        is_heic = "heic" in mime_type.lower() or "heif" in mime_type.lower()
        if is_heic:
            try:
                from PIL import Image
                import pillow_heif
                import io
                
                heif_file = pillow_heif.read_heif(io.BytesIO(file_bytes))
                image = Image.frombytes(
                    heif_file.mode, 
                    heif_file.size, 
                    heif_file.data,
                    "raw",
                    heif_file.mode,
                    heif_file.stride,
                )
                
                out_buffer = io.BytesIO()
                image.save(out_buffer, format="JPEG", quality=90)
                file_bytes = out_buffer.getvalue()
                mime_type = "image/jpeg"
            except Exception as e:
                return {"success": False, "message": f"Error al convertir imagen HEIC a JPEG: {str(e)}"}

        is_pdf = "pdf" in mime_type.lower()
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        system_prompt = """Eres un extractor de datos de facturas y tickets fiscales para República Dominicana.
Debes retornar ÚNICAMENTE un objeto JSON estructurado con la siguiente información:
{
  "rncEmisor": "RNC del proveedor (solo números, sin guiones, de 9 u 11 dígitos)",
  "ncf": "NCF o e-CF completo (ej: B01... o E31...)",
  "supplierName": "Razón Social o nombre comercial del proveedor que emite la factura",
  "amount": 0.00, (monto total incluyendo impuestos, número flotante)
  "itbisAmount": 0.00, (monto del ITBIS extraído o calculado, número flotante)
  "concept": "Concepto o descripción corta de la compra (ej: Materiales de oficina, Almuerzo de negocios, etc.)",
  "date": "YYYY-MM-DD" (fecha de emisión de la factura),
  "items": [
    {
      "concept": "Nombre del producto o servicio individual",
      "value": 100.00, (precio unitario sin impuestos)
      "quantity": 1, (cantidad, entero)
      "tax": 0.18, (tasa de ITBIS como decimal, ej: 0.18 para 18%, o 0 si exento, o "exento" si aplica)
      "total": 118.00 (total de la línea, precio * cantidad + impuesto)
    }
  ]
}
IMPORTANTE: Si la factura tiene un desglose de items, extrae cada línea individual en el array items. Si no hay desglose visible, devuelve un solo item con el total de la factura como total y sin impuesto en value.
Si no encuentras algún dato, usa string vacío "" o 0.0 para montos, y array vacío [] para items. No agregues explicaciones, markdown o texto extra. Solo el JSON puro."""

        if is_pdf:
            try:
                import io
                import pypdf
                pdf_file = io.BytesIO(file_bytes)
                reader = pypdf.PdfReader(pdf_file)
                pdf_text = ""
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        pdf_text += page_text + "\n"
                
                user_content = f"Analiza el siguiente texto extraído de un PDF de factura e identifica los campos solicitados:\n\n{pdf_text}"
            except Exception as e:
                return {"success": False, "message": f"Error al procesar el archivo PDF: {str(e)}"}
        else:
            base64_image = base64.b64encode(file_bytes).decode('utf-8')
            user_content = [
                {
                    "type": "text",
                    "text": "Analiza esta factura e identifica los campos solicitados."
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{base64_image}"
                    }
                }
            ]

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_content
                }
            ],
            "temperature": 0.1,
            "max_tokens": 500
        }

        try:
            url = "https://api.openai.com/v1/chat/completions"
            response = requests.post(url, headers=headers, json=payload, timeout=20)
            if response.status_code == 200:
                res_data = response.json()
                content = res_data["choices"][0]["message"]["content"].strip()
                # Limpiar posibles bloques de código de markdown
                if content.startswith("```json"):
                    content = content[7:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                data = json.loads(content)
                
                # Corregir si el OCR intercambió NCF y RNC o leyó el NCF en el RNC
                rnc_val = "".join(filter(str.isalnum, str(data.get("rncEmisor", "")))).strip()
                ncf_val = "".join(filter(str.isalnum, str(data.get("ncf", "")))).strip()
                
                # Limpiar residuos al final si es un e-CF numérico leído en el RNC (ej: 3200000466103fi -> 3200000466103)
                if rnc_val.startswith(('31', '32', '41', '43', '45')) and len(rnc_val) > 12:
                    digits_only = "".join(filter(str.isdigit, rnc_val))
                    if len(digits_only) == 12:
                        rnc_val = digits_only

                is_rnc_actually_ncf = False
                
                # Caso A: Empieza con letras típicas de NCF/e-CF
                if any(c.isalpha() for c in rnc_val) and rnc_val.upper().startswith(('B', 'E', 'A')):
                    is_rnc_actually_ncf = True
                # Caso B: Tiene 13 caracteres (ej: E320000466103)
                elif len(rnc_val) == 13:
                    is_rnc_actually_ncf = True
                # Caso C: Tiene 12 dígitos y empieza con prefijos de e-CF sin la 'E' (31, 32, 41, 43, 45)
                elif len(rnc_val) == 12 and rnc_val.startswith(('31', '32', '41', '43', '45')):
                    is_rnc_actually_ncf = True
                    rnc_val = "E" + rnc_val # Restaurar 'E' inicial
                
                if is_rnc_actually_ncf:
                    ncf_digits = "".join(filter(str.isdigit, ncf_val))
                    if len(ncf_digits) in [9, 11]:
                        data["rncEmisor"] = ncf_digits
                    else:
                        data["rncEmisor"] = "" # Limpiar RNC incorrecto
                    data["ncf"] = rnc_val
                
                # Sanear RNC (solo dígitos)
                if data.get("rncEmisor"):
                    data["rncEmisor"] = "".join(filter(str.isdigit, str(data["rncEmisor"])))
                # Sanear NCF (alfanumérico y mayúsculas, sin espacios ni guiones)
                if data.get("ncf"):
                    data["ncf"] = "".join(filter(str.isalnum, str(data["ncf"]))).upper()
                # Sanear supplierName
                if data.get("supplierName"):
                    data["supplierName"] = str(data["supplierName"]).strip()
                else:
                    data["supplierName"] = ""
                # Sanear items: asegurar que sea lista y cada item tenga los campos requeridos
                items = data.get("items", [])
                if not isinstance(items, list):
                    items = []
                sanitized_items = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    si = {}
                    si["concept"] = str(item.get("concept", "")).strip()
                    try:
                        si["value"] = float(item.get("value", 0) or 0)
                    except (ValueError, TypeError):
                        si["value"] = 0.0
                    try:
                        si["quantity"] = int(item.get("quantity", 1) or 1)
                    except (ValueError, TypeError):
                        si["quantity"] = 1
                    tax_raw = item.get("tax")
                    if tax_raw == "exento" or str(tax_raw).lower() == "exento":
                        si["tax"] = "exento"
                    else:
                        try:
                            si["tax"] = float(tax_raw or 0)
                        except (ValueError, TypeError):
                            si["tax"] = 0.0
                    try:
                        si["total"] = float(item.get("total", 0) or 0)
                    except (ValueError, TypeError):
                        si["total"] = 0.0
                    if si["concept"] or si["total"] > 0:
                        sanitized_items.append(si)
                data["items"] = sanitized_items
                    
                return {"success": True, "data": data}
            else:
                return {"success": False, "message": f"Error API OpenAI: {response.text}"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @classmethod
    def classify_dgii_expense(cls, owner_uid, concept):
        """
        Analiza el concepto de un gasto y determina el código de tipo de gasto de la DGII.
        """
        api_key = cls._get_api_key(owner_uid)
        if not api_key or api_key == "YOUR_OPENAI_API_KEY_HERE":
            # Fallback simple local si no hay API Key
            concept_l = concept.lower()
            if "personal" in concept_l or "empleado" in concept_l or "nomina" in concept_l:
                return "01" # Gastos de Personal
            elif "arrend" in concept_l or "alquiler" in concept_l:
                return "05" # Arrendamientos
            elif "manten" in concept_l or "repar" in concept_l:
                return "06" # Gastos de Activos Fijos
            elif "seguro" in concept_l:
                return "07" # Gastos de Seguros
            elif "financ" in concept_l or "interes" in concept_l or "banc" in concept_l:
                return "08" # Gastos Financieros
            elif "comerc" in concept_l or "public" in concept_l or "anuncio" in concept_l:
                return "09" # Gastos de Representación/Promoción
            return "02" # Gastos por Trabajos, Suministros y Servicios (Default común)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        system_prompt = """Clasifica el concepto de un gasto comercial según los códigos oficiales de la DGII para República Dominicana:
01 - Gastos de Personal (Nómina, bonos, capacitación)
02 - Gastos por Trabajos, Suministros y Servicios (Honorarios, servicios contratados, insumos de oficina, luz, internet)
03 - Arrendamientos (Alquiler de locales, vehículos, equipos)
04 - Gastos de Activos Fijos (Mantenimiento, reparación de maquinaria, depreciación)
05 - Gastos de Representación (Relaciones públicas, publicidad, viajes de negocio)
06 - Otras deducciones (Seguros, tasas, patentes)
07 - Gastos Financieros (Intereses de préstamos, comisiones bancarias)

Retorna ÚNICAMENTE las dos cifras del código correspondiente (ej: 02 o 05). Sin explicaciones."""

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Concepto: {concept}"}
            ],
            "temperature": 0.1,
            "max_tokens": 5
        }

        try:
            url = "https://api.openai.com/v1/chat/completions"
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code == 200:
                code = response.json()["choices"][0]["message"]["content"].strip()
                # Limpiar posibles caracteres extras
                code = "".join(filter(str.isdigit, code))
                if len(code) == 1:
                    code = "0" + code
                # Validar código mapeado de vuelta a las opciones del formulario
                # Nota: El formulario usa '01', '02', '03', '04', '05', '06', '07', etc.
                valid_codes = ["01", "02", "03", "04", "05", "06", "07"]
                # Mapear de 05 (representación) a la clasificación del formulario (suele ser 02 o similar)
                if code == "08" or code == "07":
                    return "07" # Financieros
                if code == "05":
                    return "05" # Representación / Promoción en tu formulario
                return code if code in valid_codes else "02"
            else:
                return "02"
        except:
            return "02"

    @classmethod
    def draft_collection_message(cls, owner_uid, client_name, amount, due_date, status, tone="formal", sender_name=None):
        """
        Redacta un recordatorio de cobranza por WhatsApp/Email.
        """
        api_key = cls._get_api_key(owner_uid)
        
        profile = DatabaseService.get_company_profile(owner_uid)
        brand_name = profile.get("tradeName") or profile.get("companyName", "Nuestra Empresa")
        company_rnc = profile.get("companyRNC", "")
        final_sender_name = sender_name or "Departamento de Cobranzas"
        
        # Fallback local
        days_status = "vencida" if status == "Vencida" else "pendiente de pago"
        default_templates = {
            "friendly": f"Hola {client_name}, espero que estés bien. Te escribimos para recordarte que tienes un balance de RD$ {amount:,.2f} {days_status} con fecha límite al {due_date}. Agradecemos tu apoyo con el saldo. ¡Feliz día!\n\nAtentamente,\n{final_sender_name}\nDepartamento de Cobranzas\n{brand_name}",
            "formal": f"Estimado/a {client_name},\n\nLe saludamos cordialmente. A través de la presente le recordamos que su factura con balance de RD$ {amount:,.2f} se encuentra actualmente {days_status} (vence/venció el {due_date}).\n\nLe solicitamos realizar el pago correspondiente a la brevedad. Quedamos a su disposición para cualquier duda.\n\nAtentamente,\n{final_sender_name}\nDepartamento de Cobranzas\n{brand_name}",
            "urgent": f"AVISO DE COBRO URGENTE - {client_name}\n\nLe notificamos que presenta un balance vencido de RD$ {amount:,.2f} desde la fecha {due_date}. Rogamos proceder con el pago inmediato para evitar la suspensión de servicios y cargos adicionales.\n\nAtentamente,\n{final_sender_name}\nDepartamento de Cobranzas\n{brand_name}"
        }

        if not api_key or api_key == "YOUR_OPENAI_API_KEY_HERE":
            return default_templates.get(tone, default_templates["formal"])

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        system_prompt = f"""Eres el encargado de cobranzas de {brand_name} (RNC: {company_rnc}).
Tu tarea es redactar un mensaje corto, directo y altamente personalizado de recordatorio de pago dirigido específicamente a {client_name}.
El tono del mensaje debe ser: {tone} (las opciones son: friendly/amigable, formal, urgent/urgente).
Datos de la deuda:
- Cliente: {client_name}
- Balance pendiente: RD$ {amount:,.2f}
- Fecha de vencimiento: {due_date}
- Estado actual: {status}

Instrucciones:
- NO uses saludos genéricos como "Estimado cliente" ni inventes nombres. Saluda directamente usando el nombre proporcionado: {client_name}.
- Si el tono es friendly: Sé cercano, educado y agradecido.
- Si el tono es formal: Sé profesional, pulcro y respetuoso.
- Si el tono es urgent: Sé imperativo, directo y advierte sobre recargos o suspensión, sin perder la educación.
- El mensaje debe ser apto para enviarse por correo electrónico o WhatsApp.
- Al final del mensaje, DEBES firmar exactamente con el siguiente bloque:

Atentamente,
{final_sender_name}
Departamento de Cobranzas
{brand_name}

- NO menciones "{get_product_name()}" en ninguna parte del texto, ya que la empresa que emite el cobro es {brand_name}.
- Retorna ÚNICAMENTE el texto redactado del mensaje. Sin introducciones ni saludos explicativos."""

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Genera el mensaje de recordatorio de cobro."}
            ],
            "temperature": 0.4,
            "max_tokens": 400
        }

        try:
            url = "https://api.openai.com/v1/chat/completions"
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"].strip()
            else:
                return default_templates.get(tone, default_templates["formal"])
        except:
            return default_templates.get(tone, default_templates["formal"])

    @classmethod
    def suggest_mapping(cls, owner_uid, headers, target_fields):
        """
        Usa IA para emparejar campos del sistema con las columnas cabeceras del CSV.
        Retorna un diccionario mapeando: { target_field_id: index_of_csv_header }
        """
        api_key = cls._get_api_key(owner_uid)
        if not api_key or api_key == "YOUR_OPENAI_API_KEY_HERE":
            return {"success": False, "message": "API Key de OpenAI no configurada."}

        headers_str = ", ".join([f"[{i}]: '{h}'" for i, h in enumerate(headers)])
        # Simplificar estructura para no saturar tokens
        targets_simple = [{"id": t["id"], "name": t["name"]} for t in target_fields]
        targets_str = json.dumps(targets_simple, ensure_ascii=False)

        system_prompt = """Eres un asistente inteligente de integración de datos.
Te daremos una lista de columnas de un archivo CSV con sus índices, y una lista de campos de destino del sistema.
Tu tarea es emparejar de forma lógica cada campo de destino con el índice del CSV correspondiente que mejor encaje con su significado.

Estructura de respuesta:
Debes retornar únicamente un objeto JSON con las asignaciones, donde las claves sean los IDs de los campos de destino y los valores sean los índices numéricos enteros de la columna del CSV (o null si no hay ninguna coincidencia lógica aceptable).

Ejemplo de salida JSON:
{
  "name": 1,
  "price": 3,
  "barcode": null
}

No agregues explicaciones, markdown ni texto extra."""

        user_content = f"Columnas del CSV disponible:\n{headers_str}\n\nCampos de destino del sistema:\n{targets_str}"

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.1,
            "max_tokens": 500
        }

        try:
            api_headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            url = "https://api.openai.com/v1/chat/completions"
            response = requests.post(url, headers=api_headers, json=payload, timeout=12)
            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"].strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                mapping = json.loads(content)
                return {"success": True, "mapping": mapping}
            else:
                return {"success": False, "message": f"Error API OpenAI: {response.text}"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @classmethod
    def polish_comment(cls, owner_uid, content):
        """
        Mejora la ortografía y redacción de un comentario utilizando GPT-4o-mini.
        """
        api_key = cls._get_api_key(owner_uid)
        if not api_key or api_key == "YOUR_OPENAI_API_KEY_HERE":
            return {"success": False, "message": "API Key de OpenAI no configurada."}

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        system_prompt = f"""Eres un asistente inteligente para el sistema {get_product_name()}. Tu tarea es corregir la ortografía y mejorar la redacción de los comentarios y notas internas del usuario sobre documentos de forma profesional, fluida y coherente.
Importante:
- Corrige errores gramaticales u ortográficos.
- Mantén el significado original intacto.
- Retorna ÚNICAMENTE el texto mejorado y corregido, sin explicaciones ni rodeos ni comillas."""

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ],
            "temperature": 0.3,
            "max_tokens": 800
        }

        try:
            url = "https://api.openai.com/v1/chat/completions"
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            if response.status_code == 200:
                polished_text = response.json()["choices"][0]["message"]["content"].strip()
                return {"success": True, "text": polished_text}
            else:
                return {"success": False, "message": f"Error API OpenAI: {response.text}"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @classmethod
    def polish_contract_terms(cls, owner_uid, content, context="", content_type="terms"):
        """
        Mejora y completa términos contractuales utilizando GPT-4o-mini con contexto legal.
        content_type puede ser "terms" (términos legales) o "notes" (notas comerciales).
        """
        api_key = cls._get_api_key(owner_uid)
        if not api_key or api_key == "YOUR_OPENAI_API_KEY_HERE":
            return {"success": False, "message": "API Key de OpenAI no configurada."}

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        if content_type == "terms":
            system_prompt = f"""Eres un asistente legal especializado en redacción de contratos para {get_product_name()}.
Tu tarea es mejorar y completar los términos y condiciones de un contrato, corrigiendo ortografía, mejorando redacción y haciéndolos más profesionales y completos desde el punto de vista legal.

Contexto del contrato:
{context}

Importante:
- Corrige errores gramaticales u ortográficos.
- Mejora la redacción para que sea clara, profesional y юридически sólida.
- Mantén el significado original intacto.
- Si el texto es muy corto o genérico, puedes completarlo con cláusulas estándar apropiadas.
- Retorna ÚNICAMENTE el texto mejorado, sin explicaciones ni comillas."""
        else:
            system_prompt = f"""Eres un asistente inteligente para {get_product_name()}. 
Tu tarea es mejorar las notas comerciales de un contrato, corrigiendo ortografía, mejorando redacción y haciéndolas más profesionales.

Contexto del contrato:
{context}

Importante:
- Corrige errores gramaticales u ortográficos.
- Mantén el significado original intacto.
- Retorna ÚNICAMENTE el texto mejorado, sin explicaciones ni comillas."""

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ],
            "temperature": 0.3,
            "max_tokens": 1200
        }

        try:
            url = "https://api.openai.com/v1/chat/completions"
            response = requests.post(url, headers=headers, json=payload, timeout=20)
            if response.status_code == 200:
                polished_text = response.json()["choices"][0]["message"]["content"].strip()
                return {"success": True, "text": polished_text}
            else:
                return {"success": False, "message": f"Error API OpenAI: {response.text}"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @classmethod
    def generate_client_strategy(cls, owner_uid, client, invoices):
        """
        Analiza un cliente y genera un plan de mitigación para evitar su pérdida.
        Retorna dict con riskLevel, executiveSummary, mitigationSteps, productOffers, campaignSuggestions.
        """
        api_key = cls._get_api_key(owner_uid)
        no_key_fallback = {
            "success": False,
            "message": "API Key de OpenAI no configurada. Configúrela en Ajustes → OpenAI API Key."
        }
        if not api_key or api_key == "YOUR_OPENAI_API_KEY_HERE":
            return no_key_fallback

        # Métricas del cliente
        total_invoiced = sum(inv.get('total', 0) for inv in invoices if inv.get('status') not in ('Anulada', 'Borrador'))
        total_cxc = sum(inv.get('netPayable', 0) for inv in invoices if inv.get('status') in ('Emitida', 'Vencida', 'Revision de Pago'))

        now = __import__('datetime').datetime.now()
        created = client.get('createdAt', '')
        if isinstance(created, str):
            try:
                created_dt = __import__('datetime').datetime.fromisoformat(created.replace('Z', '+00:00'))
                days_active = (now - created_dt).days
            except:
                days_active = 0
        else:
            days_active = 0

        # Última compra
        dated_invoices = [inv for inv in invoices if inv.get('date') and inv.get('status') not in ('Anulada', 'Borrador')]
        dated_invoices.sort(key=lambda x: x.get('date', ''), reverse=True)
        last_invoice = dated_invoices[0] if dated_invoices else None
        last_purchase_days = 0
        if last_invoice and last_invoice.get('date'):
            try:
                last_date = __import__('datetime').datetime.fromisoformat(str(last_invoice['date']).replace('Z', '+00:00'))
                last_purchase_days = (now - last_date).days
            except:
                pass

        invoice_count = len(dated_invoices)

        # Productos más comprados (agregar items de todas las facturas)
        from collections import Counter
        product_counter = Counter()
        product_revenue = {}
        for inv in dated_invoices:
            for item in inv.get('items', []):
                name = item.get('name', 'Producto')
                price = float(item.get('price', 0))
                qty = float(item.get('quantity', 1))
                product_counter[name] += qty
                product_revenue[name] = product_revenue.get(name, 0) + price * qty

        top_products = product_counter.most_common(10)
        top_products_str = "\n".join(
            f"- {name}: {qty:.0f} unidades, RD$ {product_revenue[name]:,.2f}"
            for name, qty in top_products
        ) or "Sin productos registrados."

        # Resumen de facturas recientes (últimas 10)
        recent_invoices = dated_invoices[:10]
        invoices_summary = "\n".join(
            f"  #{inv.get('invoiceNumber', 'N/A')} | {inv.get('date', '')} | RD$ {inv.get('total', 0):,.2f} | {inv.get('status', '')}"
            for inv in recent_invoices
        ) or "Sin facturas."

        # Frecuencia de compra
        if invoice_count > 1 and days_active > 0:
            avg_days_between = days_active // invoice_count
            if avg_days_between <= 30:
                frequency = "Muy frecuente (menos de 30 días entre compras)"
            elif avg_days_between <= 60:
                frequency = "Frecuente (30-60 días)"
            elif avg_days_between <= 120:
                frequency = "Ocasional (2-4 meses)"
            else:
                frequency = "Esporádico (más de 4 meses)"
        else:
            frequency = "Sin suficiente historial"

        # Comportamiento de pago
        paid_count = sum(1 for inv in dated_invoices if inv.get('status') in ('Pagada', 'Cobrada'))
        if invoice_count > 0:
            payment_ratio = paid_count / invoice_count
            if payment_ratio >= 0.8:
                payment_behavior = "Excelente (paga puntualmente)"
            elif payment_ratio >= 0.5:
                payment_behavior = "Regular (paga con retrasos ocasionales)"
            else:
                payment_behavior = "Deficiente (paga con frecuencia fuera de plazo)"
        else:
            payment_behavior = "Sin historial de pagos"

        profile = DatabaseService.get_company_profile(owner_uid)
        brand_name = profile.get("tradeName") or profile.get("companyName", "la empresa")

        system_prompt = f"""Eres un experto en retención de clientes y estrategia comercial para una empresa dominicana ({brand_name}). Tu tarea es analizar el perfil de un cliente y generar un plan de mitigación personalizado para evitar que abandone el servicio.

Genera un análisis con:
1. **Nivel de riesgo** (Alto/Medio/Bajo) basado en frecuencia de compra, antigüedad, ticket promedio, deuda y tiempo desde última compra.
2. **Resumen ejecutivo** de la situación del cliente.
3. **Pasos de mitigación** prioritarios (máximo 5).
4. **Ofertas personalizadas** en productos que ya compra (máximo 3), con descuento sugerido (%).
5. **Sugerencias de campaña** (Email/Call/SMS/WhatsApp) con mensaje breve y timing sugerido.

Responde SOLO con JSON válido. Sin markdown, sin bloques ```json. JSON puro.

Estructura requerida:
{{
    "riskLevel": "Alto",
    "riskScore": 75,
    "executiveSummary": "Resumen ejecutivo en 2-3 oraciones.",
    "riskJustification": "Por qué este cliente tiene este nivel de riesgo.",
    "mitigationSteps": [
        {{"step": "Descripción del paso", "priority": "Alta"}}
    ],
    "productOffers": [
        {{"productName": "Nombre producto", "currentPrice": 1000.0, "suggestedDiscount": 15, "reason": "Por qué este producto"}}
    ],
    "campaignSuggestions": [
        {{"type": "Email", "message": "Mensaje breve para el cliente", "timing": "Día 1 después del análisis"}}
    ],
    "clientHealth": {{
        "purchaseFrequency": "{frequency}",
        "averageTicket": {total_invoiced / max(invoice_count, 1):.2f},
        "lastPurchaseDays": {last_purchase_days},
        "paymentPunctuality": "{payment_behavior}",
        "totalSpent": {total_invoiced:.2f},
        "outstandingDebt": {total_cxc:.2f},
        "daysActive": {days_active},
        "totalInvoices": {invoice_count}
    }}
}}"""

        user_message = f"""Genera el plan de mitigación para el siguiente cliente:

Nombre: {client.get('razonSocial', client.get('name', 'Cliente'))}
RNC: {client.get('rnc', 'N/A')}
Pipeline: {client.get('pipelineStage', 'N/A')}
Antigüedad: {days_active} días
Total facturado: RD$ {total_invoiced:,.2f}
Cuentas por cobrar: RD$ {total_cxc:,.2f}
Última compra: hace {last_purchase_days} días
Frecuencia: {frequency}
Comportamiento de pago: {payment_behavior}

Productos más comprados:
{top_products_str}

Facturas recientes ({len(recent_invoices)}):
{invoices_summary}"""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.3,
            "max_tokens": 2000
        }

        try:
            url = "https://api.openai.com/v1/chat/completions"
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                text = response.json()["choices"][0]["message"]["content"].strip()
                text = text.replace('```json', '').replace('```', '').strip()
                data = json.loads(text)
                data["success"] = True
                return data
            else:
                return {"success": False, "message": f"Error API OpenAI: {response.text}"}
        except json.JSONDecodeError:
            return {"success": False, "message": "La respuesta de la IA no fue JSON válido."}
        except Exception as e:
            return {"success": False, "message": str(e)}

