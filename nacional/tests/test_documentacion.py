"""La tabla de endpoints del README tiene que ser la de la API: si se agrega, saca o renombra una ruta sin tocar el README, falla."""
import re
from pathlib import Path

from app.main import app

README = Path(__file__).resolve().parents[1] / "README.md"
SIN_DOCUMENTAR = {"/health"}  # el README lo nombra aparte, no en la tabla


def _ruta(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path.split("?")[0])


def test_la_tabla_de_endpoints_del_readme_coincide_con_la_api():
    en_readme = {
        (metodo, _ruta(ruta))
        for metodo, ruta in re.findall(r"^\| (GET|POST|PUT|PATCH|DELETE) \| `([^`]+)`", README.read_text(encoding="utf-8"), re.M)
    }
    en_api = {
        (metodo.upper(), _ruta(ruta))
        for ruta, operaciones in app.openapi()["paths"].items()
        if ruta not in SIN_DOCUMENTAR
        for metodo in operaciones
    }
    assert en_readme == en_api, (
        f"Falta en el README: {sorted(en_api - en_readme)}. Sobra en el README: {sorted(en_readme - en_api)}."
    )


def _con_ejemplos():
    import inspect

    from pydantic import BaseModel

    from app import schemas

    return [m for _, m in inspect.getmembers(schemas, inspect.isclass)
            if issubclass(m, BaseModel) and m.__module__ == schemas.__name__ and "examples" in (m.model_config.get("json_schema_extra") or {})]


def test_los_ejemplos_de_swagger_son_validos_para_su_modelo():
    modelos = _con_ejemplos()
    assert len(modelos) >= 20
    for modelo in modelos:
        for ejemplo in modelo.model_config["json_schema_extra"]["examples"]:
            modelo.model_validate(ejemplo)


def test_todo_endpoint_documenta_sus_errores_y_tiene_descripcion():
    for ruta, operaciones in app.openapi()["paths"].items():
        for metodo, op in operaciones.items():
            assert op.get("description"), (metodo, ruta)
            if "security" in op:
                assert "401" in op["responses"], (metodo, ruta)


def test_la_copia_del_swagger_en_entrega_3_esta_al_dia():
    import json

    copia = json.loads((README.parents[1] / "entrega-3" / "swagger-api-nacional.json").read_text(encoding="utf-8"))
    copia.pop("servers", None)
    assert copia == json.loads(json.dumps(app.openapi())), "Regenerar con: python nacional/scripts/exportar_openapi.py"
