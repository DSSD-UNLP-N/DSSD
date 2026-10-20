"""Muestra a qué URLs llama cada tarea de servicio de un .bos (sirve para confirmar si es el de la nube o el local).

    python bonita/scripts/ver_conectores.py entrega-3/entrega42_nube.bos
"""
from __future__ import annotations

import html
import re
import sys
import zipfile

URL = re.compile(r"https?://(?!www\.(?:bonitasoft|omg)|www\.eclipse)[^/&\"\s]+/[A-Za-z0-9_/\-{}.$]*")


def conectores(bos: str) -> dict[str, list[str]]:
    with zipfile.ZipFile(bos) as z:
        proc = z.read(next(n for n in z.namelist() if n.endswith(".proc"))).decode("utf-8")
    tareas = re.finditer(r'<elements xmi:type="process:ServiceTask"[^>]*name="([^"]+)"(.*?)</elements>', proc, re.S)
    return {t.group(1): sorted(set(URL.findall(html.unescape(t.group(2))))) for t in tareas}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    for tarea, urls in conectores(sys.argv[1]).items():
        print(tarea)
        for u in urls:
            print("   ", u)
