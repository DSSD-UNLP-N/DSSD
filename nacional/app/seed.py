"""Datos de demo del Sistema Nacional, alineados con el seed de la app local (mismos CUIT).

Uso (después de `alembic upgrade head`):  python -m app.seed
Es idempotente: lo que ya existe (por código o CUIT) no se toca. Las fechas son relativas a hoy
para que la demo siempre tenga certificaciones vigentes y una vencida.
"""
from datetime import date, timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    CategoriaRecurso as Cat,
    Certificacion,
    EstadoOng,
    Inventario,
    Ong,
    OngCertificacion,
    Riesgo,
    TipoRecurso,
)

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


def seed(session_factory=SessionLocal) -> None:
    hoy = date.today()
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
            if db.scalar(select(Ong).where(Ong.cuit == cuit)) is not None:
                continue
            db.add(Ong(
                cuit=cuit, nombre=nombre, estado=estado,
                certificaciones=[
                    OngCertificacion(certificacion=certs[c], riesgo_max=riesgo, vence_el=hoy + timedelta(days=dias))
                    for c, (riesgo, dias) in certificaciones.items()
                ],
                inventario=[
                    Inventario(tipo_recurso=tipos[t], cantidad_total=cantidad) for t, cantidad in inventario.items()
                ],
            ))
        db.commit()


if __name__ == "__main__":
    seed()
    print("Seed del Sistema Nacional listo.")
