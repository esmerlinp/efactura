import json
import requests
import base64
from flask import current_app

PAYPAL_API_SANDBOX = "https://api-m.sandbox.paypal.com"
PAYPAL_API_LIVE = "https://api-m.paypal.com"

PAYPAL_SUPPORTED_CURRENCIES = {
    "AUD", "BRL", "CAD", "CNY", "CZK", "DKK", "EUR", "HKD", "HUF", "ILS",
    "JPY", "MYR", "MXN", "TWD", "NZD", "NOK", "PHP", "PLN", "GBP",
    "RUB", "SGD", "SEK", "CHF", "THB", "USD",
}


class PayPalService:

    @staticmethod
    def _get_base_url(sandbox=True):
        return PAYPAL_API_SANDBOX if sandbox else PAYPAL_API_LIVE

    @staticmethod
    def get_access_token(client_id, client_secret, sandbox=True):
        base_url = PayPalService._get_base_url(sandbox)
        token_url = f"{base_url}/v1/oauth2/token"

        credentials = f"{client_id}:{client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        data = {"grant_type": "client_credentials"}

        try:
            resp = requests.post(token_url, headers=headers, data=data, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("access_token")
            else:
                print(f"PayPal get_access_token error: {resp.status_code} {resp.text}")
                return None
        except requests.RequestException as e:
            print(f"PayPal get_access_token exception: {e}")
            return None

    @staticmethod
    def create_order(access_token, amount, currency, invoice_id, owner_uid, return_url, cancel_url, sandbox=True, company_id=None):
        base_url = PayPalService._get_base_url(sandbox)
        order_url = f"{base_url}/v2/checkout/orders"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": invoice_id,
                    "description": f"Factura #{invoice_id}",
                    "amount": {
                        "currency_code": currency,
                        "value": f"{amount:.2f}",
                    },
                    "custom_id": json.dumps({
                        "invoice_id": invoice_id,
                        "owner_uid": owner_uid,
                        "sandbox": sandbox,
                    }),
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "payment_method_preference": "IMMEDIATE_PAYMENT_REQUIRED",
                        "landing_page": "LOGIN",
                        "user_action": "PAY_NOW",
                        "return_url": return_url,
                        "cancel_url": cancel_url,
                    }
                }
            },
        }

        try:
            resp = requests.post(order_url, headers=headers, json=payload, timeout=30)
            if resp.status_code in (200, 201):
                data = resp.json()
                order_id = data.get("id")
                approval_url = None
                for link in data.get("links", []):
                    if link.get("rel") == "approve":
                        approval_url = link.get("href")
                        break
                if not approval_url and order_id:
                    host = "www.sandbox.paypal.com" if sandbox else "www.paypal.com"
                    approval_url = f"https://{host}/checkoutnow?token={order_id}"
                return {
                    "success": True,
                    "order_id": order_id,
                    "status": data.get("status"),
                    "approval_url": approval_url,
                }
            else:
                return {
                    "success": False,
                    "error": f"PayPal create_order: {resp.status_code} {resp.text}",
                }
        except requests.RequestException as e:
            return {"success": False, "error": f"PayPal create_order exception: {e}"}

    @staticmethod
    def capture_order(access_token, order_id, sandbox=True):
        base_url = PayPalService._get_base_url(sandbox)
        capture_url = f"{base_url}/v2/checkout/orders/{order_id}/capture"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            resp = requests.post(capture_url, headers=headers, timeout=30)
            if resp.status_code in (200, 201):
                data = resp.json()
                status = data.get("status")
                if status == "COMPLETED":
                    purchase_unit = data.get("purchase_units", [{}])[0]
                    payments = purchase_unit.get("payments", {})
                    captures = payments.get("captures", [])
                    capture_detail = captures[0] if captures else {}

                    return {
                        "success": True,
                        "status": status,
                        "capture_id": capture_detail.get("id"),
                        "order_id": order_id,
                        "amount": float(capture_detail.get("amount", {}).get("value", 0)),
                        "currency": capture_detail.get("amount", {}).get("currency_code", ""),
                        "create_time": capture_detail.get("create_time"),
                        "final_capture": capture_detail.get("final_capture", True),
                        "seller_receivable_breakdown": capture_detail.get("seller_receivable_breakdown"),
                        "full_response": data,
                    }
                else:
                    return {
                        "success": False,
                        "status": status,
                        "error": f"PayPal capture returned status: {status}",
                        "full_response": data,
                    }
            else:
                return {
                    "success": False,
                    "error": f"PayPal capture_order: {resp.status_code} {resp.text}",
                }
        except requests.RequestException as e:
            return {"success": False, "error": f"PayPal capture_order exception: {e}"}

    @staticmethod
    def get_order_details(access_token, order_id, sandbox=True):
        base_url = PayPalService._get_base_url(sandbox)
        details_url = f"{base_url}/v2/checkout/orders/{order_id}"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            resp = requests.get(details_url, headers=headers, timeout=30)
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            else:
                return {"success": False, "error": f"PayPal get_order: {resp.status_code} {resp.text}"}
        except requests.RequestException as e:
            return {"success": False, "error": f"PayPal get_order exception: {e}"}

    @staticmethod
    def verify_webhook(headers_dict, body, webhook_id, sandbox=True):
        base_url = PayPalService._get_base_url(sandbox)
        verify_url = f"{base_url}/v1/notifications/verify-webhook-signature"

        transmission_id = headers_dict.get("Paypal-Transmission-Id", "")
        transmission_time = headers_dict.get("Paypal-Transmission-Time", "")
        cert_url = headers_dict.get("Paypal-Cert-Url", "")
        auth_algo = headers_dict.get("Paypal-Auth-Algo", "")
        transmission_sig = headers_dict.get("Paypal-Transmission-Sig", "")

        payload = {
            "auth_algo": auth_algo,
            "cert_url": cert_url,
            "transmission_id": transmission_id,
            "transmission_sig": transmission_sig,
            "transmission_time": transmission_time,
            "webhook_id": webhook_id,
            "webhook_event": body if isinstance(body, dict) else json.loads(body),
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            resp = requests.post(verify_url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                return result.get("verification_status") == "SUCCESS"
            return False
        except requests.RequestException as e:
            print(f"PayPal verify_webhook exception: {e}")
            return False
