"""Escenario de la segunda parada: después de la evaluación, el Coordinador decide y el Municipio adjudica.

  A) cobertura parcial: pide 10 paramédicos; Cruz Roja ofrece 4 y Bomberos 2 (60 %).
     El Coordinador elige PARCIAL; el Municipio adjudica solo a Cruz Roja.
     Esperado: Cruz Roja queda ADJUDICADA (4 comprometidos), Bomberos LIBERADA (0), la emergencia pasa a EN_EJECUCION
     y el caso de Bonita espera en "Monitorear Ejecucion del Despliegue".
  B) reformulación: pide 3000 L de agua; Cruz Roja ofrece 2000 (66,7 %). El Coordinador elige REFORMULAR.
     Esperado: se libera la reserva, vuelve a REGISTRADA con la ronda 2, el Coordinador publica de nuevo, Cruz Roja ofrece
     los 3000 L, la evaluación de la ronda 2 cubre todo, va directo a adjudicación y el Municipio adjudica.

Requisitos: Bonita con el proceso desplegado, incluidos los conectores de "Notificar Adjudicacion y Registrar Compromiso
Nacional"; app en :8001; API Nacional en :8002 con el seed y nada comprometido. Tarda unos 8 minutos.

    python scripts/escenario_adjudicacion.py
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from escenario_tope import Escenario, crear_y_publicar  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.integrations.bonita import BonitaClient  # noqa: E402

CRUZ_ROJA, BOMBEROS = "30-54666544-5", "30-68522415-9"
VENTANA_S = 130


def comprometido(nacional: str, cuit: str, tipo: str) -> int:
    ficha = requests.get(f"{nacional}/ongs/{cuit}", timeout=60).json()
    return next(i["cantidad_comprometida"] for i in ficha["inventario"] if i["tipo_recurso"] == tipo)


def esperar(e: Escenario, emergencia: int, condicion, segundos: int) -> dict | None:
    """Mira el detalle del Coordinador cada pocos segundos hasta que `condicion(detalle)` sea cierta."""
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        try:
            d = e.get("coordinador.regional", f"/emergencias/{emergencia}").json()
        except requests.ConnectionError:  # el servidor cerró la conexión inactiva
            d = None
        if d is not None and condicion(d):
            return d
        time.sleep(6)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="http://localhost:8001")
    args = ap.parse_args()
    e = Escenario(args.app)
    cfg = get_settings()
    nacional = cfg.nacional_base_url.rstrip("/")
    admin = BonitaClient(cfg.bonita_base_url, cfg.bonita_timeout_seconds)
    admin.login(cfg.bonita_username, cfg.bonita_password)

    print("== Preparación")
    previos = {(c, t): comprometido(nacional, c, t) for c, t in
               [(CRUZ_ROJA, "PARAMEDICO"), (BOMBEROS, "PARAMEDICO"), (CRUZ_ROJA, "AGUA_POTABLE")]}
    e.check("La API Nacional no tiene nada comprometido al empezar", not any(previos.values()), previos)
    fin = datetime.now().astimezone() + timedelta(seconds=VENTANA_S)
    ea, caso_a, la = crear_y_publicar(e, "Escenario A", "ALTO", [("PARAMEDICO", 10, "PRINCIPAL")], fin)
    eb, caso_b, lb = crear_y_publicar(e, "Escenario B", "MEDIO", [("AGUA_POTABLE", 3000, "PRINCIPAL")], fin)
    print(f"     A=#{ea} (caso {caso_a}) · B=#{eb} (caso {caso_b}) · vencen {fin:%H:%M:%S}")
    e.esperar("A1 Cruz Roja ofrece 4 paramédicos", e.ofrecer("ong.cruzroja", ea, (la["PARAMEDICO"], 4)), 201)
    e.esperar("A2 Bomberos ofrece 2 paramédicos", e.ofrecer("ong.bomberos", ea, (la["PARAMEDICO"], 2)), 201)
    e.esperar("B1 Cruz Roja ofrece 2000 L de agua", e.ofrecer("ong.cruzroja", eb, (lb["AGUA_POTABLE"], 2000)), 201)

    print(f"\n== Esperando la evaluación de Bonita ({fin:%H:%M:%S})")
    espera = VENTANA_S + 200
    da = esperar(e, ea, lambda d: d["evaluacion"] is not None, espera)
    db = esperar(e, eb, lambda d: d["evaluacion"] is not None, 60)
    e.check("A y B quedaron evaluadas (en EN_EVALUACION: la cobertura no alcanza)",
            da is not None and db is not None and da["estado"] == db["estado"] == "EN_EVALUACION",
            (da and da["estado"], db and db["estado"]))
    if da is None or db is None:
        print(f"\n{e.ok}/{e.total} verificaciones OK")
        return 1

    print("\n== Permisos de la decisión")
    e.esperar("P1 El Municipio no decide → 403", e.post("operador.municipal", f"/emergencias/{ea}/decision", {"decision": "PARCIAL"}), 403)
    e.esperar("P2 La ONG no decide → 403", e.post("ong.cruzroja", f"/emergencias/{ea}/decision", {"decision": "PARCIAL"}), 403)

    print("\n== A: el Coordinador sigue con cobertura parcial y el Municipio adjudica a Cruz Roja")
    r = e.post("coordinador.regional", f"/emergencias/{ea}/decision", {"decision": "PARCIAL"})
    e.check("A3 PARCIAL → la emergencia pasa a ADJUDICACION", r.status_code == 200 and r.json()["estado"] == "ADJUDICACION", r.text)
    tarea = admin.wait_for_task(caso_a, "Adjudicar Ofertas", retries=20)
    e.check("A4 Bonita: el caso pasó a 'Adjudicar Ofertas' (Municipio)", tarea is not None,
            [t["displayName"] for t in admin.get_human_tasks(caso_a)])
    e.esperar("A5 El Coordinador no adjudica → 403", e.post("coordinador.regional", f"/emergencias/{ea}/adjudicar", {"cuits": [CRUZ_ROJA]}), 403)
    e.esperar("A6 No se puede elegir una ONG sin oferta validada → 400",
              e.post("operador.municipal", f"/emergencias/{ea}/adjudicar", {"cuits": ["30-99999999-9"]}), 400)
    r = e.post("operador.municipal", f"/emergencias/{ea}/adjudicar", {"cuits": [CRUZ_ROJA]})
    e.check("A7 El Municipio adjudica a Cruz Roja", r.status_code == 200, r.text)
    d = esperar(e, ea, lambda d: d["estado"] == "EN_EJECUCION", 90)
    e.check("A8 Bonita avisó y la emergencia pasó a EN_EJECUCION", d is not None, d and d["estado"])
    ofertas = {o["ong_nombre"]: o["estado"] for o in e.get("coordinador.regional", f"/emergencias/{ea}/ofertas").json()}
    e.check("A9 Cruz Roja ADJUDICADA, Bomberos NO_ADJUDICADA",
            ofertas == {"Cruz Roja Argentina": "ADJUDICADA", "Bomberos Voluntarios": "NO_ADJUDICADA"}, ofertas)
    e.check("A10 Nacional: Cruz Roja sigue con 4 comprometidos y a Bomberos se le liberaron los 2",
            (comprometido(nacional, CRUZ_ROJA, "PARAMEDICO"), comprometido(nacional, BOMBEROS, "PARAMEDICO")) == (4, 0))
    tarea = admin.wait_for_task(caso_a, "Monitorear Ejecucion", retries=20)
    e.check("A11 Bonita: el caso espera en 'Monitorear Ejecucion del Despliegue' (Coordinador)", tarea is not None,
            [t["displayName"] for t in admin.get_human_tasks(caso_a)])
    e.check("A12 Nacional: la reserva de Cruz Roja quedó ADJUDICADA y la de Bomberos LIBERADA",
            requests.post(f"{nacional}/adjudicaciones/emg-{ea}-r1-{CRUZ_ROJA}/confirmar", timeout=60).json()["estado"] == "ADJUDICADA"
            and requests.post(f"{nacional}/adjudicaciones/emg-{ea}-r1-{BOMBEROS}/liberar", timeout=60).json()["estado"] == "LIBERADA")

    print("\n== B: el Coordinador reformula")
    d = e.get("coordinador.regional", f"/emergencias/{eb}").json()
    e.check("B2 La evaluación de B: 66,7 %", d["evaluacion"]["porcentaje_cobertura"] == 66.7, d["evaluacion"]["porcentaje_cobertura"])
    e.check("B3 Nacional: 2000 L de agua reservados", comprometido(nacional, CRUZ_ROJA, "AGUA_POTABLE") == 2000)
    r = e.post("coordinador.regional", f"/emergencias/{eb}/decision", {"decision": "REFORMULAR"})
    e.check("B4 REFORMULAR → vuelve a REGISTRADA, ronda 2, sin evaluación",
            r.status_code == 200 and r.json()["estado"] == "REGISTRADA" and r.json()["evaluacion"] is None, r.text)
    e.check("B5 Nacional: se liberó la reserva del agua", comprometido(nacional, CRUZ_ROJA, "AGUA_POTABLE") == 0)
    o = e.get("coordinador.regional", f"/emergencias/{eb}/ofertas").json()
    e.check("B6 La oferta de la ronda 1 quedó retirada (con su historial)", len(o) == 1 and o[0]["retirada"] is True, o)
    tarea = admin.wait_for_task(caso_b, "Revisar Informacion", retries=20)
    e.check("B7 Bonita: el caso volvió a 'Revisar Informacion y Generar Lotes' (camino REFORMULAR)", tarea is not None,
            [t["displayName"] for t in admin.get_human_tasks(caso_b)])

    print("\n== B: segunda ronda")
    fin2 = datetime.now().astimezone() + timedelta(seconds=100)
    r = e.post("coordinador.regional", f"/emergencias/{eb}/publicar", {"ventana_fin": fin2.isoformat(timespec="seconds")})
    e.check("B8 El Coordinador publica de nuevo", r.status_code == 200 and r.json()["estado"] == "CONVOCATORIA", r.text)
    e.esperar("B9 Cruz Roja ofrece los 3000 L completos", e.ofrecer("ong.cruzroja", eb, (lb["AGUA_POTABLE"], 3000)), 201)
    print(f"     la ronda 2 vence {fin2:%H:%M:%S}")
    d = esperar(e, eb, lambda d: d["evaluacion"] is not None, 100 + 200)
    e.check("B10 La evaluación de la ronda 2 cubre todo y va directo a ADJUDICACION",
            d is not None and d["estado"] == "ADJUDICACION" and d["evaluacion"]["cobertura_completa"] is True
            and d["evaluacion"]["ronda"] == 2, d and (d["estado"], d["evaluacion"]["ronda"]))
    if d is not None:
        ref2 = d["evaluacion"]["ongs"][0]["referencia"]
        e.check("B11 La referencia lleva la ronda 2", ref2 == f"emg-{eb}-r2-{CRUZ_ROJA}", ref2)
        tarea = admin.wait_for_task(caso_b, "Adjudicar Ofertas", retries=20)
        e.check("B12 Bonita: el caso está en 'Adjudicar Ofertas'", tarea is not None,
                [t["displayName"] for t in admin.get_human_tasks(caso_b)])
        r = e.post("operador.municipal", f"/emergencias/{eb}/adjudicar", {"cuits": [CRUZ_ROJA]})
        e.check("B13 El Municipio adjudica", r.status_code == 200, r.text)
        d = esperar(e, eb, lambda d: d["estado"] == "EN_EJECUCION", 90)
        e.check("B14 La emergencia pasa a EN_EJECUCION", d is not None, d and d["estado"])
        e.check("B15 Nacional: 3000 L de agua adjudicados", comprometido(nacional, CRUZ_ROJA, "AGUA_POTABLE") == 3000)

    print("\n== Limpieza: se liberan las reservas de la prueba (el cierre todavía no existe)")
    for ref in (f"emg-{ea}-r1-{CRUZ_ROJA}", f"emg-{eb}-r2-{CRUZ_ROJA}"):
        r = requests.post(f"{nacional}/adjudicaciones/{ref}/liberar", timeout=60)
        e.check(f"Liberar {ref}", r.status_code == 200, r.text)
    e.check("La API Nacional quedó como al empezar", {k: comprometido(nacional, *k) for k in previos} == previos)

    print(f"\n{e.ok}/{e.total} verificaciones OK")
    return 0 if e.ok == e.total else 1


if __name__ == "__main__":
    sys.exit(main())
