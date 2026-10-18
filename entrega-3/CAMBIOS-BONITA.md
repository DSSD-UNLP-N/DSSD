# Cambios en el proyecto de Bonita (Entrega 3)

Bitácora de lo que se tocó en `RescueSync-1.0.proc` desde el export de la Entrega 2. El export vigente está en este directorio
(`entrega41_*.bos`).

| Fecha | Cambio | Cómo |
|---|---|---|
| 15-17/10 | Cinco conectores REST: `get obteber ofertas` (GET a la app), `evaluarOfertas` (POST `/evaluaciones`), `avisarEvaluacion` (evento `EVALUACION`), `resolverReservas` (POST `/adjudicaciones/resolucion`), `avisarAdjudicacion` (evento `ADJUDICACION`). Variable nueva `evaluacionJson`. Timeouts de 60 s. | En Studio |
| 17/10 | Dos conectores en «Liberar Recursos y Notificar Cierre»: `cerrarAdjudicaciones` (POST `/cierres/lote` con un `{cuit, referencia}` por cada ONG adjudicada) y `avisarCierre` (evento `CIERRE` con los CUIT adjudicados). Son clones de `resolverReservas` y `avisarAdjudicacion` con otra URL y otro cuerpo. | `bonita/scripts/agregar_conector_cierre.py` genera el `.bos` nuevo; se importa en Studio |
| 17/10 | «Confirmar Finalizacion de Actividades» pasa de multi-instancia a tarea estándar (se le saca `type="PARALLEL"`). | El mismo script, en `entrega41_20261017_1311_cierre_v2.bos`. Falta importarlo en Studio y repetir `escenario_cierre_variantes.py` |

## Para volver atrás
El `.bos` anterior queda en el repo hasta que el nuevo se pruebe con Bonita real (`escenario_cierre.py`).

## Pendiente de la versión v2
«Confirmar Finalizacion de Actividades» sigue, en el `.bos` ya probado, como multi-instancia sin configurar (Studio la señala en rojo).
Con Bonita real el motor crea una sola instancia y la app la completa cuando terminaron todas las ONGs, así que anda. En
`..._cierre_v2.bos` queda como tarea estándar y desaparece el aviso; hay que importarlo, ejecutar y repetir los escenarios antes de
darlo por bueno. Si algo anda distinto, se vuelve al `_cierre.bos`.

## Si un conector del cierre falla
Probado el 17/10 apagando la API Nacional (o la app) justo al validar el cierre: Bonita deja «Liberar Recursos y Notificar Cierre»
como **nodo fallido** (un conector en `FAILED`, el otro sin ejecutar), la emergencia sigue `EN_EJECUCION` con el cierre validado y
repetir «Validar cierre» da 409. No se rompe nada ni se cierra dos veces: los dos pasos son idempotentes.

La API REST de Bonita Community no permite reintentar el nodo (`PUT /API/bpm/activity` solo acepta `skipped` y `completed`, y
`connectorInstance` no admite `PUT`). Para destrabarlo, con la API Nacional y la app arriba:

```
python backend/scripts/recuperar_cierre.py <número de emergencia>
```

Repite lo que hacen los conectores (cierra las referencias, manda el evento `CIERRE`) y marca el nodo fallido como `skipped` para que
el caso termine. También se puede hacer desde el Portal de administración de Bonita (Reintentar la tarea fallida), pero ese camino no
está probado. Antes de la demo en la nube, despertar la API Nacional de Render con una llamada (el primer pedido tras un rato
dormida tarda, y el conector podría fallar).
