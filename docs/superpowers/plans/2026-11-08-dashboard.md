# Dashboard de indicadores — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Página `/indicadores` para el Auditor/Directivo que combina datos de la app con tiempos por etapa sacados de Bonita, con gráficos interactivos y exportación a JSON, CSV y PDF.

**Architecture:** El servicio `app/services/indicadores.py` arma el reporte con una función por bloque. El router `app/routers/indicadores.py` lo sirve en JSON y en CSV por bloque. El front tiene una página propia en `src/indicadores.tsx`, con Recharts y una hoja de estilos de impresión para el PDF. La oferta gana `adjudicada_en`.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, pytest; React 19 + TypeScript + Recharts 3.x; Playwright; Bonita 2025.2 (REST API de tareas archivadas).

**Spec:** `docs/superpowers/specs/2026-11-08-dashboard-design.md`

## Global Constraints

- Se implementa después de consorcios, en la misma rama `claude/stoic-brown-65bucb`. El PR a `dev` se abre solo cuando el usuario lo pida. Commits en inglés y convencionales.
- Solo el rol `AUDITOR`: 403 para los demás, en todas las rutas de indicadores.
- Filtros: `desde` y `hasta` (fechas ISO `YYYY-MM-DD`; por defecto, hoy menos 6 meses y hoy), `municipio_id` opcional. Si `desde` es posterior a `hasta`, o una fecha es inválida: 422.
- Zona horaria para agrupar y mostrar: `America/Argentina/Buenos_Aires`.
- Cantidades siempre por tipo de recurso. Los lotes sin `tipo_recurso` van como `"Sin tipo"`.
- Si Bonita falla, la respuesta es 200, con `tiempos.disponible = false` y un `motivo`. Los casos que no existen en Bonita se saltean.
- CSV: UTF-8 con BOM, separador coma, encabezados en castellano. Nombre: `indicadores_<bloque>_<desde>_<hasta>.csv`.
- Recharts: versión exacta 3.x publicada hace por lo menos dos semanas (`npm view recharts time`), fijada sin `^` en `package.json`.
- Gráficos según el skill `dataviz` (leerlo antes de la Task 6).

## Review Focus

1. Período sin ninguna emergencia: 200, tarjetas en 0, gráficos con "Sin datos en el período" y CSV con solo encabezados (Task 3, `test_reporte_vacio`; Task 4, `test_csv_vacio_tiene_encabezados`).
2. Bonita caído a mitad del reporte: el resto de los bloques igual llega (Task 4, `test_bonita_caido_degrada_solo_tiempos`).
3. Emergencia con dos rondas (REFORMULAR): las tareas repetidas se suman por emergencia antes de promediar (Task 3, `test_etapas_repetidas_se_suman_por_emergencia`).
4. Oferta adjudicada antes de la migración y sin notificación: no entra en suministros y no rompe nada (Task 1, `test_backfill_sin_notificacion_queda_nulo`).
5. `municipio_id` inexistente: 200 con todo en 0, no 404 ni 500 (Task 4, `test_municipio_inexistente_da_vacio`).

---

### Task 0: Spike contra Bonita real (descartable)

**Files:** solo el scratchpad. No se commitea código.

- [ ] **Step 1:** Con el Bonita de la nube y un caso terminado por los escenarios, pedir `GET /API/bpm/archivedHumanTask?f=caseId=<id>&c=100` y `GET /API/bpm/archivedActivity?f=caseId=<id>&c=100`. Con un caso ya archivado, probar también `f=sourceObjectId`/`f=rootCaseId` si `caseId` no devuelve nada.
- [ ] **Step 2:** Anotar en la sección "Decisiones del diseño" de la spec: qué campos de fecha hay, si `reached_state_date` y `archivedDate` difieren, y qué definición de duración queda (la del registro o la de "desde la actividad anterior"). Incluir una respuesta real recortada como ejemplo para el `FakeBonita`.
- [ ] **Step 3:** Commit de la spec actualizada: `docs(dashboard): fix stage duration definition from Bonita spike`.

### Task 1: `oferta.adjudicada_en`

**Files:**
- Modify: `backend/app/models/entities.py` (`Oferta`), `backend/app/services/evaluacion.py` (`registrar_adjudicacion`)
- Create: `backend/migrations/versions/0008_oferta_adjudicada_en.py` (revision `'0008'`, down_revision `'0007'`)
- Test: `backend/tests/test_ciclo.py`, `backend/tests/test_migrations.py`

**Interfaces:**
- Produces: `Oferta.adjudicada_en: datetime | None`.

- [ ] **Step 1:** Tests que fallan:
  - `test_registrar_adjudicacion_guarda_fecha`: después del evento, las ofertas adjudicadas tienen `adjudicada_en` y las no adjudicadas, `None`
  - `test_backfill_toma_la_fecha_de_la_notificacion`
  - `test_backfill_sin_notificacion_queda_nulo` (en `test_migrations.py`, con datos insertados antes de subir a `0008`)
- [ ] **Step 2:** Correrlos: fallan.
- [ ] **Step 3:** Agregar la columna (nullable, con timezone). En `registrar_adjudicacion`, completar `adjudicada_en = now` en las ofertas que pasan a `ADJUDICADA`. La migración agrega la columna y completa el backfill con SQL portable: el `creada_en` más viejo de la `notificacion` de esa ONG y esa emergencia cuyo texto contiene el aviso de adjudicación. El texto exacto se toma de `registrar_adjudicacion`.
- [ ] **Step 4:** `python -m pytest -q tests/test_ciclo.py tests/test_migrations.py`: pasa.
- [ ] **Step 5:** Commit `feat(dashboard): store award date on offers`.

### Task 2: Cliente y `FakeBonita` para tareas archivadas

**Files:**
- Modify: `backend/app/integrations/bonita.py`, `backend/tests/conftest.py`
- Test: `backend/tests/test_bonita_client.py`

**Interfaces:**
- Produces:
  - `BonitaClient.get_archived_activities(case_id) -> list[dict]` (solo si el spike lo pide; si alcanza con `get_archived_human_tasks`, se usa ese y este paso no se hace).
  - Fixture `fake_bonita` en `conftest.py`: un objeto con `login`, `get_archived_human_tasks(case_id)` y `get_archived_activities(case_id)` que devuelve lo cargado con `fake_bonita.tareas[case_id] = [...]`. `fake_bonita.falla = True` hace que lance `requests.ConnectionError`. Se inyecta con una dependencia `get_bonita_lectura` (Task 4) que se puede sobreescribir.

- [ ] **Step 1:** Test con `responses`: `test_get_archived_activities_pide_por_caso`, con la URL y los parámetros que fijó el spike.
- [ ] **Step 2–4:** Implementar, correr y verificar que pasa.
- [ ] **Step 5:** Commit `feat(dashboard): Bonita client reads archived activities`.

### Task 3: Métricas

**Files:**
- Create: `backend/app/services/indicadores.py`, `backend/app/schemas/indicadores.py`
- Test: `backend/tests/test_indicadores.py`

**Interfaces:**
- Consumes: `consorcios_validos` (plan de consorcios), `Oferta.adjudicada_en`, `fake_bonita`.
- Produces (schemas):
  - `Filtros(desde: date, hasta: date, municipio_id: int | None)`
  - `Kpis(emergencias: int, resueltas: int, en_curso: int, pct_consorcio: float | None, cobertura_promedio: float | None)`
  - `SuministroMes(mes: str  # "2026-10", tipo_recurso: str, cantidad: int)`
  - `EstadoCantidad(estado: str, etiqueta: str, cantidad: int)`
  - `TiempoEtapa(tarea: str, horas_promedio: float, emergencias: int)` y `Tiempos(disponible: bool, motivo: str | None, etapas: list[TiempoEtapa], horas_total_promedio: float | None)`
  - `Finalizada(emergencia_id: int, municipio: str, tipo: str, gravedad: str, ongs: list[str], consorcio: bool, horas_total: float | None, cobertura: float | None)`
  - `Reporte(filtros: Filtros, generado_en: datetime, kpis: Kpis, suministros: list[SuministroMes], estados: list[EstadoCantidad], tiempos: Tiempos, finalizadas: list[Finalizada])`
- Produces (funciones): `kpis(db, f)`, `suministros_por_mes(db, f)`, `emergencias_por_estado(db, f)`, `tiempos_por_etapa(db, bonita, f) -> Tiempos`, `finalizadas(db, f)` y `reporte(db, bonita, f) -> Reporte`.
- Orden de las etapas, tal cual: `Revisar Informacion y Generar Lotes de Necesidades`, `Publicar Convocatoria y Notificar a la Red de ONGs`, `Cargar Ofertas de Ayuda`, `Evaluar Cobertura y Definir Curso de Accion`, `Adjudicar Ofertas`, `Monitorear Ejecucion del Despliegue`, `Confirmar Finalizacion de Actividades`, `Validar Cierre Operativo Bilateral`.

- [ ] **Step 1:** Tests que fallan, uno por función, con datos armados en la base:
  - `test_kpis_cuenta_por_estado_y_filtra_por_municipio`
  - `test_pct_consorcio` (2 resueltas, 1 con consorcio adjudicado → 50.0)
  - `test_pct_consorcio_sin_resueltas_es_none`
  - `test_suministros_por_mes_y_tipo_usa_version_vigente`, con una oferta de 2 versiones
  - `test_suministros_ignora_ofertas_sin_adjudicada_en`
  - `test_emergencias_por_estado_incluye_todos_los_estados_con_cero`
  - `test_tiempos_promedio_por_etapa_en_orden`
  - `test_etapas_repetidas_se_suman_por_emergencia`
  - `test_caso_inexistente_se_saltea`
  - `test_finalizadas_lista_ongs_y_consorcio`
  - `test_reporte_vacio`
- [ ] **Step 2:** Correrlos: fallan.
- [ ] **Step 3:** Implementar. Cada función recibe los mismos `Filtros` y no conoce a las demás. `reporte` las junta y atrapa los errores de Bonita solo alrededor de `tiempos_por_etapa`.
- [ ] **Step 4:** `python -m pytest -q tests/test_indicadores.py`: pasa.
- [ ] **Step 5:** Commit `feat(dashboard): indicator metrics service`.

### Task 4: Rutas JSON y CSV

**Files:**
- Create: `backend/app/routers/indicadores.py`
- Modify: `backend/app/main.py` (incluir el router), `backend/app/core/deps.py` (`get_bonita_lectura`)
- Test: `backend/tests/test_api_indicadores.py`

**Interfaces:**
- Consumes: `reporte` y schemas de la Task 3.
- Produces:
  - `GET /api/indicadores?desde=&hasta=&municipio_id=` → `Reporte`
  - `GET /api/indicadores/export.csv?bloque=&desde=&hasta=&municipio_id=` con `bloque` en `kpis | suministros | estados | tiempos | finalizadas` (otro valor: 422) → `text/csv; charset=utf-8` y `Content-Disposition: attachment; filename="indicadores_<bloque>_<desde>_<hasta>.csv"`
  - `get_bonita_lectura() -> BonitaClient` ya logueado con la cuenta técnica de `Settings`.

- [ ] **Step 1:** Tests que fallan:
  - `test_solo_auditor` (MUNICIPIO, COORDINADOR y ONG → 403; sin sesión → 401)
  - `test_fechas_invertidas_da_422`
  - `test_fecha_invalida_da_422`
  - `test_municipio_inexistente_da_vacio`
  - `test_bonita_caido_degrada_solo_tiempos`
  - `test_csv_tiene_bom_encabezados_y_acentos`
  - `test_csv_vacio_tiene_encabezados`
  - `test_bloque_invalido_da_422`
- [ ] **Step 2:** Correrlos: fallan.
- [ ] **Step 3:** Implementar. Los encabezados del CSV se definen una vez por bloque, en el router. Documentar en Swagger con ejemplos, según el skill `nuevo-endpoint`.
- [ ] **Step 4:** `python -m pytest -q tests/test_api_indicadores.py` y `python scripts/verificar_todo.py`: pasan.
- [ ] **Step 5:** Commit `feat(dashboard): indicators JSON and CSV endpoints`.

### Task 5: Página de indicadores

**Files:**
- Create: `frontend/src/indicadores.tsx`
- Modify: `frontend/src/api.ts` (tipos `Reporte` y compañía, `api.indicadores(filtros)`, `urlExportCsv(bloque, filtros)`), `frontend/src/App.tsx` (ruta `/indicadores`), `frontend/src/pages.tsx` (`MENU.AUDITOR`: "Indicadores" primero), `frontend/src/styles.css` (`@media print`), `frontend/package.json` (`recharts`)

**Interfaces:**
- Consumes: rutas de la Task 4.
- Produces: `IndicadoresPage`, con `data-testid` `kpis`, `grafico-suministros`, `grafico-estados`, `grafico-tiempos`, `tabla-finalizadas`, `exportar-json`, `exportar-pdf` y `csv-<bloque>`.

- [ ] **Step 1:** Leer el skill `dataviz` e instalar Recharts con versión fija.
- [ ] **Step 2:** Página con filtros (fechas y municipio, de `api.meta()` o de las emergencias visibles), tarjetas, los tres gráficos (barras por mes con selector de tipo; barras horizontales de estados; barras horizontales de horas por etapa con tooltip "N emergencias") y la tabla. Bloque de tiempos con "Bonita no disponible: <motivo>" cuando `disponible` es false. "Sin datos en el período" donde corresponda.
- [ ] **Step 3:** Exportación:
  - JSON con `Blob` y la descarga del reporte cargado.
  - CSV con un enlace a `urlExportCsv`.
  - PDF con `window.print()`. En `@media print` se esconden el menú y los botones, los gráficos van a ancho completo y arriba aparece un encabezado con filtros y fecha de emisión (visible solo al imprimir).
- [ ] **Step 4:** `npm run typecheck` y `npm run build`: sin errores.
- [ ] **Step 5:** Commit `feat(dashboard): indicators page with charts and exports`.

### Task 6: Prueba de interfaz, datos reales y documentación

**Files:**
- Create: `backend/scripts/ui_indicadores.py`
- Modify: `backend/scripts/correr_ui.py`, `README.md`, `backend/README.md`, `.claude/skills/rescuesync-estado/SKILL.md`

- [ ] **Step 1:** `ui_indicadores.py` (Playwright): login como `auditor`, abrir `/indicadores`, esperar los cuatro bloques y que el de tiempos tenga al menos una barra (corre después de los escenarios, así que hay casos terminados). Descarga JSON y un CSV y los valida. Genera un PDF con `page.pdf()` sobre la vista de impresión y guarda capturas en `scripts/capturas/indicadores_*.png`. Un login como `coordinador.regional` no ve el menú y `/indicadores` le muestra "sin acceso".
- [ ] **Step 2:** Registrarlo en `correr_ui.py` y correr la suite completa de interfaz.
- [ ] **Step 3:** Si con los datos de los escenarios los gráficos quedan vacíos para el coloquio, abrir una tarea aparte para el script de datos de demostración (spec, decisión 3). No se hace sin necesidad.
- [ ] **Step 4:** Documentar el dashboard (README, `backend/README.md`, skill `rescuesync-estado`).
- [ ] **Step 5:** Commit `test(dashboard): UI walkthrough with exports; docs`.
