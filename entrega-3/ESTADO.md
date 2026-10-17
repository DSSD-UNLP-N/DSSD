# Estado vivo de la Entrega 3

Se actualiza en cada checkpoint. Última actualización: **17/10/2026**. Entrega: **jueves 22/10**.
Rama `modelado-tomas-e-3`, [PR #10](https://github.com/FrancoCirielli16/DSSD/pull/10) a `dev` abierto.

## Hecho (y cómo se probó)
- WP0 contratos, WP1 consolidado de ofertas + estados nuevos + tope, WP2 reserva todo-o-nada en la API Nacional,
  WP5 decisión del Coordinador y adjudicación del Municipio, conectores de Bonita para evaluar, avisar y resolver reservas.
- **Parada 1** (evaluación con reserva) 26/26 y **Parada 2** (decisión, adjudicación, ronda 2) 34/34 por API, con Bonita real.
- **Parada 2 por la interfaz real (17/10):** `backend/scripts/ui_parada2.py` 46/46 (dos casos: parcial y reformular), con capturas
  de cada paso. Guía con imágenes: `guia-parada-2.html` ([publicada](https://claude.ai/artifact/K47xuvWUCXUHAwvfTv643L), privada).
  **Tomás todavía no la recorrió a mano.**
- Tests: backend 188 pasan / 2 se saltean (16 s), API Nacional 93 / 3. `verificar_despliegue.py` local 53/53.
- `.bos` actual con los 5 conectores: `entrega41_20261017_1311.bos`.

## Falta
- **Parada 3 (cierre):** WP3 `POST /cierres` por referencia, WP6 ONG marca finalizada + monitoreo + cierre bilateral + notificaciones
  + multi-instancia de "Confirmar Finalizacion" + conector "Liberar Recursos y Notificar Cierre" y evento `CIERRE`.
- WP9 recorrido completo de punta a punta, WP7 Render con el código nuevo, WP8 Docker Compose + Postgres, WP10 entrega,
  WP11 JWT (postergado), WP12 parámetros de Bonita (al final).
- Plan de la nube y de Local vs Production: `plan-nube-docker-entrega.md`.

## Cómo se verifica
```
python scripts/verificar_todo.py                                              # tests backend + nacional + tipos del front
python backend/scripts/escenario_evaluacion.py                                # Parada 1 (Bonita real)
python backend/scripts/escenario_adjudicacion.py                              # Parada 2 por API (Bonita real)
python backend/scripts/ui_parada2.py                                          # Parada 2 por la interfaz, con capturas (~15 min)
python backend/scripts/escenario_tope.py                                      # tope de ofertas
PYTHONIOENCODING=utf-8 python nacional/scripts/verificar_despliegue.py http://localhost:8002
```
Los escenarios necesitan Bonita (`:8080`), la app (`:8001`) y la API Nacional (`:8002`) arriba.

## Entorno (17/10)
- Bonita: proceso desplegado 12:58, 0 casos, usuarios `operador.municipal`, `coordinador.regional`, `ong.cruzroja` (pass `bpm`).
- Servidores de preview: `rescuesync-backend` (8001), `rescuesync-frontend` (5173), `rescuesync-nacional` (8002). Mueren entre turnos.

## Trampas conocidas
- Cada **Ejecutar** en Studio borra los casos. Tomcat puede tardar hasta 4 minutos: no tocar Studio y esperar.
- Si "Run" dice que falló el login de `walter.bates`, la causa real suele estar en `workspace\tomcat\server\logs\bonita.log` (Connection refused).
- Nube: la base de Render persiste. Una referencia ya `LIBERADA` o `CERRADA` da 409. No reiniciar la base local al probar contra la nube.
- Nunca apuntar `POSTGRES_TEST_DATABASE_URL` a la base de la demo: las pruebas de concurrencia hacen `drop_all`.
- Windows: correr los scripts con `PYTHONIOENCODING=utf-8` si fallan por un carácter.

## Ayudas de Claude en este proyecto
- `.claude/agents/lector-de-logs` (lee logs largos y devuelve la causa) y `.claude/agents/verificador` (corre los chequeos y devuelve el resultado).
