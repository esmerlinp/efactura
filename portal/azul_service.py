import hashlib
import time
from config import Config

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
    def prepare_payment_request(company_id, amount, return_url):
        """
        Prepara los parámetros requeridos para el formulario hosted de Azul.
        """
        merchant_id = Config.AZUL_MERCHANT_ID or "MOCK_MERCHANT_123"
        order_number = f"INV-{company_id[:8]}-{int(time.time())}"
        
        params = {
            'MerchantId': merchant_id,
            'Amount': f"{amount:.2f}",
            'OrderNumber': order_number,
            'ReturnUrl': return_url,
            'Tax': "0.00",
            'CustomField1': company_id,  # Guardar el ID de la empresa aquí para reactivarla al volver
        }
        
        auth_key = Config.AZUL_AUTH1 or "mock-secret-auth-key"
        params['Signature'] = AzulService.generate_signature(params, auth_key)
        
        # Determinar URL de redirección de pasarela
        azul_url = "https://pruebas.azul.com.do/WebMerchant/" if not Config.AZUL_MERCHANT_ID else "https://pagos.azul.com.do/WebMerchant/"
        
        return {
            'url': azul_url,
            'params': params
        }

    @staticmethod
    def verify_payment_response(response_data):
        """
        Verifica la autenticidad del callback / postback de Azul y parsea los datos.
        """
        iso_code = response_data.get('IsoCode')  # '00' indica aprobado
        company_id = response_data.get('CustomField1')
        amount = float(response_data.get('Amount', 0))
        auth_code = response_data.get('AuthorizationCode', 'MOCK_AUTH_CODE')
        order_number = response_data.get('OrderNumber', '')
        response_msg = response_data.get('ResponseMessage', 'Aprobado')
        
        # En caso de no tener credenciales, se asume demo/pruebas y se confía en el IsoCode recibido
        if not Config.AZUL_MERCHANT_ID:
            return {
                'success': iso_code == '00',
                'company_id': company_id,
                'amount': amount,
                'reference': f"Azul-{auth_code}",
                'order': order_number,
                'error': None if iso_code == '00' else response_msg
            }
            
        # Validación de firma real de Azul en producción
        auth_key = Config.AZUL_AUTH2 or "mock-secret-auth-key"
        received_signature = response_data.get('Signature')
        
        # Excluir la firma de la verificación
        verify_params = {k: v for k, v in response_data.items() if k != 'Signature'}
        expected_signature = AzulService.generate_signature(verify_params, auth_key)
        
        signature_valid = (received_signature == expected_signature)
        
        if not signature_valid:
            return {
                'success': False,
                'company_id': company_id,
                'amount': amount,
                'reference': f"Azul-{auth_code}",
                'order': order_number,
                'error': "Firma de respuesta de Azul inválida."
            }
            
        return {
            'success': iso_code == '00',
            'company_id': company_id,
            'amount': amount,
            'reference': f"Azul-{auth_code}",
            'order': order_number,
            'error': None if iso_code == '00' else response_msg
        }
