import json

import pytest
import responses

from app.core.config import get_settings
from app.core.security import verify_password
from app.integrations.nacional import NacionalError
from app.models import Ong, Rol
from app.services.alta_ong import AltaOngError, DatosAlta, alta_ong, normalizar_cuit

BASE = get_settings().bonita_base_url
RUBROS = [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 4}, {"tipo_recurso": "RACION_ALIMENTO", "cantidad_total": 0}]


def _datos(**kw) -> DatosAlta:
    base = dict(ong_nombre="Techo Digno", cuit="30-71234567-8", nombre="Ana Paz", username="ong.techo",
                password="secreto123", rubros=RUBROS)
    base.update(kw)
    return DatosAlta(**base)


def _mock_bonita_ok(usuario_existente=None):
    responses.add(responses.POST, f"{BASE}/loginservice", status=204,
                  headers={"Set-Cookie": "X-Bonita-API-Token=tok; Path=/"})
    responses.add(responses.GET, f"{BASE}/API/identity/user", json=usuario_existente or [])
    responses.add(responses.POST, f"{BASE}/API/identity/user", json={"id": "77"})
    responses.add(responses.GET, f"{BASE}/API/identity/group", json=[{"id": "5"}])
    responses.add(responses.GET, f"{BASE}/API/identity/role", json=[{"id": "3"}])
    responses.add(responses.POST, f"{BASE}/API/identity/membership", status=200, json={})
    responses.add(responses.DELETE, f"{BASE}/API/identity/user/77", status=200)


def _llamadas(metodo, sufijo):
    return [c for c in responses.calls if c.request.method == metodo and c.request.url.split("?")[0].endswith(sufijo)]


def _ongs(factory):
    with factory() as s:
        return [o.cuit for o in s.query(Ong).all()]


@responses.activate
def test_alta_ok_crea_en_los_tres_sistemas(seeded, nacional):
    _mock_bonita_ok()
    with seeded() as s:
        u = alta_ong(s, get_settings(), nacional, _datos())
        assert u.rol == Rol.ONG
        assert u.ong.cuit == "30-71234567-8"
        assert verify_password("secreto123", u.password_hash)
    assert nacional.ongs_registradas[0]["cuit"] == "30-71234567-8"
    assert nacional.inventarios["30-71234567-8"] == RUBROS
    assert json.loads(_llamadas("POST", "/API/identity/user")[0].request.body)["password"] == "bpm"
    assert json.loads(_llamadas("POST", "/API/identity/membership")[0].request.body) == {
        "user_id": "77", "group_id": "5", "role_id": "3"}
    assert "30-71234567-8" in _ongs(seeded)


@responses.activate
def test_duplicado_local_no_llama_a_nadie(seeded, nacional):
    with seeded() as s:
        with pytest.raises(AltaOngError) as e:
            alta_ong(s, get_settings(), nacional, _datos(username="ong.cruzroja"))
    assert e.value.status == 409
    assert len(responses.calls) == 0
    assert nacional.ongs_registradas == []


@responses.activate
def test_cuit_sin_guiones_se_normaliza_y_detecta_duplicado(seeded, nacional):
    with seeded() as s:
        with pytest.raises(AltaOngError) as e:
            alta_ong(s, get_settings(), nacional, _datos(cuit="30546665445"))
    assert e.value.status == 409
    assert normalizar_cuit("30712345678") == "30-71234567-8"
    with pytest.raises(AltaOngError) as e2:
        normalizar_cuit("123")
    assert e2.value.status == 422


@responses.activate
def test_usuario_ya_existe_en_bonita(seeded, nacional):
    _mock_bonita_ok(usuario_existente=[{"id": "9"}])
    with seeded() as s:
        with pytest.raises(AltaOngError) as e:
            alta_ong(s, get_settings(), nacional, _datos())
    assert e.value.status == 409
    assert _llamadas("POST", "/API/identity/user") == []
    assert nacional.ongs_registradas == []


@responses.activate
def test_bonita_login_falla_no_crea_nada(seeded, nacional):
    responses.add(responses.POST, f"{BASE}/loginservice", status=401)
    with seeded() as s:
        with pytest.raises(AltaOngError) as e:
            alta_ong(s, get_settings(), nacional, _datos())
    assert e.value.status == 503
    assert nacional.ongs_registradas == []
    assert "30-71234567-8" not in _ongs(seeded)


@responses.activate
def test_nacional_409_borra_usuario_bonita(seeded, nacional):
    _mock_bonita_ok()
    nacional.falla_registro = NacionalError("El CUIT ya está registrado", 409)
    with seeded() as s:
        with pytest.raises(AltaOngError) as e:
            alta_ong(s, get_settings(), nacional, _datos())
    assert e.value.status == 409
    assert "El CUIT ya está registrado" in str(e.value)
    assert len(_llamadas("DELETE", "/API/identity/user/77")) == 1
    assert "30-71234567-8" not in _ongs(seeded)


@responses.activate
def test_nacional_caido_borra_usuario_bonita(seeded, nacional):
    _mock_bonita_ok()
    nacional.falla_registro = NacionalError("timeout", None)
    with seeded() as s:
        with pytest.raises(AltaOngError) as e:
            alta_ong(s, get_settings(), nacional, _datos())
    assert e.value.status == 503
    assert len(_llamadas("DELETE", "/API/identity/user/77")) == 1


@responses.activate
def test_falla_inventario_avisa_que_quedo_sin_rubros(seeded, nacional):
    _mock_bonita_ok()
    nacional.falla_inventario = NacionalError("tipo inexistente", 404)
    with seeded() as s:
        with pytest.raises(AltaOngError) as e:
            alta_ong(s, get_settings(), nacional, _datos())
    assert e.value.status == 502
    assert "sin rubros" in str(e.value)
    assert "PUT /ongs/30-71234567-8/inventario" in str(e.value)
    assert len(_llamadas("DELETE", "/API/identity/user/77")) == 1
    assert "30-71234567-8" not in _ongs(seeded)
