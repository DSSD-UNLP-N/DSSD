# Instalación — modo NUBE (por defecto)

Es la configuración de la entrega: la **API Nacional corre en Render** y no hay que instalarla. En la PC corren solo Bonita Studio, la app web y el front.

```
Bonita Studio (:8080) ──HTTPS──▶ API Nacional en Render
      │  ▲
      │  └── la app llama a Bonita (REST)           App web (:8001) ──HTTPS──▶ API Nacional en Render
      └────── Bonita llama a la app (conector) ─────▶ App web (:8001)
```

Requisitos: Bonita Studio Community 10.4.0, Python 3.12+, Node 20+, Chrome (solo para las pruebas por interfaz).

## Qué `.bos` importar y por qué

**`entrega-3/entrega42_nube.bos`.** Es el proceso vigente con los conectores apuntando a Render y con la clave de la cuenta `bonita-service` (la de la demo) ya cargada en el `loginNacional`. Es idéntico a `entrega42_local.bos` salvo esas URLs y esa clave (lo verifica un test).

URLs de cada conector en este `.bos`:

| Tarea de servicio | Llama a la API Nacional (Render) | Llama a la app (siempre local) |
|---|---|---|
| Obtener Ofertas de la Red | — | `GET http://localhost:8001/api/bonita/emergencias/${emergenciaId}/ofertas` |
| Validar en Sistema Nacional y Calcular Cobertura | `POST https://rescuesync-nacional.onrender.com/login` y `/evaluaciones` | `POST http://localhost:8001/api/bonita/emergencias/${emergenciaId}/eventos` |
| Notificar Adjudicacion y Registrar Compromiso Nacional | `POST https://rescuesync-nacional.onrender.com/login` y `/adjudicaciones/resolucion` | `POST http://localhost:8001/api/bonita/emergencias/${emergenciaId}/eventos` |
| Liberar Recursos y Notificar Cierre | `POST https://rescuesync-nacional.onrender.com/login` y `/cierres/lote` | `POST http://localhost:8001/api/bonita/emergencias/${emergenciaId}/eventos` |

Bonita y la app **siempre están en la PC**, por eso la URL de la app es `localhost:8001` en los dos `.bos`. Lo único que cambia entre nube y local es la dirección de la API Nacional.

Para comprobar qué URLs trae un archivo: `python bonita/scripts/ver_conectores.py entrega-3/entrega42_nube.bos`.

## Pasos

### 1. Despertar la API Nacional
El plan gratis de Render duerme el servicio tras 15 min sin uso y la primera llamada tarda 30-60 s. Antes de empezar, abrir (o `curl`) hasta que responda:

```
https://rescuesync-nacional.onrender.com/health
```
Swagger: https://rescuesync-nacional.onrender.com/docs

### 2. Bonita Studio
1. **Archivo → Importar** → `entrega-3/entrega42_nube.bos`. (Solo puede haber uno de los dos `.bos` activo: mismo nombre y versión de proceso. Si estaba el local, esto lo reemplaza.)
2. Editor de la **Organización** → importar `entrega-2/ACME.xml` → **Desplegar** (botón del editor; sin esto falla con "Actor … does not contain any members").
3. Sobre el proceso `Gestion Integral de la Emergencia`: **Ejecutar**. Cada Ejecutar reinicia el motor y borra los casos.
4. Comprobar `http://localhost:8080/bonita` (técnico `walter.bates` / `bpm`; de prueba `operador.municipal`, `coordinador.regional`, `ong.cruzroja`, `ong.bomberos`, todos `bpm`).

Si algo falla al desplegar, el motivo real está en `<Studio>\workspace\tomcat\server\logs\bonita.log`.

### 3. App web (`:8001`)
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate         # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
copy .env.nube .env                                    # Linux/Mac: cp .env.nube .env
python -m alembic upgrade head && python -m app.seed   # SQLite (dev.db)
uvicorn app.main:app --port 8001
```
`.env.nube` ya trae la URL de Render, la clave de la cuenta `app-service`, `NACIONAL_TIMEOUT_SECONDS=90` (por el despertar del plan gratis) y SQLite. No hay que editar ni generar nada. Si se cambia el `.env` con la app corriendo, reiniciarla.

### 4. Front (`:5173`)
```bash
cd frontend && npm install && npm run dev              # Vite reenvía /api al backend
```

### 5. Probar
Entrar a http://localhost:5173 como `operador.municipal` (clave `demo1234`) y registrar una emergencia. Recorrido completo automático, con capturas (≈ 7 min):
`cd backend && python scripts/ui_parada3.py`.

Alta de ONGs de prueba: `http://localhost:5173/alta-ong` (no está en el menú). Crea la ONG en Bonita (grupo `/rescuesync/ong`), en la API Nacional con sus rubros y en la app; después se ingresa con ese usuario. La ONG queda creada en Render y no se puede borrar. Para comprobar el alta de punta a punta (app, Bonita y Render; con `--ofertar` suma una emergencia y la oferta de la ONG nueva): `cd backend && python scripts/e2e_alta_ong.py`.

## Notas de la nube
- **La numeración de las emergencias no choca entre bases.** Render recuerda cada emergencia por su número (referencia `emg-<n>-r1-<cuit>`) y no la vuelve a evaluar, así que una base de la app nueva no arranca en 1 sino en los minutos desde 1970 (un número de 8 cifras) y sigue de a uno. Se puede borrar `backend/dev.db` sin riesgo de pisar los ensayos de otros. Para ver qué números usó Render: `GET /ongs/{cuit}/cierres` en Swagger.
- **El stock no se gasta.** Durante la ventana y la adjudicación Render reserva lo ofrecido y al cerrar lo libera (comprometido vuelve a 0); el total de cada ONG no cambia. No hay nada que reponer. Se puede ver con `GET /recursos/disponibilidad` en Swagger.
- Verificar el despliegue de la API (recorre los 19 endpoints y no deja datos; con `--crear-ong` suma el alta de una ONG, que sí queda): `python nacional/scripts/verificar_despliegue.py https://rescuesync-nacional.onrender.com --clave <BONITA_SERVICE_PASSWORD>`.
- Render construye `nacional/Dockerfile` desde la rama `dev` y redespliega en cada commit; `JWT_SECRET` y las dos contraseñas de servicio son variables de entorno del servicio (`render.yaml` es el blueprint de referencia).
- Si la nube falla (Render caído, sin internet): [instalacion-local.md](instalacion-local.md).
