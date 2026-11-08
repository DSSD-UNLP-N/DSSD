# Entrega 5 (19/11) y coloquio (26/11): hoja de ruta

> Plan maestro. Cada frente (A, B, …) pasa por su propio ciclo superpowers: brainstorming → spec en
> `docs/superpowers/specs/` → plan en `docs/superpowers/plans/` → ejecución por subagentes con TDD.
> Este archivo solo ordena los frentes, las herramientas y el calendario.

## 1. Qué pide la consigna y qué falta

Entrega 5: *"Informe final del trabajo ajustado al modelo propuesto. Documentación de cada uno de los
componentes, su rol e interacción en la arquitectura final."* El coloquio (26/11) evalúa el sistema
completo contra los 4 ítems de la consigna.

| Ítem de la consigna | Estado | Falta |
|---|---|---|
| 1. Bonita (timer + camino alternativo + cierre) | Hecho | — |
| 2. App web: 4 perfiles RBAC | Parcial | Auditor/Directivo solo tiene "consulta de emergencias" |
| 2. Versiones de ofertas con trazabilidad | Hecho (`OfertaItem.version`) | — |
| 2. Ofertas parciales / **consorcios** entre ONGs | **No hay consorcios**: `Oferta` tiene un solo `ong_id` y es única por (emergencia, ONG) | Modelo + UI + regla de reserva en Nacional |
| 3. API Nacional (JWT, Docker, Render, Swagger, locking) | Hecho (Entrega 3) | — |
| 4. **Dashboard de indicadores** | **No existe** | Todo: métricas locales + tiempos de Bonita, gráficos interactivos, exportación |
| Entrega 4: Gantt con desvíos (semana 5/11) | No está en el repo | Confirmar si se entregó por fuera |

## 2. Herramientas y para qué se usa cada una

### Superpowers y modo corto
El plugin no se puede instalar en las sesiones en la nube, así que sus skills están **copiadas al repo** en `.claude/skills/`
(origen y licencia en `.claude/skills/SUPERPOWERS.md`). Se invocan sin prefijo: `brainstorming`, `writing-plans`, etc.
El modo corto (estilo caveman) es una preferencia personal en el `CLAUDE.md` local, que no se versiona.

| Pieza | Uso en este trabajo |
|---|---|
| **Superpowers** (obra) | Columna vertebral. `brainstorming` (diseño, una pregunta por vez), `writing-plans`, `using-git-worktrees` (un worktree por frente), `subagent-driven-development` (un subagente por tarea del plan, con revisión entre tareas), `test-driven-development`, `systematic-debugging` (fallos con Bonita), `dispatching-parallel-agents` (frentes independientes), `requesting-code-review`, `verification-before-completion`, `finishing-a-development-branch` (PR a `dev`). |
| **Modo corto** (caveman) | Respuestas cortas en el chat para ahorrar lectura y tokens. **No** se aplica a: informe, Swagger, textos de UI ni mensajes de commit. |

### Skills del repo (`.claude/skills/`)
| Skill | Cuándo |
|---|---|
| `rescuesync-estado` | Al arrancar cada sesión |
| `nuevo-endpoint` | Endpoints del dashboard y de consorcios (checklist: validación 422, Swagger, tests, docs) |
| `probar-en-nube` | Cierre de cada frente, con Bonita real (en la PC del usuario) |
| `editar-bos` / `rescuesync-bpmn` | Solo si consorcios o indicadores obligan a tocar el proceso (idealmente no) |

### Subagentes
| Agente | Cuándo |
|---|---|
| `Explore` / `Plan` | Relevar código antes de cada spec; diseñar el plan |
| `verificador` | Después de cada tarea: `verificar_todo.py` y devuelve solo el resultado |
| `revisor-de-diffs` | Antes de cada PR (SQLite vs Postgres, 500 vs 422, Swagger/README, secretos, tests) |
| `lector-de-logs` | Fallos de escenarios, Bonita o uvicorn: causa raíz en pocas líneas |
| `general-purpose` | Redacción en paralelo de secciones del informe (una por componente) |

### Skills del entorno
- `dataviz`: paleta, tipos de gráfico y KPIs del dashboard (antes de escribir el primer gráfico).
- `/code-review` y `/security-review`: sobre cada PR, además del `revisor-de-diffs`.
- `/simplify`: pasada de limpieza al terminar cada frente.
- `artifact-diagramming`: diagramas de arquitectura y de secuencia para el informe.
- `docx` / `pdf`: armar el informe final en el formato que pida la cátedra.

### Hooks propuestos (`.claude/settings.json`)
Hoy `.gitignore` excluye `.claude/*` salvo `agents/` y `skills/`, así que los hooks quedarían solo en la PC
de cada uno. **Decisión pendiente:** versionar `.claude/settings.json` (agregar `!.claude/settings.json`) para que el equipo los tenga.

| Evento | Qué hace | Por qué |
|---|---|---|
| `PreToolUse` en `Bash(git commit*)` | Corre `python scripts/verificar_todo.py`; si falla, bloquea el commit | Que nada entre sin tests verdes (~30 s) |
| `PreToolUse` en `Edit\|Write` sobre `*.bos` | Bloquea y recuerda el skill `editar-bos` | El `.bos` se edita solo por script |
| `PreToolUse` en `Edit\|Write` sobre `.env*` | Bloquea | Secretos fuera del alcance del agente |
| `SessionStart` | Imprime rama, último commit y estado de `dev` vs rama | Orientación rápida (complementa el hook de Superpowers) |

Los hooks se escriben en Python (corren igual en Windows y en la nube).

### Sesiones en la nube en paralelo
Sirven para frentes que no necesitan Bonita (backend con fakes, front, redacción del informe). **Bonita corre en la
PC del usuario (`:8080`)**: las pruebas con Bonita real (`probar-en-nube`, escenarios) se hacen allá, una por vez.

## 3. Pipeline por frente

1. `brainstorming` → spec `docs/superpowers/specs/AAAA-MM-DD-<frente>-design.md` (revisada por el usuario)
2. `writing-plans` → plan `docs/superpowers/plans/AAAA-MM-DD-<frente>.md` con "Review Focus", como el de alta-ong
3. `using-git-worktrees` → rama `feat/<frente>` desde `dev`
4. `subagent-driven-development` + TDD → una tarea por subagente; `verificador` al terminar cada una
5. `revisor-de-diffs` + `/code-review` → PR a `dev` → CI verde (job "CI verde")
6. `probar-en-nube` en la PC del usuario → `verification-before-completion` → merge

## 4. Frentes, en orden

### A. Dashboard de indicadores (ítem 4) — prioridad 1
Borrador para el brainstorming (no es la spec):
- **Backend** `app/services/indicadores.py` + `GET /api/indicadores` (rol AUDITOR; ¿también COORDINADOR?) con filtros de fecha/municipio, y `GET /api/indicadores/export?formato=csv|json`.
  - Datos propios: emergencias por estado y finalizadas, suministros movilizados por mes y tipo de recurso (ítems de la versión vigente de ofertas adjudicadas), % de cobertura por emergencia, ofertas y ediciones por ONG, % de emergencias resueltas con consorcio (depende de B).
  - Datos de Bonita: tiempo promedio por etapa a partir de `archivedHumanTask` (`reached_state_date` → `archivedDate`, agrupado por tarea) y duración total del caso. `BonitaClient.get_archived_human_tasks` ya existe.
  - Si Bonita no responde, la sección de tiempos dice "no disponible" y el resto se muestra (nunca 500).
- **Front**: página `/indicadores` con tarjetas KPI, barras (suministros por mes), torta o anillo (estados), barras horizontales (tiempo por etapa) con tooltips, filtros y botones de exportar. Hay que elegir la librería de gráficos (hoy no hay ninguna; candidata: Recharts).
- **Datos de demo**: hace falta historial. Ojo con el **tope de 150 casos por proyecto en Bonita**: reusar los casos de los escenarios antes que generar casos nuevos.
- **Tests**: servicio con `FakeBonita`, 403 para los otros roles, formatos de exportación, Bonita caído; prueba de UI con captura.

### B. Consorcios entre ONGs (ítem 2) — prioridad 2, **decisión pendiente**
La consigna los nombra en el eslabón 3 y en el perfil ONG. Opción mínima: una oferta con ONG líder + ONGs asociadas,
cada línea atribuida a una ONG, y que la reserva en Nacional se haga por ONG. Toca modelo, migración, UI de ofertas,
el JSON que lee Bonita y la evaluación. Sin esto, la métrica "% resuelto mediante consorcios" del dashboard no tiene datos.

### C. Perfil Auditor/Directivo completo — sale con A
Menú propio (Indicadores + consulta de emergencias en solo lectura) y tests de permisos.

### D. Informe final (Entrega 5) — se empieza en paralelo el 12/11
Estructura propuesta:
1. Introducción y alcance
2. Arquitectura general (diagrama de componentes)
3. Un capítulo por componente (Bonita, app web, API Nacional, dashboard, Postgres/Docker/Render): rol, tecnología, interfaces
4. Interacciones (diagramas de secuencia: alta → convocatoria → timer → GET de ofertas → validación y lock → adjudicación → cierre y liberación)
5. Seguridad (sesión, JWT, cuentas de servicio)
6. Pruebas y CI
7. Despliegue e instalación
8. Desvíos respecto del modelo (Gantt)
9. Conclusiones

Fuentes: `README.md`, `docs/instalacion-*.md`, `entrega-3/ENTREGA.md`, specs y planes. Cada capítulo de componente lo redacta un subagente en paralelo y después se unifica el estilo.

### E. Gantt de la Entrega 4 — verificar hoy
Si no se entregó, actualizar `entrega-1/Diagrama de gantt.xlsx` (skill `xlsx`) con los desvíos reales y los frentes A–D.

### F. Coloquio (26/11)
Guion de demo por rol, plan B local (`docs/instalacion-local.md`), preguntas probables y quién responde cada una.

## 5. Calendario

| Fecha | Qué |
|---|---|
| Dom 8/11 | Este plan; instalar plugins; hooks; decisiones abiertas |
| Lun 9 – Mar 10 | A: brainstorming, spec y plan; backend de indicadores (TDD) |
| Mié 11 – Vie 13 | A: front y exportación. B si se aprueba (en paralelo, otro worktree) |
| Jue 12 → | D: capítulos que no dependen de A ni de B |
| Sáb 14 – Dom 15 | `probar-en-nube` completo con Bonita real; datos de demo; correcciones |
| Lun 16 – Mié 18 | D: capítulos del dashboard y de consorcios, diagramas, revisión, PDF |
| **Jue 19/11** | **Entrega 5** |
| 20 – 25/11 | F: ensayo del coloquio |

## 6. Decisiones abiertas
1. ¿Se hacen consorcios (B)? ¿Alcance mínimo o completo?
2. Dashboard: ¿quién lo ve (solo Auditor o también Coordinador)? ¿Qué métricas exactas? ¿Librería de gráficos?
3. Exportación: ¿CSV y JSON alcanza, o también XLSX/PDF?
4. ¿Se versionan los hooks (`.claude/settings.json`)?
5. Formato del informe (¿docx/PDF? ¿plantilla de la cátedra?) y estado de la Entrega 4.

## 7. Riesgos
- Tope de 150 casos de Bonita Community: contar casos antes de generar datos de demo.
- Pruebas simultáneas sobre el mismo Bonita, app o Render se pisan: una por vez.
- Render dormido (30-60 s en la primera llamada): despertarlo antes de la demo.
- Postgres rechaza lo que SQLite acepta: los datos inválidos dan 422, nunca 500; CI con Postgres 16.
- Si consorcios cambia el JSON de ofertas, el `.bos` y la API Nacional tienen que seguir compatibles.
