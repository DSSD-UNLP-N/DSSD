"""Variantes del cierre con Bonita real: lo que `escenario_cierre.py` (el camino feliz) no cubre.

Publica siete emergencias a la vez (las ventanas vencen escalonadas) y recorre cada una hasta el cierre:

  A  subconjunto        Cruz Roja y Bomberos ofrecen; el Municipio adjudica solo a Cruz Roja. Se cierra una sola
                        referencia, la otra queda LIBERADA y Bomberos no recibe aviso de cierre.
  B  cobertura completa Cubre todo en la ronda 1 (va directo a adjudicar). Matriz de permisos, repeticiones
                        idempotentes, doble validación y lo que se rechaza después del cierre.
  C  ronda 2            REFORMULAR, segunda convocatoria, adjudicación y cierre de la referencia `r2` (la `r1` no se toca).
  D  Nacional caída     La API Nacional se apaga cuando se valida el cierre: el nodo de Bonita falla y se recupera con
                        `recuperar_cierre.py` (la API REST de Bonita no deja reintentarlo).
  D2 App caída          Bonita ya cerró en Nacional pero la app no responde al aviso: se recupera sin cerrar dos veces.
  E  concurrencia       Las dos ONGs finalizan al mismo tiempo y el Coordinador valida dos veces a la vez.
  F  eventos directos   Clave, estado, repetición y datos de un evento CIERRE mandado a mano.

Al final: nada comprometido en la API Nacional, ninguna reserva abierta y ningún caso abierto en Bonita.

Requisitos: Bonita con el proceso desplegado (con los conectores de cierre), app en :8001 y API Nacional en :8002 con el
seed y nada comprometido, las dos locales con SQLite. D y D2 apagan y vuelven a levantar esos dos servidores. Unos 20 min.

    python scripts/escenario_cierre_variantes.py
    python scripts/escenario_cierre_variantes.py --solo A,B      # algunas variantes
"""
from __future__ import annotations

import os
import argparse
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from escenario_adjudicacion import BOMBEROS, CRUZ_ROJA, comprometido, esperar  # noqa: E402
from escenario_cierre import sin_tareas  # noqa: E402
from escenario_tope import Escenario, crear_y_publicar  # noqa: E402
from recuperar_cierre import recuperar  # noqa: E402

from nacional_auth import nacional_get  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.integrations.bonita import BonitaClient  # noqa: E402
from app.seed import DEMO_PASSWORD  # noqa: E402

VENTANA_S = int(os.environ.get("ESCENARIO_VENTANA_S", 60)) + 15  # la primera emergencia vence a los 75 s
ESCALON_S = 12  # cada emergencia vence unos segundos después de la anterior
NACIONAL_DB = REPO / "nacional" / "nacional.db"
CLAVES = [(CRUZ_ROJA, "PARAMEDICO"), (BOMBEROS, "PARAMEDICO"), (CRUZ_ROJA, "AGUA_POTABLE")]


class Ctx:
    def __init__(self, app: str) -> None:
        self.app = app.rstrip("/")
        self.e = Escenario(app)
        cfg = get_settings()
        self.cfg = cfg
        self.nacional = cfg.nacional_base_url.rstrip("/")
        self.admin = BonitaClient(cfg.bonita_base_url, cfg.bonita_timeout_seconds)
        self.admin.login(cfg.bonita_username, cfg.bonita_password)
        self.emg: dict[str, dict] = {}  # variante -> {id, caso, lotes}

    # --- lectura -----------------------------------------------------------------------------------------------
    def detalle(self, emg: int, usuario: str = "coordinador.regional") -> dict:
        return self.e.get(usuario, f"/emergencias/{emg}").json()

    def estado_ref(self, ref: str) -> str | None:
        """Estado de una reserva, leído de la base local de la API Nacional."""
        con = sqlite3.connect(f"file:{NACIONAL_DB}?mode=ro", uri=True)
        try:
            fila = con.execute("select estado from adjudicacion where referencia_id = ?", (ref,)).fetchone()
        finally:
            con.close()
        return str(fila[0]).split(".")[-1] if fila else None

    def reservas_abiertas(self) -> int:
        con = sqlite3.connect(f"file:{NACIONAL_DB}?mode=ro", uri=True)
        try:
            return con.execute("select count(*) from adjudicacion where estado in ('RESERVADA', 'ADJUDICADA')").fetchone()[0]
        finally:
            con.close()

    def cierres(self, cuit: str, emg: int) -> list[dict]:
        todos = nacional_get(f"{self.nacional}/ongs/{cuit}/cierres", timeout=60).json()
        return [c for c in todos if c["referencia"].startswith(f"emg-{emg}-")]

    def avisos(self, usuario: str, emg: int, texto: str = "se cerró") -> list[str]:
        return [a["texto"] for a in self.e.get(usuario, "/notificaciones").json() if f"#{emg} {texto}" in a["texto"]]

    def tareas(self, caso: int) -> list[str]:
        return [t["displayName"] for t in self.admin.get_human_tasks(caso)]

    def espera_tarea(self, caso: int, prefijo: str, reintentos: int = 20) -> bool:
        return self.admin.wait_for_task(caso, prefijo, retries=reintentos) is not None

    def nodos_fallidos(self, caso: int) -> list[dict]:
        r = self.admin._request("GET", "/API/bpm/flowNode", params={"f": [f"caseId={caso}", "state=failed"], "p": 0, "c": 20})
        return r.json() if r.ok else []

    def sesion_nueva(self, usuario: str) -> requests.Session:
        s = requests.Session()
        s.post(f"{self.app}/api/auth/login", json={"username": usuario, "password": DEMO_PASSWORD}).raise_for_status()
        return s

    # --- pasos comunes -----------------------------------------------------------------------------------------
    def evaluada(self, emg: int, segundos: int = 400) -> dict | None:
        return esperar(self.e, emg, lambda d: d["evaluacion"] is not None, segundos)

    def adjudicar(self, nombre: str, emg: int, caso: int, cuits: list[str], decidir: bool = True) -> bool:
        e = self.e
        if decidir:
            r = e.post("coordinador.regional", f"/emergencias/{emg}/decision", {"decision": "PARCIAL"})
            e.check(f"{nombre}: el Coordinador sigue con la cobertura parcial", r.status_code == 200, r.text)
        e.check(f"{nombre}: Bonita espera «Adjudicar Ofertas»", self.espera_tarea(caso, "Adjudicar Ofertas"), self.tareas(caso))
        r = e.post("operador.municipal", f"/emergencias/{emg}/adjudicar", {"cuits": cuits})
        e.check(f"{nombre}: el Municipio adjudica a {len(cuits)} ONG", r.status_code == 200, r.text)
        d = esperar(e, emg, lambda d: d["estado"] == "EN_EJECUCION", 90)
        e.check(f"{nombre}: pasa a EN_EJECUCION", d is not None, d and d["estado"])
        ok = self.espera_tarea(caso, "Monitorear Ejecucion")
        e.check(f"{nombre}: Bonita espera «Monitorear Ejecucion»", ok, self.tareas(caso))
        return d is not None and ok

    def hasta_validar(self, nombre: str, emg: int, caso: int, finalizan: list[str]) -> None:
        """Monitorear y que finalicen las ONGs de `finalizan` (usuarios), una tras otra."""
        e = self.e
        e.esperar(f"{nombre}: el Coordinador monitorea", e.post("coordinador.regional", f"/emergencias/{emg}/monitorear", {}), 200)
        e.check(f"{nombre}: Bonita pasó a «Confirmar Finalizacion»", self.espera_tarea(caso, "Confirmar Finalizacion"), self.tareas(caso))
        for u in finalizan:
            e.esperar(f"{nombre}: {u} marca su actividad finalizada", e.post(u, f"/emergencias/{emg}/finalizar", {}), 200)
        e.check(f"{nombre}: Bonita pasó a «Validar Cierre»", self.espera_tarea(caso, "Validar Cierre"), self.tareas(caso))

    def cierre_ok(self, nombre: str, emg: int, caso: int, cerradas: list[tuple[str, str, str]],
                  liberadas: list[tuple[str, str, str]] = ()) -> None:
        """cerradas / liberadas: (usuario, cuit, ref). Todo lo que debe haber pasado después del cierre."""
        e = self.e
        d = esperar(e, emg, lambda d: d["estado"] == "RESUELTA", 120)
        e.check(f"{nombre}: la emergencia queda RESUELTA", d is not None, d and d["estado"])
        for usuario, cuit, ref in cerradas:
            e.check(f"{nombre}: {ref} CERRADA, con un solo cierre", self.estado_ref(ref) == "CERRADA" and len(self.cierres(cuit, emg)) == 1,
                    (self.estado_ref(ref), self.cierres(cuit, emg)))
            e.check(f"{nombre}: {usuario} recibió un solo aviso de cierre", len(self.avisos(usuario, emg)) == 1, self.avisos(usuario, emg))
        for usuario, cuit, ref in liberadas:
            e.check(f"{nombre}: {ref} sigue LIBERADA y no tiene cierre", self.estado_ref(ref) == "LIBERADA" and not self.cierres(cuit, emg),
                    (self.estado_ref(ref), self.cierres(cuit, emg)))
            e.check(f"{nombre}: {usuario} no recibió aviso de cierre", not self.avisos(usuario, emg), self.avisos(usuario, emg))
        e.check(f"{nombre}: el caso de Bonita terminó, sin tareas", sin_tareas(self.admin, caso), self.tareas(caso))


def en_paralelo(*llamadas):
    """Dispara las llamadas a la vez (con una barrera) y devuelve sus resultados en el mismo orden."""
    barrera = threading.Barrier(len(llamadas))
    resultados: list = [None] * len(llamadas)

    def correr(i, f):
        barrera.wait()
        try:
            resultados[i] = f()
        except Exception as exc:  # noqa: BLE001
            resultados[i] = exc

    hilos = [threading.Thread(target=correr, args=(i, f)) for i, f in enumerate(llamadas)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    return resultados


# --- apagar y levantar los servidores locales ---------------------------------------------------------------------
def pid_en_puerto(puerto: int) -> int | None:
    cmd = f"(Get-NetTCPConnection -LocalPort {puerto} -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess"
    out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True).stdout.strip()
    return int(out) if out.isdigit() else None


def apagar(puerto: int) -> bool:
    pid = pid_en_puerto(puerto)
    if pid is None:
        return False
    subprocess.run(["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force"], capture_output=True)
    for _ in range(20):
        if pid_en_puerto(puerto) is None:
            return True
        time.sleep(0.5)
    return False


def levantar(directorio: str, puerto: int, ruta_salud: str) -> bool:
    log = open(Path(tempfile.gettempdir()) / f"uvicorn-variantes-{puerto}.log", "ab")
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(REPO / directorio), "--port", str(puerto)],
        stdout=log, stderr=log, cwd=str(REPO / directorio), close_fds=True,
        creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    )
    limite = time.monotonic() + 40
    while time.monotonic() < limite:
        try:
            if requests.get(f"http://localhost:{puerto}{ruta_salud}", timeout=3).status_code < 500:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def recuperar_ok(ctx: Ctx, emg: int) -> bool:
    """Termina el cierre trabado con el script de recuperación (Bonita no deja reintentar el nodo por REST)."""
    try:
        for paso in recuperar(emg, ctx.app):
            print(f"       {paso}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"       falló: {exc}")
        return False


# --- variantes ----------------------------------------------------------------------------------------------------
def variante_a(ctx: Ctx) -> None:
    e, v = ctx.e, ctx.emg["A"]
    emg, caso = v["id"], v["caso"]
    print("\n== A: el Municipio adjudica solo a Cruz Roja")
    d = ctx.evaluada(emg)
    e.check("A: Bonita evaluó (EN_EVALUACION)", d is not None and d["estado"] == "EN_EVALUACION", d and d["estado"])
    if d is None or not ctx.adjudicar("A", emg, caso, [CRUZ_ROJA]):
        return
    e.check("A: Nacional: Cruz Roja ADJUDICADA y Bomberos LIBERADA",
            (ctx.estado_ref(f"emg-{emg}-r1-{CRUZ_ROJA}"), ctx.estado_ref(f"emg-{emg}-r1-{BOMBEROS}")) == ("ADJUDICADA", "LIBERADA"))
    db = ctx.detalle(emg, "ong.bomberos")
    e.check("A: Bomberos (no adjudicada) ve la ejecución sin filas propias", db["ejecucion"] is not None and db["ejecucion"]["ongs"] == [], db["ejecucion"])
    e.esperar("A: Bomberos no puede monitorear → 403", e.post("ong.bomberos", f"/emergencias/{emg}/monitorear", {}), 403)
    e.esperar("A: el Coordinador monitorea", e.post("coordinador.regional", f"/emergencias/{emg}/monitorear", {}), 200)
    e.esperar("A: Bomberos (no adjudicada) no puede finalizar → 403", e.post("ong.bomberos", f"/emergencias/{emg}/finalizar", {}), 403, "no fue adjudicada")
    e.check("A: Bonita espera «Confirmar Finalizacion»", ctx.espera_tarea(caso, "Confirmar Finalizacion"), ctx.tareas(caso))
    e.esperar("A: con una sola ONG adjudicada, Cruz Roja alcanza para finalizar", e.post("ong.cruzroja", f"/emergencias/{emg}/finalizar", {}), 200)
    e.check("A: Bonita pasó a «Validar Cierre» sin esperar a Bomberos", ctx.espera_tarea(caso, "Validar Cierre"), ctx.tareas(caso))
    e.esperar("A: el Coordinador valida el cierre", e.post("coordinador.regional", f"/emergencias/{emg}/validar-cierre", {}), 200)
    ctx.cierre_ok("A", emg, caso, [("ong.cruzroja", CRUZ_ROJA, f"emg-{emg}-r1-{CRUZ_ROJA}")],
                  [("ong.bomberos", BOMBEROS, f"emg-{emg}-r1-{BOMBEROS}")])
    avisos = [a["texto"] for a in e.get("ong.bomberos", "/notificaciones").json()]
    e.check("A: Bomberos conserva su aviso de «no seleccionada»", any(f"#{emg} no fue seleccionada" in a for a in avisos), avisos[:3])


def variante_b(ctx: Ctx) -> None:
    e, v = ctx.e, ctx.emg["B"]
    emg, caso = v["id"], v["caso"]
    print("\n== B: cobertura completa en la ronda 1, permisos y repeticiones")
    d = ctx.evaluada(emg)
    e.check("B: la cobertura es completa y va directo a ADJUDICACION", d is not None and d["estado"] == "ADJUDICACION"
            and d["evaluacion"]["cobertura_completa"] is True, d and (d["estado"], d["evaluacion"]["cobertura_completa"]))
    if d is None:
        return
    r = e.post("coordinador.regional", f"/emergencias/{emg}/decision", {"decision": "PARCIAL"})
    e.check("B: con cobertura completa no hay nada que decidir → error", r.status_code >= 400, r.status_code)
    if not ctx.adjudicar("B", emg, caso, [CRUZ_ROJA, BOMBEROS], decidir=False):
        return

    print("   -- permisos")
    base = f"{ctx.app}/api/emergencias/{emg}"
    for accion in ("monitorear", "finalizar", "validar-cierre"):
        e.check(f"B: sin sesión, {accion} → 401", requests.post(f"{base}/{accion}", json={}, timeout=30).status_code == 401)
    e.esperar("B: el Municipio no monitorea → 403", e.post("operador.municipal", f"/emergencias/{emg}/monitorear", {}), 403)
    e.esperar("B: el Auditor no monitorea → 403", e.post("auditor", f"/emergencias/{emg}/monitorear", {}), 403)
    e.esperar("B: la ONG no valida el cierre → 403", e.post("ong.cruzroja", f"/emergencias/{emg}/validar-cierre", {}), 403)
    e.esperar("B: el Coordinador no finaliza → 403", e.post("coordinador.regional", f"/emergencias/{emg}/finalizar", {}), 403)
    e.esperar("B: el Municipio no finaliza → 403", e.post("operador.municipal", f"/emergencias/{emg}/finalizar", {}), 403)
    e.esperar("B: antes de monitorear la ONG no finaliza → 409", e.post("ong.cruzroja", f"/emergencias/{emg}/finalizar", {}), 409)
    e.esperar("B: antes de monitorear no se valida el cierre → 409", e.post("coordinador.regional", f"/emergencias/{emg}/validar-cierre", {}), 409)

    print("   -- ejecución")
    e.esperar("B: el Coordinador monitorea", e.post("coordinador.regional", f"/emergencias/{emg}/monitorear", {}), 200)
    e.esperar("B: monitorear de nuevo → 409", e.post("coordinador.regional", f"/emergencias/{emg}/monitorear", {}), 409, "ya empezó")
    for usuario in ("auditor", "operador.municipal", "coordinador.regional"):
        ong = ctx.detalle(emg, usuario)["ejecucion"]["ongs"]
        e.check(f"B: {usuario} ve a las dos ONGs", sorted(o["cuit"] for o in ong) == sorted([CRUZ_ROJA, BOMBEROS]), ong)
    mia = ctx.detalle(emg, "ong.cruzroja")["ejecucion"]["ongs"]
    e.check("B: Cruz Roja solo ve su fila", [o["cuit"] for o in mia] == [CRUZ_ROJA], mia)
    e.check("B: Bonita espera «Confirmar Finalizacion»", ctx.espera_tarea(caso, "Confirmar Finalizacion"), ctx.tareas(caso))
    e.esperar("B: Cruz Roja finaliza", e.post("ong.cruzroja", f"/emergencias/{emg}/finalizar", {}), 200)
    e.esperar("B: Cruz Roja finaliza otra vez → idempotente", e.post("ong.cruzroja", f"/emergencias/{emg}/finalizar", {}), 200)
    e.check("B: con Bomberos pendiente Bonita sigue en «Confirmar Finalizacion»", ctx.espera_tarea(caso, "Confirmar Finalizacion", 3), ctx.tareas(caso))
    e.esperar("B: sin que Bomberos termine, no se valida el cierre → 409", e.post("coordinador.regional", f"/emergencias/{emg}/validar-cierre", {}), 409, "Bomberos")
    e.esperar("B: Bomberos finaliza (la última)", e.post("ong.bomberos", f"/emergencias/{emg}/finalizar", {}), 200)
    e.esperar("B: Bomberos finaliza otra vez → idempotente", e.post("ong.bomberos", f"/emergencias/{emg}/finalizar", {}), 200)
    e.check("B: Bonita pasó a «Validar Cierre»", ctx.espera_tarea(caso, "Validar Cierre"), ctx.tareas(caso))
    e.check("B: el detalle dice que todas finalizaron", ctx.detalle(emg)["ejecucion"]["todas_finalizadas"] is True)

    print("   -- cierre")
    e.esperar("B: el Coordinador valida el cierre", e.post("coordinador.regional", f"/emergencias/{emg}/validar-cierre", {}), 200)
    r = e.post("coordinador.regional", f"/emergencias/{emg}/validar-cierre", {})
    e.check("B: validar de nuevo → 409 (ya validado o ya resuelta)", r.status_code == 409, f"{r.status_code} {r.text}")
    ctx.cierre_ok("B", emg, caso, [("ong.cruzroja", CRUZ_ROJA, f"emg-{emg}-r1-{CRUZ_ROJA}"), ("ong.bomberos", BOMBEROS, f"emg-{emg}-r1-{BOMBEROS}")])
    e.esperar("B: ya resuelta, finalizar → 409", e.post("ong.cruzroja", f"/emergencias/{emg}/finalizar", {}), 409)
    e.esperar("B: ya resuelta, monitorear → 409", e.post("coordinador.regional", f"/emergencias/{emg}/monitorear", {}), 409)
    e.esperar("B: ya resuelta, validar → 409", e.post("coordinador.regional", f"/emergencias/{emg}/validar-cierre", {}), 409)
    d = ctx.detalle(emg)
    e.check("B: el detalle resuelto muestra las dos ONGs finalizadas y el cierre validado",
            d["estado"] == "RESUELTA" and d["ejecucion"]["cierre_validado"] is True
            and all(o["estado"] == "FINALIZADA" for o in d["ejecucion"]["ongs"]), d["ejecucion"])

    print("   -- avisos")
    avisos = e.get("ong.cruzroja", "/notificaciones").json()
    cierre = next((a for a in avisos if f"#{emg} se cerró" in a["texto"]), None)
    e.check("B: el aviso de cierre llega sin leer", cierre is not None and cierre["leida"] is False, cierre)
    if cierre:
        e.esperar("B: Bomberos no marca el aviso de Cruz Roja → 404", e.post("ong.bomberos", f"/notificaciones/{cierre['id']}/leida", {}), 404)
        e.esperar("B: Cruz Roja marca su aviso", e.post("ong.cruzroja", f"/notificaciones/{cierre['id']}/leida", {}), 200)
        ahora = next(a for a in e.get("ong.cruzroja", "/notificaciones").json() if a["id"] == cierre["id"])
        e.check("B: el aviso quedó leído", ahora["leida"] is True)
    e.check("B: el Coordinador no tiene avisos", e.get("coordinador.regional", "/notificaciones").json() == [])


def variante_c_parte1(ctx: Ctx) -> None:
    e, v = ctx.e, ctx.emg["C"]
    emg, caso = v["id"], v["caso"]
    print("\n== C (1/2): reformulación")
    d = ctx.evaluada(emg)
    e.check("C: la ronda 1 cubre 66,7 % y queda en EN_EVALUACION", d is not None and d["estado"] == "EN_EVALUACION"
            and d["evaluacion"]["porcentaje_cobertura"] == 66.7, d and (d["estado"], d["evaluacion"]["porcentaje_cobertura"]))
    if d is None:
        return
    r = e.post("coordinador.regional", f"/emergencias/{emg}/decision", {"decision": "REFORMULAR"})
    e.check("C: REFORMULAR → vuelve a REGISTRADA en la ronda 2", r.status_code == 200 and r.json()["estado"] == "REGISTRADA", r.text)
    e.check("C: Bonita volvió a «Revisar Informacion»", ctx.espera_tarea(caso, "Revisar Informacion"), ctx.tareas(caso))
    e.check("C: la reserva de la ronda 1 se liberó", ctx.estado_ref(f"emg-{emg}-r1-{CRUZ_ROJA}") == "LIBERADA")
    v["fin2"] = datetime.now().astimezone() + timedelta(seconds=110)
    r = e.post("coordinador.regional", f"/emergencias/{emg}/publicar", {"ventana_fin": v["fin2"].isoformat(timespec="seconds")})
    e.check("C: el Coordinador publica la ronda 2", r.status_code == 200 and r.json()["estado"] == "CONVOCATORIA", r.text)
    e.esperar("C: Cruz Roja ofrece los 3000 L completos", e.ofrecer("ong.cruzroja", emg, (v["lotes"]["AGUA_POTABLE"], 3000)), 201)
    v["ok1"] = True


def variante_c_parte2(ctx: Ctx) -> None:
    e, v = ctx.e, ctx.emg["C"]
    emg, caso = v["id"], v["caso"]
    if not v.get("ok1"):
        return
    print(f"\n== C (2/2): ronda 2 (vence {v['fin2']:%H:%M:%S}) y cierre de la referencia r2")
    d = esperar(e, emg, lambda d: d["evaluacion"] is not None and d["evaluacion"]["ronda"] == 2, 360)
    e.check("C: la ronda 2 cubre todo y va a ADJUDICACION", d is not None and d["estado"] == "ADJUDICACION", d and d["estado"])
    if d is None or not ctx.adjudicar("C", emg, caso, [CRUZ_ROJA], decidir=False):
        return
    r1, r2 = f"emg-{emg}-r1-{CRUZ_ROJA}", f"emg-{emg}-r2-{CRUZ_ROJA}"
    e.check("C: Nacional: r1 LIBERADA y r2 ADJUDICADA", (ctx.estado_ref(r1), ctx.estado_ref(r2)) == ("LIBERADA", "ADJUDICADA"))
    ctx.hasta_validar("C", emg, caso, ["ong.cruzroja"])
    e.esperar("C: el Coordinador valida el cierre", e.post("coordinador.regional", f"/emergencias/{emg}/validar-cierre", {}), 200)
    ctx.cierre_ok("C", emg, caso, [("ong.cruzroja", CRUZ_ROJA, r2)])
    cierres = [c["referencia"] for c in ctx.cierres(CRUZ_ROJA, emg)]
    e.check("C: el único cierre es el de la ronda 2 y la ronda 1 sigue LIBERADA", cierres == [r2] and ctx.estado_ref(r1) == "LIBERADA", cierres)
    e.check("C: Nacional: los 3000 L de agua volvieron", comprometido(ctx.nacional, CRUZ_ROJA, "AGUA_POTABLE") == 0)


def variante_e(ctx: Ctx) -> None:
    e, v = ctx.e, ctx.emg["E"]
    emg, caso = v["id"], v["caso"]
    print("\n== E: las dos ONGs finalizan a la vez y el Coordinador valida dos veces a la vez")
    d = ctx.evaluada(emg)
    if d is None or not ctx.adjudicar("E", emg, caso, [CRUZ_ROJA, BOMBEROS]):
        return
    e.esperar("E: el Coordinador monitorea", e.post("coordinador.regional", f"/emergencias/{emg}/monitorear", {}), 200)
    e.check("E: Bonita espera «Confirmar Finalizacion»", ctx.espera_tarea(caso, "Confirmar Finalizacion"), ctx.tareas(caso))
    for u in ("ong.cruzroja", "ong.bomberos"):
        e.como(u)
    ra, rb = en_paralelo(lambda: e.post("ong.cruzroja", f"/emergencias/{emg}/finalizar", {}),
                         lambda: e.post("ong.bomberos", f"/emergencias/{emg}/finalizar", {}))
    estados = [getattr(r, "status_code", r) for r in (ra, rb)]
    e.check("E: las dos finalizaciones simultáneas responden bien", estados == [200, 200], [getattr(r, "text", r) for r in (ra, rb)])
    d = ctx.detalle(emg)
    e.check("E: las dos ofertas quedan FINALIZADAS", d["ejecucion"]["todas_finalizadas"] is True, d["ejecucion"])
    e.check("E: Bonita pasó a «Validar Cierre» (no quedó trabada en «Confirmar Finalizacion»)",
            ctx.espera_tarea(caso, "Validar Cierre", 15), ctx.tareas(caso))
    if "Validar Cierre" not in " ".join(ctx.tareas(caso)):
        return
    otra = ctx.sesion_nueva("coordinador.regional")
    e.como("coordinador.regional")
    ra, rb = en_paralelo(lambda: e.post("coordinador.regional", f"/emergencias/{emg}/validar-cierre", {}),
                         lambda: otra.post(f"{ctx.app}/api/emergencias/{emg}/validar-cierre", json={}, timeout=120))
    estados = sorted(getattr(r, "status_code", 0) for r in (ra, rb))
    e.check("E: dos validaciones simultáneas → al menos una vale y la otra no rompe nada (Bonita ignora la segunda)",
            200 in estados and set(estados) <= {200, 409, 502}, estados)
    ctx.cierre_ok("E", emg, caso, [("ong.cruzroja", CRUZ_ROJA, f"emg-{emg}-r1-{CRUZ_ROJA}"), ("ong.bomberos", BOMBEROS, f"emg-{emg}-r1-{BOMBEROS}")])


def variante_d(ctx: Ctx) -> None:
    e, v = ctx.e, ctx.emg["D"]
    emg, caso = v["id"], v["caso"]
    print("\n== D: la API Nacional está caída cuando se valida el cierre")
    d = ctx.evaluada(emg)
    if d is None or not ctx.adjudicar("D", emg, caso, [CRUZ_ROJA, BOMBEROS]):
        return
    ctx.hasta_validar("D", emg, caso, ["ong.cruzroja", "ong.bomberos"])
    e.check("D: se apagó la API Nacional", apagar(8002))
    e.esperar("D: el Coordinador valida el cierre (la app solo avanza la tarea de Bonita)",
              e.post("coordinador.regional", f"/emergencias/{emg}/validar-cierre", {}), 200)
    fallidos: list[dict] = []
    for _ in range(15):
        fallidos = ctx.nodos_fallidos(caso)
        if fallidos:
            break
        time.sleep(2)
    e.check("D: Bonita deja «Liberar Recursos y Notificar Cierre» como nodo fallido", bool(fallidos),
            [(n.get("displayName"), n.get("state")) for n in ctx.admin._request("GET", "/API/bpm/flowNode", params={"f": f"caseId={caso}", "p": 0, "c": 20}).json()])
    d = ctx.detalle(emg)
    e.check("D: mientras tanto la emergencia sigue EN_EJECUCION, con el cierre validado", d["estado"] == "EN_EJECUCION"
            and d["ejecucion"]["cierre_validado"] is True, (d["estado"], d["ejecucion"]))
    e.esperar("D: validar de nuevo no repite nada → 409", e.post("coordinador.regional", f"/emergencias/{emg}/validar-cierre", {}), 409)
    e.check("D: sin la API Nacional el catálogo da 503 y no 500", e.get("coordinador.regional", "/tipos-recurso").status_code == 503)
    e.check("D: se levantó la API Nacional", levantar("nacional", 8002, "/ongs"))
    e.check("D: recuperar_cierre.py termina el cierre trabado", recuperar_ok(ctx, emg))
    ctx.cierre_ok("D", emg, caso, [("ong.cruzroja", CRUZ_ROJA, f"emg-{emg}-r1-{CRUZ_ROJA}"), ("ong.bomberos", BOMBEROS, f"emg-{emg}-r1-{BOMBEROS}")])


def variante_d2(ctx: Ctx) -> None:
    e, v = ctx.e, ctx.emg["D2"]
    emg, caso = v["id"], v["caso"]
    print("\n== D2: Bonita cierra en la API Nacional pero la app no responde al aviso")
    d = ctx.evaluada(emg)
    if d is None or not ctx.adjudicar("D2", emg, caso, [BOMBEROS]):
        return
    ctx.hasta_validar("D2", emg, caso, ["ong.bomberos"])
    ref = f"emg-{emg}-r1-{BOMBEROS}"
    e.check("D2: se apagó la app", apagar(8001))
    # La app no está: se completa «Validar Cierre» directo en Bonita, como lo haría el Portal.
    ctx.admin.login("coordinador.regional", ctx.cfg.bonita_test_password)
    ctx.admin.complete_task_as_self(ctx.admin.find_task(caso, "Validar Cierre")["id"])
    ctx.admin.login(ctx.cfg.bonita_username, ctx.cfg.bonita_password)
    fallidos: list[dict] = []
    for _ in range(15):
        fallidos = ctx.nodos_fallidos(caso)
        if fallidos:
            break
        time.sleep(2)
    e.check("D2: Bonita deja el nodo de cierre como fallido (la app no respondió)", bool(fallidos))
    e.check("D2: pero la API Nacional ya había cerrado la referencia", ctx.estado_ref(ref) == "CERRADA", ctx.estado_ref(ref))
    e.check("D2: se levantó la app", levantar("backend", 8001, "/api/meta"))
    e.sesiones.clear()
    e.check("D2: recuperar_cierre.py termina el cierre trabado", recuperar_ok(ctx, emg))
    ctx.cierre_ok("D2", emg, caso, [("ong.bomberos", BOMBEROS, ref)])
    e.check("D2: la recuperación repitió el cierre sin restar de nuevo (sigue habiendo un solo cierre)", len(ctx.cierres(BOMBEROS, emg)) == 1)


def variante_f(ctx: Ctx) -> None:
    e = ctx.e
    emg = ctx.emg["A"]["id"]
    print("\n== F: eventos CIERRE mandados a mano")
    url = f"{ctx.app}/api/bonita/emergencias/{{}}/eventos"
    clave = {"X-Api-Key": ctx.cfg.bonita_api_key}
    cuerpo = {"tipo": "CIERRE", "cuits": [CRUZ_ROJA]}
    e.check("F: sin clave → 401/403", requests.post(url.format(emg), json=cuerpo, timeout=30).status_code in (401, 403))
    e.check("F: con una clave equivocada → 401/403", requests.post(url.format(emg), json=cuerpo, headers={"X-Api-Key": "otra"}, timeout=30).status_code in (401, 403))
    antes = len(e.get("ong.cruzroja", "/notificaciones").json())
    e.check("F: repetir el evento en una emergencia ya resuelta → 204", requests.post(url.format(emg), json=cuerpo, headers=clave, timeout=30).status_code == 204)
    e.check("F: y no duplica los avisos", len(e.get("ong.cruzroja", "/notificaciones").json()) == antes)
    e.check("F: emergencia inexistente → 404", requests.post(url.format(999999), json=cuerpo, headers=clave, timeout=30).status_code == 404)
    e.check("F: sin ONGs → 422", requests.post(url.format(emg), json={"tipo": "CIERRE", "cuits": []}, headers=clave, timeout=30).status_code == 422)
    nueva = e.post("operador.municipal", "/emergencias", {"tipo": "otro", "nivel_gravedad": "BAJO", "zona_afectada": "F", "descripcion": "x"}).json()
    e.check("F: una emergencia que no está en ejecución no se cierra → 409",
            requests.post(url.format(nueva["id"]), json=cuerpo, headers=clave, timeout=30).status_code == 409)
    ctx.admin.delete_case(nueva["bonita_case_id"])  # el caso que abrió esta emergencia de prueba


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="http://localhost:8001")
    ap.add_argument("--solo", default="", help="variantes a correr, p. ej. A,B (D y D2 apagan servidores)")
    args = ap.parse_args()
    ctx = Ctx(args.app)
    e = ctx.e
    pedidas = set(filter(None, args.solo.upper().split(","))) or {"A", "B", "C", "D", "D2", "E", "F"}

    print("== Preparación")
    previos = {k: comprometido(ctx.nacional, *k) for k in CLAVES}
    e.check("La API Nacional no tiene nada comprometido al empezar", not any(previos.values()), previos)
    e.check("Bonita no tiene casos abiertos", ctx.admin._request("GET", "/API/bpm/case", params={"p": 0, "c": 50}).json() == [])
    base = datetime.now().astimezone() + timedelta(seconds=VENTANA_S)
    plan = [  # variante, zona, lotes, ofertas (usuario, cantidad)
        ("A", [("PARAMEDICO", 10, "PRINCIPAL")], [("ong.cruzroja", 1), ("ong.bomberos", 1)]),
        ("B", [("PARAMEDICO", 2, "PRINCIPAL")], [("ong.cruzroja", 1), ("ong.bomberos", 1)]),
        ("E", [("PARAMEDICO", 10, "PRINCIPAL")], [("ong.cruzroja", 1), ("ong.bomberos", 1)]),
        ("C", [("AGUA_POTABLE", 3000, "PRINCIPAL")], [("ong.cruzroja", 2000)]),
        ("D", [("PARAMEDICO", 10, "PRINCIPAL")], [("ong.cruzroja", 1), ("ong.bomberos", 1)]),
        ("D2", [("PARAMEDICO", 10, "PRINCIPAL")], [("ong.bomberos", 2)]),
    ]
    i = 0
    for nombre, lotes, ofertas in plan:
        if nombre not in pedidas and not (nombre == "A" and "F" in pedidas):
            continue
        fin = base + timedelta(seconds=i * ESCALON_S)
        i += 1
        emg, caso, ids = crear_y_publicar(e, f"Variante {nombre}", "ALTO", lotes, fin)
        ctx.emg[nombre] = {"id": emg, "caso": caso, "lotes": ids}
        for usuario, n in ofertas:
            e.esperar(f"{nombre}: {usuario} ofrece {n}", e.ofrecer(usuario, emg, (ids[lotes[0][0]], n)), 201)
        print(f"     {nombre} = emergencia #{emg} (caso {caso}) · vence {fin:%H:%M:%S}")

    # C se reformula apenas se evalúa; su segunda mitad espera a que venza la ronda 2.
    pasos = [("C", variante_c_parte1), ("A", variante_a), ("B", variante_b), ("E", variante_e), ("C", variante_c_parte2),
             ("D", variante_d), ("D2", variante_d2), ("F", variante_f)]
    for nombre, paso in pasos:
        if nombre not in pedidas:
            continue
        try:
            paso(ctx)
        except Exception:  # noqa: BLE001
            e.check(f"{nombre}: la variante terminó sin excepciones", False, traceback.format_exc(limit=4))

    print("\n== Al final")
    e.check("Nacional: nada comprometido, como al empezar", {k: comprometido(ctx.nacional, *k) for k in CLAVES} == previos,
            {k: comprometido(ctx.nacional, *k) for k in CLAVES})
    e.check("Nacional: ninguna reserva quedó RESERVADA o ADJUDICADA", ctx.reservas_abiertas() == 0, ctx.reservas_abiertas())
    abiertos = ctx.admin._request("GET", "/API/bpm/case", params={"p": 0, "c": 50}).json()
    e.check("Bonita: ningún caso abierto", abiertos == [], [c["id"] for c in abiertos])
    print(f"\n{e.ok}/{e.total} verificaciones OK")
    return 0 if e.ok == e.total else 1


if __name__ == "__main__":
    sys.exit(main())
