# Plan para cerrar la Entrega 3: flujo completo, reparto, pruebas end to end y entrega

Versión del 15/10/2026. Base: `modelado-tomas-e-3` (= `dev` + arreglo de migraciones, PR #8). Entrega: 22/10.
JWT (servicio 1) queda fuera de este plan por decisión del 15/10; tiene su paquete al final para cuando se retome.

---

## 0. Quién es quién en el proceso

| Perfil | Quién es | Usuario de demo | Qué hace en el proceso |
|---|---|---|---|
| **Operador Municipal** (Municipio) | El municipio afectado: pide ayuda | `operador.municipal` | Registra la emergencia. **Adjudica**: elige las ofertas validadas (consigna, eslabón 5; en Bonita, "Adjudicar Ofertas" está en su lane) |
| **Centro Coordinador Regional** | Organiza la respuesta | `coordinador.regional` | Arma los lotes y publica la convocatoria. Si las ofertas no cubren los lotes, **decide** reformular o seguir con cobertura parcial. Monitorea la ejecución y valida el cierre |
| **Representante de ONG** | Quien ayuda | `ong.cruzroja`, `ong.bomberos` | Oferta, edita y retira. Ve sus notificaciones. Marca sus actividades como finalizadas |
| **Auditor / Directivo** | Control | `auditor` | Solo lectura |

Está modelado en las tres capas: lanes y actores en Bonita (grupos `/rescuesync/...`), roles en la app (`require_role`) y
usuarios homónimos en los dos sistemas (app: `demo1234`; Bonita: `bpm`).

---

## 1. Qué dice la consigna del tramo final

- **Directiva 2**: el timer de Bonita administra la ventana; al vencer, el flujo avanza solo a una tarea de validación.
- **Directiva 3**: Bonita inicia la comunicación: una tarea de servicio hace un GET al backend local y recibe el JSON
  consolidado de ofertas de la emergencia.
- **Directiva 4**: con ese JSON, Bonita llama a la API del Sistema Nacional (nube, JWT), que valida y, con control de
  concurrencia, **aplica los bloqueos** para evitar sobre-asignaciones. Al terminar la ejecución y marcarse el cierre en
  la app local, se llama a la **liberación**.
- **Eslabón 4**: al vencer la convocatoria se evalúa cada oferta (perfiles de competencia, lote principal o de apoyo) y
  la API garantiza el bloqueo concurrente.
- **Eslabón 5**: el Municipio ve **solo las ofertas validadas** y elige; el sistema notifica a cada ONG si fue elegida.
- **Eslabón 6 y servicio 4**: tras la adjudicación se registra el **compromiso** en el Sistema Nacional.
- **Eslabón 7 y servicio 5**: las ONGs marcan sus actividades como finalizadas, se informa al sistema central y se
  liberan los recursos.
- **Directiva 1**: la API del Cloud no guarda borradores ni ofertas preliminares (mientras la ventana está abierta,
  las ofertas viven solo en la app local).

---

## 2. Diseño acordado: el recurso pasa por cuatro estados

| Fase | Dónde se guarda la reserva | Qué la libera |
|---|---|---|
| **1. Ventana abierta** (ofertas en borrador) | App local: el tope suma las ofertas vigentes de la ONG (hecho) | Editar, reducir o retirar la oferta (hecho) |
| **2. Ventana vencida, sin decisión** | **API Nacional**: Bonita llama a `POST /evaluaciones`, que valida y **reserva** con `FOR UPDATE` (estado `RESERVADA`) | Que el Municipio no la elija, o que el Coordinador reformule |
| **3. Adjudicada** | API Nacional (estado `ADJUDICADA`): el compromiso nacional | El cierre de la actividad |
| **4. Cerrada** | Nada: `POST /cierres` devolvió el stock (estado `CERRADA`) | — |

Así se cumple "reservado hasta que se decida" sin guardar borradores en la nube: en la fase 1 las ofertas son
borradores (locales); desde que vence la ventana son definitivas y la reserva pasa a la API Nacional.

**No choca con el tope local**: el tope ya compara contra el disponible nacional (total − comprometido). Cuando la
reserva pasa a la API, la app deja de contar esas ofertas y el disponible nacional baja: el resultado es el mismo.
Para que no quede un hueco entre que vence la ventana y Bonita reserva (unos segundos), el tope local sigue contando
las ofertas de una convocatoria vencida **hasta que Bonita pidió el consolidado** (la emergencia pasa a
`EN_EVALUACION` en ese GET). Ver WP1.

### Secuencia por nodo del proceso (modelo verificado en el `.bos`)

| Nodo de Bonita | Quién | Qué pasa | Llamadas |
|---|---|---|---|
| Registrar Emergencia | Municipio | Alta (hecho) | App → Bonita |
| Revisar… / Publicar Convocatoria | Coordinador | Lotes y publicación (hecho) | App → Bonita, App → Nacional (catálogo) |
| Cargar Ofertas de Ayuda + timer | ONGs | Ofertas con tope (hecho). El timer vence → sigue | App → Nacional (`/validaciones`) |
| **Obtener Ofertas de la Red (GET App Local)** | Bonita (servicio) | Pide el consolidado; la emergencia pasa a `EN_EVALUACION` | Bonita → App `GET /api/bonita/emergencias/{id}/ofertas` |
| **Validar en Sistema Nacional y Calcular Cobertura** | Bonita (servicio) | Valida, reserva y calcula la cobertura; setea `coberturaCompleta`, `porcentajeCobertura`, `ofertasJson` | Bonita → Nacional `POST /evaluaciones` |
| ¿Se cubrieron todos los lotes? | Bonita | Sí → Adjudicar; No → Evaluar Cobertura | — |
| **Evaluar Cobertura y Definir Curso de Acción** | Coordinador | Pantalla nueva: REFORMULAR o PARCIAL (setea `decisionCoordinador`) | App → Bonita (y App → Nacional `liberar` si reformula) |
| **Adjudicar Ofertas** | Municipio | Pantalla nueva: ve las ofertas validadas y elige; setea `ongsAdjudicadas` | App → Bonita |
| **Notificar Adjudicación y Registrar Compromiso Nacional** | Bonita (servicio) | Elegidas → `confirmar`; no elegidas → `liberar`; avisa a la app para notificar | Bonita → Nacional, Bonita → App |
| **Monitorear Ejecución del Despliegue** | Coordinador | Pantalla: estado de cada ONG adjudicada | App → Bonita |
| **Confirmar Finalización de Actividades** | ONGs | La ONG marca su actividad como finalizada | App → Bonita |
| **Validar Cierre Operativo Bilateral** | Coordinador | Confirma el cierre cuando todas terminaron | App → Bonita |
| **Liberar Recursos y Notificar Cierre** | Bonita (servicio) | `POST /cierres` por cada ONG adjudicada; avisa a la app | Bonita → Nacional, Bonita → App |

**A verificar en Studio antes de empezar** (en el `.bos` del repo, del 20/09): "Evaluar Cobertura y Definir Curso de
Acción" figura en la lane de la ONG, y debería estar en la del Coordinador (si no, Bonita la asigna al actor ONG). Lo
mismo con "Obtener Ofertas…" (es de servicio, da igual la lane). "Confirmar Finalización" es multi-instancia sin
configurar: ver WP6.

---

## 3. Contratos (acordarlos el primer día, antes de programar)

### 3.1 App local → Bonita: consolidado de ofertas

`GET /api/bonita/emergencias/{id}/ofertas` — protegido con un header `X-Api-Key` (secreto compartido en `.env` de la
app y en una variable/parámetro del proceso). Marca la emergencia `EN_EVALUACION`.

```json
{"emergencia_id": 12, "gravedad": "ALTO",
 "lotes": [{"lote_id": 31, "tipo_recurso": "PARAMEDICO", "cantidad": 10, "tipo": "PRINCIPAL"}],
 "ofertas": [{"cuit": "30-54666544-5", "ong": "Cruz Roja Argentina", "version": 3,
              "items": [{"lote_id": 31, "tipo_recurso": "PARAMEDICO", "cantidad": 4}]}]}
```

### 3.2 Bonita → API Nacional

| Endpoint | Para qué | Respuesta |
|---|---|---|
| `POST /evaluaciones` | Recibe el JSON de 3.1. Por cada ONG: valida (competencia + cantidades) y **reserva** con `FOR UPDATE` (referencia `emg-{id}:{cuit}`, estado `RESERVADA`). Idempotente por referencia | Resultado por ONG e ítem (nivel, asignación sugerida, cantidad reservada) + cobertura por lote + `cobertura_completa` + `porcentaje_cobertura` |
| `POST /adjudicaciones/{referencia}/confirmar` | Elegida por el Municipio | Estado `ADJUDICADA` |
| `POST /adjudicaciones/{referencia}/liberar` | No elegida, o reformular | Estado `LIBERADA`; resta lo comprometido |
| `POST /cierres` `{cuit, referencia}` | Fin de la actividad | Estado `CERRADA`; resta lo comprometido de **esa** referencia |

Se arma sobre lo de Leandro (`adjudicacion` + `adjudicacion_item`, locking ordenado, idempotencia): se le agrega el
estado y se pasa a CUIT y código de recurso (lo que conocen la app y Bonita), y `/cierres` se ata a la referencia.
Las tablas `compromiso*` (PR #6, sin uso) se borran con una migración.

### 3.3 Variables del proceso (ya existen)

`ofertasJson` (respuesta de `/evaluaciones`), `coberturaCompleta`, `porcentajeCobertura`, `decisionCoordinador`
(`REFORMULAR` | `PARCIAL`), `ongsAdjudicadas` (lista JSON de CUIT).

### 3.4 Bonita → App local: avisos para notificar

`POST /api/bonita/emergencias/{id}/eventos` `{"tipo": "ADJUDICACION" | "CIERRE"}` con `X-Api-Key`: la app crea las
notificaciones y actualiza estados.

### 3.5 Estados en la app local

- Emergencia: `REGISTRADA` → `CONVOCATORIA` → `CERRADA` (ventana vencida) → `EN_EVALUACION` → `ADJUDICACION` →
  `EN_EJECUCION` → `RESUELTA` (REFORMULAR vuelve a `REGISTRADA` con una ronda nueva).
- Oferta: vigente / retirada (hecho) → `ADJUDICADA` | `NO_ADJUDICADA` → `FINALIZADA`.
- Tabla nueva `notificacion` (usuario u ONG, texto, emergencia, leída).

---

## 4. Paquetes de trabajo y reparto (propuesta: ajustar con el equipo)

| WP | Qué | Responsable propuesto | Depende de | h |
|---|---|---|---|---|
| **WP0** | Contratos de la sección 3 por escrito y acordados; verificar lanes en Studio | Tomás (+ todos revisan) | — | 2 |
| **WP1** | App: `GET /api/bonita/.../ofertas` con `X-Api-Key`; estado `EN_EVALUACION`; el tope cuenta convocatorias vencidas hasta la evaluación | **Tomás** | WP0 | 4 |
| **WP2** | Nacional: `POST /evaluaciones` (valida + reserva + cobertura), estados de adjudicación, `confirmar`/`liberar` por referencia con CUIT y código, borrar `compromiso*` | **Leandro** (bloqueo) + **Tomás** (validación y cobertura) | WP0 | 8 |
| **WP3** | Nacional: `/cierres` atado a la referencia (libera lo de esa adjudicación) | **Franco C.** | WP2 | 3 |
| **WP4** | Bonita: conectores de los 4 ServiceTasks (REST si está en Studio; si no, conector de script Groovy con `HttpClient`), mover "Evaluar Cobertura" a la lane del Coordinador, exportar `.bos` | **Tomás** (tiene Studio) | WP1, WP2 | 8 |
| **WP5** | App + SPA: pantalla del Coordinador "Evaluar cobertura" (PARCIAL / REFORMULAR) y del Municipio "Adjudicar" (ofertas validadas con nivel y asignación sugerida) | **Franco V.** | WP0 | 8 |
| **WP6** | App + SPA: notificaciones de la ONG; "Marcar finalizada"; Coordinador "Monitorear" y "Validar cierre"; endpoint de eventos (3.4). Bonita: configurar la multi-instancia (cardinalidad desde `ongsAdjudicadas`) o simplificarla a una tarea que la app completa cuando terminaron todas | **Franco C.** | WP0 | 8 |
| **WP7** | Deploy: un solo Dockerfile (el de `dev`), redeploy en Render desde `dev`, Postgres confirmada, deploy hook, `verificar_despliegue.py` en verde contra la URL | **Fabrizio** | PR #8 | 4 |
| **WP8** | Docker Compose (Postgres + backend + frontend) a partir de `e3-leandro`; la app local en Postgres | **Leandro** | — | 4 |
| **WP9** | Pruebas end to end: script `escenario_completo.py`, `e2e_ui.py` ampliado, guía manual (sección 6) | **Tomás** | WP1–WP6 | 6 |
| **WP10** | Entrega: README de instalación, guion de demo, video de respaldo, prueba en limpio en otra PC | **Fabrizio** + todos | WP7, WP8 | 4 |
| WP11 | JWT (un token por usuario; emite la API Nacional; Bonita con cuenta de servicio). Base: rama `franco_v` | Franco V. (cuando se retome) | — | 8 |

### Cronograma

| Día | Qué |
|---|---|
| Jue 15/10 | WP0 (contratos) · WP7 arranca (deploy con PR #8) |
| Vie 16 – Sáb 17 | WP1, WP2, WP3, WP5, WP6, WP8 en paralelo |
| Dom 18 – Lun 19 | WP4 (conectores, ya con WP1/WP2) · integración |
| Mar 20 | WP9: escenarios completos, correcciones |
| Mié 21 | WP10: guía, demo, prueba en limpio, video |
| Jue 22 | Entrega |

Regla de trabajo: cada WP en su rama, PR a `dev` con tests en verde y probado contra servicios reales; no reescribir
migraciones ya mergeadas (agregar una nueva).

---

## 5. Entorno para probar (manual o con scripts)

1. **Bonita**: Studio → abrir el proyecto → Organización → **Desplegar** → proceso → **Ejecutar** (cada Ejecutar borra
   los casos). Portal: `http://localhost:8080/bonita` (`walter.bates` / `bpm`) para ver casos y tareas.
2. **API Nacional** (empezar limpio): en `nacional\`, borrar `nacional.db`, después
   `..\backend\.venv\Scripts\python -m alembic upgrade head`, `... -m app.seed` y `... -m uvicorn app.main:app --port 8002`.
   Swagger: `http://localhost:8002/docs`. **Para ver el inventario**: `GET /ongs/30-54666544-5` (total, comprometido,
   disponible).
3. **Backend**: en `backend\`, base limpia opcional (borrar `dev.db`), `.venv\Scripts\python -m alembic upgrade head`,
   `... -m app.seed`, `... -m uvicorn app.main:app --port 8001`.
4. **Frontend**: en `frontend\`, `npm run dev` → `http://localhost:5173`.
5. Usuarios: `operador.municipal`, `coordinador.regional`, `ong.cruzroja` (4 paramédicos, 3000 L de agua),
   `ong.bomberos` (6 paramédicos con certificación vencida, 12 rescatistas acuáticos), `auditor`. Clave `demo1234`.
6. Para ver el timer: publicar con el cierre **a 3 minutos**.
7. Para usar la nube: `NACIONAL_BASE_URL=https://sistema-nacional-latest.onrender.com` y
   `NACIONAL_TIMEOUT_SECONDS=60` en `backend\.env`; despertar antes con `/health`.

---

## 6. Escenarios end to end (guía manual)

Cada escenario: **pasos** (usuario → acción) y **qué verificar** en la SPA, en Swagger (inventario) y en el portal de
Bonita (tarea activa). La columna "Desde" dice cuándo se puede correr.

| # | Escenario | Desde |
|---|---|---|
| M1 | Alta y publicación | Hoy |
| M2 | Tope de inventario | Hoy |
| M3 | Editar y retirar | Hoy |
| M4 | El timer cierra la ventana | Hoy (va siempre a "Evaluar Cobertura") |
| M5 | Evaluación y reserva automática | WP1 + WP2 + WP4 |
| M6 | Cobertura completa → adjudicar | + WP5 |
| M7 | Cobertura incompleta → PARCIAL | + WP5 |
| M8 | Cobertura incompleta → REFORMULAR | + WP5 |
| M9 | Notificaciones | + WP6 |
| M10 | Ejecución y cierre bilateral | + WP3 + WP6 |
| M11 | Concurrencia | WP2 + Postgres |
| M12 | Fallas | Por partes |
| M13 | Permisos | Por partes |
| M14 | Todo contra la nube | WP7 |

**M1. Alta y publicación** — `operador.municipal`: Registrar emergencia (inundación, ALTO) → ver "Registrada" y el
caso de Bonita. Portal: tarea "Revisar…". `coordinador.regional`: abrir la emergencia → lote Paramédico × 10
(principal) y Agua potable × 5000 → Publicar con cierre a 3 min → "Convocatoria abierta". Portal: "Cargar Ofertas de
Ayuda".

**M2. Tope** (crear antes una 2ª emergencia publicada, igual que M1) — `ong.cruzroja`: ofrecer 2 paramédicos en la 1
→ OK. Ofrecer 3 en la 2 → "No alcanza tu inventario… sumás 5… tenés 4". Ofrecer 9000 L de agua → rechazo. Swagger: el
inventario **no cambia** (todavía es borrador).

**M3. Editar y retirar** — `ong.cruzroja`: editar la 1 a 3 → versión 2. En la 2, ofrecer 1 → OK (3 + 1 = 4). "Retirar
mi oferta" en la 1 → retirada; ahora en la 2 entra 4. `coordinador.regional`: ve la de Cruz Roja como retirada.

**M4. Timer** — esperar el cierre: la ONG ve "La ventana de ofertas cerró" y ya no puede ofertar. Portal: el caso pasó
a la validación (hoy termina en "Evaluar Cobertura" porque los pasos automáticos están vacíos).

**M5. Evaluación y reserva** — con Cruz Roja 4 paramédicos y Bomberos 2 en una emergencia que pide 10: al vencer, Swagger
muestra `comprometida = 4` en Cruz Roja y `2` en Bomberos (**reservado**). Cruz Roja intenta ofrecer paramédicos en
otra emergencia → rechazo (no tiene disponibles). Portal: `coberturaCompleta = false`, `porcentajeCobertura = 60`.

**M6. Cobertura completa** — ofertas que cubren todos los lotes → al vencer, Bonita va directo a "Adjudicar Ofertas".
`operador.municipal`: ve solo las validadas, con su nivel (PLENA/PARCIAL/SUPERVISADA) y asignación sugerida; elige
Cruz Roja, no Bomberos → Swagger: Cruz Roja sigue comprometida (`ADJUDICADA`), Bomberos vuelve a 0 (`LIBERADA`).

**M7. PARCIAL** — cobertura incompleta → `coordinador.regional` ve la cobertura por lote y elige "Seguir con cobertura
parcial" → el caso pasa a "Adjudicar Ofertas" → seguir como M6.

**M8. REFORMULAR** — `coordinador.regional` elige "Reformular" → Swagger: todas las reservas de esa emergencia vuelven
a 0; la emergencia vuelve a "Registrada" para cargar lotes nuevos y publicar otra vez; las ofertas de la ronda
anterior quedan en el historial.

**M9. Notificaciones** — después de M6: `ong.cruzroja` ve "Tu oferta fue seleccionada"; `ong.bomberos` ve "no fue
seleccionada" y puede ofertar esos recursos en otra emergencia.

**M10. Ejecución y cierre** — `coordinador.regional` ve el despliegue en curso. `ong.cruzroja`: "Marcar actividad
finalizada". Con todas finalizadas, el Coordinador "Valida el cierre" → Swagger: `comprometida = 0`, inventario como
al principio; `GET /ongs/{cuit}/cierres` muestra el cierre; la emergencia queda "Resuelta"; las ONGs reciben el aviso.
Portal: caso terminado ("Emergencia cerrada").

**M11. Concurrencia** — `POSTGRES_TEST_DATABASE_URL=… pytest nacional/tests/test_concurrencia_adjudicacion.py`
contra una Postgres (la de Render o una local con Docker): dos reservas simultáneas sobre el mismo stock → una pasa,
la otra 409.

**M12. Fallas** — API Nacional apagada: cargar lote y ofertar → 503 sin guardar (hoy); retirar anda (hoy). Al vencer el
timer con la API caída → la tarea de servicio queda fallida en el portal; al levantar la API, reintentarla desde el
portal → sigue el flujo. Bonita lento al dar de alta → no quedan casos huérfanos (hoy).

**M13. Permisos** — cada pantalla nueva solo para su rol (Municipio adjudica, Coordinador decide y cierra, ONG
finaliza); el Auditor ve todo y no opera; una ONG no ve las ofertas ni notificaciones de otra.

**M14. Contra la nube** — repetir M1–M10 con el backend apuntando a Render y Bonita llamando a la URL pública.

### Automatización

- `backend/scripts/escenario_tope.py` (hoy: M1–M4, 39 verificaciones) → ampliarlo o sumar `escenario_completo.py`
  con M5–M10 (Bonita real; completa las tareas de cada rol por la API de la app).
- `backend/scripts/e2e_ui.py` (navegador): sumar las pantallas nuevas.
- `nacional/scripts/verificar_despliegue.py <url>`: sumar evaluación, confirmar, liberar y cierre (con datos de prueba
  que deja el inventario como estaba).

---

## 7. Formato de entrega

Los profesores tienen que poder levantarlo y usarlo:

1. **Repositorio** (`main`) con todo: app, API Nacional, `.bos`, organización, scripts.
2. **API Nacional en Render**: URL + Swagger. Avisar que la primera llamada tarda ~45 s (plan gratis).
3. **`docker compose up`** levanta Postgres + backend + frontend (WP8). La API Nacional también puede correr en local con
   su `Dockerfile`.
4. **Bonita**: `RescueSync.bos` + `ACME.xml` y los pasos para importarlo, desplegar la organización y ejecutar.
5. **README de instalación** en la raíz: requisitos (Docker, Bonita Studio 2025.2, Node solo si no usan Docker),
   `.env.example`, comandos, usuarios y claves, cómo despertar la API, problemas comunes.
6. **Guion de demo** paso a paso (sección 6) y **video** de respaldo.
7. **Prueba en limpio** antes de entregar: alguien clona desde cero en otra PC y sigue el README al pie de la letra.

---

## 8. Riesgos y decisiones abiertas

- **Lane de "Evaluar Cobertura"**: verificar en Studio que sea del Coordinador.
- **Multi-instancia de "Confirmar Finalización"**: configurarla bien lleva tiempo; la alternativa simple es una tarea
  única que la app completa cuando todas las ONGs marcaron finalizada.
- **REFORMULAR** es el camino más caro (ronda nueva de ofertas): si no llega, dejarlo para la entrega final y decirlo.
- **Conectores**: si Studio no trae el conector REST, usar conector de script Groovy; probar temprano (WP4 es el de
  mayor riesgo).
- **Nube**: arranque en frío ~45 s; el conector de Bonita y el backend necesitan timeout largo.
- **Docker** no arranca en la PC de Tomás: la prueba del compose y la prueba en limpio las hace otro integrante.
- **Tiempo**: ~60 h de trabajo en 6 días repartidas entre 5. Si no alcanza, prioridad: WP7 → WP1/WP2/WP4 (lo que pide
  la Entrega 3: la API funcionando e integrada) → WP5 → WP6 → WP8/WP10.
