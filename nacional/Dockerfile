FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el proyecto
COPY . .

# Asegurar finales de línea Unix (LF) y permisos de ejecución
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Puerto estándar (Render asigna $PORT automáticamente en runtime)
EXPOSE 8002

ENTRYPOINT ["/bin/sh", "/app/entrypoint.sh"]
