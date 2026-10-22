"""Corre los escenarios con Bonita real uno tras otro y deja un resumen con el tiempo de cada uno.

No se pueden correr a la vez: comparten el Bonita, la app, la API Nacional y su stock (cada uno chequea «nada comprometido»).
Lo que sí hace en paralelo es lo que no toca esos servidores: los tests unitarios y el chequeo de tipos del front corren mientras
tanto (casi todo el tiempo de un escenario es esperar a que venza la ventana de ofertas).

Entre escenario y escenario borra los casos que dejó abiertos en Bonita (las variantes exigen que no haya ninguno) y corta en el
primero que falla. La duración de la ventana de ofertas es lo que más pesa: ESCENARIO_VENTANA_S (60 s por defecto; subirla si la
PC está cargada y aparecen fallas de «ventana cerrada»).

    python scripts/correr_escenarios.py                       # los seis, unos 25 min
    python scripts/correr_escenarios.py --solo cierre,jwt     # algunos
    python scripts/correr_escenarios.py --ventana 40          # ventana de ofertas más corta (PC holgada)
    python scripts/correr_escenarios.py --sin-unitarios

Requisitos: los de cada escenario (Bonita con el `.bos` de JWT, app en :8001 y API Nacional en :8002 con seed y nada comprometido).
Los de la interfaz (e2e_ui.py, ui_parada2.py, ui_ejecucion.py) necesitan además el front en :5173 y se corren aparte.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from app.core.config import get_settings  # noqa: E402
from app.integrations.bonita import BonitaClient  # noqa: E402

ESCENARIOS = {
    "evaluacion": "escenario_evaluacion.py",
    "tope": "escenario_tope.py",
    "adjudicacion": "escenario_adjudicacion.py",
    "cierre": "escenario_cierre.py",
    "variantes": "escenario_cierre_variantes.py",
    "jwt": "escenario_jwt.py",
}


def borrar_casos_abiertos() -> int:
    cfg = get_settings()
    admin = BonitaClient(cfg.bonita_base_url, cfg.bonita_timeout_seconds)
    admin.login(cfg.bonita_username, cfg.bonita_password)
    casos = admin._request("GET", "/API/bpm/case", params={"p": 0, "c": 200}).json()
    for c in casos:
        admin.delete_case(c["id"])
    return len(casos)


def unitarios(resultado: dict) -> None:
    inicio = time.monotonic()
    p = subprocess.run([sys.executable, str(HERE.parents[1] / "scripts" / "verificar_todo.py")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    resultado.update(codigo=p.returncode, salida=p.stdout.strip(), segundos=time.monotonic() - inicio)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", default="", help=f"separados por coma: {', '.join(ESCENARIOS)}")
    ap.add_argument("--sin-unitarios", action="store_true")
    ap.add_argument("--ventana", type=int, metavar="SEGUNDOS",
                    help="duración de la ventana de ofertas (ESCENARIO_VENTANA_S; 60 por defecto): en una PC holgada se puede bajar")
    args = ap.parse_args()
    elegidos = [n for n in ESCENARIOS if not args.solo or n in args.solo.split(",")]

    hilo, unit = None, {}
    if not args.sin_unitarios:
        hilo = threading.Thread(target=unitarios, args=(unit,))
        hilo.start()

    inicio, resumen, ok = time.monotonic(), [], True
    for nombre in elegidos:
        borrados = borrar_casos_abiertos()
        t = time.monotonic()
        print(f"\n########## {nombre} (casos de Bonita borrados antes: {borrados})", flush=True)
        env = {**os.environ, "ESCENARIO_VENTANA_S": str(args.ventana)} if args.ventana else None
        p = subprocess.Popen([sys.executable, "-u", str(HERE / ESCENARIOS[nombre])], cwd=str(HERE.parent), stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env)
        texto = []
        for linea in p.stdout:
            print(linea, end="", flush=True)
            texto.append(linea)
        codigo = p.wait()
        final = "".join(texto)
        fallas = len(re.findall(r"\[FALLA\]", final))
        m = re.findall(r"(\d+/\d+) verificaciones OK", final)
        resumen.append((nombre, codigo == 0 and not fallas, m[-1] if m else "sin resumen", time.monotonic() - t))
        if codigo or fallas:
            ok = False
            break

    print("\n==================== RESUMEN")
    for nombre, bien, cuantas, segs in resumen:
        print(f"  [{'OK   ' if bien else 'FALLA'}] {nombre:<13} {cuantas:>8}  {segs / 60:5.1f} min")
    if hilo:
        hilo.join()
        print(f"  [{'OK   ' if unit['codigo'] == 0 else 'FALLA'}] unitarios (en paralelo) {unit['segundos'] / 60:.1f} min")
        print("      " + unit["salida"].replace("\n", "\n      "))
        ok = ok and unit["codigo"] == 0
    print(f"\nTotal: {(time.monotonic() - inicio) / 60:.1f} min · {'TODO OK' if ok else 'HAY FALLAS'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
