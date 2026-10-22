import enum
import re
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import Path
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator
from app.models import CategoriaRecurso, EstadoAdjudicacion, EstadoOng, Riesgo

# Las columnas numéricas son INTEGER (32 bits): un valor mayor llegaría a Postgres y volvería como 500.
MAX_ENTERO = 2_147_483_647
Cantidad = Annotated[int, Field(gt=0, le=MAX_ENTERO)]
IdExterno = Annotated[int, Field(gt=0, le=MAX_ENTERO)]


def ejemplos(*datos: dict, **config) -> ConfigDict:
    """Ejemplos que Swagger muestra como cuerpo de prueba (entrada) o como respuesta de muestra (salida)."""
    return ConfigDict(json_schema_extra={"examples": list(datos)}, **config)


def normalizar_cuit(valor):
    """`30546665445`, ` 30-54666544-5 ` y `30-54666544-5` son el mismo CUIT: se guarda y se busca como `NN-NNNNNNNN-N`.
    Lo que no tiene 11 dígitos se deja tal cual para que el patrón lo rechace."""
    if not isinstance(valor, str):
        return valor
    m = re.fullmatch(r"([0-9]{2})-?([0-9]{8})-?([0-9])", valor.strip())
    return f"{m[1]}-{m[2]}-{m[3]}" if m else valor.strip()


_CUIT_DOC = dict(description="CUIT de la ONG, 11 dígitos. Se acepta con o sin guiones y se guarda como `NN-NNNNNNNN-N`.",
                 examples=["30-54666544-5"])
Cuit = Annotated[str, BeforeValidator(normalizar_cuit), Field(pattern=r"^[0-9]{2}-[0-9]{8}-[0-9]$", **_CUIT_DOC)]
CuitPath = Annotated[str, BeforeValidator(normalizar_cuit), Path(**_CUIT_DOC)]  # en la ruta no se rechaza: un CUIT que no existe da 404
_REFERENCIA_DOC = dict(description="Referencia de la reserva: `emg-{emergencia}-r{ronda}-{cuit}`.", examples=["emg-12-r1-30-54666544-5"])
Referencia = Annotated[str, Field(**_REFERENCIA_DOC)]
ReferenciaPath = Annotated[str, Path(**_REFERENCIA_DOC)]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, description="Cuenta de servicio (`bonita-service`, `app-service`) o de una ONG")
    password: str = Field(min_length=1)

    model_config = ejemplos({"username": "bonita-service", "password": "su-clave"})


class RegisterOngIn(BaseModel):
    ong_nombre: str = Field(min_length=2, max_length=120, description="Nombre de la ONG (único en el registro)")
    cuit: Cuit
    nombre: str = Field(min_length=2, max_length=120, description="Nombre de la persona que administra la cuenta")
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9._-]+$",
                          description="Letras, números, punto, guion y guion bajo; único")
    password: str = Field(min_length=8, max_length=128)

    model_config = ejemplos({
        "ong_nombre": "Asociación Vecinal Esperanza", "cuit": "30-71234567-8", "nombre": "María Gómez",
        "username": "esperanza.admin", "password": "una-clave-de-8+",
    })

    @field_validator("ong_nombre", "nombre", "username", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def password_no_vacia(cls, value):
        if not value.strip():
            raise ValueError("La contraseña no puede ser solo espacios")
        return value


class CuentaOut(BaseModel):
    username: str
    rol: str
    cuit: str | None = Field(None, description="CUIT de la ONG de la cuenta; null para las cuentas de servicio")


class TokenOut(BaseModel):
    access_token: str = Field(description="JWT (HS256). Se envía como `Authorization: Bearer <token>`")
    token_type: str = "bearer"
    user: CuentaOut

    model_config = ejemplos({
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJib25pdGEtc2VydmljZSIs...",
        "token_type": "bearer",
        "user": {"username": "bonita-service", "rol": "BONITA", "cuit": None},
    })


class TipoRecursoOut(BaseModel):
    codigo: str = Field(description="Código que se usa como `tipo_recurso` en el resto de la API")
    nombre: str
    categoria: CategoriaRecurso
    unidad: str
    certificacion_requerida: str | None = Field(description="Certificación que habilita el recurso; null si no exige ninguna")

    model_config = ejemplos({"codigo": "PARAMEDICO", "nombre": "Paramédico", "categoria": "PERSONAL", "unidad": "personas",
                             "certificacion_requerida": "SALUD_PREHOSP"})


class CertificacionOut(BaseModel):
    codigo: str
    nombre: str
    descripcion: str | None
    tipos_recurso: list[str]  # códigos de los tipos de recurso que habilita

    model_config = ejemplos({"codigo": "SALUD_PREHOSP", "nombre": "Atención de salud prehospitalaria",
                             "descripcion": "Emergencias médicas en terreno y traslado",
                             "tipos_recurso": ["AMBULANCIA", "PARAMEDICO"]})


class OngOut(BaseModel):
    cuit: str
    nombre: str
    estado: EstadoOng

    model_config = ejemplos({"cuit": "30-54666544-5", "nombre": "Cruz Roja Argentina", "estado": "HABILITADA"},
                            from_attributes=True)


class OngCertificacionOut(BaseModel):
    codigo: str
    nombre: str
    riesgo_max: Riesgo = Field(description="Riesgo máximo que la certificación permite operar")
    vence_el: date
    vigente: bool = Field(description="false si ya venció: la ONG opera supervisada")


class InventarioOut(BaseModel):
    tipo_recurso: str
    nombre: str
    unidad: str
    cantidad_total: int = Field(description="Lo que la ONG declaró tener")
    cantidad_comprometida: int = Field(description="Bloqueado por reservas y adjudicaciones abiertas")
    disponible: int = Field(description="`cantidad_total - cantidad_comprometida`")
    riesgo_permitido: Riesgo | None = Field(
        description="Hasta qué gravedad puede operar este recurso hoy; null si no tiene certificación vigente")

    model_config = ejemplos({"tipo_recurso": "PARAMEDICO", "nombre": "Paramédico", "unidad": "personas", "cantidad_total": 4,
                             "cantidad_comprometida": 1, "disponible": 3, "riesgo_permitido": "MEDIO"})


class FichaOngOut(OngOut):
    certificaciones: list[OngCertificacionOut]
    inventario: list[InventarioOut]

    model_config = ejemplos({
        "cuit": "30-54666544-5", "nombre": "Cruz Roja Argentina", "estado": "HABILITADA",
        "certificaciones": [{"codigo": "SALUD_PREHOSP", "nombre": "Atención de salud prehospitalaria", "riesgo_max": "MEDIO",
                             "vence_el": "2027-10-01", "vigente": True}],
        "inventario": [{"tipo_recurso": "PARAMEDICO", "nombre": "Paramédico", "unidad": "personas", "cantidad_total": 4,
                        "cantidad_comprometida": 0, "disponible": 4, "riesgo_permitido": "MEDIO"}],
    }, from_attributes=True)


class DisponibilidadOngOut(BaseModel):
    cuit: str
    ong: str
    disponible: int


class DisponibilidadOut(BaseModel):
    tipo_recurso: str
    nombre: str
    unidad: str
    cantidad_total: int
    cantidad_comprometida: int
    disponible: int
    por_ong: list[DisponibilidadOngOut]

    model_config = ejemplos({
        "tipo_recurso": "PARAMEDICO", "nombre": "Paramédico", "unidad": "personas",
        "cantidad_total": 10, "cantidad_comprometida": 2, "disponible": 8,
        "por_ong": [{"cuit": "30-54666544-5", "ong": "Cruz Roja Argentina", "disponible": 3},
                    {"cuit": "30-68522415-9", "ong": "Bomberos Voluntarios", "disponible": 5}],
    })


class InventarioItemIn(BaseModel):
    tipo_recurso: str = Field(min_length=1, description="Código de `GET /tipos-recurso`", examples=["PARAMEDICO"])
    cantidad_total: int = Field(ge=0, le=MAX_ENTERO,
                                description="Total que la ONG tiene; no puede ser menor a lo ya comprometido")


class InventarioIn(BaseModel):
    items: list[InventarioItemIn] = Field(min_length=1)

    model_config = ejemplos({"items": [{"tipo_recurso": "PARAMEDICO", "cantidad_total": 6},
                                       {"tipo_recurso": "AMBULANCIA", "cantidad_total": 2}]})


class NivelCompetencia(str, enum.Enum):
    PLENA = "PLENA"  # certificación vigente y suficiente para la gravedad
    PARCIAL = "PARCIAL"  # certificación vigente pero de menor riesgo que la gravedad
    SUPERVISADA = "SUPERVISADA"  # sin certificación vigente (o ONG no habilitada)


class Asignacion(str, enum.Enum):
    PRINCIPAL = "PRINCIPAL"
    APOYO = "APOYO"


class ItemValidacionIn(BaseModel):
    cuit: Cuit
    tipo_recurso: str = Field(min_length=1, description="Código de `GET /tipos-recurso`", examples=["PARAMEDICO"])
    cantidad: Cantidad = Field(description="Cantidad ofrecida por la ONG")


class ValidacionIn(BaseModel):
    gravedad: Riesgo = Field(description="Gravedad de la emergencia; se compara con el riesgo que cada ONG puede operar")
    items: list[ItemValidacionIn] = Field(min_length=1)

    model_config = ejemplos({"gravedad": "ALTO", "items": [
        {"cuit": "30-54666544-5", "tipo_recurso": "PARAMEDICO", "cantidad": 3},
        {"cuit": "30-68522415-9", "tipo_recurso": "BOTE_RESCATE", "cantidad": 2},
    ]})


class ResultadoValidacionOut(BaseModel):
    cuit: str
    ong: str | None  # None = ONG no registrada
    tipo_recurso: str
    nombre_recurso: str
    unidad: str
    solicitado: int
    disponible: int
    alcanza: bool = Field(description="true si lo solicitado entra en lo disponible")
    nivel: NivelCompetencia = Field(
        description="PLENA: certificación suficiente para la gravedad; PARCIAL: certificación de menor riesgo; "
        "SUPERVISADA: sin certificación vigente")
    riesgo_permitido: Riesgo | None
    asignacion_sugerida: Asignacion = Field(description="PRINCIPAL si la competencia es plena; APOYO si no")
    observaciones: list[str]


class ValidacionOut(BaseModel):
    alcanza_todo: bool
    resultados: list[ResultadoValidacionOut]

    model_config = ejemplos({"alcanza_todo": True, "resultados": [{
        "cuit": "30-54666544-5", "ong": "Cruz Roja Argentina", "tipo_recurso": "PARAMEDICO", "nombre_recurso": "Paramédico",
        "unidad": "personas", "solicitado": 3, "disponible": 4, "alcanza": True, "nivel": "PARCIAL", "riesgo_permitido": "MEDIO",
        "asignacion_sugerida": "APOYO", "observaciones": ["Certificación vigente hasta riesgo MEDIO; la emergencia es ALTO"],
    }]})


class CierreIn(BaseModel):
    cuit: Cuit
    referencia: Referencia = Field(min_length=1, max_length=80)

    model_config = ejemplos({"cuit": "30-54666544-5", "referencia": "emg-12-r1-30-54666544-5"}, str_strip_whitespace=True)


class CierreLoteIn(BaseModel):
    """Los cierres de varias ONGs de una emergencia, para que un solo pedido de Bonita los resuelva."""
    cierres: list[CierreIn] = Field(min_length=1)

    model_config = ejemplos({"cierres": [{"cuit": "30-54666544-5", "referencia": "emg-12-r1-30-54666544-5"},
                                         {"cuit": "30-68522415-9", "referencia": "emg-12-r1-30-68522415-9"}]})


class CierreItemOut(BaseModel):
    tipo_recurso: str
    nombre: str
    unidad: str
    cantidad_liberada: int = Field(description="Lo que la adjudicación tenía comprometido y vuelve al inventario")
    cantidad_total: int
    cantidad_comprometida: int
    disponible: int


class CierreOut(BaseModel):
    id: int
    cuit: str
    ong: str
    referencia: str
    informado_en: datetime
    items: list[CierreItemOut]

    model_config = ejemplos({
        "id": 7, "cuit": "30-54666544-5", "ong": "Cruz Roja Argentina", "referencia": "emg-12-r1-30-54666544-5",
        "informado_en": "2026-10-22T14:30:00Z",
        "items": [{"tipo_recurso": "PARAMEDICO", "nombre": "Paramédico", "unidad": "personas", "cantidad_liberada": 3,
                   "cantidad_total": 4, "cantidad_comprometida": 0, "disponible": 4}],
    })


class AdjudicacionItemIn(BaseModel):
    inventario_id: IdExterno = Field(description="Id de la fila de inventario de la ONG (no el código del recurso)")
    cantidad: Cantidad = Field(description="Cantidad a bloquear; no puede superar lo disponible")


class AdjudicacionIn(BaseModel):
    referencia_id: str = Field(
        min_length=1, max_length=80,
        description="Clave de idempotencia: repetir la misma referencia devuelve la adjudicación ya creada")
    ong_id: IdExterno = Field(description="Id numérico de la ONG dueña de los inventarios")
    emergencia_id: IdExterno = Field(description="Id de la emergencia en la app local")
    items: list[AdjudicacionItemIn] = Field(min_length=1)

    model_config = ejemplos({"referencia_id": "emg-12-r1-30-54666544-5", "ong_id": 1, "emergencia_id": 12,
                             "items": [{"inventario_id": 1, "cantidad": 3}]}, str_strip_whitespace=True)


class AdjudicacionItemOut(BaseModel):
    inventario_id: int
    cantidad: int


class AdjudicacionOut(BaseModel):
    id: int
    referencia_id: str
    ong_id: int
    emergencia_id: int
    fecha_creacion: datetime
    estado: EstadoAdjudicacion
    items: list[AdjudicacionItemOut]

    model_config = ejemplos({"id": 5, "referencia_id": "emg-12-r1-30-54666544-5", "ong_id": 1, "emergencia_id": 12,
                             "fecha_creacion": "2026-10-22T14:00:00Z", "estado": "RESERVADA",
                             "items": [{"inventario_id": 1, "cantidad": 3}]})


# --- Evaluación y reserva (eslabón 4): lo que Bonita manda tal cual lo recibió de la app local ---

class LoteEvaluacionIn(BaseModel):
    lote_id: IdExterno = Field(description="Id del lote de necesidad en la app local")
    tipo_recurso: str | None = Field(
        None, description="Código del recurso pedido; null = lote anterior al catálogo, no se puede cubrir")
    cantidad: Cantidad = Field(description="Cantidad pedida")
    tipo: Literal["PRINCIPAL", "APOYO"] = Field("PRINCIPAL", description="Si el lote es recurso principal o de apoyo")


class ItemOfertaIn(BaseModel):
    lote_id: IdExterno = Field(description="Lote del pedido al que responde; debe existir en `lotes`")
    tipo_recurso: str = Field(min_length=1, description="Debe ser el mismo recurso que pide el lote")
    cantidad: Cantidad = Field(description="Cantidad ofrecida")


class OfertaEvaluacionIn(BaseModel):
    cuit: Cuit
    ong: str | None = Field(None, description="Nombre de la ONG, informativo")
    version: int | None = Field(None, description="Versión de la oferta en la app local, informativa")
    items: list[ItemOfertaIn] = Field(min_length=1)


class EvaluacionIn(BaseModel):
    emergencia_id: IdExterno = Field(description="Id de la emergencia en la app local")
    ronda: int = Field(default=1, ge=1, le=MAX_ENTERO,
                       description="Ronda de evaluación; forma parte de la referencia de la reserva")
    gravedad: Riesgo
    lotes: list[LoteEvaluacionIn] = Field(description="Lo que la emergencia necesita; cada `lote_id` una sola vez")
    ofertas: list[OfertaEvaluacionIn] = Field(description="Lo que ofreció cada ONG, apuntando a lotes del pedido")

    model_config = ejemplos({
        "emergencia_id": 12, "ronda": 1, "gravedad": "MEDIO",
        "lotes": [{"lote_id": 101, "tipo_recurso": "PARAMEDICO", "cantidad": 6, "tipo": "PRINCIPAL"},
                  {"lote_id": 102, "tipo_recurso": "AMBULANCIA", "cantidad": 2, "tipo": "APOYO"}],
        "ofertas": [{"cuit": "30-54666544-5", "ong": "Cruz Roja Argentina", "version": 1,
                     "items": [{"lote_id": 101, "tipo_recurso": "PARAMEDICO", "cantidad": 3},
                               {"lote_id": 102, "tipo_recurso": "AMBULANCIA", "cantidad": 1}]}],
    })

    @model_validator(mode="after")
    def lotes_y_ofertas_coherentes(self):
        """Cada lote una sola vez y cada ítem ofrecido apunta a un lote del pedido y de su mismo recurso: si no, se
        reservaría stock para algo que no se pidió o se contaría como cobertura de otro recurso."""
        ids = [l.lote_id for l in self.lotes]
        if len(set(ids)) != len(ids):
            raise ValueError("Hay lotes repetidos")
        por_id = {l.lote_id: l for l in self.lotes}
        for oferta in self.ofertas:
            for item in oferta.items:
                lote = por_id.get(item.lote_id)
                if lote is None:
                    raise ValueError(f"La oferta de {oferta.cuit} apunta al lote {item.lote_id}, que no está en el pedido")
                if lote.tipo_recurso != item.tipo_recurso:
                    raise ValueError(
                        f"La oferta de {oferta.cuit} ofrece {item.tipo_recurso} para el lote {item.lote_id}, "
                        f"que pide {lote.tipo_recurso}"
                    )
        return self


class LoteCoberturaOut(BaseModel):
    lote_id: int
    tipo_recurso: str | None
    pedido: int
    reservado: int
    porcentaje: float = Field(description="`reservado / pedido`, de 0 a 1")
    cubierto: bool


class ItemEvaluadoOut(BaseModel):
    lote_id: int
    tipo_recurso: str
    ofrecido: int
    reservado: int
    nivel: NivelCompetencia
    riesgo_permitido: Riesgo | None
    asignacion_sugerida: Asignacion
    observaciones: list[str]


class OngEvaluadaOut(BaseModel):
    cuit: str
    ong: str | None
    referencia: str | None = Field(
        description="Referencia de la reserva; null = ONG no registrada, no hay nada reservado")
    estado: str = Field(
        description="Estado de la reserva (RESERVADA, ADJUDICADA, ...) o NO_RESERVADA si lo ofrecido supera lo disponible")
    items: list[ItemEvaluadoOut]


class EvaluacionOut(BaseModel):
    emergencia_id: int
    ronda: int
    cobertura_completa: bool
    porcentaje_cobertura: float = Field(description="Promedio simple de la cobertura de los lotes, de 0 a 1")
    lotes: list[LoteCoberturaOut]
    ongs: list[OngEvaluadaOut]

    model_config = ejemplos({
        "emergencia_id": 12, "ronda": 1, "cobertura_completa": False, "porcentaje_cobertura": 0.5,
        "lotes": [{"lote_id": 101, "tipo_recurso": "PARAMEDICO", "pedido": 6, "reservado": 3, "porcentaje": 0.5,
                   "cubierto": False}],
        "ongs": [{"cuit": "30-54666544-5", "ong": "Cruz Roja Argentina", "referencia": "emg-12-r1-30-54666544-5",
                  "estado": "RESERVADA",
                  "items": [{"lote_id": 101, "tipo_recurso": "PARAMEDICO", "ofrecido": 3, "reservado": 3, "nivel": "PLENA",
                             "riesgo_permitido": "MEDIO", "asignacion_sugerida": "PRINCIPAL", "observaciones": []}]}],
    })


class ReservaOut(BaseModel):
    referencia: str
    estado: EstadoAdjudicacion

    model_config = ejemplos({"referencia": "emg-12-r1-30-54666544-5", "estado": "ADJUDICADA"})


class RecursoLiberadoOut(BaseModel):
    tipo_recurso: str
    cantidad: int


class LiberacionOut(ReservaOut):
    liberado: list[RecursoLiberadoOut]

    model_config = ejemplos({"referencia": "emg-12-r1-30-54666544-5", "estado": "LIBERADA",
                             "liberado": [{"tipo_recurso": "PARAMEDICO", "cantidad": 3}]})


class ResolucionIn(BaseModel):
    """La decisión del Municipio sobre las reservas de una emergencia: cuáles se confirman y cuáles se liberan."""
    confirmar: list[str] = Field(default_factory=list, description="Referencias que pasan a ADJUDICADA")
    liberar: list[str] = Field(default_factory=list, description="Referencias cuyo stock se devuelve")

    model_config = ejemplos({"confirmar": ["emg-12-r1-30-54666544-5"], "liberar": ["emg-12-r1-30-68522415-9"]})


class ResolucionOut(BaseModel):
    confirmadas: list[ReservaOut]
    liberadas: list[LiberacionOut]

    model_config = ejemplos({
        "confirmadas": [{"referencia": "emg-12-r1-30-54666544-5", "estado": "ADJUDICADA"}],
        "liberadas": [{"referencia": "emg-12-r1-30-68522415-9", "estado": "LIBERADA",
                       "liberado": [{"tipo_recurso": "BOTE_RESCATE", "cantidad": 2}]}],
    })
