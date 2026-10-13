# Plan de pruebas: app completa contra la API Nacional en la nube (E3)

API: `https://sistema-nacional-latest.onrender.com` (código de `modelado-tomas-e-3`).
Objetivo: probar de punta a punta, con Bonita real, que la app local usa la API de la nube para el catálogo y la
validación de ofertas de las ONGs, y dejar evidencia para la entrega.

## Precondiciones (verificadas 12/10)

- La nube tiene exactamente los datos del seed: Cruz Roja (4 paramédicos, `SALUD_PREHOSP` hasta MEDIO vigente,
  3000 L de agua, 5000 raciones) y Bomberos (6 paramédicos con `SALUD_PREHOSP` **vencida**, 12 rescatistas
  acuáticos CRITICO, 20 brigadistas ALTO, 4 autobombas). Nada comprometido. Las pruebas cuentan con estos números:
  si alguien del equipo los cambia, hay que volver a mirarlos antes.
- **Arranque en frío: 42 s** la primera llamada después de un rato. El backend tiene timeout de 5 s → daría 503.
  Para estas pruebas: `NACIONAL_TIMEOUT_SECONDS=60` y despertar el servicio antes (`GET /health`).
- La app local corre sobre una **copia** de `dev.db` (`e3-nube.db`), así `dev.db` no se toca.
- **La nube no se modifica**: todo lo que se usa es lectura o `POST /validaciones` (que no guarda nada). Lo único
  que escribe en la nube es `PUT /inventario`, y solo se prueba con casos que fallan antes de escribir (404/422).

Configuración del backend para las pruebas (variables de entorno, sin tocar código):

```
DATABASE_URL=sqlite:///E:/DSSD/backend/e3-nube.db
NACIONAL_BASE_URL=https://sistema-nacional-latest.onrender.com
NACIONAL_TIMEOUT_SECONDS=60
```

## Bloque A — La API sola, por HTTP (sin app local ni Bonita)

Script reutilizable: `nacional/scripts/verificar_despliegue.py <url>` (sirve para chequear cada deploy).

| # | Prueba | Esperado |
|---|---|---|
| A1 | `/health`, `/docs`, `/openapi.json` | 200; los 7 endpoints de catálogo, inventario y validación |
| A2 | `GET /tipos-recurso` | 11 tipos; `PARAMEDICO` pide `SALUD_PREHOSP`; insumos sin certificación |
| A3 | `GET /certificaciones` | 4, cada una con los tipos que habilita |
| A4 | `GET /ongs` y `?estado=HABILITADA` | 3 y 2 (la suspendida queda afuera); estado inválido → 422 |
| A5 | `GET /ongs/{cuit}` | Cruz Roja: cert vigente hasta MEDIO; Bomberos: `SALUD_PREHOSP` vencida → paramédicos sin riesgo permitido; CUIT inexistente → 404 |
| A6 | `GET /recursos/disponibilidad?tipo_recurso=PARAMEDICO` | 10 (4 + 6), desglose por ONG; tipo inexistente → 404 |
| A7 | `PUT /inventario` que falla antes de escribir | ONG inexistente → 404; tipo inexistente → 404; cantidad negativa → 422 |

**Validación de ofertas (`POST /validaciones`, el corazón):**

| # | Caso | Esperado |
|---|---|---|
| V1 | Cruz Roja, 10 paramédicos | `alcanza=false`, disponible 4 |
| V2 | Cruz Roja, 4 paramédicos | `alcanza=true` |
| V3 | Cruz Roja, 2 + 3 paramédicos (dos ítems) | se suman: solicitado 5, `alcanza=false` |
| V4 | Cruz Roja paramédicos, gravedad MEDIO | PLENA → PRINCIPAL |
| V5 | Cruz Roja paramédicos, gravedad ALTO | PARCIAL → APOYO, riesgo permitido MEDIO (no se rechaza) |
| V6 | Bomberos rescatistas acuáticos, CRITICO | PLENA → PRINCIPAL |
| V7 | Bomberos brigadistas, CRITICO | PARCIAL (cert hasta ALTO) |
| V8 | Bomberos paramédicos | SUPERVISADA (cert vencida), pero `alcanza=true` |
| V9 | Raciones, CRITICO | PLENA (insumo sin certificación) |
| V10 | ONG suspendida | SUPERVISADA, disponible 0 |
| V11 | CUIT desconocido | `ong=null`, SUPERVISADA, sin error |
| V12 | Varias ONGs en un pedido | un resultado por (ONG, recurso); `alcanza_todo` correcto |
| V13 | Tipo inexistente / cantidad 0 / gravedad inválida | 422 |
| V14 | Validar no guarda nada | la ficha de la ONG queda igual antes y después |

## Bloque B — Recorrido completo con Bonita, apuntando a la nube

`backend/scripts/e2e_ui.py` (navegador real, 59 verificaciones) con el backend configurado contra la nube:
alta en Bonita, lotes eligiendo el tipo del catálogo **de la nube**, publicación, ofertas de Cruz Roja (rechazo por
9000 L de agua cuando tiene 3000), versiones, retiro de Bomberos, Coordinador y Auditor. Opcional: `--timer 90`
para ver al timer de Bonita cerrar la ventana.

## Bloque C — Validación de ofertas de las ONGs, escenario completo

Script nuevo `backend/scripts/escenario_tope.py`: por la API de la app local (la misma que usa la SPA), con Bonita
real y la API de la nube. Crea dos emergencias, carga un lote de paramédicos en cada una, publica y recorre:

| # | Paso | Esperado |
|---|---|---|
| C1 | Cruz Roja ofrece 2 en la emergencia 1 | 201, versión 1 |
| C2 | Ofrece 3 en la emergencia 2 | 400: "sumás 5 personas y tenés 4 disponibles" |
| C3 | Edita la emergencia 1 a 3 | 201, versión 2 (reemplaza, no suma) |
| C4 | Ofrece 2 en la emergencia 2 | 400 (3 + 2 > 4) |
| C5 | Ofrece 1 en la emergencia 2 | 201 (3 + 1 = 4) |
| C6 | Retira su oferta de la emergencia 1 | 201, `retirada=true`; el historial sigue |
| C7 | Sube la emergencia 2 a 4 | 201 (el retiro liberó el cupo) |
| C8 | Bomberos ofrece 6 paramédicos en la emergencia 1 | 201 (inventario propio, independiente de Cruz Roja) |
| C9 | Bomberos ofrece 7 | 400 |
| C10 | Retirar sin oferta / dos veces | 400 |
| C11 | El Coordinador lista las ofertas | ve la de Cruz Roja como retirada y la de Bomberos vigente |
| C12 | Limpieza | retira todas las ofertas del escenario |

## Bloque D — Fallas

| # | Caso | Esperado |
|---|---|---|
| D1 | Backend con `NACIONAL_BASE_URL` a una URL que no existe | cargar lote y ofertar → 503 "El Sistema Nacional no responde"; no se guarda nada |
| D2 | Mismo caso, retirar una oferta | funciona (retirar nunca consulta a la API) |
| D3 | Servicio dormido con timeout de 5 s | 503 en la primera llamada → justifica subir el timeout por defecto |

## Bloque E — Regresión automática

`pytest` en `nacional/` (55) y en `backend/` (153, 2 omitidos que necesitan Bonita).

## Qué no se prueba y por qué

- **JWT y alta de ONGs**: no existen todavía (servicio 1).
- **Bloqueo/compromiso**: no existe (servicio 4); nada sube `cantidad_comprometida`.
- **`/cierres`**: está en la rama de Franco y no se desplegó. Cuando se despliegue, se suma al bloque A.
- **Base de la nube**: si es Postgres o SQLite se ve en el panel de Render, no por la API.

## Criterio de éxito

Bloques A, B, C y E en verde; D se comporta como dice la tabla. Lo que falle se anota acá con su causa antes de
corregir nada.

## Resultados (12/10, Bonita real + API en la nube)

| Bloque | Cómo | Resultado |
|---|---|---|
| A | `nacional/scripts/verificar_despliegue.py https://sistema-nacional-latest.onrender.com` | **38/38** |
| B | `backend/scripts/e2e_ui.py` con el backend apuntando a la nube | **59/59** |
| C | `backend/scripts/escenario_tope.py` (dos corridas seguidas) | **39/39** y **39/39** |
| D1 | API inaccesible: cargar lote y aumentar oferta | 503, nada guardado (0 lotes nuevos, misma versión) |
| D2 | API inaccesible: retirar | 201, retirada |
| D3 | API que tarda 8 s, timeout de 5 s | 503 → con la nube dormida (42-51 s en frío) hay que subir el timeout o despertarla antes |
| E | `pytest` | nacional **55**; backend **156** (2 omitidos que necesitan Bonita), incluidos 3 tests nuevos del alta |

**Hallazgo y corrección.** En la primera corrida de C, el alta de una emergencia justo después de publicar otra dio
502: Bonita creó el caso pero la tarea "Registrar Emergencia" tardó más de 5 s en aparecer. La base local quedó bien
(rollback), pero en Bonita quedó un **caso huérfano** (10003) trabado en esa tarea y con `emergenciaId` 7, que SQLite
reusó para la emergencia siguiente (caso 10004): dos casos apuntando a la misma emergencia. Corregido en
`services/emergencias.py`: la espera de la tarea pasa a 20 s y, si el alta falla después de crear el caso, el usuario
técnico lo borra (`DELETE /API/bpm/case/{id}`, probado contra Bonita real). El huérfano 10003 se borró a mano.
