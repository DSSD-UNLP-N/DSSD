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
TABLAS = {"municipio", "ong", "usuario", "emergencia", "lote", "oferta", "oferta_item", "notificacion", "consorcio", "consorcio_miembro"}


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


def test_0005_deja_ronda_1_ofertas_presentadas_y_acepta_los_estados_nuevos(cfg):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    command.upgrade(cfg, "0004")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO municipio (id, nombre, provincia) VALUES (1, 'M', 'P')"))
        conn.execute(text("INSERT INTO ong (id, nombre) VALUES (1, 'O')"))
        conn.execute(text(
            "INSERT INTO emergencia (id, municipio_id, tipo, nivel_gravedad, zona_afectada, descripcion,"
            " estado, creada_en) VALUES (1, 1, 'x', 'ALTO', 'z', 'd', 'CERRADA', '2026-09-22')"))
        conn.execute(text(
            "INSERT INTO oferta (emergencia_id, ong_id, version_actual, creada_en) VALUES (1, 1, 1, '2026-09-22')"))

    command.upgrade(cfg, "head")
    with engine.begin() as conn:
        assert conn.execute(text("SELECT ronda FROM emergencia")).scalar_one() == 1
        assert conn.execute(text("SELECT estado FROM oferta")).scalar_one() == "PRESENTADA"
        conn.execute(text("UPDATE emergencia SET estado = 'EN_EVALUACION'"))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("UPDATE emergencia SET estado = 'CUALQUIERA'"))


def _sembrar_0007(engine):
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO municipio (id, nombre, provincia) VALUES (1, 'M', 'P')"))
        conn.execute(text("INSERT INTO ong (id, nombre) VALUES (1, 'A')"))
        conn.execute(text("INSERT INTO ong (id, nombre) VALUES (2, 'B')"))
        conn.execute(text(
            "INSERT INTO emergencia (id, municipio_id, tipo, nivel_gravedad, zona_afectada, descripcion,"
            " estado, creada_en) VALUES (1, 1, 'x', 'ALTO', 'z', 'd', 'EN_EJECUCION', '2026-09-22')"))
        for ong_id, estado in ((1, 'ADJUDICADA'), (2, 'NO_ADJUDICADA')):
            conn.execute(text(
                "INSERT INTO oferta (emergencia_id, ong_id, version_actual, estado, creada_en)"
                f" VALUES (1, {ong_id}, 1, '{estado}', '2026-09-22')"))


def test_backfill_toma_la_fecha_de_la_notificacion(cfg):
    from sqlalchemy import text

    command.upgrade(cfg, "0007")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
    _sembrar_0007(engine)
    with engine.begin() as conn:
        for texto, fecha in (
            ("Tu oferta para la emergencia #1 fue seleccionada.", "2026-10-02 10:00:00"),
            ("Tu oferta para la emergencia #1 fue seleccionada.", "2026-10-03 10:00:00"),
            ("Otro aviso", "2026-09-30 10:00:00"),
            ("Tu oferta para la emergencia #1 no fue seleccionada.", "2026-10-01 10:00:00"),
        ):
            conn.execute(text(
                "INSERT INTO notificacion (ong_id, emergencia_id, texto, creada_en, leida)"
                f" VALUES (1, 1, '{texto}', '{fecha}', 0)"))
        conn.execute(text(
            "INSERT INTO notificacion (ong_id, emergencia_id, texto, creada_en, leida) VALUES"
            " (2, 1, 'Tu oferta para la emergencia #1 no fue seleccionada.', '2026-10-02 10:00:00', 0)"))

    command.upgrade(cfg, "0008")
    with engine.connect() as conn:
        filas = dict(conn.execute(text("SELECT ong_id, adjudicada_en FROM oferta")).all())
    assert str(filas[1]).startswith("2026-10-02 10:00:00")
    assert filas[2] is None


def test_backfill_sin_notificacion_queda_nulo(cfg):
    from sqlalchemy import text

    command.upgrade(cfg, "0007")
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
    _sembrar_0007(engine)

    command.upgrade(cfg, "0008")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT adjudicada_en FROM oferta WHERE adjudicada_en IS NOT NULL")).all() == []


def test_hay_una_sola_cabeza_de_migraciones():
    from alembic.script import ScriptDirectory

    c = Config(str(BACKEND / "alembic.ini"))
    c.set_main_option("script_location", str(BACKEND / "migrations"))
    assert len(ScriptDirectory.from_config(c).get_heads()) == 1
