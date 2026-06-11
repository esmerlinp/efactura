import os
from dotenv import load_dotenv

# Cargar variables de entorno del archivo .env
load_dotenv(override=True)

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'efacturard_web_secret_session_key_2026')
    
    # Configuración de Firebase
    FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON', 'firebase-adminsdk.json')
    FIREBASE_STORAGE_BUCKET = os.getenv('FIREBASE_STORAGE_BUCKET', 'e-factura-c2b78.firebasestorage.app')
    FIREBASE_API_KEY = os.getenv('FIREBASE_API_KEY', 'AIzaSyDUhGH7Pa2DP5kNUJxiwEbxrfRGvpKANTc')
    FIREBASE_PROJECT_ID = os.getenv('FIREBASE_PROJECT_ID', 'e-factura-c2b78')

    
    # Integración con Alanube API (Sandbox)
    ALANUBE_SANDBOX_BASE_URL = os.getenv('ALANUBE_SANDBOX_BASE_URL', 'https://sandbox.alanube.co')
    ALANUBE_SANDBOX_TOKEN = os.getenv('ALANUBE_SANDBOX_TOKEN', 'DEVELOPMENT_SANDBOX_TOKEN')
    ALANUBE_SANDBOX_COMPANY_ID = os.getenv('ALANUBE_SANDBOX_COMPANY_ID', '132109122')
    
    # Integración con Alanube API (Producción)
    ALANUBE_PRODUCTION_BASE_URL = os.getenv('ALANUBE_PRODUCTION_BASE_URL', 'https://api.alanube.co')
    ALANUBE_PRODUCTION_TOKEN = os.getenv('ALANUBE_PRODUCTION_TOKEN', 'PRODUCTION_REAL_TOKEN')
    ALANUBE_PRODUCTION_COMPANY_ID = os.getenv('ALANUBE_PRODUCTION_COMPANY_ID', 'PRODUCTION_COMPANY_ID')
    
    # Servidor de Correo SMTP
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    SMTP_USER = os.getenv('SMTP_USER', '')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')

    # OpenAI API Key para el Chatbot
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')

    # Proveedor de Emisión de e-CF (alanube / dgii_direct)
    E_CF_PROVIDER = os.getenv('E_CF_PROVIDER', 'alanube')



