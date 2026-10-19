# Parada 3 — de la emergencia al cierre, paso a paso

Recorrido real por la interfaz con Bonita real, el que automatiza `backend/scripts/ui_parada3.py` (47 verificaciones; también corrido contra la
API Nacional en la nube). Una emergencia, dos ONGs. Las capturas son de esa corrida.

Cómo repetirlo: Bonita con `entrega42_local.bos` desplegado, app en `:8001`, front en `:5173`, API Nacional (local en `:8002` o la de Render) con el seed y
nada comprometido; después `cd backend && python scripts/ui_parada3.py`.

## 1. El Municipio registra la emergencia
Inundación, gravedad alta. Al guardar, la app crea el caso en Bonita y completa «Registrar Emergencia» como `operador.municipal`.

![Formulario](img/parada-3/01-municipio-formulario.png)
![Detalle](img/parada-3/02-municipio-detalle.png)

## 2. El Coordinador carga el lote y publica la convocatoria
10 paramédicos, con la ventana de ofertas (la fecha de cierre la usa el timer de Bonita).

![Lote](img/parada-3/03-coordinador-lote.png)
![Publicada](img/parada-3/04-coordinador-publicada.png)

## 3. Las ONGs ofrecen
Cruz Roja ofrece 4 y Bomberos 2: cobertura del 60 %. La app guarda las ofertas; **nunca** completa la tarea «Cargar Ofertas de Ayuda» de Bonita.

![Cruz Roja](img/parada-3/05-ong-cruzroja-oferta.png)
![Bomberos](img/parada-3/06-ong-bomberos-oferta.png)

## 4. Vence la ventana: Bonita evalúa y el Coordinador decide
Al vencer el timer, Bonita inicia sesión en la API Nacional (JWT), valida las ofertas y **reserva el stock**. El Coordinador ve la cobertura (60 %, no alcanza) y sigue con la cobertura parcial.

![Evaluación](img/parada-3/07-coordinador-evaluacion.png)

## 5. El Municipio adjudica
Elige las dos ONGs. Bonita confirma las reservas en la API Nacional y la emergencia pasa a **En ejecución**.

![Adjudicar](img/parada-3/08-municipio-adjudicar.png)
![En ejecución](img/parada-3/09-municipio-en-ejecucion.png)

## 6. Ejecución: el Coordinador monitorea y las ONGs finalizan
El Coordinador inicia el monitoreo (Bonita avanza a «Confirmar Finalizacion de Actividades»). Cada ONG marca su actividad como finalizada y ve solo su propia fila;
Bonita avanza a «Validar Cierre» recién cuando termina la última.

![Antes de monitorear](img/parada-3/10-coordinador-antes-de-monitorear.png)
![Monitoreando](img/parada-3/11-coordinador-monitoreando.png)
![Cruz Roja finaliza](img/parada-3/12-ong-cruzroja-antes-de-finalizar.png)
![Bomberos finaliza](img/parada-3/13-ong-bomberos-antes-de-finalizar.png)

## 7. Cierre bilateral
Con las dos ONGs terminadas, el Coordinador valida el cierre. Bonita ejecuta «Liberar Recursos y Notificar Cierre»: inicia sesión en la API Nacional, la
cierra en lote (libera y descuenta el stock, un solo cierre por ONG) y avisa a la app, que marca la emergencia **Resuelta**.

![Validar cierre](img/parada-3/14-coordinador-valida-cierre.png)
![Resuelta](img/parada-3/15-coordinador-resuelta.png)

## 8. Avisos y estado final
Cada ONG recibe el aviso en la campana (se marca como leído al abrirlo) y el Municipio ve la emergencia resuelta.

![Campana Cruz Roja](img/parada-3/16-ong-cruzroja-campana.png)
![Cruz Roja resuelta](img/parada-3/17-ong-cruzroja-resuelta.png)
![Campana Bomberos](img/parada-3/18-ong-bomberos-campana.png)
![Bomberos resuelta](img/parada-3/19-ong-bomberos-resuelta.png)
![Municipio](img/parada-3/20-municipio-resuelta.png)

## Qué pasa si algo falla
- **La API Nacional no responde al cerrar:** el nodo «Liberar Recursos y Notificar Cierre» de Bonita queda fallido y la emergencia sigue «En ejecución». Con la API de vuelta,
  `python backend/scripts/recuperar_cierre.py` lo termina sin duplicar nada (los cierres son idempotentes). Probado en `escenario_cierre_variantes.py`.
- **Clave de `bonita-service` rotada o token vencido:** ver `backend/scripts/escenario_jwt.py` (la app vuelve a entrar sola; en Bonita el nodo queda fallido hasta restaurar la clave).
