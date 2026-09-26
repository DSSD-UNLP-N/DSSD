"""Datos de demo: un municipio, dos ONGs y un usuario por cada perfil del enunciado.

Uso (después de `alembic upgrade head`):  python -m app.seed
Es idempotente: si el usuario ya existe, no lo vuelve a crear.
"""
from sqlalchemy import select

from app.core.security import hash_password
from app.db import SessionLocal
from app.models import Municipio, Ong, Rol, Usuario

DEMO_PASSWORD = "demo1234"

MUNICIPIO = ("Bahía Blanca", "Buenos Aires")
# Dos ONGs: sin la segunda no se pueden probar consorcios, ofertas parciales ni cobertura.
ONGS = [("Cruz Roja Argentina", "30-54666544-5"), ("Bomberos Voluntarios", "30-68522415-9")]

# (username, nombre, rol, ONG a la que representa). Los MUNICIPIO van al municipio de arriba.
# Cada uno tiene su homónimo en la organización de Bonita (entrega-2/ACME.xml): la app
# completa las tareas del motor logueándose con el mismo username.
DEMO_USERS = [
    ("operador.municipal", "Operador Municipal", Rol.MUNICIPIO, None),
    # Segundo municipal: con uno solo, "la tarea la ejecutó el usuario del rol" se cumple
    # por casualidad y no prueba nada.
    ("operador.municipal2", "Operador Municipal (segundo turno)", Rol.MUNICIPIO, None),
    ("coordinador.regional", "Centro Coordinador Regional", Rol.COORDINADOR, None),
    ("ong.cruzroja", "Representante Cruz Roja", Rol.ONG, "Cruz Roja Argentina"),
    ("ong.bomberos", "Representante Bomberos Voluntarios", Rol.ONG, "Bomberos Voluntarios"),
    ("auditor", "Auditor / Directivo", Rol.AUDITOR, None),
]


def seed(session_factory=SessionLocal) -> None:
    with session_factory() as db:
        municipio = db.scalar(select(Municipio).where(Municipio.nombre == MUNICIPIO[0]))
        if municipio is None:
            municipio = Municipio(nombre=MUNICIPIO[0], provincia=MUNICIPIO[1])
            db.add(municipio)
        ongs = {}
        for nombre, cuit in ONGS:
            ong = db.scalar(select(Ong).where(Ong.nombre == nombre))
            if ong is None:
                ong = Ong(nombre=nombre, cuit=cuit)
                db.add(ong)
            ongs[nombre] = ong
        db.flush()

        for username, nombre, rol, ong_nombre in DEMO_USERS:
            if db.scalar(select(Usuario).where(Usuario.username == username)) is None:
                db.add(
                    Usuario(
                        username=username,
                        password_hash=hash_password(DEMO_PASSWORD),
                        nombre=nombre,
                        rol=rol,
                        municipio_id=municipio.id if rol is Rol.MUNICIPIO else None,
                        ong_id=ongs[ong_nombre].id if ong_nombre else None,
                    )
                )
        db.commit()


if __name__ == "__main__":
    seed()
    print("Seed listo. Usuarios de demo con contraseña:", DEMO_PASSWORD)
