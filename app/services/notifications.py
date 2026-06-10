# app/services/notifications.py
import os
import smtplib
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from flask import current_app
from app.services.db_service import DatabaseService

class NotificationService:
    @classmethod
    def send_cxc_reminder(cls, owner_uid, invoice, recipient_contact, method='email', sandbox=True, portal_url="", custom_message=None):
        """
        Envía un recordatorio de pago (vía email o WhatsApp) y registra la interacción en el historial del cliente.
        """
        company = DatabaseService.get_company_profile(owner_uid) or {}
        company_name = company.get("tradeName") or company.get("companyName") or "e-Factura Proveedor"
        
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
            portal_url = f"{base_url}/portal/cliente/{owner_uid}/{client_id}?sandbox={'true' if sandbox else 'false'}"

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
                                            f"Simulación de envío para factura {invoice_number} al correo {recipient_contact}. Balance pendiente: RD$ {remaining_balance:,.2f}.\nContenido custom: {custom_message}", 
                                            sandbox=sandbox)
                    return True, f"Simulado: Recordatorio enviado por correo a {recipient_contact} (SMTP no configurado)."
                return False, "Servidor de correo SMTP no configurado en los ajustes de la aplicación."
                
            try:
                # Construir el correo HTML
                msg = MIMEMultipart('alternative')
                msg["Subject"] = f"⚠️ Recordatorio de Pago - Factura {invoice_number} - {company_name}"
                msg["From"] = f"{company_name} <{smtp_user}>"
                msg["To"] = recipient_contact
                
                content_html = custom_message.replace("\n", "<br>") if custom_message else f"Le escribimos para recordarle que tiene un balance pendiente de pago correspondiente a la factura <strong>{invoice_number}</strong>."
                
                html_body = f"""
                <html>
                <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                    <div style="text-align: center; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 2px solid #10b981;">
                        <h2 style="color: #10b981; margin: 0;">Recordatorio de Pago Pendiente</h2>
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
                                <td style="padding: 6px 0; color: #10b981; font-weight: bold;">Balance Pendiente:</td>
                                <td style="padding: 6px 0; color: #10b981; font-weight: bold; font-size: 1.1rem; text-align: right;">RD$ {remaining_balance:,.2f}</td>
                            </tr>
                        </table>
                    </div>
                    
                    <p style="text-align: center; margin: 28px 0;">
                        <a href="{portal_url}" style="background: linear-gradient(135deg, #10b981, #059669); color: white; text-decoration: none; padding: 12px 30px; border-radius: 6px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(16, 185, 129, 0.2);">
                            Pagar o Ver Detalle en Línea
                        </a>
                    </p>
                    
                    <p style="font-size: 0.85rem; color: #6b7280; text-align: center;">
                        Si ya realizó este pago, por favor ignore este mensaje o envíenos el comprobante respondiendo a este correo.
                    </p>
                    
                    <hr style="border: 0; border-top: 1px solid #e5e7eb; margin: 24px 0;">
                    
                    <div style="font-size: 0.8rem; color: #9ca3af; text-align: center;">
                        Enviado de forma automática por la plataforma e-Factura.
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
            "date": datetime.utcnow().isoformat(),
            "completed": True,
            "registeredBy": "Sistema CxC"
        }
        try:
            DatabaseService.save_client_interaction(owner_uid, client_id, interaction_id, interaction_dict, sandbox=sandbox)
        except Exception as e:
            print(f"⚠️ Error al guardar interacción del recordatorio: {e}")
