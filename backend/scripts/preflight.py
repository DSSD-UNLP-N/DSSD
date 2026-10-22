"""Antes de correr escenarios o una demo: ¿está todo en pie y en el modo que se cree?

Revisa lo que en la práctica rompió pruebas: el modo (local o nube) del `.env`, la API Nacional (versión desplegada, login, nada
comprometido), la app y el front, Bonita (login, proceso desplegado, casos abiertos) y la base de la app (convocatorias abiertas, que
descuentan inventario). Sale con 1 si algo impide probar; los avisos no lo impiden.

    python scripts/preflight.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.integrations.bonita import BonitaClient  # noqa: E402

fallas = avisos = 0


def ok(texto: str) -> None:
    print(f"  [OK   ] {texto}")


def aviso(texto: str) -> None:
    global avisos
    avisos += 1
    print(f"  [AVISO] {texto}")


def falla(texto: str) -> None:
    global fallas
    fallas += 1
    print(f"  [FALLA] {texto}")


def responde(url: str, timeout: float = 5) -> bool:
    try:
        return requests.get(url, timeout=timeout).status_code < 500
    except requests.RequestException:
        return False


def nacional(cfg) -> None:
    nube = "onrender.com" in cfg.nacional_base_url
    print(f"\n== API Nacional: {'NUBE (Render)' if nube else 'LOCAL'} · {cfg.nacional_base_url}")
    timeout = max(cfg.nacional_timeout_seconds, 90 if nube else 5)  # el plan gratis duerme: la primera llamada tarda
    try:
        salud = requests.get(f"{cfg.nacional_base_url}/health", timeout=timeout).json()
    except (requests.RequestException, ValueError) as exc:
        return falla(f"/health no responde ({exc.__class__.__name__}): ¿está levantada?")
    ok(f"/health ok · commit {salud.get('commit', '¿?')[:7]}")
    login = requests.post(f"{cfg.nacional_base_url}/login", timeout=timeout,
                          json={"username": cfg.nacional_service_username, "password": cfg.nacional_service_password})
    if login.status_code != 200:
        return falla(f"login de {cfg.nacional_service_username} → {login.status_code}: revisar NACIONAL_SERVICE_PASSWORD del .env")
    ok(f"login de {cfg.nacional_service_username}")
    header = {"Authorization": f"Bearer {login.json()['access_token']}"}
    comprometido = sum(r["cantidad_comprometida"] for r in
                       requests.get(f"{cfg.nacional_base_url}/recursos/disponibilidad", headers=header, timeout=timeout).json())
    if comprometido:
        aviso(f"hay {comprometido} unidades comprometidas en Nacional: los escenarios exigen «nada comprometido»")
    else:
        ok("nada comprometido")


def app() -> None:
    print("\n== App y front")
    if responde("http://localhost:8001/openapi.json"):
        ok("app en :8001")
    else:
        falla("la app no responde en :8001 (preview_start rescuesync-backend, o uvicorn)")
    if responde("http://localhost:5173"):
        ok("front en :5173")
    else:
        aviso("el front no responde en :5173 (solo lo necesitan las pruebas de interfaz)")


def bonita(cfg) -> None:
    print(f"\n== Bonita · {cfg.bonita_base_url}")
    admin = BonitaClient(cfg.bonita_base_url, cfg.bonita_timeout_seconds)
    try:
        admin.login(cfg.bonita_username, cfg.bonita_password)
    except Exception as exc:  # noqa: BLE001
        return falla(f"login de {cfg.bonita_username} falló ({exc.__class__.__name__}): ¿Studio con el proyecto ejecutado?")
    ok(f"login de {cfg.bonita_username}")
    try:
        admin.resolve_process_id(cfg.bonita_process_name, cfg.bonita_process_version)
        ok(f"proceso «{cfg.bonita_process_name}» v{cfg.bonita_process_version} desplegado")
    except Exception:  # noqa: BLE001
        falla("el proceso no está desplegado: importar el .bos (nube o local, según el modo) y ejecutar")
    casos = admin._request("GET", "/API/bpm/case", params={"p": 0, "c": 200}).json()
    if casos:
        aviso(f"{len(casos)} caso(s) abiertos en Bonita: tienen timers que reservan stock y las variantes exigen ninguno "
              "(correr_escenarios los borra al empezar)")
    else:
        ok("sin casos abiertos")
    print("     (el .bos importado tiene que ser el del modo de arriba: entrega42_nube.bos para Render, entrega42_local.bos para :8002)")


def base_de_la_app(cfg) -> None:
    print("\n== Base de la app")
    ruta = cfg.database_url.removeprefix("sqlite:///")
    if not cfg.database_url.startswith("sqlite:///") or not Path(ruta).exists():
        return ok("no es un SQLite local: nada que revisar")
    con = sqlite3.connect(ruta, timeout=10)
    total, = con.execute("select count(*) from emergencia").fetchone()
    abiertas, = con.execute("select count(*) from emergencia where estado = 'CONVOCATORIA'").fetchone()
    ok(f"{total} emergencia(s) en {ruta}")
    if abiertas:
        aviso(f"{abiertas} convocatoria(s) abiertas: sus ofertas descuentan inventario de las ONGs (retirar_previas las retira)")


def main() -> int:
    cfg = get_settings()
    nacional(cfg)
    app()
    bonita(cfg)
    base_de_la_app(cfg)
    print(f"\n{fallas} falla(s), {avisos} aviso(s)")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
