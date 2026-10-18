# WP7 — Poner la API Nacional en la nube (Render), paso a paso desde cero

Guía para quien nunca tocó Render. No hace falta saber programar: son clics en un panel web y un comando al final para comprobar.

> **Estado (18/10):** hecho. El servicio de imagen (`sistema_nacional:v1.0.0`) no se puede pasar a Git, así que se creó uno nuevo,
> `rescuesync-nacional` (`https://rescuesync-nacional.onrender.com`), que construye `nacional/Dockerfile` desde la rama `dev` con
> auto-deploy y usa la misma Postgres. El viejo quedó suspendido. Los pasos de abajo sirven para rehacerlo o para el cambio a `main`.
> Al crear un servicio nuevo en el panel: *New +* → *Web Service* → repo público `DSSD-UNLP-N/DSSD` → rama `dev` → *Language: Docker* →
> *Dockerfile Path* `./nacional/Dockerfile` y *Docker Build Context* `./nacional`.

## 1. Qué es esto y por qué hay que hacerlo

La consigna de la Entrega 3 pide la **API del Sistema Nacional corriendo en la nube, dockerizada, con JWT y Swagger**. Hoy la API
funciona perfecto en nuestras PCs (`localhost:8002`), pero lo que está en internet es una **copia vieja** (de mediados de octubre).
WP7 es **actualizar esa copia** con el código nuevo (JWT, cuentas de servicio, cierre en lote) y comprobar que anda.

**Resultado esperado:** abrir `https://<nuestra-url>.onrender.com/docs` y ver Swagger con `/login`, y que el script de verificación
dé `72/72 verificaciones OK`.

## 2. Vocabulario mínimo

| Palabra | Qué es, en criollo |
|---|---|
| **Render** | Servicio web que ejecuta nuestros programas en internet (como alquilar una PC prendida siempre). Tiene plan gratis. |
| **Web Service** | Un programa de Render que atiende pedidos HTTP. Nuestra API Nacional es uno. |
| **Docker / imagen** | Una "caja" con el programa y todo lo que necesita. Render la arma solo leyendo el archivo `nacional/Dockerfile`. No hace falta instalar Docker en tu PC para esto. |
| **Rama (branch)** | Una versión del código en GitHub. Render descarga **una rama**. Hoy tiene que ser `dev` (o `main` cuando cerremos). |
| **Deploy** | Descargar el código de la rama, armar la caja y reemplazar la versión que está andando. Tarda 3-8 min. |
| **Variable de entorno** | Un dato de configuración que se carga en el panel (una contraseña, una dirección) sin escribirlo en el código. |
| **Postgres** | La base de datos de verdad (SQLite es la de juguete que usamos en local). Render la ofrece aparte y se conecta con una dirección llamada `DATABASE_URL`. |
| **Secret (de GitHub)** | Una variable guardada en GitHub, que los robots (Actions) pueden usar pero nadie puede leer. |

## 3. Cómo está hoy (lo que sabemos del repo y de la URL)

- URL viva: `https://sistema-nacional-v1-0-0.onrender.com` (la anterior, `sistema-nacional-latest`, ya no existe).
- Responde, pero con **código viejo**: Swagger dice versión `0.1.0`, **no tiene `/login`** y los endpoints responden sin token.
- Lo creó Fabrizio **a mano** (no con el archivo `render.yaml`): Web Service, runtime Docker, *Root Directory* `nacional`, conectado al
  repo de GitHub.
- No se actualizó con nuestros merges porque está mirando **otra rama** (probablemente `cloud-deploy-fabri` o `modelado-tomas-e-3`)
  y porque en GitHub falta el secret `RENDER_DEPLOY_HOOK_URL`.
- **No sabemos** (hay que mirar el panel): la rama exacta, si tiene una base Postgres o usa SQLite dentro del contenedor, y en qué cuenta de Render está.

> Atención: el repo se movió a la organización de GitHub `DSSD-UNLP-N/DSSD` (antes `FrancoCirielli16/DSSD`). Si Render quedó atado
> al nombre viejo, puede hacer falta reconectarlo (paso 5.B).

## 4. Qué se necesita antes de empezar

1. **Acceso al panel de Render del servicio** (https://dashboard.render.com). Si el servicio está en la cuenta de Fabrizio: que te
   invite como miembro (Workspace → Members) o que lo haga él siguiendo esta guía.
2. **Que la cuenta de Render tenga acceso al repo de GitHub** `DSSD-UNLP-N/DSSD` (se concede instalando la "Render GitHub App" en la
   organización; lo puede hacer un administrador de la org).
3. **Dos contraseñas nuevas**, largas y distintas a las de ejemplo (ver 5.D). Sirven para que Bonita y la app inicien sesión en la API.
4. **Python 3.11 o más** en tu PC, solo para correr el script de verificación del paso 5.F (no hace falta instalar nada más, usa la biblioteca estándar).

## 5. Paso a paso en el panel de Render

### A. Ubicar el servicio
1. Entrar a https://dashboard.render.com e iniciar sesión.
2. En la lista de servicios abrir el que se llama `sistema-nacional-v1-0-0`.
3. Arriba aparece la URL pública. Anotala.

### B. Apuntarlo a la rama correcta
1. Pestaña **Settings** → sección **Build & Deploy**.
2. **Repository**: tiene que decir `DSSD-UNLP-N/DSSD` (si dice `FrancoCirielli16/DSSD` y falla, botón *Edit* → reconectar al repo de la organización).
3. **Branch**: cambiar a `dev` y guardar. (Cuando cerremos la entrega pasa a `main`.)
4. Verificar que estén así (si no, corregir):
   - **Runtime**: `Docker`
   - **Root Directory**: `nacional`
   - **Dockerfile Path**: `./Dockerfile` (o `Dockerfile`)
5. **Auto-Deploy**: dejar en **On Commit**. Con eso Render redespliega solo cada vez que cambia la rama `dev`: **ese es el deploy automático**, y no hace falta ningún secret de GitHub.

### C. Mirar si hay base Postgres
1. En el panel principal, ¿hay un item tipo **PostgreSQL**? Si no hay: botón **New +** → **PostgreSQL**, nombre `rescuesync-nacional-db`, región igual a la del servicio, plan Free. Crear.
2. Abrir esa base → **Connections** → copiar **Internal Database URL** (empieza con `postgres://`; "internal" funciona porque el servicio y la base están en la misma región).
3. **Importante (plan gratis):** las bases Postgres gratuitas de Render **vencen a los 30 días** y se borran. Anotar la fecha de creación; la demo tiene que ser antes. Si hace falta, se recrea (el contenedor arranca vacío, corre las migraciones y carga el seed solo).

### D. Cargar las variables de entorno
Servicio → pestaña **Environment** → **Add Environment Variable**. Cargar exactamente estas cuatro:

| Nombre | Valor |
|---|---|
| `DATABASE_URL` | La *Internal Database URL* del paso C.2 (se pega tal cual; el código la adapta). |
| `JWT_SECRET` | Texto al azar de 40+ caracteres (es la "llave" que firma los tokens). Render puede generarlo con el botón *Generate*. |
| `BONITA_SERVICE_PASSWORD` | Una contraseña nueva, larga. **Es la que usará Bonita** para iniciar sesión. |
| `APP_SERVICE_PASSWORD` | Otra contraseña nueva, distinta. **Es la que usará nuestra app.** |

Reglas:
- **No** usar los valores de ejemplo (`change-me`, `change-me-app`, `dev-only-change-me`): con Postgres la API **se niega a arrancar** si ve alguno (es a propósito, para que nadie firme tokens con una llave pública).
- Las contraseñas se anotan en un lugar privado del equipo (no en el repo, no en capturas). Se necesitan después en el paso 6.
- Guardar. Render ofrece redesplegar solo al guardar.

### E. Desplegar
1. Si no arrancó solo: botón **Manual Deploy** → **Deploy latest commit** (si algo quedó raro: **Clear build cache & deploy**).
2. Pestaña **Logs**: seguir el progreso. Tiene que terminar con líneas parecidas a `Running alembic upgrade` → `seed` → `Uvicorn running on http://0.0.0.0:...` y el estado del servicio en **Live** (verde).
3. Si dice *Failed*: leer las últimas líneas del log (ver sección 7).

### F. Comprobar que anda
1. Abrir en el navegador `https://<url>/health` → debe mostrar `{"estado":"ok"}`. (El plan gratis duerme tras 15 min sin uso: **la primera llamada tarda ~45-60 s**, es normal.)
2. Abrir `https://<url>/docs` → Swagger; ahora **tiene que aparecer `POST /login`**.
3. Abrir `https://<url>/tipos-recurso` → ahora tiene que dar **401 (no autenticado)**, antes daba 200. Esa es la prueba de que el JWT está activo.
4. En una terminal, dentro de la carpeta del repo:
   ```bash
   python nacional/scripts/verificar_despliegue.py https://<url> --clave <BONITA_SERVICE_PASSWORD>
   ```
   Tiene que terminar con **`72/72 verificaciones OK`**. El script no deja datos modificados (las reservas de prueba se liberan solas).

### G. Deploy automático (ya quedó en 5.B)
- Con *Auto-Deploy → On Commit* y rama `dev`, cada merge a `dev` redespliega.
- Alternativa (solo si Render no se puede conectar al repo): Settings → **Deploy Hook** → copiar la URL, y en GitHub (Settings → Secrets and variables → Actions → *New repository secret*) crear `RENDER_DEPLOY_HOOK_URL` con ese valor. El workflow `.github/workflows/deploy-nacional.yml` ya sabe usarlo.

## 6. Después de que el servicio esté bien (esto no es del panel)

1. **La app** (`backend/.env`): `NACIONAL_BASE_URL=https://<url>` y `NACIONAL_SERVICE_PASSWORD=<APP_SERVICE_PASSWORD>`.
2. **Bonita**: los conectores tienen escritas a mano la dirección `http://localhost:8002` y la clave `change-me`. Hay que cambiarlas por `https://<url>` y `<BONITA_SERVICE_PASSWORD>` (esto es WP12, se hace en Bonita Studio). Hasta entonces Bonita sigue hablando con la API local.
3. Repetir los escenarios contra la nube (WP9). Ojo: **los datos de la nube persisten** y cada cierre descuenta stock real de la base; no hay botón de reset, hay que borrar/recrear la base de Render o restaurar el inventario.

## 7. Si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| Deploy *Failed*, el log dice `Con Postgres hay que definir valores propios para: ...` | Falta o quedó con valor de ejemplo `JWT_SECRET`, `BONITA_SERVICE_PASSWORD` o `APP_SERVICE_PASSWORD` | Corregir en Environment y redesplegar. |
| Log: `could not connect to server` / `connection refused` | `DATABASE_URL` mal copiada o la base está en otra región | Usar la *Internal URL* de la base de la misma región. |
| Deploy *Failed* en el build, `Dockerfile not found` | Root Directory o Dockerfile Path mal | Root Directory `nacional`, Dockerfile Path `./Dockerfile`. |
| `/docs` sigue sin `/login` | Sigue desplegando otra rama o no terminó | Revisar Branch en 5.B y la pestaña *Events*. |
| El verificador da `401` en todo | `--clave` distinta de `BONITA_SERVICE_PASSWORD` | Usar exactamente la clave cargada en 5.D. |
| `/health` tarda un minuto | El plan gratis estaba dormido | Esperar; después responde rápido. |
| Render no encuentra el repo | La app de GitHub de Render no tiene acceso a la organización | Un admin de la org: GitHub → Settings → Applications → Render → dar acceso a `DSSD-UNLP-N/DSSD`. |

## 8. Hecho cuando

- [ ] `https://<url>/docs` muestra `POST /login`.
- [ ] `https://<url>/tipos-recurso` sin token da 401.
- [ ] `verificar_despliegue.py` da `72/72`.
- [ ] El servicio mira la rama `dev` con *Auto-Deploy* en *On Commit*.
- [ ] `DATABASE_URL` es una Postgres (no SQLite) y anotamos cuándo vence.
- [ ] Las dos contraseñas están guardadas en un lugar privado del equipo.
- [ ] La URL pública está en `entrega-3/ESTADO.md` y en `backend/.env.example` (como comentario).

## 9. Qué preguntarle a Fabrizio si no se puede resolver mirando el panel

1. ¿En qué cuenta/equipo de Render está `sistema-nacional-v1-0-0` y cómo me da acceso (o la API key para que lo haga Claude)?
2. ¿Qué rama y qué repo tiene configurados, y tiene Auto-Deploy?
3. ¿Hay una base Postgres en Render o el servicio usa el SQLite del contenedor? ¿Cuándo se creó?
4. ¿Qué variables de entorno tiene cargadas (solo los nombres)?
