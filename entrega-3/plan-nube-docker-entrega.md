# Plan: la API en la nube (WP7), Docker y Postgres (WP8) y la entrega (WP10)

Versión del 17/10/2026. Hasta hoy **todo corre en local**; en la nube hay una sola cosa, la API Nacional, y con código viejo.

## 0. Dónde está cada cosa hoy

| Pieza | Hoy | Entrega 3 (consigna) |
|---|---|---|
| API Nacional | Local (`:8002`, SQLite) **y** una copia en Render (`https://sistema-nacional-latest.onrender.com`) con **código viejo** | **En la nube**, dockerizada, con Swagger y Dockerfile |
| Base de la API Nacional | SQLite local; Postgres en Render, registrada en la migración `0001` | Postgres (recomendada; dockerizada da puntaje extra) |
| App web (backend + SPA) | Local (`:8001`, `:5173`, SQLite) | Local (la consigna la llama "aplicación web local") |
| Bonita | Local, en Bonita Studio (`:8080`) | No pide nube |

Lo que hay en la nube hoy responde (`/health` tarda 35 s en despertar), pero **no tiene** `/evaluaciones`,
`/adjudicaciones/{ref}/confirmar|liberar` ni `/adjudicaciones/resolucion`: son los 4 endpoints de esta entrega.

Lo que ya existe para desplegar: `nacional/Dockerfile`, `nacional/scripts/start.sh` (migra, carga el seed y levanta
Uvicorn), `render.yaml` (servicio web + Postgres gratis), `.github/workflows/deploy-nacional.yml` (construye la imagen y
dispara un deploy hook de Render si existe el secreto `RENDER_DEPLOY_HOOK_URL`) y `nacional/README_DOCKER.md`.
`nacional/entrypoint.sh` (de Fabri) duplica a `start.sh` y no lo usa nadie.

Dato a confirmar: el servicio vivo se llama `sistema-nacional-latest` y `render.yaml` dice `rescuesync-nacional`, así que
el servicio vivo se creó a mano y **el blueprint nunca se usó**. No puedo ver el panel de Render: la rama, las variables y
el plan los tiene que mirar quien tenga acceso.

---

## WP7: API Nacional en Render con Postgres (unas 4 h)

**Objetivo:** que la URL pública sirva el código nuevo, con Postgres, y que `verificar_despliegue.py` dé verde contra ella.

1. **Decidir de qué rama despliega Render.** El código vive en `modelado-tomas-e-3` (sin PR abierto). Dos caminos:
   - rápido: en Render, *Settings → Branch* = `modelado-tomas-e-3`;
   - ordenado: PR a `dev` y que Render despliegue `dev` (necesita revisión del equipo).
   La rama ya trae la cadena de migraciones restaurada (`0001 → b99371d39182 → 2798b12b1c24 → 0002 → 0003`), así que la
   base de Render, que está en `0001`, migra sin romperse (hay un test que lo cubre).
2. **Mirar el panel de Render** (Fabrizio o quien lo creó): que el servicio sea *Docker*, con *Root Directory* `nacional`
   y *Dockerfile Path* `Dockerfile`; que `DATABASE_URL` apunte a la Postgres (Render entrega `postgres://…` y la app lo
   convierte sola); que exista el *Auto-Deploy* o el hook. Anotar el plan (gratis) y la fecha de creación de la base:
   según la política actual de Render, **las Postgres gratuitas vencen a los 30 días**; verificarlo antes de la demo.
3. **Desplegar** y mirar el log de arranque: `alembic upgrade head` (tiene que pasar por `0003`), el seed y Uvicorn.
4. **Verificar**: `python nacional/scripts/verificar_despliegue.py https://sistema-nacional-latest.onrender.com` → 50 de 50.
   Entra en la sección R: reserva, confirma y libera; el inventario tiene que quedar como al principio.
5. **Swagger en la nube**: `/docs` tiene que listar los endpoints nuevos. Exportar `openapi.json` para la entrega.
6. **Arranque en frío**: la primera llamada tarda de 35 a 45 s. Hay que (a) mantener los timeouts de 60 s del backend
   (`NACIONAL_TIMEOUT_SECONDS=60`) y de los conectores de Bonita, y (b) despertar la API con `/health` antes de la demo
   (opcional: un ping cada 10 minutos desde un cron externo).
7. **Deploy automático** (opcional): crear el secreto `RENDER_DEPLOY_HOOK_URL` en GitHub (*Settings → Secrets*, necesita
   permisos de administrador del repo). Sin eso, el job `deploy` se saltea.
8. **JWT**: hoy los endpoints de la nube son públicos. El JWT (WP11) agrega `JWT_SECRET` como variable de Render.

**Cuidado con la prueba de concurrencia:** `nacional/tests/test_concurrencia_*.py` hacen `drop_all` de las tablas de la
base que les pases. **No apuntarlos a la Postgres de la demo**: dejarían la base sin tablas y marcada como migrada.
Usar una Postgres descartable (la del compose, o una gratuita aparte).

**Hecho cuando:** 50/50 contra Render, `/docs` con los endpoints nuevos y una nota con la rama y el commit desplegados.

## Pasar todo a la nube (después de que todo pase en local, es el WP12)

1. En `backend/.env`: `NACIONAL_BASE_URL=https://sistema-nacional-latest.onrender.com` y `NACIONAL_TIMEOUT_SECONDS=60`.
2. En Bonita: cambiar la URL de los conectores que llaman a la API Nacional (hoy `localhost:8002`) por la de Render. Con los
   parámetros del WP12 es un solo valor. **Tienen que coincidir** con el `.env` de la app: los escenarios de `backend/scripts/`
   leen el inventario con la URL del `.env` y Bonita reserva con la suya.
3. Despertar la API (`/health`), reiniciar la app y volver a correr los escenarios (M14). Cada Ejecutar en Studio borra casos.

---

## WP8: Docker Compose y Postgres local (unas 4 h, da puntaje extra)

**Objetivo:** `docker compose up --build` levanta todo desde un clon limpio, con Postgres.

Estado: el `docker-compose.yml` de la raíz solo tiene un Postgres. Hay otro, más completo, en `origin/e3-leandro`, que
**no se va a mergear**; se rehace con estos arreglos:

1. **Dos bases separadas.** La app y la API Nacional tienen una tabla `ong` distinta y las dos usan `alembic_version`:
   en la misma base se pisarían. Dos servicios Postgres, o uno con dos bases (script de inicialización).
2. **Dockerfile del backend** (hoy no hay): imagen con un arranque que corre `alembic upgrade head`, `python -m app.seed` y
   Uvicorn (como `start.sh`). Leandro lo dejaba arrancar sin migrar, contra una base vacía.
3. **API Nacional**: la imagen que ya existe, con `DATABASE_URL` de su Postgres.
4. **SPA**: construirla (`npm run build`) y servirla con nginx, que además reenvía `/api` al backend (en desarrollo lo hace
   Vite). Alternativa mínima: dejar `npm run dev` fuera del compose.
5. **Bonita queda fuera del compose** (corre en Studio). El backend en contenedor necesita llegar a Bonita en el host:
   `BONITA_BASE_URL=http://host.docker.internal:8080/bonita`. Los conectores de Bonita siguen llamando a `localhost:8001`
   y `localhost:8002`, que el compose publica en el host.
6. Variables: `BONITA_API_KEY`, `SESSION_SECRET`, `NACIONAL_BASE_URL=http://nacional:8002`, `NACIONAL_TIMEOUT_SECONDS`.
7. Con el compose en marcha, correr la **prueba de concurrencia en Postgres**:
   `POSTGRES_TEST_DATABASE_URL=postgresql+psycopg://…@localhost:<puerto>/…` y `pytest nacional/tests/test_concurrencia_*.py`.

**Bloqueo:** en la PC de Tomás el motor de Docker no arranca (falta activar la virtualización). Lo probaría quien tenga
Docker funcionando (Leandro o Fabrizio), o se activa la virtualización y se reinicia.

**Hecho cuando:** desde un clon nuevo, `docker compose up --build` deja la app, la API y las dos bases arriba, los dos `/health`
responden y los escenarios pasan; y la prueba de concurrencia pasa en Postgres.

---

## WP10: preparar la entrega (unas 4 h)

Qué pide la consigna para la Entrega 3: las **URLs de los servicios**, el **documento Swagger**, los **repositorios** y el
**Dockerfile**.

1. **Entregables**: URL pública de la API y de su `/docs`, `openapi.json` exportado (o capturas), URL del repositorio y
   `nacional/Dockerfile`.
2. **README** de instalación desde cero: Bonita (importar el `.bos`, la organización `ACME.xml`, Ejecutar), la app, la API
   Nacional, el compose, variables de entorno, usuarios de demo y el orden de arranque.
3. **Reexportar el `.bos` final** desde Studio (el del repo tiene solo el primer conector) y verificar que `ACME.xml`
   trae los usuarios.
4. **Guion de demo** de 5 minutos con los escenarios M1 a M10 y qué mostrar en Swagger y en el portal de Bonita.
5. **Video de respaldo** de la demo, por si falla la nube o Bonita ese día.
6. **Prueba en limpio en otra PC**: clonar, compose, importar en Bonita, correr un escenario.
7. **Limpieza**: sacar `nacional/entrypoint.sh` (duplicado) o usarlo en vez de `start.sh`; revisar que no haya claves en el
   repo; decidir si se borra `POST /adjudicaciones` (heredado); unificar el PR y mergear a `dev`/`main`, con un tag
   `entrega-3`.

**Hecho cuando:** otra persona levanta todo con el README sin ayuda.

---

## Orden y fechas (hoy sábado 17; entrega el jueves 22)

- **Sáb–dom:** en paralelo, WP7 (Render con el código nuevo) y WP8 (compose) por el equipo, mientras sigo con el cierre en
  la app (WP3 y WP6).
- **Lunes:** WP12 y el escenario M14 contra la nube.
- **Martes:** pruebas de punta a punta del flujo completo (WP9).
- **Miércoles:** WP10, la prueba en limpio y el video.
- **Jueves:** entrega.

## Lo que hay que decidir
1. Rama de despliegue de Render, y quién tiene acceso al panel de Render y a los *Secrets* de GitHub.
2. Cuándo se abre el PR a `dev` (hoy no hay ninguno abierto).
3. Quién prueba el Docker, dado que en tu PC no arranca.
4. Qué Postgres descartable se usa para la prueba de concurrencia.
