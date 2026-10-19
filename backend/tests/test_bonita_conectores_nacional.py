"""Los conectores de Bonita que llaman a la API Nacional entran con JWT.

No hay forma de correr Bonita en CI, así que se arma el .bos con los scripts de `bonita/scripts` (partiendo del export
versionado) y se revisa que la cadena `loginNacional -> llamada con Authorization: Bearer` esté completa en cada
tarea de servicio que toca a Nacional. Que el motor la ejecute bien lo prueban los escenarios con Bonita real.
"""
import re
import sys
import zipfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
BASE = RAIZ / "entrega-3" / "entrega41_20261017_1311.bos"
sys.path.insert(0, str(RAIZ / "bonita" / "scripts"))

import agregar_conector_cierre  # noqa: E402
import agregar_login_nacional  # noqa: E402

pytestmark = pytest.mark.skipif(not BASE.exists(), reason="no está el export de entrega-3")


@pytest.fixture(scope="module")
def jwt_bos(tmp_path_factory) -> Path:
    carpeta = tmp_path_factory.mktemp("bos")
    cierre, jwt = carpeta / "cierre.bos", carpeta / "jwt.bos"
    agregar_conector_cierre.main(str(BASE), str(cierre))
    agregar_login_nacional.main(str(cierre), str(jwt))
    return jwt


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
