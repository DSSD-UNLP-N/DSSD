"""Alta de una ONG de punta a punta contra los sistemas reales: app, Bonita (Studio) y la API Nacional (Render o local).

Registra una ONG nueva por `POST /api/ongs/alta` y comprueba que quedó en los tres sistemas y que sirve para entrar
en cada uno. **Deja la ONG creada**: la API Nacional no permite borrarla (el usuario de Bonita sí se puede borrar a mano).

    cd backend
    python scripts/e2e_alta_ong.py                      # app en http://localhost:8001, Nacional y Bonita según backend/.env
    python scripts/e2e_alta_ong.py --api http://localhost:8001

Hace falta: app corriendo, Bonita con la organización desplegada (grupo /rescuesync/ong, rol representante_ong) y la API Nacional
despierta. Sale con código 1 si algún chequeo falla.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta

import requests

from app.core.config import get_settings
from app.integrations.bonita import BonitaClient

ok = total = 0


def check(nombre: str, condicion: bool, detalle=None) -> bool:
    global ok, total
    total += 1
    ok += bool(condicion)
    print(f"  {'OK  ' if condicion else 'FALLA'} {nombre}" + ("" if condicion or detalle is None else f"  -> {detalle}"))
    return bool(condicion)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api", default="http://localhost:8001", help="URL de la app")
    ap.add_argument("--ofertar", action="store_true",
                    help="además registra y publica una emergencia y hace ofertar a la ONG nueva (queda abierta en Bonita)")
    args = ap.parse_args()
    cfg = get_settings()
    app = args.api.rstrip("/")

    marca = int(time.time())
    cuit_digitos = f"30{marca % 10**8:08d}9"
    cuit = f"{cuit_digitos[:2]}-{cuit_digitos[2:10]}-{cuit_digitos[10]}"
    usuario, clave = f"ong.e2e.{marca}", "demo1234"
    cuerpo = {"ong_nombre": f"ONG E2E {marca}", "cuit": cuit_digitos, "nombre": "Representante E2E", "username": usuario,
              "password": clave, "rubros": [{"tipo_recurso": "FRAZADA", "cantidad_total": 20},
                                            {"tipo_recurso": "PARAMEDICO", "cantidad_total": 3}]}

    print(f"== Alta de {cuerpo['ong_nombre']} ({cuit}, usuario {usuario}) vía {app}")
    tipos = requests.get(f"{app}/api/ongs/alta/tipos-recurso", timeout=90)
    check("El catálogo de rubros es público (200)", tipos.status_code == 200 and any(t["codigo"] == "FRAZADA" for t in tipos.json()), tipos.status_code)

    r = requests.post(f"{app}/api/ongs/alta", json=cuerpo, timeout=120)
    check("POST /api/ongs/alta → 201 con el CUIT normalizado", r.status_code == 201 and r.json().get("cuit") == cuit, (r.status_code, r.text[:200]))
    if r.status_code != 201:
        print(f"\n{ok}/{total} verificaciones OK")
        return 1

    print("\n== En la app")
    sesion = requests.Session()
    login = sesion.post(f"{app}/api/auth/login", json={"username": usuario, "password": clave}, timeout=30)
    check("La ONG entra a la app con su clave y rol ONG", login.status_code == 200 and login.json().get("rol") == "ONG", login.text[:150])

    print("\n== En Bonita")
    admin = BonitaClient(cfg.bonita_base_url, cfg.bonita_timeout_seconds)
    admin.login(cfg.bonita_username, cfg.bonita_password)
    uid = admin.find_user_id(usuario)
    check("Existe el usuario", uid is not None)
    miembros = admin._request("GET", "/API/identity/membership", params={"p": 0, "c": 50, "f": f"user_id={uid}", "d": "group_id"}).json() if uid else []
    check("Es miembro de /rescuesync/ong con el rol representante_ong",
          any(m["group_id"]["path"] == "/rescuesync/ong" and m["role_id"] == admin.role_id("representante_ong") for m in miembros), miembros)
    propio = BonitaClient(cfg.bonita_base_url, cfg.bonita_timeout_seconds)
    try:
        propio.login(usuario, cfg.bonita_test_password)
        entra = True
    except Exception as exc:  # noqa: BLE001 - interesa cualquier fallo de login
        entra = False
        print("    ", exc)
    check("Entra a Bonita con la clave de pruebas", entra)

    print("\n== En la API Nacional")
    nacional = requests.post(f"{cfg.nacional_base_url}/login", json={"username": usuario, "password": clave}, timeout=90)
    check("Entra a la API Nacional con su clave (JWT)", nacional.status_code == 200 and "access_token" in nacional.json(), (nacional.status_code, nacional.text[:150]))
    if nacional.status_code == 200:
        token = {"Authorization": f"Bearer {nacional.json()['access_token']}"}
        ficha = requests.get(f"{cfg.nacional_base_url}/ongs/{cuit}", headers=token, timeout=60)
        inv = {i["tipo_recurso"]: i["cantidad_total"] for i in ficha.json().get("inventario", [])} if ficha.status_code == 200 else {}
        check("Ficha HABILITADA con los rubros declarados", ficha.status_code == 200 and ficha.json().get("estado") == "HABILITADA"
              and inv == {"FRAZADA": 20, "PARAMEDICO": 3}, (ficha.status_code, inv))

    print("\n== Errores")
    rep = requests.post(f"{app}/api/ongs/alta", json=cuerpo, timeout=60)
    check("Repetir el alta → 409", rep.status_code == 409, rep.status_code)
    mal = requests.post(f"{app}/api/ongs/alta", json={**cuerpo, "ong_nombre": "Otra", "username": "otro.usuario", "cuit": "123"}, timeout=60)
    check("CUIT inválido → 422", mal.status_code == 422, mal.status_code)
    check("El intento repetido no dejó otro usuario en Bonita", admin.find_user_id(usuario) == uid)

    if args.ofertar and login.status_code == 200:
        ofertar(app, cfg, sesion)

    print(f"\n{ok}/{total} verificaciones OK")
    return 0 if ok == total else 1


def ofertar(app: str, cfg, sesion: requests.Session) -> None:
    """La ONG nueva responde a una emergencia: su oferta se valida contra el inventario que declaró en la API Nacional."""
    print("\n== La ONG nueva responde a una emergencia (su inventario se valida contra la API Nacional)")

    def entrar(usuario: str) -> requests.Session:
        ses = requests.Session()
        ses.post(f"{app}/api/auth/login", json={"username": usuario, "password": "demo1234"}, timeout=30).raise_for_status()
        return ses

    municipio, coordinador = entrar("operador.municipal"), entrar("coordinador.regional")
    em = municipio.post(f"{app}/api/emergencias", json={"tipo": "INUNDACION", "nivel_gravedad": "ALTO", "zona_afectada": "Zona E2E alta-ong",
                                                         "descripcion": "Prueba de la ONG recién dada de alta"}, timeout=120)
    if not check("El Municipio registra la emergencia (201)", em.status_code == 201, (em.status_code, em.text[:150])):
        return
    eid = em.json()["id"]
    lote = coordinador.post(f"{app}/api/emergencias/{eid}/lotes", json={"tipo_recurso": "FRAZADA", "cantidad": 10}, timeout=60)
    if not check("El Coordinador arma un lote de FRAZADA (201)", lote.status_code == 201, (lote.status_code, lote.text[:150])):
        return
    ventana = (datetime.now().astimezone() + timedelta(hours=2)).isoformat(timespec="seconds")
    pub = coordinador.post(f"{app}/api/emergencias/{eid}/publicar", json={"ventana_fin": ventana}, timeout=120)
    check("Publica la convocatoria (200)", pub.status_code == 200, (pub.status_code, pub.text[:150]))

    def oferta(cantidad: int) -> requests.Response:
        items = [{"lote_id": lote.json()["id"], "recurso": "Frazada", "cantidad": cantidad}]
        return sesion.post(f"{app}/api/emergencias/{eid}/ofertas", json={"items": items}, timeout=90)

    r = oferta(5)
    check("Ofrece 5 de las 20 que declaró (201)", r.status_code == 201, (r.status_code, r.text[:150]))
    r = oferta(500)
    check("Ofrecer 500 con 20 en el inventario → 400 «No alcanza tu inventario»",
          r.status_code == 400 and "No alcanza tu inventario" in r.text, (r.status_code, r.text[:150]))
    print(f"    (la emergencia #{eid} queda abierta esperando ofertas)")


if __name__ == "__main__":
    sys.exit(main())
