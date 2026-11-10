"""Login, sesión y control de acceso por rol (T-04), por la API que usa la SPA."""
import pytest
from fastapi import Depends

from app.core.deps import require_role
from app.main import app
from app.models import Rol

USUARIOS = ["operador.municipal", "operador.municipal2", "coordinador.regional", "ong.cruzroja", "ong.bomberos",
            "auditor"]
ROL_DE = {"operador.municipal": "MUNICIPIO", "operador.municipal2": "MUNICIPIO", "coordinador.regional": "COORDINADOR",
          "ong.cruzroja": "ONG", "ong.bomberos": "ONG", "auditor": "AUDITOR"}


# Ruta de prueba, una vez por proceso: solo el Coordinador puede entrar.
if not any(getattr(r, "path", "") == "/api/_t/coord" for r in app.routes):
    @app.get("/api/_t/coord")
    def _t_api_coord(u=Depends(require_role(Rol.COORDINADOR))):
        return {"ok": u.username}


def test_usuarios_de_demo_ocultos_por_defecto(client):
    assert client.get("/api/meta").json()["demo"] is None


def test_usuarios_de_demo_visibles_si_se_activa(client):
    from app.core.config import Settings, get_settings

    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, show_demo_users=True)
    demo = client.get("/api/meta").json()["demo"]
    assert demo["password"] == "demo1234"
    assert {u["username"] for u in demo["users"]} == set(USUARIOS)


def test_sin_sesion_devuelve_401_json(client):
    for ruta in ("/api/auth/me", "/api/_t/coord", "/api/emergencias"):
        r = client.get(ruta)
        assert r.status_code == 401 and "detail" in r.json(), ruta


@pytest.mark.parametrize("password", ["incorrecta", "DEMO1234"])
def test_login_con_password_incorrecta(client, password):
    r = client.post("/api/auth/login", json={"username": "ong.cruzroja", "password": password})
    assert r.status_code == 401
    assert "incorrectos" in r.json()["detail"]
    assert client.get("/api/auth/me").status_code == 401  # sigue sin sesión


def test_login_con_password_vacia_es_rechazado(client):
    r = client.post("/api/auth/login", json={"username": "ong.cruzroja", "password": ""})
    assert r.status_code in (401, 422)
    assert client.get("/api/auth/me").status_code == 401


def test_login_de_usuario_inexistente(client):
    r = client.post("/api/auth/login", json={"username": "nadie", "password": "demo1234"})
    assert r.status_code == 401


@pytest.mark.parametrize("username", USUARIOS)
def test_cada_perfil_entra_y_se_reconoce(login, username):
    r = login(username).get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["username"] == username and r.json()["rol"] == ROL_DE[username]


def test_rol_incorrecto_da_403(login):
    r = login("ong.cruzroja").get("/api/_t/coord")
    assert r.status_code == 403 and "no tiene acceso" in r.json()["detail"]


def test_rol_correcto_pasa(login):
    assert login("coordinador.regional").get("/api/_t/coord").json() == {"ok": "coordinador.regional"}


def test_logout_cierra_la_sesion(login):
    c = login("ong.cruzroja")
    assert c.post("/api/auth/logout").status_code == 204
    assert c.get("/api/auth/me").status_code == 401


def test_sesion_de_usuario_borrado_deja_de_valer(login, seeded):
    from sqlalchemy import delete
    from app.models import Usuario

    c = login("auditor")
    with seeded() as s:
        s.execute(delete(Usuario).where(Usuario.username == "auditor"))
        s.commit()
    assert c.get("/api/auth/me").status_code == 401
