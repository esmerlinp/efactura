import base64
import json
import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

import msal
import requests

logger = logging.getLogger(__name__)


class Mailer:
    CATEGORY_MAP = {
        'invoice':      'MAIL_FROM_INVOICE',
        'receipt':      'MAIL_FROM_INVOICE',
        'notification': 'MAIL_FROM_NOTIFICATION',
        'reminder':     'MAIL_FROM_NOTIFICATION',
        'noreply':      'MAIL_FROM_NOREPLY',
        'support':      'MAIL_FROM_SUPPORT',
        'credentials':  'MAIL_FROM_NOTIFICATION',
    }

    _token_cache = {}

    @classmethod
    def send(cls, app, to_email, subject, html_body, from_name=None,
             category='notification', attachments=None):
        use_graph = app.config.get("MAIL_USE_GRAPH_API", False)

        if use_graph:
            return cls._send_via_graph(app, to_email, subject, html_body,
                                       from_name, category, attachments)
        else:
            return cls._send_via_smtp(app, to_email, subject, html_body,
                                      from_name, category, attachments)

    @classmethod
    def _send_via_smtp(cls, app, to_email, subject, html_body, from_name,
                       category, attachments):
        smtp_server = app.config.get("SMTP_SERVER", "smtp.office365.com")
        smtp_port   = int(app.config.get("SMTP_PORT", 587))
        smtp_user   = app.config.get("SMTP_USER", "")
        smtp_pass   = app.config.get("SMTP_PASSWORD", "")

        if not smtp_user or not smtp_pass:
            logger.warning("SMTP no configurado, correo no enviado a %s", to_email)
            return False

        config_key  = cls.CATEGORY_MAP.get(category, 'MAIL_FROM_NOTIFICATION')
        from_addr   = app.config.get(config_key, smtp_user)

        if not from_name:
            from app.brand import get_product_name
            from_name = get_product_name()

        msg = MIMEMultipart('alternative')
        msg["From"]    = formataddr((from_name, from_addr))
        msg["To"]      = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, 'html'))

        if attachments:
            for a in attachments:
                part = MIMEApplication(a['data'], _subtype=a.get('mimetype', 'octet-stream'))
                part.add_header('Content-Disposition', 'attachment',
                                filename=a['filename'])
                msg.attach(part)

        try:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(from_addr, to_email, msg.as_string())
            return True
        except Exception as e:
            logger.exception("Error SMTP enviando correo a %s", to_email)
            return False

    @classmethod
    def _get_graph_token(cls, app):
        tenant_id = app.config.get("MAIL_TENANT_ID", "")
        client_id = app.config.get("MAIL_CLIENT_ID", "")
        client_secret = app.config.get("MAIL_CLIENT_SECRET", "")

        cache_key = f"{tenant_id}_{client_id}"
        cached = cls._token_cache.get(cache_key)
        if cached:
            return cached

        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app_msal = msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=authority
        )
        scope = ["https://graph.microsoft.com/.default"]
        result = app_msal.acquire_token_silent(scope, account=None)
        if not result:
            result = app_msal.acquire_token_for_client(scopes=scope)

        if "access_token" not in result:
            logger.error("Error obteniendo token Graph: %s", result.get("error_description", result))
            return None

        token = result["access_token"]
        cls._token_cache[cache_key] = token
        return token

    @classmethod
    def _send_via_graph(cls, app, to_email, subject, html_body, from_name,
                        category, attachments):
        config_key = cls.CATEGORY_MAP.get(category, 'MAIL_FROM_NOTIFICATION')
        from_addr  = app.config.get(config_key, app.config.get("SMTP_USER", ""))

        if not from_name:
            from app.brand import get_product_name
            from_name = get_product_name()

        token = cls._get_graph_token(app)
        if not token:
            return False

        graph_user = app.config.get("MAIL_GRAPH_USER", from_addr)

        message = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": html_body
                },
                "from": {
                    "emailAddress": {
                        "address": from_addr,
                        "name": from_name
                    }
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": to_email
                        }
                    }
                ]
            },
            "saveToSentItems": True
        }

        if attachments:
            file_attachments = []
            for a in attachments:
                data_bytes = a['data']
                if isinstance(data_bytes, str):
                    data_bytes = data_bytes.encode('utf-8')
                b64_content = base64.b64encode(data_bytes).decode('utf-8')
                file_attachments.append({
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": a['filename'],
                    "contentBytes": b64_content
                })
            message["message"]["attachments"] = file_attachments

        url = f"https://graph.microsoft.com/v1.0/users/{graph_user}/sendMail"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        try:
            resp = requests.post(url, headers=headers, json=message, timeout=30)
            if resp.status_code in (200, 202):
                return True
            else:
                logger.error("Error Graph API %s: %s", resp.status_code, resp.text)
                return False
        except Exception as e:
            logger.exception("Error HTTP enviando vía Graph a %s", to_email)
            return False
