"""Corre en paralelo todo lo que no necesita Bonita ni servidores: tests del backend, tests de
la API Nacional y chequeo de tipos del front. Imprime una línea por pieza y, si algo falla,
el final de su salida.

    python scripts/verificar_todo.py

Sale con código 1 si falla algo. Los escenarios con Bonita real (backend/scripts/escenario_*.py)
y verificar_despliegue.py necesitan servidores y no entran acá.
"""
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
VENV = RAIZ / "backend" / ".venv" / "Scripts" / "python.exe"
PY = str(VENV if VENV.exists() else sys.executable)

PIEZAS = {
    "backend": ([PY, "-m", "pytest", "-q"], RAIZ / "backend"),
    "nacional": ([PY, "-m", "pytest", "-q"], RAIZ / "nacional"),
    "front (tipos)": ([shutil.which("npm") or "npm", "run", "typecheck"], RAIZ / "frontend"),
}


def correr(item):
    nombre, (cmd, cwd) = item
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    lineas = [l for l in (p.stdout + p.stderr).splitlines() if l.strip()]
    return nombre, p.returncode, lineas


with ThreadPoolExecutor() as pool:
    resultados = list(pool.map(correr, PIEZAS.items()))

for nombre, codigo, lineas in resultados:
    resumen = lineas[-1] if lineas and not lineas[-1].startswith(">") else "sin errores"
    print(f"[{'OK   ' if codigo == 0 else 'FALLA'}] {nombre}: {resumen}")
    if codigo != 0:
        print("\n".join("    " + l for l in lineas[-40:]))

sys.exit(any(c != 0 for _, c, _ in resultados))
