"""Cómo la API traduce a HTTP cada error de los servicios: código y mensaje que ve la SPA.

Fija el contrato de errores de routers/api.py: el servicio se reemplaza por uno que falla, así cada caso prueba solo la
traducción. Si se cambia la forma de mapear errores, estos tests tienen que seguir pasando igual.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.integrations.nacional import NacionalError
from app.models import EstadoEmergencia
from app.routers import api
from app.services.alta_ong import AltaOngError
from app.services.ciclo import CicloError
from app.services.emergencias import AltaEmergenciaError
from app.services.lotes import LoteError, PublicacionError
from app.services.ofertas import OfertaError
from tests.conftest import body_alta_ong as _alta_ong, crear_emergencia

MENSAJE = "mensaje del servicio"
NACIONAL_CAIDO = "El Sistema Nacional no responde; probá de nuevo en un momento."
FUTURO = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
EMERGENCIA = {"tipo": "inundacion", "nivel_gravedad": "ALTO", "zona_afectada": "Centro", "descripcion": "d"}


@pytest.fixture
def emergencia(seeded):
    return crear_emergencia(seeded, EstadoEmergencia.CONVOCATORIA, lotes=(), ofertas=(), bonita_case_id=4242,
                            ventana_ofertas_fin=datetime.now(timezone.utc) + timedelta(days=1))[0]


# (servicio en routers/api.py, usuario, método, ruta, cuerpo, error que lanza, código y mensaje esperados)
CASOS = [
    ("registrar_emergencia", "operador.municipal", "post", "/api/emergencias", EMERGENCIA,
     AltaEmergenciaError(MENSAJE), 502, MENSAJE),
    ("decidir", "coordinador.regional", "post", "/api/emergencias/{id}/decision", {"decision": "PARCIAL"},
     CicloError(MENSAJE, 409), 409, MENSAJE),
    ("decidir", "coordinador.regional", "post", "/api/emergencias/{id}/decision", {"decision": "PARCIAL"},
     NacionalError("caído"), 503, NACIONAL_CAIDO),
    ("adjudicar", "operador.municipal", "post", "/api/emergencias/{id}/adjudicar", {"cuits": ["30-54666544-5"]},
     CicloError(MENSAJE, 400), 400, MENSAJE),
    ("monitorear", "coordinador.regional", "post", "/api/emergencias/{id}/monitorear", None,
     CicloError(MENSAJE, 409), 409, MENSAJE),
    ("finalizar", "ong.cruzroja", "post", "/api/emergencias/{id}/finalizar", None,
     CicloError(MENSAJE, 403), 403, MENSAJE),
    ("validar_cierre", "coordinador.regional", "post", "/api/emergencias/{id}/validar-cierre", None,
     CicloError(MENSAJE, 502), 502, MENSAJE),
    ("alta_ong", None, "post", "/api/ongs/alta", _alta_ong(),
     AltaOngError(MENSAJE, 409), 409, MENSAJE),
    ("agregar_lote", "coordinador.regional", "post", "/api/emergencias/{id}/lotes",
     {"tipo_recurso": "PARAMEDICO", "cantidad": 3}, LoteError(MENSAJE), 400, MENSAJE),
    ("agregar_lote", "coordinador.regional", "post", "/api/emergencias/{id}/lotes",
     {"tipo_recurso": "PARAMEDICO", "cantidad": 3}, NacionalError("caído"), 503, NACIONAL_CAIDO),
    ("borrar_lote", "coordinador.regional", "delete", "/api/emergencias/{id}/lotes/1", None,
     LoteError(MENSAJE), 400, MENSAJE),
    ("publicar_convocatoria", "coordinador.regional", "post", "/api/emergencias/{id}/publicar",
     {"ventana_fin": FUTURO}, PublicacionError(MENSAJE), 400, MENSAJE),
    ("publicar_oferta", "ong.cruzroja", "post", "/api/emergencias/{id}/ofertas",
     {"items": [{"lote_id": 1, "recurso": "Paramédico", "cantidad": 1}]}, OfertaError(MENSAJE), 400, MENSAJE),
    ("publicar_oferta", "ong.cruzroja", "post", "/api/emergencias/{id}/ofertas",
     {"items": [{"lote_id": 1, "recurso": "Paramédico", "cantidad": 1}]}, NacionalError("caído"), 503, NACIONAL_CAIDO),
]


@pytest.mark.parametrize("servicio, usuario, metodo, ruta, cuerpo, error, codigo, mensaje", CASOS,
                         ids=[f"{c[0]}-{type(c[5]).__name__}" for c in CASOS])
def test_cada_error_de_servicio_llega_con_su_codigo_y_mensaje(
    monkeypatch, client, login, emergencia, servicio, usuario, metodo, ruta, cuerpo, error, codigo, mensaje,
):
    def falla(*args, **kwargs):
        raise error

    monkeypatch.setattr(api, servicio, falla)
    c = login(usuario) if usuario else client
    kwargs = {"json": cuerpo} if cuerpo is not None else {}
    r = getattr(c, metodo)(ruta.format(id=emergencia), **kwargs)

    assert r.status_code == codigo
    assert r.json() == {"detail": mensaje}


@pytest.mark.parametrize("ruta", ["/api/tipos-recurso", "/api/ongs/alta/tipos-recurso"])
def test_catalogo_con_el_sistema_nacional_caido(login, nacional, ruta):
    nacional.caido = True
    r = login("coordinador.regional").get(ruta)
    assert r.status_code == 503
    assert r.json() == {"detail": NACIONAL_CAIDO}
