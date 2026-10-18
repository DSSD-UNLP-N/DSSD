# RescueSync — DSSD

TP de la materia DSSD (Diseño de Sistemas de Software Distribuidos): un
sistema de coordinación de emergencias que conecta municipios afectados con
un Centro Coordinador Regional y una red de ONGs, modelado con Bonita BPM y
con una app web propia (FastAPI) para los formularios y la persistencia.

Equipo: Tomas Echeverria, Franco Cirielli, Franco Viscardi, Leandro Masuda,
Fabrizio Perri.

## Qué hay en el repo

```
entrega-1/          Entrega 1 ya entregada (10/9): modelo BPM inicial, informe,
                     grooming. No se edita.
entrega-2/           Archivo vivo del proceso Bonita de la Entrega 2 (1/10):
  RescueSync.bos      el proyecto de Bonita Studio (modelo + formularios).
  ACME.xml            la organización activa (usuarios y grupos de prueba).
bonita/               Cliente REST de Bonita standalone (CLI) y notas sobre
                     qué se puede automatizar en Bonita Studio Community.
backend/              La API: FastAPI + SQLAlchemy + Alembic (solo JSON, bajo
                     /api). Ver backend/README.md.
frontend/             La interfaz: SPA de React (Vite + TypeScript). Habla con
                     la API por /api; no hay páginas HTML en el backend.
docker-compose.yml    Postgres 16 para el backend (opcional, ver más abajo).
teorias/              Material de la materia.
```

## El proceso, en una frase

Un municipio registra una emergencia → el Centro Coordinador la desglosa en
lotes de necesidades y publica la convocatoria → las ONGs cargan ofertas
dentro de una ventana de tiempo (timer) → al vencer, el sistema calcula
cobertura y el municipio adjudica → se notifica el compromiso y, al
finalizar, se libera todo. El detalle completo está en
`entrega-1/Entrega1_RescueSync.docx` y modelado en `entrega-2/RescueSync.bos`.

**La app web reemplaza los formularios nativos de Bonita**: cuando alguien
completa una pantalla propia (por ejemplo, dar de alta una emergencia),
la app también avanza la tarea equivalente en Bonita en nombre del usuario
correspondiente, para que el caso no quede esperando una acción que nunca va
a llegar desde la UI nativa de Bonita.

## Puesta en marcha (de cero)

Para levantar todo el proceso hacen falta dos partes corriendo en paralelo:
**Bonita Studio** (el motor del proceso) y **el backend** (la app web).

### 1. Bonita Studio

1. Instalar **Bonita Studio Community 10.4.0** o superior.
2. Abrir Studio → **Importar** → seleccionar `entrega-2/RescueSync.bos`.
3. Abrir el editor de la **Organización** → Importar `entrega-2/ACME.xml` →
   **Desplegar** (botón dentro del editor; si no se hace, el motor no ve los
   usuarios nuevos y falla con "Actor ... does not contain any members").
4. Sobre el proceso `Gestion Integral de la Emergencia`: **Ejecutar** (o
   Desplegar). Cada Ejecutar/Desplegar reinicia el motor embebido y borra los
   casos existentes — normal, hay que redesplegar después de cualquier
   cambio en el diagrama.
5. Confirmar que responde: `http://localhost:8080/bonita` (usuario técnico
   `walter.bates` / `bpm`).

**Bonita Studio no queda corriendo entre reinicios de la PC ni de Studio.**
Hay que repetir el paso 4 (o abrir Studio y volver a desplegar) cada vez que
se lo necesite.

Usuarios de prueba de la organización (todos con password `bpm`):
`operador.municipal` (Municipio), `coordinador.regional` (Centro
Coordinador), `ong.cruzroja` (ONG). `walter.bates` es el usuario técnico/admin.

Si algo falla al desplegar, el diálogo de Studio no da el motivo real; hay
que mirar los logs: `<instalación de Studio>\workspace\tomcat\server\logs\bonita.log`
y `workspace\.metadata\.log`.

### 2. Backend (la app web)

Requisitos: Python 3.11+. Docker es **opcional** (ver más abajo).

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate              # Windows; en Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env              # Windows; en Linux/Mac: cp .env.example .env
```

Por defecto `backend/.env.example` apunta a Postgres (ver "Base de datos" más
abajo). Para arrancar rápido sin Docker, en `backend/.env` usar SQLite:

```
DATABASE_URL=sqlite:///./dev.db
```

Después:

```bash
alembic upgrade head      # crea las tablas
python -m app.seed        # datos de demo: 5 usuarios (2 ONGs), pass demo1234
uvicorn app.main:app --reload
```

- App: http://localhost:8000/
- Login de prueba: `operador.municipal`, `coordinador.regional`,
  `ong.cruzroja`, `ong.bomberos` o `auditor`, todos con contraseña `demo1234`
  (son usuarios propios de la app, **distintos** de los usuarios de Bonita de
  arriba, aunque tengan el mismo nombre). Con `SHOW_DEMO_USERS=true` en
  `backend/.env` la pantalla de login los lista.
- Swagger automático: http://localhost:8000/docs

Con ambas partes arriba (Bonita en :8080 y el backend en :8000), entrar como
`operador.municipal` → "Registrar emergencia" ya deja la emergencia
persistida y el caso instanciado y avanzado en Bonita.

Detalle de la estructura del backend, cómo correr los tests y cómo proteger
una ruta por rol: **`backend/README.md`**.

### 3. Frontend de React (SPA)

La interfaz es una SPA de React (Vite + TypeScript, `react-router`) y es la
única: el backend no sirve páginas, solo la API bajo `/api`. En desarrollo
corren dos procesos: el backend en `:8001` y Vite en `:5173`, que reenvía
`/api` al backend (mismo origen para el navegador, así que la cookie de
sesión funciona sin tokens ni CORS).

Requisitos: Node 20+.

```bash
cd backend && .venv\Scripts\python -m uvicorn app.main:app --port 8001   # Windows
cd frontend && npm install && npm run dev                                  # http://localhost:5173
```

`npm run build` compila a `frontend/dist`; `npm run typecheck` chequea los tipos.
Swagger de la API: `http://localhost:8001/docs`.

### Base de datos: SQLite (rápido) o Postgres (recomendado por la consigna)

Para desarrollar alcanza con SQLite (paso de arriba). Para usar Postgres,
como recomienda la consigna:

```bash
docker compose up -d db      # desde la raíz del repo, levanta Postgres en :5432
```

Y en `backend/.env` dejar la `DATABASE_URL` de Postgres que ya trae
`.env.example`. El resto de los comandos (`alembic upgrade head`,
`python -m app.seed`, `uvicorn ...`) son los mismos: SQLAlchemy abstrae la
diferencia.

### Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest                                            # unitarios, no necesitan Bonita ni Postgres
RUN_BONITA_INTEGRATION=1 pytest -m integration    # opcional: con Bonita Studio corriendo
```

## Estado actual

Ver `backend/README.md` para el detalle de qué endpoints/pantallas existen, y
la skill `.claude/skills/rescuesync-estado` (uso interno con Claude Code)
para el estado completo del proceso Bonita y del backend tarea por tarea.

## Flujo de Git para el `.bos`

`*.bos` y `*.bar` son binarios (ver `.gitattributes`): nunca hacer
diff/merge textual, se corrompen. Con más de una persona editando el
proceso en Bonita Studio, coordinar quién lo edita en cada momento — dos
ediciones simultáneas del mismo `.bos` son un conflicto sin resolución
automática.
