import os

# Antes de importar la app: que ningún test toque dev.db ni un Postgres real.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SESSION_SECRET"] = "test-secret"
os.environ["BONITA_BASE_URL"] = "http://bonita.test/bonita"  # nunca pegarle a un Bonita real en los tests
os.environ["NACIONAL_BASE_URL"] = "http://nacional.test"  # nunca pegarle a una API Nacional real en los tests
os.environ["SHOW_DEMO_USERS"] = "false"  # que el .env local de cada uno no cambie lo que ven los tests

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.integrations.nacional import NacionalError, get_nacional  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import DEMO_PASSWORD, seed  # noqa: E402

PASSWORD = DEMO_PASSWORD


@pytest.fixture(autouse=True)
def _bonita_sin_espera(monkeypatch):
    """Los reintentos de get_human_tasks no deben hacer esperar a los tests."""
    from app.integrations import bonita as bonita_mod

    monkeypatch.setattr(bonita_mod.time, "sleep", lambda s: None)


@pytest.fixture
def session_factory():
    """BD en memoria, con las tablas creadas desde los modelos y una sola conexión compartida."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def db(session_factory):
    with session_factory() as session:
        yield session


@pytest.fixture
def seeded(session_factory):
    seed(session_factory)
    return session_factory


class FakeNacional:
    """Sustituye al Sistema Nacional en los tests; el cliente HTTP real se prueba en test_nacional_client.py."""

    TIPOS = [
        {"codigo": "PARAMEDICO", "nombre": "Paramédico", "categoria": "PERSONAL", "unidad": "personas",
         "certificacion_requerida": "SALUD_PREHOSP"},
        {"codigo": "RACION_ALIMENTO", "nombre": "Ración de alimento", "categoria": "INSUMO", "unidad": "raciones",
         "certificacion_requerida": None},
        {"codigo": "AGUA_POTABLE", "nombre": "Agua potable", "categoria": "INSUMO", "unidad": "litros",
         "certificacion_requerida": None},
    ]

    def __init__(self):
        self.caido = False
        # Disponible por (CUIT de la ONG, tipo de recurso): lo mismo que cargan los seeds.
        self.inventario = {
            ("30-54666544-5", "PARAMEDICO"): 4,
            ("30-54666544-5", "RACION_ALIMENTO"): 5000,
            ("30-68522415-9", "PARAMEDICO"): 6,
        }
        self.validaciones = []  # (gravedad, items) de cada llamada a validar()
        self.liberadas = []  # referencia de cada llamada a liberar()

    def _verificar(self):
        if self.caido:
            raise NacionalError("Sistema Nacional caído (simulado)")

    def liberar(self, referencia):
        self._verificar()
        self.liberadas.append(referencia)
        return {"referencia": referencia, "estado": "LIBERADA", "liberado": []}

    def tipos_recurso(self):
        self._verificar()
        return self.TIPOS

    def validar(self, gravedad, items):
        """Como la API real: suma lo pedido por (ONG, recurso) y compara con lo disponible."""
        self._verificar()
        self.validaciones.append((gravedad, items))
        pedido = {}
        for i in items:
            clave = (i["cuit"], i["tipo_recurso"])
            pedido[clave] = pedido.get(clave, 0) + i["cantidad"]
        tipos = {t["codigo"]: t for t in self.TIPOS}
        resultados = [
            {"cuit": cuit, "tipo_recurso": codigo, "nombre_recurso": tipos[codigo]["nombre"],
             "unidad": tipos[codigo]["unidad"], "solicitado": n, "disponible": self.inventario.get((cuit, codigo), 0),
             "alcanza": n <= self.inventario.get((cuit, codigo), 0), "nivel": "PLENA",
             "riesgo_permitido": "CRITICO", "asignacion_sugerida": "PRINCIPAL", "observaciones": []}
            for (cuit, codigo), n in pedido.items()
        ]
        return {"alcanza_todo": all(r["alcanza"] for r in resultados), "resultados": resultados}


@pytest.fixture
def nacional():
    return FakeNacional()


@pytest.fixture
def client(seeded, nacional):
    def _get_db():
        with seeded() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_nacional] = lambda: nacional
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def login(client):
    def _login(username: str):
        r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        assert r.status_code == 200, f"login de {username} falló: {r.status_code}"
        return client

    return _login
