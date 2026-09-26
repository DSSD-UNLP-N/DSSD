"""T-14: prueba end-to-end automática contra la app y Bonita reales.

Recorre el flujo completo con los cinco usuarios de demo y verifica, en cada paso, tanto
lo que muestra la app como lo que pasó del lado del motor (caso, tarea activa, variables).
No usa navegador: habla HTTP igual que el navegador.

Requisitos: Bonita Studio con el proceso desplegado, la app corriendo
(`uvicorn app.main:app`) y la base migrada + seedeada.

    python scripts/e2e.py                 # ~30 s
    python scripts/e2e.py --timer 90      # además espera a que dispare el boundary timer
    python scripts/e2e.py --app http://localhost:8000
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.integrations.bonita import BonitaClient  # noqa: E402
from app.models import Lote  # noqa: E402
from app.seed import DEMO_PASSWORD  # noqa: E402

TAREA_TRAS_ALTA = "Revisar Informacion"
TAREA_TRAS_PUBLICAR = "Cargar Ofertas de Ayuda"
TAREA_TRAS_TIMER = "Evaluar Cobertura"
TAREA_PUBLICAR = "Publicar Convocatoria"

# Quién hace el recorrido. El motor tiene que registrar estos mismos usuarios como
# iniciador del caso y ejecutor de cada tarea, no un genérico por rol ni el técnico.
USUARIO_MUNICIPAL = "operador.municipal"
USUARIO_COORDINADOR = "coordinador.regional"

LOTES = [("Agua potable", "5000", "litros", "PRINCIPAL"),
         ("Frazadas", "800", "unidades", "PRINCIPAL"),
         ("Generadores", "4", "unidades", "APOYO")]


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


class Cliente:
    """Sesión HTTP contra la app. No sigue redirecciones: el 303 es parte de lo que se verifica."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.s = requests.Session()

    def get(self, path: str) -> requests.Response:
        return self.s.get(self.base + path, allow_redirects=False, timeout=30)

    def post(self, path: str, data: dict) -> requests.Response:
        return self.s.post(self.base + path, data=data, allow_redirects=False, timeout=60)

    def login(self, username: str) -> requests.Response:
        return self.post("/login", {"username": username, "password": DEMO_PASSWORD})


def destino(resp: requests.Response) -> str:
    return resp.headers.get("location", "")


def tarea_activa(admin: BonitaClient, case_id) -> str:
    tareas = admin.get_human_tasks(case_id)
    return tareas[0]["displayName"] if tareas else "(ninguna)"


def iniciado_por(admin: BonitaClient, case_id) -> str:
    return admin.user_name(admin.get_case(case_id)["started_by"])


def ejecutada_por(admin: BonitaClient, case_id, prefijo: str) -> str:
    """Quién completó esa tarea según el historial del motor, no según lo que cree la app."""
    for tarea in admin.get_archived_human_tasks(case_id):
        if tarea["displayName"].startswith(prefijo):
            return admin.user_name(tarea["executedBy"])
    return "(no ejecutada)"


def esperar_tarea(admin: BonitaClient, case_id, prefijo: str, segundos: int) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if admin.find_task(case_id, prefijo) is not None:
            return True
        time.sleep(5)
    return False


def id_de_lote(emergencia_id: int, recurso: str) -> int | None:
    with SessionLocal() as db:
        lote = next((l for l in db.query(Lote).filter_by(emergencia_id=emergencia_id) if l.recurso == recurso), None)
        return lote.id if lote else None


def fase_anonimo(r: Reporte, app: str) -> None:
    r.fase("Anónimo: nada accesible sin login")
    anon = Cliente(app)
    resp = anon.get("/")
    r.check("GET / redirige al login", resp.status_code == 303 and destino(resp) == "/login",
            f"{resp.status_code} {destino(resp)}")
    r.check("GET /emergencias redirige al login", anon.get("/emergencias").status_code == 303)
    resp = anon.post("/emergencias/1/lotes", {"recurso": "x", "cantidad": "1", "unidad": "u"})
    r.check("POST de lote sin sesión redirige al login", resp.status_code == 303)
    resp = anon.post("/login", {"username": "operador.municipal", "password": "mal"})
    r.check("Contraseña incorrecta: 401 con mensaje",
            resp.status_code == 401 and "incorrectos" in resp.text, str(resp.status_code))


def fase_municipio(r: Reporte, app: str) -> tuple[int, int] | None:
    r.fase("Operador Municipal: alta de la emergencia")
    muni = Cliente(app)
    resp = muni.login(USUARIO_MUNICIPAL)
    r.check("Login correcto", resp.status_code == 303 and destino(resp) == "/", str(resp.status_code))
    r.check("Home con el menú del perfil", "Registrar emergencia" in muni.get("/").text)

    resp = muni.post("/emergencias/nueva",
                     {"tipo": "", "nivel_gravedad": "", "zona_afectada": "", "descripcion": ""})
    r.check("Formulario vacío: 400 y 'es obligatorio'",
            resp.status_code == 400 and "es obligatorio" in resp.text, str(resp.status_code))

    antes = muni.get("/emergencias").text.count("<tr>")
    resp = muni.post("/emergencias/nueva", {
        "tipo": "inundacion", "nivel_gravedad": "ALTO", "zona_afectada": "Villa Rosas, sector sur",
        "descripcion": "Desborde del arroyo Napostá tras 180 mm en 6 horas. 400 evacuados.",
    })
    if not r.check("Alta: 303 al detalle con aviso",
                   resp.status_code == 303 and destino(resp).endswith("?nueva=1"),
                   f"{resp.status_code} {destino(resp)}"):
        return None
    emergencia_id = int(destino(resp).split("/")[2].split("?")[0])

    detalle = muni.get(f"/emergencias/{emergencia_id}")
    r.check("Detalle visible con el caso de Bonita",
            detalle.status_code == 200 and "Caso Bonita" in detalle.text and "Registrada" in detalle.text)
    case_id = int(detalle.text.split("Caso Bonita")[1].split("#")[1].split("<")[0])
    print(f"     emergencia #{emergencia_id}, caso Bonita #{case_id}")

    for _ in range(3):
        muni.get(f"/emergencias/{emergencia_id}")
    despues = muni.get("/emergencias").text.count("<tr>")
    r.check("Recargar el detalle no duplica la emergencia (PRG)", despues == antes + 1,
            f"{antes} filas antes, {despues} después")

    r.check("Municipio no puede cargar lotes (403)",
            muni.post(f"/emergencias/{emergencia_id}/lotes",
                      {"recurso": "a", "cantidad": "1", "unidad": "u"}).status_code == 403)
    r.check("Municipio no puede publicar (403)",
            muni.post(f"/emergencias/{emergencia_id}/publicar",
                      {"ventana_fin": "2027-01-01T10:00"}).status_code == 403)
    return emergencia_id, case_id


def fase_bonita_alta(r: Reporte, admin: BonitaClient, emergencia_id: int, case_id: int) -> None:
    r.fase("Bonita: el caso quedó esperando al Coordinador")
    activa = tarea_activa(admin, case_id)
    r.check(f"Tarea activa '{TAREA_TRAS_ALTA}…'", activa.startswith(TAREA_TRAS_ALTA), activa)
    r.check("'Registrar Emergencia' ya no está pendiente",
            admin.find_task(case_id, "Registrar Emergencia") is None)
    variables = admin.get_case_variables(case_id)
    r.check("El contrato quedó en las variables del caso",
            variables.get("emergenciaId") == str(emergencia_id) and variables.get("nivelGravedad") == "ALTO",
            str({k: variables.get(k) for k in ("emergenciaId", "nivelGravedad")}))

    r.fase("Bonita: trazabilidad del alta (¿quién figura que lo hizo?)")
    inicio = iniciado_por(admin, case_id)
    r.check(f"El caso lo inició '{USUARIO_MUNICIPAL}', no el usuario técnico", inicio == USUARIO_MUNICIPAL, inicio)
    ejecutor = ejecutada_por(admin, case_id, "Registrar Emergencia")
    r.check(f"'Registrar Emergencia' la ejecutó '{USUARIO_MUNICIPAL}'", ejecutor == USUARIO_MUNICIPAL, ejecutor)


def fase_ong_sin_publicar(r: Reporte, app: str, emergencia_id: int) -> Cliente:
    r.fase("ONG: todavía no ve nada (la convocatoria no está publicada)")
    ong = Cliente(app)
    ong.login("ong.cruzroja")
    listado = ong.get("/emergencias").text
    r.check("La emergencia sin publicar no está en su listado", f'/emergencias/{emergencia_id}"' not in listado)
    r.check("Detalle de una emergencia sin publicar: 404",
            ong.get(f"/emergencias/{emergencia_id}").status_code == 404)
    r.check("ONG no puede cargar lotes (403)",
            ong.post(f"/emergencias/{emergencia_id}/lotes",
                     {"recurso": "a", "cantidad": "1", "unidad": "u"}).status_code == 403)
    return ong


def fase_lotes(r: Reporte, app: str, emergencia_id: int) -> Cliente:
    r.fase("Centro Coordinador: lotes de necesidades")
    coord = Cliente(app)
    coord.login(USUARIO_COORDINADOR)
    r.check("Ve la emergencia de otro municipio", coord.get(f"/emergencias/{emergencia_id}").status_code == 200)

    resp = coord.post(f"/emergencias/{emergencia_id}/lotes",
                      {"recurso": "Agua potable", "cantidad": "0", "unidad": "litros"})
    r.check("Cantidad 0 rechazada", "error=" in destino(resp), destino(resp))
    resp = coord.post(f"/emergencias/{emergencia_id}/lotes",
                      {"recurso": "", "cantidad": "10", "unidad": "litros"})
    r.check("Recurso vacío rechazado", "error=" in destino(resp), destino(resp))

    for recurso, cantidad, unidad, tipo in LOTES:
        resp = coord.post(f"/emergencias/{emergencia_id}/lotes",
                          {"recurso": recurso, "cantidad": cantidad, "unidad": unidad, "tipo": tipo})
        r.check(f"Lote '{recurso}' cargado", destino(resp) == f"/emergencias/{emergencia_id}", destino(resp))

    detalle = coord.get(f"/emergencias/{emergencia_id}").text
    r.check("Los 3 lotes aparecen en el detalle", all(lote[0] in detalle for lote in LOTES))
    r.check("El lote de apoyo sale etiquetado como tal", "Apoyo" in detalle)

    resp = coord.post(f"/emergencias/{emergencia_id}/lotes/999999/borrar", {})
    r.check("Borrar un lote inexistente falla", "error=" in destino(resp), destino(resp))

    sobrante = id_de_lote(emergencia_id, "Generadores")
    if r.check("Lote a borrar encontrado en la base", sobrante is not None):
        coord.post(f"/emergencias/{emergencia_id}/lotes/{sobrante}/borrar", {})
        r.check("Lote borrado", "Generadores" not in coord.get(f"/emergencias/{emergencia_id}").text)
    return coord


def fase_publicar(r: Reporte, coord: Cliente, emergencia_id: int, segundos: int) -> datetime | None:
    r.fase("Centro Coordinador: publicación de la convocatoria")
    resp = coord.post(f"/emergencias/{emergencia_id}/publicar", {"ventana_fin": "2020-01-01T10:00"})
    r.check("Ventana en el pasado rechazada", "futura" in destino(resp), destino(resp))
    resp = coord.post(f"/emergencias/{emergencia_id}/publicar", {"ventana_fin": ""})
    r.check("Ventana vacía rechazada", "error=" in destino(resp), destino(resp))

    ventana = (datetime.now().astimezone() + timedelta(seconds=segundos)).replace(microsecond=0)
    resp = coord.post(f"/emergencias/{emergencia_id}/publicar", {"ventana_fin": ventana.isoformat()})
    if not r.check("Publicación aceptada", destino(resp) == f"/emergencias/{emergencia_id}", destino(resp)):
        return None
    detalle = coord.get(f"/emergencias/{emergencia_id}").text
    r.check("Estado pasa a 'Convocatoria abierta'", "Convocatoria abierta" in detalle)
    r.check("El detalle muestra el cierre de ofertas elegido",
            ventana.strftime("%d/%m/%Y %H:%M") in detalle, ventana.isoformat())
    return ventana


def fase_bonita_publicacion(r: Reporte, admin: BonitaClient, case_id: int, ventana: datetime) -> None:
    r.fase("Bonita: la convocatoria abrió la ventana de ofertas")
    activa = tarea_activa(admin, case_id)
    r.check(f"Tarea activa '{TAREA_TRAS_PUBLICAR}'", activa.startswith(TAREA_TRAS_PUBLICAR), activa)
    guardada = admin.get_case_variables(case_id).get("ventanaOfertasISO", "")
    r.check("ventanaOfertasISO = la ventana publicada", guardada.startswith(ventana.isoformat()[:16]),
            f"{guardada} vs {ventana.isoformat()}")

    for prefijo in (TAREA_TRAS_ALTA, TAREA_PUBLICAR):
        ejecutor = ejecutada_por(admin, case_id, prefijo)
        r.check(f"'{prefijo}…' la ejecutó '{USUARIO_COORDINADOR}'", ejecutor == USUARIO_COORDINADOR, ejecutor)


def fase_ya_publicada(r: Reporte, coord: Cliente, emergencia_id: int, ventana: datetime) -> None:
    r.fase("Centro Coordinador: la convocatoria publicada ya no se toca")
    resp = coord.post(f"/emergencias/{emergencia_id}/lotes",
                      {"recurso": "Tarde", "cantidad": "1", "unidad": "u"})
    r.check("No se pueden agregar lotes después de publicar", "publicada" in destino(resp), destino(resp))
    resp = coord.post(f"/emergencias/{emergencia_id}/publicar", {"ventana_fin": ventana.isoformat()})
    r.check("No se puede publicar dos veces", "publicada" in destino(resp), destino(resp))


def fase_ong_publicada(r: Reporte, app: str, ong: Cliente, emergencia_id: int, ventana: datetime) -> None:
    r.fase("ONG: ahora sí ve la convocatoria y sus lotes")
    listado = ong.get("/emergencias").text
    r.check("La convocatoria aparece en el listado", f'/emergencias/{emergencia_id}"' in listado)
    detalle = ong.get(f"/emergencias/{emergencia_id}")
    r.check("Detalle accesible con los lotes",
            detalle.status_code == 200 and all(lote[0] in detalle.text for lote in LOTES[:2]))
    ong2 = Cliente(app)
    ong2.login("ong.bomberos")
    r.check("La segunda ONG también la ve", ong2.get(f"/emergencias/{emergencia_id}").status_code == 200)
    r.check("ONG no puede publicar (403)",
            ong.post(f"/emergencias/{emergencia_id}/publicar",
                     {"ventana_fin": ventana.isoformat()}).status_code == 403)


def api_login(app: str, username: str) -> requests.Session:
    """Sesión contra la API JSON de la SPA (las ofertas no tienen pantalla Jinja)."""
    s = requests.Session()
    s.post(f"{app}/api/auth/login", json={"username": username, "password": DEMO_PASSWORD}, timeout=30)
    return s


def oferta(s: requests.Session, app: str, emergencia_id: int, cantidades: dict[int, int]) -> requests.Response:
    items = [{"lote_id": l, "recurso": "e2e", "cantidad": c} for l, c in cantidades.items()]
    return s.post(f"{app}/api/emergencias/{emergencia_id}/ofertas", json={"items": items}, timeout=30)


def fase_ofertas(r: Reporte, app: str, emergencia_id: int) -> requests.Session:
    r.fase("ONGs: ofertas versionadas (API de la SPA)")
    agua, frazadas = id_de_lote(emergencia_id, "Agua potable"), id_de_lote(emergencia_id, "Frazadas")
    cruz = api_login(app, "ong.cruzroja")
    v1 = oferta(cruz, app, emergencia_id, {agua: 3000, frazadas: 500})
    r.check("Cruz Roja oferta dos lotes en una versión",
            v1.status_code == 201 and v1.json()["version_actual"] == 1 and len(v1.json()["items"]) == 2, v1.text)
    v2 = oferta(cruz, app, emergencia_id, {agua: 4000})
    r.check("Reenviar crea la versión 2 y reemplaza los ítems",
            v2.status_code == 201 and v2.json()["version_actual"] == 2 and len(v2.json()["items"]) == 1, v2.text)
    r.check("Cantidad 0 rechazada (422)", oferta(cruz, app, emergencia_id, {agua: 0}).status_code == 422)
    bomb = api_login(app, "ong.bomberos")
    r.check("Bomberos oferta sobre la misma convocatoria",
            oferta(bomb, app, emergencia_id, {frazadas: 300}).status_code == 201)
    propias = bomb.get(f"{app}/api/emergencias/{emergencia_id}/ofertas", timeout=30).json()
    r.check("Cada ONG ve solo su oferta", [o["ong_nombre"] for o in propias] == ["Bomberos Voluntarios"], str(propias))
    todas = api_login(app, "coordinador.regional").get(f"{app}/api/emergencias/{emergencia_id}/ofertas", timeout=30).json()
    r.check("El Coordinador ve las dos ofertas", len(todas) == 2, str(todas))
    muni = api_login(app, "operador.municipal")
    r.check("El Municipio no puede ofertar (403)", oferta(muni, app, emergencia_id, {agua: 1}).status_code == 403)
    return cruz


def fase_auditor(r: Reporte, app: str, emergencia_id: int, ventana: datetime) -> None:
    r.fase("Auditor: consulta sin poder operar")
    aud = Cliente(app)
    aud.login("auditor")
    r.check("Ve la emergencia", aud.get(f"/emergencias/{emergencia_id}").status_code == 200)
    r.check("No puede registrar emergencias (403)", aud.get("/emergencias/nueva").status_code == 403)
    r.check("No puede cargar lotes (403)",
            aud.post(f"/emergencias/{emergencia_id}/lotes",
                     {"recurso": "a", "cantidad": "1", "unidad": "u"}).status_code == 403)
    r.check("No puede publicar (403)",
            aud.post(f"/emergencias/{emergencia_id}/publicar",
                     {"ventana_fin": ventana.isoformat()}).status_code == 403)

    r.fase("Cierre de sesión")
    aud.post("/logout", {})
    r.check("Después del logout no se accede", aud.get("/emergencias").status_code == 303)


def fase_timer(r: Reporte, admin: BonitaClient, case_id: int, ventana: datetime, espera: int,
               app: str, ong: requests.Session, emergencia_id: int) -> None:
    r.fase(f"Boundary timer: esperando el cierre de la ventana ({espera} s)")
    faltan = (ventana - datetime.now().astimezone()).total_seconds()
    if faltan > 0:
        time.sleep(faltan + 5)
    ok = esperar_tarea(admin, case_id, TAREA_TRAS_TIMER, 180)
    r.check(f"El timer disparó y el caso avanzó a '{TAREA_TRAS_TIMER}…'", ok, tarea_activa(admin, case_id))
    r.check(f"'{TAREA_TRAS_PUBLICAR}' se cerró sola", admin.find_task(case_id, TAREA_TRAS_PUBLICAR) is None)
    resp = oferta(ong, app, emergencia_id, {id_de_lote(emergencia_id, "Agua potable"): 1})
    r.check("Con la ventana cerrada la app rechaza ofertas", resp.status_code == 400, f"{resp.status_code} {resp.text}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="http://localhost:8000")
    ap.add_argument("--timer", type=int, metavar="SEGUNDOS",
                    help="publica con una ventana tan corta y espera a que dispare el boundary timer")
    args = ap.parse_args()

    settings = get_settings()
    r = Reporte()
    admin = BonitaClient(settings.bonita_base_url, settings.bonita_timeout_seconds)
    admin.login(settings.bonita_username, settings.bonita_password)

    fase_anonimo(r, args.app)
    ids = fase_municipio(r, args.app)
    if ids is None:
        return r.resumen()
    emergencia_id, case_id = ids

    fase_bonita_alta(r, admin, emergencia_id, case_id)
    ong = fase_ong_sin_publicar(r, args.app, emergencia_id)
    coord = fase_lotes(r, args.app, emergencia_id)

    ventana = fase_publicar(r, coord, emergencia_id, args.timer or 7200)
    if ventana is None:
        return r.resumen()

    fase_bonita_publicacion(r, admin, case_id, ventana)
    fase_ya_publicada(r, coord, emergencia_id, ventana)
    fase_ong_publicada(r, args.app, ong, emergencia_id, ventana)
    ong_api = fase_ofertas(r, args.app, emergencia_id)
    fase_auditor(r, args.app, emergencia_id, ventana)

    if args.timer:
        fase_timer(r, admin, case_id, ventana, args.timer, args.app, ong_api, emergencia_id)
    return r.resumen()


if __name__ == "__main__":
    sys.exit(main())
