"""Verifica un despliegue de la API Nacional por HTTP: catálogo, fichas, disponibilidad y las reglas de
validación de ofertas. Recorre los 19 endpoints. No deja datos modificados: lecturas, `POST /validaciones` (no guarda
nada), `PUT` que fallan antes de escribir y reservas, cierres y una adjudicación directa que se liberan al final.
Espera los datos del seed (app/seed.py) sin nada comprometido; puede haber más ONGs registradas.

Con `--crear-ong` suma el caso feliz de `POST /ongs`, que registra una ONG de verificación y **la deja en la base** (no hay
forma de borrarla desde la API): usarlo a propósito, no en cada corrida.

    python scripts/verificar_despliegue.py https://sistema-nacional-latest.onrender.com --clave <BONITA_SERVICE_PASSWORD>
    python scripts/verificar_despliegue.py http://localhost:8002
    python scripts/verificar_despliegue.py <URL> --clave <BONITA_SERVICE_PASSWORD> --crear-ong

La API exige JWT: entra como la cuenta de servicio de Bonita (por defecto `bonita-service` con la clave de ejemplo, que
sirve contra una API local; contra la nube pasar `--clave` o la variable NACIONAL_VERIFY_PASSWORD). Para las pruebas de
inventario usa la cuenta de ONG de demo del seed (`ong.cruzroja`).

Solo usa la biblioteca estándar: corre con cualquier Python 3.11+.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

CRUZ_ROJA, BOMBEROS, SUSPENDIDA = "30-54666544-5", "30-68522415-9", "30-70000000-1"
ONG_DEMO, CLAVE_DEMO = "ong.cruzroja", "demo1234"


class Verificador:
    def __init__(self, base: str, usuario: str = "bonita-service", clave: str = "change-me") -> None:
        self.base = base.rstrip("/")
        self.usuario, self.clave = usuario, clave
        self.token: str | None = None
        self.ok = self.total = 0

    def pedir(self, metodo: str, ruta: str, cuerpo=None, timeout: float = 90, token: str | None = "servicio") -> tuple[int, object]:
        """`token`: "servicio" (el de la cuenta de servicio), None (sin cabecera) o un JWT puntual."""
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        headers = {"Content-Type": "application/json"}
        jwt = self.token if token == "servicio" else token
        if jwt:
            headers["Authorization"] = f"Bearer {jwt}"
        req = urllib.request.Request(f"{self.base}{ruta}", data=datos, method=metodo, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def entrar(self, usuario: str, clave: str) -> str | None:
        status, r = self.pedir("POST", "/login", {"username": usuario, "password": clave}, token=None)
        return r["access_token"] if status == 200 else None

    def check(self, nombre: str, condicion: bool, detalle: object = "") -> None:
        self.total += 1
        self.ok += bool(condicion)
        print(f"  [{'OK   ' if condicion else 'FALLA'}] {nombre}" + ("" if condicion else f"  -> {detalle}"))

    def validar(self, gravedad: str, *items: tuple[str, str, int]) -> dict:
        status, r = self.pedir("POST", "/validaciones", {
            "gravedad": gravedad,
            "items": [{"cuit": c, "tipo_recurso": t, "cantidad": n} for c, t, n in items],
        })
        assert status == 200, (status, r)
        return r

    def uno(self, gravedad: str, cuit: str, tipo: str, cantidad: int) -> dict:
        (res,) = self.validar(gravedad, (cuit, tipo, cantidad))["resultados"]
        return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", default="http://localhost:8002")
    ap.add_argument("--usuario", default=os.environ.get("NACIONAL_VERIFY_USER", "bonita-service"))
    ap.add_argument("--clave", default=os.environ.get("NACIONAL_VERIFY_PASSWORD", "change-me"))
    ap.add_argument("--crear-ong", action="store_true", help="registra una ONG de verificación (queda en la base)")
    args = ap.parse_args()
    v = Verificador(args.url, args.usuario, args.clave)
    print(f"API Nacional en {v.base}")

    print("\n== A1. Estado y Swagger")
    inicio = time.monotonic()
    status, salud = v.pedir("GET", "/health")
    print(f"     /health respondió en {time.monotonic() - inicio:.1f} s (si estaba dormido, tarda)")
    v.check("/health responde ok", status == 200 and salud == {"estado": "ok"}, (status, salud))
    status, api = v.pedir("GET", "/openapi.json")
    rutas = set(api["paths"]) if status == 200 else set()
    esperadas = {"/tipos-recurso", "/certificaciones", "/ongs", "/ongs/{cuit}", "/ongs/{cuit}/inventario",
                 "/recursos/disponibilidad", "/validaciones", "/evaluaciones", "/login",
                 "/adjudicaciones/{referencia}/confirmar", "/adjudicaciones/{referencia}/liberar", "/cierres", "/cierres/lote",
                 "/adjudicaciones", "/adjudicaciones/resolucion", "/cierres/{cierre_id}", "/ongs/{cuit}/cierres", "/health"}
    v.check("Swagger expone los 19 endpoints (catálogo, inventario, validación, reservas, adjudicación y cierre)",
            esperadas <= rutas, sorted(esperadas - rutas))
    print(f"     endpoints: {', '.join(sorted(rutas))}")

    print("\n== A0. Autenticación (JWT)")
    v.check("Sin token → 401", v.pedir("GET", "/tipos-recurso", token=None)[0] == 401)
    v.check("Token inválido → 401", v.pedir("GET", "/tipos-recurso", token="no.es.un.jwt")[0] == 401)
    v.check("Login con clave incorrecta → 401",
            v.pedir("POST", "/login", {"username": v.usuario, "password": "incorrecta"}, token=None)[0] == 401)
    v.token = v.entrar(v.usuario, v.clave)
    v.check(f"Login de la cuenta de servicio {v.usuario}", v.token is not None)
    if v.token is None:
        print("     sin token no se puede seguir (¿clave de la cuenta de servicio? ver --clave)")
        return 1
    ong = v.entrar(ONG_DEMO, CLAVE_DEMO)
    v.check(f"Hay una cuenta de ONG de demo ({ONG_DEMO}) con clave {CLAVE_DEMO}", ong is not None)
    v.check("Una ONG no puede liberar reservas → 403",
            v.pedir("POST", "/adjudicaciones/no-existe/liberar", token=ong)[0] == 403)
    v.check("La cuenta de servicio sí pasa (404: la reserva no existe)",
            v.pedir("POST", "/adjudicaciones/no-existe/liberar")[0] == 404)
    v.check("Registro de ONG con un CUIT que ya existe → 409 (sin crear nada)",
            v.pedir("POST", "/ongs", {"ong_nombre": "Otra ONG", "cuit": CRUZ_ROJA, "nombre": "Alguien",
                                      "username": "verificador.despliegue", "password": "una-clave-larga"}, token=None)[0] == 409)
    v.check("Registro de ONG con un CUIT mal formado → 422",
            v.pedir("POST", "/ongs", {"ong_nombre": "Otra ONG", "cuit": "123", "nombre": "Alguien",
                                      "username": "verificador.despliegue", "password": "una-clave-larga"}, token=None)[0] == 422)

    print("\n== A2-A3. Catálogo")
    _, tipos = v.pedir("GET", "/tipos-recurso")
    por_codigo = {t["codigo"]: t for t in tipos}
    v.check("11 tipos de recurso", len(tipos) == 11, len(tipos))
    v.check("PARAMEDICO requiere SALUD_PREHOSP", por_codigo["PARAMEDICO"]["certificacion_requerida"] == "SALUD_PREHOSP")
    v.check("Los insumos no requieren certificación",
            all(t["certificacion_requerida"] is None for t in tipos if t["categoria"] == "INSUMO"))
    _, certs = v.pedir("GET", "/certificaciones")
    v.check("4 certificaciones, cada una con los recursos que habilita",
            len(certs) == 4 and all(c["tipos_recurso"] for c in certs), certs)

    print("\n== A4-A5. ONGs y fichas")
    _, todas = v.pedir("GET", "/ongs")
    _, habilitadas = v.pedir("GET", "/ongs?estado=HABILITADA")
    cuits_todas, cuits_hab = {o["cuit"] for o in todas}, {o["cuit"] for o in habilitadas}
    v.check("Están las 3 ONGs del seed (puede haber más registradas), 2 de ellas habilitadas",
            {CRUZ_ROJA, BOMBEROS, SUSPENDIDA} <= cuits_todas and {CRUZ_ROJA, BOMBEROS} <= cuits_hab, (len(todas), len(habilitadas)))
    v.check("La suspendida no figura entre las habilitadas", SUSPENDIDA not in {o["cuit"] for o in habilitadas})
    v.check("Estado inválido → 422", v.pedir("GET", "/ongs?estado=NOSE")[0] == 422)
    _, cruz = v.pedir("GET", f"/ongs/{CRUZ_ROJA}")
    inv_cruz = {i["tipo_recurso"]: i for i in cruz["inventario"]}
    v.check("Cruz Roja: SALUD_PREHOSP vigente hasta MEDIO",
            [(c["codigo"], c["riesgo_max"], c["vigente"]) for c in cruz["certificaciones"]] == [("SALUD_PREHOSP", "MEDIO", True)],
            cruz["certificaciones"])
    v.check("Cruz Roja: 4 paramédicos disponibles, nada comprometido",
            (inv_cruz["PARAMEDICO"]["disponible"], inv_cruz["PARAMEDICO"]["cantidad_comprometida"]) == (4, 0),
            inv_cruz["PARAMEDICO"])
    _, bomb = v.pedir("GET", f"/ongs/{BOMBEROS}")
    inv_bomb = {i["tipo_recurso"]: i for i in bomb["inventario"]}
    vencida = next(c for c in bomb["certificaciones"] if c["codigo"] == "SALUD_PREHOSP")
    v.check("Bomberos: SALUD_PREHOSP vencida → sus paramédicos sin riesgo permitido",
            not vencida["vigente"] and inv_bomb["PARAMEDICO"]["riesgo_permitido"] is None, (vencida, inv_bomb["PARAMEDICO"]))
    v.check("CUIT inexistente → 404", v.pedir("GET", "/ongs/99-99999999-9")[0] == 404)
    v.check("El CUIT sin guiones encuentra la misma ficha", v.pedir("GET", f"/ongs/{CRUZ_ROJA.replace('-', '')}")[1].get("cuit") == CRUZ_ROJA)

    print("\n== A6. Disponibilidad global")
    _, disp = v.pedir("GET", "/recursos/disponibilidad?tipo_recurso=PARAMEDICO")
    v.check("Paramédicos: al menos 10 disponibles (4 + 6 del seed), desglosados por ONG",
            disp[0]["disponible"] >= 10 and {CRUZ_ROJA, BOMBEROS} <= {o["cuit"] for o in disp[0]["por_ong"]}, disp)
    _, raciones = v.pedir("GET", "/recursos/disponibilidad?tipo_recurso=RACION_ALIMENTO")
    v.check("Raciones: la ONG suspendida no suma ni aparece en el desglose",
            SUSPENDIDA not in {o["cuit"] for o in raciones[0]["por_ong"]} and raciones[0]["cantidad_total"] >= 5000, raciones)
    v.check("Tipo inexistente → 404", v.pedir("GET", "/recursos/disponibilidad?tipo_recurso=NADA")[0] == 404)

    print("\n== A7. PUT de inventario: solo la propia ONG, y falla antes de escribir")
    uno = {"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 1}]}
    v.check("Sin token → 401", v.pedir("PUT", f"/ongs/{CRUZ_ROJA}/inventario", uno, token=None)[0] == 401)
    v.check("La cuenta de servicio no declara inventarios → 403", v.pedir("PUT", f"/ongs/{CRUZ_ROJA}/inventario", uno)[0] == 403)
    v.check("Una ONG no toca el inventario de otra → 403", v.pedir("PUT", f"/ongs/{BOMBEROS}/inventario", uno, token=ong)[0] == 403)
    v.check("Tipo inexistente → 404 (y no guarda el resto)",
            v.pedir("PUT", f"/ongs/{CRUZ_ROJA}/inventario", {"items": [
                {"tipo_recurso": "PARAMEDICO", "cantidad_total": 99}, {"tipo_recurso": "NADA", "cantidad_total": 1}]}, token=ong)[0] == 404)
    v.check("Cantidad de más de 32 bits → 422 (en Postgres sería un 500)",
            v.pedir("PUT", f"/ongs/{CRUZ_ROJA}/inventario", {"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 3_000_000_000}]}, token=ong)[0] == 422)
    v.check("Cantidad negativa → 422",
            v.pedir("PUT", f"/ongs/{CRUZ_ROJA}/inventario", {"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": -1}]}, token=ong)[0] == 422)

    print("\n== V. Validación de ofertas (POST /validaciones)")
    r = v.uno("ALTO", CRUZ_ROJA, "PARAMEDICO", 10)
    v.check("V1  Cruz Roja pide 10 paramédicos: no alcanza (disponible 4)",
            (r["alcanza"], r["disponible"]) == (False, 4) and "Solicitado 10, disponible 4" in r["observaciones"], r)
    v.check("V2  Pide 4: alcanza", v.uno("MEDIO", CRUZ_ROJA, "PARAMEDICO", 4)["alcanza"] is True)
    resp = v.validar("MEDIO", (CRUZ_ROJA, "PARAMEDICO", 2), (CRUZ_ROJA, "PARAMEDICO", 3))
    (r,) = resp["resultados"]
    v.check("V3  2 + 3 en dos ítems se suman: 5 > 4",
            (r["solicitado"], r["alcanza"], resp["alcanza_todo"]) == (5, False, False), resp)
    r = v.uno("MEDIO", CRUZ_ROJA, "PARAMEDICO", 2)
    v.check("V4  Gravedad MEDIO: PLENA → PRINCIPAL",
            (r["nivel"], r["asignacion_sugerida"], r["riesgo_permitido"]) == ("PLENA", "PRINCIPAL", "MEDIO"), r)
    r = v.uno("ALTO", CRUZ_ROJA, "PARAMEDICO", 2)
    v.check("V5  Gravedad ALTO: PARCIAL → APOYO, sin rechazar",
            (r["nivel"], r["asignacion_sugerida"], r["alcanza"]) == ("PARCIAL", "APOYO", True), r)
    r = v.uno("CRITICO", BOMBEROS, "RESCATISTA_ACUATICO", 12)
    v.check("V6  Bomberos rescatistas acuáticos, CRITICO: PLENA", (r["nivel"], r["alcanza"]) == ("PLENA", True), r)
    v.check("V7  Bomberos brigadistas, CRITICO: PARCIAL (cert hasta ALTO)",
            v.uno("CRITICO", BOMBEROS, "BRIGADISTA_FORESTAL", 5)["nivel"] == "PARCIAL")
    r = v.uno("BAJO", BOMBEROS, "PARAMEDICO", 2)
    v.check("V8  Bomberos paramédicos: SUPERVISADA por cert vencida, pero alcanza",
            (r["nivel"], r["riesgo_permitido"], r["alcanza"]) == ("SUPERVISADA", None, True)
            and any("vencida" in o for o in r["observaciones"]), r)
    r = v.uno("CRITICO", CRUZ_ROJA, "RACION_ALIMENTO", 5000)
    v.check("V9  Raciones (insumo) en CRITICO: PLENA", (r["nivel"], r["riesgo_permitido"]) == ("PLENA", "CRITICO"), r)
    r = v.uno("BAJO", SUSPENDIDA, "RACION_ALIMENTO", 1)
    v.check("V10 ONG suspendida: SUPERVISADA y disponible 0",
            (r["nivel"], r["disponible"], r["alcanza"]) == ("SUPERVISADA", 0, False), r)
    r = v.uno("BAJO", "99-99999999-9", "RACION_ALIMENTO", 1)
    v.check("V11 CUIT bien formado pero no registrado: se informa sin error (ong = null)", (r["ong"], r["nivel"]) == (None, "SUPERVISADA"), r)
    r = v.uno("BAJO", CRUZ_ROJA.replace("-", ""), "RACION_ALIMENTO", 1)
    v.check("V11a El CUIT sin guiones es el mismo CUIT", (r["ong"], r["cuit"]) == ("Cruz Roja Argentina", CRUZ_ROJA), r)
    r = v.uno("BAJO", CRUZ_ROJA, "BOTE_RESCATE", 1)
    v.check("V11b Recurso que la ONG no tiene ni está certificada: disponible 0, SUPERVISADA",
            (r["disponible"], r["nivel"]) == (0, "SUPERVISADA"), r)
    resp = v.validar("MEDIO", (CRUZ_ROJA, "PARAMEDICO", 4), (BOMBEROS, "RESCATISTA_ACUATICO", 12))
    v.check("V12 Dos ONGs que alcanzan: alcanza_todo = true", resp["alcanza_todo"] is True, resp)
    resp = v.validar("MEDIO", (CRUZ_ROJA, "PARAMEDICO", 4), (BOMBEROS, "RESCATISTA_ACUATICO", 13))
    v.check("V12b Si una no alcanza: alcanza_todo = false", resp["alcanza_todo"] is False, resp)
    for nombre, cuerpo in [
        ("tipo inexistente", {"gravedad": "ALTO", "items": [{"cuit": CRUZ_ROJA, "tipo_recurso": "NADA", "cantidad": 1}]}),
        ("cantidad 0", {"gravedad": "ALTO", "items": [{"cuit": CRUZ_ROJA, "tipo_recurso": "PARAMEDICO", "cantidad": 0}]}),
        ("gravedad inválida", {"gravedad": "ENORME", "items": [{"cuit": CRUZ_ROJA, "tipo_recurso": "PARAMEDICO", "cantidad": 1}]}),
        ("sin ítems", {"gravedad": "ALTO", "items": []}),
        ("CUIT mal formado", {"gravedad": "ALTO", "items": [{"cuit": "abc", "tipo_recurso": "PARAMEDICO", "cantidad": 1}]}),
        ("cantidad de más de 32 bits", {"gravedad": "ALTO", "items": [{"cuit": CRUZ_ROJA, "tipo_recurso": "PARAMEDICO", "cantidad": 3_000_000_000}]}),
    ]:
        v.check(f"V13 {nombre} → 422", v.pedir("POST", "/validaciones", cuerpo)[0] == 422)
    _, antes = v.pedir("GET", f"/ongs/{CRUZ_ROJA}")
    v.validar("ALTO", (CRUZ_ROJA, "PARAMEDICO", 3))
    _, despues = v.pedir("GET", f"/ongs/{CRUZ_ROJA}")
    v.check("V14 Validar no guarda nada: la ficha queda igual", antes == despues)
    for nombre, items in [("a un lote que no está en el pedido", [{"lote_id": 77, "tipo_recurso": "PARAMEDICO", "cantidad": 1}]),
                          ("otro recurso que el del lote", [{"lote_id": 1, "tipo_recurso": "AGUA_POTABLE", "cantidad": 1}])]:
        status, _ = v.pedir("POST", "/evaluaciones", {
            "emergencia_id": int(time.time()), "gravedad": "ALTO",
            "lotes": [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 2}], "ofertas": [{"cuit": CRUZ_ROJA, "items": items}]})
        v.check(f"V15 Evaluar una oferta {nombre} → 422 (no reserva nada)", status == 422)

    print("\n== R. Reserva: evaluar, confirmar y liberar (deja el inventario como estaba)")
    emergencia = int(time.time())  # única por corrida: una referencia liberada no se puede evaluar de nuevo
    ref = f"emg-{emergencia}-r1-{CRUZ_ROJA}"
    ref_b = f"emg-{emergencia}-r1-{BOMBEROS}"
    pedido = {"emergencia_id": emergencia, "ronda": 1, "gravedad": "ALTO",
              "lotes": [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 10}],
              "ofertas": [{"cuit": CRUZ_ROJA, "items": [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 4}]},
                          {"cuit": BOMBEROS, "items": [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 2}]}]}

    def comprometidos() -> tuple[int, int]:
        return tuple(
            next(i for i in v.pedir("GET", f"/ongs/{c}")[1]["inventario"] if i["tipo_recurso"] == "PARAMEDICO")["cantidad_comprometida"]
            for c in (CRUZ_ROJA, BOMBEROS))

    status, ev = v.pedir("POST", "/evaluaciones", pedido)
    v.check("R1 Evaluar: cobertura 60 % (4 + 2 de 10), incompleta",
            status == 200 and (ev["porcentaje_cobertura"], ev["cobertura_completa"]) == (60.0, False), (status, ev))
    v.check("R2 Cada ONG recibe su referencia, RESERVADA",
            status == 200 and [(o["referencia"], o["estado"]) for o in ev["ongs"]] == [
                (ref, "RESERVADA"), (ref_b, "RESERVADA")], ev)
    v.check("R3 La reserva bloqueó el stock: 4 y 2 comprometidos", comprometidos() == (4, 2), comprometidos())
    v.check("R4 Repetir la evaluación devuelve lo mismo", v.pedir("POST", "/evaluaciones", pedido) == (200, ev))
    v.check("R5 …y no reserva dos veces", comprometidos() == (4, 2), comprometidos())
    v.check("R6 Confirmar Cruz Roja → ADJUDICADA",
            v.pedir("POST", f"/adjudicaciones/{ref}/confirmar") == (200, {"referencia": ref, "estado": "ADJUDICADA"}))
    status, lib = v.pedir("POST", f"/adjudicaciones/{ref_b}/liberar")
    v.check("R7 Liberar Bomberos devuelve sus 2 paramédicos",
            status == 200 and lib["estado"] == "LIBERADA" and lib["liberado"] == [{"tipo_recurso": "PARAMEDICO", "cantidad": 2}]
            and comprometidos() == (4, 0), (status, lib, comprometidos()))
    v.check("R8 Liberar de nuevo no resta otra vez",
            v.pedir("POST", f"/adjudicaciones/{ref_b}/liberar")[0] == 200 and comprometidos() == (4, 0))
    v.check("R9 Una liberada no se confirma → 409", v.pedir("POST", f"/adjudicaciones/{ref_b}/confirmar")[0] == 409)
    v.check("R10 Referencia inexistente → 404", v.pedir("POST", "/adjudicaciones/no-existe/confirmar")[0] == 404)
    status, _ = v.pedir("POST", f"/adjudicaciones/{ref}/liberar")
    v.check("R11 Liberar la adjudicada deja el inventario como al principio",
            status == 200 and comprometidos() == (0, 0), (status, comprometidos()))
    de_mas = {**pedido, "emergencia_id": emergencia + 1,
              "ofertas": [{"cuit": CRUZ_ROJA, "items": [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 5}]}]}
    status, ev = v.pedir("POST", "/evaluaciones", de_mas)
    v.check("R12 Ofrecer más de lo que tiene (5 > 4): NO_RESERVADA, sin recortar ni reservar nada",
            status == 200 and (ev["ongs"][0]["estado"], ev["ongs"][0]["items"][0]["reservado"]) == ("NO_RESERVADA", 0)
            and comprometidos() == (0, 0), (status, ev, comprometidos()))
    segunda = {**pedido, "emergencia_id": emergencia + 2}
    ref2, ref2_b = f"emg-{emergencia + 2}-r1-{CRUZ_ROJA}", f"emg-{emergencia + 2}-r1-{BOMBEROS}"
    v.pedir("POST", "/evaluaciones", segunda)
    status, res = v.pedir("POST", "/adjudicaciones/resolucion", {"confirmar": [ref2], "liberar": [ref2_b]})
    v.check("R13 Resolución: confirma Cruz Roja y libera Bomberos en una sola llamada",
            status == 200 and [c["estado"] for c in res["confirmadas"]] == ["ADJUDICADA"]
            and [x["estado"] for x in res["liberadas"]] == ["LIBERADA"] and comprometidos() == (4, 0),
            (status, res, comprometidos()))
    v.check("R14 Repetir la resolución no cambia nada",
            v.pedir("POST", "/adjudicaciones/resolucion", {"confirmar": [ref2], "liberar": [ref2_b]})[0] == 200
            and comprometidos() == (4, 0))
    v.pedir("POST", f"/adjudicaciones/{ref2}/liberar")
    v.check("R15 Al liberar la adjudicada, el inventario queda como al principio", comprometidos() == (0, 0), comprometidos())

    print("\n== C. Cierre: libera exactamente lo que comprometió la referencia (deja el inventario como estaba)")
    cierre = emergencia + 3
    ref3 = f"emg-{cierre}-r1-{CRUZ_ROJA}"
    v.pedir("POST", "/evaluaciones", {
        **pedido, "emergencia_id": cierre,
        "ofertas": [{"cuit": CRUZ_ROJA, "items": [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 3}]}]})
    v.check("C1 Una reserva sin confirmar no se cierra → 409",
            v.pedir("POST", "/cierres", {"cuit": CRUZ_ROJA, "referencia": ref3})[0] == 409 and comprometidos() == (3, 0))
    v.pedir("POST", f"/adjudicaciones/{ref3}/confirmar")
    status, cie = v.pedir("POST", "/cierres", {"cuit": CRUZ_ROJA, "referencia": ref3})
    v.check("C2 Cerrar la adjudicada libera sus 3 paramédicos y deja el inventario como al principio",
            status == 201 and cie["items"][0]["cantidad_liberada"] == 3 and comprometidos() == (0, 0), (status, cie))
    status, otra = v.pedir("POST", "/cierres", {"cuit": CRUZ_ROJA, "referencia": ref3})
    v.check("C3 Repetir el cierre devuelve el mismo, sin restar de nuevo",
            status == 200 and otra["id"] == cie["id"] and comprometidos() == (0, 0), (status, otra))
    v.check("C4 Referencia inexistente → 404",
            v.pedir("POST", "/cierres", {"cuit": CRUZ_ROJA, "referencia": "no-existe"})[0] == 404)
    v.check("C5 Una cerrada no se libera ni se evalúa de nuevo → 409",
            v.pedir("POST", f"/adjudicaciones/{ref3}/liberar")[0] == 409
            and v.pedir("POST", "/evaluaciones", {
                **pedido, "emergencia_id": cierre,
                "ofertas": [{"cuit": CRUZ_ROJA, "items": [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 3}]}]})[0] == 409)
    status, lista = v.pedir("GET", f"/ongs/{CRUZ_ROJA}/cierres")
    v.check("C6 El cierre queda en GET /ongs/{cuit}/cierres",
            status == 200 and any(c["id"] == cie["id"] for c in lista), (status, lista))
    status, uno_cierre = v.pedir("GET", f"/cierres/{cie['id']}")
    v.check("C6b GET /cierres/{id} devuelve el cierre informado",
            status == 200 and (uno_cierre["id"], uno_cierre["cuit"], uno_cierre["referencia"]) == (cie["id"], CRUZ_ROJA, ref3), (status, uno_cierre))
    v.check("C6c Un cierre que no existe → 404", v.pedir("GET", "/cierres/999999999")[0] == 404)
    v.check("C6d Una ONG no consulta cierres → 403", v.pedir("GET", f"/cierres/{cie['id']}", token=ong)[0] == 403)
    lote = emergencia + 4
    v.pedir("POST", "/evaluaciones", {**pedido, "emergencia_id": lote})
    refs = [f"emg-{lote}-r1-{CRUZ_ROJA}", f"emg-{lote}-r1-{BOMBEROS}"]
    for ref in refs:
        v.pedir("POST", f"/adjudicaciones/{ref}/confirmar")
    cuerpo_lote = {"cierres": [{"cuit": CRUZ_ROJA, "referencia": refs[0]}, {"cuit": BOMBEROS, "referencia": refs[1]}]}
    status, cerrados = v.pedir("POST", "/cierres/lote", cuerpo_lote)
    v.check("C7 El lote cierra las dos ONGs en una llamada y deja el inventario como al principio",
            status == 200 and [c["items"][0]["cantidad_liberada"] for c in cerrados] == [4, 2] and comprometidos() == (0, 0),
            (status, cerrados, comprometidos()))
    status, otra = v.pedir("POST", "/cierres/lote", cuerpo_lote)
    v.check("C8 Repetir el lote devuelve los mismos cierres, sin restar de nuevo",
            status == 200 and [c["id"] for c in otra] == [c["id"] for c in cerrados] and comprometidos() == (0, 0))

    print("\n== D. Adjudicación directa (POST /adjudicaciones): compromete y se libera (deja el inventario como estaba)")

    def comprometido_seed() -> int:
        return sum(i["cantidad_comprometida"] for c in (CRUZ_ROJA, BOMBEROS, SUSPENDIDA)
                   for i in v.pedir("GET", f"/ongs/{c}")[1]["inventario"])

    directa = f"verif-{emergencia}-directa"

    def cuerpo_d(ong_id: int, inv_id: int, cantidad: int = 1, ref: str = directa) -> dict:
        return {"referencia_id": ref, "ong_id": ong_id, "emergencia_id": emergencia + 5,
                "items": [{"inventario_id": inv_id, "cantidad": cantidad}]}

    previo = comprometido_seed()
    hallado = None
    # ong_id e inventario_id son ids internos que ningún endpoint publica: se buscan entre los primeros (400 = no coincide, 409 = sin stock).
    for ong_id in range(1, 6):
        for inv_id in range(1, 41):
            status, adj = v.pedir("POST", "/adjudicaciones", cuerpo_d(ong_id, inv_id))
            if status == 201:
                hallado = (ong_id, inv_id, adj)
                break
            if status not in (400, 409):
                break
        if hallado:
            break
    v.check("D1 Una ONG no adjudica → 403 y sin token → 401",
            v.pedir("POST", "/adjudicaciones", cuerpo_d(1, 1, ref="verif-sin-permiso"), token=ong)[0] == 403
            and v.pedir("POST", "/adjudicaciones", cuerpo_d(1, 1, ref="verif-sin-permiso"), token=None)[0] == 401)
    v.check("D2 Adjudicar compromete lo pedido (201, ADJUDICADA)",
            hallado is not None and hallado[2]["estado"] == "ADJUDICADA" and hallado[2]["referencia_id"] == directa
            and comprometido_seed() == previo + 1, hallado)
    if hallado:
        ong_id, inv_id, adj = hallado
        status, otra = v.pedir("POST", "/adjudicaciones", cuerpo_d(ong_id, inv_id))
        v.check("D3 Repetir la referencia devuelve la misma (200) sin comprometer otra vez",
                status == 200 and otra["id"] == adj["id"] and comprometido_seed() == previo + 1, (status, otra))
        v.check("D4 Pedir más de lo disponible → 409 y no compromete nada",
                v.pedir("POST", "/adjudicaciones", cuerpo_d(ong_id, inv_id, 10**9, ref=directa + "-de-mas"))[0] == 409
                and comprometido_seed() == previo + 1)
        v.check("D5 Un inventario que no es de esa ONG o no existe → 400",
                v.pedir("POST", "/adjudicaciones", cuerpo_d(ong_id, 10**6, ref=directa + "-inexistente"))[0] == 400)
        v.check("D6 El mismo inventario dos veces en un pedido → 400",
                v.pedir("POST", "/adjudicaciones", {**cuerpo_d(ong_id, inv_id, ref=directa + "-repetido"),
                                                    "items": [{"inventario_id": inv_id, "cantidad": 1}] * 2})[0] == 400)
        v.check("D7 Cantidad 0 → 422",
                v.pedir("POST", "/adjudicaciones", cuerpo_d(ong_id, inv_id, 0, ref=directa + "-cero"))[0] == 422)
        status, lib = v.pedir("POST", f"/adjudicaciones/{directa}/liberar")
        v.check("D8 Liberarla devuelve el stock: el inventario queda como al principio",
                status == 200 and lib["estado"] == "LIBERADA" and comprometido_seed() == previo, (status, lib))

    if args.crear_ong:
        print("\n== O. Registro de una ONG nueva (POST /ongs): DEJA UNA ONG EN LA BASE")
        marca = int(time.time())
        cuit_nuevo, usuario_nuevo = f"30-{marca % 10**8:08d}-9", f"verif.{marca}"
        cuerpo_o = {"ong_nombre": f"ONG de verificación {marca}", "cuit": cuit_nuevo, "nombre": "Verificador",
                    "username": usuario_nuevo, "password": "clave-de-verificacion"}
        status, reg = v.pedir("POST", "/ongs", cuerpo_o, token=None)
        v.check("O1 Registrar una ONG nueva → 201 con su token", status == 201 and reg["user"]["cuit"] == cuit_nuevo, (status, reg))
        token_nuevo = v.entrar(usuario_nuevo, "clave-de-verificacion")
        v.check("O2 La cuenta nueva inicia sesión", token_nuevo is not None)
        status, ficha = v.pedir("GET", f"/ongs/{cuit_nuevo}")
        v.check("O3 Queda HABILITADA y sin inventario", status == 200 and ficha["estado"] == "HABILITADA" and ficha["inventario"] == [], (status, ficha))
        status, inv = v.pedir("PUT", f"/ongs/{cuit_nuevo}/inventario",
                              {"items": [{"tipo_recurso": "FRAZADA", "cantidad_total": 5}]}, token=token_nuevo)
        v.check("O4 Declara su inventario con su propio token (200)",
                status == 200 and any(i["tipo_recurso"] == "FRAZADA" and i["cantidad_total"] == 5 for i in inv), (status, inv))
        v.check("O5 Figura en GET /ongs", cuit_nuevo in {o["cuit"] for o in v.pedir("GET", "/ongs")[1]})
        v.check("O6 Registrarla de nuevo → 409", v.pedir("POST", "/ongs", cuerpo_o, token=None)[0] == 409)

    print(f"\n{v.ok}/{v.total} verificaciones OK")
    return 0 if v.ok == v.total else 1


if __name__ == "__main__":
    sys.exit(main())
