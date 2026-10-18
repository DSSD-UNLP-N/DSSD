import os

# Antes de importar la app: que ningún test toque nacional.db ni un Postgres real.
os.environ["DATABASE_URL"] = "sqlite://"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402


@pytest.fixture
def session_factory():
    """BD en memoria con las tablas creadas desde los modelos y una sola conexión compartida."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def db(session_factory):
    with session_factory() as session:
        yield session


@pytest.fixture
def client(session_factory):
    seed(session_factory)

    def _get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as c:
        settings = get_settings()
        response = c.post(
            "/login",
            json={
                "username": settings.bonita_service_username,
                "password": settings.bonita_service_password,
            },
        )
        assert response.status_code == 200, response.text
        c.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def ong_headers(client):
    def _headers(cuit: str) -> dict[str, str]:
        username = {
            "30-54666544-5": "ong.cruzroja",
            "30-68522415-9": "ong.bomberos",
        }[cuit]
        response = client.post("/login", json={"username": username, "password": "demo1234"})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _headers
