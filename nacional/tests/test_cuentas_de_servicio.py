"""La app local y Bonita entran a esta API con cuentas de servicio; las personas no."""
import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


def _token(client, username, password):
    r = client.post("/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_la_cuenta_de_servicio_de_la_app_puede_liberar_y_validar(client):
    s = get_settings()
    app_service = _token(client, s.app_service_username, s.app_service_password)

    # 404 = pasó la autorización; la reserva no existe
    assert client.post("/adjudicaciones/no-existe/liberar", headers=app_service).status_code == 404
    validar = {"gravedad": "BAJO", "items": [{"cuit": "30-54666544-5", "tipo_recurso": "PARAMEDICO", "cantidad": 1}]}
    assert client.post("/validaciones", json=validar, headers=app_service).status_code == 200
    assert client.get("/tipos-recurso", headers=app_service).status_code == 200


def test_una_persona_no_puede_liberar_reservas(client):
    coordinador = _token(client, "coordinador.regional", "demo1234")
    assert client.post("/adjudicaciones/no-existe/liberar", headers=coordinador).status_code == 403


def test_las_dos_cuentas_de_servicio_son_distintas_y_ambas_entran(client):
    s = get_settings()
    assert s.app_service_username != s.bonita_service_username
    for usuario, clave in ((s.bonita_service_username, s.bonita_service_password),
                           (s.app_service_username, s.app_service_password)):
        assert client.post("/cierres/lote", json={"cierres": []}, headers=_token(client, usuario, clave)).status_code != 403


def test_en_la_nube_no_arranca_con_los_secretos_de_ejemplo():
    nube = "postgresql://u:p@host:5432/nacional"
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url=nube)
    for nombre in ("JWT_SECRET", "BONITA_SERVICE_PASSWORD", "APP_SERVICE_PASSWORD"):
        assert nombre in str(error.value)

    propios = Settings(_env_file=None, database_url=nube, jwt_secret="a" * 40,
                       bonita_service_password="b" * 20, app_service_password="c" * 20)
    assert propios.database_url.startswith("postgresql+psycopg://")


def test_en_sqlite_sirven_los_valores_de_ejemplo():
    Settings(_env_file=None, database_url="sqlite://")
