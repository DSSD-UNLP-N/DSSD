# Cambios manuales en Bonita Studio (rama `migracion-bonita`)

Bitácora de lo que se cambió a mano en Studio/motor y cómo deshacerlo. Studio no versiona
el diagrama como texto, así que un rollback por git solo alcanza para `ACME.xml` y el `.bos`.
El resto hay que revertirlo a mano con estos pasos.

**Punto de retorno:** tag `checkpoint-pre-migracion-20260925` (commit `533239f`), con el
`.bos` y la organización tal como estaban en la demo de la Entrega 2 (e2e 54/54).

```bash
git checkout checkpoint-pre-migracion-20260925 -- entrega-2/
```

Después: importar el `.bos` en Studio, importar y **Desplegar** `ACME.xml`, y **Ejecutar**.

## Cambio 1 — Organización con roles y usuarios reales (Fase 1)

| | antes | después |
|---|---|---|
| Archivo | `entrega-2/ACME.xml` (24 usuarios) | `entrega-2/ACME.xml` (7 usuarios) |
| Roles | `member` | `member` + `operador_municipal`, `coordinador_regional`, `representante_ong`, `auditor` |
| Usuarios | operador.municipal, coordinador.regional, ong.cruzroja + 21 de ACME | walter.bates, operador.municipal, **operador.municipal2**, coordinador.regional, ong.cruzroja, **ong.bomberos**, **auditor** |
| Grupos | `/rescuesync/{municipio,coordinador,ong}` | los mismos + `/rescuesync/auditoria` |
| Actor mapping | por grupo | **sin cambios** (por grupo, ids 102/103/104) |

Cómo se aplicó: Studio → importar `ACME.xml` → botón **Desplegar** en el editor de la
organización → redesplegar el proceso.

**Ojo con el rollback:** desplegar una organización *suma y actualiza, no borra*. Los 21
usuarios de ACME que ya no están en el XML **siguen en el motor** (27 usuarios en total), y
los roles nuevos tampoco desaparecen al reimportar la organización vieja. No molestan.
Para limpiarlos: Portal de Bonita → Organización.

Cada usuario tiene contraseña `bpm` y el mismo username que su cuenta de la app
(la app entra a Bonita con `BONITA_TEST_PASSWORD`).

Verificación: contra el motor, `GET /API/identity/role` devuelve 5 roles y
`GET /API/identity/group` incluye `auditoria`.

## Cambio 2 — `Municipio` como actor iniciador del Pool (Fase 2)

Dónde: seleccionar el **Pool** (no una lane) → pestaña **General** → **Actores** → fila
`Municipio` → botón. **El botón muestra la acción inversa al estado actual**: dice
"Iniciador sin establecer" cuando `Municipio` *ya es* el iniciador (clic = quitarlo) y
"Establecer como iniciador" cuando no lo es (clic = ponerlo). Sin iniciador, Studio avisa
que el proceso "solo se puede iniciar mediante programación".

Rollback: mismo lugar, mismo botón, y volver a **Ejecutar**.

**Qué hace y qué no.** La marca solo indica quién ve el proceso como iniciable en el Portal de
Bonita. **No restringe las llamadas REST de instanciación**: con `Municipio` como iniciador,
`coordinador.regional`, `ong.cruzroja` y `auditor` igual pudieron instanciar por REST (se
probó). La restricción real de quién da de alta una emergencia es la de la app
(`require_role(Rol.MUNICIPIO)`), no la del motor.

Lo que sí garantiza la Fase 2, independientemente de esta marca: como la app entra a Bonita
con el username del operador, el caso figura `started_by` = ese operador (verificado en el
e2e con `operador.municipal`; el segundo operador tiene su propio test).

## Cambios en el código que dependen de los de Studio

| Commit / cambio | Depende de |
|---|---|
| `497399f` seed con `operador.municipal2` | Cambio 1 |
| `registrar_emergencia` entra a Bonita como el operador, no como `walter.bates` | Cambio 1 (los usuarios deben existir) y Cambio 2 |

Si se revierte el Cambio 1 y no el código, el alta falla con 401 al loguearse en Bonita.

## Estado

- Cambio 1: aplicado y verificado (5 roles, 7 usuarios propios, e2e 58/58).
- Cambio 2: aplicado, e2e 58/58. Es opcional para la migración: no restringe por REST (ver
  arriba). Conviene dejarlo marcado (modelo correcto, sin aviso de Studio); si en Studio
  quedó sin marcar, volver a poner `Municipio` como iniciador con el próximo redeploy.
