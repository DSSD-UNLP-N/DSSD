def test_health(client, monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"estado": "ok", "commit": "local"}


def test_health_dice_que_commit_esta_desplegado(client, monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc1234")
    assert client.get("/health").json()["commit"] == "abc1234"


def test_swagger_expone_el_titulo(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert r.json()["info"]["title"] == "Sistema Nacional de Gestión de Recursos y Riesgos"
