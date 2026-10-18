# RescueSync — backend

API de RescueSync (FastAPI + SQLAlchemy). La interfaz es la SPA de `frontend/`; acá solo hay JSON bajo `/api`.

## Correr

```bash
docker compose up -d db         # desde la raíz del repo: Postgres en :5432
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # ajustar valores si hace falta
alembic upgrade head            # crea las tablas
python -m app.seed              # datos de demo (4 perfiles, 2 ONGs, pass: demo1234)
uvicorn app.main:app --reload
```

Cambios de modelo: editar `app/models/entities.py` y correr
`alembic revision --autogenerate -m "descripcion"` + `alembic upgrade head`.

- App: http://localhost:8000/
- Swagger (automático): http://localhost:8000/docs

## Estructura

```
app/
  main.py          # crea la app y registra el router de /api
  core/            # config (variables de entorno), permisos por rol y textos
  routers/         # endpoints /api/...
  services/        # lógica de negocio; los routers solo la llaman
  models/          # modelos SQLAlchemy (T-03)
  schemas/         # esquemas Pydantic de entrada/salida
  integrations/    # clientes externos (Bonita)
```

Convención: router → service → models/integrations. Los routers no
tocan la BD ni Bonita directamente.

## Tests

```bash
pip install -r requirements-dev.txt
pytest                                   # unitarios: sin Postgres ni Bonita, ~25 s
RUN_BONITA_INTEGRATION=1 pytest -m integration   # opcional: contra Bonita Studio corriendo
```

Qué protegen:
- `test_models.py`: restricciones del esquema (únicos, CHECK de enums, cascadas, versiones de oferta).
- `test_migrations.py`: **las migraciones coinciden con los modelos**. Si falla, cambiaste
  `models/entities.py` sin correr `alembic revision --autogenerate`.
- `test_auth.py`: login JWT, registro ONG y 401/403 por rol.
- `test_bonita_client.py`: cliente de Bonita con HTTP simulado.
- `test_bonita_contract.py`: el contrato de instanciación y las tareas del `.bos`
  (`entrega-2/RescueSync.bos`) coinciden con lo que manda la app. Si cambiás el contrato en
  Studio, exportá el `.bos` y actualizá `CONTRACT_INPUTS`.

Regla: cada pieza nueva (endpoint, pantalla, servicio) entra con sus tests.

## End-to-end automático (T-14)

`scripts/e2e_ui.py` recorre el flujo completo con los cinco usuarios de demo **en un navegador real** (Playwright + Chrome) contra la
SPA React: login de los 5 perfiles, alta, lotes, publicación, ofertas versionadas de dos ONGs,
Auditor y, con `--timer`, el cierre por timer. Además de la pantalla verifica Bonita (tarea activa, variables, quién inició el caso y quién ejecutó cada tarea) y deja una
captura por paso en `scripts/capturas/` (gitignoreado). Necesita backend (`:8001`) y `npm run dev`.

```bash
python scripts/e2e_ui.py              # headless, ~1 min (50 verificaciones; 54 con --timer 90)
python scripts/e2e_ui.py --demo       # navegador visible y lento, para mostrarlo
```
Usa el Chrome instalado; sin Chrome, `playwright install chromium`.

## Login y roles (T-04)

La API Nacional (`nacional/`) emite el JWT. La app local primero verifica que el
usuario exista y est? habilitado en su base, luego hace `POST /login` a la API
Nacional con las mismas credenciales y devuelve a la SPA el token Nacional. En
ambos servicios configurar el mismo `JWT_SECRET` y `JWT_EXPIRATION_MINUTES`
(60 minutos por defecto); en producci?n, usar un secreto aleatorio fuera del
repositorio. Usuarios de demo (`python -m app.seed`, pass `demo1234`):
`operador.municipal`, `coordinador.regional`, `ong.cruzroja`, `ong.bomberos` y
`auditor`. Con `SHOW_DEMO_USERS=true` en `.env` el login los lista (solo desarrollo).

`POST /api/auth/login` devuelve `access_token`, `token_type` y `user`; verifica
las credenciales localmente y en la API Nacional. El token incluye identidad,
rol, CUIT de la ONG y vencimiento; en cada petici?n, el backend vuelve a
contrastar esos datos con la cuenta local vigente. La SPA manda el Bearer en
cada llamada al backend, y este lo reenv?a a las llamadas autenticadas al
Sistema Nacional. En Swagger UI (`/docs`), ejecutar el login con **Try it out**,
copiar `access_token` y pegarlo en **Authorize**.

La API local tambi?n ofrece `POST /login` y `POST /ongs` para compatibilidad con
el contrato Nacional; los paths `/api/auth/login` y
`/api/auth/register-ong` se mantienen para los clientes de la SPA. El registro
crea la ONG y su cuenta tanto en la API local como en la Nacional; el CUIT es
obligatorio para enlazar ambas cuentas. El login responde 401 ante credenciales
incorrectas; el registro responde 409 si el usuario o la organizaci?n ya
existen. Para rutas protegidas, enviar `Authorization: Bearer <access_token>`.

Proteger una ruta con el rol:

```python
from app.core.deps import require_role
from app.models import Rol

@router.get("/lotes")
def lotes(user: Usuario = Depends(require_role(Rol.COORDINADOR))): ...
```

Sin token o con token inv?lido: `/api/*` ? 401 JSON. Rol incorrecto: 403.
`GET /api/emergencias` est? permitido a `MUNICIPIO`, `COORDINADOR` y
`AUDITOR`; `POST /api/emergencias` solo a `MUNICIPIO`. El rol se resuelve
desde la cuenta actual en la base de datos al validar cada token. Las cuentas
`ONG` consultan exclusivamente las convocatorias abiertas mediante
`GET /api/emergencias/convocatorias/abiertas`; el listado general les responde
403. Crear lotes y publicar convocatorias corresponde a `COORDINADOR`;
borrar lotes y crear ofertas corresponde a `ONG`.
El logout es stateless: el cliente descarta el token y este deja de servir al
expirar; no se mantiene una lista de revocaci?n en el servidor.

## Sistema Nacional (nacional/)

Los lotes se cargan eligiendo un tipo de recurso del cat?logo del Sistema Nacional (`nacional/`, otra
API en `:8002`; ver su README). `app/integrations/nacional.py` es el cliente; si la API no responde,
cargar un lote da 503 y no guarda nada. Config en `.env` (`NACIONAL_*`). Los tests la reemplazan por
`FakeNacional` (`tests/conftest.py`).

Para usar la API Nacional desplegada en Render, configurar en el entorno del backend
`NACIONAL_BASE_URL` con la URL pública del servicio (por ejemplo,
`https://sistema-nacional-latest.onrender.com`) y `NACIONAL_TIMEOUT_SECONDS=60`
para permitir el arranque en frío del plan gratuito. La URL por defecto
`http://localhost:8002` solo sirve si la API Nacional corre localmente. Desplegar
también la versión Nacional que incluye `POST /login`; si esa ruta aún no existe,
el backend devuelve 502 en vez de presentarlo como caída temporal.

Tope de ofertas (`app/services/ofertas.py`): al enviar una oferta se suma lo que la ONG ofrece de cada recurso
con lo que ya ofreci? en sus otras convocatorias abiertas y se valida contra su inventario en el Sistema
Nacional (`POST /validaciones`); si no alcanza, 400 y no se guarda nada. Reducir o retirar nunca consulta a la
API. Retirar un lote = reenviar la oferta sin ?l; retirarla toda = reenviarla vac?a (versi?n sin ?tems,
`retirada: true`); el historial de versiones no se toca.

La API Nacional permite consultar el cat?logo y usar la validaci?n de ofertas con cualquier JWT;
solo la cuenta ONG vinculada al CUIT puede modificar ese inventario. Evaluaci?n, adjudicaci?n y cierre
son operaciones exclusivas de la cuenta de servicio BONITA, no del usuario interactivo. Bonita debe
recibir `nacionalServiceUsername` y `nacionalServicePassword` como par?metros del proceso, iniciar
sesi?n en la API Nacional y usar el token emitido en sus conectores. El `.bos` del repositorio todav?a
no incluye esos conectores; su configuraci?n en Bonita Studio queda pendiente.

## Bonita

`app/integrations/bonita.py` es el cliente REST (login con CSRF, instanciar,
listar tareas, setear variables). Está probado contra Studio 10.4.0.
Configuración en `.env` (`BONITA_*`).

Reglas: la app nunca completa la tarea `Cargar Ofertas de Ayuda`; guarda el
`caseId` de cada emergencia; avanza tareas logueándose como un usuario del
rol correspondiente. Si se reinicia la base de Bonita sin limpiar la de la
app, Bonita puede volver a emitir un `caseId` ya guardado. Al registrar una
emergencia, la app verifica la variable `emergenciaId` del caso nuevo y solo
libera la asociación anterior si confirma que ese ID ahora corresponde a la
emergencia nueva; si no puede comprobarlo, aborta el alta en vez de asociar el
caso incorrecto.
