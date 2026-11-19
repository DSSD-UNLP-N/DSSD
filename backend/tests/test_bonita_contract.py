"""La app y el modelo de Bonita deben hablar el mismo contrato.

Lee entrega-3/entrega42_local.bos (el export vigente de Studio). Si alguien cambia el contrato
en Studio y no la app (o al revés), estos tests fallan.
"""
import re
import zipfile
from pathlib import Path

import pytest

from app.core.config import Settings
from app.integrations.bonita import CONTRACT_INPUTS

BOS = Path(__file__).resolve().parents[2] / "entrega-3" / "entrega42_local.bos"

pytestmark = pytest.mark.skipif(not BOS.exists(), reason="no está entrega-3/entrega42_local.bos")


@pytest.fixture(scope="module")
def proc() -> str:
    with zipfile.ZipFile(BOS) as z:
        name = next(n for n in z.namelist() if n.endswith(".proc"))
        return z.read(name).decode("utf8", "replace")


def test_inputs_del_contrato_son_los_que_manda_la_app(proc):
    en_modelo = re.findall(r'<inputs [^>]*name="([^"]*)"', proc)
    assert set(en_modelo) == set(CONTRACT_INPUTS)


def test_cada_input_del_contrato_esta_atado_a_una_variable(proc):
    atadas = set(re.findall(
        r'<data [^>]*name="([^"]*)"[^>]*>\s*<defaultValue[^>]*type="TYPE_CONTRACT_INPUT"', proc))
    assert set(CONTRACT_INPUTS) <= atadas


def test_el_timer_usa_la_variable_de_la_ventana(proc):
    timer = re.search(r'BoundaryTimerEvent.*?<condition [^>]*content="([^"]*)"', proc, re.S)
    assert timer, "no hay boundary timer en el modelo"
    assert "ventanaOfertasISO" in timer.group(1)


def test_nombre_y_version_del_proceso_coinciden_con_la_configuracion(proc):
    s = Settings(_env_file=None)
    pool = re.search(r'xmi:type="process:Pool"[^>]*\bname="([^"]*)"', proc)
    assert pool and pool.group(1) == s.bonita_process_name
    assert f'version="{s.bonita_process_version}"' in proc


def test_variables_que_la_app_va_a_setear_existen(proc):
    variables = set(re.findall(r'<data [^>]*name="([^"]*)"', proc))
    assert {"ventanaOfertasISO", "ongsAdjudicadas", "ofertasJson"} <= variables


def test_tareas_que_la_app_avanza_existen(proc):
    for tarea in ("Registrar Emergencia", "Revisar Informacion y Generar Lotes de Necesidades",
                  "Publicar Convocatoria y Notificar a la Red de ONGs", "Cargar Ofertas de Ayuda"):
        assert f'name="{tarea}"' in proc, f"falta la tarea '{tarea}' en el modelo"
