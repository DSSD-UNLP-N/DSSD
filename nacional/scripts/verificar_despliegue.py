"""Verifica un despliegue de la API Nacional por HTTP: catálogo, fichas, disponibilidad y las reglas de
validación de ofertas. No modifica datos (solo lecturas, `POST /validaciones`, que no guarda nada, y `PUT`
que fallan antes de escribir). Espera los datos del seed (app/seed.py) sin nada comprometido.

    python scripts/verificar_despliegue.py https://sistema-nacional-latest.onrender.com
    python scripts/verificar_despliegue.py http://localhost:8002

Solo usa la biblioteca estándar: corre con cualquier Python 3.11+.
"""
import json
import sys
import time
import urllib.error
import urllib.request

CRUZ_ROJA, BOMBEROS, SUSPENDIDA = "30-54666544-5", "30-68522415-9", "30-70000000-1"


class Verificador:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.ok = self.total = 0

    def pedir(self, metodo: str, ruta: str, cuerpo=None, timeout: float = 90) -> tuple[int, object]:
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(f"{self.base}{ruta}", data=datos, method=metodo,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

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
    v = Verificador(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8002")
    print(f"API Nacional en {v.base}")

    print("\n== A1. Estado y Swagger")
    inicio = time.monotonic()
    status, salud = v.pedir("GET", "/health")
    print(f"     /health respondió en {time.monotonic() - inicio:.1f} s (si estaba dormido, tarda)")
    v.check("/health responde ok", status == 200 and salud == {"estado": "ok"}, (status, salud))
    status, api = v.pedir("GET", "/openapi.json")
    rutas = set(api["paths"]) if status == 200 else set()
    esperadas = {"/tipos-recurso", "/certificaciones", "/ongs", "/ongs/{cuit}", "/ongs/{cuit}/inventario",
                 "/recursos/disponibilidad", "/validaciones"}
    v.check("Swagger expone catálogo, inventario y validación", esperadas <= rutas, sorted(esperadas - rutas))
    print(f"     endpoints: {', '.join(sorted(rutas))}")

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
    v.check("3 ONGs registradas, 2 habilitadas", (len(todas), len(habilitadas)) == (3, 2), (len(todas), len(habilitadas)))
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
    v.check("CUIT inexistente → 404", v.pedir("GET", "/ongs/00-0-0")[0] == 404)

    print("\n== A6. Disponibilidad global")
    _, disp = v.pedir("GET", "/recursos/disponibilidad?tipo_recurso=PARAMEDICO")
    v.check("Paramédicos: 10 disponibles (4 + 6), desglosados por ONG",
            disp[0]["disponible"] == 10 and {o["cuit"] for o in disp[0]["por_ong"]} == {CRUZ_ROJA, BOMBEROS}, disp)
    _, raciones = v.pedir("GET", "/recursos/disponibilidad?tipo_recurso=RACION_ALIMENTO")
    v.check("Raciones: la ONG suspendida no suma (5000, no 5800)", raciones[0]["cantidad_total"] == 5000, raciones)
    v.check("Tipo inexistente → 404", v.pedir("GET", "/recursos/disponibilidad?tipo_recurso=NADA")[0] == 404)

    print("\n== A7. PUT de inventario que falla antes de escribir")
    v.check("ONG inexistente → 404",
            v.pedir("PUT", "/ongs/00-0-0/inventario", {"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 1}]})[0] == 404)
    v.check("Tipo inexistente → 404 (y no guarda el resto)",
            v.pedir("PUT", f"/ongs/{CRUZ_ROJA}/inventario", {"items": [
                {"tipo_recurso": "PARAMEDICO", "cantidad_total": 99}, {"tipo_recurso": "NADA", "cantidad_total": 1}]})[0] == 404)
    v.check("Cantidad negativa → 422",
            v.pedir("PUT", f"/ongs/{CRUZ_ROJA}/inventario", {"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": -1}]})[0] == 422)

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
    r = v.uno("BAJO", "00-0-0", "RACION_ALIMENTO", 1)
    v.check("V11 CUIT desconocido: se informa sin error (ong = null)", (r["ong"], r["nivel"]) == (None, "SUPERVISADA"), r)
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
    ]:
        v.check(f"V13 {nombre} → 422", v.pedir("POST", "/validaciones", cuerpo)[0] == 422)
    _, antes = v.pedir("GET", f"/ongs/{CRUZ_ROJA}")
    v.validar("ALTO", (CRUZ_ROJA, "PARAMEDICO", 3))
    _, despues = v.pedir("GET", f"/ongs/{CRUZ_ROJA}")
    v.check("V14 Validar no guarda nada: la ficha queda igual", antes == despues)

    print(f"\n{v.ok}/{v.total} verificaciones OK")
    return 0 if v.ok == v.total else 1


if __name__ == "__main__":
    sys.exit(main())
