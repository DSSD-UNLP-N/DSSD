# Plan para cerrar la entrega: flujo completo, pruebas end to end, entrega y reparto

Revisado el 15/10 contra `modelado-tomas-e-3` (= `dev` + arreglo de migraciones, PR #8), el modelo de Bonita
(`entrega-2/RescueSync.bos`) y la consigna. Entrega: semana del 22/10.

---

## 1. Actores (quién es quién)

| Actor | Usuario de demo | En la app | En Bonita (lane / actor) | Tareas de Bonita |
|---|---|---|---|---|
| **Municipio** (Operador Municipal del municipio afectado) | `operador.municipal` | rol `MUNICIPIO`, municipio Bahía Blanca | lane "Municipio (Operador Municipal)", actor `Municipio` | Registrar Emergencia ✅, **Adjudicar Ofertas** ❌ |
| **Centro Coordinador Regional** | `coordinador.regional` | rol `COORDINADOR` | lane "Centro Coordinador Regional" | Revisar y Generar Lotes ✅, Publicar Convocatoria ✅, **Evaluar Cobertura** ❌, **Monitorear Ejecución** ❌, **Validar Cierre Operativo Bilateral** ❌ |
| **ONG** | `ong.cruzroja`, `ong.bomberos` | rol `ONG` | lane "ONG / Organismo de Rescate" | Cargar Ofertas (ancla del timer, la app nunca la completa), **Confirmar Finalización de Actividades** ❌ (multi-instancia) |
| **Sistema Nacional** | — | API `nacional/` | lane "Entidad Nacional / Sistema RescueSync" | 4 tareas automáticas (ServiceTasks), **todas vacías** ❌ |
| **Auditor / Directivo** | `auditor` | rol `AUDITOR`, solo lectura | — | — |

No hay "organizador": el **Municipio** es quien sufre la emergencia, la registra y **elige las ofertas** (consigna,
eslabón 5); el **Coordinador** arma los lotes, publica, y decide qué hacer si no se cubren (eslabón 2 y timer).

## 2. Qué dice la consigna sobre el flujo después de la ventana

- **Directiva 2**: Bonita administra la ventana con el timer; al vencer, avanza solo a una tarea de validación.
- **Directiva 3**: como Bonita no conoce las ofertas (viven en la app), **Bonita inicia la comunicación**: una tarea de
  servicio o conector hace un GET a un endpoint de la app local, que responde un JSON con todas las ofertas.
- **Directiva 4**: con ese JSON, **Bonita invoca a la API del Sistema Nacional** (con JWT); la API evalúa y, con control
  de concurrencia, **aplica los bloqueos** para evitar sobre-asignaciones. Al terminar la ejecución y marcarse el cierre
  en la app, se invoca la **liberación**.
- **Eslabón 4**: la API garantiza consistencia y bloqueo concurrente; las ofertas se adaptan a lote principal o apoyo.
- **Eslabón 5**: el **Municipio** ve solo las ofertas validadas y elige; el sistema **notifica** a las ONGs si fueron
  seleccionadas.
- **Eslabón 6**: tras adjudicar, se registra el **compromiso** en el Sistema Nacional (que la ONG no lo ofrezca en
  paralelo en otra emergencia).
- **Eslabón 7**: el Coordinador monitorea; las ONGs marcan sus actividades como finalizadas; la plataforma informa a la
  API y se **liberan** los recursos.
- **Directiva 1**: la API del Cloud **no guarda borradores ni ofertas preliminares**.
- **Servicio 4**: bloqueo/compromiso transaccional con locking en PostgreSQL. **Servicio 5**: liberación y cierre.

## 3. Modelo de reserva del recurso (decidido 15/10: "reservado hasta que se decida")

| Etapa | Dónde vive la reserva | Cómo |
|---|---|---|
| Ventana abierta (la ONG oferta, edita, retira) | **App local** | Tope por inventario: suma de ofertas activas vs disponible nacional (hecho) |
| Vence el timer → hasta que se decida | **Sistema Nacional, estado RESERVADO** | Bonita manda las ofertas a la API, que valida y bloquea (directiva 4). Ya no son borradores: no choca con la directiva 1 |
| Adjudicación | Nacional: elegidas → **COMPROMETIDO**; no elegidas → **LIBERADO** | Bonita, en "Notificar Adjudicación y Registrar Compromiso Nacional" |
| Reformular lotes | Nacional: todo lo reservado → **LIBERADO** | Bonita o la app al volver a "Revisar…" |
| Cierre bilateral | Nacional: comprometido → **LIBERADO** | Bonita, en "Liberar Recursos y Notificar Cierre" |

`disponible = total − (reservado + comprometido)`. Como el tope de la app ya usa el disponible nacional, una ONG no
puede reofertar en otra emergencia lo que quedó reservado esperando decisión. **La regla "reservado hasta que se decida"
se cumple sin que la app cuente convocatorias cerradas.**

## 4. Contratos (acordarlos primero: así cada uno trabaja en paralelo)

### 4.1 App local → Bonita (directiva 3)
`GET /api/integracion/emergencias/{id}/ofertas` (acceso: usuario técnico / token de servicio)
```json
{"referencia": "emergencia-12", "gravedad": "ALTO",
 "lotes": [{"id": 31, "tipo_recurso": "PARAMEDICO", "cantidad": 10, "tipo": "PRINCIPAL"}],
 "ofertas": [{"cuit": "30-54666544-5", "ong": "Cruz Roja Argentina", "version": 2,
              "items": [{"lote_id": 31, "tipo_recurso": "PARAMEDICO", "cantidad": 4}]}]}
```
Solo versiones vigentes, sin ofertas retiradas.

### 4.2 Bonita → API Nacional: reservar al vencer la ventana (servicios 3 + 4)
`POST /reservas` — evoluciona el `POST /adjudicaciones` actual (Leandro): con **CUIT y código de recurso** (lo que
conocen la app y Bonita), validación de competencia incluida, `FOR UPDATE` e idempotencia por `referencia` + CUIT.
```json
{"referencia": "emergencia-12", "gravedad": "ALTO",
 "items": [{"cuit": "30-54666544-5", "tipo_recurso": "PARAMEDICO", "cantidad": 4}]}
```
Respuesta: por (ONG, recurso) `solicitado`, `reservado` (puede ser menor si alguien ganó el stock), `nivel`,
`asignacion_sugerida`, `observaciones`.

### 4.3 Bonita → API Nacional: adjudicar
`POST /reservas/{referencia}/adjudicar` con `{"cuits": ["30-54666544-5"]}` → elegidas COMPROMETIDO, resto LIBERADO.

### 4.4 Bonita/app → API Nacional: reformular
`POST /reservas/{referencia}/liberar` → libera todo lo reservado de esa emergencia.

### 4.5 Bonita → API Nacional: cierre (servicio 5)
`POST /cierres` con `{"cuit", "referencia"}` → libera **lo que esa ONG tiene comprometido en esa referencia** (hoy libera
cantidades sueltas; atarlo a la reserva).

### 4.6 Variables de Bonita (ya existen en el modelo)
| Variable | La escribe | Uso |
|---|---|---|
| `ofertasJson` | ServiceTask "Obtener Ofertas…" | JSON de 4.1 |
| `coberturaCompleta`, `porcentajeCobertura` | ServiceTask "Validar… y Calcular Cobertura" | XOR "¿Se cubrieron todos los lotes?" |
| `decisionCoordinador` | App (pantalla Evaluar Cobertura) | `REFORMULAR` / `PARCIAL` |
| `ongsAdjudicadas` | App (pantalla Adjudicar) | JSON con los CUIT elegidos; cardinalidad de la multi-instancia |

Cobertura: por lote, `min(Σ reservado de sus ofertas, pedido) / pedido`; `porcentajeCobertura` = promedio ponderado por
cantidad pedida; `coberturaCompleta` = todos los lotes al 100 %.

### 4.7 Notificaciones (app local)
Tabla `notificacion` (destinatario ONG, emergencia, tipo, texto, leída, fecha) + bandeja en la SPA. Se crean al:
publicar convocatoria (a todas las ONGs), adjudicar (seleccionada / no seleccionada), cerrar (recursos liberados).

## 5. Trabajo a hacer

| ID | Tarea | Parte | Depende de | h |
|---|---|---|---|---|
| **N1** | `POST /reservas` + `/adjudicar` + `/liberar` (estados RESERVADO/COMPROMETIDO/LIBERADO, CUIT + código, `FOR UPDATE`, idempotencia); sacar tablas `compromiso*`; tests (incluido concurrencia en Postgres) | API Nacional | contrato 4.2-4.4 | 10 |
| **N2** | `/cierres` atado a la reserva comprometida (CUIT + referencia) + tests | API Nacional | N1 | 4 |
| **A1** | `GET /api/integracion/emergencias/{id}/ofertas` + acceso de servicio + tests | App | contrato 4.1 | 3 |
| **A2** | Estados nuevos de la emergencia (`EN_EVALUACION`, `ADJUDICADA`, `EN_EJECUCION`, `RESUELTA`) leyendo la tarea activa de Bonita | App | — | 3 |
| **A3** | Pantalla Coordinador "Evaluar cobertura": cobertura por lote, REFORMULAR / PARCIAL → `decisionCoordinador` + completa la tarea | App + SPA | A2, B2 | 5 |
| **A4** | Pantalla Municipio "Adjudicar": ofertas validadas (nivel, principal/apoyo), elegir ONGs → `ongsAdjudicadas` + completa la tarea; marca ofertas adjudicadas / no adjudicadas | App + SPA | A2, B2 | 6 |
| **A5** | Notificaciones (tabla + bandeja de la ONG) | App + SPA | A4 | 4 |
| **A6** | Ejecución y cierre: Coordinador "Monitorear" (completa la tarea); ONG "Marcar actividad finalizada" (su instancia); Coordinador "Validar cierre bilateral" | App + SPA | B3 | 6 |
| **B1** | Parámetros de proceso (`APP_URL`, `NACIONAL_URL`, credenciales) | Bonita | — | 1 |
| **B2** | Conectores (script Groovy con HTTP) en "Obtener Ofertas" (GET A1) y "Validar… y Calcular Cobertura" (POST N1 + cobertura) | Bonita | A1, N1 | 8 |
| **B3** | Conectores en "Notificar Adjudicación y Registrar Compromiso" (N1 adjudicar) y "Liberar Recursos y Notificar Cierre" (N2); flujo por defecto del XOR "Curso de acción"; liberar al REFORMULAR | Bonita | N1, N2 | 6 |
| **B4** | Multi-instancia "Confirmar Finalización de Actividades": una instancia por CUIT de `ongsAdjudicadas` | Bonita | A4 | 3 |
| **B5** | Exportar el `.bos` a `entrega-3/RescueSync.bos` y comparar con `test_bonita_contract.py` | Bonita | B1-B4 | 1 |
| **D1** | Unificar Dockerfile (quedarse con el de `dev`), Docker Compose con Postgres + backend + frontend (partir de `e3-leandro`), `.env.example` | Deploy | — | 6 |
| **D2** | Render: servicio oficial desde `dev`, Postgres confirmada, deploy hook; `verificar_despliegue.py` | Deploy | PR #8 | 3 |
| **D3** | Guía de instalación para los profesores + guion de demo + video de respaldo | Entrega | todo | 5 |
| **T1** | `escenario_completo.py`: los escenarios de la sección 6 automatizados contra Bonita real | Pruebas | A*, B*, N* | 6 |
| **J1** | JWT (servicio 1): `/login` y registro de ONGs en la API Nacional, un token por usuario, cuenta de servicio para Bonita | API Nacional | — | 10 (en pausa) |

Total sin JWT: ~83 h. Con 5 personas a ~8 h en la semana, entra justo: **acordar los contratos (sección 4) el primer
día** es lo que permite trabajar en paralelo.

### Cronograma sugerido
| Día | Hito |
|---|---|
| 16/10 | Contratos acordados. Arrancan N1, A1, A2, B1, D1 en paralelo |
| 17-19/10 | N1, N2, A3, A4, A5, B2, B3, B4, D1 |
| 20/10 | A6; integración completa en `dev`; escenarios manuales S1-S8 |
| 21/10 | T1 automatizado; deploy (D2); escenarios contra la nube |
| 22/10 | Guía (D3), ensayo en una PC limpia, entrega |

### Reparto propuesto (ajustar con el equipo)
| Persona | Tareas | Por qué |
|---|---|---|
| **Tomás** | B1-B5 (Bonita) + A1 + T1 | Hizo la integración con Bonita y el modelo de validación |
| **Leandro** | N1 (+ test de concurrencia en Postgres) | Hizo el bloqueo (`/adjudicaciones`) |
| **Franco Cirielli** | N2 + A6 | Hizo `/cierres` |
| **Franco Viscardi** | A2 + A3 + A4 + A5 (pantallas de la app) y después J1 | Trabajó en el backend y en JWT |
| **Fabrizio** | D1 + D2 + D3 | Hizo el empaquetado y el deploy |

---

## 6. Pruebas end to end

### 6.1 Puesta a punto (una vez por sesión de pruebas)

Cuatro terminales, desde `E:\DSSD`. **`DATABASE_URL` solo en la terminal de su servicio.**

1. **Bonita**: en Studio, desplegar la organización y **Ejecutar** el proceso (borra los casos anteriores).
2. **API Nacional limpia** (terminal 1, en `nacional\`):
   ```powershell
   Remove-Item nacional.db -ErrorAction SilentlyContinue
   ..\backend\.venv\Scripts\python -m alembic upgrade head
   ..\backend\.venv\Scripts\python -m app.seed
   ..\backend\.venv\Scripts\python -m uvicorn app.main:app --port 8002
   ```
3. **App local con base limpia** (terminal 2, en `backend\`):
   ```powershell
   $env:DATABASE_URL = "sqlite:///E:/DSSD/backend/e2e.db"
   Remove-Item e2e.db -ErrorAction SilentlyContinue
   .venv\Scripts\python -m alembic upgrade head
   .venv\Scripts\python -m app.seed
   .venv\Scripts\python -m uvicorn app.main:app --port 8001
   ```
4. **SPA** (terminal 3, en `frontend\`): `npm run dev` → `http://localhost:5173`.
5. **Para mirar** (terminal 4 / navegador):
   - Inventario nacional: `http://localhost:8002/docs` → `GET /ongs/{cuit}` (columnas comprometido / disponible).
   - Bonita: portal `http://localhost:8080/bonita` (usuario `walter.bates` / `bpm`) → casos y tareas.
   - Contra la nube: en la terminal 2, antes de levantar: `$env:NACIONAL_BASE_URL = "https://sistema-nacional-latest.onrender.com"`
     y `$env:NACIONAL_TIMEOUT_SECONDS = "60"`; despertarla antes abriendo `/health`.

Datos de partida (seed nacional): **Cruz Roja** 4 paramédicos (certificación hasta MEDIO), 3000 L de agua, 5000 raciones;
**Bomberos** 6 paramédicos (certificación **vencida**), 12 rescatistas acuáticos (hasta CRITICO), 20 brigadistas (hasta
ALTO). Usuarios de la app: clave `demo1234`; de Bonita: clave `bpm`.

### 6.2 Escenarios (manuales; ✅ = ya se puede probar hoy)

| # | Escenario | Pasos | Resultado esperado |
|---|---|---|---|
| **S1** ✅ | Tope al ofertar | Municipio registra 2 emergencias; Coordinador carga en cada una un lote "Paramédico ×10" y publica (cierre en 2 h). Cruz Roja ofrece 2 en la 1 y 3 en la 2 | La 2 se rechaza: "sumás 5 personas y tenés 4" |
| **S2** ✅ | Editar y retirar | Cruz Roja edita la 1 a 3 (OK), ofrece 1 en la 2 (OK), retira la 1 y sube la 2 a 4 | Editar reemplaza; retirar libera el cupo |
| **S3** ✅ | Competencia | Swagger `POST /validaciones` gravedad ALTO: Cruz Roja paramédicos; Bomberos paramédicos; Bomberos rescatistas en CRITICO | PARCIAL→APOYO; SUPERVISADA (vencida); PLENA→PRINCIPAL |
| **S4** | Vence la ventana → reserva nacional | Publicar con cierre a 2 min; Cruz Roja ofrece 4 paramédicos; esperar el cierre | Bonita pasa por los 2 ServiceTasks; en `GET /ongs/{cuit}` Cruz Roja queda con 4 reservados, disponible 0; la emergencia aparece "En evaluación" |
| **S5** | Reservado hasta que se decida | Con S4 sin decidir, Cruz Roja intenta ofertar paramédicos en otra convocatoria abierta | Rechazo: disponible 0 |
| **S6** | Cobertura completa → adjudicar | Lote ×4, Cruz Roja ofrece 4, vence | XOR va directo a "Adjudicar Ofertas"; el Municipio ve la oferta (nivel y principal/apoyo) y la elige → comprometida en nacional; Cruz Roja recibe "seleccionada" |
| **S7** | Oferta no elegida se libera | Lote ×6; Cruz Roja ofrece 4 y Bomberos 6; vence (cobertura completa); el Municipio elige solo Bomberos | Bomberos comprometido; Cruz Roja liberada (disponible vuelve a 4) y notificada "no seleccionada"; puede ofertar en otra emergencia |
| **S8** | Cobertura parcial → PARCIAL | Lote ×10, solo Cruz Roja ofrece 4; vence | Va a "Evaluar Cobertura" (40 %); Coordinador elige PARCIAL → Municipio adjudica |
| **S9** | Cobertura parcial → REFORMULAR | Igual que S8, el Coordinador elige REFORMULAR | Reservas liberadas; el caso vuelve a "Revisar…"; el Coordinador carga lotes nuevos y vuelve a publicar |
| **S10** | Sin ofertas | Publicar y no ofertar | Cobertura 0 % → "Evaluar Cobertura" |
| **S11** | Ejecución y cierre bilateral | Desde S7: Coordinador "Monitorear" → Bomberos "Marcar actividad finalizada" → Coordinador "Validar cierre" | Bonita llega a "Emergencia cerrada"; nacional libera lo comprometido (inventario como al principio); emergencia "Resuelta"; notificación de cierre |
| **S12** | Concurrencia | Dos emergencias con cierre al mismo minuto, la misma ONG ofreciendo todo su stock en ambas (forzando por API) | Una reserva completa, la otra parcial o nada; nunca comprometido > total (test de Postgres de N1) |
| **S13** | Reintentos / idempotencia | Reintentar un conector fallido desde el portal de Bonita; repetir adjudicar o cierre | No descuenta dos veces |
| **S14** | Fallas | API Nacional apagada al vencer el timer | El ServiceTask queda en error en Bonita; al levantarla y reintentar, sigue el flujo |
| **S15** | Permisos | Cada rol intenta las acciones de otro (adjudicar, decidir cobertura, marcar finalizada) | 403 y sin botones en la SPA |
| **S16** | Todo contra la nube | S4, S6, S11 con `NACIONAL_BASE_URL` = Render | Igual que en local |

T1 automatiza S1-S11, S13 y S15 (`escenario_completo.py`); S12 queda en el test de Postgres de Leandro.

---

## 7. Formato de entrega

- **API Nacional**: URL de Render + Swagger, y su `Dockerfile` para correrla en local.
- **App + base**: `docker compose up` (Postgres + backend + frontend, y opcional la API Nacional en local). Postgres
  dockerizada suma puntaje según la consigna.
- **Bonita**: `RescueSync.bos` + organización, con los pasos para importar en Studio y ejecutar (los profesores usan
  Studio en la materia).
- **README de instalación** en la raíz: requisitos, `docker compose up`, Bonita, variables (`.env.example`), usuarios y
  claves, cómo despertar Render, problemas comunes.
- **Guion de demo** con los escenarios S1-S11 y video de respaldo.
- **Ensayo en limpio**: alguien con Docker funcionando clona el repo y sigue la guía al pie de la letra.

## 8. JWT (en pausa)

Un token por usuario (lleva id y rol; cada endpoint chequea el rol). Lo emite la API Nacional (`/login` + registro de
ONGs, como pide la consigna); la app guarda el del usuario y lo manda en cada llamada; Bonita usa una cuenta de servicio.
La rama `franco_v` lo hizo en la app local: sirve de base, hay que llevarlo a `nacional/` y adaptar la SPA.

## 9. PostgreSQL

Nube: obligatorio (servicio 4, locking). Local: recomendado y con puntaje extra si está dockerizado; además hace
efectivos los bloqueos de fila de la app (SQLite los ignora). Hoy la app local usa SQLite → lo resuelve D1.
