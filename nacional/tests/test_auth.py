import jwt
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Cuenta, RolCuenta
from app.security import verify_password
from app.seed import DEMO_PASSWORD


def test_login_emite_token_con_identidad_rol_y_expiracion(client):
    response = client.post(
        "/login",
        json={"username": "ong.cruzroja", "password": DEMO_PASSWORD},
    )

    assert response.status_code == 200
    body = response.json()
    claims = jwt.decode(body["access_token"], get_settings().jwt_secret, algorithms=["HS256"])
    assert body["user"] == {
        "username": "ong.cruzroja",
        "rol": "ONG",
        "cuit": "30-54666544-5",
    }
    assert claims["username"] == "ong.cruzroja"
    assert claims["rol"] == "ONG"
    assert claims["cuit"] == "30-54666544-5"
    assert claims["exp"] > claims["iat"]


@pytest.mark.parametrize(
    "username,password",
    [("ong.cruzroja", "incorrecta"), ("no-existe", DEMO_PASSWORD)],
)
def test_login_rechaza_credenciales_invalidas(client, username, password):
    response = client.post("/login", json={"username": username, "password": password})
    assert response.status_code == 401


def test_cuenta_de_servicio_bonita_se_crea_con_password_hasheada(client, session_factory):
    with session_factory() as db:
        cuenta = db.scalar(select(Cuenta).where(Cuenta.rol == RolCuenta.BONITA))

    assert cuenta is not None
    assert cuenta.password_hash != "change-me"
    assert verify_password("change-me", cuenta.password_hash)


def test_registro_ong_crea_cuenta_y_emite_token(client, session_factory):
    response = client.post(
        "/ongs",
        json={
            "ong_nombre": "Rescate Solidario",
            "cuit": "30-12345678-9",
            "nombre": "Ana Pérez",
            "username": "ana.rescate",
            "password": "clave-segura-123",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user"] == {
        "username": "ana.rescate",
        "rol": "ONG",
        "cuit": "30-12345678-9",
    }
    claims = jwt.decode(body["access_token"], get_settings().jwt_secret, algorithms=["HS256"])
    assert claims["username"] == "ana.rescate"
    with session_factory() as db:
        cuenta = db.scalar(select(Cuenta).where(Cuenta.username == "ana.rescate"))
        assert cuenta is not None
        assert cuenta.ong.cuit == "30-12345678-9"
        assert verify_password("clave-segura-123", cuenta.password_hash)


def test_registro_ong_rechaza_cuit_duplicado(client):
    response = client.post(
        "/ongs",
        json={
            "ong_nombre": "Otra ONG",
            "cuit": "30-54666544-5",
            "nombre": "Ana Pérez",
            "username": "ana.otra",
            "password": "clave-segura-123",
        },
    )
    assert response.status_code == 409
