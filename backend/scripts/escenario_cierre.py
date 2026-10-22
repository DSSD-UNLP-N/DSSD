"""Escenario de la tercera parada: de la adjudicación al cierre, con las dos ONGs y Bonita real.

Pide 10 paramédicos; Cruz Roja ofrece 4 y Bomberos 2 (60 %). El Coordinador sigue con la cobertura parcial y el
Municipio adjudica a las dos. Después:

  1. el Coordinador empieza a monitorear (Bonita pasa a «Confirmar Finalizacion»);
  2. cada ONG marca su actividad como finalizada (con la última, Bonita pasa a «Validar Cierre»);
  3. el Coordinador valida el cierre bilateral y Bonita, con sus conectores, libera lo de cada ONG en la API Nacional
     (`POST /cierres/lote`) y le avisa a la app (evento CIERRE).

Esperado al final: emergencia RESUELTA, el inventario nacional como al empezar, un cierre por ONG, un aviso de cierre en
la campana de cada ONG y el caso de Bonita terminado.

Requisitos: Bonita con el proceso desplegado, incluidos los conectores de «Liberar Recursos y Notificar Cierre»
(`bonita/scripts/agregar_conector_cierre.py`); app en :8001; API Nacional en :8002 con el seed y nada comprometido.
Tarda unos 6 minutos.

    python scripts/escenario_cierre.py
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

from escenario_adjudicacion import BOMBEROS, CRUZ_ROJA, VENTANA_S, comprometido, esperar  # noqa: E402
from escenario_tope import Escenario, crear_y_publicar  # noqa: E402

from nacional_auth import nacional_get  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.integrations.bonita import BonitaClient  # noqa: E402


def sin_tareas(admin: BonitaClient, caso: int, segundos: int = 60) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if not admin.get_human_tasks(caso):
            return True
        time.sleep(1)
    return False


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
    claves = [(CRUZ_ROJA, "PARAMEDICO"), (BOMBEROS, "PARAMEDICO")]
    previos = {k: comprometido(nacional, *k) for k in claves}
    e.check("La API Nacional no tiene nada comprometido al empezar", not any(previos.values()), previos)
    fin = datetime.now().astimezone() + timedelta(seconds=VENTANA_S)
    emg, caso, lotes = crear_y_publicar(e, "Escenario de cierre", "ALTO", [("PARAMEDICO", 10, "PRINCIPAL")], fin)
    print(f"     emergencia #{emg} (caso {caso}) · vence {fin:%H:%M:%S}")
    e.esperar("Cruz Roja ofrece 4", e.ofrecer("ong.cruzroja", emg, (lotes["PARAMEDICO"], 4)), 201)
    e.esperar("Bomberos ofrece 2", e.ofrecer("ong.bomberos", emg, (lotes["PARAMEDICO"], 2)), 201)

    print(f"\n== Evaluación y adjudicación (la ventana vence {fin:%H:%M:%S})")
    d = esperar(e, emg, lambda d: d["evaluacion"] is not None, 200, desde=fin)
    e.check("Bonita evaluó: EN_EVALUACION con 60 %", d is not None and d["estado"] == "EN_EVALUACION", d and d["estado"])
    if d is None:
        print(f"\n{e.ok}/{e.total} verificaciones OK")
        return 1
    r = e.post("coordinador.regional", f"/emergencias/{emg}/decision", {"decision": "PARCIAL"})
    e.check("El Coordinador sigue con la cobertura parcial", r.status_code == 200, r.text)
    admin.wait_for_task(caso, "Adjudicar Ofertas", retries=20)
    r = e.post("operador.municipal", f"/emergencias/{emg}/adjudicar", {"cuits": [CRUZ_ROJA, BOMBEROS]})
    e.check("El Municipio adjudica a las dos ONGs", r.status_code == 200, r.text)
    d = esperar(e, emg, lambda d: d["estado"] == "EN_EJECUCION", 90)
    e.check("La emergencia pasa a EN_EJECUCION", d is not None, d and d["estado"])
    e.check("Nacional: 4 y 2 paramédicos comprometidos", tuple(comprometido(nacional, *k) for k in claves) == (4, 2))
    e.check("Bonita espera «Monitorear Ejecucion»", admin.wait_for_task(caso, "Monitorear Ejecucion", retries=20) is not None)

    print("\n== Ejecución")
    e.esperar("E1 Antes de monitorear, la ONG no puede finalizar → 409", e.post("ong.cruzroja", f"/emergencias/{emg}/finalizar", {}), 409)
    e.esperar("E2 La ONG no monitorea → 403", e.post("ong.cruzroja", f"/emergencias/{emg}/monitorear", {}), 403)
    e.esperar("E3 El Coordinador monitorea", e.post("coordinador.regional", f"/emergencias/{emg}/monitorear", {}), 200)
    e.check("E4 Bonita pasó a «Confirmar Finalizacion de Actividades»",
            admin.wait_for_task(caso, "Confirmar Finalizacion", retries=20) is not None,
            [t["displayName"] for t in admin.get_human_tasks(caso)])
    e.esperar("E5 Con una ONG pendiente no se valida el cierre → 409", e.post("coordinador.regional", f"/emergencias/{emg}/validar-cierre", {}), 409)
    e.esperar("E6 Bomberos marca su actividad finalizada", e.post("ong.bomberos", f"/emergencias/{emg}/finalizar", {}), 200)
    e.check("E7 Con Cruz Roja pendiente, Bonita sigue en «Confirmar Finalizacion»",
            admin.find_task(caso, "Confirmar Finalizacion") is not None)
    e.esperar("E8 Cruz Roja marca su actividad finalizada", e.post("ong.cruzroja", f"/emergencias/{emg}/finalizar", {}), 200)
    e.check("E9 Bonita pasó a «Validar Cierre Operativo Bilateral»",
            admin.wait_for_task(caso, "Validar Cierre", retries=20) is not None, [t["displayName"] for t in admin.get_human_tasks(caso)])
    d = e.get("coordinador.regional", f"/emergencias/{emg}").json()
    e.check("E10 El detalle dice que todas finalizaron", d["ejecucion"]["todas_finalizadas"] is True, d["ejecucion"])

    print("\n== Cierre")
    e.esperar("C1 El Municipio no valida el cierre → 403", e.post("operador.municipal", f"/emergencias/{emg}/validar-cierre", {}), 403)
    e.esperar("C2 El Coordinador valida el cierre bilateral", e.post("coordinador.regional", f"/emergencias/{emg}/validar-cierre", {}), 200)
    d = esperar(e, emg, lambda d: d["estado"] == "RESUELTA", 120)
    e.check("C3 Bonita liberó y avisó: la emergencia queda RESUELTA", d is not None, d and d["estado"])
    e.check("C4 Nacional: el inventario volvió a como estaba", {k: comprometido(nacional, *k) for k in claves} == previos,
            {k: comprometido(nacional, *k) for k in claves})
    for nombre, cuit in (("Cruz Roja", CRUZ_ROJA), ("Bomberos", BOMBEROS)):
        cierres = nacional_get(f"{nacional}/ongs/{cuit}/cierres", timeout=60).json()
        propios = [c for c in cierres if c["referencia"] == f"emg-{emg}-r1-{cuit}"]
        e.check(f"C5 Nacional: hay un cierre de {nombre} para esta emergencia", len(propios) == 1, cierres)
    e.check("C6 Bonita: el caso terminó, sin tareas pendientes", sin_tareas(admin, caso), [t["displayName"] for t in admin.get_human_tasks(caso)])
    for usuario in ("ong.cruzroja", "ong.bomberos"):
        avisos = e.get(usuario, "/notificaciones").json()
        e.check(f"C7 {usuario}: recibió el aviso del cierre",
                any(f"#{emg} se cerró" in a["texto"] for a in avisos), [a["texto"] for a in avisos][:3])

    print(f"\n{e.ok}/{e.total} verificaciones OK")
    return 0 if e.ok == e.total else 1


if __name__ == "__main__":
    sys.exit(main())
