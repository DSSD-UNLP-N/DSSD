"""Camino alternativo REABRIR en la interfaz real, con Bonita real: misma convocatoria, mismos lotes, ventana nueva.

Pide 10 paramédicos; en la ronda 1 solo Cruz Roja ofrece 4 (40 %). El Coordinador reabre con un cierre nuevo: Bonita
libera la reserva de la ronda 1 («Liberar Reservas de la Ronda») y vuelve a la tarea ancla sin pasar por «Revisar». La
oferta de Cruz Roja sigue vigente; Bomberos suma 6, la ronda 2 cubre el 100 % y va directo a «Adjudicar Ofertas». El
Municipio adjudica a las dos. Verifica en cada paso la pantalla, la tarea de Bonita y lo reservado en la API Nacional.
Capturas en `entrega-5/img/reabrir/`. Al final libera lo adjudicado (el cierre lo recorre `ui_parada3.py`).

Usa los paramédicos de las dos ONGs: no correr a la vez que ui_parada3.py ni que el caso A de ui_parada2.py.

Requisitos: Bonita con el proceso que tiene «Liberar Reservas de la Ronda», app en :8001, front en :5173, API Nacional
con el seed (o el de demo) y sin paramédicos comprometidos; Chrome o Chromium. Tarda unos 4 minutos.

    python scripts/ui_reabrir.py
    python scripts/ui_reabrir.py --visible --ventana 1.5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from comun import BOMBEROS, CRUZ_ROJA, admin_bonita, comprometido, esperar, tarea_activa
import ui_comun
from ui_comun import (PLAZO, Reporte, Ui, agregar_lote, cierre_de_ventana, ejecutada_por, esperar_estado,
                      esperar_evaluacion, esperar_hasta, ofrecer, publicar, registrar)
from nacional_auth import nacional_post
from app.core.config import get_settings

HERE = Path(__file__).resolve().parent
IMG = HERE.parents[1] / "entrega-5" / "img" / "reabrir"
ui_comun.CAPTURAS = IMG


def paramedicos(nacional: str) -> tuple[int, int]:
    return comprometido(nacional, CRUZ_ROJA, "PARAMEDICO"), comprometido(nacional, BOMBEROS, "PARAMEDICO")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="http://localhost:5173")
    ap.add_argument("--ventana", type=float, default=0.9, help="minutos de margen para la oferta de la ronda 1")
    ap.add_argument("--visible", action="store_true", help="navegador visible")
    ap.add_argument("--sin-capturas", action="store_true", help="no guardar las fotos de cada paso")
    args = ap.parse_args()

    ui_comun.SIN_CAPTURAS = args.sin_capturas
    if not args.sin_capturas:
        IMG.mkdir(parents=True, exist_ok=True)
        for vieja in IMG.glob("*.png"):
            vieja.unlink()
    nacional = get_settings().nacional_base_url.rstrip("/")
    admin = admin_bonita()
    r = Reporte()
    app = args.app
    emg = 0

    r.fase("Preparación")
    r.check("La API Nacional no tiene paramédicos comprometidos", paramedicos(nacional) == (0, 0), paramedicos(nacional))

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=not args.visible)
        except Exception:
            browser = pw.chromium.launch(headless=not args.visible)
        page: Page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        page.set_default_timeout(PLAZO)
        u = Ui(page, r)
        try:
            r.fase("1. Municipio: registra la emergencia")
            u.entrar(app, "operador.municipal")
            emg, caso = registrar(u, app, "ALTO", "Reabrir · Barrio Ribera",
                                  "Inundación: faltan paramédicos para los centros de evacuación.", "municipio-formulario")
            print(f"     emergencia #{emg} (caso {caso})")

            r.fase("2. Coordinador: lote de 10 paramédicos y publicación")
            u.entrar(app, "coordinador.regional")
            u.abrir(app, emg)
            agregar_lote(u, "PARAMEDICO", "10", "Paramédico")
            fin1 = cierre_de_ventana(args.ventana * 60)
            publicar(u, fin1)
            u.foto("coordinador-publicada")
            print(f"     la ronda 1 vence a las {fin1:%H:%M}")

            r.fase("3. Ronda 1: solo Cruz Roja ofrece 4")
            u.entrar(app, "ong.cruzroja")
            ofrecer(u, app, emg, "4", "ong-cruzroja-oferta")

            r.fase(f"4. Vence la ronda 1 ({fin1:%H:%M}): Bonita evalúa y la cobertura no alcanza")
            u.entrar(app, "coordinador.regional")
            esperar_hasta(fin1)
            ok = esperar_evaluacion(u, app, emg, 240)
            r.check("Bonita evaluó y el Coordinador ve la cobertura", ok, u.page.url)
            if not ok:
                raise RuntimeError("la evaluación de la ronda 1 no llegó")
            cob = u.page.locator("[data-testid=cobertura-total]").inner_text()
            r.check("Cobertura 40 %, no alcanza", cob.startswith("40") and "no alcanza" in cob, cob)
            r.check("Nacional: 4 paramédicos de Cruz Roja reservados (ronda 1)", paramedicos(nacional) == (4, 0),
                    paramedicos(nacional))
            r.check("Bonita: el caso espera en «Evaluar Cobertura»", tarea_activa(admin, caso).startswith("Evaluar Cobertura"),
                    tarea_activa(admin, caso))
            r.check("El Coordinador ve las tres decisiones",
                    all(u.page.locator(f"[data-testid=decidir-{d}]").count() == 1 for d in ("parcial", "reformular", "reabrir")))
            u.foto("coordinador-evaluacion-ronda-1")

            r.fase("5. El Coordinador reabre la convocatoria con un cierre nuevo")
            fin2 = cierre_de_ventana(45)
            u.page.locator("[name=ventana_reabrir]").fill(fin2.strftime("%Y-%m-%dT%H:%M"))
            u.foto("coordinador-reabre")
            u.page.locator("[data-testid=decidir-reabrir]").click()
            u.ve("Convocatoria reabierta", "La app confirma la reapertura", timeout=40000)
            r.check("La emergencia vuelve a «Convocatoria abierta»", esperar_estado(u, app, emg, "Convocatoria abierta", 30))
            r.check("Nacional: Bonita liberó la reserva de la ronda 1",
                    bool(esperar(lambda: paramedicos(nacional) == (0, 0), 60)), paramedicos(nacional))
            r.check("Bonita: el caso volvió a la tarea ancla «Cargar Ofertas» (sin pasar por «Revisar»)",
                    bool(esperar(lambda: tarea_activa(admin, caso).startswith("Cargar Ofertas"), 30)), tarea_activa(admin, caso))
            r.check("Bonita: «Evaluar Cobertura» la completó coordinador.regional",
                    ejecutada_por(admin, caso, "Evaluar") == "coordinador.regional", ejecutada_por(admin, caso, "Evaluar"))
            u.ve("Paramédico", "El lote sigue igual (10 paramédicos)")
            u.foto("coordinador-reabierta")
            print(f"     la ronda 2 vence a las {fin2:%H:%M}")

            r.fase("6. Ronda 2: la oferta de Cruz Roja sigue; Bomberos suma 6")
            u.entrar(app, "ong.cruzroja")
            u.abrir(app, emg)
            u.ve("versión 1", "Cruz Roja ve su oferta de la ronda 1 vigente")
            u.foto("ong-cruzroja-oferta-vigente")
            u.entrar(app, "ong.bomberos")
            ofrecer(u, app, emg, "6", "ong-bomberos-oferta")

            r.fase(f"7. Vence la ronda 2 ({fin2:%H:%M}): cobertura completa, directo a adjudicar")
            u.entrar(app, "coordinador.regional")
            esperar_hasta(fin2)
            r.check("Bonita evaluó la ronda 2", esperar_evaluacion(u, app, emg, 240))
            cob = u.page.locator("[data-testid=cobertura-total]").inner_text()
            r.check("Cobertura 100 %, lotes cubiertos", cob.startswith("100") and "lotes cubiertos" in cob, cob)
            r.check("No hay botones de decisión", u.page.locator("[data-testid=decidir-parcial]").count() == 0)
            r.check("La emergencia está en «Adjudicación»", esperar_estado(u, app, emg, "Adjudicación", 30))
            r.check("Nacional: 4 + 6 paramédicos reservados (ronda 2)", paramedicos(nacional) == (4, 6), paramedicos(nacional))
            r.check("Bonita: el caso está en «Adjudicar Ofertas»", tarea_activa(admin, caso).startswith("Adjudicar Ofertas"),
                    tarea_activa(admin, caso))
            u.foto("coordinador-evaluacion-ronda-2")

            r.fase("8. El Municipio adjudica a las dos ONGs")
            u.entrar(app, "operador.municipal")
            u.abrir(app, emg)
            u.page.locator("[data-testid=adjudicacion]").wait_for(timeout=PLAZO)
            for cuit in (CRUZ_ROJA, BOMBEROS):
                u.page.locator(f"[data-testid=elegir-{cuit}] input").check()
            u.foto("municipio-adjudicar")
            u.page.locator("[data-testid=adjudicar]").click()
            u.ve("Adjudicación enviada", "El Municipio envió la adjudicación")
            r.check("La emergencia pasó a «En ejecución»", esperar_estado(u, app, emg, "En ejecución", 90))
            r.check("Nacional: 4 + 6 comprometidos", paramedicos(nacional) == (4, 6), paramedicos(nacional))
            r.check("Bonita espera en «Monitorear Ejecucion»", tarea_activa(admin, caso).startswith("Monitorear Ejecucion"),
                    tarea_activa(admin, caso))
            u.foto("municipio-en-ejecucion")
        except Exception as exc:
            r.check("El recorrido llegó hasta el final", False, f"{type(exc).__name__}: {str(exc)[:300]}")
            u.foto("error")
        finally:
            browser.close()

    r.fase("Limpieza: se libera lo de la ronda 2 (el cierre lo recorre ui_parada3.py)")
    if emg:
        for cuit in (CRUZ_ROJA, BOMBEROS):
            nacional_post(f"{nacional}/adjudicaciones/emg-{emg}-r2-{cuit}/liberar", timeout=60)
    r.check("La API Nacional quedó como al empezar", paramedicos(nacional) == (0, 0), paramedicos(nacional))
    return r.resumen()


if __name__ == "__main__":
    sys.exit(main())
