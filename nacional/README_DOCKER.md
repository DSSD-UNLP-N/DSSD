# Guía de Docker y Deploy en Render — Sistema Nacional

Esta guía explica cómo construir y correr el contenedor Docker del **Sistema Nacional** (Servicio 3) tanto de forma local como para su despliegue en **Render** con base de datos Cloud.

> **Ubicación del código:**  
> Todo el código fuente, la lógica, los modelos y el Dockerfile del servicio residen en la carpeta **`nacional/`**.  
> *(La carpeta `sistema-nacional/` en la raíz contiene únicamente archivos de entorno y caché local; no se utiliza).*

---

## 1. Ejecución Local con Docker

El contenedor se encarga de forma automática de:
1. Instalar todas las dependencias requeridas.
2. Aplicar las migraciones de base de datos con Alembic (`alembic upgrade head`).
3. Cargar el seed de prueba con ONGs, certificaciones e inventarios (`python -m app.seed`).
4. Iniciar el servidor Uvicorn en el puerto `8002`.

### Comandos:

```bash
# Posicionarse en la carpeta nacional
cd nacional

# 1. Construir la imagen Docker
docker build -t sistema-nacional .

# 2. Iniciar el contenedor mapeando el puerto 8002
docker run -p 8002:8002 --name api-nacional sistema-nacional
```

Para detener y limpiar el contenedor:
```bash
docker stop api-nacional && docker rm api-nacional
```

---

## 2. Acceso y Verificación

Una vez corriendo:
* **Swagger UI (Documentación interactiva):** [http://localhost:8002/docs](http://localhost:8002/docs)
* **Healthcheck:** [http://localhost:8002/health](http://localhost:8002/health)
* **Catálogo de recursos:** [http://localhost:8002/tipos-recurso](http://localhost:8002/tipos-recurso)
* **ONGs registradas:** [http://localhost:8002/ongs](http://localhost:8002/ongs)

---

## 3. Despliegue en Render (Cloud)

### Pasos para configurar el Web Service en Render:

1. **Crear Web Service:**
   * Entrar a [Render Dashboard](https://dashboard.render.com/) y seleccionar **New +** > **Web Service**.
   * Conectar el repositorio de GitHub y seleccionar la rama de trabajo (`modelado-tomas-e-3` o `main`).
2. **Configuración de Build:**
   * **Language / Runtime:** `Docker`
   * **Root Directory:** `nacional` *(imprescindible para que Render use el contexto de esta carpeta)*
   * **Dockerfile Path:** `Dockerfile`
3. **Variables de Entorno (Environment Variables):**
   * **`DATABASE_URL`**:
     * Si creas una base de datos PostgreSQL en Render (o usas Supabase / Neon), coloca aquí la URL de conexión.
     * *Adaptación automática:* Render suele proveer la URL con el prefijo `postgres://` o `postgresql://`. La configuración de la app (`app/config.py`) la adapta automáticamente a `postgresql+psycopg://` para el driver `psycopg 3` de SQLAlchemy.
     * Si no se define `DATABASE_URL`, la app funcionará por defecto con SQLite (`nacional.db`).
   * **`PORT`**: Render inyecta esta variable de forma automática. El script de arranque (`entrypoint.sh`) la lee y enlaza Uvicorn al puerto asignado.
   * **`RUN_SEED`**: (Opcional, por defecto `true`). Si está en `true`, carga automáticamente el seed de demo en la base de datos al iniciar el contenedor (es idempotente, no duplica registros).

---

## 4. Integración con el Backend Principal (`backend/`)

Para que la aplicación local `backend/` (RescueSync) se comunique con esta API del Sistema Nacional:

Editar el archivo `backend/.env`:

```env
# Si corre con Docker local:
NACIONAL_BASE_URL=http://localhost:8002

# Si corre desplegado en Render:
NACIONAL_BASE_URL=https://tu-servicio-nacional.onrender.com
```

---

## 5. Estructura de Archivos Docker

* **`Dockerfile`**: Basado en `python:3.12-slim`, define `PYTHONPATH=/app` e instala `requirements.txt`.
* **`entrypoint.sh`**: Script de inicialización que corre migraciones (`alembic`), seed inicial y levanta Uvicorn.
* **`.dockerignore`**: Excluye `.venv`, bases locales SQLite `*.db`, caches `__pycache__` y archivos de test para mantener la imagen limpia y liviana.
