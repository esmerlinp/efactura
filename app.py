import os
import platform


# Fix para WeasyPrint en desarrollo local con Mac (Apple Silicon / ARM64)
if platform.system() == 'Darwin':
    os.environ['DYLD_FALLBACK_LIBRARY_PATH'] = '/opt/homebrew/lib'
    import ctypes.util
    _orig_find_library = ctypes.util.find_library
    def _mac_find_library(name):
        res = _orig_find_library(name)
        if not res:
            for p in ['/opt/homebrew/lib', '/usr/local/lib']:
                cand = os.path.join(p, f'lib{name}.dylib')
                if os.path.exists(cand): return cand
                cand = os.path.join(p, f'{name}.dylib')
                if os.path.exists(cand): return cand
        return res
    ctypes.util.find_library = _mac_find_library

# app.py
from app import create_app

# Crear la aplicación Flask modularizada
app = create_app()

if __name__ == '__main__':
    import sys
    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() in ('true', '1', 'yes')
    port = int(os.getenv('FLASK_PORT', '5001'))
    app.run(debug=debug_mode, port=port)
