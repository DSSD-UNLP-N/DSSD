# Contratos entre la app, Bonita y la API Nacional (WP0)

Versión 1 — 16/10/2026. Es lo que hay que acordar **antes** de programar WP1 a WP6. Si algo cambia, se cambia acá primero
(PR a `dev`) y después el código.

Convenciones
- JSON en UTF-8; fechas ISO 8601 con zona; cantidades enteras; nombres de campo en `snake_case`.
- Identidad de la ONG: **CUIT** (`30-54666544-5`). Identidad de un recurso: **código** del catálogo (`PARAMEDICO`).
  Los ids internos de la base **no** salen de cada sistema.
- Errores: `{"detail": "texto"}`. `400` pedido inválido, `401` falta o es mala la clave, `404` no existe, `409`
  conflicto de estado o de stock, `422` formato inválido, `5xx` falla del servidor (Bonita reintenta).
- Idempotencia: repetir cualquier llamada de Bonita **no** puede cambiar el resultado ni descontar dos veces.

---

## 0. Estado real del modelo de Bonita (verificado el 16/10 en el workspace de Studio, `entrega41`, 02/10)

| Qué | Estado |
|---|---|
| "Evaluar Cobertura y Definir Curso de Accion" | **Ya está en la lane del Coordinador** (el `.bos` del repo, del 20/09, la tenía en la de la ONG: hay que reexportar) |
| Actores | `Municipio`, `centro de controlador regional`, `ONG` (mapeados a grupos `/rescuesync/...`) |
| Conectores | **Ninguno** en los 4 ServiceTasks |
| `Confirmar Finalizacion de Actividades` | Tipo paralelo (multi-instancia) con **cardinalidad vacía** |
| Variables | `emergenciaId`, `municipioId` (Long); `nivelGravedad`, `ventanaOfertasISO`, `plazoAdjudicacionISO`, `decisionCoordinador`, `ofertasJson`, `ongsAdjudicadas` (**Text**, sin límite de 255); `coberturaCompleta` (Boolean); `porcentajeCobertura` (Double) |
| Contrato de instanciación | `emergenciaId`, `municipioId`, `nivelGravedad`, `ventanaOfertasISO` |
| REST connector | Por confirmar en Studio (Connectors → agregar → buscar "REST"); si no está, conector de script Groovy |

Además se agregan al proceso **parámetros** (Configuración del proceso → Parámetros): `appBaseUrl`
(`http://localhost:8001`), `nacionalBaseUrl` (`http://localhost:8002` o la URL de Render) y `bonitaApiKey`.
Un parámetro se cambia desde el portal sin volver a desplegar el diagrama.

---

## 1. Referencia de una adjudicación

Una **referencia** identifica "lo que esta ONG puso en esta emergencia en esta ronda". Es opaca para todos:

```
emg-{emergencia_id}-r{ronda}-{cuit}      p. ej.  emg-12-r1-30-54666544-5     (máx. 80 caracteres)
```

- `ronda` empieza en 1 y sube cada vez que el Coordinador elige REFORMULAR (la emergencia vuelve a cargar lotes y a
  publicar). Sin `ronda`, una ronda nueva chocaría con la referencia ya liberada de la anterior.
- La arma la API Nacional al evaluar y la devuelve en cada resultado; Bonita y la app solo la **reenvían**.

---

## 2. App local → Bonita: consolidado de ofertas (directiva 3)

`GET {appBaseUrl}/api/bonita/emergencias/{emergencia_id}/ofertas`
Header: `X-Api-Key: <bonitaApiKey>` (si falta o no coincide: `401`).

Efecto: la emergencia pasa a `EN_EVALUACION` (a partir de ahí deja de contar en el tope local, porque la reserva pasa
a la API Nacional). Repetir la llamada devuelve lo mismo y no cambia nada más.

```json
{
  "emergencia_id": 12,
  "ronda": 1,
  "gravedad": "ALTO",
  "lotes": [
    {"lote_id": 31, "tipo_recurso": "PARAMEDICO", "cantidad": 10, "tipo": "PRINCIPAL"},
    {"lote_id": 32, "tipo_recurso": "AGUA_POTABLE", "cantidad": 5000, "tipo": "PRINCIPAL"}
  ],
  "ofertas": [
    {"cuit": "30-54666544-5", "ong": "Cruz Roja Argentina", "version": 3,
     "items": [{"lote_id": 31, "tipo_recurso": "PARAMEDICO", "cantidad": 4},
               {"lote_id": 32, "tipo_recurso": "AGUA_POTABLE", "cantidad": 3000}]}
  ]
}
```

Reglas
- Solo ofertas **vigentes**: versión actual, no retiradas, con al menos un ítem.
- Lotes sin `tipo_recurso` (anteriores al catálogo) no figuran en `ofertas.items`.
- `404` si la emergencia no existe; `409` si todavía no está en `CERRADA` (ventana vencida) o ya fue evaluada y
  reformulada.

---

## 3. Bonita → API Nacional

Todas sin autenticación en esta versión (el JWT entra después como `Authorization: Bearer`; el campo de cabecera queda
reservado). Mientras la API de la nube esté en el plan gratis, el conector necesita **timeout ≥ 60 s**.

### 3.1 `POST /evaluaciones` — validar y reservar

Request: **el cuerpo del punto 2, tal cual**.

Qué hace, por cada ONG de `ofertas`:
1. Valida con las reglas de `/validaciones` (competencia contra `gravedad`, y cantidades contra el disponible).
2. **Reserva** (bloqueo de filas ordenado, en una transacción) lo ofrecido, sumando por recurso entre sus ítems, con
   estado `RESERVADA` y la referencia del punto 1.
3. Si lo ofrecido por una ONG (sumado por recurso) supera lo que tiene disponible, **no se reserva nada de esa oferta**:
   no se recorta ni se edita. Vuelve como `NO_RESERVADA` con el motivo y la ONG tiene que rehacerla (en la ronda
   siguiente si el Coordinador reformula). No suma a la cobertura. La oferta es una unidad: la ONG manda la oferta
   completa cada vez, así que o entra entera o no entra.

Response `200`:

```json
{
  "emergencia_id": 12,
  "ronda": 1,
  "cobertura_completa": false,
  "porcentaje_cobertura": 63.0,
  "lotes": [
    {"lote_id": 31, "tipo_recurso": "PARAMEDICO", "pedido": 10, "reservado": 6, "porcentaje": 60.0, "cubierto": false},
    {"lote_id": 32, "tipo_recurso": "AGUA_POTABLE", "pedido": 5000, "reservado": 3000, "porcentaje": 60.0, "cubierto": false}
  ],
  "ongs": [
    {"cuit": "30-54666544-5", "ong": "Cruz Roja Argentina", "referencia": "emg-12-r1-30-54666544-5",
     "estado": "RESERVADA",
     "items": [
       {"lote_id": 31, "tipo_recurso": "PARAMEDICO", "ofrecido": 4, "reservado": 4,
        "nivel": "PARCIAL", "riesgo_permitido": "MEDIO", "asignacion_sugerida": "APOYO",
        "observaciones": ["SALUD_PREHOSP vigente hasta riesgo MEDIO; la emergencia es ALTO"]}
     ]}
  ]
}
```

Cálculo de la cobertura (decisión a confirmar en la revisión):
- `reservado` de un lote = suma de lo reservado por todas las ONGs a ese lote.
- `porcentaje` de un lote = `min(reservado, pedido) / pedido × 100`.
- `porcentaje_cobertura` = **promedio simple** de los porcentajes de los lotes (cada lote pesa igual; sumar personas
  con litros no tiene sentido).
- `cobertura_completa` = todos los lotes con `reservado ≥ pedido`. Los lotes `APOYO` también cuentan (el modelo
  pregunta "¿se cubrieron todos los lotes?").
- Sin ofertas: `cobertura_completa = false`, `porcentaje_cobertura = 0`, `ongs = []`.

Una ONG sin reserva (CUIT desconocido, suspendida, o sin stock para su oferta) vuelve con `estado: "NO_RESERVADA"`,
`referencia: null` y `reservado: 0` en cada ítem, y la observación `Oferta sin reservar: <motivo>`. No hay nada que
confirmar ni liberar. Lo que sobra del lote se reserva entero (el Municipio elige después; lo demás se libera).

Idempotencia: la clave es la referencia. Si ya existe en `RESERVADA` o `ADJUDICADA`, se devuelve lo mismo; si está
`LIBERADA` o `CERRADA` (otra ronda ya la usó) responde `409`.

### 3.2 `POST /adjudicaciones/{referencia}/confirmar`

Pasa `RESERVADA` → `ADJUDICADA` (el compromiso nacional, eslabón 6). Sin cuerpo.
Response `200`: `{"referencia": "...", "estado": "ADJUDICADA"}`. Repetida → `200` igual. Si estaba `LIBERADA` → `409`.
No existe → `404`.

### 3.3 `POST /adjudicaciones/{referencia}/liberar`

Pasa `RESERVADA` (o `ADJUDICADA` sin cerrar) → `LIBERADA` y **devuelve el stock** (resta lo comprometido).
Response `200`: `{"referencia": "...", "estado": "LIBERADA", "liberado": [{"tipo_recurso": "PARAMEDICO", "cantidad": 4}]}`.
Repetida → `200` sin volver a restar. Si estaba `CERRADA` → `409`.

### 3.3b `POST /adjudicaciones/resolucion` — lo que decidió el Municipio, en una sola llamada

Request: `{"confirmar": ["emg-12-r1-30-54666544-5"], "liberar": ["emg-12-r1-30-68522415-9"]}`.
Confirma las primeras (`ADJUDICADA`) y libera las segundas (`LIBERADA`, devuelve el stock). Valida todo antes de cambiar
nada (`404` si una referencia no existe, `409` si alguna ya no admite la operación, `400` si una está repetida o en las
dos listas) y es idempotente: repetir la llamada completa no resta dos veces. Response `200`:
`{"confirmadas": [{referencia, estado}], "liberadas": [{referencia, estado, liberado}]}`.
Bonita arma el cuerpo con Groovy a partir de `evaluacionJson` (las referencias) y `ongsAdjudicadas` (los CUIT elegidos),
así un solo conector REST resuelve un número de ONGs que cambia en cada emergencia.

### 3.4 `POST /cierres` — fin de la actividad (servicio 5)

```json
{"cuit": "30-54666544-5", "referencia": "emg-12-r1-30-54666544-5"}
```

Libera **exactamente** lo que esa referencia tenía comprometido: exige estado `ADJUDICADA`, resta con bloqueo de filas,
la pasa a `CERRADA` y guarda el cierre. Response `201` con el cierre actual de la API (`id`, `cuit`, `ong`,
`referencia`, `informado_en`, `items[] {tipo_recurso, nombre, unidad, cantidad_liberada, cantidad_total,
cantidad_comprometida, disponible}`). Repetido → `200` con el mismo cierre, sin restar. Si no estaba `ADJUDICADA` → `409`.

> Cambio respecto de hoy: `/cierres` recibe `{cuit, referencia, items}` y libera lo que le piden; pasa a recibir solo
> la referencia y liberar lo que realmente se comprometió (WP3). Hasta que WP3 esté mergeado conviene que Bonita no lo
> use.

### 3.5 Transiciones de una reserva

```
            evaluar               confirmar                 cerrar
  (nada) ──────────▶ RESERVADA ──────────────▶ ADJUDICADA ──────────▶ CERRADA
                         │                         │
                         └──── liberar ────────────┴────▶ LIBERADA
```

El stock comprometido sube al reservar y baja al liberar o cerrar. `confirmar` no toca el stock.

---

## 4. Bonita → app local: eventos

`POST {appBaseUrl}/api/bonita/emergencias/{emergencia_id}/eventos`
Header: `X-Api-Key`. Respuesta `204`. Idempotente (el mismo evento dos veces no duplica notificaciones).

| `tipo` | Cuándo lo manda Bonita | Cuerpo | Qué hace la app |
|---|---|---|---|
| `EVALUACION` | Después de `POST /evaluaciones` | `{"tipo": "EVALUACION", "resultado": <respuesta de 3.1>}` | Guarda el resultado (lo que ven el Coordinador y el Municipio) |
| `ADJUDICACION` | Después de confirmar y liberar | `{"tipo": "ADJUDICACION", "adjudicadas": ["30-54666544-5"], "no_adjudicadas": ["30-68522415-9"]}` | Marca las ofertas, notifica a cada ONG, emergencia → `EN_EJECUCION` |
| `CIERRE` | Después de los `POST /cierres` | `{"tipo": "CIERRE", "cuits": ["30-54666544-5"]}` | Emergencia → `RESUELTA`, notifica el cierre |

El detalle de la evaluación **no** se guarda en una variable de Bonita: viaja en el evento y la app lo guarda
(`ofertasJson` solo se usa para pasar el consolidado entre dos tareas).

---

## 5. App local → Bonita (lo que la app ya hace, y lo nuevo)

| Acción de la app | Quién | Qué hace en Bonita | Estado |
|---|---|---|---|
| Alta de emergencia | Municipio | Instancia el caso y completa "Registrar Emergencia" | Hecho |
| Publicar convocatoria | Coordinador | Completa "Revisar…" y "Publicar…", setea `ventanaOfertasISO` | Hecho |
| **Decidir** (`POST /api/emergencias/{id}/decision`) | Coordinador | Setea `decisionCoordinador` = `PARCIAL` \| `REFORMULAR` y completa "Evaluar Cobertura…". REFORMULAR antes libera en la API Nacional las referencias de la ronda | Hecho |
| **Adjudicar** (`POST /api/emergencias/{id}/adjudicar`) | Municipio | Setea `ongsAdjudicadas` (lista JSON de CUIT) y completa "Adjudicar Ofertas"; solo se puede elegir entre las ONGs `RESERVADA` | Hecho |
| **Monitorear** (`POST /api/emergencias/{id}/monitoreo`) | Coordinador | Completa "Monitorear Ejecucion del Despliegue"; habilita que las ONGs finalicen | Hecho (WP6) |
| **Finalizar** (`POST /api/emergencias/{id}/finalizar`) | ONG | Marca la oferta FINALIZADA; cuando todas finalizaron, la app completa "Confirmar Finalizacion de Actividades" como admin | Hecho (WP6) |
| **Validar cierre** (`POST /api/emergencias/{id}/validar-cierre`) | Coordinador | 409 si alguna ONG no finalizó; completa "Validar Cierre Operativo Bilateral"; Bonita libera stock y manda CIERRE | Hecho (WP6) |

Cada tarea la ejecuta el usuario del rol correspondiente (mismo username en Bonita), como hoy.

**REFORMULAR**: la app libera en la API Nacional las referencias de la ronda (`POST .../liberar`), retira las
ofertas de la ronda (versión vacía, queda el historial), sube `ronda`, vuelve la emergencia a `REGISTRADA` y el caso de
Bonita regresa solo a "Revisar Información…" por el camino alternativo del modelo.

---

## 6. Estados en la app local

```
Emergencia:  REGISTRADA ─▶ CONVOCATORIA ─▶ CERRADA ─▶ EN_EVALUACION ─▶ ADJUDICACION ─▶ EN_EJECUCION ─▶ RESUELTA
                 ▲                                         │ (REFORMULAR: ronda + 1)
                 └─────────────────────────────────────────┘
Oferta:      vigente ─▶ ADJUDICADA | NO_ADJUDICADA ─▶ FINALIZADA          (o RETIRADA en cualquier momento antes de la evaluación)
```

Tabla nueva `notificacion`: `id`, destinatario (`ong_id` o `usuario_id`), `emergencia_id`, `texto`, `creada_en`, `leida`.
Columna nueva `emergencia.ronda` (entero, default 1).
Columna nueva `emergencia.monitoreo_completado` (booleano, default false) — migración 0006.
Todo esto va en **dos migraciones** de la app: WP1 (0005) para los estados y notificaciones; 0006 para monitoreo_completado.

### Nuevos endpoints de la app (WP6)

| Método | Ruta | Rol | Descripción |
|---|---|---|---|
| `GET` | `/api/notificaciones` | ONG | Lista propias (por `ong_id`), más recientes primero; incluye `leida` |
| `POST` | `/api/notificaciones/{id}/leida` | ONG | Marca leída; 404 si no pertenece a la ONG |
| `POST` | `/api/emergencias/{id}/monitoreo` | COORDINADOR | Completa el monitoreo; 409 si no es EN_EJECUCION; idempotente |
| `POST` | `/api/emergencias/{id}/finalizar` | ONG | Oferta adjudicada → FINALIZADA; 409 si no hay monitoreo; idempotente; cuando todas finalizan la app completa la tarea Bonita |
| `POST` | `/api/emergencias/{id}/validar-cierre` | COORDINADOR | 409 si alguna ONG no finalizó; completa la tarea Bonita; devuelve EmergenciaOut todavía EN_EJECUCION (RESUELTA llega vía evento CIERRE) |

El detalle (`GET /api/emergencias/{id}`) devuelve además:
- `monitoreo_completado: bool`
- `ongs_adjudicadas: [{ong_id, ong_nombre, cuit, estado_oferta}]` — solo para COORDINADOR y AUDITOR

---

## 7. Qué cambia en lo que ya existe

| Dónde | Hoy | Cambio |
|---|---|---|
| API Nacional `POST /adjudicaciones` | Compromete con `ong_id` e `inventario_id` | `/evaluaciones` + `confirmar`/`liberar` ya existen (WP2). Se deja por ahora (tiene tests y es el bloqueo transaccional de Leandro); sus filas nacen `ADJUDICADA`. Borrarlo cuando el equipo lo confirme |
| API Nacional tablas `compromiso`, `compromiso_item` | Sin uso | Se borran con una migración nueva |
| API Nacional `POST /cierres` | Libera lo que le pasen | Libera lo que comprometió la referencia (WP3) |
| `.bos` del repo | Del 20/09; "Evaluar Cobertura" en la lane de la ONG | Reexportar desde Studio (WP0) |
| App local `NacionalClient` | `tipos_recurso`, `validar`, `adjudicar_recursos_nacional` | Se agregan `evaluar` (si la app necesita llamarla), `liberar` (REFORMULAR) y `cerrar`; se quita `adjudicar_recursos_nacional` cuando deje de existir `/adjudicaciones` |

---

## 8. Decisiones abiertas (cerrarlas en la reunión del equipo)

1. **Cobertura**: promedio simple por lote, todos los lotes cuentan (propuesta). ¿Alcanza o se pondera/excluye apoyo?
2. ~~Recorte de reserva~~ **Resuelto (16/10):** sin recorte. Si el stock no alcanza para la oferta, esa ONG queda `NO_RESERVADA` y rehace la oferta.
3. **Quién llama a `/liberar` al REFORMULAR**: la app (propuesta, porque el caso vuelve atrás por el modelo) o Bonita.
4. **Multi-instancia** de "Confirmar Finalizacion": versión simple (una tarea que la app completa cuando todas las ONGs
   adjudicadas finalizaron) o configurarla con cardinalidad `ongsAdjudicadas`.
5. **Clave compartida** `X-Api-Key`: solo para el tramo Bonita ↔ app; hasta que llegue JWT, la API Nacional no pide nada.
