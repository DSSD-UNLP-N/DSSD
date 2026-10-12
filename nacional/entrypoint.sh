#!/bin/sh
set -e

export PYTHONPATH="/app:${PYTHONPATH}"

echo "=== Iniciando Sistema Nacional ==="

# Ejecutar migraciones
echo "Aplicando migraciones de base de datos..."
alembic upgrade head

# Cargar seed de datos inicial si está habilitado (por defecto true, es idempotente)
if [ "${RUN_SEED:-true}" = "true" ]; then
    echo "Poblando base de datos con seed inicial..."
    python -m app.seed
fi

# Render asigna la variable $PORT dinámicamente. Si no está seteada, usa 8002.
PORT="${PORT:-8002}"
echo "Iniciando servidor Uvicorn en el puerto ${PORT}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
