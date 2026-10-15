# Informe técnico: concurrencia y bloqueo transaccional

Alcance: API nacional (`nacional/`) y su integración con la app local (`backend/`).
Fecha de relevamiento: 2026-10-13. Se citan rutas; no se infieren componentes ausentes.

## 1. Stack y estructura
- API: [`nacional/app/`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/nacional/app/), FastAPI.
- Versiones declaradas en [`nacional/requirements.txt`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/nacional/requirements.txt):
  FastAPI 0.141.1, SQLAlchemy 2.0.54, Alembic 1.20.0, `pydantic-settings` 2.15.0
  (Pydantic no está fijado directamente), `psycopg[binary]` 3.3.6.
- Sesión **sync**: [`nacional/app/db.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/nacional/app/db.py):
  `engine = create_engine(...)`, `SessionLocal = sessionmaker(...)`.
  Dependencia: `def get_db(): db = SessionLocal(); yield db; db.close()`.
- Configuración: [`nacional/app/config.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/nacional/app/config.py).
  Default de desarrollo: SQLite `nacional/nacional.db`; `.env.example` documenta también Postgres.

## 2. Modelo de recursos y migraciones
Definiciones en [`nacional/app/models.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/nacional/app/models.py).
- `Ong`: `id Integer PK`, `cuit String(13) UNIQUE`, `nombre String(120)`,
  `estado Enum EstadoOng` (`HABILITADA|SUSPENDIDA`). Relaciones 1:N a
  `OngCertificacion` e `Inventario`, con `cascade="all, delete-orphan"`.
- `Certificacion`: `id Integer PK`, `codigo String(40) UNIQUE`, `nombre String(120)`,
  `descripcion Text NULL`.
- `TipoRecurso`: `id Integer PK`, `codigo String(40) UNIQUE`, `nombre String(120)`,
  `categoria Enum CategoriaRecurso`, `unidad String(30)`,
  `certificacion_id Integer NULL FK -> certificacion.id`; relación a `Certificacion`.
- `OngCertificacion`: `id Integer PK`, `ong_id Integer FK -> ong.id`,
  `certificacion_id Integer FK -> certificacion.id`, `riesgo_max Enum Riesgo`,
  `vence_el Date`; `UNIQUE(ong_id, certificacion_id)`; relaciones a ONG y certificación.
- `Inventario`: `id Integer PK`, `ong_id Integer FK -> ong.id`,
  `tipo_recurso_id Integer FK -> tipo_recurso.id`, `cantidad_total Integer`,
  `cantidad_comprometida Integer DEFAULT 0`; `UNIQUE(ong_id, tipo_recurso_id)`.
  Checks: `cantidad_total >= 0` y `0 <= cantidad_comprometida <= cantidad_total`.
  `disponible` es propiedad calculada: `cantidad_total - cantidad_comprometida`.
- No existe en `nacional/` una entidad `Compromiso`, `Reserva` o `Asignación`
  persistida: **NO EXISTE**.
- Migraciones, en orden: [`nacional/migrations/versions/0001_esquema_inicial.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/nacional/migrations/versions/0001_esquema_inicial.py)
  (`revision='0001'`, sin predecesora). No hay otra migración en `versions/`.

## 3. Endpoints actuales de la API nacional
Registro en [`nacional/app/main.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/nacional/app/main.py),
[`nacional/app/routers/catalogo.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/nacional/app/routers/catalogo.py),
[`nacional/app/routers/inventario.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/nacional/app/routers/inventario.py)
y [`nacional/app/routers/validacion.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/nacional/app/routers/validacion.py).
Todos son públicos: no tienen `Depends` de seguridad y **NO EXISTE** auth nacional.

| Método/ruta | Archivo | Auth |
|---|---|---|
| GET `/health` | `nacional/app/main.py` | No |
| GET `/tipos-recurso` | `nacional/app/routers/catalogo.py` | No |
| GET `/certificaciones` | `nacional/app/routers/catalogo.py` | No |
| GET `/ongs?estado=` | `nacional/app/routers/catalogo.py` | No |
| GET `/ongs/{cuit}` | `nacional/app/routers/catalogo.py` | No |
| GET `/recursos/disponibilidad?tipo_recurso=` | `nacional/app/routers/catalogo.py` | No |
| PUT `/ongs/{cuit}/inventario` | `nacional/app/routers/inventario.py` | No |
| POST `/validaciones` | `nacional/app/routers/validacion.py` | No |
`POST /validaciones` usa request `ValidacionIn`: `gravedad: Riesgo`,
`items: list[ItemValidacionIn]`, donde cada ítem tiene `cuit`, `tipo_recurso` y
`cantidad > 0`. Responde `ValidacionOut`: `alcanza_todo` y
`resultados: list[ResultadoValidacionOut]` con solicitado, disponible, alcanza,
nivel, riesgo permitido, asignación sugerida y observaciones. Schemas en
[`nacional/app/schemas.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/nacional/app/schemas.py).
El endpoint agrupa ítems repetidos por `(cuit, tipo_recurso)` y no persiste.

## 4. Stock, transacciones y locks actuales
- El stock disponible se deriva de un contador materializado:
  `cantidad_total - cantidad_comprometida`; no se calcula desde una tabla de
  movimientos. Implementación en [`nacional/app/models.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/nacional/app/models.py)
  y lectura en [`nacional/app/services/validacion.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/nacional/app/services/validacion.py).
- `cantidad_comprometida` existe, pero en la API nacional no hay código que la
  incremente ni decremente: el compromiso/bloqueo transaccional **NO EXISTE**.
- No hay `with_for_update`, `SELECT ... FOR UPDATE`, `begin()` explícito ni
  aislamiento configurable en `nacional/`. `db.commit()` aparece en el PUT de
  inventario; cada request obtiene una sesión sync.
- Sí hay un lock, pero en la app local: [`backend/app/services/ofertas.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/backend/app/services/ofertas.py),
  `select(Ong.id).where(Ong.id == ong.id).with_for_update()`, para serializar
  publicaciones simultáneas de la misma ONG. Ese lock no actualiza el inventario
  nacional y no protege adjudicaciones.

## 5. Autenticación
- En `nacional/`: `/login`, JWT, dependencias de seguridad y roles **NO EXISTEN**.
- La app local sí tiene login por sesión/cookie, no JWT: [`backend/app/routers/api.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/backend/app/routers/api.py)
  (`POST /api/auth/login`, `/logout`, `/me`) y roles `MUNICIPIO`, `COORDINADOR`,
  `ONG`, `AUDITOR` en [`backend/app/models/entities.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/backend/app/models/entities.py).
- Falta en la API nacional: identidad/autorización del actor que modifica
  inventario, permisos para bloquear/liberar, auditoría y protección del endpoint
  de escritura.

## 6. Llamadas desde web local y Bonita
- Cliente nacional: [`backend/app/integrations/nacional.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/backend/app/integrations/nacional.py).
  Usa `requests`, `NACIONAL_BASE_URL` y timeout configurable; implementa GET
  `/tipos-recurso` y POST `/validaciones`.
- Proxy web: [`backend/app/routers/api.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/backend/app/routers/api.py):
  GET `/api/tipos-recurso` exige usuario local; publicar oferta es
  POST `/api/emergencias/{id}/ofertas` y exige rol ONG.
- Adjudicación/bloqueo: **NO EXISTE** en el código relevado. El flujo actual
  valida al publicar, sumando ofertas abiertas locales en
  [`backend/app/services/ofertas.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/backend/app/services/ofertas.py).
- Bonita figura como futura llamada al vencer el timer: validar ofertas y luego
  bloquear; el ServiceTask de esa validación está pendiente según
  [`entrega-3/plan-modelado-validacion.md`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/entrega-3/plan-modelado-validacion.md).
  Conector Bonita para esas operaciones nacionales: **NO EXISTE**.

## 7. Tests y CI
- Framework: pytest + `TestClient`/httpx; tests nacionales en
  [`nacional/tests/`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/nacional/tests/).
- Fixture principal: [`nacional/tests/conftest.py`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/nacional/tests/conftest.py)
  fuerza `DATABASE_URL=sqlite://`, crea SQLite en memoria con `StaticPool`,
  `Base.metadata.create_all`, override de `get_db` y seed.
- Los tests nacionales usan SQLite, **NO PostgreSQL**. Hay tests de constraints,
  endpoints, migración y validación, pero no tests de concurrencia/lock.
- CI en [`.github/workflows/backend-tests.yml`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/.github/workflows/backend-tests.yml):
  dos jobs separados (`backend` y `nacional`), Python 3.14, `pip install` y
  `pytest -q`. No levanta un servicio Postgres.

## 8. Docker y deploy
- [`docker-compose.yml`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/docker-compose.yml)
  solo levanta `postgres:16-alpine` para `backend` (puerto 5432, usuario/db
  `rescuesync`, password declarada en compose). No define servicio nacional.
- Dockerfile para `nacional/`: **NO EXISTE**. Docker/deploy documentado en
  `nacional/README.md` es **NO EXISTE**; el README dice explícitamente sin Docker
  ni deploy en la rama relevada.
- Variables nacionales: `DATABASE_URL` (en [`nacional/.env.example`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/nacional/.env.example));
  el nombre de app es opcional por default. No requiere variables de auth porque
  auth nacional **NO EXISTE**.
- URL desplegada documentada: `https://sistema-nacional-latest.onrender.com`,
  en [`entrega-3/plan-pruebas-nube.md`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/entrega-3/plan-pruebas-nube.md)
  y el plan E3. El plan advierte confirmar que Render use Postgres.

## 9. Plan E3 y pruebas
- [`entrega-3/plan-modelado-validacion.md`](D:/Facultad/Sistemas%20Distribuidos/Trabajo/DSSD/entrega-3/plan-modelado-validacion.md)
  decidió: inventario nacional como fuente única; `disponible=total-comprometido`;
  validación sin persistencia; tope preventivo en ofertas locales; liberar al
  retirar; y dejar bloqueo/liberación para servicio 4.
- Pendientes explícitos: desplegar rama de liberación y `/cierres`, implementar
  bloqueo/compromiso, JWT/alta de ONGs, revisar timeout, PRs y opcionales de UI.
- [`entrega-3/plan-pruebas-nube.md`](D:/Facultad/Sistemas%20Distribuidos%20Trabajo/DSSD/entrega-3/plan-pruebas-nube.md)
  reporta bloques A/B/C/E verdes y pruebas de caída; aclara que bloqueo/compromiso
  no existe, `/cierres` no estaba desplegado y no se modifica la nube.

## 10. TODOs y brechas para implementar
- **Validar restricciones:** ya existen checks/unicidades y tests de modelo; falta
  probar concurrencia real contra PostgreSQL, conflictos/rollback y autorización.
- **Comprometer con locking:** crear operación nacional transaccional de adjudicación:
  agrupar por ONG/recurso, `SELECT inventario ... FOR UPDATE`, verificar ONG
  habilitada/certificación/cantidad, actualizar `cantidad_comprometida`, y
  confirmar todo atómicamente. Definir idempotencia, orden de locks y respuestas
  para 409/423. Hoy **NO EXISTE** endpoint, modelo de compromiso ni migración.
- **Liberar recursos:** crear operación transaccional inversa, validar que no libere
  dos veces, registrar referencia a adjudicación/cierre y evitar que comprometido
  quede negativo. `POST /cierres` y su implementación en esta rama: **NO EXISTE**.
- Agregar auth/roles para escritura, auditoría, tests PostgreSQL (incluidos dos
  workers concurrentes) y CI con servicio Postgres.
- Revisar `PUT /inventario` bajo concurrencia: actualmente carga y modifica sin
  lock explícito; debe impedir reducir total por debajo de compromisos concurrentes.
