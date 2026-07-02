import requests
import json
from config import Config
from app.services.db_service import DatabaseService
from app.brand import get_product_name

class ChatbotService:
    
    @classmethod
    def get_company_context(cls, owner_uid, sandbox=True):
        """Recopila un resumen compacto de los datos del cliente actual en Firebase
        para alimentar el prompt de la IA sin saturar el contexto de tokens.
        """
        try:
            # 1. Perfil de empresa
            profile = DatabaseService.get_company_profile(owner_uid)
            
            # 2. Clientes
            clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
            clients_summary = [f"- {c['razonSocial']} (RNC: {c['rnc']})" for c in clients[:10]]
            total_clients = len(clients)
            
            # 3. Catálogo de items
            items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
            items_summary = [f"- {i['name']} (Precio: RD$ {i['price']:.2f}, Código: {i['code']})" for i in items[:8]]
            total_items = len(items)
            
            # 4. Gastos Recientes
            expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
            expenses_summary = []
            total_expenses_amount = 0.0
            total_deductible_amount = 0.0
            for e in expenses[:10]:
                deduc_str = "Deducible" if e.get('isDeductible') else "No Deducible"
                expenses_summary.append(f"- {e['concept']} ({e['date'][:10]}): RD$ {e['amount']:.2f} [{deduc_str}]")
                total_expenses_amount += e['amount']
                if e.get('isDeductible'):
                    total_deductible_amount += e['amount']
            
            # 5. Facturas / Documentos
            invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
            real_invoices = [inv for inv in invoices if not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador']]
            invoices_summary = []
            total_sales_amount = 0.0
            for inv in real_invoices[:10]:
                invoices_summary.append(f"- Factura {inv.get('invoiceNumber', inv['id'])} ({inv['date'][:10]}) para {inv.get('clientName', 'Consumidor Final')}: RD$ {inv['total']:.2f} [{inv['status']}]")
                total_sales_amount += inv['total']

            # 6. Cotizaciones
            quotations = [inv for inv in invoices if inv.get('isQuotation')]
            quotations_summary = []
            for q in quotations[:8]:
                quotations_summary.append(f"- Cotización {q.get('invoiceNumber', q['id'])} ({q['date'][:10]}) para {q.get('clientName') or 'Cliente'}: RD$ {q['total']:.2f}")

            # 7. Resumen consolidado
            context_data = {
                "company_name": profile.get("companyName", "Mi Empresa"),
                "company_rnc": profile.get("companyRNC", "N/A"),
                "company_email": profile.get("companyEmail", "N/A"),
                "regimen_fiscal": profile.get("regimenFiscal", "General"),
                "total_clients": total_clients,
                "recent_clients": "\n".join(clients_summary) if clients_summary else "Ninguno registrado",
                "total_items": total_items,
                "recent_items": "\n".join(items_summary) if items_summary else "Ninguno registrado",
                "total_expenses_amount": total_expenses_amount,
                "total_deductible_amount": total_deductible_amount,
                "recent_expenses": "\n".join(expenses_summary) if expenses_summary else "Ninguno registrado",
                "total_sales_amount": total_sales_amount,
                "recent_invoices": "\n".join(invoices_summary) if invoices_summary else "Ninguno registrado",
                "recent_quotations": "\n".join(quotations_summary) if quotations_summary else "Ninguno registrado",
                "sandbox_mode": sandbox
            }
            return context_data
        except Exception as e:
            print(f"❌ Error recopilando contexto para el chatbot: {e}")
            return {}

    @classmethod
    def get_help_kb(cls):
        """Retorna la base de conocimiento estática alimentada por la ayuda fiscal
        y los flujos del sistema.
        """
        product = get_product_name()
        return f"""
=== BASE DE CONOCIMIENTO FISCAL DE {product.upper()} (REPÚBLICA DOMINICANA) ===

1. RÉGIMEN SIMPLIFICADO DE TRIBUTACIÓN (RST) BASADO EN INGRESOS:
- Es un beneficio de la DGII para profesionales independientes y microempresas.
- Los comprobantes electrónicos (e-CF) se reportan en tiempo real, simplificando la presentación de declaraciones.
- Exime de la liquidación mensual de ITBIS (IT-1).
- Declaración anual simplificada en febrero/marzo sobre ingresos acumulados.
- Límite de facturación para el año 2026: RD$ 12,068,181.09. Si excedes este tope exacto, la DGII te traslada obligatoriamente al Régimen General (retroactivo con penalidades).
- En {product}, al activar el régimen RST en Configuración, el dashboard muestra una barra visual de control del límite anual y alertas preventivas (amarilla al 70%, roja al 90%).

2. GASTOS DEDUCIBLES:
- Según el Art. 287 del Código Tributario, un gasto es deducible solo si es necesario para obtener, mantener y conservar ingresos gravados.
- Deducibles: Laptops de trabajo, internet comercial, software ({product}), suscripciones (AWS, Figma), alquiler de oficina, pasajes de reuniones.
- No Deducibles: Compras de supermercado familiar, ropa de uso diario, boletos de cine, comidas de fin de semana.
- En {product}, el switch "Deducible (Sí/No)" permite al usuario registrar gastos personales para control de presupuesto pero los filtra y excluye al 100% de los simuladores y diagnósticos DGII para proteger el cumplimiento legal.
- Compras Menores (E43 / Tipo 13): Comprobante emitido por ti cuando compras bienes o servicios a personas físicas no registradas en DGII.

3. RETENCIONES DE ISR E ITBIS (PROFESIONALES INDEPENDIENTES EN RD):
- Cuando un freelancer/profesional independiente presta servicios a una persona jurídica (empresa), esta debe retener impuestos como abono adelantado:
  * ISR Retenido: 10% fijo del subtotal neto del servicio.
  * ITBIS Retenido: 100% del ITBIS facturado (si es servicio profesional, tasa estándar del 18%).
- Neto a Recibir (netPayable): Es el valor exacto que recibirás en tu banco tras aplicar las retenciones (Subtotal + ITBIS - Retención ISR - Retención ITBIS). En {product} se destaca en verde esmeralda para facilitar la conciliación bancaria.

4. FACTURACIÓN ELECTRÓNICA Y COMPROBANTES (E-CF):
- Ley 32-23 de Facturación Electrónica: Transición obligatoria a e-CF.
- NCF Tradicional (ej: B0100000001) vs e-CF Electrónico (ej: E3100000001). Los e-CF son formatos XML firmados digitalmente que se transmiten y validan con DGII en tiempo real.
- Código QR obligatorio en la representación impresa para permitir la validación rápida de timbre oficial de la DGII.
- Correcciones y Anulaciones:
  * Ya enviados: Solo con Nota de Crédito o Débito Electrónica.
  * Regla de los 30 días: Las Notas de Crédito emitidas después de 30 días calendario de la venta conllevan la restitución del precio pagado sin incluir la devolución del ITBIS.
  * Si el cliente (Receptor) lo rechaza: Requiere Nota de Crédito obligatoria.
  * Si la DGII lo rechaza: El comprobante queda anulado; debes emitir un nuevo e-CF con secuencia diferente.

5. PROCEDIMIENTOS DE CONTINGENCIA DE LA DGII (Art. 40 al 43):
- Falta de conectividad (Emisión Offline): Se generan e-CF firmados localmente. En su impresión es obligatoria la leyenda "e-CF emitido en modalidad de contingencia". Plazo máximo de 72 horas para enviarlos a la DGII tras recuperar internet.
- Imposibilidad de emisión del e-CF (Fallo Técnico): Debes facturar usando secuencias físicas de Comprobantes tradicionales no electrónicos. Este periodo no puede exceder 15 días calendario.
- Regularización: Plazo de 30 días calendario para registrar y remitir los e-CF que reemplazan las facturas manuales de contingencia, referenciando el comprobante original.
- Automatización en {product}: Si la conexión directa con DGII está inaccesible, el sistema activa automáticamente el Modo Fallback, estampando los códigos locales y leyendas correspondientes.
"""

    @classmethod
    def ask_chatbot(cls, owner_uid, message, history=None, sandbox=True):
        """Construye el prompt experto y realiza la solicitud a la API de OpenAI
        utilizando la clave provista por el propietario o la del servidor.
        """
        if history is None:
            history = []
            
        # 1. Recuperar perfil para buscar token de OpenAI personalizado
        profile = DatabaseService.get_company_profile(owner_uid)
        api_key = profile.get("openaiApiKey", "").strip()
        
        # Fallback a la clave global de .env si no hay clave personalizada
        using_global_key = False
        if not api_key:
            api_key = Config.OPENAI_API_KEY.strip()
            using_global_key = True
            
        if not api_key or api_key == "YOUR_OPENAI_API_KEY_HERE":
            return {
                "success": False,
                "message": "⚠️ **Clave de API de OpenAI no configurada.**\n\nPor favor, introduce tu clave secreta de OpenAI en el panel de **Administrar Empresa** (sección Datos del Emisor) o solicita al administrador del servidor que la agregue al archivo `.env` como `OPENAI_API_KEY`."
            }
            
        # 2. Control de límites/cuota si se utiliza la clave global del servidor
        FREE_MONTHLY_LIMIT = 50 # Límite de consultas gratuitas de cortesía por cliente al mes
        current_month = datetime.now(timezone.utc).strftime("%Y-%m") # Formato: YYYY-MM
        
        if using_global_key:
            last_reset = profile.get("chatbotLastReset", "")
            usage_count = int(profile.get("chatbotUsageCount", 0))
            
            # Reinicio mensual automático
            if last_reset != current_month:
                usage_count = 0
                profile["chatbotUsageCount"] = 0
                profile["chatbotLastReset"] = current_month
                DatabaseService.save_company_profile(owner_uid, profile)
                
            # Validar si excedió el límite mensual
            if usage_count >= FREE_MONTHLY_LIMIT:
                return {
                    "success": False,
                    "message": f"⚠️ **Límite de consultas mensuales alcanzado (Cuota del Servidor).**\n\nHaz consumido tus **{FREE_MONTHLY_LIMIT} consultas de cortesía** de este mes.\n\nPara seguir disfrutando del asistente fiscal IA de forma **ilimitada**, introduce tu propia clave de API de OpenAI en la pantalla de [Configuración de Empresa](/company/settings) o solicita una ampliación de cuota a soporte."
                }
            
        # 3. Recopilar contextos
        company_data = cls.get_company_context(owner_uid, sandbox=sandbox)
        help_kb = cls.get_help_kb()

        
        # 3. Construir el System Prompt de Guardrails Estricto
        system_prompt = f"""Eres el Asistente Virtual Inteligente de {get_product_name()} y un Experto Fiscal Senior de la República Dominicana (DGII), especializado en la Ley 32-23 de Facturación Electrónica.

TU ROL Y LIMITACIONES ABSOLUTAS:
- Debes presentarte como el Asistente Inteligente de {get_product_name()} y experto tributario dominicano.
- Solo debes responder a temas fiscales, facturación electrónica (e-CF), IT-1, RST y al uso del software {get_product_name()}.
- **BAJO NINGÚN CONCEPTO o motivo debes salir de este rol.**
- Si el usuario te hace preguntas no relacionadas (por ejemplo: "escríbeme un código de programación", "dame una receta de cocina", "quién es el presidente de Francia", "ayúdame con una tarea de historia"), debes negarte cortésmente diciendo exactamente esto o algo muy similar: "Lo siento, como asistente exclusivo de {get_product_name()} y asesor tributario de República Dominicana, solo puedo ayudarte con temas de facturación electrónica, tus datos financieros locales y regulaciones fiscales de la DGII."
- Sé claro, amigable, pedagógico (explica conceptos complejos con peras y manzanas), humilde, sumamente profesional y asertivo.
- Tus respuestas deben estar estructuradas usando formato Markdown estándar (negritas, viñetas, tablas cuando aplique) para que sean fáciles de leer en pantalla.

CONTEXTO DENTRO DEL SOFTWARE {get_product_name().upper()} DE LA EMPRESA ACTUAL:
- Nombre de la Empresa: {company_data.get('company_name')}
- RNC del Contribuyente: {company_data.get('company_rnc')}
- Correo Electrónico: {company_data.get('company_email')}
- Régimen Tributario Actual: Régimen {company_data.get('regimen_fiscal')}
- Modo de Operación: {"Pruebas / Certificación (Sandbox)" if company_data.get('sandbox_mode') else "Entorno Real (Producción)"}

RESUMEN DE DATOS DEL USUARIO ACTUAL (DESDE SU BASE DE DATOS EN FIREBASE):
* Clientes Registrados: {company_data.get('total_clients')} clientes.
  Diez clientes más recientes o importantes:
  {company_data.get('recent_clients')}

* Catálogo de Productos/Servicios: {company_data.get('total_items')} items.
  Items principales:
  {company_data.get('recent_items')}

* Ventas y Facturación Reciente:
  Ventas Acumuladas en este ambiente: RD$ {company_data.get('total_sales_amount'):,.2f}
  Facturas recientes:
  {company_data.get('recent_invoices')}
  
* Cotizaciones vigentes recientes:
  {company_data.get('recent_quotations')}

* Gastos y Egresos del Negocio:
  Gastos totales en este ambiente: RD$ {company_data.get('total_expenses_amount'):,.2f}
  Gastos deducibles válidos: RD$ {company_data.get('total_deductible_amount'):,.2f}
  Gastos registrados recientemente:
  {company_data.get('recent_expenses')}

CONOCIMIENTO OFICIAL DE NORMAS FISCALES:
{help_kb}

Instrucción de Respuesta:
Usa la información de la base de datos del cliente provista arriba para responder a preguntas personales sobre su negocio (ej: "¿Cuánto he facturado?", "¿Quiénes son mis clientes?", "¿Qué gastos registré?"). Usa la sección de conocimiento para dar consejos de retenciones, límites de RST (tope RD$ 12.06M para 2026), deducibilidad y contingencia.
"""

        # 4. Formatear historial y mensajes para la API
        api_messages = [{"role": "system", "content": system_prompt}]
        
        # Limitar historial para no saturar tokens (últimos 8 mensajes)
        for chat in history[-8:]:
            api_messages.append({"role": chat.get("role"), "content": chat.get("content")})
            
        api_messages.append({"role": "user", "content": message})
        
        # 5. Ejecutar la llamada HTTP a OpenAI
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": "gpt-4o-mini",  # Modelo rápido, altamente capaz y económico
            "messages": api_messages,
            "temperature": 0.3,      # Mantenerlo estructurado y con baja variabilidad
            "max_tokens": 800
        }
        
        try:
            url = "https://api.openai.com/v1/chat/completions"
            response = requests.post(url, headers=headers, json=payload, timeout=20)
            
            if response.status_code == 200:
                res_data = response.json()
                assistant_reply = res_data["choices"][0]["message"]["content"]
                
                # Incrementar cuota de consumo si usó la clave global del servidor
                if using_global_key:
                    try:
                        profile["chatbotUsageCount"] = int(profile.get("chatbotUsageCount", 0)) + 1
                        DatabaseService.save_company_profile(owner_uid, profile)
                    except Exception as ex:
                        print(f"⚠️ Error al guardar incremento de cuota en Firestore: {ex}")
                        
                return {
                    "success": True,
                    "message": assistant_reply
                }
            else:
                err_json = {}
                try:
                    err_json = response.json()
                except:
                    pass
                err_msg = err_json.get("error", {}).get("message", f"Código HTTP: {response.status_code}")
                return {
                    "success": False,
                    "message": f"❌ **Error en la API de OpenAI:**\n\n{err_msg}"
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ **Error de conexión con el servidor de inteligencia artificial:**\n\n{str(e)}"
            }
