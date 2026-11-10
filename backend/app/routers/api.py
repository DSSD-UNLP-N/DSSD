
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.core.deps import require_role
from app.core.security import verify_password
from app.core.labels import ROL_LABEL, TIPO_LABEL
from app.db import get_db
from app.integrations.nacional import NacionalClient, get_nacional
from app.models import Consorcio, Emergencia, Notificacion, Oferta, Ong, Rol, Usuario
from app.schemas.api import (
    AdjudicarIn,
    AltaOngIn,
    AltaOngOut,
    ConsorcioIn,
    ConsorcioOut,
    DecisionIn,
    EmergenciaIn,
    EmergenciaOut,
    InvitacionIn,
    InventarioIn,
    InventarioOngOut,
    LoginIn,
    LoteIn,
    LoteOut,
    MiembroOut,
    NotificacionOut,
    OfertaIn,
    OfertaOut,
    OngOut,
    PublicarIn,
    RespuestaIn,
    TipoRecursoOut,
    UsuarioOut,
)
from app.schemas.evaluacion import Evaluacion
from app.seed import DEMO_PASSWORD, DEMO_USERS
from app.services.emergencias import (
    emergencia_visible,
    emergencias_visibles,
    registrar_emergencia,
    tarea_ong_en_bonita,
)
from app.services import inventario
from app.services.alta_ong import alta_ong
from app.services.ciclo import adjudicar, decidir
from app.services.ejecucion import finalizar, monitorear, resumen, validar_cierre
from app.services import consorcios as svc_consorcios
from app.services.consorcios import ConsorcioError
from app.services.ofertas import publicar_oferta
from app.services.lotes import agregar_lote, borrar_lote, publicar_convocatoria

router = APIRouter(prefix="/api")

# Ids de la ruta: enteros de 32 bits como las columnas. Con Postgres un valor más grande da 500 (el dialecto
# psycopg castea el parámetro a INTEGER); así sale 422.
Id = Annotated[int, Path(ge=1, le=2**31 - 1)]


def _require_visible(db: Session, user: Usuario, emergencia_id: int) -> Emergencia:
    emergencia = emergencia_visible(db, user, emergencia_id)
    if emergencia is None:
        raise HTTPException(status_code=404, detail="Emergencia no encontrada")
    return emergencia


@router.get("/meta")
def meta(settings: Settings = Depends(get_settings)):
    demo = None
    if settings.show_demo_users:
        demo = {
            "password": DEMO_PASSWORD,
            "users": [
                {"username": u, "rol": rol.value, "label": ROL_LABEL[rol.value]}
                for u, _, rol, _ in DEMO_USERS
            ],
        }
    return {"tipos": TIPO_LABEL, "demo": demo}


@router.post("/auth/login", response_model=UsuarioOut)
def api_login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(Usuario).where(Usuario.username == body.username.strip()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    request.session.clear()
    request.session.update({"uid": user.id, "nombre": user.nombre, "rol": user.rol.value})
    return user


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def api_logout(request: Request):
    request.session.clear()


@router.get("/auth/me", response_model=UsuarioOut)
def api_me(user: Usuario = Depends(require_role())):
    return user


@router.get("/emergencias", response_model=list[EmergenciaOut])
def api_listar(
    user: Usuario = Depends(require_role()),
    db: Session = Depends(get_db),
):
    return emergencias_visibles(db, user)


@router.post("/emergencias", response_model=EmergenciaOut, status_code=201)
def api_crear(
    body: EmergenciaIn,
    user: Usuario = Depends(require_role(Rol.MUNICIPIO)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    return registrar_emergencia(db, settings, operador=user, **body.model_dump())


@router.get("/emergencias/{emergencia_id}", response_model=EmergenciaOut)
def api_detalle(
    emergencia_id: Id,
    user: Usuario = Depends(require_role()),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    return _detalle_out(db, _require_visible(db, user, emergencia_id), user, settings)


def _detalle_out(db: Session, emergencia: Emergencia, user: Usuario, settings: Settings) -> EmergenciaOut:
    out = EmergenciaOut.model_validate(emergencia)
    out.tarea_bonita = tarea_ong_en_bonita(settings, emergencia, user)
    if emergencia.evaluacion and user.rol is not Rol.ONG:
        out.evaluacion = Evaluacion.model_validate_json(emergencia.evaluacion)
    out.ejecucion = resumen(db, emergencia, user)
    return out


@router.post("/emergencias/{emergencia_id}/decision", response_model=EmergenciaOut)
def api_decidir(
    emergencia_id: Id,
    body: DecisionIn,
    user: Usuario = Depends(require_role(Rol.COORDINADOR)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    nacional: NacionalClient = Depends(get_nacional),
):
    """Con la cobertura incompleta: PARCIAL sigue con lo reservado; REFORMULAR libera todo y empieza otra ronda."""
    emergencia = _require_visible(db, user, emergencia_id)
    decidir(db, settings, nacional, emergencia=emergencia, coordinador=user, decision=body.decision)
    return _detalle_out(db, emergencia, user, settings)


@router.post("/emergencias/{emergencia_id}/adjudicar", response_model=EmergenciaOut)
def api_adjudicar(
    emergencia_id: Id,
    body: AdjudicarIn,
    user: Usuario = Depends(require_role(Rol.MUNICIPIO)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """El Municipio elige entre las ofertas validadas. Bonita confirma lo elegido y libera lo demás."""
    emergencia = _require_visible(db, user, emergencia_id)
    adjudicar(db, settings, emergencia=emergencia, municipal=user, cuits=body.cuits)
    return _detalle_out(db, emergencia, user, settings)


def _avanzar(db: Session, emergencia_id: int, user: Usuario, settings: Settings, paso) -> EmergenciaOut:
    """Un paso de la ejecución: lo hace `paso(emergencia)`; si algo falla no queda nada a medias."""
    emergencia = _require_visible(db, user, emergencia_id)
    paso(emergencia)
    return _detalle_out(db, emergencia, user, settings)


@router.post("/emergencias/{emergencia_id}/monitorear", response_model=EmergenciaOut)
def api_monitorear(
    emergencia_id: Id,
    user: Usuario = Depends(require_role(Rol.COORDINADOR)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """El Coordinador empieza a monitorear la ejecución; desde ahí las ONGs pueden marcar su actividad finalizada."""
    return _avanzar(db, emergencia_id, user, settings,
                    lambda e: monitorear(db, settings, emergencia=e, coordinador=user))


@router.post("/emergencias/{emergencia_id}/finalizar", response_model=EmergenciaOut)
def api_finalizar(
    emergencia_id: Id,
    user: Usuario = Depends(require_role(Rol.ONG)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Una ONG adjudicada informa que terminó su actividad."""
    return _avanzar(db, emergencia_id, user, settings,
                    lambda e: finalizar(db, settings, emergencia=e, usuario=user))


@router.post("/emergencias/{emergencia_id}/validar-cierre", response_model=EmergenciaOut)
def api_validar_cierre(
    emergencia_id: Id,
    user: Usuario = Depends(require_role(Rol.COORDINADOR)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Con todas las ONGs finalizadas, el Coordinador valida el cierre bilateral; Bonita libera los recursos."""
    return _avanzar(db, emergencia_id, user, settings,
                    lambda e: validar_cierre(db, settings, emergencia=e, coordinador=user))


@router.get("/notificaciones", response_model=list[NotificacionOut])
def api_notificaciones(user: Usuario = Depends(require_role()), db: Session = Depends(get_db)):
    """Los avisos de la ONG del usuario, los más nuevos primero. Los demás perfiles no reciben avisos."""
    if user.ong_id is None:
        return []
    return db.scalars(
        select(Notificacion).where(Notificacion.ong_id == user.ong_id)
        .order_by(Notificacion.id.desc()).limit(100)
    ).all()


@router.post("/notificaciones/{notificacion_id}/leida", response_model=NotificacionOut)
def api_marcar_leida(
    notificacion_id: Id,
    user: Usuario = Depends(require_role(Rol.ONG)),
    db: Session = Depends(get_db),
):
    aviso = db.get(Notificacion, notificacion_id)
    if aviso is None or aviso.ong_id != user.ong_id:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    aviso.leida = True
    db.commit()
    return aviso


@router.get("/tipos-recurso", response_model=list[TipoRecursoOut])
def api_tipos_recurso(
    user: Usuario = Depends(require_role()),
    nacional: NacionalClient = Depends(get_nacional),
):
    """Catálogo de recursos del Sistema Nacional, para elegir el tipo de cada lote."""
    return nacional.tipos_recurso()


@router.get("/ong/inventario", response_model=InventarioOngOut)
def api_ver_inventario(
    user: Usuario = Depends(require_role(Rol.ONG)),
    nacional: NacionalClient = Depends(get_nacional),
):
    """Certificaciones e inventario de la ONG del usuario, leídos del Sistema Nacional con la cuenta de servicio."""
    return inventario.ver(nacional, user.ong)


@router.put("/ong/inventario", response_model=InventarioOngOut)
def api_declarar_inventario(
    body: InventarioIn,
    user: Usuario = Depends(require_role(Rol.ONG)),
    nacional: NacionalClient = Depends(get_nacional),
):
    """Actualiza el total de cada rubro de la ONG del usuario en el Sistema Nacional (los rubros que no vienen no
    cambian). 409 si un total queda por debajo de lo comprometido; 422 si un tipo de recurso no existe."""
    return inventario.declarar(nacional, user.ong, body.rubros)


@router.get("/ongs/alta/tipos-recurso", response_model=list[TipoRecursoOut])
def api_alta_tipos_recurso(nacional: NacionalClient = Depends(get_nacional)):
    """Catálogo para la pantalla pública de alta de ONG (sin sesión)."""
    return nacional.tipos_recurso()


@router.post("/ongs/alta", response_model=AltaOngOut, status_code=201)
def api_alta_ong(
    body: AltaOngIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    nacional: NacionalClient = Depends(get_nacional),
):
    """Alta pública de una ONG en Bonita, el Sistema Nacional y la app."""
    usuario = alta_ong(db, settings, nacional, body)
    return AltaOngOut(ong_nombre=usuario.ong.nombre, cuit=usuario.ong.cuit, username=usuario.username,
                      rubros=body.rubros)


@router.post("/emergencias/{emergencia_id}/lotes", response_model=LoteOut, status_code=201)
def api_crear_lote(
    emergencia_id: Id,
    body: LoteIn,
    user: Usuario = Depends(require_role(Rol.COORDINADOR)),
    db: Session = Depends(get_db),
    nacional: NacionalClient = Depends(get_nacional),
):
    emergencia = _require_visible(db, user, emergencia_id)
    return agregar_lote(db, emergencia, body, nacional)


@router.delete("/emergencias/{emergencia_id}/lotes/{lote_id}", status_code=204)
def api_borrar_lote(
    emergencia_id: Id,
    lote_id: Id,
    user: Usuario = Depends(require_role(Rol.COORDINADOR)),
    db: Session = Depends(get_db),
):
    emergencia = _require_visible(db, user, emergencia_id)
    borrar_lote(db, emergencia, lote_id)


@router.post("/emergencias/{emergencia_id}/publicar", response_model=EmergenciaOut)
def api_publicar(
    emergencia_id: Id,
    body: PublicarIn,
    user: Usuario = Depends(require_role(Rol.COORDINADOR)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    emergencia = _require_visible(db, user, emergencia_id)
    return publicar_convocatoria(
        db,
        settings,
        emergencia=emergencia,
        coordinador=user,
        ventana_fin=body.ventana_fin,
    )


def _con_consorcio(out: OfertaOut, consorcio: Consorcio | None) -> OfertaOut:
    if consorcio is None:
        return out
    return out.model_copy(update={"consorcio_id": consorcio.id, "consorcio_nombre": consorcio.nombre})


@router.get("/emergencias/{emergencia_id}/ofertas", response_model=list[OfertaOut])
def api_listar_ofertas(
    emergencia_id: Id,
    user: Usuario = Depends(require_role()),
    db: Session = Depends(get_db),
):
    """Ofertas de la emergencia. Una ONG ve la suya y, si pertenece a un consorcio válido, la vigente de los
    miembros aceptados (solo lectura); nada más. Cada oferta trae su consorcio válido, si lo tiene."""
    _require_visible(db, user, emergencia_id)
    por_ong = {
        m.ong_id: c
        for c in svc_consorcios.consorcios_validos(db, emergencia_id)
        for m in svc_consorcios.miembros_aceptados(c)
    }
    query = select(Oferta).where(Oferta.emergencia_id == emergencia_id)
    if user.rol is Rol.ONG:  # una ONG no ve las ofertas de las demás, salvo las de su consorcio válido
        propio = por_ong.get(user.ong_id)
        visibles = {m.ong_id for m in svc_consorcios.miembros_aceptados(propio)} if propio else set()
        query = query.where(Oferta.ong_id.in_(visibles | {user.ong_id}))
    ofertas = db.scalars(query.options(selectinload(Oferta.items), selectinload(Oferta.ong))).all()
    return [_con_consorcio(OfertaOut.model_validate(o), por_ong.get(o.ong_id)) for o in ofertas]


@router.post("/emergencias/{emergencia_id}/ofertas", response_model=OfertaOut, status_code=201)
def api_crear_oferta(
    emergencia_id: Id,
    body: OfertaIn,
    user: Usuario = Depends(require_role(Rol.ONG)),
    db: Session = Depends(get_db),
    nacional: NacionalClient = Depends(get_nacional),
):
    """Cada envío es la oferta completa: una versión nueva con todos sus ítems (T-12)."""
    emergencia = _require_visible(db, user, emergencia_id)
    return publicar_oferta(db, nacional, emergencia=emergencia, ong=user.ong, items=body.items)


# --- Consorcios -----------------------------------------------------------------------------------------------

def _errores(**codigos: str) -> dict:
    return {int(c[1:]): {"description": d} for c, d in codigos.items()}


def _consorcio_out(db: Session, c: Consorcio) -> ConsorcioOut:
    lider = db.get(Ong, c.ong_lider_id)
    miembros = sorted(c.miembros, key=lambda m: m.id)
    return ConsorcioOut(
        id=c.id,
        emergencia_id=c.emergencia_id,
        nombre=c.nombre,
        ong_lider_id=c.ong_lider_id,
        ong_lider_nombre=lider.nombre,
        valido=svc_consorcios.es_valido(c),
        disuelto=c.disuelto_en is not None,
        miembros=[
            MiembroOut(
                ong_id=m.ong_id, ong_nombre=m.ong.nombre, cuit=m.ong.cuit, estado=m.estado.value,
                invitado_en=m.invitado_en, respondido_en=m.respondido_en, salio_en=m.salio_en,
            )
            for m in miembros
        ],
    )


def _consorcio_visible(db: Session, user: Usuario, consorcio_id: int) -> Consorcio:
    c = db.get(Consorcio, consorcio_id)
    if c is None or emergencia_visible(db, user, c.emergencia_id) is None:
        raise HTTPException(status_code=404, detail="Consorcio no encontrado")
    return c


@router.get(
    "/emergencias/{emergencia_id}/consorcios",
    response_model=list[ConsorcioOut],
    summary="Consorcios de una emergencia",
    responses=_errores(_401="Sin sesión.", _404="La emergencia no existe o no es visible para el usuario."),
)
def api_listar_consorcios(
    emergencia_id: Id,
    user: Usuario = Depends(require_role()),
    db: Session = Depends(get_db),
):
    """Los consorcios no disueltos de la emergencia, con sus miembros. Lo ve cualquier rol que vea la emergencia
    y responde siempre, también con la ventana de ofertas cerrada."""
    _require_visible(db, user, emergencia_id)
    filas = db.scalars(
        select(Consorcio)
        .where(Consorcio.emergencia_id == emergencia_id, Consorcio.disuelto_en.is_(None))
        .order_by(Consorcio.id)
        .options(selectinload(Consorcio.miembros))
    ).all()
    return [_consorcio_out(db, c) for c in filas]


@router.post(
    "/emergencias/{emergencia_id}/consorcios",
    response_model=ConsorcioOut,
    status_code=201,
    summary="Crear un consorcio",
    responses=_errores(
        _401="Sin sesión.", _403="Solo las ONGs crean consorcios.", _404="La emergencia no existe o no es visible.",
        _409="Ventana de ofertas cerrada, nombre repetido en la emergencia o la ONG ya está en un consorcio.",
        _422="Nombre vacío o fuera de 2 a 80 caracteres.",
    ),
)
def api_crear_consorcio(
    emergencia_id: Id,
    body: ConsorcioIn,
    user: Usuario = Depends(require_role(Rol.ONG)),
    db: Session = Depends(get_db),
):
    """La ONG que llama queda como líder y primera miembro aceptada. Con un solo miembro todavía no es válido."""
    emergencia = _require_visible(db, user, emergencia_id)
    try:
        c = svc_consorcios.crear(db, emergencia=emergencia, ong=user.ong, nombre=body.nombre)
    except IntegrityError as exc:  # dos pedidos con el mismo nombre a la vez: gana uno y el otro choca con la tabla
        db.rollback()
        raise ConsorcioError(svc_consorcios.NOMBRE_REPETIDO) from exc
    return _consorcio_out(db, c)


@router.post(
    "/consorcios/{consorcio_id}/invitaciones",
    response_model=ConsorcioOut,
    status_code=201,
    summary="Invitar a una ONG al consorcio",
    responses=_errores(
        _401="Sin sesión.", _403="Solo la ONG líder invita.", _404="El consorcio o la ONG no existen.",
        _409="Ventana cerrada, consorcio disuelto, la ONG ya está en un consorcio o es la propia líder.",
        _422="ong_id mal formado.",
    ),
)
def api_invitar(
    consorcio_id: Id,
    body: InvitacionIn,
    user: Usuario = Depends(require_role(Rol.ONG)),
    db: Session = Depends(get_db),
):
    """Crea una invitación pendiente y le avisa a la ONG invitada."""
    c = _consorcio_visible(db, user, consorcio_id)
    invitada = db.get(Ong, body.ong_id)
    if invitada is None:
        raise HTTPException(status_code=404, detail="ONG no encontrada")
    svc_consorcios.invitar(db, consorcio=c, lider=user.ong, invitada=invitada)
    return _consorcio_out(db, c)


@router.post(
    "/consorcios/{consorcio_id}/respuesta",
    response_model=ConsorcioOut,
    summary="Aceptar o rechazar una invitación",
    responses=_errores(
        _401="Sin sesión.", _403="La ONG no tiene una invitación pendiente en este consorcio.",
        _404="El consorcio no existe.",
        _409="Ventana cerrada (la invitación venció), consorcio disuelto o la ONG ya está en otro consorcio.",
        _422="acepta ausente o no booleano.",
    ),
)
def api_responder(
    consorcio_id: Id,
    body: RespuestaIn,
    user: Usuario = Depends(require_role(Rol.ONG)),
    db: Session = Depends(get_db),
):
    """Solo la ONG invitada responde. Al aceptar pasa a ser miembro y ve las ofertas de los demás miembros."""
    c = _consorcio_visible(db, user, consorcio_id)
    svc_consorcios.responder(db, consorcio=c, ong=user.ong, acepta=body.acepta)
    return _consorcio_out(db, c)


@router.post(
    "/consorcios/{consorcio_id}/salida",
    status_code=204,
    summary="Salir de un consorcio",
    responses=_errores(
        _401="Sin sesión.", _403="Solo las ONGs.", _404="El consorcio no existe.",
        _409="Ventana cerrada, consorcio disuelto, la ONG no es miembro o es la líder (tiene que disolver).",
    ),
)
def api_salir(
    consorcio_id: Id,
    user: Usuario = Depends(require_role(Rol.ONG)),
    db: Session = Depends(get_db),
):
    """Un miembro aceptado que no es líder sale; la fila queda como SALIO para la trazabilidad."""
    c = _consorcio_visible(db, user, consorcio_id)
    svc_consorcios.salir(db, consorcio=c, ong=user.ong)


@router.delete(
    "/consorcios/{consorcio_id}",
    status_code=204,
    summary="Disolver un consorcio",
    responses=_errores(
        _401="Sin sesión.", _403="Solo la ONG líder disuelve.", _404="El consorcio no existe.",
        _409="Ventana cerrada o consorcio ya disuelto.",
    ),
)
def api_disolver(
    consorcio_id: Id,
    user: Usuario = Depends(require_role(Rol.ONG)),
    db: Session = Depends(get_db),
):
    """Marca el consorcio como disuelto (no se borra) y deja libres a sus miembros."""
    c = _consorcio_visible(db, user, consorcio_id)
    svc_consorcios.disolver(db, consorcio=c, lider=user.ong)


@router.get(
    "/ongs",
    response_model=list[OngOut],
    summary="ONGs que se pueden invitar a un consorcio",
    responses=_errores(
        _401="Sin sesión.", _403="Solo las ONGs.", _404="La emergencia indicada no existe o no es visible.",
    ),
)
def api_listar_ongs(
    emergencia_id: Annotated[int | None, Query(ge=1, le=2**31 - 1)] = None,
    user: Usuario = Depends(require_role(Rol.ONG)),
    db: Session = Depends(get_db),
):
    """ONGs con CUIT (las que se pueden adjudicar), menos la propia y, si se indica `emergencia_id`, las que ya
    están en un consorcio de esa emergencia."""
    if emergencia_id is not None:
        _require_visible(db, user, emergencia_id)
    ongs = db.scalars(select(Ong).where(Ong.cuit.is_not(None), Ong.id != user.ong_id).order_by(Ong.nombre)).all()
    if emergencia_id is not None:
        ongs = [o for o in ongs if svc_consorcios.consorcio_de(db, emergencia_id, o.id) is None]
    return ongs
