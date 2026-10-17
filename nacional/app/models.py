"""Modelos del Sistema Nacional.

`inventario.cantidad_comprometida` la escriben el bloqueo y la liberación de recursos;
disponible = cantidad_total - cantidad_comprometida.
"""
import enum
from datetime import date, datetime


from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _enum(e: type[enum.Enum]) -> SAEnum:
    # VARCHAR + CHECK: portable entre Postgres y SQLite, sin ALTER TYPE (igual que backend/).
    return SAEnum(
        e, native_enum=False, create_constraint=True, length=20,
        values_callable=lambda x: [m.value for m in x],
    )


class EstadoOng(str, enum.Enum):
    HABILITADA = "HABILITADA"
    SUSPENDIDA = "SUSPENDIDA"


class Riesgo(str, enum.Enum):
    """Misma escala que la gravedad de las emergencias de la app local."""
    BAJO = "BAJO"
    MEDIO = "MEDIO"
    ALTO = "ALTO"
    CRITICO = "CRITICO"


class CategoriaRecurso(str, enum.Enum):
    PERSONAL = "PERSONAL"
    VEHICULO = "VEHICULO"
    EQUIPAMIENTO = "EQUIPAMIENTO"
    INSUMO = "INSUMO"


class RolCuenta(str, enum.Enum):
    ONG = "ONG"
    MUNICIPIO = "MUNICIPIO"
    COORDINADOR = "COORDINADOR"
    AUDITOR = "AUDITOR"
    BONITA = "BONITA"


class Ong(Base):
    __tablename__ = "ong"

    id: Mapped[int] = mapped_column(primary_key=True)
    cuit: Mapped[str] = mapped_column(String(13), unique=True)
    nombre: Mapped[str] = mapped_column(String(120))
    estado: Mapped[EstadoOng] = mapped_column(_enum(EstadoOng), default=EstadoOng.HABILITADA)

    certificaciones: Mapped[list["OngCertificacion"]] = relationship(
        back_populates="ong", cascade="all, delete-orphan"
    )
    inventario: Mapped[list["Inventario"]] = relationship(back_populates="ong", cascade="all, delete-orphan")


class Cuenta(Base):
    __tablename__ = "cuenta"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    rol: Mapped[RolCuenta] = mapped_column(_enum(RolCuenta))
    ong_id: Mapped[int | None] = mapped_column(ForeignKey("ong.id"))

    ong: Mapped[Ong | None] = relationship()


class Certificacion(Base):
    __tablename__ = "certificacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    nombre: Mapped[str] = mapped_column(String(120))
    descripcion: Mapped[str | None] = mapped_column(Text)


class TipoRecurso(Base):
    __tablename__ = "tipo_recurso"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    nombre: Mapped[str] = mapped_column(String(120))
    categoria: Mapped[CategoriaRecurso] = mapped_column(_enum(CategoriaRecurso))
    unidad: Mapped[str] = mapped_column(String(30))
    # Certificación que habilita a operar este recurso; None = no requiere (p. ej. insumos).
    certificacion_id: Mapped[int | None] = mapped_column(ForeignKey("certificacion.id"))

    certificacion: Mapped[Certificacion | None] = relationship()


class OngCertificacion(Base):
    __tablename__ = "ong_certificacion"
    __table_args__ = (UniqueConstraint("ong_id", "certificacion_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ong_id: Mapped[int] = mapped_column(ForeignKey("ong.id"))
    certificacion_id: Mapped[int] = mapped_column(ForeignKey("certificacion.id"))
    # Hasta qué nivel de riesgo puede operar la ONG con esta certificación.
    riesgo_max: Mapped[Riesgo] = mapped_column(_enum(Riesgo))
    vence_el: Mapped[date] = mapped_column(Date)

    ong: Mapped[Ong] = relationship(back_populates="certificaciones")
    certificacion: Mapped[Certificacion] = relationship()


class Inventario(Base):
    __tablename__ = "inventario"
    __table_args__ = (
        UniqueConstraint("ong_id", "tipo_recurso_id"),
        CheckConstraint("cantidad_total >= 0", name="ck_inventario_total"),
        CheckConstraint(
            "cantidad_comprometida >= 0 AND cantidad_comprometida <= cantidad_total",
            name="ck_inventario_comprometida",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ong_id: Mapped[int] = mapped_column(ForeignKey("ong.id"))
    tipo_recurso_id: Mapped[int] = mapped_column(ForeignKey("tipo_recurso.id"))
    cantidad_total: Mapped[int] = mapped_column(Integer)
    cantidad_comprometida: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    ong: Mapped[Ong] = relationship(back_populates="inventario")
    tipo_recurso: Mapped[TipoRecurso] = relationship()

    @property
    def disponible(self) -> int:
        return self.cantidad_total - self.cantidad_comprometida


class CierreOperativo(Base):
    """Aviso de que una ONG terminó una actividad: libera lo que tenía bloqueado."""

    __tablename__ = "cierre_operativo"
    __table_args__ = (UniqueConstraint("ong_id", "referencia", name="uq_cierre_ong_referencia"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ong_id: Mapped[int] = mapped_column(ForeignKey("ong.id"))
    # Identificador de la actividad en el sistema que informa el cierre (emergencia, lote, etc.).
    referencia: Mapped[str] = mapped_column(String(80))
    informado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    ong: Mapped[Ong] = relationship()
    items: Mapped[list["CierreItem"]] = relationship(back_populates="cierre", cascade="all, delete-orphan")


class CierreItem(Base):
    __tablename__ = "cierre_item"
    __table_args__ = (
        UniqueConstraint("cierre_id", "tipo_recurso_id"),
        CheckConstraint("cantidad > 0", name="ck_cierre_item_cantidad"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cierre_id: Mapped[int] = mapped_column(ForeignKey("cierre_operativo.id"))
    tipo_recurso_id: Mapped[int] = mapped_column(ForeignKey("tipo_recurso.id"))
    cantidad: Mapped[int] = mapped_column(Integer)

    cierre: Mapped[CierreOperativo] = relationship(back_populates="items")
    tipo_recurso: Mapped[TipoRecurso] = relationship()


class EstadoAdjudicacion(str, enum.Enum):
    RESERVADA = "RESERVADA"    # lo ofrecido está bloqueado hasta que se decida (evaluación)
    ADJUDICADA = "ADJUDICADA"  # elegida: compromiso nacional firme
    LIBERADA = "LIBERADA"      # no elegida o reformulada: el stock volvió
    CERRADA = "CERRADA"        # la actividad terminó y se liberó lo comprometido


class Adjudicacion(Base):
    """Stock que una ONG tiene bloqueado para una emergencia y una ronda, identificado por su referencia."""

    __tablename__ = "adjudicacion"
    __table_args__ = (UniqueConstraint("referencia_id", name="uq_adjudicacion_referencia"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    referencia_id: Mapped[str] = mapped_column(String(80), nullable=False)
    ong_id: Mapped[int] = mapped_column(ForeignKey("ong.id"), nullable=False)
    emergencia_id: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    estado: Mapped[EstadoAdjudicacion] = mapped_column(
        _enum(EstadoAdjudicacion),
        default=EstadoAdjudicacion.ADJUDICADA,
        server_default=EstadoAdjudicacion.ADJUDICADA.value,
    )

    ong: Mapped[Ong] = relationship()
    items: Mapped[list["AdjudicacionItem"]] = relationship(
        back_populates="adjudicacion", cascade="all, delete-orphan"
    )


class AdjudicacionItem(Base):
    __tablename__ = "adjudicacion_item"
    __table_args__ = (
        UniqueConstraint("adjudicacion_id", "inventario_id", name="uq_adjudicacion_inventario"),
        CheckConstraint("cantidad > 0", name="ck_adjudicacion_item_cantidad"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    adjudicacion_id: Mapped[int] = mapped_column(ForeignKey("adjudicacion.id"), nullable=False)
    inventario_id: Mapped[int] = mapped_column(ForeignKey("inventario.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)

    adjudicacion: Mapped[Adjudicacion] = relationship(back_populates="items")
    inventario: Mapped[Inventario] = relationship()
