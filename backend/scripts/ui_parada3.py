"""Parada 3 completa en la interfaz real: del alta de la emergencia al cierre bilateral, con Bonita real.

Una sola emergencia, los cuatro perfiles y dos ONGs. En cada paso verifica lo que se ve en pantalla, lo que pasó en la API
Nacional y en qué tarea quedó el caso de Bonita (y con qué usuario la completó el motor). Saca una captura de cada paso en
`entrega-3/img/parada-3/`.

  1. Municipio registra la emergencia (pide 10 paramédicos).
  2. Coordinador carga el lote y publica la convocatoria.
  3. Cruz Roja ofrece 4 y Bomberos 2 (cobertura 60 %).
  4. Vence la ventana, Bonita evalúa y reserva el stock; el Coordinador sigue con la cobertura parcial.
  5. El Municipio adjudica a las dos ONGs; la emergencia pasa a «En ejecución».
  6. El Coordinador monitorea; cada ONG marca su actividad como finalizada (Bonita avanza recién con la última).
  7. El Coordinador valida el cierre; Bonita cierra en la API Nacional, avisa a la app y la emergencia queda RESUELTA.
  8. Las ONGs reciben el aviso en la campana y el Municipio ve la emergencia resuelta.

El cierre libera lo reservado en la API Nacional (4 y 2 paramédicos): el stock queda como estaba. Contra la nube, la emergencia
no puede tener un número ya cerrado en Render (ver docs/instalacion-nube.md).

Requisitos: Bonita con el `.bos` de JWT desplegado, app en :8001, front en :5173 y API Nacional en :8002 con el seed y nada
comprometido de paramédicos; Chrome o Chromium. Tarda unos 2 a 3 minutos. Puede correr a la vez que e2e_ui.py y
ui_parada2.py (usan otros recursos): ver correr_ui.py.

    python scripts/ui_parada3.py
    python scripts/ui_parada3.py --ventana 1      # minutos de margen para cargar las ofertas antes del cierre (por defecto 0.5)
    python scripts/ui_parada3.py --sin-capturas
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import e2e_ui  # noqa: E402
from e2e_ui import PLAZO, Reporte, Ui, cierre_de_ventana, ejecutada_por, esperar_hasta, tarea_activa  # noqa: E402

from nacional_auth import nacional_get  # noqa: E402
from ui_ejecucion import esperar_resuelta, esperar_tarea_activa, sin_tareas  # noqa: E402
from ui_parada2 import (  # noqa: E402
    BOMBEROS, CRUZ_ROJA, agregar_lote, comprometido, esperar_estado, esperar_evaluacion, ofrecer, publicar, registrar,
)
from app.core.config import get_settings  # noqa: E402
from app.integrations.bonita import BonitaClient  # noqa: E402

IMG = HERE.parents[1] / "entrega-3" / "img" / "parada-3"
e2e_ui.CAPTURAS = IMG
ONGS = (("ong.cruzroja", CRUZ_ROJA, "Cruz Roja"), ("ong.bomberos", BOMBEROS, "Bomberos"))


def cierres(nacional: str, cuit: str, referencia: str) -> int:
    lista = nacional_get(f"{nacional}/ongs/{cuit}/cierres", timeout=60).json()
    return sum(1 for c in lista if c["referencia"] == referencia)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="http://localhost:5173")
    ap.add_argument("--api", default="http://localhost:8001")
    ap.add_argument("--ventana", type=float, default=0.5, help="minutos de margen para cargar las ofertas antes del cierre")
    ap.add_argument("--visible", action="store_true", help="navegador visible")
    ap.add_argument("--sin-capturas", action="store_true", help="no guardar las fotos de cada paso")
    args = ap.parse_args()

    e2e_ui.SIN_CAPTURAS = args.sin_capturas
    if not args.sin_capturas:
        IMG.mkdir(parents=True, exist_ok=True)
        for vieja in IMG.glob("*.png"):
            vieja.unlink()
    cfg = get_settings()
    nacional = cfg.nacional_base_url.rstrip("/")
    admin = BonitaClient(cfg.bonita_base_url, cfg.bonita_timeout_seconds)
    admin.login(cfg.bonita_username, cfg.bonita_password)
    r = Reporte()
    app = args.app

    previos = {(c, "PARAMEDICO"): comprometido(nacional, c, "PARAMEDICO") for c in (CRUZ_ROJA, BOMBEROS)}
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
        emg = 0
        try:
            r.fase("1. Municipio: registra la emergencia")
            u.entrar(app, "operador.municipal")
            emg, caso = registrar(u, app, "ALTO", "Parada 3 · recorrido completo",
                                  "Inundación: faltan paramédicos para los centros de evacuación.", "municipio-formulario")
            u.foto("municipio-detalle")
            print(f"     emergencia #{emg} (caso {caso})")
            u.salir()

            r.fase("2. Coordinador: lote y publicación de la convocatoria")
            u.entrar(app, "coordinador.regional")
            fin = cierre_de_ventana(args.ventana * 60)
            u.abrir(app, emg)
            agregar_lote(u, "PARAMEDICO", "10", "Paramédico")
            u.foto("coordinador-lote")
            publicar(u, fin)
            u.foto("coordinador-publicada")
            u.salir()

            r.fase("3. ONGs: Cruz Roja ofrece 4 y Bomberos 2")
            u.entrar(app, "ong.cruzroja")
            ofrecer(u, app, emg, "4", "ong-cruzroja-oferta")
            u.salir()
            u.entrar(app, "ong.bomberos")
            ofrecer(u, app, emg, "2", "ong-bomberos-oferta")
            u.salir()

            r.fase(f"4. Espera: la ventana vence a las {fin:%H:%M}, Bonita evalúa y el Coordinador sigue con la cobertura parcial")
            u.entrar(app, "coordinador.regional")
            esperar_hasta(fin)
            ok = esperar_evaluacion(u, app, emg, 240)
            r.check("Bonita evaluó y el Coordinador ve la cobertura", ok, u.page.url)
            if not ok:
                u.foto("error-sin-evaluacion")
                raise RuntimeError("la evaluación no llegó")
            cob = page.locator("[data-testid=cobertura-total]").inner_text()
            r.check("Cobertura 60 %, no alcanza", cob.startswith("60") and "no alcanza" in cob, cob)
            for _, cuit, nombre in ONGS:
                r.check(f"{nombre} figura como reservada",
                        "Reservada" in page.locator(f'[data-testid="evaluacion-ong-{cuit}"]').inner_text())
            r.check("Nacional tiene 4 + 2 paramédicos reservados",
                    (comprometido(nacional, CRUZ_ROJA, "PARAMEDICO"), comprometido(nacional, BOMBEROS, "PARAMEDICO")) == (4, 2))
            r.check("El Coordinador ve los botones de decisión",
                    page.locator("[data-testid=decidir-parcial]").count() == 1
                    and page.locator("[data-testid=decidir-reformular]").count() == 1)
            u.foto("coordinador-evaluacion")
            page.locator("[data-testid=decidir-parcial]").click()
            u.ve("Seguís con la cobertura parcial", "El Coordinador eligió la cobertura parcial")
            r.check("La emergencia pasó a «Adjudicación»", esperar_estado(u, app, emg, "Adjudicación", 30))
            r.check("Bonita espera «Adjudicar Ofertas»", esperar_tarea_activa(admin, caso, "Adjudicar").startswith("Adjudicar"),
                    tarea_activa(admin, caso))
            u.salir()

            r.fase("5. Municipio: adjudica a las dos ONGs")
            u.entrar(app, "operador.municipal")
            u.abrir(app, emg)
            page.locator("[data-testid=adjudicacion]").wait_for(timeout=PLAZO)
            for _, cuit, _ in ONGS:
                page.locator(f"[data-testid=elegir-{cuit}] input").check()
            u.foto("municipio-adjudicar")
            page.locator("[data-testid=adjudicar]").click()
            u.ve("Adjudicación enviada", "El Municipio envió la adjudicación")
            r.check("Bonita avisó y la emergencia pasó a «En ejecución»", esperar_estado(u, app, emg, "En ejecución", 90), page.url)
            u.foto("municipio-en-ejecucion")
            r.check("Bonita espera «Monitorear Ejecucion»", esperar_tarea_activa(admin, caso, "Monitorear").startswith("Monitorear"),
                    tarea_activa(admin, caso))
            r.check("Nacional conserva las dos reservas (4 y 2)",
                    (comprometido(nacional, CRUZ_ROJA, "PARAMEDICO"), comprometido(nacional, BOMBEROS, "PARAMEDICO")) == (4, 2))
            u.salir()

            r.fase("6. Coordinador: monitorea la ejecución")
            u.entrar(app, "coordinador.regional")
            u.abrir(app, emg)
            u.ve("Ejecución y cierre", "El detalle muestra «Ejecución y cierre»")
            r.check("Las dos ONGs aparecen «En ejecución»", page.get_by_test_id("ejecucion").get_by_text("En ejecución").count() >= 2)
            r.check("No hay botón de validar el cierre todavía", page.get_by_test_id("validar-cierre").count() == 0)
            u.foto("coordinador-antes-de-monitorear")
            page.get_by_test_id("monitorear").click()
            u.ve("Monitoreo iniciado", "Aparece el mensaje «Monitoreo iniciado»")
            r.check("Bonita avanzó a «Confirmar Finalizacion de Actividades»",
                    esperar_tarea_activa(admin, caso, "Confirmar Finalizacion").startswith("Confirmar Finalizacion"),
                    tarea_activa(admin, caso))
            r.check("«Monitorear» la completó coordinador.regional",
                    ejecutada_por(admin, caso, "Monitorear") == "coordinador.regional", ejecutada_por(admin, caso, "Monitorear"))
            u.foto("coordinador-monitoreando")
            u.salir()

            r.fase("7. ONGs: cada una marca su actividad como finalizada")
            for i, (usuario, _, nombre) in enumerate(ONGS):
                u.entrar(app, usuario)
                u.abrir(app, emg)
                r.check(f"{nombre} ve solo su propia fila", page.get_by_test_id("ejecucion").locator(".lote-row").count() == 1)
                u.foto(f"ong-{usuario.split('.')[1]}-antes-de-finalizar")
                page.get_by_test_id("finalizar").click()
                u.ve("Marcaste tu actividad como finalizada", f"{nombre} marca su actividad como finalizada")
                page.get_by_test_id("finalizar").wait_for(state="hidden", timeout=15000)  # la pantalla se refresca tras el clic
                r.check(f"{nombre}: ya no se ofrece finalizar de nuevo", page.get_by_test_id("finalizar").count() == 0)
                if i == 0:
                    # Con una ONG todavía en ejecución, el cierre no está listo: Bonita sigue esperando la confirmación.
                    r.check("Bonita sigue en «Confirmar Finalizacion» hasta que termine la otra ONG",
                            tarea_activa(admin, caso).startswith("Confirmar Finalizacion"), tarea_activa(admin, caso))
                u.salir()
            r.check("Bonita avanzó a «Validar Cierre Operativo Bilateral»",
                    esperar_tarea_activa(admin, caso, "Validar Cierre").startswith("Validar Cierre"), tarea_activa(admin, caso))

            r.fase("8. Coordinador: valida el cierre bilateral")
            u.entrar(app, "coordinador.regional")
            u.abrir(app, emg)
            u.ve("Todas las ONGs terminaron", "Con las dos finalizadas se ofrece validar el cierre")
            u.foto("coordinador-valida-cierre")
            page.get_by_test_id("validar-cierre").click()
            u.ve("Cierre validado", "Aparece «Cierre validado»", timeout=15000)
            r.check("«Validar Cierre» la completó coordinador.regional",
                    ejecutada_por(admin, caso, "Validar Cierre") == "coordinador.regional", ejecutada_por(admin, caso, "Validar Cierre"))
            r.check("El caso de Bonita ya no tiene tareas pendientes", sin_tareas(admin, caso), tarea_activa(admin, caso))
            r.check("Bonita liberó y avisó: la app marca la emergencia RESUELTA", esperar_resuelta(args.api, emg))
            page.reload()
            u.ve("Emergencia resuelta", "La emergencia queda «Resuelta»", timeout=30000)
            u.foto("coordinador-resuelta")
            u.salir()

            r.fase("9. API Nacional: un solo cierre por ONG y nada comprometido")
            for _, cuit, nombre in ONGS:
                ref = f"emg-{emg}-r1-{cuit}"
                r.check(f"{nombre}: un solo cierre informado ({ref})", cierres(nacional, cuit, ref) == 1, cierres(nacional, cuit, ref))
            r.check("No quedó stock comprometido",
                    {k: comprometido(nacional, *k) for k in previos} == previos, {k: comprometido(nacional, *k) for k in previos})

            r.fase("10. ONGs y Municipio: lo que ven al final")
            for usuario, _, nombre in ONGS:
                u.entrar(app, usuario)
                texto = f"emergencia #{emg} se cerró"
                page.get_by_test_id("campana-contador").wait_for(timeout=PLAZO)
                page.get_by_test_id("campana").click()
                lista = page.get_by_test_id("campana-lista")
                lista.wait_for(timeout=PLAZO)
                r.check(f"{nombre}: la campana lista el aviso del cierre, sin leer",
                        lista.locator("button.aviso.nuevo", has_text=texto).count() == 1,
                        lista.get_by_text(texto).count())
                u.foto(f"ong-{usuario.split('.')[1]}-campana")
                lista.get_by_text(texto).first.click()
                page.wait_for_url(f"**/emergencias/{emg}", timeout=PLAZO)
                u.ve("Emergencia resuelta", f"{nombre}: al tocar el aviso abre la emergencia resuelta")
                # El aviso de esta emergencia, no el contador global: otras corridas pueden estar avisando a la misma ONG.
                page.get_by_test_id("campana").click()
                lista = page.get_by_test_id("campana-lista")
                lista.wait_for(timeout=PLAZO)
                try:
                    expect(lista.locator("button.aviso.nuevo", has_text=texto)).to_have_count(0, timeout=PLAZO)
                    leido = lista.locator("button.aviso", has_text=texto).count() == 1
                except AssertionError:
                    leido = False
                r.check(f"{nombre}: el aviso se marcó como leído", leido)
                page.get_by_test_id("campana").click()
                u.foto(f"ong-{usuario.split('.')[1]}-resuelta")
                u.salir()
            u.entrar(app, "operador.municipal")
            u.abrir(app, emg)
            u.ve("Emergencia resuelta", "El Municipio ve «Emergencia resuelta»")
            u.foto("municipio-resuelta")
            u.salir()
        except Exception as exc:
            r.check("El recorrido llegó hasta el final", False, f"{type(exc).__name__}: {str(exc)[:300]}")
            u.foto("error")
        finally:
            browser.close()
    return r.resumen()


if __name__ == "__main__":
    sys.exit(main())
