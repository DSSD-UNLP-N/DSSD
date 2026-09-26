from sqlalchemy import func, select

from app.models import Ong, Rol, Usuario
from app.seed import DEMO_USERS, seed


def test_hay_dos_ongs_cada_una_con_su_representante(seeded):
    with seeded() as s:
        reps = s.scalars(select(Usuario).where(Usuario.rol == Rol.ONG)).all()
        assert {u.username: u.ong.nombre for u in reps} == {
            "ong.cruzroja": "Cruz Roja Argentina",
            "ong.bomberos": "Bomberos Voluntarios",
        }


def test_hay_un_usuario_por_cada_perfil(seeded):
    with seeded() as s:
        assert set(s.scalars(select(Usuario.rol))) == set(Rol)


def test_hay_dos_operadores_en_el_mismo_municipio(seeded):
    """Con un solo municipal, 'la tarea la ejecutó quien la pidió' se cumple por casualidad."""
    with seeded() as s:
        municipales = s.scalars(select(Usuario).where(Usuario.rol == Rol.MUNICIPIO)).all()
        assert len(municipales) == 2
        assert len({u.municipio_id for u in municipales}) == 1


def test_seed_es_idempotente(seeded):
    seed(seeded)
    with seeded() as s:
        assert s.scalar(select(func.count()).select_from(Ong)) == 2
        assert s.scalar(select(func.count()).select_from(Usuario)) == len(DEMO_USERS)
