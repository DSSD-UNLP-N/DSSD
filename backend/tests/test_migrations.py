"""Garantizan que las migraciones de Alembic y los modelos no se desincronicen."""
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.db import Base

BACKEND = Path(__file__).resolve().parents[1]
TABLAS = {"municipio", "ong", "usuario", "emergencia", "lote", "oferta", "oferta_item"}


@pytest.fixture
def cfg(tmp_path):
    c = Config(str(BACKEND / "alembic.ini"))
    c.set_main_option("script_location", str(BACKEND / "migrations"))
    c.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'mig.db'}")
    return c


def test_upgrade_head_crea_todas_las_tablas(cfg):
    command.upgrade(cfg, "head")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
    assert TABLAS <= set(inspect(engine).get_table_names())


def test_migraciones_coinciden_con_los_modelos(cfg):
    """Si esto falla: cambiaste models/entities.py sin generar migración.
    Corré `alembic revision --autogenerate -m "..."`."""
    command.upgrade(cfg, "head")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"Modelos y migraciones difieren: {diff}"


def test_downgrade_a_base_deja_la_bd_vacia(cfg):
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
    assert TABLAS.isdisjoint(inspect(engine).get_table_names())


def test_0002_marca_como_principal_los_lotes_existentes(cfg):
    from sqlalchemy import text

    command.upgrade(cfg, "0001")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO municipio (id, nombre, provincia) VALUES (1, 'M', 'P')"))
        conn.execute(text(
            "INSERT INTO emergencia (id, municipio_id, tipo, nivel_gravedad, zona_afectada, descripcion,"
            " estado, creada_en) VALUES (1, 1, 'x', 'ALTO', 'z', 'd', 'REGISTRADA', '2026-09-22')"))
        conn.execute(text(
            "INSERT INTO lote (emergencia_id, recurso, cantidad, unidad) VALUES (1, 'Agua', 10, 'litros')"))

    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT tipo FROM lote")).scalar_one() == "PRINCIPAL"


def test_0004_deja_sin_tipo_de_recurso_los_lotes_existentes(cfg):
    from sqlalchemy import text

    command.upgrade(cfg, "0003")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO municipio (id, nombre, provincia) VALUES (1, 'M', 'P')"))
        conn.execute(text(
            "INSERT INTO emergencia (id, municipio_id, tipo, nivel_gravedad, zona_afectada, descripcion,"
            " estado, creada_en) VALUES (1, 1, 'x', 'ALTO', 'z', 'd', 'REGISTRADA', '2026-09-22')"))
        conn.execute(text(
            "INSERT INTO lote (emergencia_id, recurso, cantidad, unidad, tipo)"
            " VALUES (1, 'Agua', 10, 'litros', 'PRINCIPAL')"))

    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT tipo_recurso FROM lote")).scalar_one() is None


def test_hay_una_sola_cabeza_de_migraciones():
    from alembic.script import ScriptDirectory

    c = Config(str(BACKEND / "alembic.ini"))
    c.set_main_option("script_location", str(BACKEND / "migrations"))
    assert len(ScriptDirectory.from_config(c).get_heads()) == 1
