"""Escenario de la primera parada (M5/M6): al vencer la ventana, Bonita trae las ofertas de la app, la API Nacional las
valida y RESERVA el stock, la app guarda la evaluación y el caso sigue por el camino que marca la cobertura.

Crea dos emergencias con la misma ventana corta:
  A) cobertura parcial: pide 10 paramédicos; Cruz Roja ofrece 4 y Bomberos 2 (60 %)  → "Evaluar Cobertura" (Coordinador)
  B) cobertura completa: pide agua y raciones; Cruz Roja ofrece todo (100 %)            → "Adjudicar Ofertas" (Municipio)
y verifica el camino completo con Bonita real, la API Nacional local y la app. Al final libera las reservas que hizo.

Requisitos: Bonita con el proceso desplegado (con los conectores nuevos), app en :8001 y API Nacional en :8002 con el
seed y sin nada comprometido. Tarda unos 3 minutos.

    python scripts/escenario_evaluacion.py
"""
from __future__ import annotations

import os
import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from escenario_tope import Escenario, crear_y_publicar, retirar_previas  # noqa: E402

from nacional_auth import nacional_get, nacional_post  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.integrations.bonita import BonitaClient  # noqa: E402

CRUZ_ROJA, BOMBEROS = "30-54666544-5", "30-68522415-9"
VENTANA_S = int(os.environ.get("ESCENARIO_VENTANA_S", 60))  # alcanza para crear las dos emergencias y cargar las ofertas


def comprometido(nacional: str, cuit: str, tipo: str) -> int:
    ficha = nacional_get(f"{nacional}/ongs/{cuit}", timeout=60).json()
    return next(i["cantidad_comprometida"] for i in ficha["inventario"] if i["tipo_recurso"] == tipo)


def variable(admin: BonitaClient, caso: int, nombre: str):
    return admin.get_case_variables(caso).get(nombre)


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
               [(CRUZ_ROJA, "PARAMEDICO"), (BOMBEROS, "PARAMEDICO"), (CRUZ_ROJA, "AGUA_POTABLE"),
                (CRUZ_ROJA, "RACION_ALIMENTO")]}
    e.check("La API Nacional no tiene nada comprometido al empezar", not any(previos.values()), previos)
    fin = datetime.now().astimezone() + timedelta(seconds=VENTANA_S)
    ea, caso_a, la = crear_y_publicar(e, "Escenario A", "ALTO", [("PARAMEDICO", 10, "PRINCIPAL")], fin)
    eb, caso_b, lb = crear_y_publicar(e, "Escenario B", "MEDIO",
                                      [("AGUA_POTABLE", 2000, "PRINCIPAL"), ("RACION_ALIMENTO", 1000, "APOYO")], fin)
    print(f"     A=#{ea} (caso {caso_a}) · B=#{eb} (caso {caso_b}) · vencen {fin:%H:%M:%S}")
    print(f"     limpieza: {retirar_previas(e, {ea, eb})} ofertas de corridas anteriores retiradas")

    e.esperar("A1 Cruz Roja ofrece 4 paramédicos", e.ofrecer("ong.cruzroja", ea, (la["PARAMEDICO"], 4)), 201)
    e.esperar("A2 Bomberos ofrece 2 paramédicos", e.ofrecer("ong.bomberos", ea, (la["PARAMEDICO"], 2)), 201)
    e.esperar("B1 Cruz Roja ofrece 2000 L de agua y 1000 raciones",
              e.ofrecer("ong.cruzroja", eb, (lb["AGUA_POTABLE"], 2000), (lb["RACION_ALIMENTO"], 1000)), 201)
    e.check("Antes de vencer, la evaluación todavía no existe",
            e.get("coordinador.regional", f"/emergencias/{ea}").json()["evaluacion"] is None)

    print(f"\n== Esperando que venza la ventana ({fin:%H:%M:%S}) y que Bonita evalúe, sin tocar nada")
    limite = fin + timedelta(seconds=180)
    evaluadas: dict[int, dict] = {}
    time.sleep(max(0.0, (fin - datetime.now().astimezone()).total_seconds()))  # antes del cierre no hay nada que ver
    while datetime.now().astimezone() < limite and len(evaluadas) < 2:
        time.sleep(1.5)
        for emergencia in (ea, eb):
            try:
                d = e.get("coordinador.regional", f"/emergencias/{emergencia}").json()
            except requests.ConnectionError:  # el servidor cerró la conexión inactiva: se reintenta en la vuelta siguiente
                continue
            if d["evaluacion"] is not None:
                evaluadas[emergencia] = d
    e.check("La app recibió la evaluación de A y de B (la mandó Bonita)", len(evaluadas) == 2, sorted(evaluadas))
    if len(evaluadas) < 2:
        print("     (Bonita no evaluó a tiempo: revisá el caso en el portal y bonita.log)")
        print(f"\n{e.ok}/{e.total} verificaciones OK")
        return 1

    print("\n== A: cobertura parcial")
    a = evaluadas[ea]
    ev = a["evaluacion"]
    e.check("A estado EN_EVALUACION", a["estado"] == "EN_EVALUACION", a["estado"])
    e.check("A cobertura 60 %, incompleta", (ev["porcentaje_cobertura"], ev["cobertura_completa"]) == (60.0, False), ev)
    e.check("A reservado 6 de 10 en el lote", (ev["lotes"][0]["reservado"], ev["lotes"][0]["pedido"]) == (6, 10), ev["lotes"])
    e.check("A las dos ONGs vienen RESERVADA, con su referencia",
            sorted((o["cuit"], o["estado"], o["referencia"]) for o in ev["ongs"]) == sorted([
                (CRUZ_ROJA, "RESERVADA", f"emg-{ea}-r1-{CRUZ_ROJA}"), (BOMBEROS, "RESERVADA", f"emg-{ea}-r1-{BOMBEROS}")]),
            ev["ongs"])
    e.check("A la ONG no ve la evaluación", e.get("ong.cruzroja", f"/emergencias/{ea}").json()["evaluacion"] is None)
    e.check("A Nacional: Cruz Roja 4 y Bomberos 2 paramédicos comprometidos",
            (comprometido(nacional, CRUZ_ROJA, "PARAMEDICO"), comprometido(nacional, BOMBEROS, "PARAMEDICO")) == (4, 2))
    e.check("A Bonita: coberturaCompleta = false", variable(admin, caso_a, "coberturaCompleta") in (False, "false"),
            variable(admin, caso_a, "coberturaCompleta"))
    e.check("A Bonita: porcentajeCobertura = 60", float(variable(admin, caso_a, "porcentajeCobertura") or -1) == 60.0,
            variable(admin, caso_a, "porcentajeCobertura"))
    tarea = admin.wait_for_task(caso_a, "Evaluar Cobertura", retries=20)
    e.check("A Bonita: el caso espera al Coordinador en 'Evaluar Cobertura…'", tarea is not None,
            [t["displayName"] for t in admin.get_human_tasks(caso_a)])

    print("\n== B: cobertura completa")
    b = evaluadas[eb]
    ev = b["evaluacion"]
    e.check("B cobertura 100 %, completa", (ev["porcentaje_cobertura"], ev["cobertura_completa"]) == (100.0, True), ev)
    e.check("B Nacional: 2000 L de agua y 1000 raciones comprometidos",
            (comprometido(nacional, CRUZ_ROJA, "AGUA_POTABLE"), comprometido(nacional, CRUZ_ROJA, "RACION_ALIMENTO"))
            == (2000, 1000))
    e.check("B Bonita: coberturaCompleta = true", variable(admin, caso_b, "coberturaCompleta") in (True, "true"),
            variable(admin, caso_b, "coberturaCompleta"))
    tarea = admin.wait_for_task(caso_b, "Adjudicar Ofertas", retries=20)
    e.check("B Bonita: va directo a 'Adjudicar Ofertas' (Municipio), sin pasar por el Coordinador", tarea is not None,
            [t["displayName"] for t in admin.get_human_tasks(caso_b)])

    print("\n== La reserva bloquea el stock para otras emergencias")
    ec, _, lc = crear_y_publicar(e, "Escenario C", "ALTO", [("PARAMEDICO", 5, "PRINCIPAL")],
                                 datetime.now().astimezone() + timedelta(hours=2))
    e.esperar("C1 Cruz Roja ya no tiene paramédicos disponibles (los reservó A) → 400",
              e.ofrecer("ong.cruzroja", ec, (lc["PARAMEDICO"], 1)), 400, "tenés 0 disponibles")
    e.esperar("C2 Bomberos sí tiene 4 disponibles (reservó 2 de 6) → 201",
              e.ofrecer("ong.bomberos", ec, (lc["PARAMEDICO"], 4)), 201)
    e.esperar("C3 …pero no 5 → 400", e.ofrecer("ong.bomberos", ec, (lc["PARAMEDICO"], 5)), 400, "tenés 4 disponibles")
    e.ofrecer("ong.bomberos", ec)  # retira la oferta de la prueba

    print("\n== Limpieza: se liberan las reservas de la prueba")
    for emergencia in (ea, eb):
        for o in evaluadas[emergencia]["evaluacion"]["ongs"]:
            r = nacional_post(f"{nacional}/adjudicaciones/{o['referencia']}/liberar", timeout=60)
            e.check(f"Liberar {o['referencia']}", r.status_code == 200 and r.json()["estado"] == "LIBERADA", r.text)
    e.check("La API Nacional quedó como al empezar",
            {k: comprometido(nacional, *k) for k in previos} == previos)

    print(f"\n{e.ok}/{e.total} verificaciones OK")
    return 0 if e.ok == e.total else 1


if __name__ == "__main__":
    sys.exit(main())
