---
name: nuevo-endpoint
description: Checklist de "hecho" para agregar o cambiar un endpoint de la API Nacional (nacional/) o de la app (backend/). Usar al crear una ruta, cambiar un schema o tocar validaciones: cubre código, validación de entrada, Swagger (ejemplos y errores), tests, documentación y deploy.
---

# Un endpoint está hecho cuando…

Cada punto tiene un test o un chequeo de CI que falla si se omite.

## API Nacional (`nacional/app/`)
1. **Schema** en `schemas.py`: tipos `Cuit`, `Cantidad`, `IdExterno`, `Referencia` (no `int`/`str` sueltos); enteros ≤ `MAX_ENTERO` (32 bits, Postgres);
   dígitos con `[0-9]`, nunca `\d`. `Field(description=…)` en los campos que no se entienden solos y `model_config = ejemplos({...})`
   con un ejemplo realista en **cada** modelo de entrada y de salida (el test `test_los_ejemplos_de_swagger_son_validos_para_su_modelo` los valida).
2. **Router**: `summary`, docstring que explique la regla, y `responses=errores({404: …, 409: …})` con cada código que el código puede devolver.
   Permisos: `get_current_account` (cualquier cuenta), `require_servicio` (Bonita/app) o `require_ong_account` (la propia ONG); el router suma `errores(AUTH)` o `errores(SERVICIO)`.
   El tag tiene que existir en `openapi_tags` de `main.py` (minúsculas).
3. **Entrada hostil**: un dato mal formado da **422**, nunca 500 (agregar el caso a `tests/test_validaciones_de_entrada.py`). Cuidado con lo que SQLite acepta y Postgres no.
4. **Tests**: camino feliz, 401 sin token, 403 con el rol equivocado, cada 4xx documentado, idempotencia si repetir el pedido es posible.
5. **Documentación**: fila en la tabla de endpoints de `nacional/README.md` (un test la compara con la API) y `python nacional/scripts/exportar_openapi.py`
   (un test falla si `entrega-3/swagger-api-nacional.json` está desactualizado). Si cambia un servicio de la consigna, `entrega-3/ENTREGA.md`.
6. **Modelo/migración**: si cambia una tabla, `alembic revision --autogenerate` + `upgrade head` (hay un test que detecta modelos sin migración).

## App web (`backend/app/`)
1. Ruta en `routers/api.py` con `require_role(...)`; lógica en `services/`; la SPA llama desde `frontend/src/api.ts`.
2. Tests en `backend/tests/` (cada rol que no debe pasar → 403). Si toca Bonita, mockear con `responses` y, si cambia el contrato, `test_bonita_contract.py`.
3. Tipos del front: `cd frontend && npx tsc --noEmit`.

## Antes del PR
`python scripts/verificar_todo.py`. CI corre además Postgres, el fuzz de Schemathesis (ningún pedido puede dar 5xx), gitleaks y "CI verde".
Al mergear a `dev` el workflow redespliega Render y verifica que `/health` sirva ese commit y que `verificar_despliegue.py` dé verde.
