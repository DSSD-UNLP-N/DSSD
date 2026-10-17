"""Agrega los conectores de "Liberar Recursos y Notificar Cierre" a un export de Bonita (.bos), sin abrir Studio.

Clona los dos conectores REST que ya tiene "Notificar Adjudicacion y Registrar Compromiso Nacional" y cambia solo
lo que difiere:

  cerrarAdjudicaciones   POST http://localhost:8002/cierres/lote   {cierres: [{cuit, referencia}]} de las ONGs adjudicadas
  avisarCierre           POST http://localhost:8001/api/bonita/emergencias/${emergenciaId}/eventos   {tipo: CIERRE, cuits}

No modifica el archivo de entrada: escribe uno nuevo para importarlo en Studio (Archivo > Importar) y volver a
ejecutar. Si el servicio ya tiene conectores, no hace nada.

    python bonita/scripts/agregar_conector_cierre.py entrega-3/entrega41_20261017_1311.bos entrega-3/entrega41_cierre.bos
"""
from __future__ import annotations

import base64
import re
import sys
import uuid
import zipfile
from xml.dom import minidom

ORIGEN = "Notificar Adjudicacion y Registrar Compromiso Nacional"
DESTINO = "Liberar Recursos y Notificar Cierre"

BODY_CERRAR = """def ev = new groovy.json.JsonSlurper().parseText(evaluacionJson)
def elegidas = new groovy.json.JsonSlurper().parseText(ongsAdjudicadas)
groovy.json.JsonOutput.toJson([
\tcierres: ev.ongs.findAll { it.referencia && elegidas.contains(it.cuit) }.collect { [cuit: it.cuit, referencia: it.referencia] }
])"""

BODY_AVISAR = """def elegidas = new groovy.json.JsonSlurper().parseText(ongsAdjudicadas)
groovy.json.JsonOutput.toJson([
\ttipo: "CIERRE",
\tcuits: elegidas
])"""


def atributo(texto: str) -> str:
    """Escapa un texto para un atributo XML con el mismo formato que usa Studio (saltos como &#xD;&#xA;)."""
    return (texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            .replace("\t", "&#x9;").replace("\r\n", "&#xD;&#xA;").replace("\n", "&#xD;&#xA;"))


def id_nuevo() -> str:
    return "_" + base64.urlsafe_b64encode(uuid.uuid4().bytes).decode().rstrip("=")


def bloque(x: str, inicio: int, tag: str) -> int:
    """Posición donde termina el elemento <tag> que empieza en `inicio` (cuenta los anidados del mismo tag)."""
    profundidad = 0
    for m in re.finditer(rf"<(/?){tag}\b[^>]*?(/?)>", x[inicio:]):
        cierre, auto = m.group(1), m.group(2)
        if cierre:
            profundidad -= 1
            if profundidad == 0:
                return inicio + m.end()
        elif not auto:
            profundidad += 1
        elif profundidad == 0:
            return inicio + m.end()
    raise ValueError(f"No se encontró el cierre de <{tag}>")


def conector(x: str, desde: int, hasta: int, nombre: str) -> tuple[int, int]:
    m = re.search(rf'<connectors [^>]*\bname="{re.escape(nombre)}"', x[desde:hasta])
    if not m:
        raise ValueError(f"No está el conector {nombre} en «{ORIGEN}»")
    ini = desde + m.start()
    return ini, bloque(x, ini, "connectors")


def clonar(texto: str, nombre_viejo: str, nombre_nuevo: str) -> str:
    """Mismo conector con ids nuevos (Studio no tolera dos elementos con el mismo xmi:id) y otro nombre."""
    for viejo in set(re.findall(r'xmi:id="([^"]+)"', texto)):
        texto = texto.replace(f'"{viejo}"', f'"{id_nuevo()}"')
    return texto.replace(f'"{nombre_viejo}"', f'"{nombre_nuevo}"')


def cambiar_parametro(texto: str, clave: str, nuevo_contenido: str) -> str:
    """Pone `nuevo_contenido` (ya escapado) en el atributo content de la expresión del parámetro `clave`."""
    m = re.search(rf'key="{clave}">\s*<expression [^>]*?\bcontent="', texto)
    if not m:
        raise ValueError(f"No está el parámetro {clave}")
    ini = m.end()
    fin = texto.index('"', ini)
    return texto[:ini] + nuevo_contenido + texto[fin:]


def agregar(proc: str) -> str:
    t_ini = proc.index(f'name="{DESTINO}"')
    t_ini = proc.rindex("<elements ", 0, t_ini)
    t_fin = bloque(proc, t_ini, "elements")
    if "<connectors " in proc[t_ini:t_fin]:
        raise ValueError(f"«{DESTINO}» ya tiene conectores")
    o_ini = proc.rindex("<elements ", 0, proc.index(f'name="{ORIGEN}"'))
    o_fin = bloque(proc, o_ini, "elements")

    a_ini, a_fin = conector(proc, o_ini, o_fin, "resolverReservas")
    b_ini, b_fin = conector(proc, o_ini, o_fin, "avisarAdjudicacion")

    cerrar = clonar(proc[a_ini:a_fin], "resolverReservas", "cerrarAdjudicaciones")
    cerrar = cerrar.replace("http://localhost:8002/adjudicaciones/resolucion", "http://localhost:8002/cierres/lote")
    cerrar = cambiar_parametro(cerrar, "body", atributo(BODY_CERRAR))

    avisar = clonar(proc[b_ini:b_fin], "avisarAdjudicacion", "avisarCierre")
    avisar = cambiar_parametro(avisar, "body", atributo(BODY_AVISAR))
    # El aviso solo lee ongsAdjudicadas: se quita la referencia a evaluacionJson que arrastra el clon.
    avisar = re.sub(r'\s*<referencedElements [^>]*\bname="evaluacionJson"[^>]*/>', "", avisar)

    # Los conectores van después de stepSummary, como en el resto de las tareas de servicio.
    paso = re.search(r"<stepSummary [^>]*/>", proc[t_ini:t_fin])
    corte = t_ini + paso.end()
    sangria = "\r\n          "
    return proc[:corte] + sangria + cerrar + sangria + avisar + proc[corte:]


def main(entrada: str, salida: str) -> None:
    with zipfile.ZipFile(entrada) as zin:
        nombre = next(n for n in zin.namelist() if n.endswith(".proc"))
        proc = zin.read(nombre).decode("utf-8")
        nuevo = agregar(proc)
        minidom.parseString(nuevo.encode("utf-8"))  # que siga siendo XML válido
        with zipfile.ZipFile(salida, "w") as zout:
            for info in zin.infolist():
                datos = nuevo.encode("utf-8") if info.filename == nombre else zin.read(info.filename)
                zout.writestr(info, datos, compress_type=info.compress_type)
    print(f"Listo: {salida}")
    print(f"  «{DESTINO}» ahora tiene los conectores cerrarAdjudicaciones y avisarCierre.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
