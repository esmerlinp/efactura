import requests
import json
from datetime import datetime, timezone
from config import Config
from app.services.db_service import DatabaseService, db_firestore
from app.brand import get_product_name


def _coll(owner_uid, sandbox, name):
    prefix = "sandbox_" if sandbox else ""
    return db_firestore.collection("users").document(owner_uid).collection(f"{prefix}{name}")


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_clients",
            "description": "Buscar clientes de la empresa. Filtros opcionales por nombre o RNC.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Texto para buscar en nombre o RNC del cliente"},
                    "limit": {"type": "integer", "description": "Máximo de resultados (default 50, max 100)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_invoices",
            "description": "Buscar facturas electrónicas (e-CF) emitidas. Excluye Borrador, Anulada y Eliminada por defecto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filtrar por estado: Emitida, Vencida, Parcialmente Cobrada, Cobrada, Revisión de Pago"},
                    "date_from": {"type": "string", "description": "Fecha inicial (YYYY-MM-DD)"},
                    "date_to": {"type": "string", "description": "Fecha final (YYYY-MM-DD)"},
                    "client_name": {"type": "string", "description": "Filtrar por nombre del cliente"},
                    "include_borrador": {"type": "boolean", "description": "Incluir facturas en Borrador"},
                    "limit": {"type": "integer", "description": "Máximo de resultados (default 50, max 100)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_quotations",
            "description": "Buscar cotizaciones. Filtros opcionales por estado, fecha o cliente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filtrar por estado: Borrador, Pendiente, Aprobada, Rechazada"},
                    "date_from": {"type": "string", "description": "Fecha inicial (YYYY-MM-DD)"},
                    "date_to": {"type": "string", "description": "Fecha final (YYYY-MM-DD)"},
                    "client_name": {"type": "string", "description": "Filtrar por nombre del cliente"},
                    "limit": {"type": "integer", "description": "Máximo de resultados (default 50, max 100)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_expenses",
            "description": "Buscar gastos registrados. Filtros opcionales.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": "Fecha inicial (YYYY-MM-DD)"},
                    "date_to": {"type": "string", "description": "Fecha final (YYYY-MM-DD)"},
                    "deducible": {"type": "boolean", "description": "Filtrar por deducibilidad"},
                    "search": {"type": "string", "description": "Texto para buscar en concepto del gasto"},
                    "limit": {"type": "integer", "description": "Máximo de resultados (default 50, max 100)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_items",
            "description": "Buscar productos o servicios del catálogo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Texto para buscar en nombre o código"},
                    "limit": {"type": "integer", "description": "Máximo de resultados (default 50, max 100)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_financial_summary",
            "description": "Obtener resumen financiero: total de ventas, cuentas por cobrar, gastos y conteos en un rango de fechas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": "Fecha inicial (YYYY-MM-DD). Si no se especifica, incluye todo el historial."},
                    "date_to": {"type": "string", "description": "Fecha final (YYYY-MM-DD)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_client_debt",
            "description": "Consultar la deuda pendiente de un cliente específico. Busca facturas emitidas, parcialmente cobradas o vencidas con saldo > 0. No incluye borradores, anuladas ni eliminadas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {"type": "string", "description": "Nombre del cliente (búsqueda parcial, no necesita ser exacto)"},
                    "client_rnc": {"type": "string", "description": "RNC del cliente (opcional, para más precisión)"}
                },
                "required": ["client_name"]
            }
        }
    }
]


def _serialize_doc(doc):
    data = doc.to_dict() if doc.exists else {}
    data["id"] = doc.id
    for k, v in data.items():
        if hasattr(v, "isoformat"):
            data[k] = v.isoformat()
    return data


def _run_query_clients(owner_uid, sandbox, args):
    search = (args.get("search") or "").strip().lower()
    limit = min(int(args.get("limit", 50)), 100)
    results = []
    for doc in _coll(owner_uid, sandbox, "clients").get():
        d = _serialize_doc(doc)
        if search:
            name = (d.get("razonSocial") or d.get("name") or "").lower()
            rnc = (d.get("rnc") or "").lower()
            if search not in name and search not in rnc:
                continue
        results.append({
            "id": d["id"],
            "nombre": d.get("razonSocial") or d.get("name") or "N/A",
            "rnc": d.get("rnc", ""),
            "email": d.get("email", ""),
            "telefono": d.get("telefono", ""),
            "direccion": d.get("direccion", "")
        })
        if len(results) >= limit:
            break
    return json.dumps({"total": len(DatabaseService.get_clients(owner_uid, sandbox=sandbox)), "results": results}, ensure_ascii=False)


def _run_query_invoices(owner_uid, sandbox, args):
    status_filter = args.get("status")
    date_from = args.get("date_from")
    date_to = args.get("date_to")
    client_name = (args.get("client_name") or "").strip().lower()
    include_borrador = args.get("include_borrador", False)
    limit = min(int(args.get("limit", 50)), 100)
    results = []
    excluded = {"Anulada", "Eliminada"}
    if not include_borrador:
        excluded.add("Borrador")
    for doc in _coll(owner_uid, sandbox, "invoices").get():
        d = _serialize_doc(doc)
        if d.get("isQuotation"):
            continue
        if d.get("status") in excluded:
            continue
        if status_filter and d.get("status") != status_filter:
            continue
        if date_from and (d.get("date") or "")[:10] < date_from:
            continue
        if date_to and (d.get("date") or "")[:10] > date_to:
            continue
        if client_name and client_name not in (d.get("clientName") or "").lower():
            continue
        balance = d.get("remainingBalance", d.get("total", 0))
        results.append({
            "id": d["id"],
            "numero": d.get("invoiceNumber", d["id"]),
            "fecha": (d.get("date") or "")[:10],
            "cliente": d.get("clientName", "Consumidor Final"),
            "total": d.get("total", 0),
            "saldo_pendiente": balance,
            "estado": d.get("status"),
            "tipo": d.get("ecfType", "N/A")
        })
        if len(results) >= limit:
            break
    total_sum = sum(r["total"] for r in results)
    pending_sum = sum(r["saldo_pendiente"] for r in results if r["estado"] in ("Emitida", "Parcialmente Cobrada", "Vencida") and r["saldo_pendiente"] > 0)
    return json.dumps({"count": len(results), "total_sum": total_sum, "pending_sum": pending_sum, "results": results}, ensure_ascii=False)


def _run_query_quotations(owner_uid, sandbox, args):
    status_filter = args.get("status")
    date_from = args.get("date_from")
    date_to = args.get("date_to")
    client_name = (args.get("client_name") or "").strip().lower()
    limit = min(int(args.get("limit", 50)), 100)
    results = []
    status_map = {"Borrador": "Borrador", "Pendiente": "Pendiente", "Aprobada": "Aprobada", "Rechazada": "Rechazada", "Facturada": "Facturada"}
    for doc in _coll(owner_uid, sandbox, "invoices").get():
        d = _serialize_doc(doc)
        if not d.get("isQuotation"):
            continue
        s = status_map.get(d.get("status"), d.get("status", "Borrador"))
        if status_filter and s != status_filter:
            continue
        if date_from and (d.get("date") or "")[:10] < date_from:
            continue
        if date_to and (d.get("date") or "")[:10] > date_to:
            continue
        if client_name and client_name not in (d.get("clientName") or "").lower():
            continue
        results.append({
            "id": d["id"],
            "numero": d.get("invoiceNumber", d["id"]),
            "fecha": (d.get("date") or "")[:10],
            "cliente": d.get("clientName") or "Cliente",
            "total": d.get("total", 0),
            "estado": s
        })
        if len(results) >= limit:
            break
    return json.dumps({"count": len(results), "results": results}, ensure_ascii=False)


def _run_query_expenses(owner_uid, sandbox, args):
    date_from = args.get("date_from")
    date_to = args.get("date_to")
    deducible = args.get("deducible")
    search = (args.get("search") or "").strip().lower()
    limit = min(int(args.get("limit", 50)), 100)
    results = []
    for doc in _coll(owner_uid, sandbox, "expenses").get():
        d = _serialize_doc(doc)
        if date_from and (d.get("date") or "")[:10] < date_from:
            continue
        if date_to and (d.get("date") or "")[:10] > date_to:
            continue
        if deducible is not None and d.get("isDeductible") != deducible:
            continue
        if search and search not in (d.get("concept") or d.get("description") or "").lower():
            continue
        results.append({
            "id": d["id"],
            "concepto": d.get("concept") or d.get("description", ""),
            "fecha": (d.get("date") or "")[:10],
            "monto": d.get("amount", 0),
            "deducible": d.get("isDeductible", False),
            "tipo": d.get("expenseType", "General")
        })
        if len(results) >= limit:
            break
    total_sum = sum(r["monto"] for r in results)
    deductible_sum = sum(r["monto"] for r in results if r["deducible"])
    return json.dumps({"count": len(results), "total_sum": total_sum, "deductible_sum": deductible_sum, "results": results}, ensure_ascii=False)


def _run_query_items(owner_uid, sandbox, args):
    search = (args.get("search") or "").strip().lower()
    limit = min(int(args.get("limit", 50)), 100)
    results = []
    for doc in _coll(owner_uid, sandbox, "items").get():
        d = _serialize_doc(doc)
        if search:
            name = (d.get("name") or "").lower()
            code = (d.get("code") or "").lower()
            if search not in name and search not in code:
                continue
        results.append({
            "id": d["id"],
            "nombre": d.get("name", "N/A"),
            "codigo": d.get("code", ""),
            "precio": d.get("price", 0),
            "stock": d.get("stock", 0),
            "tipo": d.get("type", "Producto")
        })
        if len(results) >= limit:
            break
    return json.dumps({"count": len(results), "results": results}, ensure_ascii=False)


def _run_get_financial_summary(owner_uid, sandbox, args):
    date_from = args.get("date_from", "0001-01-01")
    date_to = args.get("date_to", "9999-12-31")
    total_sales = 0.0
    total_pending = 0.0
    invoice_count = 0
    expense_total = 0.0
    expense_count = 0
    client_count = 0
    for doc in _coll(owner_uid, sandbox, "invoices").get():
        d = _serialize_doc(doc)
        if d.get("isQuotation") or d.get("status") in ("Anulada", "Eliminada", "Borrador"):
            continue
        if (d.get("date") or "")[:10] < date_from or (d.get("date") or "")[:10] > date_to:
            continue
        total_sales += d.get("total", 0)
        invoice_count += 1
        balance = d.get("remainingBalance", d.get("total", 0))
        if d.get("status") in ("Emitida", "Parcialmente Cobrada", "Vencida") and balance > 0:
            total_pending += balance
    for doc in _coll(owner_uid, sandbox, "expenses").get():
        d = _serialize_doc(doc)
        if (d.get("date") or "")[:10] < date_from or (d.get("date") or "")[:10] > date_to:
            continue
        expense_total += d.get("amount", 0)
        expense_count += 1
    for _ in _coll(owner_uid, sandbox, "clients").get():
        client_count += 1
    return json.dumps({
        "periodo": {"desde": date_from, "hasta": date_to},
        "ventas": {"total": total_sales, "cantidad_facturas": invoice_count},
        "cuentas_por_cobrar": {"pendiente": total_pending},
        "gastos": {"total": expense_total, "cantidad": expense_count},
        "clientes": {"registrados": client_count}
    }, ensure_ascii=False)


def _run_query_client_debt(owner_uid, sandbox, args):
    client_name = (args.get("client_name") or "").strip().lower()
    client_rnc = (args.get("client_rnc") or "").strip().lower()
    results = []
    # 1. Find matching clients
    matched_client_ids = set()
    client_names_map = {}
    for doc in _coll(owner_uid, sandbox, "clients").get():
        d = _serialize_doc(doc)
        name = (d.get("razonSocial") or d.get("name") or "").lower()
        rnc = (d.get("rnc") or "").lower()
        if client_name and client_name not in name:
            continue
        if client_rnc and client_rnc != rnc:
            continue
        matched_client_ids.add(d["id"])
        client_names_map[d["id"]] = d.get("razonSocial") or d.get("name") or "N/A"

    if not matched_client_ids:
        return json.dumps({"total_deuda": 0, "cantidad_facturas": 0, "mensaje": f"No se encontró ningún cliente que coincida con '{args.get('client_name', '')}'."}, ensure_ascii=False)

    # 2. Find pending invoices for matched clients
    pending_statuses = {"Emitida", "Parcialmente Cobrada", "Vencida"}
    for doc in _coll(owner_uid, sandbox, "invoices").get():
        d = _serialize_doc(doc)
        if d.get("isQuotation"):
            continue
        if d.get("status") not in pending_statuses:
            continue
        if d.get("clientId") not in matched_client_ids:
            continue
        balance = d.get("remainingBalance", d.get("total", 0))
        if balance <= 0:
            continue
        results.append({
            "id": d["id"],
            "numero": d.get("invoiceNumber", d["id"]),
            "fecha": (d.get("date") or "")[:10],
            "cliente": d.get("clientName", ""),
            "total": d.get("total", 0),
            "saldo_pendiente": balance,
            "estado": d.get("status"),
            "enlace": f"/invoices/{d['id']}"
        })

    total_deuda = sum(r["saldo_pendiente"] for r in results)
    return json.dumps({
        "total_deuda": total_deuda,
        "cantidad_facturas": len(results),
        "facturas": results
    }, ensure_ascii=False)


TOOL_HANDLERS = {
    "query_clients": _run_query_clients,
    "query_invoices": _run_query_invoices,
    "query_quotations": _run_query_quotations,
    "query_expenses": _run_query_expenses,
    "query_items": _run_query_items,
    "get_financial_summary": _run_get_financial_summary,
    "query_client_debt": _run_query_client_debt,
}


class ChatbotService:

    @classmethod
    def get_help_kb(cls):
        product = get_product_name()
        return f"""
=== BASE DE CONOCIMIENTO FISCAL DE {product.upper()} (REPÚBLICA DOMINICANA) ===

1. RÉGIMEN SIMPLIFICADO DE TRIBUTACIÓN (RST) BASADO EN INGRESOS:
- Beneficio DGII para profesionales independientes y microempresas.
- e-CF se reportan en tiempo real, simplificando declaraciones.
- Exime de liquidación mensual de ITBIS (IT-1).
- Declaración anual simplificada en febrero/marzo.
- Límite 2026: RD$ 12,068,181.09. Excederlo traslada al Régimen General retroactivo con penalidades.
- En {product}, al activar RST en Configuración, el dashboard muestra barra visual de control del límite anual.

2. GASTOS DEDUCIBLES (Art. 287 Código Tributario):
- Deducibles si son necesarios para obtener y conservar ingresos gravados.
- Deducibles: Laptops de trabajo, internet comercial, software, suscripciones, alquiler oficina.
- No Deducibles: Compras supermercado familiar, ropa personal, entretenimiento.
- En {product}, el switch "Deducible" permite control y filtrado para cumplimiento DGII.

3. RETENCIONES ISR E ITBIS (PROFESIONALES INDEPENDIENTES):
- ISR Retenido: 10% fijo del subtotal neto.
- ITBIS Retenido: 100% del ITBIS facturado (tasa 18%).
- Neto a Recibir (netPayable): Subtotal + ITBIS - Ret. ISR - Ret. ITBIS.

4. FACTURACIÓN ELECTRÓNICA (E-CF) - LEY 32-23:
- Transición obligatoria a e-CF. NCF Tradicional vs e-CF Electrónico.
- Código QR obligatorio en representación impresa.
- Correcciones: Nota de Crédito o Débito. Regla 30 días para devolución ITBIS.
- Rechazo del cliente requiere Nota de Crédito. Rechazo DGII anula el comprobante.

5. CONTINGENCIA DGII (Art. 40-43):
- Emisión Offline: Máximo 72h para enviar a DGII. Leyenda "e-CF emitido en modalidad de contingencia".
- Fallo Técnico: Hasta 15 días con secuencias físicas. Regularización en 30 días.
- En {product}, se activa Modo Fallback automáticamente.
"""

    @classmethod
    def ask_chatbot(cls, owner_uid, message, history=None, sandbox=True):
        if history is None:
            history = []

        profile = DatabaseService.get_company_profile(owner_uid)
        api_key = profile.get("openaiApiKey", "").strip()

        using_global_key = False
        if not api_key:
            api_key = Config.OPENAI_API_KEY.strip()
            using_global_key = True

        if not api_key or api_key == "YOUR_OPENAI_API_KEY_HERE":
            return {
                "success": False,
                "message": "⚠️ **Clave de API de OpenAI no configurada.**\n\nPor favor, introduce tu clave secreta de OpenAI en el panel de **Administrar Empresa** (sección Datos del Emisor) o solicita al administrador del servidor que la agregue al archivo `.env` como `OPENAI_API_KEY`."
            }

        FREE_MONTHLY_LIMIT = 50
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")

        if using_global_key:
            last_reset = profile.get("chatbotLastReset", "")
            usage_count = int(profile.get("chatbotUsageCount", 0))
            if last_reset != current_month:
                usage_count = 0
                profile["chatbotUsageCount"] = 0
                profile["chatbotLastReset"] = current_month
                DatabaseService.save_company_profile(owner_uid, profile)
            if usage_count >= FREE_MONTHLY_LIMIT:
                return {
                    "success": False,
                    "message": f"⚠️ **Límite de consultas mensuales alcanzado (Cuota del Servidor).**\n\nHaz consumido tus **{FREE_MONTHLY_LIMIT} consultas de cortesía** de este mes.\n\nPara seguir disfrutando del asistente IA de forma **ilimitada**, introduce tu propia clave de API de OpenAI en la pantalla de [Configuración de Empresa](/company/settings) o solicita una ampliación de cuota a soporte."
                }

        product = get_product_name()

        system_prompt = f"""Eres el Asistente Inteligente de {product}, un experto en análisis de datos empresariales y fiscal de la República Dominicana (DGII), especializado en la Ley 32-23 de Facturación Electrónica.

ROL Y NORMAS:
- Te llamas "Asistente {product}" y debes presentarte así la primera vez.
- Responde preguntas sobre los **datos de la empresa** combinados con tu **conocimiento fiscal** (RST, ITBIS, ISR, retenciones, deducibilidad, Ley 32-23, contingencia DGII).
- **SIEMPRE que menciones un documento**, incluye un enlace directo Markdown: `[Texto](URL)`. Las URLs disponibles son:
  - Factura o Cotización: `/invoices/<id>`
  - Cliente: `/clients/<id>`
  - Gasto: `/expenses/<id>`
- **USA LAS HERRAMIENTAS DISPONIBLES** para consultar datos. No inventes cifras. Si la herramienta no devuelve resultados, dilo claramente.
- **Para consultar la deuda de un cliente específico usa `query_client_debt`.** Ejemplo: "¿cuánto debe el cliente X?" o "¿cuál es la deuda de X?" → llama a `query_client_debt(client_name="X")`.
- **NO respondas preguntas no relacionadas** con los datos de la empresa o normativa fiscal dominicana. Responde: "Lo siento, solo puedo ayudarte con preguntas relacionadas con los datos de tu empresa y normativa fiscal dominicana. Esta consulta viola las políticas de uso del asistente."
- **NO realices acciones** (crear, modificar, eliminar). Ofrece el enlace a la sección correspondiente.
- Sé claro, profesional, pedagógico. Usa Markdown (negritas, viñetas, tablas).
- Usa un tono amigable pero profesional. Muestra seguridad en los números.

EMPRESA ACTUAL:
- Nombre: {profile.get("companyName", "N/A")}
- RNC: {profile.get("companyRNC", "N/A")}
- Régimen: {profile.get("regimenFiscal", "N/A")}
- Entorno: {"Sandbox (Pruebas)" if sandbox else "Producción"}

{cls.get_help_kb()}
"""
        api_messages = [{"role": "system", "content": system_prompt}]
        for chat in history[-8:]:
            api_messages.append({"role": chat.get("role"), "content": chat.get("content")})
        api_messages.append({"role": "user", "content": message})

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        MAX_TOOL_ROUNDS = 5
        current_round = 0

        while current_round < MAX_TOOL_ROUNDS:
            current_round += 1
            payload = {
                "model": "gpt-4o-mini",
                "messages": api_messages,
                "temperature": 0.3,
                "max_tokens": 1000
            }
            if current_round == 1:
                payload["tools"] = TOOLS
                payload["tool_choice"] = "auto"

            try:
                resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=30)
                if resp.status_code != 200:
                    err_json = {}
                    try:
                        err_json = resp.json()
                    except:
                        pass
                    err_msg = err_json.get("error", {}).get("message", f"Código HTTP: {resp.status_code}")
                    return {"success": False, "message": f"❌ **Error en la API de OpenAI:**\n\n{err_msg}"}

                data = resp.json()
                choice = data["choices"][0]
                msg = choice["message"]

                if not msg.get("tool_calls"):
                    assistant_reply = msg.get("content") or ""

                    if using_global_key:
                        try:
                            profile["chatbotUsageCount"] = int(profile.get("chatbotUsageCount", 0)) + 1
                            DatabaseService.save_company_profile(owner_uid, profile)
                        except Exception as ex:
                            print(f"⚠️ Error al guardar incremento de cuota en Firestore: {ex}")

                    return {"success": True, "message": assistant_reply}

                api_messages.append(msg)

                for tc in msg["tool_calls"]:
                    tool_name = tc["function"]["name"]
                    try:
                        tool_args = json.loads(tc["function"]["arguments"])
                    except:
                        tool_args = {}

                    handler = TOOL_HANDLERS.get(tool_name)
                    if handler:
                        try:
                            result = handler(owner_uid, sandbox, tool_args)
                        except Exception as e:
                            result = json.dumps({"error": str(e)})
                    else:
                        result = json.dumps({"error": f"Tool '{tool_name}' not found"})

                    api_messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result
                    })

            except requests.exceptions.Timeout:
                return {"success": False, "message": "❌ **La consulta tomó demasiado tiempo.** Intenta con una pregunta más específica."}
            except Exception as e:
                return {"success": False, "message": f"❌ **Error de conexión con el servidor de inteligencia artificial:**\n\n{str(e)}"}

        return {"success": False, "message": "⚠️ **La consulta requirió demasiadas operaciones.** Intenta simplificar la pregunta."}
