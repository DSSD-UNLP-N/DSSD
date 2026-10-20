
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.core.deps import require_role
from app.core.security import verify_password
from app.core.labels import ROL_LABEL, TIPO_LABEL
from app.db import get_db
from app.integrations.nacional import NacionalClient, NacionalError, get_nacional
from app.models import Emergencia, Notificacion, Oferta, Rol, Usuario
from app.schemas.api import (
    AdjudicarIn,
    AltaOngIn,
    AltaOngOut,
    DecisionIn,
    EmergenciaOut,
    LoginIn,
    LoteOut,
    NotificacionOut,
    OfertaIn,
    OfertaItemOut,
    OfertaOut,
    PublicarIn,
    TipoRecursoOut,
    UsuarioOut,
)
from app.schemas.emergencias import EmergenciaIn
from app.schemas.evaluacion import Evaluacion
from app.schemas.lotes import LoteIn, PublicacionIn
from app.seed import DEMO_PASSWORD, DEMO_USERS
from app.services.emergencias import (
    AltaEmergenciaError,
    emergencia_visible,
    emergencias_visibles,
    registrar_emergencia,
    tarea_ong_en_bonita,
)
from app.services.alta_ong import AltaOngError, DatosAlta, alta_ong
from app.services.ciclo import CicloError, adjudicar, decidir
from app.services.ejecucion import finalizar, monitorear, resumen, validar_cierre
from app.services.ofertas import OfertaError, publicar_oferta
from app.services.lotes import (
    LoteError,
    PublicacionError,
    agregar_lote,
    borrar_lote,
    publicar_convocatoria,
)

router = APIRouter(prefix="/api")


def _load_emergencia(db: Session, emergencia_id: int) -> Emergencia | None:
    return db.scalar(
        select(Emergencia)
        .where(Emergencia.id == emergencia_id)
        .options(selectinload(Emergencia.lotes), selectinload(Emergencia.municipio))
    )


def _emergencia_out(e: Emergencia) -> EmergenciaOut:
    return EmergenciaOut(
        id=e.id,
        tipo=e.tipo,
        nivel_gravedad=e.nivel_gravedad,
        zona_afectada=e.zona_afectada,
        descripcion=e.descripcion,
        estado=e.estado,
        bonita_case_id=e.bonita_case_id,
        ventana_ofertas_fin=e.ventana_ofertas_fin,
        creada_en=e.creada_en,
        municipio_nombre=e.municipio.nombre if e.municipio else None,
        municipio_provincia=e.municipio.provincia if e.municipio else None,
        lotes=[LoteOut.model_validate(l) for l in e.lotes],
    )


def _require_visible(db: Session, user: Usuario, emergencia_id: int) -> Emergencia:
    emergencia = _load_emergencia(db, emergencia_id)
    if emergencia is None or emergencia_visible(db, user, emergencia_id) is None:
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
    return {"tipos": TIPO_LABEL, "roles": ROL_LABEL, "demo": demo}


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
    items = emergencias_visibles(db, user)
    out: list[EmergenciaOut] = []
    for e in items:
        full = _load_emergencia(db, e.id)
        if full:
            out.append(_emergencia_out(full))
    return out


@router.post("/emergencias", response_model=EmergenciaOut, status_code=201)
def api_crear(
    body: EmergenciaIn,
    user: Usuario = Depends(require_role(Rol.MUNICIPIO)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        emergencia = registrar_emergencia(db, settings, operador=user, **body.model_dump())
    except AltaEmergenciaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    full = _load_emergencia(db, emergencia.id)
    return _emergencia_out(full or emergencia)


@router.get("/emergencias/{emergencia_id}", response_model=EmergenciaOut)
def api_detalle(
    emergencia_id: int,
    user: Usuario = Depends(require_role()),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    return _detalle_out(db, _require_visible(db, user, emergencia_id), user, settings)


def _detalle_out(db: Session, emergencia: Emergencia, user: Usuario, settings: Settings) -> EmergenciaOut:
    out = _emergencia_out(emergencia)
    out.tarea_bonita = tarea_ong_en_bonita(settings, emergencia, user)
    if emergencia.evaluacion and user.rol is not Rol.ONG:
        out.evaluacion = Evaluacion.model_validate_json(emergencia.evaluacion)
    out.ejecucion = resumen(db, emergencia, user)
    return out


@router.post("/emergencias/{emergencia_id}/decision", response_model=EmergenciaOut)
def api_decidir(
    emergencia_id: int,
    body: DecisionIn,
    user: Usuario = Depends(require_role(Rol.COORDINADOR)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    nacional: NacionalClient = Depends(get_nacional),
):
    """Con la cobertura incompleta: PARCIAL sigue con lo reservado; REFORMULAR libera todo y empieza otra ronda."""
    emergencia = _require_visible(db, user, emergencia_id)
    try:
        decidir(db, settings, nacional, emergencia=emergencia, coordinador=user, decision=body.decision)
    except CicloError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except NacionalError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=NACIONAL_CAIDO) from exc
    return _detalle_out(db, _load_emergencia(db, emergencia_id), user, settings)


@router.post("/emergencias/{emergencia_id}/adjudicar", response_model=EmergenciaOut)
def api_adjudicar(
    emergencia_id: int,
    body: AdjudicarIn,
    user: Usuario = Depends(require_role(Rol.MUNICIPIO)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """El Municipio elige entre las ofertas validadas. Bonita confirma lo elegido y libera lo demás."""
    emergencia = _require_visible(db, user, emergencia_id)
    try:
        adjudicar(settings, emergencia=emergencia, municipal=user, cuits=body.cuits)
    except CicloError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return _detalle_out(db, _load_emergencia(db, emergencia_id), user, settings)


def _avanzar(db: Session, emergencia_id: int, user: Usuario, settings: Settings, paso) -> EmergenciaOut:
    """Un paso de la ejecución: lo hace `paso(emergencia)`; si algo falla no queda nada a medias."""
    emergencia = _require_visible(db, user, emergencia_id)
    try:
        paso(emergencia)
    except CicloError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return _detalle_out(db, _load_emergencia(db, emergencia_id), user, settings)


@router.post("/emergencias/{emergencia_id}/monitorear", response_model=EmergenciaOut)
def api_monitorear(
    emergencia_id: int,
    user: Usuario = Depends(require_role(Rol.COORDINADOR)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """El Coordinador empieza a monitorear la ejecución; desde ahí las ONGs pueden marcar su actividad finalizada."""
    return _avanzar(db, emergencia_id, user, settings,
                    lambda e: monitorear(db, settings, emergencia=e, coordinador=user))


@router.post("/emergencias/{emergencia_id}/finalizar", response_model=EmergenciaOut)
def api_finalizar(
    emergencia_id: int,
    user: Usuario = Depends(require_role(Rol.ONG)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Una ONG adjudicada informa que terminó su actividad."""
    return _avanzar(db, emergencia_id, user, settings,
                    lambda e: finalizar(db, settings, emergencia=e, usuario=user))


@router.post("/emergencias/{emergencia_id}/validar-cierre", response_model=EmergenciaOut)
def api_validar_cierre(
    emergencia_id: int,
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
    notificacion_id: int,
    user: Usuario = Depends(require_role(Rol.ONG)),
    db: Session = Depends(get_db),
):
    aviso = db.get(Notificacion, notificacion_id)
    if aviso is None or aviso.ong_id != user.ong_id:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    aviso.leida = True
    db.commit()
    return aviso


NACIONAL_CAIDO = "El Sistema Nacional no responde; probá de nuevo en un momento."


@router.get("/tipos-recurso", response_model=list[TipoRecursoOut])
def api_tipos_recurso(
    user: Usuario = Depends(require_role()),
    nacional: NacionalClient = Depends(get_nacional),
):
    """Catálogo de recursos del Sistema Nacional, para elegir el tipo de cada lote."""
    try:
        return nacional.tipos_recurso()
    except NacionalError as exc:
        raise HTTPException(status_code=503, detail=NACIONAL_CAIDO) from exc


@router.get("/ongs/alta/tipos-recurso", response_model=list[TipoRecursoOut])
def api_alta_tipos_recurso(nacional: NacionalClient = Depends(get_nacional)):
    """Catálogo para la pantalla pública de alta de ONG (sin sesión)."""
    try:
        return nacional.tipos_recurso()
    except NacionalError as exc:
        raise HTTPException(status_code=503, detail=NACIONAL_CAIDO) from exc


@router.post("/ongs/alta", response_model=AltaOngOut, status_code=201)
def api_alta_ong(
    body: AltaOngIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    nacional: NacionalClient = Depends(get_nacional),
):
    """Alta pública de una ONG en Bonita, el Sistema Nacional y la app."""
    datos = DatosAlta(
        ong_nombre=body.ong_nombre, cuit=body.cuit, nombre=body.nombre, username=body.username,
        password=body.password, rubros=[r.model_dump() for r in body.rubros],
    )
    try:
        usuario = alta_ong(db, settings, nacional, datos)
    except AltaOngError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return AltaOngOut(ong_nombre=usuario.ong.nombre, cuit=usuario.ong.cuit, username=usuario.username,
                      rubros=body.rubros)


@router.post("/emergencias/{emergencia_id}/lotes", response_model=LoteOut, status_code=201)
def api_crear_lote(
    emergencia_id: int,
    body: LoteIn,
    user: Usuario = Depends(require_role(Rol.COORDINADOR)),
    db: Session = Depends(get_db),
    nacional: NacionalClient = Depends(get_nacional),
):
    emergencia = _require_visible(db, user, emergencia_id)
    try:
        lote = agregar_lote(db, emergencia, body, nacional)
    except LoteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NacionalError as exc:
        raise HTTPException(status_code=503, detail=NACIONAL_CAIDO) from exc
    return lote


@router.delete("/emergencias/{emergencia_id}/lotes/{lote_id}", status_code=204)
def api_borrar_lote(
    emergencia_id: int,
    lote_id: int,
    user: Usuario = Depends(require_role(Rol.COORDINADOR)),
    db: Session = Depends(get_db),
):
    emergencia = _require_visible(db, user, emergencia_id)
    try:
        borrar_lote(db, emergencia, lote_id)
    except LoteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/emergencias/{emergencia_id}/publicar", response_model=EmergenciaOut)
def api_publicar(
    emergencia_id: int,
    body: PublicarIn,
    user: Usuario = Depends(require_role(Rol.COORDINADOR)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    emergencia = _require_visible(db, user, emergencia_id)
    try:
        publicada = publicar_convocatoria(
            db,
            settings,
            emergencia=emergencia,
            coordinador=user,
            ventana_fin=PublicacionIn(ventana_fin=body.ventana_fin).ventana_fin,
        )
    except PublicacionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    full = _load_emergencia(db, publicada.id)
    return _emergencia_out(full or publicada)


def _oferta_out(o: Oferta) -> OfertaOut:
    items = [OfertaItemOut.model_validate(i) for i in o.items if i.version == o.version_actual]
    return OfertaOut(
        id=o.id,
        emergencia_id=o.emergencia_id,
        ong_id=o.ong_id,
        ong_nombre=o.ong.nombre,
        version_actual=o.version_actual,
        items=items,
        retirada=not items,
        estado=o.estado,
    )


@router.get("/emergencias/{emergencia_id}/ofertas", response_model=list[OfertaOut])
def api_listar_ofertas(
    emergencia_id: int,
    user: Usuario = Depends(require_role()),
    db: Session = Depends(get_db),
):
    _require_visible(db, user, emergencia_id)
    query = select(Oferta).where(Oferta.emergencia_id == emergencia_id)
    if user.rol is Rol.ONG:  # una ONG no ve las ofertas de las demás
        query = query.where(Oferta.ong_id == user.ong_id)
    ofertas = db.scalars(query.options(selectinload(Oferta.items), selectinload(Oferta.ong))).all()
    return [_oferta_out(o) for o in ofertas]


@router.post("/emergencias/{emergencia_id}/ofertas", response_model=OfertaOut, status_code=201)
def api_crear_oferta(
    emergencia_id: int,
    body: OfertaIn,
    user: Usuario = Depends(require_role(Rol.ONG)),
    db: Session = Depends(get_db),
    nacional: NacionalClient = Depends(get_nacional),
):
    """Cada envío es la oferta completa: una versión nueva con todos sus ítems (T-12)."""
    emergencia = _require_visible(db, user, emergencia_id)
    try:
        oferta = publicar_oferta(db, nacional, emergencia=emergencia, ong=user.ong, items=body.items)
    except OfertaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NacionalError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=NACIONAL_CAIDO) from exc
    return _oferta_out(oferta)
