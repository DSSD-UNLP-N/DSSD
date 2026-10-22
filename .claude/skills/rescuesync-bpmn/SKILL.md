---
name: rescuesync-bpmn
description: Read, understand, and edit the RescueSync BPMN process (entrega-1/RescueSync.bpmn) for this DSSD Bonita BPM university project. Use this whenever the user wants to develop, modify, extend, or discuss "el diagrama RescueSync", "el proceso", "el BPMN", RescueSync's tasks/gateways/lanes/variables, or anything about the emergency-management process model in this repo — even if they just say "agregá una tarea", "cambiá el flujo", "sacame un diagrama del proceso" without naming the file. Also use it before answering questions about what the process does, since the raw XML is not self-explanatory without this context.
---

# RescueSync BPMN skill

## What this file is (and isn't)

`entrega-1/RescueSync.bpmn` is a standard BPMN 2.0 XML export of the RescueSync
process, produced from Bonita Studio 10.4.0. Treat it as the **working
spec/reference copy** you read and edit directly — it's plain XML, no special
tool needed.

The real source of truth inside Bonita is `entrega-1/RescueSync.bos`, a binary
zip (Bonita project archive) that can only be opened and edited inside Bonita
Studio itself. You cannot touch `.bos` directly, and it does **not**
auto-sync with the `.bpmn`. So the workflow is always:

1. Edit `RescueSync.bpmn` here.
2. Tell the user explicitly, every time, that they need to manually replicate
   the change in Bonita Studio (open the `.bos`, make the same change on the
   `.proc` diagram, re-export/save). Don't let this reminder get lost — it's
   the one step that's easy to forget and the two files silently drift apart
   if skipped.

See the repo's local CLAUDE.md for the full repo/Bonita context (versions, git
conventions for `.bos`/`.bar` binaries, etc.) if you need it.

## What the process models

RescueSync = "Gestion Integral de la Emergencia", a single pool orchestrating
an emergency's lifecycle: registration → generating batches of needs →
publishing the call and notifying NGOs → NGOs load offers → offer window
closes → fetching and validating offers, calculating coverage → decision
(full coverage vs. partial, with a reformulate-and-retry loop) → award →
notification and national commitment registration → deployment monitoring →
bilateral closeout → resource release and closure notice.

**Important — element IDs are opaque and will change on every Studio
export.** The moment this file was created, it used readable ids like
`T_registrarEmergencia`. As soon as the user re-exports from Bonita Studio
(as happened already once), Studio regenerates every id as an unreadable GUID
(e.g. `_iE69sKxXEfGR3cB9VRwXjA`) and may restructure/rename/merge elements.
**Never rely on memorized ids from a previous read of this file or from this
skill.** Always re-read the current `.bpmn`, and identify elements by their
`name` attribute — that's the only thing that stays human-meaningful across
exports. Update the tables below (lanes, variables, branches) whenever you
notice they've drifted from what's actually in the file, the same way this
skill was refreshed after this project's own first Studio round-trip.

### Lanes and who owns what (as of the latest read — verify against the live file)

- **"Municipio (Operador Municipal)"**: Emergencia detectada (start) →
  Registrar Emergencia → Adjudicar Ofertas
- **"Centro Coordinador Regional"**: Revisar Informacion y Generar Lotes de
  Necesidades → Publicar Convocatoria y Notificar a la Red de ONGs →
  Evaluar Cobertura y Definir Curso de Accion → gateway "Curso de accion" →
  Monitorear Ejecucion del Despliegue → Validar Cierre Operativo Bilateral
- **"ONG / Organismo de Rescate"**: Cargar Ofertas de Ayuda (with a boundary
  timer "Cierre de la ventana de recepcion de ofertas" attached) →
  Confirmar Finalizacion de Actividades (multi-instance, one per awarded NGO)
- **"Entidad Nacional / Sistema RescueSync"** (renamed from an earlier
  "Sistema RescueSync (BPM / Conectores)" — don't be surprised if the label
  keeps evolving): Obtener Ofertas de la Red (GET App Local) → Validar en
  Sistema Nacional y Calcular Cobertura → gateway "Se cubrieron todos los
  lotes?" → Notificar Adjudicacion y Registrar Compromiso Nacional →
  Liberar Recursos y Notificar Cierre → Emergencia cerrada (end)

When adding a node, put it in the lane whose actor actually performs it — a
`userTask` goes in a human lane (Municipio/CCR/ONG), a `serviceTask` goes in
the system/national lane (it represents a connector call).

### Naming convention

The **current live file no longer uses readable id prefixes** (that was true
only of the very first hand-authored version). Studio-exported ids look like
`_iE69sKxXEfGR3cB9VRwXjA` and carry no semantic meaning — don't try to
pattern-match on them. What you *can* rely on:
- Element `name` attributes are human-written and meaningful — always match
  by name, and when writing new elements give them a clear Spanish name
  consistent with the existing ones.
- The XML element tag itself tells you the type (`model:userTask`,
  `model:serviceTask`, `model:exclusiveGateway`, `model:boundaryEvent`,
  `model:startEvent`, `model:endEvent`) — this is Bonita's own namespace
  (`model:`, `di:`, `di_1:`), not the plain `bpmn:`/`bpmndi:` namespace the
  hand-authored version used. Check the `xmlns` declarations at the top of
  the file before assuming which prefix is in play.
- Most sequence flows in the current export have `name=""` (empty) — only
  the ones carrying a decision label or condition have a real `name`. That's
  fine; don't invent names for unconditional flows just for symmetry.

### Process variables

Documented in the `model:documentation` (CDATA) block inside `model:process`,
referenced via `${varName}` in `conditionExpression` — but **not yet created
as real Bonita variables inside the `.bos`**, that's a Studio task.

- `emergenciaId` (Long), `municipioId` (Long), `nivelGravedad` (String)
- `ventanaOfertasISO` (String) — feeds the boundary timer on "Cargar Ofertas
  de Ayuda"
- `coberturaCompleta` (Boolean), `porcentajeCobertura` (Double)
- `decisionCoordinador` (String) — values currently used:
  `"REFORMULAR"`, `"PARCIAL"` (fewer than before — see branching below)
- `ofertasJson` (String), `ongsAdjudicadas` (String)

**Note:** an earlier version of this process also had `plazoAdjudicacionISO`
feeding an adjudication-timeout boundary event. That element and variable
are gone in the current export (see below) — don't assume it still exists
just because it's mentioned in older documentation or memory.

If you introduce a new condition or timer, either reuse one of these or add
the new variable name to the `model:documentation` block *and* flag to the
user that it still needs to be created in Bonita Studio.

### The branching logic (verify structure against the live file — it has changed once already)

**Gateway "Se cubrieron todos los lotes?"** (default flow → award):
- default/unconditioned → full coverage → Adjudicar Ofertas
- `${coberturaCompleta == false}` → Evaluar Cobertura y Definir Curso de
  Accion

**Gateway "Curso de accion"** (fed by "Evaluar Cobertura..."), branches on
`decisionCoordinador`:
- `"REFORMULAR"` → loops back to "Revisar Informacion y Generar Lotes de
  Necesidades" (redo the batches)
- `"PARCIAL"` → proceeds to "Adjudicar Ofertas" (continue with partial
  coverage)

Earlier iterations of this process also had `"REABRIR"` (reopen the call) and
`"CANCELAR"` (terminate with no coverage) branches plus a dedicated
cancellation end event — those are **not present** in the current export.
If the user asks to reintroduce cancellation/reopen logic, that's a
reasonable ask (it matches the originally documented design in the local CLAUDE.md)
but treat it as adding new branches, not restoring something that secretly
still exists.

The boundary timer "Cierre de la ventana de recepcion de ofertas" is attached
to "Cargar Ofertas de Ayuda" (`cancelActivity="true"`) — it cuts off NGOs
loading offers once the window closes, then flows into "Obtener Ofertas de
la Red". This replaced an earlier design where the timer was a standalone
intermediate event in the system lane and a *separate* boundary timeout
existed on the award step — that award-side timeout is gone for now.

Keep this mental model in mind before editing, but treat every fact in this
section as "true as of the last time someone read the file carefully" rather
than eternal — Bonita Studio re-exports can restructure things more than a
typical hand-edit would.

## Editing workflow

### 1. Read before you write

Read the full current `.bpmn` before editing it — not a partial view. IDs
must stay unique and every reference must match exactly:
`flowNodeRef` (in the lane) ↔ the element's own `id` ↔ its `incoming`/
`outgoing` flow ids ↔ the matching `sequenceFlow`'s `sourceRef`/`targetRef`
↔ the diagram's `bpmnElement` references. A mismatch anywhere in this chain
produces a `.bpmn` that looks fine but won't validate or render correctly.

### 2. Adding a node — do all of these, in order

1. Add its id to the correct `bpmn:lane`'s `flowNodeRef` list.
2. Add the element itself under `bpmn:process`, in roughly the same order as
   process flow (the file is easier to read and diff when element order
   tracks execution order — don't just append at the end).
3. Add/update the `incoming`/`outgoing` flow ids on the new element and on
   whatever it's now spliced between.
4. Add the `bpmn:sequenceFlow` element(s) for each new connection
   (`sourceRef`/`targetRef`, plus `name`/`conditionExpression` if it's a
   conditioned branch off a gateway).
5. **Add diagram info — this is the step it's easiest to forget, and BPMN
   viewers (including Bonita's) will render a node at `(0,0)` or not at all
   without it:**
   - A `bpmndi:BPMNShape` with `dc:Bounds` sized like its siblings: tasks
     ~120×72, gateways 50×50, events (start/end/timer/boundary) 36×36. Add a
     nested `bpmndi:BPMNLabel` with its own `dc:Bounds` if the element has a
     `name`.
   - A `bpmndi:BPMNEdge` with at least two `di:waypoint`s for every new
     `sequenceFlow`, plus a `BPMNLabel` if the flow has a `name`.
   - Place new shapes using the existing coordinate space as a guide: the
     pool spans roughly x=160→4590, with 4 lanes each 180px tall starting at
     y=80 (muni), y=260 (ccr), y=440 (ong), y=620 (sys). Slot new nodes into
     open space near their neighbors rather than recomputing the whole
     layout — this file's layout is hand-authored and wide by design.

### 3. Verify visually before the user touches Studio

After a non-trivial edit, offer to render the updated process as a diagram
(a Mermaid flowchart or an SVG artifact — see the `artifact-diagramming`
skill for how) so the user can sanity-check the new flow visually. The raw
XML diff is hard to read even for someone who knows BPMN; a picture catches
mistakes (like a dangling flow or a node in the wrong lane) much faster than
re-reading tags.

### 4. Always close the loop with Bonita Studio

End every edit session with an explicit reminder: this `.bpmn` change is not
live in the actual project until it's manually replicated inside Bonita
Studio on the `.bos`. Don't let this be implicit — say it plainly so the user
doesn't assume the two files are already in sync.

## Other notes

- `entrega-1/*.md` (the assignment brief, working notes) and the root
  CLAUDE.md are gitignored on purpose — they exist locally but aren't in
  version control. If you need the assignment spec for context and don't
  have it in the conversation already, ask the user or look for it under
  `entrega-1/` rather than assuming it doesn't exist.
- Don't invent Bonita-specific XML extensions (e.g. connector configuration,
  actor mappings) inside the `.bpmn` — those live only inside the `.bos` and
  Bonita Studio's own project format, and hand-writing them into the BPMN
  export wouldn't do anything real.
