"""Después de la evaluación: el Coordinador decide, el Municipio adjudica y Bonita avisa lo que hizo con las reservas.
Bonita va mockeado (`responses`); la secuencia real se prueba con scripts/escenario_adjudicacion.py."""
import json
from urllib.parse import urlparse

import pytest
import responses
from sqlalchemy import select

from app.models import (
    Consorcio, ConsorcioMiembro, Emergencia, EstadoEmergencia, EstadoMiembro, EstadoOferta, Notificacion, Oferta,
    OfertaItem, Ong,
)
from tests.conftest import (
    BOMBEROS, CASE, CLAVE, CRUZ_ROJA, cambiar_emergencia, crear_emergencia, estado_de, mock_tarea, tarea_completada,
)

TAREA_EVALUAR = "Evaluar Cobertura y Definir Curso de Accion"
TAREA_ADJUDICAR = "Adjudicar Ofertas"


def _evaluacion(emergencia_id, lote_id, completa=False, ronda=1):
    def ong(cuit, nombre, cantidad, estado="RESERVADA"):
        return {"cuit": cuit, "ong": nombre, "referencia": f"emg-{emergencia_id}-r{ronda}-{cuit}" if estado != "NO_RESERVADA" else None,
                "estado": estado,
                "items": [{"lote_id": lote_id, "tipo_recurso": "PARAMEDICO", "ofrecido": cantidad,
                           "reservado": cantidad if estado != "NO_RESERVADA" else 0, "nivel": "PARCIAL",
                           "riesgo_permitido": "MEDIO", "asignacion_sugerida": "APOYO", "observaciones": []}]}
    reservado = 10 if completa else 6
    return {"emergencia_id": emergencia_id, "ronda": ronda, "cobertura_completa": completa,
            "porcentaje_cobertura": 100.0 if completa else 60.0,
            "lotes": [{"lote_id": lote_id, "tipo_recurso": "PARAMEDICO", "pedido": 10, "reservado": reservado,
                       "porcentaje": 100.0 if completa else 60.0, "cubierto": completa}],
            "ongs": [ong(CRUZ_ROJA, "Cruz Roja Argentina", 4), ong(BOMBEROS, "Bomberos Voluntarios", 2)]}


@pytest.fixture
def evaluada(seeded):
    """Emergencia EN_EVALUACION con cobertura 60 %, un lote de 10 paramédicos y las ofertas de las dos ONGs."""
    emergencia_id, (lote_id,) = crear_emergencia(seeded, EstadoEmergencia.EN_EVALUACION)
    cambiar_emergencia(seeded, emergencia_id, evaluacion=json.dumps(_evaluacion(emergencia_id, lote_id)))
    return emergencia_id, lote_id


def _variable_seteada(nombre):
    for c in responses.calls:
        if urlparse(c.request.url).path.endswith(f"/caseVariable/{CASE}/{nombre}"):
            return json.loads(c.request.body)["value"]
    return None


# --- decisión del Coordinador ---

@responses.activate
def test_parcial_sigue_con_lo_reservado(login, seeded, nacional, evaluada):
    emergencia_id, _ = evaluada
    mock_tarea(TAREA_EVALUAR)

    r = login("coordinador.regional").post(f"/api/emergencias/{emergencia_id}/decision", json={"decision": "PARCIAL"})

    assert r.status_code == 200 and r.json()["estado"] == "ADJUDICACION"
    assert _variable_seteada("decisionCoordinador") == "PARCIAL" and tarea_completada()
    assert nacional.liberadas == []  # PARCIAL no libera nada
    assert r.json()["evaluacion"]["porcentaje_cobertura"] == 60.0


@responses.activate
def test_reformular_libera_las_reservas_retira_las_ofertas_y_empieza_otra_ronda(login, seeded, nacional, evaluada):
    emergencia_id, lote = evaluada
    mock_tarea(TAREA_EVALUAR)

    r = login("coordinador.regional").post(f"/api/emergencias/{emergencia_id}/decision", json={"decision": "REFORMULAR"})

    assert r.status_code == 200
    assert r.json()["estado"] == "REGISTRADA" and r.json()["evaluacion"] is None
    assert r.json()["ventana_ofertas_fin"] is None
    assert sorted(nacional.liberadas) == [f"emg-{emergencia_id}-r1-{CRUZ_ROJA}", f"emg-{emergencia_id}-r1-{BOMBEROS}"]
    assert _variable_seteada("decisionCoordinador") == "REFORMULAR" and tarea_completada()
    with seeded() as s:
        assert s.get(Emergencia, emergencia_id).ronda == 2
        ofertas = s.scalars(select(Oferta).where(Oferta.emergencia_id == emergencia_id)).all()
        assert all(o.version_actual == 2 for o in ofertas)  # versión nueva sin ítems: el historial queda
        assert s.query(OfertaItem).filter(OfertaItem.version == 2).count() == 0
        assert s.query(OfertaItem).filter(OfertaItem.version == 1).count() == 2


@responses.activate
def test_un_lote_con_ofertas_en_el_historial_no_se_puede_borrar(login, seeded, nacional, evaluada):
    emergencia_id, lote = evaluada
    mock_tarea(TAREA_EVALUAR)
    c = login("coordinador.regional")
    c.post(f"/api/emergencias/{emergencia_id}/decision", json={"decision": "REFORMULAR"})

    r = c.delete(f"/api/emergencias/{emergencia_id}/lotes/{lote}")

    assert r.status_code == 400 and "historial" in r.json()["detail"]


def test_la_decision_es_solo_del_coordinador(login, evaluada):
    emergencia_id, _ = evaluada
    for usuario in ("operador.municipal", "ong.cruzroja", "auditor"):
        r = login(usuario).post(f"/api/emergencias/{emergencia_id}/decision", json={"decision": "PARCIAL"})
        assert r.status_code == 403, usuario


def test_no_se_decide_fuera_de_la_evaluacion_ni_con_la_cobertura_completa(login, seeded, evaluada):
    emergencia_id, lote = evaluada
    c = login("coordinador.regional")
    assert c.post(f"/api/emergencias/{emergencia_id}/decision", json={"decision": "OTRA"}).status_code == 422

    cambiar_emergencia(seeded, emergencia_id, estado=EstadoEmergencia.CONVOCATORIA)
    assert c.post(f"/api/emergencias/{emergencia_id}/decision", json={"decision": "PARCIAL"}).status_code == 409

    cambiar_emergencia(seeded, emergencia_id, estado=EstadoEmergencia.EN_EVALUACION,
                evaluacion=json.dumps(_evaluacion(emergencia_id, lote, completa=True)))
    r = c.post(f"/api/emergencias/{emergencia_id}/decision", json={"decision": "REFORMULAR"})
    assert r.status_code == 409 and "cobertura está completa" in r.json()["detail"]


@responses.activate
def test_si_la_api_nacional_no_responde_al_reformular_no_cambia_nada(login, seeded, nacional, evaluada):
    emergencia_id, _ = evaluada
    nacional.caido = True

    r = login("coordinador.regional").post(f"/api/emergencias/{emergencia_id}/decision", json={"decision": "REFORMULAR"})

    assert r.status_code == 503
    assert estado_de(seeded, emergencia_id) is EstadoEmergencia.EN_EVALUACION
    assert len(responses.calls) == 0  # ni siquiera se tocó Bonita


@responses.activate
def test_si_bonita_no_tiene_la_tarea_pendiente_no_cambia_nada(login, seeded, nacional, evaluada):
    emergencia_id, _ = evaluada
    mock_tarea("Otra tarea")

    r = login("coordinador.regional").post(f"/api/emergencias/{emergencia_id}/decision", json={"decision": "PARCIAL"})

    assert r.status_code == 409
    assert estado_de(seeded, emergencia_id) is EstadoEmergencia.EN_EVALUACION


# --- adjudicación del Municipio ---

@pytest.fixture
def en_adjudicacion(seeded, evaluada):
    cambiar_emergencia(seeded, evaluada[0], estado=EstadoEmergencia.ADJUDICACION)
    return evaluada


@responses.activate
def test_el_municipio_adjudica_y_bonita_recibe_las_ongs_elegidas(login, seeded, en_adjudicacion):
    emergencia_id, _ = en_adjudicacion
    mock_tarea(TAREA_ADJUDICAR)

    r = login("operador.municipal").post(f"/api/emergencias/{emergencia_id}/adjudicar", json={"cuits": [CRUZ_ROJA]})

    assert r.status_code == 200
    assert json.loads(_variable_seteada("ongsAdjudicadas")) == [CRUZ_ROJA] and tarea_completada()
    # la app sigue en ADJUDICACION: pasa a EN_EJECUCION cuando Bonita avisa que confirmó las reservas
    assert estado_de(seeded, emergencia_id) is EstadoEmergencia.ADJUDICACION


def test_la_adjudicacion_valida_lo_que_se_elige(login, seeded, en_adjudicacion):
    emergencia_id, lote = en_adjudicacion
    c = login("operador.municipal")
    url = f"/api/emergencias/{emergencia_id}/adjudicar"
    assert c.post(url, json={"cuits": []}).status_code == 422
    assert c.post(url, json={"cuits": [CRUZ_ROJA, CRUZ_ROJA]}).status_code == 400
    r = c.post(url, json={"cuits": ["30-99999999-9"]})
    assert r.status_code == 400 and "no tiene una oferta validada" in r.json()["detail"]

    evaluacion = _evaluacion(emergencia_id, lote)
    evaluacion["ongs"][1]["estado"] = "NO_RESERVADA"  # Bomberos no pudo reservar: no se puede elegir
    cambiar_emergencia(seeded, emergencia_id, estado=EstadoEmergencia.ADJUDICACION, evaluacion=json.dumps(evaluacion))
    assert c.post(url, json={"cuits": [BOMBEROS]}).status_code == 400


def _consorcio(seeded, emergencia_id, nombre="Red Litoral"):
    with seeded() as s:
        cruz, bomberos = (s.query(Ong).filter_by(cuit=c).one() for c in (CRUZ_ROJA, BOMBEROS))
        c = Consorcio(emergencia_id=emergencia_id, nombre=nombre, ong_lider_id=cruz.id)
        c.miembros = [ConsorcioMiembro(ong_id=o.id, estado=EstadoMiembro.ACEPTADA, invitado_por_ong_id=cruz.id)
                      for o in (cruz, bomberos)]
        s.add(c)
        s.commit()


def test_adjudicar_parte_de_un_consorcio_da_409(login, seeded, en_adjudicacion):
    emergencia_id, _ = en_adjudicacion
    _consorcio(seeded, emergencia_id)

    r = login("operador.municipal").post(f"/api/emergencias/{emergencia_id}/adjudicar", json={"cuits": [CRUZ_ROJA]})

    assert r.status_code == 409
    assert r.json()["detail"] == "El consorcio «Red Litoral» se adjudica entero: falta Bomberos Voluntarios."


@responses.activate
def test_adjudicar_consorcio_con_miembro_sin_reserva(login, seeded, en_adjudicacion):
    emergencia_id, lote = en_adjudicacion
    _consorcio(seeded, emergencia_id)
    evaluacion = _evaluacion(emergencia_id, lote)
    evaluacion["ongs"][1]["estado"] = "NO_RESERVADA"
    cambiar_emergencia(seeded, emergencia_id, estado=EstadoEmergencia.ADJUDICACION, evaluacion=json.dumps(evaluacion))
    mock_tarea(TAREA_ADJUDICAR)

    r = login("operador.municipal").post(f"/api/emergencias/{emergencia_id}/adjudicar", json={"cuits": [CRUZ_ROJA]})

    assert r.status_code == 200
    assert json.loads(_variable_seteada("ongsAdjudicadas")) == [CRUZ_ROJA]


@responses.activate
def test_adjudicar_consorcio_entero_pasa(login, seeded, en_adjudicacion):
    emergencia_id, _ = en_adjudicacion
    _consorcio(seeded, emergencia_id)
    mock_tarea(TAREA_ADJUDICAR)

    r = login("operador.municipal").post(f"/api/emergencias/{emergencia_id}/adjudicar",
                                         json={"cuits": [CRUZ_ROJA, BOMBEROS]})

    assert r.status_code == 200 and json.loads(_variable_seteada("ongsAdjudicadas")) == [CRUZ_ROJA, BOMBEROS]


@responses.activate
def test_adjudicar_sin_consorcios_igual_que_antes(login, seeded, en_adjudicacion):
    emergencia_id, _ = en_adjudicacion
    mock_tarea(TAREA_ADJUDICAR)

    r = login("operador.municipal").post(f"/api/emergencias/{emergencia_id}/adjudicar", json={"cuits": [BOMBEROS]})

    assert r.status_code == 200 and json.loads(_variable_seteada("ongsAdjudicadas")) == [BOMBEROS]


def test_solo_el_municipio_adjudica_y_solo_en_su_momento(login, seeded, en_adjudicacion):
    emergencia_id, _ = en_adjudicacion
    for usuario in ("coordinador.regional", "ong.cruzroja", "auditor"):
        r = login(usuario).post(f"/api/emergencias/{emergencia_id}/adjudicar", json={"cuits": [CRUZ_ROJA]})
        assert r.status_code == 403, usuario
    cambiar_emergencia(seeded, emergencia_id, estado=EstadoEmergencia.EN_EVALUACION)
    r = login("operador.municipal").post(f"/api/emergencias/{emergencia_id}/adjudicar", json={"cuits": [CRUZ_ROJA]})
    assert r.status_code == 409


# --- eventos de Bonita ---

def _evento_adjudicacion(client, emergencia_id, adjudicadas, no_adjudicadas, clave=CLAVE):
    return client.post(f"/api/bonita/emergencias/{emergencia_id}/eventos", headers=clave,
                       json={"tipo": "ADJUDICACION", "adjudicadas": adjudicadas, "no_adjudicadas": no_adjudicadas})


def test_el_evento_de_adjudicacion_marca_las_ofertas_avisa_a_las_ongs_y_pasa_a_ejecucion(client, seeded, en_adjudicacion):
    emergencia_id, _ = en_adjudicacion

    assert _evento_adjudicacion(client, emergencia_id, [CRUZ_ROJA], [BOMBEROS]).status_code == 204

    with seeded() as s:
        assert s.get(Emergencia, emergencia_id).estado is EstadoEmergencia.EN_EJECUCION
        estados = {o.ong.cuit: o.estado for o in s.scalars(select(Oferta).where(Oferta.emergencia_id == emergencia_id))}
        assert estados == {CRUZ_ROJA: EstadoOferta.ADJUDICADA, BOMBEROS: EstadoOferta.NO_ADJUDICADA}
        avisos = s.scalars(select(Notificacion)).all()
        assert len(avisos) == 2
        por_ong = {n.ong_id: n.texto for n in avisos}
        cruz = s.query(Ong).filter_by(cuit=CRUZ_ROJA).one().id
        bomberos = s.query(Ong).filter_by(cuit=BOMBEROS).one().id
        assert por_ong[cruz] == f"Tu oferta para la emergencia #{emergencia_id} fue seleccionada."
        assert por_ong[bomberos] == f"Tu oferta para la emergencia #{emergencia_id} no fue seleccionada."


def test_registrar_adjudicacion_guarda_fecha(client, seeded, en_adjudicacion):
    emergencia_id, _ = en_adjudicacion

    _evento_adjudicacion(client, emergencia_id, [CRUZ_ROJA], [BOMBEROS])

    with seeded() as s:
        fechas = {o.ong.cuit: o.adjudicada_en for o in s.scalars(select(Oferta).where(Oferta.emergencia_id == emergencia_id))}
        assert fechas[CRUZ_ROJA] is not None
        assert fechas[BOMBEROS] is None


def test_repetir_el_evento_de_adjudicacion_no_duplica_los_avisos(client, seeded, en_adjudicacion):
    emergencia_id, _ = en_adjudicacion
    _evento_adjudicacion(client, emergencia_id, [CRUZ_ROJA], [BOMBEROS])

    assert _evento_adjudicacion(client, emergencia_id, [CRUZ_ROJA], [BOMBEROS]).status_code == 204

    with seeded() as s:
        assert s.query(Notificacion).count() == 2


def test_el_evento_de_adjudicacion_exige_la_clave_el_estado_y_datos_coherentes(client, seeded, evaluada):
    emergencia_id, _ = evaluada  # sigue EN_EVALUACION
    assert _evento_adjudicacion(client, emergencia_id, [CRUZ_ROJA], [], clave={}).status_code == 401
    assert _evento_adjudicacion(client, emergencia_id, [CRUZ_ROJA], [BOMBEROS]).status_code == 409
    assert _evento_adjudicacion(client, 9999, [CRUZ_ROJA], []).status_code == 404
    cambiar_emergencia(seeded, emergencia_id, estado=EstadoEmergencia.ADJUDICACION)
    assert _evento_adjudicacion(client, emergencia_id, [CRUZ_ROJA], [CRUZ_ROJA]).status_code == 409


def test_con_la_cobertura_completa_el_evento_de_evaluacion_pasa_directo_a_adjudicacion(client, seeded, evaluada):
    emergencia_id, lote = evaluada
    completa = _evaluacion(emergencia_id, lote, completa=True)
    url = f"/api/bonita/emergencias/{emergencia_id}/eventos"

    assert client.post(url, headers=CLAVE, json={"tipo": "EVALUACION", "resultado": completa}).status_code == 204
    assert estado_de(seeded, emergencia_id) is EstadoEmergencia.ADJUDICACION
    # un reintento de Bonita con el mismo resultado no falla
    assert client.post(url, headers=CLAVE, json={"tipo": "EVALUACION", "resultado": completa}).status_code == 204
    # pero otro resultado distinto, ya en adjudicación, sí
    otra = _evaluacion(emergencia_id, lote, completa=True)
    otra["porcentaje_cobertura"] = 90.0
    assert client.post(url, headers=CLAVE, json={"tipo": "EVALUACION", "resultado": otra}).status_code == 409
