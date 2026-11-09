"""La documentación versionada no puede citar archivos que no estén en git.

Cada vez que un `.md` o un comentario remite a un archivo que solo existe en la PC de alguien (o que se borró), quien clona el repo
se queda sin la explicación. Mira solo lo que `git ls-files` devuelve, así que falla igual en tu PC y en CI aunque el archivo esté en disco.
"""
import re
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
# Documentos de planificación de un momento puntual: nombran archivos que después cambiaron de lugar.
EXCLUIDOS = ("docs/superpowers/",)
# Rutas que se nombran a propósito aunque git no las guarde (carpetas generadas).
PERMITIDOS = {"scripts/capturas/"}
EXTENSIONES = r"md|html|bos|py|sh|json|yml|yaml|xml|tsx|ts"


@pytest.fixture(scope="module")
def versionados() -> set[str]:
    try:
        salida = subprocess.run(["git", "ls-files", "-z"], cwd=RAIZ, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("sin git no se puede saber qué está versionado")
    return {p for p in salida.split("\0") if p}


def _existe(ref: str, desde: str, versionados: set[str]) -> bool:
    es_carpeta = ref.endswith("/")
    ref = ref.rstrip("/")
    carpeta = str(Path(desde).parent).replace("\\", "/")
    candidatos = {ref, ref if carpeta == "." else f"{carpeta}/{ref}"}
    for archivo in versionados:
        if es_carpeta:
            if any(archivo.startswith(c + "/") for c in candidatos) or f"/{ref}/" in f"/{archivo}":
                return True
        elif archivo in candidatos or archivo.endswith("/" + ref):
            return True
    return False


def _rutas_en_markdown(texto: str) -> set[str]:
    texto = re.sub(r"```.*?```", "", texto, flags=re.S)  # los bloques de comandos usan archivos locales (.env, .venv)
    rutas = set()
    for token in re.findall(r"`([^`\s]+)`", texto):
        if re.search(r"[<>*{}$|\\:]", token):
            continue
        if re.fullmatch(rf"[\w.\-]+(/[\w.\-]+)*/[\w\-]+\.({EXTENSIONES})", token) or re.fullmatch(rf"[\w\-]+\.({EXTENSIONES})", token) \
                or re.fullmatch(r"[\w.\-]+(/[\w.\-]+)*/", token):
            rutas.add(token)
    return rutas


def _documentos_en_codigo(texto: str) -> set[str]:
    return set(re.findall(r"(?<![\w/.\-])((?:[\w\-]+/)*[\w\-]+\.(?:md|html))\b", texto))


def test_los_md_no_citan_archivos_que_no_estan_en_git(versionados):
    faltan = []
    for archivo in sorted(versionados):
        if not archivo.endswith(".md") or archivo.startswith(EXCLUIDOS):
            continue
        texto = (RAIZ / archivo).read_text(encoding="utf-8")
        faltan += [f"{archivo}: `{r}`" for r in sorted(_rutas_en_markdown(texto)) if r not in PERMITIDOS and not _existe(r, archivo, versionados)]
    assert not faltan, "Citan archivos que no están versionados:\n" + "\n".join(faltan)


def test_los_comentarios_del_codigo_no_citan_documentos_que_no_estan_en_git(versionados):
    faltan = []
    for archivo in sorted(versionados):
        if not re.search(r"\.(py|sh|ya?ml|example|toml)$", archivo) or archivo.startswith(EXCLUIDOS):
            continue
        try:
            texto = (RAIZ / archivo).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        faltan += [f"{archivo}: {r}" for r in sorted(_documentos_en_codigo(texto)) if not _existe(r, archivo, versionados)]
    assert not faltan, "Citan documentos que no están versionados:\n" + "\n".join(faltan)
