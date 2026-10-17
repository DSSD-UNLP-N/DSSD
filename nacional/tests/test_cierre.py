"""Tests de POST /cierres con el nuevo contrato (WP3).

Flujo de estado: RESERVADA (POST /evaluaciones) → ADJUDICADA (POST /adjudicaciones/{ref}/confirmar)
                 → CERRADA (POST /cierres {cuit, referencia}).

Idempotencia (contratos.md §3.4): repetir POST /cierres con la misma referencia
devuelve 200 con el mismo cierre y no vuelve a restar inventario.
"""

CUIT = "30-54666544-5"
REF = "emg-1-r1-30-54666544-5"

# Cuerpo de evaluacion que reserva 2 PARAMEDICO de Cruz Roja Argentina.
_EVAL = {
    "emergencia_id": 1,
    "ronda": 1,
    "gravedad": "BAJO",
    "lotes": [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 2}],
    "ofertas": [
        {
            "cuit": CUIT,
            "items": [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 2}],
        }
    ],
}


def _inv(client, tipo: str, cuit: str = CUIT) -> dict:
    inventario = client.get(f"/ongs/{cuit}").json()["inventario"]
    return next(i for i in inventario if i["tipo_recurso"] == tipo)


def _reservar(client) -> str:
    """Crea la adjudicacion en estado RESERVADA y devuelve la referencia."""
    r = client.post("/evaluaciones", json=_EVAL)
    assert r.status_code == 200, r.text
    ong = next(o for o in r.json()["ongs"] if o["cuit"] == CUIT)
    return ong["referencia"]


def _confirmar(client, referencia: str) -> None:
    """Pasa la adjudicacion a ADJUDICADA."""
    r = client.post(f"/adjudicaciones/{referencia}/confirmar")
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Flujo principal
# ---------------------------------------------------------------------------

def test_reservar_confirmar_cerrar_libera_inventario(client):
    """reserve → confirm → close deja inventario exactamente como al principio."""
    antes = _inv(client, "PARAMEDICO")
    assert antes["cantidad_comprometida"] == 0

    ref = _reservar(client)
    assert ref == REF
    assert _inv(client, "PARAMEDICO")["cantidad_comprometida"] == 2

    _confirmar(client, ref)
    assert _inv(client, "PARAMEDICO")["cantidad_comprometida"] == 2

    r = client.post("/cierres", json={"cuit": CUIT, "referencia": ref})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["referencia"] == ref
    assert body["cuit"] == CUIT
    item = next(i for i in body["items"] if i["tipo_recurso"] == "PARAMEDICO")
    assert item["cantidad_liberada"] == 2
    assert item["cantidad_comprometida"] == 0
    assert item["disponible"] == antes["cantidad_total"]

    # Inventario volvio al punto de partida.
    despues = _inv(client, "PARAMEDICO")
    assert despues["cantidad_comprometida"] == 0
    assert despues["disponible"] == antes["cantidad_total"]


def test_cerrar_estado_reservada_da_409(client):
    """Intentar cerrar una adjudicacion que esta en RESERVADA (no confirmada) → 409."""
    ref = _reservar(client)
    r = client.post("/cierres", json={"cuit": CUIT, "referencia": ref})
    assert r.status_code == 409, r.text
    # Inventario no se toco.
    assert _inv(client, "PARAMEDICO")["cantidad_comprometida"] == 2


def test_cerrar_referencia_inexistente_da_409(client):
    """Referencia que no existe → 409."""
    r = client.post("/cierres", json={"cuit": CUIT, "referencia": "emg-999-r1-no-existe"})
    assert r.status_code == 409, r.text


def test_cierre_idempotente_devuelve_200(client):
    """Cerrar dos veces la misma referencia: segunda llamada → 200 con el mismo id, inventario sin cambios."""
    ref = _reservar(client)
    _confirmar(client, ref)

    r1 = client.post("/cierres", json={"cuit": CUIT, "referencia": ref})
    assert r1.status_code == 201, r1.text

    r2 = client.post("/cierres", json={"cuit": CUIT, "referencia": ref})
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == r1.json()["id"]

    # Inventario no se resto dos veces.
    assert _inv(client, "PARAMEDICO")["cantidad_comprometida"] == 0


def test_ong_desconocida_da_404(client):
    """CUIT inexistente → 404."""
    r = client.post("/cierres", json={"cuit": "00-0-0", "referencia": REF})
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# GET endpoints
# ---------------------------------------------------------------------------

def test_obtener_cierre_por_id(client):
    ref = _reservar(client)
    _confirmar(client, ref)
    creado = client.post("/cierres", json={"cuit": CUIT, "referencia": ref}).json()

    r = client.get(f"/cierres/{creado['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == creado["id"]
    assert r.json()["referencia"] == ref


def test_obtener_cierre_inexistente_da_404(client):
    assert client.get("/cierres/99999").status_code == 404


def test_cierres_de_ong(client):
    ref = _reservar(client)
    _confirmar(client, ref)
    client.post("/cierres", json={"cuit": CUIT, "referencia": ref})

    r = client.get(f"/ongs/{CUIT}/cierres")
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert r.json()[0]["referencia"] == ref


def test_cierres_ong_inexistente_da_404(client):
    assert client.get("/ongs/00-0-0/cierres").status_code == 404


# ---------------------------------------------------------------------------
# Validacion de entrada
# ---------------------------------------------------------------------------

def test_entradas_invalidas_dan_422(client):
    for body in (
        {"cuit": CUIT, "referencia": ""},           # referencia vacia
        {"cuit": "", "referencia": "emg-1"},         # cuit vacio
        {"referencia": "emg-1"},                     # falta cuit
        {"cuit": CUIT},                              # falta referencia
    ):
        assert client.post("/cierres", json=body).status_code == 422, body
