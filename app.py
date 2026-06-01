# app.py
from app import create_app

# Crear la aplicación Flask modularizada
app = create_app()

if __name__ == '__main__':
    # Arrancar el servidor en modo desarrollo
    app.run(debug=True, port=5001)
