---
name: editar-bos
description: Cómo modificar el proceso de Bonita (el .bos) sin romperlo ni pisar a otra persona: por script, un solo editor a la vez, local y nube idénticos salvo URLs y clave. Usar antes de tocar conectores, tareas, variables o la organización, o al preparar el .bos de nube.
---

# Editar el `.bos`

- **Es un zip binario** (`.gitattributes`): nunca diff ni merge textual. Edita **una persona por vez**; avisar antes de empezar y después de subir.
- **Preferir scripts** a Studio: `bonita/scripts/agregar_conector_cierre.py`, `agregar_login_nacional.py`, `preparar_entorno.py`, `ver_conectores.py`.
  Dejan la edición repetible y revisable; la bitácora de cada cambio va en el archivo CAMBIOS-BONITA.md de la carpeta de la entrega (solo local).
- **Solo dos `.bos` versionados**: `entrega-3/entrega42_local.bos` y `entrega42_nube.bos`. Son idénticos salvo las URLs de los conectores (`localhost:8002` ↔ Render) y la clave de
  `bonita-service` (la de la demo, pública a propósito). Un test lo verifica. Generar el de nube desde el local:
  `NACIONAL_BONITA_PASSWORD=<clave> python bonita/scripts/preparar_entorno.py entrega-3/entrega42_local.bos entrega-3/entrega42_nube.bos --nacional https://rescuesync-nacional.onrender.com`.
- **Revisar antes de subir**: `python .claude/skills/rescuesync-estado/scripts/inspect_bos.py <archivo>` (variables, contrato, timer, actores) y `ver_conectores.py`.
- **Importar**: Studio → importar como proyecto **nuevo** (base H2 limpia, 150 casos nuevos) → *Ejecutar* → *Desplegar organización*. Cada Ejecutar borra los casos.
  Tomcat tarda hasta 4 min: no tocar Studio. Si el login de `walter.bates` falla: `workspace\tomcat\server\logs\bonita.log`.
- **Reglas del modelo**: la descripción del Pool < 255 caracteres; las condiciones de los XOR son Groovy (`coberturaCompleta == false`), no `${…}`; el timer evalúa `ventanaOfertasISO` al
  activarse la tarea; la app nunca completa «Cargar Ofertas de Ayuda». Un nodo de servicio fallido no se reintenta por REST: `backend/scripts/recuperar_cierre.py`.
- **Después**: `probar-en-nube` (al menos `cierre` y `e2e_ui`) con el `.bos` recién importado.
