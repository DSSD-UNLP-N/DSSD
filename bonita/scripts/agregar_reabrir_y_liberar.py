"""Agrega al proceso la liberación de reservas al descartar la cobertura parcial y la decisión REABRIR, sin abrir Studio.

Antes:   XOR «Curso de accion» ─ REFORMULAR → «Revisar Informacion y Generar Lotes de Necesidades»
                               └ PARCIAL    → «Adjudicar Ofertas»
Después: XOR «Curso de accion» ─ REFORMULAR o REABRIR → [servicio] «Liberar Reservas de la Ronda» → XOR «Reformular o reabrir»
                               │                            ├ REFORMULAR → «Revisar Informacion y Generar Lotes…» (igual que antes)
                               │                            └ REABRIR    → «Publicar Convocatoria…» (mismos lotes, ventana nueva)
                               └ PARCIAL    → «Adjudicar Ofertas» (sin cambios)

La tarea de servicio clona «Notificar Adjudicacion y Registrar Compromiso Nacional» (login JWT + POST /adjudicaciones/resolucion)
y cambia el body: no confirma nada y libera todas las reservas de la ronda (las referencias salen de evaluacionJson). Así la
app no llama nunca a la API Nacional (pauta de la cátedra: solo Bonita orquesta validación, compromiso y liberación).

No modifica el archivo de entrada: escribe uno nuevo para importarlo en Studio como proyecto nuevo. Si ya tiene la tarea, no hace nada.

    python bonita/scripts/agregar_reabrir_y_liberar.py entrega-3/entrega42_local.bos salida.bos
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path
from xml.dom import minidom

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agregar_conector_cierre import atributo, bloque, clonar, cambiar_parametro, id_nuevo  # noqa: E402

MOLDE = "Notificar Adjudicacion y Registrar Compromiso Nacional"
XOR_CURSO = "Curso de accion"
REVISAR = "Revisar Informacion y Generar Lotes de Necesidades"
PUBLICAR = "Publicar Convocatoria y Notificar a la Red de ONGs"
LANE_NACIONAL = " Entidad Nacional / Sistema RescueSync"
LIBERAR = "Liberar Reservas de la Ronda"
XOR_NUEVO = "Reformular o reabrir"

BODY_LIBERAR = """def ev = new groovy.json.JsonSlurper().parseText(evaluacionJson)
groovy.json.JsonOutput.toJson([
\tconfirmar: [],
\tliberar: ev.ongs.findAll { it.referencia }.collect { it.referencia }
])"""

COND = 'decisionCoordinador == &quot;{}&quot;'
NL = "\r\n"


def elemento(x: str, nombre: str) -> tuple[int, int]:
    """Bloque <elements …name="nombre"…> (proceso)."""
    ini = x.rindex("<elements ", 0, x.index(f'name="{nombre}"'))
    return ini, bloque(x, ini, "elements")


def por_id(x: str, tag: str, xmi_id: str) -> tuple[int, int]:
    ini = x.rindex(f"<{tag} ", 0, x.index(f'xmi:id="{xmi_id}"'))
    return ini, bloque(x, ini, tag)


def id_de(x: str, ini: int) -> str:
    return re.search(r'xmi:id="([^"]+)"', x[ini:]).group(1)


def shape_de(x: str, elemento_id: str) -> tuple[int, int]:
    ini = x.rindex("<children ", 0, x.index(f'element="{elemento_id}"'))
    return ini, bloque(x, ini, "children")


def cabecera(texto: str, **attrs: str) -> str:
    """Cambia (o agrega) atributos de la primera etiqueta del bloque."""
    fin = texto.index(">")
    tag = texto[:fin]
    for clave, valor in attrs.items():
        clave = clave.replace("_", ":") if clave == "xmi_id" else clave
        if re.search(rf'\s{clave}="[^"]*"', tag):
            tag = re.sub(rf'(\s{clave}=")[^"]*(")', rf"\g<1>{valor}\g<2>", tag, count=1)
        else:
            tag += f' {clave}="{valor}"'
    return tag + texto[fin:]


def bounds(texto: str, x: int, y: int, w: int | None = None, h: int | None = None) -> str:
    m = list(re.finditer(r'<layoutConstraint xmi:type="notation:Bounds"[^>]*/>', texto))[-1]
    attrs = f'x="{x}" y="{y}"' + (f' width="{w}" height="{h}"' if w else "")
    nuevo = re.sub(r'\s(x|y|width|height)="[^"]*"', "", m.group(0)).replace("/>", f" {attrs}/>")
    return texto[:m.start()] + nuevo + texto[m.end():]


def sin_bendpoints(texto: str) -> str:
    return re.sub(r'points="[^"]*"', 'points="[0, 0, 0, 0]$[0, 0, 0, 0]"', texto)


def condicion(texto: str, contenido: str) -> str:
    return re.sub(r'(<condition [^>]*?\bcontent=")[^"]*(")', rf"\g<1>{contenido}\g<2>", texto, count=1)


def agregar(x: str) -> str:
    if f'name="{LIBERAR}"' in x:
        raise ValueError(f"El proceso ya tiene «{LIBERAR}»")
    ids = {k: id_nuevo() for k in ("L", "X2", "Fa", "Fb", "Fc", "SL", "SX2", "EA", "EB", "EC")}

    xor_ini, xor_fin = elemento(x, XOR_CURSO)
    xor_id = id_de(x, xor_ini)
    rev_ini, _ = elemento(x, REVISAR)
    rev_id = id_de(x, rev_ini)
    pub_ini, _ = elemento(x, PUBLICAR)
    pub_id = id_de(x, pub_ini)

    # Flujo XOR «Curso de accion» → Revisar (REFORMULAR): pasa a ir a la tarea de servicio.
    f_ini = re.search(rf'<connections [^>]*target="{rev_id}" source="{xor_id}"', x).start()
    f_fin = bloque(x, f_ini, "connections")
    f_orig = x[f_ini:f_fin]
    f_id = id_de(f_orig, 0)
    plano_ini = re.search(r'<connections [^>]*>\s*<decisionTable [^>]*/>\s*<condition [^>]*content=""', x).start()
    plano = x[plano_ini:bloque(x, plano_ini, "connections")]

    # --- semántica: tarea de servicio y XOR nuevos -----------------------------------------------------------------
    m_ini, m_fin = elemento(x, MOLDE)
    liberar = clonar(x[m_ini:m_fin], "resolverReservas", "liberarReservas")
    a = re.search(r'<connectors [^>]*name="avisarAdjudicacion"', liberar).start()
    liberar = liberar[:a] + liberar[bloque(liberar, a, "connectors"):]
    c = re.search(r'<connectors [^>]*name="liberarReservas"', liberar).start()
    c_fin = bloque(liberar, c, "connectors")
    con = cambiar_parametro(liberar[c:c_fin], "body", atributo(BODY_LIBERAR))
    con = re.sub(r'\s*<referencedElements [^>]*\bname="ongsAdjudicadas"[^>]*/>', "", con)
    liberar = liberar[:c] + con + liberar[c_fin:]
    liberar = cabecera(liberar, xmi_id=ids["L"], name=LIBERAR, outgoing=ids["Fa"], incoming=f_id)

    xor2 = clonar(x[xor_ini:xor_fin], XOR_CURSO, XOR_NUEVO)
    xor2 = cabecera(xor2, xmi_id=ids["X2"], outgoing=f'{ids["Fb"]} {ids["Fc"]}', incoming=ids["Fa"])

    # --- flujos ------------------------------------------------------------------------------------------------------
    plano = re.sub(r'^(<connections [^>]*?)\sname="[^"]*"', r"\g<1>", plano)  # el molde puede tener nombre
    fa = cabecera(clonar(plano, "", ""), xmi_id=ids["Fa"], source=ids["L"], target=ids["X2"])
    fb = cabecera(clonar(f_orig, "", ""), xmi_id=ids["Fb"], name="Reformular lotes", source=ids["X2"], target=rev_id)
    fc = cabecera(clonar(f_orig, "", ""), xmi_id=ids["Fc"], name="Reabrir convocatoria", source=ids["X2"], target=pub_id)
    fc = condicion(fc, COND.format("REABRIR"))
    f_nuevo = cabecera(f_orig, name="No - Reformular o reabrir", target=ids["L"])
    f_nuevo = condicion(f_nuevo, COND.format("REFORMULAR") + " || " + COND.format("REABRIR"))

    # --- notación: formas y aristas ---------------------------------------------------------------------------------
    s_ini, s_fin = shape_de(x, id_de(x, m_ini))
    shape_l = cabecera(clonar(x[s_ini:s_fin], "", ""), xmi_id=ids["SL"], element=ids["L"])
    shape_l = bounds(shape_l, 1040, 160, 150, 64)
    sx_ini, sx_fin = shape_de(x, xor_id)
    shape_x = cabecera(clonar(x[sx_ini:sx_fin], "", ""), xmi_id=ids["SX2"], element=ids["X2"])
    shape_x = bounds(shape_x, 950, 172)
    shape_xor = id_de(x, sx_ini)
    shape_rev = id_de(x, shape_de(x, rev_id)[0])
    shape_pub = id_de(x, shape_de(x, pub_id)[0])

    e_ini = x.rindex("<edges ", 0, x.index(f'element="{f_id}"'))
    e_fin = bloque(x, e_ini, "edges")
    e_orig = x[e_ini:e_fin]
    edge = lambda k, el, src, tgt: sin_bendpoints(cabecera(clonar(e_orig, "", ""), xmi_id=ids[k], element=el,  # noqa: E731
                                                           source=src, target=tgt))
    e_nuevas = [edge("EA", ids["Fa"], ids["SL"], ids["SX2"]), edge("EB", ids["Fb"], ids["SX2"], shape_rev),
                edge("EC", ids["Fc"], ids["SX2"], shape_pub)]
    e_mod = sin_bendpoints(cabecera(e_orig, target=ids["SL"]))
    assert f'source="{shape_xor}"' in e_mod

    # --- aplicar, de atrás para adelante para no correr las posiciones ---------------------------------------------
    cambios: list[tuple[int, int, str]] = [
        (e_ini, e_fin, e_mod + NL + NL.join(e_nuevas)),
        (f_ini, f_fin, f_nuevo + NL + fa + NL + fb + NL + fc),
    ]
    lane_ini, lane_fin = elemento(x, LANE_NACIONAL)
    corte = x.rindex("</elements>", lane_ini, lane_fin)
    cambios.append((corte, corte, liberar + NL + xor2 + NL))
    nodo = x.index(f'element="{id_de(x, lane_ini)}"')
    comp_ini = re.compile(r'<children xmi:type="notation:DecorationNode"[^>]*type="7002"').search(x, nodo).start()
    comp_fin = bloque(x, comp_ini, "children")
    corte_n = x.rindex("</children>", comp_ini, comp_fin)
    cambios.append((corte_n, corte_n, shape_l + NL + shape_x + NL))
    for ini, fin, texto in sorted(cambios, key=lambda c: c[0], reverse=True):
        x = x[:ini] + texto + x[fin:]

    # Entradas de Revisar y Publicar: Revisar ahora llega desde el XOR nuevo; Publicar suma la rama REABRIR.
    rev_ini, _ = elemento(x, REVISAR)
    rev_tag_fin = x.index(">", rev_ini)
    x = x[:rev_ini] + x[rev_ini:rev_tag_fin].replace(f_id, ids["Fb"]) + x[rev_tag_fin:]
    pub_ini, _ = elemento(x, PUBLICAR)
    pub_tag_fin = x.index(">", pub_ini)
    tag = x[pub_ini:pub_tag_fin]
    tag = re.sub(r'(\sincoming=")([^"]*)(")', rf'\g<1>\g<2> {ids["Fc"]}\g<3>', tag, count=1)
    return x[:pub_ini] + tag + x[pub_tag_fin:]


def verificar(x: str) -> None:
    minidom.parseString(x.encode("utf-8"))
    todos = re.findall(r'xmi:id="([^"]+)"', x)
    repetidos = {i for i in todos if todos.count(i) > 1}
    if repetidos:
        raise ValueError(f"xmi:id repetidos: {sorted(repetidos)[:5]}")
    definidos = set(todos)
    for attr in ("source", "target", "element", "incoming", "outgoing"):
        for valor in re.findall(rf'\s{attr}="([^"]+)"', x):
            for ref in valor.split():
                if ref.startswith("_") and ref not in definidos:
                    raise ValueError(f"{attr}={ref} no existe")


def main(entrada: str, salida: str) -> None:
    with zipfile.ZipFile(entrada) as zin:
        nombre = next(n for n in zin.namelist() if n.endswith(".proc"))
        nuevo = agregar(zin.read(nombre).decode("utf-8"))
        verificar(nuevo)
        with zipfile.ZipFile(salida, "w") as zout:
            for info in zin.infolist():
                datos = nuevo.encode("utf-8") if info.filename == nombre else zin.read(info.filename)
                zout.writestr(info, datos, compress_type=info.compress_type)
    print(f"Listo: {salida}")
    print(f"  «{LIBERAR}» (login + POST /adjudicaciones/resolucion) y XOR «{XOR_NUEVO}» con las ramas REFORMULAR y REABRIR.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
