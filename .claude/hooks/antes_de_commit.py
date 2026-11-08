"""Hook PreToolUse (Bash): antes de un `git commit`, corre `scripts/verificar_todo.py` y bloquea el commit si algo falla.

Claude Code le pasa por stdin el JSON de la llamada. Salir con código 2 bloquea la herramienta y le muestra stderr a Claude.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

datos = json.load(sys.stdin)
comando = (datos.get("tool_input") or {}).get("command", "")
if not re.search(r"\bgit\b[^|;&]*\bcommit\b", comando):
    sys.exit(0)

raiz = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
p = subprocess.run([sys.executable, str(raiz / "scripts" / "verificar_todo.py")], cwd=raiz,
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
if p.returncode != 0:
    salida = (p.stdout + p.stderr).strip().splitlines()
    print("verificar_todo.py falló; arreglalo antes de commitear:\n" + "\n".join(salida[-40:]), file=sys.stderr)
    sys.exit(2)
sys.exit(0)
