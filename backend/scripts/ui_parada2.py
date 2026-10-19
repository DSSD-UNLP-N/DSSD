"""Parada 2 en la interfaz real: decisión del Coordinador y adjudicación del Municipio, con Bonita real.

Recorre la SPA en un navegador con los cuatro perfiles y verifica, en cada paso, lo que se ve en pantalla,
lo que pasó en la API Nacional y en qué tarea quedó el caso de Bonita. Saca una captura de cada paso en
`entrega-3/img/parada-2/`.

  A) cobertura parcial: pide 10 paramédicos; Cruz Roja ofrece 4 y Bomberos 2 (60 %). El Coordinador sigue con
     la cobertura parcial y el Municipio adjudica solo a Cruz Roja.
  B) reformulación: pide 3000 raciones; Cruz Roja ofrece 2000 (66,7 %). El Coordinador reformula; en la
     segunda ronda Cruz Roja ofrece las 3000, la cobertura es completa y va directo a la adjudicación.

Requisitos: Bonita con el proceso desplegado, app en :8001, front en :5173 y API Nacional en :8002 con el seed y
nada comprometido; Chrome o Chromium. Tarda unos 15 minutos (dos ventanas de ofertas).

    python scripts/ui_parada2.py
    python scripts/ui_parada2.py --ventana 5      # minutos de la primera ventana (por defecto 5)
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from playwright.sync_api import Page, sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import e2e_ui  # noqa: E402
from e2e_ui import PLAZO, Reporte, Ui, dato, tarea_activa  # noqa: E402

from nacional_auth import nacional_get, nacional_post  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.integrations.bonita import BonitaClient  # noqa: E402

CRUZ_ROJA, BOMBEROS = "30-54666544-5", "30-68522415-9"
IMG = HERE.parents[1] / "entrega-3" / "img" / "parada-2"
e2e_ui.CAPTURAS = IMG


def comprometido(nacional: str, cuit: str, tipo: str) -> int:
    ficha = nacional_get(f"{nacional}/ongs/{cuit}", timeout=60).json()
    return next(i["cantidad_comprometida"] for i in ficha["inventario"] if i["tipo_recurso"] == tipo)


def registrar(u: Ui, app: str, gravedad: str, zona: str, descripcion: str, foto: str) -> tuple[int, str]:
    p = u.page
    p.goto(f"{app}/emergencias/nueva")
    p.get_by_role("heading", name="Registrar emergencia").wait_for(timeout=PLAZO)
    p.locator("select").nth(0).select_option("inundacion")
    p.locator("select").nth(1).select_option(gravedad)
    p.get_by_placeholder("Barrio, localidad o área").fill(zona)
    p.get_by_placeholder("Situación inicial, impacto y necesidades estimadas").fill(descripcion)
    u.foto(foto)
    p.get_by_role("button", name="Registrar emergencia").click()
    p.wait_for_url(re.compile(r"/emergencias/\d+$"), timeout=40000)
    u.ve(zona, f"Detalle con los datos cargados ({zona})")
    return int(p.url.rsplit("/", 1)[1]), dato(p, "Caso Bonita")


def agregar_lote(u: Ui, recurso: str, cantidad: str, nombre: str) -> None:
    u.page.locator("[name=tipo_recurso]").select_option(recurso)
    u.page.locator("[name=cantidad]").fill(cantidad)
    u.page.locator("[name=tipo]").select_option("PRINCIPAL")
    u.page.get_by_role("button", name="Agregar lote").click()
    u.ve(nombre, f"Lote «{nombre}» en la lista")


def publicar(u: Ui, fin: datetime) -> None:
    u.page.locator("[name=ventana_fin]").fill(fin.strftime("%Y-%m-%dT%H:%M"))
    u.page.get_by_role("button", name="Publicar a la red").click()
    u.ve("Convocatoria publicada", "Publicación aceptada", timeout=40000)
    u.ve("Convocatoria abierta", "Estado «Convocatoria abierta»")


def ofrecer(u: Ui, app: str, emergencia: int, cantidad: str, foto: str | None = None) -> None:
    u.abrir(app, emergencia)
    u.page.locator("[name^=lote_]").first.fill(cantidad)
    u.page.get_by_role("button", name="Enviar oferta").click()
    u.ve("versión 1", f"Oferta de {cantidad} enviada (versión 1)")
    if foto:
        u.foto(foto)


def esperar_evaluacion(u: Ui, app: str, emergencia: int, segundos: int) -> bool:
    """El Coordinador recarga el detalle hasta que aparece la cobertura que calculó Bonita."""
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        u.abrir(app, emergencia)
        if u.page.locator("[data-testid=cobertura-total]").count():
            return True
        time.sleep(8)
    return False


def esperar_estado(u: Ui, app: str, emergencia: int, etiqueta: str, segundos: int) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        u.abrir(app, emergencia)
        if u.page.locator(".badge", has_text=etiqueta).count():
            return True
        time.sleep(5)
    return False


def adjudicar(u: Ui, app: str, emergencia: int, cuit: str, foto_antes: str, foto_despues: str) -> None:
    u.abrir(app, emergencia)
    u.page.locator("[data-testid=adjudicacion]").wait_for(timeout=PLAZO)
    u.page.locator(f"[data-testid=elegir-{cuit}] input").check()
    u.foto(foto_antes)
    u.page.locator("[data-testid=adjudicar]").click()
    u.ve("Adjudicación enviada", "El Municipio envió la adjudicación")
    u.r.check("Bonita avisó y la emergencia pasó a «En ejecución»",
              esperar_estado(u, app, emergencia, "En ejecución", 90), u.page.url)
    u.foto(foto_despues)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="http://localhost:5173")
    ap.add_argument("--ventana", type=int, default=2, help="minutos hasta el cierre de la primera ventana")
    ap.add_argument("--visible", action="store_true", help="navegador visible")
    args = ap.parse_args()

    IMG.mkdir(parents=True, exist_ok=True)
    for vieja in IMG.glob("*.png"):
        vieja.unlink()
    cfg = get_settings()
    nacional = cfg.nacional_base_url.rstrip("/")
    admin = BonitaClient(cfg.bonita_base_url, cfg.bonita_timeout_seconds)
    admin.login(cfg.bonita_username, cfg.bonita_password)
    r = Reporte()
    app = args.app

    previos = {(c, t): comprometido(nacional, c, t) for c, t in
               [(CRUZ_ROJA, "PARAMEDICO"), (BOMBEROS, "PARAMEDICO"), (CRUZ_ROJA, "RACION_ALIMENTO")]}
    r.fase("Preparación")
    r.check("La API Nacional no tiene nada comprometido al empezar", not any(previos.values()), previos)

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=not args.visible)
        except Exception:
            browser = pw.chromium.launch(headless=not args.visible)
        page: Page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        page.set_default_timeout(PLAZO)
        u = Ui(page, r)
        ea = eb = 0
        try:
            r.fase("1. Municipio: registra las dos emergencias")
            u.entrar(app, "operador.municipal")
            ea, caso_a = registrar(u, app, "ALTO", "Parada 2 · caso A (parcial)",
                                   "Inundación: faltan paramédicos para los centros de evacuación.", "municipio-formulario-a")
            u.foto("municipio-detalle-a")
            eb, caso_b = registrar(u, app, "MEDIO", "Parada 2 · caso B (reformular)",
                                   "Inundación: faltan raciones de alimento para las familias evacuadas.", "municipio-formulario-b")
            print(f"     A = emergencia #{ea} (caso {caso_a}) · B = emergencia #{eb} (caso {caso_b})")
            u.salir()

            r.fase("2. Coordinador: lotes y publicación de las dos convocatorias")
            u.entrar(app, "coordinador.regional")
            fin = (datetime.now().astimezone() + timedelta(minutes=args.ventana)).replace(second=0, microsecond=0)
            u.abrir(app, ea)
            agregar_lote(u, "PARAMEDICO", "10", "Paramédico")
            u.foto("coordinador-lote-a")
            publicar(u, fin)
            u.foto("coordinador-publicada-a")
            u.abrir(app, eb)
            agregar_lote(u, "RACION_ALIMENTO", "3000", "Ración de alimento")
            publicar(u, fin)
            u.salir()
            print(f"     las dos ventanas vencen a las {fin:%H:%M}")

            r.fase("3. ONGs: ofertas parciales")
            u.entrar(app, "ong.cruzroja")
            ofrecer(u, app, ea, "4", "ong-cruzroja-oferta-a")
            ofrecer(u, app, eb, "2000")
            u.salir()
            u.entrar(app, "ong.bomberos")
            ofrecer(u, app, ea, "2", "ong-bomberos-oferta-a")
            u.salir()

            r.fase(f"4. Espera: la ventana vence a las {fin:%H:%M} y Bonita evalúa")
            u.entrar(app, "coordinador.regional")
            espera = max(0, int((fin - datetime.now().astimezone()).total_seconds())) + 240
            ok = esperar_evaluacion(u, app, ea, espera)
            r.check("A: Bonita evaluó y el Coordinador ve la cobertura", ok, u.page.url)
            if not ok:
                u.foto("error-sin-evaluacion-a")
                raise RuntimeError("la evaluación de A no llegó")
            cob = u.page.locator("[data-testid=cobertura-total]").inner_text()
            r.check("A: cobertura 60 %, no alcanza", cob.startswith("60") and "no alcanza" in cob, cob)
            for cuit, nombre in ((CRUZ_ROJA, "Cruz Roja"), (BOMBEROS, "Bomberos")):
                r.check(f"A: {nombre} figura como reservada",
                        "Reservada" in u.page.locator(f"[data-testid=evaluacion-ong-{cuit}]").inner_text())
            r.check("A: Nacional tiene 4 + 2 paramédicos reservados",
                    (comprometido(nacional, CRUZ_ROJA, "PARAMEDICO"), comprometido(nacional, BOMBEROS, "PARAMEDICO")) == (4, 2))
            r.check("A: el Coordinador ve los botones de decisión",
                    u.page.locator("[data-testid=decidir-parcial]").count() == 1
                    and u.page.locator("[data-testid=decidir-reformular]").count() == 1)
            u.foto("coordinador-evaluacion-a")

            r.fase("5. Caso A: el Coordinador sigue con la cobertura parcial")
            u.page.locator("[data-testid=decidir-parcial]").click()
            u.ve("Seguís con la cobertura parcial", "El Coordinador eligió la cobertura parcial")
            r.check("A: la emergencia pasó a «Adjudicación»", esperar_estado(u, app, ea, "Adjudicación", 30))
            r.check("A: Bonita pasó el caso a «Adjudicar Ofertas»", tarea_activa(admin, caso_a).startswith("Adjudicar Ofertas"),
                    tarea_activa(admin, caso_a))
            u.foto("coordinador-adjudicacion-a")

            r.fase("6. Caso B: el Coordinador reformula")
            r.check("B: Bonita evaluó la primera ronda", esperar_evaluacion(u, app, eb, 120))
            cob = u.page.locator("[data-testid=cobertura-total]").inner_text()
            r.check("B: cobertura 66,7 %, no alcanza", cob.startswith("66.7") and "no alcanza" in cob, cob)
            r.check("B: Nacional tiene 2000 raciones reservadas", comprometido(nacional, CRUZ_ROJA, "RACION_ALIMENTO") == 2000)
            u.foto("coordinador-evaluacion-b")
            u.page.locator("[data-testid=decidir-reformular]").click()
            u.ve("Convocatoria reformulada", "El Coordinador reformuló la convocatoria")
            u.abrir(app, eb)
            r.check("B: vuelve a «Registrada»", u.page.locator(".badge", has_text="Registrada").count() > 0)
            r.check("B: Nacional liberó la reserva", comprometido(nacional, CRUZ_ROJA, "RACION_ALIMENTO") == 0)
            r.check("B: Bonita volvió a «Revisar Informacion»", tarea_activa(admin, caso_b).startswith("Revisar Informacion"),
                    tarea_activa(admin, caso_b))
            u.foto("coordinador-reformulada-b")
            fin2 = (datetime.now().astimezone() + timedelta(minutes=2)).replace(second=0, microsecond=0)
            publicar(u, fin2)
            u.foto("coordinador-ronda-2-b")
            u.salir()
            u.entrar(app, "ong.cruzroja")
            u.abrir(app, eb)
            u.page.locator("[name^=lote_]").first.fill("3000")
            u.page.get_by_role("button", name="Enviar oferta").click()
            u.ve("versión", "Cruz Roja ofrece las 3000 raciones en la ronda 2")
            u.foto("ong-cruzroja-ronda-2-b")
            u.salir()
            print(f"     la ronda 2 vence a las {fin2:%H:%M}")

            r.fase("7. Caso A: el Municipio adjudica")
            u.entrar(app, "operador.municipal")
            adjudicar(u, app, ea, CRUZ_ROJA, "municipio-adjudicar-a", "municipio-en-ejecucion-a")
            r.check("A: Nacional: Cruz Roja conserva 4 y Bomberos queda en 0",
                    (comprometido(nacional, CRUZ_ROJA, "PARAMEDICO"), comprometido(nacional, BOMBEROS, "PARAMEDICO")) == (4, 0))
            r.check("A: Bonita espera en «Monitorear Ejecucion»", tarea_activa(admin, caso_a).startswith("Monitorear Ejecucion"),
                    tarea_activa(admin, caso_a))
            u.salir()

            r.fase("8. Caso A: lo que ven las ONGs")
            u.entrar(app, "ong.cruzroja")
            u.abrir(app, ea)
            r.check("Cruz Roja ve su oferta «adjudicada»", u.page.get_by_text("adjudicada", exact=True).count() > 0)
            u.foto("ong-cruzroja-adjudicada-a")
            u.salir()
            u.entrar(app, "ong.bomberos")
            u.abrir(app, ea)
            r.check("Bomberos ve su oferta «no adjudicada»", u.page.get_by_text("no adjudicada", exact=True).count() > 0)
            u.foto("ong-bomberos-no-adjudicada-a")
            u.salir()

            r.fase(f"9. Caso B, ronda 2: vence a las {fin2:%H:%M}; la cobertura es completa y va directo a adjudicación")
            u.entrar(app, "coordinador.regional")
            espera = max(0, int((fin2 - datetime.now().astimezone()).total_seconds())) + 240
            r.check("B: Bonita evaluó la ronda 2", esperar_evaluacion(u, app, eb, espera))
            cob = u.page.locator("[data-testid=cobertura-total]").inner_text()
            r.check("B: cobertura 100 %, lotes cubiertos", cob.startswith("100") and "lotes cubiertos" in cob, cob)
            r.check("B: no hay botones de decisión", u.page.locator("[data-testid=decidir-parcial]").count() == 0)
            r.check("B: la emergencia está en «Adjudicación»", esperar_estado(u, app, eb, "Adjudicación", 30))
            u.foto("coordinador-evaluacion-ronda-2-b")
            u.salir()

            r.fase("10. Caso B: el Municipio adjudica")
            u.entrar(app, "operador.municipal")
            adjudicar(u, app, eb, CRUZ_ROJA, "municipio-adjudicar-b", "municipio-en-ejecucion-b")
            r.check("B: Nacional: 3000 raciones adjudicadas a Cruz Roja", comprometido(nacional, CRUZ_ROJA, "RACION_ALIMENTO") == 3000)
            ref2 = nacional_post(f"{nacional}/adjudicaciones/emg-{eb}-r2-{CRUZ_ROJA}/confirmar", timeout=60).json()
            r.check("B: la reserva de la ronda 2 existe y está ADJUDICADA", ref2.get("estado") == "ADJUDICADA", ref2)
            u.salir()
        except Exception as exc:
            r.check("El recorrido llegó hasta el final", False, f"{type(exc).__name__}: {str(exc)[:300]}")
            u.foto("error")
        finally:
            browser.close()

    r.fase("Limpieza: se liberan las reservas de la prueba (el cierre todavía no existe)")
    for ea_, ronda, cuit in ((ea, 1, CRUZ_ROJA), (eb, 2, CRUZ_ROJA)):
        if ea_:
            nacional_post(f"{nacional}/adjudicaciones/emg-{ea_}-r{ronda}-{cuit}/liberar", timeout=60)
    r.check("La API Nacional quedó como al empezar", {k: comprometido(nacional, *k) for k in previos} == previos)
    return r.resumen()


if __name__ == "__main__":
    sys.exit(main())
