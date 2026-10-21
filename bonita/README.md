# Bonita: herramientas del repo

Lo que hay alrededor del proceso `Gestion Integral de la Emergencia`. El diagrama en sí (lanes, tareas, timer, variables, actor
mapping) se diseña en Bonita Studio Community 10.4.0; lo demás se automatiza desde acá. Cómo levantar todo:
[`docs/instalacion-nube.md`](../docs/instalacion-nube.md) (por defecto) y [`docs/instalacion-local.md`](../docs/instalacion-local.md) (plan B).

## Qué `.bos` se usa

| Archivo | Para qué |
|---|---|
| `entrega-3/entrega42_nube.bos` | Proceso vigente con los conectores apuntando a la API Nacional de Render. |
| `entrega-3/entrega42_local.bos` | El mismo proceso con los conectores apuntando a `localhost:8002`. |
| `entrega-2/RescueSync.bos` | Export de la Entrega 2: lo lee `backend/tests/test_bonita_contract.py` para comprobar el contrato de instanciación. |

En Studio solo puede haber uno activo a la vez (mismo nombre y versión de proceso). Los dos vigentes se generaron con los
scripts de abajo y `backend/tests/test_bonita_conectores_nacional.py` comprueba que el de la nube es el local apuntando a Render.

## `scripts/`

Los scripts que editan el `.bos` trabajan sobre el XML interno (`.proc`, formato XMI) dentro del zip, no tocan el archivo de
entrada y escriben uno nuevo para importar en Studio. Cada uno explica su uso en el docstring.

| Script | Qué hace |
|---|---|
| `bonita_client.py` | Cliente REST de Bonita (login con el token CSRF, instanciar, tareas, variables) y una CLI mínima para instanciar un caso. La app tiene su propio cliente en `backend/app/integrations/bonita.py`. |
| `agregar_conector_cierre.py` | Agrega los conectores de «Liberar Recursos y Notificar Cierre» y deja «Confirmar Finalizacion de Actividades» como tarea estándar. |
| `agregar_login_nacional.py` | Agrega el conector `loginNacional` (JWT) antes de cada llamada a la API Nacional y la cabecera `Authorization: Bearer`. |
| `preparar_entorno.py` | Cambia la URL de la API Nacional y la clave de `bonita-service` de un `.bos` (así se generó el de la nube a partir del local). |
| `ver_conectores.py` | Muestra a qué URLs llama cada tarea de servicio de un `.bos`. |

## `organizations/`

`RescueSyncOrg.xml` es una organización de referencia. **La que se usa es `entrega-2/ACME.xml`** (ACME editada de forma aditiva, con los
grupos `/rescuesync/{municipio,coordinador,ong,auditoria}` y un usuario por perfil). Importarla y **Desplegarla** desde el editor de la
organización; Bonita solo tiene una organización activa a la vez. Los cambios hechos a mano en Studio están en
[`entrega-2/CAMBIOS-BONITA.md`](../entrega-2/CAMBIOS-BONITA.md).

## Lo que solo se hace en Studio

Crear o cambiar variables, lanes, el timer y el actor mapping (la edición Community no trae `BonitaStudioBuilder`). Después de cambiar
el diagrama hay que exportar el `.bos`, y si cambia el contrato de instanciación actualizar `CONTRACT_INPUTS` en
`backend/app/integrations/bonita.py`: el test del contrato avisa si no coinciden.

## API REST de Bonita

Todo lo que pasa con el proceso desplegado (login, instanciar, tareas, variables) es la REST API del motor, disponible en Community:
[REST API Overview](https://documentation.bonitasoft.com/bonita/latest/api/rest-api-overview) y
[CSRF security](https://documentation.bonitasoft.com/bonita/latest/security/csrf-security).
