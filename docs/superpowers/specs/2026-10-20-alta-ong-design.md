# Alta de ONG (`/alta-ong`) — diseño

Fecha: 2026-10-20 · Rama: `feat/alta-ong` (desde `dev`, PR a `dev`)

## Intención

La cátedra pidió (mail del 15/10) que la Entrega 3 incluya "la funcionalidad para registrar una ONG en el sistema
nacional, con los rubros que puede prestar". Es una funcionalidad para que el equipo y quien corrige puedan dar de alta
ONGs de prueba, no una pantalla del enunciado. La API Nacional ya lo permite en dos pasos (`POST /ongs` y
`PUT /ongs/{cuit}/inventario`), pero la app no tiene forma de hacerlo y una ONG creada solo en la API Nacional no puede
entrar a la app ni ejecutar sus tareas en Bonita.

Se agrega una pantalla **oculta** `/alta-ong` en la SPA que da de alta una ONG en los tres sistemas a la vez, para que
la ONG nueva pueda recorrer el flujo completo (ofertar, ser adjudicada, marcar su actividad terminada).

"Rubros" = tipos de recurso del catálogo nacional que la ONG puede prestar, con la cantidad disponible de cada uno
(se guarda como inventario en la API Nacional). Si la cátedra confirma otra interpretación, Tomás lo ajusta.

## Objetivos

- Ruta `/alta-ong` en la SPA, **sin link en ningún menú ni en el login**, accesible escribiendo la URL. No requiere
  sesión.
- Formulario: nombre de la ONG, CUIT, nombre de la persona de contacto, usuario, contraseña, y una lista de rubros
  (tipo de recurso elegido del catálogo + cantidad entera ≥ 0, al menos uno, sin repetir tipos).
- Un endpoint del backend de la app que, en una sola operación, deja la ONG:
  1. en **Bonita**: usuario con el mismo username, membresía rol `representante_ong` en el grupo `/rescuesync/ong`
     (es el grupo al que está mapeado el actor "ONG" del proceso);
  2. en la **API Nacional**: `POST /ongs` y, con el token que devuelve, `PUT /ongs/{cuit}/inventario` con los rubros;
  3. en la **base local de la app**: fila `Ong` (nombre, CUIT) y `Usuario` con rol ONG asociado a esa ONG, con la
     contraseña elegida (hash).
- Al terminar bien, la pantalla muestra éxito y un link al login. La ONG puede loguearse en la app con su usuario y
  contraseña.
- Errores claros en el formulario: usuario, nombre o CUIT ya registrados (en cualquiera de los tres sistemas), Bonita o
  API Nacional no disponibles, validación de campos.

## No objetivos

- Certificaciones de la ONG (no se pueden cargar por la API Nacional; la evaluación por competencia baja de nivel en vez
  de rechazar, alcanza para testear).
- Editar o borrar ONGs, o editar el inventario después del alta (para eso está `PUT /ongs/{cuit}/inventario` en Swagger).
- Proteger la ruta con autenticación o roles. Es oculta, no segura; se acepta para una herramienta de prueba.
- Cambios en la API Nacional ni en el `.bos`.

## Anti-objetivos

- Que el alta deje la ONG a medias de forma silenciosa (p. ej., creada en la API Nacional pero sin usuario en Bonita) y
  la pantalla diga "ok". Si algo queda a medias, se informa.
- Que aparezca un link a `/alta-ong` en la interfaz normal.
- Romper el seed, los usuarios demo o los tests existentes.

## Restricciones y hechos del código

- La app completa tareas de Bonita entrando **con el username del usuario de la app** y la contraseña
  `settings.bonita_test_password` (`"bpm"`), ver `backend/app/services/ciclo.py:37-46` y
  `backend/app/services/ejecucion.py:90`. Por eso el usuario de Bonita se crea con esa contraseña, no con la que eligió
  la ONG.
- Organización Bonita (`entrega-2/ACME.xml`): grupo `/rescuesync/ong`, rol `representante_ong`. El actor "ONG" está
  mapeado al grupo (`process_configurations/*.conf` del `.bos`), así que una membresía nueva alcanza.
- Las operaciones administrativas en Bonita se hacen con el usuario técnico (`settings.bonita_username` /
  `bonita_password`), como en `ciclo.py:44`. API REST: `POST /API/identity/user`, `GET /API/identity/group`,
  `GET /API/identity/role`, `POST /API/identity/membership`, `DELETE /API/identity/user/{id}`. El usuario debe quedar
  `enabled`.
- API Nacional: `POST /ongs` es pública (body `ong_nombre`, `cuit`, `nombre`, `username`, `password`), devuelve
  `TokenOut` con `access_token`; 409 por usuario, nombre o CUIT repetido. `PUT /ongs/{cuit}/inventario` exige el token
  de esa ONG; body `{"items":[{"tipo_recurso": "<codigo>", "cantidad_total": n}]}`; 404 tipo inexistente, 422 repetido.
  La API Nacional **no tiene endpoint para borrar** una ONG.
- La app ya expone `GET /api/tipos-recurso` (catálogo de la API Nacional) para elegir rubros.
- Modelos locales: `Ong(nombre unique, cuit unique)`, `Usuario(username unique, password_hash, nombre, rol, ong_id)` en
  `backend/app/models/entities.py`. El nombre de la persona de contacto va a `Usuario.nombre` (y a `nombre` en
  `POST /ongs`). No hace falta migración.
- `PUT /ongs/{cuit}/inventario` acepta `cantidad_total = 0` (`InventarioItemIn`: `Field(ge=0)`), así que el formulario
  permite 0 y se manda tal cual.
- Cliente de la API Nacional: `backend/app/integrations/nacional.py` (hoy usa la cuenta de servicio `app-service`); el
  alta necesita llamadas sin ese login y otra con el token de la ONG.
- Mismo estilo que el resto: FastAPI + SQLAlchemy, React + TypeScript, textos de UI en español, tests con pytest
  (TDD estricto) y los dobles/fakes que ya usan los tests de la app para Bonita y la API Nacional.

## Orden de la operación (decidido)

1. Validar el body. Chequear en la base local que no existan el username, el nombre de ONG ni el CUIT → 409.
2. Bonita: login técnico, verificar que el username no exista → 409; crear usuario (contraseña
   `bonita_test_password`, habilitado) y su membresía. Si Bonita no responde → 503 sin tocar nada más.
3. API Nacional: `POST /ongs`. Si falla (409, caída, timeout) → **borrar el usuario de Bonita creado en el paso 2** y
   devolver el error (409 o 502/503).
4. API Nacional: `PUT /ongs/{cuit}/inventario` con el token del paso 3. Si falla → no hay forma de deshacer la ONG en la
   API Nacional: borrar el usuario de Bonita, no crear nada local, y devolver un error que diga explícitamente que la
   ONG quedó registrada en la API Nacional sin rubros (y que se puede completar desde Swagger con
   `PUT /ongs/{cuit}/inventario`).
5. Base local: crear `Ong` y `Usuario` y commitear. Si falla (carrera de unicidad) → borrar el usuario de Bonita y
   devolver 409 informando que la ONG quedó en la API Nacional.
6. 201 con los datos de la ONG creada (nombre, CUIT, username, rubros).

## Decisiones tomadas como criterio propio (revisables)

- Endpoint del backend: `POST /api/ongs/alta`, sin sesión ni API key.
- Contraseña de la app y de la API Nacional = la que elige el usuario (mín. 8, como exige la API Nacional); la de
  Bonita = `bonita_test_password`.
- Username con el formato libre que acepte la API Nacional (3-60); sugerencia en el placeholder: `ong.<nombre>`.
- CUIT se guarda localmente con el mismo formato que se envió a la API Nacional (la API Nacional acepta con o sin
  guiones; normalizar a `NN-NNNNNNNN-N` en la app para que coincida con el seed).

## Queda a criterio de quien implementa

- Nombres de funciones, archivos y componentes; dónde vive la lógica de orquestación (servicio nuevo en
  `backend/app/services/`).
- Diseño visual del formulario, siguiendo los estilos existentes (`frontend/src/styles.css`) y responsive.
- Cómo se ve la lista de rubros (filas dinámicas agregar/quitar, o checklist del catálogo con cantidad).
- Códigos HTTP exactos de error no listados arriba, siempre con `detail` legible en español.

## Verificación

- Tests de backend que cubran: alta exitosa (los tres sistemas llamados en orden, datos locales creados), duplicado
  local, duplicado en Bonita, 409 de la API Nacional con compensación en Bonita, falla del inventario con mensaje
  explícito, Bonita caído → nada creado.
- Typecheck y build del front.
- Prueba manual: alta de una ONG en `/alta-ong`, login con esa ONG en la app, aparece en `GET /ongs/{cuit}` de la API
  Nacional con su inventario, y existe en el portal de Bonita en el grupo `/rescuesync/ong`.
- Documentar en las guías de instalación/uso la ruta `/alta-ong` (una línea en cada guía).
