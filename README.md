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

## Guía de Instalación y Despliegue desde Cero

Esta guía configura el entorno local completo de RescueSync: PostgreSQL 16 con dos
bases (`rescuesync` y `nacional`), la API Nacional, el backend, el frontend y el
proceso BPM de Bonita. Los valores mostrados son únicamente para desarrollo local.

### 1. Requisitos previos

Instalar y tener disponibles en el `PATH`:

- **Docker Desktop**, con Docker Compose habilitado.
- **Python 3.12 o superior**.
- **Node.js 18 o superior** y npm.
- **Bonita Studio 2023.2 o superior**, para importar y ejecutar el proceso BPM.

Se recomienda utilizar PowerShell en Windows o Bash en Linux/macOS. Todos los
comandos siguientes se ejecutan desde la raíz del repositorio.

### 2. Paso 1: Configuración de variables de entorno (`.env`)

Crear `backend/.env` copiando `backend/.env.example` y dejar, como mínimo, estas
variables para la instalación local:

```env
DATABASE_URL=postgresql+psycopg://rescuesync:rescuesync@localhost:5433/rescuesync
SESSION_SECRET=dev-only-change-me
SHOW_DEMO_USERS=true
NACIONAL_BASE_URL=http://localhost:8002
BONITA_BASE_URL=http://localhost:8080/bonita
BONITA_USERNAME=install
BONITA_PASSWORD=install
BONITA_API_KEY=rescuesync-dev-key
```

PowerShell:

```powershell
Copy-Item backend\.env.example backend\.env
```

Bash:

```bash
cp backend/.env.example backend/.env
```

Crear `nacional/.env` con la conexión a la segunda base PostgreSQL y las
credenciales de desarrollo:

```env
DATABASE_URL=postgresql+psycopg://rescuesync:rescuesync@localhost:5433/nacional
JWT_SECRET=dev-only-change-me
JWT_EXPIRATION_MINUTES=60
BONITA_SERVICE_USERNAME=bonita-service
BONITA_SERVICE_PASSWORD=change-me
APP_SERVICE_USERNAME=app-service
APP_SERVICE_PASSWORD=change-me-app
```

No usar estos secretos en producción. La API Nacional rechaza los valores de
ejemplo cuando se conecta a PostgreSQL fuera del modo local.

### 3. Paso 2: Levantar PostgreSQL con Docker

El servicio `db` usa `postgres:16-alpine`, publica el puerto host `5433` hacia el
puerto interno `5432` y monta el volumen persistente `rescuesync-pgdata`.
`docker/init-dbs.sql` crea la base `nacional` durante la primera inicialización
del volumen.

PowerShell o Bash:

```bash
docker compose up -d db
docker compose ps
```

Comprobar que el contenedor está saludable:

```bash
docker compose exec db pg_isready -U rescuesync -d rescuesync
```

El script SQL de inicialización se ejecuta solo cuando el volumen se crea por
primera vez. Si se modificó el script y se necesita reinicializar ambas bases
(esto elimina los datos locales), ejecutar:

```bash
docker compose down -v
docker compose up -d db
```

### 4. Paso 3: Instalar dependencias y preparar la API Nacional

PowerShell:

```powershell
cd nacional
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m app.seed
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

Bash:

```bash
cd nacional
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m app.seed
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

Mantener este proceso abierto. La API queda disponible en
`http://localhost:8002`; su estado se puede consultar en
`http://localhost:8002/health` y su Swagger en `http://localhost:8002/docs`.

### 5. Paso 4: Instalar dependencias y preparar el backend

Abrir otra terminal en la raíz del repositorio.

PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m app.seed
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

Bash:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m app.seed
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

El backend queda disponible en `http://localhost:8001` y usa la base
`rescuesync` de PostgreSQL.

### 6. Paso 5: Instalar y ejecutar el frontend

Abrir una tercera terminal:

```bash
cd frontend
npm install
npm run dev
```

La interfaz queda disponible en `http://localhost:5173`. Vite reenvía las
llamadas `/api` al backend local.

### 7. Paso 6: Importar y ejecutar Bonita

1. Abrir Bonita Studio.
2. Importar `entrega-3/entrega42_local.bos`.
3. Abrir el editor de la organización e importar `entrega-2/ACME.xml`.
4. Pulsar **Desplegar** en el editor de la organización. Este paso es necesario
   para que los actores tengan miembros asignados.
5. Ejecutar el proceso `Gestion Integral de la Emergencia`.
6. Verificar `http://localhost:8080/bonita`.

Para la integración local, Bonita debe poder acceder al backend en `:8001` y a
la API Nacional en `:8002`. Las credenciales de los usuarios de demostración
son `demo1234`; el usuario técnico configurado por defecto en el proceso es
`walter.bates` con contraseña `bpm`. Si el proceso local usa otras credenciales,
ajustar `BONITA_USERNAME` y `BONITA_PASSWORD` en `backend/.env`.

Si falla el despliegue, revisar el log de Bonita en
`<Studio>\workspace\tomcat\server\logs\bonita.log`.

### 8. Paso 7: Verificación de la instalación

Con todos los servicios activos:

```bash
curl http://localhost:8002/health
curl http://localhost:8001/docs
```

Abrir `http://localhost:5173` e ingresar con `operador.municipal` y la
contraseña `demo1234`. Luego registrar una emergencia para comprobar la
comunicación entre frontend, backend, API Nacional y Bonita.

## Guía de Uso y Escenarios de Prueba End-to-End (E2E)

La siguiente guía describe las rutas principales y un recorrido completo por
los tres sistemas locales: SPA, backend FastAPI, API Nacional y Bonita BPM.
Antes de ejecutar los escenarios, completar la [instalación desde cero](#guía-de-instalación-y-despliegue-desde-cero)
y comprobar que los servicios estén disponibles en `:5173`, `:8001`, `:8002` y
`8080`.

### 1. Catálogo de endpoints principales

#### Backend principal — `http://localhost:8001`

| Método | Ruta | Uso |
|---|---|---|
| `GET` | `/docs` | Documentación interactiva Swagger. |
| `POST` | `/api/auth/login` | Autenticación de usuarios de la aplicación y creación de sesión. |
| `POST` | `/api/emergencias` | Creación de una emergencia desde la SPA. |
| `GET` | `/api/emergencias/{id}` | Consulta del detalle y estado de una emergencia. |
| `GET` | `/api/emergencias/{id}/ofertas` | Consulta de las ofertas registradas para una emergencia. |
| `POST` | `/api/bonita/emergencias/{id}/eventos` | Callback protegido con `BONITA_API_KEY` para que Bonita actualice eventos y estados. |
| `GET` | `/api/bonita/emergencias/{id}/ofertas` | Consulta protegida que Bonita utiliza para obtener las ofertas de una emergencia. |

El backend usa una sesión por cookie para los usuarios de la SPA. Los
endpoints bajo `/api/bonita` no usan esa sesión: requieren la cabecera
`X-Api-Key` configurada en `BONITA_API_KEY`.

#### API Nacional — `http://localhost:8002` o Render

| Método | Ruta | Uso |
|---|---|---|
| `GET` | `/docs` | Documentación interactiva Swagger. |
| `POST` | `/login` | Autenticación de `bonita-service` o `app-service` y emisión de JWT. |
| `POST` | `/evaluaciones` | Evaluación de cobertura y reserva inicial de stock nacional. |
| `POST` | `/adjudicaciones/resolucion` | Resolución de la adjudicación y confirmación de recursos para las ONGs seleccionadas. |
| `POST` | `/cierres/lote` | Cierre de varias adjudicaciones y liberación o descuento del stock comprometido. |

Las rutas protegidas de la API Nacional requieren
`Authorization: Bearer <JWT>`. La cuenta `bonita-service` es la utilizada por
los conectores BPM para evaluar, adjudicar y cerrar recursos.

### 2. Escenarios de prueba End-to-End

#### Escenario 1: creación de una emergencia e inicio del proceso

1. Abrir la SPA en `http://localhost:5173` e iniciar sesión con un usuario
   operador. En el seed actual, usar `operador.municipal` / `demo1234`
   (si el entorno contiene una cuenta alternativa como
   `operador@rescuesync.com`, utilizar sus credenciales).
2. Registrar una emergencia indicando tipo, ubicación y nivel de gravedad.
   La SPA envía `POST /api/emergencias` al backend.
3. Verificar que la emergencia se haya guardado consultando
   `GET /api/emergencias/{id}` o desde la interfaz.
4. Crear los lotes de recursos y publicar la convocatoria desde la SPA. El
   backend persiste los lotes y coordina la instancia del proceso BPM mediante
   la API REST de Bonita.

En la implementación actual, la emergencia recién creada queda en estado
`ABIERTA`; durante el flujo de ofertas pasa por `CONVOCATORIA` y, cuando vence
la ventana, por `CERRADA`. Estos estados representan funcionalmente las etapas
de pendiente de procesamiento y convocatoria abierta; no se utilizan
literalmente los estados `PENDIENTE` u `OFERTADA`.

#### Escenario 2: evaluación y cobertura nacional mediante Bonita BPM

1. Bonita recibe el evento de la emergencia y ejecuta el conector REST que
   primero llama a `POST /login` en la API Nacional con la cuenta
   `bonita-service`.
2. Con el JWT obtenido, Bonita llama a `POST /evaluaciones`. La API Nacional
   consulta el catálogo de ONGs, certificaciones e inventarios, evalúa la
   cobertura y reserva el stock correspondiente.
3. Bonita notifica el resultado al backend mediante
   `POST /api/bonita/emergencias/{id}/eventos`, incluyendo la cabecera
   `X-Api-Key`.
4. Consultar `GET /api/emergencias/{id}` para verificar el avance del proceso.
   En el modelo actual, la convocatoria se representa con `CONVOCATORIA` y el
   vencimiento de la ventana con `CERRADA`; la UI puede mostrar etiquetas
   equivalentes como evaluada u ofertada según la tarea que esté activa.

#### Escenario 3: selección de ofertas y adjudicación

1. Desde la SPA, consultar las ofertas con
   `GET /api/emergencias/{id}/ofertas`. Bonita obtiene la misma información
   mediante `GET /api/bonita/emergencias/{id}/ofertas`.
2. Revisar las cantidades ofrecidas y la cobertura de cada ONG. El operador
   confirma la decisión desde la SPA o desde la tarea correspondiente en el
   portal de Bonita.
3. El backend registra la decisión y Bonita ejecuta el conector hacia
   `POST /adjudicaciones/resolucion` en la API Nacional.
4. La API Nacional reserva de forma atómica los recursos de las ONGs
   seleccionadas. Si la reserva es válida, Bonita notifica el resultado al
   backend mediante el endpoint de eventos.

#### Escenario 4: cierre de la emergencia y liberación de recursos

1. Una vez atendida la contingencia, completar las tareas de ejecución y
   validación de cierre en Bonita.
2. Bonita obtiene un JWT de servicio y llama a
   `POST /cierres/lote` en la API Nacional. La operación consolida los cierres
   y libera o descuenta exactamente el stock comprometido, de forma
   idempotente.
3. Bonita envía el evento final al backend mediante
   `POST /api/bonita/emergencias/{id}/eventos`.
4. Verificar con `GET /api/emergencias/{id}` que la emergencia haya quedado en
   estado `RESUELTA`. En el flujo local, `CERRADA` identifica el vencimiento de
   la ventana de ofertas; `RESUELTA` identifica el cierre bilateral completo.

Para automatizar escenarios adicionales existe
`backend/scripts/correr_escenarios.py`. Requiere Bonita, el backend y la API
Nacional locales, y permite validar evaluación, topes de oferta, adjudicación,
JWT y cierre sin depender únicamente de la interfaz gráfica.

## Usar la API Nacional de la nube

La API Nacional está desplegada en Render (Docker construido desde `nacional/Dockerfile`, rama `dev`, Postgres). Para que la app y Bonita la usen:

1. **App:** en `backend/.env`: `NACIONAL_BASE_URL=https://rescuesync-nacional.onrender.com`, `NACIONAL_SERVICE_PASSWORD=<APP_SERVICE_PASSWORD>` y
   `NACIONAL_TIMEOUT_SECONDS=90` (el plan gratis duerme tras 15 min y la primera llamada tarda ~30-60 s).
2. **Bonita:** los conectores llevan escrita la URL y la clave de `bonita-service`. Generar el `.bos` para la nube (no se sube al repo, lleva la clave):
   ```bash
   NACIONAL_BONITA_PASSWORD=<BONITA_SERVICE_PASSWORD> python bonita/scripts/preparar_entorno.py entrega-3/entrega42_local.bos entrega-3/entrega42_nube.bos --nacional https://rescuesync-nacional.onrender.com
   ```
   e importarlo en Studio como arriba. Para volver a local, reimportar `entrega42_local.bos`.
3. Despertar el servicio antes de empezar: `curl https://rescuesync-nacional.onrender.com/health`.

Verificar un despliegue de la API (72 chequeos, no deja datos): `python nacional/scripts/verificar_despliegue.py <URL> --clave <BONITA_SERVICE_PASSWORD>`.
Las dos contraseñas y `JWT_SECRET` se cargan como variables de entorno del servicio en Render , que construye `nacional/Dockerfile` desde la rama `dev` (`render.yaml` es el blueprint de referencia).

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
entrega-3/      Entrega 3: entrega42_local.bos (proceso vigente), entrega41_20261017_1311.bos (export base), ficha de entrega y Swagger.
render.yaml     Blueprint de Render para la API Nacional (referencia; el servicio vivo se creó desde el repo).
docker-compose.yml   Postgres 16 para el backend (opcional).
```

## Flujo de Git

`*.bos` y `*.bar` son binarios (ver `.gitattributes`): no se hace diff ni merge textual. Dos ediciones simultáneas del mismo `.bos` son un
conflicto sin resolución automática: coordinar quién lo edita. Los cambios entran a `dev` por pull request con "CI verde".
