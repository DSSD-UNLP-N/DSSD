"""Protegen el esquema de datos: restricciones, defaults y trazabilidad de versiones."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.models import (
    Emergencia,
    EstadoEmergencia,
    Gravedad,
    Lote,
    Municipio,
    Oferta,
    OfertaItem,
    Ong,
    Rol,
    TipoLote,
    Usuario,
)


@pytest.fixture
def base(db):
    m = Municipio(nombre="Bahía Blanca", provincia="Buenos Aires")
    o = Ong(nombre="Cruz Roja", cuit="30-1-1")
    db.add_all([m, o])
    db.flush()
    e = Emergencia(
        municipio_id=m.id, tipo="inundacion", nivel_gravedad=Gravedad.ALTO,
        zona_afectada="Centro", descripcion="d",
    )
    e.lotes = [Lote(recurso="Paramédicos", cantidad=5, unidad="personas")]
    db.add(e)
    db.commit()
    return m, o, e


def test_emergencia_nace_registrada_y_sin_caso_bonita(base):
    _, _, e = base
    assert e.estado is EstadoEmergencia.REGISTRADA
    assert e.bonita_case_id is None
    assert e.ventana_ofertas_fin is None
    assert e.creada_en is not None


def test_bonita_case_id_es_unico(db, base):
    m, _, e = base
    e.bonita_case_id = 1001
    db.commit()
    otra = Emergencia(municipio_id=m.id, tipo="incendio", nivel_gravedad=Gravedad.BAJO,
                      zona_afectada="z", descripcion="d", bonita_case_id=1001)
    db.add(otra)
    with pytest.raises(IntegrityError):
        db.commit()


def test_nivel_gravedad_invalido_se_rechaza(db, base):
    m, _, _ = base
    db.add(Emergencia(municipio_id=m.id, tipo="x", nivel_gravedad="MUY_GRAVE",
                      zona_afectada="z", descripcion="d"))
    with pytest.raises(IntegrityError):  # CHECK de la columna
        db.commit()


def test_lote_es_principal_por_defecto(base):
    _, _, e = base
    assert e.lotes[0].tipo is TipoLote.PRINCIPAL


def test_tipo_de_lote_invalido_se_rechaza(db, base):
    _, _, e = base
    db.add(Lote(emergencia_id=e.id, recurso="Agua", cantidad=100, unidad="litros", tipo="TERCIARIO"))
    with pytest.raises(IntegrityError):  # CHECK de la columna
        db.commit()


def test_borrar_emergencia_borra_sus_lotes(db, base):
    _, _, e = base
    db.delete(e)
    db.commit()
    assert db.scalars(select(Lote)).all() == []


def test_una_oferta_por_ong_y_emergencia(db, base):
    _, o, e = base
    db.add(Oferta(emergencia_id=e.id, ong_id=o.id))
    db.commit()
    db.add(Oferta(emergencia_id=e.id, ong_id=o.id))
    with pytest.raises(IntegrityError):
        db.commit()


def test_editar_oferta_conserva_versiones_anteriores(db, base):
    """Trazabilidad (T-12): editar = agregar líneas con version+1, nunca pisar."""
    _, o, e = base
    lote = e.lotes[0]
    oferta = Oferta(emergencia_id=e.id, ong_id=o.id)
    oferta.items = [OfertaItem(version=1, lote_id=lote.id, recurso="Paramédicos", cantidad=3)]
    db.add(oferta)
    db.commit()

    oferta.version_actual = 2
    oferta.items.append(OfertaItem(version=2, lote_id=lote.id, recurso="Paramédicos", cantidad=5))
    db.commit()

    por_version = {i.version: i.cantidad for i in oferta.items}
    assert por_version == {1: 3, 2: 5}
    assert oferta.version_actual == 2


def test_username_es_unico(db):
    db.add(Usuario(username="a", password_hash=hash_password("x"), nombre="A", rol=Rol.AUDITOR))
    db.commit()
    db.add(Usuario(username="a", password_hash=hash_password("x"), nombre="B", rol=Rol.AUDITOR))
    with pytest.raises(IntegrityError):
        db.commit()


def test_claves_foraneas_estan_declaradas():
    from app.db import Base

    fks = {(t.name, fk.parent.name, fk.column.table.name)
           for t in Base.metadata.tables.values() for fk in t.foreign_keys}
    assert ("lote", "emergencia_id", "emergencia") in fks
    assert ("oferta_item", "lote_id", "lote") in fks
    assert ("oferta_item", "oferta_id", "oferta") in fks
    assert ("emergencia", "municipio_id", "municipio") in fks
