"""Piezas de la interfaz que comparten los guiones con navegador (e2e_ui.py, ui_parada2.py, ui_parada3.py): el reporte de
verificaciones, el manejo de la página (`Ui`), las esperas y los pasos de pantalla que repiten las paradas.

Las capturas van a `CAPTURAS` (cada guion la cambia por su carpeta) salvo con `SIN_CAPTURAS`."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import Page

from comun import esperar
from app.integrations.bonita import BonitaClient
from app.seed import DEMO_PASSWORD

CAPTURAS = Path(__file__).resolve().parent / "capturas"
PLAZO = 8000  # ms que se espera a que la SPA muestre algo
PLAZO_LENTO = 25000  # lo que pasa por la API Nacional (en la nube, y con otros guiones en paralelo, tarda más)
POLL_S = 1.0  # cada cuánto se consulta a Bonita o a la app mientras se espera un cambio
SIN_CAPTURAS = False  # --sin-capturas: no se guardan las fotos de cada paso


class Reporte:
    def __init__(self) -> None:
        self.fallas = 0
        self.total = 0

    def fase(self, titulo: str) -> None:
        print(f"\n== {titulo}")

    def check(self, nombre: str, ok: bool, detalle: str = "") -> bool:
        self.total += 1
        if not ok:
            self.fallas += 1
        print(f"  [{'OK   ' if ok else 'FALLA'}] {nombre}" + ("" if ok else f"  -> {detalle}"))
        return ok

    def resumen(self) -> int:
        print(f"\n{self.total - self.fallas}/{self.total} verificaciones OK")
        return 1 if self.fallas else 0


def ejecutada_por(admin: BonitaClient, case_id, prefijo: str) -> str:
    """Quién completó esa tarea según el historial del motor, no según lo que cree la app."""
    for tarea in admin.get_archived_human_tasks(case_id):
        if tarea["displayName"].startswith(prefijo):
            return admin.user_name(tarea["executedBy"])
    return "(no ejecutada)"


def esperar_hasta(momento: datetime, holgura_s: float = 0) -> None:
    """Duerme hasta `momento`: mientras la ventana está abierta no hay nada que ver, y recargar la pantalla cada
    segundo solo carga a la app, a Bonita y al navegador."""
    falta = (momento - datetime.now().astimezone()).total_seconds() + holgura_s
    if falta > 0:
        time.sleep(falta)


def cierre_de_ventana(margen_s: float) -> datetime:
    """Cierre de la convocatoria: el campo de la pantalla tiene precisión de minuto, así que se redondea hacia arriba.
    Garantiza al menos `margen_s` desde ahora (el tiempo que tarda el guion en cargar las ofertas) y a lo sumo un minuto más."""
    return (datetime.now().astimezone() + timedelta(seconds=margen_s)).replace(second=0, microsecond=0) + timedelta(minutes=1)


class Ui:
    def __init__(self, page: Page, r: Reporte) -> None:
        self.page, self.r, self.n = page, r, 0
        self.sesiones: dict[str, list] = {}  # usuario -> cookies de su sesión (la app firma la cookie: no hay estado en el servidor)

    def ve(self, texto: str, nombre: str | None = None, visible: bool = True, timeout: int = PLAZO) -> bool:
        """Verifica que un texto aparezca (o, con visible=False, que no esté) en la pantalla."""
        loc = self.page.get_by_text(texto, exact=False).first
        try:
            loc.wait_for(state="visible" if visible else "hidden", timeout=timeout)
            ok = True
        except Exception:
            ok = False
        detalle = self.page.url
        if not ok:  # lo que había en pantalla (un mensaje de error de la app, por ejemplo) explica la falla
            try:
                detalle += " | " + " ".join(self.page.locator("body").inner_text(timeout=2000).split())[-300:]
            except Exception:
                pass
        return self.r.check(nombre or (f"Se ve «{texto}»" if visible else f"No se ve «{texto}»"), ok, detalle)

    def foto(self, nombre: str) -> None:
        self.n += 1
        if SIN_CAPTURAS:
            return
        CAPTURAS.mkdir(exist_ok=True)
        self.page.screenshot(path=str(CAPTURAS / f"{self.n:02d}-{nombre}.png"), full_page=True)

    def entrar(self, app: str, usuario: str, clave: str = DEMO_PASSWORD, esperar: bool = True) -> None:
        """La primera vez de cada perfil entra por la pantalla de login; las siguientes reponen su cookie de sesión
        (el login ya está probado) y se ahorran el recorrido por el formulario."""
        p = self.page
        ctx = p.context
        ctx.clear_cookies()
        if esperar and clave == DEMO_PASSWORD and usuario in self.sesiones:
            ctx.add_cookies(self.sesiones[usuario])
            p.goto(f"{app}/")
            return
        p.goto(f"{app}/login")
        p.get_by_placeholder("ej. operador.municipal").fill(usuario)
        p.locator("input[type=password]").fill(clave)
        p.get_by_role("button", name="Entrar al panel").click()
        if esperar:  # sin esto, un goto inmediato cancela el login en curso
            p.wait_for_url(lambda url: "/login" not in url, timeout=PLAZO)
            if clave == DEMO_PASSWORD:
                self.sesiones[usuario] = ctx.cookies()

    def salir(self) -> None:
        """Deja al perfil: el próximo `entrar` cambia de cookie. Para probar el cierre de sesión en sí, `cerrar_sesion`."""

    def cerrar_sesion(self) -> None:
        self.page.get_by_role("button", name="Salir").click()
        self.page.wait_for_url(re.compile(r"/login"), timeout=PLAZO)

    def abrir(self, app: str, emergencia_id: int) -> None:
        self.page.goto(f"{app}/emergencias/{emergencia_id}")
        self.page.get_by_text("Lotes de necesidades").wait_for(timeout=PLAZO)


def dato(page: Page, etiqueta: str) -> str:
    return page.locator(".meta-item", has_text=etiqueta).locator("strong").inner_text().strip()


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
    u.ve(nombre, f"Lote «{nombre}» en la lista", timeout=PLAZO_LENTO)


def publicar(u: Ui, fin: datetime) -> None:
    u.page.locator("[name=ventana_fin]").fill(fin.strftime("%Y-%m-%dT%H:%M"))
    u.page.get_by_role("button", name="Publicar a la red").click()
    u.ve("Convocatoria publicada", "Publicación aceptada", timeout=40000)
    u.ve("Convocatoria abierta", "Estado «Convocatoria abierta»")


def ofrecer(u: Ui, app: str, emergencia: int, cantidad: str, foto: str | None = None) -> None:
    u.abrir(app, emergencia)
    u.page.locator("[name^=lote_]").first.fill(cantidad)
    u.page.get_by_role("button", name="Enviar oferta").click()
    if not u.ve("versión 1", f"Oferta de {cantidad} enviada (versión 1)"):
        u.foto(f"error-oferta-{cantidad}")
    if foto:
        u.foto(foto)


def esperar_evaluacion(u: Ui, app: str, emergencia: int, segundos: int) -> bool:
    """El Coordinador recarga el detalle hasta que aparece la cobertura que calculó Bonita. Llamar cuando la ventana ya
    venció (`esperar_hasta`): antes no hay nada que ver."""
    def aparece():
        u.abrir(app, emergencia)
        return u.page.locator("[data-testid=cobertura-total]").count()
    return bool(esperar(aparece, segundos, cada=POLL_S))


def esperar_estado(u: Ui, app: str, emergencia: int, etiqueta: str, segundos: int) -> bool:
    def aparece():
        u.abrir(app, emergencia)
        return u.page.locator(".badge", has_text=etiqueta).count()
    return bool(esperar(aparece, segundos, cada=POLL_S))
