import hashlib
import time

class AzulService:
    @staticmethod
    def generate_signature(params, auth_key):
        """
        Genera la firma digital SHA512 para la pasarela de pagos Azul.
        """
        if not auth_key:
            return "mock-signature"
            
        # Concatenar todos los valores de los parámetros en orden alfabético de clave
        concat_str = "".join(str(params[k]) for k in sorted(params.keys())) + auth_key
        return hashlib.sha512(concat_str.encode('utf-8')).hexdigest()

    @staticmethod
    def prepare_payment_request(company, invoice, return_url, sandbox=True, company_id=None):
        """
        Prepara los parámetros requeridos para el formulario hosted de Azul usando las credenciales de la empresa.
        """
        # Intentar cargar credenciales de la empresa
        merchant_id = company.get('azulMerchantId')
        auth_key = company.get('azulAuth1')
        
        # Modo simulación si no tiene credenciales configuradas
        is_mock = not merchant_id or not auth_key
        
        if is_mock:
            merchant_id = "MOCK_MERCHANT_123"
            auth_key = "mock-secret-auth-key"

        order_number = f"FAC-{invoice['id'][:8]}-{int(time.time())}"
        
        params = {
            'MerchantId': merchant_id,
            'Amount': f"{float(invoice.get('remainingBalance', invoice.get('netPayable', 0.0))):.2f}",
            'OrderNumber': order_number,
            'ReturnUrl': return_url,
            'Tax': "0.00",
            'CustomField1': company.get('ownerUID', ''), # owner_uid
            'CustomField2': invoice.get('id', ''), # invoice_id
            'CustomField3': 'true' if sandbox else 'false', # sandbox mode
        }
        
        params['Signature'] = AzulService.generate_signature(params, auth_key)
        
        # URL de pasarela
        azul_url = "https://pruebas.azul.com.do/WebMerchant/" if (sandbox or is_mock) else "https://pagos.azul.com.do/WebMerchant/"
        
        return {
            'url': azul_url,
            'params': params,
            'is_mock': is_mock
        }

    @staticmethod
    def verify_payment_response(company, response_data, company_id=None):
        """
        Verifica la autenticidad de la respuesta de Azul y parsea los datos.
        """
        iso_code = response_data.get('IsoCode')  # '00' indica aprobado
        owner_uid = response_data.get('CustomField1')
        invoice_id = response_data.get('CustomField2')
        is_sandbox = response_data.get('CustomField3') == 'true'
        amount = float(response_data.get('Amount', 0))
        auth_code = response_data.get('AuthorizationCode', 'MOCK_AUTH_CODE')
        order_number = response_data.get('OrderNumber', '')
        response_msg = response_data.get('ResponseMessage', 'Aprobado')
        
        merchant_id = company.get('azulMerchantId')
        auth_key = company.get('azulAuth2')
        
        is_mock = not merchant_id or not auth_key
        
        if is_mock:
            return {
                'success': iso_code == '00',
                'owner_uid': owner_uid,
                'invoice_id': invoice_id,
                'is_sandbox': is_sandbox,
                'amount': amount,
                'reference': f"Azul-{auth_code}",
                'order': order_number,
                'error': None if iso_code == '00' else response_msg
            }
            
        received_signature = response_data.get('Signature')
        
        # Excluir la firma de la verificación
        verify_params = {k: v for k, v in response_data.items() if k != 'Signature'}
        expected_signature = AzulService.generate_signature(verify_params, auth_key)
        
        signature_valid = (received_signature == expected_signature)
        
        if not signature_valid:
            return {
                'success': False,
                'owner_uid': owner_uid,
                'invoice_id': invoice_id,
                'is_sandbox': is_sandbox,
                'amount': amount,
                'reference': f"Azul-{auth_code}",
                'order': order_number,
                'error': "Firma de respuesta de Azul inválida."
            }
            
        return {
            'success': iso_code == '00',
            'owner_uid': owner_uid,
            'invoice_id': invoice_id,
            'is_sandbox': is_sandbox,
            'amount': amount,
            'reference': f"Azul-{auth_code}",
            'order': order_number,
            'error': None if iso_code == '00' else response_msg
        }
