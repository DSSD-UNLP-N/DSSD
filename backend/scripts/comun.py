"""Piezas que comparten los escenarios y guiones de prueba con Bonita real: el `sys.path` (para importar `app` y los
otros scripts), las ONGs del seed, las esperas y el cliente HTTP de los escenarios por API (`Escenario`)."""
from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from nacional_auth import nacional_get  # noqa: E402
from app.integrations.bonita import BonitaClient  # noqa: E402
from app.seed import DEMO_PASSWORD  # noqa: E402

CRUZ_ROJA, BOMBEROS = "30-54666544-5", "30-68522415-9"
# Segundos de la ventana de ofertas. Tiene que alcanzar para crear las emergencias y cargar las ofertas (unos 20 s en una PC
# cargada); es casi todo lo que tarda cada escenario, así que se puede achicar o agrandar con ESCENARIO_VENTANA_S.
VENTANA_S = int(os.environ.get("ESCENARIO_VENTANA_S", 60))


def esperar(cond, segundos: float, desde: datetime | None = None, cada: float = 1.0):
    """Llama a `cond()` cada `cada` s hasta que devuelva algo verdadero (y lo devuelve) o pasen `segundos` (None). Con
    `desde` (el cierre de la ventana) primero duerme hasta ese momento, sin consultar: antes no hay nada que ver;
    `segundos` cuenta desde ahí."""
    if desde is not None:
        time.sleep(max(0.0, (desde - datetime.now().astimezone()).total_seconds()))
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        valor = cond()
        if valor:
            return valor
        time.sleep(cada)
    return None


def comprometido(nacional: str, cuit: str, tipo: str) -> int:
    ficha = nacional_get(f"{nacional}/ongs/{cuit}", timeout=60).json()
    return next(i["cantidad_comprometida"] for i in ficha["inventario"] if i["tipo_recurso"] == tipo)


def tarea_activa(admin: BonitaClient, case_id) -> str:
    tareas = admin.get_human_tasks(case_id)
    return tareas[0]["displayName"] if tareas else "(ninguna)"


def esperar_tarea_activa(admin: BonitaClient, caso: int, prefijo: str, segundos: int = 40) -> str:
    def activa():
        nombre = tarea_activa(admin, caso)
        return nombre if nombre.startswith(prefijo) else None
    return esperar(activa, segundos) or tarea_activa(admin, caso)


def sin_tareas(admin: BonitaClient, caso: int, segundos: int = 60) -> bool:
    return bool(esperar(lambda: not admin.get_human_tasks(caso), segundos))


def esperar_resuelta(api: str, emergencia: int, segundos: int = 60) -> bool:
    """La tarea humana ya terminó, pero el servicio «Liberar Recursos y Notificar Cierre» (login, cierre en Nacional, aviso
    a la app) corre después en el motor: hasta que la app recibe el evento CIERRE la emergencia no está RESUELTA."""
    sesion = requests.Session()
    sesion.post(f"{api}/api/auth/login", json={"username": "coordinador.regional", "password": DEMO_PASSWORD}, timeout=30)
    return bool(esperar(lambda: sesion.get(f"{api}/api/emergencias/{emergencia}", timeout=30).json().get("estado") == "RESUELTA",
                        segundos))


class Escenario:
    def __init__(self, app: str) -> None:
        self.app = app.rstrip("/")
        self.ok = self.total = 0
        self.sesiones: dict[str, requests.Session] = {}
        self._lock = threading.Lock()  # las variantes del cierre corren en hilos: contadores, líneas y logins no se pisan

    def check(self, nombre: str, condicion: bool, detalle: object = "") -> None:
        with self._lock:
            self.total += 1
            self.ok += bool(condicion)
            print(f"  [{'OK   ' if condicion else 'FALLA'}] {nombre}" + ("" if condicion else f"  -> {detalle}"), flush=True)

    def como(self, usuario: str) -> requests.Session:
        with self._lock:
            if usuario not in self.sesiones:
                s = requests.Session()
                r = s.post(f"{self.app}/api/auth/login", json={"username": usuario, "password": DEMO_PASSWORD})
                r.raise_for_status()
                self.sesiones[usuario] = s
            return self.sesiones[usuario]

    def get(self, usuario: str, ruta: str) -> requests.Response:
        return self.como(usuario).get(f"{self.app}/api{ruta}", timeout=120)

    def post(self, usuario: str, ruta: str, cuerpo: dict) -> requests.Response:
        return self.como(usuario).post(f"{self.app}/api{ruta}", json=cuerpo, timeout=120)

    def ofrecer(self, ong: str, emergencia: int, *pares: tuple[int, int]) -> requests.Response:
        """pares: (lote_id, cantidad). Sin pares = retirar toda la oferta."""
        return self.post(ong, f"/emergencias/{emergencia}/ofertas",
                         {"items": [{"lote_id": l, "recurso": "x", "cantidad": n} for l, n in pares]})

    def esperar(self, nombre: str, r: requests.Response, status: int, *textos: str) -> dict:
        cuerpo = r.json() if r.content else {}
        detalle = cuerpo.get("detail", "") if isinstance(cuerpo, dict) else ""
        ok = r.status_code == status and all(t in detalle for t in textos)
        self.check(nombre, ok, f"{r.status_code} {detalle or cuerpo}")
        return cuerpo


def esperar_detalle(e: Escenario, emergencia: int, condicion, segundos: int, desde: datetime | None = None) -> dict | None:
    """Mira el detalle del Coordinador cada 1,5 s hasta que `condicion(detalle)` sea cierta y lo devuelve (None si no).
    `desde` como en `esperar`."""
    def mirar():
        try:
            d = e.get("coordinador.regional", f"/emergencias/{emergencia}").json()
        except requests.ConnectionError:  # el servidor cerró la conexión inactiva
            return None
        return d if condicion(d) else None
    return esperar(mirar, segundos, desde, cada=1.5)


def _ok(r: requests.Response) -> requests.Response:
    if not r.ok:
        raise RuntimeError(f"{r.request.method} {r.url} → {r.status_code}: {r.text[:300]}")
    return r


def crear(e: Escenario, zona: str, gravedad: str, lotes: list[tuple[str, int, str]]) -> tuple[int, int, dict[str, int]]:
    """Registra la emergencia (instancia el caso en Bonita, lo lento) y le carga los lotes, sin publicarla."""
    r = e.post("operador.municipal", "/emergencias", {
        "tipo": "inundacion", "nivel_gravedad": gravedad, "zona_afectada": zona,
        "descripcion": "Escenario de prueba del tope de ofertas (E3)"})
    emergencia = _ok(r).json()
    ids = {}
    for tipo_recurso, cantidad, tipo in lotes:
        r = e.post("coordinador.regional", f"/emergencias/{emergencia['id']}/lotes",
                   {"tipo_recurso": tipo_recurso, "cantidad": cantidad, "tipo": tipo})
        ids[tipo_recurso] = _ok(r).json()["id"]
    return emergencia["id"], emergencia["bonita_case_id"], ids


def publicar(e: Escenario, emergencia: int, ventana: datetime) -> None:
    _ok(e.post("coordinador.regional", f"/emergencias/{emergencia}/publicar", {"ventana_fin": ventana.isoformat(timespec="seconds")}))


def crear_y_publicar(e: Escenario, zona: str, gravedad: str, lotes: list[tuple[str, int, str]],
                     ventana: datetime) -> tuple[int, int, dict[str, int]]:
    emergencia, caso, ids = crear(e, zona, gravedad, lotes)
    publicar(e, emergencia, ventana)
    return emergencia, caso, ids


def retirar_previas(e: Escenario, propias: set[int]) -> int:
    """Corridas anteriores dejan convocatorias abiertas con ofertas que descuentan inventario."""
    retiradas = 0
    for ong in ("ong.cruzroja", "ong.bomberos"):
        for em in e.get(ong, "/emergencias").json():
            if em["id"] in propias or em["estado"] != "CONVOCATORIA":
                continue
            for o in e.get(ong, f"/emergencias/{em['id']}/ofertas").json():
                if not o["retirada"] and e.ofrecer(ong, em["id"]).status_code == 201:
                    retiradas += 1
    return retiradas
