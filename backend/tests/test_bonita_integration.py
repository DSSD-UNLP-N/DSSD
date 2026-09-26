"""Prueba real contra el Bonita de Studio. Apagada por defecto.

Correr con Studio ejecutado y el proceso desplegado:
    RUN_BONITA_INTEGRATION=1 pytest -m integration
Crea un caso de prueba (se borra al próximo Ejecutar/Desplegar de Studio).
"""
import os
from datetime import datetime, timedelta

import pytest

from app.core.config import Settings
from app.integrations.bonita import BonitaClient
from app.services.lotes import publicar_en_bonita

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_BONITA_INTEGRATION") != "1",
                       reason="definir RUN_BONITA_INTEGRATION=1 (requiere Studio corriendo)"),
]


@pytest.fixture(scope="module")
def settings():
    # conftest.py apunta BONITA_BASE_URL a un host falso para el resto de los tests.
    return Settings(_env_file=None,
                    bonita_base_url=os.getenv("BONITA_INTEGRATION_URL", "http://localhost:8080/bonita"))


@pytest.fixture(scope="module")
def bonita(settings):
    s = settings
    c = BonitaClient(s.bonita_base_url, s.bonita_timeout_seconds)
    c.login(s.bonita_username, s.bonita_password)
    c.process_id = c.resolve_process_id(s.bonita_process_name, s.bonita_process_version)
    return c


def test_instanciar_arranca_en_registrar_emergencia_y_permite_pisar_la_ventana(bonita):
    ventana = (datetime.now().astimezone() + timedelta(hours=72)).isoformat(timespec="seconds")
    case_id = bonita.start_case(bonita.process_id, {
        "emergenciaId": 999, "municipioId": 1, "nivelGravedad": "ALTO", "ventanaOfertasISO": ventana})
    tareas = bonita.get_human_tasks(case_id)
    assert any(t["displayName"].startswith("Registrar Emergencia") for t in tareas)

    real = (datetime.now().astimezone() + timedelta(hours=1)).isoformat(timespec="seconds")
    bonita.set_case_variable(case_id, "ventanaOfertasISO", real, "java.lang.String")


def test_publicar_deja_el_caso_esperando_ofertas_con_la_ventana_elegida(bonita, settings):
    """T-10 contra Bonita real: Registrar → (Revisar + ventana + Publicar) → Cargar Ofertas."""
    provisoria = (datetime.now().astimezone() + timedelta(hours=72)).isoformat(timespec="seconds")
    case_id = bonita.start_case(bonita.process_id, {
        "emergenciaId": 998, "municipioId": 1, "nivelGravedad": "ALTO", "ventanaOfertasISO": provisoria})

    municipio = BonitaClient(settings.bonita_base_url, settings.bonita_timeout_seconds)
    municipio.login("operador.municipal", settings.bonita_test_password)
    municipio.complete_task_as_self(bonita.wait_for_task(case_id, "Registrar Emergencia")["id"])

    ventana = datetime.now().astimezone() + timedelta(hours=2)
    publicar_en_bonita(settings, case_id, ventana, "coordinador.regional")

    tarea = bonita.wait_for_task(case_id, "Cargar Ofertas de Ayuda")
    assert tarea is not None, "tras publicar, el caso tiene que quedar esperando las ofertas"

    variables = {v["name"]: v["value"] for v in bonita._request(
        "GET", "/API/bpm/caseVariable", params={"f": f"case_id={case_id}", "p": 0, "c": 20}).json()}
    assert variables["ventanaOfertasISO"] == ventana.isoformat(timespec="seconds")
