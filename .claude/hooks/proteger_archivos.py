"""Hook PreToolUse (Edit/Write): bloquea la edición directa de los `.bos` y de los `.env`.

- Los `.bos` se editan solo por script (skill `editar-bos`): a mano se rompen o se pisa el trabajo de otro.
- Los `.env` tienen secretos: los edita la persona, no el agente. `.env.example` sí se puede editar.
"""
import json
import sys
from pathlib import Path

datos = json.load(sys.stdin)
ruta = (datos.get("tool_input") or {}).get("file_path") or (datos.get("tool_input") or {}).get("notebook_path") or ""
nombre = Path(ruta).name

if nombre.lower().endswith(".bos"):
    print("No edites el .bos a mano: usá los scripts de bonita/scripts/ (skill editar-bos).", file=sys.stderr)
    sys.exit(2)
if nombre.startswith(".env") and nombre != ".env.example":
    print(f"{nombre} tiene secretos: pedile a la persona que lo edite.", file=sys.stderr)
    sys.exit(2)
sys.exit(0)
