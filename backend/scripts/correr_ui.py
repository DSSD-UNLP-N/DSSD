"""Corre los recorridos de la interfaz a la vez en lugar de uno tras otro.

Casi todo lo que tardan es esperar a que venza la ventana de ofertas (un timer real de Bonita) y eso no gasta nada: tres
navegadores pueden esperar al mismo tiempo. Los tres guiones usan recursos distintos, así que no se pisan:

  e2e_ui.py       brigadistas, agua, autobombas y raciones (la convocatoria queda abierta; sin evaluación)
  ui_parada2.py   raciones de Cruz Roja (caso B: reformular y segunda ronda)
  ui_parada3.py   paramédicos de las dos ONGs (alta → cierre bilateral)

`ui_ejecucion.py` no entra: es el tramo final de ui_parada3.py para una emergencia que ya está adjudicada.
`--completo` suma después, en serie, el caso A de ui_parada2.py (cobertura parcial con adjudicación a una sola ONG): usa los
mismos paramédicos que ui_parada3.py y por eso no puede ir a la vez.

Requisitos: los de cada guion (Bonita con el proceso desplegado, app en :8001, front en :5173, API Nacional con el seed y
nada comprometido de lo que usa cada uno); Chrome o Chromium. Tres navegadores a la vez piden más memoria: si la PC está
justa, usar --solo o --ventana 1.5.

    python scripts/correr_ui.py                    # los tres a la vez, ~3 min
    python scripts/correr_ui.py --completo         # + caso A de la parada 2 en serie
    python scripts/correr_ui.py --solo parada3,e2e # algunos
    python scripts/correr_ui.py --sin-capturas
    python scripts/correr_ui.py --ventana 1.5      # más margen para cargar ofertas antes del cierre (PC lenta)
    python scripts/correr_ui.py --timer 120        # e2e_ui espera además al boundary timer

Sale con código 1 si falla alguno.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
VENV = BACKEND / ".venv" / "Scripts" / "python.exe"
PY = str(VENV if VENV.exists() else sys.executable)

GUIONES = {"e2e": "e2e_ui.py", "parada2": "ui_parada2.py", "parada3": "ui_parada3.py"}
ONGS = ("30-54666544-5", "30-68522415-9")  # Cruz Roja y Bomberos: las que usan los guiones


def servicio_responde(url: str) -> bool:
    try:
        return requests.get(url, timeout=5).status_code < 500
    except requests.RequestException:
        return False


def chequear_servicios() -> list[str]:
    """Falla rápido, antes de abrir tres navegadores, si falta algo levantado."""
    pedidos = {"la app (:8001)": "http://localhost:8001/docs", "el front (:5173)": "http://localhost:5173/",
               "Bonita (:8080)": "http://localhost:8080/bonita/"}
    return [nombre for nombre, url in pedidos.items() if not servicio_responde(url)]


def _nacional():
    sys.path.insert(0, str(BACKEND))
    sys.path.insert(0, str(HERE))
    from app.core.config import get_settings
    from nacional_auth import nacional_get, nacional_post

    return get_settings().nacional_base_url.rstrip("/"), nacional_get, nacional_post


def comprometido() -> dict[str, int]:
    base, get, _ = _nacional()
    return {f"{cuit} {i['tipo_recurso']}": i["cantidad_comprometida"] for cuit in ONGS
            for i in get(f"{base}/ongs/{cuit}", timeout=90).json()["inventario"] if i["cantidad_comprometida"]}


def liberar_reservas() -> None:
    """Libera en la API Nacional las reservas que dejó una corrida que falló a medias (lo que no existe da 404 y se ignora)."""
    base, _, post = _nacional()  # también deja `app` importable
    from app.seed import DEMO_PASSWORD

    s = requests.Session()
    s.post("http://localhost:8001/api/auth/login", json={"username": "coordinador.regional", "password": DEMO_PASSWORD}, timeout=30)
    # Solo donde puede haber una reserva: sin evaluar todavía (REGISTRADA, CONVOCATORIA) o ya cerrada (RESUELTA) no hay ninguna.
    refs = [f"emg-{e['id']}-r{ronda}-{cuit}" for e in s.get("http://localhost:8001/api/emergencias", timeout=30).json()
            if e["estado"] in ("CERRADA", "EN_EVALUACION", "ADJUDICACION", "EN_EJECUCION") for ronda in (1, 2) for cuit in ONGS]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda ref: post(f"{base}/adjudicaciones/{ref}/liberar", timeout=90), refs))


def correr(nombre: str, args: list[str], resultados: dict) -> None:
    inicio = time.monotonic()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run([PY, str(HERE / args[0]), *args[1:]], cwd=BACKEND, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    segundos = time.monotonic() - inicio
    resultados[nombre] = (p.returncode, segundos, p.stdout + p.stderr)
    print(f"  [{'OK   ' if p.returncode == 0 else 'FALLA'}] {nombre} terminó en {segundos:.0f} s", flush=True)


def comandos(args: argparse.Namespace) -> dict[str, list[str]]:
    extra = ["--sin-capturas"] if args.sin_capturas else []
    ventana = ["--ventana", str(args.ventana)] if args.ventana else []
    return {
        "e2e": ["e2e_ui.py", *extra, *(["--timer", str(args.timer)] if args.timer else [])],
        "parada2": ["ui_parada2.py", *extra, *ventana],
        "parada3": ["ui_parada3.py", *extra, *ventana],
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # la salida de los guiones trae flechas y tildes
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo", help="lista separada por comas de: " + ", ".join(GUIONES))
    ap.add_argument("--completo", action="store_true", help="suma, en serie, el caso A de la parada 2")
    ap.add_argument("--sin-capturas", action="store_true")
    ap.add_argument("--ventana", type=float, help="minutos de margen para cargar ofertas antes del cierre (parada 2 y 3)")
    ap.add_argument("--timer", type=int, metavar="SEGUNDOS", help="e2e_ui: cierre a esa distancia, y espera al timer")
    ap.add_argument("--liberar", action="store_true", help="antes de empezar, libera las reservas que dejó una corrida fallida")
    args = ap.parse_args()

    elegidos = list(GUIONES) if not args.solo else [s.strip() for s in args.solo.split(",") if s.strip()]
    desconocidos = [s for s in elegidos if s not in GUIONES]
    if desconocidos:
        print(f"Desconocidos: {desconocidos}. Opciones: {list(GUIONES)}")
        return 2
    faltan = chequear_servicios()
    if faltan:
        print("No responde: " + ", ".join(faltan) + ". Levantarlos antes de correr (ver docs/instalacion-local.md).")
        return 2

    if args.liberar:
        liberar_reservas()
    colgado = comprometido()
    if colgado:
        print(f"La API Nacional tiene stock comprometido de una corrida anterior: {colgado}.\n"
              "Los guiones comparan contra «nada comprometido» y fallarían. Repetir con --liberar.")
        return 2

    cmds = comandos(args)
    resultados: dict[str, tuple[int, float, str]] = {}
    inicio = time.monotonic()
    print(f"Corriendo a la vez: {', '.join(elegidos)}", flush=True)
    hilos = [threading.Thread(target=correr, args=(n, cmds[n], resultados)) for n in elegidos]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    if args.completo:
        print("Ahora el caso A de la parada 2 (cobertura parcial), solo, porque usa los paramédicos…", flush=True)
        correr("parada2 + caso A", ["ui_parada2.py", "--con-parcial", *(["--sin-capturas"] if args.sin_capturas else []),
                                    *(["--ventana", str(args.ventana)] if args.ventana else [])], resultados)

    total = time.monotonic() - inicio
    print(f"\n== Resumen ({total:.0f} s en total; en serie serían {sum(s for _, s, _ in resultados.values()):.0f} s)")
    fallo = False
    for nombre, (codigo, segundos, salida) in resultados.items():
        lineas = [l for l in salida.splitlines() if l.strip()]
        ultima = next((l for l in reversed(lineas) if re.search(r"verificaciones OK", l)), lineas[-1] if lineas else "sin salida")
        print(f"  [{'OK   ' if codigo == 0 else 'FALLA'}] {nombre:<18} {segundos:>4.0f} s   {ultima.strip()}")
        if codigo != 0:
            fallo = True
            for l in lineas:
                if "FALLA" in l:
                    print("        " + l.strip())
    return 1 if fallo else 0


if __name__ == "__main__":
    sys.exit(main())
