
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings, get_settings
from app.core.deps import require_role
from app.core.security import hash_password, verify_password
from app.core.labels import ROL_LABEL, TIPO_LABEL
from app.db import get_db
from app.models import Emergencia, EstadoEmergencia, Oferta, OfertaItem, Ong, Rol, Usuario
from app.integrations.nacional import (
    NacionalClient,
    NacionalError,
    NacionalLoginEndpointMissing,
    NacionalLoginRejected,
    get_nacional,
)
from app.models import Emergencia, Oferta, Rol, Usuario
from app.schemas.api import (
    AdjudicarIn,
    DecisionIn,
    EmergenciaOut,
    LoginIn,
    LoteOut,
    OfertaIn,
    OfertaItemOut,
    OfertaOut,
    PublicarIn,
    RegisterOngIn,
    TokenOut,
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
from app.services.ciclo import CicloError, adjudicar, decidir
from app.services.ofertas import OfertaError, publicar_oferta
from app.services.lotes import (
    LoteError,
    PublicacionError,
    agregar_lote,
    borrar_lote,
    publicar_convocatoria,
)

router = APIRouter(prefix="/api")
national_auth_router = APIRouter()


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


def _token_response(user: Usuario, access_token: str) -> TokenOut:
    return TokenOut(access_token=access_token, user=user)


@national_auth_router.post("/login", response_model=TokenOut)
@router.post("/auth/login", response_model=TokenOut)
def api_login(
    body: LoginIn,
    db: Session = Depends(get_db),
    nacional: NacionalClient = Depends(get_nacional),
):
    user = _authenticate_user(db, body.username, body.password)
    try:
        token = nacional.login(user.username, body.password)["access_token"]
    except NacionalLoginRejected as exc:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos") from exc
    except NacionalLoginEndpointMissing as exc:
        raise HTTPException(
            status_code=502,
            detail="La API Nacional desplegada no tiene disponible POST /login; hay que actualizar su despliegue.",
        ) from exc
    except NacionalError as exc:
        raise HTTPException(status_code=503, detail=NACIONAL_CAIDO) from exc
    return _token_response(user, token)


def _authenticate_user(db: Session, username: str, password: str) -> Usuario:
    user = db.scalar(select(Usuario).where(Usuario.username == username.strip()))
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    return user


@national_auth_router.post("/ongs", response_model=TokenOut, status_code=201)
@router.post("/auth/register-ong", response_model=TokenOut, status_code=201)
def api_register_ong(
    body: RegisterOngIn,
    db: Session = Depends(get_db),
    nacional: NacionalClient = Depends(get_nacional),
):
    username = body.username
    ong_name = body.ong_nombre
    cuit = body.cuit
    if db.scalar(select(Usuario.id).where(Usuario.username == username)):
        raise HTTPException(status_code=409, detail="El nombre de usuario ya está registrado")
    if db.scalar(select(Ong.id).where(Ong.nombre == ong_name)):
        raise HTTPException(status_code=409, detail="La ONG ya está registrada")
    if cuit and db.scalar(select(Ong.id).where(Ong.cuit == cuit)):
        raise HTTPException(status_code=409, detail="El CUIT ya está registrado")
    if not cuit:
        raise HTTPException(status_code=422, detail="El CUIT es obligatorio para registrar la ONG en el Sistema Nacional")

    try:
        token = nacional.registrar_ong(body.model_dump())["access_token"]
    except NacionalError as exc:
        raise HTTPException(status_code=503, detail=NACIONAL_CAIDO) from exc

    try:
        ong = Ong(nombre=ong_name, cuit=cuit)
        db.add(ong)
        db.flush()
        user = Usuario(
            username=username,
            password_hash=hash_password(body.password),
            nombre=body.nombre,
            rol=Rol.ONG,
            ong_id=ong.id,
        )
        db.add(user)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="La ONG o el usuario ya están registrados") from exc
    db.refresh(user)
    return _token_response(user, token)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def api_logout():
    # JWT is stateless; clients discard their access token on logout.
    return None


@router.get("/auth/me", response_model=UsuarioOut)
def api_me(user: Usuario = Depends(require_role())):
    return user


@router.get("/emergencias", response_model=list[EmergenciaOut])
def api_listar(
    user: Usuario = Depends(require_role(Rol.MUNICIPIO, Rol.COORDINADOR, Rol.AUDITOR)),
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


@router.get("/emergencias/convocatorias/abiertas", response_model=list[EmergenciaOut])
def api_listar_convocatorias_abiertas(
    user: Usuario = Depends(require_role(Rol.ONG)),
    db: Session = Depends(get_db),
):
    convocatorias = [
        emergencia
        for emergencia in emergencias_visibles(db, user)
        if emergencia.estado is EstadoEmergencia.CONVOCATORIA
    ]
    out: list[EmergenciaOut] = []
    for emergencia in convocatorias:
        full = _load_emergencia(db, emergencia.id)
        if full:
            out.append(_emergencia_out(full))
    return out


@router.get("/emergencias/{emergencia_id}", response_model=EmergenciaOut)
def api_detalle(
    emergencia_id: int,
    user: Usuario = Depends(require_role()),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    return _detalle_out(_require_visible(db, user, emergencia_id), user, settings)


def _detalle_out(emergencia: Emergencia, user: Usuario, settings: Settings) -> EmergenciaOut:
    out = _emergencia_out(emergencia)
    out.tarea_bonita = tarea_ong_en_bonita(settings, emergencia, user)
    if emergencia.evaluacion and user.rol is not Rol.ONG:
        out.evaluacion = Evaluacion.model_validate_json(emergencia.evaluacion)
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
    return _detalle_out(_load_emergencia(db, emergencia_id), user, settings)


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
    return _detalle_out(_load_emergencia(db, emergencia_id), user, settings)


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
    user: Usuario = Depends(require_role(Rol.ONG)),
    db: Session = Depends(get_db),
):
    emergencia = _load_emergencia(db, emergencia_id)
    if emergencia is None:
        raise HTTPException(status_code=404, detail="Emergencia no encontrada")
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
