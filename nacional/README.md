# Sistema Nacional de Gestión de Recursos y Riesgos

API externa de la consigna (servicio 3): catálogo de certificaciones y recursos, inventario de las
ONGs, validación de ofertas por niveles de competencia, reserva y liberación de recursos. Corre aparte de `backend/` (la app local).
Desplegada en Render (https://rescuesync-nacional.onrender.com/docs); en desarrollo corre local con SQLite y en la nube con Postgres.
Emite los JWT con los que la app local y Bonita le hablan.

## Correr

```bash
cd nacional
pip install -r requirements-dev.txt     # sirve el venv de backend/ (mismas versiones)
alembic upgrade head
python -m app.seed                      # ONGs, certificaciones, tipos de recurso e inventarios de demo
uvicorn app.main:app --port 8002 --reload
```

`DATABASE_URL` (en `nacional/.env` o el entorno) por defecto es `nacional/nacional.db` (SQLite). Ojo: `backend/`
lee la misma variable; si exportás una en la terminal, la leen los dos.
`JWT_SECRET` y `JWT_EXPIRATION_MINUTES` son solo de esta API: ella firma y ella valida los tokens (la app local y Bonita
los presentan sin conocer el secreto, así que no hay que copiarlo en `backend/.env`). En desarrollo valen
`dev-only-change-me` y 60 minutos. Después de migrar y ejecutar el seed están creadas las cuentas de demo (`demo1234`) y
las dos cuentas de servicio: `BONITA_SERVICE_USERNAME` / `BONITA_SERVICE_PASSWORD` (conectores de Bonita) y
`APP_SERVICE_USERNAME` / `APP_SERVICE_PASSWORD` (la app local; en `backend/.env`: `NACIONAL_SERVICE_USERNAME` /
`NACIONAL_SERVICE_PASSWORD`). El seed vuelve a fijar la clave de las cuentas de servicio desde el entorno, así que
cambiarla y reiniciar la rota.

Con Postgres (la nube) la API **no arranca** si `JWT_SECRET`, `BONITA_SERVICE_PASSWORD` o `APP_SERVICE_PASSWORD` siguen
con el valor de ejemplo: están a la vista en el repositorio y con ellos cualquiera podría firmar un token.

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
| POST | `/evaluaciones` | Solo cuentas de servicio |
| POST | `/adjudicaciones` | Solo cuentas de servicio: compromete inventario de forma atómica |
| POST | `/adjudicaciones/{referencia}/confirmar` | Solo cuentas de servicio |
| POST | `/adjudicaciones/{referencia}/liberar` | Solo cuentas de servicio |
| POST | `/adjudicaciones/resolucion` | Solo cuentas de servicio |
| POST | `/cierres` | Solo cuentas de servicio: informa el cierre de una adjudicación (`{cuit, referencia}`) y libera exactamente lo que tenía comprometido |
| POST | `/cierres/lote` | Solo cuentas de servicio: lo mismo para varias ONGs en una llamada (`{cierres: [{cuit, referencia}]}`); todo o nada, idempotente |
| GET | `/cierres/{id}` | Solo cuentas de servicio |
| GET | `/ongs/{cuit}/cierres` | Solo cuentas de servicio |

Los endpoints protegidos exigen `Authorization: Bearer <access_token>`. La API valida firma, vencimiento,
identidad y rol contra la tabla `cuenta`. El JWT debe incluir `sub`, `username`, `rol`, `cuit`, `iat` y `exp`.
Un token ONG solo puede modificar el inventario de la ONG que tiene asociada; los endpoints de evaluación,
adjudicación y cierre exigen específicamente la cuenta BONITA.
`/health` también es público.

Hay dos cuentas de servicio (rol `BONITA`): `bonita-service`, para los conectores de Bonita, y `app-service`, para la
app local. Las personas (Municipio, Coordinador, ONG, Auditor) inician sesión en la app, no acá: la app valida sus
credenciales con su propia base y, cuando necesita al Sistema Nacional, hace `POST /login` con `app-service`. Bonita hace
lo mismo con `bonita-service`: sus parámetros de proceso `nacionalServiceUsername` y `nacionalServicePassword` van a
`/login` y el JWT devuelto se manda en las llamadas protegidas. Las cuentas de ONG (`POST /ongs`) sirven para usar esta
API directamente, por ejemplo desde Swagger.

### Reglas de entrada (todos los endpoints)

- **CUIT**: se acepta con o sin guiones y con espacios alrededor (`30546665445`, ` 30-54666544-5 `) y siempre se guarda y compara como `NN-NNNNNNNN-N`. En un cuerpo, un CUIT que no tiene 11 dígitos da **422**; en una ruta (`/ongs/{cuit}`…) da 404 como cualquier CUIT no registrado. No se controla el dígito verificador.
- **Cantidades e ids**: enteros entre 1 y 2 147 483 647 (el inventario admite 0). Las columnas son de 32 bits: pasarse daría un error de Postgres, así que se rechaza con **422**.
- **Registro (`POST /ongs`)**: el usuario solo admite letras, números, `.`, `_` y `-`; usuario y nombre de ONG son únicos sin distinguir mayúsculas (409); la contraseña no puede ser solo espacios.
- **`POST /evaluaciones`**: no repite lotes, `tipo` es `PRINCIPAL` o `APOYO`, y cada ítem ofrecido apunta a un lote del mismo pedido y de su mismo `tipo_recurso`; si no, 422 y no se reserva nada.

### `POST /validaciones`

Recibe la `gravedad` de la emergencia y ítems `{cuit, tipo_recurso, cantidad}`; los de la misma ONG y recurso se
suman. Un pedido bien formado siempre responde 200 con un resultado por (ONG, recurso); un CUIT bien formado que no está registrado no es un error, se informa en el resultado (`ong: null`):

- `alcanza`: lo pedido entra en `disponible` (= total − comprometido). Una ONG suspendida o no registrada tiene 0.
- `nivel` + `asignacion_sugerida`, sin rechazos binarios: certificación vigente con `riesgo_max` ≥ gravedad →
  **PLENA / PRINCIPAL**; vigente pero de menor riesgo → **PARCIAL / APOYO**; sin certificación, vencida u ONG no
  habilitada → **SUPERVISADA / APOYO**. Los recursos sin certificación requerida (insumos) son PLENA.

La app local (`backend/`) lo usa al publicar una oferta: suma lo que la ONG ya ofreció en sus otras convocatorias
abiertas y rechaza si no alcanza. Bonita, al vencer la ventana, usa `POST /evaluaciones`, que valida y además reserva el stock.

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

## Docker y deploy

```bash
docker build -t rescuesync-nacional ./nacional
docker run --rm -p 8002:8002 rescuesync-nacional
```

`scripts/start.sh` (el `CMD` del Dockerfile) aplica `alembic upgrade head`, corre el seed (idempotente) y levanta uvicorn en `$PORT` (Render lo
inyecta; sin él, 8002). Sin `DATABASE_URL` usa SQLite dentro del contenedor.

**El servicio de la entrega** es un Web Service de Render con runtime Docker, construido desde este repo (rama `dev`, `dockerfilePath` `./nacional/Dockerfile`,
contexto `./nacional`) y con deploy automático: cada commit a `dev` lo redespliega. Variables de entorno del servicio:

| Variable | Qué es |
|---|---|
| `DATABASE_URL` | Postgres de Render. Con el prefijo `postgres://` o `postgresql://` se normaliza a `postgresql+psycopg://`. |
| `JWT_SECRET` | Secreto con el que se firman los tokens. |
| `BONITA_SERVICE_PASSWORD` | Clave de `bonita-service`; es la que llevan los conectores del `.bos`. |
| `APP_SERVICE_PASSWORD` | Clave de `app-service`; es `NACIONAL_SERVICE_PASSWORD` en el `.env` de la app. |

Con Postgres la API no arranca si esos tres secretos quedan con el valor de ejemplo. `render.yaml` es el blueprint equivalente (servicio web + Postgres
free) para crearlo de cero con New → Blueprint: genera solo el `JWT_SECRET` y pide las dos claves. El plan gratis duerme el servicio tras 15 minutos sin
uso y la primera llamada tarda 30-60 s; abrir `/health` antes de usarlo.

`.github/workflows/deploy-nacional.yml` construye la imagen en cada PR que toca `nacional/` y, si existe el secret `RENDER_DEPLOY_HOOK_URL`,
dispara el deploy; como Render ya despliega solo desde GitHub, el hook es opcional.

Verificar un servicio desplegado (recorre los 19 endpoints y no deja datos modificados): `python scripts/verificar_despliegue.py <URL> --clave <BONITA_SERVICE_PASSWORD>`.
Con `--crear-ong` suma el registro de una ONG nueva, que sí queda en la base (la API no permite borrarla).

## Tests

```bash
pytest
```

`tests/test_concurrencia_adjudicacion.py` prueba el locking pesimista y solo corre si se define `POSTGRES_TEST_DATABASE_URL`; en CI corre
contra un Postgres real. `tests/test_documentacion.py` comprueba que la tabla de endpoints de este README coincida con las rutas de la API.

## Estructura

```
app/
  main.py      # app FastAPI
  config.py    # variables de entorno (DATABASE_URL, JWT y cuentas de servicio)
  db.py        # engine, sesión, Base
  security.py  # JWT, hash de claves y dependencias de permisos por rol
  models.py    # cuenta, ong, certificacion, tipo_recurso, inventario, adjudicación, cierre
  schemas.py   # entrada/salida de la API
  routers/     # auth, catalogo, inventario, validacion, reservas, adjudicacion, cierre
  services/    # reglas (catálogo, competencia, validación, reservas), sin HTTP
  seed.py      # datos de demo (mismos CUIT que backend/)
migrations/    # Alembic
scripts/       # start.sh (arranque del contenedor) y verificar_despliegue.py
tests/
```
