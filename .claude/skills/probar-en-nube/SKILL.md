---
name: probar-en-nube
description: Corrida completa de pruebas del sistema contra Bonita real y la API Nacional en Render (o local), en el orden que no se pisa. Usar antes de entregar, después de cambios que toquen Bonita/Nacional/app, o cuando pidan "probar todo" / "la prueba final".
---

# Prueba completa (≈ 30 min, ≈ 25 casos de Bonita en modo nube)

Una prueba por vez. Si algo falla, parar y diagnosticar (el subagente `lector-de-logs` lee los logs largos); no encadenar corridas.

## 0. Modo y preflight
- **Nube**: `backend/.env` = `.env.nube` (Render, `NACIONAL_TIMEOUT_SECONDS=90`) y en Studio el proyecto con `entrega-3/entrega42_nube.bos` (proceso desplegado + organización).
  **Local**: `.env.local`, `entrega42_local.bos`, API Nacional en `:8002` (`cd nacional && python -m uvicorn app.main:app --port 8002`).
- Levantar la app (`cd backend && python -m uvicorn app.main:app --port 8001`) y el front (`cd frontend && npm run dev`).
- `python backend/scripts/preflight.py` — tiene que dar 0 fallas. Si Bonita es un proyecto nuevo, los ids de caso arrancan en 1: la app ya los resuelve.

## 1. Sin Bonita
```
python scripts/verificar_todo.py
PYTHONIOENCODING=utf-8 python nacional/scripts/verificar_despliegue.py https://rescuesync-nacional.onrender.com --clave <BONITA_SERVICE_PASSWORD>   # 90/90
```
La clave de Render está en las variables del servicio (`BONITA_SERVICE_PASSWORD`). Swagger: `/docs` → Authorize → probar los ejemplos de `/login` y `/validaciones`
(no `/evaluaciones`: reserva stock).

## 2. Con Bonita real (desde `backend/`, con `PYTHONIOENCODING=utf-8`)
```
python scripts/correr_escenarios.py --solo evaluacion,tope,adjudicacion,cierre --sin-unitarios   # 26+39+34+28, ~10 min, ~16 casos
python scripts/correr_ui.py --completo                                                           # e2e_ui 59, parada3 50, parada2 25 y 46, ~6 min
python scripts/e2e_alta_ong.py --ofertar                                                         # 16, deja una emergencia abierta
```
`variantes` y `jwt` apagan Nacional y rotan claves: **solo en local** (175 y 39). Costo en casos: evaluación 2, adjudicación 2, cierre 1, tope 3,
e2e_ui 1, parada2 1 (2 con `--con-parcial`), parada3 1, variantes ~8, jwt ~5. El límite es 150 por proyecto y 30 días.

## 3. Cierre
- Borrar los casos que dejó abiertos (`correr_escenarios.borrar_casos_abiertos()`) y confirmar en `preflight.py` que Nacional no tiene nada comprometido.
- Nube: la base de Render persiste; las ONGs de prueba (`e2e_alta_ong`) quedan creadas. No hay reset.
- Reportar con los conteos de cada prueba y el commit que sirve Render (`/health`).

## Si falla
Mirar primero `preflight.py` (modo, proyecto de Bonita, casos abiertos). Luego el log del escenario y el de la app. Casos típicos: ventana
cerrada antes de tiempo (subir `ESCENARIO_VENTANA_S`), Bonita sin el proceso desplegado, convocatorias viejas que descuentan inventario, referencia ya cerrada en Render (409).
