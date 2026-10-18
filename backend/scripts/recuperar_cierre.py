"""Termina a mano un cierre que Bonita dejó trabado: la API Nacional o la app no respondían cuando se validó el cierre.

Bonita deja «Liberar Recursos y Notificar Cierre» como nodo fallido y, con la API REST de la Community, no hay forma de
reintentarlo (el Portal de administración sí). Este script hace lo mismo que los conectores, en el mismo orden, y como los
dos pasos son idempotentes sirve también si el primero ya se había hecho:

  1. POST /cierres/lote en la API Nacional con las referencias de las ONGs adjudicadas;
  2. evento CIERRE a la app (la emergencia pasa a RESUELTA y las ONGs reciben el aviso);
  3. el nodo fallido se marca «skipped» para que el caso de Bonita termine.

Solo actúa si todas las ONGs adjudicadas finalizaron y Bonita tiene un nodo fallido en ese caso. Requiere la API
Nacional y la app arriba. Lee todo de las APIs (no toca ninguna base).

    python scripts/recuperar_cierre.py 12                  # número de emergencia
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nacional_auth import nacional_post  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.integrations.bonita import BonitaClient  # noqa: E402
from app.seed import DEMO_PASSWORD  # noqa: E402


class SinCierreTrabado(RuntimeError):
    pass


def recuperar(emergencia: int, app: str = "http://localhost:8001", coordinador: str = "coordinador.regional",
              clave: str = DEMO_PASSWORD) -> list[str]:
    """Devuelve lo que hizo, paso por paso."""
    cfg = get_settings()
    app = app.rstrip("/")
    sesion = requests.Session()
    sesion.post(f"{app}/api/auth/login", json={"username": coordinador, "password": clave}, timeout=30).raise_for_status()
    d = sesion.get(f"{app}/api/emergencias/{emergencia}", timeout=30).json()
    bonita = BonitaClient(cfg.bonita_base_url, cfg.bonita_timeout_seconds)
    bonita.login(cfg.bonita_username, cfg.bonita_password)
    fallidos = bonita._request("GET", "/API/bpm/flowNode",
                               params={"f": [f"caseId={d['bonita_case_id']}", "state=failed"], "p": 0, "c": 20}).json()
    if d["estado"] != "EN_EJECUCION" or not fallidos or not (d.get("ejecucion") or {}).get("todas_finalizadas"):
        raise SinCierreTrabado(
            f"La emergencia #{emergencia} (estado {d['estado']}) no tiene un cierre trabado: hace falta que todas las ONGs "
            "hayan finalizado y que Bonita tenga un nodo fallido. Si falta validar el cierre, se hace desde la app.")
    cuits = [o["cuit"] for o in d["ejecucion"]["ongs"]]
    referencias = {o["cuit"]: o["referencia"] for o in d["evaluacion"]["ongs"]}
    hecho = []

    r = nacional_post(f"{cfg.nacional_base_url.rstrip('/')}/cierres/lote", timeout=60,
                      json={"cierres": [{"cuit": c, "referencia": referencias[c]} for c in cuits]})
    r.raise_for_status()
    hecho.append(f"API Nacional: {len(cuits)} referencia(s) cerradas ({', '.join(referencias[c] for c in cuits)})")

    r = requests.post(f"{app}/api/bonita/emergencias/{emergencia}/eventos", json={"tipo": "CIERRE", "cuits": cuits},
                      headers={"X-Api-Key": cfg.bonita_api_key}, timeout=60)
    r.raise_for_status()
    hecho.append("App: evento CIERRE enviado (emergencia RESUELTA y avisos a las ONGs)")

    for nodo in fallidos:
        bonita._request("PUT", f"/API/bpm/activity/{nodo['id']}", json={"state": "skipped"}).raise_for_status()
        hecho.append(f"Bonita: nodo fallido «{nodo['displayName']}» salteado")
    return hecho


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("emergencia", type=int)
    ap.add_argument("--app", default="http://localhost:8001")
    args = ap.parse_args()
    try:
        for paso in recuperar(args.emergencia, args.app):
            print(f"  {paso}")
    except SinCierreTrabado as exc:
        print(exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
