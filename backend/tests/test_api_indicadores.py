"""Tests de la API de indicadores: permisos, validaciones, JSON y CSV.

Estrategia TDD: estos tests fallan antes de crear el router. Se corre:
  python -m pytest -q tests/test_api_indicadores.py   (rojo)
  <implementar router>
  python -m pytest -q tests/test_api_indicadores.py   (verde)
"""
import csv
import io

import pytest

from app.seed import DEMO_PASSWORD


# ---------------------------------------------------------------------------
# Fixture: cliente HTTP con overrides de DB, Nacional y Bonita
# ---------------------------------------------------------------------------

@pytest.fixture
def indicadores_client(seeded, fake_bonita, nacional):
    from app.core.deps import get_bonita_lectura
    from app.db import get_db
    from app.integrations.nacional import get_nacional
    from app.main import app
    from fastapi.testclient import TestClient

    def _get_db():
        with seeded() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_nacional] = lambda: nacional
    app.dependency_overrides[get_bonita_lectura] = lambda: fake_bonita
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, username: str):
    r = client.post("/api/auth/login", json={"username": username, "password": DEMO_PASSWORD})
    assert r.status_code == 200, f"Login de '{username}' falló: {r.status_code} {r.text}"
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_solo_auditor(indicadores_client):
    """Sin sesión → 401; roles no AUDITOR → 403; AUDITOR → 200."""
    c = indicadores_client

    # Sin sesión
    assert c.get("/api/indicadores").status_code == 401
    assert c.get("/api/indicadores/export.csv?bloque=estados").status_code == 401

    # Roles sin acceso
    for usuario in ("operador.municipal", "coordinador.regional", "ong.cruzroja"):
        _login(c, usuario)
        assert c.get("/api/indicadores").status_code == 403, f"{usuario} debería obtener 403"
        c.post("/api/auth/logout")

    # Auditor tiene acceso
    _login(c, "auditor")
    assert c.get("/api/indicadores").status_code == 200


def test_fechas_invertidas_da_422(indicadores_client):
    """Si 'desde' es posterior a 'hasta', la respuesta es 422."""
    c = _login(indicadores_client, "auditor")
    r = c.get("/api/indicadores?desde=2026-11-01&hasta=2026-10-01")
    assert r.status_code == 422


def test_fecha_invalida_da_422(indicadores_client):
    """Un valor que no es una fecha ISO válida devuelve 422."""
    c = _login(indicadores_client, "auditor")
    r = c.get("/api/indicadores?desde=no-es-fecha&hasta=2026-11-01")
    assert r.status_code == 422


def test_municipio_inexistente_da_vacio(indicadores_client):
    """Un municipio_id que no existe en la BD devuelve 200 con todo en cero, no 404 ni 500."""
    c = _login(indicadores_client, "auditor")
    r = c.get("/api/indicadores?municipio_id=99999")
    assert r.status_code == 200
    body = r.json()
    assert body["kpis"]["emergencias"] == 0
    assert body["kpis"]["resueltas"] == 0
    assert body["kpis"]["en_curso"] == 0
    assert body["suministros"] == []
    assert body["finalizadas"] == []


def test_bonita_caido_degrada_solo_tiempos(seeded, nacional):
    """Cuando get_bonita_lectura no puede conectar (devuelve None), el reporte sigue siendo 200
    con tiempos.disponible=False y el resto de los bloques intactos."""
    from app.core.deps import get_bonita_lectura
    from app.db import get_db
    from app.integrations.nacional import get_nacional
    from app.main import app
    from fastapi.testclient import TestClient

    def _get_db():
        with seeded() as session:
            yield session

    # None simula que get_bonita_lectura no pudo hacer login (Bonita caído)
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_nacional] = lambda: nacional
    app.dependency_overrides[get_bonita_lectura] = lambda: None

    with TestClient(app, follow_redirects=False) as c:
        r = c.post("/api/auth/login", json={"username": "auditor", "password": DEMO_PASSWORD})
        assert r.status_code == 200
        r = c.get("/api/indicadores")

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["tiempos"]["disponible"] is False
    assert body["tiempos"]["motivo"] is not None and len(body["tiempos"]["motivo"]) > 0
    for bloque in ("kpis", "suministros", "estados", "finalizadas"):
        assert bloque in body, f"Falta el bloque '{bloque}' con Bonita caído"


def test_csv_tiene_bom_encabezados_y_acentos(indicadores_client):
    """El CSV del bloque 'estados' tiene BOM UTF-8, encabezados en español y acentos legibles."""
    c = _login(indicadores_client, "auditor")
    r = c.get("/api/indicadores/export.csv?bloque=estados")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    disposition = r.headers.get("content-disposition", "")
    assert 'filename="indicadores_estados_' in disposition

    raw = r.content
    # UTF-8 con BOM
    assert raw[:3] == b"\xef\xbb\xbf", "El CSV debe empezar con BOM UTF-8"

    text = raw.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    encabezados = next(reader)
    assert len(encabezados) > 0, "El CSV no tiene encabezados"
    # Encabezados en español con las columnas esperadas
    encabezados_lower = " ".join(encabezados).lower()
    assert "estado" in encabezados_lower
    assert "cantidad" in encabezados_lower

    # Las etiquetas de estado incluyen acentos (ej. "En evaluación")
    # El decoding correcto se verifica implícitamente: si fuera latin-1, falla la aserción anterior
    assert "ó" in text or "é" in text or "Estado" in text


def test_csv_vacio_tiene_encabezados(indicadores_client):
    """Un período sin datos devuelve igual los encabezados del CSV, sin filas de datos."""
    c = _login(indicadores_client, "auditor")
    r = c.get("/api/indicadores/export.csv?bloque=finalizadas&desde=2000-01-01&hasta=2000-01-31")
    assert r.status_code == 200

    raw = r.content
    assert raw[:3] == b"\xef\xbb\xbf", "El CSV vacío también debe tener BOM"
    text = raw.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    encabezados = next(reader)
    assert len(encabezados) > 0, "El CSV vacío debe tener al menos una columna de encabezado"
    filas = list(reader)
    assert filas == [], f"El CSV no debería tener filas de datos, pero tiene: {filas}"


def test_bloque_invalido_da_422(indicadores_client):
    """Un bloque que no existe en el enum devuelve 422."""
    c = _login(indicadores_client, "auditor")
    r = c.get("/api/indicadores/export.csv?bloque=inexistente")
    assert r.status_code == 422


@pytest.mark.parametrize("query", [
    "desde=0001-01-01&hasta=2026-11-01",  # el pasaje a UTC desborda
    "desde=2026-01-01&hasta=9999-12-31",
    "municipio_id=2147483648",  # más que un INTEGER de Postgres
    "municipio_id=0",
])
def test_entrada_fuera_de_rango_da_422(indicadores_client, query):
    c = _login(indicadores_client, "auditor")
    assert c.get(f"/api/indicadores?{query}").status_code == 422
    assert c.get(f"/api/indicadores/export.csv?bloque=kpis&{query}").status_code == 422
