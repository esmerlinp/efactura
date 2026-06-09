import os
import platform

# Fix para WeasyPrint en desarrollo local con Mac (Apple Silicon / ARM64)
if platform.system() == 'Darwin':
    os.environ['DYLD_FALLBACK_LIBRARY_PATH'] = '/opt/homebrew/lib'

# app.py
from app import create_app

# Crear la aplicación Flask modularizada
app = create_app()

if __name__ == '__main__':
    # Arrancar el servidor en modo desarrollo
    app.run(debug=True, port=5001)
