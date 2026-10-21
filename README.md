# RescueSync — DSSD

TP de la materia DSSD (Diseño de Sistemas de Software Distribuidos): coordinación de emergencias entre municipios, un Centro
Coordinador Regional y una red de ONGs. Son **tres sistemas** que se hablan por HTTP:

| Sistema | Carpeta | Qué hace | Dónde corre |
|---|---|---|---|
| **App web** | `backend/` (FastAPI) + `frontend/` (React) | Pantallas por rol (Municipio, Coordinador, ONG), persistencia de emergencias, lotes y ofertas. Avanza las tareas de Bonita en nombre de cada usuario. | Local: API `:8001`, front `:5173` |
| **Bonita BPM** | `entrega-3/entrega42_local.bos`, `entrega-2/ACME.xml` | El proceso `Gestion Integral de la Emergencia`: ventana de ofertas con timer, evaluación, decisión, adjudicación, ejecución y cierre. Llama a la app y a la API Nacional con conectores. | Local: Bonita Studio `:8080` |
| **API Nacional** | `nacional/` (FastAPI + Postgres) | Registro nacional: ONGs, certificaciones, stock. Valida ofertas, reserva stock (todo o nada) y lo libera al cerrar. **JWT**, Swagger y Dockerfile. | **Nube (Render)**: https://rescuesync-nacional.onrender.com/docs · Local: `:8002` |

Equipo: Tomas Echeverria, Franco Cirielli, Franco Viscardi, Leandro Masuda, Fabrizio Perri.

## El proceso, en una frase

El Municipio registra la emergencia → el Coordinador arma los lotes de necesidades y publica la convocatoria → las ONGs ofrecen dentro de
una ventana (timer de Bonita) → al vencer, Bonita evalúa las ofertas en la API Nacional (reserva el stock) → el Coordinador sigue con la
cobertura o reformula → el Municipio adjudica → ejecución: el Coordinador monitorea y cada ONG marca su actividad terminada → el
Coordinador valida el cierre → Bonita le avisa a la API Nacional (libera lo reservado) y a la app (emergencia **Resuelta**, aviso a las ONGs).

Ficha de la Entrega 3 (URLs, Swagger, repositorio y Dockerfile): [`entrega-3/ENTREGA.md`](entrega-3/ENTREGA.md).

## Autenticación

- **Personas → app:** usuario y contraseña propios de la app, sesión por cookie. Perfiles: `operador.municipal`, `coordinador.regional`,
  `ong.cruzroja`, `ong.bomberos`, `auditor` (contraseña de demo `demo1234`).
- **App y Bonita → API Nacional: JWT.** La API tiene dos cuentas de servicio, `app-service` y `bonita-service`. Cada una entra con
  `POST /login`, recibe un token y lo manda como `Authorization: Bearer`. La app guarda el token y lo renueva sola ante un 401; Bonita
  entra de nuevo en cada tarea de servicio (conector `loginNacional`). Las ONGs y sus altas (`POST /ongs`) también pasan por JWT.
- Con Postgres, la API Nacional **no arranca** si `JWT_SECRET`, `BONITA_SERVICE_PASSWORD` o `APP_SERVICE_PASSWORD` tienen el valor de ejemplo.

## Puesta en marcha

Bonita y la app siempre corren en la PC; lo que cambia es **dónde está la API Nacional**. Hay dos guías, completas y por separado:

| | [**Nube** (por defecto, la de la entrega)](docs/instalacion-nube.md) | [**Local** (plan B si falla la nube)](docs/instalacion-local.md) |
|---|---|---|
| API Nacional | https://rescuesync-nacional.onrender.com (ya desplegada, no se instala) | `nacional/` en `:8002` |
| `.bos` de Bonita | `entrega-3/entrega42_nube.bos` | `entrega-3/entrega42_local.bos` |
| Conectores de Bonita → API Nacional | `https://rescuesync-nacional.onrender.com/...` | `http://localhost:8002/...` |
| Conectores de Bonita → app | `http://localhost:8001/api/bonita/...` | `http://localhost:8001/api/bonita/...` |
| Configuración de la app | `backend/.env.nube` | `backend/.env.local` |

No se pueden tener los dos `.bos` activos a la vez en Studio (mismo nombre y versión de proceso): se importa uno, y para cambiar se reimporta el otro. Las guías
explican cada paso, qué URL tiene cada conector y cómo comprobarlo (`python bonita/scripts/ver_conectores.py <bos>`).

Para dar de alta una ONG de prueba hay una pantalla oculta en `http://localhost:5173/alta-ong` (no está en el menú); ver el paso 5 de cada guía.

## Pruebas

| Qué | Cómo | Necesita |
|---|---|---|
| Unitarias: app, API Nacional, tipos del front | `python scripts/verificar_todo.py` | nada |
| Escenarios con Bonita real (evaluación, tope, adjudicación, cierre, variantes, JWT) | `cd backend && python scripts/correr_escenarios.py` (≈ 25 min) | Bonita + app + API Nacional **locales** |
| Recorrido completo por la interfaz, con capturas | `cd backend && python scripts/ui_parada3.py` (≈ 7 min; sirve contra local y contra la nube) | + front `:5173`, Chrome |
| Otras pruebas de interfaz | `scripts/e2e_ui.py`, `scripts/ui_parada2.py`, `scripts/ui_ejecucion.py` | ídem |

`ESCENARIO_VENTANA_S` (por defecto 60) acorta o alarga la ventana de ofertas de los escenarios. En la nube no hace falta reponer nada (el cierre libera lo reservado); lo único que Render recuerda son las emergencias ya cerradas por número: ver las notas de [`docs/instalacion-nube.md`](docs/instalacion-nube.md).

## Integración continua

`.github/workflows/ci.yml` corre en cada PR y push a `dev` y `main`: tests de la app y de la API Nacional, tipos y build del front, y dos jobs
con **Postgres 16** (migraciones de ida y vuelta, arranque, verificador con JWT y concurrencia de adjudicaciones). El job **CI verde** los resume y
es el chequeo que exige la regla de ramas (`.github/rulesets/`): nadie pushea directo a `dev` ni a `main`. Los escenarios con Bonita no corren en CI.

## Qué hay en el repo

```
backend/        App web (FastAPI + SQLAlchemy + Alembic). Ver backend/README.md.
frontend/       SPA de React (Vite + TypeScript).
nacional/       API Nacional (FastAPI): JWT, reservas, cierres, Dockerfile, scripts/verificar_despliegue.py.
docs/           Guías de instalación: nube (por defecto) y local (plan B).
bonita/         Herramientas: cliente REST y scripts que editan el .bos (conectores de cierre, login JWT, preparar_entorno.py, ver_conectores.py).
entrega-1/      Entrega 1 (entregada): modelo BPM inicial e informe.
entrega-2/      Entrega 2 (entregada): RescueSync.bos, ACME.xml (organización) y bitácora de cambios en Bonita.
entrega-3/      Entrega 3: entrega42_local.bos y entrega42_nube.bos (el proceso vigente, local y contra la API de Render), ficha de entrega y Swagger.
render.yaml     Blueprint de Render para la API Nacional (referencia; el servicio vivo se creó desde el repo).
docker-compose.yml   Postgres 16 para el backend (opcional).
```

## Flujo de Git

`*.bos` y `*.bar` son binarios (ver `.gitattributes`): no se hace diff ni merge textual. Dos ediciones simultáneas del mismo `.bos` son un
conflicto sin resolución automática: coordinar quién lo edita. Los cambios entran a `dev` por pull request con "CI verde".
