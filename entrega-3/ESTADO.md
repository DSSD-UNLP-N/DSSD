# Estado vivo de la Entrega 3

Última actualización: **19/10/2026**. Entrega: **semana del 22/10** (ficha para entregar: [`ENTREGA.md`](ENTREGA.md)).
Código: `dev` y `main` están iguales y con CI verde; el tag **`entrega-3`** apunta al último commit de `main`.

**En una línea:** el sistema completo funciona de la emergencia al cierre con Bonita real, JWT entre los tres sistemas, y la API Nacional
corre en la nube (Render, Docker, Postgres). Probado contra local y contra la nube.

## Cómo está armado

| Sistema | Carpeta | Dónde corre | Autenticación |
|---|---|---|---|
| App web (API FastAPI + SPA React) | `backend/`, `frontend/` | Local: `:8001` y `:5173` | Personas: usuario y contraseña propios, cookie de sesión |
| Bonita (proceso `Gestion Integral de la Emergencia`) | `entrega-3/entrega42_local.bos`, `entrega-2/ACME.xml` | Local: Studio `:8080` | Usuarios de Bonita (`bpm`) |
| API Nacional (FastAPI) | `nacional/` | **Render**: https://rescuesync-nacional.onrender.com · local `:8002` | **JWT**: cuentas de servicio `app-service` y `bonita-service`, y las ONGs |

- La app llama a la API Nacional con un token que guarda y renueva sola ante un 401. Bonita entra de nuevo en cada tarea de servicio (conector `loginNacional`,
  respuesta en la variable `nacionalLoginJson`, cabecera `Authorization: Bearer`).
- Con Postgres, la API Nacional **no arranca** si `JWT_SECRET`, `BONITA_SERVICE_PASSWORD` o `APP_SERVICE_PASSWORD` valen lo de ejemplo.
- La app **nunca** completa «Cargar Ofertas de Ayuda» en Bonita (ancla del timer). Las ofertas viven en la base de la app.

## Qué hay hecho

**Proceso y app (WP0–WP6)** — contratos, consolidado de ofertas, reserva todo o nada en la API Nacional, decisión del Coordinador (parcial/reformular), adjudicación del Municipio,
ronda 2, ejecución (monitorear, finalizar por ONG, validar cierre), cierre por referencia (`/cierres` y `/cierres/lote`), eventos de Bonita a la app, avisos en la campana.

**Bonita** — siete conectores REST (obtener ofertas, evaluar, avisar evaluación, resolver reservas, avisar adjudicación, cerrar y avisar cierre) más tres `loginNacional`.
«Confirmar Finalizacion de Actividades» es tarea estándar. Las ediciones del `.bos` se hacen con scripts (`bonita/scripts/`): `agregar_conector_cierre.py`,
`agregar_login_nacional.py` y `preparar_entorno.py` (tarea estándar; apuntar los conectores a otra API Nacional con otra clave). Bitácora: [`CAMBIOS-BONITA.md`](CAMBIOS-BONITA.md).

**JWT (WP11)** — `POST /login`, onboarding de ONGs (`POST /ongs`), protección por rol, cuentas de servicio sembradas desde variables de entorno.

**Nube (WP7, 18/10)** — servicio `rescuesync-nacional` en Render, Docker construido desde la rama `dev` con auto-deploy, base Postgres de Render. El servicio anterior
(imagen de Docker Hub de Fabrizio, código viejo) quedó suspendido. Guía: [`guia-wp7-render.md`](guia-wp7-render.md).

**CI** — `.github/workflows/ci.yml`: tests de la app y de la API Nacional, tipos y build del front, y dos jobs con Postgres 16 (migraciones de ida y vuelta, fail-fast con secretos
de ejemplo, arranque, `verificar_despliegue.py`, concurrencia de adjudicaciones). El job **CI verde** es el chequeo exigido por el ruleset de GitHub (activo): dev y main solo por PR.

**Herramientas de prueba** — `backend/scripts/`: escenarios por API con Bonita real, pruebas por interfaz con capturas, `correr_escenarios.py` (todos en orden, con limpieza y tiempos),
`recuperar_cierre.py`, `escenario_jwt.py`. `ESCENARIO_VENTANA_S` acorta la ventana de ofertas (60 s por defecto).

## Cómo se probó (con Bonita real y bases nuevas)

| Prueba | Resultado |
|---|---|
| Evaluación (Parada 1) | 26/26 |
| Tope de ofertas | 39/39 |
| Adjudicación (Parada 2, API) | 34/34 |
| Cierre | 28/28 |
| Variantes del cierre (subconjunto de ONGs, cobertura completa, reformulación `r2`, permisos, repeticiones, finalización simultánea, API Nacional caída, app caída, eventos a mano) | 175/175 |
| JWT (clave de Bonita rotada → nodo fallido y recuperación; secreto distinto y token vencido → la app vuelve a entrar sola) | 39/39 |
| UI: recorrido completo `ui_parada3.py` (dos ONGs, con capturas) | 47/47 local · **47/47 contra la API de Render** |
| UI: `e2e_ui.py` · `ui_parada2.py` · `ui_ejecucion.py` | 59/59 · 46/46 · 25/25 |
| Unitarias | app 222 · API Nacional 126 · tipos del front sin errores |
| `verificar_despliegue.py` (72 chequeos) | 72/72 local, en CI con Postgres y contra Render |
| Prueba en limpio (clon del tag, instalación desde el README) | API 126 tests + 72/72, app 222 tests y arranque, front build |

Una falla puntual vista y no reproducida: `escenario_cierre.py` 3/4 en una corrida (Bonita no entregó la evaluación a tiempo); repetido solo dio 28/28.

## Qué falta
- **Antes de entregar:** despertar el servicio de Render (`curl .../health`, tarda 30-60 s dormido), enviar la ficha ([`ENTREGA.md`](ENTREGA.md)) y no mergear nada a `dev`/`main` (cada commit a `dev` redespliega).
- **La Postgres gratis de Render vence el 15/11/2026**, antes del coloquio (26/11): recrearla (la API aplica migraciones y seed sola) o pasarla a plan pago, y actualizar `DATABASE_URL`.
- **PR #11 de Franco** (WP3+WP6): duplica lo ya integrado y agrega una migración que dejaría Alembic con dos cabezas. Cerrarlo.
- Revocar la API key de Render que se compartió por chat y el deploy hook del servicio viejo.
- Opcionales: Docker Compose completo y Dockerfiles de app y front (la consigna solo pide dockerizar la API Nacional), video y guion de demo, indicadores (dashboard, no es de esta entrega).
- No probado: Docker en la PC local (el motor no arranca; el `Dockerfile` sí lo construyen Render y CI).

## Cómo se verifica
```
python scripts/verificar_todo.py                                       # unitarias app + API Nacional + tipos del front (~30 s)
cd backend && python scripts/correr_escenarios.py                      # los seis escenarios con Bonita real (~25 min); --solo cierre,jwt para algunos
cd backend && python scripts/ui_parada3.py                             # recorrido completo por la interfaz (~7 min; local o nube)
PYTHONIOENCODING=utf-8 python nacional/scripts/verificar_despliegue.py <URL> --clave <BONITA_SERVICE_PASSWORD>
python backend/scripts/recuperar_cierre.py <emergencia>                # destraba un cierre cuyo nodo de Bonita quedó fallido
```
Necesitan Bonita (`:8080`) con el proceso desplegado, la app (`:8001`), el front (`:5173`, solo las de interfaz) y la API Nacional (`:8002` o la nube) con el seed y nada comprometido.

## Cómo pasar entre local y nube
1. **Local:** importar `entrega42_local.bos` en Studio y desplegar; `backend/.env` con `NACIONAL_BASE_URL=http://localhost:8002` y la clave por defecto.
2. **Nube:** `NACIONAL_BONITA_PASSWORD=<clave> python bonita/scripts/preparar_entorno.py entrega-3/entrega42_local.bos entrega-3/entrega42_nube.bos --nacional https://rescuesync-nacional.onrender.com`,
   importar `entrega42_nube.bos` (no se sube al repo, lleva la clave) y en `backend/.env` poner la URL, `NACIONAL_SERVICE_PASSWORD` y `NACIONAL_TIMEOUT_SECONDS=90`.
No hay forma de tener los dos `.bos` activos a la vez: Bonita identifica el proceso por nombre y versión.

## Trampas conocidas
- Cada **Ejecutar** en Studio borra los casos. Tomcat puede tardar hasta 4 minutos: no tocar Studio y esperar. Si el login de `walter.bates` falla, mirar `workspace\tomcat\server\logs\bonita.log`.
- Nube: la base persiste y cada cierre descuenta stock real, sin botón de reset. Una referencia `LIBERADA` o `CERRADA` da 409. No reiniciar la base local al probar contra la nube (los ids de emergencia se reusarían).
- Nunca apuntar `POSTGRES_TEST_DATABASE_URL` a la base de la demo: la prueba de concurrencia hace `drop_all`.
- Si la API Nacional o la app no responden al validar el cierre, Bonita deja «Liberar Recursos y Notificar Cierre» como nodo fallido y su API REST no permite reintentarlo: se destraba con `recuperar_cierre.py`.
- Windows: correr los scripts con `PYTHONIOENCODING=utf-8` si fallan por un carácter. Los servidores de preview mueren entre turnos (el front se cae).
- El `.bos` es binario: edita una sola persona a la vez. Los `*_nube.bos` están en `.gitignore`.

## Otros documentos
[`ENTREGA.md`](ENTREGA.md) (ficha de entrega) · [`guia-parada-3.md`](guia-parada-3.md) (recorrido con capturas) · [`guia-del-sistema.md`](guia-del-sistema.md) (cómo funciona todo, explicado desde cero) ·
[`guia-wp7-render.md`](guia-wp7-render.md) · [`contratos.md`](contratos.md) · [`CAMBIOS-BONITA.md`](CAMBIOS-BONITA.md) · [`plan-cierre-entrega.md`](plan-cierre-entrega.md) (plan y tareas, histórico).
