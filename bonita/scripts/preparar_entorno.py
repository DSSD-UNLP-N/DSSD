"""Deja el .bos listo para un entorno, sin abrir Studio: la tarea estándar (WP4) y la URL y clave de la API Nacional (WP12).

Los conectores de Bonita tienen escrita la dirección de la API Nacional (`http://localhost:8002`) y la clave de la cuenta
`bonita-service` en el `loginNacional`. Este script cambia solo eso y deja el resto igual:

  --estandar          «Confirmar Finalizacion de Actividades» deja de ser multi-instancia (saca el aviso rojo de Studio).
  --nacional URL      reemplaza `http://localhost:8002` en los 6 conectores que llaman a Nacional (3 logins, evaluaciones,
                      adjudicaciones/resolucion, cierres/lote). Ej.: https://rescuesync-nacional.onrender.com
  clave               si hay --nacional, la clave de `bonita-service` se toma de la variable NACIONAL_BONITA_PASSWORD
                      (así no queda en el historial ni en el repositorio).

No modifica el archivo de entrada. `entrega-3/entrega42_nube.bos` ya está generado y versionado (con la clave de la API de la demo); este script sirve para rehacerlo si cambia la URL o la clave.

    python bonita/scripts/preparar_entorno.py <bos con los conectores de cierre y el login> entrega-3/entrega42_local.bos --estandar
    NACIONAL_BONITA_PASSWORD=... python bonita/scripts/preparar_entorno.py entrega-3/entrega42_local.bos entrega-3/entrega42_nube.bos \\
        --nacional https://rescuesync-nacional.onrender.com
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
from xml.dom import minidom

LOCAL = "http://localhost:8002"
CLAVE_LOCAL = "change-me"
TAREA = "Confirmar Finalizacion de Actividades"


def estandar(x: str) -> str:
    m = re.search(rf'(<elements xmi:type="process:Task"[^>]*name="{re.escape(TAREA)}"[^>]*?) type="PARALLEL"', x)
    if not m:
        if re.search(rf'name="{re.escape(TAREA)}"', x):
            return x  # ya es estándar
        raise ValueError(f"No está la tarea «{TAREA}»")
    return x[:m.start()] + m.group(1) + x[m.end():]


def nacional(x: str, url: str, clave: str) -> str:
    destino = url.rstrip("/")
    if x.count(f"&quot;{LOCAL}/") != 6:
        raise ValueError(f"Se esperaban 6 conectores con {LOCAL} y hay {x.count(f'&quot;{LOCAL}/')}: ¿ya está cambiado?")
    x = x.replace(f"&quot;{LOCAL}/", f"&quot;{destino}/")
    viejo = f"password: &quot;{CLAVE_LOCAL}&quot;"
    if x.count(viejo) != 3:
        raise ValueError(f"Se esperaban 3 logins con la clave de ejemplo y hay {x.count(viejo)}")
    return x.replace(viejo, f"password: &quot;{clave}&quot;")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada")
    ap.add_argument("salida")
    ap.add_argument("--estandar", action="store_true")
    ap.add_argument("--nacional", metavar="URL")
    args = ap.parse_args()
    if not (args.estandar or args.nacional):
        sys.exit("Nada para hacer: pasá --estandar y/o --nacional URL")
    clave = os.environ.get("NACIONAL_BONITA_PASSWORD", "")
    if args.nacional and (not clave or clave == CLAVE_LOCAL or any(c in clave for c in '"&<>\\$')):
        sys.exit("Con --nacional hace falta NACIONAL_BONITA_PASSWORD (la clave de bonita-service en esa API, sin comillas ni & < > \\ $)")

    with zipfile.ZipFile(args.entrada) as zin:
        nombre = next(n for n in zin.namelist() if n.endswith(".proc"))
        proc = zin.read(nombre).decode("utf-8")
        if args.estandar:
            proc = estandar(proc)
        if args.nacional:
            proc = nacional(proc, args.nacional, clave)
        minidom.parseString(proc.encode("utf-8"))  # que siga siendo XML válido
        with zipfile.ZipFile(args.salida, "w") as zout:
            for info in zin.infolist():
                datos = proc.encode("utf-8") if info.filename == nombre else zin.read(info.filename)
                zout.writestr(info, datos, compress_type=info.compress_type)
    print(f"Listo: {args.salida}")
    if args.estandar:
        print(f"  «{TAREA}»: tarea estándar")
    if args.nacional:
        print(f"  API Nacional: {args.nacional} (6 conectores) y clave de bonita-service cambiada (3 logins)")


if __name__ == "__main__":
    main()
