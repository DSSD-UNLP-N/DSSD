# Prueba a mano de la Parada 2: decisión y adjudicación

La guía completa, con capturas, comandos, qué mirar en Bonita y en la API Nacional y el resultado de la corrida, está en
[`guia-parada-2.html`](guia-parada-2.html) (abrirla en el navegador; las imágenes están en `img/parada-2/`).

Resumen de lo que se prueba, con los usuarios de la app (clave `demo1234`):

1. **Caso A, cobertura parcial:** `operador.municipal` registra una emergencia ALTO; `coordinador.regional` carga el lote
   PARAMEDICO 10 y publica con un cierre a unos 5 minutos; `ong.cruzroja` ofrece 4 y `ong.bomberos` 2 (60 %). Al vencer, Bonita
   evalúa y reserva; el Coordinador elige *Seguir con cobertura parcial*; el Municipio adjudica solo a Cruz Roja.
2. **Caso B, reformular:** lote RACION_ALIMENTO 3000; Cruz Roja ofrece 2000 (66,7 %); el Coordinador elige *Reformular*; se
   publica de nuevo (ronda 2), Cruz Roja ofrece 3000, la cobertura es completa y va directo a adjudicación.

Se usan paramédicos y raciones (no agua) porque una oferta vieja de Cruz Roja en la emergencia 1 ocupa el tope del agua.

Automático (unos 15 minutos, con capturas): `backend/.venv/Scripts/python backend/scripts/ui_parada2.py`.
