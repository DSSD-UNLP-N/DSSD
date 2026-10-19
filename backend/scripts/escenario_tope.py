"""Escenario completo de validación de ofertas de las ONGs, por la API de la app (la misma que usa la SPA), con
Bonita real y la API Nacional que tenga configurada el backend (local o la nube).

Crea tres emergencias, carga lotes eligiendo tipos del catálogo nacional, las publica en Bonita y recorre los
casos del tope por inventario, el retiro de ofertas, los permisos y una convocatoria que vence mientras corre.

Requisitos: Bonita con el proceso desplegado, backend en :8001 apuntando a la API Nacional, y esa API con los
datos del seed (Cruz Roja: 4 paramédicos, 3000 L de agua; Bomberos: 6 paramédicos).

    python scripts/escenario_tope.py                 # ~3 min: espera a que venza la tercera convocatoria
    python scripts/escenario_tope.py --app http://localhost:8001
"""
from __future__ import annotations

import os
import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nacional_auth import nacional_post  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.integrations.bonita import BonitaClient  # noqa: E402
from app.seed import DEMO_PASSWORD  # noqa: E402

VENTANA_CORTA_S = int(os.environ.get("ESCENARIO_VENTANA_S", 60)) + 20  # la tercera convocatoria vence durante la corrida


class Escenario:
    def __init__(self, app: str) -> None:
        self.app = app.rstrip("/")
        self.ok = self.total = 0
        self.sesiones: dict[str, requests.Session] = {}

    def check(self, nombre: str, condicion: bool, detalle: object = "") -> None:
        self.total += 1
        self.ok += bool(condicion)
        print(f"  [{'OK   ' if condicion else 'FALLA'}] {nombre}" + ("" if condicion else f"  -> {detalle}"))

    def como(self, usuario: str) -> requests.Session:
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


def _ok(r: requests.Response) -> requests.Response:
    if not r.ok:
        raise RuntimeError(f"{r.request.method} {r.url} → {r.status_code}: {r.text[:300]}")
    return r


def crear_y_publicar(e: Escenario, zona: str, gravedad: str, lotes: list[tuple[str, int, str]],
                     ventana: datetime) -> tuple[int, int, dict[str, int]]:
    r = e.post("operador.municipal", "/emergencias", {
        "tipo": "inundacion", "nivel_gravedad": gravedad, "zona_afectada": zona,
        "descripcion": "Escenario de prueba del tope de ofertas (E3)"})
    emergencia = _ok(r).json()
    ids = {}
    for tipo_recurso, cantidad, tipo in lotes:
        r = e.post("coordinador.regional", f"/emergencias/{emergencia['id']}/lotes",
                   {"tipo_recurso": tipo_recurso, "cantidad": cantidad, "tipo": tipo})
        ids[tipo_recurso] = _ok(r).json()["id"]
    r = e.post("coordinador.regional", f"/emergencias/{emergencia['id']}/publicar",
               {"ventana_fin": ventana.isoformat(timespec="seconds")})
    _ok(r)
    return emergencia["id"], emergencia["bonita_case_id"], ids


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="http://localhost:8001")
    args = ap.parse_args()
    e = Escenario(args.app)
    settings = get_settings()

    print("== Preparación: catálogo, emergencias y lotes")
    tipos = e.get("coordinador.regional", "/tipos-recurso")
    e.check("El catálogo llega desde la API Nacional", tipos.status_code == 200 and len(tipos.json()) == 11,
            tipos.status_code)
    em_tmp = e.post("operador.municipal", "/emergencias", {
        "tipo": "otro", "nivel_gravedad": "BAJO", "zona_afectada": "Sin publicar", "descripcion": "Queda registrada"})
    em_sin_publicar = em_tmp.json()["id"]
    e.esperar("Lote con un tipo fuera del catálogo → 400",
              e.post("coordinador.regional", f"/emergencias/{em_sin_publicar}/lotes",
                     {"tipo_recurso": "NAVE_ESPACIAL", "cantidad": 1, "tipo": "PRINCIPAL"}),
              400, "Tipo de recurso inexistente")
    r = e.post("coordinador.regional", f"/emergencias/{em_sin_publicar}/lotes",
               {"tipo_recurso": "PARAMEDICO", "detalle": "con equipo de trauma", "cantidad": 2, "tipo": "PRINCIPAL"})
    e.check("El nombre y la unidad del lote salen del catálogo, con el detalle",
            r.status_code == 201 and (r.json()["recurso"], r.json()["unidad"]) == ("Paramédico (con equipo de trauma)", "personas"),
            r.text)

    ahora = datetime.now().astimezone()
    e1, caso1, l1 = crear_y_publicar(e, "Centro", "ALTO", [
        ("PARAMEDICO", 10, "PRINCIPAL"), ("AGUA_POTABLE", 8000, "PRINCIPAL"), ("RACION_ALIMENTO", 2000, "APOYO")],
        ahora + timedelta(hours=2))
    e2, _, l2 = crear_y_publicar(e, "Norte", "MEDIO", [("PARAMEDICO", 10, "PRINCIPAL")], ahora + timedelta(hours=2))
    fin3 = datetime.now().astimezone() + timedelta(seconds=VENTANA_CORTA_S)
    e3, caso3, l3 = crear_y_publicar(e, "Sur", "ALTO", [("PARAMEDICO", 10, "PRINCIPAL")], fin3)
    print(f"     emergencias #{e1}, #{e2} (2 h) y #{e3} (vence {fin3:%H:%M:%S}); casos Bonita {caso1}…{caso3}")
    e.check("Las tres convocatorias quedaron abiertas",
            all(e.get("coordinador.regional", f"/emergencias/{i}").json()["estado"] == "CONVOCATORIA" for i in (e1, e2, e3)))
    print(f"     limpieza: {retirar_previas(e, {e1, e2, e3})} ofertas de corridas anteriores retiradas")

    pm1, agua1, rac1, pm2, pm3 = l1["PARAMEDICO"], l1["AGUA_POTABLE"], l1["RACION_ALIMENTO"], l2["PARAMEDICO"], l3["PARAMEDICO"]

    print("\n== Bomberos ocupa todo su stock en la convocatoria corta")
    e.esperar("B1 Bomberos ofrece sus 6 paramédicos en #3", e.ofrecer("ong.bomberos", e3, (pm3, 6)), 201)
    e.esperar("B2 1 más en #1 → 400 (6 + 1 > 6)", e.ofrecer("ong.bomberos", e1, (pm1, 1)), 400,
              "sumás 7 personas y tenés 6 disponibles")

    print("\n== Cruz Roja: tope de paramédicos entre emergencias (tiene 4)")
    r = e.ofrecer("ong.cruzroja", e1, (pm1, 2))
    e.check("C1 Ofrece 2 en #1 → versión 1", r.status_code == 201 and r.json()["version_actual"] == 1, r.text)
    e.esperar("C2 Ofrece 3 en #2 → 400 (2 + 3 > 4)", e.ofrecer("ong.cruzroja", e2, (pm2, 3)), 400,
              "No alcanza tu inventario", "Paramédico: entre tus ofertas abiertas sumás 5 personas y tenés 4 disponibles")
    r = e.ofrecer("ong.cruzroja", e1, (pm1, 3))
    e.check("C3 Edita #1 a 3 → versión 2 (reemplaza, no suma)", r.status_code == 201 and r.json()["version_actual"] == 2, r.text)
    e.esperar("C4 Ofrece 2 en #2 → 400 (3 + 2 > 4)", e.ofrecer("ong.cruzroja", e2, (pm2, 2)), 400, "sumás 5")
    e.esperar("C5 Ofrece 1 en #2 → 201 (3 + 1 = 4, justo)", e.ofrecer("ong.cruzroja", e2, (pm2, 1)), 201)
    e.esperar("C5b Repite la misma oferta en #2 → 201 (no aumenta, no consulta)", e.ofrecer("ong.cruzroja", e2, (pm2, 1)), 201)

    print("\n== Cruz Roja: varios recursos en una oferta")
    r = e.ofrecer("ong.cruzroja", e1, (pm1, 3), (agua1, 3000), (rac1, 1500))
    e.check("C6 #1 con paramédicos + agua + raciones (cada uno dentro de su stock) → 201",
            r.status_code == 201 and len(r.json()["items"]) == 3, r.text)
    e.esperar("C7 Agua 3001 → 400 solo por el agua", e.ofrecer("ong.cruzroja", e1, (pm1, 3), (agua1, 3001)), 400,
              "Agua potable: entre tus ofertas abiertas sumás 3001 litros y tenés 3000 disponibles")
    d = e.esperar("C8 Paramédicos 4 y agua 4000 → 400 con los dos recursos",
                  e.ofrecer("ong.cruzroja", e1, (pm1, 4), (agua1, 4000)), 400, "Paramédico", "Agua potable")
    r = e.get("ong.cruzroja", f"/emergencias/{e1}/ofertas").json()[0]
    e.check("C8b El rechazo no guardó nada: sigue la versión 3", r["version_actual"] == 3, r)

    print("\n== Cruz Roja: retirar")
    r = e.ofrecer("ong.cruzroja", e1, (pm1, 3), (agua1, 3000))
    e.check("C9 Retira las raciones de #1 → versión 4 sin ese lote",
            r.status_code == 201 and {i["lote_id"] for i in r.json()["items"]} == {pm1, agua1}, r.text)
    r = e.ofrecer("ong.cruzroja", e1)
    e.check("C10 Retira toda la oferta de #1 → retirada", r.status_code == 201 and r.json()["retirada"] is True, r.text)
    e.esperar("C11 Retirar de nuevo → 400", e.ofrecer("ong.cruzroja", e1), 400, "No tenés una oferta para retirar")
    e.esperar("C12 El retiro liberó el cupo: sube #2 a 4 → 201", e.ofrecer("ong.cruzroja", e2, (pm2, 4)), 201)
    r = e.ofrecer("ong.cruzroja", e1, (pm1, 1))
    e.esperar("C13 Vuelve a ofertar en #1 (1 más) → 400 (4 + 1 > 4)", r, 400, "sumás 5")
    e.esperar("C14 Retirar sin haber ofertado nunca (Bomberos en #2) → 400", e.ofrecer("ong.bomberos", e2), 400,
              "No tenés una oferta para retirar")

    print("\n== Datos inválidos y permisos")
    e.esperar("E1 Lote repetido en la misma oferta → 400", e.ofrecer("ong.cruzroja", e2, (pm2, 1), (pm2, 1)), 400, "repetidos")
    e.esperar("E2 Lote de otra emergencia → 400", e.ofrecer("ong.cruzroja", e2, (pm1, 1)), 400, "inválido")
    e.esperar("E3 Cantidad 0 → 422", e.ofrecer("ong.cruzroja", e2, (pm2, 0)), 422)
    e.esperar("E4 Cantidad negativa → 422", e.ofrecer("ong.cruzroja", e2, (pm2, -1)), 422)
    e.esperar("E5 Emergencia sin publicar: la ONG no la ve → 404",
              e.ofrecer("ong.cruzroja", em_sin_publicar, (1, 1)), 404)
    e.esperar("E6 El Municipio no puede ofertar → 403", e.ofrecer("operador.municipal", e2, (pm2, 1)), 403)
    e.esperar("E7 El Coordinador no puede ofertar → 403", e.ofrecer("coordinador.regional", e2, (pm2, 1)), 403)
    e.esperar("E8 El Auditor no puede ofertar → 403", e.ofrecer("auditor", e2, (pm2, 1)), 403)
    propias = e.get("ong.bomberos", f"/emergencias/{e2}/ofertas").json()
    e.check("E9 Bomberos no ve la oferta de Cruz Roja", propias == [], propias)
    vistas = {o["ong_nombre"]: o for o in e.get("coordinador.regional", f"/emergencias/{e1}/ofertas").json()}
    e.check("E10 El Coordinador ve la de Cruz Roja como retirada (con su historial)",
            vistas.get("Cruz Roja Argentina", {}).get("retirada") is True
            and vistas["Cruz Roja Argentina"]["version_actual"] == 5, vistas)
    e.check("E11 El Auditor también ve las ofertas", len(e.get("auditor", f"/emergencias/{e2}/ofertas").json()) == 1)

    print(f"\n== Convocatoria #3 vence: esperando hasta {fin3:%H:%M:%S}")
    faltan = (fin3 - datetime.now().astimezone()).total_seconds()
    if faltan > 0:  # margen para que dispare el timer de Bonita y su conector pida el consolidado
        time.sleep(faltan + 15)
    e.esperar("V1 Ofertar en #3 vencida → 400", e.ofrecer("ong.bomberos", e3, (pm3, 1)), 400, "cerró")
    e.esperar("V2 Retirar en #3 vencida → 400", e.ofrecer("ong.bomberos", e3), 400, "cerró")
    e.esperar("V3 Bonita evaluó #3 y la API Nacional reservó los 6 paramédicos de Bomberos: ya no puede ofrecer 1 en #1",
              e.ofrecer("ong.bomberos", e1, (pm1, 1)), 400, "tenés 0 disponibles")
    e.check("V5 La app marca #3 como EN_EVALUACION (el conector de Bonita pidió el consolidado)",
            e.get("coordinador.regional", f"/emergencias/{e3}").json()["estado"] == "EN_EVALUACION")
    admin = BonitaClient(settings.bonita_base_url, settings.bonita_timeout_seconds)
    admin.login(settings.bonita_username, settings.bonita_password)
    tarea = admin.wait_for_task(caso3, "Evaluar Cobertura", retries=30)
    e.check("V6 Bonita: el timer cerró la ventana y el caso pasó a 'Evaluar Cobertura…'", tarea is not None,
            [t["displayName"] for t in admin.get_human_tasks(caso3)])

    print("\n== Limpieza")
    nacional = settings.nacional_base_url.rstrip("/")
    r = nacional_post(f"{nacional}/adjudicaciones/emg-{e3}-r1-30-68522415-9/liberar", timeout=60)
    e.check("Se libera la reserva que Bonita hizo para #3", r.status_code == 200 and r.json()["estado"] == "LIBERADA", r.text)
    retiradas =sum(e.ofrecer(o, i).status_code == 201 for o in ("ong.cruzroja", "ong.bomberos") for i in (e1, e2))
    print(f"     {retiradas} ofertas del escenario retiradas (las convocatorias quedan abiertas 2 h)")

    print(f"\n{e.ok}/{e.total} verificaciones OK")
    return 0 if e.ok == e.total else 1


if __name__ == "__main__":
    sys.exit(main())
