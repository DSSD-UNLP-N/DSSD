"""Lo propio del JWT con Bonita real: cuentas de servicio, claves rotadas y tokens que vencen.

  G  clave de Bonita rotada   Nacional cambia la clave de `bonita-service` justo antes de validar el cierre: `loginNacional`
                              recibe 401 y el nodo de Bonita queda fallido. No se cerró nada en Nacional, la app sigue
                              funcionando (usa su propia cuenta) y, con la clave de vuelta, `recuperar_cierre.py` lo termina.
  H  token inválido o vencido La API Nacional se reinicia con otro `JWT_SECRET` y tokens de 1 minuto: la app, que tenía un token
                              guardado, vuelve a entrar sola (401 -> login -> reintento), y lo vuelve a hacer cuando vence.

Al final: nada comprometido en la API Nacional, ninguna reserva abierta y ningún caso abierto en Bonita.

Requisitos: igual que escenario_cierre_variantes.py (Bonita con el `.bos` de JWT, app en :8001, API Nacional en :8002 con
SQLite, seed y nada comprometido). H apaga y vuelve a levantar la API Nacional. Unos 8 minutos.

    python scripts/escenario_jwt.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from escenario_adjudicacion import BOMBEROS, CRUZ_ROJA, VENTANA_S, comprometido, esperar  # noqa: E402
from escenario_cierre_variantes import CLAVES, REPO, Ctx, apagar, levantar, recuperar_ok  # noqa: E402
from escenario_tope import crear_y_publicar  # noqa: E402

COORDINADOR = "coordinador.regional"
CLAVE_ROTADA = "clave-rotada-de-prueba"


def fijar_clave_de_bonita(clave: str | None) -> None:
    """Corre el seed de Nacional con otra BONITA_SERVICE_PASSWORD (el seed vuelve a fijar la clave de las cuentas de servicio)."""
    env = {**os.environ}
    if clave:
        env["BONITA_SERVICE_PASSWORD"] = clave
    else:
        env.pop("BONITA_SERVICE_PASSWORD", None)
    subprocess.run([sys.executable, "-m", "app.seed"], cwd=str(REPO / "nacional"), env=env, check=True, capture_output=True)


def levantar_nacional_con(env_extra: dict[str, str]) -> bool:
    """Como `levantar`, pero con variables de entorno propias (otro secreto, otro vencimiento)."""
    log = open(Path(tempfile.gettempdir()) / "uvicorn-jwt-8002.log", "ab")
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(REPO / "nacional"), "--port", "8002"],
        stdout=log, stderr=log, cwd=str(REPO / "nacional"), close_fds=True, env={**os.environ, **env_extra},
        creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    )
    limite = time.monotonic() + 40
    while time.monotonic() < limite:
        try:
            if requests.get("http://localhost:8002/health", timeout=3).status_code < 500:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def escenario_g(ctx: Ctx) -> None:
    e = ctx.e
    print("\n== G: Nacional rotó la clave de Bonita justo antes de validar el cierre")
    fin = datetime.now().astimezone() + timedelta(seconds=VENTANA_S)
    emg, caso, ids = crear_y_publicar(e, "Escenario JWT G", "ALTO", [("PARAMEDICO", 10, "PRINCIPAL")], fin)
    lote = ids["PARAMEDICO"]
    for usuario in ("ong.cruzroja", "ong.bomberos"):
        e.esperar(f"G: {usuario} ofrece 1", e.ofrecer(usuario, emg, (lote, 1)), 201)
    print(f"     G = emergencia #{emg} (caso {caso}) · vence {fin:%H:%M:%S}")
    d = ctx.evaluada(emg)
    e.check("G: Bonita evaluó con login (EN_EVALUACION)", d is not None and d["estado"] == "EN_EVALUACION", d and d["estado"])
    if d is None or not ctx.adjudicar("G", emg, caso, [CRUZ_ROJA, BOMBEROS]):
        return
    refs = {CRUZ_ROJA: f"emg-{emg}-r1-{CRUZ_ROJA}", BOMBEROS: f"emg-{emg}-r1-{BOMBEROS}"}
    e.check("G: las dos reservas quedaron ADJUDICADA en Nacional", all(ctx.estado_ref(r) == "ADJUDICADA" for r in refs.values()),
            {r: ctx.estado_ref(r) for r in refs.values()})
    ctx.hasta_validar("G", emg, caso, ["ong.cruzroja", "ong.bomberos"])

    fijar_clave_de_bonita(CLAVE_ROTADA)
    try:
        e.esperar("G: el Coordinador valida el cierre (la app solo avanza la tarea de Bonita)",
                  e.post(COORDINADOR, f"/emergencias/{emg}/validar-cierre", {}), 200)
        fallidos: list[dict] = []
        for _ in range(15):
            fallidos = ctx.nodos_fallidos(caso)
            if fallidos:
                break
            time.sleep(2)
        e.check("G: con la clave vieja, el login de Bonita falla y deja «Liberar Recursos y Notificar Cierre» fallido",
                bool(fallidos), [(n.get("displayName"), n.get("state")) for n in fallidos])
        d = ctx.detalle(emg)
        e.check("G: la emergencia sigue EN_EJECUCION, con el cierre validado", d["estado"] == "EN_EJECUCION"
                and d["ejecucion"]["cierre_validado"] is True, (d["estado"], d["ejecucion"]))
        e.check("G: Nacional no cerró nada: las dos reservas siguen ADJUDICADA",
                all(ctx.estado_ref(r) == "ADJUDICADA" for r in refs.values()), {r: ctx.estado_ref(r) for r in refs.values()})
        e.check("G: la app sigue andando con su propia cuenta (catálogo → 200)", e.get(COORDINADOR, "/tipos-recurso").status_code == 200)
    finally:
        fijar_clave_de_bonita(None)
    e.check("G: recuperar_cierre.py termina el cierre trabado (con la clave de vuelta)", recuperar_ok(ctx, emg))
    ctx.cierre_ok("G", emg, caso, [("ong.cruzroja", CRUZ_ROJA, refs[CRUZ_ROJA]), ("ong.bomberos", BOMBEROS, refs[BOMBEROS])])


def escenario_h(ctx: Ctx) -> None:
    e = ctx.e
    print("\n== H: Nacional se reinicia con otro secreto y tokens de 1 minuto")
    e.check("H: el catálogo responde (la app inicia sesión en Nacional)", e.get(COORDINADOR, "/tipos-recurso").status_code == 200)
    e.check("H: se apagó la API Nacional", apagar(8002))
    e.check("H: se levantó con otro JWT_SECRET y tokens de 1 minuto",
            levantar_nacional_con({"JWT_SECRET": "otro-secreto-de-prueba", "JWT_EXPIRATION_MINUTES": "1"}))
    e.check("H: el token que la app tenía ya no vale, vuelve a entrar sola y responde 200",
            e.get(COORDINADOR, "/tipos-recurso").status_code == 200)
    print("     esperando 70 s a que venza el token de 1 minuto…")
    time.sleep(70)
    e.check("H: con el token vencido, la app vuelve a entrar sola y responde 200", e.get(COORDINADOR, "/tipos-recurso").status_code == 200)
    e.check("H: se apagó la API Nacional de prueba", apagar(8002))
    e.check("H: se levantó la API Nacional normal", levantar("nacional", 8002, "/health"))
    e.check("H: la app sigue respondiendo con la API restaurada", e.get(COORDINADOR, "/tipos-recurso").status_code == 200)


def main() -> int:
    ctx = Ctx("http://localhost:8001")
    e = ctx.e
    print("== Preparación")
    previos = {k: comprometido(ctx.nacional, *k) for k in CLAVES}
    e.check("La API Nacional no tiene nada comprometido al empezar", not any(previos.values()), previos)
    e.check("Bonita no tiene casos abiertos", ctx.admin._request("GET", "/API/bpm/case", params={"p": 0, "c": 50}).json() == [])
    for paso in (escenario_g, escenario_h):
        try:
            paso(ctx)
        except Exception:  # noqa: BLE001
            import traceback
            e.check(f"{paso.__name__}: terminó sin excepciones", False, traceback.format_exc(limit=4))
            fijar_clave_de_bonita(None)

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
