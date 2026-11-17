"""Datos de demo del Sistema Nacional, alineados con el seed de la app local (mismos CUIT).

Uso (después de `alembic upgrade head`):  python -m app.seed
Es idempotente: lo que ya existe (por código o CUIT) no se toca. Las fechas son relativas a hoy
para que la demo siempre tenga certificaciones vigentes y una vencida.

`python -m app.seed --demo` suma, sobre lo anterior, la precarga del coloquio (pauta 2: certificaciones vigentes y stock
suficiente): ver DEMO. Los tests y los escenarios usan el seed base, que tiene los casos borde a propósito.
"""
import sys
from datetime import date, timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.config import get_settings
from app.models import (
    CategoriaRecurso as Cat,
    Certificacion,
    Cuenta,
    EstadoOng,
    Inventario,
    Ong,
    OngCertificacion,
    Riesgo,
    RolCuenta,
    TipoRecurso,
)
from app.security import hash_password

DEMO_PASSWORD = "demo1234"

CERTIFICACIONES = [
    ("SALUD_PREHOSP", "Atención de salud prehospitalaria", "Emergencias médicas en terreno y traslado"),
    ("RESCATE_ACUATICO", "Rescate acuático", "Inundaciones, crecidas y rescate en agua"),
    ("INCENDIO_FORESTAL", "Combate de incendios forestales", "Incendios de vegetación y zona rural"),
    ("RESCATE_URBANO", "Búsqueda y rescate urbano", "Derrumbes y estructuras colapsadas"),
]

# (código, nombre, categoría, unidad, certificación requerida)
TIPOS_RECURSO = [
    ("PARAMEDICO", "Paramédico", Cat.PERSONAL, "personas", "SALUD_PREHOSP"),
    ("AMBULANCIA", "Ambulancia", Cat.VEHICULO, "unidades", "SALUD_PREHOSP"),
    ("RESCATISTA_ACUATICO", "Rescatista acuático", Cat.PERSONAL, "personas", "RESCATE_ACUATICO"),
    ("BOTE_RESCATE", "Bote de rescate", Cat.VEHICULO, "unidades", "RESCATE_ACUATICO"),
    ("BRIGADISTA_FORESTAL", "Brigadista forestal", Cat.PERSONAL, "personas", "INCENDIO_FORESTAL"),
    ("AUTOBOMBA", "Autobomba", Cat.VEHICULO, "unidades", "INCENDIO_FORESTAL"),
    ("RESCATISTA_URBANO", "Rescatista urbano", Cat.PERSONAL, "personas", "RESCATE_URBANO"),
    ("GENERADOR", "Generador eléctrico", Cat.EQUIPAMIENTO, "unidades", None),
    ("RACION_ALIMENTO", "Ración de alimento", Cat.INSUMO, "raciones", None),
    ("AGUA_POTABLE", "Agua potable", Cat.INSUMO, "litros", None),
    ("FRAZADA", "Frazada", Cat.INSUMO, "unidades", None),
]

# Mismos CUIT que el seed de backend/. Cada ONG: (cuit, nombre, estado,
# certificaciones: código -> (riesgo máx, días de vigencia; negativo = vencida),
# inventario: tipo -> cantidad total).
ONGS = [
    (
        "30-54666544-5", "Cruz Roja Argentina", EstadoOng.HABILITADA,
        {"SALUD_PREHOSP": (Riesgo.MEDIO, 365)},
        {"PARAMEDICO": 4, "AMBULANCIA": 2, "RACION_ALIMENTO": 5000, "AGUA_POTABLE": 3000, "FRAZADA": 500},
    ),
    (
        "30-68522415-9", "Bomberos Voluntarios", EstadoOng.HABILITADA,
        {
            "RESCATE_ACUATICO": (Riesgo.CRITICO, 365),
            "INCENDIO_FORESTAL": (Riesgo.ALTO, 240),
            "SALUD_PREHOSP": (Riesgo.BAJO, -90),  # vencida: sus paramédicos van supervisados
        },
        {
            "RESCATISTA_ACUATICO": 12, "BOTE_RESCATE": 3, "BRIGADISTA_FORESTAL": 20,
            "AUTOBOMBA": 4, "PARAMEDICO": 6, "GENERADOR": 5,
        },
    ),
    (
        "30-70000000-1", "Fundación Solidaria Sin Habilitación", EstadoOng.SUSPENDIDA,
        {},
        {"RACION_ALIMENTO": 800},
    ),
]


# Precarga del coloquio. Bomberos renueva SALUD_PREHOSP (en el seed base está vencida) y las dos ONGs tienen más
# paramédicos, para correr los cuatro recorridos y alguna emergencia en vivo sin quedarse sin stock. Cruz Roja sigue con
# SALUD_PREHOSP hasta riesgo MEDIO: en una emergencia ALTO o CRITICO participa como PARCIAL, el caso que muestra los niveles
# de competencia. La ONG suspendida queda: sirve para mostrar que la Nacional rechaza a una ONG no habilitada.
DEMO = {
    "30-54666544-5": ({}, {"PARAMEDICO": 10, "AMBULANCIA": 4}),
    "30-68522415-9": ({"SALUD_PREHOSP": (Riesgo.ALTO, 365)}, {"PARAMEDICO": 10}),
}


def demo(session_factory=SessionLocal) -> None:
    """Aplica DEMO sobre el seed base. Idempotente: fija valores, no suma."""
    seed(session_factory)
    hoy = date.today()
    with session_factory() as db:
        for cuit, (certificaciones, inventario) in DEMO.items():
            ong = db.scalar(select(Ong).where(Ong.cuit == cuit))
            for codigo, (riesgo, dias) in certificaciones.items():
                oc = next(c for c in ong.certificaciones if c.certificacion.codigo == codigo)
                oc.riesgo_max, oc.vence_el = riesgo, hoy + timedelta(days=dias)
            for tipo, cantidad in inventario.items():
                next(i for i in ong.inventario if i.tipo_recurso.codigo == tipo).cantidad_total = cantidad
        db.commit()


def seed(session_factory=SessionLocal) -> None:
    hoy = date.today()
    settings = get_settings()
    with session_factory() as db:
        certs = {}
        for codigo, nombre, descripcion in CERTIFICACIONES:
            cert = db.scalar(select(Certificacion).where(Certificacion.codigo == codigo))
            if cert is None:
                cert = Certificacion(codigo=codigo, nombre=nombre, descripcion=descripcion)
                db.add(cert)
            certs[codigo] = cert

        tipos = {}
        for codigo, nombre, categoria, unidad, cert in TIPOS_RECURSO:
            tipo = db.scalar(select(TipoRecurso).where(TipoRecurso.codigo == codigo))
            if tipo is None:
                tipo = TipoRecurso(
                    codigo=codigo, nombre=nombre, categoria=categoria, unidad=unidad,
                    certificacion=certs[cert] if cert else None,
                )
                db.add(tipo)
            tipos[codigo] = tipo

        for cuit, nombre, estado, certificaciones, inventario in ONGS:
            ong = db.scalar(select(Ong).where(Ong.cuit == cuit))
            if ong is None:
                ong = Ong(
                    cuit=cuit, nombre=nombre, estado=estado,
                    certificaciones=[
                        OngCertificacion(certificacion=certs[c], riesgo_max=riesgo,
                                         vence_el=hoy + timedelta(days=dias))
                        for c, (riesgo, dias) in certificaciones.items()
                    ],
                    inventario=[
                        Inventario(tipo_recurso=tipos[t], cantidad_total=cantidad)
                        for t, cantidad in inventario.items()
                    ],
                )
                db.add(ong)
                db.flush()
            username = {
                "30-54666544-5": "ong.cruzroja",
                "30-68522415-9": "ong.bomberos",
            }.get(cuit)
            if username and db.scalar(select(Cuenta.id).where(Cuenta.username == username)) is None:
                db.add(Cuenta(
                    username=username, password_hash=hash_password(DEMO_PASSWORD),
                    rol=RolCuenta.ONG, ong=ong,
                ))

        usuarios_demo = [
            ("operador.municipal", RolCuenta.MUNICIPIO),
            ("operador.municipal2", RolCuenta.MUNICIPIO),
            ("coordinador.regional", RolCuenta.COORDINADOR),
            ("auditor", RolCuenta.AUDITOR),
        ]
        for username, rol in usuarios_demo:
            if db.scalar(select(Cuenta.id).where(Cuenta.username == username)) is None:
                db.add(Cuenta(username=username, password_hash=hash_password(DEMO_PASSWORD), rol=rol))

        # Cuentas de servicio: la clave sale del entorno y se vuelve a fijar en cada seed (así se rota).
        for username, password in (
            (settings.bonita_service_username, settings.bonita_service_password),
            (settings.app_service_username, settings.app_service_password),
        ):
            servicio = db.scalar(select(Cuenta).where(Cuenta.username == username))
            if servicio is None:
                db.add(Cuenta(username=username, password_hash=hash_password(password), rol=RolCuenta.BONITA))
            else:
                servicio.password_hash = hash_password(password)
        db.commit()


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
        print("Seed del Sistema Nacional listo, con la precarga del coloquio.")
    else:
        seed()
        print("Seed del Sistema Nacional listo.")
