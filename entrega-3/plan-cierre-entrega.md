# Plan para cerrar la entrega: flujo completo, pruebas end to end y formato de entrega

Revisado el 15/10 contra el código de `modelado-tomas-e-3` (= `dev` + arreglo de migraciones, PR #8) y la consigna.

## 1. Ciclo de vida de un recurso: qué está hecho y qué falta

| # | Regla | Estado | Dónde |
|---|---|---|---|
| 1 | Una ONG no puede ofertar lo que no tiene | **Hecho** | App local valida contra `POST /validaciones` |
| 2 | Lo ofrecido queda reservado mientras la oferta esté activa (suma entre emergencias) | **Hecho**, en la app local | `services/ofertas.py` (tope) |
| 3 | Editar, reducir o retirar la oferta libera el recurso | **Hecho** | Versiones de oferta + retiro |
| 4 | Al vencer el timer, las ofertas siguen reservadas **hasta que se decida** la adjudicación | **Falta**: hoy dejan de contar apenas vence la ventana | Hay que contar también las convocatorias cerradas sin adjudicar |
| 5 | Al vencer el timer, el sistema valida todas las ofertas y calcula la cobertura | **Falta**: los ServiceTasks de Bonita están vacíos | Bonita (conector) o app |
| 6 | Si no se cubren los lotes, el Coordinador decide (reformular o seguir parcial) | **Falta**: no hay pantalla; Bonita llega a "Evaluar Cobertura" y se queda ahí | App + Bonita |
| 7 | El Municipio elige las ofertas (consigna y modelo: lane Municipio, "Adjudicar Ofertas") | **Falta** | App + Bonita |
| 8 | Lo elegido se compromete en el Sistema Nacional | **API hecha** (`POST /adjudicaciones`, con `FOR UPDATE`); **no se llama** desde la app ni Bonita | App/Bonita |
| 9 | Lo no elegido se libera automáticamente | **Falta** (depende de 4 y 7) | App |
| 10 | Se notifica a cada ONG si fue seleccionada | **Falta** | App (bandeja de notificaciones de la ONG) |
| 11 | La ONG marca sus actividades como finalizadas | **Falta**; en Bonita la multi-instancia está sin configurar | App + Bonita |
| 12 | Cierre bilateral: al resolverse, se liberan los recursos y se notifica | **API hecha** (`POST /cierres`); **no se llama** | App/Bonita |

**Decisión de diseño a confirmar**: la reserva al ofertar (2) vive en la app local, no en el Sistema Nacional. La
consigna dice que la API del Cloud no guarda borradores ni ofertas preliminares (directiva 1) y que el bloqueo
nacional ocurre "al ser adjudicados" (servicio 4). Por eso: la app local reserva mientras la oferta está activa, y la
API Nacional compromete recién al adjudicar (8) y libera al cerrar (12).

## 2. Qué hay que construir para que funcione todo de punta a punta

Orden sugerido (cada paso con sus tests y prueba real, commits chicos):

1. **Reserva hasta la decisión** (regla 4): el tope cuenta también las ofertas de convocatorias cerradas que todavía
   no se adjudicaron.
2. **Evaluación al vencer el timer** (regla 5): `GET /api/emergencias/{id}/ofertas-consolidadas` en la app local
   (para Bonita, con las ofertas vigentes) y conector REST en "Obtener Ofertas…" + "Validar en Sistema Nacional y
   Calcular Cobertura…" que setea `coberturaCompleta` y `porcentajeCobertura`. Alternativa más simple: que la app haga
   la evaluación al detectar el cierre y setee las variables por la API de Bonita. Decidir cuál (la consigna pide que
   Bonita inicie la comunicación).
3. **Pantalla del Coordinador "Evaluar cobertura"** (regla 6): ver cobertura por lote; elegir REFORMULAR o PARCIAL;
   la app setea `decisionCoordinador` y completa la tarea.
4. **Pantalla del Municipio "Adjudicar"** (reglas 7, 8, 9): ve las ofertas validadas (con su nivel de competencia),
   elige; la app llama a `POST /adjudicaciones` por cada ONG elegida, marca las no elegidas como liberadas y completa
   "Adjudicar Ofertas" en Bonita. Estado nuevo de la emergencia: `ADJUDICADA` / `EN_EJECUCION`.
5. **Notificaciones** (regla 10): tabla local de notificaciones + bandeja en la SPA para la ONG ("tu oferta fue
   seleccionada / no seleccionada"; "la convocatoria se cerró").
6. **Finalización y cierre** (reglas 11, 12): la ONG marca su actividad como finalizada; el Coordinador valida el cierre;
   la app llama a `POST /cierres` y la emergencia pasa a `RESUELTA`. En Bonita: configurar la multi-instancia de
   "Confirmar Finalizacion de Actividades" (o simplificarla) y completar las tareas.
7. **Coherencia en la API Nacional**: `/adjudicaciones` con CUIT y código de recurso (como el resto); `/cierres`
   atado a la adjudicación (libera lo que esa referencia comprometió); sacar las tablas `compromiso*` sin uso.
8. **JWT** (servicio 1) cuando se retome: un token por usuario (ver sección 5).

## 3. Plan de pruebas end to end

Ampliar `backend/scripts/escenario_tope.py` (o un script nuevo `escenario_completo.py`) con Bonita real y la API
Nacional, más `e2e_ui.py` para la parte visual:

| Escenario | Qué verifica |
|---|---|
| E1 Feliz: alta → lotes → publicar → ofertas que cubren todo → timer → cobertura completa → adjudicar → compromiso nacional → notificación → finalizar → cierre → liberación | El ciclo entero y el inventario nacional vuelve al valor inicial |
| E2 Cobertura parcial → el Coordinador elige PARCIAL → adjudicar lo que hay | Camino alternativo del timer |
| E3 Cobertura parcial → REFORMULAR → nuevos lotes → nueva convocatoria | Vuelta a "Revisar…" |
| E4 Oferta no elegida → se libera y la ONG puede ofertar en otra emergencia | Regla 9 |
| E5 Reserva hasta la decisión: con la ventana vencida y sin adjudicar, la ONG no puede reofertar lo mismo | Regla 4 |
| E6 Concurrencia: dos adjudicaciones simultáneas sobre el mismo stock → una pasa, la otra 409 | Locking en Postgres (test de Leandro con `POSTGRES_TEST_DATABASE_URL`) |
| E7 Idempotencia: repetir adjudicación o cierre no descuenta dos veces | `/adjudicaciones` y `/cierres` |
| E8 Fallas: API caída → 503 sin guardar nada; Bonita lento → sin casos huérfanos | Ya cubierto, repetir |
| E9 Permisos por rol en cada pantalla nueva | RBAC |
| E10 Contra la nube: todo lo anterior con `NACIONAL_BASE_URL` = Render | Integración real |

## 4. Formato de entrega

Los profesores tienen que poder usar el proyecto. Propuesta:

- **API Nacional**: desplegada en Render (URL + Swagger) y, además, levantable en local con su `Dockerfile`.
- **App local + base**: `docker compose up` levanta Postgres + backend + frontend (la rama `e3-leandro` ya empezó un
  `docker-compose.yml`; partir de ahí). Así se usa Postgres también en local (puntaje extra de la consigna).
- **Bonita**: no se dockeriza Studio; se entrega `RescueSync.bos` + `ACME.xml` con los pasos para importarlo y
  ejecutarlo (los profesores usan Studio en la materia). Alternativa: imagen oficial de Bonita con el `.bar`.
- **Guía de instalación** (`README` en la raíz): requisitos, `docker compose up`, cómo importar el `.bos`, variables
  de entorno (`.env.example`), usuarios de demo y contraseñas, cómo despertar la API de Render, problemas comunes.
- **Guion de demo** paso a paso (ya existe uno de la Entrega 2; actualizarlo) y, como respaldo, un video corto.
- **Prueba en limpio**: alguien del equipo con Docker funcionando clona el repo desde cero y sigue la guía tal cual.
  En la PC de Tomás Docker no arranca (falta habilitar la virtualización).

## 5. JWT: un token por usuario

- Cada usuario (Municipio, Coordinador, ONG, Auditor) obtiene su token al hacer login; el token lleva su id y su rol, y
  cada endpoint chequea el rol (lo mismo que hoy hace `require_role` con la cookie).
- La consigna pide el `/login` con JWT y el registro de ONGs **en la API Nacional**. Diseño posible: la API Nacional
  emite los tokens (cuentas de usuarios + registro de ONGs); la app local, al loguear al usuario, guarda su token y lo
  manda en cada llamada a la API Nacional; Bonita usa una cuenta de servicio.
- La rama `franco_v` hizo JWT en la app local: sirve como base, pero hay que llevarlo a `nacional/` (o hacer las dos) y
  adaptar la SPA, que hoy usa cookie.

## 6. PostgreSQL: dónde y para qué

La consigna:
- Servicio 4: "locking en PostgreSQL para prevenir race conditions" → la base de la **API Nacional** (nube) tiene que
  ser Postgres.
- Directiva 1: las ofertas se guardan en la base local "(se recomienda PostgreSQL)".
- "Se recomienda firmemente PostgreSQL, la cual puede encontrarse dockerizada (… puntaje extra)".

Tener Postgres **en ambas** (nube y local): la nube lo necesita por el locking; en local suma puntaje si está
dockerizada, iguala el motor de desarrollo con el de producción, y hace efectivos los bloqueos de fila de la app local
(con SQLite se ignoran). Hoy la app local usa SQLite.
