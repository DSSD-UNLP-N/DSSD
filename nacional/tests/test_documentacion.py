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
