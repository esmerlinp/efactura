# app/services/notifications.py
import os
import smtplib
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime, timedelta, timezone
from flask import current_app
from app.services.db_service import DatabaseService
from app.brand import get_product_name

class NotificationService:
    @classmethod
    def send_cxc_reminder(cls, owner_uid, invoice, recipient_contact, method='email', sandbox=True, portal_url="", custom_message=None):
        """
        Envía un recordatorio de pago (vía email o WhatsApp) y registra la interacción en el historial del cliente.
        """
        company = DatabaseService.get_company_profile(owner_uid) or {}
        company_name = company.get("tradeName") or company.get("companyName") or f"{get_product_name()} Proveedor"
        
        client_id = invoice.get("clientId")
        if not client_id:
            return False, "La factura no tiene un cliente asociado."
            
        remaining_balance = float(invoice.get("remainingBalance", invoice.get("netPayable", 0.0)))
        invoice_number = invoice.get("invoiceNumber", f"ID: {invoice.get('id')}")
        due_date = invoice.get("dueDate", "")
        
        # Construir URL del portal si no viene especificado
        if not portal_url:
            from flask import request
            try:
                base_url = request.host_url.rstrip('/')
            except Exception:
                base_url = os.environ.get("PORTAL_BASE_URL", "http://localhost:5001").rstrip('/')
            from app.utils.security import generate_portal_token
            token = generate_portal_token(owner_uid, client_id, sandbox=sandbox)
            portal_url = f"{base_url}/portal/p/{token}"

        client_pin = ""
        try:
            clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
            client_obj = next((c for c in clients if c['id'] == client_id), None)
            if client_obj:
                client_pin = client_obj.get('accessPin', '')
        except Exception:
            pass

        if method == 'email':
            # Configuración SMTP
            smtp_server = current_app.config.get("SMTP_SERVER", "smtp.gmail.com")
            smtp_port = int(current_app.config.get("SMTP_PORT", 587))
            smtp_user = current_app.config.get("SMTP_USER", "")
            smtp_password = current_app.config.get("SMTP_PASSWORD", "")
            
            if not smtp_user or not smtp_password:
                # Si no está configurado, simulamos el envío en sandbox para no bloquear el flujo de desarrollo
                if sandbox:
                    print(f"⚠️ SMTP no configurado. Simulando envío de email a {recipient_contact}...")
                    cls._record_interaction(owner_uid, client_id, "Email", 
                                            f"Recordatorio de Pago enviado (Email Simulado)",
                                            f"Simulación de envío para factura {invoice_number} al correo {recipient_contact}. Balance pendiente: RD$ {remaining_balance:,.2f}.\nContenido custom: {custom_message}\nClave de acceso: {client_pin}", 
                                            sandbox=sandbox)
                    return True, f"Simulado: Recordatorio enviado por correo a {recipient_contact} (SMTP no configurado)."
                return False, "Servidor de correo SMTP no configurado en los ajustes de la aplicación."
                
            try:
                brand_color = company.get('colorMarca', '#10b981')
                logo_url = company.get('logoUrl', '')
                logo_html = f'<img src="{logo_url}" alt="Logo" style="max-height: 60px; margin-bottom: 15px;"><br>' if logo_url else ''
                # Construir el correo HTML
                msg = MIMEMultipart('alternative')
                msg["Subject"] = f"⚠️ Recordatorio de Pago - Factura {invoice_number} - {company_name}"
                msg["From"] = formataddr((company_name, smtp_user))
                msg["To"] = recipient_contact
                
                content_html = custom_message.replace("\n", "<br>") if custom_message else f"Le escribimos para recordarle que tiene un balance pendiente de pago correspondiente a la factura <strong>{invoice_number}</strong>."
                
                html_body = f"""
                <html>
                <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                    <div style="text-align: center; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 2px solid {brand_color};">
                        {logo_html}
                        <h2 style="color: {brand_color}; margin: 0;">Recordatorio de Pago Pendiente</h2>
                        <p style="color: #666; margin: 4px 0 0 0;">{company_name}</p>
                    </div>
                    
                    <p>Estimado/a cliente,</p>
                    
                    <p>{content_html}</p>
                    
                    <div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 16px; margin: 20px 0;">
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr>
                                <td style="padding: 6px 0; color: #6b7280; font-size: 0.9rem;">Factura N°:</td>
                                <td style="padding: 6px 0; font-weight: bold; text-align: right;">{invoice_number}</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #6b7280; font-size: 0.9rem;">Fecha de Emisión:</td>
                                <td style="padding: 6px 0; text-align: right;">{invoice.get('issueDate', '')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #6b7280; font-size: 0.9rem;">Fecha de Vencimiento:</td>
                                <td style="padding: 6px 0; color: #ef4444; font-weight: bold; text-align: right;">{due_date}</td>
                            </tr>
                            <tr>
                                <td style="padding: 12px 0 6px 0; border-top: 1px solid #e5e7eb; color: #6b7280; font-size: 0.9rem;">Total Facturado:</td>
                                <td style="padding: 12px 0 6px 0; border-top: 1px solid #e5e7eb; text-align: right;">RD$ {float(invoice.get('netPayable', 0.0)):,.2f}</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: {brand_color}; font-weight: bold;">Balance Pendiente:</td>
                                <td style="padding: 6px 0; color: {brand_color}; font-weight: bold; font-size: 1.1rem; text-align: right;">RD$ {remaining_balance:,.2f}</td>
                            </tr>
                        </table>
                    </div>
                    
                    <p style="text-align: center; margin: 28px 0 10px 0;">
                        <a href="{portal_url}" style="background: {brand_color}; color: white; text-decoration: none; padding: 12px 30px; border-radius: 6px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);">
                            Pagar o Ver Detalle en Línea
                        </a>
                    </p>
                    <div style="text-align: center; font-size: 0.85rem; color: #475569; margin-bottom: 24px;">
                        <strong>Clave de Acceso Autoservicio:</strong> <span style="font-family: monospace; font-size: 0.95rem; background: #f1f5f9; padding: 3px 8px; border-radius: 4px; font-weight: bold;">{client_pin}</span>
                    </div>
                    
                    <p style="font-size: 0.85rem; color: #6b7280; text-align: center;">
                        Si ya realizó este pago, por favor ignore este mensaje o envíenos el comprobante respondiendo a este correo.
                    </p>
                    
                    <hr style="border: 0; border-top: 1px solid #e5e7eb; margin: 24px 0;">
                    
                    <div style="font-size: 0.8rem; color: #9ca3af; text-align: center;">
                        Enviado de forma automática por la plataforma {get_product_name()}.
                    </div>
                </body>
                </html>
                """
                
                msg.attach(MIMEText(html_body, 'html'))
                
                with smtplib.SMTP(smtp_server, smtp_port) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                    server.sendmail(smtp_user, recipient_contact, msg.as_string())
                    
                cls._record_interaction(owner_uid, client_id, "Email", 
                                        f"Recordatorio de Pago enviado (Email)",
                                        f"Enviado recordatorio para factura {invoice_number} al correo {recipient_contact}. Balance pendiente: RD$ {remaining_balance:,.2f}.", 
                                        sandbox=sandbox)
                return True, f"Recordatorio enviado exitosamente por correo a {recipient_contact}."
            except Exception as e:
                print(f"⚠️ Error al enviar email: {e}")
                return False, f"Fallo al enviar correo: {str(e)}"
                
        elif method == 'whatsapp':
            whatsapp_msg = custom_message if custom_message else (
                f"Hola, le escribimos de *{company_name}* para recordarle que la factura *{invoice_number}* "
                f"tiene un balance pendiente de *RD$ {remaining_balance:,.2f}* con vencimiento el {due_date}. "
                f"Puede ver el detalle y realizar su pago en línea a través del portal de autogestión: {portal_url}"
            )
            
            print(f"📱 [WhatsApp API Simulación] Enviando a {recipient_contact}: {whatsapp_msg}")
            
            cls._record_interaction(owner_uid, client_id, "WhatsApp", 
                                    f"Recordatorio de Pago enviado (WhatsApp)",
                                    f"Enviado recordatorio para factura {invoice_number} al número {recipient_contact} vía WhatsApp.\nContenido: {whatsapp_msg}", 
                                    sandbox=sandbox)
            return True, f"Recordatorio enviado por WhatsApp a {recipient_contact} (API Simulación)."
            
        return False, "Método de envío no válido."

    @classmethod
    def _record_interaction(cls, owner_uid, client_id, method, title, content, sandbox=True):
        """Registra la comunicación en el CRM del cliente."""
        interaction_id = str(uuid.uuid4())
        interaction_dict = {
            "type": method,
            "title": title,
            "content": content,
            "date": datetime.now(timezone.utc).isoformat(),
            "completed": True,
            "registeredBy": "Sistema CxC"
        }
        try:
            DatabaseService.save_client_interaction(owner_uid, client_id, interaction_id, interaction_dict, sandbox=sandbox)
        except Exception as e:
            print(f"⚠️ Error al guardar interacción del recordatorio: {e}")

    @classmethod
    def process_automatic_reminders(cls, owner_uid, sandbox=True):
        """
        Escanea y envía automáticamente recordatorios de pago para facturas pendientes y vencidas
        según la configuración de la empresa y del cliente.
        """
        company = DatabaseService.get_company_profile(owner_uid) or {}
        if not company.get("autoRemindersEnabled", False):
            return 0

        # Evitar doble ejecución el mismo día
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if company.get("autoRemindersLastRun") == today_str:
            return 0

        # Obtener facturas reales
        invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, quotations_only=False)
        cxc_invoices = []
        for inv in invoices:
            status = inv.get("status")
            if status in ["Emitida", "Parcialmente Cobrada", "Vencida"]:
                client_name = inv.get("clientName", "")
                client_id = inv.get("clientId", "")
                if not client_id or "consumidor final" in client_name.lower():
                    continue
                cxc_invoices.append(inv)

        if not cxc_invoices:
            return 0

        # Obtener todos los clientes para revisar si están silenciados
        clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
        muted_clients = {c["id"] for c in clients if c.get("disableAutoReminders")}

        try:
            days_offset = int(company.get("autoRemindersDays", 0))
        except ValueError:
            days_offset = 0

        method = company.get("autoRemindersMethod", "email") # email o whatsapp
        tone = company.get("autoRemindersTone", "formal")

        # Calcular fecha objetivo: due_date = today - offset
        target_date = (datetime.now(timezone.utc) - timedelta(days=days_offset)).strftime("%Y-%m-%d")

        sent_count = 0
        from app.services.ai_service import AIService
        
        for inv in cxc_invoices:
            client_id = inv.get("clientId")
            if client_id in muted_clients:
                continue

            inv_due = inv.get("dueDate", "")[:10]
            if inv_due == target_date:
                # Comprobar si ya se envió recordatorio para esta factura hoy
                interactions = DatabaseService.get_client_interactions(owner_uid, client_id, sandbox=sandbox)
                already_sent = False
                for inter in interactions:
                    inter_date = inter.get("createdAt", inter.get("date", ""))[:10]
                    if inter_date == today_str and f"factura {inv.get('invoiceNumber')}" in inter.get("content", "").lower():
                        already_sent = True
                        break
                
                if already_sent:
                    continue

                # Generar mensaje con IA
                client_name = inv.get("clientName", "Cliente")
                remaining_balance = float(inv.get("remainingBalance", inv.get("netPayable", 0.0)))
                custom_message = None
                try:
                    custom_message = AIService.draft_collection_message(
                        owner_uid=owner_uid,
                        client_name=client_name,
                        amount=remaining_balance,
                        due_date=inv.get("dueDate"),
                        status=inv.get("status"),
                        tone=tone
                    )
                except Exception as e:
                    print(f"⚠️ Error al redactar mensaje con IA: {e}")

                recipient = inv.get("clientEmail") if method == "email" else inv.get("clientPhone")
                if not recipient:
                    continue

                success, msg = cls.send_cxc_reminder(
                    owner_uid=owner_uid,
                    invoice=inv,
                    recipient_contact=recipient,
                    method=method,
                    sandbox=sandbox,
                    custom_message=custom_message
                )
                if success:
                    sent_count += 1

        # Actualizar fecha de última ejecución
        company["autoRemindersLastRun"] = today_str
        DatabaseService.save_company_profile(owner_uid, company)
        return sent_count

    @classmethod
    def send_mention_notification(cls, recipient_email, recipient_name, commenter_name, comment_snippet, doc_number, doc_url, issuer_company_name=None, sandbox=True, brand_color="#10b981", logo_url=""):
        """Envía un correo electrónico de notificación cuando un usuario es tagueado en un comentario."""
        issuer_company_name = issuer_company_name or get_product_name()
        smtp_server = current_app.config.get("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(current_app.config.get("SMTP_PORT", 587))
        smtp_user = current_app.config.get("SMTP_USER", "")
        smtp_password = current_app.config.get("SMTP_PASSWORD", "")
        
        if not smtp_user or not smtp_password:
            # Si no está configurado, simulamos el envío en sandbox para no bloquear el flujo de desarrollo
            if sandbox:
                print(f"⚠️ [SMTP no configurado] Simulando email de mención a {recipient_email} ({recipient_name}): {commenter_name} te mencionó en {doc_number} ({issuer_company_name})")
                return True, f"Simulado: Notificación de mención enviada a {recipient_email}."
            return False, "Servidor de correo SMTP no configurado en los ajustes de la aplicación."
            
        try:
            # Construir el correo HTML
            msg = MIMEMultipart('alternative')
            msg["Subject"] = f"💬 Te mencionaron en un comentario — {doc_number}"
            msg["From"] = formataddr((get_product_name(), smtp_user))
            msg["To"] = recipient_email
            
            logo_html = f'<img src="{logo_url}" alt="Logo" style="max-height: 50px; margin-bottom: 15px;"><br>' if logo_url else ''
            
            html_body = f"""
            <html>
            <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                <div style="text-align: center; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 2px solid {brand_color};">
                    {logo_html}
                    <h2 style="color: {brand_color}; margin: 0;">Nueva Mención</h2>
                    <p style="color: #666; margin: 4px 0 0 0;">Plataforma {get_product_name()} · <strong>{issuer_company_name or get_product_name()}</strong></p>
                </div>
                
                <p>Hola <strong>{recipient_name}</strong>,</p>
                
                <p><strong>{commenter_name}</strong> te ha mencionado en un comentario en el documento <strong>{doc_number}</strong>:</p>
                
                <div style="background-color: #f3f4f6; border-left: 4px solid {brand_color}; border-radius: 4px; padding: 16px; margin: 20px 0; font-style: italic; color: #4b5563;">
                    "{comment_snippet}"
                </div>
                
                <p style="text-align: center; margin: 28px 0;">
                    <a href="{doc_url}" style="background: {brand_color}; color: white; text-decoration: none; padding: 12px 30px; border-radius: 6px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);">
                        Ver Comentario y Documento
                    </a>
                </p>
                
                <hr style="border: 0; border-top: 1px solid #e5e7eb; margin: 24px 0;">
                
                <div style="font-size: 0.8rem; color: #9ca3af; text-align: center;">
                    Enviado de forma automática por la plataforma {get_product_name()}.
                </div>
            </body>
            </html>
            """
            
            msg.attach(MIMEText(html_body, 'html'))
            
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, recipient_email, msg.as_string())
                
            return True, "Correo enviado correctamente."
        except Exception as e:
            print(f"⚠️ Error al enviar email de mención: {e}")
            return False, str(e)



    @classmethod
    def send_expense_assignment_notification(cls, recipient_email, recipient_name, expense, owner_uid, sandbox=True):
        """Envía un correo electrónico notificando a un usuario que se le ha asignado un gasto para revisión/aprobación."""
        company = DatabaseService.get_company_profile(owner_uid) or {}
        company_name = company.get("tradeName") or company.get("companyName") or f"{get_product_name()} Proveedor"
        brand_color = company.get('colorMarca', '#10b981')
        logo_url = company.get('logoUrl', '')
        
        smtp_server = current_app.config.get("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(current_app.config.get("SMTP_PORT", 587))
        smtp_user = current_app.config.get("SMTP_USER", "")
        smtp_password = current_app.config.get("SMTP_PASSWORD", "")
        
        if not smtp_user or not smtp_password:
            if sandbox:
                print(f"⚠️ [SMTP no configurado] Simulando email de asignación de gasto a {recipient_email} ({recipient_name})")
                return True, f"Simulado: Notificación enviada a {recipient_email}."
            return False, "Servidor de correo SMTP no configurado."
            
        try:
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            
            msg = MIMEMultipart('alternative')
            msg["Subject"] = f"📋 Gasto Pendiente de Aprobación: {expense.get('concept', 'Gasto Interno')}"
            msg["From"] = formataddr((company_name, smtp_user))
            msg["To"] = recipient_email
            
            logo_html = f'<img src="{logo_url}" alt="Logo" style="max-height: 50px; margin-bottom: 15px;"><br>' if logo_url else ''
            
            from flask import request
            try:
                base_url = request.host_url.rstrip('/')
            except Exception:
                base_url = os.environ.get("PORTAL_BASE_URL", "http://localhost:5001").rstrip('/')
                
            expense_url = f"{base_url}/expenses"
            
            html_body = f"""
            <html>
            <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                <div style="text-align: center; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 2px solid {brand_color};">
                    {logo_html}
                    <h2 style="color: {brand_color}; margin: 0;">Asignación de Aprobación</h2>
                    <p style="color: #666; margin: 4px 0 0 0;">Plataforma {get_product_name()} · <strong>{company_name}</strong></p>
                </div>
                
                <p>Hola <strong>{recipient_name}</strong>,</p>
                
                <p>Se te ha asignado un nuevo gasto interno para tu revisión y aprobación en el sistema:</p>
                
                <div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 16px; margin: 20px 0;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 6px 0; color: #6b7280; font-size: 0.9rem;">Concepto:</td>
                            <td style="padding: 6px 0; font-weight: bold; text-align: right;">{expense.get('concept', '')}</td>
                        </tr>
                        <tr>
                            <td style="padding: 6px 0; color: #6b7280; font-size: 0.9rem;">Proveedor:</td>
                            <td style="padding: 6px 0; text-align: right;">{expense.get('providerName', 'No especificado')}</td>
                        </tr>
                        <tr>
                            <td style="padding: 6px 0; color: #6b7280; font-size: 0.9rem;">Fecha de Comprobante:</td>
                            <td style="padding: 6px 0; text-align: right;">{expense.get('date', '')}</td>
                        </tr>
                        <tr>
                            <td style="padding: 12px 0 6px 0; border-top: 1px solid #e5e7eb; color: #6b7280; font-size: 0.9rem;">Monto Total:</td>
                            <td style="padding: 12px 0 6px 0; border-top: 1px solid #e5e7eb; font-weight: bold; font-size: 1.1rem; color: {brand_color}; text-align: right;">RD$ {float(expense.get('amount', 0.0)):,.2f}</td>
                        </tr>
                    </table>
                </div>
                
                <p style="text-align: center; margin: 28px 0;">
                    <a href="{expense_url}" style="background: {brand_color}; color: white; text-decoration: none; padding: 12px 30px; border-radius: 6px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);">
                        Ver y Aprobar Gasto
                    </a>
                </p>
                
                <hr style="border: 0; border-top: 1px solid #e5e7eb; margin: 24px 0;">
                
                <div style="font-size: 0.8rem; color: #9ca3af; text-align: center;">
                    Enviado de forma automática por la plataforma {get_product_name()}.
                </div>
            </body>
            </html>
            """
            
            msg.attach(MIMEText(html_body, 'html'))
            
            import smtplib
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, recipient_email, msg.as_string())
                
            return True, "Correo enviado correctamente."
        except Exception as e:
            print(f"⚠️ Error al enviar email de asignación: {e}")
            return False, str(e)

    @classmethod
    def send_portal_action_notification(cls, owner_uid, action, document_type, document_number, client_name, client_rnc, signed_at, recipient_email, document_url="", sandbox=True):
        """
        Notifica al responsable (owner/creador) cuando un cliente firma o rechaza
        una cotización o contrato desde el portal de autogestión, o cuando reporta un pago.
        
        action: 'firmada' | 'rechazada' | 'pago_reportado'
        document_type: 'Cotización' | 'Contrato' | 'Factura'
        """
        company = DatabaseService.get_company_profile(owner_uid) or {}
        company_name = company.get("tradeName") or company.get("companyName") or get_product_name()
        brand_color = company.get('colorMarca', '#10b981')
        logo_url = company.get('logoUrl', '')

        smtp_server = current_app.config.get("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(current_app.config.get("SMTP_PORT", 587))
        smtp_user = current_app.config.get("SMTP_USER", "")
        smtp_password = current_app.config.get("SMTP_PASSWORD", "")

        if not smtp_user or not smtp_password:
            print(f"⚠️ [Portal Notification] SMTP no configurado. No se notificó a {recipient_email}.")
            return False, "SMTP no configurado."

        if action == 'pago_reportado':
            icon = "💰"
            status_label = "PAGO REPORTADO (En revisión)"
            status_color = "#d97706"
            status_bg = "rgba(245, 158, 11, 0.07)"
            status_border = "rgba(245, 158, 11, 0.3)"
            body_text = f"<p>El cliente ha cargado un comprobante de pago para este documento. El estado de la factura ha cambiado a <strong>Revisión de Pago</strong> y requiere su validación en la sección de cuentas por cobrar para ser aprobado y aplicado.</p>"
        else:
            is_approved = action == 'firmada'
            icon = "✅" if is_approved else "❌"
            status_label = "APROBADA y FIRMADA" if is_approved else "RECHAZADA"
            status_color = "#059669" if is_approved else "#dc2626"
            status_bg = "rgba(5, 150, 105, 0.07)" if is_approved else "rgba(220, 38, 38, 0.07)"
            status_border = "rgba(5, 150, 105, 0.3)" if is_approved else "rgba(220, 38, 38, 0.3)"
            body_text = "<p>La firma electrónica ha sido validada con el certificado digital del cliente. El documento ya está disponible en el sistema para que proceda con los siguientes pasos.</p>" if is_approved else "<p>El cliente ha indicado que no desea proceder con esta propuesta. Se recomienda contactarle para conocer los motivos y ofrecer una alternativa.</p>"

        logo_html = f'<img src="{logo_url}" alt="Logo" style="max-height: 60px; margin-bottom: 15px;"><br>' if logo_url else ''
        doc_link_html = f'<p style="text-align: center; margin: 28px 0;"><a href="{document_url}" style="background: {brand_color}; color: white; text-decoration: none; padding: 12px 30px; border-radius: 6px; font-weight: bold; display: inline-block;">Ver {document_type} en el Sistema</a></p>' if document_url else ''

        try:
            msg = MIMEMultipart('alternative')
            msg["Subject"] = f"{icon} {document_type} {status_label} por el cliente — {document_number}"
            msg["From"] = formataddr((company_name, smtp_user))
            msg["To"] = recipient_email

            html_body = f"""
            <html>
            <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                <div style="text-align: center; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 2px solid {brand_color};">
                    {logo_html}
                    <h2 style="color: {brand_color}; margin: 0;">Notificación del Portal de Clientes</h2>
                    <p style="color: #666; margin: 4px 0 0 0;">{company_name}</p>
                </div>

                <p>Le informamos que el cliente <strong>{client_name}</strong> (RNC/Cédula: <code>{client_rnc}</code>) ha realizado una acción en su portal de autogestión:</p>

                <div style="background: {status_bg}; border: 1px solid {status_border}; border-radius: 8px; padding: 20px; margin: 20px 0; text-align: center;">
                    <div style="font-size: 2rem; margin-bottom: 8px;">{icon}</div>
                    <div style="font-size: 1.15rem; font-weight: bold; color: {status_color};">{document_type} {status_label}</div>
                    <div style="color: #475569; margin-top: 6px; font-size: 0.9rem;">Documento: <strong>{document_number}</strong></div>
                    <div style="color: #94a3b8; margin-top: 4px; font-size: 0.8rem;">Fecha y hora: {signed_at}</div>
                </div>

                {body_text}

                {doc_link_html}

                <hr style="border: 0; border-top: 1px solid #e5e7eb; margin: 24px 0;">
                <div style="font-size: 0.8rem; color: #9ca3af; text-align: center;">
                    Notificación automática del sistema {get_product_name()} · Portal de Autogestión de Clientes
                </div>
            </body>
            </html>
            """

            msg.attach(MIMEText(html_body, 'html'))

            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, recipient_email, msg.as_string())

            print(f"✅ [Portal Notification] Email enviado a {recipient_email}: {document_type} {status_label} — {document_number}")
            return True, "Notificación enviada."
        except Exception as e:
            print(f"⚠️ [Portal Notification] Error al enviar email: {e}")
            return False, str(e)

    @classmethod
    def send_client_payment_notification(cls, owner_uid, action, invoice, client_email, client_name, sandbox=True, rejection_reason=""):
        """
        Notifica al cliente por email cuando su comprobante de pago fue aprobado o rechazado.
        action: 'aprobado' | 'rechazado'
        """
        company = DatabaseService.get_company_profile(owner_uid) or {}
        company_name = company.get("tradeName") or company.get("companyName") or get_product_name()
        brand_color = company.get('colorMarca', '#10b981')
        logo_url = company.get('logoUrl', '')

        smtp_server = current_app.config.get("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(current_app.config.get("SMTP_PORT", 587))
        smtp_user = current_app.config.get("SMTP_USER", "")
        smtp_password = current_app.config.get("SMTP_PASSWORD", "")

        invoice_number = invoice.get("invoiceNumber", f"ID: {invoice.get('id', '')}")

        client_pin = ""
        client_id = invoice.get('clientId')
        if client_id:
            try:
                clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
                client_obj = next((c for c in clients if c['id'] == client_id), None)
                if client_obj:
                    client_pin = client_obj.get('accessPin', '')
            except Exception:
                pass

        if not smtp_user or not smtp_password:
            if sandbox:
                print(f"⚠️ [Cliente Pago] SMTP no configurado. Simulando email a {client_email}. Clave: {client_pin}")
                return True, "Simulado: Notificación enviada al cliente."
            return False, "SMTP no configurado."

        portal_link = ""
        from flask import request
        try:
            base_url = request.host_url.rstrip('/')
        except Exception:
            base_url = os.environ.get("PORTAL_BASE_URL", "http://localhost:5001").rstrip('/')
        
        if client_id:
            from app.utils.security import generate_portal_token
            token = generate_portal_token(owner_uid, client_id, sandbox=sandbox)
            portal_link = f"{base_url}/portal/p/{token}"

        is_approved = action == 'aprobado'
        icon = "✅" if is_approved else "❌"
        subject = f"{icon} Tu pago fue {'aprobado' if is_approved else 'rechazado'} — Factura {invoice_number}"
        status_color = "#059669" if is_approved else "#dc2626"
        status_bg = "rgba(5, 150, 105, 0.07)" if is_approved else "rgba(220, 38, 38, 0.07)"
        status_border = "rgba(5, 150, 105, 0.3)" if is_approved else "rgba(220, 38, 38, 0.3)"
        status_label = "PAGO APROBADO" if is_approved else "PAGO RECHAZADO"

        if is_approved:
            body_text = f"""
            <p>Tu comprobante de pago para la factura <strong>{invoice_number}</strong> ha sido revisado y <strong style="color: {status_color};">aprobado</strong> por nuestro equipo.</p>
            <p>El pago ya ha sido registrado en nuestro sistema. Gracias por tu puntualidad.</p>
            """
        else:
            reason_html = f'<p><strong>Motivo:</strong> {rejection_reason}</p>' if rejection_reason else ''
            body_text = f"""
            <p>Lamentamos informarte que el comprobante de pago para la factura <strong>{invoice_number}</strong> no pudo ser procesado.</p>
            {reason_html}
            <p>Por favor, contáctanos o carga un nuevo comprobante para continuar con tu proceso de pago.</p>
            """

        portal_html = ""
        if portal_link:
            portal_html = f"""
                <p style="text-align: center; margin: 28px 0 10px 0;">
                    <a href="{portal_link}" style="background: {brand_color}; color: white; text-decoration: none; padding: 10px 24px; border-radius: 6px; font-weight: bold; display: inline-block;">
                        Ingresar a mi Portal
                    </a>
                </p>
                <div style="text-align: center; font-size: 0.85rem; color: #475569; margin-bottom: 24px;">
                    <strong>Clave de Acceso Autoservicio:</strong> <span style="font-family: monospace; font-size: 0.95rem; background: #f1f5f9; padding: 3px 8px; border-radius: 4px; font-weight: bold;">{client_pin}</span>
                </div>
            """

        logo_html = f'<img src="{logo_url}" alt="Logo" style="max-height: 60px; margin-bottom: 15px;"><br>' if logo_url else ''

        try:
            msg = MIMEMultipart('alternative')
            msg["Subject"] = subject
            msg["From"] = formataddr((company_name, smtp_user))
            msg["To"] = client_email

            html_body = f"""
            <html>
            <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                <div style="text-align: center; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 2px solid {brand_color};">
                    {logo_html}
                    <h2 style="color: {brand_color}; margin: 0;">Estado de tu Pago</h2>
                    <p style="color: #666; margin: 4px 0 0 0;">{company_name}</p>
                </div>

                <p>Estimado/a <strong>{client_name}</strong>,</p>

                <div style="background: {status_bg}; border: 1px solid {status_border}; border-radius: 8px; padding: 20px; margin: 20px 0; text-align: center;">
                    <div style="font-size: 2.5rem; margin-bottom: 8px;">{icon}</div>
                    <div style="font-size: 1.2rem; font-weight: bold; color: {status_color};">{status_label}</div>
                    <div style="color: #475569; margin-top: 6px; font-size: 0.9rem;">Factura: <strong>{invoice_number}</strong></div>
                </div>

                {body_text}

                {portal_html}

                <hr style="border: 0; border-top: 1px solid #e5e7eb; margin: 24px 0;">
                <div style="font-size: 0.8rem; color: #9ca3af; text-align: center;">
                    Notificación automática del sistema {get_product_name()} &middot; {company_name}
                </div>
            </body>
            </html>
            """

            msg.attach(MIMEText(html_body, 'html'))

            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, client_email, msg.as_string())

            print(f"✅ [Cliente Pago] Email enviado a {client_email}: Pago {action} — {invoice_number}. Clave: {client_pin}")
            return True, "Notificación enviada al cliente."
        except Exception as e:
            print(f"⚠️ [Cliente Pago] Error al enviar email: {e}")
            return False, str(e)
