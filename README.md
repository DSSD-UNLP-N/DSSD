# RescueSync — DSSD

TP de la materia DSSD (Diseño de Sistemas de Software Distribuidos): coordinación de emergencias entre municipios, un Centro
Coordinador Regional y una red de ONGs. Son **tres sistemas** que se hablan por HTTP:

| Sistema | Carpeta | Qué hace | Dónde corre |
|---|---|---|---|
| **App web** | `backend/` (FastAPI) + `frontend/` (React) | Pantallas por rol (Municipio, Coordinador, ONG), persistencia de emergencias, lotes y ofertas. Avanza las tareas de Bonita en nombre de cada usuario. | Local: API `:8001`, front `:5173` |
| **Bonita BPM** | `entrega-3/entrega42_local.bos`, `entrega-2/ACME.xml` | El proceso `Gestion Integral de la Emergencia`: ventana de ofertas con timer, evaluación, decisión, adjudicación, ejecución y cierre. Llama a la app y a la API Nacional con conectores. | Local: Bonita Studio `:8080` |
| **API Nacional** | `nacional/` (FastAPI + Postgres) | Registro nacional: ONGs, certificaciones, stock. Valida ofertas, reserva stock (todo o nada), lo libera y lo descuenta al cerrar. **JWT**, Swagger y Dockerfile. | **Nube (Render)**: https://rescuesync-nacional.onrender.com/docs · Local: `:8002` |

Equipo: Tomas Echeverria, Franco Cirielli, Franco Viscardi, Leandro Masuda, Fabrizio Perri.

## El proceso, en una frase

El Municipio registra la emergencia → el Coordinador arma los lotes de necesidades y publica la convocatoria → las ONGs ofrecen dentro de
una ventana (timer de Bonita) → al vencer, Bonita evalúa las ofertas en la API Nacional (reserva el stock) → el Coordinador sigue con la
cobertura o reformula → el Municipio adjudica → ejecución: el Coordinador monitorea y cada ONG marca su actividad terminada → el
Coordinador valida el cierre → Bonita le avisa a la API Nacional (libera y descuenta) y a la app (emergencia **Resuelta**, aviso a las ONGs).

Ficha de la Entrega 3 (URLs, Swagger, repositorio y Dockerfile): [`entrega-3/ENTREGA.md`](entrega-3/ENTREGA.md).

## Autenticación

- **Personas → app:** usuario y contraseña propios de la app, sesión por cookie. Perfiles: `operador.municipal`, `coordinador.regional`,
  `ong.cruzroja`, `ong.bomberos`, `auditor` (contraseña de demo `demo1234`).
- **App y Bonita → API Nacional: JWT.** La API tiene dos cuentas de servicio, `app-service` y `bonita-service`. Cada una entra con
  `POST /login`, recibe un token y lo manda como `Authorization: Bearer`. La app guarda el token y lo renueva sola ante un 401; Bonita
  entra de nuevo en cada tarea de servicio (conector `loginNacional`). Las ONGs y sus altas (`POST /ongs`) también pasan por JWT.
- Con Postgres, la API Nacional **no arranca** si `JWT_SECRET`, `BONITA_SERVICE_PASSWORD` o `APP_SERVICE_PASSWORD` tienen el valor de ejemplo.

## Puesta en marcha

Requisitos: Bonita Studio Community 10.4.0, Python 3.12+, Node 20+, Chrome (solo para las pruebas por interfaz). Bonita y la app siempre corren en la
PC; lo que cambia es **dónde está la API Nacional**. Elegí una de las dos y seguí los 4 pasos con la columna que corresponda:

| | **Nube** (la de la entrega) | **Local** |
|---|---|---|
| API Nacional | https://rescuesync-nacional.onrender.com (ya desplegada, no se instala nada) | `nacional/` en `:8002` |
| `.bos` de Bonita | `entrega-3/entrega42_nube.bos` | `entrega-3/entrega42_local.bos` |
| Configuración de la app | `backend/.env.nube` | `backend/.env.example` |

No se pueden tener los dos `.bos` activos a la vez en Studio (mismo nombre y versión de proceso): se importa uno, y para cambiar se reimporta el otro.

### 1. Bonita Studio
1. **Archivo → Importar** → el `.bos` de la tabla.
2. Editor de la **Organización** → importar `entrega-2/ACME.xml` → **Desplegar** (botón del editor; sin esto falla con "Actor … does not contain any members").
3. Sobre el proceso `Gestion Integral de la Emergencia`: **Ejecutar**. Cada Ejecutar reinicia el motor y borra los casos.
4. Comprobar `http://localhost:8080/bonita` (técnico `walter.bates` / `bpm`; de prueba `operador.municipal`, `coordinador.regional`, `ong.cruzroja`, `ong.bomberos`, todos `bpm`).

Si algo falla al desplegar, el motivo real está en `<Studio>\workspace\tomcat\server\logs\bonita.log`.

### 2. API Nacional
**Nube:** no hay nada que levantar. El plan gratis de Render duerme el servicio tras 15 min sin uso y la primera llamada tarda 30-60 s: antes de empezar,
abrir `https://rescuesync-nacional.onrender.com/health` (o `curl` a esa URL) hasta que responda `ok`.

**Local:**
```bash
cd nacional
python -m venv .venv && .venv\Scripts\activate        # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
python -m alembic upgrade head && python -m app.seed   # SQLite por defecto (nacional.db); crea ONGs, stock y las cuentas de servicio
uvicorn app.main:app --port 8002
```
Los valores por defecto (`change-me`, `change-me-app`) son solo para local y coinciden con los del `.bos` local. Swagger: http://localhost:8002/docs.

### 3. App web (`:8001`)
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.nube .env                                    # nube. Local: copy .env.example .env   (Linux/Mac: cp)
python -m alembic upgrade head && python -m app.seed   # SQLite (dev.db); para Postgres ver backend/README.md
uvicorn app.main:app --port 8001
```
`.env.nube` ya trae la URL de Render, la clave de la cuenta `app-service` y `NACIONAL_TIMEOUT_SECONDS=90` (por el despertar del plan gratis); no hay que generar
ni editar nada. Si se cambia el `.env` con la app corriendo, reiniciarla.

### 4. Front (`:5173`)
```bash
cd frontend && npm install && npm run dev              # Vite reenvía /api al backend
```
Con todo arriba: entrar a http://localhost:5173 como `operador.municipal` (clave `demo1234`) y registrar una emergencia.

### Notas de la nube
- Cada cierre de emergencia **descuenta stock real** en la base de Render y no hay reset automático (el seed es idempotente: no repone lo gastado). Si se agota,
  se repone con `PUT /ongs/{cuit}/inventario` desde Swagger (`/docs`, autenticado con `POST /login`).
- Verificar un despliegue de la API (72 chequeos, no deja datos): `python nacional/scripts/verificar_despliegue.py <URL> --clave <BONITA_SERVICE_PASSWORD>`.
- Si cambian la URL o la clave de la API, el `.bos` de la nube se rehace con:
  ```bash
  NACIONAL_BONITA_PASSWORD=<BONITA_SERVICE_PASSWORD> python bonita/scripts/preparar_entorno.py entrega-3/entrega42_local.bos entrega-3/entrega42_nube.bos --nacional https://rescuesync-nacional.onrender.com
  ```
- Render construye `nacional/Dockerfile` desde la rama `dev` y redespliega en cada commit; las dos contraseñas de servicio y `JWT_SECRET` son variables de entorno del
  servicio (`render.yaml` es el blueprint de referencia).

## Pruebas

| Qué | Cómo | Necesita |
|---|---|---|
| Unitarias: app, API Nacional, tipos del front | `python scripts/verificar_todo.py` (≈ 30 s) | nada |
| Escenarios con Bonita real (evaluación, tope, adjudicación, cierre, variantes, JWT) | `cd backend && python scripts/correr_escenarios.py` (≈ 25 min) | Bonita + app + API Nacional **locales** |
| Recorrido completo por la interfaz, con capturas | `cd backend && python scripts/ui_parada3.py` (≈ 7 min; sirve contra local y contra la nube) | + front `:5173`, Chrome |
| Otras pruebas de interfaz | `scripts/e2e_ui.py`, `scripts/ui_parada2.py`, `scripts/ui_ejecucion.py` | ídem |

`ESCENARIO_VENTANA_S` (por defecto 60) acorta o alarga la ventana de ofertas de los escenarios. En la nube cada cierre descuenta stock real y no hay reset.

## Integración continua

`.github/workflows/ci.yml` corre en cada PR y push a `dev` y `main`: tests de la app y de la API Nacional, tipos y build del front, y dos jobs
con **Postgres 16** (migraciones de ida y vuelta, arranque, verificador con JWT y concurrencia de adjudicaciones). El job **CI verde** los resume y
es el chequeo que exige la regla de ramas (`.github/rulesets/`): nadie pushea directo a `dev` ni a `main`. Los escenarios con Bonita no corren en CI.

## Qué hay en el repo

```
backend/        App web (FastAPI + SQLAlchemy + Alembic). Ver backend/README.md.
frontend/       SPA de React (Vite + TypeScript).
nacional/       API Nacional (FastAPI): JWT, reservas, cierres, Dockerfile, scripts/verificar_despliegue.py.
bonita/         Herramientas: cliente REST y scripts que editan el .bos (conectores de cierre, login JWT, preparar_entorno.py).
entrega-1/      Entrega 1 (entregada): modelo BPM inicial e informe.
entrega-2/      Entrega 2 (entregada): RescueSync.bos, ACME.xml (organización) y bitácora de cambios en Bonita.
entrega-3/      Entrega 3: entrega42_local.bos y entrega42_nube.bos (el proceso vigente, local y contra la API de Render), ficha de entrega y Swagger.
render.yaml     Blueprint de Render para la API Nacional (referencia; el servicio vivo se creó desde el repo).
docker-compose.yml   Postgres 16 para el backend (opcional).
```

## Flujo de Git

`*.bos` y `*.bar` son binarios (ver `.gitattributes`): no se hace diff ni merge textual. Dos ediciones simultáneas del mismo `.bos` son un
conflicto sin resolución automática: coordinar quién lo edita. Los cambios entran a `dev` por pull request con "CI verde".
