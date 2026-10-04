# Sistema Nacional de Gestión de Recursos y Riesgos (versión local)

API externa de la consigna (servicio 3): catálogo de certificaciones y recursos, inventario de las
ONGs y validación de ofertas por niveles de competencia. Corre aparte de `backend/` (la app local).
Por ahora sin JWT, Docker ni deploy: SQLite en desarrollo, modelos portables a Postgres.

## Correr

```bash
cd nacional
pip install -r requirements-dev.txt     # sirve el venv de backend/ (mismas versiones)
alembic upgrade head
uvicorn app.main:app --port 8002 --reload
```

- Swagger: http://localhost:8002/docs
- Estado: http://localhost:8002/health

## Tests

```bash
pytest
```

## Estructura

```
app/
  main.py      # app FastAPI
  config.py    # variables de entorno (DATABASE_URL)
  db.py        # engine, sesión, Base
  models.py    # tablas
migrations/    # Alembic
tests/
```

Plan completo: `entrega-3/plan-modelado-validacion.md`.
