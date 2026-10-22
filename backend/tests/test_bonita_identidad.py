import json
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from app.core.config import get_settings
from app.integrations.bonita import BonitaClient, BonitaError

BASE = get_settings().bonita_base_url


def _client() -> BonitaClient:
    return BonitaClient(BASE)


def _query(call) -> dict:
    return parse_qs(urlparse(call.request.url).query)


@responses.activate
def test_find_user_id_devuelve_id():
    responses.add(responses.GET, f"{BASE}/API/identity/user", json=[{"id": "42"}])
    assert _client().find_user_id("ong1") == "42"
    assert _query(responses.calls[0]) == {"f": ["userName=ong1"]}


@responses.activate
def test_find_user_id_inexistente_devuelve_none():
    responses.add(responses.GET, f"{BASE}/API/identity/user", json=[])
    assert _client().find_user_id("nadie") is None


@responses.activate
def test_create_user_envia_body_y_devuelve_id():
    responses.add(responses.POST, f"{BASE}/API/identity/user", json={"id": "7"})
    assert _client().create_user("ong1", "secreto123", "Ana") == "7"
    assert json.loads(responses.calls[0].request.body) == {
        "userName": "ong1",
        "password": "secreto123",
        "password_confirm": "secreto123",
        "firstname": "Ana",
        "lastname": "",
        "enabled": "true",
    }


@responses.activate
def test_group_id_busca_por_nombre_y_parent_path():
    responses.add(responses.GET, f"{BASE}/API/identity/group", json=[{"id": "11"}])
    assert _client().group_id("/rescuesync/ong") == "11"
    assert _query(responses.calls[0])["f"] == ["name=ong", "parent_path=/rescuesync"]


@responses.activate
def test_group_id_inexistente_lanza_bonita_error():
    responses.add(responses.GET, f"{BASE}/API/identity/group", json=[])
    with pytest.raises(BonitaError):
        _client().group_id("/rescuesync/ong")


@responses.activate
def test_role_id_devuelve_id():
    responses.add(responses.GET, f"{BASE}/API/identity/role", json=[{"id": "5"}])
    assert _client().role_id("representante_ong") == "5"
    assert _query(responses.calls[0]) == {"f": ["name=representante_ong"]}


@responses.activate
def test_role_id_inexistente_lanza_bonita_error():
    responses.add(responses.GET, f"{BASE}/API/identity/role", json=[])
    with pytest.raises(BonitaError):
        _client().role_id("nope")


@responses.activate
def test_add_membership_envia_ids():
    responses.add(responses.POST, f"{BASE}/API/identity/membership", json={})
    assert _client().add_membership("7", "11", "5") is None
    assert json.loads(responses.calls[0].request.body) == {
        "user_id": "7", "group_id": "11", "role_id": "5"
    }


@responses.activate
def test_delete_user_llama_delete():
    responses.add(responses.DELETE, f"{BASE}/API/identity/user/7", status=200)
    assert _client().delete_user("7") is None
    assert len(responses.calls) == 1
