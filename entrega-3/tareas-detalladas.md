# Tareas para cerrar la Entrega 3, en detalle

Acompaña a `plan-cierre-entrega.md` (diseño, contratos, escenarios). Cada tarea dice: para qué sirve, qué hay hoy,
qué hay que hacer, cuándo está terminada y cómo se prueba. Los responsables se asignan después.

**Reglas para todos**
- Una rama por tarea, PR a `dev`, tests en verde y probado contra servicios reales antes de pedir merge.
- **Migraciones**: nunca editar ni renombrar una ya mergeada; siempre una nueva. Antes de mergear, traer `dev`
  y correr `pytest` (el test `test_hay_una_sola_cabeza_de_migraciones` detecta dos tareas que agregaron migraciones a
  la vez). En la app local, todas las tablas y estados nuevos van en **una sola migración (WP1)** para no chocar.
- Probar a mano con la guía de la sección 6 del plan.

---

## WP0 — Contratos y chequeos previos

**Para qué**: que cinco personas puedan programar en paralelo sin pisarse. Si el JSON que manda Bonita no es el que
espera la API, la integración falla el último día.

**Qué hay que hacer**
1. Escribir `entrega-3/contratos.md` con los ejemplos exactos (request y response, códigos de error) de:
   - `GET /api/bonita/emergencias/{id}/ofertas` (app → Bonita) y el header `X-Api-Key`;
   - `POST /evaluaciones`, `POST /adjudicaciones/{referencia}/confirmar`, `.../liberar`, `POST /cierres` (API Nacional);
   - `POST /api/bonita/emergencias/{id}/eventos` (Bonita → app);
   - formato de la referencia (`emg-{emergencia_id}:{cuit}`), variables de Bonita y estados de la app.
2. En **Bonita Studio**:
   - que "Evaluar Cobertura y Definir Curso de Acción" esté en la lane del **Coordinador** (en el `.bos` del repo
     figura en la de la ONG);
   - ver si Studio trae el **conector REST** (Extensiones). Si no, se usa un conector de script Groovy;
   - exportar el `.bos` actual al repo: el de `entrega-2/` es del 20/09 y no tiene los cambios posteriores.
3. Pasarlo al equipo por PR y acordarlo.

**Terminado cuando**: `contratos.md` mergeado y todos de acuerdo; `.bos` actualizado en el repo.
**Estimación**: 2 h.

---

## WP1 — App local: consolidado de ofertas para Bonita y reserva hasta la evaluación

**Para qué**: la directiva 3 dice que, al vencer el timer, Bonita le pide las ofertas a la app. Además, entre que vence
la ventana y Bonita reserva en la API Nacional, la ONG no tiene que poder reofertar lo mismo en otra emergencia.

**Qué hay hoy**: `services/ofertas.py` aplica el tope sumando las ofertas de convocatorias **abiertas**; cuando vence la
ventana dejan de contar. No hay endpoint para Bonita. Estados de emergencia: `REGISTRADA`, `CONVOCATORIA`, `CERRADA`.

**Qué hay que hacer**
1. **Migración `0005` de la app (única para todo el plan)**:
   - estados nuevos de emergencia: `EN_EVALUACION`, `ADJUDICACION`, `EN_EJECUCION`, `RESUELTA`;
   - estado de la oferta: `ADJUDICADA`, `NO_ADJUDICADA`, `FINALIZADA` (además de vigente/retirada que ya existen);
   - tabla `notificacion` (`id`, `ong_id` o `usuario_id`, `emergencia_id`, `texto`, `creada_en`, `leida`) para WP6.
2. **Clave compartida con Bonita**: `bonita_api_key` en `core/config.py` y `.env.example`; dependencia que valida el
   header `X-Api-Key` (comparación segura) → 401 si falta o no coincide.
3. **`GET /api/bonita/emergencias/{id}/ofertas`**:
   - devuelve gravedad, lotes con su tipo de recurso y las ofertas **vigentes** (versión actual, no retiradas) con
     el CUIT de cada ONG, en el formato del contrato;
   - pasa la emergencia a `EN_EVALUACION`;
   - si Bonita reintenta, responde lo mismo (idempotente).
4. **Tope hasta la evaluación**: el tope suma también las ofertas de convocatorias **vencidas que todavía no pasaron a
   `EN_EVALUACION`**. Desde `EN_EVALUACION` deja de contarlas porque la reserva ya está en la API Nacional.

**Terminado cuando**
- Sin clave o con clave mala → 401. Con clave → el JSON del contrato, sin ofertas retiradas ni versiones viejas.
- Con la ventana vencida y antes de la evaluación, la ONG no puede reofertar lo mismo en otra emergencia; después de
  la evaluación tampoco (por el disponible nacional), sin contar doble.

**Pruebas**: tests de la API (permisos, contenido, idempotencia, estados) y del tope en cada estado. A mano: `curl`
con el header y ver el JSON.
**Depende de**: WP0. **Bloquea a**: WP4. **Estimación**: 4 h.

---

## WP2 — API Nacional: evaluación con reserva, y confirmar o liberar

**Para qué**: eslabón 4 y directiva 4: al vencer la ventana, la API valida cada oferta y **bloquea** los recursos
hasta que se decida. Después, lo elegido queda comprometido (eslabón 6) y lo no elegido se libera.

**Qué hay hoy**: `POST /adjudicaciones` (Leandro) compromete con `FOR UPDATE` e idempotencia, pero sin estados y con
ids internos (`ong_id`, `inventario_id`). `POST /validaciones` valida sin guardar nada. Tablas `compromiso*` sin uso.

**Qué hay que hacer**
1. **Migración nueva** (sin tocar las anteriores): columna `estado` en `adjudicacion` (`RESERVADA`, `ADJUDICADA`,
   `LIBERADA`, `CERRADA`; las filas existentes quedan `ADJUDICADA`) y borrar las tablas `compromiso*` (y sus modelos).
2. **`POST /evaluaciones`** (`services/evaluacion.py`), recibe el JSON del contrato:
   - por cada ONG: valida con las mismas reglas de `/validaciones` (competencia y cantidad) y **reserva** con bloqueo
     de filas ordenado lo que ofreció (referencia `emg-{id}:{cuit}`, estado `RESERVADA`). Si no alcanza el disponible
     (no debería pasar por el tope local), reserva lo que hay y lo informa;
   - calcula la **cobertura por lote** (lo reservado sobre lo pedido), el porcentaje total y si está completa;
   - devuelve todo en el formato del contrato: es lo que el Municipio ve como "ofertas validadas";
   - idempotente: si Bonita reintenta, no reserva dos veces.
3. **`POST /adjudicaciones/{referencia}/confirmar`**: `RESERVADA` → `ADJUDICADA` (idempotente; 409 si ya estaba
   liberada).
4. **`POST /adjudicaciones/{referencia}/liberar`**: `RESERVADA` (o `ADJUDICADA` sin cerrar) → `LIBERADA`; resta lo
   comprometido con bloqueo de filas (idempotente).
5. Pasar `POST /adjudicaciones` a CUIT y código de recurso, o dejar solo los endpoints nuevos (decidirlo en WP0).
6. Sumar estos pasos a `nacional/scripts/verificar_despliegue.py` con datos de prueba que dejan el inventario igual.

**Terminado cuando**
- Evaluar baja el disponible exactamente en lo ofrecido; repetir la evaluación no cambia nada.
- Confirmar y liberar respetan las transiciones; liberar devuelve el stock.
- La cobertura da bien en los casos completa, parcial y sin ofertas.
- El test de concurrencia (dos reservas a la vez sobre el mismo stock) pasa contra una Postgres.

**Depende de**: WP0. **Bloquea a**: WP3, WP4, WP5. **Estimación**: 8 h.

---

## WP3 — API Nacional: cierre atado a la adjudicación

**Para qué**: servicio 5 y eslabón 7: al terminar la actividad se libera **exactamente** lo que se comprometió para esa
emergencia y ONG.

**Qué hay hoy**: `POST /cierres` (Franco) libera por CUIT, referencia e ítems, pero no sabe qué se comprometió: puede
liberar stock de otra adjudicación.

**Qué hay que hacer**
1. `POST /cierres` recibe `{cuit, referencia}`: busca la adjudicación `ADJUDICADA` de esa referencia, resta sus ítems
   con bloqueo de filas, la pasa a `CERRADA` y guarda el cierre (con los ítems que liberó).
2. Repetir el cierre de la misma referencia → no vuelve a restar (idempotente). Sin adjudicación confirmada → 409.
3. Mantener `GET /cierres/{id}` y `GET /ongs/{cuit}/cierres`.

**Terminado cuando**: reservar → confirmar → cerrar deja el inventario como al principio; no se puede cerrar algo no
adjudicado ni dos veces.
**Depende de**: WP2. **Estimación**: 3 h.

---

## WP4 — Bonita: conectores de los pasos automáticos

**Para qué**: hoy los cuatro pasos automáticos están vacíos, así que el proceso siempre cae en "Evaluar Cobertura" y
nunca habla con la API. La consigna exige que Bonita inicie la comunicación.

**Qué hay que hacer (en Studio)**
1. **Parámetros del proceso**: `appBaseUrl` (`http://localhost:8001`), `nacionalBaseUrl` (local o Render) y
   `bonitaApiKey`, para cambiar de entorno sin tocar el diagrama.
2. **"Obtener Ofertas de la Red"**: GET a `{appBaseUrl}/api/bonita/emergencias/{emergenciaId}/ofertas` con el header
   → guarda el cuerpo en `ofertasJson`.
3. **"Validar en Sistema Nacional y Calcular Cobertura"**: POST a `{nacionalBaseUrl}/evaluaciones` con `ofertasJson` →
   lee la respuesta (Groovy `JsonSlurper`) y setea `coberturaCompleta`, `porcentajeCobertura` y `ofertasJson` (ahora
   con el resultado). La compuerta "¿Se cubrieron todos los lotes?" ya usa `coberturaCompleta`.
4. **"Notificar Adjudicación y Registrar Compromiso Nacional"**: por cada ONG evaluada, `confirmar` si está en
   `ongsAdjudicadas` y `liberar` si no; después POST a la app `/api/bonita/emergencias/{id}/eventos`
   `{"tipo": "ADJUDICACION"}`.
5. **"Liberar Recursos y Notificar Cierre"**: `POST /cierres` por cada ONG adjudicada; después evento `CIERRE` a la app.
6. Mover "Evaluar Cobertura y Definir Curso de Acción" a la lane del Coordinador (si WP0 lo confirma).
7. Timeout de los conectores ≥ 60 s (la nube tarda en despertar).
8. Exportar el `.bos` al repo y anotar en `entrega-2/CAMBIOS-BONITA.md` (o uno nuevo de la E3) qué se cambió.

**Terminado cuando**: un caso real recorre todo el proceso y en el portal se ven las variables bien seteadas; con la
API apagada, la tarea de servicio queda fallida y al reintentarla desde el portal el flujo sigue.
**Riesgo**: es la tarea más incierta (conectores, Groovy, red entre Bonita y las APIs). Probar el primer conector el
primer día.
**Depende de**: WP1, WP2 (WP3 y WP6 para los dos últimos pasos). **Estimación**: 8 h.

---

## WP5 — App: el Coordinador decide y el Municipio adjudica

**Para qué**: eslabón 5 y camino alternativo del timer. Hoy el caso llega a "Evaluar Cobertura" o a "Adjudicar
Ofertas" y nadie puede seguir porque la app no tiene esas pantallas.

**Qué hay que hacer**
1. **`GET /api/emergencias/{id}/evaluacion`** (Coordinador, Municipio, Auditor): lee `ofertasJson` del caso de Bonita
   y devuelve la cobertura por lote y el resultado por ONG (nivel, asignación sugerida, cantidades reservadas).
2. **`POST /api/emergencias/{id}/decision`** (Coordinador) `{"decision": "PARCIAL" | "REFORMULAR"}`:
   - exige que la tarea "Evaluar Cobertura" esté pendiente;
   - setea `decisionCoordinador` y completa la tarea como el coordinador;
   - **REFORMULAR**: libera todas las reservas de la emergencia en la API Nacional, retira las ofertas de esa ronda
     (versión vacía, queda el historial) y vuelve la emergencia a `REGISTRADA` para cargar lotes y publicar de nuevo.
3. **`POST /api/emergencias/{id}/adjudicar`** (Municipio) `{"cuits": [...]}`:
   - exige la tarea "Adjudicar Ofertas" pendiente y que los CUIT estén entre los evaluados;
   - setea `ongsAdjudicadas`, completa la tarea como el operador, marca las ofertas `ADJUDICADA` / `NO_ADJUDICADA` y
     pasa la emergencia a `ADJUDICACION`. (Confirmar o liberar en la API lo hace Bonita en WP4.)
4. **SPA** (detalle de la emergencia):
   - Coordinador: panel "Cobertura" con barras por lote y botones "Seguir con cobertura parcial" / "Reformular lotes";
   - Municipio: tabla de ofertas validadas (ONG, recurso, cantidad, nivel, asignación sugerida) con casillas y botón
     "Adjudicar seleccionadas".

**Terminado cuando**: cada acción solo la puede hacer su rol; sin la tarea pendiente responde 400; reformular deja el
inventario libre y la emergencia lista para otra ronda; adjudicar deja los estados correctos.
**Pruebas**: tests con Bonita y la API Nacional simuladas (como los de hoy) y escenarios M6–M8 a mano.
**Depende de**: WP0 (se puede programar con datos simulados), WP4 para probarlo de punta a punta. **Estimación**: 8 h.

---

## WP6 — App: notificaciones, ejecución y cierre bilateral

**Para qué**: eslabones 5 y 7, y el perfil ONG de la consigna ("visualizar notificaciones de adjudicación… marcar
actividades como finalizadas").

**Qué hay que hacer**
1. **`POST /api/bonita/emergencias/{id}/eventos`** (con `X-Api-Key`):
   - `ADJUDICACION` → notificación a cada ONG ("tu oferta fue seleccionada" / "no fue seleccionada") y emergencia
     `EN_EJECUCION`;
   - `CIERRE` → emergencia `RESUELTA` y notificación de cierre a las ONGs adjudicadas.
2. **`GET /api/notificaciones`** (las del usuario o su ONG) y **`POST /api/notificaciones/{id}/leida`**.
3. **Coordinador "Monitorear ejecución"**: ve las ONGs adjudicadas y su estado; un botón completa "Monitorear Ejecución
   del Despliegue" (habilita que las ONGs finalicen).
4. **ONG "Marcar actividad finalizada"** (`POST /api/emergencias/{id}/finalizar`): marca su oferta `FINALIZADA`.
5. **"Confirmar Finalización de Actividades"** en Bonita: hoy es multi-instancia sin configurar. Opción simple
   (recomendada): convertirla en tarea común que la app completa cuando **todas** las ONGs adjudicadas finalizaron.
   Opción completa: multi-instancia con cardinalidad desde `ongsAdjudicadas` y que la app complete la instancia de cada
   ONG.
6. **Coordinador "Validar cierre bilateral"**: habilitado cuando todas finalizaron; completa la tarea → Bonita libera
   (WP4) y avisa con el evento `CIERRE`.
7. **SPA**: campana de notificaciones con contador para la ONG; botones de cada rol en el detalle.

**Terminado cuando**: después de adjudicar, cada ONG ve su notificación; tras finalizar y validar el cierre, la
emergencia queda "Resuelta", el inventario nacional vuelve al inicio y el caso de Bonita termina.
**Depende de**: WP0 (WP1 para la migración), WP3 y WP4 para probarlo entero. **Estimación**: 8 h.

---

## WP7 — Deploy de la API Nacional

**Para qué**: la entrega pide la API desplegada con URL y Swagger. Hoy la nube corre código viejo y con el de `dev`
no arrancaba (lo arregla el PR #8).

**Qué hay que hacer**
1. Mergear el PR #8 a `dev`.
2. En Render: ver de dónde se construye `sistema-nacional-latest` (repo, rama, carpeta, Dockerfile) y apuntarlo a `dev`
   con `nacional/Dockerfile` (o crear el servicio desde `render.yaml` y quedarse con ese).
3. Confirmar que `DATABASE_URL` es una **Postgres** (si es SQLite, los datos se pierden en cada deploy y no hay locking
   real): crearla en Render y configurarla.
4. Cargar el deploy hook como secret `RENDER_DEPLOY_HOOK_URL` en GitHub para que cada push a `dev`/`main` despliegue.
5. Quedarse con **un** Dockerfile: el de `dev`. Descartar los de `cloud-deploy-fabri` y los archivos vacíos de `leandro`.
6. Verificar: `python nacional/scripts/verificar_despliegue.py <url>` en verde.

**Terminado cuando**: la URL responde con todos los endpoints actuales, sobre Postgres, y un push a `dev` la actualiza.
**Estimación**: 4 h.

---

## WP8 — Docker Compose y Postgres en local

**Para qué**: que los profesores levanten todo con un comando, y el puntaje extra por Postgres dockerizada.

**Qué hay que hacer**
1. Partir del `docker-compose.yml` de la rama `e3-leandro`.
2. Servicios: `db` (Postgres 16 con volumen y healthcheck; un script crea las dos bases), `nacional` (su Dockerfile),
   `backend` (Dockerfile que migra y carga el seed al arrancar), `frontend` (build de Vite servido con un proxy de
   `/api` al backend).
3. Variables: el backend apunta a `nacional` por nombre de servicio y a Bonita por `host.docker.internal:8080`.
4. Correr una vez los tests del backend contra Postgres (enums con CHECK, bloqueo de filas).
5. Documentarlo en el README.

**Terminado cuando**: en una PC limpia con Docker, `docker compose up` deja la app en `:5173`, la API en `:8002`, y el
recorrido completo anda con Bonita en el host.
**Estimación**: 4 h. **Nota**: en la PC de Tomás Docker no arranca; lo prueba otro integrante.

---

## WP9 — Pruebas end to end

**Para qué**: la consigna espera que todo funcione de punta a punta; esto lo demuestra y deja la evidencia.

**Qué hay que hacer**
1. **`backend/scripts/escenario_completo.py`** (Bonita real + API Nacional): crea la emergencia, lotes, publica con
   ventana corta, ofertas de dos ONGs, espera el timer y la evaluación de Bonita, verifica las reservas en la API,
   decide (PARCIAL), adjudica (una sí, otra no), verifica compromiso y liberación, notificaciones, monitoreo,
   finalización, cierre, inventario de vuelta al inicio y caso terminado. Variantes: cobertura completa, REFORMULAR, y
   API caída durante la evaluación.
2. Ampliar `e2e_ui.py` con las pantallas nuevas.
3. Mantener `escenario_tope.py` y `verificar_despliegue.py` en verde.
4. Guía manual (sección 6 del plan) actualizada a lo que realmente quedó.

**Terminado cuando**: todos los escenarios pasan en local y contra la nube; resultados anotados en
`plan-pruebas-nube.md`.
**Depende de**: WP1–WP6. **Estimación**: 6 h.

---

## WP10 — Preparar la entrega

**Qué hay que hacer**
1. **README en la raíz**: qué es cada parte, requisitos, `docker compose up`, cómo importar el `.bos`, `.env.example`,
   usuarios y claves, URL de la API y cómo despertarla, problemas comunes.
2. **Guion de demo** actualizado (el de la Entrega 2 + lo nuevo) y **video** corto de respaldo.
3. **Prueba en limpio**: alguien clona el repo desde cero en otra PC y sigue el README tal cual.
4. Lista de entregables: URL de la API, link al Swagger, repositorio, Dockerfile; mergear `dev` a `main`.

**Estimación**: 4 h.

---

## WP11 — JWT (cuando se retome)

**Para qué**: servicio 1 de la consigna: `/login` con JWT y registro de ONGs en la API Nacional.

**Qué hay que hacer**
1. En la API Nacional: tabla de cuentas (usuario, clave hasheada, rol, ONG), `POST /login` → token con usuario, rol y
   vencimiento; `POST /ongs` para el registro (crea la ONG y su cuenta).
2. Proteger cada endpoint según el rol (catálogo: cualquier token; inventario: la propia ONG; evaluación, adjudicación
   y cierre: la cuenta de servicio de Bonita).
3. Un token por usuario: al loguearse en la app, la app obtiene el token de ese usuario en la API Nacional y lo manda en
   cada llamada; Bonita usa su cuenta de servicio (credenciales como parámetros del proceso).
4. Base: la rama `franco_v` (JWT en la app local) sirve como punto de partida.

**Estimación**: 8 h.
