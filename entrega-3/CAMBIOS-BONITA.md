# Cambios en el proyecto de Bonita (Entrega 3)

Bitácora de lo que se tocó en `RescueSync-1.0.proc` desde el export de la Entrega 2. El export vigente está en este directorio
(`entrega41_*.bos`).

| Fecha | Cambio | Cómo |
|---|---|---|
| 15-17/10 | Cinco conectores REST: `get obteber ofertas` (GET a la app), `evaluarOfertas` (POST `/evaluaciones`), `avisarEvaluacion` (evento `EVALUACION`), `resolverReservas` (POST `/adjudicaciones/resolucion`), `avisarAdjudicacion` (evento `ADJUDICACION`). Variable nueva `evaluacionJson`. Timeouts de 60 s. | En Studio |
| 17/10 | Dos conectores en «Liberar Recursos y Notificar Cierre»: `cerrarAdjudicaciones` (POST `/cierres/lote` con un `{cuit, referencia}` por cada ONG adjudicada) y `avisarCierre` (evento `CIERRE` con los CUIT adjudicados). Son clones de `resolverReservas` y `avisarAdjudicacion` con otra URL y otro cuerpo. | `bonita/scripts/agregar_conector_cierre.py` genera el `.bos` nuevo; se importa en Studio |

## Para volver atrás
El `.bos` anterior queda en el repo hasta que el nuevo se pruebe con Bonita real (`escenario_cierre.py`).

## Sin cambiar a propósito
«Confirmar Finalizacion de Actividades» sigue marcada como multi-instancia sin configurar (Studio la señala en rojo). Probado con
Bonita real el 17/10: el motor crea una sola instancia y la app la completa cuando terminaron todas las ONGs, así que alcanza.
Para sacar el aviso rojo: en Studio, propiedades de la tarea, General, cambiar el tipo a «Estándar».
