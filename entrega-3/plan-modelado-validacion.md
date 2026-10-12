# Plan E3 — Modelado de recursos de ONGs y validación (Tomás)

Rama `modelado-tomas-e-3` (desde `origin/main`, 04/10/2026). Entrega 3: semana del 22/10.

## Estado (04/10)

Fases 0 a 8 hechas y probadas contra servidores reales (Bonita + nacional :8002 + backend :8001 + SPA): API Nacional
completa, lote con tipo del catálogo, tope de ofertas y retirar. Tests: nacional 55, backend 153 (2 omitidos).
`scripts/e2e_ui.py` en navegador real con Bonita: 59/59, y 62 con `--timer 90` (el boundary timer sigue andando).
Pendiente: pushear la rama / PR, avisar al equipo de la tabla `inventario`, y lo opcional (pantalla de inventario de
la ONG, mostrar el nivel de competencia en la SPA).

Liberación (Franco, 12/10, rama `franco/e3-liberacion-y-deploy`): `POST /cierres` informa el fin de una actividad
y resta `cantidad_comprometida`. Imagen en `nacional/Dockerfile` y blueprint `render.yaml`; la URL pública sale
al conectar el repo en Render.

## Objetivo

1. **Modelado**: catálogo de certificaciones y tipos de recurso, ONGs del registro nacional,
   certificaciones de cada ONG e inventario (total / comprometido) en una **API Nacional local**
   (`nacional/`), base para que el resto del equipo sume JWT, bloqueo, liberación y deploy.
2. **Validación**:
   - **Cantidades**: una ONG no puede ofertar más de lo que tiene disponible, sumando todas sus
     ofertas abiertas (4 paramédicos → no puede ofrecer 10, ni 2 en una emergencia y 3 en otra).
   - **Competencia** (servicio obligatorio 3 de la consigna): sin rechazo binario; por cada ítem
     devuelve nivel (PLENA / PARCIAL / SUPERVISADA), riesgo permitido y asignación sugerida
     (lote principal o apoyo).
3. **Retirar oferta**: la ONG puede retirar su oferta a un lote (o toda) mientras la convocatoria
   esté abierta, sin perder el historial de versiones.

## Decisiones (04/10)

| Tema | Decisión |
|---|---|
| Ubicación | `nacional/` en este repo, mismo stack que `backend/` (FastAPI + SQLAlchemy + Alembic, SQLite en dev), puerto `:8002` |
| Certificaciones | Por ONG: `riesgo_max` (BAJO..CRITICO, misma escala que la gravedad) + vencimiento |
| Validación | Ambas (cantidades + competencia) en un solo `POST /validaciones`, que **no guarda nada** (directiva 1) |
| Tipo de recurso | Catálogo nacional con códigos. La app local se adapta **ya**: sin tipo por lote no se puede sumar |
| Tope | Global: ofertas vigentes de la ONG en todas las emergencias con convocatoria abierta + lo comprometido a nivel nacional |
| Retirar | Versión nueva sin ese ítem; versión vacía = oferta retirada. Historial intacto |
| Inventario | Vive en la API Nacional (fuente única; el bloqueo del servicio 4 usa la misma tabla) |
| Carga de inventario | Seed + `PUT /ongs/{cuit}/inventario`. Pantalla en la SPA: después |
| Alta de lote | Select de tipo del catálogo (la unidad sale del catálogo) + detalle libre opcional |
| API Nacional caída | La app local rechaza la publicación con 503. Nunca se publica sin validar |
| Nivel de competencia en el front | Nada por ahora: se ve en Swagger y tests; lo usará la evaluación al vencer el timer |

## Supuestos (no preguntados — corregir si alguno no va)

- **Sin auth por ahora.** Quien haga JWT agrega un `Depends` a nivel router; mis endpoints no cambian.
  La app local llama sin token hasta entonces.
- **Sin Docker ni deploy** en esta rama: corre local con SQLite. Modelos portables a Postgres
  (enums como VARCHAR + CHECK, igual que `backend/`).
- **Identidad ONG = CUIT** (`Ong.cuit` ya existe en la app local). Seed nacional con los mismos CUIT
  que el seed local.
- **"Convocatoria abierta"** = estado `CONVOCATORIA` y ventana sin vencer (el mismo criterio que ya usa
  la app para aceptar ofertas). Al cerrar la ventana esas ofertas dejan de contar; desde ahí la
  garantía dura es el bloqueo al adjudicar (servicio 4, otro integrante).
- **Lotes viejos sin tipo** (bases de dev existentes) no se validan. Los nuevos exigen tipo.
- **Bonita fuera de alcance**: conector y cálculo de cobertura van en la integración. El contrato de
  `POST /validaciones` ya sirve para el ServiceTask "Validar en Sistema Nacional y Calcular Cobertura".

## Arquitectura

```
SPA ──► App local (backend/ :8001) ──────────────► API Nacional (nacional/ :8002)
         · alta de lote: GET catálogo                 · catálogo, ONGs, inventario
         · publicar oferta: POST /validaciones        · POST /validaciones (no guarda)
         · las ofertas viven acá (directiva 1)
```

## API Nacional (`nacional/`)

### Estructura

```
nacional/
├─ app/
│  ├─ main.py            FastAPI("Sistema Nacional de Gestión de Recursos y Riesgos"), Swagger en /docs
│  ├─ config.py · db.py
│  ├─ models.py          enums + 5 tablas
│  ├─ schemas.py
│  ├─ routers/catalogo.py     GET catálogo/ONGs/disponibilidad + PUT inventario
│  ├─ routers/validacion.py   POST /validaciones
│  ├─ services/validacion.py  reglas puras (testeables sin HTTP)
│  └─ seed.py
├─ migrations/           Alembic (0001)
├─ tests/
├─ requirements.txt · requirements-dev.txt · alembic.ini · README.md
```

Routers separados por área para que JWT / bloqueo / liberación entren en archivos propios sin
pisarse.

### Modelo

```
ong                (id, cuit UNIQUE, nombre, estado: HABILITADA | SUSPENDIDA)
certificacion      (id, codigo UNIQUE, nombre, descripcion)
tipo_recurso       (id, codigo UNIQUE, nombre, categoria: PERSONAL | VEHICULO | EQUIPAMIENTO | INSUMO,
                    unidad, certificacion_id NULL → certificación requerida)
ong_certificacion  (id, ong_id, certificacion_id, riesgo_max: BAJO..CRITICO, vence_el DATE)
                    UNIQUE(ong_id, certificacion_id)
inventario         (id, ong_id, tipo_recurso_id, cantidad_total, cantidad_comprometida DEFAULT 0)
                    UNIQUE(ong_id, tipo_recurso_id), CHECK(0 <= comprometida <= total)
```

`disponible = cantidad_total − cantidad_comprometida`. `cantidad_comprometida` la escriben bloqueo
y liberación (otros integrantes) con `SELECT … FOR UPDATE` sobre la fila de `inventario`.

**Seed** alineado con la app local y armado para que la demo pase por cada caso:
- Cruz Roja Argentina (30-54666544-5): `SALUD_PREHOSP` hasta MEDIO; 4 paramédicos, ambulancias,
  raciones, agua.
- Bomberos Voluntarios (30-68522415-9): `RESCATE_ACUATICO` hasta CRITICO, `INCENDIO_FORESTAL` hasta
  ALTO, `SALUD_PREHOSP` **vencida**; rescatistas, botes, brigadistas, paramédicos.
- Una ONG SUSPENDIDA (para el filtro de habilitadas).
- ~5 certificaciones y ~10 tipos de recurso (personal con certificación; insumos sin certificación).

### Endpoints

| Método | Ruta | Qué devuelve |
|---|---|---|
| GET | `/certificaciones` | Catálogo; cada una con los tipos de recurso que habilita |
| GET | `/tipos-recurso` | Catálogo: código, nombre, categoría, unidad, certificación requerida |
| GET | `/ongs?estado=HABILITADA` | ONGs del registro (filtro opcional) |
| GET | `/ongs/{cuit}` | Ficha: certificaciones (vigente sí/no), inventario con disponible, capacidades (riesgo permitido por tipo) |
| PUT | `/ongs/{cuit}/inventario` | Declara `cantidad_total` por tipo (upsert). 409 si queda total < comprometido |
| GET | `/recursos/disponibilidad?tipo_recurso=` | Por tipo: total, comprometido, disponible y desglose por ONG habilitada |
| POST | `/validaciones` | Cantidades + competencia por (cuit, tipo). No persiste |

### `POST /validaciones`

Request (los ítems con el mismo `cuit` + `tipo_recurso` se suman):

```json
{"gravedad": "ALTO",
 "items": [{"cuit": "30-54666544-5", "tipo_recurso": "PARAMEDICO", "cantidad": 2},
           {"cuit": "30-54666544-5", "tipo_recurso": "PARAMEDICO", "cantidad": 3}]}
```

Response (siempre 200: el resultado es estructurado, no un rechazo):

```json
{"alcanza_todo": false,
 "resultados": [{
   "cuit": "30-54666544-5", "ong": "Cruz Roja Argentina", "tipo_recurso": "PARAMEDICO",
   "solicitado": 5, "disponible": 4, "alcanza": false,
   "nivel": "PARCIAL", "riesgo_permitido": "MEDIO", "asignacion_sugerida": "APOYO",
   "observaciones": ["Solicitado 5, disponible 4",
                     "SALUD_PREHOSP vigente hasta MEDIO; la emergencia es ALTO"]}]}
```

Reglas, en orden:

| Caso | nivel | riesgo_permitido | asignación |
|---|---|---|---|
| ONG suspendida o no registrada | SUPERVISADA | null | APOYO |
| Tipo sin certificación requerida (insumos) | PLENA | CRITICO | PRINCIPAL |
| Certificación vigente, `riesgo_max ≥ gravedad` | PLENA | riesgo_max | PRINCIPAL |
| Certificación vigente, `riesgo_max < gravedad` | PARCIAL | riesgo_max | APOYO |
| Sin certificación o vencida | SUPERVISADA | null | APOYO |

- `alcanza = solicitado ≤ disponible` (disponible 0 si no hay fila de inventario o la ONG no está registrada).
- Código de tipo inexistente → 422.

## Cambios en la app local (`backend/` + `frontend/`)

1. **Cliente** `app/integrations/nacional.py` (`requests`, timeout, mismo estilo que `bonita.py`):
   `tipos_recurso()`, `validar(gravedad, items)`. Caída / timeout / 5xx → `NacionalError`.
   Settings: `nacional_base_url = http://localhost:8002`, `nacional_timeout_seconds`.
2. **Lote con tipo**: migración `0004` agrega `lote.tipo_recurso` (nullable). `LoteIn` pasa a
   `{tipo_recurso, detalle?, cantidad, tipo}`; el servicio resuelve el tipo en el catálogo y completa
   `recurso` (nombre + detalle) y `unidad`, así el resto de la app que muestra `recurso`/`unidad` no
   cambia. `GET /api/tipos-recurso` (proxy) para el select. Código inexistente → 400; API caída → 503.
3. **Tope al publicar oferta** (`POST /api/emergencias/{id}/ofertas`): se mandan a `POST /validaciones`
   los ítems de la versión nueva + los de las ofertas vigentes de la ONG en **otras** emergencias con
   convocatoria abierta (la de esta emergencia se reemplaza, no suma). Si algún resultado tiene
   `alcanza=false` → 400 con el detalle por tipo ("Paramédico: entre tus ofertas abiertas sumás 5 y
   tenés 4 disponibles"). API caída → 503 y no se guarda nada. Si la versión nueva **no aumenta**
   ningún tipo respecto de la vigente, no se consulta a la API: retirar nunca falla por la API caída.
4. **Retirar**: `OfertaIn.items` acepta lista vacía (versión vacía = oferta retirada). En la SPA,
   botón "Retirar" por lote y "Retirar oferta", que reenvían la oferta sin esos ítems. Valen las
   mismas reglas de ventana abierta que para crear.
5. **SPA**: select de tipo + detalle en el alta de lote; botones de retirar; el error de tope se
   muestra como cualquier otro error del backend.
6. **Tests** (`responses` mockea la API Nacional igual que a Bonita) y `scripts/e2e_ui.py` actualizado
   (el alta de lote ahora elige tipo).

## Fases (cada una: tests en verde + prueba real → commit chico)

| # | Fase | Verificación | h |
|---|---|---|---|
| 0 | Base `nacional/`: app, config, DB, Alembic vacío, README | `uvicorn` en :8002, `/docs` abre, pytest corre | 2 |
| 1 | Modelo + migración 0001 + seed | test de migraciones (modelo = migración), seed idempotente | 3 |
| 2 | Catálogo: certificaciones, tipos, ONGs, ficha, disponibilidad | tests por endpoint + Swagger | 3 |
| 3 | `PUT /ongs/{cuit}/inventario` | tests: upsert, 404, 409 total < comprometido | 1.5 |
| 4 | Validación: reglas puras + `POST /validaciones` | tests por fila de la tabla de reglas + suma de ítems | 4 |
| 5 | App local: lote con tipo del catálogo (cliente, migración 0004, proxy, SPA) | tests + alta de lote en el navegador | 4 |
| 6 | App local: tope al publicar + 503 | tests: 2+3>4 rechaza, editar reemplaza, otra emergencia suma, API caída | 3 |
| 7 | App local: retirar oferta (backend + SPA) | tests: retirar libera cupo, no llama a la API; navegador | 2.5 |
| 8 | Recorrido real (nacional + backend + Vite + Bonita), `e2e_ui.py`, job de CI para `nacional/`, READMEs | demo completa abajo | 3 |
|   | **Total** | | **26 h ≈ 9 SP** |

Capacidad nominal hasta el 22/10: ~20 h (8 h/semana). Prioridad si no alcanza: 0–4 (la API es el
entregable de E3) → 5–6 (tu validación de cantidades) → 7 → 8.

### Demo de aceptación

1. Coordinador crea lotes eligiendo tipo (Paramédico, Raciones…) en dos emergencias y publica ambas.
2. Cruz Roja (4 paramédicos): ofrece 2 en la Emergencia 1 → OK.
3. Ofrece 3 en la Emergencia 2 → rechazo: suma 5, disponible 4.
4. Edita la Emergencia 1 a 3 → OK (reemplaza, no suma).
5. Retira su oferta de la Emergencia 1 → ofrece 3 en la Emergencia 2 → OK.
6. API Nacional apagada → publicar responde "El Sistema Nacional no responde"; retirar sigue andando.
7. Swagger, `POST /validaciones` con gravedad ALTO: Cruz Roja paramédicos → PARCIAL/APOYO;
   Bomberos rescatistas acuáticos → PLENA/PRINCIPAL; Bomberos paramédicos → SUPERVISADA (cert vencida).

## Coordinación con el equipo

- **Bloqueo / compromiso (servicio 4)**: usa `inventario` con `SELECT … FOR UPDATE` y suma a
  `cantidad_comprometida`; el CHECK impide pasar el total. Su tabla de compromisos referencia
  `ong` + `tipo_recurso`.
- **Liberación (servicio 5)**: resta `cantidad_comprometida`.
- **JWT / onboarding**: el registro de ONG escribe en `ong` (mi modelo); las cuentas de login son
  tabla suya. JWT entra como `Depends` en los routers.
- **Docker / deploy / Postgres cloud**: `nacional/` ya trae requirements propios y modelos portables.
- **Bonita (integración)**: el ServiceTask de validación llama a `POST /validaciones` con las ofertas
  de la emergencia; queda por decidir quién calcula la cobertura.

## Riesgos y limitaciones

- **Carrera**: dos publicaciones simultáneas de la misma ONG pueden pasar las dos (la validación es en
  la API Nacional y el guardado en la app local). Mitigación barata: bloquear la fila `ong` local
  (`with_for_update`) mientras valida y guarda — en Postgres serializa, en SQLite no hace falta.
  La garantía final es el bloqueo al adjudicar.
- **Más procesos en dev**: crear lotes y publicar ofertas ahora necesita la API Nacional levantada
  (backend :8001 + nacional :8002 + Vite :5173 + Bonita). Documentarlo en los READMEs.
- **Bases de dev viejas**: sus lotes no tienen tipo → no se validan.

## Fuera de alcance (esta rama)

JWT y login, registro de ONGs, bloqueo/compromiso, liberación, Dockerfile y deploy, Postgres en la
nube, conector de Bonita y cobertura, mostrar el nivel de competencia en el front, pantalla de
inventario de la ONG.
