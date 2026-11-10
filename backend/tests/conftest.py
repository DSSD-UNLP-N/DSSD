import os
from datetime import datetime, timezone
from urllib.parse import urlparse

# Antes de importar la app: que ningún test toque dev.db ni un Postgres real.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SESSION_SECRET"] = "test-secret"
os.environ["BONITA_BASE_URL"] = "http://bonita.test/bonita"  # nunca pegarle a un Bonita real en los tests
os.environ["NACIONAL_BASE_URL"] = "http://nacional.test"  # nunca pegarle a una API Nacional real en los tests
os.environ["SHOW_DEMO_USERS"] = "false"  # que el .env local de cada uno no cambie lo que ven los tests

import pytest  # noqa: E402
import responses  # noqa: E402
import requests  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core import security  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.integrations.nacional import NacionalError, get_nacional, olvidar_tokens  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Emergencia, EstadoOferta, Gravedad, Lote, Municipio, Oferta, OfertaItem, Ong,
)
from app.seed import DEMO_PASSWORD, seed  # noqa: E402

PASSWORD = DEMO_PASSWORD
BASE = get_settings().bonita_base_url
CASE = 5151
CLAVE = {"X-Api-Key": "rescuesync-dev-key"}  # la que manda Bonita a /api/bonita/...
CRUZ_ROJA, BOMBEROS = "30-54666544-5", "30-68522415-9"  # 4 y 6 paramédicos en el FakeNacional
PARAMEDICOS = {"recurso": "Paramédico", "tipo_recurso": "PARAMEDICO", "cantidad": 10, "unidad": "personas"}

# El PBKDF2 real tarda ~0,3 s por hash y `seeded` lo paga 6 veces por test (y cada login una más): era la mayor
# parte del tiempo de la suite. El hash guarda sus iteraciones, así que verificar también usa este valor chico.
security._ITERATIONS = 1_000


@pytest.fixture(autouse=True)
def _nacional_sin_sesion():
    olvidar_tokens()


@pytest.fixture(autouse=True)
def _bonita_sin_espera(monkeypatch):
    """Los reintentos de get_human_tasks no deben hacer esperar a los tests."""
    from app.integrations import bonita as bonita_mod

    monkeypatch.setattr(bonita_mod.time, "sleep", lambda s: None)


@pytest.fixture
def session_factory():
    """BD en memoria, con las tablas creadas desde los modelos y una sola conexión compartida."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def db(session_factory):
    with session_factory() as session:
        yield session


@pytest.fixture
def seeded(session_factory):
    seed(session_factory)
    return session_factory


class FakeBonita:
    """Sustituye a Bonita en las lecturas del dashboard; el cliente HTTP real se prueba en test_bonita_client.py."""

    def __init__(self):
        self.nodos = {}  # case_id -> lista de registros de archivedFlowNode
        self.falla = False  # True: cada llamada lanza requests.ConnectionError

    def login(self, *args, **kwargs):
        if self.falla:
            raise requests.ConnectionError("Bonita caído (simulado)")

    def get_archived_flow_nodes(self, case_id):
        if self.falla:
            raise requests.ConnectionError("Bonita caído (simulado)")
        return self.nodos.get(case_id, [])


@pytest.fixture
def fake_bonita():
    return FakeBonita()


class FakeNacional:
    """Sustituye al Sistema Nacional en los tests; el cliente HTTP real se prueba en test_nacional_client.py."""

    TIPOS = [
        {"codigo": "PARAMEDICO", "nombre": "Paramédico", "categoria": "PERSONAL", "unidad": "personas",
         "certificacion_requerida": "SALUD_PREHOSP"},
        {"codigo": "RACION_ALIMENTO", "nombre": "Ración de alimento", "categoria": "INSUMO", "unidad": "raciones",
         "certificacion_requerida": None},
        {"codigo": "AGUA_POTABLE", "nombre": "Agua potable", "categoria": "INSUMO", "unidad": "litros",
         "certificacion_requerida": None},
    ]

    def __init__(self):
        self.caido = False
        # Disponible por (CUIT de la ONG, tipo de recurso): lo mismo que cargan los seeds.
        self.inventario = {
            ("30-54666544-5", "PARAMEDICO"): 4,
            ("30-54666544-5", "RACION_ALIMENTO"): 5000,
            ("30-68522415-9", "PARAMEDICO"): 6,
        }
        self.comprometido = {}  # (CUIT, tipo) -> bloqueado por reservas; no cuenta en `inventario` (disponible)
        self.validaciones = []  # (gravedad, items) de cada llamada a validar()
        self.liberadas = []  # referencia de cada llamada a liberar()
        self.ongs_registradas = []  # kwargs de cada llamada a registrar_ong()
        self.inventarios = {}  # cuit -> items declarados con declarar_inventario()
        self.falla_registro = None  # NacionalError a lanzar en registrar_ong()
        self.falla_inventario = None  # NacionalError a lanzar en declarar_inventario()

    def _verificar(self):
        if self.caido:
            raise NacionalError("Sistema Nacional caído (simulado)")

    def registrar_ong(self, *, ong_nombre, cuit, nombre, username, password):
        self._verificar()
        if self.falla_registro:
            raise self.falla_registro
        self.ongs_registradas.append({"ong_nombre": ong_nombre, "cuit": cuit, "nombre": nombre,
                                      "username": username, "password": password})

    def declarar_inventario(self, cuit, items):
        """Como la API real: upsert por tipo, 404 si el tipo no existe y 409 si queda por debajo de lo comprometido."""
        self._verificar()
        if self.falla_inventario:
            raise self.falla_inventario
        codigos = {t["codigo"] for t in self.TIPOS}
        for i in items:
            if i["tipo_recurso"] not in codigos:
                raise NacionalError(f"Tipo de recurso inexistente: {i['tipo_recurso']}", 404)
            comprometido = self.comprometido.get((cuit, i["tipo_recurso"]), 0)
            if i["cantidad_total"] < comprometido:
                raise NacionalError(f"{i['tipo_recurso']}: no se puede declarar {i['cantidad_total']}, "
                                    f"hay {comprometido} comprometidos", 409)
        for i in items:
            clave = (cuit, i["tipo_recurso"])
            self.inventario[clave] = i["cantidad_total"] - self.comprometido.get(clave, 0)
        self.inventarios[cuit] = items
        return items

    def ficha_ong(self, cuit):
        """GET /ongs/{cuit}: lo que hay en `inventario` (disponible) y `comprometido`, por tipo; 404 si no la conoce."""
        self._verificar()
        if not any(c == cuit for c, _ in self.inventario):
            raise NacionalError("ONG no registrada", 404)
        tipos = {t["codigo"]: t for t in self.TIPOS}
        inventario = []
        for (c, codigo), disponible in sorted(self.inventario.items()):
            if c != cuit:
                continue
            comprometido = self.comprometido.get((c, codigo), 0)
            inventario.append({
                "tipo_recurso": codigo, "nombre": tipos[codigo]["nombre"], "unidad": tipos[codigo]["unidad"],
                "cantidad_total": disponible + comprometido, "cantidad_comprometida": comprometido,
                "disponible": disponible, "riesgo_permitido": "CRITICO",
            })
        return {"cuit": cuit, "nombre": "ONG de prueba", "estado": "HABILITADA", "inventario": inventario,
                "certificaciones": [{"codigo": "SALUD_PREHOSP", "nombre": "Atención de salud prehospitalaria",
                                     "riesgo_max": "CRITICO", "vence_el": "2027-10-01", "vigente": True}]}

    def liberar(self, referencia):
        self._verificar()
        self.liberadas.append(referencia)
        return {"referencia": referencia, "estado": "LIBERADA", "liberado": []}

    def tipos_recurso(self):
        self._verificar()
        return self.TIPOS

    def validar(self, gravedad, items):
        """Como la API real: suma lo pedido por (ONG, recurso) y compara con lo disponible."""
        self._verificar()
        self.validaciones.append((gravedad, items))
        pedido = {}
        for i in items:
            clave = (i["cuit"], i["tipo_recurso"])
            pedido[clave] = pedido.get(clave, 0) + i["cantidad"]
        tipos = {t["codigo"]: t for t in self.TIPOS}
        resultados = [
            {"cuit": cuit, "tipo_recurso": codigo, "nombre_recurso": tipos[codigo]["nombre"],
             "unidad": tipos[codigo]["unidad"], "solicitado": n, "disponible": self.inventario.get((cuit, codigo), 0),
             "alcanza": n <= self.inventario.get((cuit, codigo), 0), "nivel": "PLENA",
             "riesgo_permitido": "CRITICO", "asignacion_sugerida": "PRINCIPAL", "observaciones": []}
            for (cuit, codigo), n in pedido.items()
        ]
        return {"alcanza_todo": all(r["alcanza"] for r in resultados), "resultados": resultados}


@pytest.fixture
def nacional():
    return FakeNacional()


@pytest.fixture
def client(seeded, nacional):
    def _get_db():
        with seeded() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_nacional] = lambda: nacional
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def login(client):
    def _login(username: str):
        r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        assert r.status_code == 200, f"login de {username} falló: {r.status_code}"
        return client

    return _login


# --- datos de prueba compartidos ---

def crear_emergencia(seeded, estado, *, lotes=(PARAMEDICOS,), ofertas=((CRUZ_ROJA, 4), (BOMBEROS, 2)),
                     estado_oferta=EstadoOferta.PRESENTADA, **campos):
    """Emergencia del municipio del seed con sus lotes y una oferta (versión 1, sobre el primer lote) por cada
    (CUIT, cantidad). `campos` pisa cualquier columna de la emergencia. Devuelve (emergencia_id, [lote_id, ...])."""
    with seeded() as s:
        if "municipio_id" not in campos:
            campos["municipio_id"] = s.query(Municipio).one().id
        datos = {"tipo": "inundacion", "nivel_gravedad": Gravedad.ALTO, "zona_afectada": "Centro", "descripcion": "d",
                 "bonita_case_id": CASE, **campos}
        e = Emergencia(estado=estado, **datos)
        e.lotes = [Lote(**lote) for lote in lotes]
        s.add(e)
        s.flush()
        for cuit, cantidad in ofertas:
            o = Oferta(emergencia_id=e.id, ong_id=s.query(Ong).filter_by(cuit=cuit).one().id, estado=estado_oferta)
            o.items = [OfertaItem(version=1, lote_id=e.lotes[0].id, recurso=e.lotes[0].recurso, cantidad=cantidad)]
            s.add(o)
        s.commit()
        return e.id, [lote.id for lote in e.lotes]


def cambiar_emergencia(seeded, emergencia_id, **cambios):
    with seeded() as s:
        e = s.get(Emergencia, emergencia_id)
        for k, v in cambios.items():
            setattr(e, k, v)
        s.commit()


def estado_de(seeded, emergencia_id):
    with seeded() as s:
        return s.get(Emergencia, emergencia_id).estado


def sin_zona(delta):
    """Ahora + delta en UTC sin zona, como guarda publicar_convocatoria la ventana (SQLite descarta la zona)."""
    return datetime.now(timezone.utc).replace(tzinfo=None) + delta


def mock_login(token="tok", status=204, **kw):
    """Un POST /loginservice de Bonita. Con 204 deja la cookie del token CSRF (token=None: sin cookie); otro status falla."""
    if status == 204 and token:
        kw["headers"] = {"Set-Cookie": f"X-Bonita-API-Token={token}; Path=/"}
    responses.add(responses.POST, f"{BASE}/loginservice", status=status, **kw)


def mock_ejecutar(tarea_id):
    """complete_task_as_self: el id del usuario de la sesión, asignarle la tarea y ejecutarla."""
    responses.add(responses.GET, f"{BASE}/API/system/session/unusedid", json={"user_id": "77"})
    responses.add(responses.PUT, f"{BASE}/API/bpm/userTask/{tarea_id}", status=200)
    responses.add(responses.POST, f"{BASE}/API/bpm/userTask/{tarea_id}/execution", status=200)


def mock_tarea(nombre, tarea_id="9"):
    """Bonita con `nombre` como única tarea pendiente del caso CASE, lista para asignarla, setear variables y completarla."""
    mock_login("tok-admin")
    mock_login("tok-usuario")
    responses.add(responses.GET, f"{BASE}/API/bpm/humanTask", json=[{"id": tarea_id, "displayName": nombre}])
    responses.add(responses.PUT, f"{BASE}/API/bpm/caseVariable/{CASE}/decisionCoordinador", status=200)
    responses.add(responses.PUT, f"{BASE}/API/bpm/caseVariable/{CASE}/ongsAdjudicadas", status=200)
    mock_ejecutar(tarea_id)


def tarea_completada(tarea_id="9"):
    return any(urlparse(c.request.url).path.endswith(f"/userTask/{tarea_id}/execution") for c in responses.calls)


def mock_bonita_alta_ong(usuario_existente=None):
    """Lo que el alta de una ONG le pide a Bonita: buscar/crear el usuario, el grupo, el rol y la membresía."""
    mock_login()
    responses.add(responses.GET, f"{BASE}/API/identity/user", json=usuario_existente or [])
    responses.add(responses.POST, f"{BASE}/API/identity/user", json={"id": "77"})
    responses.add(responses.GET, f"{BASE}/API/identity/group", json=[{"id": "5"}])
    responses.add(responses.GET, f"{BASE}/API/identity/role", json=[{"id": "3"}])
    responses.add(responses.POST, f"{BASE}/API/identity/membership", status=200, json={})
    responses.add(responses.DELETE, f"{BASE}/API/identity/user/77", status=200)


def body_alta_ong(**kw):
    """Cuerpo de POST /api/ongs/alta para una ONG nueva (Techo Digno)."""
    base = dict(ong_nombre="Techo Digno", cuit="30-71234567-8", nombre="Ana Paz", username="ong.techo",
                password="secreto123",
                rubros=[{"tipo_recurso": "PARAMEDICO", "cantidad_total": 4},
                        {"tipo_recurso": "RACION_ALIMENTO", "cantidad_total": 0}])
    base.update(kw)
    return base
