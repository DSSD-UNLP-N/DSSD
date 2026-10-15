"""Garantizan que las migraciones de Alembic y los modelos no se desincronicen."""
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.db import Base

NACIONAL = Path(__file__).resolve().parents[1]
TABLAS = {
    "ong", "certificacion", "tipo_recurso", "ong_certificacion", "inventario",
    "cierre_operativo", "cierre_item", "compromiso", "compromiso_item",
    "adjudicacion", "adjudicacion_item",
}


@pytest.fixture
def cfg(tmp_path):
    c = Config(str(NACIONAL / "alembic.ini"))
    c.set_main_option("script_location", str(NACIONAL / "migrations"))
    c.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'mig.db'}")
    return c


def test_upgrade_head_crea_todas_las_tablas(cfg):
    command.upgrade(cfg, "head")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
    assert TABLAS <= set(inspect(engine).get_table_names())


def test_migraciones_coinciden_con_los_modelos(cfg):
    """Si esto falla: cambiaste models.py sin generar migración.
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


def test_hay_una_sola_cabeza_de_migraciones():
    c = Config(str(NACIONAL / "alembic.ini"))
    c.set_main_option("script_location", str(NACIONAL / "migrations"))
    assert len(ScriptDirectory.from_config(c).get_heads()) == 1
