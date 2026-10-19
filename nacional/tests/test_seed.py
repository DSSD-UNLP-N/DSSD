from datetime import date

from sqlalchemy import func, select

from app.models import Certificacion, EstadoOng, Inventario, Ong, TipoRecurso
from app.seed import ONGS, TIPOS_RECURSO, seed


def test_seed_es_idempotente(session_factory):
    seed(session_factory)
    seed(session_factory)
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Ong)) == len(ONGS)
        assert db.scalar(select(func.count()).select_from(TipoRecurso)) == len(TIPOS_RECURSO)
        assert db.scalar(select(func.count()).select_from(Certificacion)) == 4


def test_seed_usa_los_cuit_de_la_app_local(session_factory):
    from app.seed import ONGS as nacionales

    # Los mismos que backend/app/seed.py: sin esto la app local no encontraría a sus ONGs.
    assert {c for c, *_ in nacionales} >= {"30-54666544-5", "30-68522415-9"}


def test_seed_cubre_los_casos_de_la_demo(session_factory):
    seed(session_factory)
    with session_factory() as db:
        cruz = db.scalar(select(Ong).where(Ong.cuit == "30-54666544-5"))
        bomberos = db.scalar(select(Ong).where(Ong.cuit == "30-68522415-9"))
        suspendida = db.scalar(select(Ong).where(Ong.estado == EstadoOng.SUSPENDIDA))
        assert suspendida is not None

        # Cruz Roja: 4 paramédicos (el caso de "ofrecer 10 / 2 y después 3").
        paramedicos = next(i for i in cruz.inventario if i.tipo_recurso.codigo == "PARAMEDICO")
        assert paramedicos.disponible == 4

        # Bomberos: una certificación vencida y las demás vigentes.
        vencida = [c.certificacion.codigo for c in bomberos.certificaciones if c.vence_el < date.today()]
        assert vencida == ["SALUD_PREHOSP"]
        assert len(bomberos.certificaciones) == 3


def test_insumos_no_requieren_certificacion(session_factory):
    seed(session_factory)
    with session_factory() as db:
        raciones = db.scalar(select(TipoRecurso).where(TipoRecurso.codigo == "RACION_ALIMENTO"))
        paramedico = db.scalar(select(TipoRecurso).where(TipoRecurso.codigo == "PARAMEDICO"))
        assert raciones.certificacion is None
        assert paramedico.certificacion.codigo == "SALUD_PREHOSP"
        assert db.scalar(select(func.count()).select_from(Inventario)) > 0
