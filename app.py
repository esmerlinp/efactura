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
    import sys
    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() in ('true', '1', 'yes')
    port = int(os.getenv('FLASK_PORT', '5001'))
    app.run(debug=debug_mode, port=port)
