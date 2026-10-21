# RescueSync — backend

API de RescueSync (FastAPI + SQLAlchemy). La interfaz es la SPA de `frontend/`; acá solo hay JSON bajo `/api`.
Cómo levantar todo el sistema (Bonita, API Nacional, app y front, en la nube o en local): [`docs/instalacion-nube.md`](../docs/instalacion-nube.md)
y [`docs/instalacion-local.md`](../docs/instalacion-local.md).

## Correr

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.nube .env             # o .env.local (API Nacional en tu PC); .env.example es la referencia comentada de todas las variables
alembic upgrade head            # crea las tablas
python -m app.seed              # datos de demo (perfiles y ONGs, pass: demo1234)
uvicorn app.main:app --port 8001 --reload
```

`.env.example` apunta a Postgres (`docker compose up -d db` desde la raíz del repo); `.env.nube` y `.env.local` usan SQLite.

Cambios de modelo: editar `app/models/entities.py` y correr
`alembic revision --autogenerate -m "descripcion"` + `alembic upgrade head`.

Swagger de esta API (no es el de la entrega, que es el de la API Nacional): http://localhost:8001/docs

## Estructura

```
app/
  main.py          # crea la app y registra los routers
  core/            # config (variables de entorno), permisos por rol (deps.py) y textos
  routers/         # api.py: endpoints /api/...; bonita.py: callbacks de Bonita en /api/bonita/...
  services/        # lógica de negocio; los routers solo la llaman
  models/          # modelos SQLAlchemy
  schemas/         # esquemas Pydantic de entrada/salida
  integrations/    # clientes externos (Bonita, API Nacional)
```

Convención: router → service → models/integrations. Los routers no tocan la BD ni Bonita directamente.

## Tests

```bash
pip install -r requirements-dev.txt
pytest                                   # unitarios: sin Postgres ni Bonita
RUN_BONITA_INTEGRATION=1 pytest -m integration   # opcional: contra Bonita Studio corriendo
```

Qué protegen (entre otros):
- `test_models.py`: restricciones del esquema (únicos, CHECK de enums, cascadas, versiones de oferta).
- `test_migrations.py`: **las migraciones coinciden con los modelos**. Si falla, cambiaste
  `models/entities.py` sin correr `alembic revision --autogenerate`.
- `test_auth.py`: login, sesión y 401/403 por rol.
- `test_bonita_client.py`: cliente de Bonita con HTTP simulado.
- `test_bonita_contract.py`: el contrato de instanciación y las tareas del `.bos` (`entrega-2/RescueSync.bos`) coinciden con
  lo que manda la app. Si cambiás el contrato en Studio, exportá el `.bos` y actualizá `CONTRACT_INPUTS`.
- `test_bonita_conectores_nacional.py`: los `.bos` vigentes (`entrega-3/entrega42_*.bos`) llaman a la API Nacional con login previo y
  `Authorization`, y el de la nube es el local apuntando a Render.
- `test_documentacion.py`: los `.md` y los comentarios versionados no citan archivos que no estén en git.

Regla: cada pieza nueva (endpoint, pantalla, servicio) entra con sus tests.

## Pruebas con Bonita real

Los scripts de `scripts/` necesitan Bonita, la app y (según el caso) la API Nacional y el front corriendo:

- `correr_escenarios.py`: corre los `escenario_*.py` (evaluación, tope, adjudicación, cierre, variantes, JWT) en orden y limpia los casos de
  Bonita entre uno y otro. Son lentos y solo sirven en modo local.
- `e2e_ui.py`: recorre el flujo con los perfiles de demo **en un navegador real** (Playwright + Chrome) contra la SPA, verifica además lo que
  pasa en Bonita y deja una captura por paso en `scripts/capturas/` (gitignoreado). `--demo` lo hace visible y lento; `--timer 90` suma el cierre por timer.
- `ui_parada2.py`, `ui_ejecucion.py`, `ui_parada3.py`: recorridos por la interfaz de cada tramo; `ui_parada3.py` es el completo (alta,
  ofertas de dos ONGs, evaluación, adjudicación, ejecución y cierre) y sirve contra local y contra la nube. `ui_parada2.py` corre el caso de
  reformulación (raciones); su caso de cobertura parcial es opcional (`--con-parcial`) porque usa los mismos paramédicos que `ui_parada3.py`.
- `correr_ui.py`: corre `e2e_ui.py`, `ui_parada2.py` y `ui_parada3.py` **a la vez** (usan recursos distintos), en lugar de uno tras otro: casi todo lo que
  tardan es esperar a que venza la ventana de ofertas. `--completo` suma después el caso parcial; `--sin-capturas` omite las fotos.

Usan el Chrome instalado; sin Chrome, `playwright install chromium`.

**Presupuesto de casos de Bonita.** La edición Community no deja iniciar procesos tras **150 casos en 30 días** por proyecto de Studio (cuenta los
casos iniciados aunque se borren). Cada corrida gasta: `e2e_ui` 1, `ui_parada3` 1, `ui_parada2` 1 (2 con `--con-parcial`), `correr_ui` 3, y los escenarios
`evaluacion` 2, `adjudicacion` 2, `cierre` 1, `tope` 3, `variantes` ~6, `jwt` ~2 (`correr_escenarios` completo, ~16). Al llegar al 80 % y 90 % `bonita.log` avisa
(`allowed cases`); al agotarse la app contesta 502 «No se pudo iniciar el caso en Bonita» y el log dice `Process start limit (150 cases during last 30 days)`.
La salida es importar el `.bos` en Studio como proyecto nuevo (base H2 nueva) y desplegar la organización.

## Login y roles

Sesión por cookie firmada (`SESSION_SECRET`). Usuarios de demo (`python -m app.seed`, pass `demo1234`): `operador.municipal`,
`coordinador.regional`, `ong.cruzroja`, `ong.bomberos`, `auditor`. Con `SHOW_DEMO_USERS=true` en `.env` el login los lista (solo desarrollo).

Proteger una ruta con el rol:

```python
from app.core.deps import require_role
from app.models import Rol

@router.get("/lotes")
def lotes(user: Usuario = Depends(require_role(Rol.COORDINADOR))): ...
```

Sin sesión, `/api/*` responde 401 JSON; con el rol incorrecto, 403. El menú de cada perfil lo arma la SPA (`MENU` en `frontend/src/pages.tsx`).

Alta de ONGs: `POST /api/ongs/alta` (y `GET /api/ongs/alta/tipos-recurso` para el catálogo) son públicos y sirven a la pantalla oculta
`/alta-ong` del front: crean la ONG en Bonita, en la API Nacional con sus rubros y en la app.

## Sistema Nacional (nacional/)

Los lotes se cargan eligiendo un tipo de recurso del catálogo del Sistema Nacional (`nacional/`, otra API; ver su README).
`app/integrations/nacional.py` es el cliente; si la API no responde, cargar un lote da 503 y no guarda nada. Config en `.env` (`NACIONAL_*`).

La API Nacional exige JWT. La app entra con su cuenta de servicio (`NACIONAL_SERVICE_USERNAME` / `NACIONAL_SERVICE_PASSWORD`, `app-service`),
no con la de la persona que usa la pantalla: las personas se autentican contra la base de la app (sesión por cookie) y la app ya validó su rol
antes de llamar a Nacional. El token se pide una vez por proceso y se renueva solo si Nacional contesta 401. Iniciar sesión en la app no
depende de Nacional. Contra Render (que duerme y tarda en despertar) hace falta un `NACIONAL_TIMEOUT_SECONDS` alto: `.env.nube` ya lo trae.
Los tests la reemplazan por `FakeNacional` (`tests/conftest.py`).

Tope de ofertas (`app/services/ofertas.py`): al enviar una oferta se suma lo que la ONG ofrece de cada recurso con lo que ya ofreció en sus otras
convocatorias abiertas y se valida contra su inventario en el Sistema Nacional (`POST /validaciones`); si no alcanza, 400 y no se guarda nada.
Reducir o retirar nunca consulta a la API. Retirar un lote = reenviar la oferta sin él; retirarla toda = reenviarla vacía (versión sin ítems,
`retirada: true`); el historial de versiones no se toca.

## Bonita

`app/integrations/bonita.py` es el cliente REST (login con CSRF, instanciar, listar tareas, setear variables), probado contra Studio.
Configuración en `.env` (`BONITA_*`). La app entra a Bonita con el username de quien actúa (misma clave `bpm`): el caso lo inicia
`operador.municipal`, las tareas del Coordinador las ejecuta `coordinador.regional`, y `walter.bates` queda solo para lo administrativo.

Bonita llama de vuelta a la app con los conectores de las tareas de servicio, en `/api/bonita/emergencias/{id}/ofertas` (GET, el consolidado
de ofertas) y `/api/bonita/emergencias/{id}/eventos` (POST, avisos de evaluación, adjudicación y cierre). Van con la cabecera `X-Api-Key`
(`BONITA_API_KEY`); cambiarla fuera de desarrollo, y también en los conectores del `.bos`.

Reglas:
- La app **nunca completa** la tarea `Cargar Ofertas de Ayuda`: las ofertas viven en la base de la app y esa tarea es solo el ancla del
  timer de la ventana; si alguien la completa, cierra la ventana antes de tiempo.
- La app guarda el `caseId` de cada emergencia (`bonita_case_id`) y avanza las tareas logueándose como un usuario del rol correspondiente.
- «Confirmar Finalizacion de Actividades» es una tarea estándar: la app la completa una sola vez, cuando todas las ONGs adjudicadas terminaron.

### Ventana de ofertas (`ventanaOfertasISO`)

El contrato de instanciación pide `ventanaOfertasISO` al dar de alta la emergencia (la hace el Municipio), pero la ventana la abre el Coordinador al
publicar la convocatoria y el timer usa una fecha absoluta. El alta manda entonces un valor provisorio válido (ahora + `VENTANA_PROVISORIA_HORAS`) y
la publicación de lotes lo **sobrescribe** con `PUT /API/bpm/caseVariable/{caseId}/ventanaOfertasISO` justo antes de completar «Publicar
Convocatoria…». Funciona porque el timer evalúa la variable cuando se activa la tarea, no al instanciar. El valor provisorio no significa nada;
quedó así por ser lo más simple y no tocar el diagrama.
