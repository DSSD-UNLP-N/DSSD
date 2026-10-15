"""Modelos del Sistema Nacional.

`inventario.cantidad_comprometida` la escriben el bloqueo y la liberación de recursos;
disponible = cantidad_total - cantidad_comprometida.
"""
import enum
from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, PrimaryKeyConstraint, String, Text, UniqueConstraint, Enum, Boolean, Column
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

class EstadoCompromiso(str, enum.Enum):
    ACTIVO = "ACTIVO"
    LIBERADO = "LIBERADO"

class Compromiso(Base):
    __tablename__ = "compromiso"
    __table_args__ = (
        UniqueConstraint("emergencia_id", "ong_id", name="uq_compromiso_emergencia_ong"),
    )
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    emergencia_id: Mapped[int] = mapped_column(index=True)
    ong_id: Mapped[int] = mapped_column(ForeignKey("ong.id"))
    
    # Se asume el uso de la función _enum existente en tu archivo models.py
    estado: Mapped[EstadoCompromiso] = mapped_column(
        _enum(EstadoCompromiso), 
        default=EstadoCompromiso.ACTIVO, 
        server_default=EstadoCompromiso.ACTIVO.value,
        nullable=False
    )
    
    ong: Mapped["Ong"] = relationship()
    items: Mapped[list["CompromisoItem"]] = relationship(back_populates="compromiso", cascade="all, delete-orphan")

class CompromisoItem(Base):
    __tablename__ = "compromiso_item"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_compromiso_item_cantidad"),
        UniqueConstraint("compromiso_id", "tipo_recurso_id", name="uq_compromiso_item_recurso"),
    )
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    compromiso_id: Mapped[int] = mapped_column(ForeignKey("compromiso.id"))
    tipo_recurso_id: Mapped[int] = mapped_column(ForeignKey("tipo_recurso.id"))
    cantidad: Mapped[int] = mapped_column()
    
    compromiso: Mapped["Compromiso"] = relationship(back_populates="items")
    tipo_recurso: Mapped["TipoRecurso"] = relationship()