# Cambios en el proyecto de Bonita (Entrega 3)

Bitácora de lo que se tocó en `RescueSync-1.0.proc` desde el export de la Entrega 2. El export vigente está en este directorio
(`entrega41_*.bos`).

| Fecha | Cambio | Cómo |
|---|---|---|
| 15-17/10 | Cinco conectores REST: `get obteber ofertas` (GET a la app), `evaluarOfertas` (POST `/evaluaciones`), `avisarEvaluacion` (evento `EVALUACION`), `resolverReservas` (POST `/adjudicaciones/resolucion`), `avisarAdjudicacion` (evento `ADJUDICACION`). Variable nueva `evaluacionJson`. Timeouts de 60 s. | En Studio |
| 17/10 | Dos conectores en «Liberar Recursos y Notificar Cierre»: `cerrarAdjudicaciones` (POST `/cierres/lote` con un `{cuit, referencia}` por cada ONG adjudicada) y `avisarCierre` (evento `CIERRE` con los CUIT adjudicados). Son clones de `resolverReservas` y `avisarAdjudicacion` con otra URL y otro cuerpo. | `bonita/scripts/agregar_conector_cierre.py` genera el `.bos` nuevo; se importa en Studio |
| 17/10 | «Confirmar Finalizacion de Actividades» pasa de multi-instancia a tarea estándar (se le saca `type="PARALLEL"`). | El mismo script, en `entrega41_20261017_1311_cierre_v2.bos`. Falta importarlo en Studio y repetir `escenario_cierre_variantes.py` |
| 18/10 | JWT en la API Nacional: un conector `loginNacional` (POST `/login` con la cuenta `bonita-service`) al principio de cada tarea que llama a Nacional (`evaluarOfertas`, `resolverReservas`, `cerrarAdjudicaciones`), y la cabecera `Authorization: Bearer <token>` en esas tres llamadas. Variable nueva `nacionalLoginJson` (Text) con la respuesta del login. | `bonita/scripts/agregar_login_nacional.py` sobre el `_cierre.bos` (el ya probado en Studio) genera `entrega41_20261017_1311_cierre_jwt.bos`; se importa en Studio. **Sin importarlo, los conectores reciben 401** de una API Nacional con JWT |

## Para volver atrás
El `.bos` anterior queda en el repo hasta que el nuevo se pruebe con Bonita real (`escenario_cierre.py`).

## Pendiente de la versión v2
«Confirmar Finalizacion de Actividades» sigue, en el `.bos` ya probado, como multi-instancia sin configurar (Studio la señala en rojo).
Con Bonita real el motor crea una sola instancia y la app la completa cuando terminaron todas las ONGs, así que anda. En
`..._cierre_v2.bos` queda como tarea estándar y desaparece el aviso; hay que importarlo, ejecutar y repetir los escenarios antes de
darlo por bueno. Si algo anda distinto, se vuelve al `_cierre.bos`.

## Login a la API Nacional (JWT)
La consigna pide que Bonita invoque a la API Nacional «con JWT». Un token vence (60 min por defecto) y una ventana de ofertas dura
horas, así que no se guarda uno fijo: **cada tarea que llama a Nacional empieza con `loginNacional`**, que pide un token nuevo, y el
conector siguiente lo manda como `Authorization: Bearer`. El token queda en `nacionalLoginJson` (el JSON del login) y se saca con
Groovy: `new groovy.json.JsonSlurper().parseText(nacionalLoginJson).access_token`. Las llamadas a la app siguen con `X-Api-Key`.

Cómo se arma y se prueba (parte del `_cierre.bos`, el que ya se importó y ejecutó, así lo único nuevo es el login; el `_v2.bos`
que saca la multi-instancia se puede aplicar después con el mismo método):

```
python bonita/scripts/agregar_login_nacional.py entrega-3/entrega41_20261017_1311_cierre.bos entrega-3/entrega41_20261017_1311_cierre_jwt.bos
```

En Studio: importar el `.bos` nuevo, Run, y con la API Nacional (con JWT) y la app arriba, `escenario_cierre.py` y
`escenario_cierre_variantes.py`. La cuenta y la clave están escritas en el conector (`bonita-service` / `change-me`, las de
desarrollo), igual que las URLs y el `X-Api-Key`: para la nube hay que cambiarlas, y llevarlas a parámetros del proceso es el
trabajo de «Local vs Production» (WP12). Si el motor no acepta la expresión Groovy dentro de la tabla de cabeceras, el síntoma es
un conector `evaluarOfertas` fallido con un error de expresión: avisar y se arma la variante que guarda la cabecera en una variable.

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
