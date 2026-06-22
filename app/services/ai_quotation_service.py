import requests
import json
from config import Config
from app.services.db_service import DatabaseService
from app.brand import get_product_name

class AIQuotationService:
    @staticmethod
    def _get_api_key(owner_uid=None):
        api_key = Config.OPENAI_API_KEY.strip()
        if api_key and api_key != "YOUR_OPENAI_API_KEY_HERE" and api_key != "":
            return api_key
        if owner_uid:
            profile = DatabaseService.get_company_profile(owner_uid)
            return profile.get("openaiApiKey", "").strip()
        return ""

    @classmethod
    def _call_openai(cls, owner_uid, system_prompt, user_message, temperature=0.3, max_tokens=2000):
        api_key = cls._get_api_key(owner_uid)
        if not api_key or api_key == "YOUR_OPENAI_API_KEY_HERE":
            return {"success": False, "message": "API Key de OpenAI no configurada."}

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return {"success": True, "content": content}
        except requests.exceptions.Timeout:
            return {"success": False, "message": "La IA no respondió a tiempo. Intente de nuevo."}
        except Exception as e:
            return {"success": False, "message": f"Error de IA: {str(e)}"}

    @classmethod
    def generate_full_quotation(cls, owner_uid, user_context, company):
        product_name = get_product_name()
        today = __import__('datetime').datetime.now().strftime('%d/%m/%Y')

        system_prompt = f"""Eres un experto en crear cotizaciones profesionales para servicios de software y tecnología en República Dominicana.
Trabajas para {product_name}, una plataforma de facturación electrónica certificada por la DGII.

Debes generar una cotización profesional en formato JSON válido. Tu respuesta debe ser ÚNICAMENTE el JSON, sin explicaciones ni markdown.

La estructura JSON debe ser:

{{
  "subject": "Título o asunto de la cotización",
  "items": [
    {{
      "code": "Código del item",
      "name": "Nombre del producto/servicio",
      "description": "Descripción detallada",
      "quantity": 1,
      "price": 0.00,
      "itbisRate": 0.18
    }}
  ],
  "scopeIncluded": ["Lista de lo que incluye el proyecto"],
  "scopeExcluded": ["Lista de lo que NO incluye"],
  "deliverables": [
    {{"name": "Nombre del entregable", "description": "Descripción", "estimatedDate": "Tiempo estimado"}}
  ],
  "timeline": [
    {{"phase": "Nombre de la fase", "description": "Descripción", "duration": "Duración (ej: 2 semanas)"}}
  ],
  "paymentSchedule": [
    {{"installment": 1, "description": "Descripción del hito", "percentage": 50.0, "trigger": "Evento que activa el pago"}}
  ],
  "validityDays": 15,
  "termsAndConditions": "Términos y condiciones generales",
  "intellectualProperty": "Cláusula de propiedad intelectual",
  "confidentiality": "Cláusula de confidencialidad",
  "supportTerms": "Términos de soporte post-entrega",
  "warrantyTerms": "Términos de garantía",
  "observations": "Observaciones adicionales",
  "currency": "RD$",
  "paymentType": "Transferencia Bancaria",
  "paymentMethod": "Transferencia"
}}

Reglas:
- Los precios deben ser en RD$ (pesos dominicanos).
- ITBIS por defecto 18% (0.18).
- La suma de percentages en paymentSchedule debe ser 100.
- Los términos deben ser legales pero amigables, adaptados a la legislación dominicana.
- Si el usuario no especifica precios, sugiere precios de mercado razonables."""

        user_message = f"""Contexto del cliente:
Empresa: {company.get('companyName', 'Mi Empresa')}
RNC: {company.get('companyRNC', 'N/A')}
Rubro: {company.get('companyBusinessType', 'Tecnología')}

Fecha actual: {today}

Instrucciones del usuario para la cotización:
{user_context}

Genera la cotización profesional completa en JSON."""

        result = cls._call_openai(owner_uid, system_prompt, user_message, temperature=0.4, max_tokens=3000)
        if not result["success"]:
            return result

        content = result["content"].strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            data = json.loads(content)
            return {"success": True, "data": data}
        except json.JSONDecodeError:
            return {"success": False, "message": "La IA generó una respuesta inválida. Intente de nuevo con más detalles."}

    @classmethod
    def suggest_section(cls, owner_uid, section, context_data):
        section_names = {
            "scope": "Alcance del Proyecto (incluye/excluye)",
            "deliverables": "Entregables",
            "timeline": "Cronograma o Fases",
            "payment": "Plan de Pagos",
            "terms": "Términos Legales (T&C, Propiedad Intelectual, Confidencialidad, Soporte, Garantía)",
            "items": "Partidas / Productos / Servicios"
        }
        section_name = section_names.get(section, section)

        system_prompt = f"""Eres un experto en crear cotizaciones profesionales de software.
Genera ÚNICAMENTE contenido en JSON para la sección "{section_name}" de una cotización.
Responde solo con el JSON válido, sin explicaciones."""

        user_message = f"""Contexto del proyecto:
{json.dumps(context_data, indent=2) if isinstance(context_data, dict) else str(context_data)}

Genera el JSON para la sección: {section_name}"""

        return cls._call_openai(owner_uid, system_prompt, user_message, temperature=0.3, max_tokens=1500)
