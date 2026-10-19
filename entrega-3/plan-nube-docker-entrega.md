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

### Qué cambia y qué no

Solo se mueve **una pieza** (la API Nacional). La app web, el front y Bonita siguen en local: la consigna los llama "locales".
Lo único que cambia es **a qué dirección llama cada uno cuando habla con la API Nacional**:

| Quién llama a la API Nacional | Dónde está la URL hoy | En local | En la nube |
|---|---|---|---|
| La app (reservar/liberar al reformular, `POST /api/emergencias/{id}/decision`) | `backend/.env` → `NACIONAL_BASE_URL` | `http://localhost:8002` | `https://sistema-nacional-latest.onrender.com` |
| Bonita, conector `evaluarOfertas` (`POST /evaluaciones`) | URL del conector, escrita a mano en el diagrama | `http://localhost:8002/evaluaciones` | `https://sistema-nacional-latest.onrender.com/evaluaciones` |
| Bonita, conector `resolverReservas` (`POST /adjudicaciones/resolucion`) | ídem | `http://localhost:8002/adjudicaciones/resolucion` | `https://sistema-nacional-latest.onrender.com/adjudicaciones/resolucion` |
| Bonita, conector de cierre (a crear en la Parada 3) | ídem | `http://localhost:8002/cierres` | `https://sistema-nacional-latest.onrender.com/cierres` |

**No cambian** (la app sigue en local): los conectores `get obteber ofertas`, `avisarEvaluacion` y `avisarAdjudicacion`, que
llaman a `http://localhost:8001`; ni `BONITA_BASE_URL` (`http://localhost:8080/bonita`) ni `BONITA_API_KEY`.

Además de las URLs, en la nube hay tres diferencias:
- **HTTPS** en vez de HTTP. Los conectores de Bonita usan el certificado público de Render, que Java ya reconoce; no hace falta
  tocar la pestaña SSL del conector. *Sin verificar hasta la primera corrida contra Render.*
- **Arranque en frío** de 35 a 45 s después de un rato sin uso: `NACIONAL_TIMEOUT_SECONDS=60` en el `.env` y los 60000 ms que ya
  tienen los conectores. Despertar la API con `GET /health` antes de probar o de la demo.
- **Los datos son los de la base de Render**, no los de tu SQLite, y **persisten entre corridas**. El inventario queda como estaba
  (los escenarios reservan y liberan), pero las referencias `emg-ID-rN-CUIT` quedan guardadas. Si la base local de la app se
  reinicia (SQLite nueva, los ids de emergencia vuelven a 1) y se vuelve a evaluar una referencia que en la nube ya está
  `LIBERADA` o `CERRADA`, la API responde **409** ("ya está LIBERADA; no se puede evaluar de nuevo") y el conector de Bonita falla.
  Si la referencia sigue `RESERVADA` o `ADJUDICADA`, en cambio, es idempotente y devuelve la vieja. Por eso: **no reiniciar la base
  local de la app mientras se prueba contra la nube** (los ids siguen creciendo) o, si hay que hacerlo, usar emergencias con id
  mayor al último usado en la nube.

**Regla de oro:** la URL del `.env` de la app y la de los conectores de Bonita **tienen que apuntar al mismo lado**. Los
escenarios de `backend/scripts/` leen el inventario con la URL del `.env`, y Bonita reserva con la suya; si apuntan a lugares
distintos, el escenario ve un inventario y Bonita reserva en otro.

### Las dos "configuraciones" de Bonita: Local y Production

Lo que se ve en Studio (Configurar) son dos conjuntos de valores distintos del mismo proceso:

- **Local** es la que usa **Ejecutar** en Studio. Es la que importa para probar y para la demo. Está bien: los tres actores
  mapeados a `/rescuesync/coordinador`, `/rescuesync/ong` y `/rescuesync/municipio`.
- **Production** es la que se usa al **exportar/desplegar a un servidor Bonita real** (no es nuestro caso: la consigna pide
  Bonita local). Hoy tiene los actores sin mapear y por eso muestra el aviso amarillo. **No impide nada**: Ejecutar no la mira.
  Igual conviene dejarla igual a Local para que no quede el aviso y para que el `.bos` entregado sea consistente:
  1. Configurar → **Local** → *Mapeo de actores* → **Exportar mapeo de actor al archivo…** (guardar un `.xml`).
  2. Configurar → **Production** → *Mapeo de actores* → **Importar archivo de mapeo de actores…** → elegir ese `.xml`.
  3. Finalizar. El aviso desaparece.
- **Importante:** el diagrama **no tiene parámetros de proceso hoy** (verificado en el `.proc`: 0) y las URLs de los conectores
  están **escritas en el diagrama** (`http://localhost:8002/...` y `http://localhost:8001/...`). Por eso cambiar entre Local
  y Production **no cambia ninguna URL**: hoy, cambiar de local a nube obliga a editar cada conector a mano.

### La forma más fácil de alternar: un parámetro del proceso (WP12)

Se define **un parámetro** y los conectores arman la URL con él. Después, pasar de local a nube es **cambiar un valor en un solo
lugar**, no editar conectores.

1. En Studio, seleccionar el Pool → *Parámetros* (en la pestaña del proceso) → agregar:
   - `nacionalBaseUrl` (Texto), valor por defecto `http://localhost:8002`.
   - `appBaseUrl` (Texto), valor por defecto `http://localhost:8001` (opcional: la app no se mueve, pero queda todo en un lugar).
   - `bonitaApiKey` (Texto), valor `rescuesync-dev-key` (hoy está escrita en los 3 conectores que llaman a la app).
2. En cada conector, la **URL** pasa a ser una expresión Groovy que usa el parámetro, por ejemplo:
   `nacionalBaseUrl + "/evaluaciones"` y `appBaseUrl + "/api/bonita/emergencias/" + emergenciaId + "/eventos"`
   (el editor de expresiones tiene el tipo *Parámetro* para elegirlo).
3. Configurar → **Local** → *Parámetros*: poner el valor que se quiera usar **cuando se ejecuta en Studio**:
   - para probar en local: `nacionalBaseUrl = http://localhost:8002`
   - para probar contra la nube: `nacionalBaseUrl = https://sistema-nacional-latest.onrender.com`
4. Configurar → **Production** → *Parámetros*: dejar la URL de la nube (así el `.bos` ya trae el valor "de producción").
5. **Ejecutar** (redespliega y borra los casos viejos). Verificar con un caso de prueba que Bonita llama a donde se espera
   (en los logs de la API que corresponda).
6. Del lado de la app: en `backend/.env`, la línea de `NACIONAL_BASE_URL` apunta al mismo lado.

**Ojo con lo que es distinto en la práctica:** como Ejecutar usa **Local**, para probar contra la nube desde Studio hay que
**cambiar el valor de Local**; no alcanza con "pasar a Production". La config Production solo sirve para dejar el valor de nube
guardado en el `.bos` y para un despliegue en un servidor real.

*Sin verificar todavía:* que la edición de parámetros se pueda hacer también desde el portal de Bonita Community sin redesplegar
(si se puede, evita borrar casos). Se prueba al hacer este WP; si no, se edita en Studio.

### Resumen de cómo alternar (cuando el WP12 esté hecho)

| Quiero | `backend/.env` (`NACIONAL_BASE_URL`) | Bonita, Configurar → Local → Parámetros (`nacionalBaseUrl`) |
|---|---|---|
| Todo en local | `http://localhost:8002` | `http://localhost:8002` |
| App y Bonita contra la nube | `https://sistema-nacional-latest.onrender.com` (y timeout 60) | `https://sistema-nacional-latest.onrender.com` |

Después de cambiar: reiniciar la app, **Ejecutar** en Studio, despertar la nube con `/health`, y recién ahí correr los escenarios.

### Pasos (M14, una vez que todo pasa en local)
1. En `backend/.env`: `NACIONAL_BASE_URL=https://sistema-nacional-latest.onrender.com` y `NACIONAL_TIMEOUT_SECONDS=60`.
2. En Bonita: el parámetro `nacionalBaseUrl` de la configuración **Local** con la URL de Render.
3. Despertar la API (`/health`), reiniciar la app, Ejecutar en Studio y volver a correr los escenarios (`escenario_evaluacion.py`,
   `escenario_adjudicacion.py`, `escenario_tope.py`) y `verificar_despliegue.py`.

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
