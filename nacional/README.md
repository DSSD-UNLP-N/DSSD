# Sistema Nacional de Gestión de Recursos y Riesgos (versión local)

API externa de la consigna (servicio 3): catálogo de certificaciones y recursos, inventario de las
ONGs y validación de ofertas por niveles de competencia. Corre aparte de `backend/` (la app local).
SQLite en desarrollo y Postgres en la nube. Emite los JWT que la app local reenvía en sus llamadas.

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
Configurar el mismo `JWT_SECRET` y `JWT_EXPIRATION_MINUTES` en `backend/.env` y
`nacional/.env`. Después de migrar y ejecutar el seed, las cuentas de demo
(`demo1234`) y la cuenta indicada por `BONITA_SERVICE_USERNAME` /
`BONITA_SERVICE_PASSWORD` están creadas.

- Swagger: http://localhost:8002/docs
- Estado: http://localhost:8002/health

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/login` | Público: valida una cuenta y emite un JWT con usuario, rol, ONG y vencimiento |
| POST | `/ongs` | Público: registra la ONG junto con su cuenta representante y emite un JWT |
| GET | `/tipos-recurso` | JWT de cualquier rol: catálogo de recursos |
| GET | `/certificaciones` | JWT de cualquier rol: catálogo de certificaciones |
| GET | `/ongs?estado=HABILITADA` | JWT de cualquier rol: ONGs del registro |
| GET | `/ongs/{cuit}` | JWT de cualquier rol: ficha de la ONG |
| PUT | `/ongs/{cuit}/inventario` | Solo la cuenta ONG cuyo CUIT coincide con `{cuit}` |
| GET | `/recursos/disponibilidad?tipo_recurso=` | JWT de cualquier rol: disponibilidad global |
| POST | `/validaciones` | Cualquier JWT: valida cantidades y competencia; **no guarda nada** |
| POST | `/evaluaciones` | Solo el JWT de la cuenta de servicio BONITA |
| POST | `/adjudicaciones` | Solo BONITA: compromete inventario de forma atómica |
| POST | `/adjudicaciones/{referencia}/confirmar` | Solo BONITA |
| POST | `/adjudicaciones/{referencia}/liberar` | Solo BONITA |
| POST | `/adjudicaciones/resolucion` | Solo BONITA |
| POST | `/cierres` | Solo BONITA: informa el cierre y libera recursos |
| GET | `/cierres/{id}` | Solo BONITA |
| GET | `/ongs/{cuit}/cierres` | Solo BONITA |

Los endpoints protegidos exigen `Authorization: Bearer <access_token>`. La API valida firma, vencimiento,
identidad y rol contra la tabla `cuenta`. Un token ONG solo puede modificar el inventario de la ONG que tiene
asociada; los endpoints de evaluación, adjudicación y cierre exigen específicamente la cuenta BONITA.
`/health` también es público.

La app local obtiene el token Nacional durante el login (`POST /login`) y reenvía ese mismo Bearer al hacer
llamadas al catálogo y a `/validaciones`. Bonita debe autenticarse por separado: sus parámetros de proceso
`nacionalServiceUsername` y `nacionalServicePassword` se envían a `/login`, y los conectores usan el JWT devuelto
en las llamadas protegidas. El `.bos` del repositorio todavía no tiene conectores REST configurados: esa parte
debe completarse en Bonita Studio antes de considerar probado el flujo completo de Bonita.

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

Informa al sistema central que la ONG terminó una actividad y libera los recursos que tenía bloqueados.
Resta `cantidad_comprometida` (el bloqueo, servicio 4, es quien la suma). No toca `cantidad_total`.

```json
{ "cuit": "30-54666544-5", "referencia": "emergencia-12", "items": [{ "tipo_recurso": "PARAMEDICO", "cantidad": 2 }] }
```

- 201 con lo liberado y el inventario que queda (`comprometida` / `disponible`).
- 409 si se pide liberar más de lo bloqueado, si el tipo no está en el inventario, o si esa `referencia` ya se informó para la misma ONG. Si un ítem falla, no se libera ninguno.

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
  config.py    # variables de entorno (DATABASE_URL, JWT y cuenta de Bonita)
  db.py        # engine, sesión, Base
  models.py    # cuenta, ong, certificacion, tipo_recurso, inventario, cierre
  schemas.py   # entrada/salida de la API
  routers/     # catalogo, inventario, validacion, cierre
  services/    # reglas (competencia y validación), sin HTTP
  seed.py      # datos de demo (mismos CUIT que backend/)
migrations/    # Alembic
tests/
```

Plan completo: `entrega-3/plan-modelado-validacion.md`.
