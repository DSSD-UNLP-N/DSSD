"""T-14 (interfaz): recorre la SPA React en un navegador real con los 5 perfiles y verifica, en cada
paso, lo que se ve en pantalla y lo que pasó en Bonita. Complementa a e2e.py, que habla HTTP.

Requisitos: Bonita Studio con el proceso desplegado, backend (`uvicorn app.main:app --port 8001`),
API Nacional (`cd nacional; uvicorn app.main:app --port 8002`, migrada y con seed),
frontend (`npm run dev`), base migrada + seedeada, y Chrome o Chromium instalado.

    pip install -r requirements-dev.txt
    python scripts/e2e_ui.py                    # headless, ~1 min
    python scripts/e2e_ui.py --demo             # navegador visible y lento, para mostrarlo
    python scripts/e2e_ui.py --timer 120        # además espera a que dispare el boundary timer
    python scripts/e2e_ui.py --app http://localhost:5173

Deja una emergencia nueva por corrida y capturas de cada paso en scripts/capturas/.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.integrations.bonita import BonitaClient  # noqa: E402
from app.seed import DEMO_PASSWORD  # noqa: E402

TAREA_TRAS_ALTA = "Revisar Informacion"
TAREA_TRAS_PUBLICAR = "Cargar Ofertas de Ayuda"
TAREA_TRAS_TIMER = "Evaluar Cobertura"
TAREA_PUBLICAR = "Publicar Convocatoria"

# Bonita tiene que registrar a estos mismos usuarios como iniciador del caso y ejecutor de cada
# tarea, no a un genérico por rol ni al usuario técnico.
# Actor del proceso al que debe pertenecer cada tarea humana (el que se mapea al grupo de esa lane).
ACTOR_DE_TAREA = {
    "Registrar Emergencia": "Municipio",
    "Revisar Informacion": "centro de controlador regional",
    "Publicar Convocatoria": "centro de controlador regional",
    "Cargar Ofertas de Ayuda": "ONG",
}
USUARIO_MUNICIPAL = "operador.municipal"
USUARIO_COORDINADOR = "coordinador.regional"


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


def tarea_activa(admin: BonitaClient, case_id) -> str:
    tareas = admin.get_human_tasks(case_id)
    return tareas[0]["displayName"] if tareas else "(ninguna)"


def actor_de(admin: BonitaClient, case_id, prefijo: str) -> str:
    """A qué actor del proceso pertenece la tarea (pendiente o ya hecha). Es lo que decide quién la ve como
    suya en el portal de Bonita; el motor deja ejecutarla aunque el usuario no sea del actor, así que
    solo se nota mirándolo."""
    actores = admin.actor_names(admin.get_case(case_id)["processDefinitionId"])
    for tarea in admin.get_human_tasks(case_id) + admin.get_archived_human_tasks(case_id):
        if tarea["displayName"].startswith(prefijo):
            return actores.get(tarea["actorId"], tarea["actorId"])
    return "(sin tarea)"


def esperar_tarea(admin: BonitaClient, case_id, prefijo: str, segundos: int) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if admin.find_task(case_id, prefijo) is not None:
            return True
        time.sleep(5)
    return False


def iniciado_por(admin: BonitaClient, case_id) -> str:
    return admin.user_name(admin.get_case(case_id)["started_by"])


def ejecutada_por(admin: BonitaClient, case_id, prefijo: str) -> str:
    """Quién completó esa tarea según el historial del motor, no según lo que cree la app."""
    for tarea in admin.get_archived_human_tasks(case_id):
        if tarea["displayName"].startswith(prefijo):
            return admin.user_name(tarea["executedBy"])
    return "(no ejecutada)"


CAPTURAS = Path(__file__).resolve().parent / "capturas"
# (código del catálogo del Sistema Nacional, nombre que muestra, cantidad, tipo de lote)
LOTES = [("BRIGADISTA_FORESTAL", "Brigadista forestal", "30", "PRINCIPAL"),
         ("AGUA_POTABLE", "Agua potable", "8000", "PRINCIPAL"),
         ("AUTOBOMBA", "Autobomba", "3", "PRINCIPAL"),
         ("RACION_ALIMENTO", "Ración de alimento", "200", "APOYO")]
PLAZO = 8000  # ms que se espera a que la SPA muestre algo


class Ui:
    def __init__(self, page: Page, r: Reporte) -> None:
        self.page, self.r, self.n = page, r, 0

    def ve(self, texto: str, nombre: str | None = None, visible: bool = True, timeout: int = PLAZO) -> bool:
        """Verifica que un texto aparezca (o, con visible=False, que no esté) en la pantalla."""
        loc = self.page.get_by_text(texto, exact=False).first
        try:
            loc.wait_for(state="visible" if visible else "hidden", timeout=timeout)
            ok = True
        except Exception:
            ok = False
        return self.r.check(nombre or (f"Se ve «{texto}»" if visible else f"No se ve «{texto}»"), ok, self.page.url)

    def foto(self, nombre: str) -> None:
        self.n += 1
        CAPTURAS.mkdir(exist_ok=True)
        self.page.screenshot(path=str(CAPTURAS / f"{self.n:02d}-{nombre}.png"), full_page=True)

    def entrar(self, app: str, usuario: str, clave: str = DEMO_PASSWORD, esperar: bool = True) -> None:
        p = self.page
        p.goto(f"{app}/login")
        p.get_by_placeholder("ej. operador.municipal").fill(usuario)
        p.locator("input[type=password]").fill(clave)
        p.get_by_role("button", name="Entrar al panel").click()
        if esperar:  # sin esto, un goto inmediato cancela el login en curso
            p.wait_for_url(lambda url: "/login" not in url, timeout=PLAZO)

    def salir(self) -> None:
        self.page.get_by_role("button", name="Salir").click()
        self.page.wait_for_url(re.compile(r"/login"), timeout=PLAZO)

    def abrir(self, app: str, emergencia_id: int) -> None:
        self.page.goto(f"{app}/emergencias/{emergencia_id}")
        self.page.get_by_text("Lotes de necesidades").wait_for(timeout=PLAZO)


def dato(page: Page, etiqueta: str) -> str:
    return page.locator(".meta-item", has_text=etiqueta).locator("strong").inner_text().strip()


def fase_anonimo(u: Ui, app: str) -> None:
    u.r.fase("Anónimo: nada accesible sin login")
    u.page.goto(f"{app}/emergencias")
    u.page.wait_for_url(re.compile(r"/login"), timeout=PLAZO)
    u.r.check("/emergencias redirige al login", "/login" in u.page.url, u.page.url)
    u.entrar(app, "operador.municipal", "mal", esperar=False)
    u.ve("incorrectos", "Contraseña incorrecta: muestra el error")
    u.foto("login-error")


def fase_municipio(u: Ui, app: str) -> tuple[int, int]:
    u.r.fase("Operador Municipal: alta de la emergencia")
    u.entrar(app, "operador.municipal")
    u.ve("Hola, Operador", "Login correcto: panel del Operador Municipal")
    u.ve("Registrar emergencia")
    u.r.check("No hay entradas de otros perfiles", u.page.get_by_text("Convocatorias abiertas").count() == 0)
    u.foto("municipio-panel")

    u.page.get_by_text("Registrar emergencia").first.click()
    u.page.get_by_role("heading", name="Registrar emergencia").wait_for(timeout=PLAZO)
    u.page.locator("select").nth(0).select_option("incendio")
    u.page.locator("select").nth(1).select_option("CRITICO")
    u.page.get_by_placeholder("Barrio, localidad o área").fill("Sierra de la Ventana (UI e2e)")
    u.page.get_by_placeholder("Situación inicial, impacto y necesidades estimadas").fill(
        "Incendio forestal avanza hacia zona de cabañas. 40 familias evacuadas.")
    u.foto("municipio-formulario")
    u.page.get_by_role("button", name="Registrar emergencia").click()
    u.page.wait_for_url(re.compile(r"/emergencias/\d+$"), timeout=30000)
    emergencia_id = int(u.page.url.rsplit("/", 1)[1])
    u.ve("Sierra de la Ventana (UI e2e)", "Detalle con los datos cargados")
    caso = dato(u.page, "Caso Bonita")
    u.r.check("El detalle muestra el caso de Bonita", caso.isdigit(), caso)
    u.r.check("Estado 'Registrada'", u.page.locator(".badge", has_text="Registrada").count() > 0)
    u.r.check("Gravedad CRITICO", u.page.locator(".badge", has_text="CRITICO").count() > 0)
    u.r.check("Municipio sin formularios de lotes ni de publicación",
              u.page.get_by_text("Agregar lote").count() == 0 and u.page.get_by_text("Publicar a la red").count() == 0)
    u.foto("municipio-detalle")
    print(f"     emergencia #{emergencia_id}, caso Bonita #{caso}")

    u.page.goto(f"{app}/emergencias")
    u.ve("Sierra de la Ventana (UI e2e)", "Aparece en 'Mis emergencias'")
    u.salir()
    return emergencia_id, int(caso)


def fase_bonita_alta(r: Reporte, admin: BonitaClient, emergencia_id: int, case_id: int) -> None:
    r.fase("Bonita: el caso quedó esperando al Coordinador")
    activa = tarea_activa(admin, case_id)
    r.check(f"Tarea activa '{TAREA_TRAS_ALTA}…'", activa.startswith(TAREA_TRAS_ALTA), activa)
    v = admin.get_case_variables(case_id)
    r.check("Contrato en las variables del caso",
            v.get("emergenciaId") == str(emergencia_id) and v.get("nivelGravedad") == "CRITICO",
            str({k: v.get(k) for k in ("emergenciaId", "nivelGravedad")}))

    r.fase("Bonita: trazabilidad del alta (¿quién figura que lo hizo?)")
    inicio = iniciado_por(admin, case_id)
    r.check(f"El caso lo inició '{USUARIO_MUNICIPAL}', no el usuario técnico", inicio == USUARIO_MUNICIPAL, inicio)
    ejecutor = ejecutada_por(admin, case_id, "Registrar Emergencia")
    r.check(f"'Registrar Emergencia' la ejecutó '{USUARIO_MUNICIPAL}'", ejecutor == USUARIO_MUNICIPAL, ejecutor)

    r.fase("Bonita: cada tarea pertenece al actor de su lane")
    for prefijo, esperado in ACTOR_DE_TAREA.items():
        if prefijo in (TAREA_TRAS_PUBLICAR, TAREA_PUBLICAR):
            continue  # todavía no llegó el caso
        actor = actor_de(admin, case_id, prefijo)
        r.check(f"'{prefijo}…' es del actor '{esperado}'", actor == esperado, actor)


def fase_lotes_y_publicacion(u: Ui, app: str, emergencia_id: int, espera: int) -> datetime:
    u.r.fase("Centro Coordinador: lotes y publicación")
    u.entrar(app, "coordinador.regional")
    u.ve("Hola, Centro", "Login correcto: panel del Coordinador")
    u.abrir(app, emergencia_id)
    u.ve("todavía no cargó lotes", "Sin lotes al principio")

    for codigo, nombre, cantidad, tipo in LOTES:
        u.page.locator("[name=tipo_recurso]").select_option(codigo)
        u.page.locator("[name=cantidad]").fill(cantidad)
        u.page.locator("[name=tipo]").select_option(tipo)
        u.page.get_by_role("button", name="Agregar lote").click()
        u.ve(nombre, f"Lote '{nombre}' aparece en la lista")
    u.r.check("El formulario se limpia tras agregar", u.page.locator("[name=tipo_recurso]").input_value() == "")
    u.r.check("El lote de apoyo sale etiquetado", u.page.get_by_text("APOYO").count() > 0)
    u.foto("coordinador-lotes")

    pasado = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    u.page.locator("[name=ventana_fin]").fill(pasado)
    u.page.get_by_role("button", name="Publicar a la red").click()
    u.ve("fecha futura", "Cierre en el pasado: rechazado")

    fin = (datetime.now().astimezone() + timedelta(seconds=espera)).replace(second=0, microsecond=0) + timedelta(minutes=1)
    u.page.locator("[name=ventana_fin]").fill(fin.strftime("%Y-%m-%dT%H:%M"))
    u.page.get_by_role("button", name="Publicar a la red").click()
    u.ve("Convocatoria publicada", "Publicación aceptada", timeout=40000)
    u.ve("Convocatoria abierta", "Estado 'Convocatoria abierta'")
    u.ve("Agregar lote", "Ya no se pueden agregar lotes", visible=False)
    u.foto("coordinador-publicada")
    u.salir()
    return fin


def fase_bonita_publicacion(r: Reporte, admin: BonitaClient, case_id: int, fin: datetime) -> None:
    r.fase("Bonita: la convocatoria abrió la ventana de ofertas")
    activa = tarea_activa(admin, case_id)
    r.check(f"Tarea activa '{TAREA_TRAS_PUBLICAR}'", activa.startswith(TAREA_TRAS_PUBLICAR), activa)
    guardada = admin.get_case_variables(case_id).get("ventanaOfertasISO", "")
    r.check("ventanaOfertasISO = el cierre elegido en la pantalla",
            datetime.fromisoformat(guardada) == fin, f"{guardada} vs {fin.isoformat()}")
    for prefijo in (TAREA_TRAS_ALTA, TAREA_PUBLICAR):
        ejecutor = ejecutada_por(admin, case_id, prefijo)
        r.check(f"'{prefijo}…' la ejecutó '{USUARIO_COORDINADOR}'", ejecutor == USUARIO_COORDINADOR, ejecutor)
    for prefijo in (TAREA_PUBLICAR, TAREA_TRAS_PUBLICAR):
        esperado = ACTOR_DE_TAREA[prefijo]
        actor = actor_de(admin, case_id, prefijo)
        r.check(f"'{prefijo}…' es del actor '{esperado}'", actor == esperado, actor)


def cargar_oferta(u: Ui, cantidades: list[str]) -> None:
    for campo, valor in zip(u.page.locator("[name^=lote_]").all(), cantidades):
        campo.fill(valor)
    u.page.get_by_role("button", name="Enviar oferta").click()


def fase_ongs(u: Ui, app: str, emergencia_id: int) -> None:
    u.r.fase("ONG Cruz Roja: oferta versionada")
    u.entrar(app, "ong.cruzroja")
    u.ve("Hola,", "Login correcto: panel de la ONG")
    u.page.goto(f"{app}/emergencias")
    u.ve("Sierra de la Ventana (UI e2e)", "Ve la convocatoria publicada")
    u.abrir(app, emergencia_id)
    u.r.check("La ONG no ve formularios de lotes ni de publicación",
              u.page.get_by_text("Agregar lote").count() == 0 and u.page.get_by_text("Publicar a la red").count() == 0)
    u.ve("tenés pendiente la tarea «Cargar Ofertas de Ayuda»", "Bonita: la ONG ve su tarea pendiente, sin botón para completarla")

    cargar_oferta(u, ["0", "0", "0", "0"])
    u.ve("al menos un lote", "Oferta vacía: pide cargar algo")
    # Cruz Roja tiene 3000 litros de agua y 5000 raciones en el Sistema Nacional (nacional/app/seed.py).
    cargar_oferta(u, ["0", "9000", "0", "0"])
    u.ve("No alcanza tu inventario", "Ofrecer más agua de la que tiene: rechazado")
    cargar_oferta(u, ["0", "2500", "0", "150"])
    u.ve("versión 1", "Primer envío: versión 1")
    u.foto("ong-cruzroja-v1")
    cargar_oferta(u, ["0", "3000", "0", "0"])
    u.ve("versión 2", "Reenvío: versión 2")
    u.ve("Mi oferta vigente")
    u.ve("3000 / 8000", "La v2 muestra el agua ofrecida")
    # 1 = la fila del lote pedido; si la v1 siguiera vigente habría una 2ª en "Mi oferta vigente"
    u.r.check("La v2 reemplaza a la v1: sin raciones",
              u.page.locator(".lote-row", has_text="Ración de alimento").count() == 1)
    u.foto("ong-cruzroja-v2")
    u.salir()

    u.r.fase("ONG Bomberos: misma convocatoria, oferta propia")
    u.entrar(app, "ong.bomberos")
    u.abrir(app, emergencia_id)
    u.r.check("Bomberos no ve la oferta de Cruz Roja", u.page.get_by_text("Cruz Roja").count() == 0)
    # Bomberos tiene 20 brigadistas y 4 autobombas.
    cargar_oferta(u, ["18", "0", "3", "0"])
    u.ve("versión 1", "Bomberos: versión 1")
    u.foto("ong-bomberos")
    u.page.locator(".field", has_text="Autobomba").get_by_role("button", name="Retirar de este lote").click()
    u.ve("Retiraste tu oferta a ese lote", "Bomberos retira las autobombas: versión 2 sin ese lote")
    u.r.check("La v2 ya no ofrece autobombas", u.page.locator(".lote-row", has_text="Autobomba").count() == 1)
    u.salir()


def fase_coordinador_ve_ofertas(u: Ui, app: str, emergencia_id: int) -> None:
    u.r.fase("Centro Coordinador: ofertas recibidas")
    u.entrar(app, "coordinador.regional")
    u.abrir(app, emergencia_id)
    u.ve("Ofertas recibidas")
    u.r.check("Ve a Cruz Roja y a Bomberos",
              u.page.get_by_text("Cruz Roja Argentina").count() > 0 and u.page.get_by_text("Bomberos Voluntarios").count() > 0)
    u.foto("coordinador-ofertas")
    u.salir()


def fase_auditor(u: Ui, app: str, emergencia_id: int) -> None:
    u.r.fase("Auditor: consulta sin poder operar")
    u.entrar(app, "auditor")
    u.ve("Auditor", "Login correcto: perfil Auditor")
    u.r.check("Sin acceso a registrar emergencias", u.page.get_by_text("Registrar emergencia").count() == 0)
    u.abrir(app, emergencia_id)
    u.ve("Ofertas recibidas")
    u.r.check("Sin formularios de operación",
              all(u.page.get_by_text(t).count() == 0 for t in ("Agregar lote", "Publicar a la red", "Enviar oferta")))
    u.foto("auditor")
    u.salir()
    u.page.goto(f"{app}/emergencias")
    u.page.wait_for_url(re.compile(r"/login"), timeout=PLAZO)
    u.r.check("Tras salir, /emergencias vuelve al login", "/login" in u.page.url)


def fase_timer(u: Ui, admin: BonitaClient, app: str, case_id: int, emergencia_id: int, fin: datetime) -> None:
    u.r.fase("Boundary timer: cierre de la ventana")
    faltan = (fin - datetime.now().astimezone()).total_seconds()
    if faltan > 0:
        print(f"     esperando {int(faltan) + 5} s hasta el cierre ({fin:%H:%M})")
        time.sleep(faltan + 5)
    ok = esperar_tarea(admin, case_id, TAREA_TRAS_TIMER, 180)
    u.r.check(f"El timer disparó: el caso avanzó a '{TAREA_TRAS_TIMER}…'", ok, tarea_activa(admin, case_id))
    u.r.check(f"'{TAREA_TRAS_PUBLICAR}' se cerró sola", admin.find_task(case_id, TAREA_TRAS_PUBLICAR) is None)
    u.entrar(app, "ong.cruzroja")
    u.abrir(app, emergencia_id)
    u.ve("ventana de ofertas cerró", "La ONG ve que la ventana cerró")
    u.ve("Enviar oferta", "Ya no puede ofertar", visible=False)
    u.foto("ong-ventana-cerrada")
    u.salir()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="http://localhost:5173")
    ap.add_argument("--timer", type=int, metavar="SEGUNDOS", help="cierre de ofertas a esa distancia; espera al timer")
    ap.add_argument("--demo", action="store_true", help="navegador visible y lento")
    args = ap.parse_args()

    for vieja in CAPTURAS.glob("*.png"):  # solo quedan las de esta corrida
        vieja.unlink()
    settings = get_settings()
    r = Reporte()
    admin = BonitaClient(settings.bonita_base_url, settings.bonita_timeout_seconds)
    admin.login(settings.bonita_username, settings.bonita_password)

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=not args.demo, slow_mo=500 if args.demo else 0)
        except Exception:  # sin Chrome: el Chromium que baja `playwright install chromium`
            browser = pw.chromium.launch(headless=not args.demo, slow_mo=500 if args.demo else 0)
        page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        page.set_default_timeout(PLAZO)
        u = Ui(page, r)
        try:
            fase_anonimo(u, args.app)
            emergencia_id, case_id = fase_municipio(u, args.app)
            fase_bonita_alta(r, admin, emergencia_id, case_id)
            fin = fase_lotes_y_publicacion(u, args.app, emergencia_id, args.timer or 7200)
            fase_bonita_publicacion(r, admin, case_id, fin)
            fase_ongs(u, args.app, emergencia_id)
            fase_coordinador_ve_ofertas(u, args.app, emergencia_id)
            fase_auditor(u, args.app, emergencia_id)
            if args.timer:
                fase_timer(u, admin, args.app, case_id, emergencia_id, fin)
        except Exception as exc:  # un paso que no aparece corta el recorrido, pero deja evidencia
            r.check("El recorrido llegó hasta el final", False, f"{type(exc).__name__}: {str(exc)[:200]}")
            u.foto("error")
        finally:
            browser.close()
    return r.resumen()


if __name__ == "__main__":
    sys.exit(main())
