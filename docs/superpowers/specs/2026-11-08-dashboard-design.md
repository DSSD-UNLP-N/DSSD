# Dashboard de indicadores (Auditor/Directivo) — diseño

Fecha: 8/11/2026. Frente A de la hoja de ruta (`docs/superpowers/plans/2026-11-08-entrega-5-hoja-de-ruta.md`).
Depende del frente B (`2026-11-08-consorcios-design.md`) solo para la métrica de consorcios.

## Intención

Ítem 4 de la consigna: "Aplicación web que permita al personal directivo la evaluación, seguimiento y métricas de los
procesos. Debe permitir obtener reportes combinando datos propios (ej. cantidad de suministros movilizados en el mes,
porcentaje de resolución mediante consorcios, estado de proyectos finalizados) con datos extraídos de la API de Bonita
(ej. tiempos promedio de resolución de cada etapa de la emergencia). Inclusión de gráficos interactivos y opciones de
exportación de datos estructurados."

Hoy no existe nada de esto. El perfil Auditor/Directivo solo tiene "Consulta de emergencias" en solo lectura. El
dashboard se muestra en el coloquio del 26/11 y se documenta en el informe del 19/11.

## Objetivos
- Una página de indicadores para el Auditor/Directivo que combine datos de la app con tiempos sacados de Bonita.
- Gráficos interactivos (tooltips, leyendas, selector) y filtros por fechas y municipio.
- Exportación en JSON (reporte completo), CSV (por bloque) y PDF (reporte imprimible con los gráficos).

## No objetivos
- No hay métricas en tiempo real ni refresco automático: se calcula al abrir la página o al cambiar un filtro.
- No se consulta la API Nacional: el stock nacional no es parte del reporte.
- No se cambia el proceso de Bonita ni la API Nacional.
- La lista exacta de métricas puede ajustarse después con feedback de la cátedra. El diseño tiene que permitir agregar
  o sacar una métrica sin reescribir todo (decisión del usuario, 8/11: "las métricas las ajustamos después").

## Anti-objetivos
- Que Bonita caído o lento rompa la página o dé 500. La parte de la app se muestra siempre.
- Sumar cantidades con unidades distintas (personas + raciones). Las cantidades van siempre por tipo de recurso.
- Que otro rol vea el dashboard o sus exportaciones.

## Restricciones
- Backend FastAPI y SQLAlchemy, con tests en pytest (`FakeBonita` en `backend/tests/conftest.py`). Front en React 19,
  Vite y TypeScript, en `frontend/src/` (hoy `pages.tsx` es un solo archivo grande).
- El cliente de Bonita (`backend/app/integrations/bonita.py`) ya tiene `get_archived_human_tasks(case_id)` y `get_case`.
- Bonita Community corta en 150 casos por proyecto: los datos de demo reutilizan los casos de los escenarios.
- Postgres en CI: los datos mal formados (fechas inválidas en los filtros) dan 422, nunca 500.
- Endpoints con el checklist del skill `nuevo-endpoint`.

## Enfoques considerados
1. **Página dentro de la SPA actual, con un endpoint de agregados en el backend (elegido).** Reusa la sesión, el RBAC y
   el estilo de la app. El backend calcula todo y el front solo dibuja. Una sola fuente para la pantalla y las
   exportaciones.
2. **Aplicación separada** (otro front u otra herramienta de BI, como Metabase). La consigna dice "aplicación web", pero
   duplica login y RBAC, y una herramienta de BI no puede leer la API de Bonita sin otro adaptador. Descartado.
3. **Calcular en el front** a partir de los endpoints existentes. Tendría que llamar a Bonita desde el navegador (sin
   credenciales técnicas allí) y duplicaría la lógica en las exportaciones. Descartado.

## Diseño (propuesta aprobada por el usuario el 8/11)

### Quién lo ve
- **Solo el rol AUDITOR** (decisión del usuario). Los demás roles reciben 403 en la API y no ven el menú.
- El menú del Auditor pasa a tener "Indicadores" (primero) y "Consulta de emergencias".

### Filtros
- Rango de fechas (desde/hasta, por defecto los últimos 6 meses hasta hoy) y municipio (por defecto todos).
- El rango se aplica sobre la fecha de alta de la emergencia (`creada_en`), salvo en "suministros por mes", que usa la
  fecha de adjudicación (ver más abajo).

### Bloques
1. **Tarjetas KPI:** emergencias del período, resueltas, en curso (todo lo que no es `RESUELTA`), % resueltas mediante
   consorcio (definición en la spec de consorcios) y cobertura promedio de lotes (promedio de `porcentaje_cobertura` de
   la evaluación guardada, solo de las emergencias evaluadas).
2. **Suministros movilizados por mes:** barras por mes con un selector de tipo de recurso. Cantidad = suma de los ítems de
   la versión vigente de las ofertas `ADJUDICADA` o `FINALIZADA`, agrupada por tipo de recurso del lote y por mes de
   adjudicación.
   - Hoy la oferta no guarda cuándo se adjudicó. Se agrega `oferta.adjudicada_en` (nullable), que se completa en
     `registrar_adjudicacion`. Para las ofertas adjudicadas antes de la migración, el valor se completa con la fecha de la
     notificación de adjudicación de esa ONG en esa emergencia si existe, y si no queda nulo y la oferta no entra en el
     gráfico.
3. **Emergencias por estado:** barras horizontales, una por estado, con los nombres de estado que ya muestra la app.
4. **Tiempo promedio por etapa (Bonita):** barras horizontales en horas, una por tarea humana del proceso, en el orden del
   flujo: Revisar Información y Generar Lotes, Publicar Convocatoria, Cargar Ofertas de Ayuda (la ventana: termina
   abortada por el timer), Evaluar Cobertura, Adjudicar Ofertas, Monitorear Ejecución, Confirmar Finalización de
   Actividades, Validar Cierre Operativo Bilateral.
   - Duración de una tarea = desde que quedó lista (`reached_state_date`) hasta que se archivó (`archivedDate`), sacadas de
     las tareas archivadas del caso (`bonita_case_id`). Se promedia por nombre de tarea entre las emergencias del filtro.
   - Además: duración total promedio de las emergencias resueltas (alta → cierre validado), con datos de la app.
   - Si Bonita no responde o falla, el bloque dice "Bonita no disponible" y la respuesta indica qué parte falta. El resto
     del dashboard se muestra igual.
5. **Emergencias finalizadas:** tabla con municipio, tipo, gravedad, ONGs adjudicadas, si hubo consorcio, duración total
   y cobertura.

### Exportación (decisión del usuario: JSON, CSV y PDF)
- **JSON:** el reporte completo, con los mismos filtros (es la misma respuesta del endpoint).
- **CSV:** un botón por bloque. Cada bloque es una tabla con encabezados en castellano, UTF-8 con BOM para que Excel
  muestre bien los acentos, separador coma.
- **PDF:** botón "Imprimir / Guardar PDF" que abre la impresión del navegador sobre una vista armada para papel (hoja de
  estilos de impresión: sin menú, gráficos a ancho completo, encabezado con filtros y fecha de emisión). Así el PDF tiene
  los mismos gráficos sin otra librería.
- Los nombres de archivo llevan el bloque y el rango: `indicadores_suministros_2026-06-01_2026-11-08.csv`.

### Arquitectura
- Backend: servicio `app/services/indicadores.py` que arma el reporte, y un router con:
  - `GET /api/indicadores?desde=&hasta=&municipio_id=` → reporte en JSON (rol AUDITOR).
  - `GET /api/indicadores/export.csv?bloque=&desde=&hasta=&municipio_id=` → CSV de un bloque (rol AUDITOR).
- Las métricas se arman como funciones separadas (una por bloque) que el servicio junta. Agregar o sacar una métrica
  toca una función y su test (requisito: "ajustamos las métricas después").
- Front: página `/indicadores` (componente propio, no dentro de `pages.tsx`), con **Recharts 3.x** para los gráficos
  (decisión del diseño: React declarativo, tooltips y leyendas incluidos, compatible con React 19). El JSON se descarga
  desde los datos ya cargados; el CSV, desde el endpoint.
- Paleta y formas de los gráficos según el skill `dataviz`, y que se lea bien en claro y en oscuro si la app lo soporta.

### Boceto
```
Indicadores ·  [01/06/2026 → 08/11/2026]  [Municipio: todos ▾]   [JSON] [Imprimir / PDF]
┌──────────┬──────────┬───────────┬──────────────┬──────────────┐
│ 14 emerg.│ 9 resuel.│ 5 en curso│ 33 % consorc.│ 87 % cobert. │
└──────────┴──────────┴───────────┴──────────────┴──────────────┘
Suministros por mes  [Raciones ▾]  [CSV]   Tiempo por etapa (Bonita)          [CSV]
 ▇▇ ▇▇▇ ▇ ▇▇▇▇ ▇▇ ▇▇▇                       Cargar ofertas (ventana) ████████ 24 h
 jun jul ago sep oct nov                     Adjudicar ofertas        ███ 6 h ...
Emergencias por estado  [CSV]              Emergencias finalizadas            [CSV]
```

## Decisiones del diseño tomadas en la revisión
1. **Definición de duración, a verificar contra Bonita real.** Si `reached_state_date` y `archivedDate` del registro
   archivado salen casi iguales (Bonita los escribe al terminar la tarea), la duración de una tarea se mide desde el
   archivo de la actividad anterior del mismo caso (tareas humanas y de servicio, ordenadas por fecha; se consulta
   `archivedActivity`) o desde el inicio del caso si es la primera. El plan empieza con un spike corto contra el Bonita de
   la nube para confirmar qué campos sirven, y fija la definición antes de escribir la métrica.
   **Resultado del spike (8/11, Bonita 2025.2-u5 en Docker, caso archivado 15):**
   - En `archivedHumanTask`, `reached_state_date` y `archivedDate` difieren en milisegundos, así que no sirven.
   - `GET /API/bpm/archivedFlowNode?f=caseId=<id>&p=<n>&c=100` (funciona con casos abiertos y archivados) devuelve un
     registro por cambio de estado de cada nodo: `initializing`, `ready`, `completed` o `aborted`.
   - **Definición:** duración de una instancia de tarea humana = `archivedDate - reached_state_date` de su registro
     `type=USER_TASK, state=ready`. Es el tiempo que la tarea estuvo esperando a una persona, o al timer en el caso de
     "Cargar Ofertas de Ayuda".
   - Cada instancia (por ejemplo, las dos rondas) tiene su propio registro `ready`.
   - Las fechas tienen el formato `"2026-11-08 21:54:53.794"`, en la hora del servidor de Bonita (UTC en Docker).
   - Hay que paginar: un caso con dos rondas tiene unos 60 registros.
   - Ejemplo recortado para el `FakeBonita`:
     `{"type": "USER_TASK", "name": "Cargar Ofertas de Ayuda", "state": "ready", "reached_state_date": "2026-11-08 21:54:53.794", "archivedDate": "2026-11-08 21:56:13.015", "rootCaseId": "15"}`.
2. **Etapas repetidas (REFORMULAR):** por emergencia se suman todas las instancias de la misma tarea, y después se
   promedia entre las emergencias que la completaron. Las emergencias en curso aportan solo las tareas ya terminadas.
   Así "tiempo por etapa" es el tiempo que la emergencia pasó en esa etapa, rondas incluidas.
3. **Datos de demo:** el dashboard muestra los datos tal como salen. No se mueven fechas en la base. Si hace falta
   historia para que los gráficos no se vean vacíos, se carga con un script aparte, marcado como "datos de demostración"
   (el reporte lo indica), y desactivado por defecto. Los tiempos de Bonita salen siempre de casos reales, aunque sean
   cortos, y el informe explica por qué.
4. **Orden con el frente B:** se implementa B primero y después A. La migración de `adjudicada_en` va después de la de
   consorcios. El campo de consorcios en el JSON del reporte igual es tolerante: si no hay datos, la tarjeta muestra
   "sin datos".
5. **Detalles:**
   - `porcentaje_cobertura` hoy llega de 0 a 100: se usa así.
   - Backfill de `adjudicada_en` buscando la notificación de adjudicación por texto, porque `Notificacion` no tiene tipo.
   - Los lotes sin `tipo_recurso` van como "Sin tipo".
   - Los meses se agrupan en hora de Argentina (America/Argentina/Buenos_Aires).
   - Hay que crear un `FakeBonita` para los tests.
   - Los casos que ya no existen en Bonita (por ejemplo, después de reimportar el `.bos`) se saltean y no marcan el
     bloque como "no disponible".

## Queda para el builder
- Nombres exactos de schemas, campos del JSON y componentes.
- Cómo se consulta Bonita en bloque sin una llamada por caso si se puede (si no, una por caso con un tope razonable de
  tiempo total y degradación a "no disponible").
- Formato de horas (decimales o "1 d 4 h").
- Datos de demo para que el dashboard no se vea vacío en el coloquio (seed o script, sin pasar el tope de casos).

## Verificación
- Tests de cada métrica con datos armados, incluido el caso sin datos.
- Tests del endpoint: 403 para MUNICIPIO, COORDINADOR y ONG; 422 con fechas inválidas; filtro por municipio.
- Bonita caído (`FakeBonita` que falla): 200 con el bloque de tiempos marcado como no disponible.
- CSV: encabezados, BOM, acentos y `Content-Disposition` con el nombre de archivo.
- Migración de `adjudicada_en` de ida y vuelta; CI con Postgres.
- Tipos del front (`npm run typecheck`) y una prueba de interfaz con captura del dashboard con datos reales, después de
  correr los escenarios con Bonita (skill `probar-en-nube`).
