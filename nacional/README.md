# Sistema Nacional de Gestión de Recursos y Riesgos (versión local)

API externa de la consigna (servicio 3): catálogo de certificaciones y recursos, inventario de las
ONGs y validación de ofertas por niveles de competencia. Corre aparte de `backend/` (la app local).
SQLite en desarrollo y Postgres en la nube. JWT todavía no está: entra como `Depends` sin cambiar estos contratos.

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
| POST | `/adjudicaciones` | Compromete inventario de forma atómica e idempotente |
| POST | `/cierres` | Cierra una adjudicación (`{cuit, referencia}`) y libera exactamente lo que tenía comprometido |
| GET | `/cierres/{id}` | Un cierre ya informado |
| GET | `/ongs/{cuit}/cierres` | Cierres de una ONG |

### `POST /validaciones`

Recibe la `gravedad` de la emergencia y ítems `{cuit, tipo_recurso, cantidad}`; los de la misma ONG y recurso se
suman. Siempre responde 200 con un resultado por (ONG, recurso):

- `alcanza`: lo pedido entra en `disponible` (= total − comprometido). Una ONG suspendida o no registrada tiene 0.
- `nivel` + `asignacion_sugerida`, sin rechazos binarios: certificación vigente con `riesgo_max` ≥ gravedad →
  **PLENA / PRINCIPAL**; vigente pero de menor riesgo → **PARCIAL / APOYO**; sin certificación, vencida u ONG no
  habilitada → **SUPERVISADA / APOYO**. Los recursos sin certificación requerida (insumos) son PLENA.

La app local (`backend/`) lo usa al publicar una oferta: suma lo que la ONG ya ofreció en sus otras convocatorias
abiertas y rechaza si no alcanza. Más adelante lo puede usar Bonita al vencer el timer.

### `POST /cierres`

Informa que la ONG terminó la actividad de una adjudicación y libera lo que esa referencia tenía bloqueado. No se
indican ítems: se resta de `cantidad_comprometida` exactamente lo que la referencia comprometió (con las filas de
inventario bloqueadas) y la referencia pasa de `ADJUDICADA` a `CERRADA`. No toca `cantidad_total`.

```json
{ "cuit": "30-54666544-5", "referencia": "emg-12-r1-30-54666544-5" }
```

- 201 con lo liberado y el inventario que queda (`comprometida` / `disponible`).
- Repetirlo → 200 con el mismo cierre, sin restar de nuevo.
- 404 si la ONG o la referencia no existen, o la referencia es de otra ONG. 409 si la referencia no está `ADJUDICADA`
  (reservada sin confirmar, o liberada).

### `POST /adjudicaciones`

Recibe `referencia_id`, `ong_id`, `emergencia_id` e ítems con `inventario_id` y `cantidad`.
En PostgreSQL bloquea las filas de inventario con `SELECT ... FOR UPDATE`, valida el stock y
actualiza `cantidad_comprometida` junto con la cabecera y sus ítems en una única transacción.
La referencia es única: repetirla devuelve la adjudicación existente con 200 sin volver a
comprometer recursos; una nueva adjudicación creada responde 201 y el stock insuficiente
responde 409.
- La misma actividad se identifica con `referencia`: un segundo aviso no vuelve a descontar.

## Docker y deploy

```bash
docker build -t rescuesync-nacional ./nacional
docker run --rm -p 8002:8002 rescuesync-nacional
```

Al arrancar corre `alembic upgrade head` y el seed. `DATABASE_URL` en Postgres (`postgres://` de Render se normaliza a `postgresql+psycopg://`). Sin esa variable usa SQLite dentro del contenedor.

El blueprint está en `render.yaml` (servicio web + Postgres free). En Render: New → Blueprint, con este repo. La URL pública es la del servicio `rescuesync-nacional` (`/health` y `/docs`).

Para que un push a `main` o `dev` despliegue solo: en el servicio, Settings → Deploy Hook, y guardar esa URL como secret `RENDER_DEPLOY_HOOK_URL` del repo. El workflow `.github/workflows/deploy-nacional.yml` construye la imagen en cada PR y, si el secret existe, dispara el hook.

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
  models.py    # ong, certificacion, tipo_recurso, ong_certificacion, inventario, cierre
  schemas.py   # entrada/salida de la API
  routers/     # catalogo, inventario, validacion, cierre
  services/    # reglas (competencia y validación), sin HTTP
  seed.py      # datos de demo (mismos CUIT que backend/)
migrations/    # Alembic
tests/
```

Plan completo: `entrega-3/plan-modelado-validacion.md`.
