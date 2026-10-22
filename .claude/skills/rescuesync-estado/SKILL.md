---
name: rescuesync-estado
description: Orientación rápida sobre el repo DSSD/RescueSync (Bonita + app web + API Nacional en la nube). Usar al arrancar una sesión, o cuando pregunten "en qué estamos", "qué falta", "cómo se prueba", "dónde está X", antes de tocar código o de guiar en Bonita Studio. Complementa a rescuesync-bpmn (el proceso en sí), probar-en-nube, nuevo-endpoint y editar-bos.
---

# RescueSync: el repo y su estado

Tres sistemas que se hablan: **app web** (FastAPI en `backend/` `:8001` + SPA React en `frontend/` `:5173`), **Bonita** (Studio en `:8080`,
proceso `Gestion Integral de la Emergencia`) y **API Nacional** (`nacional/`, FastAPI, JWT, Postgres; en Render
https://rescuesync-nacional.onrender.com o local `:8002`). Entrega 3 (API en la nube) hecha; quedan la 4 (Gantt con desvíos) y la 5
(informe final, coloquio 26/11). Pendiente de producto: dashboard de indicadores (punto 4 de la consigna) y el perfil Auditor.

## Dónde está cada cosa

| Ruta | Qué es |
|---|---|
| `backend/` | App: `app/routers/api.py`, `app/services/` (alta, ofertas, ejecución, cierre), `app/integrations/bonita.py`, `scripts/` (escenarios con Bonita real, `preflight.py`) |
| `frontend/` | SPA React (Vite + TS). La UI nueva va acá, no en templates |
| `nacional/` | API Nacional: `app/routers/`, `schemas.py` (ejemplos y reglas de entrada), `services/`, `scripts/` (`verificar_despliegue.py`, `exportar_openapi.py`) |
| `entrega-3/` | `ENTREGA.md` (ficha), `swagger-api-nacional.json` (se regenera), `entrega42_local.bos` / `entrega42_nube.bos` (los únicos `.bos` versionados) |
| `bonita/scripts/` | Edición del `.bos` por script, `preparar_entorno.py`, `ver_conectores.py` |
| `docs/` | `instalacion-local.md`, `instalacion-nube.md` |
| `.github/workflows/` | `ci.yml` (tests, Postgres, fuzz Schemathesis, gitleaks, "CI verde"), `deploy-nacional.yml` (redeploy a Render desde `dev` y verificación) |

Documentos de trabajo (`ESTADO.md`, guías) viven solo en local (`.gitignore`); lo que importa para otros va en `docs/` o en este skill.

## Cómo verificar (en este orden)

```
python backend/scripts/preflight.py          # ¿está todo en pie y en el modo que creés? (modo, Nacional, app, Bonita, base)
python scripts/verificar_todo.py             # unitarias app + Nacional + tipos del front (~30 s)
```
Después, según qué se toque: skill **probar-en-nube** (escenarios con Bonita real, UI, despliegue). Un endpoint nuevo: **nuevo-endpoint**.
Cambios en el proceso Bonita: **editar-bos**. Estado del `.bos`: `python .claude/skills/rescuesync-estado/scripts/inspect_bos.py [archivo]`.

## Trampas que ya costaron horas
- **Bonita Community corta a los 150 casos en 30 días por proyecto** (cuenta aunque se borren). Si pasa: importar el `.bos` como proyecto nuevo y desplegar la organización.
- **Una prueba por vez**: dos corridas sobre el mismo Bonita/app/Render se pisan (timers que reservan stock, convocatorias que descuentan inventario).
- **Solo un `.bos` activo** (mismo nombre y versión): local o nube, no los dos. El `.env` de `backend/` tiene que coincidir (`.env.nube` / `.env.local`).
- Postgres rechaza lo que SQLite deja pasar (NUL, enteros > 32 bits, `NaN`): los datos mal formados tienen que dar 422, nunca 500.
- Render (plan gratis) duerme a los 15 min: la primera llamada tarda 30-60 s. `/health` devuelve el `commit` que está sirviendo.
- La app nunca completa «Cargar Ofertas de Ayuda» en Bonita (es el ancla del timer).
- Bonita Studio no queda corriendo entre sesiones: `GET http://localhost:8080/bonita` (200 = arriba); si no, pedirle al usuario que lo abra y despliegue.

## Diagnóstico de Studio/Bonita
`C:\BonitaStudioCommunity-2025.2-u0\workspace\tomcat\server\logs\bonita.log` (motor, buscar `ERROR`/`Caused by`) y `workspace\.metadata\.log`
(Studio). El diálogo solo dice "Error when trying to deploy". Caso visto: descripción del Pool > 255 caracteres rompe el deploy.

## Cómo trabajar con el usuario
- Bonita Studio en español, un paso por mensaje, pedir captura; no inventar rutas de menú.
- Probar en runtime real antes de seguir; cada pieza nueva entra con sus tests. Commits chicos, a nombre del usuario; no pushear sin pedido.
- Respuestas cortas en castellano.
