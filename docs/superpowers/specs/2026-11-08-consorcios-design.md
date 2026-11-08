# Consorcios entre ONGs — diseño

Fecha: 8/11/2026. Frente B de la hoja de ruta (`docs/superpowers/plans/2026-11-08-entrega-5-hoja-de-ruta.md`).

## Intención

La consigna pide consorcios en cuatro lugares:

1. Eslabón 3: "la aplicación web permitirá registrar ofertas parciales o conjuntas (consorcios entre ONGs asociándose
   mediante la interfaz)".
2. Ítem 1, nota: "La conformación de consorcios entre ONGs y la gestión de ofertas parciales se resuelve a nivel de los
   formularios web y la base de datos local, por lo que no requiere una complejidad excesiva en los nodos internos del BPM".
3. Ítem 2, perfil ONG: "registrar ofertas parciales/consorcios".
4. Ítem 4, dashboard: "porcentaje de resolución mediante consorcios".

Hoy no existen: cada `Oferta` tiene una sola ONG y es única por (emergencia, ONG). Las ofertas parciales sí existen. El
objetivo es que varias ONGs puedan asociarse desde la app para cubrir juntas una emergencia, que el Municipio las vea y
las adjudique como un bloque, y que el dashboard pueda medir cuántas emergencias se resolvieron con consorcios.

## Objetivos

- Una ONG puede crear un consorcio dentro de una emergencia e invitar a otras ONGs, que aceptan o rechazan desde la app.
- El Municipio ve cada consorcio como un bloque (miembros, cobertura sumada, estado de cada miembro según la API
  Nacional) y lo adjudica entero con una sola selección.
- El historial de membresía queda guardado (quién invitó, cuándo aceptó, cuándo salió).
- El dato que necesita el dashboard queda disponible: qué emergencias resueltas tuvieron al menos un consorcio adjudicado.

## No objetivos

- No se cambia el proceso de Bonita ni ningún `.bos`.
- No se cambia la API Nacional ni su contrato.
- No se cambia el JSON del consolidado que lee Bonita (`GET /api/bonita/emergencias/{id}/ofertas`).
- No hay una "oferta conjunta" con líneas de varias ONGs: esa era la opción 2 y se descartó.
- No se reparte la responsabilidad de ejecución: cada ONG sigue marcando su propia actividad como finalizada.

## Anti-objetivos (sería un fracaso aunque funcione)

- Que un miembro sin reserva en la API Nacional deje afuera a todo el consorcio. La consigna pide evitar los rechazos
  punitivos o binarios.
- Que los escenarios con Bonita real (`backend/scripts/correr_escenarios.py`) o las pruebas de interfaz existentes dejen
  de pasar. Una emergencia sin consorcios tiene que comportarse exactamente igual que hoy.
- Que un dato mal formado dé 500 en vez de 422 o 409 (Postgres rechaza cosas que SQLite deja pasar).

## Restricciones

- Hay que entregar el 19/11, con el dashboard todavía por hacer. El alcance tiene que caber en 2 o 3 días.
- Backend FastAPI + SQLAlchemy + Alembic. Toda migración tiene que ir y volver (`test_migrations.py`) y correr en
  Postgres 16 (job de CI).
- La adjudicación ya va por CUIT: `ciclo.adjudicar(cuits)` completa "Adjudicar Ofertas" en Bonita con
  `ongsAdjudicadas = [cuits]`, y solo acepta CUIT con estado `RESERVADA` en la evaluación guardada.
- Textos de UI y `detail` de errores en castellano neutro, como el resto de la app. Identificadores en castellano.
- Cada endpoint nuevo sigue el checklist del skill `nuevo-endpoint`.

## Enfoques considerados

1. **Agrupación de ofertas individuales (elegido).** Cada ONG mantiene su oferta y el consorcio solo las agrupa. Bonita,
   la API Nacional y el consolidado no cambian: adjudicar el consorcio es mandar los CUIT de sus miembros. Una
   migración, pantallas en la app y tests.
2. **Oferta conjunta.** Una oferta con líder y asociadas, y cada línea atribuida a una ONG. Cambian la restricción
   única, el JSON del consolidado, la evaluación y la reserva en Nacional (todo o nada por consorcio). Es más fiel a
   "oferta conjunta", pero arriesga los conectores del `.bos` y lleva el triple de trabajo. Descartado por plazo y riesgo.

El usuario eligió la opción 1 el 8/11, apoyado en la nota del ítem 1 de la consigna.

## Diseño (decidido con el usuario)

### Formación
- Mientras la ventana de ofertas está abierta (estado `CONVOCATORIA` y `ventana_ofertas_fin` en el futuro, la misma regla
  que ya usa `ofertas._esta_abierta`), una ONG crea un consorcio en esa emergencia con un nombre. Queda como **líder** y
  miembro aceptado.
- La líder invita a otras ONGs. La invitada recibe una `Notificacion` y acepta o rechaza desde la app.
- Una ONG está, como mucho, en **un consorcio por emergencia** (contando invitaciones pendientes y membresías
  aceptadas). No puede invitarse a una ONG que ya está en otro.
- Con la ventana abierta, un miembro puede salir y la líder puede disolver el consorcio.
- Al cerrarse la ventana, el consorcio queda **fijo**: no se invita, no se acepta, no se sale.
- Un consorcio con **un solo miembro aceptado** no cuenta como consorcio (ni para el Municipio ni para el dashboard).

### Ofertas
- Cada miembro carga y edita su propia oferta como hoy (`ofertas.publicar_oferta`): mismas versiones, mismo tope por
  inventario, misma ventana. El consorcio no tiene oferta propia.
- Pertenecer a un consorcio no obliga a tener oferta. Un miembro sin oferta no aporta cobertura.

### Adjudicación (Municipio)
- En la pantalla de adjudicación, las ofertas de los miembros aceptados de un consorcio se muestran juntas, en un bloque
  con: nombre del consorcio, líder, cada miembro con lo ofrecido y su estado en la evaluación guardada (`RESERVADA` /
  `NO_RESERVADA`), y la cobertura sumada por lote.
- El bloque tiene **una sola casilla**. Al tildarla, se adjudican los miembros con estado `RESERVADA`.
- **Si un miembro no tiene reserva, el consorcio se adjudica igual con los demás** (decisión del usuario, opción a). El
  bloque lo muestra como "sin reserva, no se adjudica". Si ningún miembro tiene reserva, el bloque no se puede tildar.
- La app traduce la selección a CUIT y llama a `ciclo.adjudicar` sin cambios. Bonita no se entera de que hubo consorcio.
- Las ONGs que no están en ningún consorcio se siguen mostrando y adjudicando una por una, como hoy.

### Trazabilidad
- Se guarda cada membresía con: consorcio, ONG, estado (`INVITADA`, `ACEPTADA`, `RECHAZADA`, `SALIO`), quién invitó y
  las fechas de invitación, respuesta y salida. Disolver el consorcio lo marca como disuelto y no borra filas.

### Para el dashboard
- "% de resolución mediante consorcios" = emergencias `RESUELTA` con al menos un consorcio (con 2 o más miembros
  aceptados) que tenga al menos un miembro con oferta `ADJUDICADA` o `FINALIZADA`, dividido por emergencias `RESUELTA`.
  Se filtra por el mismo rango de fechas que el resto del dashboard.

### Modelo de datos (propuesta del diseño, el builder puede ajustar nombres)
- `consorcio`: id, emergencia_id, nombre (2-80, único por emergencia), ong_lider_id, creado_en, disuelto_en (nullable).
- `consorcio_miembro`: id, consorcio_id, ong_id, estado, invitado_por_ong_id, invitado_en, respondido_en (nullable),
  salio_en (nullable).
- La regla "un consorcio por ONG y emergencia" se valida en el servicio (y, si se puede de forma portable entre SQLite y
  Postgres, también con una restricción).
- Migración nueva `0007_consorcios`, de ida y vuelta.

### Endpoints (rol ONG salvo aclaración; todos devuelven 409 con la ventana cerrada)
- `GET  /api/emergencias/{id}/consorcios`: los consorcios de la emergencia. La ONG ve todos (para saber a quién puede
  invitar); Municipio, Coordinador y Auditor también, en solo lectura.
- `POST /api/emergencias/{id}/consorcios`: crear (la ONG que llama queda como líder).
- `POST /api/consorcios/{id}/invitaciones`: invitar a una ONG (solo la líder).
- `POST /api/consorcios/{id}/respuesta`: aceptar o rechazar (solo la invitada).
- `POST /api/consorcios/{id}/salida`: salir (miembro que no es líder).
- `DELETE /api/consorcios/{id}`: disolver (solo la líder).
- La respuesta de ofertas que usa la pantalla de adjudicación incluye a qué consorcio pertenece cada oferta (campo
  aditivo; no se toca el consolidado de Bonita).

### Pantallas
- **ONG, en la convocatoria:** sección "Consorcio" con crear, invitar (selector de ONGs disponibles), miembros y estado, y
  salir o disolver. Las invitaciones pendientes se ven ahí y en las notificaciones.
- **Municipio, al adjudicar:** bloques por consorcio, como en el boceto.

```
Emergencia #12 · Ofertas
┌ Consorcio "Red Litoral" (líder: Cruz Roja) ─────────┐
│ Cruz Roja   20 paramédicos   ✓ reservado            │
│ Bomberos    10 paramédicos   ✓ reservado            │
│ Cobertura del lote Paramédicos: 30/30 (100 %)       │
│ [x] Adjudicar consorcio                             │
└─────────────────────────────────────────────────────┘
  Cáritas (individual)  500 raciones ✓    [ ] Adjudicar
```

- **Coordinador y Auditor:** ven a qué consorcio pertenece cada oferta (solo lectura).

## Queda para el builder
- Nombres exactos de tablas, campos, schemas y componentes.
- Mensajes de error concretos (en castellano, con el código correcto: 403 rol o ONG equivocada, 404 inexistente, 409
  ventana cerrada o regla de membresía, 422 validación).
- Cómo se reparte la UI dentro de `frontend/src/pages.tsx` (hoy es un solo archivo grande).
- Datos de demo: agregar un consorcio al seed si ayuda a las pruebas de interfaz.

## Verificación
- Tests de servicio y de API: cada regla de formación, ventana cerrada, permisos por rol, una ONG en dos consorcios,
  adjudicar un consorcio con un miembro sin reserva, consorcio de un solo miembro.
- `test_migrations.py` con la migración nueva; job de CI con Postgres.
- `python scripts/verificar_todo.py` en verde.
- Escenarios con Bonita real sin regresiones y una prueba de interfaz del recorrido con consorcio (skill `probar-en-nube`).
