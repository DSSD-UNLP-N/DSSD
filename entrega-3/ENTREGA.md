# Entrega 3 — API del Sistema Nacional

Lo que pide la consigna: *API con autenticación JWT dockerizada desplegada en la nube que permita la validación de certificaciones,
gestión de ONGs y el compromiso/liberación de recursos. URLs de servicios, documento Swagger, repositorios y Dockerfile.*

| Qué | Dónde |
|---|---|
| **API en la nube** (Render, Docker, Postgres) | https://rescuesync-nacional.onrender.com |
| **Swagger interactivo** | https://rescuesync-nacional.onrender.com/docs |
| **Documento OpenAPI/Swagger** (descargable) | https://rescuesync-nacional.onrender.com/openapi.json · copia en el repo: [`swagger-api-nacional.json`](swagger-api-nacional.json) |
| **Repositorio** | https://github.com/DSSD-UNLP-N/DSSD (tag `entrega-3`, ramas `dev` y `main`) |
| **Dockerfile** | [`nacional/Dockerfile`](../nacional/Dockerfile) (Python 3.12; al arrancar aplica migraciones y seed: `nacional/scripts/start.sh`) |
| Blueprint de Render | [`render.yaml`](../render.yaml) |

> El plan gratis de Render duerme el servicio tras 15 minutos sin uso: **la primera llamada tarda 30-60 s**. Abrir `/health` antes de probar.

## Cómo probarla (Swagger)
1. Abrir `/docs` → `POST /login` con una cuenta de servicio o de ONG → copiar `access_token`.

**Cuentas de prueba** (de la demo; la base es de práctica):

| Usuario | Clave | Para qué sirve |
|---|---|---|
| `bonita-service` | `1gom_DfYwiGTjWmBkks4MvHT` | Cuenta de servicio: puede llamar a **todos** los endpoints (evaluaciones, adjudicaciones, cierres, catálogo, inventario ajeno). Es la que usan los conectores de Bonita |
| `ong.cruzroja` · `ong.bomberos` | `demo1234` | Cuentas de ONG: catálogo, validaciones y declarar el inventario **propio**. Los endpoints de reservas, adjudicaciones y cierres les dan 403 |
| (sin cuenta) | — | `POST /ongs` está abierto: registra una ONG nueva y devuelve su token |

`app-service` es la otra cuenta de servicio (la usa la app web). Estas claves son las mismas que ya están en `backend/.env.nube` y en `entrega-3/entrega42_nube.bos`.
2. Botón **Authorize** → pegar el token. Todos los endpoints (salvo `/health` y `/login`) exigen JWT.
3. Probar `GET /tipos-recurso`, `GET /ongs`, `POST /validaciones`, `POST /evaluaciones`, etc.

Los datos mal formados (CUIT que no tiene 11 dígitos, cantidades fuera de rango, textos con caracteres inválidos, cuerpos rotos) responden **422** y no guardan nada; las reglas están en [`nacional/README.md`](../nacional/README.md#reglas-de-entrada-todos-los-endpoints).

Verificación automática de un despliegue (no deja datos modificados):
`python nacional/scripts/verificar_despliegue.py https://rescuesync-nacional.onrender.com --clave <BONITA_SERVICE_PASSWORD>`.

## Servicios mínimos de la consigna → endpoints

| Servicio pedido | Endpoints |
|---|---|
| 1. Autenticación y cuentas | `POST /login` (JWT) · `POST /ongs` (registro/onboarding de ONGs, crea su cuenta) |
| 2. Catálogo y consulta | `GET /certificaciones` · `GET /ongs`, `GET /ongs/{cuit}` · `GET /recursos/disponibilidad` · `GET /tipos-recurso` · `PUT /ongs/{cuit}/inventario` |
| 3. Validación por niveles de competencia | `POST /validaciones` (objetos con capacidades habilitadas y niveles de riesgo, sin rechazo binario) · `POST /evaluaciones` (evalúa y reserva) |
| 4. Concurrencia y bloqueo | `POST /adjudicaciones` · `POST /adjudicaciones/resolucion` · `POST /adjudicaciones/{referencia}/confirmar` · `.../liberar` — locking pesimista en PostgreSQL; la prueba de concurrencia corre en CI contra Postgres real |
| 5. Liberación y cierre | `POST /cierres` · `POST /cierres/lote` · `GET /cierres/{id}` · `GET /ongs/{cuit}/cierres` (liberan lo comprometido) |

## Qué más hay detrás
La API la consumen la app web (JWT con la cuenta `app-service`) y el proceso de Bonita (conector `loginNacional` + `Authorization: Bearer`). El recorrido completo
(emergencia → ofertas → evaluación → adjudicación → ejecución → cierre) está probado con Bonita real y con esta API en la nube (`backend/scripts/ui_parada3.py`); cómo levantarlo y probarlo: raíz [`README.md`](../README.md).
