FROM python:3.11-slim

# Evitar prompts durante la instalación de paquetes
ENV DEBIAN_FRONTEND=noninteractive

# Instalar librerías del sistema necesarias para WeasyPrint (PDFs)
RUN apt-get update && apt-get install -y \
    libpango-1.0-0 \
    libharfbuzz0b \
    libpangoft2-1.0-0 \
    libffi-dev \
    libjpeg-dev \
    libopenjp2-7-dev \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar requerimientos e instalar (aprovechando caché de Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código de la aplicación
COPY . .

# Comando de arranque para Cloud Run
# Cloud Run por defecto inyecta la variable de entorno $PORT (usualmente 8080)
# WEB_CONCURRENCY controla número de workers (default: 4)
CMD exec gunicorn --bind :$PORT --workers ${WEB_CONCURRENCY:-4} --threads 8 --timeout 0 "app:create_app()"
