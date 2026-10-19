"""Restricciones del esquema: la BD rechaza lo que el modelo no permite."""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    CategoriaRecurso,
    Certificacion,
    Inventario,
    Ong,
    OngCertificacion,
    Riesgo,
    TipoRecurso,
)


@pytest.fixture
def base(db):
    ong = Ong(cuit="30-1-1", nombre="ONG")
    tipo = TipoRecurso(codigo="X", nombre="X", categoria=CategoriaRecurso.INSUMO, unidad="u")
    cert = Certificacion(codigo="C", nombre="C")
    db.add_all([ong, tipo, cert])
    db.commit()
    return ong, tipo, cert


def test_ong_nace_habilitada(db, base):
    assert base[0].estado.value == "HABILITADA"


def test_cuit_y_codigos_son_unicos(db, base):
    for obj in (
        Ong(cuit="30-1-1", nombre="otra"),
        Certificacion(codigo="C", nombre="otra"),
        TipoRecurso(codigo="X", nombre="otro", categoria=CategoriaRecurso.INSUMO, unidad="u"),
    ):
        db.add(obj)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_inventario_disponible_y_comprometida_por_defecto(db, base):
    ong, tipo, _ = base
    inv = Inventario(ong_id=ong.id, tipo_recurso_id=tipo.id, cantidad_total=10)
    db.add(inv)
    db.commit()
    assert inv.cantidad_comprometida == 0
    inv.cantidad_comprometida = 6
    assert inv.disponible == 4


@pytest.mark.parametrize("total, comprometida", [(5, 6), (5, -1), (-1, 0)])
def test_inventario_rechaza_cantidades_imposibles(db, base, total, comprometida):
    ong, tipo, _ = base
    db.add(Inventario(ong_id=ong.id, tipo_recurso_id=tipo.id, cantidad_total=total, cantidad_comprometida=comprometida))
    with pytest.raises(IntegrityError):
        db.commit()


def test_una_fila_de_inventario_por_ong_y_tipo(db, base):
    ong, tipo, _ = base
    db.add_all([Inventario(ong_id=ong.id, tipo_recurso_id=tipo.id, cantidad_total=1) for _ in range(2)])
    with pytest.raises(IntegrityError):
        db.commit()


def test_una_certificacion_por_ong(db, base):
    ong, _, cert = base
    db.add_all(
        [
            OngCertificacion(ong_id=ong.id, certificacion_id=cert.id, riesgo_max=Riesgo.ALTO, vence_el=date(2030, 1, 1))
            for _ in range(2)
        ]
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_riesgo_fuera_de_la_escala_se_rechaza(db, base):
    from sqlalchemy import text

    ong, _, cert = base
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO ong_certificacion (ong_id, certificacion_id, riesgo_max, vence_el)"
                f" VALUES ({ong.id}, {cert.id}, 'ENORME', '2030-01-01')"
            )
        )
