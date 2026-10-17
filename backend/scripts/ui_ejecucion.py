"""Ejecución y cierre en la interfaz real, con Bonita real: monitoreo, actividad finalizada, cierre bilateral y avisos.

Parte de una emergencia ya adjudicada (EN_EJECUCION) cuyo caso de Bonita espera "Monitorear Ejecucion del
Despliegue", y la lleva hasta RESUELTA con tres perfiles: Coordinador, ONG y Municipio. En cada paso verifica lo que
se ve en pantalla y en qué tarea quedó el caso de Bonita (y con qué usuario la completó el motor).

Mientras el conector "Liberar Recursos y Notificar Cierre" no exista en Bonita, el aviso `CIERRE` no llega solo:
con --simular-cierre el script lo manda como lo mandaría el conector.

Requisitos: Bonita con el proceso desplegado, app en :8001 y front en :5173; Chrome o Chromium.

    python scripts/ui_ejecucion.py --emergencia 22 --caso 12001 --ong ong.cruzroja --simular-cierre
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import Page, sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import e2e_ui  # noqa: E402
from e2e_ui import PLAZO, Reporte, Ui, ejecutada_por, tarea_activa  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.integrations.bonita import BonitaClient  # noqa: E402

IMG = HERE.parents[1] / "entrega-3" / "img" / "parada-3"
e2e_ui.CAPTURAS = IMG


def esperar_tarea_activa(admin: BonitaClient, caso: int, prefijo: str, segundos: int = 40) -> str:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        activa = tarea_activa(admin, caso)
        if activa.startswith(prefijo):
            return activa
        time.sleep(1)
    return tarea_activa(admin, caso)


def sin_tareas(admin: BonitaClient, caso: int, segundos: int = 40) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if tarea_activa(admin, caso) == "(ninguna)":
            return True
        time.sleep(1)
    return False


def contador(page: Page) -> int:
    loc = page.get_by_test_id("campana-contador")
    return int(loc.inner_text()) if loc.count() else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="http://localhost:5173")
    ap.add_argument("--api", default="http://localhost:8001")
    ap.add_argument("--emergencia", type=int, required=True)
    ap.add_argument("--caso", type=int, required=True, help="caso de Bonita de esa emergencia")
    ap.add_argument("--ong", default="ong.cruzroja", help="representante de la ONG adjudicada")
    ap.add_argument("--simular-cierre", action="store_true", help="mandar el aviso CIERRE como el conector de Bonita")
    ap.add_argument("--cuit", default="30-54666544-5", help="CUIT de la ONG adjudicada (para el aviso simulado)")
    ap.add_argument("--visible", action="store_true", help="navegador visible")
    args = ap.parse_args()

    IMG.mkdir(parents=True, exist_ok=True)
    for vieja in IMG.glob("*.png"):
        vieja.unlink()
    cfg = get_settings()
    admin = BonitaClient(cfg.bonita_base_url, cfg.bonita_timeout_seconds)
    admin.login(cfg.bonita_username, cfg.bonita_password)
    r = Reporte()
    app, emg, caso = args.app, args.emergencia, args.caso

    r.fase("Preparación")
    r.check("El caso de Bonita espera «Monitorear Ejecucion»", tarea_activa(admin, caso).startswith("Monitorear"),
            tarea_activa(admin, caso))

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=not args.visible)
        except Exception:
            browser = pw.chromium.launch(headless=not args.visible)
        page: Page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        page.set_default_timeout(PLAZO)
        u = Ui(page, r)
        try:
            r.fase("1. Coordinador: ve la ejecución y empieza a monitorear")
            u.entrar(app, "coordinador.regional")
            u.abrir(app, emg)
            u.ve("Ejecución y cierre", "El detalle muestra «Ejecución y cierre»")
            r.check("Las ONGs aparecen «En ejecución»", page.get_by_test_id("ejecucion").get_by_text("En ejecución").count() >= 1)
            r.check("No hay botón de validar el cierre todavía", page.get_by_test_id("validar-cierre").count() == 0)
            u.foto("coordinador-antes-de-monitorear")
            page.get_by_test_id("monitorear").click()
            u.ve("Monitoreo iniciado", "Aparece el mensaje «Monitoreo iniciado»")
            u.foto("coordinador-monitoreando")
            r.check("Bonita avanzó a «Confirmar Finalizacion de Actividades»",
                    esperar_tarea_activa(admin, caso, "Confirmar Finalizacion").startswith("Confirmar Finalizacion"),
                    tarea_activa(admin, caso))
            r.check("«Monitorear» la completó coordinador.regional",
                    ejecutada_por(admin, caso, "Monitorear") == "coordinador.regional", ejecutada_por(admin, caso, "Monitorear"))
            r.check("Ya no se ofrece monitorear", page.get_by_test_id("monitorear").count() == 0)
            u.salir()

            r.fase("2. ONG: marca su actividad como finalizada")
            u.entrar(app, args.ong)
            u.abrir(app, emg)
            u.ve("Ejecución y cierre", "La ONG ve «Ejecución y cierre»")
            r.check("La ONG ve solo su propia fila", page.get_by_test_id("ejecucion").locator(".lote-row").count() == 1)
            r.check("La campana muestra avisos sin leer", contador(page) >= 1, contador(page))
            u.foto("ong-antes-de-finalizar")
            page.get_by_test_id("finalizar").click()
            u.ve("Marcaste tu actividad como finalizada", "Aparece «Marcaste tu actividad como finalizada»")
            u.foto("ong-finalizada")
            r.check("Bonita avanzó a «Validar Cierre Operativo Bilateral»",
                    esperar_tarea_activa(admin, caso, "Validar Cierre").startswith("Validar Cierre"), tarea_activa(admin, caso))
            r.check("«Confirmar Finalizacion» la completó la ONG de Bonita",
                    ejecutada_por(admin, caso, "Confirmar") == "ong.cruzroja", ejecutada_por(admin, caso, "Confirmar"))
            r.check("Ya no se ofrece finalizar de nuevo", page.get_by_test_id("finalizar").count() == 0)
            u.salir()

            r.fase("3. Coordinador: valida el cierre bilateral")
            u.entrar(app, "coordinador.regional")
            u.abrir(app, emg)
            u.ve("Todas las ONGs terminaron", "Con todas finalizadas se ofrece validar el cierre")
            u.foto("coordinador-valida-cierre")
            page.get_by_test_id("validar-cierre").click()
            u.ve("Cierre validado", "Aparece «Cierre validado»", timeout=15000)
            r.check("«Validar Cierre» la completó coordinador.regional",
                    ejecutada_por(admin, caso, "Validar Cierre") == "coordinador.regional",
                    ejecutada_por(admin, caso, "Validar Cierre"))
            r.check("El caso de Bonita ya no tiene tareas pendientes", sin_tareas(admin, caso), tarea_activa(admin, caso))

            if args.simular_cierre:
                r.fase("   (simulado) Bonita avisa el CIERRE como lo haría el conector")
                ev = requests.post(f"{args.api}/api/bonita/emergencias/{emg}/eventos", timeout=60,
                                   headers={"X-Api-Key": cfg.bonita_api_key},
                                   json={"tipo": "CIERRE", "cuits": [args.cuit]})
                r.check("La app acepta el evento CIERRE (204)", ev.status_code == 204, ev.status_code)

            page.reload()
            u.ve("Emergencia resuelta", "La emergencia queda «Resuelta»", timeout=30000)
            u.foto("coordinador-resuelta")
            u.salir()

            r.fase("4. ONG: el aviso del cierre llega a la campana")
            u.entrar(app, args.ong)
            page.get_by_test_id("campana-contador").wait_for(timeout=PLAZO)  # la campana carga sus avisos aparte
            antes = contador(page)
            page.get_by_test_id("campana").click()
            lista = page.get_by_test_id("campana-lista")
            lista.wait_for(timeout=PLAZO)
            r.check("La campana lista el aviso del cierre", lista.get_by_text(f"emergencia #{emg} se cerró").count() >= 1)
            u.foto("ong-campana")
            lista.get_by_text(f"emergencia #{emg} se cerró").first.click()
            page.wait_for_url(f"**/emergencias/{emg}", timeout=PLAZO)
            u.ve("Emergencia resuelta", "Al tocar el aviso abre la emergencia")
            page.wait_for_timeout(1500)
            r.check("El aviso se marcó como leído (el contador baja)", contador(page) == max(antes - 1, 0), (antes, contador(page)))
            u.foto("ong-resuelta")
            u.salir()

            r.fase("5. Municipio: ve la emergencia resuelta")
            u.entrar(app, "operador.municipal")
            u.abrir(app, emg)
            u.ve("Emergencia resuelta", "El Municipio ve «Emergencia resuelta»")
            u.foto("municipio-resuelta")
        finally:
            browser.close()
    return r.resumen()


if __name__ == "__main__":
    sys.exit(main())
