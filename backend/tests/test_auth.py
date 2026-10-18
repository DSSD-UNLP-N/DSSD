"""Login JWT, onboarding ONG y control de acceso por rol (T-04)."""
import pytest
from fastapi import Depends
from sqlalchemy import select

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


def test_sin_token_devuelve_401_json(client):
    for ruta in ("/api/auth/me", "/api/_t/coord", "/api/emergencias"):
        r = client.get(ruta)
        assert r.status_code == 401 and "detail" in r.json(), ruta


@pytest.mark.parametrize("password", ["incorrecta", "DEMO1234"])
def test_login_con_password_incorrecta(client, password):
    r = client.post("/api/auth/login", json={"username": "ong.cruzroja", "password": password})
    assert r.status_code == 401
    assert "incorrectos" in r.json()["detail"]
    assert client.get("/api/auth/me").status_code == 401


def test_login_con_password_vacia_es_rechazado(client):
    r = client.post("/api/auth/login", json={"username": "ong.cruzroja", "password": ""})
    assert r.status_code in (401, 422)
    assert client.get("/api/auth/me").status_code == 401


def test_login_de_usuario_inexistente(client):
    r = client.post("/api/auth/login", json={"username": "nadie", "password": "demo1234"})
    assert r.status_code == 401


def test_login_emite_jwt_y_autoriza_rutas(client):
    from app.integrations.nacional import get_nacional

    import jwt
    from app.core.config import get_settings

    response = client.post(
        "/api/auth/login",
        json={"username": "ong.cruzroja", "password": "demo1234"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["user"]["username"] == "ong.cruzroja"
    claims = jwt.decode(
        payload["access_token"],
        get_settings().jwt_secret,
        algorithms=["HS256"],
    )
    assert claims["username"] == "ong.cruzroja"
    assert claims["rol"] == "ONG"
    assert claims["exp"] > claims["iat"]
    assert client.app.dependency_overrides[get_nacional]().login_calls == [
        ("ong.cruzroja", "demo1234")
    ]
    assert client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    ).json()["username"] == "ong.cruzroja"


def test_api_nacional_login_y_registro_ong(client):
    login_response = client.post(
        "/login",
        json={"username": "ong.cruzroja", "password": "demo1234"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["user"]["rol"] == "ONG"

    register_response = client.post(
        "/ongs",
        json={
            "ong_nombre": "Rescate Nacional",
            "cuit": "30-55555555-5",
            "nombre": "Representante",
            "username": "representante.rescate",
            "password": "clave-segura-123",
        },
    )
    assert register_response.status_code == 201
    assert register_response.json()["user"]["rol"] == "ONG"


@pytest.mark.parametrize(
    "error,status_code,detail",
    [
        (
            "missing",
            502,
            "La API Nacional desplegada no tiene disponible POST /login; hay que actualizar su despliegue.",
        ),
        ("rejected", 401, "Usuario o contraseña incorrectos"),
    ],
)
def test_login_informa_correctamente_errores_de_autenticacion_nacional(
    client, nacional, monkeypatch, error, status_code, detail
):
    from app.integrations.nacional import NacionalLoginEndpointMissing, NacionalLoginRejected

    exception = NacionalLoginEndpointMissing if error == "missing" else NacionalLoginRejected

    def reject_login(username, password):
        raise exception("fallo simulado")

    monkeypatch.setattr(nacional, "login", reject_login)
    response = client.post(
        "/api/auth/login",
        json={"username": "ong.cruzroja", "password": "demo1234"},
    )

    assert response.status_code == status_code
    assert response.json()["detail"] == detail


def test_login_rechaza_credenciales_invalidas(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "ong.cruzroja", "password": "incorrecta"},
    )
    assert response.status_code == 401


def test_openapi_publica_bearer_para_swagger(client):
    schema = client.get("/openapi.json").json()
    security_schemes = schema["components"]["securitySchemes"]
    bearer = next(s for s in security_schemes.values() if s["type"] == "http")
    assert bearer["scheme"] == "bearer"
    login = schema["paths"]["/api/auth/login"]["post"]
    assert "application/json" in login["requestBody"]["content"]


def test_no_hay_endpoint_de_login_duplicado(client):
    assert client.post("/api/auth/token").status_code == 404


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


def test_logout_el_cliente_descarta_el_token(login):
    c = login("ong.cruzroja")
    assert c.post("/api/auth/logout").status_code == 204
    c.headers.pop("Authorization")
    assert c.get("/api/auth/me").status_code == 401


def test_token_de_usuario_borrado_deja_de_valer(login, seeded):
    from sqlalchemy import delete
    from app.models import Usuario

    c = login("auditor")
    with seeded() as s:
        s.execute(delete(Usuario).where(Usuario.username == "auditor"))
        s.commit()
    assert c.get("/api/auth/me").status_code == 401


def test_token_manipulado_devuelve_401(login):
    client = login("ong.cruzroja")
    client.headers["Authorization"] = "Bearer token.invalido"
    assert client.get("/api/auth/me").status_code == 401


def test_registro_ong_crea_ong_usuario_y_token(client, seeded):
    response = client.post(
        "/api/auth/register-ong",
        json={
            "ong_nombre": "Brigada Solidaria",
            "cuit": "30-12345678-9",
            "nombre": "Ana Pérez",
            "username": "ana.brigada",
            "password": "clave-segura-123",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["user"]["rol"] == "ONG"
    from app.integrations.nacional import get_nacional
    assert client.app.dependency_overrides[get_nacional]().registration_calls[0]["cuit"] == "30-12345678-9"
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {payload['access_token']}"}
    ).json()["username"] == "ana.brigada"
    from app.models import Ong, Usuario

    with seeded() as db:
        user = db.scalar(select(Usuario).where(Usuario.username == "ana.brigada"))
        assert user is not None and user.ong_id is not None
        assert db.get(Ong, user.ong_id).nombre == "Brigada Solidaria"


def test_registro_ong_rechaza_usuario_duplicado(client):
    response = client.post(
        "/api/auth/register-ong",
        json={
            "ong_nombre": "Nueva ONG",
            "nombre": "Ana Pérez",
            "username": "ong.cruzroja",
            "password": "clave-segura-123",
        },
    )
    assert response.status_code == 409


def test_registro_ong_exige_password_segura(client):
    response = client.post(
        "/api/auth/register-ong",
        json={
            "ong_nombre": "Nueva ONG",
            "nombre": "Ana Pérez",
            "username": "ana.nueva",
            "password": "corta",
        },
    )
    assert response.status_code == 422
