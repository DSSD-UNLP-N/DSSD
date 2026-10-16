"""Reservas concurrentes contra una instancia PostgreSQL real (SQLite no implementa SELECT ... FOR UPDATE).

Se omite salvo que se configure POSTGRES_TEST_DATABASE_URL (misma convención que test_concurrencia_adjudicacion.py).
"""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.db import Base
from app.models import Adjudicacion, Inventario, Ong, TipoRecurso
from app.routers.reservas import evaluar_ofertas
from app.schemas import EvaluacionIn
from app.seed import seed

CRUZ_ROJA = "30-54666544-5"  # 4 paramédicos


@pytest.fixture
def postgres():
    url = os.environ.get("POSTGRES_TEST_DATABASE_URL")
    if not url or not url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        pytest.skip("requiere POSTGRES_TEST_DATABASE_URL con PostgreSQL")
    engine = create_engine(url, poolclass=NullPool, pool_pre_ping=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    seed(factory)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def _pedido(emergencia_id: int, cantidad: int) -> EvaluacionIn:
    return EvaluacionIn(
        emergencia_id=emergencia_id, gravedad="ALTO",
        lotes=[{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": 10}],
        ofertas=[{"cuit": CRUZ_ROJA, "items": [{"lote_id": 1, "tipo_recurso": "PARAMEDICO", "cantidad": cantidad}]}],
    )


def _en_paralelo(factory, pedidos: list[EvaluacionIn]):
    barrera = Barrier(len(pedidos))

    def enviar(pedido):
        with factory() as db:
            barrera.wait()
            return evaluar_ofertas(pedido, db)

    with ThreadPoolExecutor(max_workers=len(pedidos)) as pool:
        return list(pool.map(enviar, pedidos))


def _comprometido(factory) -> int:
    with factory() as db:
        return db.scalar(
            select(Inventario.cantidad_comprometida)
            .join(Ong).join(TipoRecurso).where(Ong.cuit == CRUZ_ROJA, TipoRecurso.codigo == "PARAMEDICO")
        )


@pytest.mark.integration
def test_dos_emergencias_que_piden_el_mismo_stock_no_lo_pasan(postgres):
    """Cruz Roja tiene 4 paramédicos y ofrece 3 a cada una: una reserva 3 y la otra se recorta a 1."""
    respuestas = _en_paralelo(postgres, [_pedido(101, 3), _pedido(102, 3)])

    reservado = sorted(r.ongs[0].items[0].reservado for r in respuestas)
    assert reservado == [1, 3]
    assert _comprometido(postgres) == 4


@pytest.mark.integration
def test_el_mismo_pedido_repetido_a_la_vez_reserva_una_sola_vez(postgres):
    """Un reintento de Bonita que llega mientras el primero sigue en curso no duplica la reserva."""
    respuestas = _en_paralelo(postgres, [_pedido(101, 3), _pedido(101, 3)])

    assert respuestas[0] == respuestas[1]
    assert _comprometido(postgres) == 3
    with postgres() as db:
        assert len(db.scalars(select(Adjudicacion)).all()) == 1
