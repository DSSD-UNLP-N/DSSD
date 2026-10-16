"""Prueba de locking contra una instancia PostgreSQL real.

SQLite no implementa el mismo comportamiento de SELECT ... FOR UPDATE, por eso el
test se omite salvo que se configure POSTGRES_TEST_DATABASE_URL.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.db import Base
from app.models import Adjudicacion, Inventario, Ong
from app.routers.adjudicacion import adjudicar
from app.schemas import AdjudicacionIn, AdjudicacionItemIn
from app.seed import seed


@pytest.mark.integration
def test_dos_adjudicaciones_concurrentes_solo_una_compromete():
    url = os.environ.get("POSTGRES_TEST_DATABASE_URL")
    if not url or not url.startswith(("postgres://", "postgresql://")):
        pytest.skip("requiere POSTGRES_TEST_DATABASE_URL con PostgreSQL")

    engine = create_engine(url, poolclass=NullPool, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    seed(factory)

    with factory() as db:
        ong_id = db.scalar(select(Ong.id).where(Ong.cuit == "30-54666544-5"))
        inventario_id = db.scalar(
            select(Inventario.id).where(Inventario.ong_id == ong_id).order_by(Inventario.id)
        )
        fila = db.get(Inventario, inventario_id)
        fila.cantidad_comprometida = 0
        db.commit()

    barrera = Barrier(2)

    def enviar() -> int:
        referencia = f"concurrencia-{uuid4()}"
        body = AdjudicacionIn(
            referencia_id=referencia,
            ong_id=ong_id,
            emergencia_id=999,
            items=[AdjudicacionItemIn(inventario_id=inventario_id, cantidad=4)],
        )
        with factory() as db:
            barrera.wait()
            try:
                adjudicar(body, Response(), db)
                return 201
            except HTTPException as exc:
                return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: enviar(), range(2)))

        assert sorted(statuses) == [201, 409]
        with factory() as db:
            fila = db.get(Inventario, inventario_id)
            assert fila.cantidad_comprometida == 4
            assert db.scalar(select(Adjudicacion.id)) is not None
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
