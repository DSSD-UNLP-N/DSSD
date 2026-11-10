
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.core.deps import require_role
from app.core.security import verify_password
from app.core.labels import ROL_LABEL, TIPO_LABEL
from app.db import get_db
from app.integrations.nacional import NacionalClient, get_nacional
from app.models import Emergencia, Notificacion, Oferta, Rol, Usuario
from app.schemas.api import (
    AdjudicarIn,
    AltaOngIn,
    AltaOngOut,
    DecisionIn,
    EmergenciaIn,
    EmergenciaOut,
    InventarioIn,
    InventarioOngOut,
    LoginIn,
    LoteIn,
    LoteOut,
    NotificacionOut,
    OfertaIn,
    OfertaOut,
    PublicarIn,
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
from app.services.ofertas import publicar_oferta
from app.services.lotes import agregar_lote, borrar_lote, publicar_convocatoria

router = APIRouter(prefix="/api")


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
    emergencia_id: int,
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
    emergencia_id: int,
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
    emergencia_id: int,
    body: AdjudicarIn,
    user: Usuario = Depends(require_role(Rol.MUNICIPIO)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """El Municipio elige entre las ofertas validadas. Bonita confirma lo elegido y libera lo demás."""
    emergencia = _require_visible(db, user, emergencia_id)
    adjudicar(settings, emergencia=emergencia, municipal=user, cuits=body.cuits)
    return _detalle_out(db, emergencia, user, settings)


def _avanzar(db: Session, emergencia_id: int, user: Usuario, settings: Settings, paso) -> EmergenciaOut:
    """Un paso de la ejecución: lo hace `paso(emergencia)`; si algo falla no queda nada a medias."""
    emergencia = _require_visible(db, user, emergencia_id)
    paso(emergencia)
    return _detalle_out(db, emergencia, user, settings)


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
    emergencia_id: int,
    body: LoteIn,
    user: Usuario = Depends(require_role(Rol.COORDINADOR)),
    db: Session = Depends(get_db),
    nacional: NacionalClient = Depends(get_nacional),
):
    emergencia = _require_visible(db, user, emergencia_id)
    return agregar_lote(db, emergencia, body, nacional)


@router.delete("/emergencias/{emergencia_id}/lotes/{lote_id}", status_code=204)
def api_borrar_lote(
    emergencia_id: int,
    lote_id: int,
    user: Usuario = Depends(require_role(Rol.COORDINADOR)),
    db: Session = Depends(get_db),
):
    emergencia = _require_visible(db, user, emergencia_id)
    borrar_lote(db, emergencia, lote_id)


@router.post("/emergencias/{emergencia_id}/publicar", response_model=EmergenciaOut)
def api_publicar(
    emergencia_id: int,
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
    return db.scalars(query.options(selectinload(Oferta.items), selectinload(Oferta.ong))).all()


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
    return publicar_oferta(db, nacional, emergencia=emergencia, ong=user.ong, items=body.items)
