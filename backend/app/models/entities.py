import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _enum(e: type[enum.Enum]) -> SAEnum:
    # VARCHAR + CHECK: portable entre Postgres y SQLite, sin ALTER TYPE, y la BD rechaza
    # valores fuera del catálogo (sin create_constraint aceptaría cualquier texto).
    return SAEnum(
        e, native_enum=False, create_constraint=True, length=20,
        values_callable=lambda x: [m.value for m in x],
    )


class Rol(str, enum.Enum):
    MUNICIPIO = "MUNICIPIO"
    COORDINADOR = "COORDINADOR"
    ONG = "ONG"
    AUDITOR = "AUDITOR"


class Gravedad(str, enum.Enum):
    BAJO = "BAJO"
    MEDIO = "MEDIO"
    ALTO = "ALTO"
    CRITICO = "CRITICO"


class EstadoEmergencia(str, enum.Enum):
    REGISTRADA = "REGISTRADA"      # alta hecha, caso Bonita instanciado
    CONVOCATORIA = "CONVOCATORIA"  # lotes publicados, ventana abierta
    CERRADA = "CERRADA"            # ventana vencida; la app todavía no se la entregó a Bonita
    EN_EVALUACION = "EN_EVALUACION"  # Bonita pidió el consolidado; la reserva vive en la API Nacional
    ADJUDICACION = "ADJUDICACION"    # el Coordinador decidió PARCIAL; el Municipio elige ofertas
    EN_EJECUCION = "EN_EJECUCION"    # adjudicado; las ONGs trabajan
    RESUELTA = "RESUELTA"            # cierre bilateral validado, recursos liberados


class EstadoOferta(str, enum.Enum):
    PRESENTADA = "PRESENTADA"        # cargada por la ONG; todavía no se decidió
    ADJUDICADA = "ADJUDICADA"
    NO_ADJUDICADA = "NO_ADJUDICADA"
    FINALIZADA = "FINALIZADA"        # la ONG informó que terminó


class TipoLote(str, enum.Enum):
    PRINCIPAL = "PRINCIPAL"
    APOYO = "APOYO"  # apoyo secundario (consigna, etapa 3 del proceso)


class Municipio(Base):
    __tablename__ = "municipio"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True)
    provincia: Mapped[str] = mapped_column(String(80))

class Ong(Base):
    __tablename__ = "ong"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True)
    cuit: Mapped[str | None] = mapped_column(String(13), unique=True)


class Usuario(Base):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    nombre: Mapped[str] = mapped_column(String(120))
    rol: Mapped[Rol] = mapped_column(_enum(Rol))
    # Un operador municipal pertenece a un municipio; un representante, a una ONG.
    municipio_id: Mapped[int | None] = mapped_column(ForeignKey("municipio.id"))
    ong_id: Mapped[int | None] = mapped_column(ForeignKey("ong.id"))

    municipio: Mapped[Municipio | None] = relationship()
    ong: Mapped[Ong | None] = relationship()


class Emergencia(Base):
    __tablename__ = "emergencia"

    id: Mapped[int] = mapped_column(primary_key=True)
    municipio_id: Mapped[int] = mapped_column(ForeignKey("municipio.id"))
    tipo: Mapped[str] = mapped_column(String(40))  # inundación, incendio, terremoto…
    nivel_gravedad: Mapped[Gravedad] = mapped_column(_enum(Gravedad))
    zona_afectada: Mapped[str] = mapped_column(String(200))
    descripcion: Mapped[str] = mapped_column(Text)
    estado: Mapped[EstadoEmergencia] = mapped_column(
        _enum(EstadoEmergencia), default=EstadoEmergencia.REGISTRADA
    )
    # Caso de Bonita (None hasta que se instancia; ver T-07).
    bonita_case_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    # Ventana real de recepción de ofertas; la fija el Coordinador al publicar.
    ventana_ofertas_fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Sube cuando el Coordinador elige REFORMULAR; entra en la referencia de cada adjudicación.
    ronda: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    municipio: Mapped[Municipio] = relationship()
    lotes: Mapped[list["Lote"]] = relationship(back_populates="emergencia", cascade="all, delete-orphan")
    ofertas: Mapped[list["Oferta"]] = relationship(back_populates="emergencia")


class Lote(Base):
    """Lote de necesidades (p. ej. 5 paramédicos, 1000 raciones de alimento)."""

    __tablename__ = "lote"

    id: Mapped[int] = mapped_column(primary_key=True)
    emergencia_id: Mapped[int] = mapped_column(ForeignKey("emergencia.id"))
    recurso: Mapped[str] = mapped_column(String(120))
    cantidad: Mapped[int] = mapped_column(Integer)
    unidad: Mapped[str] = mapped_column(String(30))  # personas, raciones, litros…
    # Código del catálogo del Sistema Nacional (PARAMEDICO…). Nullable: los lotes anteriores al
    # catálogo no lo tienen y no se validan contra el inventario.
    tipo_recurso: Mapped[str | None] = mapped_column(String(40))
    tipo: Mapped[TipoLote] = mapped_column(
        _enum(TipoLote), default=TipoLote.PRINCIPAL, server_default=TipoLote.PRINCIPAL.value
    )

    emergencia: Mapped[Emergencia] = relationship(back_populates="lotes")


class Oferta(Base):
    """Cabecera de una oferta de una ONG. El detalle vive en OfertaItem, versionado."""

    __tablename__ = "oferta"
    __table_args__ = (UniqueConstraint("emergencia_id", "ong_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    emergencia_id: Mapped[int] = mapped_column(ForeignKey("emergencia.id"))
    ong_id: Mapped[int] = mapped_column(ForeignKey("ong.id"))
    version_actual: Mapped[int] = mapped_column(Integer, default=1)
    estado: Mapped[EstadoOferta] = mapped_column(
        _enum(EstadoOferta), default=EstadoOferta.PRESENTADA, server_default=EstadoOferta.PRESENTADA.value
    )
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    emergencia: Mapped[Emergencia] = relationship(back_populates="ofertas")
    ong: Mapped[Ong] = relationship()
    items: Mapped[list["OfertaItem"]] = relationship(back_populates="oferta", cascade="all, delete-orphan")


class OfertaItem(Base):
    """Línea de una oferta en una versión. Editar = insertar líneas con version+1;
    las versiones anteriores no se tocan (trazabilidad, T-12)."""

    __tablename__ = "oferta_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    oferta_id: Mapped[int] = mapped_column(ForeignKey("oferta.id"))
    version: Mapped[int] = mapped_column(Integer)
    lote_id: Mapped[int] = mapped_column(ForeignKey("lote.id"))
    recurso: Mapped[str] = mapped_column(String(120))
    cantidad: Mapped[int] = mapped_column(Integer)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    oferta: Mapped[Oferta] = relationship(back_populates="items")
    lote: Mapped[Lote] = relationship()


class Notificacion(Base):
    """Aviso para una ONG (adjudicación, cierre…). La app no manda mails: se lee en la propia app."""

    __tablename__ = "notificacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    ong_id: Mapped[int] = mapped_column(ForeignKey("ong.id"))
    emergencia_id: Mapped[int] = mapped_column(ForeignKey("emergencia.id"))
    texto: Mapped[str] = mapped_column(String(300))
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    leida: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
