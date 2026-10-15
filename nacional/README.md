# Sistema Nacional de Gestión de Recursos y Riesgos (versión local)

API externa de la consigna (servicio 3): catálogo de certificaciones y recursos, inventario de las
ONGs y validación de ofertas por niveles de competencia. Corre aparte de `backend/` (la app local).
Por ahora sin JWT, Docker ni deploy: SQLite en desarrollo, modelos portables a Postgres.

## Correr

```bash
cd nacional
pip install -r requirements-dev.txt     # sirve el venv de backend/ (mismas versiones)
alembic upgrade head
python -m app.seed                      # 3 ONGs, 4 certificaciones, 11 tipos de recurso, inventarios
uvicorn app.main:app --port 8002 --reload
```

`DATABASE_URL` (en `nacional/.env` o el entorno) por defecto es `nacional/nacional.db` (SQLite). Ojo: `backend/`
lee la misma variable; si exportás una en la terminal, la leen los dos.

- Swagger: http://localhost:8002/docs
- Estado: http://localhost:8002/health

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/tipos-recurso` | Catálogo: código, nombre, categoría, unidad, certificación requerida |
| GET | `/certificaciones` | Catálogo, con los tipos de recurso que habilita cada una |
| GET | `/ongs?estado=HABILITADA` | ONGs del registro (filtro opcional por estado) |
| GET | `/ongs/{cuit}` | Ficha: certificaciones (vigente o no), inventario y riesgo permitido por recurso |
| PUT | `/ongs/{cuit}/inventario` | Declara `cantidad_total` por tipo de recurso (upsert); 409 si queda por debajo de lo comprometido |
| GET | `/recursos/disponibilidad?tipo_recurso=` | Disponibilidad global (solo ONGs habilitadas) con desglose por ONG |
| POST | `/validaciones` | Valida cantidades y competencia; **no guarda nada** |

### `POST /validaciones`

Recibe la `gravedad` de la emergencia y ítems `{cuit, tipo_recurso, cantidad}`; los de la misma ONG y recurso se
suman. Siempre responde 200 con un resultado por (ONG, recurso):

- `alcanza`: lo pedido entra en `disponible` (= total − comprometido). Una ONG suspendida o no registrada tiene 0.
- `nivel` + `asignacion_sugerida`, sin rechazos binarios: certificación vigente con `riesgo_max` ≥ gravedad →
  **PLENA / PRINCIPAL**; vigente pero de menor riesgo → **PARCIAL / APOYO**; sin certificación, vencida u ONG no
  habilitada → **SUPERVISADA / APOYO**. Los recursos sin certificación requerida (insumos) son PLENA.

La app local (`backend/`) lo usa al publicar una oferta: suma lo que la ONG ya ofreció en sus otras convocatorias
abiertas y rechaza si no alcanza. Más adelante lo puede usar Bonita al vencer el timer.

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
  models.py    # ong, certificacion, tipo_recurso, ong_certificacion, inventario
  schemas.py   # entrada/salida de la API
  routers/     # catalogo, inventario, validacion
  services/    # reglas (competencia y validación), sin HTTP
  seed.py      # datos de demo (mismos CUIT que backend/)
migrations/    # Alembic
tests/
```

Plan completo: `entrega-3/plan-modelado-validacion.md`.
