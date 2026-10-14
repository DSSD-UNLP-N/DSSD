import os

# Antes de importar la app: que ningún test toque dev.db ni un Postgres real.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["BONITA_BASE_URL"] = "http://bonita.test/bonita"  # nunca pegarle a un Bonita real en los tests
os.environ["SHOW_DEMO_USERS"] = "false"  # que el .env local de cada uno no cambie lo que ven los tests

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base, get_db  # noqa: E402
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


@pytest.fixture
def client(seeded):
    def _get_db():
        with seeded() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def login(client):
    def _login(username: str):
        r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        assert r.status_code == 200, f"login de {username} falló: {r.status_code}"
        client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        return client

    return _login
