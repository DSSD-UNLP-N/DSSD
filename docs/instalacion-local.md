# Instalación — modo LOCAL (plan B si falla la nube)

Todo corre en la PC, incluida la **API Nacional**. Se usa si Render está caído, sin internet o si se quiere probar sin gastar el stock de la nube. Lo normal es el modo nube: [instalacion-nube.md](instalacion-nube.md).

```
Bonita Studio (:8080) ──▶ API Nacional local (:8002)      App web (:8001) ──▶ API Nacional local (:8002)
      └────── Bonita llama a la app (conector) ─────▶ App web (:8001)
```

Requisitos: Bonita Studio Community 10.4.0, Python 3.12+, Node 20+, Chrome (solo para las pruebas por interfaz).

## Qué `.bos` importar y por qué

**`entrega-3/entrega42_local.bos`.** Es el proceso vigente con los conectores apuntando a `localhost:8002` y la clave de ejemplo de `bonita-service` (`change-me`) en el `loginNacional`, que coincide con los valores por defecto de la API Nacional local. Es el mismo proceso que `entrega42_nube.bos`; solo cambian esas URLs y esa clave.

URLs de cada conector en este `.bos`:

| Tarea de servicio | Llama a la API Nacional (local) | Llama a la app (siempre local) |
|---|---|---|
| Obtener Ofertas de la Red | — | `GET http://localhost:8001/api/bonita/emergencias/${emergenciaId}/ofertas` |
| Validar en Sistema Nacional y Calcular Cobertura | `POST http://localhost:8002/login` y `/evaluaciones` | `POST http://localhost:8001/api/bonita/emergencias/${emergenciaId}/eventos` |
| Notificar Adjudicacion y Registrar Compromiso Nacional | `POST http://localhost:8002/login` y `/adjudicaciones/resolucion` | `POST http://localhost:8001/api/bonita/emergencias/${emergenciaId}/eventos` |
| Liberar Recursos y Notificar Cierre | `POST http://localhost:8002/login` y `/cierres/lote` | `POST http://localhost:8001/api/bonita/emergencias/${emergenciaId}/eventos` |

Para comprobar qué URLs trae un archivo: `python bonita/scripts/ver_conectores.py entrega-3/entrega42_local.bos`.

## Pasos

### 1. API Nacional (`:8002`)
```bash
cd nacional
python -m venv .venv && .venv\Scripts\activate         # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
python -m alembic upgrade head && python -m app.seed   # SQLite (nacional.db): ONGs, stock y las cuentas de servicio
uvicorn app.main:app --port 8002
```
Los valores por defecto (`change-me` para `bonita-service`, `change-me-app` para `app-service`) son solo para local. Swagger: http://localhost:8002/docs. Comprobar: `http://localhost:8002/health`.

### 2. Bonita Studio
1. **Archivo → Importar** → `entrega-3/entrega42_local.bos`. (Solo puede haber uno de los dos `.bos` activo: mismo nombre y versión de proceso. Si estaba el de la nube, esto lo reemplaza.)
2. Editor de la **Organización** → importar `entrega-2/ACME.xml` → **Desplegar** (sin esto falla con "Actor … does not contain any members").
3. Sobre el proceso `Gestion Integral de la Emergencia`: **Ejecutar**. Cada Ejecutar reinicia el motor y borra los casos.
4. Comprobar `http://localhost:8080/bonita` (técnico `walter.bates` / `bpm`; de prueba `operador.municipal`, `coordinador.regional`, `ong.cruzroja`, `ong.bomberos`, todos `bpm`).

Si algo falla al desplegar, el motivo real está en `<Studio>\workspace\tomcat\server\logs\bonita.log`.

### 3. App web (`:8001`)
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.local .env                                   # Linux/Mac: cp .env.local .env
python -m alembic upgrade head && python -m app.seed   # SQLite (dev.db)
uvicorn app.main:app --port 8001
```
`.env.local` apunta a `http://localhost:8002` con la clave `change-me-app` y SQLite. Si se cambia el `.env` con la app corriendo, reiniciarla. (`.env.example` es la referencia comentada de todas las variables; usa Postgres del `docker-compose.yml`.)

### 4. Front (`:5173`)
```bash
cd frontend && npm install && npm run dev              # Vite reenvía /api al backend
```

### 5. Probar
Entrar a http://localhost:5173 como `operador.municipal` (clave `demo1234`) y registrar una emergencia. Recorrido completo automático, con capturas (≈ 2-3 min): `cd backend && python scripts/ui_parada3.py` (toma la URL de la API Nacional del `backend/.env`).

Alta de ONGs de prueba: `http://localhost:5173/alta-ong` (no está en el menú). Crea la ONG en Bonita (grupo `/rescuesync/ong`), en la API Nacional con sus rubros y en la app; después se ingresa con ese usuario.

Pruebas con Bonita real (≈ 25 min): `cd backend && python scripts/correr_escenarios.py`. Solo funcionan en modo local (necesitan resetear la API Nacional).

## Volver a la nube
`copy backend\.env.nube backend\.env`, reiniciar la app, reimportar `entrega-3/entrega42_nube.bos` en Studio (y Ejecutar).
