# Consorcios entre ONGs — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que varias ONGs se asocien en un consorcio dentro de una emergencia, que se vean entre sí las ofertas, y que el Municipio adjudique el consorcio como un bloque, sin cambiar Bonita ni la API Nacional.

**Architecture:** Dos tablas nuevas (`consorcio`, `consorcio_miembro`) y un servicio `app/services/consorcios.py` con las reglas de formación. La API suma endpoints de consorcios y un listado de ONGs, y `OfertaOut` gana el consorcio de cada oferta. `ciclo.adjudicar` agrega una validación: el consorcio va entero. El front suma `src/consorcios.tsx` (panel de la ONG y bloques de adjudicación) y lo usa desde `DetallePage`.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, pydantic v2, pytest; React 19 + TypeScript (Vite); Playwright para la prueba de interfaz; Bonita 2025.2 para el escenario.

**Spec:** `docs/superpowers/specs/2026-11-08-consorcios-design.md`

## Global Constraints

- Rama de trabajo de esta sesión: `claude/stoic-brown-65bucb` (consorcios y después dashboard, en orden). El PR a `dev` se abre solo cuando el usuario lo pida. Commits en inglés, formato convencional, sin emojis.
- TDD estricto en el backend: primero el test que falla.
- Textos de UI y `detail` en castellano neutro. Identificadores en castellano, como el resto del código.
- No se tocan `nacional/`, ningún `.bos` ni el consolidado de `GET /api/bonita/emergencias/{id}/ofertas`.
- Códigos: 403 rol u ONG equivocada, 404 inexistente, 409 ventana cerrada o regla de membresía, 422 validación de pydantic.
- Nombre de consorcio: 2 a 80 caracteres después de recortar espacios, único por emergencia.
- Ventana abierta = `ofertas._esta_abierta(emergencia, ahora)` (reusar, no duplicar).
- Un consorcio cuenta como tal con 2 o más miembros `ACEPTADA`.
- Tests del backend desde `backend/` con `python -m pytest -q` (en Windows, `.venv/Scripts/python.exe -m pytest -q`). Chequeo completo: `python scripts/verificar_todo.py` desde la raíz. Lo corre también el hook antes de cada commit.

## Review Focus

1. Una ONG invitada a dos consorcios de la misma emergencia: la segunda invitación da 409 (Task 2, `test_no_se_invita_a_ong_ya_en_otro_consorcio`).
2. Adjudicar por API solo a una parte de un consorcio válido da 409 y nombra el consorcio (Task 4, `test_adjudicar_parte_de_un_consorcio_da_409`).
3. Un miembro `NO_RESERVADA`: tildar el consorcio adjudica solo a los `RESERVADA` y no da error (Task 4, `test_adjudicar_consorcio_con_miembro_sin_reserva`).
4. Una ONG que no está en el consorcio no ve las ofertas de sus miembros (Task 3, `test_ong_ajena_no_ve_ofertas_del_consorcio`).
5. Invitación pendiente al cerrar la ventana: ya no se puede aceptar (409) y no cuenta como miembro (Task 2, `test_invitacion_pendiente_vence_con_la_ventana`).

---

### Task 1: Modelo y migración

**Files:**
- Modify: `backend/app/models/entities.py`, `backend/app/models/__init__.py`
- Create: `backend/migrations/versions/0007_consorcios.py` (revision `'0007'`, down_revision `'0006'`)
- Test: `backend/tests/test_models.py`, `backend/tests/test_migrations.py`

**Interfaces:**
- Produces:
  - `class EstadoMiembro(str, enum.Enum)` con `INVITADA`, `ACEPTADA`, `RECHAZADA`, `SALIO`.
  - `Consorcio`: `id`, `emergencia_id` (FK), `nombre` (String 80), `ong_lider_id` (FK ong), `creado_en`, `disuelto_en` (nullable), `miembros: list[ConsorcioMiembro]`, y `UniqueConstraint("emergencia_id", "nombre")`.
  - `ConsorcioMiembro`: `id`, `consorcio_id` (FK), `ong_id` (FK), `estado: EstadoMiembro`, `invitado_por_ong_id` (FK ong), `invitado_en`, `respondido_en` (nullable), `salio_en` (nullable), relación `ong`.

- [ ] **Step 1:** Test `test_consorcio_con_miembros` en `test_models.py`: crea un consorcio con líder `ACEPTADA` y un invitado `INVITADA`, recarga y verifica estados, `invitado_por_ong_id` y que `disuelto_en` es `None`.
- [ ] **Step 2:** Correrlo: falla porque no existe `Consorcio`.
- [ ] **Step 3:** Agregar `EstadoMiembro`, `Consorcio` y `ConsorcioMiembro`, con `_enum(...)` como los demás enums. Exportarlos en `models/__init__.py`. Escribir `0007_consorcios.py` con `op.create_table` para las dos tablas y `downgrade` que las borra en orden inverso. El enum se crea igual que en `0001` y se borra en `downgrade` si es nativo de Postgres.
- [ ] **Step 4:** `python -m pytest -q tests/test_models.py tests/test_migrations.py`: pasa, y `test_migrations` sube y baja hasta `0007`.
- [ ] **Step 5:** Commit `feat(consorcios): add consortium tables`.

### Task 2: Servicio de consorcios

**Files:**
- Create: `backend/app/services/consorcios.py`
- Test: `backend/tests/test_consorcios.py`

**Interfaces:**
- Consumes: modelos de la Task 1; `ofertas._esta_abierta`; `Notificacion`.
- Produces:
  - `class ConsorcioError(RuntimeError)` con `__init__(self, mensaje: str, status: int = 409)`, como `CicloError`.
  - `crear(db, *, emergencia: Emergencia, ong: Ong, nombre: str) -> Consorcio`
  - `invitar(db, *, consorcio: Consorcio, lider: Ong, invitada: Ong) -> ConsorcioMiembro`
  - `responder(db, *, consorcio: Consorcio, ong: Ong, acepta: bool) -> ConsorcioMiembro`
  - `salir(db, *, consorcio: Consorcio, ong: Ong) -> None`
  - `disolver(db, *, consorcio: Consorcio, lider: Ong) -> None`
  - `consorcio_de(db, emergencia_id: int, ong_id: int) -> Consorcio | None`: el consorcio no disuelto donde la ONG está `INVITADA` o `ACEPTADA`.
  - `miembros_aceptados(c: Consorcio) -> list[ConsorcioMiembro]` y `es_valido(c: Consorcio) -> bool` (2 o más aceptados, no disuelto).
  - `consorcios_validos(db, emergencia_id: int) -> list[Consorcio]`

- [ ] **Step 1:** Tests que fallan, uno por regla, con las dos ONGs del seed (Cruz Roja y Bomberos) y una tercera creada en el test:
  - `test_crear_deja_a_la_ong_como_lider_aceptada`
  - `test_nombre_repetido_en_la_emergencia_da_409`
  - `test_no_se_crea_con_la_ventana_cerrada`
  - `test_solo_la_lider_invita` (403)
  - `test_no_se_invita_a_ong_ya_en_otro_consorcio` (409)
  - `test_no_se_invita_a_si_misma` (409)
  - `test_invitar_notifica_a_la_invitada`: hay una `Notificacion` para la invitada que nombra el consorcio
  - `test_aceptar_y_rechazar`
  - `test_invitacion_pendiente_vence_con_la_ventana`: con la ventana vencida, `responder` da 409 y `miembros_aceptados` no la incluye
  - `test_la_lider_no_puede_salir` (409: tiene que disolver)
  - `test_salir_marca_salio_y_fecha`
  - `test_disolver_marca_disuelto_y_no_borra_filas`
  - `test_un_solo_aceptado_no_es_valido`
  - `test_despues_de_reformular_se_puede_editar`: emergencia en `CONVOCATORIA` con ventana nueva y `ronda=2`, el consorcio de la ronda 1 sigue y acepta invitaciones
- [ ] **Step 2:** Correrlos: fallan.
- [ ] **Step 3:** Implementar. Nombre recortado y validado a 2-80 caracteres (si no cumple, `ConsorcioError(..., 422)`). Cada cambio de estado guarda su fecha (`datetime.now(timezone.utc)`). Todo lo que modifica exige la ventana abierta.
- [ ] **Step 4:** `python -m pytest -q tests/test_consorcios.py`: pasa.
- [ ] **Step 5:** Commit `feat(consorcios): formation rules service`.

### Task 3: Endpoints, listado de ONGs y ofertas visibles entre miembros

**Files:**
- Modify: `backend/app/schemas/api.py`, `backend/app/routers/api.py`
- Test: `backend/tests/test_api_consorcios.py`, `backend/tests/test_api_ofertas.py`

**Interfaces:**
- Consumes: servicio de la Task 2.
- Produces (schemas en `schemas/api.py`):
  - `ConsorcioIn(nombre: str)`, `InvitacionIn(ong_id: int)`, `RespuestaIn(acepta: bool)`
  - `MiembroOut(ong_id: int, ong_nombre: str, cuit: str | None, estado: str, invitado_en: datetime, respondido_en: datetime | None, salio_en: datetime | None)`
  - `ConsorcioOut(id: int, emergencia_id: int, nombre: str, ong_lider_id: int, ong_lider_nombre: str, valido: bool, disuelto: bool, miembros: list[MiembroOut])`
  - `OngOut(id: int, nombre: str, cuit: str | None)`
  - `OfertaOut` suma `consorcio_id: int | None = None` y `consorcio_nombre: str | None = None` (aditivo).
- Rutas:
  - `GET /api/emergencias/{id}/consorcios` (cualquier rol con la emergencia visible) → `list[ConsorcioOut]`, sin los disueltos
  - `POST /api/emergencias/{id}/consorcios` (ONG) → 201 `ConsorcioOut`
  - `POST /api/consorcios/{id}/invitaciones` (ONG) → 201 `ConsorcioOut`
  - `POST /api/consorcios/{id}/respuesta` (ONG) → `ConsorcioOut`
  - `POST /api/consorcios/{id}/salida` (ONG) → 204
  - `DELETE /api/consorcios/{id}` (ONG) → 204
  - `GET /api/ongs` (ONG) → `list[OngOut]`: las ONGs con CUIT, menos la propia y las que ya están en otro consorcio de la emergencia indicada por `?emergencia_id=`

- [ ] **Step 1:** Tests de API que fallan (`client` y `login` de `conftest.py`):
  - `test_flujo_crear_invitar_aceptar`: Cruz Roja crea, invita a Bomberos, Bomberos acepta, el GET muestra `valido: true`
  - `test_municipio_no_puede_crear` (403)
  - `test_consorcio_inexistente_da_404`
  - `test_nombre_vacio_da_422`
  - `test_listado_de_ongs_excluye_propia_y_ocupadas`
  - En `test_api_ofertas.py`: `test_miembros_ven_ofertas_del_consorcio` (Bomberos ve la oferta de Cruz Roja con `consorcio_nombre`) y `test_ong_ajena_no_ve_ofertas_del_consorcio`
  - `test_ofertas_traen_consorcio_para_el_municipio`
- [ ] **Step 2:** Correrlos: fallan.
- [ ] **Step 3:** Implementar las rutas con `require_role(...)`. `ConsorcioError` se traduce a `HTTPException(exc.status, str(exc))`. En `api_listar_ofertas`, para una ONG con consorcio válido el filtro pasa a `ong_id IN (miembros aceptados)`. `_oferta_out` recibe un mapa `ong_id -> Consorcio` y completa los campos nuevos. Documentar cada ruta en Swagger (summary, ejemplos, errores), siguiendo el skill `nuevo-endpoint`.
- [ ] **Step 4:** `python -m pytest -q tests/test_api_consorcios.py tests/test_api_ofertas.py`: pasa.
- [ ] **Step 5:** Commit `feat(consorcios): consortium endpoints and shared offer visibility`.

### Task 4: Adjudicación por bloque

**Files:**
- Modify: `backend/app/services/ciclo.py` (`adjudicar`), `backend/app/routers/api.py` (pasar `db` a `adjudicar`)
- Test: `backend/tests/test_ciclo.py`

**Interfaces:**
- Consumes: `consorcios_validos`, `miembros_aceptados` (Task 2).
- Produces: `adjudicar(db, settings, *, emergencia, municipal, cuits) -> None`. Cambia la firma: se agrega `db` al principio. Se actualizan todos los llamadores.

- [ ] **Step 1:** Tests que fallan, con una evaluación guardada y Bonita falso:
  - `test_adjudicar_parte_de_un_consorcio_da_409`: consorcio Cruz Roja + Bomberos, ambos `RESERVADA`; mandar solo Cruz Roja da 409 con el nombre del consorcio
  - `test_adjudicar_consorcio_con_miembro_sin_reserva`: Bomberos `NO_RESERVADA`; mandar solo Cruz Roja pasa y llama a Bonita con `["<cuit cruz roja>"]`
  - `test_adjudicar_sin_consorcios_igual_que_antes`
- [ ] **Step 2:** Correrlos: fallan.
- [ ] **Step 3:** Antes de completar en Bonita, validar: para cada consorcio válido de la emergencia, si `cuits` incluye a alguno de sus miembros aceptados, tiene que incluir a todos los que tienen estado `RESERVADA` en la evaluación. Si no, `CicloError("El consorcio «X» se adjudica entero: falta …", 409)`.
- [ ] **Step 4:** `python -m pytest -q tests/test_ciclo.py` y `python scripts/verificar_todo.py` (desde la raíz): pasan.
- [ ] **Step 5:** Commit `feat(consorcios): consortium is awarded as a whole`.

### Task 5: Interfaz

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/pages.tsx` (`DetallePage`)
- Create: `frontend/src/consorcios.tsx`

**Interfaces:**
- Consumes: rutas y schemas de la Task 3.
- Produces:
  - En `api.ts`: tipos `Consorcio`, `MiembroConsorcio`, `OngResumen`; `Oferta` suma `consorcio_id` y `consorcio_nombre`. Métodos `listConsorcios(id)`, `crearConsorcio(id, nombre)`, `invitar(cid, ong_id)`, `responder(cid, acepta)`, `salirConsorcio(cid)`, `disolverConsorcio(cid)`, `listOngs(emergencia_id)`.
  - En `consorcios.tsx`:
    - `ConsorcioPanel({ e, onCambio })`, para la ONG con la convocatoria abierta: crear, invitar, aceptar/rechazar, salir o disolver, lista de miembros con su estado y las ofertas de los otros miembros.
    - `agruparParaAdjudicar(ev: Evaluacion, consorcios: Consorcio[])`, que devuelve bloques y ONGs sueltas.
    - `BloqueConsorcio`, la casilla única con la cobertura sumada de lo reservado y los miembros "sin reserva, no se adjudica".
  - `data-testid`: `consorcio-crear`, `consorcio-invitar`, `consorcio-aceptar`, `bloque-consorcio`, `adjudicar` (el que ya existe).

- [ ] **Step 1:** Tipos y métodos en `api.ts`.
- [ ] **Step 2:** `ConsorcioPanel` y la sección de adjudicación con bloques. La casilla del bloque agrega o quita todos los CUIT `RESERVADA` de los miembros. Si ningún miembro tiene reserva, la casilla queda deshabilitada.
- [ ] **Step 3:** Coordinador, Municipio y Auditor ven el nombre del consorcio al lado de cada oferta.
- [ ] **Step 4:** `npm run typecheck` y `npm run build` en `frontend/`: sin errores.
- [ ] **Step 5:** Commit `feat(consorcios): consortium UI for ONGs and award blocks`.

### Task 6: Escenario con Bonita, prueba de interfaz y documentación

**Files:**
- Create: `backend/scripts/escenario_consorcio.py`, `backend/scripts/ui_consorcio.py`
- Modify: `backend/scripts/correr_escenarios.py` (`ESCENARIOS`), `backend/scripts/correr_ui.py`, `README.md`, `backend/README.md`, `.claude/skills/rescuesync-estado/SKILL.md`

**Interfaces:**
- Consumes: `Escenario` y `crear_y_publicar` de `escenario_tope.py`; constantes `CRUZ_ROJA` y `BOMBEROS` de `escenario_adjudicacion.py`.

- [ ] **Step 1:** `escenario_consorcio.py`. Se pide 10 paramédicos. Cruz Roja crea "Red Litoral", invita a Bomberos y Bomberos acepta. Cruz Roja ofrece 6 y Bomberos 4. Vence la ventana y Bonita evalúa (100 %). Por API se intenta adjudicar solo a Cruz Roja: tiene que dar 409. Después se adjudica el bloque. Esperado: las dos ofertas `ADJUDICADA`, emergencia `EN_EJECUCION`, el caso de Bonita esperando en "Monitorear Ejecucion del Despliegue". Al final se cierra todo para liberar el stock en Nacional.
- [ ] **Step 2:** `ui_consorcio.py` (Playwright, mismo estilo que `ui_parada3.py`). Hace el mismo recorrido por la interfaz con dos sesiones de ONG y guarda capturas en `scripts/capturas/consorcio_*.png`.
- [ ] **Step 3:** Registrarlos en `correr_escenarios.py` y `correr_ui.py`.
- [ ] **Step 4:** Correr `python scripts/correr_escenarios.py` completo, con Bonita, app y Nacional locales: todos en verde, también los que ya existían. Correr `python scripts/correr_ui.py`: en verde.
- [ ] **Step 5:** Documentar consorcios en el README (una línea en "El proceso, en una frase" y en la tabla de pruebas), en `backend/README.md` (endpoints) y en el skill `rescuesync-estado`.
- [ ] **Step 6:** Commit `test(consorcios): Bonita scenario and UI walkthrough; docs`.
