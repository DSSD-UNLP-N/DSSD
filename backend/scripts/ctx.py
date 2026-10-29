"""Contexto de los escenarios de cierre con Bonita real (escenario_cierre_variantes.py y escenario_jwt.py): el `Ctx` con las
lecturas y los pasos comunes, y cómo apagar y levantar los servidores locales."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import requests

from comun import BOMBEROS, CRUZ_ROJA, Escenario, esperar_detalle, sin_tareas
from recuperar_cierre import recuperar
from nacional_auth import nacional_get
from app.core.config import get_settings
from app.integrations.bonita import BonitaClient
from app.seed import DEMO_PASSWORD

REPO = Path(__file__).resolve().parents[2]
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
        return esperar_detalle(self.e, emg, lambda d: d["evaluacion"] is not None, segundos)

    def adjudicar(self, nombre: str, emg: int, caso: int, cuits: list[str], decidir: bool = True) -> bool:
        e = self.e
        if decidir:
            r = e.post("coordinador.regional", f"/emergencias/{emg}/decision", {"decision": "PARCIAL"})
            e.check(f"{nombre}: el Coordinador sigue con la cobertura parcial", r.status_code == 200, r.text)
        e.check(f"{nombre}: Bonita espera «Adjudicar Ofertas»", self.espera_tarea(caso, "Adjudicar Ofertas"), self.tareas(caso))
        r = e.post("operador.municipal", f"/emergencias/{emg}/adjudicar", {"cuits": cuits})
        e.check(f"{nombre}: el Municipio adjudica a {len(cuits)} ONG", r.status_code == 200, r.text)
        d = esperar_detalle(e, emg, lambda d: d["estado"] == "EN_EJECUCION", 90)
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
        d = esperar_detalle(e, emg, lambda d: d["estado"] == "RESUELTA", 120)
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


def levantar(directorio: str, puerto: int, ruta_salud: str, env_extra: dict[str, str] | None = None) -> bool:
    """Levanta la app o la API Nacional en segundo plano, con `env_extra` sumado al entorno, y espera a que responda."""
    log = open(Path(tempfile.gettempdir()) / f"uvicorn-variantes-{puerto}.log", "ab")
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(REPO / directorio), "--port", str(puerto)],
        stdout=log, stderr=log, cwd=str(REPO / directorio), close_fds=True, env={**os.environ, **(env_extra or {})},
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
