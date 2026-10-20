"""El `.bos` que se entrega (entrega-3/entrega42_local.bos): los conectores que llaman a la API Nacional entran con JWT.

No hay forma de correr Bonita en CI, así que se revisa el export versionado: la cadena `loginNacional -> llamada con
Authorization: Bearer` completa en cada tarea de servicio que toca a Nacional, la tarea estándar y lo que hace
`bonita/scripts/preparar_entorno.py` para apuntarlo a la nube. Que el motor la ejecute bien lo prueban los escenarios con Bonita real.
"""
import re
import sys
import zipfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
BOS = RAIZ / "entrega-3" / "entrega42_local.bos"
sys.path.insert(0, str(RAIZ / "bonita" / "scripts"))

import agregar_conector_cierre  # noqa: E402
import agregar_login_nacional  # noqa: E402
import preparar_entorno  # noqa: E402

pytestmark = pytest.mark.skipif(not BOS.exists(), reason="no está entrega-3/entrega42_local.bos")


@pytest.fixture(scope="module")
def jwt_bos() -> Path:
    return BOS


def _proc(bos: Path) -> str:
    with zipfile.ZipFile(bos) as z:
        return z.read(next(n for n in z.namelist() if n.endswith(".proc"))).decode("utf-8")


def _tareas_de_servicio(proc: str) -> dict[str, list[str]]:
    """nombre de la tarea -> texto de cada uno de sus conectores, en orden."""
    tareas = {}
    for m in re.finditer(r'<elements xmi:type="process:ServiceTask"[^>]*?\bname="([^"]+)"', proc):
        cuerpo = proc[m.start():agregar_conector_cierre.bloque(proc, m.start(), "elements")]
        conectores, pos = [], 0
        while (c := cuerpo.find("<connectors ", pos)) != -1:
            fin = agregar_conector_cierre.bloque(cuerpo, c, "connectors")
            conectores.append(cuerpo[c:fin])
            pos = fin
        tareas[m.group(1)] = conectores
    return tareas


def _nombre(conector: str) -> str:
    return re.search(r'\bname="([^"]+)"', conector).group(1)


def test_las_tareas_que_llaman_a_nacional_empiezan_con_el_login(jwt_bos):
    con_nacional = {t: cs for t, cs in _tareas_de_servicio(_proc(jwt_bos)).items() if any(":8002/" in c for c in cs)}
    assert set(con_nacional) == set(agregar_login_nacional.TAREAS)
    for tarea, conectores in con_nacional.items():
        assert _nombre(conectores[0]) == "loginNacional", tarea
        assert "http://localhost:8002/login" in conectores[0]


def test_cada_llamada_a_nacional_manda_el_token_del_login(jwt_bos):
    for tarea, conectores in _tareas_de_servicio(_proc(jwt_bos)).items():
        for c in conectores:
            if ":8002/" in c and _nombre(c) != "loginNacional":
                assert 'content="Authorization"' in c, (tarea, _nombre(c))
                assert "Bearer" in c and "access_token" in c and 'name="nacionalLoginJson"' in c, (tarea, _nombre(c))


def test_el_login_guarda_la_respuesta_en_una_variable_que_existe_una_sola_vez(jwt_bos):
    proc = _proc(jwt_bos)
    assert len(re.findall(r'<data [^>]*\bname="nacionalLoginJson"', proc)) == 1
    for conectores in _tareas_de_servicio(proc).values():
        for c in conectores:
            if _nombre(c) == "loginNacional":
                salida = re.search(r"<outputs .*?</outputs>", c, re.S).group(0)
                assert 'name="nacionalLoginJson"' in salida and 'name="bodyAsString"' in salida


def test_los_ids_siguen_siendo_unicos(jwt_bos):
    ids = re.findall(r'xmi:id="([^"]+)"', _proc(jwt_bos))
    repetidos = {i for i in ids if ids.count(i) > 1}
    assert not repetidos, sorted(repetidos)[:5]


def test_las_llamadas_a_la_app_no_cambian(jwt_bos):
    """La app se sigue llamando con X-Api-Key, sin token de Nacional."""
    for conectores in _tareas_de_servicio(_proc(jwt_bos)).values():
        for c in conectores:
            if ":8001/" in c:
                assert "Bearer" not in c


def test_aplicarlo_dos_veces_avisa(jwt_bos, tmp_path):
    with pytest.raises(ValueError):
        agregar_login_nacional.main(str(jwt_bos), str(tmp_path / "otra.bos"))


def test_confirmar_finalizacion_es_tarea_estandar(jwt_bos):
    tarea = re.search(r'<elements xmi:type="process:Task"[^>]*name="Confirmar Finalizacion de Actividades"[^>]*>', _proc(jwt_bos))
    assert tarea and 'type="PARALLEL"' not in tarea.group(0)


def test_preparar_entorno_apunta_a_la_nube_con_otra_clave(jwt_bos):
    nube = preparar_entorno.nacional(_proc(jwt_bos), "https://api.ejemplo.com/", "clave-de-la-nube")
    assert "localhost:8002" not in nube and "change-me" not in nube
    assert nube.count("&quot;https://api.ejemplo.com/") == 6  # 3 logins + evaluar, resolver y cerrar
    assert nube.count("password: &quot;clave-de-la-nube&quot;") == 3
    assert nube.count("localhost:8001") == _proc(jwt_bos).count("localhost:8001")  # la app no cambia


def test_preparar_entorno_no_se_aplica_dos_veces(jwt_bos):
    nube = preparar_entorno.nacional(_proc(jwt_bos), "https://api.ejemplo.com", "otra-clave")
    with pytest.raises(ValueError):
        preparar_entorno.nacional(nube, "https://otra.com", "x")


def test_el_bos_de_la_nube_es_el_local_apuntando_a_render():
    nube_bos = BOS.with_name("entrega42_nube.bos")
    if not nube_bos.exists():
        pytest.skip("no está entrega42_nube.bos")
    local, nube = _proc(BOS), _proc(nube_bos)
    assert "localhost:8002" not in nube and "change-me" not in nube
    assert nube.count("&quot;https://rescuesync-nacional.onrender.com/") == 6
    assert re.sub(r"https://rescuesync-nacional\.onrender\.com|http://localhost:8002", "X", re.sub(r"password: &quot;[^&]+&quot;", "P", nube)) == \
        re.sub(r"https://rescuesync-nacional\.onrender\.com|http://localhost:8002", "X", re.sub(r"password: &quot;[^&]+&quot;", "P", local))
