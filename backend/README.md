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
- `test_auth.py`: login, sesión y 401/403 por rol.
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

Sesión por cookie firmada (`SESSION_SECRET`). Usuarios de demo (`python -m app.seed`,
pass `demo1234`): `operador.municipal`, `coordinador.regional`, `ong.cruzroja`, `ong.bomberos`,
`auditor`. Con `SHOW_DEMO_USERS=true` en `.env` el login los lista (solo desarrollo).

Proteger una ruta con el rol:

```python
from app.core.deps import require_role
from app.models import Rol

@router.get("/lotes")
def lotes(user: Usuario = Depends(require_role(Rol.COORDINADOR))): ...
```

Sin sesión: páginas → redirige a `/login`; `/api/*` → 401 JSON. Rol incorrecto: 403.
Para sumar una pantalla al menú de un perfil, poner su ruta en `MENU_POR_ROL`
(`app/routers/pages.py`). Las plantillas reciben `session_user` y `rol_label` solas.

## Sistema Nacional (nacional/)

Los lotes se cargan eligiendo un tipo de recurso del catálogo del Sistema Nacional (`nacional/`, otra
API en `:8002`; ver su README). `app/integrations/nacional.py` es el cliente; si la API no responde,
cargar un lote da 503 y no guarda nada. Config en `.env` (`NACIONAL_*`). Los tests la reemplazan por
`FakeNacional` (`tests/conftest.py`).

## Bonita

`app/integrations/bonita.py` es el cliente REST (login con CSRF, instanciar,
listar tareas, setear variables). Está probado contra Studio 10.4.0.
Configuración en `.env` (`BONITA_*`).

Reglas: la app nunca completa la tarea `Cargar Ofertas de Ayuda`; guarda el
`caseId` de cada emergencia; avanza tareas logueándose como un usuario del
rol correspondiente.
