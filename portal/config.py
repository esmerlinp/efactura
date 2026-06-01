import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'default-portal-secret-key')
    PORTAL_ADMIN_USER = os.getenv('PORTAL_ADMIN_USER', 'admin')
    PORTAL_ADMIN_PASSWORD = os.getenv('PORTAL_ADMIN_PASSWORD', 'admin123')
    AZUL_MERCHANT_ID = os.getenv('AZUL_MERCHANT_ID', '')
    AZUL_AUTH1 = os.getenv('AZUL_AUTH1', '')
    AZUL_AUTH2 = os.getenv('AZUL_AUTH2', '')
