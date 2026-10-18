# Estado vivo de la Entrega 3

Última actualización: **17/10/2026 (noche)**. Entrega: **jueves 22/10**.
Rama `modelado-tomas-e-3`. El [PR #10](https://github.com/FrancoCirielli16/DSSD/pull/10) ya está mergeado a `dev`; todo lo posterior
(cierre, ejecución, conectores, scripts, docs) está commiteado en la rama y **sin pushear**.

> **Rama `integracion-jwt` (18/10)**, salida del tag `e3-estable-20261017` (la versión estable, sin JWT). Trae `nacional/` de `dev`
> (JWT: `/login`, `/ongs`, cuentas) y deja la app con su sesión por cookie. La app y Bonita entran a Nacional con cuentas de servicio
> (`app-service`, `bonita-service`); las personas no necesitan cuenta ahí. Bonita usa `entrega41_20261017_1311_cierre_jwt.bos`
> (importado y ejecutado en Studio el 18/10). **Probado todo con Bonita real y bases nuevas (18/10):** evaluación 26/26 · tope 39/39 ·
> adjudicación 34/34 · cierre 28/28 · variantes 175/175 · `escenario_jwt.py` 39/39 (clave de Bonita rotada, secreto distinto, token
> vencido) · UI `e2e_ui` 59/59 · UI parada 2 46/46 · UI ejecución 25/25 · `verificar_despliegue.py` 72/72 · backend 222, nacional 126, tipos del front.
> Falta: pasar las credenciales y URLs de los conectores a parámetros del proceso (WP12), el resto de la entrega (WP7 hecho: API Nacional en Render, 72/72).

**En una línea:** el flujo completo funciona en local con Bonita real, de la emergencia al cierre y la liberación del stock.
Falta JWT, el deploy en la nube, Docker Compose, la entrega (README, video, prueba en limpio) y las variantes de prueba.
La tabla de paquetes de trabajo con responsables y horas está en [`plan-cierre-entrega.md`](plan-cierre-entrega.md) (sección «Estado al 17/10»).

## Hecho (y cómo se probó)
- **WP0 a WP6** completos: contratos, consolidado de ofertas, reserva todo o nada en la API Nacional, decisión del Coordinador,
  adjudicación del Municipio, ronda 2, cierre por referencia (`POST /cierres` y `/cierres/lote`), evento `CIERRE`, avisos, monitorear,
  finalizar, validar cierre, campana y botones en la SPA.
- **Siete conectores de Bonita**: obtener ofertas, evaluar, avisar evaluación, resolver reservas, avisar adjudicación, cerrar y avisar
  cierre. Los dos últimos se armaron sin Studio con `bonita/scripts/agregar_conector_cierre.py` y el `.bos` resultante se importó y
  ejecutó en Studio (17/10). Bitácora: [`CAMBIOS-BONITA.md`](CAMBIOS-BONITA.md).
- **Pruebas con Bonita real**: Parada 1 26/26 · Parada 2 34/34 por API y 46/46 por la interfaz (guía ilustrada
  [`guia-parada-2.html`](guia-parada-2.html)) · **cierre `escenario_cierre.py` 28/28** (las dos ONGs, Bonita libera sola y avisa) ·
  ejecución por la interfaz `ui_ejecucion.py` 24/25 (la falla era una espera del script, ya corregida).
- **Todo de nuevo desde cero (17/10 noche)**: bases locales nuevas (migraciones + seed) y `escenario_cierre.py` 28/28, más la batería
  `escenario_cierre_variantes.py` con Bonita real: subconjunto de ONGs, cobertura completa en la ronda 1, reformulación y cierre de la
  referencia `r2`, permisos y repeticiones, dos ONGs finalizando a la vez, API Nacional caída, app caída y eventos `CIERRE` a mano.
  Dejó el stock en cero y ningún caso abierto en Bonita.
- **Carrera corregida**: si las dos ONGs finalizaban en el mismo instante, ninguna completaba «Confirmar Finalizacion» y el caso
  quedaba trabado con las dos ofertas FINALIZADAS. Hay un test que fuerza ese orden.
- **Tests**: backend 206 pasan / 2 se saltean (17 s) · API Nacional 99 / 3 · tipos del front sin errores ·
  `verificar_despliegue.py` en local 61/61.
- Hallazgo: «Confirmar Finalizacion» sigue marcada multi-instancia sin configurar y el motor crea una sola instancia; la app la completa
  con el usuario de la ONG que finaliza última. Alcanza; en Studio se puede cambiar a «Estándar» para sacar el aviso rojo.

## Falta
| WP | Qué | h | Quién |
|---|---|---|---|
| WP11 | **JWT**: cuentas, `POST /login`, `POST /ongs`, protección por rol. Sin empezar y la consigna lo pide | 8 | Sin responsable (propuesta: Franco C., base `franco_v`) |
| ~~WP7~~ | **Hecho 18/10**: API Nacional en Render (`https://rescuesync-nacional.onrender.com`, Docker construido desde `dev`, auto-deploy en cada commit, Postgres), `verificar_despliegue.py` 72/72. El servicio viejo (imagen de Docker Hub) quedó suspendido. **La Postgres gratis vence el 15/11**, antes del coloquio (26/11): recrearla o pasarla a plan pago | 0 | Hecho |
| WP8 | Docker Compose completo (hoy solo hay Postgres), Dockerfile del backend y del front; probar la concurrencia en Postgres | 4 | Alguien con Docker |
| WP9 | `ui_parada3.py` completo, variantes (cobertura completa, API Nacional caída), repetir contra la nube | 4 | Tomás/Claude |
| WP10 | README de la raíz y del backend (son de la Entrega 2), guía de la Parada 3, guion de demo, video, prueba en limpio, merge a `main`, tag | 7 | Todos |
| WP12 | Parámetros de Bonita por entorno y prueba contra la nube (M14) | 3 | Tomás (Studio) |
| WP4 | Importar `entrega41_20261017_1311_cierre_v2.bos` en Studio (trae «Confirmar Finalizacion» como tarea estándar), repetir los escenarios y re-exportar el `.bos` final | 1 | Tomás |

## Decisiones abiertas
1. **Dos implementaciones de WP3 + WP6**: esta rama y el [PR #11](https://github.com/FrancoCirielli16/DSSD/pull/11). Comparadas a fondo
   el 17/10: esta rama es un superconjunto (el PR #11 no tiene `/cierres/lote`, así que Bonita no puede liberar sola; ni el estado de
   cierre validado, ni el resumen para todos los roles, ni escenarios). **Las dos agregan una migración `0006` con distinto nombre**:
   juntas dejan Alembic con dos cabezas. Propuesta: quedarse con esta rama y cerrar el PR #11 (la idea de completar la tarea con el
   usuario de la ONG ya está adoptada). Falta que el equipo lo confirme.
2. ¿Quién hace JWT? 3. ¿Quién tiene Render y de qué rama se construye? 4. ¿Quién prueba Docker y Postgres?

## CI en GitHub
`.github/workflows/ci.yml` corre en cada PR y push a `dev`/`main`: tests del backend (incluye migraciones y contratos con Bonita), tests de la
API Nacional y tipos + build del front. Un job final, **CI verde**, resume todo; ese es el chequeo que exige la regla de las ramas
(`.github/rulesets/proteger-dev-y-main.json`: nadie pushea directo a `dev`/`main` y el merge queda bloqueado si CI no está verde).
La regla la tiene que activar un administrador del repo (Franco):
`gh api -X POST repos/FrancoCirielli16/DSSD/rulesets --input .github/rulesets/proteger-dev-y-main.json`.
No corren en CI los escenarios con Bonita real ni `verificar_despliegue.py`: se corren a mano antes de mergear a `main`.

## Cómo se verifica
```
python scripts/verificar_todo.py                                              # tests backend + nacional + tipos del front (~26 s)
python backend/scripts/escenario_evaluacion.py                                # Parada 1 (Bonita real)
python backend/scripts/escenario_adjudicacion.py                              # Parada 2 por API (Bonita real, ~8 min)
python backend/scripts/escenario_cierre.py                                    # de la adjudicación al cierre (Bonita real, ~6 min)
python backend/scripts/escenario_cierre_variantes.py                          # todas las variantes del cierre (Bonita real, ~17 min; apaga y levanta Nacional y app)
python backend/scripts/recuperar_cierre.py 12                                 # destraba un cierre cuyo nodo de Bonita quedó fallido
python backend/scripts/ui_parada2.py                                          # Parada 2 por la interfaz, con capturas (~15 min)
python backend/scripts/ui_ejecucion.py --emergencia N --caso C --simular-cierre   # ejecución y cierre por la interfaz
python backend/scripts/escenario_tope.py                                      # tope de ofertas
PYTHONIOENCODING=utf-8 python nacional/scripts/verificar_despliegue.py http://localhost:8002
```
Los escenarios necesitan Bonita (`:8080`) con el proceso desplegado, la app (`:8001`) y la API Nacional (`:8002`) arriba, esta
última con el seed y nada comprometido.

## Entorno (17/10)
- Bonita: proceso con los siete conectores desplegado a las 20:30, usuarios `operador.municipal`, `coordinador.regional`,
  `ong.cruzroja`, `ong.bomberos` (pass `bpm`).
- Servidores de preview: `rescuesync-backend` (8001), `rescuesync-frontend` (5173), `rescuesync-nacional` (8002). Mueren entre turnos.

## Trampas conocidas
- Cada **Ejecutar** en Studio borra los casos. Tomcat puede tardar hasta 4 minutos: no tocar Studio y esperar.
- Si "Run" dice que falló el login de `walter.bates`, la causa real suele estar en `workspace\tomcat\server\logs\bonita.log` (Connection refused).
- Nube: la base de Render persiste. Una referencia ya `LIBERADA` o `CERRADA` da 409. No reiniciar la base local al probar contra la nube
  (los ids de emergencia se reusarían y chocarían con las referencias viejas).
- Nunca apuntar `POSTGRES_TEST_DATABASE_URL` a la base de la demo: las pruebas de concurrencia hacen `drop_all`.
- Si la API Nacional o la app no responden cuando se valida el cierre, Bonita deja «Liberar Recursos y Notificar Cierre» como nodo
  fallido y la API REST no permite reintentarlo: se destraba con `recuperar_cierre.py` (ver `CAMBIOS-BONITA.md`). En la demo en la
  nube, despertar la API Nacional de Render antes de validar el cierre.
- Windows: correr los scripts con `PYTHONIOENCODING=utf-8` si fallan por un carácter.
- El `.bos` es binario: edita una sola persona a la vez.

## Ayudas de Claude en este proyecto
- `.claude/agents/lector-de-logs` (lee logs largos y devuelve la causa) y `.claude/agents/verificador` (corre los chequeos y devuelve el resultado).
  `.claude/` está gitignoreado: no se comparte con el equipo.
