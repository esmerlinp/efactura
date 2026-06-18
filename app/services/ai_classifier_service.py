import requests
import json
from config import Config
from app.services.db_service import DatabaseService, db_firestore, firebase_initialized
from app.services.ai_service import AIService


class AIExpenseClassifier:

    CATEGORIES = [
        "Comida y Restaurantes",
        "Transporte y Combustible",
        "Servicios Básicos",
        "Software y Tecnología",
        "Materiales de Oficina",
        "Alquileres",
        "Impuestos y Tasas",
        "Otros Gastos",
    ]

    @classmethod
    def classify_expense_from_import(cls, owner_uid, supplier_name, supplier_rnc,
                                     items_text, total, date_str, ecf_type):
        api_key = AIService._get_api_key(owner_uid)
        if not api_key or api_key == "YOUR_OPENAI_API_KEY_HERE":
            return cls._fallback_classify(supplier_name, items_text)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        system_prompt = f"""Eres un clasificador inteligente de gastos empresariales para República Dominicana.
Analiza los datos del comprobante fiscal electrónico (e-CF) y responde ÚNICAMENTE con un objeto JSON.

Categorías de gasto disponibles:
{chr(10).join(f'- {c}' for c in cls.CATEGORIES)}

Códigos DGII de tipo de gasto:
01 - Gastos de Personal (Nómina, bonos, capacitación)
02 - Gastos por Trabajos, Suministros y Servicios (Honorarios, servicios contratados, insumos, luz, internet)
03 - Arrendamientos (Alquiler de locales, vehículos, equipos)
04 - Gastos de Activos Fijos (Mantenimiento, reparación, depreciación)
05 - Gastos de Representación (Relaciones públicas, publicidad, viajes)
06 - Otras deducciones (Seguros, tasas, patentes)
07 - Gastos Financieros (Intereses, comisiones bancarias)

Responde con:
{{
  "category": "nombre de la categoría más adecuada",
  "tipoGastoDGII": "código de dos dígitos",
  "suggestedAccount": "nombre de cuenta contable sugerida",
  "confidence": 0.0 a 1.0,
  "isRecurring": true o false,
  "recurrenceInterval": "mensual" (si isRecurring es true, si no: ""),
  "isDeductible": true o false,
  "anomalies": ["descripción de alerta si hay inconsistencia"]
}}"""

        user_content = f"""Proveedor: {supplier_name}
RNC: {supplier_rnc}
Tipo e-CF: {ecf_type}
Fecha: {date_str}
Monto Total: RD$ {total:.2f}
Detalle: {items_text}"""

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.1,
            "max_tokens": 300,
        }

        try:
            url = "https://api.openai.com/v1/chat/completions"
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"].strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                result = json.loads(content)
                if result.get("category") not in cls.CATEGORIES:
                    result["category"] = "Otros Gastos"
                valid_dgii = ["01", "02", "03", "04", "05", "06", "07"]
                if result.get("tipoGastoDGII") not in valid_dgii:
                    result["tipoGastoDGII"] = "02"
                result["confidence"] = min(max(float(result.get("confidence", 0.5)), 0.0), 1.0)
                return result
            else:
                return cls._fallback_classify(supplier_name, items_text)
        except Exception as e:
            print(f"⚠️ AI classifier error: {e}")
            return cls._fallback_classify(supplier_name, items_text)

    @classmethod
    def _fallback_classify(cls, supplier_name, items_text):
        text = (supplier_name + " " + items_text).lower()
        category = "Otros Gastos"
        dgii_code = "02"
        is_recurring = False
        is_deductible = True

        if any(w in text for w in ["comida", "restaurant", "almuerzo", "cafeteria"]):
            category = "Comida y Restaurantes"
            dgii_code = "05"
        elif any(w in text for w in ["combustible", "gasolina", "gasoil", "taxi", "uber", "transporte"]):
            category = "Transporte y Combustible"
            dgii_code = "02"
        elif any(w in text for w in ["luz", "internet", "agua", "telefono", "celular", "energia"]):
            category = "Servicios Básicos"
            dgii_code = "02"
            is_recurring = True
        elif any(w in text for w in ["software", "hosting", "dominio", "aws", "azure", "cloud", "servidor", "saas"]):
            category = "Software y Tecnología"
            dgii_code = "02"
            is_recurring = True
        elif any(w in text for w in ["oficina", "papeleria", "papel", "tinta", "toner", "escritorio"]):
            category = "Materiales de Oficina"
            dgii_code = "02"
        elif any(w in text for w in ["alquiler", "renta", "arrendamiento"]):
            category = "Alquileres"
            dgii_code = "03"
            is_recurring = True
        elif any(w in text for w in ["impuesto", "tasa", "patente", "municipal"]):
            category = "Impuestos y Tasas"
            dgii_code = "06"

        return {
            "category": category,
            "tipoGastoDGII": dgii_code,
            "suggestedAccount": f"Gastos de {category}",
            "confidence": 0.6,
            "isRecurring": is_recurring,
            "recurrenceInterval": "mensual" if is_recurring else "",
            "isDeductible": is_deductible,
            "anomalies": [],
        }

    @classmethod
    def detect_duplicate(cls, owner_uid, supplier_rnc, total, date_str, sandbox=True):
        rnc_clean = "".join(filter(str.isdigit, str(supplier_rnc))) if supplier_rnc else ""
        if not rnc_clean:
            return None

        expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
        for exp in expenses:
            exp_rnc = "".join(filter(str.isdigit, str(exp.get("rncEmisor", ""))))
            if exp_rnc != rnc_clean:
                continue
            exp_total = float(exp.get("amount", 0))
            if abs(exp_total - total) / max(total, 1) > 0.05:
                continue
            exp_date = (exp.get("date") or "")[:10]
            if date_str and exp_date:
                from datetime import datetime as dt
                try:
                    d1 = dt.strptime(date_str[:10], "%Y-%m-%d")
                    d2 = dt.strptime(exp_date, "%Y-%m-%d")
                    if abs((d1 - d2).days) <= 3:
                        return {
                            "duplicate": True,
                            "existingId": exp["id"],
                            "existingConcept": exp.get("concept", ""),
                            "existingDate": exp_date,
                            "existingAmount": exp_total,
                        }
                except ValueError:
                    continue
        return None
