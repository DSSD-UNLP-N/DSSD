"""Reglas de formación de consorcios (servicio, sin HTTP)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import (
    Consorcio, ConsorcioMiembro, Emergencia, EstadoEmergencia, EstadoMiembro, Municipio, Notificacion, Ong,
)
from app.services import consorcios
from app.services.consorcios import ConsorcioError


def _ahora():
    return datetime.now(timezone.utc)


@pytest.fixture
def mundo(seeded):
    """Sesión, emergencia con la ventana abierta y tres ONGs (dos del seed y una creada acá)."""
    with seeded() as s:
        municipio = s.query(Municipio).one()
        e = Emergencia(municipio_id=municipio.id, tipo="inundacion", nivel_gravedad="ALTO", zona_afectada="Centro",
                       descripcion="d", estado=EstadoEmergencia.CONVOCATORIA,
                       ventana_ofertas_fin=_ahora() + timedelta(hours=2))
        s.add(e)
        tercera = Ong(nombre="Cáritas", cuit="30-11111111-1")
        s.add(tercera)
        s.commit()
        ongs = s.scalars(select(Ong).order_by(Ong.id)).all()
        cruz, bomberos = [o for o in ongs if o.nombre != "Cáritas"][:2]
        yield s, e, cruz, bomberos, tercera


def _cerrar(s, e):
    e.ventana_ofertas_fin = _ahora() - timedelta(minutes=1)
    s.commit()


def test_crear_deja_a_la_ong_como_lider_aceptada(mundo):
    s, e, cruz, _, _ = mundo
    c = consorcios.crear(s, emergencia=e, ong=cruz, nombre="  Red Litoral  ")
    assert c.nombre == "Red Litoral" and c.ong_lider_id == cruz.id
    [m] = c.miembros
    assert m.ong_id == cruz.id and m.estado is EstadoMiembro.ACEPTADA
    assert m.invitado_por_ong_id == cruz.id and m.respondido_en is not None


def test_nombre_invalido_da_422(mundo):
    s, e, cruz, _, _ = mundo
    for nombre in ("", " a ", "x" * 81):
        with pytest.raises(ConsorcioError) as exc:
            consorcios.crear(s, emergencia=e, ong=cruz, nombre=nombre)
        assert exc.value.status == 422


def test_nombre_repetido_en_la_emergencia_da_409(mundo):
    s, e, cruz, bomberos, _ = mundo
    consorcios.crear(s, emergencia=e, ong=cruz, nombre="Red")
    with pytest.raises(ConsorcioError) as exc:
        consorcios.crear(s, emergencia=e, ong=bomberos, nombre="Red")
    assert exc.value.status == 409


def test_nombre_de_consorcio_disuelto_tampoco_se_reusa(mundo):
    s, e, cruz, bomberos, _ = mundo
    c = consorcios.crear(s, emergencia=e, ong=cruz, nombre="Red")
    consorcios.disolver(s, consorcio=c, lider=cruz)
    # La restricción única de la tabla lo impide: el servicio lo informa como 409, no como 500.
    with pytest.raises(ConsorcioError) as exc:
        consorcios.crear(s, emergencia=e, ong=bomberos, nombre="Red")
    assert exc.value.status == 409


def test_no_se_crea_con_la_ventana_cerrada(mundo):
    s, e, cruz, _, _ = mundo
    _cerrar(s, e)
    with pytest.raises(ConsorcioError) as exc:
        consorcios.crear(s, emergencia=e, ong=cruz, nombre="Red")
    assert exc.value.status == 409


def test_una_ong_no_crea_si_ya_esta_en_otro_consorcio(mundo):
    s, e, cruz, bomberos, _ = mundo
    consorcios.crear(s, emergencia=e, ong=cruz, nombre="Uno")
    with pytest.raises(ConsorcioError) as exc:
        consorcios.crear(s, emergencia=e, ong=cruz, nombre="Dos")
    assert exc.value.status == 409


def test_solo_la_lider_invita(mundo):
    s, e, cruz, bomberos, tercera = mundo
    c = consorcios.crear(s, emergencia=e, ong=cruz, nombre="Red")
    with pytest.raises(ConsorcioError) as exc:
        consorcios.invitar(s, consorcio=c, lider=bomberos, invitada=tercera)
    assert exc.value.status == 403


def test_no_se_invita_a_ong_ya_en_otro_consorcio(mundo):
    s, e, cruz, bomberos, tercera = mundo
    c1 = consorcios.crear(s, emergencia=e, ong=cruz, nombre="Uno")
    consorcios.crear(s, emergencia=e, ong=bomberos, nombre="Dos")
    with pytest.raises(ConsorcioError) as exc:
        consorcios.invitar(s, consorcio=c1, lider=cruz, invitada=bomberos)
    assert exc.value.status == 409


def test_no_se_invita_dos_veces_a_la_misma_ong(mundo):
    s, e, cruz, bomberos, _ = mundo
    c = consorcios.crear(s, emergencia=e, ong=cruz, nombre="Red")
    consorcios.invitar(s, consorcio=c, lider=cruz, invitada=bomberos)
    with pytest.raises(ConsorcioError) as exc:
        consorcios.invitar(s, consorcio=c, lider=cruz, invitada=bomberos)
    assert exc.value.status == 409


def test_no_se_invita_a_si_misma(mundo):
    s, e, cruz, _, _ = mundo
    c = consorcios.crear(s, emergencia=e, ong=cruz, nombre="Red")
    with pytest.raises(ConsorcioError) as exc:
        consorcios.invitar(s, consorcio=c, lider=cruz, invitada=cruz)
    assert exc.value.status == 409


def test_invitar_notifica_a_la_invitada(mundo):
    s, e, cruz, bomberos, _ = mundo
    c = consorcios.crear(s, emergencia=e, ong=cruz, nombre="Red Litoral")
    m = consorcios.invitar(s, consorcio=c, lider=cruz, invitada=bomberos)
    assert m.estado is EstadoMiembro.INVITADA and m.invitado_por_ong_id == cruz.id
    [n] = s.scalars(select(Notificacion).where(Notificacion.ong_id == bomberos.id)).all()
    assert "Red Litoral" in n.texto and n.emergencia_id == e.id and len(n.texto) < 300


def test_aceptar_y_rechazar(mundo):
    s, e, cruz, bomberos, tercera = mundo
    c = consorcios.crear(s, emergencia=e, ong=cruz, nombre="Red")
    consorcios.invitar(s, consorcio=c, lider=cruz, invitada=bomberos)
    consorcios.invitar(s, consorcio=c, lider=cruz, invitada=tercera)
    m1 = consorcios.responder(s, consorcio=c, ong=bomberos, acepta=True)
    m2 = consorcios.responder(s, consorcio=c, ong=tercera, acepta=False)
    assert m1.estado is EstadoMiembro.ACEPTADA and m1.respondido_en is not None
    assert m2.estado is EstadoMiembro.RECHAZADA and m2.respondido_en is not None
    assert {m.ong_id for m in consorcios.miembros_aceptados(c)} == {cruz.id, bomberos.id}
    assert consorcios.es_valido(c)
    # Sin invitación pendiente no hay nada que responder.
    with pytest.raises(ConsorcioError) as exc:
        consorcios.responder(s, consorcio=c, ong=tercera, acepta=True)
    assert exc.value.status == 403


def test_una_rechazada_puede_ser_invitada_de_nuevo_con_fila_nueva(mundo):
    s, e, cruz, bomberos, _ = mundo
    c = consorcios.crear(s, emergencia=e, ong=cruz, nombre="Red")
    consorcios.invitar(s, consorcio=c, lider=cruz, invitada=bomberos)
    consorcios.responder(s, consorcio=c, ong=bomberos, acepta=False)
    consorcios.invitar(s, consorcio=c, lider=cruz, invitada=bomberos)
    filas = s.scalars(select(ConsorcioMiembro).where(ConsorcioMiembro.ong_id == bomberos.id)).all()
    assert sorted(f.estado.value for f in filas) == ["INVITADA", "RECHAZADA"]


def test_invitacion_pendiente_vence_con_la_ventana(mundo):
    s, e, cruz, bomberos, tercera = mundo
    c = consorcios.crear(s, emergencia=e, ong=cruz, nombre="Red")
    consorcios.invitar(s, consorcio=c, lider=cruz, invitada=bomberos)
    _cerrar(s, e)
    with pytest.raises(ConsorcioError) as exc:
        consorcios.responder(s, consorcio=c, ong=bomberos, acepta=True)
    assert exc.value.status == 409
    assert bomberos.id not in {m.ong_id for m in consorcios.miembros_aceptados(c)}
    # La vencida ya no cuenta como "en un consorcio".
    assert consorcios.consorcio_de(s, e.id, bomberos.id) is None
    assert consorcios.consorcio_de(s, e.id, cruz.id) is c


def test_la_lider_no_puede_salir(mundo):
    s, e, cruz, _, _ = mundo
    c = consorcios.crear(s, emergencia=e, ong=cruz, nombre="Red")
    with pytest.raises(ConsorcioError) as exc:
        consorcios.salir(s, consorcio=c, ong=cruz)
    assert exc.value.status == 409 and "disolv" in str(exc.value)


def test_salir_marca_salio_y_fecha(mundo):
    s, e, cruz, bomberos, _ = mundo
    c = consorcios.crear(s, emergencia=e, ong=cruz, nombre="Red")
    consorcios.invitar(s, consorcio=c, lider=cruz, invitada=bomberos)
    consorcios.responder(s, consorcio=c, ong=bomberos, acepta=True)
    consorcios.salir(s, consorcio=c, ong=bomberos)
    m = next(m for m in c.miembros if m.ong_id == bomberos.id)
    assert m.estado is EstadoMiembro.SALIO and m.salio_en is not None
    assert consorcios.consorcio_de(s, e.id, bomberos.id) is None


def test_salir_sin_ser_miembro_da_409(mundo):
    s, e, cruz, bomberos, _ = mundo
    c = consorcios.crear(s, emergencia=e, ong=cruz, nombre="Red")
    with pytest.raises(ConsorcioError) as exc:
        consorcios.salir(s, consorcio=c, ong=bomberos)
    assert exc.value.status == 409


def test_disolver_marca_disuelto_y_no_borra_filas(mundo):
    s, e, cruz, bomberos, _ = mundo
    c = consorcios.crear(s, emergencia=e, ong=cruz, nombre="Red")
    consorcios.invitar(s, consorcio=c, lider=cruz, invitada=bomberos)
    with pytest.raises(ConsorcioError) as exc:
        consorcios.disolver(s, consorcio=c, lider=bomberos)
    assert exc.value.status == 403
    consorcios.disolver(s, consorcio=c, lider=cruz)
    assert c.disuelto_en is not None
    assert s.query(ConsorcioMiembro).count() == 2 and s.query(Consorcio).count() == 1
    assert consorcios.consorcio_de(s, e.id, bomberos.id) is None
    assert not consorcios.es_valido(c)
    with pytest.raises(ConsorcioError) as exc:
        consorcios.invitar(s, consorcio=c, lider=cruz, invitada=bomberos)
    assert exc.value.status == 409


def test_un_solo_aceptado_no_es_valido(mundo):
    s, e, cruz, bomberos, _ = mundo
    c = consorcios.crear(s, emergencia=e, ong=cruz, nombre="Red")
    assert not consorcios.es_valido(c)
    assert consorcios.consorcios_validos(s, e.id) == []
    consorcios.invitar(s, consorcio=c, lider=cruz, invitada=bomberos)
    consorcios.responder(s, consorcio=c, ong=bomberos, acepta=True)
    assert consorcios.consorcios_validos(s, e.id) == [c]


def test_despues_de_reformular_se_puede_editar(mundo):
    s, e, cruz, bomberos, tercera = mundo
    c = consorcios.crear(s, emergencia=e, ong=cruz, nombre="Red")
    consorcios.invitar(s, consorcio=c, lider=cruz, invitada=bomberos)
    consorcios.responder(s, consorcio=c, ong=bomberos, acepta=True)
    # Ronda 1 cierra y el Coordinador reformula: ventana nueva, ronda 2.
    _cerrar(s, e)
    with pytest.raises(ConsorcioError):
        consorcios.invitar(s, consorcio=c, lider=cruz, invitada=tercera)
    e.estado, e.ronda, e.ventana_ofertas_fin = EstadoEmergencia.CONVOCATORIA, 2, _ahora() + timedelta(hours=1)
    s.commit()
    assert consorcios.consorcio_de(s, e.id, cruz.id) is c
    consorcios.invitar(s, consorcio=c, lider=cruz, invitada=tercera)
    assert consorcios.responder(s, consorcio=c, ong=tercera, acepta=True).estado is EstadoMiembro.ACEPTADA
