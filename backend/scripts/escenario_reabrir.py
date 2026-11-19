"""Escenario del camino alternativo REABRIR (pauta de la cátedra): misma convocatoria, mismos lotes, ventana nueva.

Pide 10 paramédicos; en la ronda 1 solo Cruz Roja ofrece 4 (40 %). Al vencer, Bonita evalúa y reserva; el Coordinador
elige REABRIR con un cierre nuevo. Esperado:
  - Bonita pasa por «Liberar Reservas de la Ronda» y libera la reserva r1 en la API Nacional (la app no la llama);
  - la app sube a la ronda 2, conserva el lote y la oferta de Cruz Roja (no se retira) y publica sola: CONVOCATORIA;
  - Bonita salta «Revisar Informacion» y queda otra vez en la tarea ancla con la ventana nueva;
  - Bomberos suma 6 en la ronda 2: la evaluación cubre 10/10 (100 %) con referencias r2 y va directo a «Adjudicar Ofertas».
Al final libera las reservas de la ronda 2.

Requisitos: Bonita con `entrega42_local.bos` (o el de nube) que tenga «Liberar Reservas de la Ronda»; app en :8001; API
Nacional con el seed y nada comprometido. Tarda unos 4 minutos.

    python scripts/escenario_reabrir.py
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta

from comun import (BOMBEROS, CRUZ_ROJA, VENTANA_S, Escenario, admin_bonita, comprometido, crear_y_publicar, esperar,
                   esperar_detalle, retirar_ofertas_abiertas, tareas)
from nacional_auth import nacional_post
from app.core.config import get_settings

RONDA2_S = VENTANA_S  # Bomberos ofrece una sola vez: alcanza con la misma ventana


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="http://localhost:8001")
    args = ap.parse_args()
    e = Escenario(args.app)
    nacional = get_settings().nacional_base_url.rstrip("/")
    admin = admin_bonita()

    print("== Preparación")
    previos = {c: comprometido(nacional, c, "PARAMEDICO") for c in (CRUZ_ROJA, BOMBEROS)}
    e.check("La API Nacional no tiene paramédicos comprometidos al empezar", not any(previos.values()), previos)
    fin1 = datetime.now().astimezone() + timedelta(seconds=VENTANA_S)
    emg, caso, lotes = crear_y_publicar(e, "Escenario reabrir", "ALTO", [("PARAMEDICO", 10, "PRINCIPAL")], fin1)
    lote = lotes["PARAMEDICO"]
    print(f"     #{emg} (caso {caso}) · la ronda 1 vence {fin1:%H:%M:%S}")
    print(f"     limpieza: {retirar_ofertas_abiertas(e.app, lambda em: em['id'] == emg)} ofertas de corridas anteriores retiradas")
    e.esperar("R1 Cruz Roja ofrece 4 paramédicos", e.ofrecer("ong.cruzroja", emg, (lote, 4)), 201)

    print("\n== Ronda 1: vence y Bonita evalúa")
    d = esperar_detalle(e, emg, lambda d: d["evaluacion"] is not None, 200, desde=fin1)
    e.check("R2 Cobertura 40 %, el caso espera al Coordinador", d is not None and d["estado"] == "EN_EVALUACION"
            and d["evaluacion"]["porcentaje_cobertura"] == 40.0, d and (d["estado"], d["evaluacion"]))
    if d is None:
        return e.terminar()
    r1 = f"emg-{emg}-r1-{CRUZ_ROJA}"
    e.check("R3 Nacional: 4 paramédicos de Cruz Roja reservados (r1)", comprometido(nacional, CRUZ_ROJA, "PARAMEDICO") == 4)
    e.check("R4 Bonita: el caso está en «Evaluar Cobertura»", admin.wait_for_task(caso, "Evaluar Cobertura", retries=20) is not None,
            tareas(admin, caso))

    print("\n== El Coordinador reabre la convocatoria")
    e.esperar("R5 REABRIR sin cierre nuevo → 422",
              e.post("coordinador.regional", f"/emergencias/{emg}/decision", {"decision": "REABRIR"}), 422)
    fin2 = datetime.now().astimezone() + timedelta(seconds=RONDA2_S)
    r = e.post("coordinador.regional", f"/emergencias/{emg}/decision",
               {"decision": "REABRIR", "ventana_fin": fin2.isoformat(timespec="seconds")})
    e.check("R6 REABRIR → CONVOCATORIA abierta otra vez, sin evaluación", r.status_code == 200
            and r.json()["estado"] == "CONVOCATORIA" and r.json()["evaluacion"] is None, r.text[:300])
    e.check("R7 Nacional: Bonita liberó la reserva r1 (servicio «Liberar Reservas de la Ronda»)",
            bool(esperar(lambda: comprometido(nacional, CRUZ_ROJA, "PARAMEDICO") == 0, 60)),
            comprometido(nacional, CRUZ_ROJA, "PARAMEDICO"))
    det = e.get("coordinador.regional", f"/emergencias/{emg}").json()
    e.check("R8 Mismo lote, misma cantidad", [(l["id"], l["cantidad"]) for l in det["lotes"]] == [(lote, 10)], det["lotes"])
    o = e.get("coordinador.regional", f"/emergencias/{emg}/ofertas").json()
    e.check("R9 La oferta de Cruz Roja sigue vigente (no se retira al reabrir)",
            len(o) == 1 and o[0]["retirada"] is False and o[0]["version_actual"] == 1, o)
    e.check("R10 Bonita: el caso volvió a la tarea ancla «Cargar Ofertas de Ayuda» (saltó «Revisar»)",
            admin.wait_for_task(caso, "Cargar Ofertas", retries=20) is not None and admin.find_task(caso, "Revisar") is None,
            tareas(admin, caso))
    e.check("R11 Bonita: ventanaOfertasISO es el cierre nuevo",
            admin.get_case_variables(caso).get("ventanaOfertasISO") == fin2.isoformat(timespec="seconds"),
            admin.get_case_variables(caso).get("ventanaOfertasISO"))

    print(f"\n== Ronda 2: Bomberos suma 6 (vence {fin2:%H:%M:%S})")
    e.esperar("R12 Bomberos ofrece 6 paramédicos", e.ofrecer("ong.bomberos", emg, (lote, 6)), 201)
    d = esperar_detalle(e, emg, lambda d: d["evaluacion"] is not None and d["evaluacion"]["ronda"] == 2, 240, desde=fin2)
    e.check("R13 La ronda 2 cubre 100 % y va directo a ADJUDICACION", d is not None and d["estado"] == "ADJUDICACION"
            and d["evaluacion"]["cobertura_completa"] is True, d and (d["estado"], d["evaluacion"]))
    if d is not None:
        refs = sorted(o["referencia"] for o in d["evaluacion"]["ongs"])
        e.check("R14 Las reservas nuevas llevan la ronda 2", refs == sorted([f"emg-{emg}-r2-{BOMBEROS}", f"emg-{emg}-r2-{CRUZ_ROJA}"]),
                refs)
        e.check("R15 Nacional: 4 + 6 reservados en la ronda 2",
                (comprometido(nacional, CRUZ_ROJA, "PARAMEDICO"), comprometido(nacional, BOMBEROS, "PARAMEDICO")) == (4, 6))
        e.check("R16 Bonita: el caso está en «Adjudicar Ofertas»",
                admin.wait_for_task(caso, "Adjudicar Ofertas", retries=20) is not None, tareas(admin, caso))
        e.check("R17 La reserva r1 quedó LIBERADA en la Nacional",
                nacional_post(f"{nacional}/adjudicaciones/{r1}/liberar", timeout=60).json().get("estado") == "LIBERADA")

        print("\n== Limpieza: se liberan las reservas de la ronda 2")
        for ref in refs:
            r = nacional_post(f"{nacional}/adjudicaciones/{ref}/liberar", timeout=60)
            e.check(f"Liberar {ref}", r.status_code == 200, r.text)
    e.check("La API Nacional quedó como al empezar", {c: comprometido(nacional, c, "PARAMEDICO") for c in previos} == previos)
    return e.terminar()


if __name__ == "__main__":
    sys.exit(main())
